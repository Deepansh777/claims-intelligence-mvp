"""Ask: answer one question in a conversation and persist everything that was executed."""

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser
from app.core.config import settings
from app.db.session import SessionLocal
from app.llm.graphs.ask import DOC_NUMBERS, allowed_numbers, execute, graph
from app.llm.guards import resolve_answer
from app.llm.schemas import AnswerSpec, SqlPlan
from app.llm.streaming import run_gated, sse
from app.llm.usage import UsageTracker
from app.repositories import conversations as repo
from app.schemas.ask import AskRequest
from app.services.analytics_sql import run_query

log = logging.getLogger(__name__)
RATE_LIMIT_PER_HOUR = 20
RUN_TIMEOUT_S = 120
# Follow-up context: the last 4 turns, the latest analysis' SQL, ~6,000 tokens in total.
CONTEXT_MESSAGES = 8
CONTEXT_REPLY_CHARS = 600
CONTEXT_SQL_CHARS = 4000
CONTEXT_CHARS = 24000
RERUN_FAILED_TEXT = "The stored query no longer runs on the current data. Ask the question again."
FAILED_TEXT = (
    "I couldn't build a working query for this question. Try rephrasing it or narrowing the "
    "period or population."
)
TIMEOUT_TEXT = "This analysis took too long and was stopped. Try a narrower question."
ERROR_TEXT = "Something went wrong. Please try again."
PLAN_OUTCOMES = {"explain": "explained", "clarify": "clarify", "decline": "declined"}


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class RateLimited(Exception):
    pass


@dataclass(frozen=True)
class PreparedRun:
    run_id: uuid.UUID
    user_id: str
    conversation_id: uuid.UUID
    assistant_message_id: uuid.UUID
    question: str
    network: str
    effort: str
    dataset_version_id: int | None
    context: str = ""
    rerun_of: uuid.UUID | None = None


def build_context(recent: list[dict]) -> str:
    """Bounded follow-up context from visible messages (newest first): turns, then latest SQL."""
    lines = []
    latest = None
    for m in recent:
        if m["role"] == "user":
            lines.append(f"User: {m['content']}")
        else:
            lines.append(f"Assistant [{m['status']}]: {m['content'][:CONTEXT_REPLY_CHARS]}")
            if latest is None and m["plan"] and m["plan"].get("queries"):
                latest = m
    lines.reverse()
    tail = ""
    if latest:
        snapshot = latest["context_snapshot"] or {}
        sql = "\n\n".join(f"{q['name']}:\n{q['sql']}" for q in latest["plan"]["queries"])
        tail = (
            f"\n\nLatest analysis (network {snapshot.get('network')}):\n"
            f"Interpretation: {json.dumps(snapshot.get('interpretation'))}\n"
            f"SQL:\n{sql[:CONTEXT_SQL_CHARS]}"
        )
    while lines and len("\n".join(lines)) + len(tail) > CONTEXT_CHARS:
        lines.pop(0)
    return ("\n".join(lines) + tail).strip()


async def _start(
    db, user: CurrentUser, conversation_id: uuid.UUID, question: str, request_id: uuid.UUID | None
) -> tuple[uuid.UUID, int | None]:
    """Rate limit, then store the question and a 'running' answer. Returns its id and data version."""
    since = datetime.now(UTC) - timedelta(hours=1)
    if await repo.count_user_messages_since(db, user.id, since) >= RATE_LIMIT_PER_HOUR:
        raise RateLimited
    try:
        await repo.insert_message(db, conversation_id, "user", question, "complete", request_id)
        assistant_id = await repo.insert_message(db, conversation_id, "assistant", "", "running")
        version = await repo.latest_dataset_version(db)
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise Conflict(
            "An answer is already in progress in this conversation."
            if "messages_one_running" in str(e.orig)
            else "This request was already submitted."
        ) from e
    return assistant_id, version


