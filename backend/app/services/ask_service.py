"""Ask: answer one question in a conversation and persist everything that was executed."""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser
from app.db.session import SessionLocal
from app.llm.graphs.ask import DOC_NUMBERS, allowed_numbers, graph
from app.llm.guards import resolve_answer
from app.llm.streaming import run_gated, sse
from app.llm.usage import UsageTracker
from app.repositories import conversations as repo
from app.schemas.ask import AskRequest
from app.services.analytics_sql import run_query

log = logging.getLogger(__name__)
RATE_LIMIT_PER_HOUR = 20
RUN_TIMEOUT_S = 120
TITLE_LEN = 60
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


async def create_conversation(user: CurrentUser) -> dict:
    async with SessionLocal() as db:
        conversation = await repo.create_conversation(db, user.id)
        await db.commit()
    return conversation


async def prepare(user: CurrentUser, conversation_id: uuid.UUID, body: AskRequest) -> PreparedRun:
    """Checks that must fail with an HTTP status before the stream starts."""
    async with SessionLocal() as db:
        if not await repo.owns_conversation(db, conversation_id, user.id):
            raise NotFound
        since = datetime.now(UTC) - timedelta(hours=1)
        if await repo.count_user_messages_since(db, user.id, since) >= RATE_LIMIT_PER_HOUR:
            raise RateLimited
        try:
            await repo.set_title_if_first_message(db, conversation_id, body.question[:TITLE_LEN])
            await repo.insert_message(
                db, conversation_id, "user", body.question, "complete", body.client_request_id
            )
            assistant_id = await repo.insert_message(
                db, conversation_id, "assistant", "", "running"
            )
            version = await repo.latest_dataset_version(db)
            await db.commit()
        except IntegrityError as e:
            await db.rollback()
            raise Conflict(
                "An answer is already in progress in this conversation."
                if "messages_one_running" in str(e.orig)
                else "This request was already submitted."
            ) from e
    return PreparedRun(
        run_id=uuid.uuid4(),
        user_id=user.id,
        conversation_id=conversation_id,
        assistant_message_id=assistant_id,
        question=body.question,
        network=body.network,
        effort=body.effort,
        dataset_version_id=version,
    )


def _outcome(state: dict) -> dict:
    plan = state.get("plan")
    base = {
        "interpretation": plan.interpretation.model_dump()
        if plan and plan.interpretation
        else None,
        "options": [],
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
        "dataset_version_id": prep.dataset_version_id,
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
                "context": {"network": prep.network, "interpretation": payload["interpretation"]},
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
    inputs = {"question": prep.question, "network": prep.network}
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
