"""Nakama Network Web API and Media Streaming Gateway.

Provides:
- REST API for catalog browsing, series detail, episode listing, and search.
- HTTP Range (206 Partial Content) streaming for browser video playback.
- Static hosting for the single-page web application.
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


# --- Utility -----------------------------------------------------------------

def parse_byte_range(range_header: str | None, total_size: int) -> tuple[int, int]:
    """Parse an HTTP Range header into (start, end) byte offsets."""
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
    """Remove HTML tags from a string."""
    return re.sub(r"<[^>]+>", "", text or "")


async def _enrich_with_anilist(name: str) -> dict[str, Any]:
    """Fetch AniList metadata for a series name and return a flat dict."""
    out: dict[str, Any] = {
        "cover_image": None,
        "banner_image": None,
        "score": None,
        "anilist_status": None,
        "genres": [],
        "year": None,
        "total_episodes_anilist": None,
        "description": "",
        "title_english": None,
        "title_romaji": None,
    }
    try:
        meta = await fetch_anime_info(name)
        if not meta:
            return out
        covers = meta.get("coverImage") or {}
        out["cover_image"] = covers.get("extraLarge") or covers.get("large")
        out["banner_image"] = meta.get("bannerImage")
        out["score"] = meta.get("averageScore")
        out["anilist_status"] = meta.get("status")
        out["genres"] = (meta.get("genres") or [])[:4]
        out["year"] = meta.get("seasonYear")
        out["total_episodes_anilist"] = meta.get("episodes")
        out["description"] = strip_html(meta.get("description") or "")
        titles = meta.get("title") or {}
        out["title_english"] = titles.get("english")
        out["title_romaji"] = titles.get("romaji")
    except Exception:
        pass
    return out


# --- API Handlers ------------------------------------------------------------


async def handle_catalog(request: web.Request) -> web.Response:
    """GET /api/catalog - All series with AniList poster art and metadata."""
    async with async_session() as session:
        summaries = await queries.get_all_series_summaries(session)

    async def build_entry(s: dict) -> dict:
        name = s["name"]
        sample = s.get("sample_file")
        latest = s.get("latest_file") or sample
        meta = await _enrich_with_anilist(name)
        status = "COMPLETED" if meta["anilist_status"] == "FINISHED" else "ONGOING"
        return {
            "name": name,
            "display_title": meta["title_english"] or meta["title_romaji"] or name,
            "total_episodes": s["total_episodes"],
            "total_downloads": s["total_downloads"],
            "sample_file_id": sample.id if sample else None,
            "latest_file_id": latest.id if latest else None,
            "cover_image": meta["cover_image"],
            "banner_image": meta["banner_image"],
            "score": meta["score"],
            "status": status,
            "genres": meta["genres"],
            "year": meta["year"],
        }

    results = await asyncio.gather(*[build_entry(s) for s in summaries])
    return web.json_response({"status": "ok", "count": len(results), "catalog": list(results)})


async def handle_series(request: web.Request) -> web.Response:
    """GET /api/series/{name} - Full series detail with episode list."""
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

    files.sort(key=lambda x: (
        extract_episode_number(x.file_name) is None,
        extract_episode_number(x.file_name) or 0,
    ))

    meta = await _enrich_with_anilist(series_name)

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
        })

    return web.json_response({
        "status": "ok",
        "series": series_name,
        "display_title": meta["title_english"] or meta["title_romaji"] or series_name,
        "cover_image": meta["cover_image"],
        "banner_image": meta["banner_image"],
        "description": meta["description"],
        "genres": meta["genres"],
        "score": meta["score"],
        "year": meta["year"],
        "anilist_status": meta["anilist_status"],
        "total_episodes_anilist": meta["total_episodes_anilist"],
        "total_episodes": len(episodes),
        "episodes": episodes,
    })


async def handle_search(request: web.Request) -> web.Response:
    """GET /api/search?q=... - Search across file names."""
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
        })

    return web.json_response({"status": "ok", "query": q, "results": results})


async def handle_latest(request: web.Request) -> web.Response:
    """GET /api/latest - Most recently added files."""
    limit = int(request.query.get("limit", "12"))
    async with async_session() as session:
        files = await queries.get_latest_files(session, limit=limit)

    results = []
    for f in files:
        results.append({
            "id": f.id,
            "file_name": f.file_name,
            "series": extract_series_name(f.file_name),
            "episode": extract_episode_number(f.file_name),
            "size": f.human_size,
            "downloads": f.download_count,
        })

    return web.json_response({"status": "ok", "results": results})


async def handle_popular(request: web.Request) -> web.Response:
    """GET /api/popular - Most downloaded files."""
    limit = int(request.query.get("limit", "12"))
    async with async_session() as session:
        files = await queries.get_popular_files(session, limit=limit)

    results = []
    for f in files:
        results.append({
            "id": f.id,
            "file_name": f.file_name,
            "series": extract_series_name(f.file_name),
            "episode": extract_episode_number(f.file_name),
            "size": f.human_size,
            "downloads": f.download_count,
        })

    return web.json_response({"status": "ok", "results": results})


async def handle_stream(request: web.Request) -> web.StreamResponse:
    """GET /stream/{file_id} - HTTP 206 byte-range streaming for video playback."""
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


# --- Static / SPA serving ----------------------------------------------------


async def serve_index(request: web.Request) -> web.FileResponse:
    index = WEB_ROOT / "index.html"
    if index.exists():
        return web.FileResponse(index)
    return web.Response(text="Nakama Network gateway is running.", content_type="text/plain")


# --- App Factory --------------------------------------------------------------


async def on_startup(app: web.Application) -> None:
    await init_db()
    logger.info("Database initialised.")


def create_app() -> web.Application:
    app = web.Application()
    app.on_startup.append(on_startup)

    # JSON API
    app.router.add_get("/api/catalog", handle_catalog)
    app.router.add_get("/api/series/{name}", handle_series)
    app.router.add_get("/api/search", handle_search)
    app.router.add_get("/api/latest", handle_latest)
    app.router.add_get("/api/popular", handle_popular)

    # Streaming
    app.router.add_get("/stream/{file_id}", handle_stream)

    # Static assets
    assets_dir = WEB_ROOT / "assets"
    if assets_dir.exists():
        app.router.add_static("/assets/", path=str(assets_dir), name="assets")

    # SPA fallback
    app.router.add_get("/", serve_index)
    app.router.add_get("/{path:.*}", serve_index)

    return app


def main() -> None:
    app = create_app()
    logger.info("Nakama Network gateway starting on http://127.0.0.1:8080")
    web.run_app(app, host="127.0.0.1", port=8080, print=None)


if __name__ == "__main__":
    main()
