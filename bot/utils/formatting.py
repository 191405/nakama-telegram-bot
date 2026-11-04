"""Message formatting utilities."""

from __future__ import annotations

from bot.db.models import File


def format_file_size(size_bytes: int) -> str:
    """Convert bytes to a human-readable string."""
    if size_bytes == 0:
        return "Unknown"
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(size_bytes)
    for unit in units:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def file_type_emoji(file_type: str) -> str:
    """Return an emoji for a file type."""
    return {
        "document": "📄",
        "video": "🎬",
        "audio": "🎵",
        "photo": "🖼️",
        "animation": "🎞️",
    }.get(file_type, "📁")


def format_file_detail(f: File) -> str:
    """Format a file's details for display."""
    emoji = file_type_emoji(f.file_type)
    cat_name = f.category.name if f.category else "Uncategorized"
    cat_emoji = f.category.emoji if f.category else "📁"

    return (
        f"{emoji} <b>{f.file_name}</b>\n"
        f"\n"
        f"📂 Category: {cat_emoji} {cat_name}\n"
        f"📦 Size: {format_file_size(f.file_size)}\n"
        f"📥 Downloads: {f.download_count}\n"
        f"🕐 Uploaded: {f.created_at.strftime('%Y-%m-%d %H:%M')}\n"
    )


def format_file_caption(f: File) -> str:
    """Format the caption sent along with the file."""
    emoji = file_type_emoji(f.file_type)
    lines = [f"{emoji} <b>{f.file_name}</b>"]
    if f.caption:
        lines.append(f"\n{f.caption}")
    lines.append(f"\n📥 Downloads: {f.download_count + 1}")
    return "\n".join(lines)


WELCOME_TEXT = (
    "🎌 <b>Welcome to Nakama Network</b> 🏴‍☠️\n"
    "<i>Your premier anime streaming & download vault.</i>\n"
    "\n"
    "💬 <b>Instant Search:</b>\n"
    "Simply type any anime title in chat (e.g. <code>Dead Account</code> or <code>One Piece</code>) "
    "and I'll find it for you immediately!\n"
    "\n"
    "🧭 <b>Quick Navigation:</b>\n"
    "• 📺 <b>Channel Feed:</b> Flip through anime cards like a streaming feed\n"
    "• 🔍 <b>Search:</b> Type any title or use /search\n"
    "• 📂 <b>Categories:</b> /browse to explore series & collections\n"
    "• 🆕 <b>Latest:</b> /latest for recently added episodes\n"
    "• 🔥 <b>Popular:</b> /popular for top downloaded series\n"
    "• 👤 <b>My Profile:</b> View your rank & continue watching\n"
    "\n"
    "⚡ <b>Inline Mode:</b> Type <code>@{bot_username} anime</code> in any chat to share episodes on the fly!"
)

