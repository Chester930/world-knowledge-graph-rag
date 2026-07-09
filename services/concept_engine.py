"""ConceptNode 路由層計算（問題概念提取 → KG 路由）。

TODO(v2 架構重整)：v1 的 cosine × alignment × magnitude 加權路由分數與
LRU 快取待重新設計後遷移。
"""
from __future__ import annotations
from uuid import UUID


async def route_kgs(question: str, top_k: int = 5) -> list[UUID]:
    raise NotImplementedError
