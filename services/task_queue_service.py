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

Traceability: 02 §2.4.1 -> 03 §3.1.2 -> 04 §4.6.
Project: SQLite queue and recovery state machine are this project's own engineering
design; no external queue project is claimed as a direct implementation source.
Tests: tests/services/test_task_queue_service.py.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal

from services import document_record_service
from services.svo_chunking import read_svo_index

logger = logging.getLogger(__name__)

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
    清單；已存在且仍在進行中的 (kg_id, source, chunk_index) 組合
    （`processing`／`pending_upload`）會被保留、不覆寫（避免重複登記把
    已在處理中的 Chunk 誤重置回 pending）。

    ⚠️ **2026-08-25 修復（真實排查發現）**：已存在但停在**終態**
    （`completed`／`failed`）的組合，先前用 `INSERT OR IGNORE` 會被完全
    忽略、狀態永遠卡在舊值——`knowledge_graph_service.build_graph(force_rebuild=True)`
    明確承諾「完整重跑 CHUNKREADY」（清空該 KG 的 Neo4j 圖譜節點＋重設
    記錄檔進度），但 `trigger_extraction()` 隨後呼叫本函式時傳入的仍是同一批
    `(kg_id, source, chunk_index)`，這批組合在 `task_queue.db` 裡因為第一次
    抽取早已標記 `completed`，重新登記被靜默忽略，Worker 因此永遠不會重新
    處理——圖譜資料被清空、佇列卻認為「已完成」，導致重建後看似成功實則
    完全沒有真正重跑抽取，且無任何錯誤訊息。改為 UPSERT：狀態為終態時才
    重置回 `pending`，`processing`／`pending_upload` 仍維持原本的保護不變。
    """
    with closing(_connect(db_path)) as conn:
        conn.executemany(
            """
            INSERT INTO task_queue (kg_id, source, chunk_index, status)
            VALUES (?, ?, ?, 'pending')
            ON CONFLICT (kg_id, source, chunk_index) DO UPDATE SET
                status = 'pending', updated_at = datetime('now')
            WHERE task_queue.status IN ('completed', 'failed')
            """,
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


def reset_stuck_processing(db_path: Path) -> list[tuple[str, str, int]]:
    """中斷處理（3.1.2「中斷處理」註記）：程式重啟時，把所有卡在
    `processing`（當機/強制關閉時未能轉為終態）的 Chunk 批次重置為
    `pending`，視為未完成、可重新處理，而非誤判為進行中而跳過。

    回傳被重置的 `(kg_id, source, chunk_index)` 清單（2026-08-31，見
    `docs/報告/21_抽取管線稽核與修正報告.md`）——這些 chunk 中斷前可能已
    對 Neo4j 寫入部分三元組（`merge_triples_to_graph()` 逐筆 `await`、非
    整個 chunk 一個交易），重新處理前應由呼叫端（`main.py::_restart_task_queue()`）
    對每一筆呼叫 `svo_service.revoke_chunk_facts()` 清理殘留資料，避免
    Fact 節點與 citations 重複。原本只回傳筆數（`int`），呼叫端無從得知
    是哪些 chunk、無法針對性清理，此為稽核發現的真實風險，非單純介面調整。
    """
    with closing(_connect(db_path)) as conn:
        cursor = conn.execute(
            "SELECT kg_id, source, chunk_index FROM task_queue WHERE status = 'processing'"
        )
        affected = [(row[0], row[1], row[2]) for row in cursor.fetchall()]
        conn.execute("UPDATE task_queue SET status = 'pending' WHERE status = 'processing'")
        conn.commit()
        return affected


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
    為 `completed` 的文件不需要登記任何 pending chunk；其餘優先讀取
    `svo_index.json` 裡實際存在的 chunk_index 清單（而非用範圍推算連續
    範圍——部份文件的 svo chunk index 並非從 1 開始連續編號，用推算範圍
    會查到不存在的 index，導致 worker 的 `_find_chunk()` 誤判為失敗，
    2026-08-04 實測發現），過濾出尚未完成的部份登記為 `pending`（`processing`
    狀態的 chunk 在記錄檔真實狀態來源裡本來就無法與「已中斷」區分，直接
    視為未完成，與 `reset_stuck_processing` 對同一問題的處理精神一致）。

    ⚠️ **`svo_index.json` 缺席時退回範圍推算（2026-08-18 訂正，修復
    2026-08-04 引入的迴歸）**：`REBUILD` 本身就是「索引檔案已遺失/損毀」
    才會觸發的救援路徑——若 `svo_index.json` 這份索引檔案剛好也在同一次
    事故中缺席（例如較舊的文件、或磁碟事故同時波及多個檔案），2026-08-04
    的版本會直接靜默跳過整份文件，救援路徑本身反而造成待處理進度悄悄消失，
    與 `REBUILD` 存在的目的矛盾。改為此時退回範圍推算並記錄警告——寧可
    誤登記幾個實際不存在的 index（worker 端 `_find_chunk()` 找不到時視為
    `failed`，可重試，非資料損毀等級的風險），也不要靜默漏掉整份文件。

    ✅ **「尚未完成」判斷改依 `completed_chunk_indices` 集合（2026-08-19，
    真實審查發現並修復）**：原本用 `chunk["index"] > record.chunk_progress`
    篩選——`chunk_progress` 只是「看過的最大 index」，若中間某個 chunk 失敗、
    但編號更大的 chunk 之後成功，`chunk_progress` 會被推高，導致這個篩選
    誤判失敗的那個 chunk「已完成」（因為它的 index 小於 chunk_progress），
    REBUILD 永遠不會把它重新排入佇列，等同永久遺失，與 `record_chunk_completed()`
    同一根因（見該函式 docstring）。改用 `not in record.completed_chunk_indices`
    （集合成員判斷，不看大小關係），不論完成順序都能正確識別出真正尚未完成
    的 chunk；`svo_index.json` 缺席的範圍推算分支同樣改用集合排除，不再假設
    「只有結尾部分未完成」。
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

                completed = set(record.completed_chunk_indices)
                svo_index = read_svo_index(doc_folder)
                if svo_index is not None:
                    pending_indices = [
                        chunk["index"] for chunk in svo_index["chunks"]
                        if chunk["index"] not in completed
                    ]
                else:
                    logger.warning(
                        "REBUILD：%s 缺少 svo_index.json，退回 1..total 範圍推算"
                        "（排除已知完成的 chunk_index，可能誤登記不存在的 index，"
                        "worker 端會視為 failed 並可重試，非資料遺失）",
                        doc_folder,
                    )
                    total = record.svo_total_chunks or record.total_chunks
                    pending_indices = (
                        [i for i in range(1, total + 1) if i not in completed] if total > 0 else []
                    )

                if not pending_indices:
                    continue
                conn.executemany(
                    "INSERT OR IGNORE INTO task_queue (kg_id, source, chunk_index, status) "
                    "VALUES (?, ?, ?, 'pending')",
                    [(kg_id, record.source, idx) for idx in pending_indices],
                )
        conn.commit()


def ensure_ready(db_path: Path, kg_folders: dict[str, Path]) -> list[tuple[str, str, int]]:
    """`RESTART` 分支入口：程式重啟／電腦開機時呼叫——索引可信就地重置卡住的
    `processing`；不可信則整份 `REBUILD`。呼叫後 `task_queue.db` 保證可查詢。

    回傳被 `reset_stuck_processing()` 重置的 `(kg_id, source, chunk_index)`
    清單，供呼叫端清理這些 chunk 在 Neo4j 裡可能殘留的部分寫入（見該函式
    docstring）。`REBUILD` 分支回傳空清單——`rebuild_from_records()` 是從
    記錄檔重建索引，無法像 `reset_stuck_processing()` 一樣精確得知哪些
    chunk 中斷於寫入中途（記錄檔只區分「已完成」與「未完成」，不記錄
    「中斷於哪個階段」），這是 `REBUILD` 這條救援路徑本身既有的資訊侷限，
    不在本次修正範圍內。
    """
    if is_index_trustworthy(db_path):
        return reset_stuck_processing(db_path)
    rebuild_from_records(db_path, kg_folders)
    return []
