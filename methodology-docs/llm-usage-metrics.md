# LLM Usage Metrics

Every LLM call records its token usage, cost, latency and outcome in a dedicated Postgres schema, `llm_metrics`. This lets us answer questions like "what did we spend this month, on which feature, for which user, with which model?" with plain SQL. This document complements `architecture.md` and `llm-best-practices.md`.

---

## 1. What Gets Recorded

There are two levels: a **run** is one user request (one graph execution), and a **call** is one model call inside that run. A single chat message may trigger several calls, for example routing, then planning, then responding.

| Metric                | Per call | Per run (sum) | Notes                                              |
|-----------------------|:-------:|:------------:|----------------------------------------------------|
| Input tokens          | âœ“ | âœ“ | Includes cached tokens                                     |
| Cached input tokens   | âœ“ | âœ“ | Billed at the cheaper cached rate                          |
| Output tokens         | âœ“ | âœ“ | Includes reasoning tokens                                  |
| Reasoning tokens      | âœ“ | âœ“ | Reasoning models only; a subset of output tokens           |
| Total tokens          | âœ“ | âœ“ | Input + output                                             |
| Cost (USD)            | âœ“ | âœ“ | Calculated at write time from the pricing table, then stored as a snapshot |
| Latency (ms)          | âœ“ | âœ“ | Wall-clock time                                            |
| Time to first token   | âœ“ |   | Measures how responsive streaming feels                    |
| Model, node           | âœ“ |   | Which LangGraph node made the call                         |
| Status, error type    | âœ“ | âœ“ | `success` / `error` / `cancelled`                          |
| Finish reason         | âœ“ |   | `stop`, `length` (truncated!), `tool_calls`â€¦               |
| User, conversation, feature |   | âœ“ | For attributing cost                                 |

**What's not recorded:** prompt text, completion text, or any user content. This schema stores numbers only, which keeps it consistent with the leak-prevention rules in `llm-best-practices.md`.

---

## 2. Schema

```
llm_metrics.model_pricing        llm_metrics.llm_runs              llm_metrics.llm_calls
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”       â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”      â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ id (PK)                â”‚       â”‚ id (PK) = request_id     â”‚â—€â”€â”€â”€â”€â”€â”‚ run_id (FK, cascade)     â”‚
â”‚ provider, model        â”‚       â”‚ user_id, conversation_id â”‚      â”‚ id (PK) = LangChain run  â”‚
â”‚ input_per_1m           â”‚       â”‚ feature, status          â”‚      â”‚ node, provider, model    â”‚
â”‚ cached_input_per_1m    â”‚       â”‚ started/ended, latency   â”‚      â”‚ status, finish_reason    â”‚
â”‚ output_per_1m          â”‚â—€â”€â”€â”   â”‚ token totals, cost_usd   â”‚      â”‚ token counts             â”‚
â”‚ effective_from / to    â”‚   â”‚   â”‚ attributes (JSONB)       â”‚      â”‚ input/output/total cost  â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜   â”‚   â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜      â”‚ latency_ms, ttft_ms      â”‚
                             â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”‚ pricing_id (FK)          â”‚
                                                                   â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
Views: v_daily_usage Â· v_user_daily_usage Â· v_unpriced_calls
```

We use a separate schema, rather than tables in `public`, for three reasons. Metrics stay clearly apart from application data. It can have different permissions, such as a read-only role for dashboards. And it can be archived or partitioned on its own schedule.

### Files

| File | Purpose |
|------|---------|
| `backend/alembic/versions/20261030_create_llm_metrics_schema.py` | Creates the schema, tables, indexes and views |
| `backend/app/models/llm_metrics.py` | SQLAlchemy models |
| `backend/app/llm/usage.py` | `UsageTracker` callback that captures and saves usage |

---

## 3. How Capture Works

```
graph.astream(config={"callbacks": [tracker]})
   â”‚
   â”œâ”€ on_chat_model_start â”€â”€â–¶ start a call record (node, model, start time)
   â”œâ”€ on_llm_new_token    â”€â”€â–¶ record time to first token
   â”œâ”€ on_llm_end          â”€â”€â–¶ read usage_metadata â†’ tokens, model, finish_reason
   â””â”€ on_llm_error        â”€â”€â–¶ mark the call as an error
   â”‚
finally: tracker.save(status)  â”€â”€â–¶ one transaction: 1 run row + N call rows
```

The design choices behind this:

- **Callbacks, not manual bookkeeping.** LangChain passes callbacks down to every model call in the graph, including subgraphs and tools that call models. New nodes get tracked automatically.
- **Buffer in memory, write once.** Nothing touches the database while tokens are streaming.
- **Use a separate DB session.** A failed metrics write is logged and swallowed. It never breaks the user's request, and the app transaction never rolls back the metrics.
- **Use `asyncio.shield` on save.** If the client disconnects, the run is cancelled but the metrics still get written, with status `cancelled`. Calls that never finished are marked `cancelled` too.
- **The run ID equals the request ID.** The `request_id` shown to users in error messages is the primary key of `llm_runs`, so support can look up the exact run.

### Required: turn on usage reporting for streaming

By default, OpenAI only reports token usage in streaming responses when asked. Set this in the model factory:

```python
# backend/app/llm/client.py
def get_chat_model(**overrides) -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        timeout=settings.openai_timeout_seconds,
        max_retries=2,
        stream_usage=True,   # â† required for token counts on streamed calls
        **overrides,
    )
```

If this is missing, the tracker logs a warning and records 0 tokens.

---

## 4. Integration

**In the service**, create the tracker and attach it to the run config:

