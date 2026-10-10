"""Диагностика анализа страниц: что находит детерминированный анализатор.

Запуск: .venv\\Scripts\\python.exe tools/analyze_report.py [ключ страницы]
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.analyzer import detector  # noqa: E402
from tests.pages import FIXTURES, FIXTURES_BY_KEY  # noqa: E402


def show(key: str, *, verbose: bool = False) -> int:
    fixture = FIXTURES_BY_KEY[key]
    document = detector.parse(fixture.html)
    analysis = detector.analyze_html(fixture.html)

    print("=" * 78)
    print(f"{key}: {fixture.title}")
    print("=" * 78)
    print(f"заголовок: {analysis.title!r}  язык: {analysis.lang!r}")
    print(f"узлов в дереве: {sum(1 for _ in document.iter_nodes()) - 1}")
    print(f"элементов размечено: {len(analysis.elements)}")
    print(f"групп повторов: {len(analysis.repeats)}")

    for group in analysis.repeats:
        print(
            f"  повторы: {group.count} шт, похожесть {group.similarity:.0%}, "
            f"контейнер <{group.container.tag} class=\"{' '.join(group.container.classes)}\">"
        )
        if verbose and group.items:
            print(f"    пример: {group.items[0].all_text(limit=100)}")

    roles = [element.role.value for element in analysis.elements]
    print(f"роли: {', '.join(roles)}")

    expected = set(fixture.expected_roles)
    found = set(roles)
    missing = expected - found
    unexpected = set(fixture.forbidden_roles) & found

    print()
    if missing:
        print(f"  НЕ НАЙДЕНО: {', '.join(sorted(missing))}")
    else:
        print("  все ожидаемые роли найдены")
    if unexpected:
        print(f"  ЛИШНИЕ (запрещённые): {', '.join(sorted(unexpected))}")
    if fixture.expected_repeat_count is not None:
        best = analysis.best_repeat
        actual = best.count if best else 0
        mark = "OK " if actual == fixture.expected_repeat_count else "НЕТ"
        print(f"  {mark} элементов в списке: {actual} (ожидалось {fixture.expected_repeat_count})")

    if analysis.warnings:
        print(f"  предупреждения: {'; '.join(analysis.warnings)}")

    if verbose:
        print()
        print(detector.build_report(analysis))

    return 1 if (missing or unexpected) else 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in FIXTURES_BY_KEY:
        return show(sys.argv[1], verbose=True)

    failures = 0
    for fixture in FIXTURES:
        failures += show(fixture.key)
    print()
    print(f"ИТОГО: страниц с проблемами — {failures} из {len(FIXTURES)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
