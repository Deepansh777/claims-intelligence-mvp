"""Conversation, message and analysis-run storage (schema `app`). Queries only.

Retention: a message is visible while created_at is within `days` of now. Every read filters on
that, so expired content disappears before the purge deletes it.
"""

import json
import uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

NEW_TITLE = "New conversation"
TITLE_LEN = 60
PREVIEW_LEN = 200
VISIBLE = "m.created_at >= now() - make_interval(days => :days)"
# Messages of one request share created_at (one transaction); the user message sorts first.
CHRONOLOGICAL = "m.created_at, m.role DESC"


async def create_conversation(db: AsyncSession, user_id: str) -> dict:
    row = await db.execute(
        text("INSERT INTO app.conversations (user_id) VALUES (:u) RETURNING id, created_at"),
        {"u": user_id},
    )
    return {**row.mappings().one(), "title": NEW_TITLE}


async def owns_conversation(
    db: AsyncSession, conversation_id: uuid.UUID, user_id: str, days: int
) -> bool:
    row = await db.execute(
        text(
            "SELECT 1 FROM app.conversations c WHERE c.id = :c AND c.user_id = :u AND ("
            "c.created_at >= now() - make_interval(days => :days) OR EXISTS ("
            f"SELECT 1 FROM app.messages m WHERE m.conversation_id = c.id AND {VISIBLE}))"
        ),
        {"c": conversation_id, "u": user_id, "days": days},
    )
    return row.first() is not None


async def list_conversations(
    db: AsyncSession,
    user_id: str,
    days: int,
    latest_version: int | None,
    conversation_id: uuid.UUID | None = None,
) -> list[dict]:
    """Title, preview and network come from visible messages only."""
    rows = await db.execute(
        text(f"""
            WITH v AS (
                SELECT m.conversation_id, m.role, m.content, m.created_at,
                       r.dataset_version_id, r.context_snapshot
                FROM app.messages m
                JOIN app.conversations c ON c.id = m.conversation_id
                LEFT JOIN app.analysis_runs r ON r.message_id = m.id
                WHERE c.user_id = :u AND {VISIBLE}
            )
            SELECT c.id, c.created_at,
                coalesce((SELECT left(content, :title_len) FROM v
                          WHERE v.conversation_id = c.id AND role = 'user'
                          ORDER BY created_at LIMIT 1), :new_title) AS title,
                (SELECT left(content, :preview_len) FROM v
                 WHERE v.conversation_id = c.id AND role = 'assistant' AND content <> ''
                 ORDER BY created_at DESC LIMIT 1) AS preview,
                (SELECT context_snapshot ->> 'network' FROM v
                 WHERE v.conversation_id = c.id AND context_snapshot IS NOT NULL
                 ORDER BY created_at DESC LIMIT 1) AS network,
                coalesce((SELECT max(created_at) FROM v WHERE v.conversation_id = c.id),
                         c.created_at) AS last_activity,
                coalesce((SELECT bool_or(dataset_version_id < :latest) FROM v
                          WHERE v.conversation_id = c.id), false) AS stale
            FROM app.conversations c
            WHERE c.user_id = :u
              AND (CAST(:c AS uuid) IS NULL OR c.id = :c)
              AND (c.created_at >= now() - make_interval(days => :days)
                   OR EXISTS (SELECT 1 FROM v WHERE v.conversation_id = c.id))
            ORDER BY last_activity DESC
        """),
        {
            "u": user_id,
            "c": conversation_id,
            "days": days,
            "latest": latest_version,
            "title_len": TITLE_LEN,
            "preview_len": PREVIEW_LEN,
            "new_title": NEW_TITLE,
        },
    )
    return [dict(r) for r in rows.mappings()]


async def get_messages(db: AsyncSession, conversation_id: uuid.UUID, days: int) -> list[dict]:
    rows = await db.execute(
        text(f"""
            SELECT m.id, m.role, m.content, m.status, m.created_at,
                   m.created_at + make_interval(days => :days) AS expires_at,
                   r.id AS run_id, r.answer, r.dataset_version_id,
                   dv.created_at AS dataset_loaded_at,
                   u.latency_ms, u.cost_usd, u.input_tokens, u.cached_input_tokens,
                   u.cache_write_tokens, u.output_tokens, u.reasoning_tokens
            FROM app.messages m
            LEFT JOIN app.analysis_runs r ON r.message_id = m.id
            LEFT JOIN app.dataset_versions dv ON dv.id = r.dataset_version_id
            LEFT JOIN llm_metrics.llm_runs u ON u.id = r.id
            WHERE m.conversation_id = :c AND {VISIBLE}
            ORDER BY {CHRONOLOGICAL}
        """),
        {"c": conversation_id, "days": days},
    )
    return [dict(r) for r in rows.mappings()]


