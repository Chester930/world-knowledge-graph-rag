"""Compare two K-arm P2 snapshot runs without contacting external services."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


L1_FIELDS = (
    ("lineage.stage1_retrieval.retrieved_fact_ids", ("lineage", "stage1_retrieval", "retrieved_fact_ids")),
    ("lineage.stage1_retrieval.retrieved_chunk_ids", ("lineage", "stage1_retrieval", "retrieved_chunk_ids")),
    ("lineage.stage1_retrieval.retrieval_trace", ("lineage", "stage1_retrieval", "retrieval_trace")),
    ("lineage.stage2_context.prompt_context_lines", ("lineage", "stage2_context", "prompt_context_lines")),
)
L2_FIELDS = (
    ("answer", ("answer",)),
    ("lineage.stage3_generation.raw_draft", ("lineage", "stage3_generation", "raw_draft")),
    ("lineage.stage3_generation.final_output", ("lineage", "stage3_generation", "final_output")),
    ("lineage.stage3_generation.grounding_passed", ("lineage", "stage3_generation", "grounding_passed")),
    ("lineage.stage3_generation.regenerated", ("lineage", "stage3_generation", "regenerated")),
)
L3_FIELDS = (
    ("atomic_score.is_perfect", ("atomic_score", "is_perfect")),
    ("atomic_score.supported_spans", ("atomic_score", "supported_spans")),
    ("atomic_score.missing_spans", ("atomic_score", "missing_spans")),
)
_MISSING = object()
_SUMMARY_LIMIT = 400


def _load_records(run_dir: str | Path) -> list[dict[str, Any]]:
    path = Path(run_dir) / "records.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("records")
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise ValueError(f"{path} must contain a JSON list of record objects")
    return payload


def _index_records(records: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        question_id = record.get("question_id")
        if not isinstance(question_id, str) or not question_id:
            raise ValueError(f"{label} contains a record without a question_id")
        if question_id in indexed:
            raise ValueError(f"{label} contains duplicate question ID: {question_id}")
        indexed[question_id] = record
    return indexed


def _at_path(record: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = record
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return _MISSING
        current = current[key]
    return current


def _short(value: Any) -> str:
    if value is _MISSING:
        return "<missing>"
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(text) > _SUMMARY_LIMIT:
        return text[: _SUMMARY_LIMIT - 1] + "…"
    return text


def _first_difference(left: Any, right: Any, path: str = "$") -> dict[str, str] | None:
    if left == right:
        return None
    if isinstance(left, dict) and isinstance(right, dict):
        for key in list(left) + [key for key in right if key not in left]:
            difference = _first_difference(left.get(key, _MISSING), right.get(key, _MISSING), f"{path}.{key}")
            if difference:
                return difference
        return {"path": path, "left": _short(left), "right": _short(right)}
    if isinstance(left, list) and isinstance(right, list):
        for index in range(min(len(left), len(right))):
            difference = _first_difference(left[index], right[index], f"{path}[{index}]")
            if difference:
                return difference
        return {"path": f"{path}.length", "left": str(len(left)), "right": str(len(right))}
    return {"path": path, "left": _short(left), "right": _short(right)}


def _compare_fields(
    left: dict[str, Any], right: dict[str, Any], fields: tuple[tuple[str, tuple[str, ...]], ...]
) -> dict[str, Any]:
    differences: list[dict[str, str]] = []
    field_results: dict[str, bool] = {}
    for name, path in fields:
        left_value = _at_path(left, path)
        right_value = _at_path(right, path)
        equal = left_value == right_value
        field_results[name] = equal
        if not equal:
            difference = _first_difference(left_value, right_value)
            assert difference is not None
            difference["field"] = name
            differences.append(difference)
    return {"equal": not differences, "fields": field_results, "differences": differences}


def _has_error(record: dict[str, Any]) -> bool:
    error = record.get("error")
    return error is not None and error != ""


def compare_runs(run_a: str | Path, run_b: str | Path) -> dict[str, Any]:
    """Compare two run directories and return a JSON-serializable report."""
    records_a = _index_records(_load_records(run_a), "run A")
    records_b = _index_records(_load_records(run_b), "run B")
    ids_a = list(records_a)
    ids_b = list(records_b)
    missing = sorted(set(ids_a) - set(ids_b))
    extra = sorted(set(ids_b) - set(ids_a))
    if missing or extra:
        parts = []
        if missing:
            parts.append(f"missing question IDs in run B: {', '.join(missing)}")
        if extra:
            parts.append(f"extra question IDs in run B: {', '.join(extra)}")
        raise ValueError("; ".join(parts))

    questions: dict[str, Any] = {}
    for question_id in ids_a:
        left = records_a[question_id]
        right = records_b[question_id]
        no_data = _has_error(left) or _has_error(right)
        if no_data:
            questions[question_id] = {
                "status": "無資料",
                "errors": {"run_a": left.get("error"), "run_b": right.get("error")},
                "l1": {"equal": False, "fields": {}, "differences": []},
                "l2": {"equal": False, "fields": {}, "differences": []},
                "l3": {"equal": False, "fields": {}, "differences": []},
            }
            continue
        questions[question_id] = {
            "status": "ok",
            "l1": _compare_fields(left, right, L1_FIELDS),
            "l2": _compare_fields(left, right, L2_FIELDS),
            "l3": _compare_fields(left, right, L3_FIELDS),
        }

    overall_l1 = all(result["l1"]["equal"] for result in questions.values())
    overall_l2 = all(result["l2"]["equal"] for result in questions.values())
    overall_l3 = all(result["l3"]["equal"] for result in questions.values())
    return {
        "run_a": str(run_a),
        "run_b": str(run_b),
        "question_ids": ids_a,
        "questions": questions,
        "overall": {"l1": overall_l1, "l2": overall_l2, "l3": overall_l3},
        "l2_uncomparable": [
            question_id
            for question_id, result in questions.items()
            if result["status"] == "ok" and not result["l2"]["equal"]
        ],
        "l3_unstable": [
            question_id
            for question_id, result in questions.items()
            if result["status"] == "ok" and not result["l3"]["equal"]
        ],
        "exit_code": 0 if overall_l1 else 1,
    }


def _symbol(equal: bool) -> str:
    return "✅" if equal else "❌"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir_a")
    parser.add_argument("run_dir_b")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        result = compare_runs(args.run_dir_a, args.run_dir_b)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.out:
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for question_id in result["question_ids"]:
        row = result["questions"][question_id]
        if row["status"] == "無資料":
            print(f"{question_id}: 無資料")
        else:
            print(
                f"{question_id}: L1 {_symbol(row['l1']['equal'])} "
                f"L2 {_symbol(row['l2']['equal'])} L3 {_symbol(row['l3']['equal'])}"
            )
    print(
        "overall: "
        f"L1 {_symbol(result['overall']['l1'])} "
        f"L2 {_symbol(result['overall']['l2'])} "
        f"L3 {_symbol(result['overall']['l3'])}"
    )
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
