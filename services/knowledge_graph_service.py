"""KG 建立、自動分群、路由層刷新。

TODO(v2 架構重整)：v1 的暫存區自動分群（LLM 分析 + 命名建議）待重新設計後遷移。
"""
from __future__ import annotations
from uuid import UUID

from models.knowledge_graph import KnowledgeGraph, KnowledgeGraphCreate


async def create_kg(payload: KnowledgeGraphCreate) -> KnowledgeGraph:
    raise NotImplementedError


async def delete_kg(kg_id: UUID) -> None:
    raise NotImplementedError


async def build_graph(kg_id: UUID, force_rebuild: bool = False) -> None:
    raise NotImplementedError
