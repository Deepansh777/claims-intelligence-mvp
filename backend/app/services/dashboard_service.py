"""Dashboards: outline a provider dashboard, generate it, and store each result as a version."""

import asyncio
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.api.deps import CurrentUser
from app.core.config import settings
from app.db.session import SessionLocal
from app.llm.dashboard_schemas import DashboardOutline, DashboardSpec, DashboardTab, outline_errors
from app.llm.graphs import dashboard
from app.llm.streaming import run_gated, sse
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


class NotFound(Exception):
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
    """Checks that must fail with an HTTP status before the stream starts."""
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
        takeaway=FAILED_TAB_TEXT,
        findings=[],
        widgets=[],
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
    async with SessionLocal() as db:
        await repo.insert_dashboard(db, prep.dashboard_id, prep.user_id, prep.outline.title)
        await repo.insert_version(db, version)
        await db.commit()


async def stream(prep: PreparedRun) -> AsyncIterator[str]:
    """Status events, then one result. Nothing is saved unless at least one tab was built."""
    tracker = UsageTracker(prep.run_id, "dashboard", prep.user_id, prep.dashboard_id)
    config = {
        "configurable": {"run_query": run_query, "effort": prep.effort},
        "callbacks": [tracker],
        "recursion_limit": 25,
    }
    inputs = {"request": prep.request, "outline": prep.outline}
    state: dict = {}
    status, error_type, t0 = "success", None, time.monotonic()
    try:
        try:
            async with (
                asyncio.timeout(RUN_TIMEOUT_S),
                aclosing(run_gated(dashboard.graph, inputs, config)) as events,
            ):
                async for kind, data in events:
                    if kind == "status":
                        yield sse("status", data)
                    else:
                        state = data
        except TimeoutError:
            status, error_type = "error", "TimeoutError"
            yield sse("result", {"outcome": "failed", "text": TIMEOUT_TEXT})
            return
        tabs = state.get("tabs") or {}
        if not any(out["spec"] for out in tabs.values()):
            yield sse("result", {"outcome": "failed", "text": FAILED_TEXT})
            return
        version = _version(prep, tabs)
        await asyncio.shield(_save(prep, version))
        yield sse(
            "result",
            {
                "outcome": "built",
                "dashboard_id": prep.dashboard_id,
                "version": 1,
                "title": prep.outline.title,
                "duration_ms": round((time.monotonic() - t0) * 1000),
                "tabs": [
                    {"id": t["id"], "name": t["name"], "outcome": t["outcome"]}
                    for t in version["spec"]["tabs"]
                ],
            },
        )
    except (asyncio.CancelledError, GeneratorExit):
        status = "cancelled"
        raise
    except Exception as e:
        status, error_type = "error", type(e).__name__
        log.exception("Dashboard run failed", extra={"request_id": str(prep.run_id)})
        yield sse("error", {"message": ERROR_TEXT, "request_id": str(prep.run_id)})
    finally:
        await asyncio.shield(tracker.save(status, error_type))


async def get_dashboard(user: CurrentUser, dashboard_id: uuid.UUID) -> dict | None:
    async with SessionLocal() as db:
        return await repo.get_current_version(
            db, dashboard_id, user.id, settings.dashboard_retention_days
        )


async def export_html(user: CurrentUser, dashboard_id: uuid.UUID) -> tuple[str, str] | None:
    """(filename, HTML) of the current version, the same file for viewing and download."""
    v = await get_dashboard(user, dashboard_id)
    if v is None:
        return None
    p = dashboard_export.payload(v)
    return dashboard_export.filename(v["outline"]["filename"]), dashboard_export.render_html(p)
