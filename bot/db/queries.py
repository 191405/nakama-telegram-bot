"""Database query functions — all DB logic lives here."""

from __future__ import annotations

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import AnimeRequest, Category, Download, File, TriviaRecord, User, Watchlist
from bot.utils.episodes import extract_episode_number, extract_series_name


# ─── Users ────────────────────────────────────────────────────────────────────


async def upsert_user(
    session: AsyncSession,
    user_id: int,
    username: str | None,
    full_name: str,
) -> User:
    """Create or update a user record with concurrency safety."""
    try:
        user = await session.get(User, user_id)
        if user is None:
            user = User(user_id=user_id, username=username, full_name=full_name)
            session.add(user)
        else:
            user.username = username
            user.full_name = full_name
        await session.commit()
        return user
    except Exception:
        await session.rollback()
        # Fallback fetch in case another concurrent request created the record
        user = await session.get(User, user_id)
        if user is not None:
            user.username = username
            user.full_name = full_name
            try:
                await session.commit()
            except Exception:
                await session.rollback()
            return user
        return User(user_id=user_id, username=username, full_name=full_name)


async def get_user(session: AsyncSession, user_id: int) -> User | None:
    """Get a user by Telegram ID."""
    return await session.get(User, user_id)


async def set_banned(session: AsyncSession, user_id: int, banned: bool) -> bool:
    """Ban or unban a user. Returns True if the user exists."""
    user = await session.get(User, user_id)
    if user is None:
        return False
    user.is_banned = banned
    await session.commit()
    return True


async def count_users(session: AsyncSession) -> int:
    """Count total users."""
    result = await session.execute(select(func.count(User.user_id)))
    return result.scalar_one()


async def get_all_user_ids(session: AsyncSession) -> list[int]:
    """Get all non-banned user IDs (for broadcast)."""
    result = await session.execute(
        select(User.user_id).where(User.is_banned == False)  # noqa: E712
    )
    return list(result.scalars().all())


# ─── Categories ───────────────────────────────────────────────────────────────


async def create_category(
    session: AsyncSession,
    name: str,
    emoji: str = "📁",
    description: str | None = None,
) -> Category:
    """Create a new category."""
    cat = Category(name=name, emoji=emoji, description=description)
    session.add(cat)
    await session.commit()
    return cat


async def get_all_categories(session: AsyncSession) -> list[Category]:
    """Get all categories ordered by sort_order."""
    result = await session.execute(
        select(Category).order_by(Category.sort_order, Category.name)
    )
    return list(result.scalars().all())


async def get_category(session: AsyncSession, category_id: int) -> Category | None:
    """Get a single category."""
    return await session.get(Category, category_id)


async def delete_category(session: AsyncSession, category_id: int) -> bool:
    """Delete a category. Returns True if it existed."""
    result = await session.execute(
        delete(Category).where(Category.id == category_id)
    )
    await session.commit()
    return result.rowcount > 0


# ─── Files ────────────────────────────────────────────────────────────────────


async def save_file(
    session: AsyncSession,
    file_name: str,
    file_id: str,
    file_unique_id: str,
    file_type: str,
    file_size: int,
    uploaded_by: int | None = None,
    category_id: int | None = None,
    caption: str | None = None,
) -> File:
    """Save a new file record."""
    # Ensure uploaded_by is a valid user ID or None (channels have negative IDs)
    valid_uploader = uploaded_by if (uploaded_by and uploaded_by > 0) else None

    f = File(
        file_name=file_name,
        file_id=file_id,
        file_unique_id=file_unique_id,
        file_type=file_type,
        file_size=file_size,
        uploaded_by=valid_uploader,
        category_id=category_id,
        caption=caption,
    )
    session.add(f)
    await session.commit()
    return f


async def get_file(session: AsyncSession, file_id: int) -> File | None:
    """Get a file by its database ID."""
    return await session.get(File, file_id)


