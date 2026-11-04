"""Fuzzy string matching and typo correction for anime searches."""

from __future__ import annotations

import difflib


def find_closest_match(query: str, possibilities: list[str], cutoff: float = 0.6) -> str | None:
    """Find the closest matching title or category for a mistyped query."""
    if not query or not possibilities:
        return None

    clean_query = query.strip().lower()
    mapping = {p.lower(): p for p in possibilities if p}

    matches = difflib.get_close_matches(
        clean_query, list(mapping.keys()), n=1, cutoff=cutoff
    )
    if matches:
        return mapping[matches[0]]

    # Word-by-word fuzzy check if query has multiple words
    words = clean_query.split()
    if len(words) > 1:
        for p_lower, original in mapping.items():
            if all(any(difflib.SequenceMatcher(None, w, pw).ratio() > 0.7 for pw in p_lower.split()) for w in words):
                return original

    return None
