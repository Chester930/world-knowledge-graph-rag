"""離線驗證 KGConfig 門檻可沿 SVO 抽取鏈讀取。"""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from core.kg_config import DedupConfig, ExtractionConfig, KGConfig, RelTypeConfig
from models.knowledge_graph import SVOTriple
from services import expand_worker, svo_service as svc


class RecordingLLM:
    def __init__(self, response: str):
        self.response = response
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


class FixedEmbedding:
    def __init__(self, vectors: dict[str, list[float]]):
        self.vectors = vectors

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.vectors[text] for text in texts]


class ScoredEmbedding:
    def __init__(self, mention: str, candidate: str, score: float):
        self.vectors = {
            mention: [1.0, 0.0],
            candidate: [score, (1 - score**2) ** 0.5],
        }

    async def encode(self, text: str) -> list[float]:
        return self.vectors[text]


@pytest.mark.asyncio
async def test_reconcile_rel_type_uses_cfg_compare_threshold(monkeypatch):
    async def fake_classify_relation_by_embedding(verb, embedding_provider):
        return "CAUSES", 0.80

    monkeypatch.setattr(svc, "classify_relation_by_embedding", fake_classify_relation_by_embedding)

    default_llm = RecordingLLM("CAUSES")
    default_result = await svc._reconcile_rel_type(
        "causes", "CAUSES", embedding_provider=object(), llm_provider=default_llm,
    )

    explicit_default_llm = RecordingLLM("CAUSES")
    explicit_default_result = await svc._reconcile_rel_type(
        "causes", "CAUSES", embedding_provider=object(), llm_provider=explicit_default_llm,
        cfg=KGConfig(),
    )

    overridden_llm = RecordingLLM("CAUSES")
    overridden_result = await svc._reconcile_rel_type(
        "causes", "CAUSES", embedding_provider=object(), llm_provider=overridden_llm,
        cfg=KGConfig(reltype=RelTypeConfig(compare_cosine_threshold=0.90)),
    )

    assert default_result == explicit_default_result == overridden_result == "CAUSES"
    assert default_llm.prompts == explicit_default_llm.prompts == []
    assert len(overridden_llm.prompts) == 1


class RecordingJsonLLM:
    async def generate_json(self, prompt: str) -> str:
        return "offline payload"


@pytest.mark.asyncio
async def test_extract_svo_triples_forwards_cfg_to_relation_reconciliation(monkeypatch):
    cfg = KGConfig()
    received_cfgs = []

    async def fake_reconcile(verb, llm_rel_type, **kwargs):
        received_cfgs.append(kwargs["cfg"])
        return llm_rel_type

    monkeypatch.setattr(svc, "_parse_triples_payload", lambda _: [{
        "subject": "甲", "subject_type": "機構", "verb": "提供",
        "object": "乙", "object_type": "機構", "rel_type": "CAUSES",
    }])
    monkeypatch.setattr(svc, "_reconcile_rel_type", fake_reconcile)

    triples = await svc.extract_svo_triples(
        "甲提供乙。", RecordingJsonLLM(), object(), cfg=cfg,
    )

    assert len(triples) == 1
    assert received_cfgs == [cfg]


@pytest.mark.asyncio
async def test_find_uncovered_sentences_threshold_precedence():
    sentence = "甲乙丙"
    triple = SVOTriple(subject="甲", verb="關係", object="乙")
    triple_text = "甲關係乙"
    embedding = FixedEmbedding({
        sentence: [1.0, 0.0],
        triple_text: [0.65, (1 - 0.65**2) ** 0.5],
    })
    cfg = KGConfig(extraction=ExtractionConfig(uncovered_sentence_threshold=0.70))

    explicit_threshold = await svc._find_uncovered_sentences(
        [sentence], [triple], embedding, threshold=0.70,
    )
    config_threshold = await svc._find_uncovered_sentences(
        [sentence], [triple], embedding, cfg=cfg,
    )
    explicit_threshold_wins = await svc._find_uncovered_sentences(
        [sentence], [triple], embedding, threshold=0.60, cfg=cfg,
    )
    default_without_cfg = await svc._find_uncovered_sentences([sentence], [triple], embedding)
    default_with_cfg = await svc._find_uncovered_sentences(
        [sentence], [triple], embedding, cfg=KGConfig(),
    )

    assert explicit_threshold == config_threshold == [sentence]
    assert explicit_threshold_wins == []
    assert default_without_cfg == default_with_cfg == []


