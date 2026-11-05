"""Chat retention (CHAT_RETENTION_DAYS): physically delete what reads already hide."""

import asyncio
import logging

from app.core.config import settings
from app.db.session import SessionLocal
from app.repositories import conversations as repo

log = logging.getLogger(__name__)
PURGE_EVERY_S = 3600
BATCH = 1000
INTERRUPTED_TEXT = "This answer was interrupted. Please ask again."


async def purge_expired() -> dict[str, int]:
    days, messages = settings.chat_retention_days, 0
    while True:
        async with SessionLocal() as db:
            deleted = await repo.delete_expired_messages(db, days, BATCH)
            await db.commit()
        messages += deleted
        if deleted < BATCH:
            break
    async with SessionLocal() as db:
        conversations = await repo.delete_expired_empty_conversations(db, days)
        await db.commit()
    return {"messages": messages, "conversations": conversations}


async def purge_forever() -> None:
    while True:
        try:
            counts = await purge_expired()
            log.info("Chat retention purge", extra=counts)
        except Exception:
            log.exception("Chat retention purge failed")
        await asyncio.sleep(PURGE_EVERY_S)


async def fail_interrupted_answers() -> None:
    """Answers still 'running' at startup died with the previous process and would lock their chat.

    shortcut: assumes one API process; with several workers, track the owning process instead.
    """
    async with SessionLocal() as db:
        await repo.fail_running_messages(db, INTERRUPTED_TEXT)
        await db.commit()
