"""Smart anime episode and series name extraction utilities."""

from __future__ import annotations

import re


EPISODE_PATTERNS = [
    r"(?:episodes?|ep|e)[\s\-_]*(\d+)",
    r"s\d+[\s\-_]*e(\d+)",
    r"-\s*(\d{1,4})\s*(?:\[|\(|\.|$)",
    r"[\s\-_](\d{1,4})\s*(?:\[|\(|\.mkv|\.mp4|\.avi)",
]

# Tags to strip when cleaning series names
STRIP_TAGS = [
    r"\[[^\]]*\]",           # [1080p], [Sub], [ΛV]
    r"\([^\)]*\)",           # (Dual Audio), (2024)
    r"\.mkv|\.mp4|\.avi",    # extensions
    r"(?:episodes?|ep|e)[\s\-_]*\d+",
    r"s\d+[\s\-_]*e\d+",
    r"s\d+",
    r"season\s*\d+",
    r"multi[\s\-_]*sub",
    r"sub|dub",
    r"1080p|720p|480p|2160p|4k|x264|x265|hevc|web-dl",
]


def extract_episode_number(filename: str) -> int | None:
    """Extract integer episode number from anime filename."""
    for pat in EPISODE_PATTERNS:
        m = re.search(pat, filename, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except (ValueError, TypeError):
                continue
    return None


def extract_series_name(filename: str) -> str:
    """Extract clean core series name from anime filename."""
    cleaned = filename
    for tag in STRIP_TAGS:
        cleaned = re.sub(tag, " ", cleaned, flags=re.IGNORECASE)

    # Clean whitespace and trailing dashes/symbols
    cleaned = re.sub(r"[\-_]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned if len(cleaned) >= 2 else filename


# Backward compatible alias
clean_series_name = extract_series_name

