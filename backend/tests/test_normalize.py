"""Тесты нормализации значений (Этап 4)."""

from __future__ import annotations

from app.engine import normalize as normalize_mod


def test_parse_price_russian_format() -> None:
    parsed = normalize_mod.parse_price("12 990,50 ₽")
    assert parsed["value"] == 12990.5
    assert parsed["currency"] is not None
    assert parsed["problem"] is None


def test_parse_price_thousands_dot() -> None:
    parsed = normalize_mod.parse_price("1.299,00 руб.")
    assert parsed["value"] == 1299.0


def test_absolute_url_resolves_relative() -> None:
    link = normalize_mod.absolute_url("/product/1", "https://shop.example.com/catalog")
    assert link == "https://shop.example.com/product/1"


def test_absolute_url_strips_tracking() -> None:
    link = normalize_mod.absolute_url(
        "https://shop.example.com/p/1?utm_source=x&color=red",
        "https://shop.example.com/",
    )
    assert link == "https://shop.example.com/p/1?color=red"


def test_url_key_collapses_variants() -> None:
    a = normalize_mod.url_key("https://www.shop.example.com/product/1/")
    b = normalize_mod.url_key("https://shop.example.com/product/1?utm_source=y")
    assert a == b == "shop.example.com/product/1"


def test_parse_date_russian_month() -> None:
    assert normalize_mod.parse_date("1 февраля 2026").isoformat() == "2026-02-01"


def test_guess_type_and_detect_kind() -> None:
    assert normalize_mod.guess_type("price", "Цена") == "price"
    assert normalize_mod.guess_type("item_url") == "url"
    assert normalize_mod.detect_kind("1 249,00 ₽") == "price"
    assert normalize_mod.detect_kind("https://a.example.com/x") == "url"
    assert normalize_mod.detect_kind("01.02.2026") == "date"


def test_normalize_price_and_url() -> None:
    price = normalize_mod.normalize("199 ₽", kind="price")
    assert price.value == 199.0
    link = normalize_mod.normalize("/a", kind="url", base_url="https://shop.example.com/")
    assert link.value == "https://shop.example.com/a"


def test_dedup_key_stable_for_same_url() -> None:
    first = normalize_mod.dedup_key({"url": "https://a.example.com/p/1", "title": "A"})
    second = normalize_mod.dedup_key({"url": "https://www.a.example.com/p/1/", "title": "A"})
    assert first == second
