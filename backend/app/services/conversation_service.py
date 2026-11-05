"""Saved conversations: list, open, delete, export. Expired messages are never returned."""

import csv
import io
import uuid
from datetime import timedelta
from typing import get_args

from app.api.deps import CurrentUser
from app.core.config import settings
from app.db.session import SessionLocal
from app.llm.client import Effort
from app.repositories import conversations as repo
from app.schemas.ask import AskRequest

USAGE_KEYS = (
    "latency_ms",
    "cost_usd",
    "input_tokens",
    "cached_input_tokens",
    "cache_write_tokens",
    "output_tokens",
    "reasoning_tokens",
)


def _summary(c: dict) -> dict:
    # The whole conversation goes once its newest message expires; older ones go earlier.
    return {**c, "expires_at": c["last_activity"] + timedelta(days=settings.chat_retention_days)}


async def create_conversation(user: CurrentUser) -> dict:
    async with SessionLocal() as db:
        conversation = await repo.create_conversation(db, user.id)
        await db.commit()
    return conversation


async def list_conversations(user: CurrentUser) -> list[dict]:
    async with SessionLocal() as db:
        latest = await repo.latest_dataset_version(db)
        rows = await repo.list_conversations(db, user.id, settings.chat_retention_days, latest)
    return [_summary(c) for c in rows]


async def get_conversation(user: CurrentUser, conversation_id: uuid.UUID) -> dict | None:
    days = settings.chat_retention_days
    async with SessionLocal() as db:
        latest = await repo.latest_dataset_version(db)
        found = await repo.list_conversations(db, user.id, days, latest, conversation_id)
        if not found:
            return None
        rows = await repo.get_messages(db, conversation_id, days)
        # shortcut: every stored row (≤5,000 per query) ships with the conversation; page or lazy-load
        # datasets if conversations with many large results get slow to open.
        datasets = await repo.run_datasets(db, [m["run_id"] for m in rows if m["run_id"]])
    messages = []
    for m in rows:
        message = {k: m[k] for k in ("id", "role", "content", "status", "created_at", "expires_at")}
        if m["run_id"]:
            version = m["dataset_version_id"]
            message["answer"] = {
                **m["answer"],
                "datasets": datasets.get(m["run_id"], {}),
                "dataset_loaded_at": m["dataset_loaded_at"],
                "stale": None not in (version, latest) and version < latest,
            }
            if user.is_admin:
                message["answer"]["usage"] = {k: m[k] for k in USAGE_KEYS}
        messages.append(message)
    return {**_summary(found[0]), "messages": messages}


async def delete_conversation(user: CurrentUser, conversation_id: uuid.UUID) -> bool:
    async with SessionLocal() as db:
        deleted = await repo.delete_conversation(db, conversation_id, user.id)
        await db.commit()
    return deleted


def csv_cell(value):
    # Spreadsheet apps execute cells starting with these characters as formulas.
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


async def export_csv(user: CurrentUser, run_id: uuid.UUID, query: str) -> str | None:
    """The stored result exactly as displayed (up to 5,000 rows)."""
    async with SessionLocal() as db:
        if await repo.get_run(db, run_id, user.id, settings.chat_retention_days) is None:
            return None
        data = (await repo.run_datasets(db, [run_id])).get(run_id, {}).get(query)
    if data is None:
        return None
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(data["columns"])
    writer.writerows([csv_cell(v) for v in row] for row in data["rows"])
    return out.getvalue()


async def meta(user: CurrentUser) -> dict:
    async with SessionLocal() as db:
        dataset = await repo.latest_dataset(db)
    return {
        "dataset_version": dataset,
        "retention_days": settings.chat_retention_days,
        "model": settings.openai_model,
        "efforts": list(get_args(Effort)),
        "default_effort": AskRequest.model_fields["effort"].default,
        "networks": list(get_args(AskRequest.model_fields["network"].annotation)),
        "default_network": AskRequest.model_fields["network"].default,
        "is_admin": user.is_admin,
    }
