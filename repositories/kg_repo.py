from __future__ import annotations
from uuid import UUID
from neo4j import AsyncDriver

from models.knowledge_graph import KnowledgeGraph, KnowledgeGraphCreate, KnowledgeGraphUpdate


class KGRepository:
    """KnowledgeGraph 節點 CRUD（主資料庫）。

    TODO(v2 架構重整)：Cypher 查詢待依重新設計的 schema 實作。
    """

    def __init__(self, driver: AsyncDriver):
        self.driver = driver

    async def create(self, kg: KnowledgeGraphCreate) -> KnowledgeGraph:
        raise NotImplementedError

    async def get(self, kg_id: UUID) -> KnowledgeGraph | None:
        raise NotImplementedError

    async def list_all(self) -> list[KnowledgeGraph]:
        raise NotImplementedError

    async def update(self, kg_id: UUID, patch: KnowledgeGraphUpdate) -> KnowledgeGraph:
        raise NotImplementedError

    async def delete(self, kg_id: UUID) -> None:
        raise NotImplementedError
