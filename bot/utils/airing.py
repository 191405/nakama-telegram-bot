"""AniList Airing Schedule client for Nakama Network."""

from __future__ import annotations

import logging
import time
from typing import Any
import aiohttp

logger = logging.getLogger(__name__)

ANILIST_API_URL = "https://graphql.anilist.co"

AIRING_QUERY = """
query ($start: Int, $end: Int, $perPage: Int) {
  Page(page: 1, perPage: $perPage) {
    airingSchedules(airingAt_greater: $start, airingAt_lesser: $end, sort: TIME) {
      id
      airingAt
      episode
      media {
        id
        title {
          romaji
          english
        }
        coverImage {
          large
        }
        genres
        siteUrl
      }
    }
  }
}
"""


def format_countdown(airing_at: int) -> str:
    """Format seconds into human-readable countdown."""
    now = int(time.time())
    diff = airing_at - now
    if diff <= 0:
        past = abs(diff)
        if past < 3600:
            return f"Aired {past // 60}m ago"
        return f"Aired {past // 3600}h ago"

    hours = diff // 3600
    minutes = (diff % 3600) // 60
    if hours > 0:
        return f"in {hours}h {minutes}m"
    return f"in {minutes}m"


async def fetch_today_airing_schedule(limit: int = 15) -> list[dict[str, Any]]:
    """Fetch anime episodes scheduled to broadcast in Japan today."""
    now = int(time.time())
    # 24-hour window from current time minus 3 hours to capture just-aired plus upcoming
    start_time = now - 10800
    end_time = now + 86400

    variables = {
        "start": start_time,
        "end": end_time,
        "perPage": limit,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ANILIST_API_URL,
                json={"query": AIRING_QUERY, "variables": variables},
                headers={"Content-Type": "application/json", "User-Agent": "NakamaBot/1.0"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    logger.warning("AniList Airing API returned %s", resp.status)
                    return []

                data = await resp.json()
                schedules = (
                    data.get("data", {})
                    .get("Page", {})
                    .get("airingSchedules", [])
                )

                results = []
                for item in schedules:
                    media = item.get("media", {})
                    title_obj = media.get("title", {})
                    name = (
                        title_obj.get("english")
                        or title_obj.get("romaji")
                        or "Unknown Title"
                    )
                    results.append({
                        "id": item.get("id"),
                        "title": name,
                        "episode": item.get("episode", 1),
                        "airing_at": item.get("airingAt", 0),
                        "countdown": format_countdown(item.get("airingAt", 0)),
                        "cover": media.get("coverImage", {}).get("large"),
                        "genres": media.get("genres", []),
                        "url": media.get("siteUrl", "https://anilist.co"),
                    })
                return results

    except Exception as exc:
        logger.error("Failed to fetch airing schedule: %s", exc)
        return []
