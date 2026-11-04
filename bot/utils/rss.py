"""SubsPlease and Nyaa RSS feed parser for automatic anime release tracking."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Any

import aiohttp

from bot.utils.episodes import extract_episode_number, extract_series_name

logger = logging.getLogger(__name__)

SUBSPLEASE_RSS_1080 = "https://subsplease.org/rss/?r=1080"
SUBSPLEASE_RSS_720 = "https://subsplease.org/rss/?r=720"


async def fetch_subsplease_rss(resolution: str = "1080", limit: int = 15) -> list[dict[str, Any]]:
    """Fetch and parse latest anime releases from SubsPlease RSS feed.

    Returns a list of dicts with:
        title, series, episode, size, pub_date, magnet
    """
    url = SUBSPLEASE_RSS_720 if resolution == "720" else SUBSPLEASE_RSS_1080

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    logger.warning("Failed to fetch SubsPlease RSS, HTTP %d", resp.status)
                    return []
                xml_text = await resp.text()

        root = ET.fromstring(xml_text)
        channel = root.find("channel")
        if channel is None:
            return []

        items = channel.findall("item")
        results = []

        for item in items[:limit]:
            title_elem = item.find("title")
            link_elem = item.find("link")
            pub_date_elem = item.find("pubDate")

            # Look for size in namespaced subsplease:size or category
            size_elem = item.find("{https://subsplease.org/rss}size")
            size_str = size_elem.text if size_elem is not None and size_elem.text else ""

            raw_title = title_elem.text if title_elem is not None and title_elem.text else ""
            magnet_link = link_elem.text if link_elem is not None and link_elem.text else ""
            pub_date = pub_date_elem.text if pub_date_elem is not None and pub_date_elem.text else ""

            series = extract_series_name(raw_title)
            ep = extract_episode_number(raw_title)

            results.append({
                "title": raw_title,
                "series": series,
                "episode": ep,
                "size": size_str,
                "pub_date": pub_date,
                "magnet": magnet_link,
            })

        return results

    except Exception as exc:
        logger.error("Error parsing SubsPlease RSS: %s", exc)
        return []
