import hashlib
import json

import pytest

from scripts.analysis.source_ambiguity_audit import (
    _cross_document_metric_values,
    PHASE2_STAGE_DIRECTORIES,
    AGGR18_EXPECTED_FACT_TEXTS,
    FactCitation,
    analyze_prompt_records,
    analyze_question,
    article_number,
    build_question_audit,
    candidate_questions,
    complete_aggr18_article_matches,
    frame_overlap,
    global_collision_report,
    jaccard_similarity,
    load_phase2_snapshot,
    normalize_text,
    pair_span_to_facts,
    validate_aggr18_preflight,
)


OLD_LAW = "N0060041_職業災害勞工保護法"
NEW_LAW = "N0050031_勞工職業災害保險及保護法"


def make_citation(article_no, fact_text, source_doc_id, title, fact_id=None):
    return FactCitation(
        fact_id=fact_id or f"fact-{source_doc_id}-{article_no}",
        fact_text=fact_text,
        document_title=title,
        source_doc_id=source_doc_id,
        article_no=article_no,
    )


def aggr18_question():
    return {
        "id": "57-AGGR18",
        "question": "新法（勞工職業災害保險及保護法）與舊法（職業災害勞工保護法）的認定機構有何不同？",
        "atomic_gold_facts": [
            {
                "exact_span": "職業災害勞工經醫療終止後，經公立醫療機構認定身心障礙不堪勝任工作。",
                "source_law": OLD_LAW,
                "source_article": "第23條第2款",
            },
            {
                "exact_span": "經公立醫療機構認定身心障礙不堪勝任工作。",
                "source_law": OLD_LAW,
                "source_article": "第24條第1款",
            },
            {
                "exact_span": "職業災害勞工經醫療終止後，經中央衛生福利主管機關醫院評鑑合格醫院認定身心障礙不堪勝任工作。",
                "source_law": NEW_LAW,
                "source_article": "第84條第1項第2款",
            },
            {
                "exact_span": "經中央衛生福利主管機關醫院評鑑合格醫院認定身心障礙不堪勝任工作。",
                "source_law": NEW_LAW,
                "source_article": "第85條第1項第1款",
            },
        ],
    }


def aggr18_citations():
    return [
        make_citation(
            "23",
            AGGR18_EXPECTED_FACT_TEXTS["23"],
            "N0060041",
            "職業災害勞工保護法",
        ),
        make_citation(
            "24",
            AGGR18_EXPECTED_FACT_TEXTS["24"],
            "N0060041",
            "職業災害勞工保護法",
        ),
        make_citation(
            "84",
            AGGR18_EXPECTED_FACT_TEXTS["84"],
            "N0050031",
            "勞工職業災害保險及保護法",
        ),
        make_citation(
            "85",
            AGGR18_EXPECTED_FACT_TEXTS["85"],
            "N0050031",
            "勞工職業災害保險及保護法",
        ),
    ]


def test_normalize_nfkc_whitespace_punctuation_but_not_simplified_conversion():
    assert normalize_text("ＡＢＣ  第３條，(甲) —") == normalize_text("ABC第3條甲")
    assert normalize_text("勞工") != normalize_text("劳动")


def test_global_exact_collision_counts_fact_and_text_denominators_separately():
    rows = [
        make_citation("1", "同 一 句。", "doc-a", "法規甲", fact_id="a1"),
        make_citation("2", "同一 句", "doc-a", "法規甲", fact_id="a2"),
        make_citation("3", "同一句！", "doc-b", "法規乙", fact_id="b1"),
        make_citation("1", "另一句。", "doc-c", "法規丙", fact_id="c1"),
    ]

    result = global_collision_report(rows)

    assert result["actual_fact_count"] == 4
    assert result["distinct_normalized_text_count"] == 2
    assert result["same_text_cross_document_distinct_text_count"] == 1
    assert result["same_text_cross_document_fact_count"] == 3
    assert result["same_text_cross_document_fact_ratio_by_facts"] == pytest.approx(0.75)
    assert result["same_text_cross_document_text_ratio_by_facts"] == pytest.approx(0.25)
    assert result["same_text_cross_document_text_ratio_by_distinct_texts"] == pytest.approx(0.5)


