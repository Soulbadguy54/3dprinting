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
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import case, delete, func, or_, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from api.bootstrap import initialize_database
from api.database import SessionLocal, engine
from api.models import (
    AuthSession,
    Collection,
    CollectionGame,
    Game,
    LoginThrottle,
    User,
    UserGame,
)

app = FastAPI(
    title="RateApp API",
    version="0.3.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

initialize_database()

PIN_RE = re.compile(r"^\d{4,8}$")
NICK_RE = re.compile(r"^[a-z0-9_]{3,24}$")
SESSION_COOKIE = "rateapp_session"
SESSION_DAYS = 30
MAX_LOGIN_FAILURES = 5
LOCK_MINUTES = 15
password_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
_igdb_token: str | None = None
_igdb_token_expires_at = 0.0


class RegisterPayload(BaseModel):
    email: EmailStr
    nickname: str = Field(min_length=3, max_length=24)
    pin: str = Field(min_length=4, max_length=8)


class LoginPayload(BaseModel):
    identifier: str = Field(min_length=3, max_length=320)
    pin: str = Field(min_length=4, max_length=8)


class CollectionPayload(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    mark: str | None = Field(default=None, max_length=8)


class LibraryPayload(BaseModel):
    gameId: int | None = None
    status: Literal["completed", "playing", "wishlist", "dropped"]
    platform: str | None = None
    completedAt: date | None = None
    startedAt: date | None = None
    score: float | None = Field(default=None, ge=1, le=10)
    atmosphereScore: float | None = Field(default=None, ge=1, le=10)
    storyScore: float | None = Field(default=None, ge=1, le=10)
    technologyScore: float | None = Field(default=None, ge=1, le=10)
    gameplayScore: float | None = Field(default=None, ge=1, le=10)
    review: str | None = Field(default=None, max_length=5000)
    collectionIds: list[str] = Field(default_factory=list)
    addedAt: date | None = None


def _session():
    if SessionLocal is None:
        raise HTTPException(status_code=503, detail="Database is not configured")
    return SessionLocal()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=os.getenv("VERCEL_ENV") != "development",
        samesite="lax",
        path="/",
    )


def _user_payload(user: User) -> dict[str, object]:
    return {
        "id": user.id,
        "email": user.email,
        "nickname": user.nickname,
        "createdAt": user.created_at.isoformat(),
        "public": True,
    }


def _create_session(session, user: User, response: Response) -> None:
    token = secrets.token_urlsafe(32)
    session.add(
        AuthSession(
            user_id=user.id,
            token_hash=_hash_token(token),
            expires_at=_now() + timedelta(days=SESSION_DAYS),
        )
    )
    session.commit()
    _set_session_cookie(response, token)


def _current_user(request: Request, session) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    row = session.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == _hash_token(token),
            AuthSession.expires_at > _now(),
        )
    )
    if row is None:
        raise HTTPException(status_code=401, detail="Session expired")

    user = session.get(User, row.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _check_throttle(session, identifier: str) -> None:
    row = session.get(LoginThrottle, identifier)
    if row is None or row.locked_until is None:
        return
    if row.locked_until > _now():
        raise HTTPException(status_code=429, detail="Слишком много попыток. Попробуйте через 15 минут.")
    session.delete(row)
    session.commit()


def _record_login_failure(session, identifier: str) -> None:
    row = session.get(LoginThrottle, identifier)
    if row is None:
        row = LoginThrottle(identifier=identifier, failures=0)
        session.add(row)

    row.failures += 1
    if row.failures >= MAX_LOGIN_FAILURES:
        row.failures = 0
        row.locked_until = _now() + timedelta(minutes=LOCK_MINUTES)
    session.commit()


def _clear_throttle(session, identifier: str) -> None:
    row = session.get(LoginThrottle, identifier)
    if row is not None:
        session.delete(row)
        session.commit()


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


def _game_payload(game: Game) -> dict[str, object]:
    release_date = game.release_date.isoformat() if game.release_date else ""
    genres = json.loads(game.genres_json) if game.genres_json else []
    platforms = json.loads(game.platforms_json) if game.platforms_json else []
    title_parts = [part for part in re.split(r"\\s+", game.title.strip()) if part]
    glyph = "".join(part[0].upper() for part in title_parts[:2]) or "G"

    return {
        "id": game.igdb_id,
        "title": game.title,
        "genres": genres,
        "year": game.release_date.year if game.release_date else 0,
        "releaseDate": release_date,
        "developer": game.developer or "—",
        "platforms": platforms,
        "igdbRating": round(float(game.igdb_rating or 0)),
        "communityRating": 0,
        "communityRatings": 0,
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
            game.cover_url = _igdb_cover(str(image_id)) if image_id else None
            game.developer = developers[0] if developers else None
            game.genres_json = json.dumps(genres, ensure_ascii=False)
            game.platforms_json = json.dumps(platforms, ensure_ascii=False)

            cached_games.append(game)

        session.flush()
        cached = [_game_payload(game) for game in cached_games]
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
) -> dict[str, object]:
    return {
        "gameId": entry.game.igdb_id,
        "status": entry.status,
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
        "addedAt": entry.added_at.date().isoformat(),
        "game": _game_payload(entry.game),
    }


def _collections_payload(session, user: User) -> list[dict[str, object]]:
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


def _library_payload(session, user: User) -> list[dict[str, object]]:
    rows = session.scalars(
        select(UserGame)
        .where(UserGame.user_id == user.id)
        .order_by(UserGame.added_at.desc())
    ).all()

    memberships: dict[int, list[str]] = {row.id: [] for row in rows}
    if rows:
        pairs = session.execute(
            select(CollectionGame.user_game_id, Collection.slug)
            .join(Collection, Collection.id == CollectionGame.collection_id)
            .where(CollectionGame.user_game_id.in_([row.id for row in rows]))
            .order_by(CollectionGame.user_game_id, Collection.id)
        ).all()
        for user_game_id, slug in pairs:
            memberships.setdefault(user_game_id, []).append(slug)

    return [
        _serialize_entry(session, row, memberships.get(row.id, []))
        for row in rows
    ]


def _normalized_search_text(value: str) -> str:
    return re.sub(r"[^\w]+", " ", value.casefold(), flags=re.UNICODE).strip()


def _igdb_search_rank(row: dict[str, object], query: str) -> float:
    query_text = _normalized_search_text(query)
    name_text = _normalized_search_text(str(row.get("name") or ""))
    score = 0.0

    # IGDB already returns textually similar candidates. Inside that set,
    # popularity is a stronger signal of what the user probably meant.
    if name_text == query_text:
        score += 45_000
    elif name_text.startswith(query_text):
        score += 30_000
    elif query_text and query_text in name_text:
        score += 15_000
    elif query_text and all(token in name_text for token in query_text.split()):
        score += 8_000

    ratings = max(
        int(row.get("total_rating_count") or 0),
        int(row.get("rating_count") or 0),
    )
    hypes = int(row.get("hypes") or 0)
    rating = float(row.get("rating") or 0)

    # IGDB already sorted candidates by total_rating_count in the query.
    # Keep popularity dominant; use quality/hype/text only as tie-breakers.
    score += math.log1p(ratings) * 100_000
    score += rating * 250
    score += math.log1p(hypes) * 5_000
    return score


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
        "database": {"configured": database_configured, "reachable": database_ok},
        "igdb": {
            "configured": bool(
                os.getenv("IGDB_CLIENT_ID", "").strip()
                and os.getenv("IGDB_CLIENT_SECRET", "").strip()
            )
        },
        "environment": os.getenv("VERCEL_ENV", "local"),
    }


