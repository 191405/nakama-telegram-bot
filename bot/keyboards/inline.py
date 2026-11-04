"""Inline keyboard builders for the bot UI."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.db.models import Category, File
from bot.utils.episodes import extract_episode_number


# ─── Main Menu ────────────────────────────────────────────────────────────────


def main_menu_kb() -> InlineKeyboardMarkup:
    """Build the main menu keyboard."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⚡ Ongoing Anime", callback_data="browse:ongoing:0"),
        InlineKeyboardButton(text="📅 Airing Today", callback_data="menu:airing"),
    )
    builder.row(
        InlineKeyboardButton(text="📺 Channel Stream Feed", callback_data="feed:0"),
    )
    builder.row(
        InlineKeyboardButton(text="🔍 Search Anime", callback_data="menu:search"),
        InlineKeyboardButton(text="📂 Browse Vault", callback_data="menu:browse"),
    )
    builder.row(
        InlineKeyboardButton(text="🔖 My Watchlist", callback_data="menu:watchlist"),
        InlineKeyboardButton(text="📸 Identify Scene", callback_data="menu:whatanime"),
    )
    builder.row(
        InlineKeyboardButton(text="🎯 Daily Trivia & XP", callback_data="menu:trivia"),
        InlineKeyboardButton(text="🏆 Leaderboard", callback_data="menu:leaderboard"),
    )
    builder.row(
        InlineKeyboardButton(text="🎭 AI Persona", callback_data="menu:persona"),
        InlineKeyboardButton(text="🤖 AI Concierge", callback_data="menu:ask_ai"),
    )
    builder.row(
        InlineKeyboardButton(text="👤 My Passport", callback_data="menu:profile"),
        InlineKeyboardButton(text="📩 Request Anime", callback_data="menu:request"),
    )
    builder.row(
        InlineKeyboardButton(text="📖 User Guide", callback_data="menu:help"),
    )
    return builder.as_markup()




# ─── Browse Hub & Series ──────────────────────────────────────────────────────


