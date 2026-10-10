"""Лёгкий HTML-парсер для анализа структуры страницы.

Полноценный CSS-движок здесь не нужен, а зависимости вредны: один и тот же код
разбирает страницы и в тестах, и в работе. Парсер терпим к битой вёрстке — это
его главное свойство, потому что реальные страницы почти всегда содержат
незакрытые теги.

Что даёт дерево:

* поиск элементов по тегам и атрибутам;
* устойчивые пути (``path``) для генерации CSS-селекторов;
* признаки видимости (``hidden``, ``display:none``, ``aria-hidden``);
* подписи (``signature``) для поиска структурно одинаковых элементов — на этом
  строится распознавание списков и карточек.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

# Теги без закрывающей пары.
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

# Содержимое этих тегов не является разметкой.
RAW_TEXT_TAGS = {"script", "style", "template", "noscript"}

TAG_RE = re.compile(r"<(/?)([a-zA-Z][\w:-]*)((?:\s+[^<>]*?)?)(/?)>", re.DOTALL)
ATTR_RE = re.compile(
    r"""([\w:.\-@]+)\s*(?:=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?""",
    re.DOTALL,
)
# Динамические части классов: длинные цифровые счётчики и хэш-подобные хвосты
# (``item-4711``, ``sc-bdVaJa9``). Обязательное условие для хвоста — хотя бы одна
# цифра, поэтому осмысленные имена вида ``product-card`` не затрагиваются.
DYNAMIC_RE = re.compile(
    r"[0-9]{4,}" r"|(?<=[-_])[A-Za-z0-9]*\d[A-Za-z0-9]*",
)


def normalize_space(text: str) -> str:
    """Схлопывает пробелы, как это делает браузер."""
    return re.sub(r"\s+", " ", text).strip()


def parse_attributes(raw: str) -> dict[str, str]:
    """Разбирает строку атрибутов в словарь."""
    attributes: dict[str, str] = {}
    if not raw:
        return attributes
    for match in ATTR_RE.finditer(raw):
        name = match.group(1).lower()
        value = match.group(2)
        if value is None:
            value = match.group(3)
        if value is None:
            value = match.group(4)
        attributes[name] = value if value is not None else ""
    return attributes


def strip_dynamic(value: str) -> str:
    """Убирает из класса динамические части, чтобы похожие элементы совпали."""
    return DYNAMIC_RE.sub("*", value)


# Пометка, которую оставляет обрезка DOM вместо схлопнутых повторов. Она несёт
# полное число элементов списка — иначе анализ обрезанной страницы сообщал бы
# «в списке 3 карточки» вместо 12.
LIST_MARKER_RE = re.compile(
    r"UPA:\s*список из\s+(\d+)\s+однотипных элементов",
    re.IGNORECASE,
)


def marker_counts(html: str) -> list[int]:
    """Полные размеры списков, сохранённые обрезкой DOM."""
    return [int(match) for match in LIST_MARKER_RE.findall(html)]


@dataclass
class Node:
    """Узел DOM."""

    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    text: str = ""
    children: list[Node] = field(default_factory=list)
    parent: Node | None = field(default=None, repr=False)
    index: int = 0
    path: tuple[int, ...] = ()

    # --- Доступ к атрибутам -------------------------------------------------

    def get(self, name: str, default: str = "") -> str:
        return self.attrs.get(name.lower(), default)

    @property
    def classes(self) -> list[str]:
        return [item for item in self.get("class").split() if item]

    @property
    def node_id(self) -> str:
        return self.get("id")

    def has_class(self, *names: str) -> bool:
        lowered = {item.lower() for item in self.classes}
        return any(name.lower() in lowered for name in names)

    # --- Содержимое ---------------------------------------------------------

    @property
    def own_text(self) -> str:
        """Текст, лежащий непосредственно в этом элементе, без вложенных."""
        return normalize_space(self.text)

    def all_text(self, limit: int = 0) -> str:
        """Весь текст поддерева, включая вложенные элементы."""
        chunks: list[str] = []
        for node in self.walk():
            if node.text and node.tag not in RAW_TEXT_TAGS:
                chunks.append(normalize_space(node.text))
        result = normalize_space(" ".join(chunk for chunk in chunks if chunk))
        if limit and len(result) > limit:
            return result[:limit].rstrip() + "…"
        return result

    def walk(self) -> Iterator[Node]:
        """Обход поддерева в глубину, начиная с себя."""
        yield self
        for child in self.children:
            yield from child.walk()

    def find_all(self, *tags: str) -> list[Node]:
        """Все потомки с указанными тегами."""
        wanted = {tag.lower() for tag in tags}
        return [node for node in self.walk() if node is not self and node.tag in wanted]

    def first(self, *tags: str) -> Node | None:
        wanted = {tag.lower() for tag in tags}
        for node in self.walk():
            if node is not self and node.tag in wanted:
                return node
        return None

    # --- Видимость ----------------------------------------------------------

    @property
    def hidden(self) -> bool:
        """Скрыт ли элемент — по атрибутам и инлайновым стилям."""
        if "hidden" in self.attrs:
            return True
        if self.get("aria-hidden").lower() == "true":
            return True
        style = self.get("style").lower().replace(" ", "")
        if "display:none" in style or "visibility:hidden" in style:
            return True
        return self.get("type").lower() == "hidden"

    # --- Структура ----------------------------------------------------------

    @property
    def signature(self) -> str:
        """Подпись для поиска структурно одинаковых элементов.

        Классы сортируются, чтобы порядок в атрибуте не мешал сравнению, а
        динамические части вырезаются: ``item-1234`` и ``item-5678`` должны
        считаться одинаковыми.
        """
        classes = sorted(strip_dynamic(item) for item in self.classes)
        return f"{self.tag}.{'.'.join(classes)}" if classes else self.tag

    @property
    def depth(self) -> int:
        return len(self.path)

    def css_path(self) -> str:
        """Путь от корня: ``html > body > div:nth-child(2)``."""
        parts: list[str] = []
        node: Node | None = self
        while node is not None and node.tag != "#document":
            parts.append(f"{node.tag}:nth-child({node.index + 1})")
            node = node.parent
        return " > ".join(reversed(parts))

    def describe(self) -> dict[str, object]:
        """Краткое описание узла — используется в кандидатах и отчёте."""
        return {
            "tag": self.tag,
            "id": self.node_id or None,
            "classes": self.classes,
            "name": self.get("name") or None,
            "type": self.get("type") or None,
            "text": self.all_text(limit=120) or None,
            "path": self.css_path(),
            "depth": self.depth,
        }


class Document:
    """Разобранный HTML-документ."""

    def __init__(self, root: Node, html: str) -> None:
        self.root = root
        self.html = html

    def iter_nodes(self) -> Iterator[Node]:
        return self.root.walk()

    def find_all(self, *tags: str) -> list[Node]:
        """Видимые элементы с указанными тегами."""
        wanted = {tag.lower() for tag in tags}
        return [
            node
            for node in self.root.walk()
            if node is not self.root and node.tag in wanted and not node.hidden
        ]

    def all_nodes(self, *tags: str) -> list[Node]:
        """Как :meth:`find_all`, но включая скрытые элементы."""
        wanted = {tag.lower() for tag in tags}
        return [node for node in self.root.walk() if node is not self.root and node.tag in wanted]

    def title(self) -> str | None:
        node = self.root.first("title")
        return node.all_text() if node else None

    def lang(self) -> str | None:
        html_node = self.root.first("html")
        return (html_node.get("lang") or None) if html_node else None

    def meta(self) -> dict[str, str]:
        """Метатеги: name/property/itemprop → content."""
        result: dict[str, str] = {}
        for node in self.root.find_all("meta"):
            key = node.get("name") or node.get("property") or node.get("itemprop")
            content = node.get("content")
            if key and content:
                result[key.lower()] = content[:400]
        return result

    def counts(self) -> dict[str, int]:
        """Сколько раз встречается каждый тег — полезно для отчёта."""
        result: dict[str, int] = {}
        for node in self.root.walk():
            if node is self.root:
                continue
            result[node.tag] = result.get(node.tag, 0) + 1
        return result


def parse(html: str) -> Document:
    """Разбирает HTML в дерево.

    Один проход по токенам с явным стеком. Незакрытые теги закрываются
    автоматически: при встрече закрывающего тега ищется ближайший открытый с
    таким именем, всё выше него закрывается принудительно. Так обрабатывается
    подавляющее большинство реальных страниц.
    """
    root = Node(tag="#document")
    stack: list[Node] = [root]
    cursor = 0

    for match in TAG_RE.finditer(html):
        # Если мы всё ещё внутри <script>/<style>, найденный «тег» — это часть
        # текста скрипта (например, строка "<div>"). Пропускаем его, но закрывающий
        # тег самого raw-элемента обязан пройти: иначе он останется на стеке и
        # весь дальнейший разбор будет считаться содержимым скрипта.
        if stack[-1].tag in RAW_TEXT_TAGS:
            closing_raw, raw_name, _attrs, _self = match.groups()
            if not (closing_raw and raw_name.lower() == stack[-1].tag):
                cursor = match.end()
                continue

        # Текст между предыдущим и текущим тегом принадлежит текущему элементу.
        if cursor < match.start():
            stack[-1].text += html[cursor : match.start()]

        closing, raw_tag, raw_attrs, self_closed = match.groups()
        tag = raw_tag.lower()
        after_tag = match.end()

        if closing:
            # Закрываем ближайший открытый тег с таким именем и всё, что выше.
            for depth in range(len(stack) - 1, 0, -1):
                if stack[depth].tag == tag:
                    del stack[depth:]
                    break
            cursor = after_tag
            continue

        node = Node(
            tag=tag,
            attrs=parse_attributes(raw_attrs),
            parent=stack[-1],
            index=len(stack[-1].children),
        )
        node.path = (*stack[-1].path, node.index)
        stack[-1].children.append(node)

        if self_closed or tag in VOID_TAGS:
            cursor = after_tag
            continue

        if tag in RAW_TEXT_TAGS:
            # Содержимое script/style/template разметкой не является, поэтому
            # перепрыгиваем его целиком. Сам элемент кладём на стек: иначе
            # «теги» внутри скрипта (строки вида "<div>") будут разобраны как
            # настоящая разметка.
            end = re.search(rf"</{tag}\s*>", html[after_tag:], re.IGNORECASE)
            stack.append(node)
            cursor = after_tag + end.end() if end is not None else len(html)
            continue

        stack.append(node)
        cursor = after_tag

    if cursor < len(html) and stack[-1].tag not in RAW_TEXT_TAGS:
        stack[-1].text += html[cursor:]

    # Незакрытые теги закрываем принудительно: без этого вложенные списки
    # остаются одной плоской группой детей и структура теряется.
    while len(stack) > 1:
        stack.pop()

    return Document(root=root, html=html)
