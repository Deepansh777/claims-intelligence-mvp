"""Dashboard, dashboard-version and dashboard-build storage (schema `app`). Queries only.

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


async def list_dashboards(db: AsyncSession, user_id: str, days: int) -> list[dict]:
    rows = await db.execute(
        text(f"""
            SELECT d.id, d.title, d.current_version, d.created_at, d.updated_at,
                   v.outline->'scope' AS scope,
                   (SELECT jsonb_agg(jsonb_build_object('name', t->>'name', 'outcome', t->>'outcome'))
                    FROM jsonb_array_elements(v.spec->'tabs') t) AS tabs
            FROM app.dashboards d
            JOIN app.dashboard_versions v
              ON v.dashboard_id = d.id AND v.version = d.current_version
            WHERE d.user_id = :u AND {VISIBLE}
            ORDER BY d.updated_at DESC
        """),
        {"u": user_id, "days": days},
    )
    return [dict(r) for r in rows.mappings()]


async def get_current_version(
    db: AsyncSession, dashboard_id: uuid.UUID, user_id: str, days: int
) -> dict | None:
    row = await db.execute(
        text(f"""
            SELECT d.id AS dashboard_id, d.title, d.current_version, d.updated_at, v.version,
                   v.request, v.outline, v.queries, v.results, v.spec, v.validation,
                   v.dataset_version_id, v.created_at, dv.created_at AS dataset_loaded_at
            FROM app.dashboards d
            JOIN app.dashboard_versions v
              ON v.dashboard_id = d.id AND v.version = d.current_version
            LEFT JOIN app.dataset_versions dv ON dv.id = v.dataset_version_id
            WHERE d.id = :id AND d.user_id = :u AND {VISIBLE}
        """),
        {"id": dashboard_id, "u": user_id, "days": days},
    )
    found = row.mappings().first()
    return dict(found) if found else None


BUILD_COLUMNS = (
    "id, title, request, outline, effort, status, steps_done, steps_total, events, "
    "dashboard_id, error, failed_step, created_at, finished_at, seen_at, "
    # Server-side so the client's clock doesn't skew the elapsed time it shows.
    "round(extract(epoch FROM coalesce(finished_at, now()) - created_at) * 1000)::bigint "
    "AS elapsed_ms"
)
BUILD_VISIBLE = "user_id = :u AND created_at >= now() - make_interval(days => :days)"


async def insert_build(db: AsyncSession, b: dict) -> None:
    await db.execute(
        text(
            "INSERT INTO app.dashboard_builds (id, user_id, title, request, outline, effort, "
            "steps_total) VALUES (:id, :user_id, :title, :request, CAST(:outline AS jsonb), "
            ":effort, :steps_total)"
        ),
        {**b, "outline": json.dumps(b["outline"], default=str)},
    )


async def add_build_event(
    db: AsyncSession, build_id: uuid.UUID, message: str, steps_done: int
) -> None:
    await db.execute(
        text(
            "UPDATE app.dashboard_builds SET steps_done = :n, events = events || "
            "jsonb_build_array(jsonb_build_object('at', now(), 'message', CAST(:m AS text))) "
            "WHERE id = :id AND status = 'running'"
        ),
        {"id": build_id, "m": message, "n": steps_done},
    )


async def finish_build(db: AsyncSession, build_id: uuid.UUID, status: str, **fields) -> bool:
    """Running -> status. False when the build already ended (for example, was cancelled)."""
    values = {"dashboard_id": None, "error": None, "failed_step": None, **fields}
    row = await db.execute(
        text(
            "UPDATE app.dashboard_builds SET status = :s, dashboard_id = :dashboard_id, "
            "error = :error, failed_step = :failed_step, finished_at = now() "
            "WHERE id = :id AND status = 'running' RETURNING 1"
        ),
        {"id": build_id, "s": status, **values},
    )
    return row.first() is not None


async def cancel_build(db: AsyncSession, build_id: uuid.UUID, user_id: str) -> bool:
    row = await db.execute(
        text(
            "UPDATE app.dashboard_builds SET status = 'cancelled', finished_at = now() "
            "WHERE id = :id AND user_id = :u AND status = 'running' RETURNING 1"
        ),
        {"id": build_id, "u": user_id},
    )
    return row.first() is not None


async def mark_build_seen(db: AsyncSession, build_id: uuid.UUID, user_id: str) -> bool:
    row = await db.execute(
        text(
            "UPDATE app.dashboard_builds SET seen_at = coalesce(seen_at, now()) "
            "WHERE id = :id AND user_id = :u AND status <> 'running' RETURNING 1"
        ),
        {"id": build_id, "u": user_id},
    )
    return row.first() is not None


async def list_open_builds(db: AsyncSession, user_id: str, days: int) -> list[dict]:
    """Running builds and finished ones whose outcome the user hasn't dismissed, oldest first."""
    rows = await db.execute(
        text(
            f"SELECT {BUILD_COLUMNS} FROM app.dashboard_builds WHERE {BUILD_VISIBLE} "
            "AND (status = 'running' OR seen_at IS NULL) ORDER BY created_at"
        ),
        {"u": user_id, "days": days},
    )
    return [dict(r) for r in rows.mappings()]


async def get_build(db: AsyncSession, build_id: uuid.UUID, user_id: str, days: int) -> dict | None:
    row = await db.execute(
        text(
            f"SELECT {BUILD_COLUMNS} FROM app.dashboard_builds WHERE id = :id AND {BUILD_VISIBLE}"
        ),
        {"id": build_id, "u": user_id, "days": days},
    )
    found = row.mappings().first()
    return dict(found) if found else None


async def fail_running_builds(db: AsyncSession, error: str) -> int:
    result = await db.execute(
        text(
            "UPDATE app.dashboard_builds SET status = 'failed', error = :e, finished_at = now(), "
            "failed_step = events->-1->>'message' WHERE status = 'running'"
        ),
        {"e": error},
    )
    return result.rowcount


async def delete_expired_builds(db: AsyncSession, days: int) -> int:
    result = await db.execute(
        text(
            "DELETE FROM app.dashboard_builds "
            "WHERE created_at < now() - make_interval(days => :days)"
        ),
        {"days": days},
    )
    return result.rowcount


async def delete_expired_dashboards(db: AsyncSession, days: int) -> int:
    """Versions cascade."""
    result = await db.execute(
        text("DELETE FROM app.dashboards WHERE updated_at < now() - make_interval(days => :days)"),
        {"days": days},
    )
    return result.rowcount
