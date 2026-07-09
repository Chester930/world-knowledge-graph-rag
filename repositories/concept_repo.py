from __future__ import annotations
import logging
from neo4j import AsyncDriver

from core.constants import VECTOR_DIM

logger = logging.getLogger(__name__)


class ConceptRepository:
    """ConceptNode 路由層存取。

    TODO(v2 架構重整)：v1 的路由演算法（cosine × alignment × magnitude 加權、
    圖拓撲共嵌入融合）待重新設計後於此實作，設計紀錄見 docs/ARCHITECTURE.md。
    """

    def __init__(self, driver: AsyncDriver):
        self.driver = driver

    async def create_vector_index(self, dim: int = VECTOR_DIM) -> None:
        await self.driver.execute_query(
            """
            CREATE VECTOR INDEX concept_q_vector IF NOT EXISTS
            FOR (c:ConceptNode) ON c.q_vector
            OPTIONS { indexConfig: { `vector.dimensions`: $dim, `vector.similarity_function`: 'cosine' } }
            """,
            dim=dim,
        )

    async def vector_search_concept_ids(self, query_vector: list[float], top_k: int) -> list[str]:
        """向量索引 KNN 粗篩，回傳最相近的 ConceptNode id 清單。"""
        result = await self.driver.execute_query(
            """
            CALL db.index.vector.queryNodes('concept_q_vector', $top_k, $vector)
            YIELD node RETURN node.id AS id
            """,
            top_k=top_k,
            vector=query_vector,
        )
        return [r["id"] for r in result.records]