def browse_hub_kb(categories_count: int = 0, series_count: int = 0) -> InlineKeyboardMarkup:
    """Build the main Browse Hub keyboard."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="⚡ Ongoing Anime Collection",
            callback_data="browse:ongoing:0",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=f"🎬 Browse All Series ({series_count} shows)",
            callback_data="browse:series:0",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=f"📂 Browse by Genre ({categories_count} genres)",
            callback_data="browse:genres",
        )
    )
    builder.row(
        InlineKeyboardButton(text="🆕 Latest Uploads", callback_data="menu:latest"),
        InlineKeyboardButton(text="🔥 Most Popular", callback_data="menu:popular"),
    )
    builder.row(
        InlineKeyboardButton(text="🔙 Back to Menu", callback_data="menu:main")
    )
    return builder.as_markup()


def series_list_kb(
    summaries: list[dict],
    page: int = 0,
    page_size: int = 8,
) -> InlineKeyboardMarkup:
    """Build a keyboard listing distinct anime series."""
    builder = InlineKeyboardBuilder()

    start = page * page_size
    end = start + page_size
    page_items = summaries[start:end]

    for item in page_items:
        name = item["name"]
        count = item["total_episodes"]
        label = f"🎬 {name[:32]} ({count} ep{'s' if count != 1 else ''})"
        builder.row(
            InlineKeyboardButton(
                text=label,
                callback_data=f"search_txt:{name[:30]}",
            )
        )

    # Pagination row
    nav_buttons: list[InlineKeyboardButton] = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(
                text="◀️ Prev",
                callback_data=f"browse:series:{page - 1}",
            )
        )
    if end < len(summaries):
        nav_buttons.append(
            InlineKeyboardButton(
                text="Next ▶️",
                callback_data=f"browse:series:{page + 1}",
            )
        )
    if nav_buttons:
        builder.row(*nav_buttons)

    builder.row(
        InlineKeyboardButton(text="📂 Browse Hub", callback_data="menu:browse"),
        InlineKeyboardButton(text="🔙 Main Menu", callback_data="menu:main"),
    )
    return builder.as_markup()


def ongoing_series_list_kb(
    summaries: list[dict],
    page: int = 0,
    page_size: int = 8,
) -> InlineKeyboardMarkup:
    """Build a keyboard listing ongoing series with episode badge counts."""
    builder = InlineKeyboardBuilder()

    start = page * page_size
    end = start + page_size
    page_items = summaries[start:end]

    for item in page_items:
        name = item["name"]
        count = item["total_episodes"]
        label = f"⚡ {name[:28]} (Ep 1-{count})" if count > 1 else f"⚡ {name[:28]} (Ep 1)"
        builder.row(
            InlineKeyboardButton(
                text=label,
                callback_data=f"search_txt:{name[:30]}",
            )
        )

    # Pagination row
    nav_buttons: list[InlineKeyboardButton] = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(
                text="◀️ Prev",
                callback_data=f"browse:ongoing:{page - 1}",
            )
        )
    if end < len(summaries):
        nav_buttons.append(
            InlineKeyboardButton(
                text="Next ▶️",
                callback_data=f"browse:ongoing:{page + 1}",
            )
        )
    if nav_buttons:
        builder.row(*nav_buttons)

    builder.row(
        InlineKeyboardButton(text="🎬 All Series", callback_data="browse:series:0"),
        InlineKeyboardButton(text="📂 Browse Hub", callback_data="menu:browse"),
    )
    return builder.as_markup()


# ─── Categories ───────────────────────────────────────────────────────────────


def categories_kb(categories: list[Category]) -> InlineKeyboardMarkup:
    """Build a keyboard listing all categories."""
    builder = InlineKeyboardBuilder()
    for cat in categories:
        builder.row(
            InlineKeyboardButton(
                text=f"{cat.emoji} {cat.name}",
                callback_data=f"cat:{cat.id}:0",
            )
        )
    builder.row(
        InlineKeyboardButton(text="📂 Browse Hub", callback_data="menu:browse"),
        InlineKeyboardButton(text="🔙 Main Menu", callback_data="menu:main"),
    )
    return builder.as_markup()



# ─── File List ────────────────────────────────────────────────────────────────


def file_list_kb(
    files: list[File],
    page: int = 0,
    page_size: int = 8,
    prefix: str = "flist",
    context_id: str = "0",
) -> InlineKeyboardMarkup:
    """Build a paginated file list keyboard.

    Parameters
    ----------
    files : list of files to display
    page : current page (0-indexed)
    page_size : items per page
    prefix : callback prefix for pagination (e.g. 'cat', 'search', 'latest')
    context_id : extra context (e.g. category_id or search query)
    """
    builder = InlineKeyboardBuilder()

    start = page * page_size
    end = start + page_size
    page_files = files[start:end]

    for f in page_files:
        label = f"{f.type_emoji} {f.file_name}"
        if len(label) > 60:
            label = label[:57] + "..."
        builder.row(
            InlineKeyboardButton(
                text=label,
                callback_data=f"file:{f.id}",
            )
        )

    # Pagination row
    safe_context = str(context_id)[:30]
    nav_buttons: list[InlineKeyboardButton] = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(
                text="◀️ Prev",
                callback_data=f"{prefix}:{safe_context}:{page - 1}",
            )
        )
    if end < len(files):
        nav_buttons.append(
            InlineKeyboardButton(
                text="Next ▶️",
                callback_data=f"{prefix}:{safe_context}:{page + 1}",
            )
        )
    if nav_buttons:
        builder.row(*nav_buttons)

    builder.row(
        InlineKeyboardButton(text="🔙 Back to Menu", callback_data="menu:main")
    )
    return builder.as_markup()


# ─── Single File Detail ──────────────────────────────────────────────────────


def file_detail_kb(file: File) -> InlineKeyboardMarkup:
    """Build a keyboard for a single file detail view."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📥 Download",
            callback_data=f"dl:{file.id}",
        ),
        InlineKeyboardButton(
            text="🎌 Anime Info",
            callback_data=f"info:{file.id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(text="🔙 Back to Menu", callback_data="menu:main")
    )
    return builder.as_markup()


def episode_delivery_kb(
    current_file: File,
    prev_file: File | None = None,
    next_file: File | None = None,
    has_siblings: bool = False,
) -> InlineKeyboardMarkup:
    """Build inline buttons attached under a delivered episode/video."""
    builder = InlineKeyboardBuilder()

    nav_row: list[InlineKeyboardButton] = []
    if prev_file:
        prev_num = extract_episode_number(prev_file.file_name)
        label = f"⏮ Ep {prev_num}" if prev_num is not None else "⏮ Prev Ep"
        nav_row.append(
            InlineKeyboardButton(text=label, callback_data=f"dl:{prev_file.id}")
        )
    if next_file:
        next_num = extract_episode_number(next_file.file_name)
        label = f"Next: Ep {next_num} ⏭" if next_num is not None else "Next Ep ⏭"
        nav_row.append(
            InlineKeyboardButton(text=label, callback_data=f"dl:{next_file.id}")
        )
    if nav_row:
        builder.row(*nav_row)

    meta_row: list[InlineKeyboardButton] = [
        InlineKeyboardButton(
            text="🎌 Anime Info", callback_data=f"info:{current_file.id}"
        )
    ]
    if has_siblings:
        meta_row.append(
            InlineKeyboardButton(
                text="📦 Download All", callback_data=f"batch_dl:{current_file.id}"
            )
        )
    builder.row(*meta_row)

    return builder.as_markup()


