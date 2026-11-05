"""The read-only analytics role can read raw/mart/ref and nothing else. Needs the live database."""

import asyncio

import asyncpg
import pytest
from sqlalchemy.engine import make_url

from app.core.config import settings


async def _run(*statements: str) -> None:
    try:
        conn = await asyncpg.connect(settings.analytics_database_url.replace("+asyncpg", ""))
    except (OSError, asyncpg.PostgresError) as e:
        pytest.skip(f"analytics database unavailable: {e}")
    try:
        # The role can switch off its read-only default, so privileges must be what blocks writes.
        await conn.execute("SET default_transaction_read_only = off")
        for s in statements:
            await conn.execute(s)
    finally:
        await conn.close()


def test_reads_analytics_schemas():
    asyncio.run(
        _run(
            "SELECT 1 FROM mart.nexus_pcp_roster LIMIT 1",
            "SELECT 1 FROM raw.claims LIMIT 1",
            "SELECT 1 FROM ref.drg LIMIT 1",
        )
    )


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1 FROM app.messages LIMIT 1",
        "SELECT 1 FROM llm_metrics.llm_runs LIMIT 1",
        "INSERT INTO mart.nexus_pcp_roster (pcp_npi) VALUES ('x')",
        "DELETE FROM raw.claims",
        "CREATE TABLE mart.scratch (x int)",
        "CREATE SCHEMA scratch",
        "SELECT pg_read_file('/etc/passwd')",
        f"SET ROLE {make_url(settings.database_url).username}",
    ],
)
def test_denied(sql):
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        asyncio.run(_run(sql))
