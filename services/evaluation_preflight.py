"""RQ1 正式評測啟動前的可重現性與資格檢查。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from models.eval_schema import ScenarioType, TestCase
from services.evaluation_eligibility import assess_test_case


SUPPORTED_ARMS = frozenset({"M1", "M2", "M3", "M4", "D", "G", "K", "K-2b"})
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass
class PreflightResult:
    """Preflight 的可序列化結果，供 console 與 manifest 共用。"""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def run_evaluation_preflight(
    *,
    test_cases: Iterable[TestCase],
    arms: Iterable[str],
    generator_provider: str,
    generator_model: str | None,
    judge_provider: str,
    judge_model: str | None,
    doc_ids: Iterable[str],
    dataset_sha256: str | None,
    query_timeout_s: float,
    allow_shared_judge: bool = False,
) -> PreflightResult:
    """檢查正式評測的靜態前置條件；不連線、不呼叫模型。"""
    result = PreflightResult()
    cases = list(test_cases)
    arm_list = [arm.strip() for arm in arms if arm and arm.strip()]
    docs = {doc.strip() for doc in doc_ids if doc and doc.strip()}

    if not cases:
        result.errors.append("no eligible test cases")

    question_ids = [case.id for case in cases]
    duplicates = sorted({qid for qid in question_ids if question_ids.count(qid) > 1})
    if duplicates:
        result.errors.append(f"duplicate question ids: {', '.join(duplicates)}")

    for case in cases:
        decision = assess_test_case(case)
        if not decision.eligible:
            reasons = ", ".join(decision.reasons)
            result.errors.append(f"question {case.id} is not eligible: {reasons}")
        for fact in case.atomic_gold_facts:
            # Type-E 的拒答真值可刻意使用 synthetic source_law=\"None\"；
            # 它不代表某一份待召回法規，不應被文件範圍檢查誤擋。
            if case.scenario_type == ScenarioType.TYPE_E or fact.source_law == "None":
                continue
            if fact.source_law and fact.source_law not in docs:
                result.errors.append(
                    f"question {case.id} source law is outside doc_ids: {fact.source_law}"
                )

    if not arm_list:
        result.errors.append("arms must not be empty")
    unsupported = sorted(set(arm_list) - SUPPORTED_ARMS)
    for arm in unsupported:
        result.errors.append(f"unsupported arm: {arm}")

    if not docs:
        result.errors.append("doc_ids must not be empty")

    if not generator_provider or not generator_model:
        result.errors.append("generator provider and model are required")
    if not judge_provider or not judge_model:
        result.errors.append("judge provider and model are required")

    same_judge = (
        generator_provider == judge_provider
        and generator_model == judge_model
    )
    if same_judge and allow_shared_judge:
        result.warnings.append(
            "shared generator/judge configuration: pilot only, not formal evaluation"
        )
    elif same_judge:
        result.errors.append(
            "independent judge required: generator and judge provider/model are identical"
        )

    if not dataset_sha256 or not _SHA256_PATTERN.fullmatch(dataset_sha256):
        result.errors.append("dataset_sha256 must be a 64-character hexadecimal digest")

    if query_timeout_s <= 0:
        result.errors.append("query_timeout_s must be greater than zero")

    return result
