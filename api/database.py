import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


def _database_url() -> str | None:
    return (
        os.getenv("DATABASE_URL")
        or os.getenv("POSTGRES_URL")
        or os.getenv("NEON_DATABASE_URL")
    )


class Base(DeclarativeBase):
    pass


DATABASE_URL = _database_url()

engine: Engine | None = (
    create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=2,
    )
    if DATABASE_URL
    else None
)

SessionLocal = (
    sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    if engine is not None
    else None
)
