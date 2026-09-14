"""單元測試：原子評分器與成本分析器（SDD-2.2）。

驗證：
1. 26-Q5 的起算日「自災害發生之當月一日起計算六個月」比對（平滑化為「當日」會精確被抓到並扣分）。
2. Type-E Canary 題目拒答核驗。
3. 成本分析器之 p50/p95 與三階段生命週期報告產出。
"""
import pytest
from models.eval_schema import AtomicGoldFact
from services.atomic_scorer import AtomicScorer
from services.cost_analyzer import CostAnalyzer


def test_atomic_scorer_exact_match():
    facts = [
        AtomicGoldFact(
            exact_span="自災害發生之當月一日起計算六個月",
            source_law="N0050030",
            source_article="第3條",
            is_essential=True,
        ),
        AtomicGoldFact(
            exact_span="災後六個月期間內被保險人應負擔之保險費，由中央政府支應",
            source_law="N0050030",
            source_article="第2條",
            is_essential=True,
        ),
    ]

    # 正確答案（完全逐字包含 exact_span）
    correct_ans = (
        "依據規定，災後六個月期間內被保險人應負擔之保險費，由中央政府支應。"
        "其期間之計算，自災害發生之當月一日起計算六個月。"
    )
    res = AtomicScorer.evaluate(correct_ans, facts)
    assert res.is_perfect is True
    assert res.atomic_accuracy == 1.0
    assert res.atomic_recall == 1.0
    assert len(res.missing_spans) == 0


def test_atomic_scorer_catches_smoothing():
    """驗證平滑化缺陷（把「當月一日」改寫成「當日」）會被精確判定未命中"""
    facts = [
        AtomicGoldFact(
            exact_span="自災害發生之當月一日起計算六個月",
            source_law="N0050030",
            source_article="第3條",
            is_essential=True,
        ),
        AtomicGoldFact(
            exact_span="由中央政府支應",
            source_law="N0050030",
            source_article="第2條",
            is_essential=True,
        ),
    ]

    # 平滑化答案（當月一日 -> 當日）
    smoothed_ans = (
        "災後六個月期間由中央政府支應，其期間自災害發生之當日起計算六個月。"
    )
    res = AtomicScorer.evaluate(smoothed_ans, facts)
    assert res.is_perfect is False
    assert "自災害發生之當月一日起計算六個月" in res.missing_spans
    assert res.atomic_recall == 0.5


def test_atomic_scorer_canary_refusal():
    # Type-E Canary 題目拒答測試
    refusal_ans = "依據目前收錄之勞動法規資料庫，並未記載此項規定，無法提供確定答覆。"
    res1 = AtomicScorer.evaluate(refusal_ans, [], refusal_expected=True)
    assert res1.is_perfect is True
    assert res1.atomic_accuracy == 1.0

    # 猜測答案（未拒答）
    guessed_ans = "依規定最高可處新臺幣十億元罰鍰。"
    res2 = AtomicScorer.evaluate(guessed_ans, [], refusal_expected=True)
    assert res2.is_perfect is False
    assert res2.atomic_accuracy == 0.0


def test_cost_analyzer_profiles():
    # 測試 M1 與 M4 的生命週期報告
    m1_report = CostAnalyzer.get_baseline_profile("M1")
    m4_report = CostAnalyzer.get_baseline_profile("M4")

    # M1 建庫時間遠小於 M4
    assert m1_report.build_cost.total_ingestion_time_hours < 1.0
    assert m4_report.build_cost.total_ingestion_time_hours > 50.0

    # M1 膨脹比遠小於 M4
    assert m1_report.build_cost.storage_multiplier < m4_report.build_cost.storage_multiplier

    # 線上延遲計算
    latencies = [100.0, 150.0, 200.0, 250.0, 300.0, 350.0, 400.0, 500.0, 800.0, 1200.0]
    tokens = [500] * 10
    serving = CostAnalyzer.compute_serving_cost("M1", latencies, tokens)
    assert serving.latency_p50_ms == 350.0
    assert serving.latency_p95_ms == 1200.0
    assert serving.estimated_cost_per_1k_queries_usd > 0.0
