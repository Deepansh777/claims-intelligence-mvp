"""Dashboard and dashboard-version storage (schema `app`). Queries only.

Retention: a dashboard, with all its versions, is visible while updated_at (its latest version
or restore) is within `days` of now. Every read filters on that before the purge deletes it.
"""

import json
import uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

VISIBLE = "d.updated_at >= now() - make_interval(days => :days)"


async def count_user_runs_since(db: AsyncSession, user_id: str, since: datetime) -> int:
    """Finished dashboard LLM runs (outline and generation), from the usage metrics."""
    row = await db.execute(
        text(
            "SELECT count(*) FROM llm_metrics.llm_runs WHERE user_id = :u "
            "AND feature LIKE 'dashboard%' AND started_at >= :since"
        ),
        {"u": user_id, "since": since},
    )
    return row.scalar_one()


async def insert_dashboard(db: AsyncSession, dashboard_id: uuid.UUID, user_id: str, title: str):
    await db.execute(
        text(
            "INSERT INTO app.dashboards (id, user_id, title, current_version) "
            "VALUES (:id, :u, :t, 1)"
        ),
        {"id": dashboard_id, "u": user_id, "t": title},
    )


async def insert_version(db: AsyncSession, v: dict) -> None:
    jsonb = ("outline", "queries", "results", "spec", "validation")
    await db.execute(
        text(
            "INSERT INTO app.dashboard_versions (dashboard_id, version, parent_version, request, "
            "outline, queries, results, spec, validation, dataset_version_id, llm_run_id) VALUES "
            "(:dashboard_id, :version, :parent_version, :request, CAST(:outline AS jsonb), "
            "CAST(:queries AS jsonb), CAST(:results AS jsonb), CAST(:spec AS jsonb), "
            "CAST(:validation AS jsonb), :dataset_version_id, :llm_run_id)"
        ),
        {**v, **{k: json.dumps(v[k], default=str) for k in jsonb}},
    )


async def get_current_version(
    db: AsyncSession, dashboard_id: uuid.UUID, user_id: str, days: int
) -> dict | None:
    row = await db.execute(
        text(f"""
            SELECT d.id AS dashboard_id, d.title, d.current_version, d.updated_at, v.version,
                   v.request, v.outline, v.queries, v.results, v.spec, v.validation,
                   v.dataset_version_id, v.created_at
            FROM app.dashboards d
            JOIN app.dashboard_versions v
              ON v.dashboard_id = d.id AND v.version = d.current_version
            WHERE d.id = :id AND d.user_id = :u AND {VISIBLE}
        """),
        {"id": dashboard_id, "u": user_id, "days": days},
    )
    found = row.mappings().first()
    return dict(found) if found else None


async def delete_expired_dashboards(db: AsyncSession, days: int) -> int:
    """Versions cascade."""
    result = await db.execute(
        text("DELETE FROM app.dashboards WHERE updated_at < now() - make_interval(days => :days)"),
        {"days": days},
    )
    return result.rowcount
