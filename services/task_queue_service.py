"""SVO 抽取任務佇列的效能索引（`task_queue.db`，SQLite）。

對應 docs/論文/03_系統設計與方法論.md § 3.1.2：文件資料夾內的記錄檔
（`_record.json`，見 `services/document_record_service.py`）才是真實狀態
來源；本模組是背景 Worker 用來快速排隊、挑選下一個待處理 Chunk 的**效能
索引**，與記錄檔保持同步——即使本模組管理的 SQLite 檔案遺失或損毀，仍可
透過 `rebuild_from_records()` 掃描各 KG 資料夾下每份文件的記錄檔重建索引，
不會真的遺失狀態。

五態狀態機（`pending`／`processing`／`completed`／`failed`／`pending_upload`）
的定義與轉換時機由 3.1.2/3.1.3/3.1.4 統一負責，本模組只負責狀態的儲存與
查詢，不判斷該不該轉換。
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal

from services import document_record_service

TaskStatus = Literal["pending", "processing", "completed", "failed", "pending_upload"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_queue (
    kg_id TEXT NOT NULL,
    source TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (kg_id, source, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_task_queue_status ON task_queue (kg_id, status, chunk_index);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA)
    return conn


def enqueue(db_path: Path, kg_id: str, source: str, chunk_indices: list[int]) -> None:
    """`ENQUEUE`：登記尚未完成的 Chunk 進佇列，初始狀態一律為 `pending`。

    呼叫端依記錄檔的 `chunk_progress` 進度，只傳入尚未完成的 `chunk_index`
    清單；已存在的 (kg_id, source, chunk_index) 組合會被忽略，不會覆蓋既有
    狀態（避免重複登記把已在處理中的 Chunk 誤重置回 pending）。
    """
    with closing(_connect(db_path)) as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO task_queue (kg_id, source, chunk_index, status) "
            "VALUES (?, ?, ?, 'pending')",
            [(kg_id, source, idx) for idx in chunk_indices],
        )
        conn.commit()


def update_status(
    db_path: Path, kg_id: str, source: str, chunk_index: int, status: TaskStatus
) -> None:
    """更新單一 Chunk 的狀態——三態轉換的實際時機分屬 3.1.3（`processing`）
    ／3.1.3 抽取結果（`pending_upload`／`failed`）／3.1.4 寫入結果
    （`completed`），本函式只負責寫入，不判斷轉換時機是否合法。"""
    with closing(_connect(db_path)) as conn:
        conn.execute(
            "UPDATE task_queue SET status = ?, updated_at = datetime('now') "
            "WHERE kg_id = ? AND source = ? AND chunk_index = ?",
            (status, kg_id, source, chunk_index),
        )
        conn.commit()


def next_pending(db_path: Path, kg_id: str | None = None) -> tuple[str, str, int] | None:
    """`WORKER`：挑出下一個待處理 Chunk（依 `chunk_index` 由小到大），
    回傳 `(kg_id, source, chunk_index)`；沒有待處理項目時回傳 `None`。

    `kg_id` 為 `None` 時跨所有 KG 查詢——3.1.2 本身未規定跨 KG 的排序政策
    （這屬於已取代的滑動視窗草案才討論過的問題，見 `03_變更紀錄.md`），
    此處先以 `chunk_index` 為唯一排序依據，跨 KG 公平排程政策留待第四章
    實作時視實際 Worker 架構再決定，非本模組需要解決的問題。
    """
    query = "SELECT kg_id, source, chunk_index FROM task_queue WHERE status = 'pending'"
    params: tuple = ()
    if kg_id is not None:
        query += " AND kg_id = ?"
        params = (kg_id,)
    query += " ORDER BY chunk_index ASC LIMIT 1"

    with closing(_connect(db_path)) as conn:
        row = conn.execute(query, params).fetchone()
        return (row[0], row[1], row[2]) if row else None


def reset_stuck_processing(db_path: Path) -> int:
    """中斷處理（3.1.2「中斷處理」註記）：程式重啟時，把所有卡在
    `processing`（當機/強制關閉時未能轉為終態）的 Chunk 批次重置為
    `pending`，視為未完成、可重新處理，而非誤判為進行中而跳過。回傳受
    影響的筆數。"""
    with closing(_connect(db_path)) as conn:
        cursor = conn.execute("UPDATE task_queue SET status = 'pending' WHERE status = 'processing'")
        conn.commit()
        return cursor.rowcount


def is_index_trustworthy(db_path: Path) -> bool:
    """`TRUST`：索引檔案存在且可正常查詢即視為可信；檔案不存在，或已損毀
    （無法解析為合法 SQLite 資料庫），視為不可信，需要 `REBUILD`。"""
    if not db_path.exists():
        return False
    try:
        with closing(sqlite3.connect(str(db_path))) as conn:
            conn.execute("SELECT 1 FROM task_queue LIMIT 1")
        return True
    except sqlite3.DatabaseError:
        return False


def rebuild_from_records(db_path: Path, kg_folders: dict[str, Path]) -> None:
    """`REBUILD`：索引遺失/損毀時，改為掃描各 KG 資料夾下每份文件的記錄檔
    重建索引，取代原本可能已損毀的索引檔案。

    `kg_folders` 為 `{kg_id: KG 資料夾路徑}`。重建規則：`extraction_status`
    為 `completed` 的文件不需要登記任何 pending chunk；其餘依
    `chunk_progress`／`svo_total_chunks` 推算尚未完成的 chunk_index 範圍，
    一律登記為 `pending`（`processing` 狀態的 chunk 在記錄檔真實狀態來源
    裡本來就無法與「已中斷」區分，直接視為未完成，與 `reset_stuck_processing`
    對同一問題的處理精神一致）。
    """
    if db_path.exists():
        db_path.unlink()

    with closing(_connect(db_path)) as conn:
        for kg_id, kg_folder in kg_folders.items():
            if not kg_folder.is_dir():
                continue
            for doc_folder in kg_folder.iterdir():
                if not doc_folder.is_dir():
                    continue
                record = document_record_service.read_record(doc_folder)
                if record is None or record.extraction_status == "completed":
                    continue
                total = record.svo_total_chunks or record.total_chunks
                if total <= 0:
                    continue
                pending_indices = range(record.chunk_progress + 1, total + 1)
                conn.executemany(
                    "INSERT OR IGNORE INTO task_queue (kg_id, source, chunk_index, status) "
                    "VALUES (?, ?, ?, 'pending')",
                    [(kg_id, record.source, idx) for idx in pending_indices],
                )
        conn.commit()


def ensure_ready(db_path: Path, kg_folders: dict[str, Path]) -> None:
    """`RESTART` 分支入口：程式重啟／電腦開機時呼叫——索引可信就地重置卡住的
    `processing`；不可信則整份 `REBUILD`。呼叫後 `task_queue.db` 保證可查詢。
    """
    if is_index_trustworthy(db_path):
        reset_stuck_processing(db_path)
    else:
        rebuild_from_records(db_path, kg_folders)
