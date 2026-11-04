"""Handlers for Airing Schedule, Watchlists, AI Personas, Trivia Leaderboards, and Voice Notes."""

from __future__ import annotations

import base64
import html
import io
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.db import queries
from bot.db.models import Watchlist
from bot.keyboards.inline import (
    airing_item_kb,
    airing_schedule_kb,
    leaderboard_kb,
    persona_picker_kb,
    trivia_quiz_kb,
    watchlist_item_actions_kb,
    watchlist_menu_kb,
)
from bot.utils.airing import fetch_today_airing_schedule
from bot.utils.gemini import ask_gemini_anime_concierge
from bot.utils.personas import PERSONAS, get_persona_info
from bot.utils.system_context import build_system_grounding
from bot.utils.trivia import TRIVIA_BANK, get_random_trivia

logger = logging.getLogger(__name__)

router = Router(name="features")


# ─── 1. Airing Schedule (/airing) ─────────────────────────────────────────────


@router.message(Command("airing"))
async def cmd_airing_schedule(message: Message) -> None:
    """Show today's anime broadcast schedule in Japan."""
    status = await message.answer("📡 <i>Fetching today's broadcast schedule from Japan...</i>", parse_mode="HTML")
    schedules = await fetch_today_airing_schedule(limit=25)
    if not schedules:
        await status.edit_text(
            "📅 <b>Airing Schedule</b>\n\n"
            "Could not fetch today's schedule right now. Please try again shortly!",
            parse_mode="HTML",
        )
        return

    text = (
        "📅 <b>Today's Anime Broadcasts (Japan)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Showing <b>{len(schedules)}</b> scheduled releases today.\n"
        "<i>Tap any title for details, vault availability, or watchlist bookmarking:</i>"
    )
    await status.edit_text(text, reply_markup=airing_schedule_kb(schedules, page=0), parse_mode="HTML")


@router.callback_query(lambda c: c.data and c.data == "menu:airing")
async def cb_menu_airing(callback: CallbackQuery) -> None:
    """Menu button for Airing Schedule."""
    await callback.answer("Loading broadcast schedule...")
    schedules = await fetch_today_airing_schedule(limit=25)
    if not schedules:
        await callback.message.edit_text("Could not fetch airing schedule right now.", parse_mode="HTML")
        return
    text = (
        "📅 <b>Today's Anime Broadcasts (Japan)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Showing <b>{len(schedules)}</b> scheduled releases today.\n"
        "<i>Tap any title for details, vault availability, or watchlist bookmarking:</i>"
    )
    await callback.message.edit_text(text, reply_markup=airing_schedule_kb(schedules, page=0), parse_mode="HTML")


@router.callback_query(lambda c: c.data and c.data.startswith("airing_pg:"))
async def cb_airing_page(callback: CallbackQuery) -> None:
    """Paginate airing schedule."""
    page = int(callback.data.split(":")[1])
    schedules = await fetch_today_airing_schedule(limit=25)
    text = (
        "📅 <b>Today's Anime Broadcasts (Japan)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Page <b>{page + 1}</b> • Showing scheduled releases today.\n"
        "<i>Tap any title to view details:</i>"
    )
    await callback.message.edit_text(text, reply_markup=airing_schedule_kb(schedules, page=page), parse_mode="HTML")
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("airing_detail:"))
async def cb_airing_detail(callback: CallbackQuery) -> None:
    """View details of a single scheduled anime."""
    sched_id = int(callback.data.split(":")[1])
    schedules = await fetch_today_airing_schedule(limit=30)
    item = next((s for s in schedules if s["id"] == sched_id), None)
    if not item:
        await callback.answer("Episode info expired or not found.", show_alert=True)
        return

    genres_str = ", ".join(item["genres"][:4]) if item["genres"] else "Anime"
    text = (
        f"📺 <b>{html.escape(item['title'])}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Episode:</b> {item['episode']}\n"
        f"• <b>Broadcast:</b> {item['countdown']}\n"
        f"• <b>Genres:</b> {genres_str}\n\n"
        f"<i>Check if we have earlier episodes in our vault or save it to your watchlist:</i>"
    )
    await callback.message.edit_text(
        text, reply_markup=airing_item_kb(item["title"], item["url"]), parse_mode="HTML"
    )
    await callback.answer()


# ─── 2. Personal Watchlist (/watchlist) ───────────────────────────────────────


