"""Provider dashboards and their immutable versions.

A version stores everything needed to re-render and audit it: the outline, the per-tab SQL and
result snapshot, the spec, and the validation outcome. HTML is rendered from these, not stored.
Not tied to chat retention.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-05
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.dashboards (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id text NOT NULL,
            title text NOT NULL,
            current_version integer NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ON app.dashboards (user_id, updated_at DESC)")
    op.execute("""
        CREATE TABLE app.dashboard_versions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            dashboard_id uuid NOT NULL REFERENCES app.dashboards ON DELETE CASCADE,
            version integer NOT NULL CHECK (version > 0),
            parent_version integer,
            request text NOT NULL,
            outline jsonb NOT NULL,
            queries jsonb NOT NULL,
            results jsonb NOT NULL,
            spec jsonb NOT NULL,
            validation jsonb NOT NULL,
            dataset_version_id bigint REFERENCES app.dataset_versions,
            llm_run_id uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (dashboard_id, version)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE app.dashboard_versions")
    op.execute("DROP TABLE app.dashboards")
