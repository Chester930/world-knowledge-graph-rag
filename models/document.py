from __future__ import annotations
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Literal


class DocumentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    # 20,000,000 字元上限（約可容納大型 PDF/DOCX 轉出的純文字），
    # 防止 JSON body 直接繞過檔案上傳路徑的大小限制塞入超大內容
    content: str = Field(..., min_length=1, max_length=20_000_000)
    file_path: str | None = None
    file_type: Literal["md", "txt", "pdf", "manual"] = "manual"
    kg_id: UUID | None = None  # 建立後自動關聯到指定 KG


class Document(BaseModel):
    id: UUID
    title: str
    content: str
    file_path: str | None = None
    file_type: str
    created_at: datetime
    updated_at: datetime


class SearchRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    top_k: int = Field(default=10, ge=1, le=50)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)


class SearchResult(BaseModel):
    document: Document
    score: float
    matched_concepts: list[str]


class ChatMessage(BaseModel):
    role: str    # "user" | "assistant"
    content: str = Field(..., max_length=20_000)


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    # 語意 Fact 檢索（`vector_search_facts()`）取回的候選筆數。預設 20：與
    # 報告23 §3.4 事實清單截斷值 `_FACT_LINE_TRUNCATE_K=18` 及 LangChain
    # `EmbeddingsFilter` 預設 k=20 對齊——先前預設 5 遠低於截斷值，排序／
    # 截斷／重排邏輯實際上永遠拿不到足夠候選（報告25 §4 發現1：Q8 三項
    # 答案事實都在庫且有 embedding，卻因 top-5 未涵蓋而完全沒進 prompt，
    # 且連鎖觸發 `_relevant_doc_ids_from_facts()` 把 BFS 結果一併濾掉）。
    # `le` 由 10 放寬到 50，對齊 `SearchRequest.top_k`。
    top_k: int = Field(default=20, ge=1, le=50)
    max_chars_per_doc: int = Field(default=2000, ge=500, le=12000)
    use_svo: bool = True
    # 報告27 L0（2026-09-04）：預設由 2 改為 1。`bfs_query()` 現把 `svo_hops`
    # 當「最大允許跳數」，一律先跑 1-hop，去重後少於門檻才擴展到 2..svo_hops。
    # 共用高頻實體當種子時 2-hop 會組合爆炸（報告26 §4 #4：Q5/6/7 各
    # 330–440 秒）；報告26 Q6 證實好種子的 1-hop 即足以接到答案並正確歸因。
    svo_hops: int = Field(default=1, ge=1, le=3)
    history: list[ChatMessage] | None = Field(default=None, max_length=50)
    kg_id: UUID | None = None  # 指定時強制路由到此 KG，跳過全域路由
