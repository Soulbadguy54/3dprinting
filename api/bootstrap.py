import os
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from api.database import Base, SessionLocal, engine
from api.data_integrity import (
    install_required_field_constraints, migrate_missing_playthrough_details,
)
from api.models import (
    Collection, CollectionGame, Game, User, UserGame,
    WISHLIST_SLUG, WISHLIST_TITLE, WISHLIST_DESCRIPTION, WISHLIST_MARK,
)


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
    (WISHLIST_SLUG, WISHLIST_TITLE, WISHLIST_DESCRIPTION, WISHLIST_MARK),
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
        # Neon/PostgreSQL ships pg_trgm; the extension indexes typo-tolerant
        # lookups against both canonical and IGDB alternative game titles.
        connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        connection.exec_driver_sql(
            "ALTER TABLE games ADD COLUMN IF NOT EXISTS popularity_count INTEGER NOT NULL DEFAULT 0"
        )
        connection.exec_driver_sql(
            "ALTER TABLE games ADD COLUMN IF NOT EXISTS hype_count INTEGER NOT NULL DEFAULT 0"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_games_title_trgm ON games USING gin (lower(title) gin_trgm_ops)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_game_aliases_name_trgm ON game_aliases USING gin (lower(name) gin_trgm_ops)"
        )
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
            "ALTER TABLE games ADD COLUMN IF NOT EXISTS details_json TEXT"
        )
        connection.exec_driver_sql(
            "ALTER TABLE games ADD COLUMN IF NOT EXISTS details_cached_at TIMESTAMPTZ"
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
        # Do not backfill by UPDATE: historical rows may violate newer
        # NOT VALID rating constraints, which PostgreSQL *will enforce* on
        # every touched row and crash API initialization (including login).
        # Legacy rows keep NULL and serialize original added_at as fallback.
        connection.exec_driver_sql(
            "ALTER TABLE user_games ADD COLUMN IF NOT EXISTS status_changed_at TIMESTAMPTZ"
        )
        connection.exec_driver_sql(
            "ALTER TABLE collections ADD COLUMN IF NOT EXISTS is_system BOOLEAN NOT NULL DEFAULT FALSE"
        )
        connection.exec_driver_sql(
            "ALTER TABLE collections ADD COLUMN IF NOT EXISTS color_scheme VARCHAR(24) NOT NULL DEFAULT 'violet'"
        )
        connection.exec_driver_sql(
            "ALTER TABLE collections ADD COLUMN IF NOT EXISTS icon_data TEXT"
        )
        connection.exec_driver_sql(
            "ALTER TABLE collections ADD COLUMN IF NOT EXISTS emoji VARCHAR(48)"
        )
        # A stable slug is the identity of the protected system collection.
        # This fixes any preexisting row with that slug without duplicating it.
        connection.exec_driver_sql(
            "UPDATE collections SET is_system = TRUE WHERE slug = 'wishlist'"
        )
        # Backfill each user's collection, including existing accounts.
        # Migrate old wishlist entries only for newly created collections:
        # repeating app initialization never re-adds an intentionally removed game.
        connection.exec_driver_sql("""
            WITH created AS (
                INSERT INTO collections (user_id, slug, title, description, mark, is_system)
                SELECT id, 'wishlist', 'Хочу пройти',
                       'Игры, которые планирую пройти.', '♡', TRUE
                FROM users
                WHERE TRUE
                ON CONFLICT (user_id, slug) DO NOTHING
                RETURNING id, user_id
            )
            INSERT INTO collection_games (collection_id, user_game_id)
            SELECT created.id, ug.id
            FROM created
            JOIN user_games AS ug ON ug.user_id = created.user_id
            WHERE ug.status = 'wishlist'
            ON CONFLICT (collection_id, user_game_id) DO NOTHING
        """)

        # Legacy membership dates were not tracked. Use original library
        # insertion timestamps as the historical approximation, never today.
        connection.exec_driver_sql(
            "ALTER TABLE collection_games ADD COLUMN IF NOT EXISTS added_at TIMESTAMPTZ"
        )
        connection.exec_driver_sql("""
            UPDATE collection_games AS cg SET added_at = ug.added_at
            FROM user_games AS ug
            WHERE cg.user_game_id = ug.id AND cg.added_at IS NULL
        """)
        connection.exec_driver_sql(
            "ALTER TABLE collection_games ALTER COLUMN added_at SET DEFAULT now()"
        )
        connection.exec_driver_sql(
            "ALTER TABLE collection_games ALTER COLUMN added_at SET NOT NULL"
        )

        # New/updated rows are checked immediately. NOT VALID deliberately
        # avoids fabricating ratings in historical incomplete playthroughs.
        constraints = {
            row[0] for row in connection.exec_driver_sql(
                "SELECT conname FROM pg_constraint WHERE conrelid = 'user_games'::regclass"
            )
        }
        if "ck_user_games_rating_completeness" not in constraints:
            connection.exec_driver_sql("""
                ALTER TABLE user_games ADD CONSTRAINT ck_user_games_rating_completeness
                CHECK (
                    (
                        status IN ('completed', 'dropped')
                        AND score IS NOT NULL
                        AND atmosphere_score IS NOT NULL
                        AND story_score IS NOT NULL
                        AND technology_score IS NOT NULL
                        AND gameplay_score IS NOT NULL
                        AND atmosphere_score BETWEEN 1 AND 10
                        AND story_score BETWEEN 1 AND 10
                        AND technology_score BETWEEN 1 AND 10
                        AND gameplay_score BETWEEN 1 AND 10
                        AND score = round(
                            (atmosphere_score + story_score + technology_score + gameplay_score) / 4,
                            1
                        )
                    )
                    OR (
                        status IN ('playing', 'wishlist', 'untracked')
                        AND score IS NULL
                        AND atmosphere_score IS NULL
                        AND story_score IS NULL
                        AND technology_score IS NULL
                        AND gameplay_score IS NULL
                    )
                ) NOT VALID
            """)
        if "ck_user_games_status_changed_at" not in constraints:
            connection.exec_driver_sql("""
                ALTER TABLE user_games ADD CONSTRAINT ck_user_games_status_changed_at
                CHECK (
                    status IN ('completed', 'playing', 'dropped')
                    OR status_changed_at IS NULL
                ) NOT VALID
            """)
        if "ck_user_games_date_coherence" not in constraints:
            connection.exec_driver_sql("""
                ALTER TABLE user_games ADD CONSTRAINT ck_user_games_date_coherence
                CHECK (
                    (status IN ('completed', 'dropped') OR completed_at IS NULL)
                    AND (status = 'playing' OR started_at IS NULL)
                    AND (status IN ('completed', 'dropped') OR review IS NULL)
                ) NOT VALID
            """)

        # The imported history predates required platforms/dates.
        # Only the two user-requested accounts are repaired. No scores,
        # statuses or original dates are overwritten.
        if os.getenv("VERCEL_ENV") == "production":
            migrate_missing_playthrough_details(
                connection, migration_date=date(2026, 10, 15),
            )
        install_required_field_constraints(connection)

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
                    is_system=(slug == WISHLIST_SLUG),
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
                    atmosphere_score=score,
                    story_score=score,
                    technology_score=score,
                    gameplay_score=score,
                    review=review,
                    added_at=_as_datetime(added_at),
                    status_changed_at=_as_datetime(added_at)
                    if status in {"completed", "playing", "dropped"} else None,
                )
                session.add(entry)
                session.flush()

                for slug in set(collection_slugs) | ({WISHLIST_SLUG} if status == "wishlist" else set()):
                    session.add(
                        CollectionGame(
                            collection_id=collection_objects[slug].id,
                            user_game_id=entry.id,
                        )
                    )

            session.commit()
        except IntegrityError:
            session.rollback()
