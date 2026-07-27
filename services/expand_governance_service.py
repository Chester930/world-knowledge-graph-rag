"""3.1.3 §a `EXPAND` 治理機制的候選池／跨 KG 關係型別登記表持久化。

對應 docs/論文/03_系統設計與方法論.md § 3.1.3 §a 決策脈絡第 5／6 點：候選池
與跨 KG 登記表併入 `task_queue.db` 同一份共用 SQLite 檔案（新增資料表，非
另開獨立 db），比照 `task_queue_service.py` 既有慣例。本模組只負責資料表
的儲存與查詢，不判斷 `POOLSIZE`／`CLUSTER`／`LLMJUDGE`／`GATE` 等治理邏輯
本身——那是治理 Worker（尚未實作，見 §a 決策脈絡第 5 點）的責任。
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from services.classify_service import cosine_similarity

_SCHEMA = """
CREATE TABLE IF NOT EXISTS expand_pool (
    kg_id TEXT NOT NULL,
    verb TEXT NOT NULL,
    verb_embedding TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (kg_id, verb)
);
CREATE INDEX IF NOT EXISTS idx_expand_pool_status ON expand_pool (kg_id, status);

CREATE TABLE IF NOT EXISTS expand_registry (
    type_name TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    description_embedding TEXT NOT NULL,
    approved_by_kg_id TEXT NOT NULL,
    approved_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA)
    return conn


def add_candidate(db_path: Path, kg_id: str, verb: str, verb_embedding: list[float]) -> None:
    """POOL：候選動詞加入該 KG 的 `EXPAND` 候選池。

    主鍵 `(kg_id, verb)` 刻意去重——已存在時不新增列，只遞增
    `occurrence_count` 並把狀態「復活」回 `pending`（即使先前是
    `discarded`），理由見設計文件誠實聲明：同一動詞未來若再被觸發，隨語料
    累積可能真的湊出有意義的群集，不永久拉黑。
    """
    with closing(_connect(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO expand_pool (kg_id, verb, verb_embedding)
            VALUES (?, ?, ?)
            ON CONFLICT (kg_id, verb) DO UPDATE SET
                status = 'pending',
                occurrence_count = occurrence_count + 1,
                last_seen_at = datetime('now')
            """,
            (kg_id, verb, json.dumps(verb_embedding)),
        )
        conn.commit()


def pool_size(db_path: Path, kg_id: str) -> int:
    """POOLSIZE：候選池內相異、狀態為 `pending` 的候選數（不含 `discarded`／
    `committed`），供治理 Worker 判斷是否達到 `EXPAND_POOL_MIN_SIZE`。"""
    with closing(_connect(db_path)) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM expand_pool WHERE kg_id = ? AND status = 'pending'",
            (kg_id,),
        ).fetchone()
        return row[0]


def pending_candidates(db_path: Path, kg_id: str) -> list[dict]:
    """CLUSTER 的輸入：該 KG 目前所有 `pending` 候選（還原 `verb_embedding`
    為 list[float]，供 HDBSCAN 分群直接使用）。"""
    with closing(_connect(db_path)) as conn:
        rows = conn.execute(
            "SELECT verb, verb_embedding, occurrence_count FROM expand_pool "
            "WHERE kg_id = ? AND status = 'pending'",
            (kg_id,),
        ).fetchall()
    return [
        {"verb": verb, "verb_embedding": json.loads(embedding), "occurrence_count": count}
        for verb, embedding, count in rows
    ]


def mark_discarded(db_path: Path, kg_id: str, verbs: list[str]) -> None:
    """LLMJUDGE 判定「非真正新類別」（`DISCARD` 分支）：狀態改為
    `discarded`，排除在未來 `POOLSIZE`／`CLUSTER` 之外，但保留列（不刪除）
    以支援 `add_candidate()` 之後的自動復活。"""
    if not verbs:
        return
    with closing(_connect(db_path)) as conn:
        conn.executemany(
            "UPDATE expand_pool SET status = 'discarded' WHERE kg_id = ? AND verb = ?",
            [(kg_id, verb) for verb in verbs],
        )
        conn.commit()


def mark_committed(db_path: Path, kg_id: str, verbs: list[str]) -> None:
    """COMMIT：候選群集核准為新型別後，該群集內的候選列標記為
    `committed`，同樣排除在未來 `POOLSIZE`／`CLUSTER` 之外。"""
    if not verbs:
        return
    with closing(_connect(db_path)) as conn:
        conn.executemany(
            "UPDATE expand_pool SET status = 'committed' WHERE kg_id = ? AND verb = ?",
            [(kg_id, verb) for verb in verbs],
        )
        conn.commit()


def register_type(
    db_path: Path,
    type_name: str,
    description: str,
    description_embedding: list[float],
    approved_by_kg_id: str,
) -> None:
    """COMMIT：新型別核准時寫入跨 KG 登記表。`type_name` 已存在時不覆寫
    （`REUSE` 分支代表其他 KG 沿用既有命名，不應改動原始核准來源）。"""
    with closing(_connect(db_path)) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO expand_registry "
            "(type_name, description, description_embedding, approved_by_kg_id) "
            "VALUES (?, ?, ?, ?)",
            (type_name, description, json.dumps(description_embedding), approved_by_kg_id),
        )
        conn.commit()


def find_similar_registered_type(
    db_path: Path, query_embedding: list[float], threshold: float
) -> tuple[str, float] | None:
    """REGCHECK：查詢跨 KG 登記表是否已有語意相近的已核准型別。比對
    `description_embedding`（非型別名稱字串本身），與 `SIM` 節點「比對描述句
    而非識別碼字串」的原則一致。回傳分數最高且 ≥ `threshold` 的
    `(type_name, score)`；皆不足門檻回傳 `None`（見主圖 `REGCHECK` 的
    「是／否」兩分支）。"""
    with closing(_connect(db_path)) as conn:
        rows = conn.execute(
            "SELECT type_name, description_embedding FROM expand_registry"
        ).fetchall()

    best_type: str | None = None
    best_score = -1.0
    for type_name, embedding_json in rows:
        score = cosine_similarity(query_embedding, json.loads(embedding_json))
        if score > best_score:
            best_score = score
            best_type = type_name

    if best_type is not None and best_score >= threshold:
        return best_type, best_score
    return None
