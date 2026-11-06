"""Smart anime episode and series name extraction utilities."""

from __future__ import annotations

import re


EPISODE_PATTERNS = [
    r"\[(?:episodes?|ep|e)[\s\-_]*(\d+)\]",
    r"(?:episodes?|ep|e)[\s\-_]*(\d+)",
    r"s\d+[\s\-_]*e(\d+)",
    r"\bS\d+\s*[-–—]\s*(\d+)\b",
    r"-\s*(\d{1,4})\s*(?:\[|\(|\.|$)",
    r"[\s\-_](\d{1,4})\s*(?:\[|\(|\.mkv|\.mp4|\.avi)",
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
    s = filename

    # Remove bracketed and parenthesized metadata
    s = re.sub(r"\[[^\]]*\]", " ", s)
    s = re.sub(r"\([^\)]*\)", " ", s)
    s = re.sub(r"\.(mkv|mp4|avi|webm)$", " ", s, flags=re.IGNORECASE)

    # Remove season and episode markers: S01E07, S1 - 03, Ep-01, Episode 10, S1, Season 2
    s = re.sub(r"\bS\d+E\d+\b", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\bS(?:eason)?\s*\d+\b", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(?:EP|Episode)?\s*[-–—]?\s*\d+\b", " ", s, flags=re.IGNORECASE)

    # Remove quality, audio, and release tags
    s = re.sub(
        r"\b(multi\s*sub|sub|dub|dual|1080p|720p|480p|2160p|4k|x264|x265|hevc|web-dl|anime\s*clan|anime_fury)\b",
        " ",
        s,
        flags=re.IGNORECASE,
    )

    # Clean punctuation, dashes and excess whitespace
    s = re.sub(r"[\-_–—]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()

    # Normalise canonical series names
    s_lower = s.lower()
    if "last stand" in s_lower or "i became a legend" in s_lower:
        return "I Became A Legend"

    return s if len(s) >= 2 else filename


clean_series_name = extract_series_name
