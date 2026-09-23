from __future__ import annotations

import json

import pytest

from core.providers.base import EmbeddingProvider
from scripts.eval.embedding_cache import CachingEmbeddingProvider


class _CountingEmbeddingProvider(EmbeddingProvider):
    def __init__(self, model_name: str = "fake-model"):
        self._model_name = model_name
        self.encode_calls: list[str] = []
        self.batch_calls: list[list[str]] = []

    @property
    def dim(self) -> int:
        return 2

    @property
    def model_name(self) -> str:
        return self._model_name

    async def encode(self, text: str) -> list[float]:
        self.encode_calls.append(text)
        return [float(len(text)), 1.0]

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        self.batch_calls.append(list(texts))
        return [[float(len(text)), 2.0] for text in texts]


@pytest.mark.asyncio
async def test_encode_miss_then_hit_calls_inner_once(tmp_path):
    inner = _CountingEmbeddingProvider()
    cached = CachingEmbeddingProvider(inner, tmp_path / "embeddings.json")

    assert await cached.encode("問題一") == await cached.encode("問題一")
    assert inner.encode_calls == ["問題一"]


@pytest.mark.asyncio
async def test_encode_batch_only_sends_uncached_unique_texts_to_inner(tmp_path):
    inner = _CountingEmbeddingProvider()
    cached = CachingEmbeddingProvider(inner, tmp_path / "embeddings.json")
    await cached.encode("已快取")
    inner.batch_calls.clear()

    result = await cached.encode_batch(["已快取", "新文字", "新文字", "另一文字"])

    assert result == [[3.0, 1.0], [3.0, 2.0], [3.0, 2.0], [4.0, 2.0]]
    assert inner.encode_calls == ["已快取"]
    assert inner.batch_calls == [["新文字", "另一文字"]]


@pytest.mark.asyncio
async def test_cache_persists_across_provider_instances(tmp_path):
    cache_path = tmp_path / "embeddings.json"
    first_inner = _CountingEmbeddingProvider()
    await CachingEmbeddingProvider(first_inner, cache_path).encode("跨程序題目")

    second_inner = _CountingEmbeddingProvider()
    result = await CachingEmbeddingProvider(second_inner, cache_path).encode("跨程序題目")

    assert result == [5.0, 1.0]
    assert second_inner.encode_calls == []
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert set(payload) == {"fake-model"}
    assert len(payload["fake-model"]) == 1


@pytest.mark.asyncio
async def test_different_model_names_do_not_share_vectors(tmp_path):
    cache_path = tmp_path / "embeddings.json"
    first_inner = _CountingEmbeddingProvider("model-a")
    await CachingEmbeddingProvider(first_inner, cache_path).encode("同一文字")

    second_inner = _CountingEmbeddingProvider("model-b")
    result = await CachingEmbeddingProvider(second_inner, cache_path).encode("同一文字")

    assert result == [4.0, 1.0]
    assert second_inner.encode_calls == ["同一文字"]
