"""正式評測題目資格檢查。

正式分數只能使用已回到原始法規核驗的題目。排除理由會保留給 manifest，
避免把題目靜默丟掉後誤解樣本數或分數。
"""
from __future__ import annotations

from dataclasses import dataclass

from models.eval_schema import ScenarioType, TestCase, VerificationStatus


@dataclass(frozen=True)
class EligibilityDecision:
    eligible: bool
    reasons: tuple[str, ...] = ()


def assess_test_case(test_case: TestCase) -> EligibilityDecision:
    """回傳題目是否可納入正式 scorer，以及可追溯的排除原因。"""
    reasons: list[str] = []

    if test_case.verification_status != VerificationStatus.VERIFIED:
        reasons.append(f"verification_status={test_case.verification_status.value}")

    if "[待核]" in test_case.gold_answer:
        reasons.append("gold_answer_contains_pending_marker")

    if test_case.wording_status == "gist":
        reasons.append("wording_status=gist_without_verbatim_recheck")

    # Type-E 是拒答題，真值是 refusal policy；一般法律題則必須有
    # 至少一個已核驗 atomic fact，避免空 gold 走 scorer 的 perfect fallback。
    if test_case.scenario_type != ScenarioType.TYPE_E and not test_case.atomic_gold_facts:
        reasons.append("missing_atomic_gold_facts")

    return EligibilityDecision(eligible=not reasons, reasons=tuple(reasons))


def split_eligible_test_cases(
    test_cases: list[TestCase],
) -> tuple[list[TestCase], list[dict[str, object]]]:
    """分離可評測題目與排除清單；保留題目順序。"""
    eligible: list[TestCase] = []
    excluded: list[dict[str, object]] = []
    for test_case in test_cases:
        decision = assess_test_case(test_case)
        if decision.eligible:
            eligible.append(test_case)
        else:
            excluded.append({"question_id": test_case.id, "reasons": list(decision.reasons)})
    return eligible, excluded

