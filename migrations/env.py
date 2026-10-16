"""Alembic online migrations. No database modification at API import time."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from api.database import DATABASE_URL, Base
import api.models  # noqa: F401 - register tables

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations_offline():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL must be configured for migrations")
    context.configure(url=DATABASE_URL, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL must be configured for migrations")
    # NullPool prevents holding extra connections open in CI / Neon poolers.
    engine = engine_from_config(
        {"sqlalchemy.url": DATABASE_URL}, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
