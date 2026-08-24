"""``Document``／``LawArticle`` 節點 repository，對應
``docs/論文/03_系統設計與方法論.md`` § 3.5「文件／法條層級的時序錨定」。

新增的節點層，不觸及既有 ``Fact``／``Chunk``／``SUPPORTED_BY`` 機制——依
2026-08-24「實作範圍定案」，``Fact.SUPPORTED_BY`` 暫維持指向 ``Chunk``，
本 repository 與 ``services/svo_service.py`` 完全不共用查詢路徑。

Traceability: 03 §3.5 -> 04（實作中）。
Project: 本專案自有的節點層設計，不是外部文獻/開源專案的直接程式依賴。
"""
from __future__ import annotations

from uuid import UUID

from neo4j import AsyncDriver

from models.law_document import LawArticle, LawArticleCreate, LawDocument, LawDocumentCreate


class LawDocumentRepository:
    def __init__(self, driver: AsyncDriver):
        self.driver = driver

    async def merge_document(self, doc: LawDocumentCreate) -> LawDocument:
        """MERGE ``(:Document {kg_id, source_doc_id})``，冪等——同一
        ``source_doc_id`` 重複呼叫只更新屬性，不建立重複節點，支援匯入腳本
        重跑／增量更新。"""
        await self.driver.execute_query(
            """
            MERGE (d:Document {kg_id: $kg_id, source_doc_id: $source_doc_id})
            SET d.source = $source,
                d.title = $title,
                d.record_type = $record_type,
                d.content_hash = $content_hash,
                d.update_date = $update_date,
                d.effective_date = $effective_date,
                d.effective_note = $effective_note,
                d.source_url = $source_url
            """,
            kg_id=str(doc.kg_id),
            source_doc_id=str(doc.source_doc_id),
            source=doc.source,
            title=doc.title,
            record_type=doc.record_type,
            content_hash=doc.content_hash,
            update_date=doc.update_date,
            effective_date=doc.effective_date,
            effective_note=doc.effective_note,
            source_url=doc.source_url,
        )
        return LawDocument(**doc.model_dump())

    async def merge_law_articles(self, articles: list[LawArticleCreate]) -> list[LawArticle]:
        """批次 MERGE ``(:LawArticle {kg_id, source_doc_id, article_no})`` 並連結
        ``[:PART_OF]->(:Document)``。

        呼叫前必須已對同一 ``source_doc_id`` 呼叫過 ``merge_document()``——
        Cypher 查詢以 ``MATCH (d:Document ...)`` 起頭，`Document` 節點不存在時
        ``MATCH`` 找不到任何列，後續 ``UNWIND``／``MERGE`` 整批都不會執行，
        不會有孤兒 ``LawArticle``（無 ``PART_OF`` 邊）留在圖中。空清單直接
        回傳空 list，不發出查詢。
        """
        if not articles:
            return []
        kg_id = str(articles[0].kg_id)
        source_doc_id = str(articles[0].source_doc_id)
        rows = [
            {
                "article_no": a.article_no,
                "article_content": a.article_content,
                "chapter_title": a.chapter_title,
            }
            for a in articles
        ]
        await self.driver.execute_query(
            """
            MATCH (d:Document {kg_id: $kg_id, source_doc_id: $source_doc_id})
            UNWIND $rows AS row
            MERGE (a:LawArticle {kg_id: $kg_id, source_doc_id: $source_doc_id, article_no: row.article_no})
            SET a.article_content = row.article_content,
                a.chapter_title = row.chapter_title
            MERGE (a)-[:PART_OF]->(d)
            """,
            kg_id=kg_id,
            source_doc_id=source_doc_id,
            rows=rows,
        )
        return list(articles)

    async def get_document(self, kg_id: UUID, source_doc_id: UUID) -> LawDocument | None:
        """查無資料回傳 ``None``（比照 ``repositories/kg_repo.py::get()`` 既有
        慣例），供匯入腳本／測試驗證用。"""
        result = await self.driver.execute_query(
            "MATCH (d:Document {kg_id: $kg_id, source_doc_id: $source_doc_id}) RETURN d",
            kg_id=str(kg_id),
            source_doc_id=str(source_doc_id),
        )
        if not result.records:
            return None
        props = dict(result.records[0]["d"])
        return LawDocument(
            kg_id=kg_id,
            source_doc_id=source_doc_id,
            source=props["source"],
            title=props["title"],
            record_type=props["record_type"],
            content_hash=props["content_hash"],
            update_date=props.get("update_date"),
            effective_date=props.get("effective_date"),
            effective_note=props.get("effective_note"),
            source_url=props.get("source_url"),
        )

    async def list_law_articles(self, kg_id: UUID, source_doc_id: UUID) -> list[LawArticle]:
        """依 ``article_no`` 字面排序回傳（Neo4j 不保證插入順序，供匯入腳本／
        測試驗證用；非給定順序即法規正式的條號排序，若需嚴格條號排序需另外
        依數值解析 ``article_no``，非本次範圍）。"""
        result = await self.driver.execute_query(
            """
            MATCH (a:LawArticle {kg_id: $kg_id, source_doc_id: $source_doc_id})
            RETURN a ORDER BY a.article_no
            """,
            kg_id=str(kg_id),
            source_doc_id=str(source_doc_id),
        )
        return [
            LawArticle(
                kg_id=kg_id,
                source_doc_id=source_doc_id,
                article_no=props["article_no"],
                article_content=props["article_content"],
                chapter_title=props.get("chapter_title"),
            )
            for record in result.records
            for props in [dict(record["a"])]
        ]
