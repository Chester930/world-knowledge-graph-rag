from __future__ import annotations
import json
import logging
from typing import AsyncIterator

import httpx

from core.providers.base import LLMProvider

logger = logging.getLogger(__name__)


class OllamaLLMProvider(LLMProvider):
    def __init__(self, base_url: str, model: str, num_predict: int = 4096):
        self.base_url = base_url.rstrip("/")
        self.model = model
        # 報告37 Bug1：SVO 抽取走 generate_json（Ollama format=json），輸出被
        # 語法約束成合法 JSON——但 generation 一旦在 num_predict 處停止，JSON
        # 沒收尾就回傳，`json.loads` 撞 "Unterminated string"／"Expecting
        # delimiter"。13 款列舉條文 chunk 的抽取 JSON 常 >1024 token（舊值），
        # 全新 KG 重抽的 9 個 failed chunk 有 8 個是這個。預設拉到 4096；可用
        # `OLLAMA_LLM_NUM_PREDICT` 覆寫。
        self._num_predict = num_predict

    # RAG prompt 通常 8000-20000 字元，需要足夠的 context window
    _NUM_CTX = 8192

    # `seed`（2026-08-31，見 docs/報告/20_抽取數值忠實性核對機制設計報告.md
    # §2／§7）：`temperature=0.0` 不保證 Ollama 推論本身是決定性的（根因是
    # 批次大小依賴，非取樣隨機性，見報告20引用的 Horace He 2025 分析）——
    # 固定 seed 無法完全解決這個問題，但零成本、沒有理由不加，屬既有防護
    # 之外的額外一層。
    _SEED = 0

    # 報告37 Bug2：超大法規（如勞動基準法）單一 chunk 的抽取 JSON 生成
    # 可能超過 300s（N0030001 c11 撞 httpx.ReadTimeout）。拉到 600s。
    _TIMEOUT = 600.0

    async def generate(self, prompt: str) -> str:
        async with httpx.AsyncClient(timeout=self._TIMEOUT) as client:
            res = await client.post(
                f"{self.base_url}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False,
                      "options": {"num_ctx": self._NUM_CTX, "temperature": 0.0,
                                  "num_predict": self._num_predict, "seed": self._SEED}},
            )
            res.raise_for_status()
            return res.json().get("response", "")

    async def generate_json(self, prompt: str) -> str:
        """使用 Ollama format=json 模式，強制輸出合法 JSON。"""
        async with httpx.AsyncClient(timeout=self._TIMEOUT) as client:
            res = await client.post(
                f"{self.base_url}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False,
                      "format": "json", "options": {"num_ctx": self._NUM_CTX, "temperature": 0.0,
                                                     "num_predict": self._num_predict, "seed": self._SEED}},
            )
            res.raise_for_status()
            return res.json().get("response", "")

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        async with httpx.AsyncClient(timeout=self._TIMEOUT) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": True,
                      "options": {"num_ctx": self._NUM_CTX}},
            ) as r:
                async for line in r.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if token := data.get("response"):
                            yield token
                        if data.get("done"):
                            return
                    except json.JSONDecodeError:
                        continue
