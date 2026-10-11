"""Живая запись действий пользователя в браузере Playwright."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings
from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.workflow.schema import RecordedEvent

log = get_logger(__name__)

# Скрипт, который вешает слушатели и шлёт события в Python через binding.
_RECORDER_JS = r"""
(() => {
  if (window.__upaRecorderInstalled) return;
  window.__upaRecorderInstalled = true;

  function cssPath(el) {
    if (!el || el.nodeType !== 1) return null;
    if (el.id) return '#' + CSS.escape(el.id);
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && parts.length < 5) {
      let part = node.tagName.toLowerCase();
      if (node.name) {
        part += `[name="${CSS.escape(node.name)}"]`;
        parts.unshift(part);
        break;
      }
      const parent = node.parentElement;
      if (!parent) {
        parts.unshift(part);
        break;
      }
      const siblings = Array.from(parent.children).filter((c) => c.tagName === node.tagName);
      if (siblings.length > 1) {
        const index = siblings.indexOf(node) + 1;
        part += `:nth-of-type(${index})`;
      }
      parts.unshift(part);
      node = parent;
      if (node.tagName && node.tagName.toLowerCase() === 'body') break;
    }
    return parts.join(' > ');
  }

  function emit(payload) {
    try {
      window.__upaRecordEvent(payload);
    } catch (e) {}
  }

  document.addEventListener('click', (event) => {
    const el = event.target;
    if (!(el instanceof Element)) return;
    emit({
      type: 'click',
      selector: cssPath(el),
      tag: el.tagName.toLowerCase(),
      text: (el.innerText || el.value || '').trim().slice(0, 120),
      name: el.getAttribute('name'),
      input_type: el.getAttribute('type'),
      timestamp_ms: Date.now(),
    });
  }, true);

  document.addEventListener('change', (event) => {
    const el = event.target;
    if (!(el instanceof Element)) return;
    const tag = el.tagName.toLowerCase();
    if (tag === 'select') {
      emit({
        type: 'select',
        selector: cssPath(el),
        value: el.value,
        tag,
        name: el.getAttribute('name'),
        timestamp_ms: Date.now(),
      });
      return;
    }
    if (tag === 'input' && (el.type === 'checkbox' || el.type === 'radio')) {
      emit({
        type: 'check',
        selector: cssPath(el),
        value: el.checked ? 'true' : 'false',
        tag,
        name: el.getAttribute('name'),
        input_type: el.type,
        timestamp_ms: Date.now(),
      });
      return;
    }
    if (tag === 'input' || tag === 'textarea') {
      emit({
        type: 'fill',
        selector: cssPath(el),
        value: el.value,
        tag,
        name: el.getAttribute('name'),
        input_type: el.getAttribute('type'),
        timestamp_ms: Date.now(),
      });
    }
  }, true);
})();
"""


@dataclass
class LiveRecordingSession:
    """Активная сессия записи в браузере."""

    id: str
    url: str
    events: list[RecordedEvent] = field(default_factory=list)
    status: str = "starting"  # starting | recording | stopped | failed
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    _task: asyncio.Task[Any] | None = field(default=None, repr=False)
    _stop: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _browser: Any = field(default=None, repr=False)
    _context: Any = field(default=None, repr=False)
    _playwright: Any = field(default=None, repr=False)


_SESSIONS: dict[str, LiveRecordingSession] = {}


def get_session(session_id: str) -> LiveRecordingSession:
    session = _SESSIONS.get(session_id)
    if session is None:
        raise NotFoundError("Сессия записи не найдена", details={"session_id": session_id})
    return session


async def start_recording(
    settings: Settings,
    url: str,
    *,
    headed: bool = True,
    dry: bool = False,
) -> LiveRecordingSession:
    """Открывает браузер и начинает писать действия."""
    if not url.startswith(("http://", "https://")):
        raise ValidationError("URL должен начинаться с http:// или https://")

    session = LiveRecordingSession(id=uuid.uuid4().hex[:16], url=url)
    _SESSIONS[session.id] = session

    if dry:
        session.status = "recording"
        session.events.append(
            RecordedEvent(type="goto", url=url, timestamp_ms=int(time.time() * 1000))
        )
        return session

    session._task = asyncio.create_task(_run_session(session, settings, headed=headed))
    # Даём задаче стартовать.
    for _ in range(50):
        if session.status in {"recording", "failed"}:
            break
        await asyncio.sleep(0.05)
    if session.status == "failed":
        raise ValidationError(
            session.error or "Не удалось открыть браузер для записи",
            details={"session_id": session.id},
        )
    return session


async def stop_recording(session_id: str) -> LiveRecordingSession:
    session = get_session(session_id)
    session._stop.set()
    if session._task is not None:
        try:
            await asyncio.wait_for(session._task, timeout=15)
        except (TimeoutError, asyncio.CancelledError):
            session._task.cancel()
    session.status = "stopped"
    return session


def session_snapshot(session: LiveRecordingSession) -> dict[str, Any]:
    return {
        "session_id": session.id,
        "url": session.url,
        "status": session.status,
        "error": session.error,
        "events": [event.model_dump(mode="json") for event in session.events],
        "events_count": len(session.events),
    }


async def _run_session(
    session: LiveRecordingSession, settings: Settings, *, headed: bool
) -> None:
    try:
        from playwright.async_api import async_playwright

        from app.crawler.browser import launch_chromium
    except Exception as exc:  # noqa: BLE001
        session.status = "failed"
        session.error = str(exc)
        return

    try:
        session._playwright = await async_playwright().start()
        session._browser = await launch_chromium(
            session._playwright, settings, headless=not headed
        )
        session._context = await session._browser.new_context(
            locale=settings.browser_locale,
            user_agent=settings.browser_user_agent or None,
            viewport={
                "width": settings.browser_viewport_width,
                "height": settings.browser_viewport_height,
            },
        )
        page = await session._context.new_page()

        async def on_event(source: Any, payload: dict[str, Any]) -> None:  # noqa: ARG001
            try:
                event = RecordedEvent.model_validate(payload)
            except Exception:  # noqa: BLE001
                return
            session.events.append(event)

        await page.expose_binding("__upaRecordEvent", on_event)
        await page.add_init_script(_RECORDER_JS)

        session.events.append(
            RecordedEvent(type="goto", url=session.url, timestamp_ms=int(time.time() * 1000))
        )
        await page.goto(session.url, wait_until="domcontentloaded", timeout=60_000)
        await page.evaluate(_RECORDER_JS)
        session.status = "recording"
        log.info("workflow.live_record_started", session_id=session.id, url=session.url)

        last_url = page.url
        while not session._stop.is_set():
            try:
                await asyncio.wait_for(session._stop.wait(), timeout=0.4)
            except TimeoutError:
                current = page.url
                if current and current != last_url:
                    session.events.append(
                        RecordedEvent(
                            type="goto",
                            url=current,
                            timestamp_ms=int(time.time() * 1000),
                        )
                    )
                    last_url = current
    except Exception as exc:  # noqa: BLE001
        session.status = "failed"
        session.error = f"{type(exc).__name__}: {exc}"
        log.error("workflow.live_record_failed", session_id=session.id, error=session.error)
    finally:
        with_context = session._context
        browser = session._browser
        playwright = session._playwright
        session._context = None
        session._browser = None
        session._playwright = None
        try:
            if with_context is not None:
                await with_context.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if browser is not None:
                await browser.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if playwright is not None:
                await playwright.stop()
        except Exception:  # noqa: BLE001
            pass
        if session.status == "recording":
            session.status = "stopped"
