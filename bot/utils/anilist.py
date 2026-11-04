"""AniList GraphQL API integration for rich anime metadata cards."""

from __future__ import annotations

import html
import logging
import re
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

ANILIST_URL = "https://graphql.anilist.co"

QUERY = """
query ($search: String) {
  Media (search: $search, type: ANIME) {
    id
    title {
      romaji
      english
      native
    }
    coverImage {
      large
      extraLarge
    }
    bannerImage
    description(asHtml: false)
    averageScore
    episodes
    status
    genres
    seasonYear
  }
}
"""

_CACHE: dict[str, dict[str, Any] | None] = {}


async def fetch_anime_info(title: str) -> dict[str, Any] | None:
    """Fetch anime details from AniList by title."""
    clean_title = title.strip()
    if not clean_title:
        return None

    cache_key = clean_title.lower()
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    variables = {"search": clean_title}
    payload = {"query": QUERY, "variables": variables}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ANILIST_URL, json=payload, timeout=aiohttp.ClientTimeout(total=4)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    media = data.get("data", {}).get("Media")
                    _CACHE[cache_key] = media
                    return media
                else:
                    _CACHE[cache_key] = None
                    return None
    except Exception as e:
        logger.debug("AniList fetch error for %r: %s", title, e)
        _CACHE[cache_key] = None
        return None


def format_anilist_card(media: dict[str, Any]) -> str:
    """Format an AniList anime into an attractive HTML card."""
    title_data = media.get("title") or {}
    title = (
        title_data.get("english")
        or title_data.get("romaji")
        or title_data.get("native")
        or "Anime"
    )

    score = media.get("averageScore")
    score_str = f"⭐ <b>{score / 10:.1f}/10</b>" if score else "⭐ N/A"

    year = media.get("seasonYear") or ""
    status = media.get("status") or "Unknown"
    status_str = status.replace("_", " ").title()

    genres = media.get("genres") or []
    genre_str = ", ".join(genres[:4]) if genres else "Anime"

    total_episodes = media.get("episodes") or "?"

    desc = media.get("description") or ""
    # Strip any stray HTML tags and trim
    desc = re.sub(r"<[^>]+>", "", desc)
    desc = html.escape(desc)
    if len(desc) > 300:
        desc = desc[:297] + "..."

    return (
        f"🎌 <b>{html.escape(title)}</b> ({year})\n"
        f"\n"
        f"{score_str} | 📺 <b>{total_episodes}</b> Ep | 🏷️ <i>{status_str}</i>\n"
        f"🎭 <b>Genres:</b> {html.escape(genre_str)}\n"
        f"\n"
        f"📝 <b>Synopsis:</b>\n"
        f"<i>{desc or 'No synopsis available.'}</i>"
    )


# Alias for backward compatibility
fetch_anilist_info = fetch_anime_info

