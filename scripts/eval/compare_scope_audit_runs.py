"""Compare saved RQ1 scope-audit runs and emit an offline adoption gate."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


def _read_records(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("records")
    if not isinstance(data, list) or not data:
        raise ValueError(f"{path} must contain a non-empty records array")
    for index, record in enumerate(data):
        if not isinstance(record, dict) or record.get("error"):
            raise ValueError(f"{path} contains an invalid or failed record at index {index}")
    return data


def _read_run(path: Path, expected_arm: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records = _read_records(path)
    manifest_path = path.with_name("manifest.json")
    if not manifest_path.is_file():
        raise ValueError(f"missing run manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "completed":
        raise ValueError(f"{manifest_path} is not completed")
    if not manifest.get("preflight", {}).get("passed"):
        raise ValueError(f"{manifest_path} preflight did not pass")
    if manifest.get("arms") != [expected_arm]:
        raise ValueError(f"{manifest_path} must declare only arm {expected_arm}")
    if manifest.get("records_count") != len(records):
        raise ValueError(f"{manifest_path} records_count does not match records.json")

    expected_runs = set(range(1, int(manifest.get("runs", 0)) + 1))
    actual_runs: dict[str, set[int]] = defaultdict(set)
    for index, record in enumerate(records):
        if record.get("arm") != expected_arm:
            raise ValueError(f"{path} record {index} has unexpected arm")
        run = record.get("run")
        question_id = record.get("question_id")
        if not isinstance(run, int) or not question_id:
            raise ValueError(f"{path} record {index} lacks question_id or integer run")
        if run in actual_runs[str(question_id)]:
            raise ValueError(f"{path} has duplicate run {run} for {question_id}")
        actual_runs[str(question_id)].add(run)
    if any(run_ids != expected_runs for run_ids in actual_runs.values()):
        raise ValueError(f"{path} run IDs do not match manifest repeat count")
    if set(actual_runs) != set(manifest.get("eligible_question_ids", [])):
        raise ValueError(f"{path} question IDs do not match its manifest")
    return records, manifest


def _nested(record: dict[str, Any], *keys: str) -> Any:
    value: Any = record
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            raise ValueError(f"record is missing metric field: {'.'.join(keys)}")
        value = value[key]
    return value


def _score(record: dict[str, Any], *keys: str) -> float:
    try:
        value = float(_nested(record, *keys))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"metric {'.'.join(keys)} is not numeric") from exc
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"metric {'.'.join(keys)} must be finite and within [0, 1]")
    return value


def summarize_records(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        question_id = record.get("question_id")
        if not question_id:
            raise ValueError("record is missing question_id")
        grouped[str(question_id)].append(record)

    summaries: dict[str, dict[str, Any]] = {}
    for question_id, rows in sorted(grouped.items()):
        audit = [_nested(row, "scope_audit") for row in rows]
        if any(not isinstance(item.get("passed"), bool) for item in audit):
            raise ValueError(f"{question_id} has records without a boolean scope_audit.passed")
        summaries[question_id] = {
            "n": len(rows),
            "atomic_accuracy": statistics.median(
                _score(row, "atomic_score", "atomic_accuracy") for row in rows
            ),
            "context_recall": statistics.median(
                _score(row, "lineage", "stage1_retrieval", "recall_rate") for row in rows
            ),
            "snr": statistics.median(
                _score(row, "lineage", "stage1_retrieval", "snr") for row in rows
            ),
            "scope_passes": sum(item["passed"] for item in audit),
            "scope_total": len(audit),
        }
    return summaries


def _compare(
    reference: dict[str, dict[str, Any]],
    candidate: dict[str, dict[str, Any]],
    *,
    require_all_scope_pass: bool,
    require_accuracy_gain: bool = True,
) -> dict[str, Any]:
    if reference.keys() != candidate.keys():
        raise ValueError("all runs must contain the same question IDs")

    regressions: list[str] = []
    scope_failures: list[str] = []
    accuracy_gains: list[str] = []
    for question_id in reference:
        before, after = reference[question_id], candidate[question_id]
        if before["n"] != after["n"]:
            raise ValueError(f"{question_id} has different repeat counts between runs")
        for metric in ("atomic_accuracy", "context_recall", "snr"):
            if after[metric] + 1e-9 < before[metric]:
                regressions.append(f"{question_id}: {metric} {before[metric]:.4f}->{after[metric]:.4f}")
        if after["atomic_accuracy"] > before["atomic_accuracy"] + 1e-9:
            accuracy_gains.append(question_id)
        if after["scope_passes"] < before["scope_passes"]:
            regressions.append(
                f"{question_id}: scope passes {before['scope_passes']}/{before['scope_total']}"
                f"->{after['scope_passes']}/{after['scope_total']}"
            )
        if require_all_scope_pass and after["scope_passes"] != after["scope_total"]:
            scope_failures.append(
                f"{question_id}: scope audit {after['scope_passes']}/{after['scope_total']}"
            )

    passed = (
        not regressions
        and not scope_failures
        and (bool(accuracy_gains) or not require_accuracy_gain)
    )
    reasons = list(regressions)
    reasons.extend(scope_failures)
    if require_accuracy_gain and not accuracy_gains:
        reasons.append("no question improved in Atomic Accuracy")
    return {
        "go": passed,
        "accuracy_gain_questions": accuracy_gains,
        "regressions": regressions,
        "scope_failures": scope_failures,
        "reasons": reasons,
    }


def compare_runs(
    baseline_records: list[dict[str, Any]],
    control_records: list[dict[str, Any]],
    candidate_records: list[dict[str, Any]],
    *,
    baseline_manifest: dict[str, Any] | None = None,
    control_manifest: dict[str, Any] | None = None,
    candidate_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _validate_run_ids(baseline_records, control_records, candidate_records)
    baseline = summarize_records(baseline_records)
    control = summarize_records(control_records)
    candidate = summarize_records(candidate_records)
    manifests = (baseline_manifest, control_manifest, candidate_manifest)
    baseline_comparable = True
    baseline_mismatch: list[str] = []
    control_check: dict[str, Any] | None = None
    if all(manifests):
        manifest_keys = (
            "kg_id",
            "doc_ids",
            "chunk_size",
            "runs",
            "dataset_sha256",
            "generator_provider",
            "generator_model",
            "judge_provider",
            "judge_model",
            "embedding_provider",
            "embedding_model",
            "query_timeout_s",
            "formal_evaluation",
            "allow_shared_judge",
        )
        control_keys = manifest_keys
        for label, manifest in zip(("baseline", "control", "candidate"), manifests):
            missing = [key for key in manifest_keys if key not in manifest]
            if missing:
                raise ValueError(f"{label} manifest missing comparison fields: {missing}")
        if any(control_manifest.get(key) != candidate_manifest.get(key) for key in control_keys):
            raise ValueError("matched control and candidate manifests are incompatible")
        for key in manifest_keys:
            if baseline_manifest.get(key) != control_manifest.get(key):
                baseline_comparable = False
                baseline_mismatch.append(key)
        if baseline_comparable:
            control_check = _compare(
                baseline,
                control,
                require_all_scope_pass=False,
                require_accuracy_gain=False,
            )
    else:
        baseline_comparable = False
        baseline_mismatch.append("manifest metadata unavailable")
    candidate_check = _compare(control, candidate, require_all_scope_pass=True)
    overall_go = baseline_comparable and bool(control_check and control_check["go"]) and candidate_check["go"]
    return {
        "decision": "GO" if overall_go else "NO-GO",
        "gate_policy": (
            "No per-question regression in Atomic Accuracy, Context Recall, SNR, or scope pass rate; "
            "candidate must pass every scope audit and improve Atomic Accuracy on at least one question; "
            "all three runs must have matching manifests for GO."
        ),
        "baseline_comparable": baseline_comparable,
        "baseline_manifest_mismatches": baseline_mismatch,
        "baseline": baseline,
        "control": control,
        "candidate": candidate,
        "control_vs_baseline": control_check,
        "candidate_vs_control": candidate_check,
    }


def _validate_run_ids(*record_sets: list[dict[str, Any]]) -> None:
    run_maps = []
    for records in record_sets:
        mapping: dict[str, set[int]] = defaultdict(set)
        for record in records:
            question_id = str(record.get("question_id", ""))
            run = record.get("run")
            if not question_id or not isinstance(run, int):
                raise ValueError("all records must include question_id and integer run")
            mapping[question_id].add(run)
        run_maps.append(mapping)
    first = run_maps[0]
    for mapping in run_maps[1:]:
        if dict(first) != dict(mapping):
            raise ValueError("runs must have matching question IDs and run numbers")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True, help="Dense baseline records.json")
    parser.add_argument("--control", type=Path, required=True, help="Matched no-swap control records.json")
    parser.add_argument("--candidate", type=Path, required=True, help="Candidate records.json")
    parser.add_argument("--out", type=Path, help="Optional path for the JSON decision report")
    args = parser.parse_args()

    baseline, baseline_manifest = _read_run(args.baseline, "K")
    control, control_manifest = _read_run(args.control, "K")
    candidate, candidate_manifest = _read_run(args.candidate, "K")
    result = compare_runs(
        baseline,
        control,
        candidate,
        baseline_manifest=baseline_manifest,
        control_manifest=control_manifest,
        candidate_manifest=candidate_manifest,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
