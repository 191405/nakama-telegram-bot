"""User-facing command handlers: /start, /help, and force-subscribe check."""

from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.db import queries
from bot.keyboards.inline import episode_delivery_kb, force_sub_kb, main_menu_kb, profile_kb
from bot.utils.autodelete import start_schedule_deletion
from bot.utils.formatting import (
    HELP_TEXT,
    WELCOME_TEXT,
    format_file_caption,
    format_user_profile,
    format_welcome_card,
)
import asyncio

router = Router(name="user")


# ─── Force-Subscribe Helper ──────────────────────────────────────────────────


async def check_subscription(bot: Bot, user_id: int) -> bool:
    """Return True if user has joined the required channel (or if disabled)."""
    channel = settings.force_sub_channel
    if not channel:
        return True
    try:
        member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        # If bot can't check (not admin in channel, etc.), allow access
        return True


# ─── /start ──────────────────────────────────────────────────────────────────


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, bot: Bot) -> None:
    """Handle /start — register user, show welcome + main menu, or deliver deep-linked file."""
    user = message.from_user
    if user is None:
        return

    # Register / update user
    db_user = await queries.upsert_user(
        session, user.id, user.username, user.full_name
    )

    # Check ban
    if db_user.is_banned:
        await message.answer("⛔ You have been banned from using this bot.")
        return

    # Check forced subscription
    if not await check_subscription(bot, user.id):
        await message.answer(
            "📢 <b>Please join our channel first to use this bot.</b>",
            reply_markup=force_sub_kb(settings.force_sub_channel),  # type: ignore
            parse_mode="HTML",
        )
        return

    # Check for direct file deep-link: /start file_123 or /start 123
    if message.text:
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1:
            arg = parts[1].strip()
            file_id_str = arg.replace("file_", "")
            if file_id_str.isdigit():
                file_db_id = int(file_id_str)
                f = await queries.get_file(session, file_db_id)
                if f:
                    await queries.record_download(session, user.id, file_db_id)
                    caption = format_file_caption(f)

                    # Get adjacent episodes and series files
                    prev_file, next_file = await queries.find_adjacent_episodes(session, f)
                    series_files = await queries.get_series_files(session, f)
                    has_siblings = len(series_files) > 1

                    markup = episode_delivery_kb(
                        f, prev_file=prev_file, next_file=next_file, has_siblings=has_siblings
                    )

                    send_method = {
                        "document": bot.send_document,
                        "video": bot.send_video,
                        "audio": bot.send_audio,
                        "photo": bot.send_photo,
                        "animation": bot.send_animation,
                    }.get(f.file_type, bot.send_document)

                    sent_msg = await send_method(
                        chat_id=user.id,
                        **{f.file_type if f.file_type != "document" else "document": f.file_id},
                        caption=caption,
                        reply_markup=markup,
                        parse_mode="HTML",
                    )

                    if settings.auto_delete_minutes > 0:
                        notice_msg = await bot.send_message(
                            chat_id=user.id,
                            text=(
                                f"⏱️ <i>This file will self-destruct in {settings.auto_delete_minutes} minutes "
                                f"for copyright safety. Forward it to your <b>Saved Messages</b> to keep it!</i>"
                            ),
                            parse_mode="HTML",
                        )
                        start_schedule_deletion(
                            bot,
                            chat_id=user.id,
                            message_ids=[sent_msg.message_id, notice_msg.message_id],
                            delay_seconds=settings.auto_delete_minutes * 60,
                        )
                    return
                else:
                    await message.answer("❌ The requested file was not found or has been removed.")
                    return

    me = await bot.get_me()
    stats = await queries.get_community_stats(session)
    text = format_welcome_card(stats, me.username or "bot")
    await message.answer(text, reply_markup=main_menu_kb(), parse_mode="HTML")


# ─── Subscription Check Callback ─────────────────────────────────────────────


@router.callback_query(lambda c: c.data == "check_sub")
async def cb_check_sub(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    """Re-check subscription when user clicks 'I've Joined'."""
    if callback.from_user is None:
        return

    if await check_subscription(bot, callback.from_user.id):
        me = await bot.get_me()
        stats = await queries.get_community_stats(session)
        text = format_welcome_card(stats, me.username or "bot")
        await callback.message.edit_text(  # type: ignore
            text, reply_markup=main_menu_kb(), parse_mode="HTML"
        )
    else:
        await callback.answer(
            "❌ You haven't joined the channel yet!", show_alert=True
        )


# ─── User Profile & Passport ─────────────────────────────────────────────────


@router.message(Command("profile"))
async def cmd_profile(message: Message, session: AsyncSession) -> None:
    """Display user profile, ranking, and continue-watching."""
    if not message.from_user:
        return
    profile = await queries.get_user_profile(session, message.from_user.id)
    if not profile:
        await message.answer("❌ Profile not found.")
        return
    cont_id = (
        profile["next_file"].id
        if profile.get("next_file")
        else (profile["continue_file"].id if profile.get("continue_file") else None)
    )
    text = format_user_profile(profile)
    await message.answer(text, reply_markup=profile_kb(cont_id), parse_mode="HTML")


@router.callback_query(lambda c: c.data == "menu:profile")
async def cb_profile(callback: CallbackQuery, session: AsyncSession) -> None:
    """Display user profile from inline callback."""
    if not callback.from_user:
        return
    profile = await queries.get_user_profile(session, callback.from_user.id)
    if not profile:
        await callback.answer("Profile not found.", show_alert=True)
        return
    cont_id = (
        profile["next_file"].id
        if profile.get("next_file")
        else (profile["continue_file"].id if profile.get("continue_file") else None)
    )
    text = format_user_profile(profile)
    await callback.message.edit_text(text, reply_markup=profile_kb(cont_id), parse_mode="HTML")  # type: ignore
    await callback.answer()


# ─── Menu Navigation Callbacks ───────────────────────────────────────────────


@router.callback_query(lambda c: c.data == "menu:main")
async def cb_main_menu(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    """Return to the main menu."""
    me = await bot.get_me()
    stats = await queries.get_community_stats(session)
    text = format_welcome_card(stats, me.username or "bot")
    await callback.message.edit_text(  # type: ignore
        text, reply_markup=main_menu_kb(), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "menu:help")
async def cb_help(callback: CallbackQuery, bot: Bot) -> None:
    """Show help text."""
    me = await bot.get_me()
    text = HELP_TEXT.replace("{bot_username}", me.username or "bot")
    await callback.message.edit_text(  # type: ignore
        text, reply_markup=main_menu_kb(), parse_mode="HTML"
    )
    await callback.answer()
