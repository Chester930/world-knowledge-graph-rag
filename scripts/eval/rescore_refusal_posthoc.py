"""事後重算 Type-E（拒答題）評分：用擴充的拒答關鍵字對已存答案重新評分（報告57 §4.20）。

不改動、不覆寫任何凍結的紀錄；只讀 records.json 與題庫，輸出「原判定 vs 擴充後」的差異，
並附上命中關鍵字前後的答案片段，供人工逐筆確認沒有誤判通過。

注意：擴充清單來自已觀察到的答案用語，因此這是**敏感度分析**，不是無偏估計；
每一筆「新通過」都必須人工讀過答案才能採信。

用法：
    python scripts/eval/rescore_refusal_posthoc.py --bank data/eval/test_cases.json \
        --records A=…/stage_a/records.json --records B4=…/stage_b4/records.json --out result.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from models.eval_schema import AtomicGoldFact  # noqa: E402
from services.atomic_scorer import AtomicScorer  # noqa: E402

# 取自凍結基準中實際出現的實質拒答用語（canary-P4、57-CANARY2）。
EXTRA_REFUSAL_PATTERNS = [
    "無法得知", "無法回答", "沒有相關資訊", "並未涉及", "並未提及", "並未明確規定", "並未明確列出",
]


def rescore_record(record: dict, case: dict, extra_patterns: list[str]) -> dict | None:
    """回傳 Type-E 紀錄的重算結果；非拒答題或錯誤紀錄回傳 None。"""
    if case.get("scenario_type") != "Type-E" or record.get("error"):
        return None
    gold = [AtomicGoldFact(**g) for g in case.get("atomic_gold_facts", [])]
    common = dict(
        answer=record["answer"], atomic_gold_facts=gold, refusal_expected=True,
        trap_claim_spans=case.get("trap_claim_spans") or [],
    )
    before = AtomicScorer.evaluate(**common)
    after = AtomicScorer.evaluate(**common, extra_refusal_patterns=extra_patterns)
    clean = AtomicScorer._clean_text(record["answer"])
    hits = [p for p in extra_patterns if AtomicScorer._clean_text(p) in clean]
    return {
        "question_id": record["question_id"],
        "before_perfect": before.is_perfect,
        "after_perfect": after.is_perfect,
        "changed": before.is_perfect != after.is_perfect,
        "extra_patterns_hit": hits,
        "answer": record["answer"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bank", required=True)
    parser.add_argument("--records", action="append", default=[], help="LABEL=path")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    bank = {q["id"]: q for q in json.loads(Path(args.bank).read_text(encoding="utf-8"))["questions"]}
    results = []
    for spec in args.records:
        label, path = spec.split("=", 1)
        for record in json.loads(Path(path).read_text(encoding="utf-8")):
            res = rescore_record(record, bank[record["question_id"]], EXTRA_REFUSAL_PATTERNS)
            if res is not None:
                res["stage"] = label
                results.append(res)
    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in results:
        mark = "→ 新通過" if r["changed"] and r["after_perfect"] else ("→ 新失敗" if r["changed"] else "")
        print(f"{r['stage']:9s} {r['question_id']:11s} 原:{'P' if r['before_perfect'] else 'F'} "
              f"後:{'P' if r['after_perfect'] else 'F'} 命中擴充詞:{r['extra_patterns_hit']} {mark}")


if __name__ == "__main__":
    main()
