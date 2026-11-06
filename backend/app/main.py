import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import router as api_v1_router
from app.core.config import settings
from app.db.session import engine
from app.services import retention


@asynccontextmanager
async def lifespan(app: FastAPI):
    await retention.fail_interrupted_answers()
    await retention.fail_interrupted_builds()
    purge = asyncio.create_task(retention.purge_forever())
    yield
    purge.cancel()
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Claims Intelligence Platform", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_v1_router, prefix="/api/v1")
    return app


app = create_app()
