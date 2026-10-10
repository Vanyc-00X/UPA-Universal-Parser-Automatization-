"""Роли элементов и построение устойчивых селекторов.

Роль — это ответ на вопрос «за что отвечает элемент» на языке пользователя:
«поле поиска», «карточка товара», «цена», «пагинация». Селектор — машинный
адрес того же элемента.

Главное правило выбора селектора: устойчивость важнее краткости. Предпочтение
отдаётся ``data-*`` и ARIA-атрибутам, штрафуется всё автогенерированное
(``css-1x2y3z``, ``sc-abc123``, ``id="item-4711"``), потому что именно такие
адреса ломаются при следующей сборке фронтенда. Список кандидатов сохраняется
целиком — он станет основой самопочинки сценариев на Этапе 6.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from app.analyzer.domlite import Node


class Role(str, Enum):
    """Роли элементов страницы."""

    SEARCH_INPUT = "search_input"
    SEARCH_FORM = "search_form"
    TEXT_INPUT = "text_input"
    EMAIL_INPUT = "email_input"
    PHONE_INPUT = "phone_input"
    PASSWORD_INPUT = "password_input"
    NUMBER_INPUT = "number_input"
    DATE_INPUT = "date_input"
    FILE_INPUT = "file_input"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    SELECT = "select"
    TEXTAREA = "textarea"
    SUBMIT = "submit"
    BUTTON = "button"
    LINK = "link"
    PAGINATION = "pagination"
    PAGINATION_NEXT = "pagination_next"
    PAGINATION_PREV = "pagination_prev"
    LOAD_MORE = "load_more"
    FILTER = "filter"
    SORT = "sort"
    LIST_CONTAINER = "list_container"
    LIST_ITEM = "list_item"
    ITEM_TITLE = "item_title"
    ITEM_LINK = "item_link"
    ITEM_PRICE = "item_price"
    ITEM_IMAGE = "item_image"
    ITEM_DESCRIPTION = "item_description"
    TABLE = "table"
    TABLE_ROW = "table_row"
    HEADING = "heading"
    NAVIGATION = "navigation"
    HEADER = "header"
    FOOTER = "footer"
    COOKIE_BANNER = "cookie_banner"
    MODAL = "modal"
    UNKNOWN = "unknown"


ROLE_LABELS: dict[Role, str] = {
    Role.SEARCH_INPUT: "Поле поиска",
    Role.SEARCH_FORM: "Форма поиска",
    Role.TEXT_INPUT: "Текстовое поле",
    Role.EMAIL_INPUT: "Поле email",
    Role.PHONE_INPUT: "Поле телефона",
    Role.PASSWORD_INPUT: "Поле пароля",
    Role.NUMBER_INPUT: "Числовое поле",
    Role.DATE_INPUT: "Поле даты",
    Role.FILE_INPUT: "Загрузка файла",
    Role.CHECKBOX: "Флажок",
    Role.RADIO: "Переключатель",
    Role.SELECT: "Выпадающий список",
    Role.TEXTAREA: "Многострочное поле",
    Role.SUBMIT: "Кнопка отправки",
    Role.BUTTON: "Кнопка",
    Role.LINK: "Ссылка",
    Role.PAGINATION: "Пагинация",
    Role.PAGINATION_NEXT: "Следующая страница",
    Role.PAGINATION_PREV: "Предыдущая страница",
    Role.LOAD_MORE: "Показать ещё",
    Role.FILTER: "Фильтр",
    Role.SORT: "Сортировка",
    Role.LIST_CONTAINER: "Контейнер списка",
    Role.LIST_ITEM: "Элемент списка (карточка)",
    Role.ITEM_TITLE: "Название элемента",
    Role.ITEM_LINK: "Ссылка на элемент",
    Role.ITEM_PRICE: "Цена",
    Role.ITEM_IMAGE: "Изображение элемента",
    Role.ITEM_DESCRIPTION: "Описание элемента",
    Role.TABLE: "Таблица",
    Role.TABLE_ROW: "Строка таблицы",
    Role.HEADING: "Заголовок",
    Role.NAVIGATION: "Навигация",
    Role.HEADER: "Шапка страницы",
    Role.FOOTER: "Подвал страницы",
    Role.COOKIE_BANNER: "Баннер о cookie",
    Role.MODAL: "Модальное окно",
    Role.UNKNOWN: "Неизвестный элемент",
}

# Роли, которые «размножаются»: в списке таких элементов много.
REPEATING_ROLES = {
    Role.LIST_ITEM,
    Role.TABLE_ROW,
    Role.ITEM_TITLE,
    Role.ITEM_LINK,
    Role.ITEM_PRICE,
    Role.ITEM_IMAGE,
}

# Роли, которые имеет смысл собирать как данные.
DATA_ROLES = {
    Role.ITEM_TITLE,
    Role.ITEM_LINK,
    Role.ITEM_PRICE,
    Role.ITEM_IMAGE,
    Role.ITEM_DESCRIPTION,
    Role.LIST_ITEM,
    Role.TABLE_ROW,
}


def label_for(role: Role) -> str:
    """Человекочитаемое название роли."""
    return ROLE_LABELS.get(role, role.value)


# ---------------------------------------------------------------------------
# Ключевые слова: по ним роль угадывается без модели
# ---------------------------------------------------------------------------

# Порядок важен: первое совпадение выигрывает, поэтому специфичные признаки идут
# раньше общих. Цена проверяется до названия, иначе класс «price-row__price»
# распознавался бы как название из-за подстроки в родительском имени.
ROLE_KEYWORDS: tuple[tuple[Role, tuple[str, ...]], ...] = (
    (Role.SEARCH_INPUT, ("search", "q", "query", "поиск", "найти", "s")),
    (Role.EMAIL_INPUT, ("email", "e-mail", "mail", "почта")),
    (Role.PHONE_INPUT, ("phone", "tel", "mobile", "телефон")),
    (Role.PASSWORD_INPUT, ("password", "passwd", "pwd", "пароль")),
    (Role.ITEM_PRICE, ("price", "cost", "amount", "цена", "стоимость", "сумма")),
    (Role.ITEM_IMAGE, ("image", "img", "photo", "thumb", "picture", "картинк", "фото")),
    (Role.ITEM_LINK, ("link", "url", "permalink", "ссылка")),
    (Role.ITEM_TITLE, ("title", "name", "heading", "название", "наименование", "заголовок")),
    (Role.ITEM_DESCRIPTION, ("description", "summary", "excerpt", "описание", "аннотация")),
    (Role.PAGINATION_NEXT, ("next", "forward", "следующ", "вперёд", "вперед")),
    (Role.PAGINATION_PREV, ("prev", "previous", "back", "предыдущ", "назад")),
    (Role.PAGINATION, ("pagination", "pager", "pages", "пагинац", "страниц")),
    (Role.LOAD_MORE, ("load-more", "loadmore", "show-more", "more", "показать", "ещё", "еще")),
    (Role.SORT, ("sort", "order", "sorting", "сортиров")),
    (Role.FILTER, ("filter", "facet", "refine", "фильтр")),
    (
        Role.LIST_CONTAINER,
        ("list", "grid", "items", "results", "catalog", "products", "список", "каталог"),
    ),
    (
        Role.LIST_ITEM,
        ("card", "item", "product", "row", "tile", "entry", "post", "article", "карточк", "товар"),
    ),
    (Role.NAVIGATION, ("nav", "menu", "breadcrumb", "навигац", "меню")),
    (Role.HEADER, ("header", "masthead", "шапка")),
    (Role.FOOTER, ("footer", "подвал")),
    (Role.COOKIE_BANNER, ("cookie", "consent", "gdpr")),
    (Role.MODAL, ("modal", "dialog", "popup", "overlay")),
    (Role.TABLE, ("table", "grid-view", "таблиц")),
    (Role.SUBMIT, ("submit", "send", "отправить", "сохранить")),
)


def guess_roles(node: Node) -> list[Role]:
    """Гипотезы о роли элемента по тегам, атрибутам и ключевым словам.

    Возвращает список, потому что один элемент честно совмещает роли: ``select``
    с именем ``sort`` — это и «выпадающий список», и «сортировка»; ссылка внутри
    карточки — и «ссылка на элемент», и «название». Первая роль считается
    основной, остальные добавляются как дополнительные.
    """
    roles: list[Role] = []
    tag = node.tag
    input_type = node.get("type").lower()
    role_attr = node.get("role").lower()

    # --- По типу элемента ---------------------------------------------------
    if tag == "input":
        mapping = {
            "search": Role.SEARCH_INPUT,
            "email": Role.EMAIL_INPUT,
            "tel": Role.PHONE_INPUT,
            "password": Role.PASSWORD_INPUT,
            "number": Role.NUMBER_INPUT,
            "date": Role.DATE_INPUT,
            "datetime-local": Role.DATE_INPUT,
            "file": Role.FILE_INPUT,
            "checkbox": Role.CHECKBOX,
            "radio": Role.RADIO,
            "submit": Role.SUBMIT,
            "button": Role.BUTTON,
            "hidden": Role.UNKNOWN,
        }
        roles.append(mapping.get(input_type, Role.TEXT_INPUT))
    elif tag == "select":
        roles.append(Role.SELECT if role_attr != "listbox" else Role.SELECT)
    elif tag == "textarea":
        roles.append(Role.TEXTAREA)
    elif tag == "button":
        roles.append(Role.SUBMIT if node.get("type").lower() == "submit" else Role.BUTTON)
    elif tag == "form":
        roles.append(Role.SEARCH_FORM)
    elif tag == "table":
        roles.append(Role.TABLE)
    elif tag == "tr":
        roles.append(Role.TABLE_ROW)
    elif tag == "a":
        roles.append(Role.LINK)
    elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        roles.append(Role.HEADING)
    elif tag in {"nav"}:
        roles.append(Role.NAVIGATION)
    elif tag in {"header"}:
        roles.append(Role.HEADER)
    elif tag in {"footer"}:
        roles.append(Role.FOOTER)
    elif tag in {"dialog"}:
        roles.append(Role.MODAL)
    elif tag in {"ul", "ol"}:
        roles.append(Role.LIST_CONTAINER)

    # --- По семантике атрибутов --------------------------------------------
    if role_attr in {"search", "searchbox"} and Role.SEARCH_INPUT not in roles:
        roles.append(Role.SEARCH_INPUT)
    if role_attr == "navigation" and Role.NAVIGATION not in roles:
        roles.append(Role.NAVIGATION)
    if role_attr == "dialog" and Role.MODAL not in roles:
        roles.append(Role.MODAL)
    if role_attr in {"list", "grid", "listbox"} and Role.LIST_CONTAINER not in roles:
        roles.append(Role.LIST_CONTAINER)
    if role_attr in {"row", "listitem"} and Role.LIST_ITEM not in roles:
        roles.append(Role.LIST_ITEM)

    # --- По ключевым словам в атрибутах и классах ---------------------------
    haystack = " ".join(
        [
            node.get("name"),
            node.node_id,
            node.get("class"),
            node.get("data-testid"),
            node.get("aria-label"),
            node.get("placeholder"),
            node.get("rel"),
            node.get("title"),
            node.get("itemprop"),
            node.get("typeof"),
        ]
    ).lower()
    classes = {item.lower() for item in node.classes}

    for candidate, keywords in ROLE_KEYWORDS:
        if candidate in roles:
            continue
        for keyword in keywords:
            # Точное совпадение класса или подстрока в атрибутах. Не прерываем
            # перебор: элемент честно может совмещать роли (сортировка + select).
            if keyword in classes or (len(keyword) > 2 and keyword in haystack):
                roles.append(candidate)
                break

    # Роли-контейнеры не имеют смысла для полей ввода и ссылок: «поле поиска,
    # внутри которого список товаров» — бессмыслица. Такие совпадения возникают
    # из-за слов в aria-label и placeholder.
    if tag in {"input", "select", "textarea", "button"} or tag == "a":
        for structural in (Role.LIST_CONTAINER, Role.TABLE, Role.LIST_ITEM):
            if structural in roles:
                roles = [item for item in roles if item is not structural]

    # --- Поправки, которые делают роль осмысленной --------------------------
    # Кликабельная карточка — это ссылка-обёртка вокруг товара.
    if Role.LINK in roles and any(item in classes for item in ("card", "product", "item", "tile")):
        roles.insert(0, Role.LIST_ITEM)

    # Форма поиска без единого поля ввода формой поиска не является.
    if Role.SEARCH_FORM in roles and not node.find_all("input"):
        roles = [item for item in roles if item != Role.SEARCH_FORM]

    return _dedupe(roles) or [Role.UNKNOWN]


def _dedupe(roles: list[Role]) -> list[Role]:
    seen: set[Role] = set()
    result: list[Role] = []
    for role in roles:
        if role in seen:
            continue
        seen.add(role)
        result.append(role)
    return result


# ---------------------------------------------------------------------------
# Селекторы
# ---------------------------------------------------------------------------

# Утилитарные классы: их стабильность нулевая, а смысла для поиска нет.
UTILITY_CLASS_RE = re.compile(
    r"^(?:"
    r"[mptg][trblxy]?-\d+|"  # tailwind: mt-4, px-2
    r"(?:text|bg|border|rounded|shadow|flex|grid|gap|w|h|p|m)-|"
    r"(?:col|row|offset)-\d+|"  # bootstrap-сетка
    r"(?:btn|d|justify|align|order)-|"
    r"(?:flex|grid|block|inline|inline-block|contents|table|hidden|visible|"
    r"relative|absolute|fixed|sticky|static|container|group|clearfix)$|"
    r"sr-only|visually-hidden|active|disabled|selected|open|show|fade|in"
    r")$",
    re.IGNORECASE,
)

# Признаки автогенерированного идентификатора или класса.
GENERATED_RE = re.compile(
    r"(?:^|[^a-z])(?:css|sc|jsx|emotion|styled)-?[a-z0-9]{4,}|"
    r"^[a-z]{1,3}[0-9]{3,}$|"
    r"[0-9a-f]{8,}|"
    r"[0-9]{4,}",
    re.IGNORECASE,
)


def looks_generated(value: str) -> bool:
    """Похоже ли имя на автогенерированное (хэш, счётчик, случайный суффикс)."""
    if not value:
        return True
    if GENERATED_RE.search(value):
        return True
    digits = sum(char.isdigit() for char in value)
    return digits > len(value) / 2


def css_escape(value: str) -> str:
    """Экранирует значение для использования в CSS-селекторе."""
    return re.sub(r'(["\\])', r"\\\1", value)


@dataclass
class SelectorCandidate:
    """Один вариант селектора с оценкой устойчивости."""

    selector: str
    kind: str
    score: float
    matches_hint: int = 1

    def as_dict(self) -> dict[str, object]:
        return {
            "selector": self.selector,
            "kind": self.kind,
            "score": round(self.score, 3),
        }


def _candidates_for(node: Node) -> list[SelectorCandidate]:
    """Собирает все возможные селекторы для элемента с их оценками."""
    candidates: list[SelectorCandidate] = []

    # 1. Тестовые и семантические data-атрибуты — самое надёжное.
    for attr in ("data-testid", "data-test", "data-qa", "data-cy", "data-action"):
        value = node.get(attr)
        if value:
            candidates.append(
                SelectorCandidate(f'[{attr}="{css_escape(value)}"]', "data-attr", 0.98)
            )
    for attr, value in node.attrs.items():
        if (
            attr.startswith("data-")
            and attr not in {"data-testid", "data-test", "data-qa", "data-cy"}
            and value
            and len(value) < 40
            and not looks_generated(value)
        ):
            candidates.append(
                SelectorCandidate(f'[{attr}="{css_escape(value)}"]', "data-attr", 0.9)
            )

    # 2. Идентификатор.
    node_id = node.node_id
    if node_id:
        escaped = css_escape(node_id)
        if looks_generated(node_id):
            candidates.append(SelectorCandidate(f"#{escaped}", "id-generated", 0.45))
        else:
            candidates.append(SelectorCandidate(f"#{escaped}", "id", 0.95))

    # 3. ARIA и доступное имя.
    aria_label = node.get("aria-label")
    if aria_label:
        candidates.append(
            SelectorCandidate(f'{node.tag}[aria-label="{css_escape(aria_label)}"]', "aria", 0.88)
        )
    if node.get("role"):
        candidates.append(
            SelectorCandidate(f'{node.tag}[role="{css_escape(node.get("role"))}"]', "role", 0.8)
        )

    # 4. Атрибуты формы и ссылок.
    if node.get("name"):
        candidates.append(
            SelectorCandidate(f'{node.tag}[name="{css_escape(node.get("name"))}"]', "name", 0.86)
        )
    if node.get("itemprop"):
        candidates.append(
            SelectorCandidate(
                f'{node.tag}[itemprop="{css_escape(node.get("itemprop"))}"]', "microdata", 0.84
            )
        )
    if node.get("placeholder"):
        candidates.append(
            SelectorCandidate(
                f'{node.tag}[placeholder="{css_escape(node.get("placeholder"))}"]',
                "placeholder",
                0.8,
            )
        )
    if node.tag == "input" and node.get("type"):
        candidates.append(
            SelectorCandidate(f'input[type="{css_escape(node.get("type"))}"]', "attr", 0.6)
        )
    if node.get("rel"):
        # rel="next"/"prev"/"nofollow" — стандарт, а не договорённость команды:
        # такой селектор переживает любые переименования классов.
        candidates.append(
            SelectorCandidate(f'{node.tag}[rel="{css_escape(node.get("rel"))}"]', "rel", 0.92)
        )

    # 5. Классы: берём только осмысленные и не автогенерированные.
    useful = [
        item
        for item in node.classes
        if not UTILITY_CLASS_RE.match(item) and not looks_generated(item) and len(item) > 2
    ]
    if useful:
        # Один класс — устойчивее, два — точнее. Даём оба варианта.
        candidates.append(SelectorCandidate(f"{node.tag}.{'.'.join(useful[:1])}", "class", 0.72))
        if len(useful) > 1:
            candidates.append(
                SelectorCandidate(f"{node.tag}.{'.'.join(useful[:2])}", "class", 0.68)
            )
        candidates.append(SelectorCandidate(f".{'.'.join(useful[:1])}", "class-short", 0.6))

    # 6. Родитель + класс: когда сам элемент безымянный.
    parent = node.parent
    if parent is not None and parent.tag != "#document":
        parent_useful = [
            item
            for item in parent.classes
            if not UTILITY_CLASS_RE.match(item) and not looks_generated(item) and len(item) > 2
        ]
        if parent_useful and useful:
            candidates.append(
                SelectorCandidate(f".{parent_useful[0]} > {node.tag}.{useful[0]}", "nested", 0.7)
            )

    # 7. Структурный путь — последний резерв.
    candidates.append(SelectorCandidate(node.css_path(), "path", 0.25))

    return candidates


def build_selectors(node: Node, *, replicas: int = 1) -> tuple[str, list[SelectorCandidate]]:
    """Возвращает лучший селектор и список кандидатов по убыванию оценки.

    ``replicas`` — сколько одинаковых элементов найдено на странице. Если
    селектор матчит несколько узлов, а элемент задуман одиночным (например, поле
    поиска), оценка снижается: искать нужно ровно одно поле.
    """
    candidates = _candidates_for(node)
    if not candidates:
        return node.css_path(), [SelectorCandidate(node.css_path(), "path", 0.2)]

    for candidate in candidates:
        if candidate.kind in {"data-attr", "aria", "name", "microdata", "rel"}:
            candidate.matches_hint = max(replicas, 1)
        elif candidate.kind in {"id", "id-generated"}:
            candidate.matches_hint = 1
        else:
            candidate.matches_hint = replicas
        # Одиночный элемент с множественным селектором — рискованно.
        if replicas > 1 and candidate.kind in {"id", "id-generated"}:
            candidate.score -= 0.1

    candidates.sort(key=lambda item: item.score, reverse=True)
    return candidates[0].selector, candidates


def selector_quality(candidates: list[SelectorCandidate]) -> float:
    """Итоговая оценка устойчивости: берём лучшего кандидата."""
    return candidates[0].score if candidates else 0.0


def merge_candidate_lists(
    lists: list[list[SelectorCandidate]], limit: int = 6
) -> list[SelectorCandidate]:
    """Объединяет кандидатов из нескольких похожих элементов.

    Для списка карточек полезно хранить селекторы, работающие на всех
    экземплярах: то, что повторилось у большинства, и есть устойчивый адрес.
    """
    counts: dict[str, tuple[SelectorCandidate, int]] = {}
    for items in lists:
        for candidate in items:
            existing = counts.get(candidate.selector)
            if existing is None:
                counts[candidate.selector] = (candidate, 1)
            else:
                counts[candidate.selector] = (existing[0], existing[1] + 1)

    merged = [
        SelectorCandidate(
            selector=candidate.selector,
            kind=candidate.kind,
            score=min(0.99, candidate.score * (0.7 + 0.3 * (count / max(len(lists), 1)))),
            matches_hint=count,
        )
        for candidate, count in counts.values()
    ]
    merged.sort(key=lambda item: item.score, reverse=True)
    return merged[:limit]


@dataclass
class Element:
    """Описанный элемент страницы."""

    role: Role
    selector: str
    candidates: list[SelectorCandidate] = field(default_factory=list)
    label: str = ""
    description: str = ""
    confidence: float = 0.0
    count: int = 1
    sample: str | None = None
    tag: str = ""
    source: str = "heuristic"
    node_path: str = ""
    attrs: dict[str, str] = field(default_factory=dict)
    # Для контейнеров повторов: сколько элементов внутри и их подпись.
    repeat_signature: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "role": self.role.value,
            "label": self.label or label_for(self.role),
            "description": self.description,
            "selector": self.selector,
            "selectors": [candidate.as_dict() for candidate in self.candidates[:6]],
            "selector_quality": round(selector_quality(self.candidates), 3),
            "confidence": round(self.confidence, 3),
            "count": self.count,
            "sample": self.sample,
            "tag": self.tag,
            "source": self.source,
            "path": self.node_path,
            "repeat_signature": self.repeat_signature,
            "attrs": self.attrs,
        }