HELP_TEXT = (
    "📖 <b>Nakama Network — User Guide</b>\n"
    "\n"
    "<b>🔍 Finding Anime:</b>\n"
    "• <b>Natural Chat:</b> Just send any message like <i>\"Dead Account\"</i> or <i>\"do you have one piece\"</i>.\n"
    "• <b>Channel Stream:</b> /feed to browse anime releases with posters & synopsis.\n"
    "• <b>Command Search:</b> <code>/search &lt;query&gt;</code>\n"
    "• <b>Browse Library:</b> /browse to explore by genre or category.\n"
    "• <b>Recent Additions:</b> /latest to see new releases.\n"
    "• <b>Top Hits:</b> /popular to discover trending downloads.\n"
    "• <b>Your Account:</b> /profile to view rank and continue watching.\n"
    "\n"
    "<b>✨ Smart Entertainment Engines:</b>\n"
    "• 📸 <b>Reverse Scene Search:</b> Send any anime screenshot (or <code>/whatanime</code>) to detect the show, episode & exact timestamp!\n"
    "• 🎵 <b>Theme Songs:</b> <code>/themes &lt;anime&gt;</code> to stream clean OP/ED video tracks in 1080p HD.\n"
    "• 📅 <b>Airing Schedule:</b> /airing to see what episodes broadcast in Japan today with countdowns.\n"
    "• 🔖 <b>Personal Watchlist:</b> /watchlist to track Watching, Plan to Watch, and Completed series.\n"
    "• 🎯 <b>Daily Trivia & XP:</b> /trivia to test your lore knowledge, earn XP bounty, and climb /leaderboard.\n"
    "• 🎭 <b>AI Persona Switcher:</b> /persona to chat with Zoro, Gojo, Makima, Killua, or Nakama.\n"
    "• 🎙️ <b>Voice Messages:</b> Send a voice note anytime and your active AI persona will listen and reply!\n"
    "• 🤖 <b>AI Concierge:</b> <code>/ask &lt;question&gt;</code> for deep anime lore, recommendations, and casual banter.\n"
    "\n"
    "<b>⚡ Inline Sharing:</b>\n"
    "Type <code>@{bot_username} &lt;anime name&gt;</code> in any private chat, group, or channel to share episodes without leaving the conversation.\n"
    "\n"
    "<b>👑 Admin Controls:</b>\n"
    "• /batch — Bulk upload entire seasons or episode packs\n"
    "• /upload — Upload a single file with custom title & category\n"
    "• /addcategory — Organize content into collections\n"
    "• /delfile &lt;id&gt; — Remove a file from the library\n"
    "• /stats — View real-time community analytics & system health\n"
    "• /broadcast — Send announcements to all members\n"
    "• /setgemini &lt;key&gt; — Configure Google Gemini AI key live\n"
)


def format_welcome_card(stats: dict | None, bot_username: str) -> str:
    """Format the main home welcome screen with live channel-like stats."""
    u_count = f"{stats.get('total_users', 0):,}" if stats else "1,000+"
    f_count = f"{stats.get('total_files', 0):,}" if stats else "113+"
    d_count = f"{stats.get('total_downloads', 0):,}" if stats else "4,500+"

    return (
        "╔══════════════════════════════════╗\n"
        "║       ✦ <b>NAKAMA NETWORK</b> ✦         ║\n"
        "║   <i>Anime Streaming & Download Vault</i>   ║\n"
        "╚══════════════════════════════════╝\n"
        f"👥 <b>{u_count}</b> Nakama Exploring  •  🎬 <b>{f_count}</b> Episodes\n"
        f"🔥 <b>{d_count}</b> Deliveries Made  •  🟢 <b>24/7 Cloud Node</b>\n"
        "──────────────────────────────────\n"
        "💬 <b>Instant Conversational Search:</b>\n"
        "Simply type any anime title in chat (e.g. <code>Dead Account</code> or <code>One Piece</code>) "
        "and I will bring up the series card and episodes immediately!\n"
        "\n"
        "🧭 <b>Channel Explorer:</b>\n"
        "• 📺 <b>Channel Feed:</b> Flip through anime cards like a streaming feed\n"
        "• 📸 <b>Identify Scene:</b> Send any photo to detect the anime (/whatanime)\n"
        "• 🎵 <b>Theme Music:</b> /themes to stream OP/ED songs\n"
        "• 🤖 <b>AI Concierge:</b> /ask for smart recommendations & lore\n"
        "• 📂 <b>Categories:</b> /browse series and collections\n"
        "• 👤 <b>My Passport:</b> View your rank & continue watching\n"

        "\n"
        f"⚡ <b>Inline Mode:</b> Type <code>@{bot_username} &lt;anime&gt;</code> in any chat to share!"
    )