def not_found_kb(query: str) -> InlineKeyboardMarkup:
    """Build keyboard when an anime search has 0 results."""
    builder = InlineKeyboardBuilder()
    clean_q = query[:25]
    builder.row(
        InlineKeyboardButton(
            text=f"📩 Request: {clean_q}",
            callback_data=f"req_add:{clean_q}",
        )
    )
    builder.row(
        InlineKeyboardButton(text="📂 Browse Categories", callback_data="menu:browse"),
        InlineKeyboardButton(text="🆕 Latest Uploads", callback_data="menu:latest"),
    )
    return builder.as_markup()


def request_admin_kb(request_id: int) -> InlineKeyboardMarkup:
    """Build admin keyboard for fulfilling user anime requests."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✅ Mark Fulfilled", callback_data=f"req_done:{request_id}"
        )
    )
    return builder.as_markup()


# ─── Admin: Category Selection for Upload ────────────────────────────────────


def admin_category_select_kb(categories: list[Category]) -> InlineKeyboardMarkup:
    """Build a category picker for admin uploads."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🤖 Auto-Categorize with AniList",
            callback_data="upload_cat:auto",
        )
    )
    for cat in categories:
        builder.row(
            InlineKeyboardButton(
                text=f"{cat.emoji} {cat.name}",
                callback_data=f"upload_cat:{cat.id}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="📁 No Category", callback_data="upload_cat:none")
    )
    builder.row(
        InlineKeyboardButton(text="❌ Cancel", callback_data="upload:cancel")
    )
    return builder.as_markup()



# ─── Admin: File Management ──────────────────────────────────────────────────


def admin_file_manage_kb(file: File) -> InlineKeyboardMarkup:
    """Build admin controls for a file."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🗑️ Delete File",
            callback_data=f"admin_del:{file.id}",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="✅ Confirm Delete",
            callback_data=f"confirm_del:{file.id}",
        ),
        InlineKeyboardButton(text="❌ Cancel", callback_data="menu:main"),
    )
    return builder.as_markup()


# ─── Confirmation ────────────────────────────────────────────────────────────


def confirm_delete_kb(file_id: int) -> InlineKeyboardMarkup:
    """Confirmation keyboard for file deletion."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✅ Yes, Delete",
            callback_data=f"confirm_del:{file_id}",
        ),
        InlineKeyboardButton(text="❌ No, Cancel", callback_data="menu:main"),
    )
    return builder.as_markup()


# ─── Force Subscribe ─────────────────────────────────────────────────────────


def force_sub_kb(channel: str) -> InlineKeyboardMarkup:
    """Keyboard prompting user to join the required channel."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📢 Join Channel",
            url=f"https://t.me/{channel.lstrip('@')}",
        )
    )
    builder.row(
        InlineKeyboardButton(text="✅ I've Joined", callback_data="check_sub")
    )
    return builder.as_markup()


# ─── Channel Feed Navigation ──────────────────────────────────────────────────


def feed_navigation_kb(
    series_name: str, current_idx: int, total_series: int, sample_file_id: int
) -> InlineKeyboardMarkup:
    """Build navigation keyboard for Channel Stream Feed mode."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🎬 View All Episodes", callback_data=f"episodes:{sample_file_id}"),
        InlineKeyboardButton(text="🎌 Anime Info", callback_data=f"info:{sample_file_id}"),
        InlineKeyboardButton(text="🎵 Themes", callback_data=f"themes:file_{sample_file_id}"),
    )
    if total_series > 1:
        prev_idx = (current_idx - 1) % total_series
        next_idx = (current_idx + 1) % total_series
        builder.row(
            InlineKeyboardButton(text="⏮ Prev Anime", callback_data=f"feed:{prev_idx}"),
            InlineKeyboardButton(text="🎲 Surprise Me", callback_data="feed:random"),
            InlineKeyboardButton(text="Next Anime ⏭", callback_data=f"feed:{next_idx}"),
        )
    builder.row(
        InlineKeyboardButton(text="🔍 Search Anime", callback_data="menu:search"),
        InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main"),
    )
    return builder.as_markup()


