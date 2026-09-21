"""離線驗證 KGConfig 門檻可沿 SVO 抽取鏈讀取。"""

import pytest

from core.kg_config import KGConfig, RelTypeConfig
from services import svo_service as svc


class RecordingLLM:
    def __init__(self, response: str):
        self.response = response
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


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
