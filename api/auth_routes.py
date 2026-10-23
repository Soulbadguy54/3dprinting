"""Auth/profile HTTP routes, separate from games and collections routes."""
import os
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError

from api.models import User, AuthSession
from api.collections_service import _ensure_wishlist_collection
from api.security import (
    PIN_RE, NICK_RE, SESSION_COOKIE, password_hasher,
    _session, _hash_token, _current_user, _create_session,
    _check_throttle, _record_login_failure, _clear_throttle, _user_payload,
)

router = APIRouter()

class RegisterPayload(BaseModel):
    email: EmailStr
    nickname: str = Field(min_length=3, max_length=16)
    pin: str = Field(min_length=4, max_length=8)


class LoginPayload(BaseModel):
    identifier: str = Field(min_length=3, max_length=320)
    pin: str = Field(min_length=4, max_length=8)

@router.post("/api/auth/register", status_code=201)
def register(payload: RegisterPayload, response: Response) -> dict[str, object]:
    if os.getenv("RATEAPP_DISABLE_REGISTRATION") == "1":
        raise HTTPException(status_code=404, detail="Registration is disabled.")
    email = str(payload.email).strip().lower()
    nickname = payload.nickname.strip().lower()
    pin = payload.pin.strip()

    if not NICK_RE.fullmatch(nickname):
        raise HTTPException(
            status_code=422,
            detail="Ник: 3–16 символов, только латиница, цифры и _.",
        )
    if not PIN_RE.fullmatch(pin) or len(pin) < 6:
        raise HTTPException(status_code=422, detail="Для нового аккаунта PIN должен содержать 6–8 цифр.")

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
            _ensure_wishlist_collection(session, user.id)
            _create_session(session, user, response)
        except IntegrityError:
            session.rollback()
            raise HTTPException(status_code=409, detail="Email или ник уже используются.")

        return _user_payload(user)


@router.post("/api/auth/login")
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


@router.post("/api/auth/logout", status_code=204)
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


@router.get("/api/auth/me")
def auth_me(request: Request) -> dict[str, object]:
    with _session() as session:
        return _user_payload(_current_user(request, session))


@router.get("/api/profile")
def profile(request: Request) -> dict[str, object]:
    with _session() as session:
        return _user_payload(_current_user(request, session))