def test_aggr18_four_fact_texts_match_the_taskbook_jaccard_and_frame_baselines():
    facts = AGGR18_EXPECTED_FACT_TEXTS
    expected_pairs = [
        ("23", "84", 0.489, 0.806),
        ("24", "85", 0.262, 0.632),
        ("23", "85", 0.362, None),
        ("24", "84", 0.255, None),
        ("23", "24", 0.621, None),
    ]

    for left, right, expected_jaccard, expected_frame in expected_pairs:
        assert jaccard_similarity(facts[left], facts[right]) == pytest.approx(
            expected_jaccard, abs=0.01
        )
        if expected_frame is not None:
            assert frame_overlap(facts[left], facts[right]) == pytest.approx(
                expected_frame, abs=0.01
            )
    assert normalize_text(facts["23"]) != normalize_text(facts["84"])
    assert normalize_text(facts["24"]) != normalize_text(facts["85"])
    unrelated_left = "事假 一年內合計不得超過 十四日"
    unrelated_right = "特別休假 五年以上十年未滿者 每年十五日"
    assert frame_overlap(unrelated_left, unrelated_right) < 0.15


def test_frame_overlap_caps_prefix_suffix_and_handles_substrings():
    assert frame_overlap("甲乙甲", "甲乙甲") == 1.0
    assert frame_overlap("甲乙甲乙甲", "乙甲乙") <= 1.0
    assert frame_overlap("法規前段共同後段", "完全不同句") <= 1.0


def test_article_number_extracts_gold_and_law_article_forms():
    assert article_number("第23條第2款") == "23"
    assert article_number("§ 84 第1項") == "84"
    assert article_number("85") == "85"
    assert article_number(None) is None


def test_span_pairing_separates_primary_and_same_law_adjacent_article():
    citations = aggr18_citations()
    matches = pair_span_to_facts(
        "經公立醫療機構認定身心障礙不堪勝任工作。",
        citations,
        OLD_LAW,
        "第24條第1款",
    )

    assert {match["matched_article_no"] for match in matches} == {"23", "24"}
    assert {match["matched_article_equals_gold"] for match in matches} == {True, False}
    assert {
        match["pair_type"] for match in matches
    } == {"主配對", "額外配對（同法他條）"}
    assert sum(match["matched_article_equals_gold"] for match in matches) == 1


def test_span_pairing_requires_eight_chars_and_records_one_to_many_candidates():
    citations = aggr18_citations()
    assert pair_span_to_facts("第23條", citations, OLD_LAW, "第23條") == []
    long_matches = pair_span_to_facts(
        "職業災害勞工經醫療終止後，經公立醫療機構認定身心障礙不堪勝任工作。",
        citations,
        OLD_LAW,
        "第23條第2款",
    )
    assert {match["matched_article_no"] for match in long_matches} == {"23", "24"}


def test_short_normalized_span_does_not_match_aggr18_facts_by_containment():
    assert pair_span_to_facts("公立醫療", aggr18_citations(), OLD_LAW, "第23條") == []


def test_aggr18_cross_document_metrics_compare_only_different_law_documents():
    metrics = _cross_document_metric_values(aggr18_citations(), source_law_count=2)

    # Four cross-law combinations count; the §23×§24 and §84×§85 same-law pairs do not.
    assert metrics["cross_doc_pair_count"] == 4
    assert metrics["max_cross_doc_jaccard"] == pytest.approx(0.489, abs=0.01)
    assert metrics["max_cross_doc_frame_overlap"] == pytest.approx(0.806, abs=0.01)


def test_aggr18_preflight_requires_four_expected_main_facts_and_metrics():
    result = validate_aggr18_preflight(aggr18_question(), [
        {
            "fact_id": citation.fact_id,
            "fact_text": citation.fact_text,
            "document_title": citation.document_title,
            "source_doc_id": citation.source_doc_id,
            "article_no": citation.article_no,
        }
        for citation in aggr18_citations()
    ])

    assert result["passed"] is True
    assert result["cross_law_exact_text_match"] is False
    assert set(result["actual_normalized_main_fact_texts"]) == {"23", "24", "84", "85"}
    actual_span_matches = {
        item["gold_article_no"]: item["matched_same_law_article_nos"]
        for item in result["matched_same_law_articles_by_span"]
    }
    assert actual_span_matches == {
        "23": ["23", "24"],
        "24": ["23", "24"],
        "84": ["84"],
        "85": ["84", "85"],
    }


