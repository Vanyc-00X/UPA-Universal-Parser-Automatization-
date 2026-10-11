"""Инспектор элементов: DOM в виде списка узлов с адресами и рамками.

Нужен визуальному редактору (Этап 3). Пользователь видит страницу и список её
элементов, может навести на строку и понять, о каком блоке речь, а также выбрать
элемент мышью на странице — для этого каждый узел получает идентификатор,
который фронтенд сопоставляет с областью на скриншоте.

Рамки вычисляются оценкой: точная геометрия требует реального браузера, а здесь
нужен лишь ориентир. Оценка достаточна, чтобы подсветить элемент и показать его
место на странице.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.analyzer.domlite import Node, parse
from app.analyzer.roles import Role, guess_roles, label_for
from app.editor.resolver import resolve

# Теги, которые имеет смысл показывать в инспекторе: контейнеры, поля, ссылки,
# картинки, таблицы. Служебная мелочь вида <b> и <i> только засоряет список.
INTERESTING_TAGS = {
    "div",
    "section",
    "article",
    "main",
    "header",
    "footer",
    "nav",
    "aside",
    "form",
    "ul",
    "ol",
    "li",
    "dl",
    "dt",
    "dd",
    "table",
    "thead",
    "tbody",
    "tr",
    "td",
    "th",
    "a",
    "button",
    "input",
    "select",
    "textarea",
    "img",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "span",
    "time",
    "label",
}

# Теги, которые в потоке страницы занимают отдельную строку.
BLOCK_TAGS = {
    "div",
    "section",
    "article",
    "main",
    "header",
    "footer",
    "nav",
    "aside",
    "form",
    "ul",
    "ol",
    "li",
    "table",
    "thead",
    "tbody",
    "tr",
    "dl",
    "dt",
    "dd",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "figure",
    "blockquote",
    "pre",
}

# Оценка высоты строки для разных элементов — грубая, но достаточная для подсветки.
LINE_HEIGHT = 20
DEFAULT_PADDING = 8


@dataclass
class InspectNode:
    """Узел страницы в том виде, в каком его показывает инспектор."""

    node_id: str
    tag: str
    role: str
    label: str
    text: str
    selector: str
    path: str
    depth: int
    parent_id: str | None
    children_ids: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    attrs: dict[str, str] = field(default_factory=dict)
    hidden: bool = False
    # Оценка положения на странице: по ней рисуется рамка поверх скриншота.
    box: dict[str, int] = field(default_factory=dict)
    matched_by: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "tag": self.tag,
            "role": self.role,
            "label": self.label,
            "text": self.text,
            "selector": self.selector,
            "path": self.path,
            "depth": self.depth,
            "parent_id": self.parent_id,
            "children_ids": self.children_ids,
            "classes": self.classes,
            "attrs": self.attrs,
            "hidden": self.hidden,
            "box": self.box,
            "matched_by": self.matched_by,
        }


@dataclass
class InspectorResult:
    """Результат обхода страницы."""

    nodes: list[InspectNode]
    total: int
    page: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "nodes": [node.as_dict() for node in self.nodes],
            "total": self.total,
            "page": self.page,
        }


def assign_ids(root: Node) -> dict[str, Node]:
    """Присваивает узлам короткие идентификаторы и возвращает словарь.

    Идентификатор строится из пути узла: он стабилен между запросами и не
    зависит от порядка обхода.
    """
    mapping: dict[str, Node] = {}
    for node in root.walk():
        if node is root:
            continue
        mapping[node_id_for(node)] = node
    return mapping


def node_id_for(node: Node) -> str:
    """Идентификатор узла по его пути в дереве."""
    return f"n{'-'.join(str(part) for part in node.path)}" if node.path else "n"


def estimate_boxes(root: Node) -> dict[str, dict[str, int]]:
    """Оценивает положение и размер элементов в потоке страницы.

    Точную геометрию даёт только браузер. Здесь считается упрощённая раскладка:
    блочные элементы занимают строку целиком, строчные идут подряд, высота
    зависит от числа строк текста и вложенных элементов. Этого достаточно, чтобы
    подсветить элемент и показать, где он находится.
    """
    boxes: dict[str, dict[str, int]] = {}
    width = 1440
    _layout(root, 0, 0, width, boxes)
    return boxes


def _text_lines(node: Node, width: int) -> int:
    """Сколько строк занимает текст элемента."""
    text = node.own_text
    if not text:
        return 0
    chars_per_line = max(width // 8, 10)
    return max(1, (len(text) + chars_per_line - 1) // chars_per_line)


def _layout(
    node: Node,
    x: int,
    y: int,
    width: int,
    boxes: dict[str, dict[str, int]],
) -> int:
    """Раскладывает поддерево и возвращает высоту занятой области."""
    if node.hidden or node.tag in {"head", "script", "style", "meta", "link"}:
        return 0

    # Корень документа и <html> лишь обёртки: раскладываем их детей в том же
    # месте, иначе обход останавливается и вся страница остаётся без рамок.
    if node.tag in {"#document", "html"}:
        total = 0
        cursor = y
        for child in node.children:
            cursor += _layout(child, x, cursor, width, boxes)
            total = max(total, cursor)
        return total

    padding = DEFAULT_PADDING if node.tag in INTERESTING_TAGS else 0
    inner_x = x + padding
    inner_width = max(width - padding * 2, 40)

    top = y
    cursor_y = y + padding
    inline_x = inner_x
    inline_height = 0
    max_bottom = cursor_y

    for child in node.children:
        if child.tag in {"script", "style"}:
            continue

        if child.tag in BLOCK_TAGS:
            if inline_height:
                cursor_y += inline_height
                inline_x = inner_x
                inline_height = 0
            height = _layout(child, inner_x, cursor_y, inner_width, boxes)
            cursor_y += height
            max_bottom = max(max_bottom, cursor_y)
            continue

        # Строчный элемент: кладём в текущую строку.
        child_width = _estimate_inline_width(child, inner_width)
        if inline_x + child_width > inner_x + inner_width and inline_x > inner_x:
            cursor_y += max(inline_height, LINE_HEIGHT)
            inline_x = inner_x
            inline_height = 0
        height = _layout(child, inline_x, cursor_y, child_width, boxes)
        inline_x += child_width
        inline_height = max(inline_height, height, LINE_HEIGHT)
        max_bottom = max(max_bottom, cursor_y + inline_height)

    own_lines = _text_lines(node, inner_width)
    if own_lines:
        cursor_y += own_lines * LINE_HEIGHT
        max_bottom = max(max_bottom, cursor_y)

    if inline_height:
        cursor_y += inline_height
        max_bottom = max(max_bottom, cursor_y)

    height = max(cursor_y - top + padding, LINE_HEIGHT if node.tag in INTERESTING_TAGS else 0)
    if node.tag in INTERESTING_TAGS:
        boxes[node_id_for(node)] = {
            "x": x,
            "y": top,
            "width": width,
            "height": height,
        }
    return height


def _estimate_inline_width(node: Node, available: int) -> int:
    """Оценка ширины строчного элемента."""
    if node.tag == "img":
        return min(available, 200)
    if node.tag in {"input", "select"}:
        return min(available, 220)
    if node.tag == "button":
        text = node.all_text(limit=30)
        return min(available, max(90, len(text) * 9 + 24))
    text = node.all_text(limit=60)
    if text:
        return min(available, max(60, len(text) * 7))
    return min(available, 120)


def build_inspector(
    html: str,
    *,
    selectors: list[str] | None = None,
    max_nodes: int = 400,
) -> InspectorResult:
    """Строит список узлов страницы для инспектора.

    ``selectors`` — адреса, попавшие в карту элементов. Для каждого узла
    отмечается, какими из них он находится: это превращает инспектор в наглядную
    проверку карты, а не просто список разметки.
    """
    document = parse(html)
    boxes = estimate_boxes(document.root)

    # Заранее считаем совпадения: иначе каждый узел пришлось бы проверять всеми
    # селекторами, а это квадратичная сложность на больших страницах.
    matched: dict[str, list[str]] = {}
    for selector in selectors or []:
        report = resolve(document.root, selector)
        if not report.valid:
            continue
        for node in report.nodes:
            matched.setdefault(node_id_for(node), []).append(selector)

    nodes: list[InspectNode] = []
    for node in document.root.walk():
        if node.tag == "#document" or node.tag not in INTERESTING_TAGS:
            continue
        node_id = node_id_for(node)
        roles = guess_roles(node)
        role = roles[0] if roles else Role.UNKNOWN
        # Родителя ищем по настоящему дереву, пока не встретим показанный узел:
        # между карточкой и каталогом могут стоять служебные обёртки.
        ancestor = node.parent
        while ancestor is not None and ancestor.tag not in INTERESTING_TAGS:
            ancestor = ancestor.parent
        parent_id = node_id_for(ancestor) if ancestor is not None else None
        nodes.append(
            InspectNode(
                node_id=node_id,
                tag=node.tag,
                role=role.value,
                label=label_for(role),
                text=node.all_text(limit=120),
                selector=node.css_path(),
                path=node.css_path(),
                depth=node.depth,
                parent_id=parent_id,
                children_ids=[
                    node_id_for(child) for child in node.children if child.tag in INTERESTING_TAGS
                ],
                classes=node.classes,
                attrs={
                    key: value
                    for key, value in node.attrs.items()
                    if key
                    in {
                        "id",
                        "class",
                        "name",
                        "type",
                        "href",
                        "src",
                        "rel",
                        "itemprop",
                        "aria-label",
                    }
                },
                hidden=node.hidden,
                box=boxes.get(node_id, {}),
                matched_by=matched.get(node_id, []),
            )
        )
        if len(nodes) >= max_nodes:
            break

    page = {"width": 1440, "height": _estimate_page_height(document.root, boxes)}
    return InspectorResult(nodes=nodes, total=len(nodes), page=page)


def _estimate_page_height(root: Node, boxes: dict[str, dict[str, int]]) -> int:
    """Высота страницы по нижней границе самого глубокого элемента."""
    if not boxes:
        return 900
    return max(box["y"] + box["height"] for box in boxes.values())


def sibling_context(html: str, node_id: str, *, window: int = 2) -> dict[str, Any]:
    """Соседи элемента — помогают понять, часть ли это списка.

    Пользователь выбирает элемент и сразу видит, есть ли рядом такие же: если
    есть, это карточка списка, а не одиночный блок.
    """
    document = parse(html)
    mapping = assign_ids(document.root)
    node = mapping.get(node_id)
    if node is None:
        return {"found": False}

    parent = node.parent
    siblings = parent.children if parent else []
    position = next((index for index, item in enumerate(siblings) if item is node), -1)
    similar = [item for item in siblings if item is not node and item.signature == node.signature]

    return {
        "found": True,
        "node_id": node_id,
        "tag": node.tag,
        "classes": node.classes,
        "position": position,
        "siblings": len(siblings),
        "similar_siblings": len(similar),
        "looks_like_list_item": len(similar) >= 2,
        "neighbours": [
            {
                "node_id": node_id_for(item),
                "text": item.all_text(limit=60),
            }
            for item in siblings[max(position - window, 0) : position + window + 1]
            if item is not node
        ],
    }
