"""RSS ingest worker: notify-only, or full debrid-powered episode ingestion.

Two modes, selected automatically:

1. Without DEBRID_API_KEY — the original behaviour: poll SubsPlease RSS and
   post a magnet-link notice into the storage channel (not playable).

2. With DEBRID_API_KEY — resolve each magnet through Real-Debrid, download the
   resulting direct link, and upload the actual video file to the storage
   channel. The main bot's channel auto-indexer then makes it streamable on
   the website. On failure, a magnet notice is posted as a fallback.

Required env for mode 2:
  SUB_BOT_TOKEN, STORAGE_CHANNEL, TELEGRAM_API_ID, TELEGRAM_API_HASH,
  DEBRID_API_KEY
Optional:
  DEBRID_PROVIDER (realdebrid|alldebrid, default realdebrid),
  SUBSPLEASE_RSS, CHECK_INTERVAL_SECONDS, MAX_DOWNLOADS_PER_RUN,
  INGEST_TMP_DIR
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import quote

import aiohttp
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from telethon import TelegramClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | [INGEST] %(levelname)-8s | %(message)s",
)
logger = logging.getLogger(__name__)

SUB_BOT_TOKEN = os.getenv("SUB_BOT_TOKEN", "")
STORAGE_CHANNEL = os.getenv("STORAGE_CHANNEL", "")
TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID", "")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
RSS_URL = os.getenv("SUBSPLEASE_RSS", "https://subsplease.org/rss/?r=1080")
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "300"))
MAX_DOWNLOADS_PER_RUN = int(os.getenv("MAX_DOWNLOADS_PER_RUN", "3"))
DEBRID_API_KEY = os.getenv("DEBRID_API_KEY", "")
DEBRID_PROVIDER = os.getenv("DEBRID_PROVIDER", "realdebrid").strip().lower()
TMP_DIR = Path(os.getenv("INGEST_TMP_DIR", "/data/ingest_tmp"))
STATE_FILE = Path(__file__).parent / "processed_releases.json"

RD_BASE = "https://api.real-debrid.com/rest/1.0"
AD_BASE = "https://api.alldebrid.com/v4"


def debrid_enabled() -> bool:
    return bool(DEBRID_API_KEY and TELEGRAM_API_ID and TELEGRAM_API_HASH)


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
    """Save processed GUIDs to local JSON state (newest first, capped)."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    ordered = list(guids)[-500:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(ordered, f, indent=2)


def _auth_headers() -> dict[str, str]:
    if DEBRID_PROVIDER == "alldebrid":
        return {}
    return {"Authorization": f"Bearer {DEBRID_API_KEY}"}


async def rd_resolve_magnet(session: aiohttp.ClientSession, magnet: str) -> list[str]:
    """Real-Debrid: add magnet, select files, wait for direct links."""
    headers = _auth_headers()
    async with session.post(
        f"{RD_BASE}/torrents/addMagnet", data={"magnet": magnet}, headers=headers
    ) as resp:
        added = await resp.json()
    torrent_id = added.get("id")
    if not torrent_id:
        raise RuntimeError(f"Real-Debrid rejected magnet: {added}")

    async with session.post(
        f"{RD_BASE}/torrents/selectFiles/{torrent_id}",
        data={"files": "all"},
        headers=headers,
    ) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"Real-Debrid selectFiles failed: {resp.status}")

    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        async with session.get(
            f"{RD_BASE}/torrents/info/{torrent_id}", headers=headers
        ) as resp:
            info = await resp.json()
        if info.get("status") == 100 or info.get("ready"):
            links: list[str] = info.get("links") or []
            if links:
                return links
        await asyncio.sleep(10)
    raise TimeoutError("Real-Debrid did not finish in time")


async def ad_resolve_magnet(session: aiohttp.ClientSession, magnet: str) -> list[str]:
    """AllDebrid: add magnet, poll until ready, collect direct links."""
    url = f"{AD_BASE}/magnet/upload?agent=nakama&magnets[]={quote(magnet, safe='')}"
    async with session.get(url) as resp:
        added = await resp.json()
    magnets = (added.get("data") or {}).get("magnets") or []
    if not magnets:
        raise RuntimeError(f"AllDebrid rejected magnet: {added}")
    magnet_id = magnets[0].get("id")

    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        async with session.get(
            f"{AD_BASE}/magnet/status?agent=nakama&id={magnet_id}"
        ) as resp:
            data = await resp.json()
        entry = ((data.get("data") or {}).get("magnets")) or {}
        if str(entry.get("status", "")).lower() == "ready":
            links = [
                item["link"] for item in entry.get("links", []) if item.get("link")
            ]
            if links:
                return links
        await asyncio.sleep(10)
    raise TimeoutError("AllDebrid did not finish in time")


async def resolve_magnet(session: aiohttp.ClientSession, magnet: str) -> list[str]:
    if DEBRID_PROVIDER == "alldebrid":
        return await ad_resolve_magnet(session, magnet)
    return await rd_resolve_magnet(session, magnet)


async def download_link(session: aiohttp.ClientSession, url: str, dest: Path) -> Path:
    """Stream a debrid direct link to disk without buffering it all in memory."""
    timeout = aiohttp.ClientTimeout(total=None, sock_read=180)
    async with session.get(url, timeout=timeout) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as fh:
            async for chunk in resp.content.iter_chunked(1024 * 1024):
                fh.write(chunk)
    return dest


