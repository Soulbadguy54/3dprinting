"""Baseline: preserve the existing production schema and imported history.

Revision ID: 20261016_01
Revises:
"""
from alembic import op

revision = "20261016_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Reuse the vetted historical/bootstrap idempotent schema changes exactly
    # once, while separating them from serverless function cold starts.
    # A future migration must consist of explicit op.* steps only.
    from api.bootstrap import initialize_database
    initialize_database()


def downgrade() -> None:
    raise RuntimeError("Historical production data must never be dropped by baseline downgrade")
