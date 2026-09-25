"""報告81：S3 missing spans 的獨立模型盲審交叉驗證（唯讀）。

本腳本只負責選取 S0 S3 records、讀取報告79 的既有判定與持久化結果；盲審
prompt、Ollama request（包含 think=false）、答案壓縮與卸載全部重用報告62
§14.6 的既有實作，不在這裡複製或改寫。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_scorer_disagreements import DATA, load  # noqa: E402
from scorer_audit_crosscheck import PROMPT, ask, compact_answer, unload  # noqa: E402


S0_ROOT = "baseline_runs/20260923_rebased"
S0_STAGES = ["stage_s0_r1", "stage_s0_r1_resume1", "stage_s0_r2"]
TARGET_IDS = [
    "18-Q1",
    "18-Q6",
    "57-COREF3",
    "57-DIST2",
    "57-AGGR6",
    "57-AGGR14",
    "57-AGGR19",
]
DEFAULT_MODELS = ["granite4.2:3b", "qwen3.5:4b"]
REJUDGE_PATH = DATA / "candidate_runs" / "s3_rule_r_rejudge.json"
DEFAULT_OUT = DATA / "candidate_runs" / "s3_blind_crosscheck.json"


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    return None


def _case_id(question_id: str, span: str) -> str:
    return f"{question_id}::{span}"


def _load_cases() -> list[dict[str, Any]]:
    """Build one case per unique (question, missing span), preserving source stages."""
    rejudge = json.loads(REJUDGE_PATH.read_text(encoding="utf-8"))
    question_votes = rejudge["arms"]["S0"]["question_votes"]
    records = load(S0_ROOT, S0_STAGES)
    cases_by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        question_id = record["question_id"]
        if question_id not in TARGET_IDS:
            continue
        votes = question_votes[question_id]
        for span in record.get("atomic_score", {}).get("missing_spans") or []:
            case_id = _case_id(question_id, span)
            case = cases_by_id.setdefault(
                case_id,
                {
                    "case_id": case_id,
                    "question_id": question_id,
                    "missing_span": span,
                    "original_meets": bool(votes["original"]),
                    "rule_r_meets": bool(votes["rule_r"]),
                    "source_stages": [],
                    "source_record_count": 0,
                    "answer": record["answer"],
                    "answer_char_count": len(record["answer"]),
                    "models": {},
                },
            )
            case["source_stages"].append(record["_stage"])
            case["source_record_count"] += 1
            if record["answer"] != case["answer"]:
                case.setdefault("answer_variants", []).append(
                    {"stage": record["_stage"], "answer": record["answer"]}
                )
    cases = list(cases_by_id.values())
    cases.sort(key=lambda case: (TARGET_IDS.index(case["question_id"]), case["missing_span"]))
    for case in cases:
        case["source_stages"] = sorted(set(case["source_stages"]))
    return cases


def _stats(cases: list[dict[str, Any]], models: list[str]) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    for model in models:
        parsed = [
            (case, _bool_or_none(case.get("models", {}).get(model, {}).get("supported")))
            for case in cases
        ]
        comparable = [(case, value) for case, value in parsed if value is not None]
        vs_original = {
            case["case_id"]
            for case, value in comparable
            if value == bool(case["original_meets"])
        }
        vs_rule_r = {
            case["case_id"]
            for case, value in comparable
            if value == bool(case["rule_r_meets"])
        }
        stats[model] = {
            "total_cases": len(cases),
            "parseable_cases": len(comparable),
            "unparseable_cases": len(cases) - len(comparable),
            "vs_original": {
                "agree": len(vs_original),
                "denominator": len(comparable),
                "rate": len(vs_original) / len(comparable) if comparable else None,
                "disagreement_case_ids": [
                    case["case_id"] for case, _ in comparable if case["case_id"] not in vs_original
                ],
            },
            "vs_rule_r": {
                "agree": len(vs_rule_r),
                "denominator": len(comparable),
                "rate": len(vs_rule_r) / len(comparable) if comparable else None,
                "disagreement_case_ids": [
                    case["case_id"] for case, _ in comparable if case["case_id"] not in vs_rule_r
                ],
            },
        }

    if len(models) >= 2:
        left, right = models[0], models[1]
        comparable_pair = []
        for case in cases:
            lv = _bool_or_none(case.get("models", {}).get(left, {}).get("supported"))
            rv = _bool_or_none(case.get("models", {}).get(right, {}).get("supported"))
            if lv is not None and rv is not None:
                comparable_pair.append((case, lv, rv))
        stats["model_pair"] = {
            "models": [left, right],
            "agree": sum(lv == rv for _, lv, rv in comparable_pair),
            "denominator": len(comparable_pair),
            "rate": (
                sum(lv == rv for _, lv, rv in comparable_pair) / len(comparable_pair)
                if comparable_pair
                else None
            ),
            "disagreement_case_ids": [
                case["case_id"] for case, lv, rv in comparable_pair if lv != rv
            ],
        }
    return stats


def _write(path: Path, cases: list[dict[str, Any]], models: list[str], status: str) -> None:
    output = {
        "description": "報告81 T1-T3：S3 S0 missing spans 的獨立模型盲審；非正式真值驗證",
        "status": status,
        "params": {
            "models": models,
            "think": False,
            "source_root": S0_ROOT,
            "source_stages": S0_STAGES,
            "target_question_ids": TARGET_IDS,
            "excluded_question_ids": ["17-Q6", "canary-P4"],
            "rejudge_source": str(REJUDGE_PATH.relative_to(DATA)),
            "case_count": len(cases),
        },
        "cases": cases,
        "stats": _stats(cases, models),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--model", action="append", dest="models")
    args = parser.parse_args()
    models = args.models or DEFAULT_MODELS
    out = Path(args.out)

    cases = _load_cases()
    if not cases:
        raise SystemExit("沒有找到目標題目的 S0 missing spans")
    if out.exists():
        previous = json.loads(out.read_text(encoding="utf-8"))
        previous_cases = {case["case_id"]: case for case in previous.get("cases", [])}
        for case in cases:
            case["models"].update(previous_cases.get(case["case_id"], {}).get("models", {}))

    question_by_id = {
        question["id"]: question
        for question in json.loads((DATA / "test_cases.json").read_text(encoding="utf-8"))["questions"]
    }
    _write(out, cases, models, "running")
    print(f"盲審案例 {len(cases)} 筆；模型：{', '.join(models)}；think=false", flush=True)
    for model in models:
        try:
            for case in cases:
                if model in case["models"]:
                    continue
                prompt = PROMPT.format(
                    question=question_by_id[case["question_id"]]["question"],
                    span=case["missing_span"],
                    answer=compact_answer(case["answer"]),
                )
                try:
                    response = ask(model, prompt)
                except SystemExit as exc:
                    response = {"supported": None, "reason": f"Ollama error: {exc}"}
                except Exception as exc:  # noqa: BLE001
                    response = {"supported": None, "reason": f"exception: {exc}"}
                case["models"][model] = response
                print(
                    f"{model} {case['question_id']} -> {response.get('supported')}",
                    flush=True,
                )
                _write(out, cases, models, "running")
        finally:
            unload(model)
    _write(out, cases, models, "complete")
    print(f"saved {out}", flush=True)
    for model, result in _stats(cases, models).items():
        if model == "model_pair":
            continue
        print(
            f"{model}: 原評分器 {result['vs_original']['agree']}/{result['vs_original']['denominator']}；"
            f"規則R {result['vs_rule_r']['agree']}/{result['vs_rule_r']['denominator']}；"
            f"N/A {result['unparseable_cases']}",
            flush=True,
        )


if __name__ == "__main__":
    main()
