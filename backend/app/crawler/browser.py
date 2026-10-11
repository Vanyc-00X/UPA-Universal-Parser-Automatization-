"""Движок браузера: Playwright, снятие снапшота страницы.

Модуль отвечает за Этап 1 целиком: открыть URL в реальном браузере, дождаться
сети и JS, закрыть мешающие баннеры, а затем снять «слепок» страницы — DOM,
скриншоты, сетевые запросы и состояние хранилища. Всё, что делает этот модуль,
детерминировано и воспроизводимо: снапшот можно переснять из кэша без обращения
к сайту.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings
from app.core.errors import BrowserError, SiteUnreachableError
from app.core.logging import get_logger
from app.crawler.dom import TrimResult, estimate_tokens, trim_html

log = get_logger(__name__)

# Селекторы типовых баннеров о cookie. Список сознательно короткий: мы закрываем
# только очевидные случаи и не воюем с сайтом за каждый пиксель.
COOKIE_SELECTORS: tuple[str, ...] = (
    "#onetrust-accept-btn-handler",
    "button#onetrust-accept-btn-handler",
    "#accept-cookie-notification",
    "button[data-testid='cookie-accept']",
    "button[data-cy='accept-cookies']",
    "button[aria-label*='Accept' i]",
    "button[aria-label*='Принять' i]",
    "[id*='cookie' i] button[class*='accept' i]",
    "[class*='cookie' i] button[class*='accept' i]",
    "[class*='consent' i] button",
    "button:has-text('Принять все')",
    "button:has-text('Accept all')",
    "button:has-text('Согласен')",
    "button:has-text('Хорошо')",
)

# Типы ресурсов, тела которых сохраняются: именно они чаще всего содержат данные.
DATA_RESOURCE_TYPES = {"xhr", "fetch"}

# Если Playwright Chromium не скачан, пробуем системные браузеры (частый случай в РФ/корп. сети).
_CHANNEL_FALLBACKS = ("chrome", "msedge")


async def launch_chromium(
    playwright: Any,
    settings: Settings,
    *,
    headless: bool | None = None,
) -> Any:
    """Запускает Chromium Playwright либо системный Chrome/Edge."""
    launch_args: dict[str, Any] = {
        "headless": settings.browser_headless if headless is None else headless
    }
    try:
        browser = await playwright.chromium.launch(**launch_args)
        log.info("browser.engine", engine="playwright-chromium")
        return browser
    except Exception as primary:  # noqa: BLE001
        primary_msg = str(primary)
        missing = "Executable doesn't exist" in primary_msg or "playwright install" in primary_msg
        if not missing:
            raise

        last_error = primary
        for channel in _CHANNEL_FALLBACKS:
            try:
                browser = await playwright.chromium.launch(channel=channel, **launch_args)
                log.info("browser.engine", engine=channel, fallback=True)
                return browser
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue

        raise BrowserError(
            "Браузер Chromium не установлен. Выполните: "
            "python -m playwright install chromium "
            "(или установите Google Chrome / Microsoft Edge)",
            details={"reason": str(last_error)},
        ) from last_error


# Обратная совместимость для внутренних вызовов.
_launch_chromium = launch_chromium


@dataclass
class NetworkEntry:
    """Один сетевой запрос страницы."""

    url: str
    method: str
    resource_type: str
    status: int | None = None
    mime: str | None = None
    size_bytes: int | None = None
    body: str | None = None
    body_truncated: bool = False
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data = {
            "url": self.url,
            "method": self.method,
            "resource_type": self.resource_type,
            "status": self.status,
            "mime": self.mime,
            "size_bytes": self.size_bytes,
            "body_truncated": self.body_truncated,
        }
        if self.body is not None:
            data["body"] = self.body
        if self.error:
            data["error"] = self.error
        return data

    @property
    def is_data_source(self) -> bool:
        """Похоже ли, что этот ответ содержит данные, а не разметку интерфейса."""
        if self.resource_type not in DATA_RESOURCE_TYPES or self.status != 200:
            return False
        return bool(self.mime) and "json" in self.mime


@dataclass
class RawSnapshot:
    """Сырой результат снятия снапшота, до сохранения в БД."""

    url: str
    final_url: str
    http_status: int | None
    title: str | None
    lang: str | None
    html: str
    dom_hash: str
    trimmed: TrimResult
    html_bytes: int
    screenshot: bytes | None = None
    screenshot_full: bytes | None = None
    network: list[NetworkEntry] = field(default_factory=list)
    storage_state: dict[str, Any] | None = None
    console_errors: list[str] = field(default_factory=list)
    blocked_requests: int = 0
    cookie_banner_closed: bool = False
    duration_ms: int = 0
    viewport: dict[str, int] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def data_sources(self) -> list[NetworkEntry]:
        """Ответы, из которых можно брать данные напрямую, без разбора HTML."""
        return [entry for entry in self.network if entry.is_data_source]

    def summary(self) -> dict[str, Any]:
        """Сводка для лога, метаданных снапшота и UI.

        Важно: ключ ``console_errors`` здесь — сам список сообщений, а не их
        количество (иначе он перетирает список в ``Snapshot.meta``).
        """
        return {
            "url": self.url,
            "final_url": self.final_url,
            "http_status": self.http_status,
            "title": self.title,
            "lang": self.lang,
            "html_bytes": self.html_bytes,
            "dom_hash": self.dom_hash,
            "network_requests": len(self.network),
            "data_sources": len(self.data_sources),
            "console_errors": list(self.console_errors),
            "console_errors_count": len(self.console_errors),
            "failed_requests": list(self.extra.get("failed_requests", [])),
            "blocked_requests": self.blocked_requests,
            "cookie_banner_closed": self.cookie_banner_closed,
            "viewport": dict(self.viewport),
            "duration_ms": self.duration_ms,
            **self.trimmed.stats.as_dict(),
        }


def hash_html(html: str) -> str:
    """Стабильный хэш DOM: ключ кэша и признак изменения вёрстки."""
    return hashlib.sha256(html.encode("utf-8")).hexdigest()[:32]


class BrowserSession:
    """Обёртка над Playwright, живущая в течение одной операции.

    Используется как асинхронный контекстный менеджер::

        async with BrowserSession(settings) as session:
            snapshot = await session.capture("https://example.com")
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None

    async def __aenter__(self) -> BrowserSession:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover — зависит от окружения
            raise BrowserError(
                'Playwright не установлен. Выполните: pip install -e ".[dev]" '
                "и python -m playwright install chromium",
                details={"reason": str(exc)},
            ) from exc

        self._playwright = await async_playwright().start()
        try:
            self._browser = await _launch_chromium(self._playwright, self.settings)
        except BrowserError:
            await self._stop_playwright()
            raise
        except Exception as exc:  # noqa: BLE001 — сообщение Playwright информативно
            await self._stop_playwright()
            message = str(exc)
            if "Executable doesn't exist" in message or "playwright install" in message:
                raise BrowserError(
                    "Браузер Chromium не установлен. Выполните: "
                    "python -m playwright install chromium "
                    "(или установите Google Chrome — UPA подхватит его автоматически)",
                    details={"reason": message},
                ) from exc
            raise BrowserError("Не удалось запустить браузер", details={"reason": message}) from exc

        context_options: dict[str, Any] = {
            "locale": self.settings.browser_locale,
            "viewport": {
                "width": self.settings.browser_viewport_width,
                "height": self.settings.browser_viewport_height,
            },
            "ignore_https_errors": True,
        }
        if self.settings.browser_user_agent:
            context_options["user_agent"] = self.settings.browser_user_agent

        self._context = await self._browser.new_context(**context_options)
        self._context.set_default_timeout(self.settings.browser_timeout_ms)
        self._context.set_default_navigation_timeout(self.settings.browser_timeout_ms)
        log.info("browser.started", headless=self.settings.browser_headless)
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        """Закрывает контекст, браузер и Playwright."""
        for closer, name in (
            (getattr(self._context, "close", None), "context"),
            (getattr(self._browser, "close", None), "browser"),
        ):
            if closer is None:
                continue
            try:
                await closer()
            except Exception as exc:  # noqa: BLE001 — закрытие не должно ломать операцию
                log.warning("browser.close_failed", target=name, error=str(exc))
        await self._stop_playwright()
        self._context = None
        self._browser = None

    async def _stop_playwright(self) -> None:
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception as exc:  # noqa: BLE001
                log.warning("browser.playwright_stop_failed", error=str(exc))
            self._playwright = None

    # --- Основная операция ---------------------------------------------------

    async def capture(self, url: str) -> RawSnapshot:
        """Открывает страницу и снимает снапшот.

        Исключения: :class:`SiteUnreachableError` (сайт не открылся) и
        :class:`BrowserError` (сбой движка или неверный URL).
        """
        from playwright.async_api import Error as PlaywrightError
        from playwright.async_api import TimeoutError as PlaywrightTimeout

        if self._context is None:
            raise BrowserError("Сессия браузера не инициализирована")

        started = time.monotonic()
        network: list[NetworkEntry] = []
        console_errors: list[str] = []
        failed_requests: list[str] = []

        page = await self._context.new_page()
        page.on("response", lambda response: _spawn_body_capture(response, network, self.settings))
        page.on("requestfailed", lambda request: _collect_failed_request(request, failed_requests))
        page.on("console", lambda message: _collect_console(message, console_errors))
        page.on("dialog", lambda dialog: _handle_dialog(dialog, self.settings))

        try:
            response = await page.goto(url, wait_until="domcontentloaded")
            await self._settle(page)
            banner_closed = (
                await self._dismiss_cookie_banners(page)
                if (self.settings.browser_dismiss_cookie_banners)
                else False
            )

            html = await page.content()
            title = await page.title()
            lang = await page.evaluate("() => document.documentElement.lang || null")
            final_url = page.url

            screenshot = await _safe_screenshot(page, full_page=False)
            screenshot_full = await _safe_screenshot(page, full_page=True)

            storage_state: dict[str, Any] | None = None
            try:
                storage_state = await self._context.storage_state()
            except Exception as exc:  # noqa: BLE001
                log.warning("browser.storage_state_failed", error=str(exc))

            # Даём фоновым задачам чтения тел ответов завершиться.
            await page.wait_for_timeout(150)
        except PlaywrightTimeout as exc:
            raise SiteUnreachableError(
                "Сайт не ответил за отведённое время",
                details={"url": url, "timeout_ms": self.settings.browser_timeout_ms},
            ) from exc
        except PlaywrightError as exc:
            message = str(exc)
            if "net::" in message or "ERR_" in message:
                raise SiteUnreachableError(
                    "Не удалось открыть сайт",
                    details={"url": url, "reason": message.splitlines()[0][:300]},
                ) from exc
            raise BrowserError(
                "Ошибка браузера при открытии страницы",
                details={"url": url, "reason": message[:300]},
            ) from exc
        finally:
            await page.close()

        trimmed = trim_html(html, max_tokens=self.settings.dom_max_tokens, base_url=final_url)
        duration_ms = int((time.monotonic() - started) * 1000)

        snapshot = RawSnapshot(
            url=url,
            final_url=final_url,
            http_status=response.status if response is not None else None,
            title=title or trimmed.title,
            lang=lang,
            html=html,
            dom_hash=hash_html(html),
            trimmed=trimmed,
            html_bytes=len(html.encode("utf-8")),
            screenshot=screenshot,
            screenshot_full=screenshot_full,
            network=network,
            storage_state=storage_state,
            console_errors=console_errors,
            blocked_requests=len([item for item in failed_requests if "ERR_BLOCKED" in item]),
            cookie_banner_closed=banner_closed,
            duration_ms=duration_ms,
            viewport={
                "width": self.settings.browser_viewport_width,
                "height": self.settings.browser_viewport_height,
            },
            extra={
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "trim": trimmed.stats.as_dict(),
                "meta": trimmed.meta,
                "failed_requests": failed_requests[:50],
            },
        )

        log.info("browser.snapshot_taken", **snapshot.summary())
        return snapshot

    # --- Вспомогательные шаги ------------------------------------------------

    async def _settle(self, page: Any) -> None:
        """Ждёт «тишины» в сети и даёт JS дорисовать страницу."""
        # networkidle достижим не всегда (опросы, вебсокеты) — это не ошибка.
        with contextlib.suppress(Exception):
            await page.wait_for_load_state("networkidle", timeout=self.settings.browser_settle_ms)
        await page.wait_for_timeout(self.settings.browser_settle_ms)

    async def _dismiss_cookie_banners(self, page: Any) -> bool:
        """Пытается закрыть баннер о cookie. Возвращает признак успеха."""
        for selector in COOKIE_SELECTORS:
            try:
                locator = page.locator(selector).first
                if await locator.count() == 0:
                    continue
                if not await locator.is_visible():
                    continue
                await locator.click(timeout=1500)
                await page.wait_for_timeout(300)
                log.info("browser.cookie_banner_closed", selector=selector)
                return True
            except Exception:  # noqa: BLE001 — селектор мог не подойти
                continue
        return False


