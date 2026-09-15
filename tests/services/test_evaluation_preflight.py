"""RQ1 正式評測啟動前的 Preflight 規則測試。"""
from models.eval_schema import (
    AtomicGoldFact,
    ScenarioType,
    TestCase as EvalTestCase,
    VerificationStatus,
)
from services.evaluation_preflight import run_evaluation_preflight


DATASET_HASH = "a" * 64


def _case(*, verified: bool = True) -> EvalTestCase:
    return EvalTestCase(
        id="q-1",
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
        verification_status=(
            VerificationStatus.VERIFIED
            if verified
            else VerificationStatus.UNVERIFIED
        ),
    )


def _kwargs(**overrides):
    values = {
        "test_cases": [_case()],
        "arms": ["M1"],
        "generator_provider": "ollama",
        "generator_model": "qwen2.5:7b",
        "judge_provider": "openai",
        "judge_model": "gpt-4o-mini",
        "doc_ids": ["LAW"],
        "dataset_sha256": DATASET_HASH,
        "query_timeout_s": 180.0,
    }
    values.update(overrides)
    return values


def test_preflight_passes_for_formal_configuration():
    result = run_evaluation_preflight(**_kwargs())

    assert result.passed is True
    assert result.errors == []


def test_preflight_rejects_unverified_question():
    result = run_evaluation_preflight(
        **_kwargs(test_cases=[_case(verified=False)])
    )

    assert result.passed is False
    assert any("verification_status=unverified" in error for error in result.errors)


def test_preflight_rejects_same_generator_and_judge_model():
    result = run_evaluation_preflight(
        **_kwargs(judge_provider="ollama", judge_model="qwen2.5:7b")
    )

    assert result.passed is False
    assert any("independent judge" in error for error in result.errors)


def test_preflight_allows_shared_judge_only_as_explicit_pilot():
    result = run_evaluation_preflight(
        **_kwargs(
            judge_provider="ollama",
            judge_model="qwen2.5:7b",
            allow_shared_judge=True,
        )
    )

    assert result.passed is True
    assert any("pilot" in warning for warning in result.warnings)


def test_preflight_allows_type_e_synthetic_source():
    case = _case()
    case.scenario_type = ScenarioType.TYPE_E
    case.atomic_gold_facts[0].source_law = "None"

    result = run_evaluation_preflight(**_kwargs(test_cases=[case]))

    assert result.passed is True


def test_preflight_rejects_invalid_dataset_hash_arm_and_timeout():
    result = run_evaluation_preflight(
        **_kwargs(arms=["UNKNOWN"], dataset_sha256="short", query_timeout_s=0)
    )

    assert result.passed is False
    assert any("unsupported arm" in error for error in result.errors)
    assert any("dataset_sha256" in error for error in result.errors)
    assert any("query_timeout_s" in error for error in result.errors)
