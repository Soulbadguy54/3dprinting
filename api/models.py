from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    nickname: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    pin_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(primary_key=True)
    igdb_id: Mapped[int] = mapped_column(unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    cover_url: Mapped[str | None] = mapped_column(String(1000))
    release_date: Mapped[date | None] = mapped_column(Date)
    igdb_rating: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    cached_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserGame(Base):
    __tablename__ = "user_games"
    __table_args__ = (UniqueConstraint("user_id", "game_id", name="uq_user_game"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    platform: Mapped[str | None] = mapped_column(String(80))
    completed_at: Mapped[date | None] = mapped_column(Date, index=True)
    started_at: Mapped[date | None] = mapped_column(Date)
    score: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    review: Mapped[str | None] = mapped_column(Text)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    game: Mapped[Game] = relationship()


class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(500))
    mark: Mapped[str | None] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CollectionGame(Base):
    __tablename__ = "collection_games"
    __table_args__ = (
        UniqueConstraint("collection_id", "user_game_id", name="uq_collection_user_game"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    collection_id: Mapped[int] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"),
        index=True,
    )
    user_game_id: Mapped[int] = mapped_column(
        ForeignKey("user_games.id", ondelete="CASCADE"),
        index=True,
    )
