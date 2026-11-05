"""App schema: dataset versions, conversations, messages, analysis runs, executed queries.

Retention is per message (created_at); runs and query rows cascade from their assistant message.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-05
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA app")
    op.execute("""
        CREATE TABLE app.dataset_versions (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            source text NOT NULL,
            table_row_counts jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE app.conversations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id text NOT NULL,
            title text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ON app.conversations (user_id, updated_at DESC)")
    op.execute("""
        CREATE TABLE app.messages (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id uuid NOT NULL REFERENCES app.conversations ON DELETE CASCADE,
            role text NOT NULL CHECK (role IN ('user', 'assistant')),
            content text NOT NULL,
            status text NOT NULL,
            client_request_id uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (conversation_id, client_request_id)
        )
    """)
    op.execute("CREATE INDEX ON app.messages (conversation_id, created_at)")
    op.execute("CREATE INDEX ON app.messages (created_at)")
    # At most one in-flight answer per conversation.
    op.execute(
        "CREATE UNIQUE INDEX messages_one_running ON app.messages (conversation_id) "
        "WHERE status = 'running'"
    )
    op.execute("""
        CREATE TABLE app.analysis_runs (
            id uuid PRIMARY KEY,
            message_id uuid NOT NULL UNIQUE REFERENCES app.messages ON DELETE CASCADE,
            dataset_version_id bigint REFERENCES app.dataset_versions,
            status text NOT NULL,
            plan jsonb,
            context_snapshot jsonb,
            answer jsonb,
            duration_ms integer,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE app.query_executions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id uuid NOT NULL REFERENCES app.analysis_runs ON DELETE CASCADE,
            name text NOT NULL,
            attempt integer NOT NULL,
            sql text NOT NULL,
            status text NOT NULL,
            error text,
            duration_ms integer,
            columns jsonb,
            row_count integer,
            truncated boolean,
            rows jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ON app.query_executions (run_id)")


def downgrade() -> None:
    op.execute("DROP SCHEMA app CASCADE")
