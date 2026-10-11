"""Проверка готовности браузера."""

from __future__ import annotations

from app.crawler import browser_ready


def test_chromium_installed_false_on_empty(tmp_path, settings, monkeypatch) -> None:
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "empty"))
    assert browser_ready.chromium_installed(settings) is False


def test_chromium_installed_true_when_dir_exists(tmp_path, settings, monkeypatch) -> None:
    root = tmp_path / "browsers"
    (root / "chromium-1234").mkdir(parents=True)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(root))
    assert browser_ready.chromium_installed(settings) is True


def test_browser_status_shape(settings, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "none"))
    status = browser_ready.browser_status(settings)
    assert "ready" in status
    assert "browsers_path" in status
    assert isinstance(status["system_channels"], list)
