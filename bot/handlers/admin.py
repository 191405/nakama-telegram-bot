"""Admin command handlers: upload, manage categories, stats, broadcast, ban."""

from __future__ import annotations

import html
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.db import queries
from bot.keyboards.inline import admin_category_select_kb, admin_stats_kb, confirm_delete_kb
from bot.utils.categories import auto_categorize_file, bulk_auto_categorize
from bot.utils.channel_poster import broadcast_ongoing_episode
from bot.utils.episodes import extract_episode_number, extract_series_name as clean_series_name
from bot.utils.formatting import format_admin_stats

logger = logging.getLogger(__name__)

router = Router(name="admin")



# ─── FSM States ──────────────────────────────────────────────────────────────


class UploadState(StatesGroup):
    """States for the file upload flow."""

    waiting_file = State()
    waiting_name = State()
    waiting_category = State()


class BatchUploadState(StatesGroup):
    """States for batch upload mode."""

    active = State()


class AddCategoryState(StatesGroup):
    """States for creating a category."""

    waiting_name = State()
    waiting_emoji = State()


class BroadcastState(StatesGroup):
    """State for broadcast message."""

    waiting_message = State()


# ─── /upload ─────────────────────────────────────────────────────────────────


@router.message(Command("upload"))
async def cmd_upload(message: Message, state: FSMContext) -> None:
    """Start the file upload flow.

    Usage: Reply to a file with /upload, or send /upload and then the file.
    """
    if message.reply_to_message and _extract_file_info(message.reply_to_message):
        # User replied to a file — skip to naming
        file_info = _extract_file_info(message.reply_to_message)
        await state.update_data(file_info=file_info)
        await state.set_state(UploadState.waiting_name)
        await message.answer(
            f"📎 Got the file!\n\n"
            f"Type: <b>{file_info['file_type']}</b>\n\n"
            f"📝 Now send me the <b>display name</b> for this file:",
            parse_mode="HTML",
        )
    else:
        await state.set_state(UploadState.waiting_file)
        await message.answer(
            "📤 <b>Upload Mode</b>\n\n"
            "Send me a file (document, video, audio, or photo).\n\n"
            "Or send /cancel to abort.",
            parse_mode="HTML",
        )


@router.message(UploadState.waiting_file, F.content_type.in_({"document", "video", "audio", "photo", "animation"}))
async def upload_receive_file(message: Message, state: FSMContext) -> None:
    """Receive the file during upload flow."""
    file_info = _extract_file_info(message)
    if file_info is None:
        await message.answer("❌ Could not read the file. Please try again.")
        return

    await state.update_data(file_info=file_info)
    await state.set_state(UploadState.waiting_name)
    await message.answer(
        f"📎 Got it! Type: <b>{file_info['file_type']}</b>\n\n"
        f"📝 Send me the <b>display name</b> for this file:",
        parse_mode="HTML",
    )


