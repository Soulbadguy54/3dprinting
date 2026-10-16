"""API health is a readiness check, not a false positive when DB is down."""
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import index


def test_health_returns_503_without_database():
    with patch.object(index, "engine", None):
        with TestClient(index.app) as client:
            r = client.get("/api/health")
            assert r.status_code == 503
            assert r.json()["ok"] is False
            assert r.json()["database"]["reachable"] is False
