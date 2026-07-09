from __future__ import annotations
from uuid import UUID
from neo4j import AsyncDriver

from models.document import Document, DocumentCreate


class DocumentRepository:
    """Document 節點 CRUD。

    TODO(v2 架構重整)：Cypher 查詢待依重新設計的 schema 實作。
    """

    def __init__(self, driver: AsyncDriver):
        self.driver = driver

    async def create(self, doc: DocumentCreate) -> Document:
        raise NotImplementedError

    async def get(self, doc_id: UUID) -> Document | None:
        raise NotImplementedError

    async def list_by_kg(self, kg_id: UUID) -> list[Document]:
        raise NotImplementedError

    async def delete(self, doc_id: UUID) -> None:
        raise NotImplementedError