async def prepare(user: CurrentUser, conversation_id: uuid.UUID, body: AskRequest) -> PreparedRun:
    """Checks that must fail with an HTTP status before the stream starts."""
    days = settings.chat_retention_days
    async with SessionLocal() as db:
        if not await repo.owns_conversation(db, conversation_id, user.id, days):
            raise NotFound
        recent = await repo.recent_messages(db, conversation_id, days, CONTEXT_MESSAGES)
        assistant_id, version = await _start(
            db, user, conversation_id, body.question, body.client_request_id
        )
    return PreparedRun(
        run_id=uuid.uuid4(),
        user_id=user.id,
        conversation_id=conversation_id,
        assistant_message_id=assistant_id,
        question=body.question,
        network=body.network,
        effort=body.effort,
        dataset_version_id=version,
        context=build_context(recent),
    )


async def rerun(user: CurrentUser, run_id: uuid.UUID) -> dict:
    """Re-execute a run's stored SQL on current data, with no model call, as a new answer."""
    async with SessionLocal() as db:
        run = await repo.get_run(db, run_id, user.id, settings.chat_retention_days)
        if run is None:
            raise NotFound
        if not (run["spec"] and run["plan"] and run["plan"]["queries"]):
            raise Conflict("This answer has no stored query to re-run.")
        question = run["context_snapshot"]["question"]
        assistant_id, version = await _start(db, user, run["conversation_id"], question, None)
    prep = PreparedRun(
        run_id=uuid.uuid4(),
        user_id=user.id,
        conversation_id=run["conversation_id"],
        assistant_message_id=assistant_id,
        question=question,
        network=run["context_snapshot"]["network"],
        effort=run["answer"]["effort"],
        dataset_version_id=version,
        rerun_of=run_id,
    )
    plan = SqlPlan.model_validate(run["plan"])
    state: dict = {"question": question, "plan": plan}
    t0 = time.monotonic()
    try:
        executions, results, error = await execute(plan.queries[:3], run_query, 1)
        state |= {"executions": executions, "results": results}
        if error:
            outcome = {**_outcome(state), "text": RERUN_FAILED_TEXT}
        else:
            # Runs saved before the narrative field existed have none.
            state["spec"] = AnswerSpec.model_validate({"narrative": "", **run["spec"]})
            outcome = _outcome(state)
        payload = _payload(prep, state, outcome)
        await _persist(prep, state, payload, round((time.monotonic() - t0) * 1000))
    except BaseException:
        await asyncio.shield(_close_unfinished(prep, state, "failed", t0))
        raise
    return payload


def _outcome(state: dict) -> dict:
    plan = state.get("plan")
    base = {
        "interpretation": plan.interpretation.model_dump()
        if plan and plan.interpretation
        else None,
        "options": [],
        "narrative": "",
        "components": [],
        "assumptions": [],
        "limitations": [],
        "followups": [],
    }
    if plan is None:
        return {**base, "outcome": "failed", "text": ERROR_TEXT}
    if plan.action in PLAN_OUTCOMES:
        options = plan.options[:4] if plan.action == "clarify" else []
        return {
            **base,
            "outcome": PLAN_OUTCOMES[plan.action],
            "text": plan.message or "",
            "options": options,
        }
    if "spec" not in state:
        return {**base, "outcome": "failed", "text": FAILED_TEXT}
    return {
        **base,
        **resolve_answer(state["spec"], state["results"], allowed_numbers(state), DOC_NUMBERS),
    }


def _payload(prep: PreparedRun, state: dict, outcome: dict) -> dict:
    """Everything the client may see. SQL is shown on purpose; database errors are not."""
    return {
        "run_id": prep.run_id,
        "message_id": prep.assistant_message_id,
        "conversation_id": prep.conversation_id,
        "network": prep.network,
        "effort": prep.effort,
        "model": settings.openai_model,
        "dataset_version_id": prep.dataset_version_id,
        "rerun_of": prep.rerun_of,
        **outcome,
        "queries": [
            {k: e[k] for k in ("name", "purpose", "attempt", "sql", "status", "duration_ms")}
            | {"row_count": e["result"] and e["result"].row_count}
            for e in state.get("executions", [])
        ],
        "datasets": {name: r.model_dump() for name, r in (state.get("results") or {}).items()},
    }


