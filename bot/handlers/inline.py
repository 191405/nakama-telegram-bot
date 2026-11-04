"""Inline query handler — lets users search & share files from any chat."""

from __future__ import annotations

import hashlib

from aiogram import Router
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultCachedDocument,
    InlineQueryResultCachedPhoto,
    InlineQueryResultCachedVideo,
    InlineQueryResultCachedAudio,
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import queries
from bot.utils.formatting import format_file_size, file_type_emoji

router = Router(name="inline")


@router.inline_query()
async def inline_search(query: InlineQuery, session: AsyncSession) -> None:
    """Handle inline search queries from any chat."""
    search_text = query.query.strip()

    if not search_text:
        # Show hint when no query is entered
        await query.answer(
            results=[
                InlineQueryResultArticle(
                    id="hint",
                    title="🔍 Type to search files...",
                    description="Enter a file name to search",
                    input_message_content=InputTextMessageContent(
                        message_text="💡 Use inline mode to search: @bot_name your query"
                    ),
                )
            ],
            cache_time=5,
            is_personal=True,
        )
        return

    files = await queries.search_files(session, search_text, limit=20)

    if not files:
        await query.answer(
            results=[
                InlineQueryResultArticle(
                    id="no_results",
                    title=f"😕 No results for '{search_text}'",
                    description="Try a different search term",
                    input_message_content=InputTextMessageContent(
                        message_text=f"😕 No files found for: {search_text}"
                    ),
                )
            ],
            cache_time=10,
            is_personal=True,
        )
        return

    results = []
    for f in files:
        # Create a stable unique ID for caching
        result_id = hashlib.md5(f"{f.id}:{f.file_unique_id}".encode()).hexdigest()
        emoji = file_type_emoji(f.file_type)
        size_str = format_file_size(f.file_size)
        cat_name = f.category.name if f.category else "Uncategorized"

        description = f"{size_str} | 📂 {cat_name} | 📥 {f.download_count}"

        if f.file_type == "photo":
            results.append(
                InlineQueryResultCachedPhoto(
                    id=result_id,
                    photo_file_id=f.file_id,
                    title=f"{emoji} {f.file_name}",
                    description=description,
                    caption=f"{emoji} <b>{f.file_name}</b>\n📥 {f.download_count} downloads",
                    parse_mode="HTML",
                )
            )
        elif f.file_type == "video":
            results.append(
                InlineQueryResultCachedVideo(
                    id=result_id,
                    video_file_id=f.file_id,
                    title=f"{emoji} {f.file_name}",
                    description=description,
                    caption=f"{emoji} <b>{f.file_name}</b>\n📥 {f.download_count} downloads",
                    parse_mode="HTML",
                )
            )
        elif f.file_type == "audio":
            results.append(
                InlineQueryResultCachedAudio(
                    id=result_id,
                    audio_file_id=f.file_id,
                    caption=f"{emoji} <b>{f.file_name}</b>\n📥 {f.download_count} downloads",
                    parse_mode="HTML",
                )
            )
        else:
            # Documents, animations, etc. — use cached document
            results.append(
                InlineQueryResultCachedDocument(
                    id=result_id,
                    document_file_id=f.file_id,
                    title=f"{emoji} {f.file_name}",
                    description=description,
                    caption=f"{emoji} <b>{f.file_name}</b>\n📥 {f.download_count} downloads",
                    parse_mode="HTML",
                )
            )

    await query.answer(
        results=results,
        cache_time=30,
        is_personal=True,
    )
