"""唯讀盤點跨法規來源歧義；所有分析函式皆不依賴 Neo4j。"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
PRIMARY_CHECKOUT = ROOT.parent.parent.parent
DEFAULT_ENV_FILE = PRIMARY_CHECKOUT / ".env"
DEFAULT_FROZEN_DIR = ROOT / "data" / "eval" / "baseline_runs" / "20260920_frozen"
DEFAULT_TEST_CASES = ROOT / "data" / "eval" / "test_cases.json"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "analysis" / "source_ambiguity"

EXPECTED_KG_ID = "236903cf-055a-40a8-8923-b9d06601f3b7"
EXPECTED_KG_FACT_TOTAL = 16826
BATCH_SIZE = 200
BATCH_PAUSE_SECONDS = 0.15
METRIC_TOLERANCE = 0.01

# 常數清單：題目明確提到兩個法規名，或含有跨新舊法／修法時序的對照字眼，
# 就視為題目本身有多法規提示。長法規名優先，避免把巢狀短名重複計為兩部法規。
LAW_NAME_TERMS = (
    "警察人員特別休假辦法",
    "員工接受召集請假期間薪資費用加成減除辦法",
    "勞動基準法",
    "勞工請假規則",
    "育嬰留職停薪實施辦法",
    "勞工退休金條例年金保險實施辦法",
    "勞工退休金條例",
    "災區受災勞工保險與勞工職業災害保險及就業保險被保險人保險費支應及傷病給付辦法",
    "勞工職業災害保險及保護法",
    "職業安全衛生法",
    "精密作業勞工視機能保護設施標準",
    "附表一 特別危害健康作業",
    "勞工健康保護規則",
    "職業安全衛生管理辦法",
    "高架作業勞工保護措施標準",
    "職業災害勞工保護法",
    "直轄市及縣市政府辦理協助職業災害勞工重返職場補助辦法",
    "就業服務法",
    "私立就業服務機構許可及管理辦法",
    "就業促進津貼實施辦法",
    "受聘僱從事就業服務法第四十六條第一項第八款至第十款規定工作之外國人請假返國辦法",
    "中高齡者及高齡者就業促進法",
    "失業中高齡者及高齡者就業促進辦法",
)
COMPARISON_TERMS = (
    "新舊法",
    "新法",
    "舊法",
    "修正前後",
    "修正前",
    "修正後",
    "修法前後",
    "修法前",
    "修法後",
    "現行法",
    "原法",
)

PUNCTUATION_EXTRAS = frozenset('<>"\'')

PREFLIGHT_QUERY = """
MATCH (f:Fact {kg_id: $kg_id})-[:SUPPORTED_BY]->(a:LawArticle {kg_id: $kg_id})
      -[:PART_OF]->(d:Document {kg_id: $kg_id})
WHERE f.fact_text CONTAINS $old_phrase OR f.fact_text CONTAINS $new_phrase
RETURN elementId(f) AS fact_id, f.fact_text AS fact_text,
       d.title AS document_title, d.source_doc_id AS source_doc_id,
       a.article_no AS article_no
ORDER BY d.source_doc_id, a.article_no, fact_id
"""

KG_WIDE_QUERY = """
MATCH (f:Fact {kg_id: $kg_id})-[:SUPPORTED_BY]->(a:LawArticle {kg_id: $kg_id})
      -[:PART_OF]->(d:Document {kg_id: $kg_id})
RETURN elementId(f) AS fact_id, f.fact_text AS fact_text,
       d.title AS document_title, d.source_doc_id AS source_doc_id,
       a.article_no AS article_no