@pytest.mark.asyncio
async def test_completeness_check_forwards_same_cfg_to_both_extraction_passes(monkeypatch):
    cfg = KGConfig()
    received_cfgs = []

    async def fake_extract(text, llm_provider, embedding_provider, **kwargs):
        received_cfgs.append(kwargs["cfg"])
        return [SVOTriple(subject=f"甲{len(received_cfgs)}", verb="提供", object="乙")]

    async def fake_find_uncovered(original_sentences, triples, embedding_provider, **kwargs):
        assert kwargs["cfg"] is cfg
        return list(original_sentences)

    monkeypatch.setattr(svc, "extract_svo_triples", fake_extract)
    monkeypatch.setattr(svc, "_find_uncovered_sentences", fake_find_uncovered)
    monkeypatch.setattr(svc, "_filter_ungrounded_quantity_triples", lambda triples, *_: triples)

    result = await svc.extract_svo_triples_with_completeness_check(
        "甲提供乙。", ["甲提供乙。"], RecordingLLM(""), object(), cfg=cfg,
    )

    assert len(result) == 2
    assert received_cfgs == [cfg, cfg]


@pytest.mark.asyncio
async def test_resolve_entity_name_uses_cfg_edit_ratio_threshold():
    mention, candidate = "台積電", "台積電公司"
    ratio = svc._edit_ratio(mention, candidate)
    assert 0.70 <= ratio < 0.90

    default_result = await svc.resolve_entity_name(mention, [{"name": candidate}])
    explicit_default_result = await svc.resolve_entity_name(
        mention, [{"name": candidate}], cfg=KGConfig(),
    )
    overridden_result = await svc.resolve_entity_name(
        mention, [{"name": candidate}],
        cfg=KGConfig(dedup=DedupConfig(edit_ratio_threshold=0.90)),
    )

    assert default_result == explicit_default_result == candidate
    assert overridden_result == mention


@pytest.mark.asyncio
async def test_resolve_entity_name_uses_cfg_cosine_threshold():
    mention, candidate = "mention", "candidate"
    embedding = ScoredEmbedding(mention, candidate, 0.90)
    candidates = [{"name": candidate}]

    default_result = await svc.resolve_entity_name(
        mention, candidates, embedding_provider=embedding,
    )
    explicit_default_result = await svc.resolve_entity_name(
        mention, candidates, embedding_provider=embedding, cfg=KGConfig(),
    )
    overridden_result = await svc.resolve_entity_name(
        mention, candidates, embedding_provider=embedding,
        cfg=KGConfig(dedup=DedupConfig(cosine_threshold=0.95, escalate_low_threshold=0.95)),
    )

    assert default_result == explicit_default_result == candidate
    assert overridden_result == mention


@pytest.mark.asyncio
async def test_resolve_entity_name_uses_cfg_escalate_low_threshold():
    mention, candidate = "mention", "candidate"
    embedding = ScoredEmbedding(mention, candidate, 0.80)
    candidates = [{"name": candidate}]
    default_llm = RecordingLLM("是")
    explicit_default_llm = RecordingLLM("是")
    overridden_llm = RecordingLLM("是")

    default_result = await svc.resolve_entity_name(
        mention, candidates, embedding_provider=embedding, llm_provider=default_llm,
    )
    explicit_default_result = await svc.resolve_entity_name(
        mention, candidates, embedding_provider=embedding, llm_provider=explicit_default_llm,
        cfg=KGConfig(),
    )
    overridden_result = await svc.resolve_entity_name(
        mention, candidates, embedding_provider=embedding, llm_provider=overridden_llm,
        cfg=KGConfig(dedup=DedupConfig(escalate_low_threshold=0.85)),
    )

    assert default_result == explicit_default_result == candidate
    assert len(default_llm.prompts) == len(explicit_default_llm.prompts) == 1
    assert overridden_result == mention
    assert overridden_llm.prompts == []


