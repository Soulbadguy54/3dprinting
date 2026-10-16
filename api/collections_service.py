"""Shared collection creation rules independent of API route modules."""
from sqlalchemy import select
from api.models import (
    Collection, CollectionGame, UserGame,
    WISHLIST_SLUG, WISHLIST_TITLE, WISHLIST_DESCRIPTION, WISHLIST_MARK,
)

def _ensure_wishlist_collection(session, user_id: int) -> Collection:
    row = session.scalar(
        select(Collection).where(
            Collection.user_id == user_id,
            Collection.slug == WISHLIST_SLUG,
        )
    )
    if row is not None:
        return row

    row = Collection(
        user_id=user_id,
        slug=WISHLIST_SLUG,
        title=WISHLIST_TITLE,
        description=WISHLIST_DESCRIPTION,
        mark=WISHLIST_MARK,
        emoji=WISHLIST_MARK,
        color_scheme="rose",
        is_system=True,
    )
    session.add(row)
    session.flush()

    # Only when first creating the system collection, preserve older
    # wishlist entries from before this feature existed.
    old_wishes = session.scalars(
        select(UserGame).where(
            UserGame.user_id == user_id,
            UserGame.status == "wishlist",
        )
    ).all()
    session.add_all([
        CollectionGame(collection_id=row.id, user_game_id=entry.id)
        for entry in old_wishes
    ])
    session.flush()
    return row
