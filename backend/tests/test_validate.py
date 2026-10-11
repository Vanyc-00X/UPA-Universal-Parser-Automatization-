"""Тесты отчёта о полноте данных (Этап 4)."""

from __future__ import annotations

from app.editor.schema import ExtractionPlan, FieldSpec, ScenarioDefinition, SelectStrategy
from app.engine import validate
from app.engine.extractor import ExtractedRecord, ExtractionResult


def _definition() -> ScenarioDefinition:
    return ScenarioDefinition(
        url="https://shop.example.com/catalog",
        plan=ExtractionPlan(mode="list"),
        fields=[
            FieldSpec(
                key="title",
                title="Название",
                selector=".title",
                strategy=SelectStrategy.TEXT,
                required=True,
            ),
            FieldSpec(
                key="price",
                title="Цена",
                selector=".price",
                strategy=SelectStrategy.TEXT,
                required=True,
            ),
        ],
    )


def test_report_passes_when_required_fields_filled() -> None:
    result = ExtractionResult(
        records=[
            ExtractedRecord(values={"title": "A", "price": 100.0}, position=0),
            ExtractedRecord(values={"title": "B", "price": 200.0}, position=1),
        ]
    )
    report = validate.build_report(result, _definition(), base_url="https://shop.example.com/")
    assert report.passed is True
    assert report.records == 2
    assert report.required_coverage == 1.0


def test_report_fails_on_missing_required() -> None:
    result = ExtractionResult(
        records=[
            ExtractedRecord(values={"title": "A", "price": None}, position=0),
            ExtractedRecord(values={"title": "B", "price": 200.0}, position=1),
        ]
    )
    report = validate.build_report(result, _definition())
    assert report.passed is False
    assert report.invalid_records == 1
    assert report.fields["price"]["coverage"] == 0.5
    assert "полнота" in validate.describe_report(report).lower() or report.records == 2
