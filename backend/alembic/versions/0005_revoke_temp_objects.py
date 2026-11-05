"""Stop every role, the read-only analytics role included, from creating temporary objects.

PUBLIC holds TEMPORARY on new databases, so the analytics role could CREATE TEMP VIEW/TABLE
after switching off its read-only default.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-05
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TEMP = "EXECUTE format('{} TEMPORARY ON DATABASE %I {} PUBLIC', current_database())"


def upgrade() -> None:
    op.execute(f"DO $$ BEGIN {TEMP.format('REVOKE', 'FROM')}; END $$")


def downgrade() -> None:
    op.execute(f"DO $$ BEGIN {TEMP.format('GRANT', 'TO')}; END $$")
