"""SQL Workspace: run a user's read-only query once, keep a capped result, serve it by page.

Paging slices the stored result, so pages stay stable and the query never re-runs; the
connection is released as soon as the capped fetch finishes. Read-only enforcement is
run_query's: validator, read-only transaction, and the analytics role's grants.
"""

import asyncio
import csv
import io
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.llm.schemas import QueryError, QueryResult
from app.services.analytics_sql import run_query, validate_sql
from app.services.conversation_service import csv_cell

ROW_CAP = 10_000
PAGE_SIZE = 50
RESULT_TTL = 15 * 60  # seconds a finished result stays pageable
MAX_RUNNING_PER_USER = 2
MAX_KEPT_PER_USER = 5


class Busy(Exception):
    pass


class Duplicate(Exception):
    pass


@dataclass
class Query:
    user_id: str
    task: asyncio.Task[QueryResult]
    started: float = field(default_factory=time.monotonic)
    finished: float | None = None


# shortcut: results live in this process's memory, so they need a single API worker and are
# lost on restart; move to Redis or a results table before running several workers.
_queries: dict[uuid.UUID, Query] = {}


def _purge(user_id: str) -> None:
    now = time.monotonic()
    for qid, q in list(_queries.items()):
        if q.finished is not None and now - q.finished > RESULT_TTL:
            del _queries[qid]
    done = [qid for qid, q in _queries.items() if q.user_id == user_id and q.task.done()]
    for qid in done[: max(0, len(done) - MAX_KEPT_PER_USER + 1)]:  # oldest first
        del _queries[qid]


def get(user_id: str, query_id: uuid.UUID) -> Query | None:
    q = _queries.get(query_id)
    return q if q is not None and q.user_id == user_id else None


async def run(user_id: str, query_id: uuid.UUID, sql: str) -> Query:
    """Start the query and wait for it to finish, fail or be cancelled."""
    validate_sql(sql)  # raises QueryError before taking a slot
    if query_id in _queries:
        raise Duplicate
    _purge(user_id)
    running = sum(1 for q in _queries.values() if q.user_id == user_id and not q.task.done())
    if running >= MAX_RUNNING_PER_USER:
        raise Busy
    q = Query(user_id, asyncio.create_task(run_query(sql, max_rows=ROW_CAP)))
    q.task.add_done_callback(lambda _: setattr(q, "finished", time.monotonic()))
    _queries[query_id] = q
    await asyncio.wait([q.task])  # wait, unlike await, doesn't cancel the task if we're cancelled
    return q


def cancel(user_id: str, query_id: uuid.UUID) -> bool:
    q = get(user_id, query_id)
    if q is None:
        return False
    q.task.cancel()
    return True


def to_csv(q: Query) -> str | None:
    """The whole stored (capped) result; None unless the query succeeded."""
    if not q.task.done() or q.task.cancelled() or q.task.exception():
        return None
    r = q.task.result()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(r.columns)
    writer.writerows([csv_cell(v) for v in row] for row in r.rows)
    return out.getvalue()


def page(query_id: uuid.UUID, q: Query, n: int) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": query_id,
        "page": n,
        "page_size": PAGE_SIZE,
        "row_cap": ROW_CAP,
        "elapsed_ms": round(((q.finished or time.monotonic()) - q.started) * 1000),
        "columns": [],
        "types": [],
        "rows": [],
        "has_next": False,
        "capped": False,
        "error": None,
    }
    if not q.task.done():
        return {**out, "status": "running"}
    if q.task.cancelled():
        return {**out, "status": "cancelled"}
    if e := q.task.exception():
        if not isinstance(e, QueryError):
            raise e
        return {**out, "status": "failed", "error": str(e)}
    r = q.task.result()
    start = n * PAGE_SIZE
    return {
        **out,
        "status": "succeeded",
        "columns": r.columns,
        "types": r.types,
        "rows": r.rows[start : start + PAGE_SIZE],
        "has_next": start + PAGE_SIZE < r.row_count,
        "capped": r.truncated,
    }
