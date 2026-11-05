"""Database metadata and table previews for the Data Explorer, read as the analytics role.

Everything goes through run_query, so the role's grants decide what is visible: catalog rows
are filtered to objects the role can SELECT.
"""

import time
from typing import Any

from app.llm.schemas import QueryResult
from app.services.analytics_sql import run_query

CACHE_TTL = 600  # seconds; loaders recreate tables rarely, a refresh shows up within this
PREVIEW_ROWS = 5
KINDS = {"r": "table", "p": "table", "v": "view", "m": "materialized view", "f": "foreign table"}

SCHEMAS_SQL = """
SELECT n.nspname AS name, count(*) AS table_count
FROM pg_namespace n JOIN pg_class c ON c.relnamespace = n.oid
WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname NOT LIKE 'pg\\_%'
  AND has_schema_privilege(n.oid, 'USAGE') AND has_table_privilege(c.oid, 'SELECT')
GROUP BY n.nspname ORDER BY n.nspname
"""

TABLES_SQL = """
SELECT c.relname AS name, c.relkind::text AS kind,
       CASE WHEN c.reltuples < 0 THEN NULL ELSE c.reltuples::bigint END AS estimated_rows
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = $1 AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
  AND has_table_privilege(c.oid, 'SELECT')
ORDER BY c.relname
"""

COLUMNS_SQL = """
SELECT a.attname AS name, format_type(a.atttypid, a.atttypmod) AS type,
       NOT a.attnotnull AS nullable
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = $1 AND c.relname = $2 AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY a.attnum
"""


class NotFound(Exception):
    pass


_cache: dict[tuple[str, ...], tuple[float, list[dict[str, Any]]]] = {}


async def _cached(key: tuple[str, ...], sql: str, *args: str) -> list[dict[str, Any]]:
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL:
        return hit[1]
    r = await run_query(sql, *args)
    rows = [dict(zip(r.columns, row, strict=True)) for row in r.rows]
    _cache[key] = (time.monotonic(), rows)
    return rows


async def schemas() -> list[dict[str, Any]]:
    return await _cached(("schemas",), SCHEMAS_SQL)


# Names are checked against the catalog before use, so cache keys and SQL only see real objects.
async def tables(schema: str) -> list[dict[str, Any]]:
    if schema not in {s["name"] for s in await schemas()}:
        raise NotFound
    rows = await _cached(("tables", schema), TABLES_SQL, schema)
    return [{**t, "kind": KINDS[t["kind"]]} for t in rows]


async def columns(schema: str, table: str) -> list[dict[str, Any]]:
    if table not in {t["name"] for t in await tables(schema)}:
        raise NotFound
    return await _cached(("columns", schema, table), COLUMNS_SQL, schema, table)


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


async def preview(schema: str, table: str) -> QueryResult:
    if table not in {t["name"] for t in await tables(schema)}:
        raise NotFound
    return await run_query(f"SELECT * FROM {_ident(schema)}.{_ident(table)} LIMIT {PREVIEW_ROWS}")
