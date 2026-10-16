"""Ensure FastAPI imports cleanly without making a database connection.

This is a permanent regression test for the production login 500 caused by
schema updates during a serverless cold start in October 2026.
"""
import os
import subprocess
import sys
import unittest


class StartupSafetyTests(unittest.TestCase):
    def test_api_import_does_not_contact_database(self):
        env = os.environ.copy()
        # Connecting to this intentionally invalid endpoint must never occur.
        env["DATABASE_URL"] = "postgresql+psycopg://not_available@127.0.0.1:1/never"
        result = subprocess.run(
            [sys.executable, "-c", "from api.index import app; print(app.title)"],
            capture_output=True, text=True, env=env, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RateApp", result.stdout)
