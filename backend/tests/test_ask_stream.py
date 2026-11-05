"""End to end through the streaming endpoint with a fake model and the live database."""

import asyncio
import json
import uuid

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.api.deps import CurrentUser, get_current_user
from app.core.config import settings
from app.llm import client as llm_client
from app.llm.schemas import AnswerSpec, Interpretation, Kpi, PlannedQuery, Ref, SqlPlan
from app.main import app
from app.schemas.ask import AskRequest
from app.services import ask_service

PMPM_SQL = (
    "SELECT sum(total_allowed_amt) / NULLIF(sum(member_months), 0) AS pmpm "
    "FROM mart.total_cost_of_care_summary_l1 "
    "WHERE level1_hierarchy = 'NEXUS' AND month_year BETWEEN '2025-07' AND '2026-06'"
)
QUESTION = "What was NEXUS PMPM for the latest 12 months?"
INTERPRETATION = Interpretation(
    metric="PMPM",
    population="NEXUS",
    period="2025-07 to 2026-06",
    date_basis="Service month",
    grain="Network",
    filters="None",
    denominator="Member months",
    sources="mart.total_cost_of_care_summary_l1",
)


def db(sql: str, *args):
    async def run():
        conn = await asyncpg.connect(settings.database_url.replace("+asyncpg", ""))
        try:
            return await conn.fetch(sql, *args)
        finally:
            await conn.close()

    return asyncio.run(run())


def query_plan(sql: str) -> SqlPlan:
    return SqlPlan(
        action="query",
        message=None,
        options=[],
        interpretation=INTERPRETATION,
        queries=[PlannedQuery(name="q1", purpose="PMPM", sql=sql)],
    )


@pytest.fixture(scope="module")
def http():
    try:
        db("SELECT 1 FROM app.conversations LIMIT 1")
    except (OSError, asyncpg.PostgresError) as e:
        pytest.skip(f"database unavailable: {e}")
    with TestClient(app) as c:
        yield c
    db("DELETE FROM app.conversations WHERE user_id LIKE 'test-%'")
    db("DELETE FROM llm_metrics.llm_runs WHERE user_id LIKE 'test-%'")
    app.dependency_overrides.clear()


def as_user() -> str:
    user = CurrentUser(id=f"test-{uuid.uuid4().hex[:8]}", is_admin=False)
    app.dependency_overrides[get_current_user] = lambda: user
    return user.id


@pytest.fixture
def llm(monkeypatch):
    """Queue of structured outputs the fake model returns, plus the prompts it received."""
    queue, prompts = [], []

    async def fake(schema, system, prompt, effort, config):
        prompts.append(prompt)
        item = queue.pop(0)
        assert isinstance(item, schema)
        return item

    monkeypatch.setattr(llm_client, "call_structured", fake)
    return queue, prompts


def ask(http, question=QUESTION):
    conversation = http.post("/api/v1/conversations").json()
    r = http.post(
        f"/api/v1/conversations/{conversation['id']}/messages/stream", json={"question": question}
    )
    events = [
        (
            block.split("\n")[0].removeprefix("event: "),
            json.loads(block.split("\n")[1].removeprefix("data: ")),
        )
        for block in r.text.strip().split("\n\n")
    ]
    return conversation, r, events


def test_answer_streams_validated_figures_and_persists_sql(http, llm):
    as_user()
    queue, _ = llm
    kpi = Kpi(
        type="kpi",
        label="PMPM",
        value=Ref(query="q1", column="pmpm", row="first"),
        format="usd2",
        sub=None,
    )
    queue += [
        query_plan(PMPM_SQL),
        AnswerSpec(
            outcome="answered",
            text="NEXUS PMPM was {{q1.pmpm|usd2}}.",
            components=[kpi],
            assumptions=[],
            limitations=[],
            followups=[],
        ),
    ]
    _conversation, r, events = ask(http)

    kinds = [k for k, _ in events]
    assert set(kinds) <= {"status", "result", "done"} and kinds[-2:] == ["result", "done"]
    result = events[-2][1]
    expected = float(db(PMPM_SQL)[0]["pmpm"])
    assert result["outcome"] == "answered"
    assert result["components"][0]["value"] == pytest.approx(expected)
    assert result["text"] == f"NEXUS PMPM was ${expected:,.2f}."
    assert result["queries"][0]["sql"] == PMPM_SQL
    assert "AI Query Policy" not in r.text and "Step `plan`" not in r.text

    stored = db(
        "SELECT q.sql, m.status, c.title, r.dataset_version_id FROM app.query_executions q "
        "JOIN app.analysis_runs r ON r.id = q.run_id JOIN app.messages m ON m.id = r.message_id "
        "JOIN app.conversations c ON c.id = m.conversation_id WHERE r.id = $1",
        uuid.UUID(result["run_id"]),
    )[0]
    assert (stored["sql"], stored["status"], stored["title"]) == (PMPM_SQL, "answered", QUESTION)
    assert stored["dataset_version_id"] == db("SELECT max(id) FROM app.dataset_versions")[0][0]
    assert (
        db("SELECT status FROM llm_metrics.llm_runs WHERE id = $1", uuid.UUID(result["run_id"]))[0][
            0
        ]
        == "success"
    )


