"""確定性原子評分器（Deterministic Atomic Fact Scorer，SDD-2.2 交付物）。

以客觀程式邏輯比對答案是否精確符合中華民國原始法規 exact_span，
徹底取代純 LLM Judge 寬鬆判定，杜絕語意平滑化（如把「當月一日」視同「當日」）。
"""
from __future__ import annotations

import re
from typing import List, Tuple
from pydantic import BaseModel, Field

from core.providers.base import LLMProvider
from models.eval_schema import AtomicGoldFact
from services.semantic_span_matcher import match_spans_with_fallback


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
        trap_claim_spans: List[str] | None = None,
        extra_refusal_patterns: List[str] | None = None,
    ) -> AtomicScoreResult:
        """評估答案對原子黃金事實之符合程度。

        `deterministic_guard_passed`／`guard_failures`（報告48 §4.1）：呼叫端
        （`scripts/eval/run_rq1_comparison.py`）在拿到最終答案後先跑
        `DeterministicGuardService`，把結果傳進來——guard 未通過時
        `is_perfect` 強制為 False，但 `atomic_accuracy`／`atomic_recall`／
        `supported_spans` 仍如實反映原始 exact-span coverage，不用任意常數
        偷偷扣分（見報告48 §4.1「保留原始 atomic coverage，另外記錄 guard
        failure」）。

        `trap_claim_spans`（報告57 §4.3，2026-09-16新增，選填）：僅
        `refusal_expected=True`時生效。真實資料發現：拒答關鍵字比對原本掃描
        答案「全文任一處」，若多段式答案在核心主張上確信斷言了錯誤結論（陷阱），
        卻在文字別處（例如次要子問題）夾帶一句無關的拒答用語，會被誤判成整題
        拒答成功（57-CANARY3實例：模型確信答錯「精密作業需要特殊健康檢查」，
        但因結尾夾帶「其他部分資料未明確記載，無法確認」而被誤判100%通過）。
        `trap_claim_spans`非空且答案命中其中任一則字串時，強制`refused=False`
        （即使拒答關鍵字也命中）——刻意維持純字串比對，不改用LLM judge：
        RefusalBench（Muhamed et al. 2025）已實測Qwen家族選擇性拒答判斷準確率
        全尺寸<17%，與`services/interval_lookup_service.py`既有G2方案E（查表
        判斷移出LLM改確定性Python檢查）同一設計原則。"""
        if refusal_expected:
            # 若為 Type-E Canary 題目，檢核是否明確觸發法定拒答
            refusal_patterns = [
                "未記載", "無法確認", "無相關規定", "資料未提及", "查無相關", "未能提供",
                "並未記載", "沒有提到", "無法提供確定答覆"
            ]
            # 事後重算專用（報告57 §4.20）：預設為空，不改變任何既有評分結果。
            refusal_patterns = refusal_patterns + list(extra_refusal_patterns or [])
            clean_ans = cls._clean_text(answer)
            refused = any(p in clean_ans for p in refusal_patterns)
            trap_triggered = any(
                cls._clean_text(trap) in clean_ans for trap in (trap_claim_spans or []) if trap
            )
            if trap_triggered:
                refused = False
            return AtomicScoreResult(
                supported_spans=["REFUSAL"] if refused else [],
                missing_spans=[] if refused else ["REFUSAL_EXPECTED"],
                atomic_accuracy=1.0 if refused else 0.0,
                atomic_recall=1.0 if refused else 0.0,
                is_perfect=refused and deterministic_guard_passed,
                details=(
                    "Failed to Refuse on Type-E Canary (Trap Claim Asserted)" if trap_triggered
                    else "Exact Refusal Passed" if refused
                    else "Failed to Refuse on Type-E Canary"
                ),
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

    @classmethod
    async def evaluate_async(
        cls,
        answer: str,
        atomic_gold_facts: List[AtomicGoldFact],
        refusal_expected: bool = False,
        judge_llm_provider: LLMProvider | None = None,
        question: str = "",
        deterministic_guard_passed: bool = True,
        guard_failures: List[str] | None = None,
        trap_claim_spans: List[str] | None = None,
    ) -> AtomicScoreResult:
        """語意 fallback 版（報告52 後續修正）：`exact_span` 逐字比對失敗時，
        才補呼叫 `judge_llm_provider` 做語意蘊含核對（見
        `services/semantic_span_matcher.py`），救回報告24自然語言化管線改寫過
        用詞、但內容其實正確的答案（如 17-Q1 案例）。`deterministic_guard_passed`／
        `guard_failures` 意義與 `evaluate()` 相同（報告48 §4.1），兩者是獨立的
        修正維度——guard 檢核確定性法律關鍵詞是否被竄改，語意 fallback 只處理
        exact_span 逐字比對的假陰性，互不覆寫。

        `refusal_expected=True` 或 `atomic_gold_facts` 為空的分支與同步版
        `evaluate()` 完全相同（純規則判定，不涉及語意比對，不需 judge LLM）。
        `judge_llm_provider=None` 時退化為與 `evaluate()` 逐字相同的結果。
        `trap_claim_spans`（報告57 §4.3）原樣轉交`evaluate()`。
        """
        if refusal_expected or not atomic_gold_facts:
            return cls.evaluate(
                answer, atomic_gold_facts, refusal_expected=refusal_expected,
                deterministic_guard_passed=deterministic_guard_passed,
                guard_failures=guard_failures,
                trap_claim_spans=trap_claim_spans,
            )

        spans = [f.exact_span for f in atomic_gold_facts]
        hit_spans, _ = await match_spans_with_fallback(
            answer, spans, judge_llm_provider, question=question,
        )
        hit_set = set(hit_spans)

        essential_facts = [f for f in atomic_gold_facts if f.is_essential]
        total_essential = len(essential_facts) if essential_facts else len(atomic_gold_facts)

        supported = [f.exact_span for f in atomic_gold_facts if f.exact_span in hit_set]
        missing = [
            f.exact_span for f in atomic_gold_facts
            if f.exact_span not in hit_set and f.is_essential
        ]
        hit_essential = len([f for f in essential_facts if f.exact_span in hit_set])
        recall = (hit_essential / total_essential) if total_essential > 0 else 1.0
        accuracy = len(supported) / len(atomic_gold_facts) if atomic_gold_facts else 1.0
        is_perfect = (
            len(missing) == 0
            and len(supported) >= total_essential
            and deterministic_guard_passed
        )

        detail_msg = (
            f"Hit {len(supported)}/{len(atomic_gold_facts)} facts "
            f"(semantic fallback{'' if judge_llm_provider else ' disabled'}). "
            f"Missed essential: {missing}"
        )
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
