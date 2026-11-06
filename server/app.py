"""Nakama Network Web API and Media Streaming Gateway.

High-performance asynchronous server providing:
- REST API for catalog discovery, series navigation, and search.
- HTTP Range (206 Partial Content) streaming engine for browser video playback.
- Static hosting for the Nakama Network web interface.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from aiohttp import ClientSession, ClientTimeout, web
from sqlalchemy import select

from bot.config import settings
from bot.db.engine import async_session, init_db
from bot.db.models import Category, File
from bot.db import queries
from bot.utils.anilist import fetch_anime_info
from bot.utils.episodes import extract_episode_number, extract_series_name

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | [STREAM-API] %(levelname)-8s | %(message)s",
)
logger = logging.getLogger("nakama.streamer")

WEB_ROOT = Path(__file__).parent.parent / "web" / "public"


# ─── HTTP Utilities & Range Headers ──────────────────────────────────────────


def parse_byte_range(range_header: str | None, total_size: int) -> tuple[int, int]:
    """Parse HTTP Range header into valid (start, end) offsets.

    Example: 'bytes=0-1048575' -> (0, 1048575)
    """
    if not range_header or not range_header.startswith("bytes="):
        return 0, total_size - 1

    range_val = range_header.replace("bytes=", "").strip()
    parts = range_val.split("-")
    start = int(parts[0]) if parts[0] else 0
    end = int(parts[1]) if len(parts) > 1 and parts[1] else total_size - 1

    start = max(0, min(start, total_size - 1))
    end = max(start, min(end, total_size - 1))
    return start, end


# ─── API Handlers ─────────────────────────────────────────────────────────────


async def handle_catalog(request: web.Request) -> web.Response:
    """Return all series grouped with episode counts and AniList poster metadata."""
    async with async_session() as session:
        summaries = await queries.get_all_series_summaries(session)

    results = []
    for s in summaries:
        sample = s["sample_file"]
        results.append({
            "name": s["name"],
            "total_episodes": s["total_episodes"],
            "total_downloads": s["total_downloads"],
            "sample_file_id": sample.id if sample else None,
            "latest_file_id": s["latest_file"].id if s.get("latest_file") else None,
        })

    return web.json_response({"status": "ok", "count": len(results), "catalog": results})


async def handle_series_detail(request: web.Request) -> web.Response:
    """Return all episodes for a specific anime series."""
    series_name = request.match_info.get("name", "").strip()
    if not series_name:
        return web.json_response({"error": "Series name required"}, status=400)

    async with async_session() as session:
        stmt = (
            select(File)
            .where(File.file_name.ilike(f"%{series_name}%"))
            .order_by(File.created_at.desc())
        )
        files = list((await session.execute(stmt)).scalars().all())

    if not files:
        return web.json_response({"error": "Series not found"}, status=404)

    # Sort files numerically by episode number
    files.sort(
        key=lambda x: (
            extract_episode_number(x.file_name) is None,
            extract_episode_number(x.file_name) or 0,
        )
    )

    # Fetch poster and summary from AniList
    meta = await fetch_anime_info(series_name)
    cover_image = None
    banner_image = None
    description = ""
    genres = []
    if meta:
        cover_image = (
            (meta.get("coverImage") or {}).get("extraLarge")
            or (meta.get("coverImage") or {}).get("large")
        )
        banner_image = meta.get("bannerImage")
        description = re.sub(r"<[^>]+>", "", meta.get("description") or "")
        genres = meta.get("genres") or []

    episodes = []
    for f in files:
        ep_num = extract_episode_number(f.file_name)
        episodes.append({
            "id": f.id,
            "file_name": f.file_name,
            "episode": ep_num,
            "size_bytes": f.file_size,
            "size_human": f.human_size,
            "downloads": f.download_count,
            "stream_url": f"/stream/{f.id}",
        })

    return web.json_response({
        "status": "ok",
        "series": series_name,
        "cover_image": cover_image,
        "banner_image": banner_image,
        "description": description,
        "genres": genres,
        "total_episodes": len(episodes),
        "episodes": episodes,
    })


async def handle_search(request: web.Request) -> web.Response:
    """Fuzzy search across files and titles."""
    q = request.query.get("q", "").strip()
    if not q:
        return web.json_response({"status": "ok", "results": []})

    async with async_session() as session:
        files = await queries.search_files(session, q, limit=20)

    results = []
    for f in files:
        results.append({
            "id": f.id,
            "file_name": f.file_name,
            "series": extract_series_name(f.file_name),
            "episode": extract_episode_number(f.file_name),
            "size": f.human_size,
            "stream_url": f"/stream/{f.id}",
        })

    return web.json_response({"status": "ok", "query": q, "results": results})


async def handle_stream(request: web.Request) -> web.StreamResponse:
    """HTTP 206 Partial Content range-streaming gateway for browser video players.

    Streams media assets directly with seekable byte ranges.
    """
    file_id_raw = request.match_info.get("file_id")
    try:
        file_id = int(file_id_raw)
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(text="Invalid file ID")

    async with async_session() as session:
        f = await queries.get_file(session, file_id)

    if not f:
        raise web.HTTPNotFound(text="File record not found in vault")

    total_size = f.file_size
    if total_size <= 0:
        # Fallback to bot direct download redirect if size is undefined
        bot_username = "NakamaNetworkbot"
        raise web.HTTPFound(location=f"https://t.me/{bot_username}?start=file_{f.id}")

    range_header = request.headers.get("Range")
    start, end = parse_byte_range(range_header, total_size)
    chunk_length = end - start + 1

    # Check for local media file if stored on disk
    local_path = Path("media") / f.file_name
    if local_path.exists() and local_path.is_file():
        response = web.StreamResponse(
            status=206,
            reason="Partial Content",
            headers={
                "Content-Type": "video/mp4",
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes {start}-{end}/{total_size}",
                "Content-Length": str(chunk_length),
            },
        )
        await response.prepare(request)
        with open(local_path, "rb") as fp:
            fp.seek(start)
            bytes_left = chunk_length
            buf_size = 64 * 1024  # 64KB read buffer
            while bytes_left > 0:
                read_amount = min(buf_size, bytes_left)
                data = fp.read(read_amount)
                if not data:
                    break
                await response.write(data)
                bytes_left -= len(data)
        await response.write_eof()
        return response

    # If the file is solely in Telegram CDN, delegate via Telegram deep link or proxy
    bot_username = "NakamaNetworkbot"
    telegram_target = f"https://t.me/{bot_username}?start=file_{f.id}"
    raise web.HTTPFound(location=telegram_target)


# ─── SPA Fallback Handler ────────────────────────────────────────────────────


async def handle_spa_index(request: web.Request) -> web.FileResponse:
    """Serve index.html for all non-API web routes."""
    index_file = WEB_ROOT / "index.html"
    if index_file.exists():
        return web.FileResponse(index_file)
    return web.Response(text="Nakama Network Gateway active. Frontend index missing.", content_type="text/plain")


# ─── Application Factory ─────────────────────────────────────────────────────


def create_app() -> web.Application:
    """Build and configure the aiohttp web application."""
    app = web.Application()

    # API endpoints
    app.router.add_get("/api/catalog", handle_catalog)
    app.router.add_get("/api/series/{name}", handle_series_detail)
    app.router.add_get("/api/search", handle_search)
    app.router.add_get("/stream/{file_id}", handle_stream)

    # Static assets and SPA routes
    if WEB_ROOT.exists():
        app.router.add_static("/assets/", path=str(WEB_ROOT / "assets"), name="assets")
    app.router.add_get("/", handle_spa_index)
    app.router.add_get("/{path:.*}", handle_spa_index)

    return app


async def run_server(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Run the standalone web server."""
    await init_db()
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    logger.info("Nakama Network Web & Streaming Gateway running on http://%s:%d", host, port)
    await site.start()


if __name__ == "__main__":
    import asyncio

    asyncio.run(run_server())
