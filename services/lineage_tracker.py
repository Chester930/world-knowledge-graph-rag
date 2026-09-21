"""全鏈路血統追蹤器（Lineage Tracker，SDD-1.3 交付物）。

提供檢索、組裝與生成三階段因果隔離診斷：
- 階段一（Retrieval）：是否召回原始法規 Gold Exact Spans。
- 階段二（Assembly）：排序/截斷/自然語言化後，Gold Exact Spans 是否仍保留在 Prompt 中。
- 階段三（Generation）：LLM 是否忠實引用，或發生語意平滑化（如「當月一日」改寫為「當日」）與內在幻覺。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from core.providers.base import LLMProvider
from models.eval_schema import (
    AtomicGoldFact,
    ContextAssemblyLineage,
    FullQueryLineage,
    GenerationStageLineage,
    RetrievalStageLineage,
    RetrievedEvidence,
)
from services.semantic_span_matcher import match_spans_with_fallback


def _compute_snr(hit_spans: List[str], retrieved_char_count: int) -> float:
    """報告57 §2.2：Signal/Noise Ratio = Σlen(hit_exact_span) / retrieved_char_count。
    以清除空白/換行後的字元數計算，與既有逐字比對的清理慣例一致。夾在
    [0,1] 內（命中片段重疊等邊界情況下分子可能略超過分母，裁掉避免
    產生不可解讀的比率）。"""
    if retrieved_char_count <= 0:
        return 0.0
    signal_chars = sum(len(span.replace(" ", "").replace("\n", "")) for span in hit_spans)
    return round(min(signal_chars / retrieved_char_count, 1.0), 4)


def _compute_chain_completeness(
    atomic_gold_facts: Optional[List[AtomicGoldFact]],
    hit_spans: List[str],
) -> Optional[float]:
    """報告57 §2.2：跨文件推論鏈完整度 = 命中≥1個essential fact的distinct
    source_law數 / 所需distinct source_law總數。題目只涉及單一
    source_law（或未提供 atomic_gold_facts）時回傳 None（不適用，非0分
    ——單文件題目不該被這個指標懲罰）。Type-E 拒答題慣用的
    synthetic source_law="None"（見 `services/evaluation_eligibility.py`
    同一慣例）不計入分組。"""
    if not atomic_gold_facts:
        return None
    essential = [
        f for f in atomic_gold_facts
        if f.is_essential and f.source_law and f.source_law != "None"
    ]
    required_laws = {f.source_law for f in essential}
    if len(required_laws) < 2:
        return None
    hit_set = set(hit_spans)
    hit_laws = {f.source_law for f in essential if f.exact_span in hit_set}
    return round(len(hit_laws) / len(required_laws), 4)


class LineageTracker:
    """單次問答全鏈路因果血統追蹤器"""

    def __init__(self, query_id: str, arm: str, question: str):
        self.query_id = query_id
        self.arm = arm
        self.question = question
        self._retrieval: Optional[RetrievalStageLineage] = None
        self._context: Optional[ContextAssemblyLineage] = None
        self._generation: Optional[GenerationStageLineage] = None

    def record_retrieval(
        self,
        retrieved_texts: List[str],
        gold_spans: List[str],
        latency_ms: float,
        chunk_ids: Optional[List[str]] = None,
        fact_ids: Optional[List[str]] = None,
        atomic_gold_facts: Optional[List[AtomicGoldFact]] = None,
        retrieval_trace: Optional[List[RetrievedEvidence]] = None,
    ) -> RetrievalStageLineage:
        """記錄階段一檢索召回結果並判定 Gold Fact 覆蓋率。`retrieval_trace`
        （報告62 T0，選填）原樣存進 lineage，不參與任何判定。`atomic_gold_facts`
        （報告57 §2.2 新增，選填）帶 source_law 分組資訊時才計算
        `chain_completeness`；未傳入（既有呼叫端）時該欄位維持 None，
        零行為變化。"""
        combined_text = "".join(retrieved_texts).replace(" ", "").replace("\n", "")
        hit_spans: List[str] = []
        missed_spans: List[str] = []

        for span in gold_spans:
            clean_span = span.replace(" ", "").replace("\n", "")
            if clean_span in combined_text:
                hit_spans.append(span)
            else:
                missed_spans.append(span)

        recall = len(hit_spans) / len(gold_spans) if gold_spans else 1.0
        retrieved_char_count = len(combined_text)

        self._retrieval = RetrievalStageLineage(
            arm=self.arm,
            retrieval_latency_ms=latency_ms,
            retrieved_chunk_ids=chunk_ids or [],
            retrieved_fact_ids=fact_ids or [],
            retrieval_trace=retrieval_trace or [],
            hit_exact_spans=hit_spans,
            missed_exact_spans=missed_spans,
            recall_rate=round(recall, 4),
            retrieved_char_count=retrieved_char_count,
            snr=_compute_snr(hit_spans, retrieved_char_count),
            chain_completeness=_compute_chain_completeness(atomic_gold_facts, hit_spans),
        )
        return self._retrieval

    async def record_retrieval_async(
        self,
        retrieved_texts: List[str],
        gold_spans: List[str],
        latency_ms: float,
        chunk_ids: Optional[List[str]] = None,
        fact_ids: Optional[List[str]] = None,
        judge_llm_provider: Optional[LLMProvider] = None,
        question: str = "",
        atomic_gold_facts: Optional[List[AtomicGoldFact]] = None,
        retrieval_trace: Optional[List[RetrievedEvidence]] = None,
    ) -> RetrievalStageLineage:
        """語意 fallback 版（報告52 後續修正），見 `record_retrieval()` 與
        `services/semantic_span_matcher.py`。逐字比對失敗才補呼叫
        `judge_llm_provider`；`judge_llm_provider=None` 時結果與同步版一致。
        `atomic_gold_facts`（報告57 §2.2 新增，選填）用法同 `record_retrieval()`。"""
        combined_text = "\n".join(retrieved_texts)
        hit_spans, missed_spans = await match_spans_with_fallback(
            combined_text, gold_spans, judge_llm_provider, question=question,
        )
        recall = len(hit_spans) / len(gold_spans) if gold_spans else 1.0
        retrieved_char_count = len(combined_text.replace(" ", "").replace("\n", ""))

        self._retrieval = RetrievalStageLineage(
            arm=self.arm,
            retrieval_latency_ms=latency_ms,
            retrieved_chunk_ids=chunk_ids or [],
            retrieved_fact_ids=fact_ids or [],
            retrieval_trace=retrieval_trace or [],
            hit_exact_spans=hit_spans,
            missed_exact_spans=missed_spans,
            recall_rate=round(recall, 4),
            retrieved_char_count=retrieved_char_count,
            snr=_compute_snr(hit_spans, retrieved_char_count),
            chain_completeness=_compute_chain_completeness(atomic_gold_facts, hit_spans),
        )
        return self._retrieval

    def record_context_assembly(
        self,
        final_prompt_context: str,
        gold_spans: List[str],
        total_tokens: int = 0,
        prompt_context_lines: Optional[List[List[str]]] = None,
    ) -> ContextAssemblyLineage:
        """記錄階段二 Context 組裝（重排/截斷）後 Gold Fact 是否仍存活。
        `prompt_context_lines`（報告62 T0，選填）＝實際組進 prompt 的事實行，
        原樣存入，不參與 retained／dropped 判定（維持與凍結基準同定義）。"""
        clean_context = final_prompt_context.replace(" ", "").replace("\n", "")
        retained: List[str] = []
        dropped: List[str] = []

        for span in gold_spans:
            clean_span = span.replace(" ", "").replace("\n", "")
            if clean_span in clean_context:
                retained.append(span)
            else:
                dropped.append(span)

        self._context = ContextAssemblyLineage(
            total_context_tokens=total_tokens,
            retained_exact_spans=retained,
            dropped_exact_spans=dropped,
            prompt_context_lines=prompt_context_lines or [],
        )
        return self._context

    async def record_context_assembly_async(
        self,
        final_prompt_context: str,
        gold_spans: List[str],
        total_tokens: int = 0,
        judge_llm_provider: Optional[LLMProvider] = None,
        question: str = "",
        prompt_context_lines: Optional[List[List[str]]] = None,
    ) -> ContextAssemblyLineage:
        """語意 fallback 版，見 `record_context_assembly()`。"""
        retained, dropped = await match_spans_with_fallback(
            final_prompt_context, gold_spans, judge_llm_provider, question=question,
        )
        self._context = ContextAssemblyLineage(
            total_context_tokens=total_tokens,
            retained_exact_spans=retained,
            dropped_exact_spans=dropped,
            prompt_context_lines=prompt_context_lines or [],
        )
        return self._context

    def record_generation(
        self,
        raw_draft: str,
        final_output: str,
        grounding_passed: bool,
        latency_ms: float,
        llm_model: str = "qwen2.5:7b",
        deterministic_guard_triggered: bool = False,
        guard_reasons: Optional[List[str]] = None,
        regenerated: bool = False,
        supported_claims: Optional[List[str]] = None,
        unsupported_claims: Optional[List[str]] = None,
    ) -> GenerationStageLineage:
        """記錄階段三生成輸出與守衛介入狀態"""
        self._generation = GenerationStageLineage(
            llm_model=llm_model,
            generation_latency_ms=latency_ms,
            raw_draft=raw_draft,
            grounding_passed=grounding_passed,
            deterministic_guard_triggered=deterministic_guard_triggered,
            guard_reasons=guard_reasons or [],
            regenerated=regenerated,
            final_output=final_output,
            supported_claims=supported_claims or [],
            unsupported_claims=unsupported_claims or [],
        )
        return self._generation

    def diagnose_failure(self, gold_spans: List[str]) -> str:
        """依據三階段因果鏈輸出客觀歸因診斷"""
        if not gold_spans:
            return "No Gold Facts Defined (Verification Not Applicable)"

        # 檢查階段一
        if self._retrieval and self._retrieval.missed_exact_spans:
            return (
                f"Stage 1 Retrieval Failure: "
                f"{len(self._retrieval.missed_exact_spans)}/{len(gold_spans)} gold facts missed "
                f"({self._retrieval.missed_exact_spans})"
            )

        # 檢查階段二
        if self._context and self._context.dropped_exact_spans:
            return (
                f"Stage 2 Assembly Failure: "
                f"{len(self._context.dropped_exact_spans)} gold facts dropped in context assembly "
                f"({self._context.dropped_exact_spans})"
            )

        # 檢查階段三
        if self._generation:
            final_clean = self._generation.final_output.replace(" ", "").replace("\n", "")
            missing_in_answer = [
                span for span in gold_spans
                if span.replace(" ", "").replace("\n", "") not in final_clean
            ]
            if missing_in_answer:
                if self._generation.deterministic_guard_triggered:
                    return (
                        f"Stage 3 Generation Failure (Guard Intercepted): "
                        f"LLM deviated from gold spans {missing_in_answer}; guard triggered."
                    )
                return (
                    f"Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): "
                    f"Facts were present in prompt context, but LLM omitted or smoothed {missing_in_answer}."
                )

        return "Success: All gold spans preserved across all 3 stages."

    async def diagnose_failure_async(
        self,
        gold_spans: List[str],
        judge_llm_provider: Optional[LLMProvider] = None,
        question: str = "",
    ) -> str:
        """語意 fallback 版，見 `diagnose_failure()`。Stage 1/2 沿用
        `self._retrieval`/`self._context` 既有紀錄（呼叫端應已用
        `record_retrieval_async()`/`record_context_assembly_async()` 產生，
        本方法不重跑那兩階段）；只有 Stage 3（最終答案 vs gold span）在此
        補做語意蘊含核對，行為與 `AtomicScorer.evaluate_async()` 一致。"""
        if not gold_spans:
            return "No Gold Facts Defined (Verification Not Applicable)"

        if self._retrieval and self._retrieval.missed_exact_spans:
            return (
                f"Stage 1 Retrieval Failure: "
                f"{len(self._retrieval.missed_exact_spans)}/{len(gold_spans)} gold facts missed "
                f"({self._retrieval.missed_exact_spans})"
            )

        if self._context and self._context.dropped_exact_spans:
            return (
                f"Stage 2 Assembly Failure: "
                f"{len(self._context.dropped_exact_spans)} gold facts dropped in context assembly "
                f"({self._context.dropped_exact_spans})"
            )

        if self._generation:
            _, missing_in_answer = await match_spans_with_fallback(
                self._generation.final_output, gold_spans, judge_llm_provider, question=question,
            )
            if missing_in_answer:
                if self._generation.deterministic_guard_triggered:
                    return (
                        f"Stage 3 Generation Failure (Guard Intercepted): "
                        f"LLM deviated from gold spans {missing_in_answer}; guard triggered."
                    )
                return (
                    f"Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): "
                    f"Facts were present in prompt context, but LLM omitted or smoothed {missing_in_answer}."
                )

        return "Success: All gold spans preserved across all 3 stages."

    def build_full_lineage(self, gold_spans: List[str]) -> FullQueryLineage:
        """構建完整可序列化之血統物件"""
        if not self._retrieval:
            self.record_retrieval([], gold_spans, 0.0)
        if not self._context:
            self.record_context_assembly("", gold_spans, 0)
        if not self._generation:
            self.record_generation("", "", False, 0.0)

        attribution = self.diagnose_failure(gold_spans)

        return FullQueryLineage(
            query_id=self.query_id,
            arm=self.arm,
            question=self.question,
            stage1_retrieval=self._retrieval,
            stage2_context=self._context,
            stage3_generation=self._generation,
            failure_attribution=attribution,
        )

    async def build_full_lineage_async(
        self,
        gold_spans: List[str],
        judge_llm_provider: Optional[LLMProvider] = None,
        question: str = "",
    ) -> FullQueryLineage:
        """語意 fallback 版，見 `build_full_lineage()`。要求呼叫端已先用
        `record_retrieval_async()`/`record_context_assembly()`/
        `record_generation()` 記錄三階段（本方法不補跑缺漏階段，因為缺漏時
        代表呼叫端刻意略過——例如報告52後續修正的離線重評分腳本，K arm 的
        BFS 三元組部分無法重建原文，刻意維持 `record_retrieval()` 同步版的
        舊判定，不應被這裡靜默覆寫成空白重算）。"""
        attribution = await self.diagnose_failure_async(
            gold_spans, judge_llm_provider, question=question,
        )
        return FullQueryLineage(
            query_id=self.query_id,
            arm=self.arm,
            question=self.question,
            stage1_retrieval=self._retrieval,
            stage2_context=self._context,
            stage3_generation=self._generation,
            failure_attribution=attribution,
        )

    def export_to_file(self, gold_spans: List[str], file_path: Path | str) -> None:
        """將完整血統 JSON 寫入磁碟"""
        record = self.build_full_lineage(gold_spans)
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record.model_dump(), f, ensure_ascii=False, indent=2)