# --- Обработчики событий Playwright -----------------------------------------


def _spawn_body_capture(response: Any, sink: list[NetworkEntry], settings: Settings) -> None:
    """Регистрирует ответ и, если он похож на источник данных, читает его тело."""
    import asyncio

    try:
        request = response.request
        entry = NetworkEntry(
            url=response.url,
            method=request.method,
            resource_type=request.resource_type,
            status=response.status,
            mime=(response.headers or {}).get("content-type"),
        )
    except Exception:  # noqa: BLE001 — ответ мог уже исчезнуть
        return

    sink.append(entry)
    if not entry.is_data_source:
        return
    # Чтение тела — асинхронная операция; событие приходит из синхронного колбэка.
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_read_body(response, entry, settings))


async def _read_body(response: Any, entry: NetworkEntry, settings: Settings) -> None:
    """Читает тело ответа с ограничением размера."""
    limit = settings.network_body_limit_kb * 1024
    try:
        body = await response.body()
    except Exception as exc:  # noqa: BLE001 — тело могло не сохраниться
        entry.error = f"body_unavailable: {type(exc).__name__}"
        return

    entry.size_bytes = len(body)
    if len(body) > limit:
        entry.body = body[:limit].decode("utf-8", errors="replace")
        entry.body_truncated = True
        return
    entry.body = body.decode("utf-8", errors="replace")


