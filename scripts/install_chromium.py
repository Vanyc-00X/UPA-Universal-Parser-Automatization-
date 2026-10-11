"""Устойчивая установка Playwright Chromium с зеркалами и проверкой fallback.

Порядок:
1. Уже установленный Chromium в PLAYWRIGHT_BROWSERS_PATH
2. Обычный ``playwright install chromium``
3. Повтор с зеркалами (npmmirror / playwright.azureedge.net CDN)
4. Проверка системного Chrome / Edge (channel fallback в UPA)

Код выхода: 0 — браузер доступен; 1 — нет ни Chromium, ни системного канала.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BROWSERS = REPO_ROOT / "data" / "_pw-browsers"

# Зеркала скачивания браузеров Playwright (актуально при блокировке CDN).
MIRRORS = (
    "",  # официальный хост Playwright
    "https://npmmirror.com/mirrors/playwright",
    "https://cdn.npmmirror.com/binaries/playwright",
    "https://playwright.azureedge.net",
)


def _browsers_path() -> Path:
    raw = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    return Path(raw) if raw else DEFAULT_BROWSERS


def chromium_installed(browsers: Path) -> bool:
    if not browsers.is_dir():
        return False
    return any(browsers.glob("chromium-*")) or any(browsers.glob("chromium_headless_shell-*"))


def system_browser_available() -> list[str]:
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


def run_install(python: str, *, download_host: str | None) -> int:
    env = os.environ.copy()
    if download_host:
        env["PLAYWRIGHT_DOWNLOAD_HOST"] = download_host.rstrip("/")
    print(f"==> playwright install chromium  host={download_host or 'default'}")
    completed = subprocess.run(
        [python, "-m", "playwright", "install", "chromium"],
        env=env,
        check=False,
    )
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Интерпретатор с установленным playwright",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ставить Chromium даже если каталог уже есть",
    )
    args = parser.parse_args(argv)

    browsers = _browsers_path()
    browsers.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(browsers))

    if chromium_installed(browsers) and not args.force:
        print(f"OK Chromium уже есть: {browsers}")
        return 0

    last_code = 1
    for mirror in MIRRORS:
        last_code = run_install(args.python, download_host=mirror or None)
        if last_code == 0 and chromium_installed(browsers):
            print(f"OK Chromium установлен через host={mirror or 'default'}")
            return 0

    channels = system_browser_available()
    if channels:
        print(
            "WARN Playwright Chromium не скачался, но найден системный браузер: "
            + ", ".join(channels)
            + ". UPA использует channel fallback (chrome/msedge)."
        )
        return 0

    print(
        "ERROR Не удалось установить Chromium и не найден Chrome/Edge.\n"
        "  1) Повторите: python scripts/install_chromium.py\n"
        "  2) Или установите Google Chrome / Microsoft Edge\n"
        f"  3) Последний код playwright install: {last_code}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
