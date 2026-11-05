import asyncio
from logging.config import fileConfig

from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app.core.config import settings

if context.config.config_file_name:
    fileConfig(context.config.config_file_name)


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=None, include_schemas=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline mode is not supported; run against the database.")
asyncio.run(run_migrations_online())
