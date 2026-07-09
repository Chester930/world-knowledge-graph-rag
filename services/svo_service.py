"""SVO 三元組提取、Neo4j MERGE、BFS 查詢。

TODO(v2 架構重整)：v1 的 SVO 提取 prompt、跨文件實體 MERGE、
自我精煉迴圈（低信心補充 chunk）待重新設計後遷移。
"""
from __future__ import annotations
from uuid import UUID

from neo4j import AsyncDriver

from models.knowledge_graph import SVOTriple


async def create_entity_index() -> None:
    """建立 Entity 節點索引（app 啟動時呼叫一次）。"""
    raise NotImplementedError


async def extract_svo_triples(text: str) -> list[SVOTriple]:
    raise NotImplementedError


async def merge_triples_to_graph(driver: AsyncDriver, kg_id: UUID, triples: list[SVOTriple]) -> None:
    raise NotImplementedError


async def bfs_query(driver: AsyncDriver, kg_id: UUID, seed_entities: list[str], hops: int = 2) -> list[SVOTriple]:
    raise NotImplementedError
