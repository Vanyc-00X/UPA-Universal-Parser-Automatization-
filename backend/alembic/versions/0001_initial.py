"""Начальная схема UPA: сайты, снапшоты, карты элементов, сценарии, запуски.

Каждая таблица описана явно через ``op.create_table``. Ранее здесь стоял вызов
``Base.metadata.create_all``, но это ловушка: такая ревизия ничего не делает на
уже существующей базе, поэтому последующие изменения схемы молча не применялись.
Явное описание делает историю миграций честной.

Revision ID: 0001_initial
Revises:
Create Date: 2026-02-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    """Метки создания и обновления записи — есть почти в каждой таблице."""
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    """Создаёт все таблицы приложения."""
    op.create_table(
        "sites",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("url", sa.String(2048), nullable=False, unique=True),
        sa.Column("origin", sa.String(512), nullable=False),
        sa.Column("title", sa.String(512)),
        sa.Column("favicon_url", sa.String(2048)),
        sa.Column("notes", sa.Text()),
        sa.Column("label", sa.String(256)),
        sa.Column("robots_txt", sa.Text()),
        sa.Column("last_visited_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index("ix_sites_origin", "sites", ["origin"])

    op.create_table(
        "snapshots",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("site_id", sa.String(32), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("final_url", sa.String(2048)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("http_status", sa.Integer()),
        sa.Column("title", sa.String(512)),
        sa.Column("lang", sa.String(32)),
        sa.Column("dom_hash", sa.String(64)),
        sa.Column("html_bytes", sa.Integer()),
        sa.Column("trimmed_bytes", sa.Integer()),
        sa.Column("est_tokens", sa.Integer()),
        sa.Column("collapsed_blocks", sa.Integer()),
        sa.Column("artifacts", sa.JSON(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("duration_ms", sa.Integer()),
        *_timestamps(),
    )
    op.create_index("ix_snapshots_site_id", "snapshots", ["site_id"])
    op.create_index("ix_snapshots_dom_hash", "snapshots", ["dom_hash"])

    op.create_table(
        "element_maps",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "snapshot_id",
            sa.String(32),
            sa.ForeignKey("snapshots.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("elements", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("llm_provider", sa.String(64)),
        sa.Column("llm_model", sa.String(128)),
        sa.Column("prompt_version", sa.String(32)),
        sa.Column("confidence", sa.Float()),
        sa.Column("edited_by_user", sa.Boolean(), nullable=False),
        *_timestamps(),
    )

    op.create_table(
        "scenarios",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("site_id", sa.String(32), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("schedule_cron", sa.String(64)),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint("site_id", "name", name="uq_scenarios_site_name"),
    )
    op.create_index("ix_scenarios_site_id", "scenarios", ["site_id"])

    op.create_table(
        "scenario_versions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "scenario_id",
            sa.String(32),
            sa.ForeignKey("scenarios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("change_note", sa.Text()),
        sa.Column("created_by", sa.String(32), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "scenario_id", "version", name="uq_scenario_versions_scenario_version"
        ),
    )
    op.create_index("ix_scenario_versions_scenario_id", "scenario_versions", ["scenario_id"])

    op.create_table(
        "runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("scenario_id", sa.String(32), sa.ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "scenario_version_id",
            sa.String(32),
            sa.ForeignKey("scenario_versions.id", ondelete="SET NULL"),
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("trigger", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("pages_done", sa.Integer(), nullable=False),
        sa.Column("pages_total", sa.Integer()),
        sa.Column("items_count", sa.Integer(), nullable=False),
        sa.Column("errors_count", sa.Integer(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("stats", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text()),
        *_timestamps(),
    )
    op.create_index("ix_runs_scenario_id", "runs", ["scenario_id"])
    op.create_index("ix_runs_status", "runs", ["status"])

    op.create_table(
        "run_items",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("run_id", sa.String(32), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("dedup_key", sa.String(128)),
        sa.Column("source_url", sa.String(2048)),
        sa.Column("is_valid", sa.Boolean(), nullable=False),
        sa.Column("validation_errors", sa.JSON(), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_run_items_run_id", "run_items", ["run_id"])
    op.create_index("ix_run_items_dedup_key", "run_items", ["dedup_key"])

    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("run_id", sa.String(32), sa.ForeignKey("runs.id", ondelete="CASCADE")),
        sa.Column("snapshot_id", sa.String(32), sa.ForeignKey("snapshots.id", ondelete="CASCADE")),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("rel_path", sa.String(1024), nullable=False),
        sa.Column("size_bytes", sa.Integer()),
        sa.Column("mime", sa.String(128)),
        sa.Column("meta", sa.JSON(), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_artifacts_run_id", "artifacts", ["run_id"])
    op.create_index("ix_artifacts_snapshot_id", "artifacts", ["snapshot_id"])


def downgrade() -> None:
    """Удаляет все таблицы в обратном порядке зависимостей."""
    for table in (
        "artifacts",
        "run_items",
        "runs",
        "scenario_versions",
        "scenarios",
        "element_maps",
        "snapshots",
        "sites",
    ):
        op.drop_table(table)