def test_complete_aggr18_matches_preserve_short_fact_and_cross_law_extra():
    citations = [
        *aggr18_citations(),
        make_citation(
            "18",
            "職業災害勞工 經醫療終止後",
            "N0060041",
            "職業災害勞工保護法",
        ),
    ]
    audit = analyze_question(aggr18_question(), citations, {})
    matches = complete_aggr18_article_matches(audit)

    assert matches == [
        {
            "source_article": "第23條第2款",
            "gold_article_no": "23",
            "primary_article_nos": ["23"],
            "extra_same_law_article_nos": ["18", "24"],
            "other_law_article_nos": [],
            "unresolved_law_article_nos": [],
        },
        {
            "source_article": "第24條第1款",
            "gold_article_no": "24",
            "primary_article_nos": ["24"],
            "extra_same_law_article_nos": ["23"],
            "other_law_article_nos": [],
            "unresolved_law_article_nos": [],
        },
        {
            "source_article": "第84條第1項第2款",
            "gold_article_no": "84",
            "primary_article_nos": ["84"],
            "extra_same_law_article_nos": [],
            "other_law_article_nos": ["18"],
            "unresolved_law_article_nos": [],
        },
        {
            "source_article": "第85條第1項第1款",
            "gold_article_no": "85",
            "primary_article_nos": ["85"],
            "extra_same_law_article_nos": ["84"],
            "other_law_article_nos": [],
            "unresolved_law_article_nos": [],
        },
    ]


def test_question_analysis_uses_gold_laws_and_null_metrics_for_single_law():
    question = {
        "id": "single-law",
        "question": "勞動基準法如何規定？",
        "atomic_gold_facts": [
            {
                "exact_span": "雇主應依規定給付工資。",
                "source_law": "N0030001_勞動基準法",
                "source_article": "第22條",
            }
        ],
    }
    citations = [
        make_citation("22", "雇主應依規定給付工資", "N0030001", "勞動基準法")
    ]
    audit = analyze_question(question, citations, {})

    assert audit["n_source_laws"] == 1
    assert audit["max_cross_doc_jaccard"] is None
    assert audit["max_cross_doc_frame_overlap"] is None
    assert audit["primary_match_count"] == 1
    assert "matched_fact_count" not in audit


def test_single_law_question_keeps_all_cross_document_metrics_null():
    question = {
        "id": "single-law-duplicate-text",
        "question": "勞動基準法如何規定？",
        "atomic_gold_facts": [
            {
                "exact_span": "雇主應依規定給付工資。",
                "source_law": "N0030001_勞動基準法",
                "source_article": "第22條",
            }
        ],
    }
    citations = [
        make_citation("22", "雇主應依規定給付工資。", "doc-a", "勞動基準法"),
        make_citation("22", "雇主應依規定給付工資。", "doc-b", "勞動基準法"),
    ]

    audit = analyze_question(question, citations, {})

    assert audit["n_source_laws"] == 1
    assert audit["primary_match_count"] == 2
    assert audit["primary_only_metrics"] == {
        "cross_doc_pair_count": 0,
        "max_cross_doc_jaccard": None,
        "max_cross_doc_frame_overlap": None,
    }
    assert audit["including_extra_same_law_metrics"] == audit["primary_only_metrics"]
    assert audit["max_cross_doc_jaccard"] is None
    assert audit["max_cross_doc_frame_overlap"] is None


