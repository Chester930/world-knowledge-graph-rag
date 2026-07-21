"""文件資料夾記錄檔讀寫（歸屬歷史／抽取進度狀態機）。

對應 docs/論文/03_系統設計與方法論.md § 3.1.1／3.1.2：每份文件資料夾內都有一份
`_record.json`，是隨資料夾一起搬移的真實狀態來源——記錄這份文件曾被分配到哪些
知識圖譜（歸屬歷史），以及目前的抽取進度。`task_queue.db`（3.1.2，尚未實作）僅作為
背景 Worker 的效能索引，需與此記錄檔保持同步，不是唯一的狀態來源。

本模組只負責 3.1.1 範圍內的職責：初始化記錄檔、追加歸屬歷史。抽取狀態機的
pending/processing/completed/failed/pending_upload 轉換（3.1.2）由後續實作的
抽取任務佇列負責，不在此模組內處理。
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID

from models.knowledge_graph import AssignmentHistoryEntry, DocumentRecord

_RECORD_FILENAME = "_record.json"


def _record_path(folder: Path) -> Path:
    return Path(folder) / _RECORD_FILENAME


def _write_record(folder: Path, record: DocumentRecord) -> None:
    """原子寫入記錄檔：先寫暫存檔再 os.replace()，避免程式在寫入中途中斷
    （斷電、強制關閉）留下截斷的 JSON，導致下次讀取時記錄遺失。"""
    path = _record_path(folder)
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{_RECORD_FILENAME}.", suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(record.model_dump_json(indent=2))
        os.replace(tmp_name, path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def read_record(folder: Path) -> DocumentRecord | None:
    """讀取文件資料夾內的記錄檔；不存在時回傳 None。"""
    path = _record_path(folder)
    if not path.exists():
        return None
    return DocumentRecord(**json.loads(path.read_text(encoding="utf-8")))


def init_record(folder: Path, source: str, total_chunks: int = 0) -> DocumentRecord:
    """初始化文件資料夾的記錄檔。

    若記錄檔已存在（例如文件內容更新後重新解析），**不會**覆蓋既有的歸屬歷史與
    抽取進度，只更新 `total_chunks`（切塊數可能因內容變動而改變），直接回傳既有
    記錄——重新解析不應該抹除這份文件曾經歷過的歸屬/抽取狀態。
    """
    existing = read_record(folder)
    if existing is not None:
        if existing.total_chunks != total_chunks:
            existing.total_chunks = total_chunks
            # 切塊數改變代表文件內容已重新解析，先前快取的 document_vector 不再
            # 代表目前內容，必須一併清空，否則分類分數會用到過期向量而不自知。
            existing.document_vector = None
            existing.normalization_status = "not_started"
            existing.normalization_progress = 0
            existing.normalization_total_sentences = 0
            existing.svo_total_chunks = 0
            _write_record(folder, existing)
        return existing

    record = DocumentRecord(source=source, total_chunks=total_chunks)
    _write_record(folder, record)
    return record


def set_document_vector(folder: Path, vector: list[float]) -> DocumentRecord | None:
    """快取文件代表向量到記錄檔，避免每次分類都重新呼叫 embedding provider。

    記錄檔不存在時（例如尚未經過 init_record 的暫時性資料夾）不建立新記錄、
    直接跳過快取，只計算不持久化——快取是效能優化，不應該讓呼叫端多一個
    「必須先初始化記錄檔才能算向量」的隱性前提。
    """
    record = read_record(folder)
    if record is None:
        return None
    record.document_vector = vector
    _write_record(folder, record)
    return record


def update_normalization_progress(
    folder: Path,
    *,
    status: Literal["not_started", "processing", "completed", "failed"],
    progress: int,
    total_sentences: int | None = None,
) -> DocumentRecord | None:
    """更新標準化前處理 checkpoint。

    標準化是文件級一次性前處理，與後續 SVO chunk 五態抽取佇列分開追蹤。
    """
    if progress < 0:
        raise ValueError("progress 不可為負數")
    if total_sentences is not None and total_sentences < 0:
        raise ValueError("total_sentences 不可為負數")

    record = read_record(folder)
    if record is None:
        return None

    if total_sentences is not None:
        record.normalization_total_sentences = total_sentences
    if record.normalization_total_sentences and progress > record.normalization_total_sentences:
        raise ValueError("progress 不可大於 normalization_total_sentences")

    record.normalization_status = status
    record.normalization_progress = progress
    _write_record(folder, record)
    return record


def set_svo_chunk_total(folder: Path, total_chunks: int) -> DocumentRecord | None:
    """記錄 SVO 專用 chunk 數，與 RAG total_chunks 分開保存。"""
    if total_chunks < 0:
        raise ValueError("total_chunks 不可為負數")
    record = read_record(folder)
    if record is None:
        return None
    record.svo_total_chunks = total_chunks
    _write_record(folder, record)
    return record


def append_assignment(
    folder: Path,
    kg_id: UUID,
    kg_name: str,
    method: Literal["manual", "auto", "ai_cluster"],
) -> DocumentRecord:
    """追加一筆歸屬歷史，代表這份文件資料夾被（重新）分配到某個 KG。

    依 § 3.1.2 已定案的重新歸屬策略：無論這是第一次歸檔還是重新歸屬，抽取狀態一律
    重設為 `pending`、chunk 進度歸零——對新 KG 完整重新抽取，不沿用舊 KG 的抽取
    結果；舊 KG 內已合併的三元組原封不動保留，不由本模組處理遷移或刪除。
    """
    record = read_record(folder)
    if record is None:
        record = DocumentRecord(source=folder.name)

    record.assignment_history.append(AssignmentHistoryEntry(
        kg_id=kg_id,
        kg_name=kg_name,
        method=method,
        assigned_at=datetime.now(timezone.utc),
    ))
    record.extraction_status = "pending"
    record.chunk_progress = 0

    _write_record(folder, record)
    return record
