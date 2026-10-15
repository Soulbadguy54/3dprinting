"""PostgreSQL invariants and audited one-time imported-history repair.

Playthrough fields are conditionally required: wishlist/collection placeholders
must remain able to exist without a platform or playthrough date.
"""
from datetime import date

from sqlalchemy import text


PLATFORM_PRIORITY = (
    ("PC", "windows"),
    ("PS5", "playstation 5"),
    ("PS4", "playstation 4"),
)


def migrate_missing_playthrough_details(
    connection, *, migration_date: date, nicknames: tuple[str, str] = ("soulbadguy", "nastya"),
) -> int:
    """Repair only absent fields on eligible playthroughs; preserve supplied data.

    Prefer actual IGDB platforms in order Windows PC, PS5, PS4.
    If IGDB does not list any of these, use PS4 as the user's explicit
    last resort and mark it as unverified in the audit for later correction.
    Rows missing the four rated criteria are not altered: the existing rating
    CHECK would reject such legacy rows, and ratings must never be invented.
    """
    connection.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS playthrough_backfill_20261015 (
            user_game_id INTEGER PRIMARY KEY REFERENCES user_games(id) ON DELETE CASCADE,
            previous_platform VARCHAR(80),
            selected_platform VARCHAR(80),
            previous_completed_at DATE,
            new_completed_at DATE,
            previous_started_at DATE,
            new_started_at DATE,
            migrated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    connection.exec_driver_sql("""
        ALTER TABLE playthrough_backfill_20261015
        ADD COLUMN IF NOT EXISTS platform_choice_source VARCHAR(20)
            NOT NULL DEFAULT 'igdb'
    """)
    result = connection.execute(text("""
        WITH candidates AS (
            SELECT ug.id, ug.platform AS previous_platform,
                   ug.completed_at AS previous_completed_at,
                   ug.started_at AS previous_started_at,
                   ug.status,
                   (
                       SELECT p.platform
                       FROM jsonb_array_elements_text(
                           COALESCE(NULLIF(g.platforms_json, ''), '[]')::jsonb
                       ) AS p(platform)
                       WHERE
                           lower(p.platform) LIKE '%windows%'
                           OR lower(p.platform) = 'pc'
                           OR lower(p.platform) IN ('playstation 5', 'ps5', 'playstation 4', 'ps4')
                       ORDER BY CASE
                           WHEN lower(p.platform) LIKE '%windows%' OR lower(p.platform) = 'pc' THEN 1
                           WHEN lower(p.platform) IN ('playstation 5', 'ps5') THEN 2
                           ELSE 3
                       END, p.platform
                       LIMIT 1
                   ) AS suggested_platform
            FROM user_games ug
            JOIN users u ON u.id = ug.user_id
            JOIN games g ON g.id = ug.game_id
            WHERE u.nickname IN (:user_one, :user_two)
              AND ug.status IN ('completed', 'dropped')
              AND ug.score IS NOT NULL
              AND ug.atmosphere_score IS NOT NULL
              AND ug.story_score IS NOT NULL
              AND ug.technology_score IS NOT NULL
              AND ug.gameplay_score IS NOT NULL
        ), repaired AS (
            UPDATE user_games AS ug
            SET platform = CASE
                    WHEN NULLIF(btrim(ug.platform), '') IS NULL
                    THEN COALESCE(c.suggested_platform, 'PlayStation 4') ELSE ug.platform
                END,
                completed_at = CASE
                    WHEN ug.status IN ('completed','dropped') AND ug.completed_at IS NULL
                    THEN :migration_date ELSE ug.completed_at
                END,
                started_at = ug.started_at
            FROM candidates c
            WHERE ug.id = c.id
              AND (
                  (NULLIF(btrim(ug.platform), '') IS NULL)
                  OR (ug.status IN ('completed', 'dropped') AND ug.completed_at IS NULL)
              )
              AND (
                  -- An existing NOT VALID CHECK still applies to updates.
                  (
                    ug.score = round((ug.atmosphere_score + ug.story_score
                                   + ug.technology_score + ug.gameplay_score) / 4, 1)
                    AND ug.atmosphere_score BETWEEN 1 AND 10
                    AND ug.story_score BETWEEN 1 AND 10
                    AND ug.technology_score BETWEEN 1 AND 10
                    AND ug.gameplay_score BETWEEN 1 AND 10
                  )
              )
            RETURNING ug.id, ug.platform, ug.completed_at, ug.started_at
        )
        INSERT INTO playthrough_backfill_20261015 (
            user_game_id, previous_platform, selected_platform,
            previous_completed_at, new_completed_at,
            previous_started_at, new_started_at, platform_choice_source
        )
        SELECT r.id, c.previous_platform, r.platform,
               c.previous_completed_at, r.completed_at,
               c.previous_started_at, r.started_at,
               CASE WHEN c.suggested_platform IS NULL THEN 'user_ps4_fallback' ELSE 'igdb' END
        FROM repaired r JOIN candidates c ON c.id = r.id
        ON CONFLICT (user_game_id) DO UPDATE SET
            selected_platform = EXCLUDED.selected_platform,
            new_completed_at = EXCLUDED.new_completed_at,
            new_started_at = EXCLUDED.new_started_at,
            platform_choice_source = EXCLUDED.platform_choice_source
        RETURNING user_game_id
    """), {
        "user_one": nicknames[0],
        "user_two": nicknames[1],
        "migration_date": migration_date,
    })
    return len(result.fetchall())


def install_required_field_constraints(connection) -> None:
    """Protect new writes now; historical rows can be validated once repaired."""
    existing = {
        name for (name,) in connection.exec_driver_sql("""
            SELECT conname FROM pg_constraint
            WHERE conrelid = 'user_games'::regclass
        """)
    }
    if "ck_user_games_required_fields" not in existing:
        connection.exec_driver_sql("""
            ALTER TABLE user_games ADD CONSTRAINT ck_user_games_required_fields
            CHECK (
                (
                    status IN ('completed', 'dropped')
                    AND platform IS NOT NULL AND btrim(platform) <> ''
                    AND completed_at IS NOT NULL AND started_at IS NULL
                )
                OR (status = 'playing' AND completed_at IS NULL)
                OR (
                    status IN ('wishlist', 'untracked')
                    AND platform IS NULL AND completed_at IS NULL AND started_at IS NULL
                )
            ) NOT VALID
        """)

    # SQLAlchemy mappings already declare the color field NOT NULL.
    # Repair only malformed historical display metadata, not memberships.
    connection.exec_driver_sql("""
        UPDATE collections
        SET title = 'Коллекция ' || id::text
        WHERE title IS NULL OR btrim(title) = ''
    """)
    connection.exec_driver_sql("""
        UPDATE collections
        SET color_scheme = 'violet'
        WHERE color_scheme IS NULL OR color_scheme NOT IN (
            'violet', 'rose', 'blue', 'cyan', 'teal',
            'emerald', 'lime', 'amber', 'orange', 'slate'
        )
    """)
    connection.exec_driver_sql("ALTER TABLE collections ALTER COLUMN title SET NOT NULL")
    connection.exec_driver_sql(
        "ALTER TABLE collections ALTER COLUMN color_scheme SET NOT NULL"
    )
    collection_constraints = {
        name for (name,) in connection.exec_driver_sql("""
            SELECT conname FROM pg_constraint
            WHERE conrelid = 'collections'::regclass
        """)
    }
    if "ck_collections_display_fields" not in collection_constraints:
        connection.exec_driver_sql("""
            ALTER TABLE collections ADD CONSTRAINT ck_collections_display_fields
            CHECK (
                title IS NOT NULL AND btrim(title) <> ''
                AND slug IS NOT NULL AND btrim(slug) <> ''
                AND color_scheme IS NOT NULL
                AND color_scheme IN (
                    'violet', 'rose', 'blue', 'cyan', 'teal',
                    'emerald', 'lime', 'amber', 'orange', 'slate'
                )
            )
        """)

    # Validate the complete legacy table when possible: for an uncleaned
    # third-party account leave NOT VALID to protect new writes, and expose
    # the unresolved row count via health instead of rewriting its history.
    invalid_count = connection.exec_driver_sql("""
        SELECT count(*) FROM user_games
        WHERE NOT (
            (status IN ('completed','dropped')
             AND platform IS NOT NULL AND btrim(platform) <> ''
             AND completed_at IS NOT NULL AND started_at IS NULL)
            OR
            (status = 'playing' AND completed_at IS NULL)
            OR
            (status IN ('wishlist','untracked') AND platform IS NULL
             AND completed_at IS NULL AND started_at IS NULL)
        )
    """).scalar_one()
    if invalid_count == 0:
        connection.exec_driver_sql(
            "ALTER TABLE user_games VALIDATE CONSTRAINT ck_user_games_required_fields"
        )


def playthrough_integrity_summary(connection) -> dict[str, object]:
    """Only aggregate, non-personal migration diagnostics for the health API."""
    result = connection.exec_driver_sql("""
        SELECT count(*) AS total,
               count(*) FILTER (
                   WHERE previous_platform IS NULL OR btrim(previous_platform) = ''
               ) AS platform_updates,
               count(*) FILTER (
                   WHERE previous_completed_at IS NULL AND new_completed_at IS NOT NULL
               ) AS date_updates,
               count(*) FILTER (
                   WHERE previous_started_at IS NULL AND new_started_at IS NOT NULL
               ) AS start_updates,
               count(*) FILTER (
                   WHERE platform_choice_source = 'user_ps4_fallback'
               ) AS fallback_platform_updates
        FROM playthrough_backfill_20261015
    """).one()
    unresolved = connection.exec_driver_sql("""
        SELECT count(*)
        FROM user_games ug JOIN users u ON ug.user_id=u.id
        WHERE u.nickname IN ('soulbadguy','nastya')
          AND ug.status IN ('completed','dropped')
          AND (
              ug.platform IS NULL OR btrim(ug.platform) = ''
              OR (ug.status IN ('completed','dropped') AND ug.completed_at IS NULL)
          )
    """).scalar_one()
    validity = connection.exec_driver_sql("""
        SELECT convalidated FROM pg_constraint
        WHERE conname = 'ck_user_games_required_fields'
          AND conrelid = 'user_games'::regclass
    """).scalar_one_or_none()
    return {
        "migrationDate": "2026-10-15",
        "updatedRows": result.total,
        "platformsSet": result.platform_updates,
        "completionDatesSet": result.date_updates,
        "startDatesSet": result.start_updates,
        "ps4FallbacksWithoutIGDBMatch": result.fallback_platform_updates,
        "unresolvedTargetRows": unresolved,
        "constraintValidated": bool(validity),
    }
