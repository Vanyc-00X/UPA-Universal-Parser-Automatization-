"""Скачивание колёс Python без использования pip-резолвера.

Зачем этот файл
---------------
В этом окружении pip зависает на сетевой фазе: он подолгу перебирает варианты
зависимостей, и установка не завершается. Обычные HTTPS-запросы при этом
работают быстро. Поэтому колёса скачиваются здесь, а устанавливаются локально::

    python -m pip install --no-index --no-deps data/_wheels/*.whl

Алгоритм
--------
Обход графа зависимостей в ширину, при котором:

* учитываются только **обязательные** зависимости (``Requires-Dist`` без пометки
  ``extra ==``) — иначе в граф попадают Sphinx, Django и прочие инструменты
  разработки, которые к работе приложения отношения не имеют;
* игнорируются зависимости, требующие Python иначе, чем наш (маркер
  ``python_version`` / ``sys_platform``);
* выбирается колесо под нашу версию Python и платформу, иначе — универсальное
  ``py3-none-any``;
* для каждого пакета берётся самая свежая версия, удовлетворяющая ограничению
  (простые спецификаторы ``>=``, ``<``, ``~=``, ``==``).

Запуск::

    python tools/fetch_wheels.py --out data/_wheels
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

PYPI_JSON = "https://pypi.org/pypi/{name}/json"
PYPI_VERSION_JSON = "https://pypi.org/pypi/{name}/{version}/json"

# Пакеты, которые не нужны приложению и раздувают граф зависимостей.
# Внимание: greenlet здесь быть не должно — он обязателен для sqlalchemy[asyncio].
BLACKLIST = {
    "setuptools",
    "wheel",
    "pip",
    "uvloop",
    "httptools",
    "watchfiles",
    "ty",
    "uv",
    "psutil",
}

REQUIRES_RE = re.compile(r"^Requires-Dist:\s*(.*)$")
SPEC_RE = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*(\[[^\]]*\])?\s*(.*)$")
CONSTRAINT_RE = re.compile(r"(==|>=|<=|~=|!=|>|<)\s*([0-9][0-9A-Za-z.\-+]*)")

# По умолчанию ищем колёса под эту версию Python и платформу.
DEFAULT_PY_TAG = f"cp{sys.version_info.major}{sys.version_info.minor}"
DEFAULT_PLATFORM_TAGS = ("win_amd64", "win32", "any")


@dataclass
class Wheel:
    """Найденное колесо."""

    name: str
    version: str
    filename: str
    url: str
    sha256: str
    requires: list[str] = field(default_factory=list)
    size: int = 0


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "UPA-wheel-fetcher/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def normalize(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def strip_extras(requirement: str) -> str:
    """Убирает пометку extra: ``uvicorn[standard]>=0.30`` → ``uvicorn>=0.30``.

    Необязательные наборы зависимостей (``[standard]``, ``[dev]``) приложению не
    нужны: они тянут компилируемые ускорители и инструменты разработки.
    """
    return re.sub(r"\[[^\]]*\]", "", requirement).strip()


def is_optional(requirement: str) -> bool:
    """Проверяет, что зависимость объявлена только для extra-набора."""
    return "extra ==" in requirement


def is_foreign_marker(requirement: str) -> bool:
    """Отсекает зависимости для чужих платформ и версий Python."""
    marker = requirement.partition(";")[2]
    if not marker:
        return False
    marker = marker.lower()
    if "sys_platform" in marker and "win32" not in marker and "==" in marker:
        return True
    if "python_version" in marker:
        # Разбираем простые случаи вида python_version < "3.11".
        match = re.search(r'python_version\s*(<|<=|>|>=|==|!=)\s*"([0-9.]+)"', marker)
        if match:
            operator, raw = match.group(1), match.group(2)
            current = f"{sys.version_info.major}.{sys.version_info.minor}"
            try:
                left, right = tuple(map(int, current.split("."))), tuple(map(int, raw.split(".")))
            except ValueError:
                return False
            result = {
                "<": left < right,
                "<=": left <= right,
                ">": left > right,
                ">=": left >= right,
                "==": left == right,
                "!=": left != right,
            }[operator]
            # Маркер описывает, когда зависимость НЕ нужна, если он ложен.
            return not result
    return False


def parse_requirement(requirement: str) -> tuple[str, list[tuple[str, str]]] | None:
    """Разбирает строку зависимости в (имя, ограничения версии)."""
    if is_optional(requirement) or is_foreign_marker(requirement):
        return None
    cleaned = strip_extras(requirement.partition(";")[0])
    match = SPEC_RE.match(cleaned)
    if not match:
        return None
    name = normalize(match.group(1))
    constraints = [(op, value) for op, value in CONSTRAINT_RE.findall(match.group(3) or "")]
    return name, constraints


def is_stable(version: str) -> bool:
    """Отличает стабильный выпуск от предрелиза (``2.14.0b2``, ``1.0rc1``, ``0.5.dev1``)."""
    return re.search(r"(a|b|rc|dev|alpha|beta)\d*$", version.lower()) is None


def satisfies(version: str, constraints: list[tuple[str, str]]) -> bool:
    """Проверяет версию на соответствие ограничениям (приближённо, но достаточно)."""

    def as_tuple(value: str) -> tuple[int, ...]:
        parts = re.split(r"[.\-+]", value)
        numbers: list[int] = []
        for part in parts:
            digits = re.match(r"^(\d+)", part)
            if not digits:
                break
            numbers.append(int(digits.group(1)))
        return tuple(numbers)

    current = as_tuple(version)
    for operator, raw in constraints:
        target = as_tuple(raw)
        length = max(len(current), len(target))
        left = current + (0,) * (length - len(current))
        right = target + (0,) * (length - len(target))
        if operator == "==" and left != right:
            return False
        if operator == "!=" and left == right:
            return False
        if operator == ">=" and left < right:
            return False
        if operator == "<=" and left > right:
            return False
        if operator == ">" and left <= right:
            return False
        if operator == "<" and left >= right:
            return False
        if operator == "~=" and left[: len(right)] != right:
            return False
    return True


def pick_wheel(files: list[dict], py_tag: str) -> dict | None:
    """Выбирает подходящее колесо: сначала под нашу платформу, затем универсальное."""
    wheels = [item for item in files if item.get("packagetype") == "bdist_wheel"]
    if not wheels:
        return None

    def compatible(name: str) -> bool:
        lowered = name.lower()
        if any(tag in lowered for tag in ("musllinux", "manylinux", "macosx")):
            return False
        return True

    candidates = [item for item in wheels if compatible(item["filename"])]
    exact = [item for item in candidates if py_tag in item["filename"]]
    # Колёса вида cp312-cp312-win_amd64 подходят лучше всего.
    for platform_tag in DEFAULT_PLATFORM_TAGS:
        for item in exact:
            if platform_tag in item["filename"]:
                return item
    for item in exact:
        if "none-any" in item["filename"]:
            return item
    for item in candidates:
        if "py3-none-any" in item["filename"] or "py2.py3-none-any" in item["filename"]:
            return item
    return None


def download_wheel(item: dict, target: Path) -> bool:
    """Скачивает файл колеса, проверяя контрольную сумму."""
    import hashlib

    path = target / item["filename"]
    expected = item.get("digests", {}).get("sha256")
    if path.exists() and expected:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest == expected:
            return True

    request = urllib.request.Request(
        item["url"], headers={"User-Agent": "UPA-wheel-fetcher/0.1"}
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        payload = response.read()
    if expected:
        digest = hashlib.sha256(payload).hexdigest()
        if digest != expected:
            print(f"    ! контрольная сумма не совпала: {item['filename']}")
            return False
    path.write_bytes(payload)
    return True


def read_requires(path: Path) -> list[str]:
    """Читает обязательные зависимости из METADATA внутри колеса."""
    requirements: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            metadata = next(
                (
                    name
                    for name in archive.namelist()
                    if name.endswith(".dist-info/METADATA")
                ),
                None,
            )
            if metadata is None:
                return requirements
            text = archive.read(metadata).decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, OSError) as exc:
        print(f"    ! не удалось прочитать метаданные {path.name}: {exc}")
        return requirements

    for line in text.splitlines():
        match = REQUIRES_RE.match(line)
        if match:
            requirements.append(match.group(1).strip())
    return requirements


def resolve(
    roots: list[str],
    target: Path,
    *,
    py_tag: str,
    max_packages: int = 120,
) -> tuple[list[Wheel], list[str]]:
    """Обходит граф зависимостей и складывает колёса в ``target``."""
    resolved: dict[str, Wheel] = {}
    queue: list[tuple[str, list[tuple[str, str]]]] = [
        (normalize(name), []) for name in roots
    ]
    problems: list[str] = []

    while queue:
        if len(resolved) >= max_packages:
            problems.append(f"достигнут предел в {max_packages} пакетов")
            break
        name, constraints = queue.pop(0)
        if name in resolved or name in BLACKLIST:
            continue

        try:
            meta = fetch_json(PYPI_JSON.format(name=name))
        except Exception as exc:  # noqa: BLE001 — сеть и отсутствие пакета
            problems.append(f"{name}: {exc}")
            continue

        available = [
            version
            for version in meta.get("releases", {})
            if satisfies(version, constraints) and meta["releases"][version]
        ]
        # Предрелизы (2.14.0b2, 1.0rc1) не используем, если есть стабильная версия.
        stable = [version for version in available if is_stable(version)]
        if stable:
            available = stable
        if not available:
            problems.append(f"{name}: нет версии под ограничения {constraints}")
            continue
        available.sort(key=lambda value: [int(part) for part in re.findall(r"\d+", value)])
        version = available[-1]
        if version != meta["info"]["version"]:
            try:
                meta = fetch_json(PYPI_VERSION_JSON.format(name=name, version=version))
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{name}=={version}: {exc}")
                continue

        item = pick_wheel(meta.get("urls", []), py_tag)
        if item is None:
            problems.append(f"{name}=={version}: нет подходящего колеса")
            continue

        target.mkdir(parents=True, exist_ok=True)
        print(f"  + {item['filename']}")
        if not download_wheel(item, target):
            problems.append(f"{name}=={version}: ошибка загрузки")
            continue

        path = target / item["filename"]
        requires = read_requires(path)
        wheel = Wheel(
            name=name,
            version=version,
            filename=item["filename"],
            url=item["url"],
            sha256=item.get("digests", {}).get("sha256", ""),
            requires=requires,
            size=path.stat().st_size,
        )
        resolved[name] = wheel

        for requirement in requires:
            parsed = parse_requirement(requirement)
            if parsed is None:
                continue
            dep_name, dep_constraints = parsed
            if dep_name in resolved or dep_name in BLACKLIST:
                continue
            queue.append((dep_name, dep_constraints))

    return list(resolved.values()), problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Скачать колёса зависимостей UPA")
    parser.add_argument(
        "--out",
        default="data/_wheels",
        help="каталог для колёс (по умолчанию data/_wheels)",
    )
    parser.add_argument(
        "--packages",
        nargs="*",
        default=[
            "fastapi",
            "uvicorn",
            "pydantic",
            "pydantic-settings",
            "sqlalchemy[asyncio]",
            "aiosqlite",
            "alembic",
            "httpx",
            "structlog",
            "python-multipart",
            "playwright",
            "pytest",
            "pytest-asyncio",
            "ruff",
            "black",
        ],
        help="корневые пакеты",
    )
    parser.add_argument("--py-tag", default=DEFAULT_PY_TAG)
    args = parser.parse_args()

    target = Path(args.out)
    if not target.is_absolute():
        target = Path(__file__).resolve().parents[1] / target

    print(f"Каталог: {target}")
    print(f"Тег Python: {args.py_tag}")
    print(f"Корневых пакетов: {len(args.packages)}")
    print()

    wheels, problems = resolve(args.packages, target, py_tag=args.py_tag)

    total_mb = sum(wheel.size for wheel in wheels) / 1024 / 1024
    print()
    print(f"Скачано пакетов: {len(wheels)}, объём: {total_mb:.1f} МБ")
    if problems:
        print(f"Проблемы ({len(problems)}):")
        for problem in problems:
            print(f"  - {problem}")
    return 0 if wheels else 1


if __name__ == "__main__":
    sys.exit(main())
