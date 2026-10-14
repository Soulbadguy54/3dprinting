"""Web Push subscriptions, authorized test notifications and release-day cron."""
import os
import secrets
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select

from api import index
from api.database import SessionLocal
from api.models import Game, PushSubscription, ReleasePushDelivery
from api.push import valid_push_endpoint

ENV = {
    "VAPID_PUBLIC_KEY": "A" * 87,
    "VAPID_PRIVATE_KEY": "B" * 180,
    "CRON_SECRET": "secret-for-automated-tests",
}


class PushTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, ENV)
        self.env.start()
        self.client = TestClient(index.app, base_url="https://testserver")
        self.game_id = secrets.randbelow(400_000_000) + 500_000_000
        suffix = secrets.token_hex(6)
        signup = self.client.post("/api/auth/register", json={
            "email": f"push_{suffix}@example.com", "nickname": f"push_{suffix}", "pin": "12345678",
        })
        self.assertEqual(signup.status_code, 201, signup.text)
        with SessionLocal() as session:
            session.add(Game(
                igdb_id=self.game_id, title="Upcoming Game",
                release_date=datetime.now(timezone.utc).date(),
            ))
            session.commit()
        added = self.client.put(f"/api/library/{self.game_id}/wishlist")
        self.assertEqual(added.status_code, 200, added.text)
        self.endpoint = f"https://fcm.googleapis.com/fcm/send/{secrets.token_urlsafe(24)}"
        self.subscription = {
            "endpoint": self.endpoint,
            "keys": {"p256dh": "A" * 87, "auth": "B" * 22},
        }

    def tearDown(self):
        self.client.close()
        self.env.stop()

    def subscribe(self):
        return self.client.put("/api/push/subscription", json=self.subscription)

    def run_cron(self, secret="secret-for-automated-tests"):
        return self.client.get(
            "/api/cron/release-alerts",
            headers={"Authorization": f"Bearer {secret}"},
        )

    def test_push_endpoint_rejects_ssrf(self):
        self.assertFalse(valid_push_endpoint("http://127.0.0.1:3000/internal"))
        self.assertFalse(valid_push_endpoint("https://fcm.googleapis.com.evil.com/endpoint"))
        self.assertFalse(valid_push_endpoint("https://user@fcm.googleapis.com/endpoint"))
        self.assertTrue(valid_push_endpoint(self.endpoint))

    def test_subscription_requires_login_and_uses_current_account(self):
        response = self.subscribe()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["subscribed"])
        self.client.cookies.clear()
        denial = self.subscribe()
        self.assertEqual(denial.status_code, 401)

    def test_test_push_only_for_users_own_wishlist_game(self):
        self.assertEqual(self.subscribe().status_code, 200)
        with patch.object(index, "send_push", return_value=(True, False)) as sender:
            sent = self.client.post("/api/push/test", json={"gameId": self.game_id})
            self.assertEqual(sent.status_code, 200, sent.text)
            self.assertEqual(sent.json()["accepted"], 1)
            self.assertIn("Сегодня вышла", sender.call_args.kwargs["title"])
            retry = self.client.post("/api/push/test", json={"gameId": self.game_id})
            self.assertEqual(retry.status_code, 429)
        missing = self.client.post("/api/push/test", json={"gameId": 1})
        self.assertEqual(missing.status_code, 404)

    def test_cron_checks_secret_and_sends_only_once_per_release(self):
        self.assertEqual(self.subscribe().status_code, 200)
        self.assertEqual(self.run_cron("wrong").status_code, 401)
        with patch.object(index, "send_push", return_value=(True, False)) as sender:
            first = self.run_cron()
            self.assertEqual(first.status_code, 200, first.text)
            self.assertGreaterEqual(first.json()["accepted"], 1)
            calls_after_first = sender.call_count
            second = self.run_cron()
            self.assertEqual(second.status_code, 200)
            self.assertEqual(sender.call_count, calls_after_first)
            self.assertEqual(second.json()["accepted"], 0)

        with SessionLocal() as session:
            subscription = session.scalar(
                select(PushSubscription).where(PushSubscription.endpoint == self.endpoint)
            )
            self.assertEqual(
                session.query(ReleasePushDelivery).filter_by(subscription_id=subscription.id).count(),
                1,
            )

    def test_future_release_and_removed_wishlist_not_notified(self):
        self.assertEqual(self.subscribe().status_code, 200)
        with SessionLocal() as session:
            game = session.scalar(select(Game).where(Game.igdb_id == self.game_id))
            game.release_date = datetime.now(timezone.utc).date() + timedelta(days=12)
            session.commit()
        with patch.object(index, "send_push", return_value=(True, False)) as sender:
            result = self.run_cron()
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(sender.call_count, 0)

        with SessionLocal() as session:
            game = session.scalar(select(Game).where(Game.igdb_id == self.game_id))
            game.release_date = datetime.now(timezone.utc).date()
            session.commit()
        removed = self.client.delete(f"/api/library/{self.game_id}/wishlist")
        self.assertEqual(removed.status_code, 200)
        with patch.object(index, "send_push", return_value=(True, False)) as sender:
            self.run_cron()
            self.assertEqual(sender.call_count, 0)

    def test_unsubscribe_prevents_future_notifications(self):
        self.assertEqual(self.subscribe().status_code, 200)
        response = self.client.request("DELETE", "/api/push/subscription", json=self.subscription)
        self.assertEqual(response.status_code, 200, response.text)
        with patch.object(index, "send_push", return_value=(True, False)) as sender:
            result = self.run_cron()
            self.assertEqual(result.status_code, 200)
            self.assertEqual(sender.call_count, 0)


if __name__ == "__main__":
    unittest.main()
