"""Q5：L3′ 試點時間感知問題集的離線驗證器與決定性選題規則（報告264 §4）。

全程離線：只讀 `pilot_manifest.json`（Q1 輸出）與 collector 歷史檔（只讀）；不連任何資料庫／模型。

選題規則（**決定性、不得挑選**）：
- 實質修改相鄰版本對依 (pcode, 條號數值, 舊版 valid_from) 排序，**每隔 4 對取 1 對**（從第 1 對起）；另加請假規則（N0030006）**全部**實質修改對；
- 對照組 `format_only`、`same_hash` 各依同樣排序，**每隔 3 對取 1 對**（從第 1 對起），各取前 3 對；
- 每個實質修改對 2 題（`as_of`＝舊版 `valid_from`＋30 天、期望舊版；`as_of`＝新版 `valid_from`＋30 天、期望新版），對照組各 1 題。

判準 `EVALUATION_CRITERIA` 在看到任何檢索結果前定稿，**之後不得調整**（題庫 meta 內含同一份，測試鎖定其雜湊）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.analysis.law_version_inventory import DEFAULT_SOURCE_DIR, load_history_files  # noqa: E402
from scripts.analysis.pilot_version_corpus_builder import (  # noqa: E402
    article_sort_key,
    authoritative_records,
    truncate_navigation_noise,
)

SUBSTANTIVE_STRIDE = 4
CONTROL_STRIDE = 3
CONTROL_PICKS = 3
FULL_COVERAGE_PCODES = ("N0030006",)  # 請假規則：全部實質修改對
AS_OF_OFFSET_DAYS = 30
FORBIDDEN_TERMS = ("年", "版", "修正前", "修正後", "舊", "新")
REQUIRED_FIELDS = ("id", "question", "as_of", "law_id", "article_no", "expected_valid_from", "other_valid_from", "gold_exact_span",
                   "contrast_exact_span", "pair_kind", "is_conflict", "selection_index")
PAIR_KINDS = ("substantive", "format_only", "same_hash")

EVALUATION_CRITERIA: dict[str, Any] = {
    "retrieval": {"modes": ["asof", "naive"], "top_k": 20, "unit": "Fact 所屬 LawArticle（law_id＋article_no＋valid_from）", "uses_generation": False},
    "hit": "回傳的 Fact 中至少 1 個屬於「目標條文的期望版本」（對照組：acceptable_valid_froms 內任一版）",
    "leak": "回傳的 Fact 中至少 1 個屬於「目標條文的另一版」，且該版在 as_of 當時不應有效（舊版已被取代、或新版尚未生效）",
    "primary_metrics": {
        "population": "pair_kind＝substantive 且 is_conflict＝false",
        "asof_leak_rate_max": 0.05,
        "asof_hit_rate_min": "naive 的 hit 率",
    },
    "secondary_metrics": ["naive 的 leak 率（量化現行風險）", "hit 率差（asof 減 naive）"],
    "control": "pair_kind 為 format_only／same_hash：asof 與 naive 的 hit 不應有差（不誤殺）",
    "conflict": "is_conflict＝true 的題目另列，不計入主要指標",
    "immutability": "判準與題目在看到任何檢索結果前定稿，之後不得調整；未達標題只記錄原因（檢索缺漏／抽取缺漏／其他）",
}


def criteria_sha256() -> str:
    return hashlib.sha256(json.dumps(EVALUATION_CRITERIA, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


# ── 選題（純運算）────────────────────────────────────────────────────────────
def remove_whitespace(text: str) -> str:
    return re.sub(r"\s+", "", text)


def manifest_pairs(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """manifest 的相鄰版本對（下一版＝`valid_to_derived`，須在 manifest 內）；每對含 old／new 版本與 kind。"""
    by_chain = {(v["pcode"], v["article_no"], v["valid_from"]): v for v in manifest["versions"]}
    pairs = []
    for old in manifest["versions"]:
        if old["diff_to_next"] and old["valid_to_derived"]:
            new = by_chain.get((old["pcode"], old["article_no"], old["valid_to_derived"]))
            if new is not None:
                pairs.append({"old": old, "new": new, "kind": old["diff_to_next"]})
    return sorted(pairs, key=lambda p: (p["old"]["pcode"], article_sort_key(p["old"]["article_no"]), p["old"]["valid_from"]))


def select_question_pairs(manifest: Mapping[str, Any]) -> dict[str, list[tuple[int, dict[str, Any]]]]:
    """回傳 `{pair_kind: [(selection_index, pair)]}`；`selection_index` 是該 kind 排序序列中的序號（從 0 起）。"""
    pairs = manifest_pairs(manifest)
    by_kind = {kind: [p for p in pairs if p["kind"] == kind] for kind in PAIR_KINDS}
    substantive = by_kind["substantive"]
    picks = [i for i, p in enumerate(substantive) if i % SUBSTANTIVE_STRIDE == 0 or p["old"]["pcode"] in FULL_COVERAGE_PCODES]
    selected = {"substantive": [(i, substantive[i]) for i in picks]}
    for kind in ("format_only", "same_hash"):
        indices = list(range(0, len(by_kind[kind]), CONTROL_STRIDE))[:CONTROL_PICKS]
        selected[kind] = [(i, by_kind[kind][i]) for i in indices]
    return selected


def as_of_for(valid_from: str, offset_days: int = AS_OF_OFFSET_DAYS) -> str:
    return (date.fromisoformat(valid_from) + timedelta(days=offset_days)).isoformat()


def skeleton_questions(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """題目骨架（不含人工撰寫的問句與 span）：id／as_of／期望版本／選取序號等，由選題規則決定。"""
    rows: list[dict[str, Any]] = []
    for kind, picks in select_question_pairs(manifest).items():
        for index, pair in picks:
            old, new = pair["old"], pair["new"]
            base = {"law_id": old["pcode"], "article_no": old["law_article_no"], "pair_kind": kind,
                    "is_conflict": bool(old["is_conflict"]), "selection_index": index}
            tag = f"PTQ-{old['pcode']}-{old['article_no']}"
            if kind == "substantive":
                rows.append({"id": f"{tag}-old", "as_of": as_of_for(old["valid_from"]), "expected_valid_from": old["valid_from"],
                             "other_valid_from": new["valid_from"], "acceptable_valid_froms": [old["valid_from"]], "expected_role": "old", **base})
                rows.append({"id": f"{tag}-new", "as_of": as_of_for(new["valid_from"]), "expected_valid_from": new["valid_from"],
                             "other_valid_from": old["valid_from"], "acceptable_valid_froms": [new["valid_from"]], "expected_role": "new", **base})
            else:
                rows.append({"id": f"{tag}-ctl-{kind}", "as_of": as_of_for(new["valid_from"]), "expected_valid_from": new["valid_from"],
                             "other_valid_from": old["valid_from"], "acceptable_valid_froms": sorted([old["valid_from"], new["valid_from"]]),
                             "expected_role": "either", **base})
    return rows


# ── 原文與驗證 ───────────────────────────────────────────────────────────────
def load_texts(file_rows: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[tuple[str, str, str], str]:
    """(pcode, 條號, valid_from) → collector 原文（雜訊截除後；保持原字串，不轉半形）。"""
    records, _conflicts = authoritative_records(file_rows)
    return {(str(r["pcode"]), r["article_no_normalized"], str(r["valid_from"])): truncate_navigation_noise(str(r.get("content", "")))[0]
            for r in records}


def _issue(question_id: str, check: str, detail: str) -> dict[str, str]:
    return {"id": question_id, "check": check, "detail": detail}


def validate_question(question: Mapping[str, Any], texts: Mapping[tuple[str, str, str], str], versions: Mapping[tuple[str, str, str], Mapping[str, Any]]) -> dict[str, Any]:
    """單題核對；回傳 `{"issues": [...], "info": {...}}`。issues 為硬性失敗；info 為供人工複核的揭露。"""
    qid = str(question.get("id"))
    issues: list[dict[str, str]] = []
    missing = [f for f in REQUIRED_FIELDS if f not in question]
    if missing:
        return {"issues": [_issue(qid, "required_fields", f"缺少欄位 {missing}")], "info": {}}
    article = re.sub(r"^第\s*|\s*條$", "", str(question["article_no"]))
    pcode = str(question["law_id"])
    expected_key = (pcode, article, str(question["expected_valid_from"]))
    other_key = (pcode, article, str(question["other_valid_from"]))
    expected_text = remove_whitespace(texts.get(expected_key, ""))
    other_text = remove_whitespace(texts.get(other_key, ""))
    if not expected_text or not other_text:
        issues.append(_issue(qid, "versions_exist", f"collector 找不到版本文字：expected={expected_key in texts} other={other_key in texts}"))
    gold = remove_whitespace(str(question["gold_exact_span"]))
    if not gold or gold not in expected_text:
        issues.append(_issue(qid, "gold_in_expected_version", "gold_exact_span 不是期望版本原文的逐字子字串（去空白後比對）"))
    contrast_raw = question["contrast_exact_span"]
    if question["pair_kind"] == "substantive":
        contrast = remove_whitespace(str(contrast_raw or ""))
        if not contrast or contrast not in other_text:
            issues.append(_issue(qid, "contrast_in_other_version", "contrast_exact_span 不是另一版原文的逐字子字串"))
        elif contrast == gold:
            issues.append(_issue(qid, "contrast_differs_from_gold", "contrast 與 gold 相同"))
    elif contrast_raw is not None:
        issues.append(_issue(qid, "control_has_no_contrast", "對照組的 contrast_exact_span 必須是 null"))
    as_of = str(question["as_of"])
    try:
        as_of_date = date.fromisoformat(as_of)
    except ValueError:
        issues.append(_issue(qid, "as_of_format", f"as_of 不是有效的 YYYY-MM-DD：{as_of!r}"))
        as_of_date = None
    expected_version = versions.get(expected_key)
    if as_of_date is not None and expected_version is not None:
        starts = date.fromisoformat(str(expected_version["valid_from"]))
        ends = expected_version["valid_to_derived"]
        if not (starts <= as_of_date and (ends is None or as_of_date < date.fromisoformat(str(ends)))):
            issues.append(_issue(qid, "as_of_within_expected_validity", f"as_of {as_of} 不在期望版本有效期間 [{expected_version['valid_from']}, {ends})"))
    hits = [term for term in FORBIDDEN_TERMS if term in str(question["question"])]
    if hits:
        issues.append(_issue(qid, "question_has_no_time_terms", f"問句含時點用語 {hits}（供人工複核）"))
    contrast_text = remove_whitespace(str(contrast_raw or ""))
    # 揭露（非硬性失敗）：「新增條款」型的修正在另一版沒有對應文字，只能引用相關的共同句，此時 gold／contrast 會同時出現在兩版
    return {"issues": issues, "info": {"gold_also_in_other_version": bool(gold) and gold in other_text,
                                       "contrast_also_in_expected_version": bool(contrast_text) and contrast_text in expected_text}}


def validate_questions(doc: Mapping[str, Any], manifest: Mapping[str, Any], file_rows: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    texts = load_texts(file_rows)
    versions = {(v["pcode"], v["article_no"], v["valid_from"]): v for v in manifest["versions"]}
    questions = list(doc["questions"])
    results = [validate_question(q, texts, versions) for q in questions]
    issues = [i for r in results for i in r["issues"]]
    skeleton = skeleton_questions(manifest)
    expected_ids = sorted(s["id"] for s in skeleton)
    actual_ids = sorted(str(q.get("id")) for q in questions)
    selection_issues = []
    if len(set(actual_ids)) != len(actual_ids):
        selection_issues.append(_issue("*", "ids_unique", "題目 id 重複"))
    if actual_ids != expected_ids:
        selection_issues.append(_issue("*", "selection_reproducible", f"題目 id 與選題規則不符：多出 {sorted(set(actual_ids) - set(expected_ids))[:5]}，缺少 {sorted(set(expected_ids) - set(actual_ids))[:5]}"))
    by_id = {str(q.get("id")): q for q in questions}
    for s in skeleton:
        q = by_id.get(s["id"])
        if q is None:
            continue
        for field in ("as_of", "law_id", "article_no", "expected_valid_from", "other_valid_from", "pair_kind", "is_conflict", "selection_index"):
            if q.get(field) != s[field]:
                selection_issues.append(_issue(s["id"], "selection_reproducible", f"{field}={q.get(field)!r}，選題規則得 {s[field]!r}"))
    if doc.get("meta", {}).get("criteria") != EVALUATION_CRITERIA:
        selection_issues.append(_issue("*", "criteria_frozen", "題庫 meta.criteria 與預先寫死的判準不一致"))
    all_issues = issues + selection_issues
    return {
        "ok": not all_issues, "questions": len(questions),
        "by_pair_kind": dict(Counter(q.get("pair_kind") for q in questions)),
        "conflict_questions": sum(bool(q.get("is_conflict")) for q in questions),
        "selection_indices": {kind: [i for i, _ in picks] for kind, picks in select_question_pairs(manifest).items()},
        "checks_passed": {"gold_in_expected_version": sum(not any(i["check"] == "gold_in_expected_version" for i in r["issues"]) for r in results),
                          "contrast_in_other_version": sum(not any(i["check"] == "contrast_in_other_version" for i in r["issues"]) for r in results),
                          "as_of_within_expected_validity": sum(not any(i["check"] == "as_of_within_expected_validity" for i in r["issues"]) for r in results),
                          "question_has_no_time_terms": sum(not any(i["check"] == "question_has_no_time_terms" for i in r["issues"]) for r in results)},
        "time_term_hits": [i for i in issues if i["check"] == "question_has_no_time_terms"],
        "gold_also_in_other_version": [str(q.get("id")) for q, r in zip(questions, results) if r["info"].get("gold_also_in_other_version")],
        "contrast_also_in_expected_version": [str(q.get("id")) for q, r in zip(questions, results) if r["info"].get("contrast_also_in_expected_version")],
        "issues": all_issues, "criteria_sha256": criteria_sha256(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    from scripts.kg import pilot_import as pi

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--questions", type=Path, default=_REPO / "data" / "eval" / "pilot_time_questions.json")
    parser.add_argument("--corpus-dir", type=Path, default=None, help="Q1 輸出資料夾（含 pilot_manifest.json；只讀）")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR, help="collector 歷史檔目錄（只讀）")
    args = parser.parse_args(argv)
    manifest = pi.load_manifest(args.corpus_dir or pi.default_corpus_dir())
    doc = json.loads(args.questions.read_text(encoding="utf-8"))
    report = validate_questions(doc, manifest, load_history_files(args.source_dir))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
