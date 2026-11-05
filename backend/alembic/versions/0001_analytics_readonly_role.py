"""Read-only login role for LLM-generated SQL.

SELECT on raw/mart/ref only, so generated SQL cannot read chat history (app) or metrics
(llm_metrics), and cannot write anywhere. Name and password come from ANALYTICS_DATABASE_URL.

Revision ID: 0001
Revises:
Create Date: 2026-11-05
"""

from sqlalchemy import text
from sqlalchemy.engine import make_url

from alembic import op
from app.core.config import settings

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMAS = ("raw", "mart", "ref")


def _role() -> str:
    return make_url(settings.analytics_database_url).username


def upgrade() -> None:
    conn = op.get_bind()
    url = make_url(settings.analytics_database_url)
    exists = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :n"), {"n": url.username})
    verb = "ALTER" if exists.scalar() else "CREATE"
    # format() quotes the identifier and password literal safely.
    stmt = conn.execute(
        text(
            f"SELECT format('{verb} ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB "
            "NOCREATEROLE NOREPLICATION NOBYPASSRLS', CAST(:n AS text), CAST(:p AS text))"
        ),
        {"n": url.username, "p": url.password},
    ).scalar()
    conn.exec_driver_sql(stmt)

    role = conn.execute(text("SELECT quote_ident(:n)"), {"n": url.username}).scalar()
    op.execute(f"ALTER ROLE {role} SET default_transaction_read_only = on")
    op.execute(f"ALTER ROLE {role} SET statement_timeout = '30s'")
    for schema in SCHEMAS:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        op.execute(f"GRANT USAGE ON SCHEMA {schema} TO {role}")
        op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA {schema} TO {role}")
        # Loaders drop and recreate tables as this (migrating) role; keep the grant on new tables.
        op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT SELECT ON TABLES TO {role}")


def downgrade() -> None:
    conn = op.get_bind()
    role = conn.execute(text("SELECT quote_ident(:n)"), {"n": _role()}).scalar()
    for schema in SCHEMAS:
        op.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} REVOKE SELECT ON TABLES FROM {role}"
        )
    op.execute(f"DROP OWNED BY {role}")
    op.execute(f"DROP ROLE {role}")
