"""Проверка CSS-селекторов на разобранном DOM.

Задача модуля — ответить на вопрос «работает ли селектор и сколько узлов он
находит». Это нужно визуальному редактору (Этап 3): пользователь должен видеть,
что его правка верна, а не надеяться на это. Тот же механизм будет основой
движка извлечения (Этап 4) и самопочинки (Этап 6).

Поддерживается подмножество CSS, которого достаточно для селекторов, генерируемых
UPA и придуманных пользователем:

* простые селекторы: ``div``, ``.class``, ``#id``, ``[attr]``, ``[attr="v"]``;
* комбинации на одном элементе: ``input[type="search"].search-field``;
* потомки и прямые дети: ``div.product-card span.price``, ``.list > .item``;
* проверки на видимость результата.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from app.analyzer.domlite import Node

# Токен одного составного селектора: тег, классы, идентификатор, атрибуты,
# псевдокласс :nth-child(N) — он нужен для резервных селекторов-путей.
# Псевдоклассы и атрибуты идут раньше тега: правило тега жадно захватывает
# двоеточие и скобки, поэтому `div:nth-child(2)` иначе не разбирается.
COMPOUND_RE = re.compile(
    r"""
    :(?P<pseudo>nth-child|nth-of-type)\((?P<pseudo_arg>\d+)\)
    | \#(?P<id>[\w\-:.]+)
    | \.(?P<cls>[\w\-:]+)
    | \[(?P<attr>[\w:.\-]+)\s*
        (?:(?P<op>[~^$*|]?=)\s*
           (?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)'|(?P<bare>[^\]]*?))
        )?\s*\]
    | (?P<tag>[a-zA-Z][\w-]*)
    | (?P<universal>\*)
    """,
    re.VERBOSE,
)

# Атрибутные селекторы, которые встречаются в реальной вёрстке.
ATTR_OPERATORS = {"=", "~=", "^=", "$=", "*=", "|="}


@dataclass
class Compound:
    """Один составной селектор: например ``a.pagination__next[rel="next"]``."""

    tag: str | None = None
    node_id: str | None = None
    classes: list[str] = field(default_factory=list)
    attributes: list[tuple[str, str | None, str | None]] = field(default_factory=list)
    # Псевдоклассы с числовым аргументом: [("nth-child", 2)].
    pseudos: list[tuple[str, int]] = field(default_factory=list)

    def __str__(self) -> str:
        parts = [self.tag or ""]
        if self.node_id:
            parts.append(f"#{self.node_id}")
        parts.extend(f".{item}" for item in self.classes)
        for name, operator, value in self.attributes:
            if operator and value is not None:
                parts.append(f'[{name}{operator}"{value}"]')
            else:
                parts.append(f"[{name}]")
        for name, argument in self.pseudos:
            parts.append(f":{name}({argument})")
        return "".join(parts) or "*"

    def matches(self, node: Node) -> bool:
        """Подходит ли узел под этот составной селектор."""
        if self.tag and node.tag != self.tag:
            return False
        if self.node_id and node.node_id != self.node_id:
            return False
        if self.classes:
            node_classes = set(node.classes)
            if not all(item in node_classes for item in self.classes):
                return False
        for name, operator, value in self.attributes:
            if name not in node.attrs:
                return False
            if operator is None:
                continue
            actual = node.get(name)
            if value is None:
                return False
            if not _attribute_matches(actual, operator, value):
                return False
        for name, argument in self.pseudos:
            # Позиция среди детей того же типа, как в CSS (нумерация с единицы).
            siblings = (
                [
                    child
                    for child in (node.parent.children if node.parent else [])
                    if child.tag == node.tag
                ]
                if name == "nth-of-type"
                else (node.parent.children if node.parent else [])
            )
            if not 1 <= argument <= len(siblings):
                return False
            if siblings[argument - 1] is not node:
                return False
        return True


def _attribute_matches(actual: str, operator: str, expected: str) -> bool:
    """Проверяет атрибутный селектор с учётом оператора."""
    if operator == "=":
        return actual == expected
    if operator == "~=":
        return expected in actual.split()
    if operator == "^=":
        return actual.startswith(expected)
    if operator == "$=":
        return actual.endswith(expected)
    if operator == "*=":
        return expected in actual
    if operator == "|=":
        return actual == expected or actual.startswith(f"{expected}-")
    return actual == expected


@dataclass
class ParsedSelector:
    """Разобранный селектор: цепочка составных частей с комбинаторами."""

    # Каждый шаг — составной селектор и комбинатор, связывающий его с предыдущим.
    steps: list[tuple[str, Compound]] = field(default_factory=list)
    raw: str = ""

    @property
    def valid(self) -> bool:
        return bool(self.steps)

    def matches(self, node: Node) -> bool:
        """Проверяет узел и его предков по всей цепочке.

        Комбинатор хранится при том шаге, к которому относится, поэтому цепочка
        проверяется целиком: отбросить последний комбинатор нельзя — иначе ``>``
        превратился бы в «потомка на любой глубине».
        """
        if not self.steps:
            return False
        return _match_prefix(node, self.steps)

    def matching_nodes(self, root: Node) -> list[Node]:
        """Все узлы поддерева, подходящие под селектор."""
        return [node for node in root.walk() if node is not root and self.matches(node)]


def _match_prefix(node: Node, steps: list[tuple[str, Compound]]) -> bool:
    """Проверяет цепочку селектора справа налево.

    Последний шаг сверяется с самим узлом, остальные — с его предками. Комбинатор
    хранится при том шаге, к которому относится, поэтому ``>`` всегда означает
    «непосредственный родитель», а не «любой предок».
    """
    if not steps:
        return True

    combinator, compound = steps[-1]
    rest = steps[:-1]

    if not compound.matches(node):
        return False
    if not rest:
        return True

    if combinator == ">":
        parent = node.parent
        if parent is None or parent.tag == "#document":
            return False
        # Родитель играет роль узла для предыдущего шага.
        return _match_ancestors(parent, rest)

    ancestor = node.parent
    while ancestor is not None and ancestor.tag != "#document":
        if _match_ancestors(ancestor, rest):
            return True
        ancestor = ancestor.parent
    return False


def _match_ancestors(node: Node, steps: list[tuple[str, Compound]]) -> bool:
    """Сверяет цепочку с узлом и его предками (узел проверяется первым)."""
    return _match_prefix(node, steps)


def parse_selector(selector: str) -> ParsedSelector:
    """Разбирает CSS-селектор в цепочку составных частей.

    Комбинаторы разбираются двумя шагами: сначала по ``>`` (прямой потомок),
    затем внутри каждой части — по пробелам (потомок на любой глубине). Такой
    разбор невозможно перепутать: пробелы вокруг ``>`` не важны.

    Возвращает разобранный селектор с ``valid=False``, если разбор не удался:
    вызывающий код должен показать пользователю «селектор не поддерживается», а
    не молча ничего не найти.
    """
    raw = (selector or "").strip()
    if not raw:
        return ParsedSelector(steps=[], raw=selector)

    steps: list[tuple[str, Compound]] = []
    # Пробелы вокруг ">" не значимы: "a > b" и "a>b" — одно и то же.
    normalized = re.sub(r"\s*>\s*", ">", raw)

    for child_chunk in _split_children(normalized):
        for index, part in enumerate(_split_descendants(child_chunk)):
            compound = _parse_compound(part)
            if compound is None:
                return ParsedSelector(steps=[], raw=selector)
            if not steps:
                steps.append((" ", compound))
            elif index == 0:
                # Первый селектор после ">" — прямой потомок предыдущего.
                steps.append((">", compound))
            else:
                steps.append((" ", compound))

    return ParsedSelector(steps=steps, raw=selector)


def _split_children(selector: str) -> list[str]:
    """Делит селектор по ``>``, не трогая содержимое кавычек и скобок."""
    chunks: list[str] = []
    buffer: list[str] = []
    quote: str | None = None
    depth = 0

    for char in selector:
        if quote:
            buffer.append(char)
            if char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
            buffer.append(char)
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth = max(depth - 1, 0)
        if char == ">" and depth == 0:
            chunks.append("".join(buffer))
            buffer = []
            continue
        buffer.append(char)

    chunks.append("".join(buffer))
    return [chunk for chunk in chunks if chunk.strip()]


def _split_descendants(chunk: str) -> list[str]:
    """Делит часть селектора по пробелам вне кавычек и квадратных скобок.

    Значение атрибута вполне может содержать пробел — ``[data-label="поиск по
    каталогу"]``. Наивное деление по пробелам разорвало бы такой селектор.
    """
    parts: list[str] = []
    buffer: list[str] = []
    quote: str | None = None
    depth = 0

    for char in chunk:
        if quote:
            buffer.append(char)
            if char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
            buffer.append(char)
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth = max(depth - 1, 0)
        if char.isspace() and depth == 0:
            if buffer:
                parts.append("".join(buffer))
                buffer = []
            continue
        buffer.append(char)

    if buffer:
        parts.append("".join(buffer))
    return parts


# Динамические части и служебные символы в значениях атрибутов.
# Пробел внутри значения атрибута встречается редко, поэтому комбинаторы можно
# разбирать по пробелам; при необходимости значение берётся в кавычки.


def _parse_compound(chunk: str) -> Compound | None:
    """Разбирает один составной селектор."""
    text = chunk.strip()
    if not text:
        return None

    compound = Compound()
    position = 0
    matched_any = False

    while position < len(text):
        match = COMPOUND_RE.match(text, position)
        if match is None or match.end() == position:
            # Непонятный символ — селектор не поддерживается.
            return None
        matched_any = True
        position = match.end()

        if match.group("tag"):
            compound.tag = match.group("tag").lower()
        elif match.group("id"):
            compound.node_id = match.group("id")
        elif match.group("cls"):
            compound.classes.append(match.group("cls"))
        elif match.group("attr"):
            value = match.group("dq")
            if value is None:
                value = match.group("sq")
            if value is None:
                value = match.group("bare")
                if value is not None:
                    value = value.strip()
            operator = match.group("op")
            if operator and operator not in ATTR_OPERATORS:
                return None
            compound.attributes.append((match.group("attr").lower(), operator, value))
        elif match.group("pseudo"):
            compound.pseudos.append((match.group("pseudo"), int(match.group("pseudo_arg"))))
        elif match.group("universal"):
            pass

    return compound if matched_any else None


@dataclass
class MatchReport:
    """Результат проверки селектора."""

    selector: str
    valid: bool
    count: int
    visible_count: int
    nodes: list[Node] = field(default_factory=list)
    error: str | None = None

    @property
    def unique(self) -> bool:
        return self.count == 1

    def sample(self, limit: int = 5) -> list[dict[str, Any]]:
        """Краткие сведения о найденных узлах — для панели проверки."""
        return [
            {
                "tag": node.tag,
                "text": node.all_text(limit=80),
                "path": node.css_path(),
                "classes": node.classes,
                "hidden": node.hidden,
            }
            for node in self.nodes[:limit]
        ]

    def as_dict(self) -> dict[str, Any]:
        return {
            "selector": self.selector,
            "valid": self.valid,
            "count": self.count,
            "visible_count": self.visible_count,
            "unique": self.unique,
            "error": self.error,
            "samples": self.sample(),
        }


def resolve(root: Node, selector: str) -> MatchReport:
    """Находит узлы по селектору и собирает отчёт.

    Жадные селекторы вида ``div span`` на реальных страницах находят десятки
    узлов. Редактору и движку извлечения это знать обязательно: «нашли 3 из 24»
    и «нашли 24 из 24» — совершенно разные ситуации, и пользователь должен
    видеть разницу.
    """
    parsed = parse_selector(selector)
    if not parsed.valid:
        return MatchReport(
            selector=selector,
            valid=False,
            count=0,
            visible_count=0,
            error="селектор не поддерживается",
        )

    try:
        nodes = parsed.matching_nodes(root)
    except Exception as exc:  # noqa: BLE001 — защита от неожиданного селектора
        return MatchReport(
            selector=selector,
            valid=False,
            count=0,
            visible_count=0,
            error=f"ошибка разбора: {type(exc).__name__}",
        )

    return MatchReport(
        selector=selector,
        valid=True,
        count=len(nodes),
        visible_count=len([node for node in nodes if not node.hidden]),
        nodes=nodes,
    )


def count_matches(root: Node, selector: str) -> int:
    """Сколько узлов находит селектор. 0 — селектор не работает."""
    return resolve(root, selector).count


def first_match(root: Node, selector: str) -> Node | None:
    """Первый подходящий узел или ``None``."""
    report = resolve(root, selector)
    return report.nodes[0] if report.nodes else None


def iter_matches(root: Node, selector: str) -> Iterator[Node]:
    """Перебор подходящих узлов — основа извлечения данных (Этап 4)."""
    yield from resolve(root, selector).nodes


def compare_selectors(root: Node, selectors: list[str]) -> dict[str, MatchReport]:
    """Проверяет список селекторов: удобно для показа кандидатов в редакторе."""
    return {selector: resolve(root, selector) for selector in selectors}