ORDER BY d.source_doc_id, a.article_no, fact_id
"""

AGGR18_EXPECTED_FACT_TEXTS = {
    "23": "職業災害勞工 經醫療終止後，經公立醫療機構認定身心障礙不堪勝任工作",
    "24": "經公立醫療機構認定身心障礙不堪勝任工作",
    "84": "職業災害勞工經醫療終止後，經中央衛生福利主管機關醫院評鑑合格醫院認定身心障礙不堪勝任工作",
    "85": "職業災害勞工 經中央衛生福利主管機關醫院評鑑合格醫院認定身心障礙不堪勝任工作",
}
AGGR18_EXPECTED_METRICS = (
    ("23", "84", 0.489, 0.806),
    ("24", "85", 0.262, 0.632),
    ("23", "85", 0.362, None),
    ("24", "84", 0.255, None),
    ("23", "24", 0.621, None),
)
AGGR18_SOURCE_LAWS = {
    "old": "N0060041_職業災害勞工保護法",
    "new": "N0050031_勞工職業災害保險及保護法",
}


@dataclass(frozen=True)
class FactCitation:
    """Fact 及其法條／文件來源；不保存、不查詢任何向量欄位。"""

    fact_id: str
    fact_text: str
    document_title: str | None
    source_doc_id: str | None
    article_no: str | None


class Aggr18PreflightError(RuntimeError):
    """真實 KG 的 AGGR18 配對或驗算基準不符時，停止全域盤點。"""

    def __init__(self, report: Mapping[str, Any]):
        super().__init__("AGGR18 preflight did not match the required baseline")
        self.report = dict(report)


def normalize_text(text: str | None) -> str:
    """NFKC → 移除所有空白 → 移除中英文標點；不做簡繁或同義詞轉換。"""
    if text is None:
        return ""
    normalized = unicodedata.normalize("NFKC", str(text))
    return "".join(
        char
        for char in normalized
        if not char.isspace()
        and not unicodedata.category(char).startswith("P")
        and char not in PUNCTUATION_EXTRAS
    )


def char_bigrams(normalized_text: str) -> set[str]:
    return {normalized_text[index : index + 2] for index in range(len(normalized_text) - 1)}


def jaccard_similarity(left: str | None, right: str | None) -> float:
    """正規化後字元 bigram 集合的 Jaccard 係數，不套用碰撞門檻。"""
    normalized_left = normalize_text(left)
    normalized_right = normalize_text(right)
    left_bigrams = char_bigrams(normalized_left)
    right_bigrams = char_bigrams(normalized_right)
    union = left_bigrams | right_bigrams
    if not union:
        return 1.0 if normalized_left == normalized_right else 0.0
    return len(left_bigrams & right_bigrams) / len(union)


def frame_overlap(left: str | None, right: str | None) -> float:
    """共同前綴＋共同後綴長度除以較短句長，總重疊上限為 1。"""
    normalized_left = normalize_text(left)
    normalized_right = normalize_text(right)
    shorter_length = min(len(normalized_left), len(normalized_right))
    if shorter_length == 0:
        return 1.0 if normalized_left == normalized_right else 0.0

    common_prefix = 0
    while (
        common_prefix < shorter_length
        and normalized_left[common_prefix] == normalized_right[common_prefix]
    ):
        common_prefix += 1

    common_suffix = 0
    while (
        common_suffix < shorter_length
        and normalized_left[-(common_suffix + 1)] == normalized_right[-(common_suffix + 1)]
    ):
        common_suffix += 1

    overlap_chars = min(common_prefix + common_suffix, shorter_length)
    return overlap_chars / shorter_length


def article_number(value: str | int | None) -> str | None:
    """抽取「第23條第2款」或 LawArticle.article_no 的條號部分。"""
    if value is None:
        return None
    text = unicodedata.normalize("NFKC", str(value)).strip()
    match = re.search(r"(?:第\s*)?(\d+(?:-\d+)*)\s*條|§\s*(\d+(?:-\d+)*)", text)
    if match:
        return next(group for group in match.groups() if group is not None)
    match = re.search(r"\d+(?:-\d+)*", text)
    return match.group(0) if match else None


def _source_law_parts(source_law: str | None) -> tuple[str | None, str | None]:
    if not source_law:
        return None, None
    law_id, separator, law_title = source_law.partition("_")
    return law_id or None, law_title.replace("_", " ") if separator else None


def matched_law_equals_gold(citation: FactCitation, source_law: str | None) -> bool | None:
    """以來源 ID 優先、Document.title 次之，判定配對 Fact 是否屬 gold 法規。"""
    law_id, law_title = _source_law_parts(source_law)
    if citation.source_doc_id and law_id:
        source_id = str(citation.source_doc_id).strip()
        if source_id == law_id or source_id.startswith(f"{law_id}_"):
            return True
    if citation.document_title and law_title:
        return normalize_text(citation.document_title) == normalize_text(law_title)
    return None


def pair_span_to_facts(
    exact_span: str,
    citations: Iterable[FactCitation],
    source_law: str | None,
    gold_article: str | int | None,
) -> list[dict[str, Any]]:
    """用雙向包含且較短字串至少 8 字配對，回傳主／額外／其他配對列。"""
    normalized_span = normalize_text(exact_span)
    gold_article_no = article_number(gold_article)
    matches: list[dict[str, Any]] = []
    for citation in citations:
        normalized_fact = normalize_text(citation.fact_text)
        shorter_length = min(len(normalized_span), len(normalized_fact))
        if shorter_length < 8 or not (
            normalized_span in normalized_fact or normalized_fact in normalized_span
        ):
            continue

        matched_article_no = article_number(citation.article_no)
        article_matches_gold = (
            gold_article_no is not None and matched_article_no == gold_article_no
        )
        law_matches_gold = matched_law_equals_gold(citation, source_law)
        if article_matches_gold:
            pair_type = "主配對"
        elif law_matches_gold is True:
            pair_type = "額外配對（同法他條）"
        elif law_matches_gold is False:
            pair_type = "其他法規文字配對"
        else:
            pair_type = "法規歸屬未能判定"

        matches.append(
            {
                "fact_id": citation.fact_id,
                "fact_text": citation.fact_text,
                "normalized_fact_text": normalized_fact,
                "document_title": citation.document_title,
                "source_doc_id": citation.source_doc_id,
                "article_no": citation.article_no,
                "matched_article_no": matched_article_no,
                "gold_article_no": gold_article_no,
                "matched_article_equals_gold": article_matches_gold,
                "matched_law_equals_gold": law_matches_gold,
                "pair_type": pair_type,
            }
        )
    return matches


def _document_identity(citation: FactCitation) -> str | None:
    if citation.source_doc_id:
        return f"source_doc_id:{citation.source_doc_id}"
    if citation.document_title:
        return f"title:{normalize_text(citation.document_title)}"
    return None


def _citation_identity(citation: FactCitation) -> tuple[str, str | None, str | None]:
    return citation.fact_id, _document_identity(citation), article_number(citation.article_no)


def unique_citations(citations: Iterable[FactCitation]) -> list[FactCitation]:
    unique: dict[tuple[str, str | None, str | None], FactCitation] = {}
    for citation in citations:
        unique.setdefault(_citation_identity(citation), citation)
    return list(unique.values())


def _document_summary(citations: Iterable[FactCitation]) -> list[dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    for citation in citations:
        identity = _document_identity(citation)
        if identity is None:
            continue
        document = documents.setdefault(
            identity,
            {
                "source_doc_id": citation.source_doc_id,
                "title": citation.document_title,
                "article_nos": set(),
            },
        )
        if citation.article_no:
            document["article_nos"].add(str(citation.article_no))
    return [
        {
            "source_doc_id": document["source_doc_id"],
            "title": document["title"],
            "article_nos": sorted(document["article_nos"], key=lambda value: (article_number(value) or "", value)),
        }
        for _, document in sorted(documents.items())
    ]


def _cross_document_metric_values(
    citations: Iterable[FactCitation], source_law_count: int
) -> dict[str, Any]:
    if source_law_count < 2:
        return {
            "cross_doc_pair_count": 0,
            "max_cross_doc_jaccard": None,
            "max_cross_doc_frame_overlap": None,
        }

    facts = unique_citations(citations)
    compared_pairs = [
        (left, right)
        for left, right in combinations(facts, 2)
        if _document_identity(left) is not None
        and _document_identity(right) is not None
        and _document_identity(left) != _document_identity(right)
    ]
    if not compared_pairs:
        return {
            "cross_doc_pair_count": 0,
            "max_cross_doc_jaccard": None,
            "max_cross_doc_frame_overlap": None,
        }
    return {
        "cross_doc_pair_count": len(compared_pairs),
        "max_cross_doc_jaccard": max(
            jaccard_similarity(left.fact_text, right.fact_text)
            for left, right in compared_pairs
        ),
        "max_cross_doc_frame_overlap": max(
            frame_overlap(left.fact_text, right.fact_text)
            for left, right in compared_pairs
        ),
    }


def multi_law_question_mentions(question_text: str) -> dict[str, Any]:
    """回傳使用的常數清單命中；長法規名優先避免巢狀重複計數。"""
    matched_law_names: list[str] = []
    for term in sorted(LAW_NAME_TERMS, key=lambda value: (-len(value), value)):
        if term in question_text and not any(term in prior for prior in matched_law_names):
            matched_law_names.append(term)
    matched_comparison_terms = [term for term in COMPARISON_TERMS if term in question_text]
    return {
        "q_mentions_multi_law": len(matched_law_names) >= 2 or bool(matched_comparison_terms),
        "matched_law_name_terms": sorted(matched_law_names),
        "matched_comparison_terms": matched_comparison_terms,
    }


def analyze_question(
    question: Mapping[str, Any],
    citations: Sequence[FactCitation],
    global_documents_by_text: Mapping[str, set[str]],
) -> dict[str, Any]:
    gold_facts = question.get("atomic_gold_facts") or []
    source_laws = sorted(
        {str(gold["source_law"]) for gold in gold_facts if gold.get("source_law")}
    )
    mention_result = multi_law_question_mentions(str(question.get("question") or ""))
    span_results: list[dict[str, Any]] = []
    all_primary: list[FactCitation] = []
    all_same_law_extras: list[FactCitation] = []
    all_exact_matches_for_collision: list[FactCitation] = []
    unmatched_spans: list[str] = []
    primary_pair_count = 0
    extra_pair_count = 0
    other_law_pair_count = 0
    unresolved_law_pair_count = 0

    for gold in gold_facts:
        exact_span = str(gold.get("exact_span") or "")
        matches = pair_span_to_facts(
            exact_span,
            citations,
            gold.get("source_law"),
            gold.get("source_article"),
        )
        if not matches:
            unmatched_spans.append(exact_span)
        primary_ids: set[tuple[str, str | None, str | None]] = set()
        extra_ids: set[tuple[str, str | None, str | None]] = set()
        other_ids: set[tuple[str, str | None, str | None]] = set()
        unresolved_ids: set[tuple[str, str | None, str | None]] = set()
        citation_lookup = {_citation_identity(citation): citation for citation in citations}
        for match in matches:
            citation_key = _citation_identity(
                FactCitation(
                    match["fact_id"],
                    match["fact_text"],
                    match["document_title"],
                    match["source_doc_id"],
                    match["article_no"],
                )
            )
            citation = citation_lookup.get(citation_key)
            if citation is None:
                continue
            identity = _citation_identity(citation)
            if match["pair_type"] == "主配對":
                primary_ids.add(identity)
                all_primary.append(citation)
                all_exact_matches_for_collision.append(citation)
            elif match["pair_type"] == "額外配對（同法他條）":
                extra_ids.add(identity)
                all_same_law_extras.append(citation)
                all_exact_matches_for_collision.append(citation)
            elif match["pair_type"] == "其他法規文字配對":
                other_ids.add(identity)
            else:
                unresolved_ids.add(identity)

        primary_pair_count += len(primary_ids)
        extra_pair_count += len(extra_ids)
        other_law_pair_count += len(other_ids)
        unresolved_law_pair_count += len(unresolved_ids)
        span_citations = [
            citation
            for citation in citations
            if _citation_identity(citation)
            in (primary_ids | extra_ids | other_ids | unresolved_ids)
        ]
        span_results.append(
            {
                "exact_span": exact_span,
                "source_law": gold.get("source_law"),
                "source_article": gold.get("source_article"),
                "gold_article_no": article_number(gold.get("source_article")),
                "primary_match_count": len(primary_ids),
                "extra_same_law_match_count": len(extra_ids),
                "other_law_match_count": len(other_ids),
                "unresolved_law_match_count": len(unresolved_ids),
                "matched_documents": _document_summary(span_citations),
                "matches": matches,
            }
        )

    primary_unique = unique_citations(all_primary)
    with_extras_unique = unique_citations([*all_primary, *all_same_law_extras])
    primary_metrics = _cross_document_metric_values(primary_unique, len(source_laws))
    with_extras_metrics = _cross_document_metric_values(with_extras_unique, len(source_laws))
    normalized_gold_facts = {
        normalize_text(citation.fact_text) for citation in all_exact_matches_for_collision
    }
    gold_exact_collision = any(
        len(global_documents_by_text.get(normalized_text, set())) >= 2
        for normalized_text in normalized_gold_facts
        if normalized_text
    )
    matched_documents = _document_summary(
        citation
        for citation in citations
        if any(
            citation.fact_id == match["fact_id"]
            and citation.source_doc_id == match["source_doc_id"]
            and citation.article_no == match["article_no"]
            for span in span_results
            for match in span["matches"]
        )
    )

    return {
        "id": question.get("id"),
        "question": question.get("question"),
        "n_source_laws": len(source_laws),
        "source_laws": source_laws,
        **mention_result,
        "primary_match_count": primary_pair_count,
        "extra_same_law_match_count": extra_pair_count,
        "other_law_match_count": other_law_pair_count,
        "unresolved_law_match_count": unresolved_law_pair_count,
        "unmatched_span_count": len(unmatched_spans),
        "unmatched_spans": unmatched_spans,
        "matched_documents": matched_documents,
        "gold_exact_collision": gold_exact_collision,
        "max_cross_doc_jaccard": primary_metrics["max_cross_doc_jaccard"],
        "max_cross_doc_frame_overlap": primary_metrics["max_cross_doc_frame_overlap"],
        "primary_only_metrics": primary_metrics,
        "including_extra_same_law_metrics": with_extras_metrics,
        "extra_pair_metric_difference": {
            key: primary_metrics[key] != with_extras_metrics[key]
            for key in ("max_cross_doc_jaccard", "max_cross_doc_frame_overlap")
        },
        "span_results": span_results,
    }


def global_collision_report(citations: Sequence[FactCitation]) -> dict[str, Any]:
    fact_ids = {citation.fact_id for citation in citations}
    grouped: dict[str, dict[str, Any]] = {}
    for citation in citations:
        normalized = normalize_text(citation.fact_text)
        if not normalized:
            continue
        group = grouped.setdefault(
            normalized,
            {"fact_ids": set(), "documents": {}, "fact_texts": set(), "article_nos": set()},
        )
        group["fact_ids"].add(citation.fact_id)
        group["fact_texts"].add(citation.fact_text)
        if citation.article_no:
            group["article_nos"].add(str(citation.article_no))
        document_identity = _document_identity(citation)
        if document_identity:
            group["documents"].setdefault(
                document_identity,
                {
                    "source_doc_id": citation.source_doc_id,
                    "title": citation.document_title,
                    "article_nos": set(),
                },
            )
            if citation.article_no:
                group["documents"][document_identity]["article_nos"].add(
                    str(citation.article_no)
                )

    collisions = [
        (normalized, group)
        for normalized, group in grouped.items()
        if len(group["documents"]) >= 2
    ]
    collision_fact_ids = {
        fact_id for _, group in collisions for fact_id in group["fact_ids"]
    }
    collision_examples = []
    for normalized, group in sorted(
        collisions,
        key=lambda item: (
            -len(item[1]["fact_ids"]),
            -len(item[1]["documents"]),
            item[0],
        ),
    )[:20]:
        documents = []
        for _, document in sorted(group["documents"].items()):
            documents.append(
                {
                    "source_doc_id": document["source_doc_id"],
                    "title": document["title"],
                    "article_nos": sorted(
                        document["article_nos"],
                        key=lambda value: (article_number(value) or "", value),
                    ),
                }
            )
        collision_examples.append(
            {
                "normalized_fact_text": normalized,
                "fact_text_examples": sorted(group["fact_texts"])[:3],
                "fact_count": len(group["fact_ids"]),
                "document_count": len(group["documents"]),
                "documents": documents,
            }
        )

    fact_count = len(fact_ids)
    unique_text_count = len(grouped)
    collision_text_count = len(collisions)
    collision_fact_count = len(collision_fact_ids)
    return {
        "actual_fact_count": fact_count,
        "distinct_normalized_text_count": unique_text_count,
        "empty_normalized_fact_count": sum(
            1 for citation in citations if not normalize_text(citation.fact_text)
        ),
        "same_text_cross_document_distinct_text_count": collision_text_count,
        "same_text_cross_document_fact_count": collision_fact_count,
        "same_text_cross_document_fact_ratio_by_facts": (
            collision_fact_count / fact_count if fact_count else 0.0
        ),
        "same_text_cross_document_text_ratio_by_facts": (
            collision_text_count / fact_count if fact_count else 0.0
        ),
        "same_text_cross_document_text_ratio_by_distinct_texts": (
            collision_text_count / unique_text_count if unique_text_count else 0.0
        ),
        "collision_examples_top20": collision_examples,
    }


def _citation_from_row(row: Mapping[str, Any]) -> FactCitation:
    return FactCitation(
        fact_id=str(row.get("fact_id") or ""),
        fact_text=str(row.get("fact_text") or ""),
        document_title=(str(row["document_title"]) if row.get("document_title") is not None else None),
        source_doc_id=(str(row["source_doc_id"]) if row.get("source_doc_id") is not None else None),
        article_no=(str(row["article_no"]) if row.get("article_no") is not None else None),
    )


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_eligible_questions(
    manifest: Mapping[str, Any], test_cases: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    eligible_ids = list(manifest.get("eligible_ids") or [])
    question_by_id = {
        str(question.get("id")): question for question in test_cases.get("questions", [])
    }
    selected = [question_by_id[question_id] for question_id in eligible_ids if question_id in question_by_id]
    missing = [question_id for question_id in eligible_ids if question_id not in question_by_id]
    return selected, missing


def _aggr18_question(test_cases: Mapping[str, Any]) -> dict[str, Any] | None:
    return next(
        (
            question
            for question in test_cases.get("questions", [])
            if question.get("id") == "57-AGGR18"
        ),
        None,
    )


def validate_aggr18_preflight(
    question: Mapping[str, Any] | None, rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    if question is None:
        return {"passed": False, "reason": "題庫找不到 57-AGGR18"}
    citations = unique_citations(_citation_from_row(row) for row in rows)
    actual_by_article: dict[str, set[str]] = defaultdict(set)
    same_law_articles_by_span: list[dict[str, Any]] = []
    span_preflight_errors: list[str] = []
    for gold in question.get("atomic_gold_facts") or []:
        gold_article_no = article_number(gold.get("source_article"))
        matches = pair_span_to_facts(
            str(gold.get("exact_span") or ""),
            citations,
            gold.get("source_law"),
            gold.get("source_article"),
        )
        same_law_matches = [match for match in matches if match["matched_law_equals_gold"] is True]
        main_matches = [match for match in same_law_matches if match["matched_article_equals_gold"]]
        if not main_matches:
            errors_for_span = f"{gold.get('source_article')} gold span 沒有配到條號相符的主配對 Fact"
        else:
            errors_for_span = None
        if errors_for_span:
            # 先記錄到暫存清單，最後與四筆 Fact／度量差異一併回報。
            span_preflight_errors.append(errors_for_span)
        for match in main_matches:
            actual_by_article[gold_article_no or ""].add(match["normalized_fact_text"])
        same_law_articles_by_span.append(
            {
                "source_article": gold.get("source_article"),
                "gold_article_no": gold_article_no,
                "matched_same_law_article_nos": sorted(
                    {match["matched_article_no"] for match in same_law_matches if match["matched_article_no"]},
                    key=lambda value: (int(value.split("-")[0]), value),
                ),
                "primary_article_nos": sorted(
                    {match["matched_article_no"] for match in main_matches if match["matched_article_no"]},
                    key=lambda value: (int(value.split("-")[0]), value),
                ),
                "extra_same_law_article_nos": sorted(
                    {
                        match["matched_article_no"]
                        for match in same_law_matches
                        if not match["matched_article_equals_gold"] and match["matched_article_no"]
                    },
                    key=lambda value: (int(value.split("-")[0]), value),
                ),
            }
        )

    errors: list[str] = list(span_preflight_errors)
    expected_by_article = {
        article_no: normalize_text(fact_text)
        for article_no, fact_text in AGGR18_EXPECTED_FACT_TEXTS.items()
    }
    actual_article_texts = {
        article_no: sorted(actual_by_article.get(article_no, set()))
        for article_no in AGGR18_EXPECTED_FACT_TEXTS
    }
    if set(actual_by_article) - set(expected_by_article):
        errors.append("主配對出現驗算基準以外的條號")
    for article_no, expected_text in expected_by_article.items():
        if actual_by_article.get(article_no, set()) != {expected_text}:
            errors.append(f"第{article_no}條主配對 Fact 文字與驗算基準不一致或缺失")

    facts_by_article = {
        article_no: next(
            (
                citation
                for citation in citations
                if article_number(citation.article_no) == article_no
                and normalize_text(citation.fact_text) == expected_by_article[article_no]
                and matched_law_equals_gold(
                    citation,
                    AGGR18_SOURCE_LAWS["old" if article_no in {"23", "24"} else "new"],
                )
                is True
            ),
            None,
        )
        for article_no in AGGR18_EXPECTED_FACT_TEXTS
    }

    actual_metrics: list[dict[str, Any]] = []
    for left_no, right_no, expected_jaccard, expected_frame in AGGR18_EXPECTED_METRICS:
        left = facts_by_article[left_no]
        right = facts_by_article[right_no]
        if left is None or right is None:
            actual_jaccard = None
            actual_frame = None
        else:
            actual_jaccard = jaccard_similarity(left.fact_text, right.fact_text)
            actual_frame = frame_overlap(left.fact_text, right.fact_text)
            if abs(actual_jaccard - expected_jaccard) > METRIC_TOLERANCE:
                errors.append(f"第{left_no}條×第{right_no}條 Jaccard 超出 ±0.01")
            if expected_frame is not None and abs(actual_frame - expected_frame) > METRIC_TOLERANCE:
                errors.append(f"第{left_no}條×第{right_no}條 frame_overlap 超出 ±0.01")
        actual_metrics.append(
            {
                "left_article_no": left_no,
                "right_article_no": right_no,
                "jaccard": actual_jaccard,
                "expected_jaccard": expected_jaccard,
                "frame_overlap": actual_frame,
                "expected_frame_overlap": expected_frame,
            }
        )

    exact_cross_law_matches = []
    for old_no in ("23", "24"):
        for new_no in ("84", "85"):
            old = facts_by_article[old_no]
            new = facts_by_article[new_no]
            if old and new and normalize_text(old.fact_text) == normalize_text(new.fact_text):
                exact_cross_law_matches.append([old_no, new_no])
    if exact_cross_law_matches:
        errors.append("新舊法主配對出現正規化後精確同文")

    return {
        "passed": not errors,
        "errors": errors,
        "expected_fact_texts": AGGR18_EXPECTED_FACT_TEXTS,
        "actual_normalized_main_fact_texts": actual_article_texts,
        "matched_same_law_articles_by_span": same_law_articles_by_span,
        "metrics": actual_metrics,
        "cross_law_exact_text_match": bool(exact_cross_law_matches),
        "cross_law_exact_text_matches": exact_cross_law_matches,
    }


def _fact_document_index(citations: Sequence[FactCitation]) -> dict[str, set[str]]:
    documents_by_text: dict[str, set[str]] = defaultdict(set)
    for citation in citations:
        normalized = normalize_text(citation.fact_text)
        identity = _document_identity(citation)
        if normalized and identity:
            documents_by_text[normalized].add(identity)
    return documents_by_text


def build_question_audit(
    questions: Sequence[Mapping[str, Any]], citations: Sequence[FactCitation]
) -> list[dict[str, Any]]:
    unique = unique_citations(citations)
    docs_by_text = _fact_document_index(unique)
    return [analyze_question(question, unique, docs_by_text) for question in questions]


def complete_aggr18_article_matches(question_audit: Mapping[str, Any]) -> list[dict[str, Any]]:
    """從完整 P1-b Fact 集合整理 AGGR18 條號主配對、同法額外與跨法文字配對。"""
    complete_matches = []
    for span in question_audit.get("span_results", []):
        matches = span.get("matches", [])
        complete_matches.append(
            {
                "source_article": span.get("source_article"),
                "gold_article_no": span.get("gold_article_no"),
                "primary_article_nos": sorted(
                    {
                        match["matched_article_no"]
                        for match in matches
                        if match["matched_article_equals_gold"]
                        and match["matched_article_no"]
                    },
                    key=lambda value: (int(value.split("-")[0]), value),
                ),
                "extra_same_law_article_nos": sorted(
                    {
                        match["matched_article_no"]
                        for match in matches
                        if match["pair_type"] == "額外配對（同法他條）"
                        and match["matched_article_no"]
                    },
                    key=lambda value: (int(value.split("-")[0]), value),
                ),
                "other_law_article_nos": sorted(
                    {
                        match["matched_article_no"]
                        for match in matches
                        if match["pair_type"] == "其他法規文字配對"
                        and match["matched_article_no"]
                    },
                    key=lambda value: (int(value.split("-")[0]), value),
                ),
                "unresolved_law_article_nos": sorted(
                    {
                        match["matched_article_no"]
                        for match in matches
                        if match["pair_type"] == "法規歸屬未能判定"
                        and match["matched_article_no"]
                    },
                    key=lambda value: (int(value.split("-")[0]), value),
                ),
            }
        )
    return complete_matches


def candidate_questions(question_audits: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    candidates = [
        audit
        for audit in question_audits
        if audit["n_source_laws"] >= 2 and audit["q_mentions_multi_law"]
    ]
    candidates.sort(
        key=lambda audit: (
            -(
                audit["max_cross_doc_frame_overlap"]
                if audit["max_cross_doc_frame_overlap"] is not None
                else -1.0
            ),
            str(audit["id"]),
        )
    )
    for index, audit in enumerate(candidates, start=1):
        audit["candidate_rank"] = index
    multi_law_without_mention = [
        {
            "id": audit["id"],
            "n_source_laws": audit["n_source_laws"],
            "question": audit["question"],
        }
        for audit in question_audits
        if audit["n_source_laws"] >= 2 and not audit["q_mentions_multi_law"]
    ]
    aggr18_rank = next(
        (index for index, audit in enumerate(candidates, start=1) if audit["id"] == "57-AGGR18"),
        None,
    )
    aggr18_audit = next(
        (audit for audit in question_audits if audit["id"] == "57-AGGR18"),
        None,
    )
    if aggr18_rank is None:
        aggr18_status = {
            "included": False,
            "rank": None,
            "reason": (
                "AGGR18 不符合候選條件；"
                f"n_source_laws={aggr18_audit['n_source_laws'] if aggr18_audit else None}, "
                f"q_mentions_multi_law={aggr18_audit['q_mentions_multi_law'] if aggr18_audit else None}"
            ),
        }
    else:
        aggr18_status = {
            "included": True,
            "rank": aggr18_rank,
            "candidate_count": len(candidates),
            "rank_fraction": aggr18_rank / len(candidates) if candidates else None,
        }
    return {
        "candidate_ids_in_rank_order": [audit["id"] for audit in candidates],
        "candidates": candidates,
        "multi_law_without_question_mention": multi_law_without_mention,
        "aggr18_candidate_status": aggr18_status,
    }


def git_commit(root: Path = ROOT) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _load_runtime_credentials(env_file: Path) -> tuple[str, str, str]:
    """只由主 checkout .env 讀取 Neo4j 連線欄位，絕不輸出值。"""
    from dotenv import dotenv_values

    values = dotenv_values(env_file, interpolate=False)
    required = ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD")
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise RuntimeError("主 checkout .env 缺少必要的 Neo4j 連線欄位")
    return tuple(str(values[key]) for key in required)  # type: ignore[return-value]


def _query_batches(
    session: Any,
    query: str,
    parameters: Mapping[str, Any],
    *,
    pause_seconds: float = BATCH_PAUSE_SECONDS,
) -> Iterator[list[dict[str, Any]]]:
    result = session.run(query, **dict(parameters))
    batch: list[dict[str, Any]] = []
    for record in result:
        batch.append(dict(record))
        if len(batch) >= BATCH_SIZE:
            yield batch
            batch = []
            if pause_seconds > 0:
                time.sleep(pause_seconds)
    if batch:
        yield batch
    result.consume()


def load_manifest_and_questions(
    frozen_dir: Path = DEFAULT_FROZEN_DIR,
    test_cases_path: Path = DEFAULT_TEST_CASES,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[str]]:
    manifest = _load_json(frozen_dir / "frozen_manifest.json")
    test_cases = _load_json(test_cases_path)
    questions, missing_ids = _load_eligible_questions(manifest, test_cases)
    return manifest, test_cases, questions, missing_ids


def _preflight_print_report(report: Mapping[str, Any]) -> None:
    print(
        "AGGR18 真實 KG 預檢："
        + json.dumps(report, ensure_ascii=False, sort_keys=True),
        flush=True,
    )


def _citation_sort_key(citation: FactCitation) -> tuple[str, str, str, str]:
    return (
        citation.document_title or "",
        citation.source_doc_id or "",
        article_number(citation.article_no) or "",
        normalize_text(citation.fact_text),
    )


def _build_summary_markdown(
    *,
    generated_at: str,
    commit: str,
    manifest: Mapping[str, Any],
    kg_stats: Mapping[str, Any],
    question_audits: Sequence[Mapping[str, Any]],
    candidates: Mapping[str, Any],
    preflight: Mapping[str, Any],
    query_stats: Mapping[str, Any],
    missing_question_ids: Sequence[str],
) -> str:
    candidate_lines = []
    for audit in candidates["candidates"]:
        candidate_lines.append(
            "| {rank} | {qid} | {laws} | {mention} | {jaccard} | {frame} | {extra_j} | {extra_f} |".format(
                rank=audit["candidate_rank"],
                qid=audit["id"],
                laws=audit["n_source_laws"],
                mention="是" if audit["q_mentions_multi_law"] else "否",
                jaccard=_format_metric(audit["max_cross_doc_jaccard"]),
                frame=_format_metric(audit["max_cross_doc_frame_overlap"]),
                extra_j=_format_metric(
                    audit["including_extra_same_law_metrics"]["max_cross_doc_jaccard"]
                ),
                extra_f=_format_metric(
                    audit["including_extra_same_law_metrics"]["max_cross_doc_frame_overlap"]
                ),
            )
        )
    if not candidate_lines:
        candidate_lines.append("| — | 無符合條件題目 | — | — | — | — | — | — |")

    unmatched_lines = []
    for audit in question_audits:
        for span in audit["unmatched_spans"]:
            unmatched_lines.append(f"- `{audit['id']}`：{span}")
    if not unmatched_lines:
        unmatched_lines.append("- 無未配對 span。")

    without_mention_lines = [
        f"- `{item['id']}`（n_source_laws={item['n_source_laws']}）：{item['question']}"
        for item in candidates["multi_law_without_question_mention"]
    ] or ["- 無此類題目。"]

    top_collision_lines = []
    for index, item in enumerate(kg_stats["collision_examples_top20"], start=1):
        law_items = "; ".join(
            f"{doc['title'] or '(無 title)'} [{doc['source_doc_id'] or '(無 source_doc_id)'}] §{','.join(doc['article_nos']) or '(無條號)'}"
            for doc in item["documents"]
        )
        text_example = item["fact_text_examples"][0] if item["fact_text_examples"] else item["normalized_fact_text"]
        top_collision_lines.append(
            f"{index}. `{text_example}`（Fact {item['fact_count']} 筆；文件 {item['document_count']} 部）：{law_items}"
        )
    if not top_collision_lines:
        top_collision_lines.append("沒有正規化後跨 Document 同文碰撞。")

    multi_law_hits = ", ".join(LAW_NAME_TERMS)
    comparison_hits = ", ".join(COMPARISON_TERMS)
    preflight_metrics = "\n".join(
        "| §{left} × §{right} | {jaccard:.3f} | {jaccard_expected:.3f} | {frame} | {frame_expected} |".format(
            left=item["left_article_no"],
            right=item["right_article_no"],
            jaccard=item["jaccard"] if item["jaccard"] is not None else float("nan"),
            jaccard_expected=item["expected_jaccard"],
            frame=(f"{item['frame_overlap']:.3f}" if item["frame_overlap"] is not None else "—"),
            frame_expected=(
                f"{item['expected_frame_overlap']:.3f}"
                if item["expected_frame_overlap"] is not None
                else "—"
            ),
        )
        for item in preflight["metrics"]
    )
    return f"""# 來源歧義盤點（TASK-3 Phase 1）

