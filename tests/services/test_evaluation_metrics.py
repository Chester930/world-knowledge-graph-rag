"""單元測試：原子評分器與成本分析器（SDD-2.2）。

驗證：
1. 26-Q5 的起算日「自災害發生之當月一日起計算六個月」比對（平滑化為「當日」會精確被抓到並扣分）。
2. Type-E Canary 題目拒答核驗。
3. 成本分析器之 p50/p95 與三階段生命週期報告產出。
"""
import json
import pytest
from models.eval_schema import AtomicGoldFact, ScenarioType, TestCase as EvalTestCase, VerificationStatus
from services.atomic_scorer import AtomicScorer
from services.cost_analyzer import CostAnalyzer
from services.evaluation_eligibility import assess_test_case


class _FakeJudge:
    def __init__(self, response: str):
        self._response = response
        self.calls = 0

    async def generate_json(self, prompt: str) -> str:
        self.calls += 1
        return self._response


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


@pytest.mark.asyncio
async def test_atomic_scorer_evaluate_async_no_judge_matches_sync():
    """報告52後續修正：judge_llm_provider=None 時，evaluate_async 與 evaluate() 逐位元相同"""
    facts = [
        AtomicGoldFact(
            exact_span="自災害發生之當月一日起計算六個月",
            source_law="N0050030", source_article="第3條", is_essential=True,
        ),
    ]
    smoothed_ans = "其期間自災害發生之當日起計算六個月。"
    sync_res = AtomicScorer.evaluate(smoothed_ans, facts)
    async_res = await AtomicScorer.evaluate_async(smoothed_ans, facts, judge_llm_provider=None)
    assert async_res.atomic_recall == sync_res.atomic_recall
    assert async_res.missing_spans == sync_res.missing_spans


@pytest.mark.asyncio
async def test_atomic_scorer_evaluate_async_rescues_paraphrase():
    """17-Q1 情境：答案內容正確但用詞被自然語言化改寫，語意 fallback 應救回"""
    facts = [
        AtomicGoldFact(
            exact_span="勞工結婚者給予婚假八日，工資照給",
            source_law="N0030006", source_article="第2條", is_essential=True,
        ),
    ]
    paraphrased_ans = "勞工結婚可以請八日婚假，婚假期間工資照給，不受影響。"
    judge = _FakeJudge(json.dumps({"results": [{"index": 1, "present": True}]}))

    sync_res = AtomicScorer.evaluate(paraphrased_ans, facts)
    assert sync_res.is_perfect is False  # 逐字比對本來就會誤判失敗

    async_res = await AtomicScorer.evaluate_async(
        paraphrased_ans, facts, judge_llm_provider=judge,
    )
    assert async_res.is_perfect is True
    assert async_res.atomic_recall == 1.0
    assert judge.calls == 1


@pytest.mark.asyncio
async def test_atomic_scorer_evaluate_async_keeps_real_smoothing_error():
    """26-Q5 情境：「當日」平滑化內容確實不同，judge 判 false 時維持失敗判定"""
    facts = [
        AtomicGoldFact(
            exact_span="自災害發生之當月一日起計算六個月",
            source_law="N0050030", source_article="第3條", is_essential=True,
        ),
    ]
    smoothed_ans = "其期間自災害發生之當日起計算六個月。"
    judge = _FakeJudge(json.dumps({"results": [{"index": 1, "present": False}]}))

    async_res = await AtomicScorer.evaluate_async(
        smoothed_ans, facts, judge_llm_provider=judge,
    )
    assert async_res.is_perfect is False
    assert "自災害發生之當月一日起計算六個月" in async_res.missing_spans


@pytest.mark.asyncio
async def test_atomic_scorer_evaluate_async_canary_unaffected():
    """refusal_expected 分支不涉及語意比對，async 版與 sync 版行為一致"""
    refusal_ans = "依據目前收錄之勞動法規資料庫，並未記載此項規定，無法提供確定答覆。"
    judge = _FakeJudge('{"results":[]}')
    res = await AtomicScorer.evaluate_async(
        refusal_ans, [], refusal_expected=True, judge_llm_provider=judge,
    )
    assert res.is_perfect is True
    assert judge.calls == 0  # refusal 分支不呼叫 judge


def test_atomic_scorer_guard_failure_blocks_perfect_without_erasing_coverage():
    fact = AtomicGoldFact(
        exact_span="自災害發生之當月一日起計算六個月",
        source_law="N0050030",
        source_article="第3條",
        is_essential=True,
    )
    res = AtomicScorer.evaluate(
        "自災害發生之當月一日起計算六個月。",
        [fact],
        deterministic_guard_passed=False,
        guard_failures=["InceptionAnchorGuard: contradictory claim detected"],
    )
    assert res.atomic_recall == 1.0
    assert res.is_perfect is False
    assert res.deterministic_guard_passed is False
    assert res.guard_failures


def test_unverified_or_empty_gold_is_not_formal_eligible():
    tc = EvalTestCase(
        id="unverified-1",
        question="問題",
        source_article="第1條",
        gold_answer="[待核]",
        verification_status=VerificationStatus.UNVERIFIED,
        scenario_type=ScenarioType.TYPE_A,
    )
    decision = assess_test_case(tc)
    assert decision.eligible is False
    assert "missing_atomic_gold_facts" in decision.reasons
    assert "verification_status=unverified" in decision.reasons


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
