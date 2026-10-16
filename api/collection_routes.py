"""Collection CRUD and membership-removal endpoints.

All mutations are user-scoped and run inside a transaction. Playthroughs and
their ratings survive collection removal, including bulk operations.
"""
import base64
import binascii
import re
import secrets
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from api.security import _session, _current_user
from api.collections_service import _ensure_wishlist_collection
from api.library_service import _collections_payload, _library_payload
from api.models import Collection, CollectionGame, Game, UserGame, WISHLIST_SLUG

router = APIRouter()

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


@router.get("/api/collections")
def collections(request: Request) -> list[dict[str, object]]:
    with _session() as session:
        user = _current_user(request, session)
        _ensure_wishlist_collection(session, user.id)
        session.commit()
        return _collections_payload(session, user)


@router.post("/api/collections", status_code=201)
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



@router.patch("/api/collections/{collection_id}")
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


@router.post("/api/collections/bulk-delete")
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


@router.delete("/api/collections/{collection_id}", status_code=204)
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


