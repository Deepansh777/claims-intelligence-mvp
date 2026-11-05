"""Execute LLM-generated SQL as the read-only analytics role.

The role's grants (SELECT on raw/mart/ref only) are the security boundary; validate_sql is
defence in depth and a clear early error for the repair loop.
"""

import asyncio
import datetime
import decimal
import re
from typing import Any

import asyncpg

from app.core.config import settings
from app.llm.schemas import QueryError, QueryResult

MAX_ROWS = 5000
STATEMENT_TIMEOUT = "30s"
_slots = asyncio.Semaphore(4)

# Functions a read-only transaction does not block. Matched against the full SQL, literals
# included, because query_to_xml runs SQL held in a string.
DENIED = re.compile(
    r"\b(set_config|query_to_xml\w*|pg_sleep\w*|dblink\w*|lo_\w+|pg_read\w*|pg_ls_\w+"
    r"|pg_terminate_backend|pg_cancel_backend)\b",
    re.IGNORECASE,
)
LITERALS_AND_COMMENTS = re.compile(r"'(?:[^']|'')*'|--[^\n]*|/\*.*?\*/", re.DOTALL)


def validate_sql(sql: str) -> str:
    body = LITERALS_AND_COMMENTS.sub(" ", sql).strip()
    if not re.match(r"(select|with)\b", body, re.IGNORECASE):
        raise QueryError("only a single SELECT or WITH query is allowed")
    if m := DENIED.search(sql):
        raise QueryError(f"disallowed function: {m.group()}")
    return sql


def _jsonable(v: Any) -> Any:
    if v is None or isinstance(v, bool | int | float | str):
        return v
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, datetime.date | datetime.datetime):
        return v.isoformat()
    return str(v)


async def run_query(sql: str) -> QueryResult:
    validate_sql(sql)
    async with _slots:
        conn = await asyncpg.connect(
            settings.analytics_database_url.replace("+asyncpg", ""), timeout=10
        )
        try:
            async with conn.transaction(readonly=True):
                await conn.execute(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'")
                stmt = await conn.prepare(sql)  # prepared statements reject multiple commands
                records = await (await stmt.cursor()).fetch(MAX_ROWS + 1)
                attrs = stmt.get_attributes()
        except asyncpg.PostgresError as e:
            raise QueryError(f"{type(e).__name__}: {e}") from e
        finally:
            await conn.close()
    return QueryResult(
        columns=[a.name for a in attrs],
        types=[a.type.name for a in attrs],
        rows=[[_jsonable(v) for v in r] for r in records[:MAX_ROWS]],
        row_count=min(len(records), MAX_ROWS),
        truncated=len(records) > MAX_ROWS,
    )
