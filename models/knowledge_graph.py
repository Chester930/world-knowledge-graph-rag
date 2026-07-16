from __future__ import annotations
from typing import Literal
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field


# ── KnowledgeGraph CRUD ───────────────────────────────────────────────────────

class KnowledgeGraphCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = ""
    is_public: bool = True


class KnowledgeGraphUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    is_public: bool | None = None


class KnowledgeGraph(BaseModel):
    id: UUID
    name: str
    description: str
    folder_path: str
    is_public: bool
    db_name: str = ""          # Neo4j 專用資料庫名稱（空白 = 使用主資料庫）
    doc_count: int = 0
    entity_count: int = 0
    relation_count: int = 0
    created_at: datetime
    updated_at: datetime


class KnowledgeGraphDetail(KnowledgeGraph):
    top_concepts: list[str] = []
    top_entities: list[str] = []


# ── 文件分配（暫存區自動分群）──────────────────────────────────────────────────

class KGCandidate(BaseModel):
    kg_id: UUID
    kg_name: str
    score: float
    top_matched_concepts: list[str] = []


class ClassifyRequest(BaseModel):
    threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    auto_assign: bool = False


class ClassifyResult(BaseModel):
    filename: str
    candidates: list[KGCandidate] = []
    matched_kg_id: UUID | None = None
    matched_kg_name: str | None = None
    score: float = 0.0
    auto_assigned: bool = False
    status: str = "pending"   # pending | assigned | unmatched


class AssignRequest(BaseModel):
    kg_id: UUID


# ── 文件資料夾記錄檔（歸屬歷史／抽取進度狀態機）─────────────────────────────────
# 對應 docs/論文/03_系統設計與方法論.md § 3.1.2：記錄檔是隨文件資料夾一起搬移的
# 真實狀態來源，task_queue.db（尚未實作）僅作為背景 Worker 的效能索引，需與此同步。

class AssignmentHistoryEntry(BaseModel):
    kg_id: UUID
    kg_name: str
    method: Literal["manual", "auto", "ai_cluster"]
    assigned_at: datetime


class DocumentRecord(BaseModel):
    source: str
    assignment_history: list[AssignmentHistoryEntry] = []
    # 抽取進度欄位由 3.1.2（抽取任務佇列）維護，3.1.1（歸檔）僅負責初始化與
    # 追加 assignment_history；重新歸屬時依 § 3.1.2 定案，狀態重設為 pending、
    # chunk 進度歸零，不沿用舊 KG 的抽取結果。
    extraction_status: Literal["pending", "processing", "completed", "failed", "pending_upload"] = "pending"
    chunk_progress: int = 0
    total_chunks: int = 0


# ── 暫存區 AI 自動分群（HDBSCAN + LLM 命名，見 § 3.1.1 §a）──────────────────────

class ClusterSuggestion(BaseModel):
    suggested_name: str
    suggested_description: str = ""
    # 整個候選分群的文件資料夾清單——使用者審核檔案清單時看到的完整名單
    candidate_folders: list[str]
    # 主導子群（Khandelwal 2025 Approach 3）篩選出、實際餵給 LLM 生成名稱的檔案，
    # 僅供命名依據參考，不代表候選分群本身的範圍
    naming_basis_folders: list[str] = []
    intra_similarity: float = 0.0


class ClusterAnalyzeResult(BaseModel):
    suggestions: list[ClusterSuggestion] = []
    unclustered_folders: list[str] = []  # 仍留在未分配池、未達 min_cluster_size 的文件


class ClusterConfirmRequest(BaseModel):
    """使用者確認建立新 KG 的請求——`REVIEWNAME`／`REVIEWFILES` 兩項獨立審核
    是前端 UX 層級的行為（各自可先微調再確認），但送出確認時合併為單一請求：
    名稱與檔案清單都可能已被使用者編輯過，不一定等於 `ClusterSuggestion` 原始
    提案的內容，後端不需要、也不會在兩次呼叫之間保存中間審核狀態。"""
    confirmed_name: str = Field(..., min_length=1, max_length=100)
    confirmed_description: str = ""
    confirmed_folders: list[str] = Field(..., min_length=1)


# ── SVO 知識層 ────────────────────────────────────────────────────────────────

class SVOTriple(BaseModel):
    subject: str
    subject_type: str = "概念"
    rel_type: str = "RELATED_TO"   # 語意關係類別，見 core/constants.py SVO_REL_TYPES
    verb: str                       # 原始動詞描述（保留自然語言）
    object: str
    object_type: str = "概念"
    confidence: int = 1
    source_doc_id: UUID | None = None


class BuildGraphRequest(BaseModel):
    doc_ids: list[UUID] | None = None
    force_rebuild: bool = False
