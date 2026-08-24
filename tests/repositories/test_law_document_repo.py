from uuid import uuid4

import pytest

from models.law_document import LawArticleCreate, LawDocumentCreate
from repositories.law_document_repo import LawDocumentRepository


class FakeResult:
    def __init__(self, records=None):
        self.records = records or []


class FakeLawDocumentDriver:
    """模擬 `Document`／`LawArticle` 節點與 `PART_OF` 邊，供
    `LawDocumentRepository` 測試使用——以字典模擬 Neo4j 節點儲存。"""

    def __init__(self):
        self._documents: dict[tuple[str, str], dict] = {}
        self._articles: dict[tuple[str, str, str], dict] = {}

    async def execute_query(self, query: str, **params):
        stripped = query.strip()
        if stripped.startswith("MERGE (d:Document"):
            key = (params["kg_id"], params["source_doc_id"])
            self._documents[key] = {
                "source": params["source"],
                "title": params["title"],
                "record_type": params["record_type"],
                "content_hash": params["content_hash"],
                "update_date": params["update_date"],
                "effective_date": params["effective_date"],
                "effective_note": params["effective_note"],
                "source_url": params["source_url"],
            }
            return FakeResult()
        if stripped.startswith("MATCH (d:Document {kg_id: $kg_id, source_doc_id: $source_doc_id})\n            UNWIND"):
            doc_key = (params["kg_id"], params["source_doc_id"])
            if doc_key not in self._documents:
                return FakeResult()  # MATCH 找不到節點，整批不執行（比照真實 Cypher 行為）
            for row in params["rows"]:
                art_key = (params["kg_id"], params["source_doc_id"], row["article_no"])
                self._articles[art_key] = {
                    "article_no": row["article_no"],
                    "article_content": row["article_content"],
                    "chapter_title": row["chapter_title"],
                }
            return FakeResult()
        if stripped == "MATCH (d:Document {kg_id: $kg_id, source_doc_id: $source_doc_id}) RETURN d":
            node = self._documents.get((params["kg_id"], params["source_doc_id"]))
            return FakeResult([{"d": dict(node)}] if node else [])
        if stripped.startswith("MATCH (a:LawArticle {kg_id: $kg_id, source_doc_id: $source_doc_id})"):
            matched = [
                v for k, v in self._articles.items()
                if k[0] == params["kg_id"] and k[1] == params["source_doc_id"]
            ]
            matched.sort(key=lambda a: a["article_no"])
            return FakeResult([{"a": dict(a)} for a in matched])
        raise AssertionError(f"未預期的查詢：{stripped}")


@pytest.mark.asyncio
async def test_merge_document_is_idempotent_and_readable_back():
    driver = FakeLawDocumentDriver()
    repo = LawDocumentRepository(driver)
    kg_id, source_doc_id = uuid4(), uuid4()
    doc = LawDocumentCreate(
        kg_id=kg_id, source_doc_id=source_doc_id, source="N0030001_勞動基準法",
        title="勞動基準法", record_type="law", content_hash="abc123",
        update_date="20240731", effective_date=None, effective_note=None,
        source_url="https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=N0030001",
    )

    await repo.merge_document(doc)
    await repo.merge_document(doc)  # 重跑冪等，不應報錯或建立第二筆

    fetched = await repo.get_document(kg_id, source_doc_id)
    assert fetched is not None
    assert fetched.title == "勞動基準法"
    assert fetched.effective_date is None
    assert fetched.source_url.endswith("pcode=N0030001")


@pytest.mark.asyncio
async def test_get_document_returns_none_when_missing():
    repo = LawDocumentRepository(FakeLawDocumentDriver())
    assert await repo.get_document(uuid4(), uuid4()) is None


@pytest.mark.asyncio
async def test_merge_law_articles_links_part_of_when_document_exists():
    driver = FakeLawDocumentDriver()
    repo = LawDocumentRepository(driver)
    kg_id, source_doc_id = uuid4(), uuid4()
    await repo.merge_document(LawDocumentCreate(
        kg_id=kg_id, source_doc_id=source_doc_id, source="N0030001_勞動基準法",
        title="勞動基準法", record_type="law", content_hash="abc123",
    ))

    articles = [
        LawArticleCreate(
            kg_id=kg_id, source_doc_id=source_doc_id,
            article_no="第 1 條", article_content="本法保障勞工權益。",
            chapter_title="第一章 總則",
        ),
        LawArticleCreate(
            kg_id=kg_id, source_doc_id=source_doc_id,
            article_no="第 2 條", article_content="本法定義如下。",
            chapter_title="第一章 總則",
        ),
    ]
    result = await repo.merge_law_articles(articles)
    assert len(result) == 2

    stored = await repo.list_law_articles(kg_id, source_doc_id)
    assert [a.article_no for a in stored] == ["第 1 條", "第 2 條"]
    assert stored[0].chapter_title == "第一章 總則"


@pytest.mark.asyncio
async def test_merge_law_articles_no_op_when_document_missing():
    """`Document` 節點不存在時，`MATCH` 找不到列，整批 `LawArticle` 都不會
    建立——不留孤兒節點（見 repository docstring）。"""
    driver = FakeLawDocumentDriver()
    repo = LawDocumentRepository(driver)
    kg_id, source_doc_id = uuid4(), uuid4()

    await repo.merge_law_articles([
        LawArticleCreate(
            kg_id=kg_id, source_doc_id=source_doc_id,
            article_no="第 1 條", article_content="本法保障勞工權益。",
        ),
    ])

    assert await repo.list_law_articles(kg_id, source_doc_id) == []


@pytest.mark.asyncio
async def test_merge_law_articles_empty_list_is_no_op():
    driver = FakeLawDocumentDriver()
    repo = LawDocumentRepository(driver)
    result = await repo.merge_law_articles([])
    assert result == []
