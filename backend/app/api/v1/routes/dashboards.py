import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi.responses import HTMLResponse, JSONResponse

from app.api.deps import CurrentUser, get_current_user
from app.schemas.dashboards import GenerateRequest, OutlineRequest
from app.services import dashboard_export, dashboard_service

router = APIRouter(prefix="/dashboards")
User = Annotated[CurrentUser, Depends(get_current_user)]
RATE_LIMITED = "Too many dashboard requests in the last hour. Try again later."


def _error(status: int, detail: str, code: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail, "code": code})


@router.post("/outline")
async def outline(body: OutlineRequest, user: User):
    try:
        return await dashboard_service.create_outline(user, body)
    except dashboard_service.RateLimited:
        return _error(429, RATE_LIMITED, "rate_limited")
    except TimeoutError:
        return _error(504, "Outlining the dashboard took too long. Try again.", "timeout")


@router.post("/builds", status_code=202)
async def start_build(body: GenerateRequest, user: User):
    try:
        return await dashboard_service.start_build(user, body)
    except dashboard_service.Invalid as e:
        return _error(422, str(e), "invalid_outline")
    except dashboard_service.RateLimited:
        return _error(429, RATE_LIMITED, "rate_limited")


@router.get("/builds")
async def list_builds(user: User):
    """Running builds and outcomes not yet dismissed; the client polls this while any run."""
    return await dashboard_service.list_builds(user)


@router.get("/builds/{build_id}")
async def get_build(build_id: uuid.UUID, user: User):
    found = await dashboard_service.get_build(user, build_id)
    return found if found is not None else _error(404, "Build not found.", "not_found")


@router.post("/builds/{build_id}/cancel")
async def cancel_build(build_id: uuid.UUID, user: User):
    try:
        return await dashboard_service.cancel_build(user, build_id)
    except dashboard_service.NotFound:
        return _error(404, "Build not found.", "not_found")
    except dashboard_service.Conflict:
        return _error(409, "This build has already finished.", "conflict")


@router.post("/builds/{build_id}/seen", status_code=204)
async def mark_build_seen(build_id: uuid.UUID, user: User):
    if not await dashboard_service.mark_build_seen(user, build_id):
        return _error(404, "Finished build not found.", "not_found")
    return Response(status_code=204)


@router.get("")
async def list_dashboards(user: User):
    return await dashboard_service.list_dashboards(user)


@router.get("/{dashboard_id}")
async def get_dashboard(dashboard_id: uuid.UUID, user: User):
    found = await dashboard_service.get_dashboard(user, dashboard_id)
    return found if found is not None else _error(404, "Dashboard not found.", "not_found")


@router.get("/{dashboard_id}/dashboard.html")
async def export_html(dashboard_id: uuid.UUID, user: User, download: bool = False):
    found = await dashboard_service.export_html(user, dashboard_id)
    if found is None:
        return _error(404, "Dashboard not found.", "not_found")
    name, body = found
    headers = {
        "Content-Security-Policy": dashboard_export.response_csp(),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
    }
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{name}"'
    return HTMLResponse(body, headers=headers)
