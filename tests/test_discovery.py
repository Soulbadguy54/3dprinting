"""Discovery feed, swipe feedback, wishlist and undo against isolated CI PostgreSQL."""
import secrets
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import select

from api.index import app
from api.database import SessionLocal
from api.models import Collection, CollectionGame, DiscoveryFeedback, Game, UserGame


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, base_url="https://testserver")
        token = secrets.token_hex(4)
        self.nickname = "d" + token
        response = self.client.post("/api/auth/register", json={
            "email": f"{self.nickname}@example.com",
            "nickname": self.nickname,
            "pin": "12345678",
        })
        self.assertEqual(response.status_code, 201, response.text)
        self.igdb_id = secrets.randbelow(600_000_000) + 300_000_000
        with SessionLocal() as session:
            session.add(Game(
                igdb_id=self.igdb_id,
                title="Discovery Test Game",
                cover_url="https://images.igdb.com/igdb/image/upload/t_cover_big_2x/test.jpg",
                igdb_rating=88,
                popularity_count=99999,
                genres_json='["Action", "RPG"]',
                platforms_json='["PC"]',
            ))
            session.commit()

    def tearDown(self):
        self.client.close()

    def test_feed_only_authenticated_and_local(self):
        self.assertEqual(TestClient(app).get("/api/discover/feed").status_code, 401)
        response = self.client.get("/api/discover/feed")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(self.igdb_id, [item["id"] for item in response.json()["items"]])

    def test_like_filters_feed_then_undo_restores(self):
        response = self.client.post("/api/discover/feedback", json={
            "gameId": self.igdb_id, "action": "like",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn(self.igdb_id, [item["id"] for item in self.client.get("/api/discover/feed").json()["items"]])
        self.assertEqual(self.client.delete(f"/api/discover/feedback/{self.igdb_id}").status_code, 200)
        self.assertIn(self.igdb_id, [item["id"] for item in self.client.get("/api/discover/feed").json()["items"]])

    def test_wishlist_and_undo_do_not_change_ratings(self):
        response = self.client.post("/api/discover/feedback", json={
            "gameId": self.igdb_id, "action": "wishlist",
        })
        self.assertEqual(response.status_code, 200, response.text)
        with SessionLocal() as session:
            row = session.scalar(select(UserGame).join(Game, Game.id == UserGame.game_id)
                                 .where(Game.igdb_id == self.igdb_id))
            self.assertIsNotNone(row)
            self.assertEqual(row.status, "untracked")
            self.assertIsNone(row.score)
            membership = session.scalar(select(CollectionGame).where(CollectionGame.user_game_id == row.id))
            self.assertIsNotNone(membership)

        self.assertEqual(self.client.delete(f"/api/discover/feedback/{self.igdb_id}").status_code, 200)
        with SessionLocal() as session:
            self.assertIsNone(session.scalar(select(UserGame).join(Game, Game.id == UserGame.game_id)
                                  .where(Game.igdb_id == self.igdb_id)))

    def test_invalid_vote_and_repeat_are_safe(self):
        self.assertEqual(self.client.post("/api/discover/feedback", json={
            "gameId": self.igdb_id, "action": "wat",
        }).status_code, 422)
        for _ in range(2):
            self.assertEqual(self.client.post("/api/discover/feedback", json={
                "gameId": self.igdb_id, "action": "dislike",
            }).status_code, 200)
        self.assertEqual(self.client.post("/api/discover/feedback", json={
            "gameId": self.igdb_id, "action": "like",
        }).status_code, 409)
        self.assertEqual(self.client.delete(f"/api/discover/feedback/{self.igdb_id}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/discover/feedback/{self.igdb_id}").status_code, 404)
