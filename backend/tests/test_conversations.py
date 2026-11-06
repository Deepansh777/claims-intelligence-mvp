"""Conversations API, retention, follow-up context, re-run and export, against the live database."""

import json
import uuid

from conftest import as_user, db
from test_ask_stream import PMPM_SQL, QUESTION, query_plan

from app.api.deps import CurrentUser, get_current_user
from app.core.config import settings
from app.llm.schemas import AnswerSpec, Kpi, Ref, SqlPlan
from app.main import app
from app.services import ask_service, conversation_service, retention

API = "/api/v1"


def pmpm_answer() -> AnswerSpec:
    kpi = Kpi(
        type="kpi",
        label="PMPM",
        value=Ref(query="q1", column="pmpm", row="first"),
        format="usd2",
        sub=None,
    )
    return AnswerSpec(
        outcome="answered",
        text="NEXUS PMPM was {{q1.pmpm|usd2}}.",
        narrative="",
        components=[kpi],
        assumptions=[],
        limitations=[],
        followups=[],
    )


def say(http, conversation_id: str, question: str) -> dict:
    r = http.post(
        f"{API}/conversations/{conversation_id}/messages/stream", json={"question": question}
    )
    assert r.status_code == 200, r.text
    return json.loads(r.text.strip().split("\n\n")[-2].split("\n")[1].removeprefix("data: "))


def answered(http, llm, conversation_id=None, question=QUESTION) -> tuple[str, dict]:
    llm[0].extend([query_plan(PMPM_SQL), pmpm_answer()])
    conversation_id = conversation_id or http.post(f"{API}/conversations").json()["id"]
    return conversation_id, say(http, conversation_id, question)


def expire_oldest_turn(conversation_id: str) -> None:
    db(
        "UPDATE app.messages SET created_at = created_at - interval '16 days' "
        "WHERE conversation_id = $1 AND created_at = "
        "(SELECT min(created_at) FROM app.messages WHERE conversation_id = $1)",
        uuid.UUID(conversation_id),
    )


def rows_for_run(run_id: str) -> tuple[int, int]:
    rid = uuid.UUID(run_id)
    return (
        db("SELECT count(*) FROM app.analysis_runs WHERE id = $1", rid)[0][0],
        db("SELECT count(*) FROM app.query_executions WHERE run_id = $1", rid)[0][0],
    )


def test_list_and_open_conversation(http, llm):
    user_id = as_user()
    conversation_id, result = answered(http, llm)

    [summary] = http.get(f"{API}/conversations").json()
    assert (summary["id"], summary["title"], summary["network"]) == (
        conversation_id,
        QUESTION,
        "NEXUS",
    )
    assert (summary["preview"], summary["stale"]) == (result["text"], False)

    detail = http.get(f"{API}/conversations/{conversation_id}").json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    answer = detail["messages"][1]["answer"]
    assert answer["components"][0]["value"] == result["components"][0]["value"]
    assert answer["datasets"]["q1"]["rows"] == result["datasets"]["q1"]["rows"]
    assert answer["queries"][0]["sql"] == PMPM_SQL
    assert "usage" not in answer

    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=user_id, is_admin=True)
    usage = http.get(f"{API}/conversations/{conversation_id}").json()["messages"][1]["answer"]
    assert set(usage["usage"]) == set(conversation_service.USAGE_KEYS)


def test_other_user_cannot_see_or_touch_a_conversation(http, llm):
    as_user()
    conversation_id, result = answered(http, llm)
    as_user()
    assert http.get(f"{API}/conversations").json() == []
    assert http.get(f"{API}/conversations/{conversation_id}").status_code == 404
    assert http.delete(f"{API}/conversations/{conversation_id}").status_code == 404
    assert http.post(f"{API}/runs/{result['run_id']}/rerun").status_code == 404
    assert rows_for_run(result["run_id"]) == (1, 1)


def test_delete_removes_everything(http, llm):
    as_user()
    conversation_id, result = answered(http, llm)
    assert http.delete(f"{API}/conversations/{conversation_id}").status_code == 204
    assert http.get(f"{API}/conversations/{conversation_id}").status_code == 404
    assert rows_for_run(result["run_id"]) == (0, 0)


def test_followup_gets_context_and_new_chat_does_not(http, llm):
    as_user()
    _, prompts = llm
    conversation_id, _ = answered(http, llm, question="NEXUS PMPM for the last 12 months?")
    answered(http, llm, conversation_id, question="Now PCN.")
    followup_plan = prompts[2]
    assert "Previous analysis context" in followup_plan
    assert "User: NEXUS PMPM for the last 12 months?" in followup_plan
    assert PMPM_SQL in followup_plan
    assert followup_plan.index(PMPM_SQL) < followup_plan.index("Question: Now PCN.")

    answered(http, llm, question="Now PCN.")
    assert "Previous analysis context" not in prompts[4]


def test_context_stays_within_budget(monkeypatch):
    monkeypatch.setattr(ask_service, "CONTEXT_CHARS", 7000)
    plan = query_plan("SELECT 1 /*" + "x" * 9000 + "*/").model_dump()
    recent = []
    for i in range(4, 0, -1):  # newest first, like the repository returns them
        recent += [
            {
                "role": "assistant",
                "content": f"reply {i} " + "r" * 900,
                "status": "answered",
                "plan": plan,
                "context_snapshot": {"network": "PCN", "interpretation": None},
            },
            {
                "role": "user",
                "content": f"question {i} " + "q" * 1500,
                "status": "complete",
                "plan": None,
                "context_snapshot": None,
            },
        ]
    context = ask_service.build_context(recent)
    assert len(context) <= 7000
    assert "question 4" in context and "question 3" not in context
    assert "reply 4 " + "r" * (ask_service.CONTEXT_REPLY_CHARS - 8) in context
    assert "r" * ask_service.CONTEXT_REPLY_CHARS not in context
    assert "network PCN" in context


