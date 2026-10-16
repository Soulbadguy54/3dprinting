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


    def test_export_is_auth_scoped_and_contains_collection_membership(self):
        anonymous = TestClient(index.app, base_url="https://testserver")
        self.assertEqual(anonymous.get("/api/export").status_code, 401)
        anonymous.close()

        collection = self.client.post("/api/collections", json={"title": "Backup source"}).json()["id"]
        self.assertEqual(self.client.put(
            f"/api/library/{self.game_id}/collections/{collection}"
        ).status_code, 200)
        result = self.client.get("/api/export")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIn("attachment;", result.headers.get("content-disposition", ""))
        self.assertEqual(result.json()["format"], "rateapp-export")
        self.assertEqual(result.json()["schemaVersion"], 1)
        self.assertEqual(result.json()["nickname"], self.nickname)
        match = next(x for x in result.json()["library"] if x["gameId"] == self.game_id)
        self.assertEqual(match["collectionIds"], [collection])
        self.assertNotIn("pinHash", str(result.json()))
        self.assertNotIn("session", str(result.json()))

    def test_same_status_edit_preserves_exact_collection_membership_rows(self):
        from sqlalchemy import func
        collection = self.client.post("/api/collections", json={"title": "Stable membership"}).json()["id"]
        path = f"/api/library/{self.game_id}"
        data = {
            "status": "completed", "platform": "PC", "completedAt": "2026-10-15",
            "collectionIds": [collection], "atmosphereScore": 8, "storyScore": 8,
            "technologyScore": 8, "gameplayScore": 8,
        }
        self.assertEqual(self.client.put(path, json=data).status_code, 200)
        with SessionLocal() as session:
            user_game = session.scalar(select(UserGame).join(User).where(
                User.nickname == self.nickname, UserGame.game.has(Game.igdb_id == self.game_id),
            ))
            original_id = session.scalar(select(CollectionGame.id).join(
                Collection, Collection.id == CollectionGame.collection_id
            ).where(
                Collection.slug == collection,
                CollectionGame.user_game_id == user_game.id,
            ))
        edited = self.client.put(path, json={**data, "review": "Edit without collection changes"})
        self.assertEqual(edited.status_code, 200, edited.text)
        with SessionLocal() as session:
            new_id = session.scalar(select(CollectionGame.id).where(
                CollectionGame.user_game_id == user_game.id
            ))
        self.assertEqual(original_id, new_id)

    def test_complete_ratings_are_required_for_finished_or_dropped(self):
        path = f"/api/library/{self.game_id}"
        for status in ("completed", "dropped"):
            missing = self.client.put(path, json={"status": status, "score": 8})
            self.assertEqual(missing.status_code, 422, missing.text)
        self.assertEqual(self.client.get("/api/library").json(), [])

    def test_score_is_computed_and_unrated_statuses_reject_ratings(self):
        path = f"/api/library/{self.game_id}"
        rated = self.client.put(path, json={
            "status": "completed", "score": 10, "platform": "PC",
            "completedAt": "2026-10-15",
            "atmosphereScore": 8, "storyScore": 9,
            "technologyScore": 7, "gameplayScore": 6,
        })
        self.assertEqual(rated.status_code, 200, rated.text)
        self.assertEqual(rated.json()["score"], 7.5)
        impossible = self.client.put(path, json={
            "status": "playing", "atmosphereScore": 5,
        })
        self.assertEqual(impossible.status_code, 422, impossible.text)
        bad_date = self.client.put(path, json={
            "status": "playing", "completedAt": "2026-01-01",
        })
        self.assertEqual(bad_date.status_code, 422, bad_date.text)

    def test_database_rejects_incomplete_ratings_even_without_api(self):
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError
        with SessionLocal() as session:
            user_id = session.scalar(select(User.id).where(User.nickname == self.nickname))
            game_id = session.scalar(select(Game.id).where(Game.igdb_id == self.game_id))
            with self.assertRaises(IntegrityError):
                session.execute(text("""
                    INSERT INTO user_games (user_id, game_id, status, score)
                    VALUES (:u, :g, 'completed', 9.0)
                """), {"u": user_id, "g": game_id})
            session.rollback()

    def test_missing_playthrough_platform_and_dates_are_rejected(self):
        game_url = f"/api/library/{self.game_id}"
        ratings = {
            "atmosphereScore": 8, "storyScore": 8,
            "technologyScore": 8, "gameplayScore": 8,
        }
        for status in ("completed", "dropped"):
            for bad in (
                {"platform": "", "completedAt": "2026-10-15"},
                {"platform": "PC"},
                {"platform": "   ", "completedAt": "2026-10-15"},
            ):
                response = self.client.put(game_url, json={
                    "status": status, **ratings, **bad,
                })
                self.assertEqual(response.status_code, 422, response.text)

        for bad in (
            {"status": "wishlist", "platform": "PC"},
        ):
            response = self.client.put(game_url, json=bad)
            self.assertEqual(response.status_code, 422, response.text)
        # The existing "Прохожу" UI has no date input, so the API accepts
        # both fields as optional instead of requiring a nonexistent input.
        response = self.client.put(game_url, json={"status": "playing"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["platform"])
        self.assertIsNone(response.json()["startedAt"])

    def test_database_enforces_platform_dates_and_collection_display_fields(self):
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError

        with SessionLocal() as session:
            user_id = session.scalar(select(User.id).where(User.nickname == self.nickname))
            game_id = session.scalar(select(Game.id).where(Game.igdb_id == self.game_id))
            with self.assertRaises(IntegrityError):
                session.execute(text("""
                    INSERT INTO user_games (
                        user_id, game_id, status,
                        atmosphere_score, story_score,
                        technology_score, gameplay_score, score
                    )
                    VALUES (:u, :g, 'completed', 8, 8, 8, 8, 8)
                """), {"u": user_id, "g": game_id})
            session.rollback()

            for field, value in (
                ("title", ""),
                ("title", None),
                ("color_scheme", "unknown"),
                ("color_scheme", None),
            ):
                values = {
                    "uid": user_id, "slug": f"test_integrity_{field}_{value}",
                    "title": "Valid", "color": "violet",
                }
                if field == "title":
                    values["title"] = value
                else:
                    values["color"] = value
                with self.assertRaises(IntegrityError):
                    session.execute(text("""
                        INSERT INTO collections (user_id, slug, title, color_scheme)
                        VALUES (:uid, :slug, :title, :color)
                    """), values)
                session.rollback()

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


    def test_last_activity_changes_only_when_playthrough_status_changes(self):
        """Collection actions, same-status edits, and dates cannot bump activity."""
        from datetime import datetime, timezone, timedelta
        from unittest.mock import patch

        path = f"/api/library/{self.game_id}"
        collection = self.client.post("/api/collections", json={"title": "Activity check"}).json()["id"]
        first = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)
        second = first + timedelta(days=1)
        third = second + timedelta(hours=2)
        fourth = third + timedelta(hours=3)

        # Collection-only games have no activity until given a playthrough status.
        with patch.object(index, "_now", return_value=first):
            added = self.client.put(f"/api/library/{self.game_id}/collections/{collection}")
        self.assertEqual(added.status_code, 200, added.text)
        self.assertIsNone(added.json()["entry"]["statusChangedAt"])

        with patch.object(index, "_now", return_value=first):
            playing = self.client.put(path, json={
                "status": "playing", "collectionIds": [collection],
            })
        self.assertEqual(playing.status_code, 200, playing.text)
        self.assertEqual(playing.json()["statusChangedAt"], first.isoformat())

        # Collection membership changes leave the status timestamp unchanged.
        wish = self.client.put(f"/api/library/{self.game_id}/wishlist")
        self.assertEqual(wish.status_code, 200, wish.text)
        self.assertEqual(wish.json()["entry"]["statusChangedAt"], first.isoformat())
        un_wish = self.client.delete(f"/api/library/{self.game_id}/wishlist")
        self.assertEqual(un_wish.status_code, 200, un_wish.text)
        self.assertEqual(un_wish.json()["entry"]["statusChangedAt"], first.isoformat())
        same = self.client.patch(f"/api/collections/{collection}", json={
            "description": "Edited collection only",
        })
        self.assertEqual(same.status_code, 200, same.text)
        self.assertEqual(same.json()["library"][0]["statusChangedAt"], first.isoformat())

        with patch.object(index, "_now", return_value=second):
            edited_playing = self.client.put(path, json={
                "status": "playing", "platform": "PC", "collectionIds": [collection],
                "startedAt": "2025-06-01",
            })
        self.assertEqual(edited_playing.status_code, 200, edited_playing.text)
        self.assertEqual(edited_playing.json()["statusChangedAt"], first.isoformat())

        ratings = {
            "atmosphereScore": 8, "storyScore": 8,
            "technologyScore": 8, "gameplayScore": 8,
        }
        with patch.object(index, "_now", return_value=third):
            completed = self.client.put(path, json={
                "status": "completed", "platform": "PC", "completedAt": "2020-03-12",
                "collectionIds": [collection], **ratings,
            })
        self.assertEqual(completed.status_code, 200, completed.text)
        self.assertEqual(completed.json()["statusChangedAt"], third.isoformat())
        self.assertEqual(completed.json()["completedAt"], "2020-03-12")

        # Adjusting the completion date or ratings does not become new activity.
        with patch.object(index, "_now", return_value=fourth):
            edited_rating = self.client.put(path, json={
                "status": "completed", "platform": "PS5", "completedAt": "2026-10-15",
                "collectionIds": [collection], **ratings,
            })
        self.assertEqual(edited_rating.status_code, 200, edited_rating.text)
        self.assertEqual(edited_rating.json()["statusChangedAt"], third.isoformat())

        with patch.object(index, "_now", return_value=fourth):
            dropped = self.client.put(path, json={
                "status": "dropped", "platform": "PC", "completedAt": "2021-01-01",
                "collectionIds": [collection], **ratings,
            })
        self.assertEqual(dropped.status_code, 200, dropped.text)
        self.assertEqual(dropped.json()["statusChangedAt"], fourth.isoformat())

        # All serialization paths use the same timestamp.
        library = self.client.get("/api/library")
        self.assertEqual(library.status_code, 200)
        self.assertEqual(library.json()[0]["statusChangedAt"], fourth.isoformat())
        bootstrap = self.client.get("/api/bootstrap")
        self.assertEqual(bootstrap.status_code, 200)
        match = next(e for e in bootstrap.json()["library"] if e["gameId"] == self.game_id)
        self.assertEqual(match["statusChangedAt"], fourth.isoformat())

        # Deleting a playthrough with memberships retains only its collection
        # placeholder and clears the activity date.
        deleted = self.client.delete(path)
        self.assertEqual(deleted.status_code, 204)
        placeholder = self.client.get("/api/library").json()[0]
        self.assertEqual(placeholder["status"], "untracked")
        self.assertIsNone(placeholder["statusChangedAt"])

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
            "atmosphereScore": 6.5, "storyScore": 6.5,
            "technologyScore": 6.5, "gameplayScore": 6.5,
            "collectionIds": [],
        })
        self.assertEqual(dropped.status_code, 200, dropped.text)
        self.assertEqual(dropped.json()["status"], "dropped")
        self.assertEqual(dropped.json()["completedAt"], "2026-01-14")
        self.assertEqual(dropped.json()["score"], 6.5)

        changed = self.client.put(path, json={
            "status": "dropped", "platform": "PC",
            "completedAt": "2026-02-20", "collectionIds": [],
            "atmosphereScore": 6.5, "storyScore": 6.5,
            "technologyScore": 6.5, "gameplayScore": 6.5,
        })
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()["completedAt"], "2026-02-20")
        library = self.client.get("/api/library").json()
        saved = next(row for row in library if row["gameId"] == self.game_id)
        self.assertEqual(saved["completedAt"], "2026-02-20")

        playing = self.client.put(path, json={
            "status": "playing", "platform": "PC",
            "startedAt": "2026-02-21", "collectionIds": [],
        })
        self.assertEqual(playing.status_code, 200, playing.text)
        self.assertIsNone(playing.json()["completedAt"])
        self.assertEqual(playing.json()["startedAt"], "2026-02-21")

    def test_custom_membership_preserves_completed_playthrough(self):
        saved = self.client.put(f"/api/library/{self.game_id}", json={
            "status": "completed", "score": 8.5, "platform": "PC", "collectionIds": [],
            "completedAt": "2026-10-15",
            "atmosphereScore": 8.5, "storyScore": 8.5,
            "technologyScore": 8.5, "gameplayScore": 8.5,
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
            "completedAt": "2026-10-15",
            "atmosphereScore": 9.0, "storyScore": 9.0,
            "technologyScore": 9.0, "gameplayScore": 9.0,
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
            "completedAt": "2026-10-15",
            "atmosphereScore": 9.0, "storyScore": 9.0,
            "technologyScore": 9.0, "gameplayScore": 9.0,
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


    def test_bulk_remove_collection_games_preserves_existing_progress(self):
        """One atomic PATCH removes three cards, but not other membership/rating data."""
        first = self.client.post("/api/collections", json={"title": "Bulk source"}).json()["id"]
        second = self.client.post("/api/collections", json={"title": "Still there"}).json()["id"]
        orphan_id, shared_id = self.game_id + 1, self.game_id + 2
        with SessionLocal() as session:
            session.add_all([
                Game(igdb_id=orphan_id, title="Bulk orphan"),
                Game(igdb_id=shared_id, title="Bulk shared"),
            ])
            session.commit()

        completed = self.client.put(f"/api/library/{self.game_id}", json={
            "status": "completed", "platform": "PC", "completedAt": "2026-10-15",
            "atmosphereScore": 9, "storyScore": 9,
            "technologyScore": 9, "gameplayScore": 9,
            "collectionIds": [first, second],
        })
        self.assertEqual(completed.status_code, 200, completed.text)
        for game_id, slugs in ((orphan_id, [first]), (shared_id, [first, second])):
            for slug in slugs:
                added = self.client.put(f"/api/library/{game_id}/collections/{slug}")
                self.assertEqual(added.status_code, 200, added.text)

        removed = self.client.patch(f"/api/collections/{first}", json={
            "removedGameIds": [self.game_id, orphan_id, shared_id],
        })
        self.assertEqual(removed.status_code, 200, removed.text)
        library = {entry["gameId"]: entry for entry in removed.json()["library"]}
        self.assertNotIn(orphan_id, library)  # Orphan placeholder can be safely dropped.
        self.assertEqual(library[self.game_id]["status"], "completed")
        self.assertEqual(library[self.game_id]["score"], 9)
        self.assertEqual(library[self.game_id]["platform"], "PC")
        self.assertEqual(library[self.game_id]["collectionIds"], [second])
        self.assertEqual(library[shared_id]["status"], "untracked")
        self.assertEqual(library[shared_id]["collectionIds"], [second])
        self.assertFalse(any(
            first in entry["collectionIds"] for entry in self.client.get("/api/library").json()
        ))

        # Same batch is idempotent; it must never create or delete other memberships.
        again = self.client.patch(f"/api/collections/{first}", json={
            "removedGameIds": [self.game_id, orphan_id, shared_id],
        })
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()["library"], removed.json()["library"])

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

    def test_collection_added_at_survives_playthrough_edits(self):
        game_path = f"/api/library/{self.game_id}"
        wished = self.client.put(f"{game_path}/wishlist")
        self.assertEqual(wished.status_code, 200, wished.text)
        initial = wished.json()["entry"]["collectionAddedAt"][WISHLIST_SLUG]
        self.assertTrue(initial)
        payload = {
            "status": "completed", "platform": "PC",
            "completedAt": "2026-10-15",
            "atmosphereScore": 8, "storyScore": 9,
            "technologyScore": 7, "gameplayScore": 8,
            "collectionIds": [WISHLIST_SLUG],
        }
        saved = self.client.put(game_path, json=payload)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["collectionAddedAt"][WISHLIST_SLUG], initial)
        edited = self.client.put(game_path, json={**payload, "review": "Updated"})
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(edited.json()["collectionAddedAt"][WISHLIST_SLUG], initial)
        library = self.client.get("/api/library")
        self.assertEqual(library.status_code, 200, library.text)
        self.assertEqual(library.json()[0]["collectionAddedAt"][WISHLIST_SLUG], initial)


if __name__ == "__main__":
    unittest.main()
