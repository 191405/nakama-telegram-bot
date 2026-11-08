"""Sync all database files into Telegram Storage Channel for MTProto streaming."""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from sqlalchemy import select

from bot.config import settings
from bot.db.engine import async_session
from bot.db.models import File

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sync_vault")

STORAGE_CHANNEL = -1001985886914


async def main():
    bot = Bot(token=settings.bot_token)
    logger.info("Starting storage vault sync...")

    async with async_session() as session:
        result = await session.execute(
            select(File).where(File.channel_message_id.is_(None)).order_id(File.id) if hasattr(select(File), 'order_id') else select(File).where(File.channel_message_id.is_(None)).order_by(File.id)
        )
        pending_files = list(result.scalars().all())

    logger.info(f"Found {len(pending_files)} files to sync into storage channel.")

    for i, file_record in enumerate(pending_files, 1):
        retries = 0
        while retries < 5:
            try:
                caption = f"Nakama Vault #{file_record.id} | {file_record.file_name}"
                logger.info(f"[{i}/{len(pending_files)}] Syncing file #{file_record.id} ({file_record.file_name[:40]})...")
                
                # Send via Bot API
                msg = await bot.send_document(
                    chat_id=STORAGE_CHANNEL,
                    document=file_record.file_id,
                    caption=caption[:1024]
                )
                
                # Save channel_message_id
                async with async_session() as update_session:
                    db_file = await update_session.get(File, file_record.id)
                    if db_file:
                        db_file.channel_message_id = msg.message_id
                        await update_session.commit()
                
                logger.info(f" -> Successfully synced! Message ID: {msg.message_id}")
                # Brief sleep to stay well within Telegram broadcast rate limits
                await asyncio.sleep(1.0)
                break

            except TelegramRetryAfter as e:
                logger.warning(f"Flood control: sleeping {e.retry_after} seconds...")
                await asyncio.sleep(e.retry_after + 1)
                retries += 1
            except Exception as e:
                logger.error(f"Error syncing file #{file_record.id}: {e}")
                break

    await bot.session.close()
    logger.info("Storage vault sync completed.")


if __name__ == "__main__":
    asyncio.run(main())
