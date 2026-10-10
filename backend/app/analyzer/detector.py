"""Детерминированный анализ страницы: что на ней есть и за что отвечает.

Этот модуль работает всегда, даже без ИИ-модели, и делает основную часть работы:

* находит повторяющиеся контейнеры — карточки товаров, строки таблиц, ленты;
* размечает поля, кнопки и ссылки по атрибутам и ключевым словам;
* определяет пагинацию, «показать ещё», фильтры и сортировку;
* отделяет основной контент от шапки, меню и подвала;
* собирает зацепки для модели: сколько чего нашлось и где.

Модель подключается позже и только уточняет формулировки — базовое понимание
страницы от неё не зависит.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.analyzer.domlite import Document, Node, marker_counts, parse
from app.analyzer.roles import (
    DATA_ROLES,
    UTILITY_CLASS_RE,
    Element,
    Role,
    build_selectors,
    guess_roles,
    label_for,
    looks_generated,
)

# Поля ввода, которые имеет смысл описывать.
INPUT_TAGS = {"input", "select", "textarea"}
# Кнопки и ссылки, которые не являются данными.
ACTION_TAGS = {"button", "a"}
# Теги-кандидаты в контейнеры повторов.
CONTAINER_TAGS = {"div", "ul", "ol", "tbody", "section", "article", "main", "nav", "table", "dl"}
# Минимальный размер группы, чтобы считать её списком. Три элемента — уже лента.
MIN_GROUP = 3


@dataclass
class RepeatGroup:
    """Группа структурно одинаковых элементов — то есть список."""

    container: Node
    items: list[Node]
    signature: str
    similarity: float
    # Полный размер списка. Совпадает с числом найденных элементов, если список
    # не схлопывался обрезкой DOM.
    total_count: int | None = None

    @property
    def count(self) -> int:
        return len(self.items)

    @property
    def real_count(self) -> int:
        """Размер списка на исходной странице."""
        return self.total_count or self.count

    @property
    def collapsed(self) -> int:
        """Сколько элементов не попало в обрезанный DOM."""
        return max(self.real_count - self.count, 0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "count": self.real_count,
            "items_in_dom": self.count,
            "collapsed": self.collapsed,
            "signature": self.signature,
            "similarity": round(self.similarity, 3),
            "container_path": self.container.css_path(),
            "container_tag": self.container.tag,
            "container_classes": self.container.classes,
            "sample_text": self.items[0].all_text(limit=160) if self.items else None,
        }


@dataclass
class PageAnalysis:
    """Результат детерминированного анализа страницы."""

    title: str | None
    lang: str | None
    meta: dict[str, str]
    counts: dict[str, int]
    elements: list[Element] = field(default_factory=list)
    repeats: list[RepeatGroup] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def data_elements(self) -> list[Element]:
        """Элементы, из которых собираются данные."""
        return [item for item in self.elements if item.role in DATA_ROLES]

    @property
    def best_repeat(self) -> RepeatGroup | None:
        return self.repeats[0] if self.repeats else None

    def summary(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "lang": self.lang,
            "elements": len(self.elements),
            "repeats": len(self.repeats),
            "data_elements": len(self.data_elements),
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Поиск повторяющихся блоков
# ---------------------------------------------------------------------------


def _text_shape(node: Node) -> str:
    """Форма текста элемента: цифры заменяются на #, буквы — на a.

    Нужна, чтобы «Товар 1» и «Товар 2» считались похожими, а «Товар» и «Цена» —
    нет.
    """
    text = node.all_text(limit=40)
    if not text:
        return ""
    shaped = "".join("#" if char.isdigit() else "a" if char.isalpha() else " " for char in text)
    return " ".join(shaped.split())[:24]


def _structure(node: Node, depth: int = 2) -> str:
    """Структурная подпись поддерева: теги и классы на несколько уровней вниз."""

    def walk(current: Node, level: int) -> str:
        if level > depth:
            return ""
        parts = [current.signature]
        for child in current.children[:6]:
            nested = walk(child, level + 1)
            if nested:
                parts.append(f"({nested})")
        return " ".join(parts)

    return walk(node, 1)


def similarity(left: Node, right: Node) -> float:
    """Насколько два элемента похожи по структуре и форме текста.

    Сравниваются три вещи: подпись тега с классами, структура поддерева и форма
    текста. Значения складываются с весами — структура важнее текста.
    """
    score = 0.0
    if left.signature == right.signature:
        score += 0.4
    elif left.tag == right.tag:
        score += 0.15

    left_structure, right_structure = _structure(left), _structure(right)
    if left_structure == right_structure:
        score += 0.35
    else:
        left_parts, right_parts = set(left_structure.split()), set(right_structure.split())
        if left_parts and right_parts:
            overlap = len(left_parts & right_parts) / len(left_parts | right_parts)
            score += 0.35 * overlap

    if _text_shape(left) and _text_shape(left) == _text_shape(right):
        score += 0.25
    elif left.children and len(left.children) == len(right.children):
        score += 0.1

    return min(score, 1.0)


def find_repeat_groups(document: Document, *, limit: int = 8) -> list[RepeatGroup]:
    """Находит списки: контейнеры с группой похожих детей.

    Именно это превращает «набор div-ов» в понятие «каталог из 24 карточек».
    Группы собираются для каждого контейнера, затем сортируются по размеру и
    похожести: самая крупная и однородная группа и есть основной список.
    """
    groups: list[RepeatGroup] = []

    for container in document.iter_nodes():
        if container.tag not in CONTAINER_TAGS or container.hidden:
            continue
        children = [child for child in container.children if child.tag not in {"script", "style"}]
        if len(children) < MIN_GROUP:
            continue

        # Группируем подряд идущих детей по подписи: список может состоять из
        # нескольких видов карточек (товар + реклама), но обычно он однороден.
        by_signature: dict[str, list[Node]] = {}
        for child in children:
            by_signature.setdefault(child.signature, []).append(child)

        for signature, items in by_signature.items():
            if len(items) < MIN_GROUP:
                continue

            # Проверяем однородность: сравниваем каждый элемент с первым.
            scores = [similarity(items[0], item) for item in items[1:]]
            mean = sum(scores) / len(scores) if scores else 1.0
            if mean < 0.5:
                continue

            groups.append(
                RepeatGroup(
                    container=container,
                    items=items,
                    signature=signature,
                    similarity=mean,
                )
            )

    # Отбрасываем вложенные группы: если элементы одной группы целиком входят в
    # другую, это одна и та же сущность, увиденная на разных уровнях.
    groups.sort(key=lambda group: (group.count, group.similarity), reverse=True)
    filtered: list[RepeatGroup] = []
    for group in groups:
        item_paths = {item.css_path() for item in group.items}
        if any(
            item_paths and item_paths <= {item.css_path() for item in kept.items}
            for kept in filtered
        ):
            continue
        if any(kept.container is group.container for kept in filtered):
            continue
        filtered.append(group)
        if len(filtered) >= limit * 2:
            break

    # Сортируем по качеству списка, а не по размеру: «основной каталог» — это та
    # группа, где почти все дети контейнера однородны. Иначе случайная подборка из
    # трёх похожих блоков обгоняла бы каталог из двенадцати карточек.
    filtered.sort(key=_group_score, reverse=True)
    return filtered[:limit]


def _group_score(group: RepeatGroup) -> float:
    """Оценка группы повторов как списка данных.

    Учитывает три вещи:

    * **сколько** элементов в группе — большой список интереснее;
    * **насколько** они похожи друг на друга;
    * **какая доля** детей контейнера попала в группу: в настоящем каталоге почти
      все дети — карточки, а в контейнере с разным содержимым карточек мало.
    """
    children = [child for child in group.container.children if child.tag not in {"script", "style"}]
    density = group.count / len(children) if children else 0.0
    return group.count * 0.05 + group.similarity * 3.0 + density


# ---------------------------------------------------------------------------
# Разметка элементов
# ---------------------------------------------------------------------------


def _role_confidence(
    role: Role, node: Node, *, in_repeat: bool, count: int, tag: str | None = None
) -> float:
    """Насколько уверенно роль присвоена элементу."""
    base = 0.5
    actual_tag = tag or node.tag
    # Точное совпадение с тегом и типом — сильный признак.
    if (
        role == Role.SEARCH_INPUT
        and node.get("type").lower() == "search"
        or role == Role.PASSWORD_INPUT
        and node.get("type").lower() == "password"
        or role == Role.EMAIL_INPUT
        and node.get("type").lower() == "email"
    ):
        base = 0.95
    elif (
        role == Role.TABLE
        and actual_tag == "table"
        or role == Role.TABLE_ROW
        and actual_tag == "tr"
    ):
        base = 0.9
    elif role == Role.LIST_ITEM and actual_tag == "li":
        base = 0.75
    elif role == Role.LINK and actual_tag == "a":
        base = 0.7
    elif role == Role.HEADING and actual_tag.startswith("h"):
        base = 0.9
    elif role in {Role.TEXT_INPUT, Role.SELECT, Role.TEXTAREA}:
        base = 0.8
    elif role in {Role.PAGINATION, Role.PAGINATION_NEXT, Role.PAGINATION_PREV}:
        base = 0.85
    elif role == Role.LOAD_MORE:
        base = 0.8
    elif role == Role.LIST_CONTAINER and actual_tag in {"ul", "ol"}:
        base = 0.85

    # rel="next"/"prev" — машинный признак пагинации, сильнее любых классов.
    if role in {Role.PAGINATION_NEXT, Role.PAGINATION_PREV} and node.get("rel"):
        base = max(base, 0.9)

    # Признаки из атрибутов добавляют уверенности.
    if node.get("itemprop"):
        base += 0.05
    if node.get("aria-label") or node.get("name"):
        base += 0.05
    if in_repeat and role in DATA_ROLES:
        base += 0.1
    if count > 1 and role in DATA_ROLES:
        base += 0.05

    return round(min(base, 0.99), 3)


def _element_from_node(
    node: Node,
    role: Role,
    *,
    count: int,
    in_repeat: bool,
    description: str = "",
    selector_override: tuple[str, list] | None = None,
    tag_override: str | None = None,
) -> Element:
    """Собирает описание элемента из узла.

    ``selector_override`` и ``tag_override`` нужны для полей внутри карточек:
    адрес берётся у карточки (у неё осмысленный класс), а содержимое и подпись —
    у конкретного поля.
    """
    if selector_override is not None:
        selector, candidates = selector_override
    else:
        selector, candidates = build_selectors(node, replicas=count)
    sample = node.all_text(limit=80) or None
    if role in {Role.TEXT_INPUT, Role.SEARCH_INPUT, Role.EMAIL_INPUT, Role.PHONE_INPUT}:
        sample = node.get("placeholder") or node.get("value") or sample
    elif node.tag == "img":
        sample = node.get("alt") or node.get("src")
    elif node.tag == "a":
        sample = node.get("href") or sample

    return Element(
        role=role,
        selector=selector,
        candidates=candidates,
        label=label_for(role),
        description=description or f"{label_for(role)} на странице",
        confidence=_role_confidence(role, node, in_repeat=in_repeat, count=count, tag=tag_override),
        count=count,
        sample=sample,
        tag=tag_override or node.tag,
        node_path=node.css_path(),
        attrs={
            key: value
            for key, value in node.attrs.items()
            if key
            in {
                "name",
                "type",
                "id",
                "class",
                "placeholder",
                "aria-label",
                "href",
                "itemprop",
                "rel",
            }
        },
    )


def _has_own_anchor(node: Node) -> bool:
    """Есть ли у элемента собственный устойчивый признак для селектора.

    ``itemprop``, ARIA-имя или говорящий класс (``product-card__price``) позволяют
    искать поле напрямую. Если ничего этого нет, надёжнее опираться на контейнер
    карточки: он одинаков для всего списка.
    """
    if node.get("itemprop") or node.get("aria-label") or node.get("data-testid"):
        return True
    useful = [
        item
        for item in node.classes
        if not UTILITY_CLASS_RE.match(item) and not looks_generated(item) and len(item) > 3
    ]
    return bool(useful)


def _apply_marker_counts(groups: list[RepeatGroup], html: str) -> None:
    """Проставляет группам полный размер списка из пометок обрезки.

    Пометки идут в том же порядке, в каком группы схлопывались (самые крупные
    первыми), поэтому сопоставляем их по убыванию размера и берём только те, что
    действительно больше числа оставшихся элементов.
    """
    counts = sorted((count for count in marker_counts(html) if count > 0), reverse=True)
    if not counts:
        return
    for group, total in zip(
        sorted(groups, key=lambda item: item.count, reverse=True), counts, strict=False
    ):
        if total > group.count:
            group.total_count = total


def _pagination_description(node: Node) -> str:
    text = node.all_text(limit=40) or node.get("aria-label") or node.get("rel")
    return f"Переход по страницам: {text}" if text else "Переход по страницам"


def analyze_document(document: Document, *, max_elements: int = 200) -> PageAnalysis:
    """Размечает страницу: элементы, списки, пагинация, предупреждения."""
    warnings: list[str] = []
    elements: list[Element] = []
    seen_paths: set[str] = set()

    repeats = find_repeat_groups(document)
    # Обрезка DOM схлопывает длинные списки, оставляя несколько примеров, и
    # сохраняет полный размер в пометке. Проставляем эти числа группам, чтобы
    # карта говорила о 12 карточках, а не о трёх оставшихся.
    _apply_marker_counts(repeats, document.html)
    # Пути элементов, входящих в найденные списки — понадобится для ролей.
    repeat_paths: dict[str, RepeatGroup] = {}
    for group in repeats:
        for item in group.items:
            repeat_paths[item.css_path()] = group

    # --- Списки -------------------------------------------------------------
    for group in repeats:
        container = group.container
        total = group.real_count
        collapsed = group.collapsed
        description = (
            f"Список из {total} однотипных элементов " f"(похожесть {group.similarity:.0%})"
        )
        if collapsed:
            description += (
                f". В обрезанном DOM оставлено {group.count}: "
                f"остальные скрыты для экономии контекста"
            )
        element = _element_from_node(
            container,
            Role.LIST_CONTAINER,
            count=total,
            in_repeat=False,
            description=description,
        )
        element.repeat_signature = group.signature
        element.sample = group.items[0].all_text(limit=80) if group.items else None
        elements.append(element)
        seen_paths.add(container.css_path())

        # Поля внутри карточки: название, цена, ссылка, картинка.
        sample_item = group.items[0]
        for child in sample_item.walk():
            if child is sample_item:
                continue
            if child.tag in {"h1", "h2", "h3", "h4", "a", "img", "span", "p", "div", "time", "td"}:
                for role in guess_roles(child):
                    if role not in DATA_ROLES or role is Role.LIST_ITEM:
                        continue
                    # Если у поля есть собственный осмысленный признак (itemprop,
                    # aria-label, говорящий класс), ищем по нему; иначе — по
                    # контейнеру карточки, который одинаков для всего списка.
                    if _has_own_anchor(child):
                        selector, candidates = build_selectors(child, replicas=total)
                        tag_value = child.tag
                    else:
                        selector, candidates = build_selectors(sample_item, replicas=total)
                        tag_value = sample_item.tag
                    key = f"repeat:{group.signature}:{role.value}"
                    if key in seen_paths:
                        break
                    seen_paths.add(key)
                    elements.append(
                        _element_from_node(
                            child,
                            role,
                            count=total,
                            in_repeat=True,
                            description=f"{label_for(role)} внутри элемента списка",
                            selector_override=(selector, candidates),
                            tag_override=tag_value,
                        )
                    )
                    break

    # --- Поля ввода и формы -------------------------------------------------
    for node in document.find_all(*INPUT_TAGS):
        if node.tag == "input" and node.get("type").lower() in {"hidden", "submit", "button"}:
            continue
        # Роли добавляются все: select с именем sort — это и «выпадающий список»,
        # и «сортировка». Пользователю важно видеть оба смысла.
        for role in guess_roles(node):
            if role is Role.UNKNOWN:
                continue
            elements.append(_element_from_node(node, role, count=1, in_repeat=False))
        seen_paths.add(node.css_path())

    # --- Кнопки -------------------------------------------------------------
    buttons = document.find_all("button")
    for node in buttons:
        # Кнопка внутри карточки — это действие карточки, не общий элемент.
        if node.css_path() in repeat_paths:
            continue
        roles = guess_roles(node)
        role = (
            Role.SUBMIT
            if Role.SUBMIT in roles
            else (Role.LOAD_MORE if Role.LOAD_MORE in roles else Role.BUTTON)
        )
        text = node.all_text(limit=40)
        elements.append(
            _element_from_node(
                node,
                role,
                count=1,
                in_repeat=False,
                description=f"Кнопка «{text}»" if text else "Кнопка",
            )
        )

    # --- Пагинация и переходы ----------------------------------------------
    for node in document.find_all("a"):
        roles = guess_roles(node)
        if Role.LIST_ITEM in roles:
            continue
        for role in roles:
            if role in {Role.PAGINATION, Role.PAGINATION_NEXT, Role.PAGINATION_PREV}:
                elements.append(
                    _element_from_node(
                        node,
                        role,
                        count=1,
                        in_repeat=False,
                        description=_pagination_description(node),
                    )
                )
                break

    # --- Таблицы ------------------------------------------------------------
    for table in document.find_all("table"):
        selector, candidates = build_selectors(table)
        rows = table.find_all("tr")
        # Первая строка часто заголовочная.
        body_rows = [row for row in rows if not row.find_all("th")]
        elements.append(
            Element(
                role=Role.TABLE,
                selector=selector,
                candidates=candidates,
                label=label_for(Role.TABLE),
                description=f"Таблица: {len(rows)} строк, {len(body_rows)} с данными",
                confidence=0.9,
                count=len(rows),
                sample=", ".join(
                    cell.all_text(limit=20)
                    for cell in (rows[0].find_all("th", "td")[:5] if rows else [])
                )
                or None,
                tag="table",
                node_path=table.css_path(),
            )
        )

    # --- Шапка, подвал, меню ------------------------------------------------
    for tag, role in (("header", Role.HEADER), ("footer", Role.FOOTER), ("nav", Role.NAVIGATION)):
        for node in document.find_all(tag)[:2]:
            elements.append(_element_from_node(node, role, count=1, in_repeat=False))

    # --- Заголовки ----------------------------------------------------------
    headings = document.find_all("h1", "h2", "h3")[:5]
    for node in headings:
        text = node.all_text(limit=80)
        if not text:
            continue
        elements.append(
            _element_from_node(
                node,
                Role.HEADING,
                count=1,
                in_repeat=False,
                description=f"Заголовок «{text}»",
            )
        )

    # --- Скрытый контент и другие предупреждения ----------------------------
    hidden_inputs = [
        node for node in document.all_nodes("input") if node.get("type").lower() == "hidden"
    ]
    if hidden_inputs:
        warnings.append(
            f"На странице {len(hidden_inputs)} скрытых полей — часть данных может "
            f"подставляться скриптами"
        )
    if not repeats:
        warnings.append(
            "Повторяющихся блоков не найдено: вероятно, это одиночная страница, " "а не список"
        )
    if not document.find_all("input", "select", "textarea"):
        warnings.append("Полей ввода не найдено: взаимодействие со страницей ограничено")

    # Убираем дубликаты: один и тот же селектор с одной ролью. Общая роль
    # LIST_ITEM не должна перекрывать конкретные поля карточки.
    unique: list[Element] = []
    seen_keys: set[tuple[str, str]] = set()
    seen_specific: set[str] = set()
    for element in elements:
        key = (element.role.value, element.selector)
        if key in seen_keys:
            continue
        if element.role is Role.LIST_ITEM and element.selector in seen_specific:
            continue
        if element.role is not Role.LIST_ITEM:
            seen_specific.add(element.selector)
        seen_keys.add(key)
        unique.append(element)

    # Сортируем по важности: данные и списки вперёд, служебное в конец.
    priority = {
        Role.LIST_CONTAINER: 0,
        Role.TABLE: 1,
        Role.SEARCH_INPUT: 2,
        Role.PAGINATION_NEXT: 3,
        Role.PAGINATION: 4,
        Role.LOAD_MORE: 5,
    }
    unique.sort(
        key=lambda item: (
            priority.get(item.role, 10 if item.role not in DATA_ROLES else 6),
            -item.confidence,
        )
    )

    return PageAnalysis(
        title=document.title(),
        lang=document.lang(),
        meta=document.meta(),
        counts=document.counts(),
        elements=unique[:max_elements],
        repeats=repeats,
        warnings=warnings,
    )


def analyze_html(html: str, *, max_elements: int = 200) -> PageAnalysis:
    """Разбирает HTML и сразу размечает его."""
    return analyze_document(parse(html), max_elements=max_elements)


def build_report(analysis: PageAnalysis) -> str:
    """Человекочитаемый отчёт о странице.

    Формулировки сознательно простые: отчёт читает пользователь, который не
    обязан знать про DOM и селекторы.
    """
    lines: list[str] = []
    title = analysis.title or "(без заголовка)"
    lines.append(f"Страница: {title}")
    if analysis.lang:
        lines.append(f"Язык: {analysis.lang}")
    if analysis.meta.get("description"):
        lines.append(f"Описание: {analysis.meta['description'][:200]}")
    lines.append("")

    best = analysis.best_repeat
    if best is not None:
        sample = best.items[0].all_text(limit=100) if best.items else ""
        lines.append(
            f"Найден список: {best.real_count} однотипных элементов "
            f"(похожесть {best.similarity:.0%})."
        )
        if best.collapsed:
            lines.append(
                f"  В обрезанном DOM оставлено {best.count} элемента — остальные "
                f"скрыты, чтобы уложиться в контекст модели."
            )
        if sample:
            lines.append(f"  Пример элемента: {sample}")
        container = best.container
        container_name = (
            f"<{container.tag} class=\"{' '.join(container.classes)}\">"
            if container.classes
            else f"<{container.tag}>"
        )
        lines.append(f"  Контейнер: {container_name}")
        if len(analysis.repeats) > 1:
            others = ", ".join(f"{group.real_count} элементов" for group in analysis.repeats[1:4])
            lines.append(f"  Другие группы повторов: {others}")
    else:
        lines.append("Списков на странице не найдено.")

    lines.append("")
    by_role: dict[str, list[Element]] = {}
    for element in analysis.elements:
        by_role.setdefault(element.role.value, []).append(element)

    interesting = [
        Role.LIST_CONTAINER,
        Role.SEARCH_INPUT,
        Role.PAGINATION_NEXT,
        Role.PAGINATION,
        Role.LOAD_MORE,
        Role.FILTER,
        Role.SORT,
        Role.SUBMIT,
        Role.TABLE,
    ]
    lines.append("Что можно делать со страницей:")
    described = 0
    for role in interesting:
        group = by_role.get(role.value)
        if not group:
            continue
        described += 1
        element = group[0]
        lines.append(
            f"  • {element.label}: {element.description} " f"(уверенность {element.confidence:.0%})"
        )
    if described == 0:
        lines.append("  • явных точек взаимодействия не найдено")

    fields = [
        element
        for element in analysis.elements
        if element.role
        in {
            Role.SEARCH_INPUT,
            Role.TEXT_INPUT,
            Role.EMAIL_INPUT,
            Role.PHONE_INPUT,
            Role.SELECT,
            Role.TEXTAREA,
            Role.CHECKBOX,
            Role.RADIO,
            Role.DATE_INPUT,
            Role.NUMBER_INPUT,
            Role.FILE_INPUT,
        }
    ]
    if fields:
        lines.append("")
        lines.append(f"Поля ввода ({len(fields)}):")
        for element in fields[:10]:
            sample = f" — «{element.sample}»" if element.sample else ""
            lines.append(f"  • {element.label}{sample} → {element.selector}")

    data_elements = analysis.data_elements
    if data_elements:
        lines.append("")
        lines.append(f"Данные, которые можно собирать ({len(data_elements)} полей):")
        for element in data_elements[:12]:
            lines.append(
                f"  • {element.label}: {element.description}"
                + (f" — пример «{element.sample}»" if element.sample else "")
            )

    if analysis.warnings:
        lines.append("")
        lines.append("На что обратить внимание:")
        for warning in analysis.warnings:
            lines.append(f"  • {warning}")

    return "\n".join(lines)
