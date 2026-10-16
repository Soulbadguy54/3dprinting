"""IGDB integration, search, metadata caching and genre endpoints.

IGDB owns the canonical external game ID; cached PostgreSQL records avoid
repeating external requests. All external calls have network timeouts.
"""
import json
import math
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import case, delete, func, or_, select, text

from api.security import _session, _current_user, _now
from api.library_service import _community_rating_map, _game_payload
from api.models import Game, GameAlias, GameGenre, Genre, GenreCatalogSync

router = APIRouter()

_igdb_token: str | None = None
_igdb_token_expires_at = 0.0


def _igdb_credentials() -> tuple[str, str]:
    client_id = os.getenv("IGDB_CLIENT_ID", "").strip()
    client_secret = os.getenv("IGDB_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=503,
            detail="IGDB ещё не настроен. Добавьте IGDB_CLIENT_ID и IGDB_CLIENT_SECRET в Vercel.",
        )
    return client_id, client_secret


def _igdb_access_token() -> tuple[str, str]:
    global _igdb_token, _igdb_token_expires_at

    client_id, client_secret = _igdb_credentials()
    if _igdb_token and time.time() < _igdb_token_expires_at - 60:
        return client_id, _igdb_token

    try:
        response = httpx.post(
            "https://id.twitch.tv/oauth2/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10.0,
        )
        if response.status_code >= 400:
            message = ""
            try:
                message = str(response.json().get("message") or "")
            except ValueError:
                pass

            if response.status_code == 400:
                raise HTTPException(
                    status_code=502,
                    detail="Twitch отклонил Client ID/Secret. Создайте новый Client Secret и обновите переменные Vercel.",
                )

            raise HTTPException(
                status_code=502,
                detail=f"Ошибка Twitch OAuth ({response.status_code})"
                + (f": {message}" if message else "."),
            )

        payload = response.json()
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Не удалось связаться с Twitch OAuth.") from exc

    token = payload.get("access_token")
    if not token:
        raise HTTPException(status_code=502, detail="IGDB не вернул access token.")

    _igdb_token = str(token)
    _igdb_token_expires_at = time.time() + int(payload.get("expires_in", 3600))
    return client_id, _igdb_token


def _igdb_cover(image_id: str | None) -> str | None:
    if not image_id:
        return None
    return f"https://images.igdb.com/igdb/image/upload/t_cover_big_2x/{image_id}.jpg"


