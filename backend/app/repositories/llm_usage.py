"""LLM usage aggregates for the Admin Console (schema `llm_metrics`). Queries only.

Counts runs as requests and sums call-level cost, so one unpriced call doesn't hide the
priced calls in the same run (the run's own cost_usd is NULL then). Dates are UTC.
"""

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Fixed SQL group keys; never user input.
GROUPS = {
    "total": "NULL",
    "bucket": "date_trunc(:unit, ts)::date",
    "model": "model",
    "user": "user_id",
    "feature": "feature",
}


async def usage(
    db: AsyncSession, group: str, start: datetime | None, end: datetime, unit: str = "day"
) -> list[dict]:
    rows = await db.execute(
        text(f"""
            SELECT {GROUPS[group]} AS key,
                   count(DISTINCT run_id) AS requests,
                   sum(tin)::bigint AS input_tokens, sum(tout)::bigint AS output_tokens,
                   coalesce(sum(cost_usd), 0)::float AS cost_usd,
                   count(*) FILTER (WHERE unpriced) AS unpriced_calls,
                   count(DISTINCT ts::date) AS active_days
            FROM (
                SELECT r.id AS run_id, r.user_id, r.feature,
                       r.started_at AT TIME ZONE 'UTC' AS ts,
                       coalesce(c.model, r.attributes->>'model', 'unknown') AS model,
                       coalesce(c.input_tokens, 0) AS tin, coalesce(c.output_tokens, 0) AS tout,
                       c.cost_usd, c.id IS NOT NULL AND c.cost_usd IS NULL AS unpriced
                FROM llm_metrics.llm_runs r
                LEFT JOIN llm_metrics.llm_calls c ON c.run_id = r.id
                WHERE r.started_at < :end
                  AND (CAST(:start AS timestamptz) IS NULL OR r.started_at >= :start)
            ) u
            GROUP BY 1
            ORDER BY cost_usd DESC, 1
        """),
        {"start": start, "end": end, "unit": unit},
    )
    return [dict(r) for r in rows.mappings()]
