"""唯讀盤點跨法規來源歧義；所有分析函式皆不依賴 Neo4j。"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
import unicodedata
from collections import Counter, defaultdict
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
DEFAULT_PHASE2_SNAPSHOT_DIR = ROOT / ".claude" / "tmp" / "task3_phase2_snapshot_20260922"

PHASE2_STAGE_DIRECTORIES = (
    "t2_k1_topk40_stage_a",
    "t2_k1_topk40_stage_a2",
    "t2_k1_topk40_stage_a3",
    "t2_k1_topk40_stage_b",
    "t2_k1_topk40_stage_b2a",
    "t2_k1_topk40_stage_b2b",
    "t2_k1_topk40_stage_b2c",
    "t2_k1_topk40_stage_c",
)

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


def _prompt_groups(value: Any) -> list[list[str]]:
    """將單層或巢狀 prompt_context_lines 統一為子問題行清單。"""
    if not isinstance(value, list) or not value:
        return []
    if all(isinstance(line, str) for line in value):
        return [[line for line in value]]
    groups: list[list[str]] = []
    for item in value:
        if isinstance(item, list):
            groups.append([str(line) for line in item if isinstance(line, str)])
        elif isinstance(item, str):
            groups.append([item])
    return groups


def _prompt_line_text_and_key(line: str) -> tuple[str, str]:
    """回傳逐字 prompt 行與去除單一「- 」前綴後的正規化比對鍵。"""
    match_text = line[2:] if line.startswith("- ") else line
    return line, normalize_text(match_text)


def _trace_document_ids(traces: Sequence[Mapping[str, Any]]) -> list[str]:
    return sorted(
        {
            str(trace["source_doc_id"]).strip()
            for trace in traces
            if trace.get("source_doc_id") is not None
            and str(trace.get("source_doc_id")).strip()
        }
    )


def _classify_trace_matches(traces: Sequence[Mapping[str, Any]]) -> str:
    """分類文字匹配結果；無來源 ID 的 trace 不會被視為唯一歸屬。"""
    if not traces:
        return "unmatched"
    document_ids = _trace_document_ids(traces)
    has_missing_document = any(
        trace.get("source_doc_id") is None or not str(trace.get("source_doc_id")).strip()
        for trace in traces
    )
    if len(document_ids) >= 2:
        return "multi_source"
    if len(document_ids) == 1 and not has_missing_document:
        return "unique"
    return "source_unresolved"


def _linear_quantiles(values: Sequence[float]) -> dict[str, float | None]:
    """計算可重現的線性插值分位數（與 NumPy method='linear' 一致）。"""
    if not values:
        return {f"p{percentile}": None for percentile in (0, 25, 50, 75, 90, 95, 100)}
    ordered = sorted(float(value) for value in values)
    results: dict[str, float] = {}
    for percentile in (0, 25, 50, 75, 90, 95, 100):
        position = (len(ordered) - 1) * percentile / 100
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        fraction = position - lower
        results[f"p{percentile}"] = ordered[lower] * (1 - fraction) + ordered[upper] * fraction
    return results


def _sha256_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def load_phase2_snapshot(snapshot_dir: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """只從指定快照讀 records.json，並驗證 allowlist、大小與 SHA-256。"""
    manifest_path = snapshot_dir / "snapshot_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    included = manifest.get("included_directories")
    if tuple(included or ()) != PHASE2_STAGE_DIRECTORIES:
        raise ValueError("snapshot manifest directories do not match the Phase 2 allowlist")
    file_entries = {entry.get("directory"): entry for entry in manifest.get("files", [])}
    if set(file_entries) != set(PHASE2_STAGE_DIRECTORIES):
        raise ValueError("snapshot manifest must contain exactly the eight allowed records files")

    records_by_folder: dict[str, list[dict[str, Any]]] = {}
    verified_files: list[dict[str, Any]] = []
    for directory in PHASE2_STAGE_DIRECTORIES:
        entry = file_entries[directory]
        if entry.get("status") != "snapshot_copy":
            raise ValueError(f"{directory}: manifest entry is not a snapshot copy")
        path = snapshot_dir / directory / "records.json"
        digest, size = _sha256_and_size(path)
        if digest != entry.get("sha256") or size != entry.get("bytes"):
            raise ValueError(f"{directory}: snapshot records.json hash or size mismatch")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
            raise ValueError(f"{directory}: records.json must contain a list of objects")
        records_by_folder[directory] = payload
        verified_files.append(
            {
                "directory": directory,
                "snapshot": f"{directory}/records.json",
                "sha256": digest,
                "bytes": size,
                "record_count": len(payload),
            }
        )
    return records_by_folder, {**manifest, "verified_files": verified_files}


def analyze_prompt_records(
    records_by_folder: Mapping[str, Sequence[Mapping[str, Any]]],
    eligible_ids: Iterable[str],
    document_names: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """離線分析每筆執行的 prompt 行與 in-prompt retrieval trace 來源。"""
    eligible = {str(question_id) for question_id in eligible_ids}
    law_names = dict(document_names or {})
    prompt_rows: list[dict[str, Any]] = []
    out_of_scope_records: list[dict[str, Any]] = []
    missing_prompt_context_records: list[dict[str, Any]] = []
    aggr18_attempts: list[dict[str, Any]] = []
    folder_record_counts: dict[str, int] = {}
    eligible_prompt_record_keys: set[tuple[str, int]] = set()

    for folder, records in records_by_folder.items():
        folder_record_counts[folder] = len(records)
        for record_index, record in enumerate(records):
            question_id = str(record.get("question_id") or "")
            location = {
                "source_folder": folder,
                "record_index": record_index,
                "question_id": question_id or None,
            }
            if question_id not in eligible:
                out_of_scope_records.append(location)
                continue
            eligible_prompt_record_keys.add((folder, record_index))

            lineage = record.get("lineage") if isinstance(record.get("lineage"), Mapping) else {}
            context = lineage.get("stage2_context")
            context = context if isinstance(context, Mapping) else {}
            if "prompt_context_lines" not in context:
                missing_prompt_context_records.append(location)
                raw_groups: Any = []
            else:
                raw_groups = context.get("prompt_context_lines")
            groups = _prompt_groups(raw_groups)

            retrieval = lineage.get("stage1_retrieval")
            retrieval = retrieval if isinstance(retrieval, Mapping) else {}
            traces = retrieval.get("retrieval_trace")
            trace_by_text: dict[str, list[dict[str, Any]]] = defaultdict(list)
            if isinstance(traces, list):
                for trace in traces:
                    if not isinstance(trace, Mapping) or trace.get("in_prompt") is not True:
                        continue
                    trace_text = trace.get("text")
                    trace_key = normalize_text(str(trace_text)) if trace_text is not None else ""
                    if not trace_key:
                        continue
                    trace_by_text[trace_key].append(
                        {
                            "kind": str(trace.get("kind") or "").lower(),
                            "text": trace_text,
                            "source_doc_id": trace.get("source_doc_id"),
                            "article_no": trace.get("article_no"),
                            "rank": trace.get("rank"),
                            "in_prompt": True,
                        }
                    )

            aggr18_attempt = {
                **location,
                "subquestions": [],
            } if question_id == "57-AGGR18" else None
            for group_index, group in enumerate(groups):
                aggr18_group = {"subquestion_index": group_index, "prompt_lines": []}
                for line_index, line in enumerate(group):
                    exact_line, key = _prompt_line_text_and_key(line)
                    matched = list(trace_by_text.get(key, [])) if key else []
                    status = _classify_trace_matches(matched)
                    source_ids = _trace_document_ids(matched)
                    row = {
                        **location,
                        "subquestion_index": group_index,
                        "line_index": line_index,
                        "prompt_line": exact_line,
                        "normalized_text": key,
                        "status": status,
                        "source_doc_ids": source_ids,
                        "documents": [
                            {"source_doc_id": source_id, "law_name": law_names.get(source_id)}
                            for source_id in source_ids
                        ],
                        "matched_traces": matched,
                        "trace_kinds": sorted({trace["kind"] for trace in matched if trace["kind"]}),
                        "same_document_duplicate": status == "unique" and len(matched) > 1,
                    }
                    prompt_rows.append(row)
                    if aggr18_attempt is not None:
                        aggr18_group["prompt_lines"].append(
                            {
                                "line_index": line_index,
                                "prompt_line": exact_line,
                                "status": status,
                                "matched_traces": matched,
                            }
                        )
                if aggr18_attempt is not None:
                    aggr18_attempt["subquestions"].append(aggr18_group)
            if aggr18_attempt is not None:
                aggr18_attempts.append(aggr18_attempt)

    total_lines = len(prompt_rows)
    status_counts = Counter(row["status"] for row in prompt_rows)
    by_question: dict[str, Counter[str]] = {question_id: Counter() for question_id in sorted(eligible)}
    for row in prompt_rows:
        stats = by_question[row["question_id"]]
        stats["prompt_lines"] += 1
        stats[row["status"]] += 1
        if row["same_document_duplicate"]:
            stats["same_document_duplicate"] += 1

    # Collision is evaluated inside one execution and one subquestion, never across reruns.
    run_groups: dict[tuple[str, int, int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in prompt_rows:
        run_groups[(row["source_folder"], row["record_index"], row["subquestion_index"], row["question_id"])].append(row)
    collision_rows: list[dict[str, Any]] = []
    collision_groups = 0
    for rows in run_groups.values():
        by_text: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            if row["status"] == "unique":
                by_text[row["normalized_text"]].append(row)
        for same_text_rows in by_text.values():
            if len({row["source_doc_ids"][0] for row in same_text_rows}) > 1:
                collision_groups += 1
                collision_rows.extend(same_text_rows)
    for row in collision_rows:
        by_question[row["question_id"]]["independent_cross_source_collision"] += 1

    def build_kind_metrics(kind: str | None) -> dict[str, Any]:
        kind_rows: list[dict[str, Any]] = []
        for row in prompt_rows:
            candidate_traces = [
                trace for trace in row["matched_traces"]
                if kind is None or trace.get("kind") == kind
            ]
            if kind is not None and not candidate_traces:
                continue
            kind_rows.append(
                {
                    **row,
                    "kind_status": _classify_trace_matches(candidate_traces),
                    "kind_source_doc_ids": _trace_document_ids(candidate_traces),
                    "kind_trace_count": len(candidate_traces),
                }
            )

        kind_counts = Counter(row["kind_status"] for row in kind_rows)
        duplicate_count = sum(
            row["kind_status"] == "unique" and row["kind_trace_count"] > 1
            for row in kind_rows
        )
        kind_collision_rows: list[dict[str, Any]] = []
        for rows in run_groups.values():
            rows_by_text: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in rows:
                traces_for_kind = [
                    trace for trace in row["matched_traces"]
                    if kind is None or trace.get("kind") == kind
                ]
                if (kind is None or traces_for_kind) and _classify_trace_matches(traces_for_kind) == "unique":
                    rows_by_text[row["normalized_text"]].append(
                        {**row, "kind_source_doc_ids": _trace_document_ids(traces_for_kind)}
                    )
            for repeated_rows in rows_by_text.values():
                if len({row["kind_source_doc_ids"][0] for row in repeated_rows}) > 1:
                    kind_collision_rows.extend(repeated_rows)

        frame_values: list[float] = []
        frame_pair_count = 0
        for rows in run_groups.values():
            attributable: list[dict[str, Any]] = []
            for row in rows:
                traces_for_kind = [
                    trace for trace in row["matched_traces"]
                    if kind is None or trace.get("kind") == kind
                ]
                if (kind is None or traces_for_kind) and _classify_trace_matches(traces_for_kind) == "unique":
                    attributable.append(
                        {**row, "kind_source_doc_ids": _trace_document_ids(traces_for_kind)}
                    )
            for left, right in combinations(attributable, 2):
                if left["kind_source_doc_ids"][0] == right["kind_source_doc_ids"][0]:
                    continue
                frame_values.append(frame_overlap(left["prompt_line"], right["prompt_line"]))
                frame_pair_count += 1

        return {
            "prompt_line_count": len(kind_rows),
            "uniquely_attributed_line_count": kind_counts["unique"],
            "multi_source_merged_line_count": kind_counts["multi_source"],
            "unmatched_line_count": kind_counts["unmatched"],
            "source_unresolved_line_count": kind_counts["source_unresolved"],
            "same_document_duplicate_line_count": duplicate_count,
            "independent_cross_source_collision_line_count": len(kind_collision_rows),
            "independent_cross_source_collision_group_count": len(
                {
                    (row["source_folder"], row["record_index"], row["subquestion_index"], row["normalized_text"])
                    for row in kind_collision_rows
                }
            ),
            "cross_document_frame_overlap_pair_count": frame_pair_count,
            "cross_document_frame_overlap_quantiles": _linear_quantiles(frame_values),
        }

    merged_examples: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
    for row in prompt_rows:
        if row["status"] != "multi_source":
            continue
        key = (row["normalized_text"], tuple(row["source_doc_ids"]))
        example = merged_examples.setdefault(
            key,
            {
                "prompt_line": row["prompt_line"],
                "normalized_text": row["normalized_text"],
                "documents": row["documents"],
                "occurrence_count": 0,
                "question_ids": set(),
                "source_folders": set(),
            },
        )
        example["occurrence_count"] += 1
        example["question_ids"].add(row["question_id"])
        example["source_folders"].add(row["source_folder"])
    top_examples = sorted(
        (
            {
                **example,
                "question_ids": sorted(example["question_ids"]),
                "source_folders": sorted(example["source_folders"]),
            }
            for example in merged_examples.values()
        ),
        key=lambda item: (-item["occurrence_count"], item["normalized_text"], tuple(doc["source_doc_id"] for doc in item["documents"])),
    )[:20]

    eligible_count = len(eligible)
    question_distribution = {
        question_id: {
            "prompt_line_count": values["prompt_lines"],
            "uniquely_attributed_line_count": values["unique"],
            "multi_source_merged_line_count": values["multi_source"],
            "unmatched_line_count": values["unmatched"],
            "source_unresolved_line_count": values["source_unresolved"],
            "same_document_duplicate_line_count": values["same_document_duplicate"],
            "independent_cross_source_collision_line_count": values["independent_cross_source_collision"],
        }
        for question_id, values in sorted(by_question.items())
    }
    collision_question_ids = sorted(
        question_id for question_id, values in by_question.items()
        if values["independent_cross_source_collision"]
    )
    all_kind_metrics = build_kind_metrics(None)
    observed_kinds = sorted(
        {kind for row in prompt_rows for kind in row["trace_kinds"] if kind}
    )
    by_trace_kind = {"fact": build_kind_metrics("fact"), "bfs": build_kind_metrics("bfs")}
    for kind in observed_kinds:
        if kind not in by_trace_kind:
            by_trace_kind[kind] = build_kind_metrics(kind)
    return {
        "eligible_question_count": eligible_count,
        "analyzed_prompt_record_count": len(eligible_prompt_record_keys),
        "prompt_line_count": total_lines,
        "prompt_line_status_counts": {
            "uniquely_attributed": status_counts["unique"],
            "multi_source_merged": status_counts["multi_source"],
            "unmatched": status_counts["unmatched"],
            "source_unresolved": status_counts["source_unresolved"],
        },
        "prompt_line_status_ratios_of_all_prompt_lines": {
            "uniquely_attributed": status_counts["unique"] / total_lines if total_lines else 0.0,
            "multi_source_merged": status_counts["multi_source"] / total_lines if total_lines else 0.0,
            "unmatched": status_counts["unmatched"] / total_lines if total_lines else 0.0,
            "source_unresolved": status_counts["source_unresolved"] / total_lines if total_lines else 0.0,
        },
        "same_document_duplicate_line_count": sum(row["same_document_duplicate"] for row in prompt_rows),
        "independent_cross_source_collision_line_count": len(collision_rows),
        "independent_cross_source_collision_line_ratio": len(collision_rows) / total_lines if total_lines else 0.0,
        "independent_cross_source_collision_group_count": collision_groups,
        "questions_with_independent_cross_source_collision": collision_question_ids,
        "questions_with_independent_cross_source_collision_count": len(collision_question_ids),
        "questions_with_independent_cross_source_collision_ratio_of_eligible": len(collision_question_ids) / eligible_count if eligible_count else 0.0,
        "multi_source_merged_examples_top20": top_examples,
        "multi_source_merged_question_distribution": {
            question_id: values["multi_source_merged_line_count"]
            for question_id, values in question_distribution.items()
        },
        "question_distribution": question_distribution,
        "by_trace_kind": {
            **by_trace_kind,
        },
        "observed_trace_kinds": observed_kinds,
        "cross_document_frame_overlap_pair_count": all_kind_metrics["cross_document_frame_overlap_pair_count"],
        "cross_document_frame_overlap_quantiles": all_kind_metrics["cross_document_frame_overlap_quantiles"],
        "out_of_scope_records": out_of_scope_records,
        "missing_prompt_context_records": missing_prompt_context_records,
        "folder_record_counts": folder_record_counts,
        "unmatched_prompt_rows": [
            {key: row[key] for key in ("source_folder", "record_index", "question_id", "subquestion_index", "line_index", "prompt_line")}
            for row in prompt_rows if row["status"] == "unmatched"
        ],
        "aggr18_prompt_attempts": aggr18_attempts,
    }


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

    candidate_ids = set(candidates["candidate_ids_in_rank_order"])
    exact_collision_lines = []
    for audit in question_audits:
        if not audit.get("gold_exact_collision"):
            continue
        if audit["id"] in candidate_ids:
            status = f"列入候選（rank={audit['candidate_rank']}）。"
        else:
            exclusions = []
            if audit["n_source_laws"] < 2:
                exclusions.append(
                    f"n_source_laws={audit['n_source_laws']}，低於候選門檻 n_source_laws >= 2"
                )
            if not audit["q_mentions_multi_law"]:
                exclusions.append("q_mentions_multi_law=false")
            status = "未列為候選：" + ("；".join(exclusions) or "未符合候選條件。")
        exact_collision_lines.append(
            f"- `{audit['id']}`：`gold_exact_collision=true`；{status}"
        )
    if not exact_collision_lines:
        exact_collision_lines.append("- 無 `gold_exact_collision=true` 的題目。")

    unmatched_lines = []
    for audit in question_audits:
        for span in audit["unmatched_spans"]:
            unmatched_lines.append(f"- `{audit['id']}`：{span}")
    if not unmatched_lines:
        unmatched_lines.append("- 無未配對 span。")

    total_gold_span_count = sum(len(audit["span_results"]) for audit in question_audits)
    unmatched_gold_span_count = sum(audit["unmatched_span_count"] for audit in question_audits)
    fully_unmatched_question_count = sum(
        bool(audit["span_results"])
        and audit["unmatched_span_count"] == len(audit["span_results"])
        for audit in question_audits
    )
    partially_unmatched_question_count = sum(
        0 < audit["unmatched_span_count"] < len(audit["span_results"])
        for audit in question_audits
    )
    unmatched_gold_span_ratio = (
        unmatched_gold_span_count / total_gold_span_count if total_gold_span_count else 0.0
    )

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
- 本段記錄 Phase 1（P1-a、P1-b、P1-c）；Phase 2 使用凍結快照後另列於下方。

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
- 與 manifest 相差的 {manifest.get('kg_fact_total', 0) - kg_stats['actual_fact_count']} 筆 Fact 全來自 `source_doc_id=c8298529-91e4-56b3-bf2b-32e847635de4`：沒有 `SUPPORTED_BY`→`LawArticle` 關係，因此被本次查詢的 join 排除；其內容包含「附表一之項次」及「有機溶劑作業場所 包含」。這些 Fact 未進入碰撞統計，故不影響碰撞數字。

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

`gold_exact_collision=true` 的題目（獨立於候選清單）：

{chr(10).join(exact_collision_lines)}

僅 `n_source_laws >= 2`、題目沒有多法規提示字眼的清單：

{chr(10).join(without_mention_lines)}

## 限制與可比性

- Jaccard 與句框重疊是字面度量，未涵蓋語意相似；句框重疊是依 AGGR18 形態設計的探索性度量，未經驗證為歧義判準。
- 配對使用文字互相包含規則，會配到同法相鄰條號；因此另外用 gold 條號標記主配對與額外配對。未配對 span 已列出；本次 {total_gold_span_count} 個 gold span 中有 {unmatched_gold_span_count} 個（{unmatched_gold_span_ratio:.1%}）未配對，遍及 {fully_unmatched_question_count + partially_unmatched_question_count} 題（{fully_unmatched_question_count} 題的所有 span 均未配對，另有 {partially_unmatched_question_count} 題部分未配對）。未配對不代表 KG 沒有該事實，只表示它未依本次文字與條號配對規則配上。
- 全 KG 64 個 Document 中有 15 個 `effective_date` 有值；`57-AGGR18` 涉及的兩部法之 Document 欄位皆為 `None`，本次不以生效日期分辨新舊法。
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


def _phase1_document_names(kg_wide: Mapping[str, Any], questions: Mapping[str, Any]) -> dict[str, str]:
    """僅從 Phase 1 已有輸出建立 source_doc_id→法規名對照。"""
    titles: dict[str, set[str]] = defaultdict(set)

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            source_id = value.get("source_doc_id")
            title = value.get("title") or value.get("document_title") or value.get("law_name")
            if source_id and title:
                titles[str(source_id).strip()].add(str(title).strip())
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(kg_wide)
    visit(questions)
    return {source_id: sorted(names)[0] for source_id, names in titles.items() if names}


def _phase2_summary_markdown(
    *,
    result: Mapping[str, Any],
    snapshot_manifest: Mapping[str, Any],
    generated_at: str,
    commit: str,
) -> str:
    folder_lines = [
        f"| `{item['directory']}` | {item['bytes']:,} | `{item['sha256']}` | {item['record_count']} |"
        for item in result["source_snapshot"]["verified_files"]
    ]
    folder_lines = folder_lines or ["| — | — | — | — |"]
    counts = result["prompt_line_status_counts"]
    ratios = result["prompt_line_status_ratios_of_all_prompt_lines"]
    kind_lines = []
    kind_order = [kind for kind in ("fact", "bfs") if kind in result["by_trace_kind"]]
    kind_order.extend(kind for kind in result["by_trace_kind"] if kind not in kind_order)
    for kind in kind_order:
        item = result["by_trace_kind"][kind]
        kind_lines.append(
            f"| {kind} | {item['prompt_line_count']} | {item['uniquely_attributed_line_count']} | "
            f"{item['multi_source_merged_line_count']} | {item['unmatched_line_count']} | "
            f"{item['same_document_duplicate_line_count']} | "
            f"{item['independent_cross_source_collision_line_count']} | "
            f"{item['cross_document_frame_overlap_pair_count']} | "
            f"{json.dumps(item['cross_document_frame_overlap_quantiles'], ensure_ascii=False, sort_keys=True)} |"
        )
    question_lines = [
        f"| `{question_id}` | {item['prompt_line_count']} | {item['uniquely_attributed_line_count']} | "
        f"{item['multi_source_merged_line_count']} | {item['unmatched_line_count']} | "
        f"{item['same_document_duplicate_line_count']} | "
        f"{item['independent_cross_source_collision_line_count']} |"
        for question_id, item in result["question_distribution"].items()
    ] or ["| — | 0 | 0 | 0 | 0 | 0 | 0 |"]
    example_lines = []
    for index, item in enumerate(result["multi_source_merged_examples_top20"], start=1):
        docs = "; ".join(
            f"`{doc['source_doc_id']}` ({doc['law_name'] or 'Phase 1 未提供法規名'})"
            for doc in item["documents"]
        )
        example_lines.append(
            f"{index}. {json.dumps(item['prompt_line'], ensure_ascii=False)} — {docs}；"
            f"出現 {item['occurrence_count']} 次；題目 {', '.join(item['question_ids'])}。"
        )
    if not example_lines:
        example_lines.append("沒有多來源合併行。")

    aggr18_lines: list[str] = []
    for attempt_index, attempt in enumerate(result["aggr18_prompt_attempts"], start=1):
        aggr18_lines.append(
            f"### 執行 {attempt_index}：`{attempt['source_folder']}`，record #{attempt['record_index']}"
        )
        for group in attempt["subquestions"]:
            aggr18_lines.append(f"子問題組 {group['subquestion_index'] + 1}：")
            for line in group["prompt_lines"]:
                aggr18_lines.append(
                    f"- 行 {line['line_index'] + 1}（{line['status']}）："
                    f"{json.dumps(line['prompt_line'], ensure_ascii=False)}"
                )
                for trace in line["matched_traces"]:
                    aggr18_lines.append(
                        "  - trace："
                        + json.dumps(
                            {
                                "kind": trace["kind"],
                                "text": trace["text"],
                                "source_doc_id": trace["source_doc_id"],
                                "article_no": trace["article_no"],
                                "rank": trace["rank"],
                                "in_prompt": trace["in_prompt"],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                    )
                if not line["matched_traces"]:
                    aggr18_lines.append("  - trace：無（unmatched）")
    if not aggr18_lines:
        aggr18_lines.append("快照中沒有 57-AGGR18 執行紀錄。")

    gold_checks = result.get("aggr18_multi_source_gold_checks", [])
    gold_lines = [
        f"- 行 {json.dumps(item['prompt_line'], ensure_ascii=False)}："
        f"gold exact span={str(item['matches_gold_exact_span']).lower()}。"
        for item in gold_checks
    ] or ["- AGGR18 沒有多來源合併行可比對 gold exact span。"]
    excluded_lines = [
        f"- `{item['source_folder']}` record #{item['record_index']}：`{item['question_id'] or '(無 question_id)'}`"
        for item in result["out_of_scope_records"]
    ] or ["- 無。"]
    unmatched_lines = [
        f"- `{item['question_id']}` / `{item['source_folder']}` record #{item['record_index']} / "
        f"子問題組 {item['subquestion_index'] + 1} / 行 {item['line_index'] + 1}："
        f"{json.dumps(item['prompt_line'], ensure_ascii=False)}"
        for item in result["unmatched_prompt_rows"]
    ] or ["- 無。"]

    frame_quantiles = json.dumps(
        result["cross_document_frame_overlap_quantiles"], ensure_ascii=False, sort_keys=True
    )
    return f"""## Phase 2：Stage A prompt 來源歧義與多來源行