def _cache_igdb_games(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    with _session() as session:
        ids = [int(row["id"]) for row in rows]
        existing = {
            game.igdb_id: game
            for game in session.scalars(select(Game).where(Game.igdb_id.in_(ids))).all()
        }
        cached_games: list[Game] = []
        incoming_genres: dict[int, str] = {}
        incoming_game_genres: dict[int, list[int]] = {}

        for row in rows:
            igdb_id = int(row["id"])
            game = existing.get(igdb_id)
            if game is None:
                game = Game(igdb_id=igdb_id, title=str(row.get("name") or "Unknown"))
                session.add(game)
                existing[igdb_id] = game

            first_release = row.get("first_release_date")
            release_date = (
                datetime.fromtimestamp(int(first_release), tz=timezone.utc).date()
                if first_release
                else None
            )
            genres = [
                str(item.get("name"))
                for item in (row.get("genres") or [])
                if isinstance(item, dict) and item.get("name")
            ]
            platforms = [
                str(item.get("name"))
                for item in (row.get("platforms") or [])
                if isinstance(item, dict) and item.get("name")
            ]
            developers = []
            for item in row.get("involved_companies") or []:
                if not isinstance(item, dict) or not item.get("developer"):
                    continue
                company = item.get("company")
                if isinstance(company, dict) and company.get("name"):
                    developers.append(str(company["name"]))

            cover = row.get("cover")
            image_id = cover.get("image_id") if isinstance(cover, dict) else None

            game.title = str(row.get("name") or game.title)
            game.release_date = release_date
            game.igdb_rating = row.get("rating")
            game.popularity_count = max(
                int(row.get("total_rating_count") or 0),
                int(row.get("rating_count") or 0),
            )
            game.hype_count = int(row.get("hypes") or 0)
            game.cover_url = _igdb_cover(str(image_id)) if image_id else None
            game.developer = developers[0] if developers else None
            game.genres_json = json.dumps(genres, ensure_ascii=False)
            if "genres" in row:
                genre_ids: list[int] = []
                for genre_row in row.get("genres") or []:
                    if not isinstance(genre_row, dict):
                        continue
                    gid, name = genre_row.get("id"), genre_row.get("name")
                    if isinstance(gid, int) and isinstance(name, str) and name.strip():
                        incoming_genres[gid] = name.strip()
                        genre_ids.append(gid)
                incoming_game_genres[igdb_id] = list(dict.fromkeys(genre_ids))
            game.platforms_json = json.dumps(platforms, ensure_ascii=False)

            # IGDB search provides store/trailer metadata in the same query.
            # Persist it immediately so search and library cards can display
            # links on first open without waiting for the details endpoint.
            if "websites" in row and "videos" in row:
                fresh_details = (
                    game.details_cached_at is not None
                    and game.details_cached_at.replace(
                        tzinfo=game.details_cached_at.tzinfo or timezone.utc
                    ) > _now() - timedelta(days=GAME_DETAILS_CACHE_DAYS)
                )
                if not fresh_details:
                    previous = json.loads(game.details_json) if game.details_json else None
                    previous = previous if isinstance(previous, dict) else {}
                    details = {
                        "storeLinks": _safe_store_links(row.get("websites")),
                        "trailerUrl": _safe_trailer_url(row.get("videos")),
                        "storyHours": previous.get("storyHours"),
                        "completionHours": previous.get("completionHours"),
                        "_linksOnly": True,
                    }
                    game.details_json = json.dumps(details, ensure_ascii=False)
                    game.details_cached_at = _now()

            cached_games.append(game)

        session.flush()
        if incoming_genres:
            session.execute(text("""
                INSERT INTO genres (id, name) VALUES (:id, :name)
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
            """), [{"id":gid, "name":name} for gid, name in incoming_genres.items()])
        if incoming_game_genres:
            affected = [existing[igdb_id].id for igdb_id in incoming_game_genres]
            session.execute(delete(GameGenre).where(GameGenre.game_id.in_(affected)))
            session.add_all(
                GameGenre(game_id=existing[igdb_id].id, genre_id=gid)
                for igdb_id, ids in incoming_game_genres.items()
                for gid in ids
            )
            session.flush()

        for row in rows:
            # Persist publisher/IGDB-provided alternative names, not handcrafted
            # abbreviations or special cases for individual games.
            if "alternative_names" not in row:
                continue
            game = existing[int(row["id"])]
            session.execute(delete(GameAlias).where(GameAlias.game_id == game.id))
            seen = {game.title.casefold()}
            for alternative in row.get("alternative_names") or []:
                name = alternative.get("name", "").strip() if isinstance(alternative, dict) else ""
                if not name or len(name) > 255 or name.casefold() in seen:
                    continue
                seen.add(name.casefold())
                session.add(GameAlias(game_id=game.id, name=name))

        ratings = _community_rating_map(session, [game.id for game in cached_games])
        cached = [_game_payload(game, ratings.get(game.id)) for game in cached_games]
        session.commit()
        return cached


def _normalized_search_text(value: str) -> str:
    return re.sub(r"[^\w]+", " ", value.casefold(), flags=re.UNICODE).strip()


def _local_game_search(session, query: str, offset: int) -> dict[str, object]:
    """Rank cached games in PostgreSQL using indexed trigram similarity.

    Both game titles and their IGDB-provided alternative names participate.
    Title relevance wins; popularity breaks near ties. No franchise-specific
    mappings are involved.
    """
    search_text = _normalized_search_text(query)
    if not search_text:
        return {"items": [], "hasMore": False, "nextOffset": None}

    title = func.lower(Game.title)
    alias = func.lower(GameAlias.name)

    def relevance(name):
        return func.greatest(
            func.similarity(name, search_text),
            func.word_similarity(search_text, name),
        )

    alias_best = (
        select(func.max(relevance(alias)))
        .where(GameAlias.game_id == Game.id)
        .correlate(Game)
        .scalar_subquery()
    )
    score = func.greatest(relevance(title), func.coalesce(alias_best, 0.0))
    exact_alias = (
        select(GameAlias.id)
        .where(GameAlias.game_id == Game.id, alias == search_text)
        .correlate(Game)
        .exists()
    )
    popularity = (
        func.ln(1 + Game.popularity_count)
        + func.ln(1 + Game.hype_count) * 0.65
    )
    # PostgreSQL can use our GIN pg_trgm indexes to shortlist candidates,
    # instead of scoring every game and every alias on a full table scan.
    alias_candidate = (
        select(GameAlias.id)
        .where(
            GameAlias.game_id == Game.id,
            or_(alias.op("%")(search_text), alias.op("%>")(search_text)),
        )
        .correlate(Game)
        .exists()
    )
    title_candidate = or_(
        title.op("%")(search_text), title.op("%>")(search_text),
    )
    rows = session.scalars(
        select(Game)
        .where(or_(title_candidate, alias_candidate), score >= 0.32)
        .order_by(
            case(
                (title == search_text, 0),
                (exact_alias, 0),
                (title.startswith(search_text), 1),
                else_=2,
            ),
            (score + popularity * 0.012).desc(),
            popularity.desc(),
            Game.id,
        )
        .offset(offset)
        .limit(GAME_SEARCH_PAGE_SIZE + 1)
    ).all()
    has_more = len(rows) > GAME_SEARCH_PAGE_SIZE
    games = rows[:GAME_SEARCH_PAGE_SIZE]
    ratings = _community_rating_map(session, [game.id for game in games])
    return {
        "items": [_game_payload(game, ratings.get(game.id)) for game in games],
        "hasMore": has_more,
        "nextOffset": offset + GAME_SEARCH_PAGE_SIZE if has_more else None,
    }


def _igdb_search_body(query: str, offset: int) -> str:
    # The IGDB search command is documented as similarity-ranked by IGDB.
    # It is not advertised as typo-tolerant, unlike our PostgreSQL search.
    safe_query = json.dumps(query.replace(";", " "), ensure_ascii=False)[1:-1]
    return (
        "fields id,name,first_release_date,rating,rating_count,"
        "total_rating_count,hypes,cover.image_id,alternative_names.name,"
        "genres.id,genres.name,platforms.name,involved_companies.developer,"
        "involved_companies.company.name,websites.url,videos.name,videos.video_id; "
        f'search "{safe_query}"; '
        "where version_parent = null; "
        f"limit {GAME_SEARCH_PAGE_SIZE + 1}; offset {offset};"
    )


def _sync_genre_catalog() -> int:
    client_id, token = _igdb_access_token()
    rows = _igdb_details_request(
        "genres", "fields id,name; sort id asc; limit 500;", client_id, token,
    )
    valid = [
        {"id": item["id"], "name": item["name"].strip()}
        for item in rows
        if isinstance(item.get("id"), int)
        and isinstance(item.get("name"), str)
        and item["name"].strip()
    ]
    if not valid:
        raise HTTPException(status_code=502, detail="IGDB не вернул список жанров.")
    with _session() as session:
        session.execute(text("""
            INSERT INTO genres (id, name) VALUES (:id, :name)
            ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
        """), valid)
        session.execute(text("""
            INSERT INTO game_genres (game_id, genre_id)
            SELECT g.id, t.id
            FROM games AS g
            CROSS JOIN LATERAL jsonb_array_elements_text(
                COALESCE(NULLIF(g.genres_json, ''), '[]')::jsonb
            ) AS legacy(name)
            JOIN genres AS t ON lower(t.name) = lower(legacy.name)
            ON CONFLICT (game_id, genre_id) DO NOTHING
        """))
        session.execute(text("""
            INSERT INTO genre_catalog_sync (id, refreshed_at)
            VALUES (1, now())
            ON CONFLICT (id) DO UPDATE SET refreshed_at = EXCLUDED.refreshed_at
        """))
        session.commit()
    return len(valid)


@router.get("/api/genres")
def list_genres(request: Request) -> list[dict[str, object]]:
    with _session() as session:
        _current_user(request, session)
        stamp = session.get(GenreCatalogSync, 1)
        outdated = stamp is None or (
            _now() - stamp.refreshed_at.replace(
                tzinfo=stamp.refreshed_at.tzinfo or timezone.utc
            ) > timedelta(days=30)
        )
    if outdated:
        try:
            _sync_genre_catalog()
        except (HTTPException, SQLAlchemyError):
            # Offline fallback: existing genres remain filterable.
            pass
    with _session() as session:
        _current_user(request, session)
        rows = session.scalars(select(Genre).order_by(Genre.name, Genre.id)).all()
        return [{"id": row.id, "name": row.name} for row in rows]


@router.get("/api/games/igdb-status")
def igdb_status(request: Request) -> dict[str, bool]:
    with _session() as session:
        _current_user(request, session)
    return {
        "configured": bool(
            os.getenv("IGDB_CLIENT_ID", "").strip()
            and os.getenv("IGDB_CLIENT_SECRET", "").strip()
        )
    }


GAME_SEARCH_PAGE_SIZE = 20



GAME_DETAILS_CACHE_DAYS = 30
STORE_DOMAINS = (
    ("steampowered.com", "steam", "Steam"),
    ("epicgames.com", "epic", "Epic Games"),
    ("gog.com", "gog", "GOG"),
    ("itch.io", "itch", "itch.io"),
    ("playstation.com", "playstation", "PlayStation Store"),
    ("xbox.com", "xbox", "Xbox"),
    ("microsoft.com", "xbox", "Microsoft Store"),
    ("nintendo.com", "nintendo", "Nintendo eShop"),
)


def _igdb_details_request(
    endpoint: str, body: str, client_id: str, token: str,
) -> list[dict[str, object]]:
    try:
        response = httpx.post(
            f"https://api.igdb.com/v4/{endpoint}",
            headers={
                "Client-ID": client_id,
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            content=body,
            timeout=10.0,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=502, detail="Не удалось получить дополнительные данные из IGDB.",
        ) from exc
    if not isinstance(payload, list):
        raise HTTPException(status_code=502, detail="IGDB вернул некорректные данные.")
    return [item for item in payload if isinstance(item, dict)]


def _safe_store_links(websites: object) -> list[dict[str, str]]:
    if not isinstance(websites, list):
        return []

    stores: dict[str, dict[str, str]] = {}
    for website in websites:
        if not isinstance(website, dict):
            continue
        raw_url = website.get("url")
        if not isinstance(raw_url, str):
            continue
        try:
            parsed = urlsplit(raw_url)
        except ValueError:
            continue
        if parsed.scheme != "https" or parsed.username or parsed.password:
            continue
        host = (parsed.hostname or "").lower()
        for domain, provider, label in STORE_DOMAINS:
            if host == domain or host.endswith(f".{domain}"):
                stores.setdefault(provider, {
                    "provider": provider, "label": label, "url": raw_url,
                })
                break

    return list(stores.values())[:6]


def _safe_trailer_url(videos: object) -> str | None:
    if not isinstance(videos, list):
        return None
    candidates = [video for video in videos if isinstance(video, dict)]
    candidates.sort(
        key=lambda item: 0 if "trailer" in str(item.get("name") or "").casefold() else 1,
    )
    for candidate in candidates:
        video_id = candidate.get("video_id")
        if isinstance(video_id, str) and re.fullmatch(r"[a-zA-Z0-9_-]{11}", video_id):
            return f"https://www.youtube.com/watch?v={video_id}"
    return None


def _hours_from_igdb(value: object) -> int | None:
    # game_time_to_beats values are in seconds, not minutes.
    try:
        seconds = float(value) if value is not None else 0
    except (TypeError, ValueError):
        return None
    if not math.isfinite(seconds) or seconds <= 0:
        return None
    return max(1, round(seconds / 3600))


def _detail_response(session, game: Game, details: dict[str, object]) -> dict[str, object]:
    # Metadata is cached for 30 days; community scores must always be live.
    ratings = _community_rating_map(session, [game.id])
    return {**details, "game": _game_payload(game, ratings.get(game.id))}


@router.get("/api/games/{game_id}/details")
def game_details(game_id: int, request: Request) -> dict[str, object]:
    with _session() as session:
        _current_user(request, session)
        game = session.scalar(select(Game).where(Game.igdb_id == game_id))
        if game is None:
            raise HTTPException(status_code=404, detail="Игра не найдена в нашей базе.")

        cached_details = (
            json.loads(game.details_json) if game.details_json else None
        )
        if (
            isinstance(cached_details, dict)
            and game.details_cached_at is not None
            and game.details_cached_at.replace(tzinfo=game.details_cached_at.tzinfo or timezone.utc)
                > _now() - timedelta(days=GAME_DETAILS_CACHE_DAYS)
        ):
            if not cached_details.get("_linksOnly"):
                return _detail_response(session, game, cached_details)
            cached_links_fresh = True
        else:
            cached_links_fresh = False

    # Search results already populate the PostgreSQL links cache. For those
    # games, fetch only the missing playtime; for uncached games, query both
    # IGDB endpoints concurrently instead of making the first screen wait for
    # two sequential network round trips.
    try:
        client_id, token = _igdb_access_token()
    except HTTPException:
        if isinstance(cached_details, dict):
            with _session() as session:
                cached_game = session.scalar(select(Game).where(Game.igdb_id == game_id))
                if cached_game is not None:
                    return _detail_response(session, cached_game, cached_details)
        raise

    def fetch_playtime():
        return _igdb_details_request(
            "game_time_to_beats",
            f"fields game_id,hastily,completely; where game_id = {game_id}; limit 1;",
            client_id, token,
        )

    if cached_links_fresh and isinstance(cached_details, dict):
        details: dict[str, object] = dict(cached_details)
        try:
            times = fetch_playtime()
        except HTTPException:
            times = None
    else:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as executor:
            times_future = executor.submit(fetch_playtime)
            try:
                game_rows = _igdb_details_request(
                    "games",
                    f"fields websites.url,videos.name,videos.video_id; where id = {game_id}; limit 1;",
                    client_id, token,
                )
            except HTTPException:
                if isinstance(cached_details, dict):
                    with _session() as session:
                        cached_game = session.scalar(select(Game).where(Game.igdb_id == game_id))
                        if cached_game is not None:
                            return _detail_response(session, cached_game, cached_details)
                raise
            game_row = game_rows[0] if game_rows else {}
            details = {
                "storeLinks": _safe_store_links(game_row.get("websites")),
                "trailerUrl": _safe_trailer_url(game_row.get("videos")),
                "storyHours": None,
                "completionHours": None,
            }
            try:
                times = times_future.result()
            except HTTPException:
                times = None

    if times:
        details["storyHours"] = _hours_from_igdb(times[0].get("hastily"))
        details["completionHours"] = _hours_from_igdb(times[0].get("completely"))
    elif isinstance(cached_details, dict):
        details["storyHours"] = cached_details.get("storyHours")
        details["completionHours"] = cached_details.get("completionHours")
    details["_linksOnly"] = bool(cached_links_fresh and times is None)

    with _session() as session:
        game = session.scalar(select(Game).where(Game.igdb_id == game_id))
        if game is None:
            raise HTTPException(status_code=404, detail="Игра не найдена в нашей базе.")
        game.details_json = json.dumps(details, ensure_ascii=False)
        game.details_cached_at = _now()
        session.commit()
        return _detail_response(session, game, details)


@router.get("/api/games/search")
def search_games(
    request: Request,
    q: str = Query(max_length=100),
    source: Literal["local", "igdb"] = "local",
    offset: int = Query(default=0, ge=0, le=10000),
) -> dict[str, object]:
    query = q.strip()
    if len(query) < 3:
        return {"items": [], "hasMore": False, "nextOffset": None}

    with _session() as session:
        _current_user(request, session)
        if source == "local":
            return _local_game_search(session, query, offset)

    if offset >= 10000:
        return {"items": [], "hasMore": False, "nextOffset": None}

    # External search runs after an empty local search or a manual deep search.
    # Cache the results in PostgreSQL for future local queries.
    client_id, token = _igdb_access_token()

    body = _igdb_search_body(query, offset)

    try:
        response = httpx.post(
            "https://api.igdb.com/v4/games",
            headers={
                "Client-ID": client_id,
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            content=body,
            timeout=12.0,
        )
        if response.status_code == 429:
            raise HTTPException(status_code=429, detail="IGDB занят. Повторите поиск через секунду.")
        response.raise_for_status()
        rows = response.json()
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Не удалось получить игры из IGDB.") from exc

    if not isinstance(rows, list):
        return {"items": [], "hasMore": False, "nextOffset": None}

    # If IGDB's title search misses, its /search index also includes
    # alternative-name records pointing back to the parent game.
    if not rows and offset == 0:
        escaped = json.dumps(query.replace(";", " "), ensure_ascii=False)[1:-1]
        try:
            alias_response = httpx.post(
                "https://api.igdb.com/v4/search",
                headers={
                    "Client-ID": client_id,
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                content=f'fields game,alternative_name,name; search "{escaped}"; where game != null; limit 20;',
                timeout=12.0,
            )
            alias_response.raise_for_status()
            matches = alias_response.json()
            matches = matches if isinstance(matches, list) else []
            ids = list(dict.fromkeys(
                int(item["game"]) for item in matches
                if isinstance(item, dict) and isinstance(item.get("game"), int)
            ))[:20]
            if ids:
                detail_response = httpx.post(
                    "https://api.igdb.com/v4/games",
                    headers={
                        "Client-ID": client_id,
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                    content=(
                        "fields id,name,first_release_date,rating,rating_count,"
                        "total_rating_count,hypes,cover.image_id,alternative_names.name,"
                        "genres.id,genres.name,platforms.name,involved_companies.developer,"
                        "involved_companies.company.name,websites.url,videos.name,videos.video_id; "
                        f"where id = ({','.join(map(str, ids))}) & version_parent = null; limit 20;"
                    ),
                    timeout=12.0,
                )
                detail_response.raise_for_status()
                candidate_rows = detail_response.json()
                if isinstance(candidate_rows, list):
                    rows = candidate_rows
        except (httpx.HTTPError, ValueError):
            # IGDB fallback is best-effort; a failed alias lookup must not
            # make the original (valid) empty search into an API error.
            pass

    has_more = len(rows) > GAME_SEARCH_PAGE_SIZE and offset + GAME_SEARCH_PAGE_SIZE < 10000
    # IGDB first selects textually similar candidates. Within the returned
    # page, prioritize exact titles/aliases and use popularity to break ties.
    # Pagination remains tied to IGDB's offset, not our database.
    normalized = _normalized_search_text(query)

    def page_rank(row: dict[str, object]) -> tuple[int, float]:
        names = [str(row.get("name") or "")]
        names.extend(
            str(alt.get("name") or "") for alt in row.get("alternative_names") or []
            if isinstance(alt, dict)
        )
        names = [_normalized_search_text(name) for name in names]
        exact = int(normalized in names)
        prefix = int(any(name.startswith(normalized) for name in names))
        popularity = math.log1p(max(
            int(row.get("total_rating_count") or 0),
            int(row.get("rating_count") or 0),
        )) + math.log1p(int(row.get("hypes") or 0)) * 0.65
        return (exact * 2 + prefix, popularity)

    page_rows = sorted(rows[:GAME_SEARCH_PAGE_SIZE], key=page_rank, reverse=True)
    cached = _cache_igdb_games(page_rows) if page_rows else []
    return {
        "items": cached,
        "hasMore": has_more,
        "nextOffset": offset + GAME_SEARCH_PAGE_SIZE if has_more else None,
    }


