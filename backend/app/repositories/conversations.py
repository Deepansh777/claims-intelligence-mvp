"""Conversation, message and analysis-run storage (schema `app`). Queries only."""

import json
import uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

NEW_TITLE = "New conversation"


async def create_conversation(db: AsyncSession, user_id: str) -> dict:
    row = await db.execute(
        text(
            "INSERT INTO app.conversations (user_id, title) VALUES (:u, :t) "
            "RETURNING id, title, created_at"
        ),
        {"u": user_id, "t": NEW_TITLE},
    )
    return dict(row.mappings().one())


async def owns_conversation(db: AsyncSession, conversation_id: uuid.UUID, user_id: str) -> bool:
    row = await db.execute(
        text("SELECT 1 FROM app.conversations WHERE id = :c AND user_id = :u"),
        {"c": conversation_id, "u": user_id},
    )
    return row.first() is not None


async def count_user_messages_since(db: AsyncSession, user_id: str, since: datetime) -> int:
    row = await db.execute(
        text(
            "SELECT count(*) FROM app.messages m JOIN app.conversations c ON c.id = m.conversation_id "
            "WHERE c.user_id = :u AND m.role = 'user' AND m.created_at >= :s"
        ),
        {"u": user_id, "s": since},
    )
    return row.scalar_one()


async def set_title_if_first_message(
    db: AsyncSession, conversation_id: uuid.UUID, title: str
) -> None:
    await db.execute(
        text(
            "UPDATE app.conversations SET title = :t, updated_at = now() WHERE id = :c "
            "AND NOT EXISTS (SELECT 1 FROM app.messages WHERE conversation_id = :c)"
        ),
        {"c": conversation_id, "t": title},
    )


async def insert_message(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    role: str,
    content: str,
    status: str,
    client_request_id: uuid.UUID | None = None,
) -> uuid.UUID:
    row = await db.execute(
        text(
            "INSERT INTO app.messages (conversation_id, role, content, status, client_request_id) "
            "VALUES (:c, :r, :content, :s, :k) RETURNING id"
        ),
        {"c": conversation_id, "r": role, "content": content, "s": status, "k": client_request_id},
    )
    return row.scalar_one()


async def latest_dataset_version(db: AsyncSession) -> int | None:
    return (await db.execute(text("SELECT max(id) FROM app.dataset_versions"))).scalar_one()


async def finish_message(
    db: AsyncSession, message_id: uuid.UUID, content: str, status: str
) -> None:
    await db.execute(
        text(
            "UPDATE app.messages SET content = :content, status = :s, updated_at = now() "
            "WHERE id = :m"
        ),
        {"m": message_id, "content": content, "s": status},
    )
    await db.execute(
        text(
            "UPDATE app.conversations SET updated_at = now() "
            "WHERE id = (SELECT conversation_id FROM app.messages WHERE id = :m)"
        ),
        {"m": message_id},
    )


async def insert_run(db: AsyncSession, run: dict) -> None:
    await db.execute(
        text(
            "INSERT INTO app.analysis_runs (id, message_id, dataset_version_id, status, plan, "
            "context_snapshot, answer, duration_ms) VALUES (:id, :message_id, :dataset_version_id, "
            ":status, CAST(:plan AS jsonb), CAST(:context AS jsonb), CAST(:answer AS jsonb), :duration_ms)"
        ),
        {**run, **{k: json.dumps(run[k], default=str) for k in ("plan", "context", "answer")}},
    )


async def insert_query_executions(
    db: AsyncSession, run_id: uuid.UUID, executions: list[dict]
) -> None:
    for e in executions:
        r = e["result"]
        await db.execute(
            text(
                "INSERT INTO app.query_executions (run_id, name, attempt, sql, status, error, "
                "duration_ms, columns, row_count, truncated, rows) VALUES (:run, :name, :attempt, "
                ":sql, :status, :error, :ms, CAST(:columns AS jsonb), :row_count, :truncated, "
                "CAST(:rows AS jsonb))"
            ),
            {
                "run": run_id,
                "name": e["name"],
                "attempt": e["attempt"],
                "sql": e["sql"],
                "status": e["status"],
                "error": e["error"],
                "ms": e["duration_ms"],
                "columns": r
                and json.dumps([{"name": c, "type": t} for c, t in zip(r.columns, r.types)]),
                "row_count": r and r.row_count,
                "truncated": r and r.truncated,
                "rows": r and json.dumps(r.rows, default=str),
            },
        )
