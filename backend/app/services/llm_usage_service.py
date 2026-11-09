"""Admin Console LLM usage report: totals, prior-period totals, a filled time series, breakdowns."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from app.db.session import SessionLocal
from app.repositories import llm_usage

Period = Literal["day", "month", "year"]
EMPTY = {
    "requests": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "cost_usd": 0.0,
    "unpriced_calls": 0,
    "active_days": 0,
}


def add_months(d: date, n: int) -> date:
    m = d.year * 12 + d.month - 1 + n
    return date(m // 12, m % 12 + 1, 1)


def window(period: Period, today: date) -> dict:
    """Current range [start, end) and the equally long prior range; year is all time, no prior."""
    end = today + timedelta(days=1)
    if period == "day":
        start = today - timedelta(days=29)
        return {
            "start": start,
            "end": end,
            "prev": start - timedelta(days=30),
            "label": "Last 30 days",
        }
    if period == "month":
        start = add_months(today, -11)
        return {
            "start": start,
            "end": end,
            "prev": add_months(start, -12),
            "label": "Last 12 months",
        }
    return {"start": None, "end": end, "prev": None, "label": "All time, by year"}


def buckets(period: Period, w: dict, first_year: int) -> list[date]:
    if period == "day":
        return [w["start"] + timedelta(days=i) for i in range(30)]
    if period == "month":
        return [add_months(w["start"], i) for i in range(12)]
    return [date(y, 1, 1) for y in range(first_year, w["end"].year + 1)]


def _ts(d: date | None) -> datetime | None:
    return d and datetime.combine(d, time(), UTC)


async def report(period: Period, today: date | None = None) -> dict:
    today = today or datetime.now(UTC).date()
    w = window(period, today)
    start, end = _ts(w["start"]), _ts(w["end"])
    async with SessionLocal() as db:
        total = await llm_usage.usage(db, "total", start, end)
        prev = await llm_usage.usage(db, "total", _ts(w["prev"]), start) if w["prev"] else None
        series = await llm_usage.usage(db, "bucket", start, end, unit=period)
        by = {g: await llm_usage.usage(db, g, start, end) for g in ("model", "user", "feature")}
    by_bucket = {r["key"]: r for r in series}
    first_year = min((k.year for k in by_bucket), default=today.year)
    return {
        "period": period,
        "label": w["label"],
        "total": total[0] if total else EMPTY,
        "previous": (prev[0] if prev else EMPTY) if w["prev"] else None,
        "series": [
            {**by_bucket.get(b, EMPTY), "key": b.isoformat()}
            for b in buckets(period, w, first_year)
        ],
        **{f"by_{g}": rows for g, rows in by.items()},
    }
