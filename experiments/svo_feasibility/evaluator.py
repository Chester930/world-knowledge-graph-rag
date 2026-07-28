"""Evaluate a small SVO feasibility benchmark.

The benchmark is intentionally independent from LLM providers and Neo4j. It
checks whether predicted SVO triples match a gold set and whether matched
triples point back to the expected source sentence.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Score:
    system: str
    gold_count: int
    predicted_count: int
    true_positive: int
    false_positive: int
    false_negative: int
    precision: float
    recall: float
    f1: float
    traceability: float


def _norm(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def triple_key(triple: dict[str, Any]) -> tuple[str, str, str]:
    return (
        _norm(str(triple.get("subject", ""))),
        _norm(str(triple.get("rel_type", ""))),
        _norm(str(triple.get("object", ""))),
    )


def _evidence_key(triple: dict[str, Any]) -> tuple[str, frozenset[str]]:
    return (
        str(triple.get("evidence_doc_id", "")),
        frozenset(str(item) for item in triple.get("evidence_sentence_ids", [])),
    )


def _safe_ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def evaluate_predictions(
    gold_triples: list[dict[str, Any]],
    predicted_triples: list[dict[str, Any]],
    *,
    system_name: str,
) -> Score:
    gold_by_key = {triple_key(item): item for item in gold_triples}
    predicted_by_key = {triple_key(item): item for item in predicted_triples}

    gold_keys = set(gold_by_key)
    predicted_keys = set(predicted_by_key)
    matched_keys = gold_keys & predicted_keys

    true_positive = len(matched_keys)
    false_positive = len(predicted_keys - gold_keys)
    false_negative = len(gold_keys - predicted_keys)

    precision = _safe_ratio(true_positive, true_positive + false_positive)
    recall = _safe_ratio(true_positive, true_positive + false_negative)
    f1 = _safe_ratio(2 * precision * recall, precision + recall)

    traceable = 0
    for key in matched_keys:
        gold_doc_id, gold_sentence_ids = _evidence_key(gold_by_key[key])
        pred_doc_id, pred_sentence_ids = _evidence_key(predicted_by_key[key])
        if pred_doc_id == gold_doc_id and gold_sentence_ids & pred_sentence_ids:
            traceable += 1

    traceability = _safe_ratio(traceable, true_positive)

    return Score(
        system=system_name,
        gold_count=len(gold_keys),
        predicted_count=len(predicted_keys),
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
        precision=precision,
        recall=recall,
        f1=f1,
        traceability=traceability,
    )


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def evaluate_sample_files(
    gold_path: Path = BASE_DIR / "gold_triples.json",
    predictions_path: Path = BASE_DIR / "sample_predictions.json",
) -> list[Score]:
    gold = load_json(gold_path)["triples"]
    systems = load_json(predictions_path)["systems"]
    return [
        evaluate_predictions(gold, system["triples"], system_name=system["name"])
        for system in systems
    ]


def _verdict(score: Score) -> str:
    if score.f1 == 1.0 and score.traceability == 1.0:
        return "PASS: 關係正確且可追溯"
    if score.predicted_count == 0:
        return "NO_TRIPLES: 無法做關係層驗證"
    return "PARTIAL: 有錯誤或來源不足"


def _format_scores(scores: list[Score]) -> str:
    lines = [
        "SVO 關聯性可行性驗證",
        "目標：檢查三元組是否正確，且是否能回到支持它的來源句。",
        "",
        "system           precision  recall  f1    trace  tp  fp  fn  verdict",
        "---------------  ---------  ------  ----  -----  --  --  --  ------------------------",
    ]
    for score in scores:
        lines.append(
            f"{score.system:15}  "
            f"{score.precision:9.2f}  "
            f"{score.recall:6.2f}  "
            f"{score.f1:4.2f}  "
            f"{score.traceability:5.2f}  "
            f"{score.true_positive:2d}  "
            f"{score.false_positive:2d}  "
            f"{score.false_negative:2d}  "
            f"{_verdict(score)}"
        )

    best = max(scores, key=lambda item: (item.f1, item.traceability))
    lines.extend(
        [
            "",
            f"結論：{best.system} 的 F1 與 Traceability 最高。",
            "解讀：只回傳文字無法直接證明關係；未驗證 SVO 會混入錯誤；驗證後 SVO 才能把關係與來源一起檢查。",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    print(_format_scores(evaluate_sample_files()))


if __name__ == "__main__":
    main()
