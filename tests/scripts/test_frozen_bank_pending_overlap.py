"""凍結題庫涉及度查證的純函式測試與真實檔案冒煙測試。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.analysis import frozen_bank_pending_overlap as subject

ROOT = Path(__file__).resolve().parents[2]


def test_normalize_article_accepts_article_and_subarticle_forms():
    assert subject.normalize_article("第2條") == "2"
    assert subject.normalize_article("第 21-3 條") == "21-3"
    assert subject.normalize_article("第2條第1項第1款") == "2"
    assert subject.normalize_article("附表一 項次一") == "附表一項次一"
    assert subject.normalize_article(None) is None


def test_source_law_maps_by_exact_folder_style_source_name():
    documents = [{"source": "N0060009_職業安全衛生設施規則"}, {"source": "N0030006_勞工請假規則"}]
    assert subject.source_law_to_document("N0060009_職業安全衛生設施規則", documents) == documents[0]["source"]
    assert subject.source_law_to_document("N0000000_不存在", documents) is None
    assert subject.source_law_to_document(None, documents) is None


def test_synthetic_pending_and_undetermined_classification():
    analysis = {
        "documents": [
            {"source": "N-PENDING_測試法", "kind": "single", "pending_articles": [
                {"article_no": "第 2 條", "scopes": ["article"], "dates": ["2027-01-01"]},
            ]},
            {"source": "N0030010_勞動契約法", "kind": "undetermined", "pending_articles": []},
        ]
    }
    pending, pending_sources, undetermined = subject.build_pending_index(analysis)
    question = {"id": "synthetic", "atomic_gold_facts": [
        {"exact_span": "待施行事實", "source_law": "N-PENDING_測試法", "source_article": "第2條"},
        {"exact_span": "現行事實", "source_law": "N-PENDING_測試法", "source_article": "第3條"},
        {"exact_span": "未定事實", "source_law": "N0030010_勞動契約法", "source_article": "第1條"},
    ]}
    classified = subject.classify_question(question, pending, pending_sources, undetermined)
    assert classified["pending"][0]["article_no"] == "2"
    assert classified["pending"][0]["scope"] == ["article"]
    assert classified["pending"][0]["effective_date"] == ["2027-01-01"]
    assert classified["five_doc_non_pending"][0]["article_no"] == "3"
    assert classified["undetermined"][0]["exact_span"] == "未定事實"


def test_synthetic_five_document_non_pending_and_selected_filter():
    analysis = {"as_of": "2026-10-03", "documents": [{
        "source": "N-PENDING_測試法", "kind": "single", "pending_articles": [
            {"article_no": "2", "scopes": ["article"], "dates": ["2027-01-01"]}
        ]
    }]}
    questions = [
        {"id": "hit", "atomic_gold_facts": [{"exact_span": "x", "source_law": "N-PENDING_測試法", "source_article": "第2條"}]},
        {"id": "current", "atomic_gold_facts": [{"exact_span": "y", "source_law": "N-PENDING_測試法", "source_article": "第3條"}]},
    ]
    pending, pending_sources, undetermined = subject.build_pending_index(analysis)
    report = subject.analyze_questions(questions, {"current"}, pending, pending_sources, undetermined)
    assert report["total_questions"] == 1
    assert report["pending"]["question_ids"] == []
    assert report["five_doc_non_pending"]["question_ids"] == ["current"]


def test_frozen_candidates_must_match_in_order():
    ids = [f"q{number}" for number in range(42)]
    assert subject.load_frozen_question_ids(
        {"eligible_ids": ids}, {"questions": [{"id": value} for value in ids]}
    ) == ids
    with pytest.raises(ValueError, match="不一致"):
        subject.load_frozen_question_ids(
            {"eligible_ids": ids}, {"questions": [{"id": ids[1]}, {"id": ids[0]}] + [{"id": value} for value in ids[2:]]}
        )


def test_real_files_smoke_output_shape_without_locking_numbers():
    pending = json.loads((ROOT / "data/analysis/kg4_pending_effect_20261003.json").read_text(encoding="utf-8"))
    questions = json.loads((ROOT / "data/eval/test_cases.json").read_text(encoding="utf-8"))["questions"]
    manifest = json.loads((ROOT / "data/eval/baseline_runs/20260920_frozen/frozen_manifest.json").read_text(encoding="utf-8"))
    alternate = json.loads((ROOT / "data/analysis/source_ambiguity/questions_frozen42.json").read_text(encoding="utf-8"))
    frozen_ids = subject.load_frozen_question_ids(manifest, alternate)
    report = subject.build_report(
        questions,
        frozen_ids,
        pending,
        frozen_manifest_path="data/eval/baseline_runs/20260920_frozen/frozen_manifest.json",
        frozen_alternate_path="data/analysis/source_ambiguity/questions_frozen42.json",
    )
    assert set(report) == {"as_of", "frozen_42", "all_65", "method"}
    for key in ("frozen_42", "all_65"):
        assert set(report[key]) == {"total_questions", "pending", "undetermined", "five_doc_non_pending"}
        for category in ("pending", "undetermined", "five_doc_non_pending"):
            assert {"question_count", "question_ids", "questions"} == set(report[key][category])
            assert all("question_id" in item and "facts" in item for item in report[key][category]["questions"])
    assert report["method"]["frozen_42_candidates_equal"] is True