@router.message(Command("watchlist"))
async def cmd_watchlist(message: Message, session: AsyncSession) -> None:
    """View user's personal saved anime watchlist."""
    if not message.from_user:
        return
    items = await queries.get_user_watchlist(session, message.from_user.id)
    if not items:
        await message.answer(
            "🔖 <b>Your Anime Watchlist is Empty!</b>\n\n"
            "You haven't bookmarked any anime yet.\n"
            "Search for any title or browse the feed, then tap <b>[🔖 Add to Watchlist]</b> to track your favorite series!",
            parse_mode="HTML",
        )
        return

    watching = [i for i in items if i.status == "watching"]
    plan = [i for i in items if i.status == "plan_to_watch"]
    done = [i for i in items if i.status == "completed"]

    text = (
        f"🔖 <b>{html.escape(message.from_user.first_name)}'s Anime Watchlist</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 <b>Watching:</b> {len(watching)} series\n"
        f"🟡 <b>Plan to Watch:</b> {len(plan)} series\n"
        f"🔵 <b>Completed:</b> {len(done)} series\n\n"
        "<i>Tap any series below to stream, check themes, or update status:</i>"
    )
    await message.answer(text, reply_markup=watchlist_menu_kb(items), parse_mode="HTML")


@router.callback_query(lambda c: c.data and c.data == "menu:watchlist")
async def cb_menu_watchlist(callback: CallbackQuery, session: AsyncSession) -> None:
    """Menu button for Watchlist."""
    items = await queries.get_user_watchlist(session, callback.from_user.id)
    if not items:
        await callback.message.edit_text(
            "🔖 <b>Your Anime Watchlist is Empty!</b>\n\n"
            "You haven't bookmarked any anime yet.\n"
            "Search for any title or browse the feed, then tap <b>[🔖 Add to Watchlist]</b> to track your favorite series!",
            parse_mode="HTML",
        )
        await callback.answer()
        return

    text = (
        f"🔖 <b>{html.escape(callback.from_user.first_name)}'s Anime Watchlist</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Tracking <b>{len(items)}</b> series in your collection.\n\n"
        "<i>Tap any series to stream, check themes, or update status:</i>"
    )
    await callback.message.edit_text(text, reply_markup=watchlist_menu_kb(items), parse_mode="HTML")
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("wl_add:"))
async def cb_watchlist_add(callback: CallbackQuery, session: AsyncSession) -> None:
    """Bookmark an anime to watchlist."""
    series_name = callback.data.split(":", 1)[1].strip()
    await queries.add_to_watchlist(session, callback.from_user.id, series_name, status="watching")
    await callback.answer(f"✅ Added '{series_name[:20]}' to your Watchlist!", show_alert=True)


@router.callback_query(lambda c: c.data and c.data.startswith("wl_item:"))
async def cb_watchlist_item(callback: CallbackQuery, session: AsyncSession) -> None:
    """View a single watchlist item."""
    item_id = int(callback.data.split(":")[1])
    item = await session.get(Watchlist, item_id)
    if not item or item.user_id != callback.from_user.id:
        await callback.answer("Item not found.", show_alert=True)
        return

    status_name = {
        "watching": "🟢 Currently Watching",
        "plan_to_watch": "🟡 Plan to Watch",
        "completed": "🔵 Completed",
    }.get(item.status, item.status)

    text = (
        f"🔖 <b>Watchlist: {html.escape(item.series_name)}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Status:</b> {status_name}\n"
        f"• <b>Saved on:</b> {item.created_at.strftime('%Y-%m-%d')}\n\n"
        "<i>Select an action below:</i>"
    )
    await callback.message.edit_text(
        text,
        reply_markup=watchlist_item_actions_kb(item.id, item.series_name, item.status),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("wl_stat:"))
async def cb_watchlist_status(callback: CallbackQuery, session: AsyncSession) -> None:
    """Update watchlist status."""
    parts = callback.data.split(":")
    item_id = int(parts[1])
    new_status = parts[2]
    item = await session.get(Watchlist, item_id)
    if item and item.user_id == callback.from_user.id:
        item.status = new_status
        await session.commit()
        await callback.answer(f"Updated status to {new_status.replace('_', ' ').title()}!")
        # Refresh screen
        await cb_watchlist_item(callback, session)
    else:
        await callback.answer("Could not update item.", show_alert=True)


@router.callback_query(lambda c: c.data and c.data.startswith("wl_del:"))
async def cb_watchlist_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    """Remove item from watchlist."""
    item_id = int(callback.data.split(":")[1])
    item = await session.get(Watchlist, item_id)
    if item and item.user_id == callback.from_user.id:
        await session.delete(item)
        await session.commit()
        await callback.answer("Removed from watchlist.")
        await cb_menu_watchlist(callback, session)
    else:
        await callback.answer("Could not delete item.", show_alert=True)


# ─── 3. AI Persona Switcher (/persona) ────────────────────────────────────────