def test_expired_messages_leave_reads_title_and_context_then_get_purged(http, llm):
    as_user()
    _, prompts = llm
    conversation_id, first = answered(http, llm, question="First question about NEXUS PMPM?")
    answered(http, llm, conversation_id, question="Second question about NEXUS PMPM?")
    expire_oldest_turn(conversation_id)

    [summary] = http.get(f"{API}/conversations").json()
    assert summary["title"] == "Second question about NEXUS PMPM?"
    detail = http.get(f"{API}/conversations/{conversation_id}").json()
    assert [m["content"] for m in detail["messages"] if m["role"] == "user"] == [
        "Second question about NEXUS PMPM?"
    ]
    answered(http, llm, conversation_id, question="Third?")
    assert "First question" not in prompts[4] and "Second question" in prompts[4]

    http.portal.call(retention.purge_expired)
    assert rows_for_run(first["run_id"]) == (0, 0)
    assert len(http.get(f"{API}/conversations/{conversation_id}").json()["messages"]) == 4

    db(
        "UPDATE app.messages SET created_at = created_at - interval '16 days' "
        "WHERE conversation_id = $1",
        uuid.UUID(conversation_id),
    )
    db(
        "UPDATE app.conversations SET created_at = created_at - interval '16 days' WHERE id = $1",
        uuid.UUID(conversation_id),
    )
    assert http.get(f"{API}/conversations").json() == []
    assert http.get(f"{API}/conversations/{conversation_id}").status_code == 404
    assert (
        http.post(
            f"{API}/conversations/{conversation_id}/messages/stream", json={"question": "Again?"}
        ).status_code
        == 404
    )
    http.portal.call(retention.purge_expired)
    assert (
        db("SELECT count(*) FROM app.conversations WHERE id = $1", uuid.UUID(conversation_id))[0][0]
        == 0
    )


def test_rerun_uses_current_data_without_the_model(http, llm):
    as_user()
    queue, prompts = llm
    conversation_id, first = answered(http, llm)
    version = db(
        "INSERT INTO app.dataset_versions (source, table_row_counts) "
        "VALUES ('test', '{}') RETURNING id"
    )[0][0]
    try:
        assert http.get(f"{API}/conversations").json()[0]["stale"] is True
        old = http.get(f"{API}/conversations/{conversation_id}").json()["messages"][1]["answer"]
        assert old["stale"] is True

        r = http.post(f"{API}/runs/{first['run_id']}/rerun")
        assert r.status_code == 200, r.text
        rerun = r.json()
        assert (rerun["outcome"], rerun["text"], rerun["dataset_version_id"]) == (
            "answered",
            first["text"],
            version,
        )
        assert rerun["rerun_of"] == first["run_id"]
        assert rerun["components"][0]["value"] == first["components"][0]["value"]
        assert (queue, len(prompts)) == ([], 2)

        messages = http.get(f"{API}/conversations/{conversation_id}").json()["messages"]
        assert [m["content"] for m in messages if m["role"] == "user"] == [QUESTION, QUESTION]
        assert messages[-1]["answer"]["stale"] is False
    finally:
        db("DELETE FROM app.conversations WHERE id = $1", uuid.UUID(conversation_id))
        db("DELETE FROM app.dataset_versions WHERE id = $1", version)


def test_answers_without_sql_cannot_be_rerun(http, llm):
    as_user()
    llm[0].append(
        SqlPlan(
            action="explain",
            message="PMPM is cost per member per month.",
            options=[],
            interpretation=None,
            queries=[],
        )
    )
    conversation_id = http.post(f"{API}/conversations").json()["id"]
    result = say(http, conversation_id, "What does PMPM mean?")
    r = http.post(f"{API}/runs/{result['run_id']}/rerun")
    assert (r.status_code, r.json()["code"]) == (409, "conflict")


def test_csv_cell_neutralises_formulas():
    assert conversation_service.csv_cell("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert conversation_service.csv_cell(-5) == -5


def test_meta(http):
    as_user()
    meta = http.get(f"{API}/meta").json()
    assert meta["retention_days"] == settings.chat_retention_days
    assert (meta["networks"], meta["default_network"]) == (["NEXUS", "PCN", "BOTH"], "NEXUS")
    assert (meta["efforts"], meta["default_effort"]) == (["low", "medium", "high"], "medium")
    assert meta["dataset_version"]["id"] == db("SELECT max(id) FROM app.dataset_versions")[0][0]


def test_answers_interrupted_by_a_restart_unlock_their_conversation(http):
    as_user()
    conversation_id = uuid.UUID(http.post(f"{API}/conversations").json()["id"])
    db(
        "INSERT INTO app.messages (conversation_id, role, content, status) "
        "VALUES ($1, 'assistant', '', 'running')",
        conversation_id,
    )
    http.portal.call(retention.fail_interrupted_answers)
    assert (
        db("SELECT status FROM app.messages WHERE conversation_id = $1", conversation_id)[0][0]
        == "failed"
    )
