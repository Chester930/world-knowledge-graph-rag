"""``GraphSchemaPort``：圖儲存的 DDL／索引群介面（報告161 §2.1 P-A；報告164 V1 第一步）。

**只宣告介面與值物件，只依賴標準庫**（不得 import ``services``／``repositories``／``routers``）。
方法只包含「現有程式已有忠實對應函式」者，轉接層（``services/graph_store/neo4j_schema.py``）逐一委派、不複製邏輯：

- ``ensure_entity_uniqueness``           ← ``svo_service.create_entity_index``
- ``ensure_vector_index(spec)``          ← 6 種目標各自的既有 ``create_*_vector_index``
- ``ensure_fulltext_index(spec)``        ← ``create_entity_name_fulltext_index``／``create_fact_fulltext_index``
- ``migrate_vector_indexes``             ← ``core.vector_migration.migrate_vector_indexes``
- ``check_embedding_meta``               ← ``core.embedding_guard.check_and_register``

報告161 草案中的 ``list_vector_indexes``／``drop_indexes``／``read_embedding_meta``／``register_embedding_meta``、
以及多資料庫管理三方法，本輪**不納入**（前者現有程式沒有可忠實委派的單一函式；後者無測試、部分無呼叫者）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Protocol, Sequence, runtime_checkable
from uuid import UUID


class VectorTarget(str, Enum):
    """現有 6 種向量索引目標。"""

    CHUNK_EMBEDDING = "chunk_embedding"          # Chunk.embedding
    ENTITY_NAME = "entity_name"                  # Entity.name_embedding
    FACT = "fact"                                # Fact_<kg>.fact_embedding（per-KG 動態標籤）
    SENTENCE = "sentence"                        # Sentence_<kg>.sentence_embedding（per-KG 動態標籤）
    RELATED_TO_VERB = "related_to_verb"          # RELATED_TO 關係的 verb_embedding（關係屬性索引）
    CONCEPT = "concept"                          # ConceptNode.q_vector


class FulltextTarget(str, Enum):
    ENTITY_NAME = "entity_name"                  # Entity.name
    FACT = "fact"                                # Fact_<kg>.fact_text（per-KG 動態標籤）


_PER_KG_VECTOR = {VectorTarget.FACT, VectorTarget.SENTENCE}


@dataclass(frozen=True)
class VectorIndexSpec:
    """向量索引規格。``FACT``／``SENTENCE`` 為 per-KG 標籤，必須帶 ``kg_id``；其餘不得帶。"""

    target: VectorTarget
    dim: int | None = None  # None＝沿用既有函式的預設維度
    kg_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.dim is not None and self.dim < 1:
            raise ValueError("向量維度必須為正整數")
        needs_kg = self.target in _PER_KG_VECTOR
        if needs_kg and self.kg_id is None:
            raise ValueError(f"{self.target.value} 索引需要 kg_id")
        if not needs_kg and self.kg_id is not None:
            raise ValueError(f"{self.target.value} 索引不接受 kg_id")


@dataclass(frozen=True)
class FulltextIndexSpec:
    target: FulltextTarget
    kg_id: UUID | None = None

    def __post_init__(self) -> None:
        needs_kg = self.target is FulltextTarget.FACT
        if needs_kg and self.kg_id is None:
            raise ValueError("fact 全文索引需要 kg_id")
        if not needs_kg and self.kg_id is not None:
            raise ValueError(f"{self.target.value} 全文索引不接受 kg_id")


@dataclass(frozen=True)
class EmbeddingMeta:
    """啟動時登記／比對的 embedding 設定。"""

    provider: str
    model_name: str
    dim: int


@runtime_checkable
class GraphSchemaPort(Protocol):
    """圖儲存 schema（約束／索引）操作。所有方法皆冪等或可重複呼叫（沿用既有函式語意）。"""

    async def ensure_entity_uniqueness(self) -> None: ...

    async def ensure_vector_index(self, spec: VectorIndexSpec) -> None: ...

    async def ensure_fulltext_index(self, spec: FulltextIndexSpec) -> None: ...

    async def migrate_vector_indexes(
        self, *, dim: int | None = None, obsolete_index_names: Iterable[str] = ()
    ) -> Sequence[str]:
        """刪除維度不符或已退役的向量索引，回傳被刪除的索引名稱（沿用既有函式語意）。"""
        ...

    async def check_embedding_meta(self, meta: EmbeddingMeta) -> None:
        """首次啟動登記；已有記錄且不一致時拋出既有的 ``EmbeddingProviderMismatchError``。"""
        ...
