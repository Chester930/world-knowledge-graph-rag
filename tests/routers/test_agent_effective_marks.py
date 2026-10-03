"""S2 router 層：沿用既有 fake provider／driver／SSE drain 手法的最小測試。"""
from __future__ import annotations

import json
from datetime import date as real_date
from uuid import uuid4

import pytest

from models.document import ChatRequest
from models.law_document import LawDocument
from routers import agent


class _FakeEmbeddingProvider:
    async def encode(self, text: str):
        return [0.1, 0.2]


class _FakeStreamLLM:
    async def stream(self, prompt: str):
        yield "ok"

    async def generate_json(self, prompt: str) -> str:
        return '{"claims":[]}'


class _FakeKGRepo:
    def __init__(self, driver):
        pass

    async def get(self, kg_id):
        return None


class _FixedDate:
    @classmethod
    def today(cls):
        return real_date(2026, 10, 3)


async def _drain(response):
    return [chunk async for chunk in response.body_iterator]


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_chat_sse_sources_effective_fields_follow_trace_flag(monkeypatch, enabled):
    kg_id = uuid4()
    doc_id = uuid4()
    document = LawDocument(
        kg_id=kg_id, source_doc_id=doc_id, source="N0060014_營造安全衛生設施標準",
        title="營造安全衛生設施標準", record_type="law", content_hash="hash",
        effective_note="一百十五年六月三十日增訂之第 11-2 條，自一百十六年七月一日施行。",
    )
    llm = _FakeStreamLLM()

    async def fake_facts(driver, kg_id_arg, vector, top_k, **kwargs):
        return [{
            "fact_text": "甲 導致 乙", "subject": "甲", "verb": "導致", "object": "乙",
            "rel_type": "CAUSES", "score": 0.9, "source_doc_id": str(doc_id),
        }]

    async def fake_resolve(question, embedding_provider, *, llm_provider, cfg=None):
        return None

    async def fake_document_map(driver, kg_id_arg, triples, fact_results):
        return {str(doc_id): document}

    monkeypatch.setattr(agent, "date", _FixedDate)
    monkeypatch.setattr(agent.settings, "trace_semantic_marks", enabled)
    monkeypatch.setattr(agent, "KGRepository", _FakeKGRepo)
    monkeypatch.setattr(agent, "get_driver", lambda: "fake-driver")
    monkeypatch.setattr(agent, "get_embedding_provider", lambda: _FakeEmbeddingProvider())
    monkeypatch.setattr(agent, "get_llm_provider", lambda: llm)
    monkeypatch.setattr(agent, "get_judge_llm_provider", lambda provider: provider)
    monkeypatch.setattr(agent, "vector_search_facts", fake_facts)
    monkeypatch.setattr(agent, "resolve_query_relation_type", fake_resolve)
    monkeypatch.setattr(agent, "_fetch_document_map", fake_document_map)

    response = await agent.chat(ChatRequest(
        question="問題", kg_id=kg_id, retrieval_mode="fact_only", include_retrieval_trace=True,
    ))
    chunks = await _drain(response)
    sources_chunk = next(chunk for chunk in chunks if chunk.startswith("event: sources\n"))
    sources = json.loads(sources_chunk.split("\n", 1)[1][len("data: "):])
    document_payload = sources["facts"][0]["document"]
    if enabled:
        assert document_payload["effective_status"] == "has_pending"
        assert document_payload["effective_pending_dates"] == ["2027-07-01"]
        marks = sources["retrieval_trace"]["facts"][0]["semantic_marks"]
        assert marks["document_effective_status"] == "has_pending"
    else:
        assert list(document_payload) == ["title", "update_date", "effective_date", "effective_note"]
        assert "effective_status" not in document_payload
        assert "effective_pending_dates" not in document_payload
        assert "semantic_marks" not in sources["retrieval_trace"]["facts"][0]
