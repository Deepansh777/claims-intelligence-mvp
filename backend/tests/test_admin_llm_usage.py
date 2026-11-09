import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from app.api.deps import CurrentUser, get_current_user
from app.main import app
from app.services.llm_usage_service import window
from tests.conftest import as_user, db


def test_window_month_crosses_year():
    w = window("month", date(2026, 1, 15))
    assert (w["start"], w["prev"], w["end"]) == (
        date(2025, 2, 1),
        date(2024, 2, 1),
        date(2026, 1, 16),
    )
    assert window("year", date(2026, 1, 15))["prev"] is None


def _seed(user_id: str, started_at: datetime, calls: list[tuple[str, int, int, float | None]]):
    run_id = uuid.uuid4()
    db(
        "INSERT INTO llm_metrics.llm_runs (id, user_id, feature, status, started_at) "
        "VALUES ($1, $2, 'ask', 'success', $3)",
        run_id,
        user_id,
        started_at,
    )
    for model, tin, tout, cost in calls:
        db(
            "INSERT INTO llm_metrics.llm_calls (id, run_id, provider, model, status, input_tokens, "
            "output_tokens, cost_usd, started_at) VALUES ($1, $2, 'openai', $3, 'success', $4, $5, $6, $7)",
            uuid.uuid4(),
            run_id,
            model,
            tin,
            tout,
            cost,
            started_at,
        )


def test_llm_usage_admin_only_and_sums_call_costs(http):
    uid = as_user()
    assert http.get("/api/v1/admin/llm-usage").status_code == 403

    now = datetime.now(UTC)
    _seed(uid, now, [("gpt-6.1-sol", 1000, 100, 0.5), ("gpt-4o-mini", 200, 20, None)])
    _seed(uid, now - timedelta(days=40), [("gpt-6.1-sol", 10, 1, 9.0)])  # outside 30 days
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=uid, is_admin=True)

    body = http.get("/api/v1/admin/llm-usage?period=day").json()
    mine = next(r for r in body["by_user"] if r["key"] == uid)
    assert mine["requests"] == 1
    assert (mine["input_tokens"], mine["output_tokens"]) == (1200, 120)
    assert mine["cost_usd"] == pytest.approx(0.5)
    assert mine["unpriced_calls"] == 1
    assert len(body["series"]) == 30 and body["series"][-1]["key"] == now.date().isoformat()
    assert body["previous"] is not None

    yearly = http.get("/api/v1/admin/llm-usage?period=year").json()
    assert next(r for r in yearly["by_user"] if r["key"] == uid)["requests"] == 2
    assert yearly["previous"] is None
    assert http.get("/api/v1/admin/llm-usage?period=week").status_code == 422