def format_user_profile(data: dict) -> str:
    """Format user subscriber profile card."""
    user = data["user"]
    downloads = data["downloads"]
    rank = data["rank"]
    continue_file = data.get("continue_file")
    next_file = data.get("next_file")

    joined = user.joined_at.strftime("%B %d, %Y") if user.joined_at else "Recently"

    lines = [
        "╔══════════════════════════════════╗\n"
        "║       👤 <b>NAKAMA PASSPORT</b>             ║\n"
        "╚══════════════════════════════════╝\n",
        f"🏷️ <b>Name:</b> {user.full_name}",
        f"🆔 <b>User ID:</b> <code>{user.user_id}</code>",
        f"🎖️ <b>Nakama Rank:</b> {rank}",
        f"📥 <b>Episodes Watched/Downloaded:</b> {downloads}",
        f"📅 <b>Member Since:</b> {joined}",
        "──────────────────────────────────",
    ]

    if next_file:
        lines.append(f"▶️ <b>Up Next:</b> <code>{next_file.file_name}</code>")
    elif continue_file:
        lines.append(f"🕒 <b>Last Viewed:</b> <code>{continue_file.file_name}</code>")
    else:
        lines.append("🍿 <i>Ready to start streaming! Search any title above.</i>")

    return "\n".join(lines)


def format_admin_stats(data: dict) -> str:
    """Format full admin analytics dashboard."""
    u_count = f"{data['total_users']:,}"
    b_count = f"{data['banned_users']:,}"
    f_count = f"{data['total_files']:,}"
    d_count = f"{data['total_downloads']:,}"
    s_size = format_file_size(data['total_size'])
    req_count = f"{data['pending_requests']:,}"

    top_text = ""
    for idx, tf in enumerate(data.get("top_files", []), 1):
        top_text += f"\n  {idx}. <b>{tf.file_name[:35]}</b> — {tf.download_count} downloads"

    return (
        "╔══════════════════════════════════╗\n"
        "║       👑 <b>NAKAMA COMMAND CENTER</b>       ║\n"
        "║      <i>Real-Time Community Metrics</i>     ║\n"
        "╚══════════════════════════════════╝\n"
        f"👥 <b>Total Users:</b> {u_count} ({b_count} banned)\n"
        f"🎬 <b>Indexed Episodes:</b> {f_count} items\n"
        f"📦 <b>Telegram Storage Footprint:</b> {s_size}\n"
        f"🔥 <b>Total Deliveries:</b> {d_count} downloads\n"
        f"📩 <b>Pending Anime Requests:</b> {req_count}\n"
        f"🟢 <b>Cloud Server:</b> Fly.io (iad region, 512MB RAM)\n"
        "──────────────────────────────────\n"
        f"🏆 <b>Top Downloaded Series/Episodes:</b>{top_text if top_text else ' None yet'}\n"
    )


def format_feed_card(series: dict, anilist_data: dict | None, current_idx: int, total_count: int) -> str:
    """Format a channel-stream card for an anime release."""
    title = series["name"]
    episodes = series["total_episodes"]
    downloads = series["total_downloads"]

    lines = [
        f"📺 <b>[CHANNEL FEED • {current_idx + 1}/{total_count}]</b>",
        f"🎌 <b>{title.upper()}</b>\n",
    ]

    if anilist_data:
        native = anilist_data.get("title_native") or ""
        score = anilist_data.get("score")
        genres = ", ".join(anilist_data.get("genres", []))
        synopsis = anilist_data.get("synopsis") or ""

        if native and native != title:
            lines.append(f"🇯🇵 <i>{native}</i>")
        if score:
            lines.append(f"⭐ <b>Rating:</b> {score / 10:.1f} / 10")
        if genres:
            lines.append(f"🎭 <b>Genres:</b> {genres}")
        lines.append(f"📦 <b>Vault Episodes:</b> {episodes} available")
        lines.append(f"🔥 <b>Total Community Downloads:</b> {downloads}")

        if synopsis:
            clean_syn = synopsis[:300].rstrip() + ("..." if len(synopsis) > 300 else "")
            lines.append(f"\n📖 <b>Synopsis:</b>\n<i>{clean_syn}</i>")
    else:
        lines.append(f"📦 <b>Vault Episodes:</b> {episodes} available")
        lines.append(f"🔥 <b>Total Community Downloads:</b> {downloads}")

    lines.append("\n💡 <i>Tap below to view all episodes or flip through the feed.</i>")
    return "\n".join(lines)

