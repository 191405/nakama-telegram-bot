"""Trace.moe reverse anime scene recognition client."""

from __future__ import annotations

import logging
from typing import Any
import aiohttp

logger = logging.getLogger(__name__)

TRACE_MOE_API = "https://api.trace.moe/search?anilistInfo"


def _format_time(seconds: float | int | None) -> str:
    """Format seconds into MM:SS."""
    if seconds is None:
        return "00:00"
    mins = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{mins:02d}:{secs:02d}"


async def identify_anime_scene(image_bytes: bytes) -> dict[str, Any] | None:
    """Send image bytes to trace.moe and return the top match details."""
    try:
        data = aiohttp.FormData()
        data.add_field(
            "image",
            image_bytes,
            filename="scene.jpg",
            content_type="image/jpeg",
        )
        async with aiohttp.ClientSession(
            headers={"User-Agent": "NakamaNetworkBot/2.0"}
        ) as session:
            async with session.post(
                TRACE_MOE_API, data=data, timeout=aiohttp.ClientTimeout(total=25)
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.warning("Trace.moe returned status %s: %s", resp.status, text[:200])
                    return None
                result_json = await resp.json()
                results = result_json.get("result", [])
                if not results:
                    return None

                top = results[0]
                anilist = top.get("anilist", {}) or {}
                titles = anilist.get("title", {}) or {}

                return {
                    "anilist_id": anilist.get("id"),
                    "title_romaji": titles.get("romaji") or "Unknown Anime",
                    "title_english": titles.get("english") or titles.get("romaji") or "Unknown Anime",
                    "title_native": titles.get("native") or "",
                    "episode": top.get("episode"),
                    "from_time": _format_time(top.get("from")),
                    "to_time": _format_time(top.get("to")),
                    "similarity": float(top.get("similarity", 0.0)),
                    "video_url": top.get("video"),
                    "image_url": top.get("image"),
                }
    except Exception as exc:
        logger.error("Error identifying scene via trace.moe: %s", exc)
        return None