# ─── Profile & Passport ───────────────────────────────────────────────────────


def profile_kb(continue_file_id: int | None = None) -> InlineKeyboardMarkup:
    """Build keyboard for user profile."""
    builder = InlineKeyboardBuilder()
    if continue_file_id:
        builder.row(
            InlineKeyboardButton(text="▶️ Continue Watching", callback_data=f"episodes:{continue_file_id}"),
        )
    builder.row(
        InlineKeyboardButton(text="📺 Channel Feed", callback_data="feed:0"),
        InlineKeyboardButton(text="🔥 Trending Hits", callback_data="menu:popular"),
    )
    builder.row(
        InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main"),
    )
    return builder.as_markup()


# ─── Admin Live Stats ─────────────────────────────────────────────────────────


def admin_stats_kb() -> InlineKeyboardMarkup:
    """Build keyboard for admin stats dashboard."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔄 Refresh Stats", callback_data="admin:stats:refresh"),
        InlineKeyboardButton(text="📢 Broadcast", callback_data="admin:broadcast"),
    )
    builder.row(
        InlineKeyboardButton(text="📦 Batch Upload", callback_data="admin:batch"),
        InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main"),
    )
    return builder.as_markup()


# ─── Themes & Music ──────────────────────────────────────────────────────────


def theme_list_kb(
    themes: list[dict],
    sample_file_id: int | None = None,
    anime_query: str = "",
) -> InlineKeyboardMarkup:
    """Build keyboard for anime themes / songs with direct video stream links."""
    builder = InlineKeyboardBuilder()
    for t in themes[:6]:
        v_url = t.get("video_url")
        slug = t.get("slug", "Theme")
        title = t.get("song_title", "Unknown")[:24]
        res = t.get("resolution", "")
        label = f"▶️ {slug}: {title} ({res})" if res else f"▶️ {slug}: {title}"
        if v_url:
            builder.row(InlineKeyboardButton(text=label, url=v_url))

    nav_row: list[InlineKeyboardButton] = []
    if sample_file_id:
        nav_row.append(InlineKeyboardButton(text="🎬 Episodes", callback_data=f"episodes:{sample_file_id}"))
        nav_row.append(InlineKeyboardButton(text="🎌 Info", callback_data=f"info:{sample_file_id}"))
    elif anime_query:
        nav_row.append(InlineKeyboardButton(text="🔍 Search in Bot", callback_data=f"search_txt:{anime_query[:25]}"))
    nav_row.append(InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main"))
    builder.row(*nav_row)
    return builder.as_markup()


# ─── Scene Search Result ─────────────────────────────────────────────────────


def scene_result_kb(
    anime_title: str,
    anilist_id: int | None = None,
    video_url: str | None = None,
) -> InlineKeyboardMarkup:
    """Build keyboard for Trace.moe reverse scene search results."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🎬 Search & Watch in Bot", callback_data=f"search_txt:{anime_title[:25]}"),
        InlineKeyboardButton(text="🎵 Themes", callback_data=f"themes:text_{anime_title[:25]}"),
    )
    external_row: list[InlineKeyboardButton] = []
    if video_url:
        external_row.append(InlineKeyboardButton(text="🎥 Scene Clip", url=video_url))
    if anilist_id:
        external_row.append(InlineKeyboardButton(text="🌐 AniList", url=f"https://anilist.co/anime/{anilist_id}"))
    if external_row:
        builder.row(*external_row)

    builder.row(
        InlineKeyboardButton(text="📸 Scan Another Scene", callback_data="menu:whatanime"),
        InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main"),
    )
    return builder.as_markup()


# ─── Airing Schedule Keyboard ─────────────────────────────────────────────────


def airing_schedule_kb(schedules: list[dict], page: int = 0, page_size: int = 5) -> InlineKeyboardMarkup:
    """Build keyboard for today's airing anime schedule."""
    builder = InlineKeyboardBuilder()
    start_idx = page * page_size
    page_items = schedules[start_idx : start_idx + page_size]

    for item in page_items:
        title = item["title"][:24]
        ep = item["episode"]
        countdown = item["countdown"]
        builder.row(
            InlineKeyboardButton(
                text=f"📺 {title} Ep {ep} ({countdown})",
                callback_data=f"airing_detail:{item['id']}",
            )
        )

    # Pagination row
    nav_row: list[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"airing_pg:{page - 1}"))
    if start_idx + page_size < len(schedules):
        nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"airing_pg:{page + 1}"))
    if nav_row:
        builder.row(*nav_row)

    builder.row(
        InlineKeyboardButton(text="🔄 Refresh Schedule", callback_data="menu:airing"),
        InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main"),
    )
    return builder.as_markup()


