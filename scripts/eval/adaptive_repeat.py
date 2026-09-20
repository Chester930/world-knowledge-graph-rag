"""Quality-gated adaptive repetition for RQ1 baseline runs.

Instead of a fixed number of runs per question, each question is repeated only
while its outcome is not yet determinable.  The standard is declared here, in
code, before any results exist, so it cannot drift after seeing the numbers.

A run MEETS THE STANDARD iff all of:
  * it produced no harness error / timeout (otherwise it is INVALID and ignored),
  * ``atomic_score.is_perfect`` is true,
  * the deterministic ``scope_audit`` (when present) passed.

Per-question decision over its valid runs (max 3):
  * [pass]                     -> single_pass  (stability unverified; audit-sample candidate)
  * [fail]                     -> needs 2nd run
  * [pass, pass]/[fail, fail]  -> stable_pass / stable_fail
  * [pass, fail]/[fail, pass]  -> needs 3rd run (tie-break)
  * three valid runs           -> unstable (majority decides the label)
  * two invalid runs           -> infra_failure (not a quality verdict)

Single-run passes could be lucky, so a seeded sample of them is re-run once and
the share that pass again is reported as an estimate of single-run reliability.

Usage:
    python scripts/eval/adaptive_repeat.py --bank data/eval/test_cases.json \
        --records A=out_a/records.json --records B=out_b/records.json \
        --eligible-ids ids.json --emit-questions next_questions.json --seed 20260920
"""
from __future__ import annotations

import argparse
import json
import math
import random
from typing import Any

MAX_VALID_RUNS = 3
MAX_INVALID_RUNS = 2
AUDIT_FRACTION = 0.25
AUDIT_MIN = 4
AUDIT_MAX = 10


def is_invalid(record: dict[str, Any]) -> bool:
    return bool(record.get("error"))


def meets_standard(record: dict[str, Any]) -> bool:
    if is_invalid(record):
        return False
    if not (record.get("atomic_score") or {}).get("is_perfect", False):
        return False
    scope_audit = record.get("scope_audit")
    return True if scope_audit is None else bool(scope_audit.get("passed", True))


def classify(valid: list[bool], invalid_count: int) -> tuple[str, bool]:
    """Return (status, needs_another_run) from the ordered valid results."""
    if len(valid) == 0:
        if invalid_count >= MAX_INVALID_RUNS:
            return "infra_failure", False
        return "pending", True
    if len(valid) == 1:
        return ("single_pass", False) if valid[0] else ("needs_second_run", True)
    if len(valid) == 2:
        if valid[0] == valid[1]:
            return ("stable_pass" if valid[0] else "stable_fail"), False
        return "needs_third_run", True
    return "unstable", False


def summarize(
    eligible_ids: list[str], runs_by_question: dict[str, list[dict[str, Any]]]
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for qid in eligible_ids:
        records = runs_by_question.get(qid, [])
        valid = [meets_standard(r) for r in records if not is_invalid(r)]
        invalid_count = sum(1 for r in records if is_invalid(r))
        status, needs = classify(valid, invalid_count)
        out[qid] = {
            "status": status,
            "needs_run": needs,
            "valid_results": valid,
            "invalid_runs": invalid_count,
        }
    return out


def pick_audit_sample(single_pass_ids: list[str], seed: int) -> list[str]:
    if not single_pass_ids:
        return []
    size = min(
        len(single_pass_ids),
        max(AUDIT_MIN, min(AUDIT_MAX, math.ceil(AUDIT_FRACTION * len(single_pass_ids)))),
    )
    return sorted(random.Random(seed).sample(sorted(single_pass_ids), size))


def audit_reliability(
    summary: dict[str, dict[str, Any]], audit_ids: list[str]
) -> dict[str, Any]:
    rerun = [q for q in audit_ids if len(summary[q]["valid_results"]) >= 2]
    repassed = [q for q in rerun if summary[q]["valid_results"][1]]
    return {
        "sampled": len(audit_ids),
        "rerun_completed": len(rerun),
        "passed_again": len(repassed),
        "reliability": (len(repassed) / len(rerun)) if rerun else None,
    }


def load_runs(record_specs: list[str]) -> dict[str, list[dict[str, Any]]]:
    runs: dict[str, list[dict[str, Any]]] = {}
    for spec in record_specs:
        _, _, path = spec.partition("=")
        with open(path or spec, encoding="utf-8") as fh:
            for record in json.load(fh):
                runs.setdefault(record["question_id"], []).append(record)
    return runs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bank", required=True)
    parser.add_argument("--records", action="append", default=[], help="LABEL=path/to/records.json，依先後順序")
    parser.add_argument("--eligible-ids", required=True, help="JSON，含 eligible_ids")
    parser.add_argument("--emit-questions", help="輸出下一批要跑的題目檔（題庫格式）")
    parser.add_argument("--audit-file", help="抽查名單（首次產生後固定，之後重用）")
    parser.add_argument("--seed", type=int, default=20260920)
    parser.add_argument("--summary-out")
    args = parser.parse_args()

    eligible_ids = json.load(open(args.eligible_ids, encoding="utf-8"))["eligible_ids"]
    runs = load_runs(args.records)
    summary = summarize(eligible_ids, runs)

    # 抽查名單以第一輪（每題只有 1 次有效結果）的單次通過者決定，之後固定不變。
    audit_ids: list[str] = []
    if args.audit_file:
        try:
            audit_ids = json.load(open(args.audit_file, encoding="utf-8"))["audit_ids"]
        except FileNotFoundError:
            first_pass = [q for q, s in summary.items() if s["status"] == "single_pass"]
            audit_ids = pick_audit_sample(first_pass, args.seed)
            with open(args.audit_file, "w", encoding="utf-8") as fh:
                json.dump({"seed": args.seed, "audit_ids": audit_ids}, fh, ensure_ascii=False, indent=1)

    next_ids = sorted(
        {q for q, s in summary.items() if s["needs_run"]}
        | {q for q in audit_ids if len(summary[q]["valid_results"]) < 2 and summary[q]["invalid_runs"] < MAX_INVALID_RUNS}
    )
    counts: dict[str, int] = {}
    for s in summary.values():
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    result = {
        "status_counts": counts,
        "next_run_ids": next_ids,
        "audit": audit_reliability(summary, audit_ids),
        "questions": summary,
    }
    if args.summary_out:
        with open(args.summary_out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=1)
    print(json.dumps({k: result[k] for k in ("status_counts", "audit")}, ensure_ascii=False))
    print("next_run_ids:", len(next_ids), next_ids)

    if args.emit_questions:
        bank = json.load(open(args.bank, encoding="utf-8"))
        selected = [q for q in bank["questions"] if q["id"] in set(next_ids)]
        with open(args.emit_questions, "w", encoding="utf-8") as fh:
            json.dump({"questions": selected}, fh, ensure_ascii=False, indent=2)
        print(f"wrote {len(selected)} questions to {args.emit_questions}")


if __name__ == "__main__":
    main()
