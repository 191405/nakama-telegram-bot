"""Nakama Network Web API and Media Streaming Gateway.

High-performance backend service providing:
- REST API for catalog discovery, latest episode feed, and series detail.
- HTTP Range (206 Partial Content) video streaming gateway.
- Static hosting for the Nakama Network web interface.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

from aiohttp import web
from sqlalchemy import select

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
    """Parse HTTP Range header into valid (start, end) byte offsets."""
    if not range_header or not range_header.startswith("bytes="):
        return 0, total_size - 1

    range_val = range_header.replace("bytes=", "").strip()
    parts = range_val.split("-")
    start = int(parts[0]) if parts[0] else 0
    end = int(parts[1]) if len(parts) > 1 and parts[1] else total_size - 1

    start = max(0, min(start, total_size - 1))
    end = max(start, min(end, total_size - 1))
    return start, end


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


async def handle_catalog(request: web.Request) -> web.Response:
    """GET /api/catalog - Grouped anime catalog with cover art and latest episodes."""
    async with async_session() as session:
        files = list((await session.execute(select(File).order_by(File.created_at.desc()))).scalars().all())

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
        "status": meta["status"],
        "total_episodes": len(episodes),
        "episodes": episodes,
    })


async def handle_stream(request: web.Request) -> web.StreamResponse:
    """GET /stream/{file_id} - HTTP 206 byte-range streaming for video player."""
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
        raise web.HTTPFound(location=f"https://t.me/NakamaNetworkbot?start=file_{f.id}")

    range_header = request.headers.get("Range")
    start, end = parse_byte_range(range_header, total_size)
    chunk_length = end - start + 1

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

    raise web.HTTPFound(location=f"https://t.me/NakamaNetworkbot?start=file_{f.id}")


# --- Static / SPA Handler ----------------------------------------------------


async def serve_index(request: web.Request) -> web.FileResponse:
    index = WEB_ROOT / "index.html"
    if index.exists():
        return web.FileResponse(index)
    return web.Response(text="Nakama Network Gateway running.", content_type="text/plain")


# --- App Factory --------------------------------------------------------------


async def on_startup(app: web.Application) -> None:
    await init_db()
    logger.info("Database initialized.")


def create_app() -> web.Application:
    app = web.Application()
    app.on_startup.append(on_startup)

    # API Routes
    app.router.add_get("/api/catalog", handle_catalog)
    app.router.add_get("/api/series/{name}", handle_series_detail)
    app.router.add_get("/stream/{file_id}", handle_stream)

    # Static assets
    assets_dir = WEB_ROOT / "assets"
    if assets_dir.exists():
        app.router.add_static("/assets/", path=str(assets_dir), name="assets")

    # SPA Fallback
    app.router.add_get("/", serve_index)
    app.router.add_get("/{path:.*}", serve_index)

    return app


def main() -> None:
    app = create_app()
    logger.info("Nakama Network streaming server starting on http://127.0.0.1:8080")
    web.run_app(app, host="127.0.0.1", port=8080, print=None)


if __name__ == "__main__":
    main()
