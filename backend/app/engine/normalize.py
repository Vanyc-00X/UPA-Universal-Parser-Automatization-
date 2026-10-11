"""Нормализация собранных значений.

Сырые данные со страницы почти всегда требуют чистки: «1 249,00 ₽» — это цена,
«/product/1» — относительная ссылка, «01.02.2026» — дата. Без нормализации
результат приходится чистить руками, а отчёт о полноте данных становится
бессмысленным: пустая строка и «нет значения» выглядят одинаково.

Модуль намеренно ничего не знает про DOM: на вход строка, на выход значение.
Это делает его легко проверяемым — а ошибки здесь дороги, потому что цена
«1 249» и цена «12 49» выглядят похоже, но значат разное.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

# Неразрывные и типографские пробелы: в ценах они встречаются постоянно.
SPACES_RE = re.compile(r"[\s\u00a0\u202f\u2009]+")
# Символы валют и типичные пометки рядом с числом.
CURRENCY_RE = re.compile(
    r"(₽|руб\.?|рублей|р\.|rub|usd|\$|€|eur|¥|cny|kzt|₸|бел\.?\s*руб|грн|uah)",
    re.IGNORECASE,
)
# Число с разделителями разрядов и необязательной дробной частью.
NUMBER_RE = re.compile(r"[-+]?\d[\d\s\u00a0\u202f']*(?:[.,]\d+)?")
# Учёт подобран специально: 1 234,56 / 1,234.56 / 1234.56 / 1234,56.
THOUSANDS_RE = re.compile(r"[ \u00a0\u202f']")
DATE_FORMATS = (
    "%Y-%m-%d",
    "%d.%m.%Y",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
    "%d %m %Y",
    "%d %B %Y",
    "%d %b %Y",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f%z",
)
MONTHS_RU = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
    "янв": 1,
    "фев": 2,
    "мар": 3,
    "апр": 4,
    "май": 5,
    "июн": 6,
    "июл": 7,
    "авг": 8,
    "сен": 9,
    "окт": 10,
    "ноя": 11,
    "дек": 12,
}
# Следы рекламы и служебных пометок, которые не являются значением.
NOISE_RE = re.compile(
    r"^\s*(реклама|промо|акция|хит|новинка|скидка|под заказ|в наличии|нет в наличии)\s*$",
    re.IGNORECASE,
)


def clean_text(value: str | None) -> str:
    """Схлопывает пробелы и убирает невидимый мусор."""
    if not value:
        return ""
    cleaned = SPACES_RE.sub(" ", value.replace("\u200b", "").replace("\ufeff", ""))
    return cleaned.strip()


def is_noise(value: str | None) -> bool:
    """Похоже ли значение на служебную пометку, а не на данные."""
    return bool(value) and bool(NOISE_RE.match(clean_text(value)))


# ---------------------------------------------------------------------------
# Числа и цены
# ---------------------------------------------------------------------------


@dataclass
class ParsedNumber:
    """Результат разбора числа."""

    value: Decimal | None
    raw: str
    currency: str | None = None
    unit: str | None = None
    problem: str | None = None

    @property
    def ok(self) -> bool:
        return self.value is not None


def _decimal_from_match(match: str) -> Decimal | None:
    """Превращает найденное число в Decimal, разбирая разделители.

    Правило: разделитель, за которым идут ровно три цифры и больше цифр после
    него нет, — это разделитель разрядов. Иначе — десятичный.
    """
    text = THOUSANDS_RE.sub("", match.strip())
    if not text:
        return None

    # Отделяем знак.
    sign = ""
    if text[0] in "+-":
        sign, text = text[0], text[1:]

    # Ищем последний разделитель среди точки и запятой.
    last_dot = text.rfind(".")
    last_comma = text.rfind(",")
    separator = max(last_dot, last_comma)
    if separator == -1:
        candidate = text
    else:
        tail = text[separator + 1 :]
        if len(tail) == 3 and len(text) > 4:
            # Похоже на разделитель разрядов: 1.234 или 1,234.
            candidate = text[:separator] + tail
        else:
            candidate = text[:separator] + "." + tail

    # Убираем оставшиеся разделители разрядов.
    candidate = candidate.replace(",", "").replace(" ", "")
    if candidate.count(".") > 1:
        parts = candidate.split(".")
        candidate = "".join(parts[:-1]) + "." + parts[-1]

    try:
        return Decimal(f"{sign}{candidate}")
    except InvalidOperation:
        return None


def parse_number(value: str | None, *, currency: bool = False) -> ParsedNumber:
    """Извлекает число из строки.

    Понимает «12 990,50 ₽», «1,299.00», «от 500 руб.», «12 990 ₽/шт».
    """
    raw = clean_text(value)
    if not raw:
        return ParsedNumber(value=None, raw=raw, problem="пустое значение")
    if is_noise(raw):
        return ParsedNumber(value=None, raw=raw, problem="служебная пометка")

    currency_found: str | None = None
    if currency:
        found = CURRENCY_RE.search(raw)
        if found:
            currency_found = found.group(1).strip().lower()

    # Знак минус перед числом сохраняем; «от» и «до» игнорируем как слова.
    matches = NUMBER_RE.findall(raw)
    if not matches:
        return ParsedNumber(
            value=None, raw=raw, currency=currency_found, problem="число не найдено"
        )

    # Берём самое длинное совпадение: в «SKU-4711, 500 ₽» числом является 500.
    longest = max(matches, key=lambda item: len(THOUSANDS_RE.sub("", item)))
    number = _decimal_from_match(longest)
    if number is None:
        return ParsedNumber(
            value=None, raw=raw, currency=currency_found, problem="число не разобрано"
        )

    unit: str | None = None
    unit_match = re.search(r"/\s*([а-яa-z]+)", raw, re.IGNORECASE)
    if unit_match:
        unit = unit_match.group(1).lower()

    return ParsedNumber(value=number, raw=raw, currency=currency_found, unit=unit)


def parse_price(value: str | None) -> dict[str, Any]:
    """Разбирает цену: значение, валюта, исходная строка."""
    parsed = parse_number(value, currency=True)
    return {
        "value": float(parsed.value) if parsed.value is not None else None,
        "currency": parsed.currency,
        "unit": parsed.unit,
        "raw": parsed.raw,
        "problem": parsed.problem,
    }


def parse_int(value: str | None) -> int | None:
    """Разбирает целое число: количество, отзывы, артикул."""
    parsed = parse_number(value)
    if parsed.value is None:
        return None
    try:
        return int(parsed.value)
    except (ValueError, OverflowError):
        return None


def parse_float(value: str | None) -> float | None:
    """Разбирает дробное число: рейтинг, вес, площадь."""
    parsed = parse_number(value)
    return float(parsed.value) if parsed.value is not None else None


# ---------------------------------------------------------------------------
# Ссылки и изображения
# ---------------------------------------------------------------------------


def absolute_url(value: str | None, base: str | None = None) -> str | None:
    """Приводит ссылку к абсолютной.

    Относительные адреса бесполезны за пределами страницы: «/product/1» нельзя
    открыть без знания домена.
    """
    if not value:
        return None
    cleaned = clean_text(value)
    if not cleaned:
        return None
    # Ссылки-заглушки и скрипты значения не несут.
    if cleaned.lower().startswith(("javascript:", "mailto:", "tel:", "data:")):
        return None
    if cleaned.startswith("#"):
        return None
    if not base:
        return cleaned if "://" in cleaned else None

    try:
        result = urljoin(base, cleaned)
    except ValueError:
        return None
    parts = urlsplit(result)
    if not parts.scheme or not parts.netloc:
        return None
    # Убираем служебные параметры трекинга: они делают ссылки уникальными зря.
    query_pairs = [
        pair
        for pair in parts.query.split("&")
        if pair and not pair.lower().startswith(("utm_", "gclid=", "yclid=", "fbclid="))
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "&".join(query_pairs), ""))


def image_url(value: str | None, base: str | None = None) -> str | None:
    """Приводит ссылку на изображение к абсолютной."""
    if not value:
        return None
    cleaned = clean_text(value)
    if cleaned.startswith("data:"):
        return None
    return absolute_url(cleaned, base)


def url_key(value: str | None) -> str | None:
    """Ключ ссылки для дедупликации: без схемы, www, слэша и параметров.

    Один товар часто доступен по «/product/1», «/product/1/» и
    «https://www.site.com/product/1?utm_source=x» — для дедупликации это одно и то же.
    """
    normalized = absolute_url(value, "https://placeholder.invalid")
    if not normalized:
        return None
    parts = urlsplit(normalized)
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/") or "/"
    return f"{host}{path}"


def navigation_key(value: str | None) -> str | None:
    """Ключ адреса для обхода страниц: учитывает query, кроме трекинга.

    В отличие от :func:`url_key`, «/catalog?page=1» и «/catalog?page=2» — разные
    страницы. Без этого пагинация останавливалась бы на первой странице.
    """
    normalized = absolute_url(value, "https://placeholder.invalid")
    if not normalized:
        return None
    parts = urlsplit(normalized)
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/") or "/"
    query_pairs = sorted(
        pair
        for pair in parts.query.split("&")
        if pair and not pair.lower().startswith(("utm_", "gclid=", "yclid=", "fbclid="))
    )
    if query_pairs:
        return f"{host}{path}?{'&'.join(query_pairs)}"
    return f"{host}{path}"


# ---------------------------------------------------------------------------
# Дата и время
# ---------------------------------------------------------------------------


def parse_date(value: str | None) -> date | None:
    """Разбирает дату в распространённых форматах, включая русский текст."""
    raw = clean_text(value)
    if not raw:
        return None

    # Русский формат: «1 февраля 2026».
    lowered = raw.lower()
    match = re.search(r"(\d{1,2})\s+([а-я]+)\.?\s+(\d{4})", lowered)
    if match:
        day = int(match.group(1))
        month = MONTHS_RU.get(match.group(2))
        year = int(match.group(3))
        if month:
            try:
                return date(year, month, day)
            except ValueError:
                return None

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()  # noqa: DTZ007 — нужна только дата
        except ValueError:
            continue

    # «сегодня», «вчера» и ISO с часовым поясом.
    if lowered.startswith("сегодня"):
        return datetime.now(timezone.utc).date()
    if lowered.startswith("вчера"):
        return (
            datetime.now(timezone.utc)
            .date()
            .fromordinal(datetime.now(timezone.utc).date().toordinal() - 1)
        )
    return None


def parse_datetime(value: str | None) -> datetime | None:
    """Разбирает дату со временем, приводя к UTC, если часовой пояс указан."""
    raw = clean_text(value)
    if not raw:
        return None
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(raw, fmt)  # noqa: DTZ007 — формат задан явно
        except ValueError:
            continue
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc)
        return parsed.replace(tzinfo=timezone.utc)
    found = parse_date(raw)
    if found is not None:
        return datetime(found.year, found.month, found.day, tzinfo=timezone.utc)
    return None


# ---------------------------------------------------------------------------
# Ключи дедупликации
# ---------------------------------------------------------------------------


def dedup_key(record: dict[str, Any], fields: list[str] | None = None) -> str:
    """Строит ключ записи для сравнения запусков.

    Берём самые устойчивые поля — ссылку и название: у одного товара они не
    меняются, даже если цену обновили.
    """
    keys = fields or ["url", "title", "sku"]
    parts: list[str] = []
    for name in keys:
        value = record.get(name)
        if value in (None, ""):
            continue
        text = str(value).strip().lower()
        if name == "url":
            text = url_key(text) or text
        parts.append(text)
    if not parts:
        # Совсем без данных опираемся на всё содержимое записи.
        parts = [str(sorted(record.items()))]
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:32]


# ---------------------------------------------------------------------------
# Значения по типу поля
# ---------------------------------------------------------------------------


# Тип значения можно задать у поля; если не задан — угадываем по названию.
FIELD_TYPE_HINTS: dict[str, str] = {
    "price": "price",
    "cost": "price",
    "amount": "price",
    "цена": "price",
    "стоимость": "price",
    "url": "url",
    "link": "url",
    "href": "url",
    "ссылка": "url",
    "image": "image",
    "img": "image",
    "photo": "image",
    "картинка": "image",
    "фото": "image",
    "date": "date",
    "published": "date",
    "дата": "date",
    "count": "int",
    "quantity": "int",
    "количество": "int",
    "отзывы": "int",
    "rating": "float",
    "рейтинг": "float",
}


def guess_type(key: str, title: str | None = None) -> str:
    """Определяет тип значения по имени поля.

    Нужен там, где пользователь не указал тип явно: цена, ссылка и дата требуют
    разной обработки, и угадать по названию дешевле, чем спрашивать.
    """
    for candidate in (key, title or ""):
        lowered = candidate.strip().lower()
        if lowered in FIELD_TYPE_HINTS:
            return FIELD_TYPE_HINTS[lowered]
        for hint, kind in FIELD_TYPE_HINTS.items():
            if lowered.endswith(f"_{hint}") or lowered.startswith(f"{hint}_"):
                return kind
    return "text"


def detect_kind(value: str | None) -> str:
    """Угадывает тип по содержимому значения — для ручной проверки в UI."""
    cleaned = clean_text(value)
    if not cleaned:
        return "text"
    lowered = cleaned.lower()
    if lowered.startswith(("http://", "https://", "//")) or (
        cleaned.startswith("/") and " " not in cleaned
    ):
        return "url"
    if CURRENCY_RE.search(cleaned) and NUMBER_RE.search(cleaned):
        return "price"
    if parse_date(cleaned) is not None:
        return "date"
    return "text"


@dataclass
class NormalizedValue:
    """Нормализованное значение поля с диагностикой."""

    value: Any
    raw: str | None
    problem: str | None = None

    @property
    def ok(self) -> bool:
        return self.value not in (None, "")


def normalize(
    raw: str | None,
    *,
    kind: str = "text",
    base_url: str | None = None,
) -> NormalizedValue:
    """Нормализует значение поля по его типу."""
    cleaned = clean_text(raw)
    if not cleaned:
        return NormalizedValue(value=None, raw=raw, problem="пустое значение")

    if kind == "text":
        return NormalizedValue(value=cleaned, raw=raw)

    if kind == "price":
        parsed = parse_price(cleaned)
        if parsed["value"] is None:
            return NormalizedValue(
                value=None, raw=raw, problem=parsed["problem"] or "цена не разобрана"
            )
        return NormalizedValue(value=parsed["value"], raw=raw)

    if kind == "int":
        number = parse_int(cleaned)
        return NormalizedValue(
            value=number,
            raw=raw,
            problem=None if number is not None else "целое число не разобрано",
        )

    if kind == "float":
        number = parse_float(cleaned)
        return NormalizedValue(
            value=number, raw=raw, problem=None if number is not None else "число не разобрано"
        )

    if kind == "url":
        link = absolute_url(cleaned, base_url)
        return NormalizedValue(value=link, raw=raw, problem=None if link else "ссылка не разобрана")

    if kind == "image":
        image = image_url(cleaned, base_url)
        return NormalizedValue(
            value=image, raw=raw, problem=None if image else "ссылка на картинку не разобрана"
        )

    if kind == "date":
        parsed_date = parse_date(cleaned)
        return NormalizedValue(
            value=parsed_date.isoformat() if parsed_date else None,
            raw=raw,
            problem=None if parsed_date else "дата не разобрана",
        )

    if kind == "datetime":
        parsed_moment = parse_datetime(cleaned)
        return NormalizedValue(
            value=parsed_moment.isoformat() if parsed_moment else None,
            raw=raw,
            problem=None if parsed_moment else "дата и время не разобраны",
        )

    return NormalizedValue(value=cleaned, raw=raw)
