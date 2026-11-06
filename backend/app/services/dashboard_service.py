"""Dashboards: outline a provider dashboard, generate it, and store each result as a version."""

import asyncio
import logging
import re
import uuid
from contextlib import aclosing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.api.deps import CurrentUser
from app.core.config import settings
from app.db.session import SessionLocal
from app.llm.dashboard_schemas import DashboardOutline, DashboardSpec, DashboardTab, outline_errors
from app.llm.graphs import dashboard
from app.llm.streaming import run_gated
from app.llm.usage import UsageTracker
from app.repositories import conversations as conversation_repo
from app.repositories import dashboards as repo
from app.schemas.dashboards import GenerateRequest, OutlineRequest
from app.services import dashboard_export
from app.services.analytics_sql import run_query

log = logging.getLogger(__name__)
RATE_LIMIT_PER_HOUR = 30  # outline and generation runs together
OUTLINE_TIMEOUT_S = 120
RUN_TIMEOUT_S = 300
MAX_TERMS = 5
MAX_CANDIDATES = 50
ROSTER_SQL = """
SELECT pcp_npi, pcp_group_tin, pcp_fullname, pcp_group_name, member_months,
       attributed_member_count
FROM mart.nexus_pcp_roster
WHERE pcp_npi = ANY($1::text[]) OR pcp_group_tin = ANY($1::text[])
   OR pcp_fullname ILIKE ANY($2::text[]) OR pcp_group_name ILIKE ANY($2::text[])
ORDER BY member_months DESC
"""
FAILED_TAB_TEXT = "This tab couldn't be built: its queries failed. Try regenerating the dashboard."
FAILED_TEXT = "The dashboard couldn't be built from the available data. Try a narrower request."
TIMEOUT_TEXT = "Building the dashboard took too long and was stopped. Try fewer tabs."
ERROR_TEXT = "Something went wrong. Please try again."
SAVING_TEXT = "Saving the dashboard…"
TAB_STEPS = ("plan", "query", "compose")  # the `step` phases each tab reports
# shortcut: tasks live in this API process, so a restart fails running builds (see retention);
# move builds to a job queue if restarts during builds become common or there are several workers.
_tasks: dict[uuid.UUID, asyncio.Task] = {}


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class Invalid(Exception):
    pass


class RateLimited(Exception):
    pass


async def find_providers(terms: list[str]) -> list[dict]:
    terms = [t.strip() for t in terms if t.strip()][:MAX_TERMS]
    patterns = ["%" + re.sub(r"([\\%_])", r"\\\1", t) + "%" for t in terms]
    r = await run_query(ROSTER_SQL, terms, patterns, max_rows=MAX_CANDIDATES)
    return [dict(zip(r.columns, row)) for row in r.rows]


async def _check_rate(user: CurrentUser) -> None:
    async with SessionLocal() as db:
        since = datetime.now(UTC) - timedelta(hours=1)
        if await repo.count_user_runs_since(db, user.id, since) >= RATE_LIMIT_PER_HOUR:
            raise RateLimited


async def create_outline(user: CurrentUser, body: OutlineRequest) -> dict:
    await _check_rate(user)
    tracker = UsageTracker(uuid.uuid4(), "dashboard_outline", user.id, None)
    config = {
        "configurable": {"find_providers": find_providers, "effort": body.effort},
        "callbacks": [tracker],
    }
    status, error_type = "success", None
    try:
        async with asyncio.timeout(OUTLINE_TIMEOUT_S):
            result = await dashboard.outline(
                body.request, [t.model_dump() for t in body.tabs], config
            )
    except BaseException as e:
        status, error_type = "error", type(e).__name__
        raise
    finally:
        await asyncio.shield(tracker.save(status, error_type))
    return result.model_dump()


@dataclass(frozen=True)
class PreparedRun:
    run_id: uuid.UUID
    dashboard_id: uuid.UUID
    user_id: str
    request: str
    outline: DashboardOutline
    effort: str
    dataset_version_id: int | None