### 執行資訊與凍結輸入

- 產出時間（UTC）：`{generated_at}`；執行時 commit：`{commit}`。
- 凍結題目範圍：`frozen_manifest.json` 的 `eligible_ids`，共 {result['eligible_question_count']} 題；只納入這些題目。
- 使用快照：`{snapshot_manifest.get('snapshot_root')}`。分析只讀快照副本，未讀取之後新增的資料夾／檔案。
- 每個 records.json 的快照大小與 SHA-256：

| 資料夾 | bytes | SHA-256 | 記錄數 |
|---|---:|---|---:|
{chr(10).join(folder_lines)}

- 未納入的非 eligible 記錄：{len(result['out_of_scope_records'])} 筆；清單見下方。
- 缺少 `prompt_context_lines` 欄位的 eligible 記錄：{len(result['missing_prompt_context_records'])} 筆。

### 配對規則與分母

- 巢狀 list 每個內層 list 視為一個子問題組；扁平 list 視為單一組；空 list 計 0 行。合併階段只按 `question_id` 納入／排除，所有資料夾與重跑記錄保留來源資料夾和 record 序號。
- 將 prompt 行開頭單一 `- ` 去除後，使用 Phase 1 `normalize_text` 與該筆 `retrieval_trace` 中 `in_prompt=true` 的 `text` 比對；不以相同字串以外的條件推測配對。
- **唯一歸屬行**：所有匹配 trace 都有 `source_doc_id`，且不同 ID 恰為 1。**多來源合併行**：同一 prompt 行匹配到至少 2 個不同 `source_doc_id`。**同文件重複**：匹配 trace 多筆，但只有 1 個不同 `source_doc_id`；不計歧義。**unmatched**：沒有匹配到任何符合條件 trace；列出並計入總行。匹配 trace 但缺來源 ID 者另列 `source_unresolved`。
- 獨立碰撞行只在同一執行、同一子問題組內計算：兩條以上各自唯一歸屬的 prompt 行正規化同文，且 source_doc_id 不同。跨資料夾／跨重跑不互相比對。依已確認的集合式文字配對，同一正規化鍵的行共享相同 trace 候選；若候選跨文件便列為多來源合併行，不任選一個來源，因此獨立碰撞行另外計數但不會把多來源行拆開。
- 以下狀態分別以總 prompt 行數為分母；同文件重複與獨立碰撞行是唯一歸屬行的子集。總行數 {result['prompt_line_count']}；唯一歸屬 {counts['uniquely_attributed']}（{ratios['uniquely_attributed']:.2%}）；多來源合併 {counts['multi_source_merged']}（{ratios['multi_source_merged']:.2%}）；unmatched {counts['unmatched']}（{ratios['unmatched']:.2%}）；來源未解 {counts['source_unresolved']}（{ratios['source_unresolved']:.2%}）；同文件重複 {result['same_document_duplicate_line_count']}；獨立跨來源碰撞行 {result['independent_cross_source_collision_line_count']}（{result['independent_cross_source_collision_line_ratio']:.2%}）。獨立碰撞文字組 {result['independent_cross_source_collision_group_count']} 組。
- 有至少一條獨立跨來源碰撞行的題目：{result['questions_with_independent_cross_source_collision_count']} / {result['eligible_question_count']}（{result['questions_with_independent_cross_source_collision_ratio_of_eligible']:.2%}）：{', '.join(result['questions_with_independent_cross_source_collision']) or '無'}。