## 執行資訊

- 產出時間（UTC）：`{generated_at}`
- 執行時 git commit：`{commit}`
- 凍結題庫範圍：manifest `eligible_ids` 共 {len(manifest.get('eligible_ids') or [])} 題；載入 {len(question_audits)} 題。
- KG：`{manifest.get('kg_id')}`；manifest 預期 Fact 數 {manifest.get('kg_fact_total')}。
- Neo4j 存取：`READ` session；每批 {BATCH_SIZE} rows，批次間隔 {BATCH_PAUSE_SECONDS:.2f}s；查詢只回傳 Fact 文字、Document 標題／來源 ID、LawArticle 條號與內部暫用 Fact ID，未查詢或回傳 `fact_embedding`。
- 全域查詢：回傳列數 {query_stats['returned_row_count']}；相異 Fact 節點 {kg_stats['actual_fact_count']}；實際查詢耗時 {query_stats['elapsed_seconds']:.2f}s。
- 未找到的題目 ID：{', '.join(missing_question_ids) if missing_question_ids else '無'}。
- 本次只完成 Phase 1（P1-a、P1-b、P1-c）；未讀取 T2 Stage A 輸出，Phase 2 待 T2 完成。

## 共同定義

- **正規化 `norm(text)`**：`unicodedata.normalize("NFKC")` → 移除所有空白 → 移除中英文標點（含 `，。、；：！？（）「」『』【】,.;:!?()[]<>\"'` 與破折號）。不做簡繁轉換、不做同義詞處理。
- **同文**：`norm(a) == norm(b)`。
- **Jaccard**：`norm` 後字元 bigram 集合的 Jaccard 係數；連續值，不設「碰撞」門檻。
- **句框重疊 `frame_overlap(a,b)`**：對 `norm(a)`、`norm(b)`，`LCP` 為最長共同前綴長度、`LCS` 為最長共同後綴長度，`min(LCP + LCS, min(len(a), len(b))) / min(len(a), len(b))`；前後綴總長度上限為較短句長度。這是描述 AGGR18 形態的探索性描述統計，尚未驗證為歧義判準。
- **同文異源**：同一 `norm(fact_text)` 出現在至少兩個 Document；以 `Document.source_doc_id` 作文件身份，缺值時退回正規化 `Document.title`。這是精確碰撞，與 Jaccard／句框連續度量分開報告。
- **exact_span ↔ Fact**：兩側正規化文字互相包含，且較短字串至少 8 字。每個 Fact 條號另與 gold `source_article` 的條號比對；條號相等列「主配對」，同一 gold 法規的其他條號列「額外配對」，其他法規或法規歸屬不明另列，不合併計數。`n_source_laws` 只計 gold 的 `source_law`。
- **多法規題目字眼常數**：法規名清單：{multi_law_hits}。對照字眼清單：{comparison_hits}。題目命中至少兩個不同法規名，或至少一個對照字眼，即 `q_mentions_multi_law=true`；巢狀法規名不重複計數。