async def _persist(prep: PreparedRun, state: dict, payload: dict, duration_ms: int) -> None:
    plan = state.get("plan")
    answer = {k: v for k, v in payload.items() if k != "datasets"}
    async with SessionLocal() as db:
        await repo.finish_message(
            db, prep.assistant_message_id, payload["text"], payload["outcome"]
        )
        await repo.insert_run(
            db,
            {
                "id": prep.run_id,
                "message_id": prep.assistant_message_id,
                "dataset_version_id": prep.dataset_version_id,
                "status": payload["outcome"],
                "plan": plan.model_dump() if plan else None,
                "spec": state["spec"].model_dump() if "spec" in state else None,
                "context": {
                    "question": prep.question,
                    "network": prep.network,
                    "interpretation": payload["interpretation"],
                    "rerun_of": prep.rerun_of,
                },
                "answer": answer,
                "duration_ms": duration_ms,
            },
        )
        await repo.insert_query_executions(db, prep.run_id, state.get("executions", []))
        await db.commit()


async def stream(prep: PreparedRun) -> AsyncIterator[str]:
    tracker = UsageTracker(prep.run_id, "ask", prep.user_id, prep.conversation_id)
    config = {
        "configurable": {"run_query": run_query, "effort": prep.effort},
        "callbacks": [tracker],
        "recursion_limit": 25,
    }
    inputs = {"question": prep.question, "network": prep.network, "context": prep.context}
    state: dict = {}
    status, error_type, t0 = "success", None, time.monotonic()
    try:
        try:
            # aclosing: stop the graph (and its model calls) as soon as the client goes away.
            async with (
                asyncio.timeout(RUN_TIMEOUT_S),
                aclosing(run_gated(graph, inputs, config)) as events,
            ):
                async for kind, data in events:
                    if kind == "status":
                        yield sse("status", data)
                    else:
                        state = data
            outcome = _outcome(state)
        except TimeoutError:
            status, error_type = "error", "TimeoutError"
            outcome = {**_outcome({}), "outcome": "failed", "text": TIMEOUT_TEXT}
        payload = _payload(prep, state, outcome)
        await asyncio.shield(_persist(prep, state, payload, round((time.monotonic() - t0) * 1000)))
        yield sse("result", payload)
        yield sse("done", {"message_id": str(prep.assistant_message_id)})
    # Disconnect arrives as CancelledError mid-await, or GeneratorExit while paused at a yield.
    except (asyncio.CancelledError, GeneratorExit):
        status = "cancelled"
        await asyncio.shield(_close_unfinished(prep, state, "cancelled", t0))
        raise
    except Exception as e:
        status, error_type = "error", type(e).__name__
        log.exception("Ask run failed", extra={"request_id": str(prep.run_id)})
        await asyncio.shield(_close_unfinished(prep, state, "failed", t0))
        yield sse("error", {"message": ERROR_TEXT, "request_id": str(prep.run_id)})
    finally:
        await asyncio.shield(tracker.save(status, error_type))


async def _close_unfinished(prep: PreparedRun, state: dict, outcome: str, t0: float) -> None:
    """Never leave a message 'running'; keep whatever SQL already executed."""
    try:
        base = {
            **_outcome({}),
            "outcome": outcome,
            "text": "" if outcome == "cancelled" else ERROR_TEXT,
        }
        payload = _payload(prep, state, base)
        await _persist(prep, state, payload, round((time.monotonic() - t0) * 1000))
    except Exception:
        log.exception("Closing unfinished ask run failed", extra={"request_id": str(prep.run_id)})
