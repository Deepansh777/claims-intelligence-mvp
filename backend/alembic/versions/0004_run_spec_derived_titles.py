"""Store each run's AnswerSpec (so stored SQL can be re-run and re-bound); derive titles on read.

A stored title copied the first question and would outlive that message's retention.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-05
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE app.analysis_runs ADD COLUMN spec jsonb")
    op.execute("ALTER TABLE app.conversations DROP COLUMN title")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE app.conversations ADD COLUMN title text NOT NULL DEFAULT 'New conversation'"
    )
    op.execute("ALTER TABLE app.conversations ALTER COLUMN title DROP DEFAULT")
    op.execute("ALTER TABLE app.analysis_runs DROP COLUMN spec")
