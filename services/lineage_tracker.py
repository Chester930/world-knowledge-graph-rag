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

from models.eval_schema import (
    ContextAssemblyLineage,
    FullQueryLineage,
    GenerationStageLineage,
    RetrievalStageLineage,
)


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
    ) -> RetrievalStageLineage:
        """記錄階段一檢索召回結果並判定 Gold Fact 覆蓋率"""
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

        self._retrieval = RetrievalStageLineage(
            arm=self.arm,
            retrieval_latency_ms=latency_ms,
            retrieved_chunk_ids=chunk_ids or [],
            retrieved_fact_ids=fact_ids or [],
            hit_exact_spans=hit_spans,
            missed_exact_spans=missed_spans,
            recall_rate=round(recall, 4),
        )
        return self._retrieval

    def record_context_assembly(
        self,
        final_prompt_context: str,
        gold_spans: List[str],
        total_tokens: int = 0,
    ) -> ContextAssemblyLineage:
        """記錄階段二 Context 組裝（重排/截斷）後 Gold Fact 是否仍存活"""
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

    def export_to_file(self, gold_spans: List[str], file_path: Path | str) -> None:
        """將完整血統 JSON 寫入磁碟"""
        record = self.build_full_lineage(gold_spans)
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record.model_dump(), f, ensure_ascii=False, indent=2)
