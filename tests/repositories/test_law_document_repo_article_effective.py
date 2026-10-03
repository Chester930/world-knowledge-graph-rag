from types import SimpleNamespace
from uuid import uuid4

import pytest

from repositories.law_document_repo import LawDocumentRepository


class _RecordingDriver:
    def __init__(self, records=()):
        self.records = list(records)
        self.calls: list[tuple[str, dict]] = []

    async def execute_query(self, query: str, **params):
        self.calls.append((query, params))
        return SimpleNamespace(records=self.records)


@pytest.mark.asyncio
async def test_article_nos_for_evidence_empty_keys_do_not_query():
    driver = _RecordingDriver()
    result = await LawDocumentRepository(driver).article_nos_for_evidence(uuid4(), [])
    assert result == {}
    assert driver.calls == []


@pytest.mark.asyncio
async def test_article_nos_for_evidence_groups_duplicates_warns_and_uses_minimum(caplog):
    driver = _RecordingDriver([
        {"source_doc_id": "doc-a", "chunk": 7, "article_no": "第 58 條"},
        {"source_doc_id": "doc-a", "chunk": 7, "article_no": "第 57 條"},
        {"source_doc_id": "doc-b", "chunk": 2, "article_no": "第 3 條"},
    ])
    kg_id = uuid4()

    with caplog.at_level("WARNING"):
        result = await LawDocumentRepository(driver).article_nos_for_evidence(
            kg_id, [("doc-a", 7), ("doc-b", 2)]
        )

    assert result == {
        ("doc-a", 7): "第 57 條",
        ("doc-b", 2): "第 3 條",
    }
    assert any("多個條號" in record.message for record in caplog.records)
    assert len(driver.calls) == 1
    query, params = driver.calls[0]
    assert params["kg_id"] == str(kg_id)
    assert params["keys"] == [
        {"source_doc_id": "doc-a", "chunk": 7},
        {"source_doc_id": "doc-b", "chunk": 2},
    ]
    assert all(token not in query.upper() for token in ("SET", "CREATE", "MERGE", "DELETE", "REMOVE", "CALL"))
    assert "kg_id" in query


@pytest.mark.asyncio
async def test_list_article_nos_returns_sorted_numbers_without_article_content():
    driver = _RecordingDriver([
        {"article_no": "第 12 條"},
        {"article_no": "第 3 條"},
    ])
    kg_id, doc_id = uuid4(), uuid4()

    result = await LawDocumentRepository(driver).list_article_nos(kg_id, doc_id)

    assert result == ["第 12 條", "第 3 條"]
    assert len(driver.calls) == 1
    query, params = driver.calls[0]
    assert params == {"kg_id": str(kg_id), "source_doc_id": str(doc_id)}
    assert "article_content" not in query
    assert "kg_id" in query