@app.get("/api")
def api_root() -> dict[str, str]:
    return {"name": "RateApp API", "status": "ok", "docs": "/api/docs"}


@app.post("/api/auth/register", status_code=201)
def register(payload: RegisterPayload, response: Response) -> dict[str, object]:
    email = str(payload.email).strip().lower()
    nickname = payload.nickname.strip().lower()
    pin = payload.pin.strip()

    if not NICK_RE.fullmatch(nickname):
        raise HTTPException(
            status_code=422,
            detail="Ник: 3–24 символа, только латиница, цифры и _.",
        )
    if not PIN_RE.fullmatch(pin):
        raise HTTPException(status_code=422, detail="PIN должен содержать 4–8 цифр.")

    with _session() as session:
        conflict = session.scalar(
            select(User).where(or_(User.email == email, User.nickname == nickname))
        )
        if conflict is not None:
            if conflict.email == email:
                raise HTTPException(status_code=409, detail="Этот email уже зарегистрирован.")
            raise HTTPException(status_code=409, detail="Этот ник уже занят.")

        user = User(
            email=email,
            nickname=nickname,
            pin_hash=password_hasher.hash(pin),
        )
        session.add(user)
        try:
            session.flush()
            _create_session(session, user, response)
        except IntegrityError:
            session.rollback()
            raise HTTPException(status_code=409, detail="Email или ник уже используются.")

        return _user_payload(user)


