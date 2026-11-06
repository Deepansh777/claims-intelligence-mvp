"""Shared fixtures for tests that run against the live database with a fake model."""

import asyncio
import uuid

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.api.deps import CurrentUser, get_current_user
from app.core.config import settings
from app.llm import client as llm_client
from app.main import app


def db(sql: str, *args):
    async def run():
        conn = await asyncpg.connect(settings.database_url.replace("+asyncpg", ""))
        try:
            return await conn.fetch(sql, *args)
        finally:
            await conn.close()

    return asyncio.run(run())


@pytest.fixture(scope="module")
def http():
    try:
        db("SELECT 1 FROM app.conversations LIMIT 1")
    except (OSError, asyncpg.PostgresError) as e:
        pytest.skip(f"database unavailable: {e}")
    with TestClient(app) as c:
        yield c
    db("DELETE FROM app.conversations WHERE user_id LIKE 'test-%'")
    db("DELETE FROM app.dashboard_builds WHERE user_id LIKE 'test-%'")
    db("DELETE FROM app.dashboards WHERE user_id LIKE 'test-%'")
    db("DELETE FROM llm_metrics.llm_runs WHERE user_id LIKE 'test-%'")
    app.dependency_overrides.clear()


def as_user(user_id: str | None = None) -> str:
    user = CurrentUser(id=user_id or f"test-{uuid.uuid4().hex[:8]}", is_admin=False)
    app.dependency_overrides[get_current_user] = lambda: user
    return user.id


@pytest.fixture
def llm(monkeypatch):
    """Queue of structured outputs the fake model returns, plus the prompts it received."""
    queue, prompts = [], []

    async def fake(schema, system, prompt, effort, config):
        prompts.append(prompt)
        item = queue.pop(0)
        assert isinstance(item, schema)
        return item

    monkeypatch.setattr(llm_client, "call_structured", fake)
    return queue, prompts
