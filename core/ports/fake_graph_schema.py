"""``GraphSchemaPort`` 的記憶體假實作（供測試與日後節點獨立測試使用；只依賴標準庫）。"""

from __future__ import annotations

from typing import Iterable, Sequence

from core.ports.graph_schema import EmbeddingMeta, FulltextIndexSpec, VectorIndexSpec


class FakeGraphSchema:
    """記錄呼叫、維持簡單的記憶體狀態，不連任何資料庫。"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.vector_indexes: dict[tuple, int | None] = {}
        self.fulltext_indexes: set[tuple] = set()
        self.entity_uniqueness = False
        self.embedding_meta: EmbeddingMeta | None = None

    async def ensure_entity_uniqueness(self) -> None:
        self.calls.append(("entity_uniqueness",))
        self.entity_uniqueness = True

    async def ensure_vector_index(self, spec: VectorIndexSpec) -> None:
        self.calls.append(("vector", spec.target.value, spec.dim, spec.kg_id))
        self.vector_indexes[(spec.target, spec.kg_id)] = spec.dim

    async def ensure_fulltext_index(self, spec: FulltextIndexSpec) -> None:
        self.calls.append(("fulltext", spec.target.value, spec.kg_id))
        self.fulltext_indexes.add((spec.target, spec.kg_id))

    async def migrate_vector_indexes(
        self, *, dim: int | None = None, obsolete_index_names: Iterable[str] = ()
    ) -> Sequence[str]:
        obsolete = list(obsolete_index_names)
        self.calls.append(("migrate", dim, tuple(obsolete)))
        return obsolete

    async def check_embedding_meta(self, meta: EmbeddingMeta) -> None:
        self.calls.append(("embedding_meta", meta.provider, meta.model_name, meta.dim))
        if self.embedding_meta is None:
            self.embedding_meta = meta
        elif self.embedding_meta != meta:
            raise RuntimeError("embedding 設定與既有記錄不一致")
