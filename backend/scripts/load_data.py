"""Load data/*.csv into Postgres: data/raw-processed-data -> schema `raw`, everything else -> `mart`.

Full replace: every run drops and recreates each table. Usage (from backend/):
    python -m scripts.load_data [path/to/data]
"""

import asyncio
import csv
import re
import sys
from pathlib import Path

import asyncpg

from app.core.config import settings

RAW_DIR = "raw-processed-data"
# Identifiers/codes stay text even when all-digit, so leading zeros survive and joins match.
ID_COLUMN = re.compile(
    r"_sk$|npi|_tin$|zip|id$|nbr|num$|number|code(?!_count)|_cd\d*$|_cd_|mod\d|^pos$|^tos$|ind$|drg"
)
DATE_COLUMN = re.compile(r"date|dob")
# Join/filter columns of the large tables; the other tables are <=12K rows and scan instantly.
INDEXES = {
    "raw.claims": ["claim_number", "member_sk", "servicing_provider_sk", "claim_servdatefrom"],
    "raw.eligibility": ["member_sk", "member_pcp_sk"],
    "raw.providers": ["provider_sk", "prov_npi", "prov_tin"],
    "mart.referrals_episodes": ["member_sk", "anchor_pcp_npi", "episode_start_date"],
}
# (sql type, pattern every non-blank value must match, cast with {v} = value, column filter).
# Checked in order; first match wins.
TYPES = [
    ("boolean", r"^(True|False)$", "{v}::boolean", lambda c: True),
    ("date", r"^\d{4}-\d{2}-\d{2}$", "{v}::date", lambda c: True),
    ("date", r"^\d{8}(\.0)?$", "to_date(left({v}, 8), 'YYYYMMDD')", DATE_COLUMN.search),
    ("date", r"^\d{2}/\d{2}/\d{4}$", "to_date({v}, 'MM/DD/YYYY')", DATE_COLUMN.search),
    ("bigint", r"^-?\d{1,18}$", "{v}::bigint", lambda c: not ID_COLUMN.search(c)),
    ("numeric", r"^-?\d+(\.\d+)?$", "{v}::numeric", lambda c: not ID_COLUMN.search(c)),
]


def blank_as_null(column: str) -> str:
    return f"NULLIF(btrim(\"{column}\"), '')"


def table_name(path: Path) -> str:
    stem = re.sub(r"^output\d*[a-z]?_", "", path.stem.lower())
    return re.sub(r"_\d{4}-\d{2}$", "", stem)


def column_cast(column: str, matches: list[bool]) -> tuple[str, str] | None:
    for (sql_type, _, cast, applies), matched in zip(TYPES, matches):
        if matched and applies(column):
            return sql_type, cast.format(v=blank_as_null(column))
    return None


async def create_indexes(conn: asyncpg.Connection, schema: str, table: str) -> None:
    for column in INDEXES.get(f"{schema}.{table}", []):
        await conn.execute(f'CREATE INDEX ON {schema}."{table}" ("{column}")')


async def load_csv(conn: asyncpg.Connection, schema: str, path: Path) -> None:
    table = table_name(path)
    with path.open(newline="", encoding="utf-8-sig") as f:
        columns = [c.strip().lower() for c in next(csv.reader(f))]

    async with conn.transaction():
        await conn.execute(f'DROP TABLE IF EXISTS {schema}."{table}" CASCADE')
        await conn.execute(
            f'CREATE TABLE {schema}."{table}" ({", ".join(f'"{c}" text' for c in columns)})'
        )
        await conn.copy_to_table(table, schema_name=schema, source=path, format="csv", header=True)

        # All-blank columns would match every pattern; require at least one value.
        checks = ", ".join(
            f"count({blank_as_null(c)}) > 0 AND bool_and({blank_as_null(c)} ~ '{pattern}')"
            for c in columns
            for _, pattern, _, _ in TYPES
        )
        row = await conn.fetchrow(f'SELECT {checks} FROM {schema}."{table}"')
        alters = []
        for i, c in enumerate(columns):
            matches = [bool(m) for m in row[i * len(TYPES) : (i + 1) * len(TYPES)]]
            if typed := column_cast(c, matches):
                alters.append(f'ALTER COLUMN "{c}" TYPE {typed[0]} USING {typed[1]}')
        if alters:
            await conn.execute(f'ALTER TABLE {schema}."{table}" {", ".join(alters)}')
        await create_indexes(conn, schema, table)
        await conn.execute(f'ANALYZE {schema}."{table}"')

    count = await conn.fetchval(f'SELECT count(*) FROM {schema}."{table}"')
    print(f"{schema}.{table}: {count:,} rows, {len(alters)}/{len(columns)} typed columns")


async def main(data_dir: Path) -> None:
    conn = await asyncpg.connect(settings.database_url.replace("+asyncpg", ""))
    try:
        for schema in ("raw", "mart"):
            await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        for path in sorted(data_dir.rglob("*.csv")):
            schema = "raw" if path.parent.name == RAW_DIR else "mart"
            await load_csv(conn, schema, path)
    finally:
        await conn.close()


if __name__ == "__main__":
    default = Path(__file__).resolve().parents[2] / "data"
    asyncio.run(main(Path(sys.argv[1]) if len(sys.argv) > 1 else default))
