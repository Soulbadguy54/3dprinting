"""Web Push management and scheduled release notifications."""
import hashlib
import os
import re
import secrets
from datetime import timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from api.security import _session, _current_user, _now
from api.push import push_ready, send_push, valid_push_endpoint
from api.models import (
    Collection, CollectionGame, Game, PushSubscription,
    ReleasePushDelivery, UserGame, WISHLIST_SLUG,
)

router = APIRouter()

class PushSubscriptionPayload(BaseModel):
    endpoint: str = Field(min_length=20, max_length=2048)
    keys: dict[str, str]


class PushTestPayload(BaseModel):
    gameId: int


def _push_key() -> str:
    key = os.getenv("VAPID_PUBLIC_KEY", "").strip()
    if not push_ready() or not key:
        raise HTTPException(status_code=503, detail="Уведомления ещё не настроены.")
    return key


@router.get("/api/push/config")
def push_config(request: Request) -> dict[str, object]:
    with _session() as session:
        user = _current_user(request, session)
        active = session.scalar(
            select(func.count(PushSubscription.id)).where(PushSubscription.user_id == user.id)
        ) or 0
    return {"enabled": push_ready(), "publicKey": os.getenv("VAPID_PUBLIC_KEY", "") if push_ready() else "",
            "devices": active}


@router.put("/api/push/subscription")
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


@router.delete("/api/push/subscription")
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


@router.post("/api/push/test")
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


@router.get("/api/cron/release-alerts")
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