async def run_datasets(db: AsyncSession, run_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    """{run_id: {query name: QueryResult-shaped dict}} from each query's last successful attempt."""
    rows = await db.execute(
        text("""
            SELECT DISTINCT ON (run_id, name) run_id, name, columns, rows, row_count, truncated
            FROM app.query_executions
            WHERE run_id = ANY(CAST(:ids AS uuid[])) AND status = 'succeeded'
            ORDER BY run_id, name, attempt DESC
        """),
        {"ids": run_ids},
    )
    out: dict[uuid.UUID, dict] = {}
    for r in rows.mappings():
        out.setdefault(r["run_id"], {})[r["name"]] = {
            "columns": [c["name"] for c in r["columns"]],
            "types": [c["type"] for c in r["columns"]],
            "rows": r["rows"],
            "row_count": r["row_count"],
            "truncated": r["truncated"],
        }
    return out


async def recent_messages(
    db: AsyncSession, conversation_id: uuid.UUID, days: int, limit: int
) -> list[dict]:
    """Newest visible, finished messages first, for follow-up context."""
    rows = await db.execute(
        text(f"""
            SELECT m.role, m.content, m.status, r.plan, r.context_snapshot
            FROM app.messages m LEFT JOIN app.analysis_runs r ON r.message_id = m.id
            WHERE m.conversation_id = :c AND {VISIBLE} AND m.status <> 'running'
            ORDER BY m.created_at DESC, m.role
            LIMIT :n
        """),
        {"c": conversation_id, "days": days, "n": limit},
    )
    return [dict(r) for r in rows.mappings()]


async def get_run(db: AsyncSession, run_id: uuid.UUID, user_id: str, days: int) -> dict | None:
    row = await db.execute(
        text(f"""
            SELECT r.id, r.status, r.plan, r.spec, r.context_snapshot, r.answer,
                   m.conversation_id
            FROM app.analysis_runs r
            JOIN app.messages m ON m.id = r.message_id
            JOIN app.conversations c ON c.id = m.conversation_id
            WHERE r.id = :r AND c.user_id = :u AND {VISIBLE}
        """),
        {"r": run_id, "u": user_id, "days": days},
    )
    found = row.mappings().first()
    return dict(found) if found else None


async def delete_conversation(db: AsyncSession, conversation_id: uuid.UUID, user_id: str) -> bool:
    result = await db.execute(
        text("DELETE FROM app.conversations WHERE id = :c AND user_id = :u"),
        {"c": conversation_id, "u": user_id},
    )
    return result.rowcount > 0


async def count_user_messages_since(db: AsyncSession, user_id: str, since: datetime) -> int:
    row = await db.execute(
        text(
            "SELECT count(*) FROM app.messages m JOIN app.conversations c ON c.id = m.conversation_id "
            "WHERE c.user_id = :u AND m.role = 'user' AND m.created_at >= :s"
        ),
        {"u": user_id, "s": since},
    )
    return row.scalar_one()


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


async def latest_dataset(db: AsyncSession) -> dict | None:
    row = await db.execute(
        text("SELECT id, created_at FROM app.dataset_versions ORDER BY id DESC LIMIT 1")
    )
    found = row.mappings().first()
    return dict(found) if found else None


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
    jsonb = ("plan", "spec", "context", "answer")
    await db.execute(
        text(
            "INSERT INTO app.analysis_runs (id, message_id, dataset_version_id, status, plan, spec, "
            "context_snapshot, answer, duration_ms) VALUES (:id, :message_id, :dataset_version_id, "
            ":status, CAST(:plan AS jsonb), CAST(:spec AS jsonb), CAST(:context AS jsonb), "
            "CAST(:answer AS jsonb), :duration_ms)"
        ),
        {**run, **{k: json.dumps(run[k], default=str) for k in jsonb}},
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


async def delete_expired_messages(db: AsyncSession, days: int, batch: int) -> int:
    """One batch; runs and query rows cascade. In-flight answers are left alone."""
    result = await db.execute(
        text("""
            DELETE FROM app.messages WHERE id IN (
                SELECT id FROM app.messages
                WHERE created_at < now() - make_interval(days => :days) AND status <> 'running'
                LIMIT :n
            )
        """),
        {"days": days, "n": batch},
    )
    return result.rowcount


async def delete_expired_empty_conversations(db: AsyncSession, days: int) -> int:
    result = await db.execute(
        text("""
            DELETE FROM app.conversations c
            WHERE c.created_at < now() - make_interval(days => :days)
              AND NOT EXISTS (SELECT 1 FROM app.messages m WHERE m.conversation_id = c.id)
        """),
        {"days": days},
    )
    return result.rowcount


async def fail_running_messages(db: AsyncSession, content: str) -> int:
    result = await db.execute(
        text("UPDATE app.messages SET status = 'failed', content = :t WHERE status = 'running'"),
        {"t": content},
    )
    return result.rowcount