@app.post("/api/auth/login")
def login(payload: LoginPayload, response: Response) -> dict[str, object]:
    print("[auth] login request received", flush=True)
    identifier = payload.identifier.strip().lower()
    pin = payload.pin.strip()

    if not PIN_RE.fullmatch(pin):
        raise HTTPException(status_code=401, detail="Неверный email/ник или PIN.")

    with _session() as session:
        _check_throttle(session, identifier)
        user = session.scalar(
            select(User).where(or_(User.email == identifier, User.nickname == identifier))
        )

        verified = False
        if user is not None:
            try:
                verified = password_hasher.verify(user.pin_hash, pin)
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                verified = False

        if not verified or user is None:
            print("[auth] login rejected", flush=True)
            _record_login_failure(session, identifier)
            raise HTTPException(status_code=401, detail="Неверный email/ник или PIN.")

        _clear_throttle(session, identifier)
        if password_hasher.check_needs_rehash(user.pin_hash):
            user.pin_hash = password_hasher.hash(pin)
            session.commit()

        _create_session(session, user, response)
        print("[auth] login succeeded", flush=True)
        return _user_payload(user)


@app.post("/api/auth/logout", status_code=204)
def logout(request: Request, response: Response) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with _session() as session:
            session.execute(
                delete(AuthSession).where(AuthSession.token_hash == _hash_token(token))
            )
            session.commit()

    response.delete_cookie(SESSION_COOKIE, path="/")
    response.status_code = 204
    return response


@app.get("/api/auth/me")
def auth_me(request: Request) -> dict[str, object]:
    with _session() as session:
        return _user_payload(_current_user(request, session))


@app.get("/api/profile")
def profile(request: Request) -> dict[str, object]:
    with _session() as session:
        return _user_payload(_current_user(request, session))


