"""SQL Workspace: paging, cap, ownership, cancellation and limits, against the live database."""

import asyncio
import time
import uuid

import pytest
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.services import sql_workspace
from tests.conftest import as_user, db

URL = "/api/v1/explorer/queries"
# A cross join of the 1.4M-row claims table runs until cancelled or timed out.
SLOW = "SELECT count(*) FROM raw.claims a CROSS JOIN raw.claims b"


def _run(http, sql, qid=None):
    return http.post(URL, json={"id": str(qid or uuid.uuid4()), "sql": sql})


def test_pages_are_stable_slices_of_one_run(http):
    as_user()
    first = _run(http, "SELECT g FROM generate_series(1, 120) g").json()
    assert first["status"] == "succeeded" and first["columns"] == ["g"]
    assert [r[0] for r in first["rows"]] == list(range(1, 51))
    assert first["has_next"] and not first["capped"]

    second = http.get(f"{URL}/{first['id']}", params={"page": 1}).json()
    assert [r[0] for r in second["rows"]] == list(range(51, 101))
    last = http.get(f"{URL}/{first['id']}", params={"page": 2}).json()
    assert len(last["rows"]) == 20 and not last["has_next"]


def test_result_is_capped(http):
    as_user()
    cap = sql_workspace.ROW_CAP
    r = _run(http, f"SELECT g FROM generate_series(1, {cap + 5}) g").json()
    assert r["capped"] and r["row_cap"] == cap
    last = http.get(f"{URL}/{r['id']}", params={"page": cap // 50 - 1}).json()
    assert last["rows"][-1] == [cap] and not last["has_next"]


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM raw.claims",
        "CREATE VIEW mart.v AS SELECT 1",
        "CREATE TEMP VIEW v AS SELECT 1",
        "SELECT * INTO TEMP t FROM raw.claims",
        "SELECT 1; DROP TABLE raw.claims",
    ],
)
def test_rejects_writes_and_ddl(http, sql):
    as_user()
    r = _run(http, sql)
    if r.status_code == 200:  # multi-statement is rejected by the database, not the validator
        assert r.json()["status"] == "failed"
    else:
        assert r.status_code == 400 and r.json()["code"] == "invalid_sql"


def test_export_csv_is_the_whole_stored_result(http):
    as_user()
    qid = _run(http, "SELECT g, '=1+1' AS f FROM generate_series(1, 120) g").json()["id"]
    r = http.get(f"{URL}/{qid}/export.csv")
    lines = r.text.splitlines()
    assert r.headers["content-type"].startswith("text/csv")
    assert lines[0] == "g,f" and len(lines) == 121 and lines[1] == "1,'=1+1"
    failed = _run(http, "SELECT * FROM raw.no_such_table").json()["id"]
    assert http.get(f"{URL}/{failed}/export.csv").status_code == 404
    as_user()
    assert http.get(f"{URL}/{qid}/export.csv").status_code == 404


def test_database_errors_are_reported(http):
    as_user()
    r = _run(http, "SELECT * FROM raw.no_such_table").json()
    assert r["status"] == "failed" and "no_such_table" in r["error"]


def test_results_are_private_and_ids_unique(http):
    as_user()
    qid = _run(http, "SELECT 1").json()["id"]
    assert _run(http, "SELECT 1", qid).status_code == 409
    as_user()
    assert http.get(f"{URL}/{qid}").status_code == 404
    assert http.delete(f"{URL}/{qid}").status_code == 404


def _active_analytics_queries() -> int:
    role = make_url(settings.analytics_database_url).username
    rows = db("SELECT count(*) FROM pg_stat_activity WHERE usename = $1 AND state = 'active'", role)
    return rows[0][0]


def test_cancel_stops_the_server_query_and_limits_apply(http):
    async def scenario():
        ids = [uuid.uuid4() for _ in range(3)]
        runs = [asyncio.create_task(sql_workspace.run("test-cancel", i, SLOW)) for i in ids[:2]]
        await asyncio.sleep(0.5)
        with pytest.raises(sql_workspace.Busy):
            await sql_workspace.run("test-cancel", ids[2], "SELECT 1")
        started = time.monotonic()
        for i in ids[:2]:
            assert sql_workspace.cancel("test-cancel", i)
        queries = await asyncio.gather(*runs)
        assert time.monotonic() - started < 5
        pages = [sql_workspace.page(i, q, 0) for i, q in zip(ids[:2], queries, strict=True)]
        assert {p["status"] for p in pages} == {"cancelled"}

    asyncio.run(scenario())
    time.sleep(0.5)
    assert _active_analytics_queries() == 0
