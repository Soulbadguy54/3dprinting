"""Readiness must fail with HTTP 503 on database outages."""
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from api import index


class HealthTests(unittest.TestCase):
    def test_health_returns_503_without_database(self):
        with patch.object(index, "engine", None):
            with TestClient(index.app) as client:
                response = client.get("/api/health")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["ok"])
        self.assertFalse(response.json()["database"]["reachable"])
