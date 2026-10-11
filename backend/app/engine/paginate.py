"""Обход страниц: сколько страниц и по каким адресам.

Пагинация — источник двух проблем: зацикливания (кнопка «далее» на последней
странице ведёт на неё же) и безудержного роста (бесконечная лента). Поэтому адрес
каждой страницы проверяется на повтор, а число страниц ограничено явно.

Режимы, которые можно обойти без браузера:

* **шаблон адреса** — адреса вычисляются заранее, браузер не нужен;
* **кнопка «далее»** — адрес берётся из ссылки на текущей странице.

Остальные режимы (скролл, «показать ещё») требуют браузера и помечаются как
неподдерживаемые здесь — их обрабатывает запуск с живой страницей.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.analyzer.domlite import Document
from app.editor import resolver
from app.editor.schema import PaginationKind, PaginationSpec
from app.engine.normalize import absolute_url, navigation_key

# Больше этого числа страниц за один запуск не обходим: защита от ленты.
HARD_PAGE_LIMIT = 500


@dataclass
class PageVisit:
    """Одна страница в очереди обхода."""

    number: int
    url: str
    key: str


@dataclass
class PaginationPlan:
    """Разобранный план обхода страниц."""

    kind: PaginationKind
    start_page: int = 1
    max_pages: int = 1
    delay_ms: int = 0
    url_template: str | None = None
    selector: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def enabled(self) -> bool:
        return self.kind is not PaginationKind.NONE and self.max_pages > 1

    @property
    def needs_browser(self) -> bool:
        """Требуется ли живая страница для перехода дальше."""
        return self.kind in {PaginationKind.SCROLL, PaginationKind.LOAD_MORE}

    def page_urls(self, base_url: str) -> list[PageVisit]:
        """Адреса страниц по шаблону. Для других режимов план не вычисляется."""
        if self.kind is not PaginationKind.URL_TEMPLATE or not self.url_template:
            return []
        visits: list[PageVisit] = []
        seen: set[str] = set()
        limit = min(self.max_pages, HARD_PAGE_LIMIT)
        for offset in range(limit):
            number = self.start_page + offset
            url = self.url_template.replace("{page}", str(number))
            key = navigation_key(url) or url
            if key in seen:
                # Шаблон не двигает страницу: дальше идти бессмысленно.
                self.notes.append(f"шаблон повторяет один и тот же адрес на странице {number}")
                break
            seen.add(key)
            visits.append(PageVisit(number=number, url=url, key=key))
        return visits


def build_plan(spec: PaginationSpec) -> PaginationPlan:
    """Преобразует описание пагинации сценария в план обхода."""
    max_pages = max(1, min(int(spec.max_pages or 1), HARD_PAGE_LIMIT))
    plan = PaginationPlan(
        kind=spec.kind,
        start_page=max(1, int(spec.start_page or 1)),
        max_pages=max_pages,
        delay_ms=max(0, int(spec.delay_ms or 0)),
        url_template=spec.url_template,
        selector=spec.selector,
    )

    if spec.kind is PaginationKind.NONE:
        plan.max_pages = 1
        return plan

    if spec.kind is PaginationKind.URL_TEMPLATE and not spec.url_template:
        plan.notes.append("выбран шаблон адреса, но сам шаблон не задан")
        plan.max_pages = 1
    elif spec.kind is PaginationKind.NEXT_LINK and not spec.selector:
        plan.notes.append("выбран переход по кнопке, но селектор не задан")
        plan.max_pages = 1
    elif spec.kind in {PaginationKind.SCROLL, PaginationKind.LOAD_MORE}:
        plan.notes.append(
            "бесконечная лента и кнопка «показать ещё» требуют браузера: "
            "при разборе снапшотов обходится только первая страница"
        )
        plan.max_pages = 1

    return plan


def find_next_url(
    document: Document,
    selector: str | None,
    *,
    base_url: str | None,
) -> tuple[str | None, str | None]:
    """Ищет адрес следующей страницы по кнопке «далее».

    Возвращает адрес и замечание. Если найденная ссылка ведёт на текущую
    страницу, это считается концом списка, а не ошибкой вёрстки: так ведут себя
    многие сайты на последней странице.
    """
    if not selector:
        return None, "селектор перехода не задан"

    report = resolver.resolve(document.root, selector)
    if not report.valid:
        return None, f"селектор перехода не поддерживается: {report.error}"
    if not report.nodes:
        return None, None  # кнопки нет — значит, страниц больше не осталось

    for node in report.nodes:
        candidate = node.get("href") or node.get("data-href") or node.get("data-url")
        if candidate:
            resolved = absolute_url(candidate, base_url)
            if resolved:
                return resolved, None

    # Кнопка без адреса: переход возможен только в браузере.
    return None, "у кнопки перехода нет адреса — нужен браузер"


def next_page_step(
    current_url: str,
    next_url: str | None,
    visit_keys: set[str],
) -> tuple[PageVisit | None, str | None]:
    """Готовит следующий шаг обхода, отсекая повторы.

    Повтор адреса означает конец списка: так выглядят и последняя страница, и
    «далее» на ней.
    """
    if not next_url:
        return None, None

    key = navigation_key(next_url) or next_url
    current_key = navigation_key(current_url) or current_url
    if key == current_key:
        return None, None
    if key in visit_keys:
        return None, f"адрес {urlsplit(next_url).path or next_url} уже был обработан"

    return PageVisit(number=0, url=next_url, key=key), None


def iter_template_pages(plan: PaginationPlan, base_url: str) -> Iterator[PageVisit]:
    """Перебор страниц по шаблону адреса."""
    yield from plan.page_urls(base_url)
