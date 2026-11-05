"""Load medical-code-reference/ into Postgres schema `ref` (all columns text/boolean, codes as text).

Full replace: every run drops and recreates the ref tables. Usage (from backend/):
    python -m scripts.load_reference [path/to/medical-code-reference]
"""

import asyncio
import csv
import re
import sys
from pathlib import Path

import asyncpg

from app.core.config import settings

ICD_FILE = "icd10cm_order_2027.txt"
ICD_YEAR = re.search(r"(\d{4})", ICD_FILE).group(
    1
)  # code-set year; the file carries no other version tag


# CMS ICD-10-CM order file, fixed width (1-based columns): order 1-5, code 7-13 (no dot),
# billable flag 15, short description 17-76, long description 78-.
def parse_icd_line(line: str) -> tuple[str, bool, str, str]:
    return line[6:13].strip(), line[14] == "1", line[16:76].strip(), line[77:].strip()


def read_csv(path: Path, columns: list[str]) -> list[tuple]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [tuple(row[c].strip() for c in columns) for row in csv.DictReader(f)]


TABLES = {
    "icd10cm": (
        "code text PRIMARY KEY, is_billable boolean, short_description text, description text, code_set_year text",
        lambda d: [
            (*parse_icd_line(line), ICD_YEAR)
            for line in (d / ICD_FILE).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ],
    ),
    "cpt_hcpcs": (
        (
            "code text PRIMARY KEY, description text, code_system text, parent_category text,"
            " subcategory text, active boolean"
        ),
        lambda d: [
            (*r[:5], r[5] == "Yes")
            for r in read_csv(
                d / "cpt_hcpcs_cleaned.csv",
                ["code", "description", "code_system", "parent_category", "subcategory", "active"],
            )
        ],
    ),
    "drg": (
        "drg_code text PRIMARY KEY, mdc text, drg_type text, drg_description text",
        lambda d: [
            tuple(v or None for v in r)
            for r in read_csv(
                d / "drg_codes.csv", ["drg_code", "mdc", "drg_type", "drg_description"]
            )
        ],
    ),
}


async def main(ref_dir: Path) -> None:
    conn = await asyncpg.connect(settings.database_url.replace("+asyncpg", ""))
    try:
        await conn.execute("CREATE SCHEMA IF NOT EXISTS ref")
        for table, (ddl, read) in TABLES.items():
            rows = read(ref_dir)
            async with conn.transaction():
                await conn.execute(f"DROP TABLE IF EXISTS ref.{table} CASCADE")
                await conn.execute(f"CREATE TABLE ref.{table} ({ddl})")
                await conn.copy_records_to_table(table, records=rows, schema_name="ref")
                await conn.execute(f"ANALYZE ref.{table}")
            print(f"ref.{table}: {len(rows):,} rows")
    finally:
        await conn.close()


if __name__ == "__main__":
    default = Path(__file__).resolve().parents[2] / "medical-code-reference"
    asyncio.run(main(Path(sys.argv[1]) if len(sys.argv) > 1 else default))