### 多來源合併行（主要指標）

- 總數：{counts['multi_source_merged']}；占總 prompt 行數 {result['prompt_line_count']} 的 {ratios['multi_source_merged']:.2%}。
- 前 20 個範例（按快照中出現次數排序；只提供 Phase 1 輸出已能確認的法規名）：

{chr(10).join(example_lines)}

AGGR18 的多來源行是否為 gold exact span：

{chr(10).join(gold_lines)}

### 逐題分布

| 題目 | prompt 行 | 唯一歸屬 | 多來源合併 | unmatched | 同文件重複 | 獨立跨來源碰撞行 |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(question_lines)}

### Trace kind 分層與 frame_overlap

- 全部唯一歸屬行中，僅在同一執行／子問題組內配對不同 `source_doc_id` 的行對；共有 {result['cross_document_frame_overlap_pair_count']} 對。frame_overlap 分位數（線性插值）：`{frame_quantiles}`。此處只使用唯一歸屬行。
- `fact`／`bfs` 分層以該 kind 的匹配 trace 單獨判定歸屬；有多 kind trace 的 prompt 行可能出現在多層。實際快照觀察到的 trace kind：{', '.join(result['observed_trace_kinds']) or '無'}。本次 `bfs` 沒有 `in_prompt=true` trace；另有 trace kind 依原值另列。unmatched 行沒有可用 trace kind，故只在總計列出。各 kind 的 prompt 行分母是至少有一筆該 kind 匹配 trace 的行數；同一行可能出現在多個 kind。每層 frame_overlap 僅使用該 kind 下唯一歸屬且跨文件的行對。

