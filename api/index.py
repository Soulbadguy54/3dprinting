import base64
import binascii
import hashlib
import json
import math
import os
import re
import secrets
import time
from urllib.parse import urlsplit
from datetime import date, datetime, timedelta, timezone
from typing import Literal

import httpx
import sentry_sdk
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy import case, delete, func, or_, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import selectinload

from api.auth_routes import router as auth_router, RegisterPayload, LoginPayload
from api.collections_service import _ensure_wishlist_collection
from api.security import (
    PIN_RE, NICK_RE, SESSION_COOKIE, password_hasher,
    _session, _now, _hash_token, _current_user, _create_session,
    _check_throttle, _record_login_failure, _clear_throttle, _user_payload,
)
from api.data_integrity import playthrough_integrity_summary
from api.push import push_ready, send_push, valid_push_endpoint
from api.database import SessionLocal, engine
from api.models import (
    AuthSession,
    Collection,
    CollectionGame,
    Game,
    GameAlias,
    Genre,
    GameGenre,
    GenreCatalogSync,
    LoginThrottle,
    PushSubscription,
    ReleasePushDelivery,
    User,
    UserGame,
    WISHLIST_SLUG, WISHLIST_TITLE, WISHLIST_DESCRIPTION, WISHLIST_MARK,
)

# Reporting is opt-in. Disable automatic request-body and PII collection.
if os.getenv("SENTRY_DSN"):
    sentry_sdk.init(
        dsn=os.environ["SENTRY_DSN"],
        environment=os.getenv("VERCEL_ENV", "development"),
        send_default_pii=False,
        max_request_body_size="never",
        traces_sample_rate=0,
    )

