from __future__ import annotations
import asyncio
import logging

from core.providers.base import EmbeddingProvider

logger = logging.getLogger(__name__)


class LocalEmbeddingProvider(EmbeddingProvider):
    """sentence-transformers 本地 Embedding，完全離線。"""

    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer
        logger.info(f"載入本地 Embedding 模型：{model_name}")
        self._model_name = model_name
        self._model = SentenceTransformer(model_name)
        self._dim: int = self._model.get_sentence_embedding_dimension()
        logger.info(f"Embedding 模型載入完成，維度={self._dim}")

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def model_name(self) -> str:
        return self._model_name

    def _encode_sync(self, text: str) -> list[float]:
        return self._model.encode(text, normalize_embeddings=True).tolist()

    def _encode_batch_sync(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(texts, normalize_embeddings=True).tolist()

    async def encode(self, text: str) -> list[float]:
        """本地模型推論為 CPU-bound（非 I/O），改用執行緒池讓出 event loop
        （見 core/providers/base.py `EmbeddingProvider` docstring 的改造說明）。"""
        return await asyncio.get_running_loop().run_in_executor(None, self._encode_sync, text)

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.get_running_loop().run_in_executor(None, self._encode_batch_sync, texts)