def test_unmatched_gold_span_is_explicitly_returned():
    question = {
        "id": "unmatched",
        "question": "題目文字",
        "atomic_gold_facts": [
            {
                "exact_span": "這個span在圖譜裡不存在",
                "source_law": OLD_LAW,
                "source_article": "第23條",
            }
        ],
    }

    audit = analyze_question(question, [], {})

    assert audit["unmatched_span_count"] == 1
    assert audit["unmatched_spans"] == ["這個span在圖譜裡不存在"]
    assert audit["primary_match_count"] == 0
    assert audit["extra_same_law_match_count"] == 0


def test_multilaw_gold_without_question_cue_is_separately_listed():
    question = {
        "id": "multi-no-cue",
        "question": "這兩項規定有何差異？",
        "atomic_gold_facts": [
            {"exact_span": "第一段至少八個字", "source_law": OLD_LAW, "source_article": "第1條"},
            {"exact_span": "第二段至少八個字", "source_law": NEW_LAW, "source_article": "第2條"},
        ],
    }
    audit = analyze_question(question, [], {})

    assert audit["n_source_laws"] == 2
    assert audit["q_mentions_multi_law"] is False
    report = candidate_questions([audit])
    assert report["candidate_ids_in_rank_order"] == []
    assert [item["id"] for item in report["multi_law_without_question_mention"]] == [
        "multi-no-cue"
    ]


def test_candidate_selection_requires_multilaw_gold_and_question_cue_and_sorts_by_frame():
    citations = aggr18_citations()
    aggr18_audit = analyze_question(aggr18_question(), citations, {})
    low_frame_question = {
        "id": "multi-no-cue",
        "question": "兩項規定有何差異？",
        "atomic_gold_facts": [
            {
                "exact_span": "事假 一年內合計不得超過 十四日",
                "source_law": OLD_LAW,
                "source_article": "第1條",
            },
            {
                "exact_span": "特別休假 五年以上十年未滿者 每年十五日",
                "source_law": NEW_LAW,
                "source_article": "第2條",
            },
        ],
    }
    low_frame_audit = analyze_question(low_frame_question, [], {})
    low_frame_audit["q_mentions_multi_law"] = True
    single_law_audit = {
        **low_frame_audit,
        "id": "single-law",
        "n_source_laws": 1,
    }

    report = candidate_questions([aggr18_audit, low_frame_audit, single_law_audit])

    assert report["candidate_ids_in_rank_order"] == ["57-AGGR18", "multi-no-cue"]
    assert report["aggr18_candidate_status"]["included"] is True
    assert report["multi_law_without_question_mention"] == []


def test_question_audit_json_has_no_vector_or_credential_fields():
    result = build_question_audit([aggr18_question()], aggr18_citations())
    serialized = json.dumps(result, ensure_ascii=False)

    assert "fact_embedding" not in serialized
    assert "NEO4J_PASSWORD" not in serialized


def phase2_record(question_id, prompt_context_lines, traces):
    return {
        "question_id": question_id,
        "lineage": {
            "stage2_context": {"prompt_context_lines": prompt_context_lines},
            "stage1_retrieval": {"retrieval_trace": traces},
        },
    }


def phase2_trace(text, source_doc_id, kind="fact", *, in_prompt=True, article_no="第1條"):
    return {
        "kind": kind,
        "text": text,
        "source_doc_id": source_doc_id,
        "article_no": article_no,
        "in_prompt": in_prompt,
    }


def test_prompt_analysis_handles_nested_flat_and_empty_prompt_lists():
    records = {
        "nested": [
            phase2_record(
                "q1",
                [["- 第一行"], ["- 第二行"]],
                [phase2_trace("第一行", "doc-a"), phase2_trace("第二行", "doc-b")],
            )
        ],
        "flat": [
            phase2_record("q1", ["- 第三行"], [phase2_trace("第三行", "doc-c")]),
            phase2_record("q1", [], []),
        ],
    }

    result = analyze_prompt_records(records, {"q1"})

    assert result["prompt_line_count"] == 3
    assert result["prompt_line_status_counts"] == {
        "uniquely_attributed": 3,
        "multi_source_merged": 0,
        "unmatched": 0,
        "source_unresolved": 0,
    }
    assert result["by_trace_kind"]["fact"]["prompt_line_count"] == 3
    assert result["analyzed_prompt_record_count"] == 3