def test_failed_sql_is_retried_and_db_errors_stay_server_side(http, llm):
    as_user()
    queue, prompts = llm
    queue += [query_plan("SELECT no_such_column FROM mart.nexus_pcp_roster")] * 3
    _, r, events = ask(http)
    result = events[-2][1]
    assert result["outcome"] == "failed"
    assert [q["status"] for q in result["queries"]] == ["failed"] * 3
    assert "does not exist" in prompts[1]  # the model sees the error to repair it
    assert "does not exist" not in r.text  # the user does not


def test_data_modifying_sql_is_blocked_by_the_database(http, llm):
    as_user()
    queue, _ = llm
    # Passes the SELECT/WITH check, so only the read-only role stops it.
    queue += [
        query_plan(
            "WITH d AS (DELETE FROM mart.nexus_pcp_roster RETURNING 1) SELECT count(*) FROM d"
        )
    ] * 3
    before = db("SELECT count(*) FROM mart.nexus_pcp_roster")[0][0]
    assert ask(http)[2][-2][1]["outcome"] == "failed"
    assert db("SELECT count(*) FROM mart.nexus_pcp_roster")[0][0] == before


def test_explain_needs_no_query(http, llm):
    as_user()
    queue, _ = llm
    queue.append(
        SqlPlan(
            action="explain",
            message="PMPM is allowed cost divided by member months.",
            options=[],
            interpretation=None,
            queries=[],
        )
    )
    result = ask(http, "What does PMPM mean?")[2][-2][1]
    assert (result["outcome"], result["queries"], result["components"]) == ("explained", [], [])


def test_other_users_conversation_is_not_found(http, llm):
    as_user()
    conversation = http.post("/api/v1/conversations").json()
    as_user()
    r = http.post(
        f"/api/v1/conversations/{conversation['id']}/messages/stream", json={"question": QUESTION}
    )
    assert r.status_code == 404


@pytest.mark.parametrize("how", ["close", "cancel"])
def test_disconnect_cancels_run_and_closes_message(http, monkeypatch, how):
    user = CurrentUser(id=as_user(), is_admin=False)
    model_stopped = []

    async def hang(schema, system, prompt, effort, config):
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            model_stopped.append(True)
            raise

    monkeypatch.setattr(llm_client, "call_structured", hang)
    conversation = http.post("/api/v1/conversations").json()

    async def run():
        prep = await ask_service.prepare(
            user, uuid.UUID(conversation["id"]), AskRequest(question=QUESTION)
        )
        gen = ask_service.stream(prep)
        first = await gen.__anext__()
        if how == "close":  # client gone while the stream is paused between events
            await gen.aclose()
        else:  # client gone while the stream is waiting on the model
            task = asyncio.ensure_future(gen.__anext__())
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        return prep, first

    prep, first = http.portal.call(run)
    assert "Interpreting" in first
    assert model_stopped == [True]
    assert (
        db("SELECT status FROM app.messages WHERE id = $1", prep.assistant_message_id)[0][0]
        == "cancelled"
    )
    assert (
        db("SELECT status FROM llm_metrics.llm_runs WHERE id = $1", prep.run_id)[0][0]
        == "cancelled"
    )


def test_one_answer_at_a_time(http, llm):
    as_user()
    conversation = http.post("/api/v1/conversations").json()
    db(
        "INSERT INTO app.messages (conversation_id, role, content, status) VALUES ($1, 'assistant', '', 'running')",
        uuid.UUID(conversation["id"]),
    )
    r = http.post(
        f"/api/v1/conversations/{conversation['id']}/messages/stream", json={"question": QUESTION}
    )
    assert (r.status_code, r.json()["code"]) == (409, "conflict")
