"""Обрезка DOM: превращает реальную страницу в компактный HTML для модели.

Задача модуля — сохранить структуру и смысл страницы, выбросив всё, что не несёт
информации: скрипты, стили, комментарии, base64-картинки, длинные инлайновые
данные. Без обрезки реальный DOM каталога товаров не влезает в контекст локальной
модели, и анализ превращается в шум.

Реализация намеренно не использует HTML-парсер: регулярная токенизация терпима к
битой вёрстке и не тянет зависимостей.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# --- Регулярные выражения ----------------------------------------------------

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_DOCTYPE_RE = re.compile(r"<!DOCTYPE[^>]*>", re.IGNORECASE)
_SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.DOTALL | re.IGNORECASE)
_SCRIPT_SELF_RE = re.compile(r"<script\b[^>]*/\s*>", re.IGNORECASE)
_STYLE_RE = re.compile(r"<style\b[^>]*>.*?</style\s*>", re.DOTALL | re.IGNORECASE)
_SVG_RE = re.compile(r"<svg\b[^>]*>.*?</svg\s*>", re.DOTALL | re.IGNORECASE)
_NOSCRIPT_RE = re.compile(r"<noscript\b[^>]*>.*?</noscript\s*>", re.DOTALL | re.IGNORECASE)
_TEMPLATE_RE = re.compile(r"<template\b[^>]*>.*?</template\s*>", re.DOTALL | re.IGNORECASE)
_HEAD_RE = re.compile(r"<head\b[^>]*>(.*?)</head\s*>", re.DOTALL | re.IGNORECASE)
_BODY_RE = re.compile(r"<body\b[^>]*>(.*)</body\s*>", re.DOTALL | re.IGNORECASE)
_BASE64_RE = re.compile(r"data:[\w.+-]+/[\w.+-]+;base64,[A-Za-z0-9+/=\s]{80,}")
_TOKEN_RE = re.compile(r"<[^>]+>|[^<]+", re.DOTALL)

# Атрибуты, которые выбрасываются целиком.
_DROP_ATTRS = {
    "style",
    "onclick",
    "onload",
    "onerror",
    "onmouseover",
    "onmouseout",
    "onchange",
    "onsubmit",
    "oninput",
    "onfocus",
    "onblur",
    "nonce",
    "integrity",
    "crossorigin",
    "srcset",
    "sizes",
    "loading",
    "decoding",
    "fetchpriority",
}

# Атрибуты, которые сохраняются, только если они короткие.
_SOFT_KEEP = {"src", "href", "action", "poster", "content", "value", "title", "alt"}
_SOFT_VALUE_LIMIT = 160

# Атрибуты, критичные для понимания элемента и для устойчивого селектора.
_HARD_KEEP = {
    "class",
    "id",
    "name",
    "type",
    "role",
    "placeholder",
    "aria-label",
    "aria-labelledby",
    "aria-describedby",
    "aria-expanded",
    "aria-hidden",
    "for",
    "href",
    "src",
    "alt",
    "title",
    "value",
    "checked",
    "selected",
    "disabled",
    "readonly",
    "multiple",
    "required",
    "min",
    "max",
    "step",
    "pattern",
    "colspan",
    "rowspan",
    "scope",
    "datetime",
    "lang",
    "dir",
    "target",
    # rel="next"/"prev" — стандартный признак пагинации, itemprop — микроразметка
    # Schema.org. Оба нужны для анализа, поэтому сохраняются всегда.
    "rel",
    "itemprop",
    "itemscope",
    "itemtype",
}

# Текст, который не несёт смысла и часто мешает модели.
_NOISE_TEXT_RE = re.compile(r"^[\s\u00a0\u200b]+$")
_WHITESPACE_RE = re.compile(r"[ \t\u00a0\u200b]+")

# Средняя длина одного токена в символах для оценок (латиница/кириллица + HTML).
_CHARS_PER_TOKEN = 3.2


def estimate_tokens(text: str) -> int:
    """Грубая оценка числа токенов.

    Точная токенизация требует модели, а решение «влезает или нет» нуждается лишь
    в консервативной оценке. Коэффициент подобран с запасом в сторону завышения.
    """
    return int(len(text) / _CHARS_PER_TOKEN) + 1


@dataclass
class TrimStats:
    """Что именно выбросила обрезка — показывается пользователю для доверия."""

    original_bytes: int = 0
    trimmed_bytes: int = 0
    original_tokens: int = 0
    estimated_tokens: int = 0
    removed_scripts: int = 0
    removed_styles: int = 0
    removed_svgs: int = 0
    removed_comments: int = 0
    removed_attrs: int = 0
    collapsed_duplicates: int = 0
    truncated: bool = False
    max_tokens: int = 0
    kept_tokens: int = 0

    @property
    def ratio(self) -> float:
        """Во сколько раз удалось сократить страницу."""
        if not self.original_tokens:
            return 1.0
        return round(self.original_tokens / max(self.estimated_tokens, 1), 2)

    @property
    def compression_ratio(self) -> float:
        """Синоним :attr:`ratio` — так это поле называется в API."""
        return self.ratio

    def as_dict(self) -> dict[str, Any]:
        return {
            "original_bytes": self.original_bytes,
            "trimmed_bytes": self.trimmed_bytes,
            "original_tokens": self.original_tokens,
            "estimated_tokens": self.estimated_tokens,
            "compression_ratio": self.ratio,
            "removed_scripts": self.removed_scripts,
            "removed_styles": self.removed_styles,
            "removed_svgs": self.removed_svgs,
            "removed_comments": self.removed_comments,
            "removed_attrs": self.removed_attrs,
            "collapsed_duplicates": self.collapsed_duplicates,
            "truncated": self.truncated,
            "max_tokens": self.max_tokens,
        }


@dataclass
class TrimResult:
    """Результат обрезки: готовый HTML плюс статистика."""

    html: str
    stats: TrimStats
    head: str = ""
    title: str | None = None
    meta: dict[str, str] = field(default_factory=dict)


# --- Вспомогательные преобразования ------------------------------------------


def normalize_url(url: str, base: str | None = None) -> str:
    """Приводит относительную ссылку к абсолютной."""
    from urllib.parse import urljoin

    if not url or url.startswith(("data:", "javascript:", "mailto:", "tel:", "#")):
        return url
    if base:
        return urljoin(base, url)
    return url


def _clean_attributes(raw_tag: str, stats: TrimStats, base_url: str | None) -> str:
    """Собирает тег заново, оставив только значимые атрибуты."""
    inner = raw_tag[1:-1].strip()
    if inner.startswith("/"):
        return "</" + inner.lstrip("/").split()[0].lower() + ">"
    if inner.endswith("/"):
        inner = inner[:-1].strip()

    parts = inner.split(None, 1)
    if not parts:
        return raw_tag
    name = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    rebuilt: list[str] = [name]
    if rest:
        attr_re = re.compile(
            r"""([\w:.-]+)\s*(?:=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?""",
            re.DOTALL,
        )
        for match in attr_re.finditer(rest):
            attr_name = match.group(1).lower()
            value = match.group(2)
            if value is None:
                value = match.group(3)
            if value is None:
                value = match.group(4)

            if attr_name in _DROP_ATTRS:
                stats.removed_attrs += 1
                continue
            is_data_attr = attr_name.startswith("data-")
            is_aria = attr_name.startswith("aria-")
            if not (attr_name in _HARD_KEEP or is_data_attr or is_aria or attr_name in _SOFT_KEEP):
                stats.removed_attrs += 1
                continue

            if value is None:
                rebuilt.append(attr_name)
                continue

            if _BASE64_RE.match(value):
                value = "[base64]"
            if attr_name in ("href", "src", "action", "poster"):
                value = normalize_url(value, base_url)
            if (
                attr_name in _SOFT_KEEP
                and attr_name not in _HARD_KEEP
                and len(value) > _SOFT_VALUE_LIMIT
            ):
                stats.removed_attrs += 1
                continue
            if len(value) > 400:
                value = value[:400] + "…"

            rebuilt.append(f'{attr_name}="{value}"')

    return "<" + " ".join(rebuilt) + ">"


def _collapse_whitespace(text: str) -> str:
    """Схлопывает пробелы и выбрасывает узлы, состоящие только из пробелов."""
    collapsed = _WHITESPACE_RE.sub(" ", text).strip()
    return collapsed


def _extract_head(source: str) -> tuple[str, str | None, dict[str, str]]:
    """Достаёт <head> из исходного HTML, чтобы сохранить метаданные страницы."""
    match = _HEAD_RE.search(source)
    head = match.group(0) if match else ""
    title_match = re.search(r"<title[^>]*>(.*?)</title\s*>", source, re.DOTALL | re.IGNORECASE)
    title = title_match.group(1).strip() if title_match else None

    meta: dict[str, str] = {}
    for tag in re.findall(r"<meta\b[^>]*>", head, re.IGNORECASE):
        name_match = re.search(r"""(?:name|property)\s*=\s*["']?([^"'>\s]+)""", tag, re.IGNORECASE)
        content_match = re.search(r"""content\s*=\s*["']([^"']*)["']""", tag, re.IGNORECASE)
        if name_match and content_match:
            meta[name_match.group(1).lower()] = content_match.group(1)[:300]
    return head, title, meta


def _strip_noise(source: str, stats: TrimStats) -> str:
    """Удаляет тяжёлые и бесполезные для анализа блоки."""
    patterns = (
        (_SCRIPT_RE, "removed_scripts"),
        (_SCRIPT_SELF_RE, "removed_scripts"),
        (_STYLE_RE, "removed_styles"),
        (_SVG_RE, "removed_svgs"),
        (_NOSCRIPT_RE, "removed_scripts"),
        (_TEMPLATE_RE, "removed_scripts"),
    )
    result = source
    for pattern, counter in patterns:
        result, count = pattern.subn("", result)
        setattr(stats, counter, getattr(stats, counter) + count)

    result, comments = _COMMENT_RE.subn("", result)
    stats.removed_comments += comments
    result = _DOCTYPE_RE.sub("", result)
    result, base64_count = _BASE64_RE.subn("[base64]", result)
    stats.removed_attrs += base64_count
    return result


def _interest(text: str) -> bool:
    """Помечает фрагмент как значимый для анализа."""
    lowered = text.lower()
    markers = (
        "data-",
        "aria-",
        "role=",
        "id=",
        "name=",
        "class=",
        "href=",
        "src=",
        "<form",
        "<input",
        "<button",
        "<select",
        "<table",
        "<tr",
        "<td",
        "<li",
        "<h1",
        "<h2",
        "<h3",
        "<label",
        "<article",
        "<section",
        "<nav",
        "<option",
        "<textarea",
        "<a ",
        "itemprop",
        "itemscope",
    )
    return any(marker in lowered for marker in markers)


def trim_html(
    source: str,
    *,
    max_tokens: int = 24_000,
    base_url: str | None = None,
) -> TrimResult:
    """Обрезает HTML до лимита токенов, сохраняя структуру и смысловые элементы.

    Порядок работы:

    1. вырезаются скрипты, стили, SVG, комментарии, base64-данные;
    2. открывающие теги пересобираются: остаются значимые атрибуты, ссылки
       делаются абсолютными, мусорные обработчики выбрасываются;
    3. текст нормализуется (схлопывание пробелов, удаление пустых узлов);
    4. **подряд идущие одинаковые по структуре блоки схлопываются** — вместо
       40 одинаковых карточек остаётся 3 и пометка о повторе. Именно это делает
       возможным анализ каталогов в контексте локальной модели;
    5. если результата всё ещё больше лимита, середина вырезается с пометкой,
       а начало (шапка, меню) и конец (пагинация, футер) сохраняются.
    """
    stats = TrimStats(
        original_bytes=len(source.encode("utf-8")),
        original_tokens=estimate_tokens(source),
        max_tokens=max_tokens,
    )

    head, title, meta = _extract_head(source)
    body_match = _BODY_RE.search(source)
    if body_match:
        skeleton = body_match.group(1)
        wrapper_open, wrapper_close = "<body>", "</body>"
    else:
        skeleton = source
        wrapper_open, wrapper_close = "", ""

    # Битая вёрстка (например, незакрытый <script>) легко съедает весь <body>.
    # Если содержимое подозрительно мало по сравнению со страницей, работаем со
    # всем документом: лучше лишний шум, чем пустая страница на выходе.
    if body_match and len(skeleton) < len(source) * 0.15:
        skeleton = source
        wrapper_open, wrapper_close = "", ""

    # Комментарии вырезаем до токенизации: жадное сопоставление тегов иначе
    # «съедает» вместе с комментарием весь следующий текст.
    skeleton, removed_comments = _COMMENT_RE.subn("", skeleton)
    stats.removed_comments += removed_comments

    cleaned = _strip_noise(skeleton, stats)

    # --- Шаг 2-3: пересборка тегов и нормализация текста --------------------
    tokens = _TOKEN_RE.findall(cleaned)
    pieces: list[str] = []
    for token in tokens:
        if token.startswith("<"):
            pieces.append(_clean_attributes(token, stats, base_url))
        else:
            text = _collapse_whitespace(token)
            if text:
                pieces.append(text)

    # --- Шаг 4: схлопывание повторов ----------------------------------------
    collapsed = _collapse_repeated_blocks(pieces, stats)

    html = wrapper_open + "".join(collapsed) + wrapper_close

    # Пометки о схлопнутых списках выносим в конец документа: по ним анализатор
    # узнаёт полный размер списка, а не только число оставленных примеров.
    # Внутри списка их держать нельзя — повторная обрезка их бы удалила.
    marker_notes = [piece for piece in collapsed if piece.startswith("<!-- UPA:")]
    if marker_notes:
        html += "".join(marker_notes)

    # --- Шаг 5: жёсткое обрезание по лимиту ---------------------------------
    html, truncated = _cap_tokens(html, max_tokens)
    stats.truncated = truncated

    stats.trimmed_bytes = len(html.encode("utf-8"))
    stats.estimated_tokens = estimate_tokens(html)
    stats.kept_tokens = stats.estimated_tokens
    return TrimResult(html=html, stats=stats, head=head, title=title, meta=meta)


def _block_signature(tag: str) -> str | None:
    """Подпись открывающего тега для поиска одинаковых блоков."""
    match = re.match(r"<(\w+)([^>]*)>", tag)
    if not match:
        return None
    name = match.group(1).lower()
    if name in {"div", "li", "tr", "article", "section", "td"}:
        attrs = match.group(2)
        class_match = re.search(r'class="([^"]*)"', attrs)
        return f"{name}:{class_match.group(1) if class_match else ''}"
    return None


# Теги, у которых не бывает закрывающей пары. Без их учёта счётчик вложенности
# уезжает и весь последующий разбор ломается (текст «прилипает» к тегам).
VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


def _is_void_tag(token: str) -> bool:
    """Проверяет, что открывающий тег не имеет закрывающей пары."""
    if token.endswith("/>"):
        return True
    match = re.match(r"<([a-zA-Z][\w:-]*)", token)
    return bool(match) and match.group(1).lower() in VOID_TAGS


def _children_spans(tokens: list[str]) -> list[tuple[str, list[str]]]:
    """Разбивает список токенов на дочерние блоки с их подписями.

    Работает рекурсивно: блоком считается элемент верхнего уровня (и его
    содержимое целиком), текст между элементами приклеивается к соседу. Если у
    элемента нет осмысленной подписи (нет класса), он всё равно остаётся блоком —
    просто «безымянным», и внутрь него рекурсия зайдёт отдельно.
    """
    spans: list[tuple[str, list[str]]] = []
    level: list[str] = []
    depth = 0
    open_tag = ""

    for token in tokens:
        if token.startswith("</"):
            if depth > 0:
                level.append(token)
                depth -= 1
                if depth == 0:
                    spans.append((_block_signature(open_tag) or "", level))
                    level = []
            continue

        if token.startswith("<"):
            if depth == 0:
                level = [token]
                open_tag = token
                if _is_void_tag(token):
                    # Одиночный элемент: блок из одного токена, вложенности нет.
                    spans.append((_block_signature(token) or "", level))
                    level = []
                    depth = 0
                else:
                    depth = 1
            else:
                level.append(token)
                if not _is_void_tag(token):
                    depth += 1
            continue

        if depth > 0:
            level.append(token)
        elif spans:
            # Текст между элементами — присоединяем к предыдущему блоку, чтобы
            # подписи вида «Товар 1» перед следующей карточкой не терялись.
            spans[-1][1].append(token)
        else:
            # Текст до первого тега (или после последнего): накапливаем в отдельный
            # блок. Раньше он молча пропадал — из-за этого исчезал весь текст
            # простых страниц и подписи между элементами.
            level.append(token)

    if level:
        spans.append((_block_signature(open_tag) or "", level))
    return spans


def _is_element_block(block: list[str]) -> bool:
    """Проверяет, что блок — это цельный элемент: тег … закрывающий тег.

    Текстовые токены и «хвосты» между элементами блоками не являются, и внутрь
    них рекурсия заходить не должна — иначе текстовые узлы теряются.
    """
    if len(block) < 2:
        return False
    opening, closing = block[0], block[-1]
    if not opening.startswith("<") or opening.startswith("</"):
        return False
    if not closing.startswith("</"):
        return False
    match = re.match(r"<([a-zA-Z][\w:-]*)", opening)
    if not match:
        return False
    return closing[2:].strip().lower().startswith(match.group(1).lower())


def _collapse_level(tokens: list[str], stats: TrimStats, keep: int) -> list[str]:
    """Схлопывает повторы среди блоков одного уровня, затем рекурсивно идёт внутрь."""
    out: list[str] = []
    seen: dict[str, int] = {}
    skipped = 0

    for signature, block in _children_spans(tokens):
        if not _is_element_block(block):
            # Текст или непарный тег — переносим содержимое без изменений.
            out.extend(block)
            continue

        # Пустой элемент: перебирать внутри нечего.
        if len(block) <= 2:
            out.extend(block)
            continue

        if signature:
            seen[signature] = seen.get(signature, 0) + 1
            if seen[signature] > keep:
                skipped += 1
                stats.collapsed_duplicates += 1
                continue
            if skipped:
                total = keep + skipped
                out.append(_repeat_marker(skipped, total, keep))
                skipped = 0

        opening, closing = block[0], block[-1]
        out.extend([opening, *_collapse_level(block[1:-1], stats, keep), closing])

    if skipped:
        total = keep + skipped
        out.append(_repeat_marker(skipped, total, keep))
    return out


def _collapse_repeated_blocks(pieces: list[str], stats: TrimStats) -> list[str]:
    """Схлопывает длинные серии структурно одинаковых блоков на любой глубине.

    Каталог из 60 одинаковых карточек товара съедает весь контекст модели, ничего
    не добавляя к пониманию структуры. Для каждого вида блока оставляем первые
    ``keep`` экземпляров, а остальные заменяем пометкой с количеством. Рекурсия
    нужна потому, что карточки почти всегда лежат внутри контейнера-обёртки, а не
    в корне страницы.
    """
    return _collapse_level(pieces, stats, keep=3)


def _repeat_marker(count: int, total: int, shown: int) -> str:
    """Пометка о схлопнутых повторах.

    В пометке сохраняется **полное** число элементов списка. Это принципиально:
    обрезка удаляет лишние карточки, и без такой пометки анализатор, работающий
    по обрезанному DOM, сообщил бы «в списке 3 элемента» вместо 12.
    """
    return (
        f"<!-- UPA: список из {total} однотипных элементов, "
        f"показаны первые {shown}, скрыто ещё {count} -->"
    )


def _cap_tokens(html: str, max_tokens: int) -> tuple[str, bool]:
    """Жёстко ограничивает размер, сохраняя начало и конец документа.

    Середина вырезается: в шапке и навигации находятся фильтры и поиск, в конце —
    пагинация, поэтому терять их нельзя.
    """
    if estimate_tokens(html) <= max_tokens:
        return html, False

    marker = "\n<!-- UPA: середина страницы вырезана из-за лимита контекста -->\n"
    # 40% — начало, 60% — конец: пагинация и «показать ещё» важнее середины списка.
    budget_chars = int(max_tokens * _CHARS_PER_TOKEN)
    head_chars = int(budget_chars * 0.4)
    tail_chars = budget_chars - head_chars - len(marker)

    # Границы режем по последнему/первому тегу, чтобы не порвать разметку.
    cut = html.rfind(">", 0, head_chars)
    head_part = html[: cut + 1] if cut > 0 else html[:head_chars]
    start = len(html) - tail_chars
    nxt = html.find("<", start)
    tail_part = html[nxt:] if nxt != -1 else html[start:]

    return head_part + marker + tail_part, True


def trim_stats_to_dict(result: TrimResult) -> dict[str, Any]:
    """Удобное представление статистики для API и UI."""
    data = result.stats.as_dict()
    data["title"] = result.title
    data["meta_keys"] = sorted(result.meta.keys())
    return data
