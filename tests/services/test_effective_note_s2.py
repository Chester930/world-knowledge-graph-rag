"""S2 文件層施行摘要與來源序列化測試。"""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from models.law_document import LawDocument
from services.effective_note import (
    DocumentEffectiveSummary,
    STATUS_IN_FORCE,
    STATUS_NO_INFORMATION,
    STATUS_UNDETERMINED,
    summarize_document_effective,
)
from services.context.telemetry import serialize_document

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "kg4_effective_notes_20261003.json"
AS_OF = "2026-10-03"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _document(note: str | None) -> LawDocument:
    doc_id = uuid4()
    return LawDocument(
        kg_id=uuid4(), source_doc_id=doc_id, source="fixture", title="fixture",
        record_type="law", content_hash="hash", effective_note=note,
    )


def test_summary_matches_all_sixteen_real_note_categories_and_dates():
    documents = _fixture()["documents"]
    expected_dates = {
        "N0060022_勞工健康保護規則": ("2027-07-01", "2028-01-01"),
        "N0060009_職業安全衛生設施規則": ("2027-01-01",),
        "N0060010_職業安全衛生教育訓練規則": ("2027-01-01",),
        "N0060004_勞工作業場所容許暴露標準": ("2027-01-01",),
        "N0060014_營造安全衛生設施標準": ("2027-07-01",),
    }
    for document in documents:
        summary = summarize_document_effective(document["note"], AS_OF)
        if document["source"] in expected_dates:
            assert summary == DocumentEffectiveSummary("has_pending", expected_dates[document["source"]])
        elif document["expected"]["kind"] == "undetermined":
            assert summary == DocumentEffectiveSummary(STATUS_UNDETERMINED, ())
        else:
            assert summary == DocumentEffectiveSummary(STATUS_IN_FORCE, ())


def test_summary_empty_none_and_unparsed_are_no_information():
    for note in (None, "", "一些無法解析的文字", "一百十五年十三月一日修正第 1 條"):
        assert summarize_document_effective(note, AS_OF) == DocumentEffectiveSummary(
            STATUS_NO_INFORMATION, ()
        )


def test_summary_as_of_boundary_and_date_deduplication():
    note = "一百十五年六月三十日修正第 21-3 條，自一百十六年一月一日施行。"
    assert summarize_document_effective(note, "2026-12-31").pending_dates == ("2027-01-01",)
    assert summarize_document_effective(note, "2027-01-01").status == STATUS_IN_FORCE
    staged = _fixture()["documents"][1]["note"]
    assert summarize_document_effective(staged, AS_OF).pending_dates == (
        "2027-07-01", "2028-01-01"
    )


@pytest.mark.parametrize("as_of", ["2026-1-01", "2026/10/03", "2026-13-01", None])
def test_summary_validates_as_of(as_of):
    with pytest.raises(ValueError):
        summarize_document_effective("施行日期以命令定之。", as_of)


def test_serialize_document_effective_fields_are_appended_and_default_is_unchanged():
    document = _document("一百十五年六月三十日增訂之第 11-2 條，自一百十六年七月一日施行。")
    baseline = serialize_document(document)
    assert list(baseline) == ["title", "update_date", "effective_date", "effective_note"]
    enriched = serialize_document(document, effective_as_of="2026-10-03")
    assert list(enriched) == [
        "title", "update_date", "effective_date", "effective_note",
        "effective_status", "effective_pending_dates",
    ]
    assert enriched["effective_status"] == "has_pending"
    assert enriched["effective_pending_dates"] == ["2027-07-01"]
    assert enriched["title"] == baseline["title"]
    assert serialize_document(None, effective_as_of="2026-10-03") is None
