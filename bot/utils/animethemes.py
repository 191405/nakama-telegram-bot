"""AnimeThemes.moe API client for fetching anime opening and ending themes."""

from __future__ import annotations

import logging
from typing import Any
import urllib.parse
import aiohttp

logger = logging.getLogger(__name__)

BASE_URL = "https://api.animethemes.moe"


async def fetch_anime_themes(query: str) -> dict[str, Any] | None:
    """Fetch anime opening and ending themes from AnimeThemes.moe."""
    clean_query = query.strip()
    if not clean_query:
        return None

    headers = {"User-Agent": "NakamaNetworkBot/2.0"}

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            # 1. First attempt: direct filter by name
            encoded_name = urllib.parse.quote(clean_query)
            url = (
                f"{BASE_URL}/anime?filter[name]={encoded_name}"
                f"&include=animethemes.animethemeentries.videos,animethemes.song.artists"
            )

            target_anime = None
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    anime_list = data.get("anime", [])
                    if anime_list:
                        target_anime = anime_list[0]

            # 2. Fallback: search endpoint if direct filter found nothing
            if not target_anime or not target_anime.get("animethemes"):
                search_url = f"{BASE_URL}/search?q={encoded_name}"
                async with session.get(search_url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                    if resp.status == 200:
                        s_data = await resp.json()
                        search_results = s_data.get("search", {}).get("anime", [])
                        if search_results:
                            matched_name = search_results[0].get("name")
                            if matched_name:
                                enc_matched = urllib.parse.quote(matched_name)
                                f_url = (
                                    f"{BASE_URL}/anime?filter[name]={enc_matched}"
                                    f"&include=animethemes.animethemeentries.videos,animethemes.song.artists"
                                )
                                async with session.get(f_url, timeout=aiohttp.ClientTimeout(total=12)) as f_resp:
                                    if f_resp.status == 200:
                                        f_data = await f_resp.json()
                                        if f_data.get("anime"):
                                            target_anime = f_data["anime"][0]

            if not target_anime:
                return None

            anime_name = target_anime.get("name") or clean_query
            raw_themes = target_anime.get("animethemes", [])
            parsed_themes: list[dict[str, Any]] = []

            for theme in raw_themes:
                slug = theme.get("slug") or f"{theme.get('type', 'Theme')}{theme.get('sequence', '')}"
                song = theme.get("song") or {}
                song_title = song.get("title") or "Unknown Title"

                artists_list = song.get("artists") or []
                artists_str = ", ".join(a.get("name", "") for a in artists_list if a.get("name"))

                # Get first video link
                video_url = None
                resolution = "HD"
                entries = theme.get("animethemeentries", [])
                for entry in entries:
                    videos = entry.get("videos", [])
                    if videos:
                        video_url = videos[0].get("link")
                        if videos[0].get("resolution"):
                            resolution = f"{videos[0]['resolution']}p"
                        break

                parsed_themes.append({
                    "slug": slug,
                    "type": theme.get("type", "Theme"),
                    "song_title": song_title,
                    "artist": artists_str,
                    "video_url": video_url,
                    "resolution": resolution,
                })

            return {
                "anime_name": anime_name,
                "year": target_anime.get("year"),
                "season": target_anime.get("season"),
                "themes": parsed_themes,
            }

    except Exception as exc:
        logger.error("Error fetching animethemes for '%s': %s", clean_query, exc)
        return None
