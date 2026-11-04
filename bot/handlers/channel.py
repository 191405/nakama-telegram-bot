"""Channel post auto-indexer and SubsPlease RSS monitor."""

from __future__ import annotations

import html
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.db import queries
from bot.utils.categories import auto_categorize_file
from bot.utils.channel_poster import broadcast_ongoing_episode
from bot.utils.episodes import extract_episode_number, extract_series_name
from bot.utils.rss import fetch_subsplease_rss

logger = logging.getLogger(__name__)

router = Router(name="channel")


# ─── Storage Channel Auto-Indexer ────────────────────────────────────────────


@router.channel_post(F.content_type.in_({"document", "video"}))
async def handle_storage_channel_post(message: Message, session: AsyncSession) -> None:
    """Intercept media dropped in storage channels by any sub-bot or admin,

    auto-index it, categorize it with AniList, and post release notifications.
    """
    # If storage_channel is explicitly configured, only index from that channel
    if settings.storage_channel:
        chat_identifier = str(message.chat.id)
        chat_username = f"@{message.chat.username}" if message.chat.username else ""
        allowed = {settings.storage_channel.strip(), chat_identifier, chat_username}
        if settings.storage_channel.strip() not in allowed and chat_identifier != settings.storage_channel.strip():
            # Not the designated storage channel
            return

    # Extract file details
    doc = message.document
    vid = message.video
    target_media = doc or vid
    if not target_media:
        return

    file_id = target_media.file_id
    file_unique_id = target_media.file_unique_id
    file_type = "video" if vid else "document"
    file_size = target_media.file_size or 0

    caption = message.caption or None
    caption_first_line = message.caption.split("\n")[0].strip() if message.caption else ""
    original_name = getattr(target_media, "file_name", None) or caption_first_line or f"Anime_{file_unique_id[:8]}"

    # Check for duplicates in database
    existing = await queries.get_file_by_telegram_id(session, file_id)
    if existing:
        logger.info("Storage channel file already indexed: %s (ID: %s)", original_name, existing.id)
        return

    uploader_id = message.sender_chat.id if message.sender_chat else (settings.admin_id_list[0] if settings.admin_id_list else 0)

    try:
        # Save file to shared database
        f = await queries.save_file(
            session=session,
            file_name=original_name,
            file_id=file_id,
            file_unique_id=file_unique_id,
            file_type=file_type,
            file_size=file_size,
            uploaded_by=uploader_id,
            category_id=None,
            caption=caption,
        )

        # Auto-categorize using AniList metadata
        cat = await auto_categorize_file(session, f)
        cat_name = f"{cat.emoji} {cat.name}" if cat else "📁 Anime"

        series = extract_series_name(original_name)
        ep = extract_episode_number(original_name)
        ep_label = f"Episode {ep}" if ep is not None else ""

        bot = message.bot
        bot_username = "NakamaNetworkbot"
        if bot:
            try:
                me = await bot.get_me()
                bot_username = me.username or bot_username
            except Exception:
                pass

        direct_link = f"https://t.me/{bot_username}?start=file_{f.id}"
        logger.info("Auto-indexed new anime release: %s (%s) -> ID: %d", series, ep_label, f.id)

        # Auto-announce to public updates channel if configured and distinct from storage channel
        if settings.update_channel and bot:
            if str(message.chat.id) != settings.update_channel and f"@{message.chat.username}" != settings.update_channel:
                await broadcast_ongoing_episode(bot, f, target_channel=settings.update_channel)

    except Exception as exc:
        logger.error("Failed to auto-index storage channel post: %s", exc)


# ─── SubsPlease RSS Monitor (/rss, /checkrss) ─────────────────────────────────


@router.message(Command("rss", "checkrss", "subsplease"))
async def cmd_check_rss(message: Message) -> None:
    """Check the latest 1080p anime releases on SubsPlease RSS feed."""
    status = await message.answer("📡 <i>Checking SubsPlease RSS feed for new releases...</i>", parse_mode="HTML")
    releases = await fetch_subsplease_rss(resolution="1080", limit=8)

    if not releases:
        await status.edit_text("⚠️ <b>Could not fetch SubsPlease RSS.</b> Please try again shortly.", parse_mode="HTML")
        return

    text = (
        "📡 <b>SUBSPLEASE RECENT RELEASES (1080p)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    for item in releases:
        series = html.escape(item["series"] or item["title"])
        ep = f"Ep {item['episode']}" if item["episode"] is not None else ""
        size = item["size"] or "HD"
        pub = item["pub_date"].split("+")[0].strip() if "+" in item["pub_date"] else item["pub_date"]

        text += (
            f"🎬 <b>{series}</b> {ep}\n"
            f"📦 <code>{size}</code> • 🕐 <i>{pub}</i>\n\n"
        )

    text += (
        "💡 <i>Tip: Any file uploaded or forwarded by your Sub-Bot into the "
        "Storage Channel is automatically indexed and made instantly available to users!</i>"
    )

    await status.edit_text(text, parse_mode="HTML", disable_web_page_preview=True)
