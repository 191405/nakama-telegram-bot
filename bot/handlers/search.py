"""Search, browse, latest, and popular file handlers."""

from __future__ import annotations

import html
import io
import random
import re

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession


from bot.config import settings
from bot.db import queries
from bot.keyboards.inline import (
    browse_hub_kb,
    categories_kb,
    episode_delivery_kb,
    feed_navigation_kb,
    file_detail_kb,
    file_list_kb,
    not_found_kb,
    ongoing_series_list_kb,
    scene_result_kb,
    series_list_kb,
    theme_list_kb,
)
from bot.utils.anilist import fetch_anilist_info
from bot.utils.animethemes import fetch_anime_themes
from bot.utils.episodes import extract_episode_number, extract_series_name as clean_series_name
from bot.utils.formatting import format_feed_card, format_file_caption, format_file_detail

from bot.utils.fuzzy import find_closest_match
from bot.utils.gemini import ask_gemini_anime_concierge
from bot.utils.memory import clear_conversation, get_active_series, set_active_series
from bot.utils.system_context import build_system_grounding
from bot.utils.trace_moe import identify_anime_scene

router = Router(name="search")




# ─── /search <query> ─────────────────────────────────────────────────────────


@router.message(Command("search"))
async def cmd_search(message: Message, session: AsyncSession) -> None:
    """Search files by name with fuzzy typo correction."""
    if message.text is None:
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            "🔍 <b>Usage:</b> <code>/search query</code>\n\n"
            "Example: <code>/search dead account</code>",
            parse_mode="HTML",
        )
        return

    query = parts[1].strip()
    files = await queries.search_files(session, query, limit=50)

    safe_query = html.escape(query)

    if not files:
        # Check for close matches / typos
        all_titles = await queries.get_all_searchable_titles(session)
        closest = find_closest_match(query, all_titles)
        if closest:
            fuzzy_files = await queries.search_files(session, closest, limit=50)
            if fuzzy_files:
                await message.answer(
                    f"🔍 Showing results for <b>{html.escape(closest)}</b> "
                    f"<i>(auto-corrected from \"{safe_query}\")</i>:",
                    reply_markup=file_list_kb(
                        fuzzy_files,
                        page=0,
                        page_size=settings.page_size,
                        prefix="search",
                        context_id=closest,
                    ),
                    parse_mode="HTML",
                )
                return

        await message.answer(
            f"😕 <b>I couldn't find any anime or files matching:</b>\n"
            f"<code>\"{safe_query}\"</code>\n\n"
            f"💡 Tap below to request it or explore our categories:",
            reply_markup=not_found_kb(query),
            parse_mode="HTML",
        )
        return

    await message.answer(
        f"🔍 Found <b>{len(files)}</b> result(s) for <b>{safe_query}</b>:",
        reply_markup=file_list_kb(
            files,
            page=0,
            page_size=settings.page_size,
            prefix="search",
            context_id=query,
        ),
        parse_mode="HTML",
    )


@router.callback_query(lambda c: c.data and c.data.startswith("menu:search"))
async def cb_search_prompt(callback: CallbackQuery) -> None:
    """Prompt user to use /search command."""
    await callback.message.edit_text(  # type: ignore
        "🔍 <b>Search Files</b>\n\n"
        "Send me a search query using:\n"
        "<code>/search your query here</code>\n\n"
        "Example: <code>/search naruto episode 1</code>",
        parse_mode="HTML",
    )
    await callback.answer()


# ─── Search Pagination ───────────────────────────────────────────────────────


