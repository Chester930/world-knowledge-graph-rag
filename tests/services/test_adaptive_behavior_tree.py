"""單元測試：自適應檢索行為樹與場景分類器（SDD-4.1 & SDD-4.2）。

驗證：
1. QueryClassifier 場景特徵分類精確度（Type-A~E）。
2. AdaptiveRetrievalService 行為樹走訪軌跡：
   - Type-E 題目直接觸發 GuardNode 早退拒答。
   - Type-A/B 題目成功調度 M2 TextBranch。
   - M2 檢索置信度不足時，自動觸發 AdaptiveFallbackToM4 升級至圖譜檢索。
   - 生成草稿違規時觸發確定性接地重生成。
"""
import pytest
from models.eval_schema import ScenarioType
from services.query_classifier import QueryClassifier
from services.adaptive_retrieval_service import AdaptiveRetrievalService


def test_query_classifier_scenarios():
    # Type-E Canary
    c_e = QueryClassifier.classify("請教若雇主未給假，可否請求前往火星太空旅行考察？")
    assert c_e.scenario == ScenarioType.TYPE_E
    assert c_e.recommended_arm == "REFUSE"

    # Type-C Multi-Hop
    c_c = QueryClassifier.classify("災區受災勞工符合規定者，保險費由中央政府支應多久？從哪一天起算？")
    assert c_c.scenario == ScenarioType.TYPE_C
    assert c_c.recommended_arm == "M4"

    # Type-B Numeric
    c_b = QueryClassifier.classify("勞工未住院之普通傷病假一年內上限為幾天？工資怎麼算？")
    assert c_b.scenario == ScenarioType.TYPE_B
    assert c_b.recommended_arm == "M2"

    # Type-A Single Doc
    c_a = QueryClassifier.classify("勞工請假規則第2條關於婚假的日數為何？")
    assert c_a.scenario in (ScenarioType.TYPE_A, ScenarioType.TYPE_B)


def test_adaptive_behavior_tree_guard_refusal():
    """驗證 Type-E 題目觸發行為樹 GuardNode 早退，不呼叫任何檢索與生成函式"""
    question = "違反法令可處新臺幣一百億元罰鍰嗎？"

    def dummy_retrieval_m2(q):
        pytest.fail("M2 retrieval should not be called on Canary!")

    def dummy_retrieval_m4(q):
        pytest.fail("M4 retrieval should not be called on Canary!")

    def dummy_generator(**kwargs):
        pytest.fail("Generator should not be called on Canary!")

    trace = AdaptiveRetrievalService.schedule_and_route(
        question=question,
        retrieval_fn_m2=dummy_retrieval_m2,
        retrieval_fn_m4=dummy_retrieval_m4,
        generator_fn=dummy_generator,
    )

    assert trace.scenario == ScenarioType.TYPE_E
    assert trace.selected_arm == "REFUSE"
    assert "GuardNode:DirectRefusal" in trace.nodes_visited
    assert "未記載" in trace.final_output


def test_adaptive_behavior_tree_m2_success():
    """驗證 Type-A/B 正常題目走 M2 TextBranch 且成功通過"""
    question = "勞工請假規則第2條關於婚假幾天？"

    def mock_retrieval_m2(q):
        return {
            "confidence": 0.85,
            "context_lines": ["勞工結婚者給予婚假八日，工資照給。"],
            "articles": ["第2條"],
        }

    def mock_retrieval_m4(q):
        pytest.fail("M4 should not be called when M2 confidence is high!")

    def mock_generator(context_lines, question, extra_note=None):
        return "依第2條規定，勞工結婚者給予婚假八日，工資照給。"

    trace = AdaptiveRetrievalService.schedule_and_route(
        question=question,
        retrieval_fn_m2=mock_retrieval_m2,
        retrieval_fn_m4=mock_retrieval_m4,
        generator_fn=mock_generator,
    )

    assert trace.selected_arm == "M2"
    assert trace.fallback_triggered is False
    assert "Selector:TextBranch(M2)" in trace.nodes_visited
    assert "ConfidenceCheck:PASS" in trace.nodes_visited
    assert "GuardNode:PASS" in trace.nodes_visited


def test_adaptive_behavior_tree_fallback_to_m4():
    """驗證 M2 檢索為空或信心低時，行為樹自動觸發回補機制升級至 M4"""
    question = "災區受災勞工保費補助由誰支應？"

    def mock_weak_m2(q):
        # M2 檢索未命中任何條文
        return {"confidence": 0.10, "context_lines": [], "articles": []}

    def mock_strong_m4(q):
        # M4 圖遍歷補足事實
        return {
            "confidence": 0.90,
            "context_lines": ["其災後六個月期間內被保險人應負擔之保險費，由中央政府支應。"],
            "articles": ["第2條"],
        }

    def mock_generator(context_lines, question, extra_note=None):
        return "災後保險費由中央政府支應六個月。"

    trace = AdaptiveRetrievalService.schedule_and_route(
        question=question,
        retrieval_fn_m2=mock_weak_m2,
        retrieval_fn_m4=mock_strong_m4,
        generator_fn=mock_generator,
    )

    assert trace.selected_arm == "M4"
    assert trace.fallback_triggered is True
    assert "Action:AdaptiveFallbackToM4" in trace.nodes_visited
    assert "GuardNode:PASS" in trace.nodes_visited


def test_adaptive_behavior_tree_guard_regeneration():
    """驗證生成草稿起算日平滑化時，行為樹觸發重生成並注入硬約束"""
    question = "災後保費補助從哪一天起算？"

    def mock_retrieval_m4(q):
        return {
            "confidence": 0.95,
            "context_lines": [
                "前條所定災後六個月期間之計算，自災害發生之當月一日起計算六個月。"
            ],
            "articles": ["第3條"],
        }

    calls = []

    def mock_generator(context_lines, question, extra_note=None):
        calls.append(extra_note)
        if extra_note is None:
            # 第一次生成：平滑化為「當日」
            return "期間自災害發生當日起計算。"
        else:
            # 收到硬約束後的重生成：修正為「當月一日」
            return "期間自災害發生之當月一日起計算六個月。"

    trace = AdaptiveRetrievalService.schedule_and_route(
        question=question,
        retrieval_fn_m2=lambda q: {"confidence": 0.1, "context_lines": []},
        retrieval_fn_m4=mock_retrieval_m4,
        generator_fn=mock_generator,
    )

    assert len(calls) == 2
    assert "Action:FactoredConstrainedRegeneration" in trace.nodes_visited
    assert "當月一日" in trace.final_output
