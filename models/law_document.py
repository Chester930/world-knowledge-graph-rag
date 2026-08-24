"""``Document``／``LawArticle`` 節點模型，對應
``docs/論文/03_系統設計與方法論.md`` § 3.5「文件／法條層級的時序錨定」。

與既有 ``models/document.py::Document``（``routers/documents.py`` 一般文件
上傳功能使用的模型）無關——那組模型完全不同的用途，且目前尚未寫入 Neo4j
（``DocumentRepository`` 仍是 ``NotImplementedError`` stub）。此處另外命名為
``LawDocument``／``LawArticle`` 避免與既有 ``Document`` 類別混淆；Neo4j
label 本身仍依設計文件為 ``Document``／``LawArticle``。

Traceability: 03 §3.5 -> 04（實作中）。
Project: 本專案自有的節點層設計，不是外部文獻/開源專案的直接程式依賴。
"""
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class LawDocumentCreate(BaseModel):
    kg_id: UUID
    source_doc_id: UUID
    source: str
    title: str
    record_type: str
    content_hash: str
    update_date: str | None = None
    effective_date: str | None = None
    effective_note: str | None = None
    source_url: str | None = None


class LawDocument(LawDocumentCreate):
    """``LawDocumentRepository.merge_document()`` 的回傳型別，欄位與
    ``LawDocumentCreate`` 相同（MERGE 後直接回傳輸入值，不含衍生欄位）。"""


class LawArticleCreate(BaseModel):
    kg_id: UUID
    source_doc_id: UUID
    article_no: str
    article_content: str
    chapter_title: str | None = None


class LawArticle(LawArticleCreate):
    """``LawDocumentRepository.merge_law_articles()`` 的回傳型別。"""