@router.callback_query(lambda c: c.data and c.data.startswith("search:"))
async def cb_search_page(callback: CallbackQuery, session: AsyncSession) -> None:
    """Handle search result pagination."""
    if callback.data is None:
        return

    # Format: search:<query>:<page>
    parts = callback.data.split(":")
    if len(parts) < 3:
        return

    query = parts[1]
    page = int(parts[2])
    files = await queries.search_files(session, query, limit=50)

    await callback.message.edit_text(  # type: ignore
        f"🔍 Found <b>{len(files)}</b> result(s) for <b>{query}</b>:",
        reply_markup=file_list_kb(
            files, page=page, page_size=settings.page_size,
            prefix="search", context_id=query,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


# ─── /browse Hub (Series & Genres) ──────────────────────────────────────────


@router.message(Command("browse"))
async def cmd_browse(message: Message, session: AsyncSession) -> None:
    """Open the Anime Vault Browse Hub."""
    cats = await queries.get_all_categories(session)
    summaries = await queries.get_all_series_summaries(session)

    await message.answer(
        "📂 <b>Anime Vault Hub</b>\n\n"
        f"Explore our collection of <b>{len(summaries)}</b> anime series "
        f"across <b>{len(cats)}</b> genre categories.\n\n"
        "How would you like to explore?",
        reply_markup=browse_hub_kb(categories_count=len(cats), series_count=len(summaries)),
        parse_mode="HTML",
    )


@router.callback_query(lambda c: c.data == "menu:browse")
async def cb_browse(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show Browse Hub via inline menu."""
    cats = await queries.get_all_categories(session)
    summaries = await queries.get_all_series_summaries(session)

    await callback.message.edit_text(  # type: ignore
        "📂 <b>Anime Vault Hub</b>\n\n"
        f"Explore our collection of <b>{len(summaries)}</b> anime series "
        f"across <b>{len(cats)}</b> genre categories.\n\n"
        "How would you like to explore?",
        reply_markup=browse_hub_kb(categories_count=len(cats), series_count=len(summaries)),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("browse:series:"))
async def cb_browse_series(callback: CallbackQuery, session: AsyncSession) -> None:
    """Browse all distinct anime series in alphabetical order with episode counts."""
    if callback.data is None:
        return
    page = int(callback.data.split(":")[2])
    summaries = await queries.get_all_series_summaries(session)
    if not summaries:
        await callback.answer("No series indexed yet!", show_alert=True)
        return

    # Sort series alphabetically
    summaries.sort(key=lambda s: s["name"].lower())

    await callback.message.edit_text(  # type: ignore
        f"🎬 <b>All Indexed Anime Series</b> ({len(summaries)} shows):\n\n"
        f"<i>Tap any series to see all available episodes:</i>",
        reply_markup=series_list_kb(summaries, page=page, page_size=settings.page_size),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("browse:ongoing:"))
async def cb_browse_ongoing(callback: CallbackQuery, session: AsyncSession) -> None:
    """Browse ongoing anime series in the vault sorted by latest release."""
    if callback.data is None:
        return
    page = int(callback.data.split(":")[2])
    summaries = await queries.get_all_series_summaries(session)
    if not summaries:
        await callback.answer("No anime series indexed yet! Check back soon.", show_alert=True)
        return

    # Sort by the most recently uploaded episode
    summaries.sort(key=lambda s: s["latest_file"].created_at, reverse=True)

    await callback.message.edit_text(  # type: ignore
        f"⚡ <b>Ongoing & Airing Anime Collection</b> ({len(summaries)} series):\n\n"
        f"<i>Fresh episodes auto-tracked from broadcast feeds.\n"
        f"Tap any anime to access all episodes, qualities, and downloads:</i>",
        reply_markup=ongoing_series_list_kb(summaries, page=page, page_size=settings.page_size),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "browse:genres")
async def cb_browse_genres(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show genre categories."""
    cats = await queries.get_all_categories(session)
    if not cats:
        await callback.answer("No categories yet! Check back soon.", show_alert=True)
        return

    await callback.message.edit_text(  # type: ignore
        f"📂 <b>Browse by Genre ({len(cats)} available):</b>\n\n"
        f"<i>Choose a genre to view episodes:</i>",
        reply_markup=categories_kb(cats),
        parse_mode="HTML",
    )
    await callback.answer()



# ─── Category File Listing ───────────────────────────────────────────────────


@router.callback_query(lambda c: c.data and c.data.startswith("cat:"))
async def cb_category_files(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show files in a category with pagination."""
    if callback.data is None:
        return

    # Format: cat:<category_id>:<page>
    parts = callback.data.split(":")
    category_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0

    cat = await queries.get_category(session, category_id)
    if cat is None:
        await callback.answer("Category not found!", show_alert=True)
        return

    files = await queries.get_files_by_category(session, category_id, limit=100)
    if not files:
        await callback.answer(f"No files in {cat.name} yet!", show_alert=True)
        return

    await callback.message.edit_text(  # type: ignore
        f"{cat.emoji} <b>{cat.name}</b> — {len(files)} file(s):",
        reply_markup=file_list_kb(
            files, page=page, page_size=settings.page_size,
            prefix="cat", context_id=str(category_id),
        ),
        parse_mode="HTML",
    )
    await callback.answer()


# ─── /latest ─────────────────────────────────────────────────────────────────


@router.message(Command("latest"))
async def cmd_latest(message: Message, session: AsyncSession) -> None:
    """Show the most recently uploaded files."""
    files = await queries.get_latest_files(session, limit=20)
    if not files:
        await message.answer("📭 No files uploaded yet!")
        return

    await message.answer(
        "🆕 <b>Latest Uploads:</b>",
        reply_markup=file_list_kb(
            files, page=0, page_size=settings.page_size,
            prefix="latest", context_id="0",
        ),
        parse_mode="HTML",
    )


@router.callback_query(lambda c: c.data == "menu:latest")
async def cb_latest(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show latest files via menu button."""
    files = await queries.get_latest_files(session, limit=20)
    if not files:
        await callback.answer("No files uploaded yet!", show_alert=True)
        return

    await callback.message.edit_text(  # type: ignore
        "🆕 <b>Latest Uploads:</b>",
        reply_markup=file_list_kb(
            files, page=0, page_size=settings.page_size,
            prefix="latest", context_id="0",
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("latest:"))
async def cb_latest_page(callback: CallbackQuery, session: AsyncSession) -> None:
    """Handle latest files pagination."""
    if callback.data is None:
        return
    parts = callback.data.split(":")
    page = int(parts[2]) if len(parts) > 2 else 0

    files = await queries.get_latest_files(session, limit=20)
    await callback.message.edit_text(  # type: ignore
        "🆕 <b>Latest Uploads:</b>",
        reply_markup=file_list_kb(
            files, page=page, page_size=settings.page_size,
            prefix="latest", context_id="0",
        ),
        parse_mode="HTML",
    )
    await callback.answer()


# ─── /popular ────────────────────────────────────────────────────────────────


@router.message(Command("popular"))
async def cmd_popular(message: Message, session: AsyncSession) -> None:
    """Show the most downloaded files."""
    files = await queries.get_popular_files(session, limit=20)
    if not files:
        await message.answer("📭 No files downloaded yet!")
        return

    await message.answer(
        "🔥 <b>Most Popular:</b>",
        reply_markup=file_list_kb(
            files, page=0, page_size=settings.page_size,
            prefix="popular", context_id="0",
        ),
        parse_mode="HTML",
    )


@router.callback_query(lambda c: c.data == "menu:popular")
async def cb_popular(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show popular files via menu button."""
    files = await queries.get_popular_files(session, limit=20)
    if not files:
        await callback.answer("No downloads yet!", show_alert=True)
        return

    await callback.message.edit_text(  # type: ignore
        "🔥 <b>Most Popular:</b>",
        reply_markup=file_list_kb(
            files, page=0, page_size=settings.page_size,
            prefix="popular", context_id="0",
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("popular:"))
async def cb_popular_page(callback: CallbackQuery, session: AsyncSession) -> None:
    """Handle popular files pagination."""
    if callback.data is None:
        return
    parts = callback.data.split(":")
    page = int(parts[2]) if len(parts) > 2 else 0

    files = await queries.get_popular_files(session, limit=20)
    await callback.message.edit_text(  # type: ignore
        "🔥 <b>Most Popular:</b>",
        reply_markup=file_list_kb(
            files, page=page, page_size=settings.page_size,
            prefix="popular", context_id="0",
        ),
        parse_mode="HTML",
    )
    await callback.answer()


# ─── Natural Language Chat Search ────────────────────────────────────────────


PATTERNS = [
    r"^(?:hey|hello|hi|yo|sup|good\s+(?:morning|evening|afternoon))[\s,!\.]*",
    r"^(?:bot|nakama)[\s,!\.]*",
    r"^(?:can\s+you\s+(?:please\s+)?(?:find|get|give\s+me|show\s+me|search))[\s:]*",
    r"^(?:could\s+you\s+(?:please\s+)?(?:find|get|give\s+me|show\s+me|search))[\s:]*",
    r"^(?:do\s+you\s+have|have\s+you\s+got)[\s:]*",
    r"^(?:i\s+want\s+to\s+(?:watch|download|find|get|see))[\s:]*",
    r"^(?:i\s+(?:want|need|am\s+looking\s+for|look\s+for))[\s:]*",
    r"^(?:please\s+(?:give\s+me|send|find|get))[\s:]*",
    r"^(?:give\s+me|send\s+me|show\s+me|find\s+me|search\s+for)[\s:]*",
    r"^(?:where\s+is|where\s+can\s+i\s+find)[\s:]*",
]

GREETING_WORDS = {"hi", "hello", "hey", "yo", "sup", "thanks", "thank you", "help"}


def clean_conversational_query(text: str) -> str:
    """Clean conversational filler words from user message."""
    c = text.strip()
    for _ in range(4):
        prev = c
        for pat in PATTERNS:
            c = re.sub(pat, "", c, flags=re.IGNORECASE).strip()
        if c == prev:
            break
    c = re.sub(r"[\s,]+(?:please|pls)[\s!\.\?]*$", "", c, flags=re.IGNORECASE)
    c = re.sub(r"[\s!\.\?]+$", "", c).strip()
    return c or text.strip()


REQUEST_BLACKLIST = {
    "send them", "send it", "the episodes", "the episodes?", "the episode",
    "episode", "episodes", "yes", "no", "what", "how", "why", "who", "tell",
    "tell me", "please", "thanks", "thank you", "hello", "hi", "can you",
    "is that the only episode", "is this the only episode", "none", "recommend",
    "suggest", "anime", "manga", "more", "ok", "okay", "send", "them", "it",
    "all", "where", "which", "send me", "give me", "give them", "give it",
    "send them please", "send please", "send the files", "send video",
}


DELIVERY_TRIGGERS = [
    r"\b(?:send|give\s+me|drop|deliver|watch|download|get|stream|play|view)\b",
    r"\b(?:the\s+episodes?|all\s+episodes?|ep\s*\d+|episode\s*\d+)\b",
    r"\b(?:send\s+them|send\s+it|send\s+episode|send\s+ep|send\s+me)\b",
]


async def send_file_to_chat(
    message: Message,
    f: queries.File,
    session: AsyncSession,
) -> None:
    """Send a media file directly to the chat with caption and episode navigation."""
    caption = format_file_caption(f)
    prev_file, next_file = await queries.find_adjacent_episodes(session, f)
    series_files = await queries.get_series_files(session, f)
    has_siblings = len(series_files) > 1

    markup = episode_delivery_kb(
        f, prev_file=prev_file, next_file=next_file, has_siblings=has_siblings
    )

    send_method = {
        "document": message.answer_document,
        "video": message.answer_video,
        "audio": message.answer_audio,
        "photo": message.answer_photo,
        "animation": message.answer_animation,
    }.get(f.file_type, message.answer_document)

    await send_method(
        **{f.file_type if f.file_type != "document" else "document": f.file_id},
        caption=caption,
        reply_markup=markup,
        parse_mode="HTML",
    )
    if message.from_user:
        await queries.record_download(session, message.from_user.id, f.id)


@router.message(StateFilter(None), F.text, ~F.text.startswith("/"))
async def chat_search_handler(message: Message, session: AsyncSession) -> None:
    """Handle natural text chat from users with fully connected AI brain and library search."""
    if message.text is None:
        return

    raw_text = message.text.strip()
    if not raw_text:
        return

    user_id = message.from_user.id if message.from_user else 0
    user_name = message.from_user.full_name if message.from_user else "Friend"
    username = message.from_user.username if message.from_user else None
    raw_lower = raw_text.lower().strip()

    # ─── 0. DIRECT EPISODE DELIVERY AUTHORITY ───────────────────────────────────
    # If the user asks to send/download/deliver episodes, execute immediately!
    is_delivery_intent = (
        raw_lower in {
            "send them", "send it", "the episodes?", "the episodes", "the episode",
            "send all", "give them", "give it", "send them please", "send please",
            "send the files", "send video", "send the video", "send episode 1",
            "send ep 1", "episode 1", "ep 1", "episodes"
        }
        or (
            any(re.search(pat, raw_text, re.IGNORECASE) for pat in DELIVERY_TRIGGERS)
            and any(w in raw_lower for w in ["send", "drop", "deliver", "download", "give", "watch", "play", "get", "ep", "episode", "them", "it", "all"])
        )
    )

    if is_delivery_intent:
        ep_num = extract_episode_number(raw_text)
        query_candidate = clean_conversational_query(raw_text)
        target_series_files: list[queries.File] = []
        target_series_name: str | None = None

        # 1. Check if user typed an anime name directly in the request
        if len(query_candidate) >= 3 and query_candidate.lower() not in REQUEST_BLACKLIST:
            target_series_files = await queries.search_files(session, query_candidate, limit=50)
            if target_series_files:
                target_series_name = clean_series_name(target_series_files[0].file_name)

        # 2. If not found in query, fall back to active series in conversation memory
        if not target_series_files:
            active_ctx = get_active_series(user_id)
            if active_ctx:
                target_series_files = await queries.search_files(session, active_ctx, limit=50)
                if target_series_files:
                    target_series_name = active_ctx

        # 3. If we have matching files for the series, deliver directly!
        if target_series_files and target_series_name:
            set_active_series(user_id, target_series_name)

            if ep_num is not None:
                # Find specific episode
                matched = next(
                    (f for f in target_series_files if extract_episode_number(f.file_name) == ep_num),
                    None,
                )
                if matched:
                    await message.answer(
                        f"🎬 <b>Delivering Episode {ep_num} of {html.escape(target_series_name)}!</b>",
                        parse_mode="HTML",
                    )
                    await send_file_to_chat(message, matched, session)
                    return
                else:
                    # Episode not available, but series has other files
                    avail_nums = [
                        extract_episode_number(f.file_name)
                        for f in target_series_files
                        if extract_episode_number(f.file_name) is not None
                    ]
                    avail_str = ", ".join(f"Ep {n}" for n in sorted(avail_nums)) if avail_nums else "Episode 1"
                    await message.answer(
                        f"📺 We currently only have <b>{avail_str}</b> for <b>{html.escape(target_series_name)}</b> in the vault.\n"
                        f"Delivering what we have right now:",
                        parse_mode="HTML",
                    )
                    await send_file_to_chat(message, target_series_files[0], session)
                    return
            else:
                # User asked for all/plural ("Send them", "The episodes?", "send it")
                if len(target_series_files) == 1:
                    await message.answer(
                        f"🎬 <b>Delivering Episode 1 of {html.escape(target_series_name)}!</b>",
                        parse_mode="HTML",
                    )
                    await send_file_to_chat(message, target_series_files[0], session)
                    return
                else:
                    # Multiple episodes available
                    builder = InlineKeyboardBuilder()
                    # Add batch download button
                    builder.row(
                        InlineKeyboardButton(
                            text=f"📦 Deliver All {len(target_series_files)} Episodes",
                            callback_data=f"batch_dl:{target_series_files[0].id}",
                        )
                    )
                    kb = file_list_kb(
                        target_series_files,
                        page=0,
                        page_size=settings.page_size,
                        prefix="search",
                        context_id=target_series_name,
                    )
                    await message.answer(
                        f"🎬 <b>Available Episodes for {html.escape(target_series_name)} ({len(target_series_files)} eps):</b>\n\n"
                        f"<i>Tap any episode to watch or download immediately:</i>",
                        reply_markup=kb,
                        parse_mode="HTML",
                    )
                    return

    # Check if user is asking a conversational question or general query
    ai_question_pattern = (
        r"^(what|why|who|how|when|where|is|can|could|would|should|tell|explain|recommend|suggest|give|do|does|did|are|was|were|hey|hello|hi|yo|sup|thanks|thank)\b"
    )
    is_conversational = (
        bool(re.search(ai_question_pattern, raw_text, re.IGNORECASE))
        or raw_text.endswith("?")
        or len(raw_text.split()) >= 4
        or raw_lower in GREETING_WORDS
    )

    query = clean_conversational_query(raw_text)

    # 1. If it's NOT conversational (user typed a direct series name like 'Bleach' or 'Naruto')
    if not is_conversational:
        files = await queries.search_files(session, query, limit=50)
        if not files and query != raw_text:
            files = await queries.search_files(session, raw_text, limit=50)

        if files:
            safe_query = html.escape(query)
            target_series = clean_series_name(files[0].file_name) or query
            set_active_series(user_id, target_series)
            await message.answer(
                f"🔍 Found <b>{len(files)}</b> result(s) for <b>{safe_query}</b>:\n"
                f"<i>Tap below to view or download:</i>",
                reply_markup=file_list_kb(
                    files,
                    page=0,
                    page_size=settings.page_size,
                    prefix="search",
                    context_id=query,
                ),
                parse_mode="HTML",
            )
            return

        # Check fuzzy match in database
        all_titles = await queries.get_all_searchable_titles(session)
        closest = find_closest_match(query, all_titles)
        if closest:
            fuzzy_files = await queries.search_files(session, closest, limit=50)
            if fuzzy_files:
                target_series = clean_series_name(fuzzy_files[0].file_name) or closest
                set_active_series(user_id, target_series)
                await message.answer(
                    f"🔍 Showing results for <b>{html.escape(closest)}</b> "
                    f"<i>(auto-corrected from \"{html.escape(query)}\")</i>:",
                    reply_markup=file_list_kb(
                        fuzzy_files,
                        page=0,
                        page_size=settings.page_size,
                        prefix="search",
                        context_id=closest,
                    ),
                    parse_mode="HTML",
                )
                return

    # 2. Fully Connected AI Brain: conversational queries OR fallback if title search found nothing
    if settings.gemini_api_key:
        if message.bot:
            await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")

        grounding, matching_files, primary_title, _ = await build_system_grounding(
            session=session,
            user_id=user_id,
            user_name=user_name,
            username=username,
            current_query=query,
        )

        reply = await ask_gemini_anime_concierge(
            query=raw_text,
            user_id=user_id,
            system_grounding=grounding,
        )

        # Build smart action buttons underneath the AI's response
        markup = None
        buttons: list[list[InlineKeyboardButton]] = []

        if matching_files:
            # If library has matching files for what they asked, offer instant watch and download buttons
            target_series = primary_title or clean_series_name(matching_files[0].file_name) or query
            set_active_series(user_id, target_series)

            buttons.append([
                InlineKeyboardButton(
                    text=f"🎬 View {target_series[:22]} ({len(matching_files)} eps)",
                    callback_data=f"search_txt:{target_series[:30]}",
                )
            ])
            if len(matching_files) == 1:
                buttons.append([
                    InlineKeyboardButton(
                        text="📥 Download Episode 1",
                        callback_data=f"dl:{matching_files[0].id}",
                    )
                ])
            else:
                buttons.append([
                    InlineKeyboardButton(
                        text=f"📦 Deliver All {len(matching_files)} Episodes",
                        callback_data=f"batch_dl:{matching_files[0].id}",
                    )
                ])
            # Offer theme songs button
            buttons.append([
                InlineKeyboardButton(
                    text="🎵 Themes (OP/ED)",
                    callback_data=f"themes:{target_series[:30]}",
                )
            ])
        else:
            # Check if user asked for a valid anime that is missing in vault
            candidate_req = (primary_title or query).strip("?!. '\"")
            req_lower = candidate_req.lower()

            if (
                req_lower not in REQUEST_BLACKLIST
                and len(candidate_req) >= 3
                and not any(w in req_lower.split() for w in ["send", "them", "it", "episode", "episodes", "the", "files", "video"])
            ):
                buttons.append([
                    InlineKeyboardButton(
                        text=f"📝 Request '{candidate_req[:24]}'",
                        callback_data=f"req_anime:{candidate_req[:30]}",
                    )
                ])

        if buttons:
            markup = InlineKeyboardMarkup(inline_keyboard=buttons)

        await message.answer(reply, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)
        return


    # 3. Fallback if AI key is not configured
    safe_query = html.escape(query)
    if is_conversational:
        await message.answer(
            f"👋 <b>Hey {html.escape(user_name)}!</b> I hear you!\n\n"
            f"To connect my full conversational AI brain across all chat and questions, "
            f"an admin can configure a free key using:\n"
            f"<code>/setgemini &lt;API_KEY&gt;</code>\n\n"
            f"In the meantime, feel free to send any anime title to search the vault!",
            reply_markup=not_found_kb(query),
            parse_mode="HTML",
        )
    else:
        await message.answer(
            f"😕 <b>I couldn't find any anime or files matching:</b>\n"
            f"<code>\"{safe_query}\"</code>\n\n"
            f"💡 Tap below to request it or explore our categories:",
            reply_markup=not_found_kb(query),
            parse_mode="HTML",
        )


# ─── /request <anime> ────────────────────────────────────────────────────────


@router.message(Command("request"))
async def cmd_request_anime(message: Message, session: AsyncSession, bot: Bot) -> None:
    """Allow users to request missing anime series."""
    if message.text is None:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            "📩 <b>Usage:</b> <code>/request &lt;anime name&gt;</code>\n\n"
            "Example: <code>/request Chainsaw Man</code>",
            parse_mode="HTML",
        )
        return

    anime_title = parts[1].strip()
    user = message.from_user
    if user is None:
        return

    req = await queries.create_request(session, user.id, anime_title)
    username = f"@{user.username}" if user.username else user.full_name

    await message.answer(
        f"✅ <b>Request Submitted!</b>\n\n"
        f"We've logged your request for <b>\"{html.escape(anime_title)}\"</b>.\n"
        f"You will get an automated notification as soon as it's uploaded!",
        parse_mode="HTML",
    )

    notify_text = (
        f"📩 <b>New Anime Request!</b> (ID: #{req.id})\n\n"
        f"🎬 <b>Title:</b> <code>{html.escape(anime_title)}</code>\n"
        f"👤 <b>From:</b> {username} (ID: <code>{user.id}</code>)\n"
        f"🕐 <b>Time:</b> {req.created_at.strftime('%Y-%m-%d %H:%M')}"
    )
    from bot.keyboards.inline import request_admin_kb
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


@router.callback_query(lambda c: c.data == "menu:request")
async def cb_request_menu(callback: CallbackQuery) -> None:
    """Prompt user to make an anime request."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    text = (
        "📩 <b>Request Missing Anime</b>\n\n"
        "Can't find an anime or episode in our library?\n\n"
        "Simply send:\n"
        "<code>/request &lt;anime name&gt;</code>\n\n"
        "<i>Example:</i> <code>/request Attack on Titan</code>\n\n"
        "Our curators will be notified instantly and upload it for you!"
    )
    markup = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 Back to Menu", callback_data="menu:main")]]
    )
    if callback.message:
        await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    await callback.answer()


# ─── Channel Stream Feed ─────────────────────────────────────────────────────


async def _render_feed_entry(
    target: Message | CallbackQuery,
    session: AsyncSession,
    index: int,
    is_callback: bool = False,
) -> None:
    """Render a single series card in Channel Stream Feed mode."""
    summaries = await queries.get_all_series_summaries(session)
    if not summaries:
        msg_text = "📺 <b>Channel Feed is Empty</b>\n\nNo anime series indexed yet."
        if is_callback:
            await target.message.answer(msg_text, parse_mode="HTML")  # type: ignore
            await target.answer()  # type: ignore
        else:
            await target.answer(msg_text, parse_mode="HTML")  # type: ignore
        return

    idx = index % len(summaries)
    series = summaries[idx]
    anilist = await fetch_anilist_info(series["name"])

    text = format_feed_card(series, anilist, idx, len(summaries))
    markup = feed_navigation_kb(series["name"], idx, len(summaries), series["sample_file"].id)

    cover = anilist.get("cover_image") if anilist else None

    if is_callback:
        cb: CallbackQuery = target  # type: ignore
        try:
            if cover and cb.message and cb.message.photo:  # type: ignore
                await cb.message.edit_media(  # type: ignore
                    InputMediaPhoto(media=cover, caption=text, parse_mode="HTML"),
                    reply_markup=markup,
                )
            elif cover:
                if cb.message:
                    await cb.message.delete()
                await cb.bot.send_photo(  # type: ignore
                    chat_id=cb.from_user.id,
                    photo=cover,
                    caption=text,
                    reply_markup=markup,
                    parse_mode="HTML",
                )
            else:
                if cb.message:
                    await cb.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        except Exception:
            if cover and cb.message:
                await cb.message.answer_photo(photo=cover, caption=text, reply_markup=markup, parse_mode="HTML")
            elif cb.message:
                await cb.message.answer(text, reply_markup=markup, parse_mode="HTML")
        await cb.answer()
    else:
        msg: Message = target  # type: ignore
        if cover:
            await msg.answer_photo(photo=cover, caption=text, reply_markup=markup, parse_mode="HTML")
        else:
            await msg.answer(text, reply_markup=markup, parse_mode="HTML")


@router.message(Command("feed"))
async def cmd_feed(message: Message, session: AsyncSession) -> None:
    """Open the Channel Stream Feed."""
    await _render_feed_entry(message, session, 0, is_callback=False)


@router.callback_query(lambda c: c.data and c.data.startswith("feed:"))
async def cb_feed(callback: CallbackQuery, session: AsyncSession) -> None:
    """Handle feed navigation callbacks (feed:<idx>, feed:random)."""
    if not callback.data:
        return
    arg = callback.data.split(":", 1)[1]
    summaries = await queries.get_all_series_summaries(session)
    if not summaries:
        await callback.answer("No series in feed yet.", show_alert=True)
        return

    if arg == "random":
        idx = random.randint(0, len(summaries) - 1)
    else:
        try:
            idx = int(arg)
        except ValueError:
            idx = 0

    await _render_feed_entry(callback, session, idx, is_callback=True)


# ─── Reverse Anime Scene Search (Trace.moe) ──────────────────────────────────


@router.message(F.photo)
@router.message(Command("whatanime"))
async def handle_photo_scene_search(message: Message, bot: Bot, session: AsyncSession) -> None:
    """Analyze an anime screenshot to identify the show, episode, and timestamp."""
    photo = None
    if message.photo:
        photo = message.photo[-1]
    elif message.reply_to_message and message.reply_to_message.photo:
        photo = message.reply_to_message.photo[-1]

    if not photo:
        await message.answer(
            "📸 <b>Anime Scene Recognition (Trace.moe)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Send any anime screenshot or reply to an image with <code>/whatanime</code>!\n\n"
            "💡 <b>Tips for best results:</b>\n"
            "• Use an original, uncropped screenshot\n"
            "• Remove black bars and subtitles if possible\n"
            "• Screenshots from 1990s–current anime are supported",
            parse_mode="HTML",
        )
        return

    status_msg = await message.answer(
        "🔍 <i>Scanning anime frame with Trace.moe neural engine...</i>",
        parse_mode="HTML",
    )

    try:
        file_io = io.BytesIO()
        await bot.download(photo, destination=file_io)
        image_bytes = file_io.getvalue()

        match = await identify_anime_scene(image_bytes)
        if not match:
            await status_msg.edit_text(
                "⚠️ <b>Could not identify this anime frame.</b>\n\n"
                "Please try a clearer, unedited screenshot without heavy filters or text overlays!",
                parse_mode="HTML",
            )
            return

        similarity = match.get("similarity", 0.0)
        title_en = match.get("title_english") or match.get("title_romaji") or "Unknown"
        title_romaji = match.get("title_romaji") or ""
        title_native = match.get("title_native") or ""
        ep = match.get("episode") if match.get("episode") is not None else "?"
        from_t = match.get("from_time", "00:00")
        to_t = match.get("to_time", "00:00")
        conf_pct = similarity * 100

        conf_emoji = "🎯" if conf_pct >= 85 else "⚠️"
        conf_note = "High Confidence" if conf_pct >= 85 else "Probable Match"

        caption = (
            f"{conf_emoji} <b>ANIME SCENE IDENTIFIED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎬 <b>Title:</b> <b>{html.escape(title_en)}</b>\n"
            f"🇯🇵 <b>Romaji:</b> <i>{html.escape(title_romaji)}</i>\n"
        )
        if title_native:
            caption += f"🈳 <b>Native:</b> <code>{html.escape(title_native)}</code>\n"

        caption += (
            f"📺 <b>Episode:</b> <code>{ep}</code>\n"
            f"⏱ <b>Timestamp:</b> <code>{from_t} - {to_t}</code>\n"
            f"📊 <b>Confidence:</b> <b>{conf_pct:.1f}%</b> ({conf_note})\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 <i>Powered by Trace.moe Engine</i>"
        )

        markup = scene_result_kb(
            anime_title=title_en,
            anilist_id=match.get("anilist_id"),
            video_url=match.get("video_url"),
        )

        preview_img = match.get("image_url")
        if preview_img:
            try:
                await status_msg.delete()
                await message.answer_photo(
                    photo=preview_img,
                    caption=caption,
                    reply_markup=markup,
                    parse_mode="HTML",
                )
                return
            except Exception:
                pass

        await status_msg.edit_text(caption, reply_markup=markup, parse_mode="HTML")

    except Exception as exc:
        await status_msg.edit_text(
            f"⚠️ <b>Error processing image:</b> <code>{html.escape(str(exc))}</code>",
            parse_mode="HTML",
        )


# ─── Anime Themes & Music (AnimeThemes.moe) ──────────────────────────────────


@router.message(Command("themes", "music"))
async def cmd_anime_themes(message: Message) -> None:
    """Fetch anime opening and ending themes with video stream links."""
    if message.text is None:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            "🎵 <b>Usage:</b> <code>/themes &lt;anime name&gt;</code>\n\n"
            "<i>Example:</i> <code>/themes Attack on Titan</code>",
            parse_mode="HTML",
        )
        return

    query = parts[1].strip()
    status = await message.answer(f"🎶 <i>Searching themes archive for '{html.escape(query)}'...</i>", parse_mode="HTML")

    data = await fetch_anime_themes(query)
    if not data or not data.get("themes"):
        await status.edit_text(
            f"🎶 <b>No official theme songs found in the archive for:</b>\n"
            f"<code>\"{html.escape(query)}\"</code>\n\n"
            f"<i>Try searching by its official English or Japanese Romaji title!</i>",
            parse_mode="HTML",
        )
        return

    anime_name = html.escape(data.get("anime_name") or query)
    year = data.get("year") or ""
    season = data.get("season") or ""
    themes = data.get("themes", [])

    text = (
        f"🎵 <b>ANIME SOUNDTRACK & THEMES</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎬 <b>{anime_name}</b>"
    )
    if year:
        text += f" ({str(season).capitalize()} {year})"
    text += f"\nFound <b>{len(themes)}</b> theme(s):\n\n"

    for t in themes[:8]:
        slug = t.get("slug", "Theme")
        s_title = html.escape(t.get("song_title", "Unknown"))
        artist = html.escape(t.get("artist", ""))
        v_url = t.get("video_url")
        res = t.get("resolution", "")

        text += f"• <b>{slug}:</b> {s_title}"
        if artist:
            text += f" — <i>{artist}</i>"
        if v_url:
            text += f" [<a href='{v_url}'>Watch {res}</a>]"
        text += "\n"

    text += "\n💡 <i>Tap any theme button below to stream the video in HD!</i>"

    markup = theme_list_kb(themes, anime_query=query)
    await status.edit_text(text, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)


@router.callback_query(lambda c: c.data and c.data.startswith("themes:"))
async def cb_anime_themes(callback: CallbackQuery, session: AsyncSession) -> None:
    """Handle theme callbacks from feed cards or scene search."""
    if not callback.data:
        return

    raw_arg = callback.data.split(":", 1)[1]
    anime_title = ""
    sample_file_id = None

    if raw_arg.startswith("file_"):
        try:
            fid = int(raw_arg.replace("file_", ""))
            f = await queries.get_file_by_id(session, fid)
            if f:
                sample_file_id = f.id
                anime_title = clean_series_name(f.file_name)
        except Exception:
            pass
    elif raw_arg.startswith("text_"):
        anime_title = raw_arg.replace("text_", "")
    else:
        anime_title = raw_arg

    if not anime_title:
        await callback.answer("Anime name not found.", show_alert=True)
        return

    await callback.answer("🎶 Loading themes...")
    data = await fetch_anime_themes(anime_title)
    if not data or not data.get("themes"):
        if callback.message:
            await callback.message.answer(
                f"🎶 <b>No official theme songs found in archive for:</b>\n"
                f"<code>\"{html.escape(anime_title)}\"</code>",
                parse_mode="HTML",
            )
        return

    name = html.escape(data.get("anime_name") or anime_title)
    year = data.get("year") or ""
    season = data.get("season") or ""
    themes = data.get("themes", [])

    text = (
        f"🎵 <b>ANIME SOUNDTRACK & THEMES</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎬 <b>{name}</b>"
    )
    if year:
        text += f" ({str(season).capitalize()} {year})"
    text += f"\nFound <b>{len(themes)}</b> theme(s):\n\n"

    for t in themes[:8]:
        slug = t.get("slug", "Theme")
        s_title = html.escape(t.get("song_title", "Unknown"))
        artist = html.escape(t.get("artist", ""))
        v_url = t.get("video_url")
        res = t.get("resolution", "")

        text += f"• <b>{slug}:</b> {s_title}"
        if artist:
            text += f" — <i>{artist}</i>"
        if v_url:
            text += f" [<a href='{v_url}'>Watch {res}</a>]"
        text += "\n"

    text += "\n💡 <i>Tap any theme button below to stream the video in HD!</i>"

    markup = theme_list_kb(themes, sample_file_id=sample_file_id, anime_query=anime_title)
    if callback.message:
        await callback.message.answer(text, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)


# ─── AI Anime Concierge (Google Gemini) ──────────────────────────────────────


@router.message(Command("ask"))
async def cmd_ask_ai(message: Message, session: AsyncSession) -> None:
    """Ask Nakama for recommendations, lore, and general questions."""
    if message.text is None:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            "💬 <b>Ask Me Anything</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "You can ask me about anything—anime recommendations, lore, trivia, or general questions!\n\n"
            "<b>Usage:</b> <code>/ask &lt;your question&gt;</code>\n\n"
            "<i>(You can also simply type your question in chat without using /ask!)</i>",
            parse_mode="HTML",
        )
        return

    prompt = parts[1].strip()
    status = await message.answer("💭 <i>Thinking...</i>", parse_mode="HTML")
    if message.bot:
        await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")

    user_id = message.from_user.id if message.from_user else 0
    user_name = message.from_user.full_name if message.from_user else "Friend"
    username = message.from_user.username if message.from_user else None

    grounding, matching_files, primary_title, _ = await build_system_grounding(
        session=session,
        user_id=user_id,
        user_name=user_name,
        username=username,
        current_query=prompt,
    )

    reply = await ask_gemini_anime_concierge(
        query=prompt,
        user_id=user_id,
        system_grounding=grounding,
    )

    buttons: list[list[InlineKeyboardButton]] = []
    if matching_files:
        target = primary_title or clean_series_name(matching_files[0].file_name) or prompt
        buttons.append([
            InlineKeyboardButton(
                text=f"🎬 View {target[:22]} ({len(matching_files)} eps)",
                callback_data=f"search_txt:{target[:30]}",
            )
        ])
    markup = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None

    await status.edit_text(reply, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)


@router.message(Command("newchat", "resetai"))
async def cmd_reset_ai(message: Message) -> None:
    """Clear conversation history for the user."""
    if not message.from_user:
        return
    clear_conversation(message.from_user.id)
    await message.answer(
        "✨ <b>Conversation memory reset!</b> What would you like to explore next?",
        parse_mode="HTML",
    )



@router.message(Command("setgemini"))
async def cmd_set_gemini(message: Message) -> None:
    """Admin command to dynamically set or update the Gemini API key."""
    if not message.from_user or message.from_user.id not in settings.admin_id_list:
        return
    if message.text is None:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer("🔑 <b>Usage:</b> <code>/setgemini &lt;API_KEY&gt;</code>", parse_mode="HTML")
        return

    new_key = parts[1].strip()
    settings.gemini_api_key = new_key
    await message.answer(
        "✅ <b>Google Gemini API Key configured!</b>\n\n"
        "Nakama AI Concierge is now active for all users across <code>/ask</code> and natural chat.",
        parse_mode="HTML",
    )


# ─── Inline Search & Menu Handlers ───────────────────────────────────────────


@router.callback_query(lambda c: c.data and c.data.startswith("search_txt:"))
async def cb_search_text(callback: CallbackQuery, session: AsyncSession) -> None:
    """Execute search from an inline button."""
    if not callback.data:
        return
    query = callback.data.split(":", 1)[1].strip()
    files = await queries.search_files(session, query, limit=50)
    safe_q = html.escape(query)
    if not files:
        all_titles = await queries.get_all_searchable_titles(session)
        closest = find_closest_match(query, all_titles)
        if closest:
            fuzzy_files = await queries.search_files(session, closest, limit=50)
            if fuzzy_files and callback.message:
                await callback.message.answer(
                    f"🔍 Showing results for <b>{html.escape(closest)}</b>:",
                    reply_markup=file_list_kb(fuzzy_files, 0, settings.page_size, "search", closest),
                    parse_mode="HTML",
                )
                await callback.answer()
                return

        if callback.message:
            await callback.message.answer(
                f"😕 <b>I couldn't find '{safe_q}' in our database.</b>",
                reply_markup=not_found_kb(query),
                parse_mode="HTML",
            )
    else:
        if callback.message:
            await callback.message.answer(
                f"🔍 Found <b>{len(files)}</b> result(s) for <b>{safe_q}</b>:",
                reply_markup=file_list_kb(files, 0, settings.page_size, "search", query),
                parse_mode="HTML",
            )
    await callback.answer()


@router.callback_query(lambda c: c.data == "menu:whatanime")
async def cb_menu_whatanime(callback: CallbackQuery) -> None:
    """Show instructions for Trace.moe scene recognition."""
    if callback.message:
        await callback.message.answer(
            "📸 <b>ANIME SCENE DETECTOR (Trace.moe)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Uncover any anime from a single picture!\n\n"
            "<b>How to use:</b>\n"
            "1. Simply <b>send any photo/screenshot</b> directly to this chat.\n"
            "2. Or reply to an existing image with <code>/whatanime</code>.\n\n"
            "<i>Our neural recognition will detect the anime title, episode, and exact timestamp in seconds!</i>",
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(lambda c: c.data == "menu:ask_ai")
async def cb_menu_ask_ai(callback: CallbackQuery) -> None:
    """Show instructions for AI companion."""
    if callback.message:
        await callback.message.answer(
            "💬 <b>CHAT WITH NAKAMA</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Ask me anything you want—anime recommendations, lore, science, gaming, or general questions!\n\n"
            "<b>How to chat:</b>\n"
            "• Just type your question or thought naturally into the chat!\n"
            "• Or use <code>/ask &lt;question&gt;</code> anytime.\n\n"
            "<i>I understand natural language, casual chat, and out-of-context questions.</i>",
            parse_mode="HTML",
        )
    await callback.answer()




