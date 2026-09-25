"""報告79：對報告72 S3 的 S0/B0/B1 做規則 R 離線敏感度重判。

這是診斷工具，不是正式評分器。規則實作全部重用報告62 §14 的工具；本檔案
只負責選取 S3 輸入、做每題多數決、輸出比較結果與兩個專項案例的證據。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scorer_rule_sensitivity as _rules  # noqa: E402
from audit_scorer_disagreements import DATA, load, overlap  # noqa: E402
from scorer_rule_sensitivity import (  # noqa: E402
    flip,
    meets_standard,
    perfect_prime,
    scope_ok,
)


ELIGIBLE_ROOT = "baseline_runs/20260923_rebased"
S0_STAGES = ["stage_s0_r1", "stage_s0_r1_resume1", "stage_s0_r2"]
ARM_STAGES = {
    "S0": (ELIGIBLE_ROOT, S0_STAGES),
    "B0": (
        "candidate_runs",
        [
            "s3_chunk_rag_b0_stage_a",
            "s3_chunk_rag_b0_stage_b",
            "s3_chunk_rag_b0_stage_c",
        ],
    ),
    "B1": (
        "candidate_runs",
        ["s3_chunk_rag_b1_stage_a", "s3_chunk_rag_b1_stage_b"],
    ),
}
SPECIAL_IDS = ("18-Q6", "57-DIST2")


def _majority(values: list[bool]) -> bool:
    """與既有敏感度腳本相同：有效執行採嚴格過半多數決。"""
    return bool(values) and sum(values) * 2 > len(values)


def _mcnemar_p(gains: list[str], losses: list[str]) -> float:
    discordant = len(gains) + len(losses)
    if discordant == 0:
        return 1.0
    tail = sum(math.comb(discordant, i) for i in range(min(len(gains), len(losses)) + 1))
    return min(1.0, 2 * tail / (2**discordant))


def _r_conditions(span: str, answer: str, threshold: float) -> dict[str, Any]:
    """展開既有 flip() 的三個條件，供 T3 審計；實際判定仍呼叫 flip()。"""
    answer_no_ws = re.sub(r"\s+", "", answer)
    number_tokens = _rules.NUM.findall(re.sub(r"\s+", "", span))
    overlap_score = overlap(span, answer)
    no_negation = not any(token in answer for token in _rules.NEG)
    numbers_present = all(token in answer_no_ws for token in number_tokens)
    return {
        "gold_span": span,
        "overlap": round(overlap_score, 6),
        "threshold": threshold,
        "overlap_ge_threshold": overlap_score >= threshold,
        "number_tokens": number_tokens,
        "all_number_tokens_present": numbers_present,
        "negation_tokens": [token for token in _rules.NEG if token in answer],
        "no_negation": no_negation,
        "flip": flip(span, answer, threshold),
    }


def _special_evidence(record: dict[str, Any], threshold: float) -> dict[str, Any]:
    answer = record.get("answer", "")
    missing = record.get("atomic_score", {}).get("missing_spans") or []
    return {
        "stage": record["_stage"],
        "question_id": record["question_id"],
        "answer": answer,
        "missing_spans": missing,
        "scope_ok": scope_ok(record),
        "deterministic_guard_passed": record.get("atomic_score", {}).get(
            "deterministic_guard_passed", True
        ),
        "conditions": [_r_conditions(span, answer, threshold) for span in missing],
    }


def _summarize(
    question_votes: dict[str, dict[str, list[bool]]], eligible_ids: list[str]
) -> dict[str, Any]:
    original = {qid: _majority(votes["original"]) for qid, votes in question_votes.items()}
    rule_r = {qid: _majority(votes["rule_r"]) for qid, votes in question_votes.items()}
    original.update({qid: False for qid in eligible_ids if qid not in original})
    rule_r.update({qid: False for qid in eligible_ids if qid not in rule_r})
    original_pass = [qid for qid in eligible_ids if original[qid]]
    rule_r_pass = [qid for qid in eligible_ids if rule_r[qid]]
    flipped_to_pass = [qid for qid in eligible_ids if not original[qid] and rule_r[qid]]
    pass_to_fail = [qid for qid in eligible_ids if original[qid] and not rule_r[qid]]
    return {
        "eligible_count": len(eligible_ids),
        "original_pass_count": len(original_pass),
        "rule_r_pass_count": len(rule_r_pass),
        "original_pass_ids": original_pass,
        "rule_r_pass_ids": rule_r_pass,
        "flipped_to_pass": flipped_to_pass,
        "pass_to_fail": pass_to_fail,
        "net_pass_change": len(rule_r_pass) - len(original_pass),
        "question_votes": {
            qid: {
                "valid_records": len(question_votes.get(qid, {}).get("original", [])),
                "original": original[qid],
                "rule_r": rule_r[qid],
                "original_votes": question_votes.get(qid, {}).get("original", []),
                "rule_r_votes": question_votes.get(qid, {}).get("rule_r", []),
            }
            for qid in eligible_ids
        },
    }


def _compare_mode(
    base: dict[str, Any],
    candidate: dict[str, Any],
    eligible_ids: list[str],
    mode: str,
) -> dict[str, Any]:
    base_pass = {qid: base["question_votes"][qid][mode] for qid in eligible_ids}
    candidate_pass = {qid: candidate["question_votes"][qid][mode] for qid in eligible_ids}
    gains = [qid for qid in eligible_ids if candidate_pass[qid] and not base_pass[qid]]
    losses = [qid for qid in eligible_ids if base_pass[qid] and not candidate_pass[qid]]
    return {
        "base_pass_count": sum(base_pass.values()),
        "candidate_pass_count": sum(candidate_pass.values()),
        "candidate_gains": gains,
        "base_advantages": losses,
        "candidate_minus_base_net": len(gains) - len(losses),
        "kg_minus_candidate_gap": len(losses) - len(gains),
        "exact_mcnemar_p": _mcnemar_p(gains, losses),
    }


def _compare(
    base: dict[str, Any], candidate: dict[str, Any], eligible_ids: list[str]
) -> dict[str, Any]:
    return {
        "candidate": candidate["arm"],
        "base": "S0",
        "original": _compare_mode(base, candidate, eligible_ids, "original"),
        "rule_r": _compare_mode(base, candidate, eligible_ids, "rule_r"),
    }


def _rejudge_arm(
    arm: str,
    records: list[dict[str, Any]],
    bank: dict[str, dict[str, Any]],
    eligible_ids: list[str],
    threshold: float,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    votes: dict[str, dict[str, list[bool]]] = {}
    rows: list[dict[str, Any]] = []
    special: list[dict[str, Any]] = []
    flag_arm = "base" if arm == "S0" else "cand"
    for record in records:
        qid = record["question_id"]
        tc = bank[qid]
        original = meets_standard(record)
        rule_r_core = perfect_prime(record, tc, threshold)
        rule_r = rule_r_core and _rules.extra_ok(record, flag_arm)
        votes.setdefault(qid, {"original": [], "rule_r": []})
        votes[qid]["original"].append(original)
        votes[qid]["rule_r"].append(rule_r)
        rows.append(
            {
                "arm": arm,
                "stage": record["_stage"],
                "question_id": qid,
                "orig_meets": original,
                "rule_r_core": rule_r_core,
                "rule_r_meets": rule_r,
                "scope_ok": scope_ok(record),
                "changed": original != rule_r,
            }
        )
        if qid in SPECIAL_IDS:
            special.append({**_special_evidence(record, threshold), "arm": arm})
    summary = _summarize(votes, eligible_ids)
    summary["arm"] = arm
    summary["record_count"] = len(records)
    summary["stage_counts"] = {
        stage: sum(1 for record in records if record["_stage"] == stage)
        for stage in ARM_STAGES[arm][1]
    }
    return summary, rows, special


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--t", type=float, default=0.7)
    parser.add_argument(
        "--out",
        default=str(DATA / "candidate_runs" / "s3_rule_r_rejudge.json"),
        help="離線重判 JSON 輸出路徑",
    )
    parser.add_argument(
        "--require-qty",
        action="store_true",
        help="保留舊工具的事後情境旗標；本次 S3 預設不啟用",
    )
    parser.add_argument(
        "--cand-fail",
        action="append",
        default=[],
        help="保留舊工具的候選強制失敗旗標；本次 S3 預設不啟用",
    )
    args = parser.parse_args()

    _rules.REQ_QTY = args.require_qty
    _rules.FORCE_FAIL_CAND.clear()
    _rules.FORCE_FAIL_CAND.update(args.cand_fail)

    bank = {
        question["id"]: question
        for question in json.loads((DATA / "test_cases.json").read_text(encoding="utf-8"))["questions"]
    }
    manifest_path = DATA / ELIGIBLE_ROOT / "frozen_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    eligible_ids = manifest["eligible_ids"]

    arms: dict[str, list[dict[str, Any]]] = {
        arm: load(stages_root, stages) for arm, (stages_root, stages) in ARM_STAGES.items()
    }
    summaries: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    special: list[dict[str, Any]] = []
    for arm, records in arms.items():
        summary, arm_rows, arm_special = _rejudge_arm(
            arm, records, bank, eligible_ids, args.t
        )
        summaries[arm] = summary
        rows.extend(arm_rows)
        special.extend(arm_special)

    comparisons = {
        f"S0_vs_{arm}": _compare(summaries["S0"], summaries[arm], eligible_ids)
        for arm in ("B0", "B1")
    }
    output = {
        "description": "報告79 T1-T4：S3 規則 R 離線敏感度分析；非正式評分結果",
        "params": {
            "T": args.t,
            "require_qty": args.require_qty,
            "cand_fail": sorted(args.cand_fail),
            "eligible_manifest": str(manifest_path.relative_to(DATA)),
            "eligible_count": len(eligible_ids),
        },
        "arms": summaries,
        "comparisons": comparisons,
        "record_results": rows,
        "special_cases": special,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"R 閾值 T={args.t}（樣本內診斷規則，非正式分數）")
    for arm in ("S0", "B0", "B1"):
        summary = summaries[arm]
        print(
            f"[{arm}] 原評分器 {summary['original_pass_count']}/{len(eligible_ids)}；"
            f"規則 R {summary['rule_r_pass_count']}/{len(eligible_ids)}；"
            f"改變 +{len(summary['flipped_to_pass'])}/-{len(summary['pass_to_fail'])}；"
            f"淨變化 {summary['net_pass_change']:+d}"
        )
    for name, comparison in comparisons.items():
        result = comparison["rule_r"]
        print(
            f"[{name}] chunk-RAG 新增 {len(result['candidate_gains'])}、"
            f"KG 優勢 {len(result['base_advantages'])}、"
            f"KG 相對差 {result['kg_minus_candidate_gap']:+d}；"
            f"exact McNemar p={result['exact_mcnemar_p']:.6f}"
        )
    print(f"寫入 {len(rows)} 筆執行重判與 {len(special)} 筆專項證據 → {out}")


if __name__ == "__main__":
    main()