def pick_media_link(links: list[str]) -> str:
    """Prefer common video extensions; otherwise take the first link."""
    hints = (".mkv", ".mp4", ".webm", ".avi", ".mov", ".ts")
    for hint in hints:
        for link in links:
            if hint in link.lower():
                return link
    return links[0]


async def ingest_release(
    telethon_client: TelegramClient,
    session: aiohttp.ClientSession,
    entry: dict[str, Any],
    bot: Bot,
) -> bool:
    """Resolve, download and upload one release. Returns True on success."""
    title = entry["title"]
    magnet = entry["magnet"]
    if not magnet:
        logger.warning("No magnet for %s — skipping", title)
        return False

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = TMP_DIR / f"release_{abs(hash(magnet))}.mkv"
    try:
        links = await resolve_magnet(session, magnet)
        url = pick_media_link(links)
        logger.info("Downloading %s from debrid...", title)
        await download_link(session, url, tmp_path)

        size_mb = tmp_path.stat().st_size / (1024 * 1024)
        logger.info("Uploading %s (%.1f MB) to storage channel...", title, size_mb)
        caption = f"{title}\n[Auto-ingested via debrid]"
        message = await telethon_client.send_file(
            int(STORAGE_CHANNEL),
            str(tmp_path),
            caption=caption[:1024],
            force_document=True,
            allow_cache=False,
        )
        logger.info("Uploaded %s as message #%s", title, message.id)
        return True
    except Exception as exc:
        logger.error("Debrid ingest failed for %s: %s", title, exc)
        return False
    finally:
        tmp_path.unlink(missing_ok=True)


async def post_magnet_notice(bot: Bot, entry: dict[str, Any]) -> None:
    """Fallback notification when debrid ingestion is unavailable/failed."""
    magnet = entry["magnet"]
    markup = None
    if magnet:
        markup = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🧲 Open Magnet", url=magnet)]]
        )
    text = (
        f"🎬 <b>{entry['title']}</b>\n\n"
        f"📦 <b>Size:</b> <code>{entry['size']}</code>\n"
        f"⚡ <b>Source:</b> SubsPlease 1080p\n\n"
        f"🧲 <code>{magnet[:120]}...</code>"
    )
    await bot.send_message(
        chat_id=int(STORAGE_CHANNEL), text=text, reply_markup=markup, parse_mode="HTML"
    )


async def check_and_publish_releases(
    bot: Bot,
    telethon_client: TelegramClient | None,
    processed: set[str],
) -> None:
    """Fetch RSS and ingest every new release."""
    logger.info("Checking SubsPlease RSS feed (%s)...", RSS_URL)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(RSS_URL, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning("SubsPlease RSS returned HTTP %d", resp.status)
                    return
                xml_text = await resp.text()

            root = ET.fromstring(xml_text)
            channel = root.find("channel")
            if channel is None:
                return

            new_items: list[dict[str, Any]] = []
            for item in reversed(channel.findall("item")):
                guid_elem = item.find("guid")
                guid = guid_elem.text.strip() if guid_elem is not None and guid_elem.text else ""
                if not guid or guid in processed:
                    continue
                title_elem = item.find("title")
                link_elem = item.find("link")
                size_elem = item.find("{https://subsplease.org/rss}size")
                new_items.append({
                    "guid": guid,
                    "title": title_elem.text.strip() if title_elem is not None and title_elem.text else "New Anime Release",
                    "magnet": link_elem.text.strip() if link_elem is not None and link_elem.text else "",
                    "size": size_elem.text.strip() if size_elem is not None and size_elem.text else "HD",
                })

            if not new_items:
                logger.info("No new releases in this cycle.")
                return

            logger.info("Found %d new release(s).", len(new_items))
            uploaded = 0
            for entry in new_items:
                success = False
                if debrid_enabled() and telethon_client and uploaded < MAX_DOWNLOADS_PER_RUN:
                    success = await ingest_release(telethon_client, session, entry, bot)
                if success:
                    uploaded += 1
                else:
                    try:
                        await post_magnet_notice(bot, entry)
                    except Exception as exc:
                        logger.error("Failed to post magnet notice: %s", exc)

                processed.add(entry["guid"])
                save_processed_guids(processed)
                await asyncio.sleep(2)
    except Exception as exc:
        logger.error("Error during RSS cycle: %s", exc)


async def main() -> None:
    if not SUB_BOT_TOKEN or not STORAGE_CHANNEL:
        logger.error("SUB_BOT_TOKEN and STORAGE_CHANNEL must be configured.")
        return

    bot = Bot(token=SUB_BOT_TOKEN)
    telethon_client: TelegramClient | None = None
    if debrid_enabled():
        telethon_client = TelegramClient(
            "debrid_uploader", int(TELEGRAM_API_ID), TELEGRAM_API_HASH
        )
        await telethon_client.start(bot_token=SUB_BOT_TOKEN)
        logger.info("Debrid ingestion enabled via %s.", DEBRID_PROVIDER)
    else:
        logger.warning("No DEBRID_API_KEY — running in magnet-notification mode.")

    processed = load_processed_guids()
    try:
        while True:
            await check_and_publish_releases(bot, telethon_client, processed)
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
    finally:
        if telethon_client:
            await telethon_client.disconnect()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
