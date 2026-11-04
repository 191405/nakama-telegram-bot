"""In-memory sliding window conversation memory for Nakama AI."""

from __future__ import annotations

import time
from typing import Any

# user_id -> list of {"role": "user" | "model", "parts": [{"text": ...}], "ts": float}
_SESSIONS: dict[int, list[dict[str, Any]]] = {}

# Session expires after 30 minutes of inactivity
SESSION_TTL_SECONDS = 1800
MAX_HISTORY_TURNS = 8  # 4 user turns + 4 model turns


# user_id -> (series_name, timestamp)
_ACTIVE_SERIES: dict[int, tuple[str, float]] = {}


def get_conversation_history(user_id: int) -> list[dict[str, Any]]:
    """Return past messages for user formatted for Gemini contents payload."""
    now = time.time()
    history = _SESSIONS.get(user_id, [])
    if not history:
        return []

    # Check expiration from last message
    if now - history[-1]["ts"] > SESSION_TTL_SECONDS:
        _SESSIONS.pop(user_id, None)
        _ACTIVE_SERIES.pop(user_id, None)
        return []

    # Return pure Gemini format (strip internal 'ts' key)
    formatted = []
    for item in history:
        formatted.append({
            "role": item["role"],
            "parts": item["parts"],
        })
    return formatted


def add_to_conversation(user_id: int, role: str, text: str) -> None:
    """Record a user or model message into the user's active session."""
    now = time.time()
    history = _SESSIONS.setdefault(user_id, [])

    # If expired, reset
    if history and (now - history[-1]["ts"] > SESSION_TTL_SECONDS):
        history.clear()
        _ACTIVE_SERIES.pop(user_id, None)

    history.append({
        "role": role,
        "parts": [{"text": text}],
        "ts": now,
    })

    # Keep within sliding window limit
    if len(history) > MAX_HISTORY_TURNS:
        _SESSIONS[user_id] = history[-MAX_HISTORY_TURNS:]


def set_active_series(user_id: int, series_name: str) -> None:
    """Save the active anime series currently being discussed with the user."""
    if series_name and len(series_name.strip()) >= 2:
        _ACTIVE_SERIES[user_id] = (series_name.strip(), time.time())


def get_active_series(user_id: int) -> str | None:
    """Retrieve the active anime series for this user, respecting session TTL."""
    entry = _ACTIVE_SERIES.get(user_id)
    if not entry:
        return None
    series_name, ts = entry
    if time.time() - ts > SESSION_TTL_SECONDS:
        _ACTIVE_SERIES.pop(user_id, None)
        return None
    return series_name


def clear_conversation(user_id: int) -> None:
    """Clear conversation history and active series for a user."""
    _SESSIONS.pop(user_id, None)
    _ACTIVE_SERIES.pop(user_id, None)

