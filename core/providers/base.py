from __future__ import annotations
from abc import ABC, abstractmethod
from typing import AsyncIterator


class LLMProvider(ABC):
    """LLM 統一介面，所有 provider 必須實作 generate 與 stream。"""

    @abstractmethod
    async def generate(self, prompt: str) -> str:
        """一次性生成回應，回傳完整字串。"""

    @abstractmethod
    async def stream(self, prompt: str) -> AsyncIterator[str]:
        """串流生成，逐 token yield 字串。"""

    async def generate_json(self, prompt: str) -> str:
        """強制 JSON 輸出模式，預設 fallback 至 generate（子類別可覆寫）。"""
        return await self.generate(prompt)


class EmbeddingProvider(ABC):
    """Embedding 統一介面，所有 provider 必須實作 encode、dim 與 model_name。

    `encode`／`encode_batch` 為 `async def`（2026-08-04 改造，見
    docs/論文/03_系統設計與方法論.md § 3.1.3「事件迴圈阻塞」誠實聲明）：
    改造前為同步方法，`OllamaEmbeddingProvider` 內部用同步 `httpx.post()`
    做網路 I/O，在 `services/svo_service.py` 抽取熱路徑（`SIM`／`DEDUP4`／
    3.1.4 §a Fact 節點）逐一同步呼叫時會整段凍結 asyncio event loop，導致
    共用同一 event loop 的其他背景任務（抽取 Worker、治理 Worker、FastAPI
    請求）暫時無法被排程——此問題在 `backfill_entity_name_embeddings()`
    因單次迴圈呼叫次數多而先被實際觸發並診斷出來（見 `EXTRACTION_LOG.md`），
    但同一根因存在於所有呼叫點，非該函式獨有。改為 `async def` 後，
    I/O-bound provider（Ollama／OpenAI）改用真正的非阻塞非同步 I/O
    （`httpx.AsyncClient`／`AsyncOpenAI`，與 `core/providers/llm/` 既有模式
    一致），CPU-bound 的 `LocalEmbeddingProvider` 則用
    `loop.run_in_executor()` 把阻塞運算丟到執行緒池，兩種情況下呼叫端
    `await` 期間都會正常讓出 event loop。與既有 `LLMProvider.generate()`
    早已是 `async def` 的介面風格一致，修正了原本兩個 Provider 抽象類別
    非同步性不對稱的設計不一致。
    """

    @property
    @abstractmethod
    def dim(self) -> int:
        """向量維度，建立 Neo4j vector index 時使用。"""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """實際使用的模型名稱，供 core.embedding_guard 記錄與比對，
        避免執行期切換 provider/model 卻沿用舊向量索引而不自知。"""

    @abstractmethod
    async def encode(self, text: str) -> list[float]:
        """將單一文字編碼為向量。"""

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """批次編碼，預設逐一呼叫 encode；provider 可覆寫以提升效率。"""
        return [await self.encode(t) for t in texts]
