"""S2 trace marks、延遲匯入與旗標開關測試。"""
from __future__ import annotations

import ast
from pathlib import Path
from uuid import uuid4

from models.knowledge_graph import SVOTriple
from models.law_document import LawDocument
from services import semantic_marks as sm
from services.context import telemetry, trace_marks

ROOT = Path(__file__).resolve().parents[2]


def _document(note: str | None = None) -> LawDocument:
    return LawDocument(
        kg_id=uuid4(), source_doc_id=uuid4(), source="fixture", title="fixture",
        record_type="law", content_hash="hash", effective_note=note,
    )


def _triple(doc_id=None) -> SVOTriple:
    return SVOTriple(
        subject="甲", subject_type="概念", rel_type="CAUSES", verb="導致", object="乙",
        object_type="概念", source_doc_id=doc_id,
    )


def test_serialize_sources_passes_effective_as_of_to_triples_and_facts():
    doc_id = uuid4()
    doc = LawDocument(
        kg_id=uuid4(), source_doc_id=doc_id, source="fixture", title="fixture",
        record_type="law", content_hash="hash",
        effective_note="一百十五年六月三十日增訂之第 11-2 條，自一百十六年七月一日施行。",
    )
    serialized = telemetry.serialize_sources(
        [_triple(doc_id)],
        [{"fact_text": "甲 導致 乙", "source_doc_id": str(doc_id)}],
        None,
        {str(doc_id): doc},
        effective_as_of="2026-10-03",
    )
    for entry in serialized["triples"] + serialized["facts"]:
        assert entry["document"]["effective_status"] == "has_pending"
        assert entry["document"]["effective_pending_dates"] == ["2027-07-01"]


def test_trace_appends_document_status_and_unknown_fallback_only_when_enabled():
    doc_id = uuid4()
    triples = [_triple(doc_id), _triple()]
    facts = [
        {"fact_text": "甲 導致 乙", "subject": "甲", "object": "乙", "verb": "導致",
         "rel_type": "CAUSES", "source_doc_id": str(doc_id)},
        {"fact_text": "丙", "subject": "丙", "object": "", "verb": "", "rel_type": "RELATED_TO"},
    ]
    trace = telemetry.build_retrieval_trace(
        triples, facts, None, include_semantic_marks=True,
        document_effective_status={str(doc_id): "has_pending"},
    )
    assert trace["facts"][0]["semantic_marks"]["document_effective_status"] == "has_pending"
    assert trace["triples"][0]["semantic_marks"]["document_effective_status"] == "has_pending"
    assert trace["facts"][1]["semantic_marks"]["document_effective_status"] == sm.INDETERMINATE
    assert trace["triples"][1]["semantic_marks"]["document_effective_status"] == sm.INDETERMINATE
    assert list(trace["facts"][0]["semantic_marks"])[-1] == "document_effective_status"

    no_map = telemetry.build_retrieval_trace(
        triples, facts, None, include_semantic_marks=True, document_effective_status=None,
    )
    off = telemetry.build_retrieval_trace(
        triples, facts, None, include_semantic_marks=False,
        document_effective_status={str(doc_id): "has_pending"},
    )
    assert all("document_effective_status" not in e["semantic_marks"] for e in no_map["facts"] + no_map["triples"])
    assert all("semantic_marks" not in e for e in off["facts"] + off["triples"])


def test_effective_marks_kwargs_closed_is_empty_and_open_summarizes_documents():
    doc = _document("一百十五年六月三十日增訂之第 11-2 條，自一百十六年七月一日施行。")
    assert trace_marks.effective_marks_kwargs(False, "not-a-date", {"doc": doc, "none": None}) == ({}, {})
    sources_kwargs, trace_kwargs = trace_marks.effective_marks_kwargs(
        True, "2026-10-03", {"doc": doc, "none": None}
    )
    assert sources_kwargs == {"effective_as_of": "2026-10-03"}
    assert trace_kwargs == {"document_effective_status": {"doc": "has_pending"}}


def test_s2_structure_guards_and_delayed_effective_note_import():
    service_paths = [
        ROOT / "services" / "effective_note.py",
        ROOT / "services" / "context" / "telemetry.py",
        ROOT / "services" / "context" / "trace_marks.py",
    ]
    for path in service_paths:
        source = path.read_text(encoding="utf-8")
        assert "date.today" not in source
        assert "datetime.now" not in source
        assert "time.time" not in source
        assert not any(token in source for token in ("import neo4j", "import requests", "import httpx", "os.environ"))

    telemetry_tree = ast.parse(service_paths[1].read_text(encoding="utf-8"))
    top_level_imports = [node for node in telemetry_tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert all("effective_note" not in ast.unparse(node) for node in top_level_imports)
    assert "from services.effective_note import summarize_document_effective" in service_paths[1].read_text(encoding="utf-8")
    assert "from services.effective_note import summarize_document_effective" in service_paths[2].read_text(encoding="utf-8")


def test_effective_note_imports_only_allowed_production_files():
    excluded = {"tests", "docs", ".claude", ".git", "scripts"}
    allowed = {
        ROOT / "services" / "effective_note.py",
        ROOT / "services" / "context" / "telemetry.py",
        ROOT / "services" / "context" / "trace_marks.py",
    }
    for path in ROOT.rglob("*.py"):
        if any(part in excluded for part in path.parts) or path.name.startswith(".env"):
            continue
        source = path.read_text(encoding="utf-8")
        if "from services.effective_note import" in source or "import services.effective_note" in source:
            assert path in allowed, path
