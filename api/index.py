import hashlib
import os
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Literal

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
        "database": {"configured": database_configured, "reachable": database_ok},
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


@app.get("/api/collections")
def collections(request: Request) -> list[dict[str, object]]:
    with _session() as session:
        user = _current_user(request, session)
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
def library(request: Request) -> list[dict[str, object]]:
    with _session() as session:
        user = _current_user(request, session)
        rows = session.scalars(
            select(UserGame)
            .where(UserGame.user_id == user.id)
            .order_by(UserGame.added_at.desc())
        ).all()
        return [_serialize_entry(session, row) for row in rows]


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