@router.message(UploadState.waiting_name)
async def upload_receive_name(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Receive the display name and ask for category."""
    if not message.text:
        await message.answer("Please send a text name.")
        return

    await state.update_data(display_name=message.text.strip())

    categories = await queries.get_all_categories(session)
    if categories:
        await state.set_state(UploadState.waiting_category)
        await message.answer(
            "📂 Choose a <b>category</b> for this file:",
            reply_markup=admin_category_select_kb(categories),
            parse_mode="HTML",
        )
    else:
        # No categories — save directly
        await _save_uploaded_file(message, state, session, category_id=None)


@router.callback_query(UploadState.waiting_category, lambda c: c.data and c.data.startswith("upload_cat:"))
async def upload_select_category(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Handle category selection during upload."""
    if callback.data is None or callback.message is None:
        return

    cat_value = callback.data.split(":")[1]
    if cat_value == "auto":
        category_id = "auto"
    elif cat_value == "none":
        category_id = None
    else:
        category_id = int(cat_value)

    await _save_uploaded_file(callback.message, state, session, category_id=category_id)
    await callback.answer("✅ File saved!")


@router.callback_query(lambda c: c.data == "upload:cancel")
async def upload_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel the upload flow."""
    await state.clear()
    await callback.message.edit_text("❌ Upload cancelled.")  # type: ignore
    await callback.answer()


async def _save_uploaded_file(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    category_id: int | str | None,
) -> None:
    """Save the uploaded file to the database with optional AniList auto-categorization."""
    data = await state.get_data()
    file_info = data["file_info"]
    display_name = data["display_name"]

    # Check for duplicates
    existing = await queries.get_file_by_telegram_id(session, file_info["file_id"])
    if existing:
        await state.clear()
        await message.answer(  # type: ignore
            f"⚠️ This file already exists as <b>{existing.file_name}</b> (ID: {existing.id}).",
            parse_mode="HTML",
        )
        return

    init_cat_id = None if (category_id is None or category_id == "auto") else int(category_id)

    f = await queries.save_file(
        session,
        file_name=display_name,
        file_id=file_info["file_id"],
        file_unique_id=file_info["file_unique_id"],
        file_type=file_info["file_type"],
        file_size=file_info["file_size"],
        uploaded_by=file_info["uploaded_by"],
        category_id=init_cat_id,
    )

    await state.clear()

    # If auto-categorize requested or no category chosen, attempt AniList auto-tagging
    cat = None
    if category_id == "auto" or category_id is None:
        cat = await auto_categorize_file(session, f)
    elif init_cat_id:
        cat = await queries.get_category(session, init_cat_id)

    cat_name = f"{cat.emoji} {cat.name}" if cat else "📁 Uncategorized"

    bot = message.bot
    bot_username = "NakamaNetworkbot"
    if bot:
        try:
            me = await bot.get_me()
            bot_username = me.username or bot_username
        except Exception:
            pass

    direct_link = f"https://t.me/{bot_username}?start=file_{f.id}"

    await message.answer(  # type: ignore
        f"✅ <b>File Saved!</b>\n\n"
        f"📄 Name: {display_name}\n"
        f"📂 Category: {cat_name}\n"
        f"🆔 ID: {f.id}\n"
        f"📦 Type: {file_info['file_type']}\n"
        f"🔗 <b>Share Link:</b> <code>{direct_link}</code>",
        parse_mode="HTML",
    )


    if settings.update_channel and bot:
        try:
            await broadcast_ongoing_episode(bot, f, target_channel=settings.update_channel)
        except Exception as e:
            logger.debug("Failed channel auto-post: %s", e)


# ─── /batch ──────────────────────────────────────────────────────────────────


@router.message(Command("batch"))
async def cmd_batch(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Enter batch upload mode — send files continuously."""
    categories = await queries.get_all_categories(session)
    cat_text = ""
    if categories:
        cat_text = "\n\nAvailable categories:\n" + "\n".join(
            f"  {c.emoji} {c.name} (ID: {c.id})" for c in categories
        )

    await state.set_state(BatchUploadState.active)
    await message.answer(
        "📦 <b>Batch Upload Mode</b>\n\n"
        "Send me files one by one. I'll save them using their original filename.\n\n"
        "To assign a category, send:\n"
        "<code>/setcat CATEGORY_ID</code>\n\n"
        "Send /done to exit batch mode."
        f"{cat_text}",
        parse_mode="HTML",
    )
    await state.update_data(batch_category_id=None)


@router.message(BatchUploadState.active, Command("setcat"))
async def batch_set_category(message: Message, state: FSMContext) -> None:
    """Set the category for subsequent batch uploads."""
    if message.text is None:
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Usage: <code>/setcat CATEGORY_ID</code>", parse_mode="HTML")
        return

    cat_id = int(parts[1])
    await state.update_data(batch_category_id=cat_id)
    await message.answer(f"📂 Category set to ID: {cat_id}")


@router.message(BatchUploadState.active, Command("done"))
async def batch_done(message: Message, state: FSMContext) -> None:
    """Exit batch upload mode."""
    await state.clear()
    await message.answer("✅ Batch upload mode ended.")


@router.message(BatchUploadState.active, F.content_type.in_({"document", "video", "audio", "photo", "animation"}))
async def batch_receive_file(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Receive a file in batch mode and save immediately."""
    file_info = _extract_file_info(message)
    if file_info is None:
        await message.answer("❌ Could not read this file.")
        return

    data = await state.get_data()
    category_id = data.get("batch_category_id")

    # Use original filename or a default
    display_name = file_info.get("original_name") or f"File_{file_info['file_unique_id'][:8]}"

    existing = await queries.get_file_by_telegram_id(session, file_info["file_id"])
    if existing:
        await message.answer(f"⏩ Skipped (duplicate): {existing.file_name}")
        return

    try:
        f = await queries.save_file(
            session,
            file_name=display_name,
            file_id=file_info["file_id"],
            file_unique_id=file_info["file_unique_id"],
            file_type=file_info["file_type"],
            file_size=file_info["file_size"],
            uploaded_by=file_info["uploaded_by"],
            category_id=category_id,
            caption=file_info.get("caption"),
        )

        cat_label = ""
        if category_id is None:
            cat = await auto_categorize_file(session, f)
            if cat:
                cat_label = f" — {cat.emoji} {cat.name}"

        bot = message.bot
        bot_username = "NakamaNetworkbot"
        if bot:
            try:
                me = await bot.get_me()
                bot_username = me.username or bot_username
            except Exception:
                pass
        direct_link = f"https://t.me/{bot_username}?start=file_{f.id}"
        await message.answer(
            f"✅ Saved: <b>{display_name}</b> (ID: {f.id}){cat_label}\n"
            f"🔗 <code>{direct_link}</code>",
            parse_mode="HTML",
        )
    except Exception:
        await session.rollback()
        await message.answer(f"⏩ Skipped (already exists): {display_name}")



# ─── /addcategory ────────────────────────────────────────────────────────────


@router.message(Command("addcategory"))
async def cmd_add_category(message: Message, state: FSMContext) -> None:
    """Start the add-category flow."""
    await state.set_state(AddCategoryState.waiting_name)
    await message.answer(
        "📂 <b>New Category</b>\n\n"
        "Send me the category <b>name</b>:",
        parse_mode="HTML",
    )


@router.message(AddCategoryState.waiting_name)
async def addcat_receive_name(message: Message, state: FSMContext) -> None:
    """Receive category name."""
    if not message.text:
        await message.answer("Please send a text name.")
        return
    await state.update_data(cat_name=message.text.strip())
    await state.set_state(AddCategoryState.waiting_emoji)
    await message.answer(
        "Send me an <b>emoji</b> for this category (or send /skip for default 📁):",
        parse_mode="HTML",
    )


@router.message(AddCategoryState.waiting_emoji)
async def addcat_receive_emoji(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Receive emoji and create the category."""
    data = await state.get_data()
    emoji = "📁"
    if message.text and message.text != "/skip":
        emoji = message.text.strip()[:10]

    cat = await queries.create_category(session, name=data["cat_name"], emoji=emoji)
    await state.clear()
    await message.answer(
        f"✅ Category created: {cat.emoji} <b>{cat.name}</b> (ID: {cat.id})",
        parse_mode="HTML",
    )


# ─── /delfile ────────────────────────────────────────────────────────────────


@router.message(Command("delfile"))
async def cmd_delete_file(message: Message, session: AsyncSession) -> None:
    """Delete a file by ID."""
    if message.text is None:
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(
            "Usage: <code>/delfile FILE_ID</code>", parse_mode="HTML"
        )
        return

    try:
        file_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Invalid file ID.")
        return

    f = await queries.get_file(session, file_id)
    if f is None:
        await message.answer("❌ File not found.")
        return

    await message.answer(
        f"⚠️ Delete <b>{f.file_name}</b> (ID: {f.id})?\n\n"
        f"This action cannot be undone.",
        reply_markup=confirm_delete_kb(f.id),
        parse_mode="HTML",
    )


@router.callback_query(lambda c: c.data and c.data.startswith("confirm_del:"))
async def cb_confirm_delete(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """Confirm and execute file deletion."""
    if callback.data is None:
        return

    file_id = int(callback.data.split(":")[1])
    deleted = await queries.delete_file(session, file_id)

    if deleted:
        await callback.message.edit_text("✅ File deleted successfully.")  # type: ignore
    else:
        await callback.message.edit_text("❌ File not found (already deleted?).")  # type: ignore
    await callback.answer()





# ─── /broadcast ──────────────────────────────────────────────────────────────


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    """Start broadcast — next message will be sent to all users."""
    if message.text is None:
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) > 1 and parts[1].strip():
        # Inline broadcast: /broadcast Hello everyone!
        await state.update_data(broadcast_text=parts[1].strip())
        await _do_broadcast(message, state)
    else:
        await state.set_state(BroadcastState.waiting_message)
        await message.answer(
            "📣 <b>Broadcast Mode</b>\n\n"
            "Send me the message to broadcast to all users.\n"
            "Send /cancel to abort.",
            parse_mode="HTML",
        )


@router.message(BroadcastState.waiting_message)
async def broadcast_receive_message(
    message: Message, state: FSMContext
) -> None:
    """Receive the broadcast message."""
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Broadcast cancelled.")
        return

    await state.update_data(broadcast_text=message.text or "")
    await _do_broadcast(message, state)


async def _do_broadcast(message: Message, state: FSMContext) -> None:
    """Execute the broadcast."""
    data = await state.get_data()
    text = data.get("broadcast_text", "")
    await state.clear()

    if not text:
        await message.answer("❌ Empty message. Broadcast cancelled.")
        return

    # Get DB session from middleware
    from bot.db.engine import async_session

    async with async_session() as session:
        user_ids = await queries.get_all_user_ids(session)

    bot = message.bot
    if bot is None:
        return

    sent = 0
    failed = 0

    status_msg = await message.answer(f"📣 Broadcasting to {len(user_ids)} users...")

    for uid in user_ids:
        try:
            await bot.send_message(uid, f"📣 <b>Broadcast</b>\n\n{text}", parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1

    await status_msg.edit_text(
        f"📣 <b>Broadcast Complete</b>\n\n"
        f"✅ Sent: {sent}\n"
        f"❌ Failed: {failed}",
        parse_mode="HTML",
    )


# ─── /ban & /unban ───────────────────────────────────────────────────────────


@router.message(Command("ban"))
async def cmd_ban(message: Message, session: AsyncSession) -> None:
    """Ban a user by Telegram ID."""
    if message.text is None:
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Usage: <code>/ban USER_ID</code>", parse_mode="HTML")
        return

    try:
        target_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Invalid user ID.")
        return

    if target_id in settings.admin_id_list:
        await message.answer("⛔ Cannot ban an admin.")
        return

    success = await queries.set_banned(session, target_id, True)
    if success:
        await message.answer(f"🚫 User <b>{target_id}</b> has been banned.", parse_mode="HTML")
    else:
        await message.answer("❌ User not found in database.")


@router.message(Command("unban"))
async def cmd_unban(message: Message, session: AsyncSession) -> None:
    """Unban a user by Telegram ID."""
    if message.text is None:
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Usage: <code>/unban USER_ID</code>", parse_mode="HTML")
        return

    try:
        target_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Invalid user ID.")
        return

    success = await queries.set_banned(session, target_id, False)
    if success:
        await message.answer(f"✅ User <b>{target_id}</b> has been unbanned.", parse_mode="HTML")
    else:
        await message.answer("❌ User not found in database.")


# ─── /stats (Community Dashboard) ───────────────────────────────────────────


@router.message(Command("stats"))
async def cmd_stats(message: Message, session: AsyncSession) -> None:
    """View detailed community metrics and analytics."""
    stats = await queries.get_admin_detailed_stats(session)
    text = format_admin_stats(stats)
    await message.answer(text, reply_markup=admin_stats_kb(), parse_mode="HTML")


@router.callback_query(lambda c: c.data == "admin:stats:refresh")
async def cb_stats_refresh(callback: CallbackQuery, session: AsyncSession) -> None:
    """Refresh the analytics dashboard in-place."""
    stats = await queries.get_admin_detailed_stats(session)
    text = format_admin_stats(stats)
    try:
        await callback.message.edit_text(text, reply_markup=admin_stats_kb(), parse_mode="HTML")  # type: ignore
    except Exception:
        pass
    await callback.answer("📊 Stats updated!")


@router.callback_query(lambda c: c.data == "admin:broadcast")
async def cb_admin_broadcast_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Trigger broadcast flow from stats dashboard."""
    await state.set_state(BroadcastState.waiting_message)
    await callback.message.answer(  # type: ignore
        "📢 <b>Broadcast Mode</b>\n\n"
        "Send the message you want to broadcast to all Nakama members.\n"
        "Supports text, photo, video, or documents.\n\n"
        "Type /cancel to abort.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "admin:batch")
async def cb_admin_batch_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Trigger batch mode from stats dashboard."""
    await state.set_state(BatchUploadState.active)
    await callback.message.answer(  # type: ignore
        "📦 <b>Batch Upload Mode Activated!</b>\n\n"
        "Forward or send all files/episodes here.\n"
        "Send /done when finished, or /cancel to abort.",
        parse_mode="HTML",
    )
    await callback.answer()


# ─── /cancel (generic) ──────────────────────────────────────────────────────


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """Cancel any active FSM state."""
    current = await state.get_state()
    if current is None:
        await message.answer("Nothing to cancel.")
        return
    await state.clear()
    await message.answer("❌ Operation cancelled.")


# ─── /autocategorize (AniList Bulk Organizer) ───────────────────────────────


@router.message(Command("autocategorize", "autocat"))
async def cmd_autocategorize(message: Message, session: AsyncSession) -> None:
    """Scan vault and auto-assign genre categories using AniList metadata."""
    if not message.from_user or message.from_user.id not in settings.admin_id_list:
        return

    status = await message.answer("🔄 <i>Scanning vault files and auto-categorizing with AniList...</i>", parse_mode="HTML")
    res = await bulk_auto_categorize(session, only_uncategorized=True)
    processed = res["processed"]
    categorized = res["categorized"]
    breakdown = res["breakdown"]

    if processed == 0:
        await status.edit_text("✅ <b>All files already categorized!</b> No uncategorized anime files found.", parse_mode="HTML")
        return

    breakdown_lines = "\n".join(f"• <b>{cat}:</b> {count} file(s)" for cat, count in breakdown.items())
    await status.edit_text(
        f"✅ <b>Auto-Categorization Complete!</b>\n\n"
        f"Processed: <b>{processed}</b> uncategorized file(s)\n"
        f"Categorized: <b>{categorized}</b> file(s)\n\n"
        f"<b>Genre Breakdown:</b>\n"
        f"{breakdown_lines or '• None'}",
        parse_mode="HTML",
    )


# ─── Frictionless Media Drop & Forward (Admin Zero-Touch) ───────────────────


@router.message(
    StateFilter(None),
    F.chat.type == "private",
    F.content_type.in_({"document", "video"}),
)
async def admin_drop_media_handler(message: Message, session: AsyncSession) -> None:
    """Zero-friction auto-indexing: Admin forwards or drops any anime file directly into the bot."""
    if not message.from_user or message.from_user.id not in settings.admin_id_list:
        return

    file_info = _extract_file_info(message)
    if not file_info:
        return

    existing = await queries.get_file_by_telegram_id(session, file_info["file_id"])
    if existing:
        await message.answer(
            f"⏩ <b>Already in vault:</b> <code>{html.escape(existing.file_name)}</code> (ID: #{existing.id})",
            parse_mode="HTML",
        )
        return

    display_name = file_info.get("original_name") or f"File_{file_info['file_unique_id'][:8]}"

    # Save file record
    f = await queries.save_file(
        session,
        file_name=display_name,
        file_id=file_info["file_id"],
        file_unique_id=file_info["file_unique_id"],
        file_type=file_info["file_type"],
        file_size=file_info["file_size"],
        uploaded_by=file_info["uploaded_by"],
        category_id=None,
        caption=file_info.get("caption"),
    )

    # Auto-categorize via AniList
    cat = await auto_categorize_file(session, f)
    cat_text = f"{cat.emoji} {cat.name}" if cat else "📁 Uncategorized"

    bot = message.bot
    bot_username = "NakamaNetworkbot"
    if bot:
        try:
            me = await bot.get_me()
            bot_username = me.username or bot_username
        except Exception:
            pass

    direct_link = f"https://t.me/{bot_username}?start=file_{f.id}"
    series = clean_series_name(display_name)
    ep = extract_episode_number(display_name)
    ep_str = f"Ep {ep}" if ep is not None else ""

    await message.answer(
        f"⚡ <b>Auto-Indexed & Categorized!</b>\n\n"
        f"🎬 <b>Series:</b> <b>{html.escape(series)}</b> {ep_str}\n"
        f"📄 <b>File:</b> <code>{html.escape(display_name)}</code>\n"
        f"📂 <b>Category:</b> {cat_text}\n"
        f"📦 <b>Size:</b> {f.human_size}\n"
        f"🔗 <b>Direct Link:</b> <code>{direct_link}</code>\n\n"
        f"<i>💡 Forward more files anytime to keep indexing without commands!</i>",
        parse_mode="HTML",
    )

    if settings.update_channel and bot:
        try:
            await broadcast_ongoing_episode(bot, f, target_channel=settings.update_channel)
        except Exception as e:
            logger.debug("Failed channel auto-post: %s", e)


# ─── Helpers ─────────────────────────────────────────────────────────────────



def _extract_file_info(message: Message) -> dict | None:
    """Extract file metadata from a message."""
    user_id = message.from_user.id if message.from_user else 0

    caption = message.caption or None
    caption_title = message.caption.split("\n")[0].strip() if message.caption else ""

    if message.document:
        return {
            "file_id": message.document.file_id,
            "file_unique_id": message.document.file_unique_id,
            "file_type": "document",
            "file_size": message.document.file_size or 0,
            "original_name": message.document.file_name or caption_title or "",
            "caption": caption,
            "uploaded_by": user_id,
        }
    elif message.video:
        return {
            "file_id": message.video.file_id,
            "file_unique_id": message.video.file_unique_id,
            "file_type": "video",
            "file_size": message.video.file_size or 0,
            "original_name": message.video.file_name or caption_title or "",
            "caption": caption,
            "uploaded_by": user_id,
        }
    elif message.audio:
        return {
            "file_id": message.audio.file_id,
            "file_unique_id": message.audio.file_unique_id,
            "file_type": "audio",
            "file_size": message.audio.file_size or 0,
            "original_name": message.audio.file_name or message.audio.title or caption_title or "",
            "caption": caption,
            "uploaded_by": user_id,
        }
    elif message.photo:
        photo = message.photo[-1]
        return {
            "file_id": photo.file_id,
            "file_unique_id": photo.file_unique_id,
            "file_type": "photo",
            "file_size": photo.file_size or 0,
            "original_name": caption_title or "",
            "caption": caption,
            "uploaded_by": user_id,
        }
    elif message.animation:
        return {
            "file_id": message.animation.file_id,
            "file_unique_id": message.animation.file_unique_id,
            "file_type": "animation",
            "file_size": message.animation.file_size or 0,
            "original_name": message.animation.file_name or caption_title or "",
            "caption": caption,
            "uploaded_by": user_id,
        }
    return None


# ─── Manual Ongoing Channel Poster (/post_channel) ───────────────────────────


@router.message(Command("post_channel", "broadcast_card"))
async def cmd_post_channel(message: Message, session: AsyncSession) -> None:
    """Manually broadcast a stylish ongoing anime release card to the updates channel."""
    if not (message.from_user and message.from_user.id in settings.admin_ids):
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "📢 <b>Post Ongoing Channel Card</b>\n\n"
            "Usage: <code>/post_channel &lt;file_id&gt;</code>\n"
            "Example: <code>/post_channel 42</code>\n\n"
            "<i>Broadcasts a high-res AniList visual card with a direct 'Download ↗' button to your channel.</i>",
            parse_mode="HTML",
        )
        return

    try:
        fid = int(parts[1].strip())
    except ValueError:
        await message.answer("❌ File ID must be a valid number.")
        return

    f = await queries.get_file(session, fid)
    if not f:
        await message.answer(f"❌ File #{fid} not found.")
        return

    if not settings.update_channel:
        await message.answer("❌ <code>UPDATE_CHANNEL</code> is not configured.", parse_mode="HTML")
        return

    success = await broadcast_ongoing_episode(message.bot, f)
    if success:
        await message.answer(
            f"✅ <b>Posted to Channel!</b>\n\n"
            f"Anime: <b>{html.escape(f.file_name)}</b>\n"
            f"Target: <code>{settings.update_channel}</code>",
            parse_mode="HTML",
        )
    else:
        await message.answer("❌ Failed to broadcast card. Ensure the bot is an admin in your channel with post permissions.")
