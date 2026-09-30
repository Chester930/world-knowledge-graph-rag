"""``GraphSchemaPort`` 的 Neo4j 轉接層：**逐一委派**既有函式，不複製邏輯（報告164 V1）。

每個方法在**呼叫當下**以模組屬性查找被委派的函式（``svo_service.create_*`` 等），因此測試可用 spy／monkeypatch 驗證
「呼叫了同一個既有函式、相同引數」。既有函式的簽名、行為、錯誤處理皆不改；例外原樣向上傳遞。
"""

from __future__ import annotations

from typing import Iterable, Sequence

from core import embedding_guard, vector_migration
from core.ports.graph_schema import (
    EmbeddingMeta,
    FulltextIndexSpec,
    FulltextTarget,
    VectorIndexSpec,
    VectorTarget,
)
from repositories.concept_repo import ConceptRepository
from services import svo_service


class Neo4jGraphSchema:
    """以 ``neo4j.AsyncDriver`` 實作 ``GraphSchemaPort``。"""

    def __init__(self, driver) -> None:
        self._driver = driver

    async def ensure_entity_uniqueness(self) -> None:
        await svo_service.create_entity_index(self._driver)

    async def ensure_vector_index(self, spec: VectorIndexSpec) -> None:
        dim_kw = {} if spec.dim is None else {"dim": spec.dim}  # None＝沿用既有函式的預設維度
        target = spec.target
        if target is VectorTarget.CHUNK_EMBEDDING:
            await svo_service.create_chunk_vector_index(self._driver, **dim_kw)
        elif target is VectorTarget.ENTITY_NAME:
            await svo_service.create_entity_name_vector_index(self._driver, **dim_kw)
        elif target is VectorTarget.FACT:
            await svo_service.create_fact_vector_index(self._driver, spec.kg_id, **dim_kw)
        elif target is VectorTarget.SENTENCE:
            await svo_service.create_sentence_vector_index(self._driver, spec.kg_id, **dim_kw)
        elif target is VectorTarget.RELATED_TO_VERB:
            await svo_service.create_related_to_vector_index(self._driver, **dim_kw)
        elif target is VectorTarget.CONCEPT:
            await ConceptRepository(self._driver).create_vector_index(**dim_kw)
        else:  # pragma: no cover - Enum 已窮舉
            raise ValueError(f"未知的向量索引目標：{target}")

    async def ensure_fulltext_index(self, spec: FulltextIndexSpec) -> None:
        if spec.target is FulltextTarget.ENTITY_NAME:
            await svo_service.create_entity_name_fulltext_index(self._driver)
        elif spec.target is FulltextTarget.FACT:
            await svo_service.create_fact_fulltext_index(self._driver, spec.kg_id)
        else:  # pragma: no cover
            raise ValueError(f"未知的全文索引目標：{spec.target}")

    async def migrate_vector_indexes(
        self, *, dim: int | None = None, obsolete_index_names: Iterable[str] = ()
    ) -> Sequence[str]:
        dim_kw = {} if dim is None else {"dim": dim}
        return await vector_migration.migrate_vector_indexes(
            self._driver, obsolete_index_names=obsolete_index_names, **dim_kw
        )

    async def check_embedding_meta(self, meta: EmbeddingMeta) -> None:
        await embedding_guard.check_and_register(self._driver, meta.provider, meta.model_name, meta.dim)
