from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from api.database import Base, SessionLocal, engine
from api.models import Collection, CollectionGame, Game, User, UserGame


GAMES = [
    (1, "Neon Divide", "2026-03-12", 88),
    (2, "Ashes of Meridian", "2025-11-04", 84),
    (3, "Driftline", "2026-06-19", 81),
    (4, "Tiny Kingdoms", "2024-08-27", 89),
    (5, "Signal Lost", "2025-10-09", 83),
    (6, "Paper Skies", "2025-05-16", 91),
    (7, "Black Circuit", "2026-01-30", 86),
    (8, "Long Way Home", "2025-09-21", 80),
    (9, "Iron Choir", "2026-08-08", 87),
]

COLLECTIONS = [
    ("best", "Лучшее из пройденного", "Игры, к которым хочется возвращаться.", "★"),
    ("2026", "2026", "Что прошёл и прохожу в этом году.", "26"),
    ("coop", "Кооп", "Игры для совместных вечеров.", "CO"),
    ("cozy", "На расслабоне", "Спокойные игры без спешки.", "☁"),
]

LIBRARY = [
    (1, "completed", "PS5", "2026-09-28", None, 9.4, "Очень цельная RPG. Больше всего зашла свобода в квестах и темп истории.", ["best", "2026"], "2026-09-28"),
    (2, "playing", "PC", None, "2026-09-22", None, None, ["2026"], "2026-09-22"),
    (4, "completed", "Switch", "2026-08-14", None, 8.7, "Идеальная маленькая стратегия для коротких сессий.", ["cozy", "2026"], "2026-08-14"),
    (5, "playing", "PS5", None, "2026-08-03", None, None, ["coop", "2026"], "2026-08-03"),
    (6, "completed", "PC", "2026-07-03", None, 9.1, "Редкий случай, когда короткая игра заканчивается ровно тогда, когда нужно.", ["best", "cozy", "2026"], "2026-07-03"),
    (7, "completed", "PS5", "2026-05-18", None, 8.9, "Быстрый, жёсткий и очень хорошо отполированный экшен.", ["best", "2026"], "2026-05-18"),
    (3, "wishlist", None, None, None, None, None, [], "2026-04-11"),
    (8, "wishlist", None, None, None, None, None, ["cozy"], "2026-03-02"),
]


def _as_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _as_datetime(value: str) -> datetime:
    parsed = date.fromisoformat(value)
    return datetime(parsed.year, parsed.month, parsed.day, 12, tzinfo=timezone.utc)


def initialize_database() -> None:
    if engine is None or SessionLocal is None:
        return

    Base.metadata.create_all(bind=engine)

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE games ADD COLUMN IF NOT EXISTS developer VARCHAR(255)"
        )
        connection.exec_driver_sql(
            "ALTER TABLE games ADD COLUMN IF NOT EXISTS genres_json TEXT"
        )
        connection.exec_driver_sql(
            "ALTER TABLE games ADD COLUMN IF NOT EXISTS platforms_json TEXT"
        )
        connection.exec_driver_sql(
            "ALTER TABLE user_games ADD COLUMN IF NOT EXISTS atmosphere_score NUMERIC(3, 1)"
        )
        connection.exec_driver_sql(
            "ALTER TABLE user_games ADD COLUMN IF NOT EXISTS story_score NUMERIC(3, 1)"
        )
        connection.exec_driver_sql(
            "ALTER TABLE user_games ADD COLUMN IF NOT EXISTS technology_score NUMERIC(3, 1)"
        )
        connection.exec_driver_sql(
            "ALTER TABLE user_games ADD COLUMN IF NOT EXISTS gameplay_score NUMERIC(3, 1)"
        )

    with SessionLocal() as session:
        existing = session.scalar(select(User).where(User.email == "demo@rateapp.local"))
        if existing is not None:
            if existing.nickname == "soulbadguy":
                existing.nickname = "demo_archive"
                session.commit()
            return

        try:
            user = User(
                email="demo@rateapp.local",
                nickname="demo_archive",
                pin_hash="auth-not-enabled-yet",
            )
            session.add(user)

            game_objects = {
                igdb_id: Game(
                    igdb_id=igdb_id,
                    title=title,
                    release_date=_as_date(release_date),
                    igdb_rating=rating,
                )
                for igdb_id, title, release_date, rating in GAMES
            }
            session.add_all(game_objects.values())

            collection_objects = {
                slug: Collection(
                    user_id=0,
                    slug=slug,
                    title=title,
                    description=description,
                    mark=mark,
                )
                for slug, title, description, mark in COLLECTIONS
            }

            session.flush()

            for collection in collection_objects.values():
                collection.user_id = user.id
            session.add_all(collection_objects.values())
            session.flush()

            for (
                game_igdb_id,
                status,
                platform,
                completed_at,
                started_at,
                score,
                review,
                collection_slugs,
                added_at,
            ) in LIBRARY:
                entry = UserGame(
                    user_id=user.id,
                    game_id=game_objects[game_igdb_id].id,
                    status=status,
                    platform=platform,
                    completed_at=_as_date(completed_at),
                    started_at=_as_date(started_at),
                    score=score,
                    review=review,
                    added_at=_as_datetime(added_at),
                )
                session.add(entry)
                session.flush()

                for slug in collection_slugs:
                    session.add(
                        CollectionGame(
                            collection_id=collection_objects[slug].id,
                            user_game_id=entry.id,
                        )
                    )

            session.commit()
        except IntegrityError:
            session.rollback()
