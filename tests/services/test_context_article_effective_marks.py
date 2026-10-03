from __future__ import annotations

import json
import inspect
import re
from pathlib import Path
from uuid import uuid4

import pytest

from services import semantic_marks as sm
from services.context import trace_marks
from repositories.law_document_repo import LawDocumentRepository

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "kg4_effective_notes_20261003.json"
AS_OF = "2026-10-03"


def _notes() -> dict[str, str | None]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return {item["source"]: item["note"] for item in payload["documents"]}


def test_article_effective_marks_covers_whole_partial_range_and_locators():
    notes = _notes()
    construction = "N0060014_營造安全衛生設施標準"
    facilities = "N0060009_職業安全衛生設施規則"
    training = "N0060010_職業安全衛生教育訓練規則"
    health = "N0060022_勞工健康保護規則"
    result = trace_marks.article_effective_marks(
        as_of=AS_OF,
        document_notes=notes,
        document_status={
            construction: "has_pending", facilities: "has_pending",
            training: "has_pending", health: "has_pending",
        },
        evidence_keys=[
            (construction, 1), (facilities, 2), (training, 3),
            (health, 4),
        ],
        article_nos={
            (construction, 1): "第 11-2 條",
            (facilities, 2): "第 185-2 條",
            (training, 3): "第 3 條",
            (health, 4): "第 6 條",
        },
        known_articles={
            construction: ["第 11-2 條", "第 12 條"],
            facilities: ["第 21-3 條", "第 57 條", "第 116 條", "第 185 條",
                          "第 185-1 條", "第 185-2 條", "第 185-3 條", "第 185-4 條"],
            training: ["第 3 條"],
            health: ["第 6 條", "第 5 條", "第 17 條"],
        },
    )

    assert result[(construction, 1)] == {
        "status": "pending_whole", "effective_from": "2027-07-01", "locators": [],
    }
    assert result[(facilities, 2)]["status"] == "pending_partial"
    assert result[(facilities, 2)]["effective_from"] == "2027-01-01"
    assert result[(training, 3)] == {
        "status": "pending_partial", "effective_from": "2027-01-01", "locators": ["附表一"],
    }
    assert result[(health, 4)]["status"] == "pending_partial"
    assert result[(health, 4)]["effective_from"] == "2027-07-01"
    assert result[(health, 4)]["locators"] == ["第2～4項"]


def test_article_effective_marks_matches_all_report_273_status_examples():
    notes = _notes()
    construction = "N0060014_營造安全衛生設施標準"
    facilities = "N0060009_職業安全衛生設施規則"
    training = "N0060010_職業安全衛生教育訓練規則"
    health = "N0060022_勞工健康保護規則"
    labor_contract = "N0030010_勞動契約法"
    leave = "N0030006_勞工請假規則"
    no_information = "N0060001_勞動基準法"
    evidence = [
        (construction, "11-2"), (construction, "12"),
        *((facilities, article) for article in ("21-3", "57", "116", "185-1", "185-2", "185-3", "185-4")),
        (training, "3"), (health, "5"), (health, "6"), (health, "17"),
        (labor_contract, "1"), (no_information, "1"), (leave, "7"),
    ]
    evidence_keys = [(doc, index) for index, (doc, _) in enumerate(evidence)]
    result = trace_marks.article_effective_marks(
        as_of=AS_OF,
        document_notes={**notes, no_information: None},
        document_status={
            construction: "has_pending", facilities: "has_pending",
            training: "has_pending", health: "has_pending",
            labor_contract: "undetermined", no_information: "no_information", leave: "in_force",
        },
        evidence_keys=evidence_keys,
        article_nos={key: f"第 {article} 條" for key, (_, article) in zip(evidence_keys, evidence)},
        known_articles={
            construction: ["11-2", "12"],
            facilities: ["21-3", "57", "116", "185", "185-1", "185-2", "185-3", "185-4"],
            training: ["3"],
            health: [str(number) for number in range(1, 30)],
            labor_contract: [], no_information: [], leave: ["7", "9", "9-1", "12"],
        },
    )
    expected = {
        (construction, "11-2"): ("pending_whole", "2027-07-01", []),
        (construction, "12"): ("in_force", None, []),
        **{(facilities, article): ("pending_partial", "2027-01-01", [])
           for article in ("21-3", "57", "116", "185-1", "185-2", "185-3", "185-4")},
        (training, "3"): ("pending_partial", "2027-01-01", ["附表一"]),
        (health, "5"): ("pending_partial", "2027-07-01", []),
        (health, "6"): ("pending_partial", "2027-07-01", ["第2～4項"]),
        (health, "17"): ("pending_partial", "2028-01-01", []),
        (labor_contract, "1"): ("undetermined", None, []),
        (no_information, "1"): ("no_information", None, []),
        (leave, "7"): ("in_force", None, []),
    }
    for (doc, article), (status, effective_from, locators) in expected.items():
        key = next(key for key, item in zip(evidence_keys, evidence) if item == (doc, article))
        actual = result[key]
        assert (actual["status"], actual["effective_from"], actual["locators"]) == (
            status, effective_from, locators
        )


