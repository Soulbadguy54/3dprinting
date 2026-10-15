"""Authenticated wishlist integration tests using the CI PostgreSQL database."""
import base64
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
        suffix = secrets.token_hex(5)
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

    def test_system_collection_only_allows_removing_games(self):
        self.client.put(f"/api/library/{self.game_id}/wishlist")
        path = f"/api/collections/{WISHLIST_SLUG}"
        changes = {"title": "Изменённое название", "removedGameIds": [self.game_id]}
        forbidden = self.client.patch(path, json=changes)
        self.assertEqual(forbidden.status_code, 403, forbidden.text)
        self.assertIn(WISHLIST_SLUG, self.client.get("/api/library").json()[0]["collectionIds"])

        allowed = self.client.patch(path, json={"removedGameIds": [self.game_id]})
        self.assertEqual(allowed.status_code, 200, allowed.text)
        self.assertEqual(allowed.json()["collection"]["title"], "Хочу пройти")
        self.assertFalse(any(
            WISHLIST_SLUG in entry["collectionIds"] for entry in allowed.json()["library"]
        ))

    def test_custom_collection_membership_toggle_is_idempotent(self):
        first = self.client.post("/api/collections", json={
            "title": "Моя коллекция", "emoji": "🎮", "colorScheme": "teal",
        })
        self.assertEqual(first.status_code, 201, first.text)
        second = self.client.post("/api/collections", json={"title": "Другие игры"})
        self.assertEqual(second.status_code, 201, second.text)

        first_path = f"/api/library/{self.game_id}/collections/{first.json()['id']}"
        second_path = f"/api/library/{self.game_id}/collections/{second.json()['id']}"
        for _ in range(2):
            added = self.client.put(first_path)
            self.assertEqual(added.status_code, 200, added.text)
            self.assertTrue(added.json()["inCollection"])
            self.assertEqual(added.json()["entry"]["status"], "untracked")
            self.assertEqual(added.json()["entry"]["collectionIds"].count(first.json()["id"]), 1)

        also_added = self.client.put(second_path)
        self.assertEqual(also_added.status_code, 200, also_added.text)
        removed = self.client.delete(first_path)
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertEqual(removed.json()["entry"]["collectionIds"], [second.json()["id"]])

        for _ in range(2):
            last_removed = self.client.delete(second_path)
            self.assertEqual(last_removed.status_code, 200, last_removed.text)
            self.assertIsNone(last_removed.json()["entry"])
        self.assertFalse(any(
            entry["gameId"] == self.game_id for entry in self.client.get("/api/library").json()
        ))

    def test_dropped_playthrough_date_is_saved_and_can_be_edited(self):
        path = f"/api/library/{self.game_id}"
        dropped = self.client.put(path, json={
            "status": "dropped", "platform": "PC",
            "completedAt": "2026-01-14", "score": 6.5,
            "collectionIds": [],
        })
        self.assertEqual(dropped.status_code, 200, dropped.text)
        self.assertEqual(dropped.json()["status"], "dropped")
        self.assertEqual(dropped.json()["completedAt"], "2026-01-14")
        self.assertEqual(dropped.json()["score"], 6.5)

        changed = self.client.put(path, json={
            "status": "dropped", "platform": "PC",
            "completedAt": "2026-02-20", "collectionIds": [],
        })
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()["completedAt"], "2026-02-20")
        library = self.client.get("/api/library").json()
        saved = next(row for row in library if row["gameId"] == self.game_id)
        self.assertEqual(saved["completedAt"], "2026-02-20")

        playing = self.client.put(path, json={
            "status": "playing", "startedAt": "2026-02-21",
            "collectionIds": [],
        })
        self.assertEqual(playing.status_code, 200, playing.text)
        self.assertIsNone(playing.json()["completedAt"])
        self.assertEqual(playing.json()["startedAt"], "2026-02-21")

    def test_custom_membership_preserves_completed_playthrough(self):
        saved = self.client.put(f"/api/library/{self.game_id}", json={
            "status": "completed", "score": 8.5, "platform": "PC", "collectionIds": [],
        })
        self.assertEqual(saved.status_code, 200, saved.text)
        collection = self.client.post("/api/collections", json={"title": "Избранное"}).json()
        path = f"/api/library/{self.game_id}/collections/{collection['id']}"
        self.assertEqual(self.client.put(path).status_code, 200)
        removed = self.client.delete(path)
        self.assertEqual(removed.status_code, 200, removed.text)
        entry = removed.json()["entry"]
        self.assertEqual(entry["status"], "completed")
        self.assertEqual(entry["score"], 8.5)
        self.assertEqual(entry["platform"], "PC")
        self.assertNotIn(collection["id"], entry["collectionIds"])

    def test_toggle_wishlist_is_idempotent(self):
        path = f"/api/library/{self.game_id}/wishlist"
        for _ in range(2):
            response = self.client.put(path)
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertTrue(data["inWishlist"])
            self.assertEqual(data["entry"]["status"], "untracked")
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


    def test_collection_theme_icon_and_sort_order(self):
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
        )
        icon = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        response = self.client.post("/api/collections", json={
            "title": "Яблоко", "description": "Яркий список",
            "colorScheme": "cyan", "iconData": icon,
        })
        self.assertEqual(response.status_code, 201, response.text)
        created = response.json()
        self.assertEqual(created["colorScheme"], "cyan")
        self.assertEqual(created["iconData"], icon)

        second = self.client.post("/api/collections", json={
            "title": "Альфа", "colorScheme": "amber",
        })
        self.assertEqual(second.status_code, 201, second.text)
        self.assertIsNone(second.json()["iconData"])

        collections = self.client.get("/api/collections").json()
        self.assertEqual(collections[0]["id"], WISHLIST_SLUG)
        filtered = [row for row in collections if row["id"] in {created["id"], second.json()["id"]}]
        self.assertEqual([row["title"] for row in filtered], ["Альфа", "Яблоко"])
        self.assertEqual(filtered[1]["iconData"], icon)

    def test_collection_upload_validation(self):
        wrong_color = self.client.post("/api/collections", json={
            "title": "Неверный цвет", "colorScheme": "unknown",
        })
        self.assertEqual(wrong_color.status_code, 422)

        unsafe = self.client.post("/api/collections", json={
            "title": "Небезопасный формат",
            "iconData": "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=",
        })
        self.assertEqual(unsafe.status_code, 422)

        invalid_bytes = self.client.post("/api/collections", json={
            "title": "Неверная картинка",
            "iconData": "data:image/png;base64," + base64.b64encode(b"not-a-png").decode("ascii"),
        })
        self.assertEqual(invalid_bytes.status_code, 422)

    def test_edit_collection_updates_emoji_color_and_name(self):
        created = self.client.post("/api/collections", json={
            "title": "Изначально", "colorScheme": "violet",
        })
        self.assertEqual(created.status_code, 201, created.text)
        slug = created.json()["id"]
        changed = self.client.patch(f"/api/collections/{slug}", json={
            "title": "Новая коллекция", "description": "Описание обновлено",
            "emoji": "🎮", "colorScheme": "cyan", "removedGameIds": [],
        })
        self.assertEqual(changed.status_code, 200, changed.text)
        updated = changed.json()["collection"]
        self.assertEqual(updated["title"], "Новая коллекция")
        self.assertEqual(updated["description"], "Описание обновлено")
        self.assertEqual(updated["emoji"], "🎮")
        self.assertEqual(updated["colorScheme"], "cyan")
        self.assertIsNone(updated["iconData"])
        self.assertEqual(
            next(row for row in self.client.get("/api/collections").json() if row["id"] == slug)["emoji"],
            "🎮",
        )

    def test_remove_collection_game_keeps_playthrough_and_other_collections(self):
        first = self.client.post("/api/collections", json={"title": "Первая"}).json()["id"]
        second = self.client.post("/api/collections", json={"title": "Вторая"}).json()["id"]
        saved = self.client.put(f"/api/library/{self.game_id}", json={
            "status": "completed", "platform": "PC", "score": 9.0,
            "collectionIds": [first, second],
        })
        self.assertEqual(saved.status_code, 200, saved.text)
        result = self.client.patch(f"/api/collections/{first}", json={
            "title": "Первая", "description": "", "colorScheme": "rose",
            "emoji": "🏆", "removedGameIds": [self.game_id],
        })
        self.assertEqual(result.status_code, 200, result.text)
        entry = next(row for row in result.json()["library"] if row["gameId"] == self.game_id)
        self.assertEqual(entry["status"], "completed")
        self.assertEqual(entry["platform"], "PC")
        self.assertEqual(entry["score"], 9.0)
        self.assertNotIn(first, entry["collectionIds"])
        self.assertIn(second, entry["collectionIds"])

        # Deleting the collection must likewise leave the real game record intact.
        self.assertEqual(self.client.delete(f"/api/collections/{second}").status_code, 204)
        after = next(row for row in self.client.get("/api/library").json() if row["gameId"] == self.game_id)
        self.assertEqual(after["status"], "completed")
        self.assertEqual(after["collectionIds"], [])

    def test_remove_collection_only_game_prunes_orphan_record(self):
        slug = self.client.post("/api/collections", json={"title": "Ожидаю"}).json()["id"]
        self.assertEqual(self.client.put(f"/api/library/{self.game_id}", json={
            "status": "wishlist", "collectionIds": [slug],
        }).status_code, 200)
        self.assertEqual(self.client.delete(f"/api/library/{self.game_id}/wishlist").status_code, 200)
        result = self.client.patch(f"/api/collections/{slug}", json={
            "title": "Ожидаю", "description": "", "colorScheme": "amber",
            "emoji": "🌌", "removedGameIds": [self.game_id],
        })
        self.assertEqual(result.status_code, 200, result.text)
        self.assertFalse(any(row["gameId"] == self.game_id for row in result.json()["library"]))

    def test_wishlist_theme_is_immutable_and_survives_bootstrap(self):
        original = self.client.get("/api/collections").json()[0]
        changed = self.client.patch(f"/api/collections/{WISHLIST_SLUG}", json={
            "title": "Хочу поиграть", "description": "Мои планы",
            "emoji": "🎁", "colorScheme": "violet", "removedGameIds": [],
        })
        self.assertEqual(changed.status_code, 403, changed.text)
        initialize_database()
        first = self.client.get("/api/collections").json()[0]
        self.assertEqual(first["id"], WISHLIST_SLUG)
        self.assertEqual(first["title"], original["title"])
        self.assertEqual(first["description"], original["description"])
        self.assertEqual(first["colorScheme"], original["colorScheme"])
        self.assertEqual(first["emoji"], original["emoji"])
        self.assertEqual(self.client.delete(f"/api/collections/{WISHLIST_SLUG}").status_code, 403)

    def test_collection_update_does_not_accept_unauthorized_user(self):
        slug = self.client.post("/api/collections", json={"title": "Приватная"}).json()["id"]
        second = TestClient(index.app, base_url="https://testserver")
        suffix = secrets.token_hex(5)
        try:
            register = second.post("/api/auth/register", json={
                "email": f"{suffix}@example.com", "nickname": f"other_{suffix}", "pin": "13572468",
            })
            self.assertEqual(register.status_code, 201, register.text)
            response = second.patch(f"/api/collections/{slug}", json={
                "title": "Чужая", "description": "", "colorScheme": "blue",
                "emoji": "⭐", "removedGameIds": [self.game_id],
            })
            self.assertEqual(response.status_code, 404)
        finally:
            second.close()

    def test_different_user_cannot_see_wishlist(self):
        self.assertEqual(self.client.put(f"/api/library/{self.game_id}/wishlist").status_code, 200)
        second = TestClient(index.app, base_url="https://testserver")
        suffix = secrets.token_hex(5)
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
