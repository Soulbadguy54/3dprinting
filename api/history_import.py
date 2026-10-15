"""One-off, secret-protected migration of complete historic game ratings.

Does not guess when multiple IGDB entries share the same title. Searches are
cached using RateApp's normal IGDB catalog pipeline even during dry runs.
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from api.database import SessionLocal
from api.models import Game, User, UserGame


class ScoreFour(BaseModel):
    technology: Decimal = Field(ge=1, le=10)
    story: Decimal = Field(ge=1, le=10)
    atmosphere: Decimal = Field(ge=1, le=10)
    gameplay: Decimal = Field(ge=1, le=10)


class RatedHistoryRow(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    query: str = Field(min_length=1, max_length=100)
    status: Literal["completed", "dropped"]
    releaseYear: int | None = Field(default=None, ge=1980, le=2035)
    igdbId: int | None = Field(default=None, ge=1)
    igdbCover: str | None = Field(default=None, pattern=r"^co[a-z0-9]+$")
    soulbadguy: ScoreFour
    nastya: ScoreFour


class RatedHistoryBatch(BaseModel):
    dryRun: bool = True
    rows: list[RatedHistoryRow] = Field(min_length=1, max_length=6)


def normalized_title(value: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if c.isalnum())


def match_igdb(rows: list[dict], query: str, year: int | None, selected_id: int | None = None, cover_id: str | None = None) -> dict | None:
    expected = normalized_title(query)
    candidates = [
        row for row in rows if isinstance(row, dict)
        and (
            normalized_title(str(row.get("name", ""))) == expected
            or any(
                normalized_title(str(alt.get("name", ""))) == expected
                for alt in row.get("alternative_names", [])
                if isinstance(alt, dict)
            )
        )
    ]
    if year is not None:
        candidates = [
            row for row in candidates
            if row.get("first_release_date")
            and datetime.fromtimestamp(int(row["first_release_date"]), timezone.utc).year == year
        ]
    if selected_id is not None:
        candidates = [row for row in candidates if int(row.get("id") or 0) == selected_id]
    if cover_id is not None:
        candidates = [
            row for row in candidates
            if isinstance(row.get("cover"), dict)
            and row["cover"].get("image_id") == cover_id
        ]
    ids = {int(row["id"]) for row in candidates if row.get("id")}
    return candidates[0] if len(ids) == 1 else None


def rounded_scores(values: ScoreFour) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    criteria = tuple(
        value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        for value in (values.atmosphere, values.story, values.technology, values.gameplay)
    )
    total = (sum(criteria) / Decimal("4")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return (*criteria, total)


def save_rated_history_row(
    session, game: Game, status: str, user_id: int, values: ScoreFour,
) -> str:
    entry = session.scalar(select(UserGame).where(
        UserGame.game_id == game.id, UserGame.user_id == user_id,
    ))
    kind = "updated" if entry else "created"
    if entry is None:
        entry = UserGame(game_id=game.id, user_id=user_id, status=status)
        session.add(entry)
    elif entry.status != status:
        # A date from a different playthrough status must not be repurposed.
        entry.completed_at = None
    entry.status = status
    entry.started_at = None
    (entry.atmosphere_score, entry.story_score, entry.technology_score,
     entry.gameplay_score, entry.score) = rounded_scores(values)
    return kind
