"""三階段全生命週期成本分析器（Cost Analyzer，SDD-2.2 交付物）。

對應論文 §5.5.2「三階段生命週期成本矩陣」：
1. 階段一：離線建庫期（Build Phase）
   - 索引/建圖總耗時 (Total Ingestion Time)
   - 存儲膨脹比 (Storage Footprint Multiplier: DB Size / Raw Size)
   - 初始算力與 Token 消耗
2. 階段二：持續維護與增量更新期（Maintenance Phase）
   - 單篇法規修訂更新耗時 (Delta Update Latency)
   - 圖譜一致性維護成本
3. 階段三：線上服務期（Serving Phase）
   - 端到端延遲 (Latency p50 / p95)
   - 單題 Token 消耗 (Tokens per Query)
   - 每次查詢預估成本
"""
from __future__ import annotations

import statistics
from typing import Dict, List, Any
from pydantic import BaseModel, Field


class BuildCost(BaseModel):
    """階段一：建庫成本"""
    total_ingestion_time_hours: float = Field(description="建庫總耗時（小時）")
    storage_footprint_mb: float = Field(description="儲存體積（MB）")
    raw_text_mb: float = Field(description="原始文字體積（MB）")
    storage_multiplier: float = Field(description="膨脹比 (storage / raw)")
    total_build_tokens: int = Field(default=0, description="初始建庫消耗總 Token 數")


class MaintenanceCost(BaseModel):
    """階段二：持續維護增量成本"""
    delta_update_latency_sec: float = Field(description="單篇法規更新耗時（秒）")
    graph_update_ops: int = Field(default=0, description="圖譜實體與關係變更次數")


class ServingCost(BaseModel):
    """階段三：線上服務成本"""
    arm: str
    query_count: int
    latency_p50_ms: float
    latency_p95_ms: float
    avg_tokens_per_query: float
    estimated_cost_per_1k_queries_usd: float = Field(description="每千次查詢成本估算（USD）")


class LifeCycleCostReport(BaseModel):
    """三階段全生命週期成本報告"""
    arm: str
    build_cost: BuildCost
    maintenance_cost: MaintenanceCost
    serving_cost: ServingCost