## AGGR18 真實 KG 預檢（全域查詢前）

預檢結果：**通過**。四個條號主配對 Fact 的正規化文字與任務書 §5.4 驗算基準一致；新舊法跨法規精確同文：否。

| 條文配對 | Jaccard | 預期 | frame_overlap | 預期 |
|---|---:|---:|---:|---:|
{preflight_metrics}

完整 KG 配對（由 P1-b 全域 Fact 結果計算；「其他法規」保留分列）：

{chr(10).join('- ' + item['source_article'] + ' → 主配對 ' + (', '.join('§' + article for article in item['primary_article_nos']) or '無') + '；同法額外 ' + (', '.join('§' + article for article in item['extra_same_law_article_nos']) or '無') + '；其他法規 ' + (', '.join('§' + article for article in item['other_law_article_nos']) or '無') for item in preflight['complete_matched_articles_by_span'])}

## P1-a：KG 全域同文異源

- 相異正規化文字：{kg_stats['distinct_normalized_text_count']}
- 同文異源相異文字：{kg_stats['same_text_cross_document_distinct_text_count']}
- 涉及碰撞的 Fact：{kg_stats['same_text_cross_document_fact_count']} / {kg_stats['actual_fact_count']}（以 Fact 為分母：{kg_stats['same_text_cross_document_fact_ratio_by_facts']:.4%}）
- 碰撞文字數 / Fact 數：{kg_stats['same_text_cross_document_text_ratio_by_facts']:.4%}
- 碰撞文字數 / 相異正規化文字數：{kg_stats['same_text_cross_document_text_ratio_by_distinct_texts']:.4%}
- 查詢列數 {query_stats['returned_row_count']}（與 manifest 差異 {query_stats['returned_row_count_difference_ratio']:.4%}）；不同 Fact {kg_stats['actual_fact_count']}（差異 {query_stats['distinct_fact_count_difference_ratio']:.4%}）；manifest `kg_fact_total` 為 {manifest.get('kg_fact_total')}。

