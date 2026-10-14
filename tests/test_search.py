"""Search aliases and unreleased-game caching for the RateApp catalog."""
import secrets
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import index


class SearchVariantsTests(unittest.TestCase):
    def test_gta_6_and_gta6_include_official_title(self):
        for query in ("GTA 6", "gta6", "GTA VI"):
            with self.subTest(query=query):
                variants = index._search_query_variants(query)
                self.assertIn(["grand", "theft", "auto", "vi"], variants)

    def test_witcher_4_matches_roman_numeral(self):
        self.assertIn(["witcher", "iv"], index._search_query_variants("Witcher 4"))
        self.assertIn(["witcher", "4"], index._search_query_variants("The Witcher IV"))

    def test_keeps_numeric_tokens(self):
        self.assertIn(["witcher", "3"], index._search_query_variants("Witcher 3"))
        self.assertIn(["grand", "theft", "auto", "6"], index._search_query_variants("GTA 6"))


class SearchApiTests(unittest.TestCase):
    def setUp(self):
        suffix = secrets.token_hex(6)
        self.client = TestClient(index.app, base_url="https://testserver")
        response = self.client.post("/api/auth/register", json={
            "email": f"search_{suffix}@example.com",
            "nickname": f"search_{suffix}",
            "pin": "12345678",
        })
        self.assertEqual(response.status_code, 201, response.text)
        self.game_id = secrets.randbelow(400_000_000) + 100_000_000

    def tearDown(self):
        self.client.close()

    def test_upcoming_gta_can_be_discovered_and_searched_locally(self):
        release_epoch = int(datetime(2031, 5, 26, tzinfo=timezone.utc).timestamp())
        captured = []

        def fake_igdb(url, *, headers, content, timeout):
            captured.append(content)
            self.assertEqual(url, "https://api.igdb.com/v4/games")
            self.assertIn('name ~ *"grand"*', content)
            self.assertIn('name ~ *"theft"*', content)
            self.assertIn('name ~ *"auto"*', content)
            self.assertIn('name ~ *"vi"*', content)
            self.assertIn("version_parent = null", content)

            class Response:
                status_code = 200

                def raise_for_status(self):
                    return None

                def json(inner_self):
                    return [{
                        "id": self.game_id,
                        "name": "Grand Theft Auto VI",
                        "first_release_date": release_epoch,
                        "cover": {"image_id": "testcover"},
                        "genres": [{"name": "Action"}],
                        "platforms": [{"name": "PC"}],
                    }]

            return Response()

        with patch.object(index, "_igdb_access_token", return_value=("client", "token")):
            with patch.object(index.httpx, "post", side_effect=fake_igdb):
                response = self.client.get("/api/games/search", params={"q": "GTA 6", "source": "igdb"})

        self.assertEqual(response.status_code, 200, response.text)
        items = response.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Grand Theft Auto VI")
        self.assertEqual(items[0]["releaseDate"], "2031-05-26")
        self.assertEqual(len(captured), 1)

        cached = self.client.get("/api/games/search", params={"q": "GTA 6", "source": "local"})
        self.assertEqual(cached.status_code, 200, cached.text)
        self.assertIn(self.game_id, [item["id"] for item in cached.json()["items"]])

    def test_local_search_witcher_4_finds_roman_title(self):
        from api.database import SessionLocal
        from api.models import Game

        with SessionLocal() as session:
            session.add(Game(igdb_id=self.game_id, title="The Witcher IV"))
            session.commit()

        response = self.client.get("/api/games/search", params={"q": "Witcher 4", "source": "local"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(self.game_id, [item["id"] for item in response.json()["items"]])


if __name__ == "__main__":
    unittest.main()
