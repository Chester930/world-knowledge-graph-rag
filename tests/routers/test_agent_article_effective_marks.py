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
        yield "answer"

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


def _configure_chat(monkeypatch, *, document, fact, article_repo):
    kg_id = document.kg_id
    llm = _FakeStreamLLM()

    async def fake_facts(driver, kg_id_arg, vector, top_k, **kwargs):
        return [dict(fact)]

    async def fake_resolve(question, embedding_provider, *, llm_provider, cfg=None):
        return None

    async def fake_document_map(driver, kg_id_arg, triples, fact_results):
        return {str(document.source_doc_id): document}

    monkeypatch.setattr(agent, "date", _FixedDate)
    monkeypatch.setattr(agent.settings, "trace_semantic_marks", True)
    monkeypatch.setattr(agent, "KGRepository", _FakeKGRepo)
    monkeypatch.setattr(agent, "LawDocumentRepository", article_repo)
    monkeypatch.setattr(agent, "get_driver", lambda: "fake-driver")
    monkeypatch.setattr(agent, "get_embedding_provider", lambda: _FakeEmbeddingProvider())
    monkeypatch.setattr(agent, "get_llm_provider", lambda: llm)
    monkeypatch.setattr(agent, "get_judge_llm_provider", lambda provider: provider)
    monkeypatch.setattr(agent, "vector_search_facts", fake_facts)
    monkeypatch.setattr(agent, "resolve_query_relation_type", fake_resolve)
    monkeypatch.setattr(agent, "_fetch_document_map", fake_document_map)
    return kg_id


def _sources(chunks):
    chunk = next(item for item in chunks if item.startswith("event: sources\n"))
    return json.loads(chunk.split("\n", 1)[1][len("data: "):])


@pytest.mark.asyncio
async def test_chat_article_effective_marks_success_and_flag_off_zero_calls(monkeypatch):
    kg_id = uuid4()
    doc_id = uuid4()
    document = LawDocument(
        kg_id=kg_id, source_doc_id=doc_id, source="N0060014_營造安全衛生設施標準",
        title="營造安全衛生設施標準", record_type="law", content_hash="hash",
        effective_note="一百十五年六月三十日增訂之第 11-2 條，自一百十六年七月一日施行。",
    )
    fact = {
        "fact_text": "甲 導致 乙", "subject": "甲", "verb": "導致", "object": "乙",
        "rel_type": "CAUSES", "score": 0.9, "source_doc_id": str(doc_id),
        "source_svo_chunk_index": 7,
    }
    calls = {"article_nos": 0, "list_articles": 0}

    class _FakeRepo:
        def __init__(self, driver):
            pass

        async def article_nos_for_evidence(self, kg_id_arg, keys):
            calls["article_nos"] += 1
            assert keys == [(str(doc_id), 7)]
            return {(str(doc_id), 7): "第 11-2 條"}

        async def list_article_nos(self, kg_id_arg, source_doc_id):
            calls["list_articles"] += 1
            assert source_doc_id == doc_id
            return ["第 11-2 條", "第 12 條"]

    _configure_chat(monkeypatch, document=document, fact=fact, article_repo=_FakeRepo)
    response = await agent.chat(ChatRequest(
        question="問題", kg_id=kg_id, retrieval_mode="fact_only", include_retrieval_trace=True,
    ))
    sources = _sources(await _drain(response))
    marks = sources["retrieval_trace"]["facts"][0]["semantic_marks"]
    assert marks["article_effective_status"] == "pending_whole"
    assert marks["article_effective_from"] == "2027-07-01"
    assert marks["article_pending_locators"] == []
    assert calls == {"article_nos": 1, "list_articles": 1}

    calls.update(article_nos=0, list_articles=0)
    monkeypatch.setattr(agent.settings, "trace_semantic_marks", False)
    response = await agent.chat(ChatRequest(
        question="問題", kg_id=kg_id, retrieval_mode="fact_only", include_retrieval_trace=True,
    ))
    sources = _sources(await _drain(response))
    assert calls == {"article_nos": 0, "list_articles": 0}
    assert "semantic_marks" not in sources["retrieval_trace"]["facts"][0]


@pytest.mark.asyncio
async def test_chat_article_query_failure_isolated_and_done_event_survives(monkeypatch):
    kg_id = uuid4()
    doc_id = uuid4()
    document = LawDocument(
        kg_id=kg_id, source_doc_id=doc_id, source="N0060014_營造安全衛生設施標準",
        title="營造安全衛生設施標準", record_type="law", content_hash="hash",
        effective_note="一百十五年六月三十日增訂之第 11-2 條，自一百十六年七月一日施行。",
    )
    fact = {
        "fact_text": "甲 導致 乙", "subject": "甲", "verb": "導致", "object": "乙",
        "rel_type": "CAUSES", "score": 0.9, "source_doc_id": str(doc_id),
        "source_svo_chunk_index": 7,
    }

    class _ExplodingRepo:
        def __init__(self, driver):
            pass

        async def article_nos_for_evidence(self, kg_id_arg, keys):
            raise RuntimeError("fake read failure")

        async def list_article_nos(self, kg_id_arg, source_doc_id):
            raise AssertionError("must not reach second read")

    _configure_chat(monkeypatch, document=document, fact=fact, article_repo=_ExplodingRepo)
    chunks = await _drain(await agent.chat(ChatRequest(
        question="問題", kg_id=kg_id, retrieval_mode="fact_only", include_retrieval_trace=True,
    )))
    sources = _sources(chunks)
    assert sources["facts"][0]["document"]["effective_status"] == "has_pending"
    assert "article_effective_status" not in sources["retrieval_trace"]["facts"][0]["semantic_marks"]
    assert any(item.startswith("event: status\ndata: ") and '"phase": "done"' in item for item in chunks)
    assert any('"token": "answer"' in item for item in chunks)


@pytest.mark.asyncio
async def test_chat_article_query_skipped_without_trace_or_without_pending(monkeypatch):
    kg_id = uuid4()
    doc_id = uuid4()
    fact = {
        "fact_text": "甲 導致 乙", "subject": "甲", "verb": "導致", "object": "乙",
        "rel_type": "CAUSES", "score": 0.9, "source_doc_id": str(doc_id),
        "source_svo_chunk_index": 7,
    }
    calls = 0

    class _FakeRepo:
        def __init__(self, driver):
            pass

        async def article_nos_for_evidence(self, kg_id_arg, keys):
            nonlocal calls
            calls += 1
            return {}

        async def list_article_nos(self, kg_id_arg, source_doc_id):
            nonlocal calls
            calls += 1
            return []

    for note, include_trace in ((None, True), ("一百十五年六月三十日增訂之第 11-2 條，自一百十六年七月一日施行。", False)):
        document = LawDocument(
            kg_id=kg_id, source_doc_id=doc_id, source="doc", title="doc", record_type="law",
            content_hash="hash", effective_note=note,
        )
        _configure_chat(monkeypatch, document=document, fact=fact, article_repo=_FakeRepo)
        await _drain(await agent.chat(ChatRequest(
            question="問題", kg_id=kg_id, retrieval_mode="fact_only", include_retrieval_trace=include_trace,
        )))
    assert calls == 0


@pytest.mark.asyncio
async def test_fetch_article_effective_inputs_empty_inputs_do_not_construct_repository(monkeypatch):
    class _ExplodingRepo:
        def __init__(self, driver):
            raise AssertionError("empty inputs must not construct repository")

    monkeypatch.setattr(agent, "LawDocumentRepository", _ExplodingRepo)
    assert await agent._fetch_article_effective_inputs("driver", uuid4(), [], []) == ({}, {})
