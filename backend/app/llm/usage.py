"""Token, cost and latency capture per run (methodology-docs/llm-usage-metrics.md).

Buffers calls in memory and writes one run row plus N call rows on its own connection;
a failed write is logged and never breaks the user's request.
"""

import json
import logging
import time
import uuid
from datetime import UTC, datetime

import asyncpg
from langchain_core.callbacks import AsyncCallbackHandler

from app.core.config import settings

log = logging.getLogger(__name__)
TOKEN_KEYS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_tokens",
    "output_tokens",
    "reasoning_tokens",
    "total_tokens",
)


def breakdown(usage: dict | None) -> dict[str, int] | None:
    """LangChain usage_metadata -> our token columns. input includes cache reads and writes."""
    if not usage:
        return None
    details_in = usage.get("input_token_details") or {}
    details_out = usage.get("output_token_details") or {}
    tokens_in, tokens_out = usage.get("input_tokens") or 0, usage.get("output_tokens") or 0
    return {
        "input_tokens": tokens_in,
        "cached_input_tokens": details_in.get("cache_read") or 0,
        "cache_write_tokens": details_in.get("cache_creation") or 0,
        "output_tokens": tokens_out,
        "reasoning_tokens": details_out.get("reasoning") or 0,
        "total_tokens": usage.get("total_tokens") or tokens_in + tokens_out,
    }


def match_price(model: str, prices: list[dict]) -> dict | None:
    """Exact model, else the longest priced name that prefixes a dated snapshot name."""
    exact = [p for p in prices if p["model"] == model]
    prefixed = sorted(
        (p for p in prices if model.startswith(p["model"])), key=lambda p: -len(p["model"])
    )
    return (exact or prefixed or [None])[0]


def cost(tokens: dict[str, int], price: dict) -> tuple[float, float]:
    cached, written = tokens["cached_input_tokens"], tokens["cache_write_tokens"]
    uncached = tokens["input_tokens"] - cached - written
    input_cost = (
        uncached * float(price["input_per_1m"])
        + cached * float(price["cached_input_per_1m"])
        + written * float(price["cache_write_per_1m"])
    ) / 1e6
    return input_cost, tokens["output_tokens"] * float(price["output_per_1m"]) / 1e6


def _ms(t0: float) -> int:
    return round((time.monotonic() - t0) * 1000)


class UsageTracker(AsyncCallbackHandler):
    def __init__(
        self, request_id: uuid.UUID, feature: str, user_id: str, conversation_id: uuid.UUID | None
    ):
        self.request_id, self.feature = request_id, feature
        self.user_id, self.conversation_id = user_id, conversation_id
        self.started_at, self._t0 = datetime.now(UTC), time.monotonic()
        self.calls: dict[uuid.UUID, dict] = {}

    async def on_chat_model_start(self, serialized, messages, *, run_id, metadata=None, **kwargs):
        self.calls[run_id] = {
            "node": (metadata or {}).get("langgraph_node"),
            "model": settings.openai_model,
            "status": "cancelled",  # until it ends or errors
            "finish_reason": None,
            "tokens": None,
            "started_at": datetime.now(UTC),
            "ended_at": None,
            "t0": time.monotonic(),
            "latency_ms": None,
            "ttft_ms": None,
        }

    async def on_llm_new_token(self, token, *, run_id, **kwargs):
        if (c := self.calls.get(run_id)) and c["ttft_ms"] is None:
            c["ttft_ms"] = _ms(c["t0"])

    async def on_llm_end(self, response, *, run_id, **kwargs):
        if not (c := self.calls.get(run_id)):
            return
        message = getattr(response.generations[0][0], "message", None)
        meta = getattr(message, "response_metadata", None) or {}
        c.update(
            status="success",
            tokens=breakdown(getattr(message, "usage_metadata", None)),
            model=meta.get("model_name") or c["model"],
            finish_reason=meta.get("finish_reason") or meta.get("status"),
            ended_at=datetime.now(UTC),
            latency_ms=_ms(c["t0"]),
        )
        if c["tokens"] is None:
            log.warning(
                "LLM call reported no token usage", extra={"request_id": str(self.request_id)}
            )

    async def on_llm_error(self, error, *, run_id, **kwargs):
        if c := self.calls.get(run_id):
            c.update(status="error", ended_at=datetime.now(UTC), latency_ms=_ms(c["t0"]))

    async def save(self, status: str, error_type: str | None = None) -> None:
        try:
            await self._save(status, error_type)
        except Exception:
            log.exception("Saving LLM usage failed", extra={"request_id": str(self.request_id)})

    async def _save(self, status: str, error_type: str | None) -> None:
        conn = await asyncpg.connect(settings.database_url.replace("+asyncpg", ""), timeout=10)
        try:
            prices = [
                dict(r)
                for r in await conn.fetch(
                    "SELECT id, model, input_per_1m, cached_input_per_1m, cache_write_per_1m, "
                    "output_per_1m FROM llm_metrics.model_pricing "
                    "WHERE provider = 'openai' AND effective_to IS NULL"
                )
            ]
            calls = []
            for call_id, c in self.calls.items():
                tokens = c["tokens"] or dict.fromkeys(TOKEN_KEYS, 0)
                price = match_price(c["model"], prices) if c["tokens"] else None
                in_cost, out_cost = cost(tokens, price) if price else (None, None)
                total = None if price is None else in_cost + out_cost
                calls.append((call_id, c, tokens, in_cost, out_cost, total, price and price["id"]))
            totals = {k: sum(t[k] for _, _, t, *_ in calls) for k in TOKEN_KEYS}
            costs = [total for *_, total, _ in calls]
            run_cost = None if None in costs else sum(costs)
            async with conn.transaction():
                await conn.execute(
                    f"INSERT INTO llm_metrics.llm_runs (id, user_id, conversation_id, feature, status, "
                    f"error_type, started_at, ended_at, latency_ms, {', '.join(TOKEN_KEYS)}, cost_usd, "
                    "attributes) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, "
                    "$15, $16, $17::jsonb)",
                    self.request_id,
                    self.user_id,
                    self.conversation_id,
                    self.feature,
                    status,
                    error_type,
                    self.started_at,
                    datetime.now(UTC),
                    _ms(self._t0),
                    *totals.values(),
                    run_cost,
                    json.dumps({"model": settings.openai_model}),
                )
                await conn.executemany(
                    f"INSERT INTO llm_metrics.llm_calls (id, run_id, node, provider, model, status, "
                    f"finish_reason, {', '.join(TOKEN_KEYS)}, input_cost_usd, output_cost_usd, "
                    "cost_usd, pricing_id, latency_ms, ttft_ms, started_at, ended_at) VALUES ($1, $2, "
                    "$3, 'openai', $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, "
                    "$18, $19, $20)",
                    [
                        (
                            call_id,
                            self.request_id,
                            c["node"],
                            c["model"],
                            c["status"],
                            c["finish_reason"],
                            *tokens.values(),
                            in_cost,
                            out_cost,
                            total,
                            price_id,
                            c["latency_ms"],
                            c["ttft_ms"],
                            c["started_at"],
                            c["ended_at"],
                        )
                        for call_id, c, tokens, in_cost, out_cost, total, price_id in calls
                    ],
                )
        finally:
            await conn.close()