前 20 個跨 Document 同文範例（含 Document 標題與條號）：

{chr(10).join(top_collision_lines)}

## P1-b：凍結 42 題 gold span 配對

- 各題分別輸出 `primary_match_count`、`extra_same_law_match_count`、其他法規配對數與未配對 span；沒有合併成單一 matched-fact 數。
- 主配對的跨文件度量為主要值；另計「主配對＋同法額外配對」對照值。若 `extra_pair_metric_difference` 為 true，兩組數值不同，題目 JSON 內保留兩組值。
- 未配對 span：

{chr(10).join(unmatched_lines)}

## P1-c：A/B 候選題

候選條件為 `n_source_laws >= 2` 且 `q_mentions_multi_law=true`；依主配對 `max_cross_doc_frame_overlap` 由高到低排列，不設歧義門檻。

| 排名 | 題目 | gold 法規數 | 題目有對照字眼 | 主配對 max Jaccard | 主配對 max frame_overlap | 含額外配對 max Jaccard | 含額外配對 max frame_overlap |
|---:|---|---:|---|---:|---:|---:|---:|
{chr(10).join(candidate_lines)}

`57-AGGR18` 候選狀態：`{json.dumps(candidates['aggr18_candidate_status'], ensure_ascii=False, sort_keys=True)}`。

