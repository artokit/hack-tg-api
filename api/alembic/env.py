import asyncio
from logging.config import fileConfig

from sqlalchemy import inspect, pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from config import DatabaseSettings
from db import models

config = context.config
database_url = DatabaseSettings().database_url.get_secret_value()

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = models.Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    inspector = inspect(connection)
    if inspector.has_table("alembic_version") and inspector.has_table("tickets"):
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        columns = {column["name"] for column in inspector.get_columns("tickets")}
        if revision in {"0002", "0003"} and "title" in columns:
            raise RuntimeError(
                "Legacy feature/tickets database detected. Migration IDs 0002/0003 "
                "differ from master. Back up this database and migrate into a new "
                "database before importing existing tickets; do not stamp or reset it."
            )
    connection.commit()
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = create_async_engine(database_url, poolclass=pool.NullPool)
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
