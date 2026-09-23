from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from models.eval_schema import (
    AtomicGoldFact,
    ScenarioType,
    TestCase as EvalTestCase,
    VerificationStatus,
)
from routers import agent
from scripts.eval import run_rq1_comparison as harness


class _FakeLineage:
    instances: list["_FakeLineage"] = []

    def __init__(self, query_id, arm, question):
        self.providers: list[object] = []
        self.failure_attribution = "ok"
        self.__class__.instances.append(self)

    async def record_retrieval_async(self, *args, judge_llm_provider=None, **kwargs):
        self.providers.append(judge_llm_provider)

    async def record_context_assembly_async(self, *args, judge_llm_provider=None, **kwargs):
        self.providers.append(judge_llm_provider)

    def record_generation(self, *args, **kwargs):
        return None

    async def build_full_lineage_async(self, *args, judge_llm_provider=None, **kwargs):
        self.providers.append(judge_llm_provider)
        return self

    def model_dump(self):
        return {}


class _FakeAtomicScore:
    def model_dump(self):
        return {}


def _case() -> EvalTestCase:
    return EvalTestCase(
        id="metric-q",
        question="問題",
        source_article="LAW §1",
        gold_answer="答案",
        scenario_type=ScenarioType.TYPE_A,
        atomic_gold_facts=[
            AtomicGoldFact(exact_span="法規原文", source_law="LAW", source_article="第1條")
        ],
        verification_status=VerificationStatus.VERIFIED,
    )


def _patch_single_query_dependencies(monkeypatch, captured_atomic):
    _FakeLineage.instances.clear()
    monkeypatch.setattr(harness, "LineageTracker", _FakeLineage)
    monkeypatch.setattr(
        harness,
        "_drain_chat",
        lambda payload: _fake_drain_chat(),
    )
    monkeypatch.setattr(
        harness.DeterministicGuardService,
        "verify_draft",
        lambda **kwargs: SimpleNamespace(
            is_valid=True, failure_reason=None, model_dump=lambda: {}
        ),
    )
    monkeypatch.setattr(harness, "audit_answer_scope", lambda answer, tc: {})

    async def fake_evaluate_async(*args, judge_llm_provider=None, **kwargs):
        captured_atomic.append(judge_llm_provider)
        return _FakeAtomicScore()

    monkeypatch.setattr(harness.AtomicScorer, "evaluate_async", fake_evaluate_async)


async def _fake_drain_chat():
    return {
        "answer": "答案",
        "error": None,
        "regenerated": False,
        "triples": [],
        "facts": [],
        "grounding": [],
        "retrieval_trace": {},
    }


@pytest.mark.asyncio
async def test_metric_counter_is_used_by_all_four_measurement_stages(monkeypatch):
    atomic_providers = []
    _patch_single_query_dependencies(monkeypatch, atomic_providers)
    counting = harness._CountingLLM(object())
    judge = harness._CountingLLM(object())
    metric = harness._CountingLLM(object())

    await harness._run_single_query(
        _case(), "K", uuid4(), [], None, counting, judge, None, None, 5,
        metric_counter=metric,
    )

    assert _FakeLineage.instances[0].providers == [metric, metric, metric]
    assert atomic_providers == [metric]


@pytest.mark.asyncio
async def test_without_metric_counter_measurements_keep_existing_judge(monkeypatch):
    atomic_providers = []
    _patch_single_query_dependencies(monkeypatch, atomic_providers)
    counting = harness._CountingLLM(object())
    judge = harness._CountingLLM(object())

    await harness._run_single_query(
        _case(), "K", uuid4(), [], None, counting, judge, None, None, 5,
    )

    assert _FakeLineage.instances[0].providers == [judge, judge, judge]
    assert atomic_providers == [judge]


@pytest.mark.asyncio
async def test_b0_generation_still_uses_arm_judge_when_metric_counter_is_set(monkeypatch):
    atomic_providers = []
    _patch_single_query_dependencies(monkeypatch, atomic_providers)
    seen_generation_judges = []
    embedding = SimpleNamespace(encode=lambda question: _fake_vector())

    async def fake_encode(question):
        return [0.0]

    embedding.encode = fake_encode
    monkeypatch.setattr(harness, "get_embedding_provider", lambda: embedding)
    monkeypatch.setattr(harness.baseline_rag_service, "search_baseline", lambda *a, **k: [])
    monkeypatch.setattr(harness.baseline_rag_service, "build_context_lines", lambda hits: [])

    async def fake_generate(*args, judge_llm_provider=None, **kwargs):
        seen_generation_judges.append(judge_llm_provider)
        yield agent._GenerationResult("答案", [], False)

    monkeypatch.setattr(harness.agent, "_generate_from_context_lines", fake_generate)
    counting = harness._CountingLLM(object())
    judge = harness._CountingLLM(object())
    metric = harness._CountingLLM(object())

    await harness._run_single_query(
        _case(), "B0", uuid4(), [], None, counting, judge, ([], []), None, 5,
        metric_counter=metric,
    )

    assert seen_generation_judges == [judge]


def _fake_vector():
    return [0.0]


@pytest.mark.asyncio
@pytest.mark.parametrize("metric_provider", [None, "ollama"])
async def test_harness_creates_metric_counter_only_when_requested(
    monkeypatch, tmp_path, metric_provider
):
    captured = {}

    async def fake_connect():
        return None

    async def fake_disconnect():
        return None

    monkeypatch.setattr(harness, "connect", fake_connect)
    monkeypatch.setattr(harness, "disconnect", fake_disconnect)
    monkeypatch.setattr(harness, "init_providers", lambda: None)
    monkeypatch.setattr(harness, "get_llm_provider", lambda: object())
    monkeypatch.setattr(harness, "get_judge_llm_provider", lambda generator: object())
    monkeypatch.setattr(harness, "get_driver", lambda: object())
    class _FakeRepository:
        async def get(self, kg):
            return None

    monkeypatch.setattr(harness, "KGRepository", lambda driver: _FakeRepository())
    monkeypatch.setattr(harness, "ConfigLoader", lambda sources: SimpleNamespace(load=lambda *a, **k: object()))
    monkeypatch.setattr(harness, "FileConfigSource", lambda path: object())
    monkeypatch.setattr(harness, "_resolve_scope", lambda kg_id, doc_ids: ([], set()))
    monkeypatch.setattr(harness, "_render_pareto_summary", lambda *args: None)

    metric_inner = object()

    def fake_make_metric(provider, model):
        captured["make_args"] = (provider, model)
        return metric_inner

    monkeypatch.setattr(harness, "make_llm_provider_for_eval", fake_make_metric)

    async def fake_single_query(*args, **kwargs):
        captured["metric_counter"] = args[-1]
        return {"question_id": "metric-q", "arm": "K", "run": 1}

    monkeypatch.setattr(harness, "_run_single_query", fake_single_query)

    args = SimpleNamespace(
        embedding_cache=None,
        metric_judge_provider=metric_provider,
        metric_judge_model="metric-model",
        allow_shared_judge=True,
        kg_id=str(uuid4()),
        doc_ids="doc",
        arms=["K"],
        runs=1,
        chunk_size=500,
        baseline_top_k=5,
        k_top_k=None,
        query_timeout_s=10,
    )
    manifest = {}
    await harness._run_harness(args, tmp_path, [_case()], manifest)

    if metric_provider is None:
        assert "make_args" not in captured
        assert captured["metric_counter"] is None
    else:
        assert captured["make_args"] == ("ollama", "metric-model")
        assert isinstance(captured["metric_counter"], harness._CountingLLM)
        assert captured["metric_counter"]._inner is metric_inner
