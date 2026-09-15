"""確定性原子評分器（Deterministic Atomic Fact Scorer，SDD-2.2 交付物）。

以客觀程式邏輯比對答案是否精確符合中華民國原始法規 exact_span，
徹底取代純 LLM Judge 寬鬆判定，杜絕語意平滑化（如把「當月一日」視同「當日」）。
"""
from __future__ import annotations

import re
from typing import List, Tuple
from pydantic import BaseModel, Field

from models.eval_schema import AtomicGoldFact


class AtomicScoreResult(BaseModel):
    """單題原子事實評分結果"""
    supported_spans: List[str] = Field(default_factory=list, description="命中之 exact_span")
    missing_spans: List[str] = Field(default_factory=list, description="遺漏之必要 exact_span")
    atomic_accuracy: float = Field(default=0.0, description="原子精確率")
    atomic_recall: float = Field(default=0.0, description="必要原子事實召回率")
    is_perfect: bool = Field(default=False, description="是否全數精確命中")
    details: str = Field(default="", description="詳細比對報告")
    deterministic_guard_passed: bool = Field(default=True, description="確定性法律守衛是否通過")
    guard_failures: List[str] = Field(default_factory=list, description="確定性守衛失敗原因")


class AtomicScorer:
    """法規原子真值精確比對器"""

    @staticmethod
    def _clean_text(text: str) -> str:
        """去除空格、換行、特定標點符號以進行標準化字串包含比對"""
        if not text:
            return ""
        # 移除非字母數字與中文字元以外的干擾符號
        cleaned = re.sub(r"[\s\n\r\t，。、；：：「」『』\"\'\(\)（）]", "", text)
        return cleaned

    @classmethod
    def evaluate(
        cls,
        answer: str,
        atomic_gold_facts: List[AtomicGoldFact],
        refusal_expected: bool = False,
        deterministic_guard_passed: bool = True,
        guard_failures: List[str] | None = None,
    ) -> AtomicScoreResult:
        """評估答案對原子黃金事實之符合程度"""
        if refusal_expected:
            # 若為 Type-E Canary 題目，檢核是否明確觸發法定拒答
            refusal_patterns = [
                "未記載", "無法確認", "無相關規定", "資料未提及", "查無相關", "未能提供",
                "並未記載", "沒有提到", "無法提供確定答覆"
            ]
            clean_ans = cls._clean_text(answer)
            refused = any(p in clean_ans for p in refusal_patterns)
            return AtomicScoreResult(
                supported_spans=["REFUSAL"] if refused else [],
                missing_spans=[] if refused else ["REFUSAL_EXPECTED"],
                atomic_accuracy=1.0 if refused else 0.0,
                atomic_recall=1.0 if refused else 0.0,
                is_perfect=refused and deterministic_guard_passed,
                details="Exact Refusal Passed" if refused else "Failed to Refuse on Type-E Canary",
                deterministic_guard_passed=deterministic_guard_passed,
                guard_failures=guard_failures or [],
            )

        if not atomic_gold_facts:
            return AtomicScoreResult(
                atomic_accuracy=1.0,
                atomic_recall=1.0,
                is_perfect=deterministic_guard_passed,
                details="No atomic gold facts defined (Unverified / Baseline).",
                deterministic_guard_passed=deterministic_guard_passed,
                guard_failures=guard_failures or [],
            )

        clean_answer = cls._clean_text(answer)
        supported: List[str] = []
        missing: List[str] = []

        essential_facts = [f for f in atomic_gold_facts if f.is_essential]
        total_essential = len(essential_facts) if essential_facts else len(atomic_gold_facts)

        for fact in atomic_gold_facts:
            clean_span = cls._clean_text(fact.exact_span)
            if clean_span in clean_answer:
                supported.append(fact.exact_span)
            else:
                if fact.is_essential:
                    missing.append(fact.exact_span)

        hit_essential = len([s for s in supported if any(s == f.exact_span and f.is_essential for f in atomic_gold_facts)])
        recall = (hit_essential / total_essential) if total_essential > 0 else 1.0

        # 精確率：命中事實數 vs 答案中陳述之事實（以 Gold Facts 總數為分母估計）
        accuracy = len(supported) / len(atomic_gold_facts) if atomic_gold_facts else 1.0
        is_perfect = (
            len(missing) == 0
            and len(supported) >= total_essential
            and deterministic_guard_passed
        )

        detail_msg = f"Hit {len(supported)}/{len(atomic_gold_facts)} facts. Missed essential: {missing}"
        if guard_failures:
            detail_msg += f" Guard failures: {guard_failures}"

        return AtomicScoreResult(
            supported_spans=supported,
            missing_spans=missing,
            atomic_accuracy=round(accuracy, 4),
            atomic_recall=round(recall, 4),
            is_perfect=is_perfect,
            details=detail_msg,
            deterministic_guard_passed=deterministic_guard_passed,
            guard_failures=guard_failures or [],
        )
