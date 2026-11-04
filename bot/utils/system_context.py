"""Live System & Database Grounding Context for Nakama Gemini AI.

Connects Gemini's intelligence with real-time database state, user profile,
library inventory, recent releases, and bot capabilities.
"""

from __future__ import annotations

import logging
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.config import settings
from bot.db import queries
from bot.db.models import File
from bot.utils.personas import get_persona_info, get_persona_prompt

logger = logging.getLogger(__name__)


async def build_system_grounding(
    session: AsyncSession,
    user_id: int,
    user_name: str = "User",
    username: str | None = None,
    current_query: str | None = None,
) -> tuple[str, list[File], str | None, str]:
    """Build dynamic real-time grounding text for Gemini.

    Returns:
        (grounding_prompt, matching_files_list, suggested_anime_title, persona_prompt)
    """
    try:
        # 1. Fetch user stats, rank, and active persona
        profile = await queries.get_user_profile(session, user_id)
        persona_key = await queries.get_user_persona(session, user_id)
        persona_info = get_persona_info(persona_key)
        persona_prompt = get_persona_prompt(persona_key)

        if profile:
            rank = profile.get("rank", "🧭 Cabin Boy / Rookie")
            downloads = profile.get("downloads", 0)
            continue_file = profile.get("continue_file")
            continue_info = (
                f"{continue_file.file_name} ({continue_file.human_size})"
                if continue_file
                else "No downloads yet"
            )
        else:
            rank = "🧭 Cabin Boy / Rookie"
            downloads = 0
            continue_info = "No downloads yet"

        is_admin = user_id in settings.admin_id_list

        # 2. Fetch user's personal watchlist
        watchlist_items = await queries.get_user_watchlist(session, user_id)
        watchlist_str = (
            ", ".join(f"{w.series_name} [{w.status}]" for w in watchlist_items[:8])
            if watchlist_items
            else "No bookmarked anime yet"
        )

        # 3. Fetch community & library inventory
        stats = await queries.get_community_stats(session)
        total_files = stats.get("total_files", 0)
        total_users = stats.get("total_users", 0)

        # 4. Fetch all anime series in the vault
        summaries = await queries.get_all_series_summaries(session)
        series_info = []
        for s in summaries[:25]:  # Top 25 series
            series_info.append(f"{s['name']} ({s['total_episodes']} eps)")
        series_str = ", ".join(series_info) if series_info else "Library is being populated"

        # 5. Fetch recent releases
        recent_files_stmt = select(File).order_by(File.created_at.desc()).limit(5)
        recent_files = list((await session.execute(recent_files_stmt)).scalars().all())
        recent_str = (
            ", ".join(f"{f.file_name}" for f in recent_files)
            if recent_files
            else "None yet"
        )

        # 6. Search for query relevance or fallback to active series context
        matching_files: list[File] = []
        primary_title = None

        from bot.utils.memory import get_active_series, set_active_series

        active_ctx = get_active_series(user_id)

        if current_query:
            clean_q = queries.extract_series_name(current_query) or current_query.strip()
            if len(clean_q) >= 2:
                matching_files = await queries.search_files(session, clean_q, limit=6)

        # If current query didn't yield files (e.g. "send them", "the episodes?", "episode 1"),
        # check if the user is in an active conversation about a series
        if not matching_files and active_ctx:
            matching_files = await queries.search_files(session, active_ctx, limit=6)
            if matching_files:
                primary_title = active_ctx

        if matching_files and not primary_title:
            primary_title = (
                queries.extract_series_name(matching_files[0].file_name)
                or matching_files[0].file_name
            )

        if primary_title:
            set_active_series(user_id, primary_title)

        matches_summary = (
            f"Found {len(matching_files)} episode(s) in vault for '{primary_title or clean_q}': "
            + ", ".join(f.file_name for f in matching_files[:4])
            if matching_files
            else "No exact files currently in vault for this title."
        )

        grounding = f"""[CHARACTER PERSONA INSTRUCTION]:
{persona_prompt}
Active Persona: {persona_info['emoji']} {persona_info['name']} ({persona_info['tagline']})

[LIVE NAKAMA SYSTEM STATE & DATABASE ACCESS]:
- Bot Identity: Nakama Network (@NakamaNetworkbot) - The All-in-One Anime Vault, Community & Assistant.
- Active User Talking to You:
  * Name: {user_name} (@{username or 'no_username'}, ID: {user_id})
  * Community Rank: {rank}
  * Total Downloads: {downloads} episodes
  * Last Watched: {continue_info}
  * Personal Watchlist: {watchlist_str}
  * Is Administrator: {is_admin}
- Vault Inventory: {total_files} total episodes across {len(summaries)} distinct series; {total_users} active members.
- Available Anime Series Currently In Vault:
  {series_str}
- Recently Uploaded New Episodes:
  {recent_str}
- Live Database Query Result for this Message:
  {matches_summary}
- System Capabilities you can tell the user about:
  1. Instant Video Downloads: High-speed 1080p/720p anime episodes hosted on Telegram CDN.
  2. Scene Recognition: Users can send any anime screenshot/photo, and the bot identifies the exact anime, episode, and timestamp (powered by Trace.moe).
  3. HD Opening & Ending Themes: Full 1080p clean anime songs with audio/video stream links (powered by AnimeThemes.moe).
  4. Seasonal Airing Schedule: Real-time broadcast schedule with countdowns for today's episodes in Japan.
  5. Personal Watchlist: Bookmarking series into Watching / Plan to Watch / Completed.
  6. Daily Anime Trivia: Quizzes that award Community XP bounty and level up ranks on the Leaderboard.
  7. Voice Note Support: Users can speak to you via Telegram voice notes!

[COGNITIVE DIRECTIVES]:
- You HAVE DIRECT ACCESS to all the above system details. Speak with complete confidence and stay in your chosen character persona.
- If the user asks what anime we have, whether an anime is available, or asks for recommendations, check the "Available Anime Series Currently In Vault" list above.
- If an anime is in our vault, confirm enthusiastically that we have it ready for them!
- When the user asks to send, watch, or deliver episodes (e.g. 'send them', 'the episodes?', 'send episode 1', 'give me ep 1'), our Telegram bot engine has FULL AUTHORITY and will automatically dispatch the video files or interactive download keyboards directly to the chat! Confirm warmly that you are delivering the episodes right now.
- If an anime is NOT in our vault, let them know it's not here yet, and reassure them they can easily request it so the team can add it.
- If they ask about their profile, rank, watchlist, or what they watched, cite their exact stats from above.
- Talk like a genuine friend in your character persona. ABSOLUTELY NEVER suggest or mention bot forward-slash commands (e.g. do not say '/download', '/search', '/request', etc.).
"""
        return grounding, matching_files, primary_title, persona_prompt

    except Exception as exc:
        logger.error("Failed to build system grounding: %s", exc)
        return "", [], None, ""