async def prepare(user: CurrentUser, body: GenerateRequest) -> PreparedRun:
    """Checks that must fail with an HTTP status before the build starts."""
    scope = body.outline.scope
    candidates = await find_providers([t for t in (scope.provider_npi, scope.provider_tin) if t])
    if errors := outline_errors(body.outline) + dashboard.scope_errors(scope, candidates):
        raise Invalid("; ".join(errors))
    await _check_rate(user)
    async with SessionLocal() as db:
        version = await conversation_repo.latest_dataset_version(db)
    return PreparedRun(
        run_id=uuid.uuid4(),
        dashboard_id=uuid.uuid4(),
        user_id=user.id,
        request=body.request,
        outline=body.outline,
        effort=body.effort,
        dataset_version_id=version,
    )


def _failed_tab(t) -> DashboardTab:
    return DashboardTab(
        id=t.id,
        name=t.name,
        outcome="unsupported",
        widgets=[],
        insights=[],
        grid=[],
        narrative=FAILED_TAB_TEXT,
        assumptions=[],
        limitations=[],
    )


def _version(prep: PreparedRun, tabs: dict) -> dict:
    """Version row from the per-tab graph output, tabs in outline order."""
    spec, queries, results, validation = [], {}, {}, {}
    for t in prep.outline.tabs:
        out = tabs.get(t.id) or {"plan": None, "executions": [], "results": {}, "spec": None}
        spec.append(out["spec"] or _failed_tab(t))
        queries[t.id] = {
            "plan": out["plan"] and out["plan"].model_dump(),
            "executions": [
                {k: v for k, v in e.items() if k != "result"} for e in out["executions"]
            ],
        }
        results[t.id] = {name: r.model_dump() for name, r in out["results"].items()}
        validation[t.id] = {
            "status": "failed" if out["spec"] is None else "ok",
            "errors": out.get("errors", []),
        }
    return {
        "dashboard_id": prep.dashboard_id,
        "version": 1,
        "parent_version": None,
        "request": prep.request,
        "outline": prep.outline.model_dump(),
        "queries": queries,
        "results": results,
        "spec": DashboardSpec(title=prep.outline.title, tabs=spec).model_dump(),
        "validation": validation,
        "dataset_version_id": prep.dataset_version_id,
        "llm_run_id": prep.run_id,
    }


async def _save(prep: PreparedRun, version: dict) -> None:
    """Saves the dashboard and marks the build built in one transaction, unless it was cancelled.

    The build row lock orders this against a concurrent cancel: exactly one of them wins.
    """
    async with SessionLocal() as db:
        await repo.insert_dashboard(db, prep.dashboard_id, prep.user_id, prep.outline.title)
        await repo.insert_version(db, version)
        if await repo.finish_build(db, prep.run_id, "built", dashboard_id=prep.dashboard_id):
            await db.commit()


async def _event(build_id: uuid.UUID, message: str, steps_done: int) -> None:
    async with SessionLocal() as db:
        await repo.add_build_event(db, build_id, message, steps_done)
        await db.commit()


async def _fail(build_id: uuid.UUID, error: str, failed_step: str) -> None:
    async with SessionLocal() as db:
        await repo.finish_build(db, build_id, "failed", error=error, failed_step=failed_step)
        await db.commit()


async def _build(prep: PreparedRun) -> None:
    """Runs a build to its outcome. Nothing is saved unless at least one tab was built."""
    tracker = UsageTracker(prep.run_id, "dashboard", prep.user_id, prep.dashboard_id)
    config = {
        "configurable": {"run_query": run_query, "effort": prep.effort},
        "callbacks": [tracker],
        "recursion_limit": 25,
    }
    inputs = {"request": prep.request, "outline": prep.outline}
    state: dict = {}
    steps, last = set(), "Starting the build"
    status, error_type = "success", None
    try:
        try:
            async with (
                asyncio.timeout(RUN_TIMEOUT_S),
                aclosing(run_gated(dashboard.graph, inputs, config)) as events,
            ):
                async for kind, data in events:
                    if kind == "status":
                        last = data["message"]
                        steps.add(data["step"] or last)
                        await _event(prep.run_id, last, len(steps))
                    else:
                        state = data
        except TimeoutError:
            status, error_type = "error", "TimeoutError"
            await _fail(prep.run_id, TIMEOUT_TEXT, last)
            return
        tabs = state.get("tabs") or {}
        if not any(out["spec"] for out in tabs.values()):
            await _fail(prep.run_id, FAILED_TEXT, last)
            return
        await _event(prep.run_id, SAVING_TEXT, _steps_total(prep.outline))
        await asyncio.shield(_save(prep, _version(prep, tabs)))
    except asyncio.CancelledError:
        status = "cancelled"
        raise
    except Exception as e:
        status, error_type = "error", type(e).__name__
        log.exception("Dashboard build failed", extra={"request_id": str(prep.run_id)})
        await _fail(prep.run_id, ERROR_TEXT, last)
    finally:
        await asyncio.shield(tracker.save(status, error_type))