```python
async def prepare_run(self, user, conversation_id, body):
    # ... ownership checks + input guards ...
    tracker = UsageTracker(
        request_id=uuid.uuid4(),
        feature="chat",
        user_id=user.id,
        conversation_id=conversation_id,
        attributes={"graph_version": "v3"},  # optional, numbers/labels only
    )
    config = {
        "configurable": {"thread_id": f"{user.id}:{conversation_id}"},
        "recursion_limit": 25,
        "callbacks": [tracker],
    }
    return graph, inputs, config, tracker
```

**In the streaming gate** (`streaming.py`), track the outcome and save it in `finally`:

```python
async def stream_run(graph, inputs, config, request, tracker) -> AsyncIterator[str]:
    request_id = str(tracker.request_id)
    status, error_type = "success", None
    try:
        async for part in graph.astream(inputs, config=config,
                                        stream_mode=["messages", "custom"], version="v2"):
            if await request.is_disconnected():
                status = "cancelled"
                break
            ...  # same allowlist logic as before
        yield sse("done", {"message_id": request_id})
    except asyncio.CancelledError:
        status = "cancelled"
        raise
    except Exception as exc:
        status, error_type = "error", type(exc).__name__
        log.exception("LLM run failed", extra={"request_id": request_id})
        yield sse("error", {"message": "Something went wrong. Please try again.",
                            "request_id": request_id})
    finally:
        await asyncio.shield(tracker.save(status, error_type))
```

Non-streaming calls (`ainvoke`) use the same pattern: pass `callbacks=[tracker]` in the config and call `save` in `finally`.

**In Alembic `env.py`**, make sure non-public schemas are picked up by autogenerate:

```python
context.configure(
    connection=connection,
    target_metadata=target_metadata,
    include_schemas=True,
)
```

Also import `app.models.llm_metrics` wherever your models are collected, so `Base.metadata` knows about the tables.

---

## 5. Pricing

Costs are calculated **at write time** and stored on each call row. Changing prices later therefore never rewrites history.

**Formula:**

```
input_cost  = (input_tokens âˆ’ cached_input_tokens) Ã— input_per_1m / 1M
            + cached_input_tokens Ã— cached_input_per_1m / 1M
output_cost = output_tokens Ã— output_per_1m / 1M     (reasoning already included)
```

**Model matching:** OpenAI often returns dated snapshot names such as `gpt-4o-mini-2024-07-18`. The tracker tries an exact match first, then falls back to the longest pricing row whose name is a prefix of the snapshot name, so you only need one row per base model.

**Changing a price:** don't edit an existing row. Close it and insert a new one:

```sql
UPDATE llm_metrics.model_pricing
   SET effective_to = now()
 WHERE provider = 'openai' AND model = 'gpt-4o-mini' AND effective_to IS NULL;

INSERT INTO llm_metrics.model_pricing (provider, model, input_per_1m, cached_input_per_1m, output_per_1m)
VALUES ('openai', 'gpt-4o-mini', <input>, <cached_input>, <output>);
```

Take the numbers from OpenAI's official pricing page. Don't hard-code prices in Python. If a model has no price row, its calls are still recorded with `cost_usd = NULL` and show up in `v_unpriced_calls`, so add a price and backfill if needed.

---

## 6. Useful Queries

```sql
-- Spend this month by feature and model
SELECT feature, model, sum(cost_usd) AS cost, sum(total_tokens) AS tokens
FROM llm_metrics.v_daily_usage
WHERE day >= date_trunc('month', now())
GROUP BY 1, 2 ORDER BY cost DESC;

-- Top 10 users by cost, last 7 days
SELECT user_id, sum(cost_usd) AS cost, sum(runs) AS runs
FROM llm_metrics.v_user_daily_usage
WHERE day >= current_date - 7
GROUP BY 1 ORDER BY cost DESC LIMIT 10;

-- Average cost and tokens per request, by feature
SELECT feature, avg(cost_usd) AS avg_cost, avg(total_tokens) AS avg_tokens,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_ms
FROM llm_metrics.llm_runs
WHERE started_at >= now() - interval '7 days'
GROUP BY 1;

-- Which graph node burns the most tokens?
SELECT node, model, sum(total_tokens) AS tokens, sum(cost_usd) AS cost
FROM llm_metrics.llm_calls
WHERE started_at >= now() - interval '7 days'
GROUP BY 1, 2 ORDER BY cost DESC;

-- Prompt-cache hit rate
SELECT model, round(100.0 * sum(cached_input_tokens) / nullif(sum(input_tokens), 0), 1) AS cache_hit_pct
FROM llm_metrics.llm_calls GROUP BY 1;

-- Truncated answers (hit max tokens)
SELECT count(*) FROM llm_metrics.llm_calls
WHERE finish_reason = 'length' AND started_at >= now() - interval '1 day';
```

---

## 7. Operations

- **Access:** give dashboards and BI tools a read-only role with `USAGE` on schema `llm_metrics` and `SELECT` on its tables and views. The app role only needs `INSERT`.
- **Budgets:** for per-user limits, check `sum(cost_usd)` for today from `llm_runs` before starting a run. Cache this value; don't query it on every token.
- **Growth:** you get one row per call. Indexes on `started_at` cover time-range queries. If the table grows into the tens of millions of rows, partition `llm_calls` by month or move older data to an archive.
- **Embeddings:** embedding models don't trigger chat-model callbacks. If you add embeddings, record their usage from the API response directly, as a call row with `node = 'embedding'`.
- **Testing:** in tests, use a fake chat model that returns `usage_metadata`, run a small graph with the tracker, and assert the run and call rows plus the computed cost.