@app.get("/api/bootstrap")
def bootstrap(request: Request) -> dict[str, object]:
    with _session() as session:
        user = _current_user(request, session)
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

        total = session.scalar(select(func.count(UserGame.id)).where(UserGame.user_id == user.id)) or 0
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
            select(func.count(UserGame.id)).where(
                UserGame.user_id == user.id,
                UserGame.status == "wishlist",
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
            return cached_details

    try:
        client_id, token = _igdb_access_token()
        game_rows = _igdb_details_request(
            "games",
            f"fields websites.url,videos.name,videos.video_id; where id = {game_id}; limit 1;",
            client_id, token,
        )
    except HTTPException:
        if isinstance(cached_details, dict):
            return cached_details
        raise

    game_row = game_rows[0] if game_rows else {}
    details: dict[str, object] = {
        "storeLinks": _safe_store_links(game_row.get("websites")),
        "trailerUrl": _safe_trailer_url(game_row.get("videos")),
        "storyHours": None,
        "completionHours": None,
    }

    # Time-to-beat data isn't available for every game. A failure to fetch it
    # must never prevent the store links / trailer from being shown.
    try:
        times = _igdb_details_request(
            "game_time_to_beats",
            f"fields game_id,hastily,completely; where game_id = {game_id}; limit 1;",
            client_id, token,
        )
        if times:
            details["storyHours"] = _hours_from_igdb(times[0].get("hastily"))
            details["completionHours"] = _hours_from_igdb(times[0].get("completely"))
    except HTTPException:
        if isinstance(cached_details, dict):
            details["storyHours"] = cached_details.get("storyHours")
            details["completionHours"] = cached_details.get("completionHours")

    with _session() as session:
        game = session.scalar(select(Game).where(Game.igdb_id == game_id))
        if game is not None:
            game.details_json = json.dumps(details, ensure_ascii=False)
            game.details_cached_at = _now()
            session.commit()

    return details


@app.get("/api/games/search")
def search_games(
    q: str,
    request: Request,
    source: Literal["local", "igdb"] = "local",
    offset: int = Query(default=0, ge=0, le=10000),
) -> dict[str, object]:
    query = q.strip()
    if len(query) < 3:
        return {"items": [], "hasMore": False, "nextOffset": None}

    query_tokens = [
        token
        for token in _normalized_search_text(query).split()
        if len(token) >= 2
    ]
    if not query_tokens:
        return {"items": [], "hasMore": False, "nextOffset": None}

    # The normal search never contacts IGDB: it searches the persistent,
    # shared games catalogue that earlier IGDB requests have already filled.
    # Wildcards must be escaped so a title search is always a literal search.
    with _session() as session:
        _current_user(request, session)
        if source == "local":
            def literal_like(value: str) -> str:
                return (
                    value.replace("\\", "\\\\")
                    .replace("%", "\\%")
                    .replace("_", "\\_")
                )

            matches = [
                Game.title.ilike(f"%{literal_like(token)}%", escape="\\")
                for token in query_tokens[:6]
            ]
            exact = literal_like(query)
            rows = session.scalars(
                select(Game)
                .where(*matches)
                .order_by(
                    case(
                        (Game.title.ilike(exact, escape="\\"), 0),
                        (Game.title.ilike(f"{exact}%", escape="\\"), 1),
                        else_=2,
                    ),
                    func.length(Game.title),
                    Game.title,
                )
                .offset(offset)
                .limit(GAME_SEARCH_PAGE_SIZE + 1)
            ).all()
            has_more = len(rows) > GAME_SEARCH_PAGE_SIZE
            return {
                "items": [_game_payload(game) for game in rows[:GAME_SEARCH_PAGE_SIZE]],
                "hasMore": has_more,
                "nextOffset": offset + GAME_SEARCH_PAGE_SIZE if has_more else None,
            }

    if offset >= 10000:
        return {"items": [], "hasMore": False, "nextOffset": None}

    # Only an explicit user action triggers this external request. The
    # returned games are written to PostgreSQL and shared by later searches.
    client_id, token = _igdb_access_token()

    escaped_tokens = [
        token.replace("\\", "\\\\").replace('"', '\\"')
        for token in query_tokens[:6]
    ]
    name_filters = " & ".join(
        f'name ~ *"{token}"*'
        for token in escaped_tokens
    )

    body = (
        "fields id,name,game_type,first_release_date,rating,rating_count,"
        "total_rating_count,hypes,cover.image_id,"
        "genres.name,platforms.name,involved_companies.developer,"
        "involved_companies.company.name; "
        f"where {name_filters} & version_parent = null; "
        "sort total_rating_count desc; "
        f"limit {GAME_SEARCH_PAGE_SIZE + 1}; "
        f"offset {offset};"
    )

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

    has_more = len(rows) > GAME_SEARCH_PAGE_SIZE and offset + GAME_SEARCH_PAGE_SIZE < 10000
    # IGDB's popularity sort gives a stable page order. Persist the complete
    # displayed page before responding, making it searchable by future users.
    page_rows = rows[:GAME_SEARCH_PAGE_SIZE]
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
        return _collections_payload(session, user)


@app.post("/api/collections", status_code=201)
def create_collection(payload: CollectionPayload, request: Request) -> dict[str, object]:
    title = payload.title.strip()
    description = (payload.description or "").strip()
    mark = (payload.mark or "").strip().upper()

    if not title:
        raise HTTPException(status_code=422, detail="Укажите название коллекции.")

    if not mark:
        mark = "".join(part[0] for part in title.split()[:2]).upper()[:3] or "★"

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
            mark=mark[:8],
        )
        session.add(collection)
        session.commit()

        return {
            "id": collection.slug,
            "title": collection.title,
            "description": collection.description or "",
            "mark": collection.mark or "",
        }


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

        if entry is None:
            entry = UserGame(user_id=user.id, game_id=game.id, status=payload.status)
            session.add(entry)

        entry.status = payload.status
        entry.platform = None if payload.status == "wishlist" else payload.platform
        entry.completed_at = payload.completedAt if payload.status == "completed" else None
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

            if all(value is not None for value in rounded_criteria):
                entry.score = round(
                    sum(value for value in rounded_criteria if value is not None) / 4,
                    1,
                )
            else:
                entry.score = round(payload.score, 1) if payload.score is not None else None
        else:
            entry.score = None
            entry.atmosphere_score = None
            entry.story_score = None
            entry.technology_score = None
            entry.gameplay_score = None

        entry.review = payload.review

        session.flush()
        session.execute(delete(CollectionGame).where(CollectionGame.user_game_id == entry.id))

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
        if entry is not None:
            session.execute(
                delete(CollectionGame).where(CollectionGame.user_game_id == entry.id)
            )
            session.delete(entry)
            session.commit()

    return Response(status_code=204)