def _steps_total(outline: DashboardOutline) -> int:
    return len(outline.tabs) * len(TAB_STEPS) + 1  # + saving


async def start_build(user: CurrentUser, body: GenerateRequest) -> dict:
    prep = await prepare(user, body)
    async with SessionLocal() as db:
        await repo.insert_build(
            db,
            {
                "id": prep.run_id,
                "user_id": user.id,
                "title": prep.outline.title,
                "request": prep.request,
                "outline": prep.outline.model_dump(),
                "effort": prep.effort,
                "steps_total": _steps_total(prep.outline),
            },
        )
        await db.commit()
    task = asyncio.create_task(_build(prep))
    _tasks[prep.run_id] = task
    task.add_done_callback(lambda _: _tasks.pop(prep.run_id, None))
    return await get_build(user, prep.run_id)


async def list_builds(user: CurrentUser) -> list[dict]:
    async with SessionLocal() as db:
        return await repo.list_open_builds(db, user.id, settings.dashboard_retention_days)


async def get_build(user: CurrentUser, build_id: uuid.UUID) -> dict | None:
    async with SessionLocal() as db:
        return await repo.get_build(db, build_id, user.id, settings.dashboard_retention_days)


async def cancel_build(user: CurrentUser, build_id: uuid.UUID) -> dict:
    """Raises NotFound, or Conflict when the build already finished (it may have just saved)."""
    async with SessionLocal() as db:
        cancelled = await repo.cancel_build(db, build_id, user.id)
        await db.commit()
    if not cancelled:
        raise NotFound if await get_build(user, build_id) is None else Conflict
    if task := _tasks.get(build_id):
        task.cancel()
    return await get_build(user, build_id)


async def mark_build_seen(user: CurrentUser, build_id: uuid.UUID) -> bool:
    async with SessionLocal() as db:
        seen = await repo.mark_build_seen(db, build_id, user.id)
        await db.commit()
    return seen


async def list_dashboards(user: CurrentUser) -> list[dict]:
    async with SessionLocal() as db:
        return await repo.list_dashboards(db, user.id, settings.dashboard_retention_days)


async def get_dashboard(user: CurrentUser, dashboard_id: uuid.UUID) -> dict | None:
    async with SessionLocal() as db:
        return await repo.get_current_version(
            db, dashboard_id, user.id, settings.dashboard_retention_days
        )


async def delete_dashboard(user: CurrentUser, dashboard_id: uuid.UUID) -> bool:
    async with SessionLocal() as db:
        deleted = await repo.delete_dashboard(db, dashboard_id, user.id)
        await db.commit()
    return deleted


async def methodology(user: CurrentUser, dashboard_id: uuid.UUID) -> dict | None:
    v = await get_dashboard(user, dashboard_id)
    return None if v is None else dashboard_export.methodology(v)


async def export_html(user: CurrentUser, dashboard_id: uuid.UUID) -> tuple[str, str] | None:
    """(filename, HTML) of the current version, the same file for viewing and download."""
    v = await get_dashboard(user, dashboard_id)
    if v is None:
        return None
    p = dashboard_export.payload(v)
    return dashboard_export.filename(v["outline"]["filename"]), dashboard_export.render_html(p)
