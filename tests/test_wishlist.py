"""Authenticated wishlist integration tests using the CI PostgreSQL database."""
import secrets
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import select

from api import index
from api.bootstrap import initialize_database
from api.database import SessionLocal
from api.models import Collection, CollectionGame, Game, User, UserGame, WISHLIST_SLUG


class WishlistApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(index.app, base_url="https://testserver")
        suffix = secrets.token_hex(6)
        self.nickname = f"test_{suffix}"
        registered = self.client.post("/api/auth/register", json={
            "email": f"{suffix}@example.com", "nickname": self.nickname, "pin": "12348765",
        })
        self.assertEqual(registered.status_code, 201, registered.text)

        self.game_id = secrets.randbelow(900_000_000) + 100_000_000
        with SessionLocal() as session:
            session.add(Game(igdb_id=self.game_id, title=f"QA game {suffix}"))
            session.commit()

    def tearDown(self):
        self.client.close()

    def test_default_collection_is_protected(self):
        data = self.client.get("/api/bootstrap").json()
        wishes = [item for item in data["collections"] if item["id"] == WISHLIST_SLUG]
        self.assertEqual(len(wishes), 1)
        self.assertTrue(wishes[0]["isSystem"])
        self.assertEqual(wishes[0]["title"], "Хочу пройти")
        forbidden = self.client.delete(f"/api/collections/{WISHLIST_SLUG}")
        self.assertEqual(forbidden.status_code, 403)

    def test_toggle_wishlist_is_idempotent(self):
        path = f"/api/library/{self.game_id}/wishlist"
        for _ in range(2):
            response = self.client.put(path)
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertTrue(data["inWishlist"])
            self.assertEqual(data["entry"]["status"], "wishlist")
            self.assertEqual(data["entry"]["collectionIds"].count(WISHLIST_SLUG), 1)

        library = self.client.get("/api/library").json()
        self.assertEqual(len([row for row in library if row["gameId"] == self.game_id]), 1)

        for _ in range(2):
            response = self.client.delete(path)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertFalse(response.json()["inWishlist"])
            self.assertIsNone(response.json()["entry"])
        library = self.client.get("/api/library").json()
        self.assertFalse(any(row["gameId"] == self.game_id for row in library))

    def test_existing_completion_keeps_status_and_rating(self):
        path = f"/api/library/{self.game_id}"
        completed = self.client.put(path, json={
            "status": "completed", "score": 9.0, "platform": "PC",
            "collectionIds": [],
        })
        self.assertEqual(completed.status_code, 200, completed.text)

        wished = self.client.put(path + "/wishlist").json()
        self.assertEqual(wished["entry"]["status"], "completed")
        self.assertIn(WISHLIST_SLUG, wished["entry"]["collectionIds"])

        removed = self.client.delete(path + "/wishlist").json()
        self.assertFalse(removed["inWishlist"])
        self.assertEqual(removed["entry"]["status"], "completed")
        self.assertEqual(removed["entry"]["score"], 9.0)
        self.assertEqual(removed["entry"]["platform"], "PC")
        self.assertNotIn(WISHLIST_SLUG, removed["entry"]["collectionIds"])

    def test_save_with_wishlist_status_creates_membership(self):
        path = f"/api/library/{self.game_id}"
        response = self.client.put(path, json={"status": "wishlist", "collectionIds": []})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(WISHLIST_SLUG, response.json()["collectionIds"])

    def test_ordinary_collection_can_be_deleted_without_touching_default(self):
        created = self.client.post("/api/collections", json={"title": "Отдельный список"})
        self.assertEqual(created.status_code, 201, created.text)
        slug = created.json()["id"]
        self.assertFalse(created.json()["isSystem"])
        self.assertEqual(self.client.delete(f"/api/collections/{slug}").status_code, 204)
        slugs = [row["id"] for row in self.client.get("/api/collections").json()]
        self.assertIn(WISHLIST_SLUG, slugs)
        self.assertNotIn(slug, slugs)

    def test_reinitialization_does_not_restore_manually_removed_item(self):
        path = f"/api/library/{self.game_id}"
        custom = self.client.post("/api/collections", json={"title": "Релизы"}).json()["id"]
        response = self.client.put(path, json={
            "status": "wishlist",
            "collectionIds": [custom],
        })
        self.assertEqual(response.status_code, 200, response.text)
        removed = self.client.delete(path + "/wishlist")
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertIsNotNone(removed.json()["entry"])
        self.assertNotIn(WISHLIST_SLUG, removed.json()["entry"]["collectionIds"])
        initialize_database()
        self.assertNotIn(
            WISHLIST_SLUG,
            next(row for row in self.client.get("/api/library").json() if row["gameId"] == self.game_id)["collectionIds"],
        )

    def test_different_user_cannot_see_wishlist(self):
        self.assertEqual(self.client.put(f"/api/library/{self.game_id}/wishlist").status_code, 200)
        second = TestClient(index.app, base_url="https://testserver")
        suffix = secrets.token_hex(6)
        try:
            register = second.post("/api/auth/register", json={
                "email": f"{suffix}@example.com", "nickname": f"other_{suffix}", "pin": "13572468",
            })
            self.assertEqual(register.status_code, 201, register.text)
            self.assertEqual(second.get("/api/library").json(), [])
            self.assertEqual(second.get("/api/collections").json()[0]["id"], WISHLIST_SLUG)
        finally:
            second.close()


if __name__ == "__main__":
    unittest.main()
