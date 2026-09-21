import json

import pytest

from scripts.analysis.source_ambiguity_audit import (
    AGGR18_EXPECTED_FACT_TEXTS,
    FactCitation,
    analyze_question,
    article_number,
    build_question_audit,
    candidate_questions,
    frame_overlap,
    global_collision_report,
    jaccard_similarity,
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