class CostAnalyzer:
    """全生命週期成本計算與彙總器"""

    # 參考定價基準（以 Qwen2.5-7B 或同級模型推論與 Embedding 算力估算）
    INPUT_TOKEN_PRICE_PER_M = 0.20   # $0.20 / 1M input tokens
    OUTPUT_TOKEN_PRICE_PER_M = 0.60  # $0.60 / 1M output tokens

    @classmethod
    def compute_serving_cost(
        cls,
        arm: str,
        latencies_ms: List[float],
        tokens_list: List[int],
    ) -> ServingCost:
        """計算線上服務期之延遲分位數與 Token 成本"""
        if not latencies_ms:
            return ServingCost(
                arm=arm,
                query_count=0,
                latency_p50_ms=0.0,
                latency_p95_ms=0.0,
                avg_tokens_per_query=0.0,
                estimated_cost_per_1k_queries_usd=0.0,
            )

        sorted_lat = sorted(latencies_ms)
        n = len(sorted_lat)
        p50 = sorted_lat[int(n * 0.50)]
        p95 = sorted_lat[min(int(n * 0.95), n - 1)]

        avg_tokens = statistics.mean(tokens_list) if tokens_list else 0.0
        # 估算千次查詢成本：假設 80% input, 20% output
        cost_per_query = (
            (avg_tokens * 0.8 / 1_000_000) * cls.INPUT_TOKEN_PRICE_PER_M +
            (avg_tokens * 0.2 / 1_000_000) * cls.OUTPUT_TOKEN_PRICE_PER_M
        )
        cost_per_1k = cost_per_query * 1000

        return ServingCost(
            arm=arm,
            query_count=n,
            latency_p50_ms=round(p50, 2),
            latency_p95_ms=round(p95, 2),
            avg_tokens_per_query=round(avg_tokens, 1),
            estimated_cost_per_1k_queries_usd=round(cost_per_1k, 4),
        )

    @classmethod
    def get_baseline_profile(cls, arm: str) -> LifeCycleCostReport:
        """⚠️ **入庫時審查發現（2026-09-14）**：本函式回傳的延遲/儲存/成本數字皆為
        **寫死的估計值**，不是程式即時載入或計算出的實測數據——docstring 原文「依據
        …實測數據建立」與實際實作不符，容易被誤認為真實量測結果。除了
        `total_ingestion_time_hours` 的建庫耗時粗略對應 KG#4 全量重抽實測（~96 小時，
        `docs/報告/42_...md`），其餘欄位（各 arm 的 p50/p95 延遲、儲存膨脹比、單題
        Token 數、每千次查詢成本）皆為工程估計，**未經任何實際跑測驗證**。使用本函式
        產出的數字前，務必先用真實 `run_rq1_comparison.py` 跑測結果覆蓋，不可直接引用
        本函式的輸出當成論文第五章 §5.5.2 的實測成本數據。
        """
        raw_size_mb = 1.63  # baseline_rag_index 約 1.7 MB

        if arm in ("M1", "B0"):
            # 純 Chunk Embedding：離線建庫極快（分鐘級）、存儲膨脹極小
            build = BuildCost(
                total_ingestion_time_hours=0.05,
                storage_footprint_mb=2.5,
                raw_text_mb=raw_size_mb,
                storage_multiplier=1.53,
                total_build_tokens=500_000,
            )
            maint = MaintenanceCost(delta_update_latency_sec=0.2, graph_update_ops=0)
            serving = ServingCost(
                arm=arm,
                query_count=0,
                latency_p50_ms=180.0,
                latency_p95_ms=350.0,
                avg_tokens_per_query=1200.0,
                estimated_cost_per_1k_queries_usd=0.336,
            )
        elif arm in ("M2", "B1"):
            # Hybrid Text (BM25 + Dense + Rerank)
            build = BuildCost(
                total_ingestion_time_hours=0.08,
                storage_footprint_mb=3.8,
                raw_text_mb=raw_size_mb,
                storage_multiplier=2.33,
                total_build_tokens=500_000,
            )
            maint = MaintenanceCost(delta_update_latency_sec=0.4, graph_update_ops=0)
            serving = ServingCost(
                arm=arm,
                query_count=0,
                latency_p50_ms=280.0,
                latency_p95_ms=520.0,
                avg_tokens_per_query=1200.0,
                estimated_cost_per_1k_queries_usd=0.336,
            )
        elif arm in ("M3", "F"):
            # Fact Vector
            build = BuildCost(
                total_ingestion_time_hours=96.0,  # 約4天 SVO 抽取
                storage_footprint_mb=18.5,
                raw_text_mb=raw_size_mb,
                storage_multiplier=11.35,
                total_build_tokens=4_500_000,
            )
            maint = MaintenanceCost(delta_update_latency_sec=15.0, graph_update_ops=35)
            serving = ServingCost(
                arm=arm,
                query_count=0,
                latency_p50_ms=450.0,
                latency_p95_ms=900.0,
                avg_tokens_per_query=650.0,  # Fact Context 壓縮比 Chunk 短
                estimated_cost_per_1k_queries_usd=0.182,
            )
        else:  # M4, K, Full KG
            # Full KG with BFS and Lineage
            build = BuildCost(
                total_ingestion_time_hours=96.0,  # 約4天抽取＋實體對齊
                storage_footprint_mb=42.0,       # Neo4j 拓撲節點＋關係邊
                raw_text_mb=raw_size_mb,
                storage_multiplier=25.77,
                total_build_tokens=4_500_000,
            )
            maint = MaintenanceCost(delta_update_latency_sec=30.0, graph_update_ops=120)
            serving = ServingCost(
                arm=arm,
                query_count=0,
                latency_p50_ms=850.0,
                latency_p95_ms=2100.0,
                avg_tokens_per_query=750.0,
                estimated_cost_per_1k_queries_usd=0.210,
            )

        return LifeCycleCostReport(
            arm=arm,
            build_cost=build,
            maintenance_cost=maint,
            serving_cost=serving,
        )
