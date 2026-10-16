"""Regression tests for immediate store-link caching and IGDB detail enrichment."""
import json
import secrets
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select

from api import index
from api.database import SessionLocal
from api.models import Game


class GameMetadataCacheTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(index.app, base_url="https://testserver")
        suffix = secrets.token_hex(3)
        response = self.client.post("/api/auth/register", json={
            "email": f"metadata_{suffix}@example.com",
            "nickname": f"metadata_{suffix}",
            "pin": "12345678",
        })
        self.assertEqual(response.status_code, 201, response.text)
        self.game_id = secrets.randbelow(200_000_000) + 600_000_000

    def tearDown(self):
        self.client.close()

    def _cache_igdb_result(self):
        return index._cache_igdb_games([{
            "id": self.game_id,
            "name": "Starfall Horizon",
            "websites": [
                {"url": "https://store.steampowered.com/app/1234"},
                {"url": "https://www.epicgames.com/store/en-US/p/starfall"},
                {"url": "https://not-steam.example/unsafe"},
            ],
            "videos": [{"name": "Trailer", "video_id": "abcdefghijk"}],
        }])

    def test_igdb_search_details_saved_and_exposed_immediately(self):
        items = self._cache_igdb_result()
        self.assertEqual([s["provider"] for s in items[0]["storeLinks"]], ["steam", "epic"])
        self.assertEqual(items[0]["trailerUrl"], "https://www.youtube.com/watch?v=abcdefghijk")
        with SessionLocal() as session:
            game = session.scalar(select(Game).where(Game.igdb_id == self.game_id))
            details = json.loads(game.details_json)
            self.assertTrue(details["_linksOnly"])
            self.assertIsNotNone(game.details_cached_at)

        with patch("api.games_routes._igdb_access_token", return_value=("client", "token")), \
             patch("api.games_routes._igdb_details_request", return_value=[{
                 "hastily": 3600 * 14,
                 "completely": 3600 * 61,
             }]) as req:
            response = self.client.get(f"/api/games/{self.game_id}/details")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(req.call_count, 1)
        self.assertEqual(req.call_args.args[0], "game_time_to_beats")
        self.assertEqual(response.json()["storyHours"], 14)
        self.assertEqual(response.json()["storeLinks"][0]["provider"], "steam")

        with patch("api.games_routes._igdb_access_token", side_effect=AssertionError("Cached data must be local")):
            again = self.client.get(f"/api/games/{self.game_id}/details")
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()["completionHours"], 61)

    def test_bootstrap_embeds_existing_cached_store_links(self):
        self._cache_igdb_result()
        self.assertEqual(
            self.client.put(f"/api/library/{self.game_id}/wishlist").status_code,
            200,
        )
        bootstrap = self.client.get("/api/bootstrap")
        self.assertEqual(bootstrap.status_code, 200, bootstrap.text)
        game = next(item["game"] for item in bootstrap.json()["library"] if item["gameId"] == self.game_id)
        self.assertEqual(game["storeLinks"][0]["provider"], "steam")
        self.assertIn("youtube.com", game["trailerUrl"])

    def test_existing_full_cache_preserved_on_repeat_search(self):
        self._cache_igdb_result()
        with SessionLocal() as session:
            game = session.scalar(select(Game).where(Game.igdb_id == self.game_id))
            full = json.loads(game.details_json)
            full["storyHours"] = 18
            full["_linksOnly"] = False
            game.details_json = json.dumps(full)
            session.commit()
        result = self._cache_igdb_result()
        self.assertEqual(result[0]["storeLinks"][0]["provider"], "steam")
        with patch("api.games_routes._igdb_access_token", side_effect=AssertionError("Should not call IGDB")):
            response = self.client.get(f"/api/games/{self.game_id}/details")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["storyHours"], 18)


if __name__ == "__main__":
    unittest.main()
