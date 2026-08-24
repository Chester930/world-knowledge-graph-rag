"""ConceptNode 路由層計算（問題概念提取 → KG 路由）。

TODO(v2 架構重整)：v1 的 cosine × alignment × magnitude 加權路由分數與
LRU 快取待重新設計後遷移。

Traceability: 02 §2.2.1／§2.4.2 -> 03 §3.2§a -> 04 §4.7.2.
RQ status: RQ2 design placeholder only. `route_kgs()` is intentionally not claimed
as an implemented ConceptNode router; the current chat path requires a single kg_id.
Project: semantic-router／namespace systems are architecture references, not direct
dependencies. Tests must not be interpreted as evidence of completed RQ2.
"""
from __future__ import annotations
from uuid import UUID


async def route_kgs(question: str, top_k: int = 5) -> list[UUID]:
    raise NotImplementedError
