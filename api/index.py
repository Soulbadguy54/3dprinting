import os
from datetime import date
from typing import Literal

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, text
from sqlalchemy.exc import SQLAlchemyError

from api.bootstrap import initialize_database
from api.database import SessionLocal, engine
from api.models import Collection, CollectionGame, Game, User, UserGame

app = FastAPI(
    title="RateApp API",
    version="0.2.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

initialize_database()


class LibraryPayload(BaseModel):
    gameId: int | None = None
    status: Literal["completed", "playing", "wishlist"]
    platform: str | None = None
    completedAt: date | None = None
    startedAt: date | None = None
    score: float | None = Field(default=None, ge=1, le=10)
    review: str | None = Field(default=None, max_length=5000)
    collectionIds: list[str] = Field(default_factory=list)
    addedAt: date | None = None


def _session():
    if SessionLocal is None:
        raise HTTPException(status_code=503, detail="Database is not configured")
    return SessionLocal()


def _demo_user(session) -> User:
    user = session.scalar(select(User).where(User.nickname == "soulbadguy"))
    if user is None:
        raise HTTPException(status_code=503, detail="Demo user is not initialized")
    return user


def _collection_slugs(session, user_game_id: int) -> list[str]:
    return list(
        session.scalars(
            select(Collection.slug)
            .join(CollectionGame, CollectionGame.collection_id == Collection.id)
            .where(CollectionGame.user_game_id == user_game_id)
            .order_by(Collection.id)
        ).all()
    )


def _serialize_entry(session, entry: UserGame) -> dict[str, object]:
    return {
        "gameId": entry.game.igdb_id,
        "status": entry.status,
        "platform": entry.platform,
        "completedAt": entry.completed_at.isoformat() if entry.completed_at else None,
        "startedAt": entry.started_at.isoformat() if entry.started_at else None,
        "score": float(entry.score) if entry.score is not None else None,
        "review": entry.review,
        "collectionIds": _collection_slugs(session, entry.id),
        "addedAt": entry.added_at.date().isoformat(),
    }


@app.get("/api/health")
def health() -> dict[str, object]:
    database_configured = engine is not None
    database_ok = False

    if engine is not None:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            database_ok = True
        except SQLAlchemyError:
            database_ok = False

    return {
        "ok": True,
        "service": "rateapp-api",
        "database": {
            "configured": database_configured,
            "reachable": database_ok,
        },
        "environment": os.getenv("VERCEL_ENV", "local"),
    }


@app.get("/api")
def api_root() -> dict[str, str]:
    return {
        "name": "RateApp API",
        "status": "ok",
        "docs": "/api/docs",
    }


@app.get("/api/profile")
def profile() -> dict[str, object]:
    with _session() as session:
        user = _demo_user(session)
        return {
            "nickname": user.nickname,
            "email": user.email,
            "createdAt": user.created_at.isoformat(),
            "public": True,
        }


@app.get("/api/collections")
def collections() -> list[dict[str, object]]:
    with _session() as session:
        user = _demo_user(session)
        rows = session.scalars(
            select(Collection)
            .where(Collection.user_id == user.id)
            .order_by(Collection.id)
        ).all()

        return [
            {
                "id": row.slug,
                "title": row.title,
                "description": row.description or "",
                "mark": row.mark or "",
            }
            for row in rows
        ]


@app.get("/api/library")
def library() -> list[dict[str, object]]:
    with _session() as session:
        user = _demo_user(session)
        rows = session.scalars(
            select(UserGame)
            .where(UserGame.user_id == user.id)
            .order_by(UserGame.added_at.desc())
        ).all()
        return [_serialize_entry(session, row) for row in rows]


@app.put("/api/library/{game_id}")
def upsert_library_game(game_id: int, payload: LibraryPayload) -> dict[str, object]:
    with _session() as session:
        user = _demo_user(session)
        game = session.scalar(select(Game).where(Game.igdb_id == game_id))
        if game is None:
            raise HTTPException(status_code=404, detail="Game is not available in the demo catalog")

        entry = session.scalar(
            select(UserGame).where(
                UserGame.user_id == user.id,
                UserGame.game_id == game.id,
            )
        )

        if entry is None:
            entry = UserGame(
                user_id=user.id,
                game_id=game.id,
                status=payload.status,
            )
            session.add(entry)

        entry.status = payload.status
        entry.platform = None if payload.status == "wishlist" else payload.platform
        entry.completed_at = payload.completedAt if payload.status == "completed" else None
        entry.started_at = payload.startedAt if payload.status == "playing" else None
        entry.score = payload.score if payload.status == "completed" else None
        entry.review = payload.review

        session.flush()
        session.execute(
            delete(CollectionGame).where(CollectionGame.user_game_id == entry.id)
        )

        if payload.collectionIds:
            selected_collections = session.scalars(
                select(Collection).where(
                    Collection.user_id == user.id,
                    Collection.slug.in_(payload.collectionIds),
                )
            ).all()
            session.add_all(
                [
                    CollectionGame(
                        collection_id=collection.id,
                        user_game_id=entry.id,
                    )
                    for collection in selected_collections
                ]
            )

        session.commit()
        session.refresh(entry)
        return _serialize_entry(session, entry)


@app.delete("/api/library/{game_id}", status_code=204)
def delete_library_game(game_id: int) -> Response:
    with _session() as session:
        user = _demo_user(session)
        game = session.scalar(select(Game).where(Game.igdb_id == game_id))
        if game is None:
            return Response(status_code=204)

        entry = session.scalar(
            select(UserGame).where(
                UserGame.user_id == user.id,
                UserGame.game_id == game.id,
            )
        )
        if entry is not None:
            session.delete(entry)
            session.commit()

    return Response(status_code=204)
