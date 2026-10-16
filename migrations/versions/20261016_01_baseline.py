"""Version the legacy schema without rewriting production user history.

Revision ID: 20261016_01
Revises:

The original RateApp schema predates Alembic. On an already running database,
this migration *only checks* compatibility and records the revision in
alembic_version. For an empty test/development database, it bootstraps the
legacy schema once; later migrations must exclusively use Alembic operations.
"""
from alembic import op
from sqlalchemy import inspect

revision = "20261016_01"
down_revision = None
branch_labels = None
depends_on = None

# Columns required by the current app, including those added before Alembic
# was introduced. If something is missing, abort without changing user rows.
_REQUIRED = {
    "games": {"id", "igdb_id", "details_json", "genres_json"},
    "user_games": {"id", "user_id", "game_id", "status", "status_changed_at"},
    "collections": {"id", "user_id", "slug", "color_scheme", "emoji", "is_system"},
    "collection_games": {"id", "collection_id", "user_game_id"},
    "users": {"id", "email", "nickname", "pin_hash"},
}


def upgrade() -> None:
    connection = op.get_bind()
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())
    app_tables = existing_tables.intersection(_REQUIRED)

    if app_tables:
        # A partially deployed schema is not a safe bootstrap target.
        missing_tables = set(_REQUIRED).difference(existing_tables)
        if missing_tables:
            raise RuntimeError(
                "Refusing to mutate partially initialized RateApp database: "
                f"missing tables: {sorted(missing_tables)}"
            )
        for table, required in _REQUIRED.items():
            columns = {col["name"] for col in inspector.get_columns(table)}
            missing = required.difference(columns)
            if missing:
                raise RuntimeError(
                    f"RateApp production schema not ready: {table} missing "
                    f"columns {sorted(missing)}. Back up and plan an explicit "
                    "migration before stamping the baseline."
                )
        return

    # The first CI/test database has no app data. Legacy bootstrap is allowed
    # here only; never execute historical repairs on an existing database.
    from api.bootstrap import initialize_database
    initialize_database()


def downgrade() -> None:
    raise RuntimeError("Historical production data cannot be dropped by baseline downgrade")