def airing_item_kb(anime_title: str, anilist_url: str) -> InlineKeyboardMarkup:
    """Action buttons for a single airing anime item."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔍 Search Vault", callback_data=f"search_txt:{anime_title[:25]}"),
        InlineKeyboardButton(text="🔖 Add to Watchlist", callback_data=f"wl_add:{anime_title[:28]}"),
    )
    builder.row(
        InlineKeyboardButton(text="🌐 AniList Info", url=anilist_url),
        InlineKeyboardButton(text="⬅️ Back to Schedule", callback_data="menu:airing"),
    )
    return builder.as_markup()


# ─── Watchlist Keyboard ───────────────────────────────────────────────────────


def watchlist_menu_kb(items: list[Any]) -> InlineKeyboardMarkup:
    """Build keyboard showing user's saved watchlist anime."""
    builder = InlineKeyboardBuilder()
    for item in items[:15]:
        status_emoji = {
            "watching": "🟢 Watching",
            "plan_to_watch": "🟡 Plan to Watch",
            "completed": "🔵 Completed",
        }.get(item.status, "📁")
        builder.row(
            InlineKeyboardButton(
                text=f"{item.series_name[:22]} • {status_emoji}",
                callback_data=f"wl_item:{item.id}",
            )
        )

    builder.row(
        InlineKeyboardButton(text="🔍 Search Anime to Add", callback_data="menu:search"),
        InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main"),
    )
    return builder.as_markup()


def watchlist_item_actions_kb(
    item_id: int, series_name: str, current_status: str
) -> InlineKeyboardMarkup:
    """Action buttons for a single watchlist item."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🎬 Watch in Vault", callback_data=f"search_txt:{series_name[:25]}"),
        InlineKeyboardButton(text="🎵 Themes", callback_data=f"themes:text_{series_name[:25]}"),
    )

    status_row: list[InlineKeyboardButton] = []
    if current_status != "watching":
        status_row.append(InlineKeyboardButton(text="🟢 Mark Watching", callback_data=f"wl_stat:{item_id}:watching"))
    if current_status != "completed":
        status_row.append(InlineKeyboardButton(text="🔵 Mark Completed", callback_data=f"wl_stat:{item_id}:completed"))
    if status_row:
        builder.row(*status_row)

    builder.row(
        InlineKeyboardButton(text="❌ Remove from Watchlist", callback_data=f"wl_del:{item_id}"),
        InlineKeyboardButton(text="⬅️ Back to Watchlist", callback_data="menu:watchlist"),
    )
    return builder.as_markup()


# ─── Persona Switcher Keyboard ───────────────────────────────────────────────


def persona_picker_kb(current_persona: str) -> InlineKeyboardMarkup:
    """Build persona switcher keyboard with visual checkmark."""
    from bot.utils.personas import PERSONAS

    builder = InlineKeyboardBuilder()
    for key, info in PERSONAS.items():
        is_active = (key == current_persona.lower())
        badge = " ✅" if is_active else ""
        builder.row(
            InlineKeyboardButton(
                text=f"{info['emoji']} {info['name']}{badge}",
                callback_data=f"set_persona:{key}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="💬 Chat with Persona", callback_data="menu:ask_ai"),
        InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main"),
    )
    return builder.as_markup()


# ─── Daily Trivia & Gamification Keyboard ────────────────────────────────────


def trivia_quiz_kb(q_hash: str, options: list[str]) -> InlineKeyboardMarkup:
    """Build interactive 4-option quiz keyboard."""
    builder = InlineKeyboardBuilder()
    labels = ["A", "B", "C", "D"]
    for idx, opt in enumerate(options):
        letter = labels[idx] if idx < len(labels) else str(idx + 1)
        builder.row(
            InlineKeyboardButton(
                text=f"[{letter}] {opt}",
                callback_data=f"trivia_ans:{q_hash}:{idx}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="🏆 Leaderboard", callback_data="menu:leaderboard"),
        InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main"),
    )
    return builder.as_markup()


def leaderboard_kb() -> InlineKeyboardMarkup:
    """Leaderboard navigation keyboard."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🎯 Play Today's Trivia", callback_data="menu:trivia"),
        InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main"),
    )
    return builder.as_markup()



