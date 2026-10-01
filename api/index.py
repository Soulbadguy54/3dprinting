import hashlib
import json
import math
import os
import re
import secrets
import time
from datetime import date, datetime, timedelta, timezone
from typing import Literal

import httpx
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, func, or_, select, text
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
        cached: list[dict[str, object]] = []

        for row in rows:
            igdb_id = int(row["id"])
            game = session.scalar(select(Game).where(Game.igdb_id == igdb_id))
            if game is None:
                game = Game(igdb_id=igdb_id, title=str(row.get("name") or "Unknown"))
                session.add(game)

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

            session.flush()
            cached.append(_game_payload(game))

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

    if name_text == query_text:
        score += 1_000_000
    elif name_text.startswith(query_text):
        score += 300_000
    elif query_text and query_text in name_text:
        score += 150_000
    elif query_text and all(token in name_text for token in query_text.split()):
        score += 80_000

    category = int(row.get("category") or 0)
    if category in {0, 4, 8, 9, 10, 11}:
        score += 60_000
    elif category in {1, 2, 3, 5, 6, 7, 13, 14}:
        score -= 100_000

    ratings = int(row.get("total_rating_count") or row.get("rating_count") or 0)
    hypes = int(row.get("hypes") or 0)
    score += math.log1p(ratings) * 12_000
    score += math.log1p(hypes) * 4_000
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
            _record_login_failure(session, identifier)
            raise HTTPException(status_code=401, detail="Неверный email/ник или PIN.")

        _clear_throttle(session, identifier)
        if password_hasher.check_needs_rehash(user.pin_hash):
            user.pin_hash = password_hasher.hash(pin)
            session.commit()

        _create_session(session, user, response)
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

        return {
            "nickname": user.nickname,
            "public": True,
            "stats": {
                "total": total,
                "completed": completed,
                "playing": playing,
                "wishlist": wishlist,
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


@app.get("/api/games/search")
def search_games(q: str, request: Request) -> list[dict[str, object]]:
    query = q.strip()
    if len(query) < 3:
        return []

    with _session() as session:
        _current_user(request, session)

    client_id, token = _igdb_access_token()
    safe_query = query.replace("\\", "\\\\").replace('"', '\\"')
    body = (
        f'search "{safe_query}"; '
        "fields id,name,category,first_release_date,rating,rating_count,"
        "total_rating_count,hypes,cover.image_id,"
        "genres.name,platforms.name,involved_companies.developer,"
        "involved_companies.company.name; "
        "where version_parent = null; "
        "limit 50;"
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
        return []

    ranked_rows = sorted(
        rows,
        key=lambda row: _igdb_search_rank(row, query),
        reverse=True,
    )[:20]
    return _cache_igdb_games(ranked_rows)


@app.get("/api/collections")
def collections(request: Request) -> list[dict[str, object]]:
    with _session() as session:
        user = _current_user(request, session)
        return _collections_payload(session, user)


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
        entry.score = payload.score if payload.status == "completed" else None
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
            session.delete(entry)
            session.commit()

    return Response(status_code=204)