app = FastAPI(
    title="RateApp API",
    version="0.3.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.include_router(auth_router)

# Database schema is upgraded by `alembic upgrade head` outside the request path.
# Never run schema changes at cold start: one malformed historic row can break login.

_igdb_token: str | None = None
_igdb_token_expires_at = 0.0


COLLECTION_COLORS = frozenset({
    "violet", "rose", "blue", "cyan", "teal",
    "emerald", "lime", "amber", "orange", "slate",
})


class CollectionPayload(BaseModel):
    title: str = Field(min_length=1, max_length=32)
    description: str | None = Field(default=None, max_length=500)
    colorScheme: Literal["violet", "rose", "blue", "cyan", "teal",
                         "emerald", "lime", "amber", "orange", "slate"] = "violet"
    iconData: str | None = Field(default=None, max_length=150000)
    emoji: str | None = Field(default=None, max_length=24)


class CollectionBulkDeletePayload(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=100)


class CollectionEditPayload(BaseModel):
    # PATCH is partial: system collections accept only removedGameIds.
    title: str | None = Field(default=None, min_length=1, max_length=32)
    description: str | None = Field(default=None, max_length=500)
    colorScheme: Literal["violet", "rose", "blue", "cyan", "teal",
                         "emerald", "lime", "amber", "orange", "slate"] | None = None
    emoji: str | None = Field(default=None, max_length=24)
    removedGameIds: list[int] = Field(default_factory=list, max_length=500)


def _validated_collection_emoji(value: str | None) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    # Allow Unicode emoji sequences (ZWJ, modifiers, variation selectors and flags), not arbitrary text.
    if len(value) > 24 or not any(ord(ch) > 0x2000 for ch in value) or any(ord(ch) < 0x20 for ch in value):
        raise HTTPException(status_code=422, detail="Выберите эмодзи из каталога.")
    return value


def _validated_collection_icon(value: str | None) -> str | None:
    if not value:
        return None
    match = re.fullmatch(r"data:image/(webp|png|jpeg);base64,([A-Za-z0-9+/=]+)", value)
    if match is None:
        raise HTTPException(status_code=422, detail="Иконка должна быть PNG, JPEG или WebP.")
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(status_code=422, detail="Не удалось прочитать иконку.")
    if len(raw) > 110000 or not raw:
        raise HTTPException(status_code=422, detail="Иконка слишком большая.")
    kind = match.group(1)
    if not (
        (kind == "webp" and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP")
        or (kind == "png" and raw.startswith(b"\x89PNG\r\n\x1a\n"))
        or (kind == "jpeg" and raw.startswith(b"\xff\xd8\xff"))
    ):
        raise HTTPException(status_code=422, detail="Неверный формат иконки.")
    return value


class LibraryPayload(BaseModel):
    gameId: int | None = None
    status: Literal["completed", "playing", "wishlist", "dropped"]
    platform: str | None = Field(default=None, max_length=80)
    completedAt: date | None = None
    startedAt: date | None = None
    score: float | None = Field(default=None, ge=1, le=10)
    atmosphereScore: float | None = Field(default=None, ge=1, le=10)
    storyScore: float | None = Field(default=None, ge=1, le=10)
    technologyScore: float | None = Field(default=None, ge=1, le=10)
    gameplayScore: float | None = Field(default=None, ge=1, le=10)
    review: str | None = Field(default=None, max_length=5000)
    collectionIds: list[str] = Field(default_factory=list, max_length=100)
    addedAt: date | None = None

    @model_validator(mode="after")
    def validate_playthrough(self):
        rated = self.status in {"completed", "dropped"}
        self.platform = (self.platform or "").strip() or None
        criteria = (self.atmosphereScore, self.storyScore, self.technologyScore, self.gameplayScore)

        if rated and self.platform is None:
            raise ValueError("Выберите платформу для прохождения.")
        if rated:
            if self.completedAt is None:
                raise ValueError("Для пройденной или дропнутой игры обязательна дата.")
            if any(value is None for value in criteria):
                raise ValueError("Для статуса «Пройдено» или «Дропнуто» обязательны все четыре оценки.")
            if self.startedAt is not None:
                raise ValueError("Дата начала допустима только для статуса «Прохожу».")
        else:
            if any(value is not None for value in criteria) or self.score is not None:
                raise ValueError("Оценки допустимы только для «Пройдено» и «Дропнуто».")
            if self.completedAt is not None:
                raise ValueError("Дата окончания допустима только для «Пройдено» и «Дропнуто».")
            if self.status != "playing" and (self.startedAt is not None or self.platform is not None):
                raise ValueError("У списка желаемого не может быть даты или платформы прохождения.")
            if self.review:
                raise ValueError("Отзыв допустим только для оценённых прохождений.")
        return self


class PushSubscriptionPayload(BaseModel):
    endpoint: str = Field(min_length=20, max_length=2048)
    keys: dict[str, str]


class PushTestPayload(BaseModel):
    gameId: int


def _igdb_credentials() -> tuple[str, str]:
    client_id = os.getenv("IGDB_CLIENT_ID", "").strip()
    client_secret = os.getenv("IGDB_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=503,
            detail="IGDB ещё не настроен. Добавьте IGDB_CLIENT_ID и IGDB_CLIENT_SECRET в Vercel.",
        )
    return client_id, client_secret


def _igdb_access_token() -> tuple[str, str]:
    global _igdb_token, _igdb_token_expires_at

    client_id, client_secret = _igdb_credentials()
    if _igdb_token and time.time() < _igdb_token_expires_at - 60:
        return client_id, _igdb_token

    try:
        response = httpx.post(
            "https://id.twitch.tv/oauth2/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10.0,
        )
        if response.status_code >= 400:
            message = ""
            try:
                message = str(response.json().get("message") or "")
            except ValueError:
                pass

            if response.status_code == 400:
                raise HTTPException(
                    status_code=502,
                    detail="Twitch отклонил Client ID/Secret. Создайте новый Client Secret и обновите переменные Vercel.",
                )

            raise HTTPException(
                status_code=502,
                detail=f"Ошибка Twitch OAuth ({response.status_code})"
                + (f": {message}" if message else "."),
            )

        payload = response.json()
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Не удалось связаться с Twitch OAuth.") from exc

    token = payload.get("access_token")
    if not token:
        raise HTTPException(status_code=502, detail="IGDB не вернул access token.")

    _igdb_token = str(token)
    _igdb_token_expires_at = time.time() + int(payload.get("expires_in", 3600))
    return client_id, _igdb_token


def _igdb_cover(image_id: str | None) -> str | None:
    if not image_id:
        return None
    return f"https://images.igdb.com/igdb/image/upload/t_cover_big_2x/{image_id}.jpg"


def _community_rating_map(session, game_ids: list[int]) -> dict[int, tuple[float, int]]:
    """Calculate one RateApp rating per user/game, excluding the seeded demo account."""
    if not game_ids:
        return {}

    rows = session.execute(
        select(UserGame.game_id, func.avg(UserGame.score), func.count(UserGame.id))
        .join(User, User.id == UserGame.user_id)
        .where(
            UserGame.game_id.in_(game_ids),
            UserGame.status.in_(("completed", "dropped")),
            UserGame.score.is_not(None),
            User.email != "demo@rateapp.local",
        )
        .group_by(UserGame.game_id)
    ).all()
    return {
        int(game_id): (round(float(average), 1), int(count))
        for game_id, average, count in rows
    }


def _game_payload(
    game: Game, community_rating: tuple[float, int] | None = None,
) -> dict[str, object]:
    release_date = game.release_date.isoformat() if game.release_date else ""
    genres = json.loads(game.genres_json) if game.genres_json else []
    platforms = json.loads(game.platforms_json) if game.platforms_json else []
    title_parts = [part for part in re.split(r"\\s+", game.title.strip()) if part]
    glyph = "".join(part[0].upper() for part in title_parts[:2]) or "G"

    saved = json.loads(game.details_json) if game.details_json else None
    extras = saved if isinstance(saved, dict) else {}
    return {
        "storeLinks": extras.get("storeLinks", []),
        "trailerUrl": extras.get("trailerUrl"),
        "id": game.igdb_id,
        "title": game.title,
        "genres": genres,
        "year": game.release_date.year if game.release_date else 0,
        "releaseDate": release_date,
        "developer": game.developer or "—",
        "platforms": platforms,
        "igdbRating": round(float(game.igdb_rating or 0)),
        "communityRating": community_rating[0] if community_rating else 0,
        "communityRatings": community_rating[1] if community_rating else 0,
        "accent": "#8cf27d",
        "accent2": "#2c6bff",
        "glyph": glyph,
        "coverUrl": game.cover_url,
    }


def _cache_igdb_games(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    with _session() as session:
        ids = [int(row["id"]) for row in rows]
        existing = {
            game.igdb_id: game
            for game in session.scalars(select(Game).where(Game.igdb_id.in_(ids))).all()
        }
        cached_games: list[Game] = []
        incoming_genres: dict[int, str] = {}
        incoming_game_genres: dict[int, list[int]] = {}

        for row in rows:
            igdb_id = int(row["id"])
            game = existing.get(igdb_id)
            if game is None:
                game = Game(igdb_id=igdb_id, title=str(row.get("name") or "Unknown"))
                session.add(game)
                existing[igdb_id] = game

            first_release = row.get("first_release_date")
            release_date = (
                datetime.fromtimestamp(int(first_release), tz=timezone.utc).date()
                if first_release
                else None
            )
            genres = [
                str(item.get("name"))
                for item in (row.get("genres") or [])
                if isinstance(item, dict) and item.get("name")
            ]
            platforms = [
                str(item.get("name"))
                for item in (row.get("platforms") or [])
                if isinstance(item, dict) and item.get("name")
            ]
            developers = []
            for item in row.get("involved_companies") or []:
                if not isinstance(item, dict) or not item.get("developer"):
                    continue
                company = item.get("company")
                if isinstance(company, dict) and company.get("name"):
                    developers.append(str(company["name"]))

            cover = row.get("cover")
            image_id = cover.get("image_id") if isinstance(cover, dict) else None

            game.title = str(row.get("name") or game.title)
            game.release_date = release_date
            game.igdb_rating = row.get("rating")
            game.popularity_count = max(
                int(row.get("total_rating_count") or 0),
                int(row.get("rating_count") or 0),
            )
            game.hype_count = int(row.get("hypes") or 0)
            game.cover_url = _igdb_cover(str(image_id)) if image_id else None
            game.developer = developers[0] if developers else None
            game.genres_json = json.dumps(genres, ensure_ascii=False)
            if "genres" in row:
                genre_ids: list[int] = []
                for genre_row in row.get("genres") or []:
                    if not isinstance(genre_row, dict):
                        continue
                    gid, name = genre_row.get("id"), genre_row.get("name")
                    if isinstance(gid, int) and isinstance(name, str) and name.strip():
                        incoming_genres[gid] = name.strip()
                        genre_ids.append(gid)
                incoming_game_genres[igdb_id] = list(dict.fromkeys(genre_ids))
            game.platforms_json = json.dumps(platforms, ensure_ascii=False)

            # IGDB search provides store/trailer metadata in the same query.
            # Persist it immediately so search and library cards can display
            # links on first open without waiting for the details endpoint.
            if "websites" in row and "videos" in row:
                fresh_details = (
                    game.details_cached_at is not None
                    and game.details_cached_at.replace(
                        tzinfo=game.details_cached_at.tzinfo or timezone.utc
                    ) > _now() - timedelta(days=GAME_DETAILS_CACHE_DAYS)
                )
                if not fresh_details:
                    previous = json.loads(game.details_json) if game.details_json else None
                    previous = previous if isinstance(previous, dict) else {}
                    details = {
                        "storeLinks": _safe_store_links(row.get("websites")),
                        "trailerUrl": _safe_trailer_url(row.get("videos")),
                        "storyHours": previous.get("storyHours"),
                        "completionHours": previous.get("completionHours"),
                        "_linksOnly": True,
                    }
                    game.details_json = json.dumps(details, ensure_ascii=False)
                    game.details_cached_at = _now()

            cached_games.append(game)

        session.flush()
        if incoming_genres:
            session.execute(text("""
                INSERT INTO genres (id, name) VALUES (:id, :name)
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
            """), [{"id":gid, "name":name} for gid, name in incoming_genres.items()])
        if incoming_game_genres:
            affected = [existing[igdb_id].id for igdb_id in incoming_game_genres]
            session.execute(delete(GameGenre).where(GameGenre.game_id.in_(affected)))
            session.add_all(
                GameGenre(game_id=existing[igdb_id].id, genre_id=gid)
                for igdb_id, ids in incoming_game_genres.items()
                for gid in ids
            )
            session.flush()

        for row in rows:
            # Persist publisher/IGDB-provided alternative names, not handcrafted
            # abbreviations or special cases for individual games.
            if "alternative_names" not in row:
                continue
            game = existing[int(row["id"])]
            session.execute(delete(GameAlias).where(GameAlias.game_id == game.id))
            seen = {game.title.casefold()}
            for alternative in row.get("alternative_names") or []:
                name = alternative.get("name", "").strip() if isinstance(alternative, dict) else ""
                if not name or len(name) > 255 or name.casefold() in seen:
                    continue
                seen.add(name.casefold())
                session.add(GameAlias(game_id=game.id, name=name))

        ratings = _community_rating_map(session, [game.id for game in cached_games])
        cached = [_game_payload(game, ratings.get(game.id)) for game in cached_games]
        session.commit()
        return cached


def _collection_slugs(session, user_game_id: int) -> list[str]:
    return list(
        session.scalars(
            select(Collection.slug)
            .join(CollectionGame, CollectionGame.collection_id == Collection.id)
            .where(CollectionGame.user_game_id == user_game_id)
            .order_by(Collection.id)
        ).all()
    )


def _serialize_entry(
    session,
    entry: UserGame,
    collection_ids: list[str] | None = None,
    community_rating: tuple[float, int] | None = None,
    collection_added_at: dict[str, str] | None = None,
) -> dict[str, object]:
    if collection_added_at is None:
        joined = session.execute(
            select(Collection.slug, CollectionGame.added_at)
            .join(Collection, Collection.id == CollectionGame.collection_id)
            .where(CollectionGame.user_game_id == entry.id)
        ).all()
        collection_added_at = {slug: timestamp.isoformat() for slug, timestamp in joined}
    return {
        "gameId": entry.game.igdb_id,
        "status": entry.status,
        "statusChangedAt": (
            (entry.status_changed_at or entry.added_at).isoformat()
            if entry.status in {"completed", "playing", "dropped"} else None
        ),
        "platform": entry.platform,
        "completedAt": entry.completed_at.isoformat() if entry.completed_at else None,
        "startedAt": entry.started_at.isoformat() if entry.started_at else None,
        "score": float(entry.score) if entry.score is not None else None,
        "atmosphereScore": float(entry.atmosphere_score) if entry.atmosphere_score is not None else None,
        "storyScore": float(entry.story_score) if entry.story_score is not None else None,
        "technologyScore": float(entry.technology_score) if entry.technology_score is not None else None,
        "gameplayScore": float(entry.gameplay_score) if entry.gameplay_score is not None else None,
        "review": entry.review,
        "collectionIds": collection_ids if collection_ids is not None else _collection_slugs(session, entry.id),
        "collectionAddedAt": collection_added_at,
        "addedAt": entry.added_at.date().isoformat(),
        "game": _game_payload(entry.game, community_rating),
    }


def _collections_payload(session, user: User) -> list[dict[str, object]]:
    rows = session.scalars(
        select(Collection)
        .where(Collection.user_id == user.id)
        .order_by(
            case((Collection.slug == WISHLIST_SLUG, 0), else_=1),
            func.lower(Collection.title),
            Collection.id,
        )
    ).all()
    return [
        {
            "id": row.slug,
            "title": row.title,
            "description": row.description or "",
            "mark": row.mark or "",
            "colorScheme": row.color_scheme,
            "iconData": row.icon_data,
            "emoji": row.emoji,
            "isSystem": row.is_system or row.slug == WISHLIST_SLUG,
        }
        for row in rows
    ]


def _library_payload(session, user: User) -> list[dict[str, object]]:
    rows = session.scalars(
        select(UserGame)
        .options(selectinload(UserGame.game))
        .where(UserGame.user_id == user.id)
        .order_by(UserGame.added_at.desc())
    ).all()

    memberships: dict[int, list[str]] = {row.id: [] for row in rows}
    membership_times: dict[int, dict[str, str]] = {row.id: {} for row in rows}
    if rows:
        pairs = session.execute(
            select(CollectionGame.user_game_id, Collection.slug, CollectionGame.added_at)
            .join(Collection, Collection.id == CollectionGame.collection_id)
            .where(CollectionGame.user_game_id.in_([row.id for row in rows]))
            .order_by(CollectionGame.user_game_id, Collection.id)
        ).all()
        for user_game_id, slug, timestamp in pairs:
            memberships.setdefault(user_game_id, []).append(slug)
            membership_times.setdefault(user_game_id, {})[slug] = timestamp.isoformat()

    ratings = _community_rating_map(session, [row.game_id for row in rows])
    return [
        _serialize_entry(
            session, row, memberships.get(row.id, []),
            ratings.get(row.game_id), membership_times.get(row.id, {}),
        )
        for row in rows
    ]


def _normalized_search_text(value: str) -> str:
    return re.sub(r"[^\w]+", " ", value.casefold(), flags=re.UNICODE).strip()


def _local_game_search(session, query: str, offset: int) -> dict[str, object]:
    """Rank cached games in PostgreSQL using indexed trigram similarity.

    Both game titles and their IGDB-provided alternative names participate.
    Title relevance wins; popularity breaks near ties. No franchise-specific
    mappings are involved.
    """
    search_text = _normalized_search_text(query)
    if not search_text:
        return {"items": [], "hasMore": False, "nextOffset": None}

    title = func.lower(Game.title)
    alias = func.lower(GameAlias.name)

    def relevance(name):
        return func.greatest(
            func.similarity(name, search_text),
            func.word_similarity(search_text, name),
        )

    alias_best = (
        select(func.max(relevance(alias)))
        .where(GameAlias.game_id == Game.id)
        .correlate(Game)
        .scalar_subquery()
    )
    score = func.greatest(relevance(title), func.coalesce(alias_best, 0.0))
    exact_alias = (
        select(GameAlias.id)
        .where(GameAlias.game_id == Game.id, alias == search_text)
        .correlate(Game)
        .exists()
    )
    popularity = (
        func.ln(1 + Game.popularity_count)
        + func.ln(1 + Game.hype_count) * 0.65
    )
    # PostgreSQL can use our GIN pg_trgm indexes to shortlist candidates,
    # instead of scoring every game and every alias on a full table scan.
    alias_candidate = (
        select(GameAlias.id)
        .where(
            GameAlias.game_id == Game.id,
            or_(alias.op("%")(search_text), alias.op("%>")(search_text)),
        )
        .correlate(Game)
        .exists()
    )
    title_candidate = or_(
        title.op("%")(search_text), title.op("%>")(search_text),
    )
    rows = session.scalars(
        select(Game)
        .where(or_(title_candidate, alias_candidate), score >= 0.32)
        .order_by(
            case(
                (title == search_text, 0),
                (exact_alias, 0),
                (title.startswith(search_text), 1),
                else_=2,
            ),
            (score + popularity * 0.012).desc(),
            popularity.desc(),
            Game.id,
        )
        .offset(offset)
        .limit(GAME_SEARCH_PAGE_SIZE + 1)
    ).all()
    has_more = len(rows) > GAME_SEARCH_PAGE_SIZE
    games = rows[:GAME_SEARCH_PAGE_SIZE]
    ratings = _community_rating_map(session, [game.id for game in games])
    return {
        "items": [_game_payload(game, ratings.get(game.id)) for game in games],
        "hasMore": has_more,
        "nextOffset": offset + GAME_SEARCH_PAGE_SIZE if has_more else None,
    }


def _igdb_search_body(query: str, offset: int) -> str:
    # The IGDB search command is documented as similarity-ranked by IGDB.
    # It is not advertised as typo-tolerant, unlike our PostgreSQL search.
    safe_query = json.dumps(query.replace(";", " "), ensure_ascii=False)[1:-1]
    return (
        "fields id,name,first_release_date,rating,rating_count,"
        "total_rating_count,hypes,cover.image_id,alternative_names.name,"
        "genres.id,genres.name,platforms.name,involved_companies.developer,"
        "involved_companies.company.name,websites.url,videos.name,videos.video_id; "
        f'search "{safe_query}"; '
        "where version_parent = null; "
        f"limit {GAME_SEARCH_PAGE_SIZE + 1}; offset {offset};"
    )


@app.get("/api/health")
def health(response: Response) -> dict[str, object]:
    database_configured = engine is not None
    database_ok = False
    integrity_report = None

    if engine is not None:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                if os.getenv("VERCEL_ENV") == "production":
                    integrity_report = playthrough_integrity_summary(connection)
            database_ok = True
        except SQLAlchemyError:
            database_ok = False

    if not database_ok:
        response.status_code = 503
    return {
        "ok": database_ok,
        "service": "rateapp-api",
        "database": {"configured": database_configured, "reachable": database_ok},
        "igdb": {
            "configured": bool(
                os.getenv("IGDB_CLIENT_ID", "").strip()
                and os.getenv("IGDB_CLIENT_SECRET", "").strip()
            )
        },
        "environment": os.getenv("VERCEL_ENV", "local"),
        "playthroughIntegrity": integrity_report,
    }


@app.get("/api")
def api_root() -> dict[str, str]:
    return {"name": "RateApp API", "status": "ok", "docs": "/api/docs"}


@app.get("/api/bootstrap")
def bootstrap(request: Request) -> dict[str, object]:
    with _session() as session:
        user = _current_user(request, session)
        _ensure_wishlist_collection(session, user.id)
        session.commit()
        return {
            "user": _user_payload(user),
            "library": _library_payload(session, user),
            "collections": _collections_payload(session, user),
        }


@app.get("/api/users/{nickname}")
def public_profile(nickname: str) -> dict[str, object]:
    with _session() as session:
        user = session.scalar(select(User).where(User.nickname == nickname.strip().lower()))
        if user is None or user.email == "demo@rateapp.local":
            raise HTTPException(status_code=404, detail="Профиль не найден.")

        total = session.scalar(select(func.count(UserGame.id)).where(
            UserGame.user_id == user.id,
            UserGame.status.in_(["completed", "playing", "dropped"]),
        )) or 0
        completed = session.scalar(
            select(func.count(UserGame.id)).where(
                UserGame.user_id == user.id,
                UserGame.status == "completed",
            )
        ) or 0
        playing = session.scalar(
            select(func.count(UserGame.id)).where(
                UserGame.user_id == user.id,
                UserGame.status == "playing",
            )
        ) or 0
        wishlist = session.scalar(
            select(func.count(UserGame.id))
            .join(CollectionGame, CollectionGame.user_game_id == UserGame.id)
            .join(Collection, Collection.id == CollectionGame.collection_id)
            .where(
                UserGame.user_id == user.id,
                Collection.user_id == user.id,
                Collection.slug == WISHLIST_SLUG,
            )
        ) or 0
        dropped = session.scalar(
            select(func.count(UserGame.id)).where(
                UserGame.user_id == user.id,
                UserGame.status == "dropped",
            )
        ) or 0

        return {
            "nickname": user.nickname,
            "public": True,
            "stats": {
                "total": total,
                "completed": completed,
                "playing": playing,
                "wishlist": wishlist,
                "dropped": dropped,
            },
        }


def _sync_genre_catalog() -> int:
    client_id, token = _igdb_access_token()
    rows = _igdb_details_request(
        "genres", "fields id,name; sort id asc; limit 500;", client_id, token,
    )
    valid = [
        {"id": item["id"], "name": item["name"].strip()}
        for item in rows
        if isinstance(item.get("id"), int)
        and isinstance(item.get("name"), str)
        and item["name"].strip()
    ]
    if not valid:
        raise HTTPException(status_code=502, detail="IGDB не вернул список жанров.")
    with _session() as session:
        session.execute(text("""
            INSERT INTO genres (id, name) VALUES (:id, :name)
            ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
        """), valid)
        session.execute(text("""
            INSERT INTO game_genres (game_id, genre_id)
            SELECT g.id, t.id
            FROM games AS g
            CROSS JOIN LATERAL jsonb_array_elements_text(
                COALESCE(NULLIF(g.genres_json, ''), '[]')::jsonb
            ) AS legacy(name)
            JOIN genres AS t ON lower(t.name) = lower(legacy.name)
            ON CONFLICT (game_id, genre_id) DO NOTHING
        """))
        session.execute(text("""
            INSERT INTO genre_catalog_sync (id, refreshed_at)
            VALUES (1, now())
            ON CONFLICT (id) DO UPDATE SET refreshed_at = EXCLUDED.refreshed_at
        """))
        session.commit()
    return len(valid)


@app.get("/api/genres")
def list_genres(request: Request) -> list[dict[str, object]]:
    with _session() as session:
        _current_user(request, session)
        stamp = session.get(GenreCatalogSync, 1)
        outdated = stamp is None or (
            _now() - stamp.refreshed_at.replace(
                tzinfo=stamp.refreshed_at.tzinfo or timezone.utc
            ) > timedelta(days=30)
        )
    if outdated:
        try:
            _sync_genre_catalog()
        except (HTTPException, SQLAlchemyError):
            # Offline fallback: existing genres remain filterable.
            pass
    with _session() as session:
        _current_user(request, session)
        rows = session.scalars(select(Genre).order_by(Genre.name, Genre.id)).all()
        return [{"id": row.id, "name": row.name} for row in rows]


@app.get("/api/games/igdb-status")
def igdb_status(request: Request) -> dict[str, bool]:
    with _session() as session:
        _current_user(request, session)
    return {
        "configured": bool(
            os.getenv("IGDB_CLIENT_ID", "").strip()
            and os.getenv("IGDB_CLIENT_SECRET", "").strip()
        )
    }


GAME_SEARCH_PAGE_SIZE = 20



GAME_DETAILS_CACHE_DAYS = 30
STORE_DOMAINS = (
    ("steampowered.com", "steam", "Steam"),
    ("epicgames.com", "epic", "Epic Games"),
    ("gog.com", "gog", "GOG"),
    ("itch.io", "itch", "itch.io"),
    ("playstation.com", "playstation", "PlayStation Store"),
    ("xbox.com", "xbox", "Xbox"),
    ("microsoft.com", "xbox", "Microsoft Store"),
    ("nintendo.com", "nintendo", "Nintendo eShop"),
)


def _igdb_details_request(
    endpoint: str, body: str, client_id: str, token: str,
) -> list[dict[str, object]]:
    try:
        response = httpx.post(
            f"https://api.igdb.com/v4/{endpoint}",
            headers={
                "Client-ID": client_id,
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            content=body,
            timeout=10.0,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=502, detail="Не удалось получить дополнительные данные из IGDB.",
        ) from exc
    if not isinstance(payload, list):
        raise HTTPException(status_code=502, detail="IGDB вернул некорректные данные.")
    return [item for item in payload if isinstance(item, dict)]


def _safe_store_links(websites: object) -> list[dict[str, str]]:
    if not isinstance(websites, list):
        return []

    stores: dict[str, dict[str, str]] = {}
    for website in websites:
        if not isinstance(website, dict):
            continue
        raw_url = website.get("url")
        if not isinstance(raw_url, str):
            continue
        try:
            parsed = urlsplit(raw_url)
        except ValueError:
            continue
        if parsed.scheme != "https" or parsed.username or parsed.password:
            continue
        host = (parsed.hostname or "").lower()
        for domain, provider, label in STORE_DOMAINS:
            if host == domain or host.endswith(f".{domain}"):
                stores.setdefault(provider, {
                    "provider": provider, "label": label, "url": raw_url,
                })
                break

    return list(stores.values())[:6]


def _safe_trailer_url(videos: object) -> str | None:
    if not isinstance(videos, list):
        return None
    candidates = [video for video in videos if isinstance(video, dict)]
    candidates.sort(
        key=lambda item: 0 if "trailer" in str(item.get("name") or "").casefold() else 1,
    )
    for candidate in candidates:
        video_id = candidate.get("video_id")
        if isinstance(video_id, str) and re.fullmatch(r"[a-zA-Z0-9_-]{11}", video_id):
            return f"https://www.youtube.com/watch?v={video_id}"
    return None


def _hours_from_igdb(value: object) -> int | None:
    # game_time_to_beats values are in seconds, not minutes.
    try:
        seconds = float(value) if value is not None else 0
    except (TypeError, ValueError):
        return None
    if not math.isfinite(seconds) or seconds <= 0:
        return None
    return max(1, round(seconds / 3600))


def _detail_response(session, game: Game, details: dict[str, object]) -> dict[str, object]:
    # Metadata is cached for 30 days; community scores must always be live.
    ratings = _community_rating_map(session, [game.id])
    return {**details, "game": _game_payload(game, ratings.get(game.id))}


@app.get("/api/games/{game_id}/details")
def game_details(game_id: int, request: Request) -> dict[str, object]:
    with _session() as session:
        _current_user(request, session)
        game = session.scalar(select(Game).where(Game.igdb_id == game_id))
        if game is None:
            raise HTTPException(status_code=404, detail="Игра не найдена в нашей базе.")

        cached_details = (
            json.loads(game.details_json) if game.details_json else None
        )
        if (
            isinstance(cached_details, dict)
            and game.details_cached_at is not None
            and game.details_cached_at.replace(tzinfo=game.details_cached_at.tzinfo or timezone.utc)
                > _now() - timedelta(days=GAME_DETAILS_CACHE_DAYS)
        ):
            if not cached_details.get("_linksOnly"):
                return _detail_response(session, game, cached_details)
            cached_links_fresh = True
        else:
            cached_links_fresh = False

    # Search results already populate the PostgreSQL links cache. For those
    # games, fetch only the missing playtime; for uncached games, query both
    # IGDB endpoints concurrently instead of making the first screen wait for
    # two sequential network round trips.
    try:
        client_id, token = _igdb_access_token()
    except HTTPException:
        if isinstance(cached_details, dict):
            with _session() as session:
                cached_game = session.scalar(select(Game).where(Game.igdb_id == game_id))
                if cached_game is not None:
                    return _detail_response(session, cached_game, cached_details)
        raise

    def fetch_playtime():
        return _igdb_details_request(
            "game_time_to_beats",
            f"fields game_id,hastily,completely; where game_id = {game_id}; limit 1;",
            client_id, token,
        )

    if cached_links_fresh and isinstance(cached_details, dict):
        details: dict[str, object] = dict(cached_details)
        try:
            times = fetch_playtime()
        except HTTPException:
            times = None
    else:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as executor:
            times_future = executor.submit(fetch_playtime)
            try:
                game_rows = _igdb_details_request(
                    "games",
                    f"fields websites.url,videos.name,videos.video_id; where id = {game_id}; limit 1;",
                    client_id, token,
                )
            except HTTPException:
                if isinstance(cached_details, dict):
                    with _session() as session:
                        cached_game = session.scalar(select(Game).where(Game.igdb_id == game_id))
                        if cached_game is not None:
                            return _detail_response(session, cached_game, cached_details)
                raise
            game_row = game_rows[0] if game_rows else {}
            details = {
                "storeLinks": _safe_store_links(game_row.get("websites")),
                "trailerUrl": _safe_trailer_url(game_row.get("videos")),
                "storyHours": None,
                "completionHours": None,
            }
            try:
                times = times_future.result()
            except HTTPException:
                times = None

    if times:
        details["storyHours"] = _hours_from_igdb(times[0].get("hastily"))
        details["completionHours"] = _hours_from_igdb(times[0].get("completely"))
    elif isinstance(cached_details, dict):
        details["storyHours"] = cached_details.get("storyHours")
        details["completionHours"] = cached_details.get("completionHours")
    details["_linksOnly"] = bool(cached_links_fresh and times is None)

    with _session() as session:
        game = session.scalar(select(Game).where(Game.igdb_id == game_id))
        if game is None:
            raise HTTPException(status_code=404, detail="Игра не найдена в нашей базе.")
        game.details_json = json.dumps(details, ensure_ascii=False)
        game.details_cached_at = _now()
        session.commit()
        return _detail_response(session, game, details)


@app.get("/api/games/search")
def search_games(
    request: Request,
    q: str = Query(max_length=100),
    source: Literal["local", "igdb"] = "local",
    offset: int = Query(default=0, ge=0, le=10000),
) -> dict[str, object]:
    query = q.strip()
    if len(query) < 3:
        return {"items": [], "hasMore": False, "nextOffset": None}

    with _session() as session:
        _current_user(request, session)
        if source == "local":
            return _local_game_search(session, query, offset)

    if offset >= 10000:
        return {"items": [], "hasMore": False, "nextOffset": None}

    # External search runs after an empty local search or a manual deep search.
    # Cache the results in PostgreSQL for future local queries.
    client_id, token = _igdb_access_token()

    body = _igdb_search_body(query, offset)

    try:
        response = httpx.post(
            "https://api.igdb.com/v4/games",
            headers={
                "Client-ID": client_id,
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            content=body,
            timeout=12.0,
        )
        if response.status_code == 429:
            raise HTTPException(status_code=429, detail="IGDB занят. Повторите поиск через секунду.")
        response.raise_for_status()
        rows = response.json()
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Не удалось получить игры из IGDB.") from exc

    if not isinstance(rows, list):
        return {"items": [], "hasMore": False, "nextOffset": None}

    # If IGDB's title search misses, its /search index also includes
    # alternative-name records pointing back to the parent game.
    if not rows and offset == 0:
        escaped = json.dumps(query.replace(";", " "), ensure_ascii=False)[1:-1]
        try:
            alias_response = httpx.post(
                "https://api.igdb.com/v4/search",
                headers={
                    "Client-ID": client_id,
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                content=f'fields game,alternative_name,name; search "{escaped}"; where game != null; limit 20;',
                timeout=12.0,
            )
            alias_response.raise_for_status()
            matches = alias_response.json()
            matches = matches if isinstance(matches, list) else []
            ids = list(dict.fromkeys(
                int(item["game"]) for item in matches
                if isinstance(item, dict) and isinstance(item.get("game"), int)
            ))[:20]
            if ids:
                detail_response = httpx.post(
                    "https://api.igdb.com/v4/games",
                    headers={
                        "Client-ID": client_id,
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                    content=(
                        "fields id,name,first_release_date,rating,rating_count,"
                        "total_rating_count,hypes,cover.image_id,alternative_names.name,"
                        "genres.id,genres.name,platforms.name,involved_companies.developer,"
                        "involved_companies.company.name,websites.url,videos.name,videos.video_id; "
                        f"where id = ({','.join(map(str, ids))}) & version_parent = null; limit 20;"
                    ),
                    timeout=12.0,
                )
                detail_response.raise_for_status()
                candidate_rows = detail_response.json()
                if isinstance(candidate_rows, list):
                    rows = candidate_rows
        except (httpx.HTTPError, ValueError):
            # IGDB fallback is best-effort; a failed alias lookup must not
            # make the original (valid) empty search into an API error.
            pass

    has_more = len(rows) > GAME_SEARCH_PAGE_SIZE and offset + GAME_SEARCH_PAGE_SIZE < 10000
    # IGDB first selects textually similar candidates. Within the returned
    # page, prioritize exact titles/aliases and use popularity to break ties.
    # Pagination remains tied to IGDB's offset, not our database.
    normalized = _normalized_search_text(query)

    def page_rank(row: dict[str, object]) -> tuple[int, float]:
        names = [str(row.get("name") or "")]
        names.extend(
            str(alt.get("name") or "") for alt in row.get("alternative_names") or []
            if isinstance(alt, dict)
        )
        names = [_normalized_search_text(name) for name in names]
        exact = int(normalized in names)
        prefix = int(any(name.startswith(normalized) for name in names))
        popularity = math.log1p(max(
            int(row.get("total_rating_count") or 0),
            int(row.get("rating_count") or 0),
        )) + math.log1p(int(row.get("hypes") or 0)) * 0.65
        return (exact * 2 + prefix, popularity)

    page_rows = sorted(rows[:GAME_SEARCH_PAGE_SIZE], key=page_rank, reverse=True)
    cached = _cache_igdb_games(page_rows) if page_rows else []
    return {
        "items": cached,
        "hasMore": has_more,
        "nextOffset": offset + GAME_SEARCH_PAGE_SIZE if has_more else None,
    }


@app.get("/api/collections")
def collections(request: Request) -> list[dict[str, object]]:
    with _session() as session:
        user = _current_user(request, session)
        _ensure_wishlist_collection(session, user.id)
        session.commit()
        return _collections_payload(session, user)


@app.post("/api/collections", status_code=201)
def create_collection(payload: CollectionPayload, request: Request) -> dict[str, object]:
    title = payload.title.strip()
    description = (payload.description or "").strip()
    icon_data = _validated_collection_icon(payload.iconData)

    if not title:
        raise HTTPException(status_code=422, detail="Укажите название коллекции.")

    with _session() as session:
        user = _current_user(request, session)

        for _ in range(5):
            slug = f"c-{secrets.token_hex(4)}"
            if session.scalar(
                select(Collection.id).where(
                    Collection.user_id == user.id,
                    Collection.slug == slug,
                )
            ) is None:
                break
        else:
            raise HTTPException(status_code=500, detail="Не удалось создать коллекцию.")

        collection = Collection(
            user_id=user.id,
            slug=slug,
            title=title,
            description=description or None,
            color_scheme=payload.colorScheme,
            icon_data=icon_data,
            emoji=_validated_collection_emoji(payload.emoji),
        )
        session.add(collection)
        session.commit()

        return {
            "id": collection.slug,
            "title": collection.title,
            "description": collection.description or "",
            "mark": collection.mark or "",
            "colorScheme": collection.color_scheme,
            "iconData": collection.icon_data,
            "emoji": collection.emoji,
            "isSystem": False,
        }



@app.patch("/api/collections/{collection_id}")
def update_collection(collection_id: str, payload: CollectionEditPayload, request: Request) -> dict[str, object]:
    removed = set(payload.removedGameIds)

    with _session() as session:
        user = _current_user(request, session)
        collection = session.scalar(
            select(Collection).where(
                Collection.user_id == user.id,
                Collection.slug == collection_id,
            )
        )
        if collection is None:
            raise HTTPException(status_code=404, detail="Коллекция не найдена.")

        appearance_fields = {"title", "description", "colorScheme", "emoji"}
        requested_appearance = payload.model_fields_set & appearance_fields
        if collection.is_system or collection.slug == WISHLIST_SLUG:
            if requested_appearance:
                raise HTTPException(status_code=403, detail="Системную коллекцию можно редактировать только удаляя игры.")
        else:
            if "title" in requested_appearance:
                title = (payload.title or "").strip()
                if not title:
                    raise HTTPException(status_code=422, detail="Укажите название коллекции.")
                collection.title = title
            if "description" in requested_appearance:
                collection.description = (payload.description or "").strip() or None
            if "colorScheme" in requested_appearance:
                if payload.colorScheme is None:
                    raise HTTPException(status_code=422, detail="Выберите цветовую схему.")
                collection.color_scheme = payload.colorScheme
            if "emoji" in requested_appearance:
                collection.emoji = _validated_collection_emoji(payload.emoji)
                # Previous uploaded icons are superseded by the selected emoji.
                collection.icon_data = None

        if removed:
            member_entries = session.scalars(
                select(UserGame)
                .join(CollectionGame, CollectionGame.user_game_id == UserGame.id)
                .join(Game, Game.id == UserGame.game_id)
                .where(
                    CollectionGame.collection_id == collection.id,
                    UserGame.user_id == user.id,
                    Game.igdb_id.in_(removed),
                )
            ).all()
            member_ids = [entry.id for entry in member_entries]
            if member_ids:
                session.execute(
                    delete(CollectionGame).where(
                        CollectionGame.collection_id == collection.id,
                        CollectionGame.user_game_id.in_(member_ids),
                    )
                )
                session.flush()
                for entry in member_entries:
                    if entry.status in {"wishlist", "untracked"}:
                        other_membership = session.scalar(
                            select(CollectionGame.id)
                            .where(CollectionGame.user_game_id == entry.id)
                            .limit(1)
                        )
                        if other_membership is None:
                            session.delete(entry)

        session.commit()
        return {
            "collection": next(row for row in _collections_payload(session, user) if row["id"] == collection_id),
            "library": _library_payload(session, user),
        }


@app.post("/api/collections/bulk-delete")
def delete_collections_bulk(payload: CollectionBulkDeletePayload, request: Request) -> dict[str, object]:
    ids = payload.ids
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=422, detail="Список коллекций содержит повторы.")

    with _session() as session:
        user = _current_user(request, session)
        selected = session.scalars(
            select(Collection).where(
                Collection.user_id == user.id,
                Collection.slug.in_(ids),
            )
        ).all()
        # Validate all of the user's collections before mutating any.
        if len(selected) != len(ids):
            raise HTTPException(status_code=404, detail="Одна из коллекций не найдена.")
        if any(item.is_system or item.slug == WISHLIST_SLUG for item in selected):
            raise HTTPException(status_code=403, detail="Системную коллекцию удалить нельзя.")

        collection_ids = [item.id for item in selected]
        previous_entries = session.scalars(
            select(UserGame)
            .join(CollectionGame, CollectionGame.user_game_id == UserGame.id)
            .where(
                CollectionGame.collection_id.in_(collection_ids),
                UserGame.user_id == user.id,
            )
        ).unique().all()
        session.execute(
            delete(CollectionGame).where(CollectionGame.collection_id.in_(collection_ids))
        )
        session.flush()
        for entry in previous_entries:
            if entry.status in {"untracked", "wishlist"}:
                remaining = session.scalar(
                    select(CollectionGame.id).where(CollectionGame.user_game_id == entry.id).limit(1)
                )
                if remaining is None:
                    session.delete(entry)
        for collection in selected:
            session.delete(collection)
        session.commit()
        return {"deletedIds": ids, "library": _library_payload(session, user)}


@app.delete("/api/collections/{collection_id}", status_code=204)
def delete_collection(collection_id: str, request: Request) -> Response:
    with _session() as session:
        user = _current_user(request, session)
        collection = session.scalar(
            select(Collection).where(
                Collection.user_id == user.id,
                Collection.slug == collection_id,
            )
        )
        if collection is None:
            raise HTTPException(status_code=404, detail="Коллекция не найдена.")
        if collection.is_system or collection.slug == WISHLIST_SLUG:
            raise HTTPException(status_code=403, detail="Системную коллекцию удалить нельзя.")

        previous_entries = session.scalars(
            select(UserGame)
            .join(CollectionGame, CollectionGame.user_game_id == UserGame.id)
            .where(CollectionGame.collection_id == collection.id, UserGame.user_id == user.id)
        ).all()
        session.execute(
            delete(CollectionGame).where(CollectionGame.collection_id == collection.id)
        )
        session.flush()
        for entry in previous_entries:
            if entry.status in {"untracked", "wishlist"}:
                other_membership = session.scalar(
                    select(CollectionGame.id).where(CollectionGame.user_game_id == entry.id).limit(1)
                )
                if other_membership is None:
                    session.delete(entry)
        session.delete(collection)
        session.commit()
    return Response(status_code=204)


@app.get("/api/export")
def export_user_data(request: Request) -> JSONResponse:
    """Account-scoped portable backup; no credentials or session tokens."""
    with _session() as session:
        user = _current_user(request, session)
        payload = {
            "format": "rateapp-export",
            "schemaVersion": 1,
            "exportedAt": _now().isoformat(),
            "nickname": user.nickname,
            "collections": _collections_payload(session, user),
            "library": _library_payload(session, user),
        }
    return JSONResponse(payload, headers={
        "Content-Disposition": 'attachment; filename="rateapp-export.json"',
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    })


@app.get("/api/library")
def library(request: Request) -> list[dict[str, object]]:
    with _session() as session:
        user = _current_user(request, session)
        return _library_payload(session, user)


@app.put("/api/library/{game_id}")
def upsert_library_game(
    game_id: int,
    payload: LibraryPayload,
    request: Request,
) -> dict[str, object]:
    with _session() as session:
        user = _current_user(request, session)
        game = session.scalar(select(Game).where(Game.igdb_id == game_id))
        if game is None:
            raise HTTPException(status_code=404, detail="Игра пока недоступна в каталоге.")

        entry = session.scalar(
            select(UserGame).where(
                UserGame.user_id == user.id,
                UserGame.game_id == game.id,
            )
        )

        # Only assigning a playthrough status, or switching it to another
        # playthrough status, counts as activity. Rating edits, dates, and
        # collection updates must never bump this timestamp.
        previous_status = entry.status if entry is not None else None
        if entry is None:
            entry = UserGame(user_id=user.id, game_id=game.id, status=payload.status)
            session.add(entry)

        if payload.status in {"completed", "playing", "dropped"}:
            if previous_status != payload.status:
                entry.status_changed_at = _now()
        else:
            entry.status_changed_at = None

        entry.status = payload.status
        entry.platform = None if payload.status == "wishlist" else payload.platform
        entry.completed_at = payload.completedAt if payload.status in {"completed", "dropped"} else None
        entry.started_at = payload.startedAt if payload.status == "playing" else None
        if payload.status in {"completed", "dropped"}:
            criteria = [
                payload.atmosphereScore,
                payload.storyScore,
                payload.technologyScore,
                payload.gameplayScore,
            ]
            rounded_criteria = [
                round(value, 1) if value is not None else None
                for value in criteria
            ]
            (
                entry.atmosphere_score,
                entry.story_score,
                entry.technology_score,
                entry.gameplay_score,
            ) = rounded_criteria

            # PostgreSQL ROUND(numeric, 1) uses half-up; keep the API identical.
            from decimal import Decimal, ROUND_HALF_UP
            entry.score = sum(
                Decimal(str(value)) for value in rounded_criteria if value is not None
            ).__truediv__(Decimal("4")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        else:
            entry.score = None
            entry.atmosphere_score = None
            entry.story_score = None
            entry.technology_score = None
            entry.gameplay_score = None

        entry.review = payload.review if payload.status in {"completed", "dropped"} else None

        session.flush()
        existing_membership_dates = dict(session.execute(
            select(CollectionGame.collection_id, CollectionGame.added_at)
            .where(CollectionGame.user_game_id == entry.id)
        ).all())
        selected_slugs = set(payload.collectionIds)
        if payload.status == "wishlist":
            _ensure_wishlist_collection(session, user.id)
            selected_slugs.add(WISHLIST_SLUG)

        selected_collections = session.scalars(
            select(Collection).where(
                Collection.user_id == user.id,
                Collection.slug.in_(selected_slugs),
            )
        ).all() if selected_slugs else []
        selected_ids = {collection.id for collection in selected_collections}
        existing_ids = set(existing_membership_dates)
        to_remove = existing_ids - selected_ids
        to_add = selected_ids - existing_ids
        # Leave unchanged rows (including their original added_at) untouched.
        # Recreating the entire membership set on every rating edit causes
        # unnecessary DELETE/INSERT churn and can race with other updates.
        if to_remove:
            session.execute(delete(CollectionGame).where(
                CollectionGame.user_game_id == entry.id,
                CollectionGame.collection_id.in_(to_remove),
            ))
        if to_add:
            session.add_all(
                CollectionGame(collection_id=collection_id, user_game_id=entry.id)
                for collection_id in to_add
            )

        session.commit()
        session.refresh(entry)
        return _serialize_entry(
            session, entry,
            community_rating=_community_rating_map(session, [game.id]).get(game.id),
        )


def _set_collection_membership(game_id: int, collection_id: str, request: Request, enabled: bool) -> dict[str, object]:
    """Idempotent membership update; never delete an existing playthrough."""
    with _session() as session:
        user = _current_user(request, session)
        collection = session.scalar(
            select(Collection).where(
                Collection.user_id == user.id,
                Collection.slug == collection_id,
            )
        )
        if collection is None:
            raise HTTPException(status_code=404, detail="Коллекция не найдена.")

        game = session.scalar(select(Game).where(Game.igdb_id == game_id))
        if game is None:
            raise HTTPException(status_code=404, detail="Игра пока недоступна в каталоге.")

        entry = session.scalar(
            select(UserGame).where(
                UserGame.user_id == user.id,
                UserGame.game_id == game.id,
            )
        )
        if enabled:
            if entry is None:
                entry = UserGame(user_id=user.id, game_id=game.id, status="untracked")
                session.add(entry)
                session.flush()

            already_added = session.scalar(
                select(CollectionGame.id).where(
                    CollectionGame.collection_id == collection.id,
                    CollectionGame.user_game_id == entry.id,
                )
            )
            if already_added is None:
                session.add(CollectionGame(
                    collection_id=collection.id,
                    user_game_id=entry.id,
                ))
        elif entry is not None:
            session.execute(
                delete(CollectionGame).where(
                    CollectionGame.collection_id == collection.id,
                    CollectionGame.user_game_id == entry.id,
                )
            )
            session.flush()
            if entry.status in {"wishlist", "untracked"}:
                remaining = session.scalar(
                    select(CollectionGame.id)
                    .where(CollectionGame.user_game_id == entry.id)
                    .limit(1)
                )
                if remaining is None:
                    session.delete(entry)
                    entry = None
                else:
                    entry.status = "untracked"

        session.commit()
        if entry is None:
            return {"inCollection": enabled, "entry": None}
        session.refresh(entry)
        return {
            "inCollection": enabled,
            "entry": _serialize_entry(
                session, entry,
                community_rating=_community_rating_map(session, [game.id]).get(game.id),
            ),
        }


@app.put("/api/library/{game_id}/collections/{collection_id}")
def add_game_to_collection(game_id: int, collection_id: str, request: Request) -> dict[str, object]:
    return _set_collection_membership(game_id, collection_id, request, True)


@app.delete("/api/library/{game_id}/collections/{collection_id}")
def remove_game_from_collection(game_id: int, collection_id: str, request: Request) -> dict[str, object]:
    return _set_collection_membership(game_id, collection_id, request, False)


@app.put("/api/library/{game_id}/wishlist")
def add_game_to_wishlist(game_id: int, request: Request) -> dict[str, object]:
    with _session() as session:
        user = _current_user(request, session)
        game = session.scalar(select(Game).where(Game.igdb_id == game_id))
        if game is None:
            raise HTTPException(status_code=404, detail="Игра пока недоступна в каталоге.")

        collection = _ensure_wishlist_collection(session, user.id)
        entry = session.scalar(
            select(UserGame).where(
                UserGame.user_id == user.id,
                UserGame.game_id == game.id,
            )
        )
        if entry is None:
            entry = UserGame(user_id=user.id, game_id=game.id, status="untracked")
            session.add(entry)
            session.flush()

        already_added = session.scalar(
            select(CollectionGame.id).where(
                CollectionGame.collection_id == collection.id,
                CollectionGame.user_game_id == entry.id,
            )
        )
        if already_added is None:
            session.add(CollectionGame(
                collection_id=collection.id,
                user_game_id=entry.id,
            ))
        session.commit()
        session.refresh(entry)
        return {
            "inWishlist": True,
            "entry": _serialize_entry(
                session, entry,
                community_rating=_community_rating_map(session, [game.id]).get(game.id),
            ),
        }



@app.delete("/api/library/{game_id}/wishlist")
def remove_game_from_wishlist(game_id: int, request: Request) -> dict[str, object]:
    with _session() as session:
        user = _current_user(request, session)
        game = session.scalar(select(Game).where(Game.igdb_id == game_id))
        if game is None:
            raise HTTPException(status_code=404, detail="Игра пока недоступна в каталоге.")
        collection = _ensure_wishlist_collection(session, user.id)
        entry = session.scalar(
            select(UserGame).where(
                UserGame.user_id == user.id,
                UserGame.game_id == game.id,
            )
        )
        if entry is None:
            session.commit()
            return {"inWishlist": False, "entry": None}

        session.execute(
            delete(CollectionGame).where(
                CollectionGame.collection_id == collection.id,
                CollectionGame.user_game_id == entry.id,
            )
        )
        other_memberships = session.scalar(
            select(CollectionGame.id).where(CollectionGame.user_game_id == entry.id).limit(1)
        )

        # A collection-only record can be removed when it has no memberships.
        if entry.status in {"wishlist", "untracked"}:
            if other_memberships is None:
                session.delete(entry)
                session.commit()
                return {"inWishlist": False, "entry": None}
            # Old wishlist placeholders that remain in other collections are not wishes.
            entry.status = "untracked"

        session.commit()
        session.refresh(entry)
        return {
            "inWishlist": False,
            "entry": _serialize_entry(
                session, entry,
                community_rating=_community_rating_map(session, [game.id]).get(game.id),
            ),
        }


@app.delete("/api/library/{game_id}", status_code=204)
def delete_library_game(game_id: int, request: Request) -> Response:
    with _session() as session:
        user = _current_user(request, session)
        game = session.scalar(select(Game).where(Game.igdb_id == game_id))
        if game is None:
            return Response(status_code=204)

        entry = session.scalar(
            select(UserGame).where(
                UserGame.user_id == user.id,
                UserGame.game_id == game.id,
            )
        )
        if entry is not None and entry.status in {"completed", "playing", "dropped"}:
            has_collections = session.scalar(
                select(CollectionGame.id)
                .where(CollectionGame.user_game_id == entry.id)
                .limit(1)
            ) is not None
            if has_collections:
                # Delete the playthrough only, never its collection memberships.
                entry.status = "untracked"
                entry.status_changed_at = None
                entry.platform = None
                entry.completed_at = None
                entry.started_at = None
                entry.score = None
                entry.atmosphere_score = None
                entry.story_score = None
                entry.technology_score = None
                entry.gameplay_score = None
                entry.review = None
            else:
                session.delete(entry)
            session.commit()

    return Response(status_code=204)


def _push_key() -> str:
    key = os.getenv("VAPID_PUBLIC_KEY", "").strip()
    if not push_ready() or not key:
        raise HTTPException(status_code=503, detail="Уведомления ещё не настроены.")
    return key


@app.get("/api/push/config")
def push_config(request: Request) -> dict[str, object]:
    with _session() as session:
        user = _current_user(request, session)
        active = session.scalar(
            select(func.count(PushSubscription.id)).where(PushSubscription.user_id == user.id)
        ) or 0
    return {"enabled": push_ready(), "publicKey": os.getenv("VAPID_PUBLIC_KEY", "") if push_ready() else "",
            "devices": active}


@app.put("/api/push/subscription")
def save_push_subscription(payload: PushSubscriptionPayload, request: Request) -> dict[str, bool]:
    _push_key()
    if not valid_push_endpoint(payload.endpoint):
        raise HTTPException(status_code=422, detail="Адрес сервиса уведомлений не поддерживается.")
    p256dh = payload.keys.get("p256dh", "")
    auth = payload.keys.get("auth", "")
    if not (
        re.fullmatch(r"[A-Za-z0-9_-]{60,160}", p256dh)
        and re.fullmatch(r"[A-Za-z0-9_-]{16,80}", auth)
    ):
        raise HTTPException(status_code=422, detail="Некорректные ключи Web Push.")

    endpoint_hash = hashlib.sha256(payload.endpoint.encode("utf-8")).hexdigest()
    with _session() as session:
        user = _current_user(request, session)
        existing = session.scalar(
            select(PushSubscription).where(PushSubscription.endpoint_hash == endpoint_hash)
        )
        if existing is None:
            session.add(PushSubscription(
                user_id=user.id, endpoint=payload.endpoint,
                endpoint_hash=endpoint_hash, p256dh=p256dh, auth=auth,
            ))
        else:
            # A browser subscription belongs to the actively signed-in account.
            existing.user_id = user.id
            existing.endpoint = payload.endpoint
            existing.p256dh = p256dh
            existing.auth = auth
        session.commit()
    return {"subscribed": True}


@app.delete("/api/push/subscription")
def delete_push_subscription(payload: PushSubscriptionPayload, request: Request) -> dict[str, bool]:
    with _session() as session:
        user = _current_user(request, session)
        digest = hashlib.sha256(payload.endpoint.encode("utf-8")).hexdigest()
        session.execute(
            delete(PushSubscription).where(
                PushSubscription.endpoint_hash == digest,
                PushSubscription.user_id == user.id,
            )
        )
        session.commit()
    return {"subscribed": False}


def _wishlist_game(session, user_id: int, igdb_id: int) -> Game | None:
    return session.scalar(
        select(Game)
        .join(UserGame, UserGame.game_id == Game.id)
        .join(CollectionGame, CollectionGame.user_game_id == UserGame.id)
        .join(Collection, Collection.id == CollectionGame.collection_id)
        .where(
            UserGame.user_id == user_id,
            Collection.user_id == user_id,
            Collection.slug == WISHLIST_SLUG,
            Game.igdb_id == igdb_id,
        )
    )


@app.post("/api/push/test")
def test_release_push(payload: PushTestPayload, request: Request) -> dict[str, object]:
    _push_key()
    with _session() as session:
        user = _current_user(request, session)
        game = _wishlist_game(session, user.id, payload.gameId)
        if game is None:
            raise HTTPException(status_code=404, detail="Игра не найдена в вашем «Хочу поиграть».")

        subs = session.scalars(
            select(PushSubscription).where(PushSubscription.user_id == user.id)
        ).all()
        if not subs:
            raise HTTPException(
                status_code=409,
                detail="Сначала разрешите уведомления на вашем устройстве.",
            )

        latest = max((sub.last_test_at for sub in subs if sub.last_test_at), default=None)
        if latest and latest.replace(tzinfo=latest.tzinfo or timezone.utc) > _now() - timedelta(seconds=30):
            raise HTTPException(status_code=429, detail="Повторить тест можно через 30 секунд.")

        accepted = 0
        for sub in subs:
            ok, expired = send_push(
                sub,
                title=f"Вышла {game.title}!",
                body="Ты хотел поиграть - играй :)",
                game_id=game.igdb_id,
                tag=f"test-release-{game.igdb_id}",
                cover_url=game.cover_url,
            )
            if expired:
                session.delete(sub)
            elif ok:
                accepted += 1
                sub.last_test_at = _now()
        session.commit()
        if not accepted:
            raise HTTPException(status_code=502, detail="Push-сервис не принял уведомление. Проверьте настройки устройства.")
        return {"accepted": accepted, "game": game.title}


@app.get("/api/cron/release-alerts")
def release_alert_cron(request: Request) -> dict[str, object]:
    """Daily release-date scan. Cron secret is supplied by Vercel as Bearer."""
    secret = os.getenv("CRON_SECRET", "")
    provided = request.headers.get("authorization", "")
    if not secret or not secrets.compare_digest(provided, f"Bearer {secret}"):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not push_ready():
        raise HTTPException(status_code=503, detail="Web Push is not configured")

    today = _now().date()
    accepted = 0
    failed = 0
    with _session() as session:
        # Actual membership in the system collection is the source of truth,
        # not UserGame.status: a user may put an already saved game on their list.
        rows = session.execute(
            select(PushSubscription, Game)
            .join(UserGame, UserGame.user_id == PushSubscription.user_id)
            .join(Game, Game.id == UserGame.game_id)
            .join(CollectionGame, CollectionGame.user_game_id == UserGame.id)
            .join(Collection, Collection.id == CollectionGame.collection_id)
            .where(
                Collection.user_id == PushSubscription.user_id,
                Collection.slug == WISHLIST_SLUG,
                Game.release_date == today,
            )
            .order_by(PushSubscription.id, Game.id)
        ).all()

        for sub, game in rows:
            already_sent = session.scalar(
                select(ReleasePushDelivery.id).where(
                    ReleasePushDelivery.subscription_id == sub.id,
                    ReleasePushDelivery.game_id == game.id,
                    ReleasePushDelivery.release_date == today,
                )
            )
            if already_sent:
                continue
            ok, expired = send_push(
                sub,
                title=f"Вышла {game.title}!",
                body="Ты хотел поиграть - играй :)",
                game_id=game.igdb_id,
                tag=f"release-{game.igdb_id}-{today.isoformat()}",
                cover_url=game.cover_url,
            )
            if expired:
                session.delete(sub)
            elif ok:
                accepted += 1
                session.add(ReleasePushDelivery(
                    subscription_id=sub.id, game_id=game.id, release_date=today,
                ))
            else:
                failed += 1
            # Persist delivery receipts even if a later push fails or times out.
            session.commit()

    return {"date": today.isoformat(), "accepted": accepted, "failed": failed}