def test_prompt_analysis_separates_merged_duplicates_unmatched_and_independent_collisions():
    records = {
        "stage_a": [
            phase2_record(
                "q1",
                [[
                    "- 同 文。",
                    "- 同文",
                    "- 合併",
                    "- 重複",
                    "- 找不到",
                    "- 單獨",
                ]],
                [
                    phase2_trace("同文", "doc-a"),
                    phase2_trace("同文。", "doc-b"),
                    phase2_trace("合併", "doc-c"),
                    phase2_trace("合併", "doc-d"),
                    phase2_trace("重複", "doc-e", "fact"),
                    phase2_trace("重複", "doc-e", "bfs"),
                    phase2_trace("單獨", "doc-f", "triple"),
                ],
            )
        ]
    }

    result = analyze_prompt_records(records, {"q1"})

    assert result["prompt_line_count"] == 6
    assert result["prompt_line_status_counts"] == {
        "uniquely_attributed": 2,
        "multi_source_merged": 3,
        "unmatched": 1,
        "source_unresolved": 0,
    }
    assert result["same_document_duplicate_line_count"] == 1
    assert result["independent_cross_source_collision_line_count"] == 0
    assert result["independent_cross_source_collision_group_count"] == 0
    assert result["unmatched_prompt_rows"][0]["prompt_line"] == "- 找不到"
    assert result["cross_document_frame_overlap_pair_count"] == 1
    assert result["by_trace_kind"]["fact"]["multi_source_merged_line_count"] == 3
    assert result["by_trace_kind"]["fact"]["independent_cross_source_collision_line_count"] == 0
    assert result["by_trace_kind"]["bfs"]["prompt_line_count"] == 1
    assert result["by_trace_kind"]["bfs"]["same_document_duplicate_line_count"] == 0
    assert result["by_trace_kind"]["triple"]["uniquely_attributed_line_count"] == 1
    assert result["questions_with_independent_cross_source_collision"] == []
    assert result["questions_with_independent_cross_source_collision_ratio_of_eligible"] == 0.0


def test_same_question_across_folders_keeps_all_runs_without_cross_run_collision():
    records = {
        "stage_a": [phase2_record("q1", ["- 同句"], [phase2_trace("同句", "doc-a")])],
        "stage_b": [
            phase2_record("q1", ["- 同句"], [phase2_trace("同句", "doc-b")]),
            phase2_record("outside", ["- 不納入"], [phase2_trace("不納入", "doc-c")]),
        ],
    }

    result = analyze_prompt_records(records, {"q1"})

    assert result["prompt_line_count"] == 2
    assert result["analyzed_prompt_record_count"] == 2
    assert result["question_distribution"]["q1"]["prompt_line_count"] == 2
    assert result["independent_cross_source_collision_line_count"] == 0
    assert result["out_of_scope_records"] == [
        {"source_folder": "stage_b", "record_index": 1, "question_id": "outside"}
    ]


def test_phase2_snapshot_loader_verifies_allowlist_size_and_sha256(tmp_path):
    files = []
    for directory in PHASE2_STAGE_DIRECTORIES:
        records_path = tmp_path / directory / "records.json"
        records_path.parent.mkdir(parents=True)
        records_path.write_text("[]\n", encoding="utf-8")
        payload = records_path.read_bytes()
        files.append(
            {
                "directory": directory,
                "status": "snapshot_copy",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
            }
        )
    (tmp_path / "snapshot_manifest.json").write_text(
        json.dumps(
            {"included_directories": list(PHASE2_STAGE_DIRECTORIES), "files": files},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    records, manifest = load_phase2_snapshot(tmp_path)

    assert list(records) == list(PHASE2_STAGE_DIRECTORIES)
    assert all(records[directory] == [] for directory in PHASE2_STAGE_DIRECTORIES)
    assert len(manifest["verified_files"]) == 8
    assert manifest["verified_files"][0]["bytes"] == 4
    changed_file = tmp_path / PHASE2_STAGE_DIRECTORIES[0] / "records.json"
    changed_file.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="hash or size mismatch"):
        load_phase2_snapshot(tmp_path)
