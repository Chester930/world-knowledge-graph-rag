"""報告62 §14.10：用已存的答案（不重跑模型），對更新後的題庫（`57-DIST1/2` 新增天數 span）
重新跑 `AtomicScorer`，比較新舊題庫下的判定是否改變（唯讀）。

只補救『答案其實有斷言新 span』的情況；不重新呼叫 LLM judge（新 span 是逐字比對，`gold_answer`
的天數片語通常逐字出現在答案中，不需要語意 fallback）。
用法：python scripts/eval/rescore_with_updated_bank.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "eval"))

from audit_scorer_disagreements import BASE_STAGES, CAND_STAGES, DATA, load  # noqa: E402
from services.atomic_scorer import AtomicScorer  # noqa: E402
from models.eval_schema import AtomicGoldFact  # noqa: E402


def clean(s: str) -> str:
    return "".join(s.split())


def main() -> None:
    bank = {q["id"]: q for q in json.loads((DATA / "test_cases.json").read_text(encoding="utf-8"))["questions"]}
    targets = ["57-DIST1", "57-DIST2"]
    facts = {qid: [AtomicGoldFact(**f) for f in bank[qid]["atomic_gold_facts"]] for qid in targets}

    for arm, loader_stages in (("base", ("baseline_runs/20260920_frozen", BASE_STAGES)), ("cand", ("candidate_runs", CAND_STAGES))):
        recs = [r for r in load(*loader_stages) if r["question_id"] in targets]
        for r in recs:
            qid = r["question_id"]
            old = r["atomic_score"]
            new = AtomicScorer.evaluate(r["answer"], facts[qid], refusal_expected=False,
                                        deterministic_guard_passed=r["deterministic_guard"]["is_valid"])
            print(f"{arm} {r['_stage']:14s} {qid}: old is_perfect={old['is_perfect']} acc={old['atomic_accuracy']:.2f} "
                  f"-> new is_perfect={new.is_perfect} acc={new.atomic_accuracy:.2f} "
                  f"| new missing={[m[:20] for m in new.missing_spans]}")


if __name__ == "__main__":
    main()
