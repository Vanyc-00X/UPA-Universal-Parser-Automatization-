"""Тесты плана пагинации (Этап 4)."""

from __future__ import annotations

from app.analyzer.domlite import parse
from app.editor.schema import PaginationKind, PaginationSpec
from app.engine import paginate
from tests.fakes import build_html


def test_url_template_builds_pages() -> None:
    plan = paginate.build_plan(
        PaginationSpec(
            kind=PaginationKind.URL_TEMPLATE,
            url_template="https://shop.example.com/catalog?page={page}",
            start_page=1,
            max_pages=3,
        )
    )
    visits = plan.page_urls("https://shop.example.com/catalog")
    assert [visit.number for visit in visits] == [1, 2, 3]
    assert visits[1].url.endswith("page=2")


def test_find_next_url_from_rel_next() -> None:
    document = parse(build_html())
    url, problem = paginate.find_next_url(
        document,
        "a[rel='next']",
        base_url="https://shop.example.com/catalog",
    )
    assert problem is None
    assert url == "https://shop.example.com/catalog?page=2"


def test_next_page_step_stops_on_repeat() -> None:
    step, note = paginate.next_page_step(
        "https://shop.example.com/catalog?page=2",
        "https://shop.example.com/catalog?page=2",
        set(),
    )
    assert step is None
    assert note is None


def test_scroll_requires_browser_and_limits_to_one() -> None:
    plan = paginate.build_plan(PaginationSpec(kind=PaginationKind.SCROLL, max_pages=10))
    assert plan.needs_browser is True
    assert plan.max_pages == 1
    assert plan.notes
