"""評測專用的 embedding 持久化快取包裝器。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.providers.base import EmbeddingProvider


class CachingEmbeddingProvider(EmbeddingProvider):
    """以 model name 與文字 hash 為鍵，快取評測用 embedding 結果。

    這個 wrapper 只由離線評測 harness opt-in 使用；底層 provider 的介面與
    metadata 直接保留，快取檔採單一 JSON 文件以便跨 subprocess 共用。
    """

    def __init__(self, inner: EmbeddingProvider, cache_path: str | Path):
        self._inner = inner
        self._cache_path = Path(cache_path)
        self._cache = self._load_cache()

    @property
    def dim(self) -> int:
        return self._inner.dim

    @property
    def model_name(self) -> str:
        return self._inner.model_name

    def _load_cache(self) -> dict[str, dict[str, list[float]]]:
        if not self._cache_path.exists():
            return {}
        payload = json.loads(self._cache_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"embedding cache 必須是 JSON object：{self._cache_path}")
        return payload

    @staticmethod
    def _text_key(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _model_cache(self) -> dict[str, list[float]]:
        return self._cache.setdefault(self.model_name, {})

    def _persist(self) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(
            json.dumps(self._cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    async def encode(self, text: str) -> list[float]:
        model_cache = self._model_cache()
        key = self._text_key(text)
        if key in model_cache:
            return model_cache[key]

        vector = await self._inner.encode(text)
        model_cache[key] = vector
        self._persist()
        return vector

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        model_cache = self._model_cache()
        keys = [self._text_key(text) for text in texts]
        missing_texts: list[str] = []
        missing_keys: list[str] = []
        seen_missing: set[str] = set()
        for text, key in zip(texts, keys):
            if key not in model_cache and key not in seen_missing:
                missing_texts.append(text)
                missing_keys.append(key)
                seen_missing.add(key)

        if missing_texts:
            vectors = await self._inner.encode_batch(missing_texts)
            if len(vectors) != len(missing_keys):
                raise ValueError(
                    "embedding provider 回傳的 batch 長度與輸入不一致"
                )
            model_cache.update(zip(missing_keys, vectors))
            self._persist()

        return [model_cache[key] for key in keys]

