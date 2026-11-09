from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import CurrentUser, get_current_user
from app.services import llm_usage_service

router = APIRouter(prefix="/admin")
User = Annotated[CurrentUser, Depends(get_current_user)]


@router.get("/llm-usage")
async def llm_usage(user: User, period: llm_usage_service.Period = "day"):
    if not user.is_admin:
        return JSONResponse(
            status_code=403, content={"detail": "Administrators only.", "code": "forbidden"}
        )
    return await llm_usage_service.report(period)
