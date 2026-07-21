from uuid import uuid4

import pytest

from models.knowledge_graph import SVOTriple
from services import svo_service as svc


class FakeLLM:
    def __init__(self, payload: str):
        self.payload = payload
        self.prompts = []

    async def generate(self, prompt: str) -> str:
        return self.payload

    async def stream(self, prompt: str):
        yield self.payload

    async def generate_json(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.payload


class FakeResult:
    def __init__(self, records=None):
        self.records = records or []


class FakeRecord(dict):
    pass


class FakeDriver:
    def __init__(self, records=None):
        self.calls = []
        self.records = records or []

    async def execute_query(self, query: str, **params):
        self.calls.append((query, params))
        return FakeResult(self.records)


@pytest.mark.asyncio
async def test_extract_svo_triples_parses_valid_json_and_filters_invalid_rel_type():
    llm = FakeLLM("""
    {"triples":[
      {"subject":"A","rel_type":"CAUSES","verb":"導致","object":"B","confidence":4},
      {"subject":"X","rel_type":"NOT_ALLOWED","verb":"關係","object":"Y","confidence":3}
    ]}
    """)

    triples = await svc.extract_svo_triples("A 導致 B。", llm)

    assert len(triples) == 1
    assert triples[0].subject == "A"
    assert triples[0].rel_type == "CAUSES"
    assert "合法 rel_type" in llm.prompts[0]


@pytest.mark.asyncio
async def test_extract_svo_triples_without_provider_returns_empty_list():
    assert await svc.extract_svo_triples("A 導致 B。") == []


@pytest.mark.asyncio
async def test_merge_triples_to_graph_passes_sentence_trace_fields():
    driver = FakeDriver()
    kg_id = uuid4()
    doc_id = uuid4()
    triple = SVOTriple(
        subject="A",
        rel_type="CAUSES",
        verb="導致",
        object="B",
        source_doc_id=doc_id,
        source_svo_chunk_index=2,
        source_svo_chunk_file="svo-chunk-002-of-003.md",
        source_sentence_start=5,
        source_sentence_end=7,
    )

    await svc.merge_triples_to_graph(driver, kg_id, [triple])

    query, params = driver.calls[0]
    assert "`CAUSES`" in query
    assert params["kg_id"] == str(kg_id)
    assert params["source_doc_id"] == str(doc_id)
    assert params["source_svo_chunk_index"] == 2
    assert params["source_sentence_start"] == 5
    assert params["source_sentence_end"] == 7


@pytest.mark.asyncio
async def test_bfs_query_maps_records_to_triples():
    doc_id = uuid4()
    driver = FakeDriver(records=[
        FakeRecord(
            subject="A",
            subject_type="概念",
            rel_type="CAUSES",
            verb="導致",
            object="B",
            object_type="概念",
            confidence=3,
            source_doc_id=str(doc_id),
            source_svo_chunk_index=1,
            source_svo_chunk_file="svo-chunk-001-of-001.md",
            source_sentence_start=1,
            source_sentence_end=2,
        )
    ])

    triples = await svc.bfs_query(driver, uuid4(), ["A"], hops=2)

    assert len(triples) == 1
    assert triples[0].source_doc_id == doc_id
    assert triples[0].source_sentence_start == 1