def test_article_effective_marks_reuses_parse_and_directly_carries_nonpending(monkeypatch):
    calls = 0

    def fail_parse(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("非待施行文件不應解析")

    import services.effective_note as effective_note

    monkeypatch.setattr(effective_note, "parse_effective_note", fail_parse)
    result = trace_marks.article_effective_marks(
        as_of=AS_OF,
        document_notes={"force": None, "unknown": None},
        document_status={"force": "in_force", "unknown": "undetermined"},
        evidence_keys=[("force", 1), ("force", 2), ("unknown", 3)],
        article_nos={("force", 1): "第 1 條", ("force", 2): "第 2 條", ("unknown", 3): "第 3 條"},
        known_articles={},
    )
    assert result == {
        ("force", 1): {"status": "in_force", "effective_from": None, "locators": []},
        ("force", 2): {"status": "in_force", "effective_from": None, "locators": []},
        ("unknown", 3): {"status": "undetermined", "effective_from": None, "locators": []},
    }
    assert calls == 0


def test_article_effective_marks_missing_document_or_article_is_indeterminate_and_skips_missing_keys():
    result = trace_marks.article_effective_marks(
        as_of=AS_OF,
        document_notes={"pending": "一百十五年六月三十日增訂之第 11-2 條，自一百十六年七月一日施行。"},
        document_status={"pending": "has_pending"},
        evidence_keys=[("pending", None), (None, 1), ("missing", 2), ("pending", 3)],
        article_nos={},
        known_articles={"pending": ["11-2"]},
    )
    assert ("pending", None) not in result
    assert (None, 1) not in result
    assert result[("missing", 2)] == {
        "status": sm.INDETERMINATE, "effective_from": None, "locators": [],
    }
    assert result[("pending", 3)] == {
        "status": sm.INDETERMINATE, "effective_from": None, "locators": [],
    }


def test_article_effective_marks_parses_each_pending_document_once(monkeypatch):
    import services.effective_note as effective_note

    original = effective_note.parse_effective_note
    calls = 0

    def counted_parse(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(effective_note, "parse_effective_note", counted_parse)
    doc = "一百十五年六月三十日增訂之第 11-2 條，自一百十六年七月一日施行。"
    result = trace_marks.article_effective_marks(
        as_of=AS_OF,
        document_notes={"pending": doc},
        document_status={"pending": "has_pending"},
        evidence_keys=[("pending", 1), ("pending", 2)],
        article_nos={("pending", 1): "第 11-2 條", ("pending", 2): "第 12 條"},
        known_articles={"pending": ["11-2", "12"]},
    )
    assert result[("pending", 1)]["status"] == "pending_whole"
    assert result[("pending", 2)]["status"] == "in_force"
    assert calls == 1


def test_s2b_structure_guards_clock_dependencies_and_read_only_queries():
    service_paths = [
        ROOT / "services" / "effective_note.py",
        ROOT / "services" / "context" / "telemetry.py",
        ROOT / "services" / "context" / "trace_marks.py",
    ]
    for path in service_paths:
        source = path.read_text(encoding="utf-8")
        assert not any(token in source for token in ("date.today", "datetime.now", "time.time"))
        assert not any(token in source for token in ("import neo4j", "import requests", "import httpx", "os.environ"))

    router_source = (ROOT / "routers" / "agent.py").read_text(encoding="utf-8")
    assert router_source.count("date.today()") == 1

    write_keywords = ("SET", "CREATE", "MERGE", "DELETE", "REMOVE", "DETACH", "CALL")
    for method in (
        LawDocumentRepository.article_nos_for_evidence,
        LawDocumentRepository.list_article_nos,
    ):
        source = inspect.getsource(method).upper()
        query = re.findall(r'"""(.*?)"""', source, re.DOTALL)[1]
        assert all(re.search(rf"\b{keyword}\b", query) is None for keyword in write_keywords)


@pytest.mark.parametrize("include_semantic_marks", [False, True])
def test_trace_article_status_is_appended_only_when_semantic_marks_enabled(include_semantic_marks):
    from models.knowledge_graph import SVOTriple
    from services.context.telemetry import build_retrieval_trace

    triple = SVOTriple(subject="甲", verb="導致", object="乙", source_svo_chunk_index=7)
    facts = [{"fact_text": "甲 導致 乙", "source_svo_chunk_index": 7}]
    kwargs = {
        "include_semantic_marks": include_semantic_marks,
        "document_effective_status": {},
        "article_effective_status": {
            (None, 7): {"status": "pending_partial", "effective_from": "2027-01-01", "locators": ["附表一"]},
        },
    }
    trace = build_retrieval_trace([triple], facts, None, **kwargs)
    if not include_semantic_marks:
        assert "semantic_marks" not in trace["facts"][0]
        assert "semantic_marks" not in trace["triples"][0]
        return
    for entry in trace["facts"] + trace["triples"]:
        assert entry["semantic_marks"]["article_effective_status"] == sm.INDETERMINATE
        assert "article_effective_from" not in entry["semantic_marks"]
        assert list(entry["semantic_marks"])[-1] == "article_effective_status"


def test_trace_article_status_preserves_order_and_pending_fields_and_missing_values_are_indeterminate():
    from models.knowledge_graph import SVOTriple
    from services.context.telemetry import build_retrieval_trace

    doc_id = uuid4()
    triple = SVOTriple(subject="甲", verb="導致", object="乙", source_doc_id=doc_id, source_svo_chunk_index=7)
    triple_missing_chunk = SVOTriple(
        subject="丙", verb="導致", object="丁", source_doc_id=doc_id, source_svo_chunk_index=None,
    )
    facts = [{
        "fact_text": "甲 導致 乙", "source_doc_id": str(doc_id), "source_svo_chunk_index": 7,
        "subject": "甲", "verb": "導致", "object": "乙", "rel_type": "CAUSES",
    }, {
        "fact_text": "丙", "source_doc_id": None, "source_svo_chunk_index": None,
    }]
    trace = build_retrieval_trace(
        [triple], facts, None,
        include_semantic_marks=True,
        document_effective_status={str(doc_id): "has_pending"},
        article_effective_status={
            (str(doc_id), 7): {"status": "pending_partial", "effective_from": "2027-01-01", "locators": ["附表一"]},
        },
    )
    marks = trace["facts"][0]["semantic_marks"]
    assert marks["document_effective_status"] == "has_pending"
    assert marks["article_effective_status"] == "pending_partial"
    assert marks["article_effective_from"] == "2027-01-01"
    assert marks["article_pending_locators"] == ["附表一"]
    assert list(marks)[-3:] == [
        "article_effective_status", "article_effective_from", "article_pending_locators",
    ]
    assert trace["facts"][1]["semantic_marks"]["article_effective_status"] == sm.INDETERMINATE

    missing_trace = build_retrieval_trace(
        [triple_missing_chunk], [], None,
        include_semantic_marks=True,
        document_effective_status={str(doc_id): "has_pending"},
        article_effective_status={},
    )
    assert missing_trace["triples"][0]["semantic_marks"]["article_effective_status"] == sm.INDETERMINATE
