"""Проверка готовности браузера: Playwright Chromium или системный Chrome/Edge."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from app.core.config import REPO_ROOT, Settings


def browsers_dir(settings: Settings | None = None) -> Path:
    raw = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if raw:
        return Path(raw)
    if settings is not None:
        return settings.data_dir / "_pw-browsers"
    return REPO_ROOT / "data" / "_pw-browsers"


def chromium_installed(settings: Settings | None = None) -> bool:
    directory = browsers_dir(settings)
    if not directory.is_dir():
        return False
    return any(directory.glob("chromium-*")) or any(
        directory.glob("chromium_headless_shell-*")
    )


def system_channels() -> list[str]:
    found: list[str] = []
    candidates = {
        "chrome": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            "/usr/bin/google-chrome",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
        ],
        "msedge": [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            "/usr/bin/microsoft-edge",
        ],
    }
    for channel, paths in candidates.items():
        if any(Path(path).is_file() for path in paths):
            found.append(channel)
            continue
        which = shutil.which(channel) or shutil.which(
            "google-chrome" if channel == "chrome" else "microsoft-edge"
        )
        if which:
            found.append(channel)
    return found


def browser_status(settings: Settings) -> dict[str, Any]:
    chromium = chromium_installed(settings)
    channels = system_channels()
    ready = chromium or bool(channels)
    return {
        "ready": ready,
        "chromium_installed": chromium,
        "browsers_path": str(browsers_dir(settings)),
        "system_channels": channels,
        "fallback": "chrome/msedge" if channels and not chromium else None,
        "install_hint": (
            None
            if ready
            else "python scripts/install_chromium.py  или установите Google Chrome / Edge"
        ),
        "headless": settings.browser_headless,
    }
