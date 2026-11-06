import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

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


@router.post("/stream")
async def generate(body: GenerateRequest, user: User):
    try:
        prep = await dashboard_service.prepare(user, body)
    except dashboard_service.Invalid as e:
        return _error(422, str(e), "invalid_outline")
    except dashboard_service.RateLimited:
        return _error(429, RATE_LIMITED, "rate_limited")
    return StreamingResponse(
        dashboard_service.stream(prep),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
