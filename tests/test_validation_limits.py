"""Input-length regressions: frontend limits are backed by API validation."""
import secrets
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import select

from api import index
from api.database import SessionLocal
from api.models import Collection, Game


class ValidationLimitsTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(index.app, base_url="https://testserver")
        suffix = secrets.token_hex(5)
        self.nickname = "v_" + suffix
        registration = self.client.post("/api/auth/register", json={
            "email": f"limit_{suffix}@example.com",
            "nickname": self.nickname,
            "pin": "12345678",
        })
        self.assertEqual(registration.status_code, 201, registration.text)

    def tearDown(self):
        self.client.close()

    def test_new_nickname_maximum_16_and_existing_login_unaffected(self):
        # Existing 16-character usernames are valid; 17 is rejected.
        suffix = secrets.token_hex(7)
        ok_nick = "v_" + suffix
        self.assertEqual(len(ok_nick), 16)
        registered = self.client.post("/api/auth/register", json={
            "email": f"new_{suffix}@example.com",
            "nickname": ok_nick,
            "pin": "12345678",
        })
        self.assertEqual(registered.status_code, 201, registered.text)
        rejected = self.client.post("/api/auth/register", json={
            "email": f"bad_{suffix}@example.com",
            "nickname": ok_nick + "z",
            "pin": "12345678",
        })
        self.assertEqual(rejected.status_code, 422, rejected.text)
        self.assertIn("nickname", rejected.text)

    def test_collection_title_32_create_and_update(self):
        name = "И" * 32
        created = self.client.post("/api/collections", json={"title": name})
        self.assertEqual(created.status_code, 201, created.text)
        slug = created.json()["id"]

        rejected = self.client.post("/api/collections", json={"title": name + "Я"})
        self.assertEqual(rejected.status_code, 422, rejected.text)
        self.assertIn("title", rejected.text)

        updated = self.client.patch(f"/api/collections/{slug}", json={"title": "А" * 32})
        self.assertEqual(updated.status_code, 200, updated.text)
        failed = self.client.patch(f"/api/collections/{slug}", json={"title": "Б" * 33})
        self.assertEqual(failed.status_code, 422, failed.text)
        self.assertEqual(
            next(x for x in self.client.get("/api/collections").json() if x["id"] == slug)["title"],
            "А" * 32,
        )

    def test_existing_long_collection_title_can_keep_description(self):
        row = self.client.post("/api/collections", json={"title": "До изменений"})
        self.assertEqual(row.status_code, 201, row.text)
        slug = row.json()["id"]
        with SessionLocal() as session:
            collection = session.scalar(select(Collection).where(Collection.slug == slug))
            collection.title = "Уже сохранённое название длиннее лимита"
            session.commit()
        updated = self.client.patch(f"/api/collections/{slug}", json={"description": "Новая подпись"})
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["collection"]["description"], "Новая подпись")

    def test_description_and_review_limits(self):
        too_long = self.client.post("/api/collections", json={
            "title": "Обычная", "description": "а" * 501,
        })
        self.assertEqual(too_long.status_code, 422, too_long.text)
        rejected = self.client.put("/api/library/1234567", json={
            "status": "completed", "review": "x" * 5001,
        })
        self.assertEqual(rejected.status_code, 422, rejected.text)

    def test_platform_memberships_and_search_are_bounded(self):
        platform = self.client.put("/api/library/1234567", json={
            "status": "completed", "platform": "P" * 81,
        })
        self.assertEqual(platform.status_code, 422, platform.text)
        too_many = self.client.put("/api/library/1234567", json={
            "status": "completed", "collectionIds": ["wishlist"] * 101,
        })
        self.assertEqual(too_many.status_code, 422, too_many.text)
        search = self.client.get("/api/games/search", params={"q": "z" * 101})
        self.assertEqual(search.status_code, 422, search.text)


if __name__ == "__main__":
    unittest.main()