| kind | 有該 kind trace 的 prompt 行 | 唯一歸屬 | 多來源 | unmatched | 同文件重複 | 獨立碰撞行 | 跨文件行對 | frame_overlap 分位數 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
{chr(10).join(kind_lines)}

### unmatched prompt 行

以下所有 unmatched 行都保留並計入總 prompt 行及 unmatched 分母：

{chr(10).join(unmatched_lines)}

### 快照中不在凍結 42 題的記錄（僅列出，不納入統計）

{chr(10).join(excluded_lines)}

### 57-AGGR18 實際 prompt 行與對應 trace

每個 prompt 字串以 JSON 字串格式逐字保留，trace 來自同筆紀錄中 `in_prompt=true` 且正規化文字匹配的項目。

{chr(10).join(aggr18_lines)}

### 限制與可比性

- 這是 `top_k=40`，不是凍結基準的 `top_k=20`；本統計只回答 prompt 行的來源是否唯一／多來源，不可用來比較答對率。
- 「source_doc_id 對應到多個 prompt 行」是觀察到的輸出關係；本統計無法單獨證實或否證 `vector_search_facts` 的 `(subject, rel_type, object)` 去重鍵如何影響候選到 prompt 行的轉換，故不據此宣稱成因。
- `frame_overlap` 是字面句框度量，不代表語意相同或有錯答風險；trace 以正規化文字對應，無法匹配者列為 unmatched。
"""


def run_phase2(
    *,
    snapshot_dir: Path = DEFAULT_PHASE2_SNAPSHOT_DIR,
    frozen_dir: Path = DEFAULT_FROZEN_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    """分析已凍結的 Stage A 輸出，不存取 Neo4j 或 T2 原始工作目錄。"""
    records_by_folder, snapshot_manifest = load_phase2_snapshot(snapshot_dir)
    frozen_manifest = json.loads((frozen_dir / "frozen_manifest.json").read_text(encoding="utf-8"))
    eligible_ids = frozen_manifest.get("eligible_ids")
    if not isinstance(eligible_ids, list) or not eligible_ids:
        raise ValueError("frozen_manifest.json must contain eligible_ids")
    kg_wide = json.loads((output_dir / "kg_wide.json").read_text(encoding="utf-8"))
    phase1_questions = json.loads(
        (output_dir / "questions_frozen42.json").read_text(encoding="utf-8")
    )
    analysis = analyze_prompt_records(
        records_by_folder,
        eligible_ids,
        _phase1_document_names(kg_wide, phase1_questions),
    )
    aggr18 = next(
        (question for question in phase1_questions.get("questions", []) if question.get("id") == "57-AGGR18"),
        {},
    )
    gold_span_keys = {
        normalize_text(span.get("exact_span"))
        for span in aggr18.get("span_results", [])
        if span.get("exact_span")
    }
    gold_checks = []
    for attempt in analysis["aggr18_prompt_attempts"]:
        for group in attempt["subquestions"]:
            for line in group["prompt_lines"]:
                if line["status"] == "multi_source":
                    _, key = _prompt_line_text_and_key(line["prompt_line"])
                    gold_checks.append(
                        {
                            "source_folder": attempt["source_folder"],
                            "record_index": attempt["record_index"],
                            "prompt_line": line["prompt_line"],
                            "matches_gold_exact_span": key in gold_span_keys,
                        }
                    )
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    analysis["aggr18_multi_source_gold_checks"] = gold_checks
    result: dict[str, Any] = {
        "generated_at_utc": generated_at,
        "git_commit": git_commit(),
        "snapshot_root": str(snapshot_dir),
        "source_snapshot": {
            "included_directories": list(PHASE2_STAGE_DIRECTORIES),
            "verified_files": snapshot_manifest["verified_files"],
        },
        "matching_rule": "strip one leading '- '; normalize_text equality with in_prompt=true retrieval_trace.text",
        "scope_rule": "question_id in frozen_manifest.eligible_ids; preserve all runs and folders",
        **analysis,
    }

    summary_path = output_dir / "summary.md"
    previous_summary = summary_path.read_text(encoding="utf-8")
    previous_summary = previous_summary.replace(
        "- 本次只完成 Phase 1（P1-a、P1-b、P1-c）；未讀取 T2 Stage A 輸出，Phase 2 待 T2 完成。",
        "- 本段記錄 Phase 1（P1-a、P1-b、P1-c）；Phase 2 使用凍結快照後另列於下方。",
    )
    previous_summary = previous_summary.replace(
        "\n- Phase 2 未執行，待 T2 Stage A 完整結束後另行處理。", ""
    )
    phase2_marker = "\n## Phase 2：Stage A prompt 來源歧義與多來源行\n"
    if phase2_marker in previous_summary:
        previous_summary = previous_summary.split(phase2_marker, 1)[0]
    phase2_summary = _phase2_summary_markdown(
        result=result,
        snapshot_manifest=snapshot_manifest,
        generated_at=generated_at,
        commit=result["git_commit"],
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "prompt_level_stageA.json", result)
    summary_path.write_text(previous_summary.rstrip() + "\n\n" + phase2_summary, encoding="utf-8")
    result["summary"] = phase2_summary
    return result


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
    parser.add_argument("--phase", choices=("1", "2"), default="1")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--frozen-dir", type=Path, default=DEFAULT_FROZEN_DIR)
    parser.add_argument("--test-cases", type=Path, default=DEFAULT_TEST_CASES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_PHASE2_SNAPSHOT_DIR)
    parser.add_argument("--batch-pause-seconds", type=float, default=BATCH_PAUSE_SECONDS)
    args = parser.parse_args(argv)
    try:
        if args.phase == "2":
            result = run_phase2(
                snapshot_dir=args.snapshot_dir,
                frozen_dir=args.frozen_dir,
                output_dir=args.output_dir,
            )
            print(
                "TASK-3 Phase 2 完成："
                + json.dumps(
                    {
                        "output_files": [
                            str(args.output_dir / "prompt_level_stageA.json"),
                            str(args.output_dir / "summary.md"),
                        ],
                        "prompt_line_count": result["prompt_line_count"],
                        "multi_source_merged_line_count": result["prompt_line_status_counts"]["multi_source_merged"],
                        "unmatched_line_count": result["prompt_line_status_counts"]["unmatched"],
                        "out_of_scope_record_count": len(result["out_of_scope_records"]),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                flush=True,
            )
            return 0
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
            f"Phase {args.phase} 停止：{type(error).__name__}；未輸出連線憑證或錯誤細節。",
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
