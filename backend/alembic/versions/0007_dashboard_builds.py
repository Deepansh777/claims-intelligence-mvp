"""Dashboard builds: background generation jobs, their progress events, and their outcome.

A build outlives the request that started it, so the client can leave and reconnect by id.
`seen_at` records when the user dismissed the outcome, so it is shown once.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-06
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.dashboard_builds (
            id uuid PRIMARY KEY,
            user_id text NOT NULL,
            title text NOT NULL,
            request text NOT NULL,
            outline jsonb NOT NULL,
            effort text NOT NULL,
            status text NOT NULL DEFAULT 'running'
                CHECK (status IN ('running', 'built', 'failed', 'cancelled')),
            steps_done integer NOT NULL DEFAULT 0,
            steps_total integer NOT NULL,
            events jsonb NOT NULL DEFAULT '[]',
            dashboard_id uuid REFERENCES app.dashboards ON DELETE SET NULL,
            error text,
            failed_step text,
            created_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            seen_at timestamptz
        )
    """)
    op.execute("CREATE INDEX ON app.dashboard_builds (user_id, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE app.dashboard_builds")
