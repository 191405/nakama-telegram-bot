"""Nakama Network Web API and Media Streaming Gateway.

High-performance backend service providing:
- REST API for catalog discovery, latest episode feed, and series detail.
- HTTP Range (206 Partial Content) video streaming gateway.
- Static hosting for the Nakama Network web interface.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any

from aiohttp import web
from aiogram import Bot
from telethon import TelegramClient
from sqlalchemy import func, select, text

from bot.config import settings
from bot.db.engine import async_session, init_db
from bot.db.models import Category, File
from bot.db import queries
from bot.utils.anilist import fetch_anime_info
from bot.utils.episodes import extract_episode_number, extract_series_name

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s - %(message)s",
)
logger = logging.getLogger("nakama.gateway")

WEB_ROOT = Path(__file__).parent.parent / "web" / "public"


# --- Utilities ---------------------------------------------------------------


def parse_byte_range(range_header: str | None, total_size: int) -> tuple[int, int]:
    """Parse an HTTP Range header into valid (start, end) byte offsets (RFC 7233).

    Malformed or unsatisfiable ranges fall back to the full resource instead of
    raising, so a bad header never turns into a 500 for the client.
    """
    if not range_header or not range_header.startswith("bytes="):
        return 0, total_size - 1

    try:
        raw = range_header[6:].strip()
        if "," in raw:  # only a single range is supported; use the first
            raw = raw.split(",", 1)[0].strip()
        start_s, _, end_s = raw.partition("-")

        # Suffix byte range: e.g. bytes=-500 (last 500 bytes)
        if not start_s and end_s:
            suffix_len = int(end_s)
            if suffix_len <= 0:
                return 0, total_size - 1
            return max(0, total_size - suffix_len), total_size - 1

        start = int(start_s) if start_s else 0
        end = int(end_s) if end_s else total_size - 1
        start = max(0, min(start, total_size - 1))
        end = max(start, min(end, total_size - 1))
        return start, end
    except (ValueError, TypeError):
        return 0, total_size - 1


def content_type_for(filename: str) -> str:
    """Best-effort MIME type for a media filename (MKV, MP4, WebM, etc.)."""
    guessed = mimetypes.guess_type(filename or "")[0]
    return guessed or "video/mp4"


def make_etag(file_record) -> str:
    """Stable weak validator derived from immutable file identity."""
    return f'W/"file-{file_record.id}-{int(file_record.file_size or 0)}"'


def get_storage_channel_id() -> int:
    """Resolve the storage channel from configuration; never hardcode an ID."""
    if not settings.storage_channel:
        raise RuntimeError("STORAGE_CHANNEL is not configured")
    try:
        return int(settings.storage_channel)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Invalid STORAGE_CHANNEL: {settings.storage_channel}") from exc


def pick_streamer(app: web.Application) -> dict | None:
    """Round-robin across the MTProto client pool to avoid a single bottleneck."""
    pool: list[dict] = app.get("telethon_pool") or []
    if not pool:
        return None
    idx = app.get("telethon_idx", 0) % len(pool)
    app["telethon_idx"] = idx + 1
    return pool[idx]


# --- Admin authentication (HMAC-signed, HttpOnly cookie) ----------------------

ADMIN_COOKIE = "nakama_admin"
ADMIN_COOKIE_TTL = 86400


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _admin_signature(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_admin_cookie(secret: str) -> str:
    payload = _b64e(
        json.dumps(
            {"exp": int(time.time()) + ADMIN_COOKIE_TTL}, separators=(",", ":")
        ).encode()
    )
    return f"{payload}.{_admin_signature(secret, payload)}"


def verify_admin_cookie(secret: str, value: str | None) -> bool:
    if not secret or not value or "." not in value:
        return False
    try:
        payload, signature = value.split(".", 1)
        if not hmac.compare_digest(_admin_signature(secret, payload), signature):
            return False
        expires = int(json.loads(_b64d(payload)).get("exp", 0))
        return expires > time.time()
    except Exception:
        return False


def require_admin(request: web.Request) -> None:
    if not verify_admin_cookie(
        settings.admin_panel_secret, request.cookies.get(ADMIN_COOKIE)
    ):
        raise web.HTTPUnauthorized(text="Admin authentication required")


def _secure_cookie(request: web.Request) -> bool:
    return request.headers.get("X-Forwarded-Proto", request.scheme) == "https"


def strip_html(text: str) -> str:
    """Remove HTML tags from raw descriptions."""
    return re.sub(r"<[^>]+>", "", text or "").strip()


async def get_series_meta(name: str) -> dict[str, Any]:
    """Fetch AniList metadata for an anime series."""
    meta = await fetch_anime_info(name)
    out: dict[str, Any] = {
        "cover_image": None,
        "banner_image": None,
        "score": None,
        "status": "ONGOING",
        "genres": [],
        "year": None,
        "description": "",
        "title_english": None,
        "title_romaji": None,
    }
    if meta:
        covers = meta.get("coverImage") or {}
        out["cover_image"] = covers.get("extraLarge") or covers.get("large")
        out["banner_image"] = meta.get("bannerImage")
        out["score"] = meta.get("averageScore")
        out["year"] = meta.get("seasonYear")
        out["genres"] = (meta.get("genres") or [])[:3]
        out["description"] = strip_html(meta.get("description") or "")
        titles = meta.get("title") or {}
        out["title_english"] = titles.get("english")
        out["title_romaji"] = titles.get("romaji")
        if meta.get("status") == "FINISHED":
            out["status"] = "COMPLETED"
    return out


# --- API Handlers ------------------------------------------------------------


async def handle_health(request: web.Request) -> web.Response:
    """GET /health - liveness/readiness probe used by Docker, Fly.io and the UI."""
    started_at: float = request.app.get("started_at", 0)
    db_ok = False
    db_error: str | None = None
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:
        db_error = str(exc)[:200]
        logger.error("Health check: database unavailable: %s", exc)

    telethon_ok = bool(
        request.app.get("telethon_client") and request.app.get("storage_entity")
    )
    payload = {
        "status": "ok" if db_ok else "degraded",
        "service": "nakama-gateway",
        "uptime_seconds": int(time.time() - started_at) if started_at else 0,
        "checks": {
            "database": {"ok": db_ok, "error": db_error},
            "mtproto": {
                "ok": telethon_ok,
                "mode": "streaming" if telethon_ok else "fallback",
            },
        },
    }
    return web.json_response(payload, status=200 if db_ok else 503)


async def get_catalog_version(session) -> str:
    """Cheap fingerprint of catalog state, used by the UI for poll-based refresh."""
    row = (
        await session.execute(
            select(
                func.count(File.id),
                func.coalesce(func.max(File.id), 0),
                func.coalesce(func.sum(File.download_count), 0),
            )
        )
    ).one()
    cat_count = (await session.execute(select(func.count(Category.id)))).scalar_one()
    return f"{row[0]}-{row[1]}-{row[2]}-{cat_count}"


async def handle_catalog_version(request: web.Request) -> web.Response:
    """GET /api/catalog/version - tiny payload for change detection."""
    async with async_session() as session:
        version = await get_catalog_version(session)
    return web.json_response({"status": "ok", "version": version})


async def handle_catalog(request: web.Request) -> web.Response:
    """GET /api/catalog - Grouped anime catalog with cover art and latest episodes."""
    async with async_session() as session:
        files = list((await session.execute(select(File).order_by(File.created_at.desc()))).scalars().all())
        version = await get_catalog_version(session)

    # Group files by clean anime title
    series_dict: dict[str, list[File]] = {}
    for f in files:
        name = (extract_series_name(f.file_name) or f.file_name).title().strip()
        series_dict.setdefault(name, []).append(f)

    # Sort each series files by episode number
    for name, f_list in series_dict.items():
        f_list.sort(key=lambda x: extract_episode_number(x.file_name) or 0)

    # Enrich all series with AniList metadata in parallel
    async def build_series_card(name: str, ep_files: list[File]) -> dict:
        meta = await get_series_meta(name)
        latest_file = ep_files[-1] if ep_files else None
        latest_ep = extract_episode_number(latest_file.file_name) if latest_file else len(ep_files)
        return {
            "name": name,
            "display_title": meta["title_english"] or meta["title_romaji"] or name,
            "total_episodes": len(ep_files),
            "latest_episode": latest_ep or len(ep_files),
            "latest_file_id": latest_file.id if latest_file else None,
            "cover_image": meta["cover_image"],
            "banner_image": meta["banner_image"],
            "score": meta["score"],
            "status": meta["status"],
            "genres": meta["genres"],
            "year": meta["year"],
            "description": meta["description"],
            "total_downloads": sum(x.download_count for x in ep_files),
        }

    catalog_cards = await asyncio.gather(*[
        build_series_card(name, ep_files)
        for name, ep_files in series_dict.items()
    ])

    # Sort catalog by popularity / episode count
    catalog_cards = sorted(catalog_cards, key=lambda x: x["total_downloads"], reverse=True)

    # Build Animepahe-style Latest Releases feed
    latest_feed = []
    for f in files[:12]:
        s_name = (extract_series_name(f.file_name) or f.file_name).title().strip()
        ep_num = extract_episode_number(f.file_name)
        matched_card = next((c for c in catalog_cards if c["name"] == s_name), None)
        cover = matched_card["cover_image"] if matched_card else None
        latest_feed.append({
            "id": f.id,
            "file_name": f.file_name,
            "series": s_name,
            "display_title": matched_card["display_title"] if matched_card else s_name,
            "episode": ep_num or 1,
            "size": f.human_size,
            "cover_image": cover,
        })

    return web.json_response({
        "status": "ok",
        "version": version,
        "total_series": len(catalog_cards),
        "catalog": catalog_cards,
        "latest_releases": latest_feed,
    })


async def handle_series_detail(request: web.Request) -> web.Response:
    """GET /api/series/{name} - All episodes and full metadata for a specific series."""
    raw_name = request.match_info.get("name", "").strip()
    if not raw_name:
        return web.json_response({"error": "Series name required"}, status=400)

    clean_target = raw_name.title().strip()

    async with async_session() as session:
        all_files = list((await session.execute(select(File))).scalars().all())

    matched_files = [
        f for f in all_files
        if (extract_series_name(f.file_name) or f.file_name).title().strip() == clean_target
    ]

    if not matched_files:
        # Fallback to substring matching
        matched_files = [f for f in all_files if raw_name.lower() in f.file_name.lower()]

    if not matched_files:
        return web.json_response({"error": "Series not found"}, status=404)

    # Sort numerically by episode number
    matched_files.sort(key=lambda x: extract_episode_number(x.file_name) or 0)

    meta = await get_series_meta(clean_target)

    episodes = []
    for f in matched_files:
        ep_num = extract_episode_number(f.file_name)
        episodes.append({
            "id": f.id,
            "file_name": f.file_name,
            "episode": ep_num or (len(episodes) + 1),
            "size": f.human_size,
            "downloads": f.download_count,
        })

    return web.json_response({
        "status": "ok",
        "series": clean_target,
        "display_title": meta["title_english"] or meta["title_romaji"] or clean_target,
        "cover_image": meta["cover_image"],
        "banner_image": meta["banner_image"],
        "description": meta["description"],
        "genres": meta["genres"],
        "score": meta["score"],
        "year": meta["year"],
        "airing_status": meta["status"],
        "total_episodes": len(episodes),
        "episodes": episodes,
    })


async def handle_stream(request: web.Request) -> web.StreamResponse:
    """GET /stream/{file_id} - HTTP byte-range streaming via Telegram MTProto.

    Returns 206 only for genuine Range requests; plain GET requests receive a
    normal 200 full-body response. Conditional headers (If-None-Match,
    If-Range) are honoured so players can probe and cache efficiently.
    """
    try:
        file_id = int(request.match_info.get("file_id"))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(text="Invalid file ID")

    async with async_session() as session:
        f = await queries.get_file(session, file_id)

    if not f:
        raise web.HTTPNotFound(text="File not found")

    total_size = f.file_size
    if total_size <= 0:
        raise web.HTTPBadRequest(text="File has zero length")

    etag = make_etag(f)

    # aiohttp implicitly registers HEAD alongside GET and calls this same
    # handler, so answer metadata-only probes here (no body, no MTProto work).
    if request.method == "HEAD":
        return web.Response(status=200, headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(int(total_size)),
            "Content-Type": content_type_for(f.file_name),
            "ETag": etag,
            "Cache-Control": "public, max-age=86400",
        })

    # Conditional request: representation unchanged.
    if request.headers.get("If-None-Match", "").strip() in (etag, "*"):
        return web.Response(
            status=304,
            headers={"ETag": etag, "Cache-Control": "public, max-age=86400"},
        )

    range_header = request.headers.get("Range")
    # If-Range: a stale validator means the Range must be ignored (send full body).
    if range_header and request.headers.get("If-Range") and request.headers["If-Range"].strip() != etag:
        range_header = None

    is_range = bool(range_header and range_header.startswith("bytes="))
    start, end = parse_byte_range(range_header, total_size)
    chunk_length = end - start + 1

    base_headers: dict[str, str] = {
        "Accept-Ranges": "bytes",
        "ETag": etag,
        "Cache-Control": "public, max-age=86400",
    }
    if is_range:
        base_headers["Content-Range"] = f"bytes {start}-{end}/{total_size}"
    status = 206 if is_range else 200
    reason = "Partial Content" if is_range else "OK"

    content_type = content_type_for(f.file_name)

    # Option A: Local media file if present on disk
    local_path = Path("media") / f.file_name
    if local_path.exists() and local_path.is_file():
        response = web.StreamResponse(
            status=status,
            reason=reason,
            headers={
                **base_headers,
                "Content-Type": content_type,
                "Content-Length": str(chunk_length),
            },
        )
        await response.prepare(request)
        with open(local_path, "rb") as fp:
            fp.seek(start)
            remaining = chunk_length
            buf = 64 * 1024
            while remaining > 0:
                data = fp.read(min(buf, remaining))
                if not data:
                    break
                await response.write(data)
                remaining -= len(data)
        await response.write_eof()
        return response

    # Option B: Stream via Telegram MTProto
    try:
        storage_channel_id = get_storage_channel_id()
    except RuntimeError as exc:
        logger.error("Cannot stream: %s", exc)
        raise web.HTTPInternalServerError(text="Storage channel is not configured")

    streamer = pick_streamer(request.app)
    telethon_client: TelegramClient | None = streamer["client"] if streamer else request.app.get("telethon_client")
    storage_entity = streamer["entity"] if streamer else request.app.get("storage_entity")

    if not telethon_client or not storage_entity:
        logger.warning("MTProto client not active, redirecting to Telegram deep link.")
        raise web.HTTPFound(location=f"https://t.me/NakamaNetworkbot?start=file_{f.id}")

    # Ensure file is registered on the storage channel
    channel_msg_id = getattr(f, "channel_message_id", None)
    if not channel_msg_id:
        try:
            bot: Bot | None = request.app.get("bot")
            if not bot:
                bot = Bot(token=settings.bot_token)
            logger.info("Syncing file #%s to storage channel on demand...", f.id)
            sync_msg = await bot.send_document(
                chat_id=storage_channel_id,
                document=f.file_id,
                caption=f"Nakama Vault #{f.id} | {f.file_name}"[:1024],
            )
            channel_msg_id = sync_msg.message_id
            async with async_session() as update_session:
                db_file = await update_session.get(File, f.id)
                if db_file:
                    db_file.channel_message_id = channel_msg_id
                    await update_session.commit()
            logger.info("File #%s auto-synced to channel message #%s", f.id, channel_msg_id)
        except Exception as e:
            logger.error("Failed to auto-sync file #%s: %s", f.id, e)
            raise web.HTTPInternalServerError(text="Failed to prepare file for streaming")

    # Fetch Telegram MTProto media object
    try:
        tg_msg = await telethon_client.get_messages(storage_entity, ids=channel_msg_id)
        if not tg_msg or not tg_msg.media:
            logger.error("Channel message #%s has no media", channel_msg_id)
            raise web.HTTPNotFound(text="Media not found on storage channel")
    except Exception as e:
        logger.error("Error retrieving channel message #%s: %s", channel_msg_id, e)
        raise web.HTTPInternalServerError(text="Failed to retrieve media from storage")

    if f.file_name.lower().endswith(".webm"):
        content_type = "video/webm"

    response = web.StreamResponse(
        status=status,
        reason=reason,
        headers={
            **base_headers,
            "Content-Type": content_type,
            "Content-Length": str(chunk_length),
            "Content-Disposition": f'inline; filename="{Path(f.file_name).name}"',
            "Access-Control-Allow-Origin": "*",
        },
    )
    await response.prepare(request)

    remaining = chunk_length
    try:
        async for chunk in telethon_client.iter_download(
            tg_msg.media,
            offset=start,
            request_size=256 * 1024,
        ):
            if remaining <= 0:
                break
            if len(chunk) > remaining:
                chunk = chunk[:remaining]
            await response.write(chunk)
            remaining -= len(chunk)
    except ConnectionResetError:
        pass
    except Exception as e:
        logger.debug("Client stream ended early: %s", e)

    await response.write_eof()
    return response




# --- AutoNews Service --------------------------------------------------------

_news_cache: list[dict[str, Any]] = []
_news_cache_time: float = 0.0
NEWS_CACHE_TTL = 1800.0  # 30 minutes

CURATED_FALLBACK_NEWS: list[dict[str, Any]] = [
    {
        "id": "nakama-news-1",
        "title": "Gachiakuta Anime Season 1 Reaches Critical Climax with Worldwide Streaming Acclaim",
        "summary": "The smash-hit adaptation of Kei Urana's battle manga continues to break viewing records with high-octane animation from Studio Bones.",
        "source": "Anime News Network",
        "category": "Seasonal",
        "published_at": "Today",
        "url": "https://www.animenewsnetwork.com",
        "image": "https://s4.anilist.co/file/anilistcdn/media/anime/banner/176496-Wj4jQx7rL8q3.jpg",
    },
    {
        "id": "nakama-news-2",
        "title": "The World's Strongest Rearguard: Labyrinth Country Saga Season 2 in Production",
        "summary": "Official production committees confirmed additional episode runs for the popular dungeon-crawling fantasy franchise.",
        "source": "Official Broadcast",
        "category": "Industry",
        "published_at": "Yesterday",
        "url": "https://www.animenewsnetwork.com",
        "image": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/large/bx128905-1Xv8x390p1.jpg",
    },
    {
        "id": "nakama-news-3",
        "title": "Black Torch TV Adaptation Spotlight: High-Grade Supernatural Action Redefines Slate",
        "summary": "Detailed look into the demon-slaying ninja aesthetic and kinetic choreography powering the latest broadcast release.",
        "source": "Industry Insights",
        "category": "Spotlight",
        "published_at": "Nov 18, 2026",
        "url": "https://www.animenewsnetwork.com",
        "image": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/large/bx139045-3129849.jpg",
    },
    {
        "id": "nakama-news-4",
        "title": "New High-Fidelity Video Encoding & Instant MTProto Media Protocol Deployed",
        "summary": "Nakama Network expands infrastructure with RFC 7233 byte-range seekability and native SSA/ASS subtitle track container preservation.",
        "source": "Nakama Network DevLog",
        "category": "Platform",
        "published_at": "Nov 19, 2026",
        "url": "#/",
        "image": "/assets/logo.svg",
    },
]


async def fetch_anime_news() -> list[dict[str, Any]]:
    """Fetch live anime news from Anime News Network RSS, cached with curated fallback."""
    global _news_cache, _news_cache_time
    import time
    import urllib.request
    import xml.etree.ElementTree as ET

    now = time.time()
    if _news_cache and (now - _news_cache_time < NEWS_CACHE_TTL):
        return _news_cache

    def _sync_fetch() -> list[dict[str, Any]]:
        articles: list[dict[str, Any]] = []
        try:
            req = urllib.request.Request(
                "https://www.animenewsnetwork.com/all/rss.xml?ann-edition=us",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Nakama/2.0"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                xml_data = resp.read()
            root = ET.fromstring(xml_data)
            items = root.findall(".//item")
            for idx, item in enumerate(items[:24]):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                desc = strip_html(item.findtext("description") or "")
                pub_date = (item.findtext("pubDate") or "").strip()
                category = (item.findtext("category") or "Anime").strip()

                if pub_date:
                    try:
                        parts = pub_date.split()
                        if len(parts) >= 4:
                            pub_date = f"{parts[2]} {parts[1]}, {parts[3]}"
                    except Exception:
                        pass

                articles.append({
                    "id": f"ann-{idx}",
                    "title": title,
                    "summary": desc[:280] + ("..." if len(desc) > 280 else ""),
                    "source": "Anime News Network",
                    "category": category,
                    "published_at": pub_date or "Recent",
                    "url": link,
                    "image": None,
                })
        except Exception as err:
            logger.warning("Error fetching ANN RSS feed: %s", err)
        return articles

    loop = asyncio.get_running_loop()
    live_articles = await loop.run_in_executor(None, _sync_fetch)

    if live_articles:
        _news_cache = live_articles
        _news_cache_time = now
        return _news_cache

    return _news_cache or CURATED_FALLBACK_NEWS


async def handle_news(request: web.Request) -> web.Response:
    """GET /api/news - Automated anime industry news feed."""
    news = await fetch_anime_news()
    return web.json_response({
        "status": "ok",
        "total": len(news),
        "articles": news,
    })


async def handle_admin_login(request: web.Request) -> web.Response:
    """POST /api/admin/login - exchange the admin secret for a signed cookie."""
    if not settings.admin_panel_secret:
        raise web.HTTPServiceUnavailable(text="Admin dashboard is not configured")
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Invalid JSON body")

    pin = str(body.get("pin", ""))
    if not hmac.compare_digest(pin, settings.admin_panel_secret):
        raise web.HTTPUnauthorized(text="Invalid PIN")

    response = web.json_response({"status": "ok"})
    response.set_cookie(
        ADMIN_COOKIE,
        make_admin_cookie(settings.admin_panel_secret),
        httponly=True,
        secure=_secure_cookie(request),
        samesite="Strict",
        max_age=ADMIN_COOKIE_TTL,
        path="/",
    )
    return response


async def handle_admin_logout(request: web.Request) -> web.Response:
    """POST /api/admin/logout - clear the admin session cookie."""
    response = web.json_response({"status": "ok"})
    response.del_cookie(ADMIN_COOKIE, path="/")
    return response


async def handle_admin_session(request: web.Request) -> web.Response:
    """GET /api/admin/session - lets the UI check whether the cookie is valid."""
    return web.json_response({
        "authenticated": verify_admin_cookie(
            settings.admin_panel_secret, request.cookies.get(ADMIN_COOKIE)
        )
    })


async def handle_admin_stats(request: web.Request) -> web.Response:
    """GET /api/admin/stats - Aggregate platform statistics for the admin dashboard."""
    require_admin(request)
    async with async_session() as session:
        files = list((await session.execute(select(File))).scalars().all())

    series_dict: dict[str, list[File]] = {}
    total_downloads = 0
    total_size_bytes = 0
    for f in files:
        name = (extract_series_name(f.file_name) or f.file_name).title().strip()
        series_dict.setdefault(name, []).append(f)
        total_downloads += f.download_count
        total_size_bytes += f.file_size or 0

    total_size_gb = round(total_size_bytes / (1024 ** 3), 2)

    return web.json_response({
        "status": "ok",
        "total_series": len(series_dict),
        "total_episodes": len(files),
        "total_downloads": total_downloads,
        "total_size_gb": total_size_gb,
        "series_breakdown": [
            {"name": name, "episodes": len(ep_list)}
            for name, ep_list in sorted(series_dict.items(), key=lambda x: len(x[1]), reverse=True)
        ],
    })


# --- Static / SPA Handler ----------------------------------------------------


async def serve_index(request: web.Request) -> web.FileResponse:
    index = WEB_ROOT / "index.html"
    if index.exists():
        return web.FileResponse(index)
    return web.Response(text="Nakama Network Gateway running.", content_type="text/plain")


async def handle_spa_fallback(request: web.Request) -> web.StreamResponse:
    """Serve the SPA for real routes, but return JSON 404 for unknown APIs."""
    path = request.path
    if path.startswith("/api/") or path.startswith("/stream/") or path == "/health":
        return web.json_response({"error": "Not found", "path": path}, status=404)
    return await serve_index(request)


# --- App Factory --------------------------------------------------------------


async def on_startup(app: web.Application) -> None:
    await init_db()
    logger.info("Database initialized.")

    if (
        settings.telegram_api_id
        and settings.telegram_api_hash
        and settings.bot_token
        and settings.storage_channel
    ):
        pool: list[dict] = []
        try:
            base_session = os.getenv("TELEGRAM_SESSION_PATH", "streamer_bot")
            if base_session == "streamer_bot" and Path("/data").is_dir():
                base_session = "/data/streamer_bot"
            storage_channel_id = get_storage_channel_id()
            size = max(1, min(settings.stream_pool_size, 8))

            for i in range(size):
                session_name = base_session if size == 1 else f"{base_session}_{i}"
                logger.info("Connecting MTProto stream client %d/%d (session: %s)...", i + 1, size, session_name)
                client = TelegramClient(
                    session_name, settings.telegram_api_id, settings.telegram_api_hash
                )
                await client.start(bot_token=settings.bot_token)
                pool.append({
                    "client": client,
                    "entity": await client.get_entity(storage_channel_id),
                })

            app["telethon_pool"] = pool
            app["telethon_idx"] = 0
            # Kept for backwards compatibility with any code reading these keys.
            app["telethon_client"] = pool[0]["client"]
            app["storage_entity"] = pool[0]["entity"]
            app["bot"] = Bot(token=settings.bot_token)
            logger.info("Telethon MTProto pool ready (%d client(s)).", len(pool))
        except Exception as e:
            logger.error("Failed to connect Telethon MTProto pool: %s", e)
            for entry in pool:
                try:
                    await entry["client"].disconnect()
                except Exception:
                    pass
    else:
        logger.warning(
            "Telegram MTProto credentials not configured (TELEGRAM_API_ID, TELEGRAM_API_HASH, "
            "BOT_TOKEN, STORAGE_CHANNEL). Web gateway running in fallback mode."
        )


async def on_cleanup(app: web.Application) -> None:
    for entry in app.get("telethon_pool", []):
        try:
            await entry["client"].disconnect()
        except Exception:
            pass
    if "bot" in app:
        try:
            await app["bot"].session.close()
        except Exception:
            pass


def create_app() -> web.Application:
    app = web.Application()
    app["started_at"] = time.time()
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    # API Routes
    app.router.add_get("/health", handle_health)
    app.router.add_get("/api/catalog", handle_catalog)
    app.router.add_get("/api/catalog/version", handle_catalog_version)
    app.router.add_get("/api/series/{name}", handle_series_detail)
    app.router.add_get("/api/news", handle_news)
    app.router.add_post("/api/admin/login", handle_admin_login)
    app.router.add_post("/api/admin/logout", handle_admin_logout)
    app.router.add_get("/api/admin/session", handle_admin_session)
    app.router.add_get("/api/admin/stats", handle_admin_stats)
    app.router.add_get("/stream/{file_id}", handle_stream)

    # Static assets
    assets_dir = WEB_ROOT / "assets"
    if assets_dir.exists():
        app.router.add_static("/assets/", path=str(assets_dir), name="assets")

    # SPA Fallback
    app.router.add_get("/", serve_index)
    app.router.add_get("/{path:.*}", handle_spa_fallback)

    return app


def main() -> None:
    app = create_app()
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    logger.info("Nakama Network streaming server starting on http://%s:%s", host, port)
    web.run_app(app, host=host, port=port, print=None)


if __name__ == "__main__":
    main()
