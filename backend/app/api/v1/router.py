from fastapi import APIRouter

from app.api.v1.routes import conversations, health

router = APIRouter()
router.include_router(health.router, tags=["health"])
router.include_router(conversations.router, tags=["conversations"])
router.include_router(conversations.runs_router, tags=["conversations"])
router.include_router(conversations.meta_router, tags=["meta"])
