"""N4 的關係型別 embedding 比對與仲裁（報告160 U1 自 ``services.svo_service`` 搬入，行為不變）。"""
from __future__ import annotations

from core.constants import SVO_REL_TYPE_DESCRIPTIONS
from core.providers.base import EmbeddingProvider
from services.classify_service import cosine_similarity

# SIM 節點的型別描述句 embedding 快取——model 與完整描述集合共同組成 key，
# 避免不同 domain pack 的 KG 在同一個 provider/model 下互相汙染結果。
_TYPE_DESCRIPTION_EMBEDDING_CACHE: dict[
    tuple[str, tuple[tuple[str, str], ...]], dict[str, list[float]]
] = {}


async def _type_description_embeddings(
    embedding_provider: EmbeddingProvider,
    descriptions: dict[str, str] | None = None,
) -> dict[str, list[float]]:
    description_map = SVO_REL_TYPE_DESCRIPTIONS if descriptions is None else descriptions
    description_items = tuple(sorted(description_map.items()))
    cache_key = (embedding_provider.model_name, description_items)
    cache = _TYPE_DESCRIPTION_EMBEDDING_CACHE.get(cache_key)
    if cache is None:
        vectors = await embedding_provider.encode_batch([description for _, description in description_items])
        cache = dict(zip((name for name, _ in description_items), vectors))
        _TYPE_DESCRIPTION_EMBEDDING_CACHE[cache_key] = cache
    return cache


async def classify_relation_by_embedding(
    verb: str,
    embedding_provider: EmbeddingProvider,
    descriptions: dict[str, str] | None = None,
) -> tuple[str, float]:
    """SIM：`verb` embedding 與 35 個關係型別**描述句**（非識別碼字串本身，見
    `SVO_REL_TYPE_DESCRIPTIONS` docstring）embedding 算 cosine 相似度，取最相似者。
    回傳 (最相似的型別, 該型別的相似度分數)。"""
    type_vectors = await _type_description_embeddings(embedding_provider, descriptions)
    verb_vec = await embedding_provider.encode(verb)
    best_type = ""
    best_score = -1.0
    for rel_type, vec in type_vectors.items():
        score = cosine_similarity(verb_vec, vec)
        if score > best_score:
            best_score = score
            best_type = rel_type
    return best_type, best_score
