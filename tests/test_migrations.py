"""Regression tests for the read-only Alembic baseline on existing databases.

In particular, don't run the old bootstrap/repair code on production rows that
may violate newer NOT VALID constraints. Such migrations previously caused
500 responses for every API endpoint, including login.
"""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

from sqlalchemy import text

from api.database import engine


def _migration():
    path = Path(__file__).resolve().parents[1] / (
        "migrations/versions/20261016_01_baseline.py"
    )
    spec = importlib.util.spec_from_file_location("rateapp_baseline", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BaselineMigrationTests(unittest.TestCase):
    def test_existing_schema_is_read_only(self):
        self.assertIsNotNone(engine)
        module = _migration()
        with engine.connect() as connection:
            before = connection.execute(text("SELECT COUNT(*) FROM user_games")).scalar()
            with (
                patch.object(module.op, "get_bind", return_value=connection),
                patch(
                    "api.bootstrap.initialize_database",
                    side_effect=AssertionError("legacy bootstrap must not run"),
                ),
            ):
                module.upgrade()
            after = connection.execute(text("SELECT COUNT(*) FROM user_games")).scalar()
        self.assertEqual(before, after)

    def test_partial_schema_is_rejected_before_bootstrap(self):
        module = _migration()

        class IncompleteInspector:
            def get_table_names(self):
                return ["user_games"]

        with (
            patch.object(module.op, "get_bind", return_value=object()),
            patch.object(module, "inspect", return_value=IncompleteInspector()),
            patch(
                "api.bootstrap.initialize_database",
                side_effect=AssertionError("must not repair partial schema"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "partially initialized"):
                module.upgrade()
