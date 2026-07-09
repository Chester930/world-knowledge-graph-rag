"""暫存區文件分類（比對各 KG ConceptNode，建議或自動分配歸屬）。

TODO(v2 架構重整)：v1 的分類門檻與自動分配邏輯待重新設計後遷移。
"""
from __future__ import annotations

from models.knowledge_graph import ClassifyResult


async def classify_all(threshold: float = 0.3, auto_assign: bool = False) -> list[ClassifyResult]:
    raise NotImplementedError