@router.message(Command("persona"))
async def cmd_persona_picker(message: Message, session: AsyncSession) -> None:
    """Select active character persona for the AI."""
    if not message.from_user:
        return
    current_persona = await queries.get_user_persona(session, message.from_user.id)
    curr_info = get_persona_info(current_persona)

    text = (
        "🎭 <b>AI Character Persona Switcher</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Current Active Persona:</b> {curr_info['emoji']} <b>{curr_info['name']}</b>\n"
        f"<i>\"{curr_info['tagline']}\"</i>\n\n"
        "Choose who answers your questions and speaks with you in chat:"
    )
    await message.answer(text, reply_markup=persona_picker_kb(current_persona), parse_mode="HTML")


@router.callback_query(lambda c: c.data and c.data == "menu:persona")
async def cb_menu_persona(callback: CallbackQuery, session: AsyncSession) -> None:
    """Menu button for Persona picker."""
    current_persona = await queries.get_user_persona(session, callback.from_user.id)
    curr_info = get_persona_info(current_persona)
    text = (
        "🎭 <b>AI Character Persona Switcher</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Current Active Persona:</b> {curr_info['emoji']} <b>{curr_info['name']}</b>\n"
        f"<i>\"{curr_info['tagline']}\"</i>\n\n"
        "Choose who answers your questions and speaks with you in chat:"
    )
    await callback.message.edit_text(text, reply_markup=persona_picker_kb(current_persona), parse_mode="HTML")
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("set_persona:"))
async def cb_set_persona(callback: CallbackQuery, session: AsyncSession) -> None:
    """Save user persona preference."""
    key = callback.data.split(":")[1]
    info = get_persona_info(key)
    await queries.set_user_persona(session, callback.from_user.id, key)

    await callback.answer(f"Activated persona: {info['name']}!", show_alert=True)
    # Refresh view
    text = (
        "🎭 <b>AI Character Persona Switcher</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Current Active Persona:</b> {info['emoji']} <b>{info['name']}</b>\n"
        f"<i>\"{info['tagline']}\"</i>\n\n"
        "Choose who answers your questions and speaks with you in chat:"
    )
    await callback.message.edit_text(text, reply_markup=persona_picker_kb(key), parse_mode="HTML")


# ─── 4. Daily Anime Trivia & Bounty XP (/trivia) ──────────────────────────────


@router.message(Command("trivia", "quiz"))
async def cmd_trivia_quiz(message: Message, session: AsyncSession) -> None:
    """Play anime trivia and earn XP bounty."""
    if not message.from_user:
        return
    q = get_random_trivia()
    text = (
        "🎯 <b>Daily Anime Trivia & Bounty Challenge</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"❓ <b>Question:</b>\n"
        f"<i>{html.escape(q['question'])}</i>\n\n"
        "💰 <b>Reward:</b> +50 Community Bounty XP\n"
        "<i>Select the correct answer below:</i>"
    )
    await message.answer(text, reply_markup=trivia_quiz_kb(q["hash"], q["options"]), parse_mode="HTML")


@router.callback_query(lambda c: c.data and c.data == "menu:trivia")
async def cb_menu_trivia(callback: CallbackQuery, session: AsyncSession) -> None:
    """Menu button for Trivia."""
    q = get_random_trivia()
    text = (
        "🎯 <b>Daily Anime Trivia & Bounty Challenge</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"❓ <b>Question:</b>\n"
        f"<i>{html.escape(q['question'])}</i>\n\n"
        "💰 <b>Reward:</b> +50 Community Bounty XP\n"
        "<i>Select the correct answer below:</i>"
    )
    await callback.message.edit_text(text, reply_markup=trivia_quiz_kb(q["hash"], q["options"]), parse_mode="HTML")
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("trivia_ans:"))
async def cb_trivia_answer(callback: CallbackQuery, session: AsyncSession) -> None:
    """Evaluate trivia answer."""
    parts = callback.data.split(":")
    q_hash = parts[1]
    chosen_idx = int(parts[2])

    # Find the question in TRIVIA_BANK
    matching_q = None
    for q in TRIVIA_BANK:
        import hashlib
        if hashlib.sha256(q["question"].encode()).hexdigest()[:16] == q_hash:
            matching_q = q
            break

    if not matching_q:
        await callback.answer("Question session expired. Send /trivia to play again!", show_alert=True)
        return

    is_correct = (chosen_idx == matching_q["correct"])
    points = 50 if is_correct else 0

    await queries.record_trivia_answer(
        session,
        user_id=callback.from_user.id,
        question_hash=q_hash,
        is_correct=is_correct,
        points=points,
    )

    if is_correct:
        res_header = "🎉 <b>CORRECT! +50 Bounty XP Earned!</b>"
    else:
        correct_text = matching_q["options"][matching_q["correct"]]
        res_header = f"❌ <b>Not quite! The correct answer was:</b> {correct_text}"

    text = (
        f"{res_header}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 <b>Lore Note:</b>\n"
        f"<i>{matching_q['explanation']}</i>\n\n"
        "Check your updated rank on the Leaderboard or take on another question!"
    )
    await callback.message.edit_text(text, reply_markup=leaderboard_kb(), parse_mode="HTML")
    await callback.answer()


