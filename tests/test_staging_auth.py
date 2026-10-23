"""Staging must disable account creation before accessing the database."""
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import index


class StagingRegistrationTests(unittest.TestCase):
    def test_registration_disabled_on_staging(self):
        payload = {
            "email": "test-registration@example.invalid",
            "nickname": "register_probe",
            "pin": "123456",
        }
        with patch.dict(os.environ, {"RATEAPP_DISABLE_REGISTRATION": "1"}):
            with TestClient(index.app) as client:
                response = client.post("/api/auth/register", json=payload)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Registration is disabled.")
