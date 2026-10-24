"""Lightweight, explainable, catalog-only personalized game discovery.

No IGDB call per swipe. Rankings derive from actual rated games, genres,
user feedback and a small deterministic exploration component.
"""
import json
from collections import defaultdict
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from api.collections_service import _ensure_wishlist_collection
from api.library_service import _game_payload, _community_rating_map
from api.models import CollectionGame, DiscoveryFeedback, Game, UserGame
from api.security import _session, _current_user

router = APIRouter()


def _genres(game: Game) -> list[str]:
    try:
        data = json.loads(game.genres_json or "[]")
        return [str(item).casefold() for item in data if isinstance(item, str)]
    except (ValueError, TypeError):
        return []


def _taste_weights(session, user_id: int) -> dict[str, float]:
    weights: dict[str, float] = defaultdict(float)
    ratings = session.scalars(
        select(UserGame).where(
            UserGame.user_id == user_id,
            UserGame.status.in_(("completed", "dropped")),
            UserGame.score.is_not(None),
        )
    ).all()
    if ratings:
        games_by_id = {
            game.id: game for game in session.scalars(
                select(Game).where(Game.id.in_([entry.game_id for entry in ratings]))
            )
        }
        for entry in ratings:
            game = games_by_id.get(entry.game_id)
            if game is None:
                continue
            # Explicit completed/dropped ratings dominate one-off discovery swipes.
            delta = (float(entry.score) - 6.3) * 2.0
            for genre in _genres(game):
                weights[genre] += delta

    feedback = session.scalars(
        select(DiscoveryFeedback).where(DiscoveryFeedback.user_id == user_id)
    ).all()
    if feedback:
        games_by_id = {
            game.id: game for game in session.scalars(
                select(Game).where(Game.id.in_([event.game_id for event in feedback]))
            )
        }
        for event in feedback:
            game = games_by_id.get(event.game_id)
            if game is None:
                continue
            delta = 0.65 if event.action in ("like", "wishlist") else -0.65
            for genre in _genres(game):
                weights[genre] += delta
    return weights


@router.get("/api/discover/feed")
def discovery_feed(request: Request) -> dict[str, object]:
    with _session() as session:
        user = _current_user(request, session)
        excluded = set(session.scalars(
            select(UserGame.game_id).where(UserGame.user_id == user.id)
        ).all())
        excluded.update(session.scalars(
            select(DiscoveryFeedback.game_id).where(DiscoveryFeedback.user_id == user.id)
        ).all())
        weights = _taste_weights(session, user.id)
        # Bounded shared local catalog; no IGDB calls and no new database rows.
        catalog = session.scalars(
            select(Game).where(
                Game.cover_url.is_not(None),
                Game.igdb_rating.is_not(None),
                Game.igdb_rating >= 55,
            ).order_by(Game.popularity_count.desc(), Game.id.desc()).limit(1800)
        ).all()

        def score(game: Game) -> float:
            genres = _genres(game)
            # Saturation stops one genre from becoming a near-permanent filter.
            taste = sum(max(-6, min(6, weights.get(genre, 0) / 5)) for genre in genres[:3])
            quality = min(float(game.igdb_rating or 0), 100) / 24
            popularity = min(game.popularity_count or 0, 1000) / 600
            explore = ((game.igdb_id * 37 + user.id * 97) % 101) / 90
            return taste + quality + popularity + explore

        remaining = [game for game in catalog if game.id not in excluded]
        remaining.sort(key=lambda game: (-score(game), game.id))
        selected = remaining[:24]
        ratings = _community_rating_map(session, [game.id for game in selected])
        return {
            "items": [_game_payload(game, ratings.get(game.id)) for game in selected],
            "remaining": len(remaining),
        }


class FeedbackPayload(BaseModel):
    gameId: int
    action: str


@router.post("/api/discover/feedback")
def discovery_feedback(payload: FeedbackPayload, request: Request) -> dict[str, object]:
    if payload.action not in ("like", "dislike", "wishlist"):
        raise HTTPException(422, detail="Недопустимое действие.")
    with _session() as session:
        user = _current_user(request, session)
        game = session.scalar(select(Game).where(Game.igdb_id == payload.gameId))
        if game is None:
            raise HTTPException(404, detail="Игра не найдена.")

        previous = session.scalar(select(DiscoveryFeedback).where(
            DiscoveryFeedback.user_id == user.id, DiscoveryFeedback.game_id == game.id
        ))
        if previous is not None:
            # Idempotent repeat of the same action; other edits require undo.
            if previous.action != payload.action:
                raise HTTPException(409, detail="Сначала отмени предыдущий свайп.")
            return {"ok": True, "action": previous.action}

        entry = session.scalar(select(UserGame).where(
            UserGame.user_id == user.id, UserGame.game_id == game.id
        ))
        if entry is not None and entry.status in ("completed", "dropped", "playing"):
            raise HTTPException(409, detail="Игра уже есть в библиотеке.")

        wishlist_added = False
        if payload.action == "wishlist":
            collection = _ensure_wishlist_collection(session, user.id)
            if entry is None:
                entry = UserGame(user_id=user.id, game_id=game.id, status="untracked")
                session.add(entry)
                session.flush()
            exists = session.scalar(select(CollectionGame.id).where(
                CollectionGame.collection_id == collection.id,
                CollectionGame.user_game_id == entry.id,
            ))
            if exists is None:
                session.add(CollectionGame(collection_id=collection.id, user_game_id=entry.id))
                wishlist_added = True
        session.add(DiscoveryFeedback(
            user_id=user.id, game_id=game.id, action=payload.action,
            wishlist_added=wishlist_added,
        ))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(409, detail="Решение уже сохранено.")
        return {"ok": True, "action": payload.action}


@router.delete("/api/discover/feedback/{game_id}")
def undo_discovery_feedback(game_id: int, request: Request) -> dict[str, bool]:
    with _session() as session:
        user = _current_user(request, session)
        game = session.scalar(select(Game).where(Game.igdb_id == game_id))
        if game is None:
            raise HTTPException(404, detail="Игра не найдена.")
        event = session.scalar(select(DiscoveryFeedback).where(
            DiscoveryFeedback.user_id == user.id, DiscoveryFeedback.game_id == game.id
        ))
        if event is None:
            raise HTTPException(404, detail="Нет свайпа для отмены.")
        if event.action == "wishlist" and event.wishlist_added:
            entry = session.scalar(select(UserGame).where(
                UserGame.user_id == user.id, UserGame.game_id == game.id
            ))
            if entry:
                from api.models import Collection
                collection = session.scalar(select(Collection).where(
                    Collection.user_id == user.id, Collection.slug == "wishlist"
                ))
                if collection is not None:
                    member = session.scalar(select(CollectionGame).where(
                        CollectionGame.collection_id == collection.id,
                        CollectionGame.user_game_id == entry.id,
                    ))
                    if member:
                        session.delete(member)
                        session.flush()
                if entry.status in ("untracked", "wishlist"):
                    others = session.scalar(select(CollectionGame.id).where(
                        CollectionGame.user_game_id == entry.id
                    ).limit(1))
                    if others is None:
                        session.delete(entry)
        session.delete(event)
        session.commit()
        return {"ok": True}