async def get_file_by_telegram_id(
    session: AsyncSession, telegram_file_id: str
) -> File | None:
    """Get a file by its Telegram file_id (to avoid duplicates)."""
    result = await session.execute(
        select(File).where(File.file_id == telegram_file_id)
    )
    return result.scalar_one_or_none()


async def search_files(
    session: AsyncSession, query: str, limit: int = 50, offset: int = 0
) -> list[File]:
    """Smart search files by name and caption (case-insensitive ILIKE)."""
    clean_query = query.strip()
    if not clean_query:
        return []

    # 1. Exact substring match in name or caption
    exact_stmt = (
        select(File)
        .where(
            or_(
                File.file_name.ilike(f"%{clean_query}%"),
                File.caption.ilike(f"%{clean_query}%"),
            )
        )
        .order_by(File.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    exact_res = (await session.execute(exact_stmt)).scalars().all()
    if exact_res:
        return list(exact_res)

    # 2. Multi-word search: all keywords must match name or caption
    keywords = [w for w in clean_query.split() if len(w) > 1]
    if len(keywords) > 1:
        conditions = []
        for kw in keywords:
            if kw.isdigit() and len(kw) == 1:
                kw_cond = or_(
                    File.file_name.ilike(f"%{kw}%"),
                    File.file_name.ilike(f"%0{kw}%"),
                    File.caption.ilike(f"%{kw}%"),
                    File.caption.ilike(f"%0{kw}%"),
                )
            else:
                kw_cond = or_(
                    File.file_name.ilike(f"%{kw}%"),
                    File.caption.ilike(f"%{kw}%"),
                )
            conditions.append(kw_cond)

        multi_stmt = (
            select(File)
            .where(and_(*conditions))
            .order_by(File.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        multi_res = (await session.execute(multi_stmt)).scalars().all()
        if multi_res:
            return list(multi_res)

    return []


async def get_files_by_category(
    session: AsyncSession, category_id: int, limit: int = 50, offset: int = 0
) -> list[File]:
    """Get all files in a category."""
    result = await session.execute(
        select(File)
        .where(File.category_id == category_id)
        .order_by(File.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def get_latest_files(session: AsyncSession, limit: int = 10) -> list[File]:
    """Get the most recently uploaded files."""
    result = await session.execute(
        select(File).order_by(File.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def get_popular_files(session: AsyncSession, limit: int = 10) -> list[File]:
    """Get files with the highest download count."""
    result = await session.execute(
        select(File).order_by(File.download_count.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def delete_file(session: AsyncSession, file_db_id: int) -> bool:
    """Delete a file by database ID. Returns True if it existed."""
    result = await session.execute(delete(File).where(File.id == file_db_id))
    await session.commit()
    return result.rowcount > 0


async def count_files(session: AsyncSession) -> int:
    """Count total files."""
    result = await session.execute(select(func.count(File.id)))
    return result.scalar_one()


async def count_files_in_category(
    session: AsyncSession, category_id: int
) -> int:
    """Count files in a specific category."""
    result = await session.execute(
        select(func.count(File.id)).where(File.category_id == category_id)
    )
    return result.scalar_one()


# ─── Downloads ────────────────────────────────────────────────────────────────


async def record_download(
    session: AsyncSession, user_id: int, file_db_id: int
) -> None:
    """Record a download and increment the file's counter."""
    dl = Download(user_id=user_id, file_id=file_db_id)
    session.add(dl)
    await session.execute(
        update(File)
        .where(File.id == file_db_id)
        .values(download_count=File.download_count + 1)
    )
    await session.commit()


async def count_downloads(session: AsyncSession) -> int:
    """Count total downloads."""
    result = await session.execute(select(func.count(Download.id)))
    return result.scalar_one()


# ─── Series & Episodes ────────────────────────────────────────────────────────


async def find_adjacent_episodes(
    session: AsyncSession, current_file: File
) -> tuple[File | None, File | None]:
    """Find the previous and next episodes relative to current_file."""
    if current_file.category_id:
        stmt = (
            select(File)
            .where(File.category_id == current_file.category_id)
            .order_by(File.id.asc())
        )
        siblings = list((await session.execute(stmt)).scalars().all())
    else:
        series_name = extract_series_name(current_file.file_name)
        stmt = (
            select(File)
            .where(File.file_name.ilike(f"%{series_name}%"))
            .order_by(File.id.asc())
        )
        siblings = list((await session.execute(stmt)).scalars().all())

    if len(siblings) <= 1:
        return None, None

    def sort_key(f: File):
        ep = extract_episode_number(f.file_name)
        return (ep is None, ep or 0, f.file_name)

    siblings.sort(key=sort_key)

    try:
        idx = [f.id for f in siblings].index(current_file.id)
    except ValueError:
        return None, None

    prev_file = siblings[idx - 1] if idx > 0 else None
    next_file = siblings[idx + 1] if idx + 1 < len(siblings) else None
    return prev_file, next_file


async def get_series_files(
    session: AsyncSession, file_or_cat: File | int
) -> list[File]:
    """Get all episodes of a series sorted in viewing order."""
    if isinstance(file_or_cat, int):
        stmt = select(File).where(File.category_id == file_or_cat)
    else:
        current_file = file_or_cat
        if current_file.category_id:
            stmt = select(File).where(File.category_id == current_file.category_id)
        else:
            series = extract_series_name(current_file.file_name)
            stmt = select(File).where(File.file_name.ilike(f"%{series}%"))

    files = list((await session.execute(stmt)).scalars().all())

    def sort_key(f: File):
        ep = extract_episode_number(f.file_name)
        return (ep is None, ep or 0, f.file_name)

    files.sort(key=sort_key)
    return files


async def get_all_searchable_titles(session: AsyncSession) -> list[str]:
    """Get all series names, file names, and category names for fuzzy matching."""
    file_names = (await session.execute(select(File.file_name))).scalars().all()
    cat_names = (await session.execute(select(Category.name))).scalars().all()

    titles: set[str] = set(cat_names)
    for fn in file_names:
        titles.add(fn)
        cleaned_series = extract_series_name(fn)
        if cleaned_series:
            titles.add(cleaned_series)

    return list(titles)


# ─── Requests ─────────────────────────────────────────────────────────────────


async def create_request(
    session: AsyncSession, user_id: int, anime_title: str
) -> AnimeRequest:
    """Create a new user anime request."""
    req = AnimeRequest(user_id=user_id, anime_title=anime_title.strip())
    session.add(req)
    await session.commit()
    return req


async def get_pending_requests(
    session: AsyncSession, limit: int = 20
) -> list[AnimeRequest]:
    """Get recent pending anime requests."""
    stmt = (
        select(AnimeRequest)
        .where(AnimeRequest.status == "pending")
        .order_by(AnimeRequest.created_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_request(
    session: AsyncSession, request_id: int
) -> AnimeRequest | None:
    """Get an anime request by ID."""
    return await session.get(AnimeRequest, request_id)


async def fulfill_request(
    session: AsyncSession, request_id: int
) -> AnimeRequest | None:
    """Mark an anime request as fulfilled."""
    req = await session.get(AnimeRequest, request_id)
    if req:
        req.status = "fulfilled"
        await session.commit()
    return req


# ─── Statistics & Community Feed ─────────────────────────────────────────────


async def get_community_stats(session: AsyncSession) -> dict:
    """Get live overview statistics for the community banner."""
    user_count = (await session.execute(select(func.count(User.user_id)))).scalar_one() or 0
    file_count = (await session.execute(select(func.count(File.id)))).scalar_one() or 0
    dl_count = (await session.execute(select(func.coalesce(func.sum(File.download_count), 0)))).scalar_one() or 0
    cat_count = (await session.execute(select(func.count(Category.id)))).scalar_one() or 0
    return {
        "total_users": user_count,
        "total_files": file_count,
        "total_downloads": dl_count,
        "total_categories": cat_count,
    }


async def get_admin_detailed_stats(session: AsyncSession) -> dict:
    """Detailed metrics for the admin /stats dashboard."""
    user_count = (await session.execute(select(func.count(User.user_id)))).scalar_one() or 0
    banned_count = (
        await session.execute(select(func.count(User.user_id)).where(User.is_banned == True))  # noqa: E712
    ).scalar_one() or 0
    file_count = (await session.execute(select(func.count(File.id)))).scalar_one() or 0
    total_size = (await session.execute(select(func.coalesce(func.sum(File.file_size), 0)))).scalar_one() or 0
    dl_count = (await session.execute(select(func.coalesce(func.sum(File.download_count), 0)))).scalar_one() or 0
    pending_requests = (
        await session.execute(select(func.count(AnimeRequest.id)).where(AnimeRequest.status == "pending"))
    ).scalar_one() or 0

    top_files_stmt = select(File).order_by(File.download_count.desc()).limit(5)
    top_files = list((await session.execute(top_files_stmt)).scalars().all())

    return {
        "total_users": user_count,
        "banned_users": banned_count,
        "total_files": file_count,
        "total_size": total_size,
        "total_downloads": dl_count,
        "pending_requests": pending_requests,
        "top_files": top_files,
    }


async def get_user_profile(session: AsyncSession, user_id: int) -> dict | None:
    """Get user profile data, download history, and continue watching info."""
    user = await session.get(User, user_id)
    if not user:
        return None

    dl_count = (
        await session.execute(select(func.count(Download.id)).where(Download.user_id == user_id))
    ).scalar_one() or 0

    # Determine Nakama Rank
    if dl_count >= 50:
        rank = "👑 Pirate King"
    elif dl_count >= 30:
        rank = "⚔️ Yonko Commander"
    elif dl_count >= 15:
        rank = "🔥 Straw Hat Nakama"
    elif dl_count >= 5:
        rank = "🗡️ East Blue Swordsman"
    else:
        rank = "🧭 Cabin Boy / Rookie"

    # Find the latest download for "Continue Watching"
    last_dl_stmt = (
        select(Download)
        .where(Download.user_id == user_id)
        .order_by(Download.downloaded_at.desc())
        .limit(1)
    )
    last_dl = (await session.execute(last_dl_stmt)).scalar_one_or_none()

    continue_file = None
    next_file = None
    if last_dl:
        last_file = await session.get(File, last_dl.file_id)
        if last_file:
            continue_file = last_file
            # Check if there is a next episode in the series
            _, next_f = await find_adjacent_episodes(session, last_file)
            next_file = next_f

    return {
        "user": user,
        "downloads": dl_count,
        "rank": rank,
        "continue_file": continue_file,
        "next_file": next_file,
    }


async def get_all_series_summaries(session: AsyncSession) -> list[dict]:
    """Get grouped summaries of all distinct anime series for Channel Feed."""
    files = list((await session.execute(select(File).order_by(File.created_at.desc()))).scalars().all())
    series_dict: dict[str, list[File]] = {}
    for f in files:
        raw_name = extract_series_name(f.file_name) or f.file_name
        s_name = raw_name.title()
        series_dict.setdefault(s_name, []).append(f)

    summaries = []
    for name, f_list in series_dict.items():
        f_list.sort(key=lambda x: (extract_episode_number(x.file_name) is None, extract_episode_number(x.file_name) or 0))
        summaries.append({
            "name": name,
            "total_episodes": len(f_list),
            "files": f_list,
            "sample_file": f_list[0],
            "latest_file": f_list[-1],
            "total_downloads": sum(x.download_count for x in f_list),
        })
    return summaries


# ─── Persona & XP Management ──────────────────────────────────────────────────


async def set_user_persona(session: AsyncSession, user_id: int, persona: str) -> bool:
    """Update active conversational character persona for a user."""
    user = await session.get(User, user_id)
    if not user:
        return False
    user.persona = persona.lower().strip()
    await session.commit()
    return True


async def get_user_persona(session: AsyncSession, user_id: int) -> str:
    """Get active persona for user."""
    user = await session.get(User, user_id)
    return (user.persona if user and user.persona else "nakama").lower()


async def add_user_xp(session: AsyncSession, user_id: int, points: int) -> int:
    """Award XP bounty points to a user and return total XP."""
    user = await session.get(User, user_id)
    if not user:
        return 0
    user.xp = (user.xp or 0) + points
    await session.commit()
    return user.xp


async def get_leaderboard(session: AsyncSession, limit: int = 10) -> list[dict]:
    """Get top members ranked by XP bounty and downloads in a single query."""
    stmt = (
        select(User, func.count(Download.id).label("dl_count"))
        .outerjoin(Download, Download.user_id == User.user_id)
        .where(User.is_banned == False)  # noqa: E712
        .group_by(User.user_id)
        .order_by(User.xp.desc(), User.last_active.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()

    results = []
    for u, dl_count in rows:
        xp = u.xp or 0
        if xp >= 1000:
            rank = "👑 Pirate King"
        elif xp >= 600:
            rank = "⚔️ Yonko Commander"
        elif xp >= 300:
            rank = "🔥 Straw Hat Nakama"
        elif xp >= 100:
            rank = "🗡️ East Blue Swordsman"
        else:
            rank = "🧭 Cabin Boy"

        results.append({
            "user_id": u.user_id,
            "full_name": u.full_name or "Anonymous Nakama",
            "username": u.username,
            "xp": xp,
            "downloads": dl_count or 0,
            "rank": rank,
        })
    return results


# ─── Watchlist & Bookmarking ──────────────────────────────────────────────────


async def add_to_watchlist(
    session: AsyncSession, user_id: int, series_name: str, status: str = "watching"
) -> Watchlist:
    """Add or update an anime series in a user's personal watchlist."""
    clean_name = series_name.strip()
    stmt = select(Watchlist).where(
        Watchlist.user_id == user_id,
        Watchlist.series_name.ilike(clean_name),
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing:
        existing.status = status
        await session.commit()
        return existing

    item = Watchlist(user_id=user_id, series_name=clean_name, status=status)
    session.add(item)
    await session.commit()
    return item


async def remove_from_watchlist(
    session: AsyncSession, user_id: int, series_name: str
) -> bool:
    """Remove a series from the user's watchlist."""
    clean_name = series_name.strip()
    stmt = select(Watchlist).where(
        Watchlist.user_id == user_id,
        Watchlist.series_name.ilike(clean_name),
    )
    item = (await session.execute(stmt)).scalar_one_or_none()
    if item:
        await session.delete(item)
        await session.commit()
        return True
    return False


async def get_user_watchlist(
    session: AsyncSession, user_id: int
) -> list[Watchlist]:
    """Get all watchlist items for a user."""
    stmt = (
        select(Watchlist)
        .where(Watchlist.user_id == user_id)
        .order_by(Watchlist.created_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def update_watchlist_status(
    session: AsyncSession, user_id: int, series_name: str, new_status: str
) -> bool:
    """Update status of a watchlist item (e.g. watching -> completed)."""
    clean_name = series_name.strip()
    stmt = select(Watchlist).where(
        Watchlist.user_id == user_id,
        Watchlist.series_name.ilike(clean_name),
    )
    item = (await session.execute(stmt)).scalar_one_or_none()
    if item:
        item.status = new_status
        await session.commit()
        return True
    return False


# ─── Daily Trivia & Gamification ──────────────────────────────────────────────


async def record_trivia_answer(
    session: AsyncSession,
    user_id: int,
    question_hash: str,
    is_correct: bool,
    points: int,
) -> None:
    """Record an answered trivia question."""
    record = TriviaRecord(
        user_id=user_id,
        question_hash=question_hash,
        is_correct=is_correct,
        points_awarded=points,
    )
    session.add(record)
    if is_correct and points > 0:
        await add_user_xp(session, user_id, points)
    await session.commit()


async def has_answered_question(
    session: AsyncSession, user_id: int, question_hash: str
) -> bool:
    """Check if user has already answered this question hash."""
    stmt = select(TriviaRecord).where(
        TriviaRecord.user_id == user_id,
        TriviaRecord.question_hash == question_hash,
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


