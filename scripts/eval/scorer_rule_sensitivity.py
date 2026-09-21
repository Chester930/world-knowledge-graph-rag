"""報告62 §14（T5）：用候選規則 R 重判所有紀錄，看 T2（K1 vs 基準）達標題數差距對評分器噪音是否穩定。

**敏感度分析，不是新的正式分數**：R 是在同一批標註案例上設計的（樣本內），且只補救偽陰性（不處理
偽陽性／歸屬錯置）。重判方式：非 Type-E 紀錄中，若評分器判 missing 的每個 gold span 都被 R 翻為
supported，且原本的 deterministic guard 與 scope audit 都通過，就把該次執行改判達標。每題結論用
「該題有效執行的多數決」（與 `t2_topk40_judgement.py` 對 unstable 題的處理一致）。
用法：python scripts/eval/scorer_rule_sensitivity.py [--t 0.7]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_scorer_disagreements import BASE_STAGES, CAND_STAGES, DATA, load, overlap  # noqa: E402

NUM = re.compile(r"[0-9]+|[一二三四五六七八九十百千萬兩]+")
NEG = ("無法確認", "未明確記載", "並未", "未直接", "沒有記載")


def flip(span: str, answer: str, t: float) -> bool:
    """規則 R（整份答案版）：重疊 ≥ t、gold 的數字／序號都在答案、答案沒有否定用語。"""
    if overlap(span, answer) < t:
        return False
    a = re.sub(r"\s+", "", answer)
    if any(n in answer for n in NEG):
        return False
    return all(n in a for n in NUM.findall(re.sub(r"\s+", "", span)))


def scope_ok(r: dict) -> bool:
    sa = r.get("scope_audit")
    return sa is None or bool(sa.get("passed", True))


def meets_standard(r: dict) -> bool:
    """與 `adaptive_repeat.py` 的達標定義一致：is_perfect 且 scope audit 通過。"""
    return bool(r["atomic_score"].get("is_perfect")) and scope_ok(r)


def perfect_prime(r: dict, tc: dict, t: float) -> bool:
    a = r["atomic_score"]
    if meets_standard(r):
        return True
    if tc["scenario_type"] == "Type-E" or not scope_ok(r):
        return False
    if not a.get("deterministic_guard_passed", True):
        return False
    missing = a.get("missing_spans") or []
    return bool(missing) and all(flip(m, r["answer"], t) for m in missing)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--t", type=float, default=0.7)
    args = ap.parse_args()
    bank = {q["id"]: q for q in json.loads((DATA / "test_cases.json").read_text(encoding="utf-8"))["questions"]}
    eligible = json.loads((DATA / "baseline_runs/20260920_frozen/frozen_manifest.json").read_text(encoding="utf-8"))["eligible_ids"]
    arms = {
        "base": load("baseline_runs/20260920_frozen", BASE_STAGES),
        "cand": load("candidate_runs", CAND_STAGES),
    }
    result = {}
    for arm, recs in arms.items():
        per_q_orig, per_q_new = {}, {}
        for r in recs:
            tc = bank[r["question_id"]]
            per_q_orig.setdefault(r["question_id"], []).append(meets_standard(r))
            per_q_new.setdefault(r["question_id"], []).append(perfect_prime(r, tc, args.t))
        result[arm] = (per_q_orig, per_q_new)

    def passed(d: dict, q: str) -> bool:
        v = d.get(q, [])
        return bool(v) and sum(v) * 2 > len(v)

    print(f"R 閾值 T={args.t}（樣本內規則；敏感度分析，非正式分數）")
    for label, idx in (("原評分器", 0), ("加規則 R 重判", 1)):
        b = {q: passed(result["base"][idx], q) for q in eligible}
        c = {q: passed(result["cand"][idx], q) for q in eligible}
        gains = [q for q in eligible if c[q] and not b[q]]
        losses = [q for q in eligible if b[q] and not c[q]]
        print(f"[{label}] 基準 {sum(b.values())}／候選 {sum(c.values())}／42；新增 {len(gains)}、退步 {len(losses)}，淨差 {len(gains) - len(losses):+d}")
        print(f"    新增 {gains}\n    退步 {losses}")
    changed = {arm: sum(1 for q in eligible if passed(result[arm][0], q) != passed(result[arm][1], q)) for arm in result}
    print("被 R 改變結論的題數：", changed)


if __name__ == "__main__":
    main()
