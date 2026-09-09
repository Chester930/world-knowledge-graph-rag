from __future__ import annotations
import logging

import httpx

from core.providers.base import EmbeddingProvider

logger = logging.getLogger(__name__)


class OllamaEmbeddingProvider(EmbeddingProvider):
    """使用 Ollama 本地模型（nomic-embed-text 等）產生 Embedding。"""

    def __init__(self, base_url: str, model: str, num_gpu: int | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        # 報告37 ②：`num_gpu` 非 None 時，把它塞進 Ollama 請求的 `options`
        # （`num_gpu=0` ＝ 該模型完全跑 CPU）。VRAM 受限機器可讓 embedding 模型
        # 讓出 GPU、生成模型獨佔，避免兩者互相逐出重載。None＝不帶此鍵，
        # 行為與先前完全一致。
        self._num_gpu = num_gpu
        self._dim = self._probe_dim()

    def _options(self) -> dict | None:
        return None if self._num_gpu is None else {"num_gpu": self._num_gpu}

    def _payload(self, prompt: str) -> dict:
        body: dict = {"model": self.model, "prompt": prompt}
        opts = self._options()
        if opts is not None:
            body["options"] = opts
        return body

    def _probe_dim(self) -> int:
        try:
            res = httpx.post(
                f"{self.base_url}/api/embeddings",
                json=self._payload("dim probe"),
                timeout=30.0,
            )
            res.raise_for_status()
            return len(res.json()["embedding"])
        except Exception as e:
            logger.warning(f"OllamaEmbedding 維度探測失敗，預設 768：{e}")
            return 768

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def model_name(self) -> str:
        return self.model

    async def encode(self, text: str) -> list[float]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.post(
                f"{self.base_url}/api/embeddings",
                json=self._payload(text),
            )
            res.raise_for_status()
            return res.json()["embedding"]