# ─── 5. Leaderboard (/leaderboard) ───────────────────────────────────────────


@router.message(Command("leaderboard"))
async def cmd_leaderboard(message: Message, session: AsyncSession) -> None:
    """View top Nakama community members."""
    leaders = await queries.get_leaderboard(session, limit=10)
    lines = []
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

    for idx, u in enumerate(leaders):
        medal = medals[idx] if idx < len(medals) else f"#{idx+1}"
        uname = f"@{u['username']}" if u['username'] else u['full_name']
        lines.append(
            f"{medal} <b>{html.escape(uname)}</b>\n"
            f"   └ {u['rank']} • <b>{u['xp']} XP</b> • {u['downloads']} downloads"
        )

    leaderboard_str = "\n".join(lines) if lines else "No ranked members yet. Play /trivia to be #1!"

    text = (
        "🏆 <b>Nakama Network Community Bounty Leaderboard</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{leaderboard_str}\n\n"
        "<i>Earn XP Bounty by answering Daily Anime Trivia!</i>"
    )
    await message.answer(text, reply_markup=leaderboard_kb(), parse_mode="HTML")


@router.callback_query(lambda c: c.data and c.data == "menu:leaderboard")
async def cb_menu_leaderboard(callback: CallbackQuery, session: AsyncSession) -> None:
    """Menu button for Leaderboard."""
    leaders = await queries.get_leaderboard(session, limit=10)
    lines = []
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

    for idx, u in enumerate(leaders):
        medal = medals[idx] if idx < len(medals) else f"#{idx+1}"
        uname = f"@{u['username']}" if u['username'] else u['full_name']
        lines.append(
            f"{medal} <b>{html.escape(uname)}</b>\n"
            f"   └ {u['rank']} • <b>{u['xp']} XP</b> • {u['downloads']} downloads"
        )

    leaderboard_str = "\n".join(lines) if lines else "No ranked members yet. Play /trivia to be #1!"

    text = (
        "🏆 <b>Nakama Network Community Bounty Leaderboard</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{leaderboard_str}\n\n"
        "<i>Earn XP Bounty by answering Daily Anime Trivia!</i>"
    )
    await callback.message.edit_text(text, reply_markup=leaderboard_kb(), parse_mode="HTML")
    await callback.answer()


# ─── 6. Voice Note Comprehension (Voice-to-Voice AI) ─────────────────────────


@router.message(F.voice)
async def voice_message_handler(message: Message, session: AsyncSession, bot: Bot) -> None:
    """Handle incoming Telegram voice notes with Gemini AI comprehension."""
    if not message.voice:
        return

    user_id = message.from_user.id if message.from_user else 0
    user_name = message.from_user.full_name if message.from_user else "Friend"
    username = message.from_user.username if message.from_user else None

    status = await message.answer("🎙️ <i>Listening to your voice note...</i>", parse_mode="HTML")
    if message.bot:
        await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")

    try:
        # Download audio from Telegram CDN
        file_info = await bot.get_file(message.voice.file_id)
        if not file_info.file_path:
            await status.edit_text("Could not retrieve voice file from Telegram.", parse_mode="HTML")
            return

        audio_bytes_io = io.BytesIO()
        await bot.download_file(file_info.file_path, destination=audio_bytes_io)
        audio_b64 = base64.b64encode(audio_bytes_io.getvalue()).decode("utf-8")

        grounding, matching_files, primary_title, persona_prompt = await build_system_grounding(
            session=session,
            user_id=user_id,
            user_name=user_name,
            username=username,
            current_query=None,
        )

        reply = await ask_gemini_anime_concierge(
            query="",
            user_id=user_id,
            system_grounding=grounding,
            audio_base64=audio_b64,
            audio_mime_type="audio/ogg",
        )

        await status.edit_text(f"🎙️ <i>Voice Note:</i>\n\n{reply}", parse_mode="HTML", disable_web_page_preview=True)

    except Exception as exc:
        logger.error("Failed to process voice note: %s", exc)
        await status.edit_text("Sorry, I had trouble hearing that voice note. Could you try sending it again?", parse_mode="HTML")
