"""Добавляет в карту элементов черновик сценария.

Revision ID: 0002_edit_draft
Revises: 0001_initial
Create Date: 2026-02-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_edit_draft"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Добавляет колонку с черновиком сценария.

    Batch-режим обязателен: SQLite не умеет ALTER COLUMN, а alembic в этом
    режиме пересоздаёт таблицу.
    """
    with op.batch_alter_table("element_maps") as batch:
        batch.add_column(sa.Column("edit_draft", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Удаляет колонку с черновиком."""
    with op.batch_alter_table("element_maps") as batch:
        batch.drop_column("edit_draft")