def _collect_console(message: Any, sink: list[str]) -> None:
    """Собирает ошибки консоли: они подсказывают, почему контента нет."""
    try:
        if message.type == "error" and len(sink) < 50:
            text = message.text
            if text:
                sink.append(text[:500])
    except Exception:  # noqa: BLE001
        return


def _collect_failed_request(request: Any, sink: list[str]) -> None:
    """Регистрирует неудавшиеся запросы: блокировки, обрывы, отмены."""
    if len(sink) >= 50:
        return
    try:
        failure = request.failure
        reason = failure if isinstance(failure, str) else (failure or {}).get("errorText", "")
        sink.append(f"{request.url[:200]} :: {reason or 'unknown'}")
    except Exception:  # noqa: BLE001
        return


def _handle_dialog(dialog: Any, settings: Settings) -> None:
    """Принимает диалоги, иначе страница может зависнуть на alert."""
    import asyncio

    if not settings.browser_auto_dismiss_dialogs:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_dismiss_dialog(dialog))


async def _dismiss_dialog(dialog: Any) -> None:
    # Диалог мог быть закрыт пользователем или сайтом — ошибка здесь безразлична.
    with contextlib.suppress(Exception):
        await dialog.accept()


async def _safe_screenshot(page: Any, *, full_page: bool) -> bytes | None:
    """Делает скриншот, не роняя операцию при неудаче."""
    try:
        return await page.screenshot(full_page=full_page, type="png")
    except Exception as exc:  # noqa: BLE001 — очень длинные страницы иногда не снимаются
        log.warning("browser.screenshot_failed", full_page=full_page, error=str(exc))
        return None


# --- Удобные обёртки ---------------------------------------------------------


@asynccontextmanager
async def browser_session(settings: Settings) -> AsyncIterator[BrowserSession]:
    """Контекстный менеджер сессии браузера."""
    session = BrowserSession(settings)
    async with session:
        yield session


async def capture_page(settings: Settings, url: str) -> RawSnapshot:
    """Открывает URL и возвращает снапшот. Сессия живёт один вызов."""
    async with browser_session(settings) as session:
        return await session.capture(url)


def screenshot_to_data_uri(png: bytes | None) -> str | None:
    """Превращает PNG в data-URI — удобно отдавать в UI без отдельного файла."""
    if not png:
        return None
    encoded = base64.b64encode(png).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def tokens_of(html: str) -> int:
    """Оценка токенов — вынесена для тестов и для UI."""
    return estimate_tokens(html)
