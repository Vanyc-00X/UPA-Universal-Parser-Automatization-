"""Пакет браузерного движка: Playwright, снапшоты, обрезка DOM."""

from app.crawler.browser import (  # noqa: F401
    BrowserSession,
    NetworkEntry,
    RawSnapshot,
    browser_session,
    capture_page,
    hash_html,
    screenshot_to_data_uri,
)
from app.crawler.dom import TrimResult, estimate_tokens, trim_html  # noqa: F401

__all__ = [
    "BrowserSession",
    "NetworkEntry",
    "RawSnapshot",
    "TrimResult",
    "browser_session",
    "capture_page",
    "estimate_tokens",
    "hash_html",
    "screenshot_to_data_uri",
    "trim_html",
]
