"""自適應檢索行為樹服務（Adaptive Retrieval Behavior Tree，SDD-4.2 交付物）。

對應論文 §3.2 §d：
實現以問題場景驅動的動態排程器，使系統在延遲、成本與高難度推理上同時達到 Pareto 最優：
1. GuardNode：安全邊界與拒答守衛（Type-E 早退）。
2. ClassifierNode：特徵識別與梯度分流。
3. TextBranch：Type-A/B 路由至 M2 Hybrid Text，保證極低延遲與上下文流暢性。
4. GraphBranch：Type-C/D 路由至 M4 Full KG，提供實體對齊、BFS 拓撲與條號級血統。
5. FallbackAction：當 TextBranch 檢索信心不足時，自適應升級至 M4 補足關聯事實。
6. PostGroundingGuard：確定性接地守衛檢核。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from models.eval_schema import ScenarioType
from services.deterministic_guard_service import DeterministicGuardService
from services.query_classifier import QueryClassifier
from services.refusal_guard import RefusalGuard


class AdaptiveExecutionTrace(BaseModel):
    """行為樹走訪軌跡記錄"""
    scenario: ScenarioType
    selected_arm: str
    fallback_triggered: bool = False
    nodes_visited: List[str] = Field(default_factory=list)
    decision_latency_ms: float = 0.0
    final_output: str
    grounding_valid: bool = True
    guard_name: Optional[str] = None


class AdaptiveRetrievalService:
    """自適應檢索排程行為樹"""

    # 檢索置信度門檻（RRF 分數或相似度）
    CONFIDENCE_THRESHOLD = 0.35

    @classmethod
    def schedule_and_route(
        cls,
        question: str,
        retrieval_fn_m2: Any,
        retrieval_fn_m4: Any,
        generator_fn: Any,
    ) -> AdaptiveExecutionTrace:
        """依行為樹邏輯執行動態排程、自適應回補與確定性檢驗"""
        t0 = time.perf_counter()
        trace_nodes: List[str] = []

        # ── 節點 1: GuardNode（檢索前：超出領域/惡意模式早退）──────────
        trace_nodes.append("GuardNode:CheckBoundary")
        ood_dec = RefusalGuard.check_out_of_domain(question)
        if ood_dec.should_refuse:
            trace_nodes.append("GuardNode:DirectRefusal")
            latency_ms = (time.perf_counter() - t0) * 1000
            return AdaptiveExecutionTrace(
                scenario=ScenarioType.TYPE_E,
                selected_arm="REFUSE",
                fallback_triggered=False,
                nodes_visited=trace_nodes,
                decision_latency_ms=round(latency_ms, 2),
                final_output=ood_dec.standard_refusal_answer or "未記載相關規定。",
                grounding_valid=True,
            )

        # ── 節點 2: ClassifierNode（場景特徵識別）───────────────────────
        trace_nodes.append("ClassifierNode:FeatureExtraction")
        cls_result = QueryClassifier.classify(question)
        scenario = cls_result.scenario
        trace_nodes.append(f"ClassifierNode:ScenarioDetermined({scenario.value})")

        selected_arm = cls_result.recommended_arm
        fallback_triggered = False
        context_lines: List[str] = []
        allowed_articles: List[str] = []

        # ── 節點 3 & 4: 分流與自適應回補 ────────────────────────────────
        if scenario in (ScenarioType.TYPE_A, ScenarioType.TYPE_B):
            trace_nodes.append("Selector:TextBranch(M2)")
            # 嘗試調度 M2
            m2_res = retrieval_fn_m2(question)
            confidence = m2_res.get("confidence", 1.0)
            context_lines = m2_res.get("context_lines", [])
            allowed_articles = m2_res.get("articles", [])

            # 置信度檢查（若未撈到有效條文或信心低於門檻，自適應回補）
            if not context_lines or confidence < cls.CONFIDENCE_THRESHOLD:
                trace_nodes.append("Action:AdaptiveFallbackToM4")
                fallback_triggered = True
                selected_arm = "M4"
                m4_res = retrieval_fn_m4(question)
                context_lines = m4_res.get("context_lines", [])
                allowed_articles = m4_res.get("articles", [])
            else:
                trace_nodes.append("ConfidenceCheck:PASS")
        else:
            # Type-C / Type-D 走 M4 Full KG
            trace_nodes.append("Selector:GraphBranch(M4)")
            m4_res = retrieval_fn_m4(question)
            context_lines = m4_res.get("context_lines", [])
            allowed_articles = m4_res.get("articles", [])

        # 若最終檢索仍為空，觸發零召回拒答
        if not context_lines:
            trace_nodes.append("GuardNode:ZeroRetrievalRefusal")
            zero_dec = RefusalGuard.check_zero_retrieval(question, retrieved_fact_count=0, top_similarity=0.0)
            latency_ms = (time.perf_counter() - t0) * 1000
            return AdaptiveExecutionTrace(
                scenario=scenario,
                selected_arm=selected_arm,
                fallback_triggered=fallback_triggered,
                nodes_visited=trace_nodes,
                decision_latency_ms=round(latency_ms, 2),
                final_output=zero_dec.standard_refusal_answer or "法規未記載相關規定。",
                grounding_valid=True,
            )

        # ── 節點 5: 生成回答 ───────────────────────────────────────────
        trace_nodes.append("Generator:GenerateDraft")
        draft_answer = generator_fn(context_lines=context_lines, question=question)

        # ── 節點 6: 確定性接地守衛覆核 ─────────────────────────────────
        trace_nodes.append("GuardNode:DeterministicGroundingCheck")
        full_context = "\n".join(context_lines)
        guard_res = DeterministicGuardService.verify_draft(
            context_text=full_context,
            fact_lines=context_lines,
            question=question,
            draft_answer=draft_answer,
            allowed_articles=allowed_articles,
        )

        final_output = draft_answer
        if not guard_res.is_valid:
            trace_nodes.append(f"GuardNode:Triggered({guard_res.guard_name})")
            # 注入確定性約束重生成
            if guard_res.extra_constrained_note:
                trace_nodes.append("Action:FactoredConstrainedRegeneration")
                final_output = generator_fn(
                    context_lines=context_lines,
                    question=question,
                    extra_note=guard_res.extra_constrained_note,
                )
        else:
            trace_nodes.append("GuardNode:PASS")

        latency_ms = (time.perf_counter() - t0) * 1000

        return AdaptiveExecutionTrace(
            scenario=scenario,
            selected_arm=selected_arm,
            fallback_triggered=fallback_triggered,
            nodes_visited=trace_nodes,
            decision_latency_ms=round(latency_ms, 2),
            final_output=final_output,
            grounding_valid=guard_res.is_valid,
            guard_name=guard_res.guard_name,
        )
