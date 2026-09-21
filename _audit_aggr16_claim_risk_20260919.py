"""Offline audit for extra and condition-mismatched AGGR15/16/17 claims.

This is deliberately deterministic and does not change the RQ1 scorer.  It audits
saved pilot answers against question-specific scope rules.  AGGR16 uses
Article 2-1's ordinary establishment thresholds for first/second category
businesses: Article 6's 500-person head-office rule is marked as an extra
scoped claim, and the second category "專責" wording is marked as a role
mismatch.  AGGR15 and AGGR17 have narrower checks for unrelated claims.
"""

from __future__ import annotations

import json
from pathlib import Path

from models.eval_schema import EvaluationDataset
from services.claim_scope_auditor import audit_answer_scope

ROOT = Path(__file__).resolve().parent
# The worktree runners write shared scratch artifacts to the main checkout's
# `.claude/tmp`, one level above the worktree's own `.claude` metadata.
BASE = ROOT.parents[2] / ".claude" / "tmp" / "rq1_fact_ranking_20260918"
DATASET = ROOT / "data" / "eval" / "test_cases.json"
METHODS = (
    "current_dense_top_k20",
    "bfs_slots_5",
    "fact_side_embedding_rerank",
    "fact_boundary_swap",
)
OUT = BASE / "claim_risk_audit.json"


def main() -> None:
    dataset = EvaluationDataset.model_validate(json.loads(DATASET.read_text(encoding="utf-8")))
    cases = {case.id: case for case in dataset.questions}
    rows: list[dict[str, object]] = []
    for method in METHODS:
        path = BASE / method / "records.json"
        if not path.exists():
            continue
        records = json.loads(path.read_text(encoding="utf-8"))
        for record in records:
            if record.get("question_id") not in {"57-AGGR15", "57-AGGR16", "57-AGGR17"}:
                continue
            question_id = record["question_id"]
            scope_audit = audit_answer_scope(record.get("answer", ""), cases[question_id])
            result = {
                "risk_flags": [issue["rule_id"] for issue in scope_audit["issues"]],
                "extra_or_condition_risk_count": scope_audit["issue_count"],
                "risk_adjusted_pass": scope_audit["passed"],
            }
            result["risk_adjusted_pass"] = bool(
                result["risk_adjusted_pass"]
                and record.get("atomic_score", {}).get("atomic_accuracy") == 1.0
            )
            rows.append(
                {
                    "method": method,
                    "question_id": question_id,
                    "run": record.get("run"),
                    "atomic_accuracy": record.get("atomic_score", {}).get("atomic_accuracy"),
                    **result,
                }
            )
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for method in METHODS:
        group = [row for row in rows if row["method"] == method]
        if not group:
            continue
        perfect = sum(row["risk_adjusted_pass"] for row in group)
        flagged = sum(row["extra_or_condition_risk_count"] > 0 for row in group)
        print(f"{method}: {len(group)} runs; atomic=",
              ",".join(str(row["atomic_accuracy"]) for row in group),
              f"; risk_adjusted_pass={perfect}/{len(group)}; flagged={flagged}/{len(group)}")


if __name__ == "__main__":
    main()
