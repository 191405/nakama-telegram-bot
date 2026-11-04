"""Automated poster and card generator for Ongoing Anime Telegram channels."""

from __future__ import annotations

import html
import logging
import re
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import settings
from bot.utils.anilist import fetch_anime_info
from bot.utils.episodes import extract_episode_number, extract_series_name

if TYPE_CHECKING:
    from bot.db.models import File

logger = logging.getLogger(__name__)


def format_ongoing_card(
    title: str,
    episode_num: int | str | None,
    season_num: int | str = "01",
    status: str = "ONGOING",
    audio: str = "Japanese [Eng Sub]",
    quality: str = "480p, 720p, 1080p, HDRip",
    bot_username: str = "NakamaNetworkbot",
) -> str:
    """Format an ongoing release card matching the sleek channel aesthetic."""
    ep_str = f"{episode_num:02d}" if isinstance(episode_num, int) else (str(episode_num) if episode_num else "01")
    s_str = f"{season_num:02d}" if isinstance(season_num, int) else str(season_num)

    return (
        f"✦ <b>{html.escape(title)}</b>\n\n"
        f"▪ <b>Status</b> : {status}\n"
        f"▪ <b>Season</b> : {s_str}\n"
        f"▪ <b>Episode</b> : {ep_str}\n"
        f"▪ <b>Audio</b> : {audio}\n"
        f"▪ <b>Quality</b> : {quality}\n"
        "───────────────────────────\n"
        f"✦ <b>Powered By</b> : @{bot_username}"
    )


async def broadcast_ongoing_episode(
    bot: Bot,
    file_record: File,
    target_channel: str | None = None,
) -> bool:
    """Publish a stylish photo/banner card with a direct download button to the channel."""
    channel_id = target_channel or settings.update_channel
    if not channel_id:
        return False

    try:
        # Extract metadata from filename
        raw_name = file_record.file_name
        series = extract_series_name(raw_name)
        ep = extract_episode_number(raw_name)

        # Detect Season
        season_match = re.search(r"s(\d+)|season\s*(\d+)", raw_name, re.IGNORECASE)
        season = int(season_match.group(1) or season_match.group(2)) if season_match else 1

        # Detect Audio
        fname_lower = raw_name.lower()
        if "dual" in fname_lower:
            audio = "Dual Audio [Eng/Jap]"
        elif "dub" in fname_lower:
            audio = "English Dub"
        else:
            audio = "Japanese [Eng Sub]"

        # Detect Quality
        qualities = []
        for q in ("480p", "720p", "1080p", "2160p", "4k", "HDRip"):
            if q.lower() in fname_lower:
                qualities.append(q)
        quality = ", ".join(qualities) if qualities else "480p, 720p, 1080p, HDRip"

        # Fetch AniList cover/banner & status
        anilist = await fetch_anime_info(series)
        status = "ONGOING"
        display_title = series
        photo_url = None

        if anilist:
            ani_status = anilist.get("status")
            if ani_status == "RELEASING":
                status = "ONGOING"
            elif ani_status == "FINISHED":
                status = "COMPLETED"

            # Prefer English or Romaji title
            titles = anilist.get("title") or {}
            display_title = titles.get("english") or titles.get("romaji") or series

            # Prefer banner image or high-res cover
            photo_url = anilist.get("bannerImage")
            if not photo_url:
                covers = anilist.get("coverImage") or {}
                photo_url = covers.get("extraLarge") or covers.get("large")

        # Get bot username for deep link & branding
        bot_username = "NakamaNetworkbot"
        try:
            me = await bot.get_me()
            bot_username = me.username or bot_username
        except Exception:
            pass

        caption = format_ongoing_card(
            title=display_title,
            episode_num=ep,
            season_num=season,
            status=status,
            audio=audio,
            quality=quality,
            bot_username=bot_username,
        )

        direct_link = f"https://t.me/{bot_username}?start=file_{file_record.id}"
        channel_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Download ↗", url=direct_link)]
            ]
        )

        # Attempt to post as Photo first
        if photo_url:
            try:
                await bot.send_photo(
                    chat_id=channel_id,
                    photo=photo_url,
                    caption=caption,
                    reply_markup=channel_kb,
                    parse_mode="HTML",
                )
                logger.info("Successfully posted ongoing photo card for %s to %s", display_title, channel_id)
                return True
            except Exception as exc:
                logger.debug("Failed to send photo to channel (%s), falling back to text: %s", photo_url, exc)

        # Fallback to text message
        await bot.send_message(
            chat_id=channel_id,
            text=caption,
            reply_markup=channel_kb,
            parse_mode="HTML",
        )
        logger.info("Successfully posted ongoing text card for %s to %s", display_title, channel_id)
        return True

    except Exception as exc:
        logger.error("Failed to broadcast ongoing card for file %d: %s", file_record.id, exc)
        return False
