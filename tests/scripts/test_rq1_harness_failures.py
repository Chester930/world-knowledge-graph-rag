"""RQ1 harness 非 timeout 例外的結構化 failure record 測試。"""
from models.eval_schema import AtomicGoldFact, ScenarioType, TestCase as EvalTestCase, VerificationStatus
from scripts.eval.run_rq1_comparison import _build_failure_record


def test_build_failure_record_preserves_lineage_and_failure_reason():
    test_case = EvalTestCase(
        id="q-transport",
        question="問題",
        source_article="LAW §1",
        gold_answer="答案",
        scenario_type=ScenarioType.TYPE_A,
        atomic_gold_facts=[
            AtomicGoldFact(
                exact_span="法規原文",
                source_law="LAW",
                source_article="第1條",
            )
        ],
        verification_status=VerificationStatus.VERIFIED,
    )

    record = _build_failure_record(
        test_case,
        "M4",
        1,
        error_code="harness_exception",
        failure_reason="RemoteProtocolError: incomplete chunked read",
        guard_name="HarnessException",
        latency_s=12.5,
    )

    assert record["error"] == "harness_exception"
    assert record["latency_s"] == 12.5
    assert "RemoteProtocolError" in record["failure_attribution"]
    assert record["lineage"]["stage3_generation"]["raw_draft"] == ""
    assert record["deterministic_guard"]["guard_name"] == "HarnessException"
    assert record["atomic_score"]["is_perfect"] is False
