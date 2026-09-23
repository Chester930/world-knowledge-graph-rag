"""RQ1 harness 非 timeout 例外的結構化 failure record 測試。"""
from models.eval_schema import AtomicGoldFact, ScenarioType, TestCase as EvalTestCase, VerificationStatus
from scripts.eval.run_rq1_comparison import (
    _build_failure_record,
    build_arg_parser,
    _render_pareto_summary,
)


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


def test_embedding_cache_cli_is_opt_in():
    parser = build_arg_parser()

    assert parser.parse_args([]).embedding_cache is None
    assert parser.parse_args(["--embedding-cache", "cache.json"]).embedding_cache == "cache.json"


def test_metric_judge_cli_is_opt_in():
    parser = build_arg_parser()

    args = parser.parse_args([])
    assert args.metric_judge_provider is None
    assert args.metric_judge_model is None

    args = parser.parse_args([
        "--metric-judge-provider", "ollama",
        "--metric-judge-model", "qwen2.5:7b",
    ])
    assert args.metric_judge_provider == "ollama"
    assert args.metric_judge_model == "qwen2.5:7b"


def test_render_pareto_summary_includes_context_quality_section(tmp_path):
    """報告57 §2.3：Context Quality矩陣（Recall/SNR/Chain Completeness）
    須與既有Atomic Accuracy矩陣並列輸出，不互相取代。"""
    single_doc_case = EvalTestCase(
        id="q-single", question="q1", source_article="LAW1 §1", gold_answer="a",
        scenario_type=ScenarioType.TYPE_A,
        atomic_gold_facts=[
            AtomicGoldFact(exact_span="法規原文", source_law="LAW1", source_article="第1條"),
        ],
        verification_status=VerificationStatus.VERIFIED,
    )
    cross_doc_case = EvalTestCase(
        id="q-cross", question="q2", source_article="LAW1/LAW2", gold_answer="b",
        scenario_type=ScenarioType.TYPE_C,
        atomic_gold_facts=[
            AtomicGoldFact(exact_span="事實一", source_law="LAW1", source_article="第1條"),
            AtomicGoldFact(exact_span="事實二", source_law="LAW2", source_article="第2條"),
        ],
        verification_status=VerificationStatus.VERIFIED,
    )
    rec1 = _build_failure_record(
        single_doc_case, "M1", 1,
        error_code="x", failure_reason="x", guard_name="x", latency_s=1.0,
    )
    rec2 = _build_failure_record(
        cross_doc_case, "M1", 1,
        error_code="x", failure_reason="x", guard_name="x", latency_s=1.0,
    )

    manifest = {"kg_id": "kg-test", "runs": 1}
    _render_pareto_summary(
        tmp_path, manifest, [rec1, rec2], ["M1"], [single_doc_case, cross_doc_case],
    )
    content = (tmp_path / "summary.md").read_text(encoding="utf-8")

    assert "Context Quality" in content
    assert "Chain Completeness" in content
    # 兩題檢索皆為空（_build_failure_record 走 failure 路徑），single_doc_case
    # 只涉及1個source_law故chain_completeness=None（不計入平均）；cross_doc_case
    # 涉及2個source_law、0命中，chain_completeness=0.0，唯一計入樣本 n=1。
    assert "n=1" in content
    assert "0.0%" in content
