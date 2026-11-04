"""Pagination helper for file lists."""

from __future__ import annotations


def paginate(items: list, page: int, page_size: int) -> tuple[list, bool, bool]:
    """Return a page of items plus whether prev/next pages exist.

    Returns
    -------
    (page_items, has_prev, has_next)
    """
    start = page * page_size
    end = start + page_size
    page_items = items[start:end]
    has_prev = page > 0
    has_next = end < len(items)
    return page_items, has_prev, has_next
