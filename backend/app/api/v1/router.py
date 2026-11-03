from fastapi import APIRouter

from app.api.v1.routes import health

router = APIRouter()
router.include_router(health.router, tags=["health"])
