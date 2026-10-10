"""Начальная схема UPA: сайты, снапшоты, карты элементов, сценарии, запуски.

Ревизия создаёт все таблицы из ``Base.metadata``. Такой подход («схема = модели»)
выбран для старта проекта: он гарантирует, что миграция и ORM не разойдутся.
Для последующих изменений схемы следует писать явные ``op.create_table`` /
``op.add_column`` в новых ревизиях.

Revision ID: 0001_initial
Revises:
Create Date: 2026-02-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.storage import Base

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Создаёт все таблицы приложения."""
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    """Удаляет все таблицы приложения в обратном порядке зависимостей."""
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind, checkfirst=True)
