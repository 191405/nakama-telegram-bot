"""Standalone Sub-Bot Worker: Automated SubsPlease RSS watcher & uploader to Storage Channel.

Architecture:
- Sub-Bot: Solely monitors anime releases (SubsPlease RSS) and uploads/drops them into your private Storage Channel.
- Main Bot (@NakamaNetworkbot): Remains the "General Arena" serving users, handling AI concierge, search, trivia, and deep-link downloads via Telegram's CDN.

Usage:
1. Create a dedicated sub-bot on Telegram via @BotFather (e.g. @NakamaUploaderBot).
2. Create a private Telegram Storage Channel (e.g. "Nakama Vault Storage").
3. Add BOTH your Sub-Bot AND @NakamaNetworkbot as Administrators to the Storage Channel.
4. Set environment variables:
   - SUB_BOT_TOKEN="your_sub_bot_token"
   - STORAGE_CHANNEL="-100xxxxxxxxxx" (or channel username)
5. Run: python -m worker.rss_sub_bot
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import aiohttp
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | [SUB-BOT] %(levelname)-8s | %(message)s",
)
logger = logging.getLogger(__name__)

SUB_BOT_TOKEN = os.getenv("SUB_BOT_TOKEN", "")
STORAGE_CHANNEL = os.getenv("STORAGE_CHANNEL", "")
RSS_URL = os.getenv("SUBSPLEASE_RSS", "https://subsplease.org/rss/?r=1080")
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "300"))  # 5 minutes
STATE_FILE = Path(__file__).parent / "processed_releases.json"


def load_processed_guids() -> set[str]:
    """Load previously seen release GUIDs to prevent duplicate posts."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def save_processed_guids(guids: set[str]) -> None:
    """Save processed GUIDs to local JSON state."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        # Keep last 500 entries to maintain light footprint
        json.dump(list(guids)[-500:], f, indent=2)


async def check_and_publish_releases(bot: Bot, processed: set[str]) -> None:
    """Fetch SubsPlease RSS and notify/upload new episodes into the Storage Channel."""
    logger.info("Checking SubsPlease RSS feed (%s)...", RSS_URL)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(RSS_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    logger.warning("SubsPlease RSS returned HTTP %d", resp.status)
                    return
                xml_text = await resp.text()

        root = ET.fromstring(xml_text)
        channel = root.find("channel")
        if channel is None:
            return

        items = channel.findall("item")
        new_items = []

        for item in reversed(items):  # Process oldest to newest
            guid_elem = item.find("guid")
            guid = guid_elem.text.strip() if guid_elem is not None and guid_elem.text else ""
            if not guid or guid in processed:
                continue

            title_elem = item.find("title")
            link_elem = item.find("link")
            size_elem = item.find("{https://subsplease.org/rss}size")

            title = title_elem.text.strip() if title_elem is not None and title_elem.text else "New Anime Release"
            magnet = link_elem.text.strip() if link_elem is not None and link_elem.text else ""
            size = size_elem.text.strip() if size_elem is not None and size_elem.text else "HD"

            new_items.append({
                "guid": guid,
                "title": title,
                "magnet": magnet,
                "size": size,
            })

        if not new_items:
            logger.info("No new releases in this cycle.")
            return

        logger.info("Found %d new anime release(s)!", len(new_items))

        for entry in new_items:
            title = entry["title"]
            magnet = entry["magnet"]
            size = entry["size"]
            guid = entry["guid"]

            text = (
                f"🎬 <b>{title}</b>\n\n"
                f"📦 <b>Size:</b> <code>{size}</code>\n"
                f"⚡ <b>Source:</b> SubsPlease 1080p\n\n"
                f"🧲 <b>Magnet URI:</b>\n<code>{magnet[:120]}...</code>"
            )

            markup = None
            if magnet:
                markup = InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="🧲 Open Magnet Link", url=magnet)]]
                )

            # Post into the Storage Channel
            await bot.send_message(
                chat_id=STORAGE_CHANNEL,
                text=text,
                reply_markup=markup,
                parse_mode="HTML",
            )
            logger.info("Delivered release to Storage Channel: %s", title)

            processed.add(guid)
            save_processed_guids(processed)
            await asyncio.sleep(2)  # Avoid Telegram flood limit

    except Exception as exc:
        logger.error("Error during RSS checking cycle: %s", exc)


async def main() -> None:
    """Run the Sub-Bot RSS daemon."""
    if not SUB_BOT_TOKEN or not STORAGE_CHANNEL:
        logger.error(
            "SUB_BOT_TOKEN or STORAGE_CHANNEL environment variables are not set! "
            "Please configure them before starting the worker."
        )
        return

    bot = Bot(token=SUB_BOT_TOKEN)
    processed = load_processed_guids()
    logger.info("Sub-Bot RSS Ingest Worker started. Storage Channel: %s", STORAGE_CHANNEL)

    try:
        while True:
            await check_and_publish_releases(bot, processed)
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