@pytest.mark.asyncio
async def test_merge_entity_forwards_optional_cfg(monkeypatch):
    received_cfgs = []

    async def fake_fetch_candidates(*args, **kwargs):
        return []

    async def fake_resolve(name, candidates, **kwargs):
        received_cfgs.append(kwargs["cfg"])
        return name

    async def fake_execute(*args, **kwargs):
        return None

    monkeypatch.setattr(svc, "_fetch_entity_candidates", fake_fetch_candidates)
    monkeypatch.setattr(svc, "resolve_entity_name", fake_resolve)
    monkeypatch.setattr(svc, "_execute_with_constraint_retry", fake_execute)

    kg_id = uuid4()
    default_result = await svc.merge_entity(object(), kg_id, "甲", "概念", "甲")
    cfg = KGConfig()
    explicit_default_result = await svc.merge_entity(
        object(), kg_id, "甲", "概念", "甲", cfg=cfg,
    )

    assert default_result == explicit_default_result == "甲"
    assert received_cfgs == [None, cfg]


@pytest.mark.asyncio
async def test_merge_triples_to_graph_forwards_cfg_to_both_entities(monkeypatch):
    received_cfgs = []

    async def fake_merge_entity(*args, **kwargs):
        received_cfgs.append(kwargs["cfg"])
        return args[2]

    class FakeDriver:
        async def execute_query(self, query, **kwargs):
            records = [{"citations_json": "[]"}] if "RETURN r.citations_json" in query else []
            return SimpleNamespace(records=records)

    monkeypatch.setattr(svc, "merge_entity", fake_merge_entity)
    triple = SVOTriple(subject="甲", verb="連結", object="乙")
    kg_id = uuid4()

    await svc.merge_triples_to_graph(FakeDriver(), kg_id, [triple])
    cfg = KGConfig()
    await svc.merge_triples_to_graph(FakeDriver(), kg_id, [triple], cfg=cfg)

    assert received_cfgs == [None, None, cfg, cfg]


@pytest.mark.asyncio
async def test_backfill_related_to_edges_uses_cfg_compare_threshold():
    class FakeEmbedding:
        async def encode(self, text: str) -> list[float]:
            return [1.0]

    class FakeDriver:
        def __init__(self):
            self.calls = []

        async def execute_query(self, query, **kwargs):
            self.calls.append((query, kwargs))
            return SimpleNamespace(records=[])

    driver = FakeDriver()
    args = (driver, uuid4(), "NEW_TYPE", "new type description", FakeEmbedding())
    default_count = await svc.backfill_related_to_edges(*args)
    explicit_default_count = await svc.backfill_related_to_edges(*args, cfg=KGConfig())
    overridden_count = await svc.backfill_related_to_edges(
        *args, cfg=KGConfig(reltype=RelTypeConfig(compare_cosine_threshold=0.91)),
    )

    thresholds = [params["threshold"] for _, params in driver.calls]
    assert default_count == explicit_default_count == overridden_count == 0
    assert thresholds == [0.75, 0.75, 0.91]


@pytest.mark.asyncio
async def test_commit_and_backfill_forwards_optional_cfg(monkeypatch):
    received_cfgs = []

    async def fake_backfill(*args, **kwargs):
        received_cfgs.append(kwargs["cfg"])
        return 7

    monkeypatch.setattr(expand_worker, "task_queue_db_path", lambda: ":memory:")
    monkeypatch.setattr(expand_worker.expand_governance_service, "mark_committed", lambda *args: None)
    monkeypatch.setattr(expand_worker, "backfill_related_to_edges", fake_backfill)

    args = (
        object(), uuid4(), object(), RecordingLLM(""),
    )
    kwargs = {
        "type_name": "NEW_TYPE", "description": "new type", "member_verbs": ["connect"],
        "reused_from_registry": True,
    }
    default_count = await expand_worker.commit_and_backfill(*args, **kwargs)
    cfg = KGConfig()
    explicit_default_count = await expand_worker.commit_and_backfill(*args, **kwargs, cfg=cfg)

    assert default_count == explicit_default_count == 7
    assert received_cfgs == [None, cfg]
