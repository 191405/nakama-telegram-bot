"""Callback handlers for file detail, download, Next/Prev episode navigation, AniList cards, batch download, and requests."""

from __future__ import annotations

import asyncio
import html
import logging

from aiogram import Bot, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.db import queries
from bot.keyboards.inline import episode_delivery_kb, file_detail_kb, file_list_kb, request_admin_kb
from bot.utils.anilist import fetch_anime_info, format_anilist_card
from bot.utils.autodelete import start_schedule_deletion
from bot.utils.episodes import extract_series_name
from bot.utils.formatting import format_file_caption, format_file_detail

logger = logging.getLogger(__name__)

router = Router(name="callbacks")


# ─── File Detail View ────────────────────────────────────────────────────────


@router.callback_query(lambda c: c.data and c.data.startswith("file:"))
async def cb_file_detail(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show file details when user clicks on a file in the list."""
    if callback.data is None:
        return

    file_db_id = int(callback.data.split(":")[1])
    f = await queries.get_file(session, file_db_id)

    if f is None:
        await callback.answer("❌ File not found!", show_alert=True)
        return

    await callback.message.edit_text(  # type: ignore
        format_file_detail(f),
        reply_markup=file_detail_kb(f),
        parse_mode="HTML",
    )
    await callback.answer()


# ─── View All Series Episodes (Feed, Profile, Themes) ─────────────────────────


@router.callback_query(lambda c: c.data and c.data.startswith("episodes:"))
async def cb_view_episodes(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show all episodes of a series when user taps 'View All Episodes' or 'Continue'."""
    if callback.data is None:
        return

    try:
        file_db_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Invalid episode request.", show_alert=True)
        return

    f = await queries.get_file(session, file_db_id)
    if f is None:
        await callback.answer("❌ Episode not found!", show_alert=True)
        return

    series_files = await queries.get_series_files(session, f)
    series_name = f.category.name if f.category else extract_series_name(f.file_name)
    safe_series = html.escape(series_name)

    text = (
        f"🎬 <b>Available Episodes for {safe_series} ({len(series_files)} eps):</b>\n\n"
        f"<i>Tap any episode below to watch or download immediately:</i>"
    )
    kb = file_list_kb(
        series_files,
        page=0,
        page_size=settings.page_size,
        prefix="search",
        context_id=series_name[:30],
    )

    if callback.message:
        try:
            if callback.message.photo:
                await callback.message.delete()
                await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
            else:
                await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")

    await callback.answer()


# ─── Download File with Next/Prev Buttons & Auto-Delete ──────────────────────


@router.callback_query(lambda c: c.data and c.data.startswith("dl:"))
async def cb_download(
    callback: CallbackQuery, session: AsyncSession, bot: Bot
) -> None:
    """Send the file with Next/Prev episode buttons and optional auto-delete."""
    if callback.data is None or callback.from_user is None:
        return

    file_db_id = int(callback.data.split(":")[1])
    f = await queries.get_file(session, file_db_id)

    if f is None:
        await callback.answer("❌ File not found or deleted!", show_alert=True)
        return

    # Record the download
    await queries.record_download(session, callback.from_user.id, file_db_id)

    caption = format_file_caption(f)
    chat_id = callback.from_user.id

    # Discover adjacent episodes (Next / Prev) and series siblings
    prev_file, next_file = await queries.find_adjacent_episodes(session, f)
    series_files = await queries.get_series_files(session, f)
    has_siblings = len(series_files) > 1

    markup = episode_delivery_kb(
        f, prev_file=prev_file, next_file=next_file, has_siblings=has_siblings
    )

    try:
        send_method = {
            "document": bot.send_document,
            "video": bot.send_video,
            "audio": bot.send_audio,
            "photo": bot.send_photo,
            "animation": bot.send_animation,
        }.get(f.file_type, bot.send_document)

        sent_msg = await send_method(
            chat_id=chat_id,
            **{f.file_type if f.file_type != "document" else "document": f.file_id},
            caption=caption,
            reply_markup=markup,
            parse_mode="HTML",
        )
        await callback.answer("📥 Episode sent!")

        # Auto-delete schedule if enabled
        if settings.auto_delete_minutes > 0:
            notice_msg = await bot.send_message(
                chat_id=chat_id,
                text=(
                    f"⏱️ <i>This file will self-destruct in {settings.auto_delete_minutes} minutes "
                    f"for copyright safety. Forward it to your <b>Saved Messages</b> to keep it!</i>"
                ),
                parse_mode="HTML",
            )
            start_schedule_deletion(
                bot,
                chat_id=chat_id,
                message_ids=[sent_msg.message_id, notice_msg.message_id],
                delay_seconds=settings.auto_delete_minutes * 60,
            )

    except Exception as e:
        logger.error("Failed to send file %s: %s", f.id, e)
        await callback.answer("❌ Failed to send file. Please try again.", show_alert=True)


# ─── Batch Download (Send Entire Season / All Episodes) ───────────────────────


@router.callback_query(lambda c: c.data and c.data.startswith("batch_dl:"))
async def cb_batch_download(
    callback: CallbackQuery, session: AsyncSession, bot: Bot
) -> None:
    """Send all episodes of the series sequentially."""
    if callback.data is None or callback.from_user is None:
        return

    file_db_id = int(callback.data.split(":")[1])
    f = await queries.get_file(session, file_db_id)
    if f is None:
        await callback.answer("File not found!", show_alert=True)
        return

    series_files = await queries.get_series_files(session, f)
    if not series_files:
        await callback.answer("No episodes found!", show_alert=True)
        return

    chat_id = callback.from_user.id
    await callback.answer(f"📦 Delivering {len(series_files)} episodes...", show_alert=False)

    status_msg = await bot.send_message(
        chat_id=chat_id,
        text=f"📦 <b>Sending {len(series_files)} episodes...</b> Please wait a moment.",
        parse_mode="HTML",
    )

    sent_ids = [status_msg.message_id]
    for ep in series_files:
        try:
            send_method = {
                "document": bot.send_document,
                "video": bot.send_video,
                "audio": bot.send_audio,
                "photo": bot.send_photo,
                "animation": bot.send_animation,
            }.get(ep.file_type, bot.send_document)

            caption = format_file_caption(ep)
            msg = await send_method(
                chat_id=chat_id,
                **{ep.file_type if ep.file_type != "document" else "document": ep.file_id},
                caption=caption,
                parse_mode="HTML",
            )
            sent_ids.append(msg.message_id)
            await queries.record_download(session, chat_id, ep.id)
            await asyncio.sleep(1.0)  # Gentle delay to avoid Telegram flood limits
        except Exception as e:
            logger.error("Error in batch delivery file %s: %s", ep.id, e)

    await status_msg.edit_text(
        f"✅ <b>Delivered all {len(series_files)} episodes!</b>",
        parse_mode="HTML",
    )

    if settings.auto_delete_minutes > 0:
        notice_msg = await bot.send_message(
            chat_id=chat_id,
            text=(
                f"⏱️ <i>These files will self-destruct in {settings.auto_delete_minutes} minutes. "
                f"Forward them to your <b>Saved Messages</b> to keep them!</i>"
            ),
            parse_mode="HTML",
        )
        sent_ids.append(notice_msg.message_id)
        start_schedule_deletion(
            bot,
            chat_id=chat_id,
            message_ids=sent_ids,
            delay_seconds=settings.auto_delete_minutes * 60,
        )


# ─── AniList Metadata & Poster Card ──────────────────────────────────────────


@router.callback_query(lambda c: c.data and c.data.startswith("info:"))
async def cb_anime_info(
    callback: CallbackQuery, session: AsyncSession, bot: Bot
) -> None:
    """Fetch AniList poster and card and display to user."""
    if callback.data is None or callback.from_user is None:
        return

    file_db_id = int(callback.data.split(":")[1])
    f = await queries.get_file(session, file_db_id)
    if f is None:
        await callback.answer("File not found!", show_alert=True)
        return

    series_title = f.category.name if f.category else extract_series_name(f.file_name)

    await callback.answer("🎌 Fetching anime details from AniList...", show_alert=False)
    media = await fetch_anime_info(series_title)

    if not media:
        await callback.answer(f"No AniList metadata found for '{series_title}'.", show_alert=True)
        return

    card_text = format_anilist_card(media)
    cover_url = media.get("coverImage", {}).get("large") or media.get("bannerImage")

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📥 Download This Episode", callback_data=f"dl:{f.id}"),
        InlineKeyboardButton(text="📦 Download All", callback_data=f"batch_dl:{f.id}"),
    )
    builder.row(
        InlineKeyboardButton(text="🔙 Back to Menu", callback_data="menu:main")
    )

    if cover_url:
        try:
            await bot.send_photo(
                chat_id=callback.from_user.id,
                photo=cover_url,
                caption=card_text,
                reply_markup=builder.as_markup(),
                parse_mode="HTML",
            )
            return
        except Exception:
            pass

    await bot.send_message(
        chat_id=callback.from_user.id,
        text=card_text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


# ─── User Anime Requests ─────────────────────────────────────────────────────


@router.callback_query(lambda c: c.data and (c.data.startswith("req_add:") or c.data.startswith("req_anime:")))
async def cb_add_request(
    callback: CallbackQuery, session: AsyncSession, bot: Bot
) -> None:
    """Submit user request for an anime and notify admins."""
    if callback.data is None or callback.from_user is None:
        return

    anime_title = callback.data.split(":", 1)[1].strip()
    safe_title = html.escape(anime_title)
    user_id = callback.from_user.id
    username = f"@{callback.from_user.username}" if callback.from_user.username else html.escape(callback.from_user.full_name)

    req = await queries.create_request(session, user_id, anime_title)

    if callback.message:
        await callback.message.edit_text(  # type: ignore
            f"✅ <b>Request Submitted!</b>\n\n"
            f"We've sent your request for <b>\"{safe_title}\"</b> to our admin team.\n"
            f"You will be notified automatically the moment it gets uploaded to <b>Nakama Network</b>!",
            parse_mode="HTML",
        )
    await callback.answer("Request sent to admins!")

    notify_text = (
        f"📩 <b>New Anime Request!</b> (ID: #{req.id})\n\n"
        f"🎬 <b>Title:</b> <code>{safe_title}</code>\n"
        f"👤 <b>From:</b> {username} (ID: <code>{user_id}</code>)\n"
        f"🕐 <b>Time:</b> {req.created_at.strftime('%Y-%m-%d %H:%M')}"
    )
    admin_kb = request_admin_kb(req.id)

    target_channel = settings.request_channel
    if target_channel:
        try:
            await bot.send_message(target_channel, notify_text, reply_markup=admin_kb, parse_mode="HTML")
            return
        except Exception:
            pass

    for admin_id in settings.admin_id_list:
        try:
            await bot.send_message(admin_id, notify_text, reply_markup=admin_kb, parse_mode="HTML")
        except Exception:
            pass


@router.callback_query(lambda c: c.data and c.data.startswith("req_done:"))
async def cb_fulfill_request(
    callback: CallbackQuery, session: AsyncSession, bot: Bot
) -> None:
    """Admin marks anime request as fulfilled and alerts the user."""
    if callback.data is None or callback.from_user is None:
        return

    # Security check: Only admins can mark requests fulfilled
    if callback.from_user.id not in settings.admin_id_list:
        await callback.answer("⛔ Only administrators can fulfill requests.", show_alert=True)
        return

    req_id = int(callback.data.split(":")[1])
    req = await queries.fulfill_request(session, req_id)
    if not req:
        await callback.answer("Request not found!", show_alert=True)
        return

    await callback.message.edit_text(  # type: ignore
        f"✅ <b>Request #{req.id} marked as Fulfilled!</b>\n\n"
        f"🎬 Anime: <b>{req.anime_title}</b>",
        parse_mode="HTML",
    )
    await callback.answer("Fulfilled!")

    # Alert the requesting user
    try:
        await bot.send_message(
            chat_id=req.user_id,
            text=(
                f"🎉 <b>Great News!</b>\n\n"
                f"The anime you requested — <b>\"{req.anime_title}\"</b> — has just been added to <b>Nakama Network</b>!\n\n"
                f"💬 Send <code>{req.anime_title}</code> in chat right now to download it!"
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass
