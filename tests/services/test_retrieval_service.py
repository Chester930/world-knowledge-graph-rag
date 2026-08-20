import json
from uuid import uuid4

import pytest

from parser.chunk_writer import document_folder_path
from services import retrieval_service as svc


class FakeResult:
    def __init__(self, records=None):
        self.records = records or []


class FakeDriver:
    def __init__(self, records=None):
        self.calls = []
        self.records = records or []

    async def execute_query(self, query: str, **params):
        self.calls.append((query, params))
        return FakeResult(self.records)


def _write_svo_index(kg_folder, source: str, chunks: list[dict]) -> None:
    doc_folder = document_folder_path(source, kg_folder)
    doc_folder.mkdir(parents=True, exist_ok=True)
    (doc_folder / "svo_index.json").write_text(
        json.dumps({"source": source, "total_svo_chunks": len(chunks), "chunks": chunks}),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_search_standardized_rag_expands_hit_to_chunk_text(tmp_path):
    driver = FakeDriver(records=[
        {"sentence_text": "馬斯克隨後研發了獵鷹火箭。", "source": "note.md",
         "chunk_index": 1, "source_doc_id": "doc-1", "score": 0.92},
    ])
    kg_id = uuid4()
    _write_svo_index(tmp_path, "note.md", [
        {"index": 1, "text": "馬斯克創立了太空公司。\n馬斯克隨後研發了獵鷹火箭。"},
    ])

    results = await svc.search_standardized_rag(driver, kg_id, tmp_path, [0.1, 0.2], top_k=5)

    assert results == [{
        "source": "note.md",
        "chunk_index": 1,
        "matched_sentence": "馬斯克隨後研發了獵鷹火箭。",
        "chunk_text": "馬斯克創立了太空公司。\n馬斯克隨後研發了獵鷹火箭。",
        "score": 0.92,
    }]


@pytest.mark.asyncio
async def test_search_standardized_rag_dedupes_same_chunk_keeping_highest_score(tmp_path):
    """同一 chunk 內相鄰句子可能同時命中——見 retrieval_service.py docstring，
    只保留分數最高的一句，不讓 top_k 名額被同一 chunk 的多個句子佔掉。"""
    driver = FakeDriver(records=[
        {"sentence_text": "第一句。", "source": "note.md", "chunk_index": 1,
         "source_doc_id": "doc-1", "score": 0.80},
        {"sentence_text": "第二句（分數較高）。", "source": "note.md", "chunk_index": 1,
         "source_doc_id": "doc-1", "score": 0.91},
        {"sentence_text": "不同 chunk 的句子。", "source": "note.md", "chunk_index": 2,
         "source_doc_id": "doc-1", "score": 0.85},
    ])
    kg_id = uuid4()
    _write_svo_index(tmp_path, "note.md", [
        {"index": 1, "text": "chunk 1 全文"},
        {"index": 2, "text": "chunk 2 全文"},
    ])

    results = await svc.search_standardized_rag(driver, kg_id, tmp_path, [0.1, 0.2], top_k=5)

    assert len(results) == 2  # chunk 1 的兩句收斂成一筆
    assert results[0]["matched_sentence"] == "第二句（分數較高）。"
    assert results[0]["score"] == 0.91
    assert results[1]["chunk_index"] == 2


@pytest.mark.asyncio
async def test_search_standardized_rag_truncates_to_top_k(tmp_path):
    records = [
        {"sentence_text": f"句子{i}", "source": "note.md", "chunk_index": i,
         "source_doc_id": "doc-1", "score": 1.0 - i * 0.01}
        for i in range(10)
    ]
    driver = FakeDriver(records=records)
    kg_id = uuid4()
    _write_svo_index(tmp_path, "note.md", [{"index": i, "text": f"chunk {i}"} for i in range(10)])

    results = await svc.search_standardized_rag(driver, kg_id, tmp_path, [0.1, 0.2], top_k=3)

    assert len(results) == 3
    assert [r["chunk_index"] for r in results] == [0, 1, 2]


@pytest.mark.asyncio
async def test_search_standardized_rag_empty_chunk_text_when_svo_index_missing(tmp_path):
    """`svo_index.json` 缺席時（防禦性情境）回傳空字串，不拋例外中斷整批查詢。"""
    driver = FakeDriver(records=[
        {"sentence_text": "命中句子。", "source": "missing-doc.md", "chunk_index": 1,
         "source_doc_id": "doc-1", "score": 0.9},
    ])
    kg_id = uuid4()

    results = await svc.search_standardized_rag(driver, kg_id, tmp_path, [0.1, 0.2], top_k=5)

    assert results[0]["chunk_text"] == ""


@pytest.mark.asyncio
async def test_search_standardized_rag_no_hits_returns_empty_list(tmp_path):
    driver = FakeDriver(records=[])
    kg_id = uuid4()

    results = await svc.search_standardized_rag(driver, kg_id, tmp_path, [0.1, 0.2], top_k=5)

    assert results == []
