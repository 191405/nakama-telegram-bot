"""Automatic genre-based categorization for anime files using AniList metadata."""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Category, File
from bot.utils.anilist import fetch_anime_info
from bot.utils.episodes import extract_series_name

logger = logging.getLogger(__name__)

# Standard anime genre to emoji mapping
GENRE_EMOJIS: dict[str, str] = {
    "Action": "⚔️",
    "Adventure": "🧭",
    "Comedy": "🤣",
    "Drama": "🎭",
    "Ecchi": "🔥",
    "Fantasy": "🧙‍♂️",
    "Horror": "🩸",
    "Mahou Shoujo": "✨",
    "Mecha": "🤖",
    "Music": "🎵",
    "Mystery": "🔍",
    "Psychological": "🧠",
    "Romance": "💖",
    "Sci-Fi": "🚀",
    "Slice of Life": "☕",
    "Sports": "⚽",
    "Supernatural": "👻",
    "Thriller": "⚡",
}


async def get_or_create_category(
    session: AsyncSession, name: str, emoji: str = "📁"
) -> Category:
    """Find an existing category by name (case-insensitive) or create a new one."""
    clean_name = name.strip()
    stmt = select(Category).where(Category.name.ilike(clean_name))
    cat = (await session.execute(stmt)).scalar_one_or_none()
    if cat:
        return cat

    cat = Category(name=clean_name, emoji=emoji, description=f"{clean_name} anime collection")
    session.add(cat)
    await session.commit()
    await session.refresh(cat)
    return cat


async def auto_categorize_file(
    session: AsyncSession, file: File, force: bool = False
) -> Category | None:
    """Auto-categorize an anime file using AniList genre metadata.

    If file already has a category and force=False, returns current category.
    """
    if file.category_id and not force:
        return await session.get(Category, file.category_id)

    series_title = extract_series_name(file.file_name)
    if not series_title or len(series_title) < 2:
        return None

    try:
        media = await fetch_anime_info(series_title)
        if not media:
            return None

        genres = media.get("genres") or []
        if not genres:
            return None

        # Pick primary genre
        primary_genre = genres[0]
        emoji = GENRE_EMOJIS.get(primary_genre, "📁")

        cat = await get_or_create_category(session, name=primary_genre, emoji=emoji)
        file.category_id = cat.id
        await session.commit()
        return cat
    except Exception as exc:
        logger.debug("Auto-categorize failed for file %s (%s): %s", file.id, file.file_name, exc)
        return None


async def bulk_auto_categorize(
    session: AsyncSession, only_uncategorized: bool = True
) -> dict[str, Any]:
    """Scan files and auto-assign them to genre categories via AniList.

    Returns:
        Summary dict with processed, categorized, and category breakdown counts.
    """
    stmt = select(File)
    if only_uncategorized:
        stmt = stmt.where(File.category_id.is_(None))

    files = list((await session.execute(stmt)).scalars().all())
    if not files:
        return {"processed": 0, "categorized": 0, "breakdown": {}}

    categorized_count = 0
    breakdown: dict[str, int] = {}

    for f in files:
        cat = await auto_categorize_file(session, f, force=not only_uncategorized)
        if cat:
            categorized_count += 1
            key = f"{cat.emoji} {cat.name}"
            breakdown[key] = breakdown.get(key, 0) + 1

    return {
        "processed": len(files),
        "categorized": categorized_count,
        "breakdown": breakdown,
    }