僅 `n_source_laws >= 2`、題目沒有多法規提示字眼的清單：

{chr(10).join(without_mention_lines)}

## 限制與可比性

- Jaccard 與句框重疊是字面度量，未涵蓋語意相似；句框重疊是依 AGGR18 形態設計的探索性度量，未經驗證為歧義判準。
- 配對使用文字互相包含規則，會配到同法相鄰條號；因此另外用 gold 條號標記主配對與額外配對。未配對 span 已列出，不假設所有 gold 都能配到。
- Document `effective_date` 全 `None`（依任務書已知現況；本次不以生效日期分辨新舊法）。
- 此結果只盤點文字與來源歧義；不是檢索品質或答對率比較。
- Phase 2 未執行，待 T2 Stage A 完整結束後另行處理。
"""


def _format_metric(value: Any) -> str:
    return "—" if value is None else f"{value:.3f}"


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def run_phase1(
    *,
    env_file: Path = DEFAULT_ENV_FILE,
    frozen_dir: Path = DEFAULT_FROZEN_DIR,
    test_cases_path: Path = DEFAULT_TEST_CASES,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    batch_pause_seconds: float = BATCH_PAUSE_SECONDS,
) -> dict[str, Any]:
    manifest, test_cases, questions, missing_ids = load_manifest_and_questions(
        frozen_dir, test_cases_path
    )
    if manifest.get("kg_id") != EXPECTED_KG_ID or manifest.get("kg_fact_total") != EXPECTED_KG_FACT_TOTAL:
        raise RuntimeError("凍結 manifest 的 kg_id／kg_fact_total 與任務書基準不符")
    aggr18 = _aggr18_question(test_cases)
    if not any(question.get("id") == "57-AGGR18" for question in questions):
        raise RuntimeError("frozen_manifest eligible_ids 未包含 57-AGGR18")

    uri, user, password = _load_runtime_credentials(env_file)
    from neo4j import GraphDatabase, READ_ACCESS

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session(
            default_access_mode=READ_ACCESS,
            fetch_size=BATCH_SIZE,
        ) as session:
            preflight_start = time.monotonic()
            preflight_rows = [
                row
                for batch in _query_batches(
                    session,
                    PREFLIGHT_QUERY,
                    {
                        "kg_id": manifest["kg_id"],
                        "old_phrase": "公立醫療機構",
                        "new_phrase": "醫院評鑑合格醫院",
                    },
                    pause_seconds=batch_pause_seconds,
                )
                for row in batch
            ]
            preflight = validate_aggr18_preflight(aggr18, preflight_rows)
            preflight["returned_row_count"] = len(preflight_rows)
            preflight["elapsed_seconds"] = time.monotonic() - preflight_start
            _preflight_print_report(preflight)
            if not preflight["passed"]:
                raise Aggr18PreflightError(preflight)

            if batch_pause_seconds > 0:
                time.sleep(batch_pause_seconds)
            query_start = time.monotonic()
            rows: list[dict[str, Any]] = []
            for batch in _query_batches(
                session,
                KG_WIDE_QUERY,
                {"kg_id": manifest["kg_id"]},
                pause_seconds=batch_pause_seconds,
            ):
                rows.extend(batch)
                if len(rows) % (BATCH_SIZE * 10) == 0:
                    print(f"Neo4j READ 全域盤點進度：已取回 {len(rows)} rows", flush=True)
            elapsed_seconds = time.monotonic() - query_start
    finally:
        driver.close()

    citations = unique_citations(_citation_from_row(row) for row in rows)
    kg_stats = global_collision_report(citations)
    expected_count = int(manifest["kg_fact_total"])
    actual_count = int(kg_stats["actual_fact_count"])
    difference_ratio = abs(actual_count - expected_count) / expected_count if expected_count else 0.0
    query_stats = {
        "returned_row_count": len(rows),
        "returned_row_count_difference_ratio": (
            abs(len(rows) - expected_count) / expected_count if expected_count else 0.0
        ),
        "distinct_fact_count": actual_count,
        "distinct_fact_count_difference_ratio": difference_ratio,
        "elapsed_seconds": elapsed_seconds,
        "batch_size": BATCH_SIZE,
        "batch_pause_seconds": batch_pause_seconds,
        "manifest_fact_count": expected_count,
        "fact_count_difference_ratio": difference_ratio,
    }
    if max(
        query_stats["returned_row_count_difference_ratio"],
        query_stats["distinct_fact_count_difference_ratio"],
    ) > 0.01:
        raise RuntimeError(
            "Neo4j returned-row or distinct-Fact count differs from frozen manifest by more than 1%; "
            f"returned_rows={len(rows)}, distinct_facts={actual_count}, expected={expected_count}"
        )

    question_audits = build_question_audit(questions, citations)
    aggr18_audit = next(
        (audit for audit in question_audits if audit["id"] == "57-AGGR18"),
        None,
    )
    if aggr18_audit is None:
        raise RuntimeError("完整題目盤點找不到 57-AGGR18")
    preflight["complete_matched_articles_by_span"] = complete_aggr18_article_matches(
        aggr18_audit
    )
    candidate_report = candidate_questions(question_audits)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    current_commit = git_commit()
    metadata = {
        "generated_at_utc": generated_at,
        "git_commit": current_commit,
        "kg_id": manifest["kg_id"],
        "manifest_kg_fact_total": expected_count,
    }
    kg_output = {
        **metadata,
        "query_stats": query_stats,
        "global_stats": kg_stats,
        "document_identity_rule": "Document.source_doc_id；缺值時退回正規化 Document.title",
        "contains_raw_fact_dump": False,
    }
    question_output = {
        **metadata,
        "eligible_question_count": len(manifest.get("eligible_ids") or []),
        "analyzed_question_count": len(question_audits),
        "missing_question_ids": missing_ids,
        "law_name_terms": list(LAW_NAME_TERMS),
        "comparison_terms": list(COMPARISON_TERMS),
        "primary_pair_rule": "LawArticle.article_no 條號等於 gold source_article 條號",
        "extra_pair_rule": "gold 法規相同但 LawArticle.article_no 不同",
        "questions": question_audits,
        "candidate_report": candidate_report,
        "aggr18_preflight": preflight,
    }
    summary = _build_summary_markdown(
        generated_at=generated_at,
        commit=current_commit,
        manifest=manifest,
        kg_stats=kg_stats,
        question_audits=question_audits,
        candidates=candidate_report,
        preflight=preflight,
        query_stats=query_stats,
        missing_question_ids=missing_ids,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "kg_wide.json", kg_output)
    _write_json(output_dir / "questions_frozen42.json", question_output)
    (output_dir / "summary.md").write_text(summary, encoding="utf-8")
    return {
        "kg_wide": kg_output,
        "questions_frozen42": question_output,
        "summary": summary,
        "aggr18_preflight": preflight,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--frozen-dir", type=Path, default=DEFAULT_FROZEN_DIR)
    parser.add_argument("--test-cases", type=Path, default=DEFAULT_TEST_CASES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--batch-pause-seconds", type=float, default=BATCH_PAUSE_SECONDS)
    args = parser.parse_args(argv)
    try:
        result = run_phase1(
            env_file=args.env_file,
            frozen_dir=args.frozen_dir,
            test_cases_path=args.test_cases,
            output_dir=args.output_dir,
            batch_pause_seconds=args.batch_pause_seconds,
        )
    except Aggr18PreflightError as error:
        print(
            "STOP：AGGR18 真實 KG 預檢未符合驗算基準；已停止，未執行全域盤點。"
            + json.dumps(error.report, ensure_ascii=False, sort_keys=True),
            flush=True,
        )
        return 2
    except Exception as error:  # noqa: BLE001 - 不顯示 driver 例外內容，避免洩漏連線資訊
        print(
            f"Phase 1 停止：{type(error).__name__}；未輸出連線憑證或錯誤細節。",
            flush=True,
        )
        return 1

    print(
        "TASK-3 Phase 1 完成："
        + json.dumps(
            {
                "output_files": [
                    str(args.output_dir / "kg_wide.json"),
                    str(args.output_dir / "questions_frozen42.json"),
                    str(args.output_dir / "summary.md"),
                ],
                "fact_count": result["kg_wide"]["global_stats"]["actual_fact_count"],
                "candidate_ids": result["questions_frozen42"]["candidate_report"][
                    "candidate_ids_in_rank_order"
                ],
                "phase2": "待 T2 Stage A 完整結束",
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
