"""3.1.3 節「`SIM` 學習/校正機制」的持久化。

對應 docs/論文/03_系統設計與方法論.md § 3.1.3「`SIM` 學習/校正機制與畢業
路徑」：每次 `ESCALATE3` 實際觸發仲裁時記錄一筆事件，供逐型別計算
`SIM` 建議與最終判定的一致率——比照 3.1.3 §a `GATE` 節點
（`expand_governance_service.recent_agreement_rate()`）沿用的 Bloodgood &
Vijay-Shanker（2009）／Bloodgood & Grothendieck（2013）Kappa 穩定度停止
準則精神。與 `task_queue.db` 共用同一份 SQLite 檔案，比照
`task_queue_service.py`／`expand_governance_service.py` 既有慣例。

只記錄真正觸發 `ESCALATE3` 的事件——`COMPARE` 一致、未升級仲裁的情況沒有
「最終仲裁結果」可比對，不需要記錄，這是既有的選擇性標籤（selective
labeling）限制，非本模組疏漏。
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS escalate3_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kg_id TEXT NOT NULL,
    rel_type_llm TEXT NOT NULL,
    rel_type_sim TEXT NOT NULL,
    sim_score REAL NOT NULL,
    rel_type_final TEXT NOT NULL,
    logged_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_escalate3_log_sim_type ON escalate3_log (rel_type_sim);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA)
    return conn


def log_escalation(
    db_path: Path,
    kg_id: str,
    rel_type_llm: str,
    rel_type_sim: str,
    sim_score: float,
    rel_type_final: str,
) -> None:
    """`ESCALATE3` 實際觸發時記錄一筆仲裁事件：`LLM_SVO` 自報值、`SIM`
    建議值與其 cosine 分數、最終仲裁結果。供 `sim_agreement_rate()` 計算
    各型別「`SIM` 建議與最終判定一致」的比例，逐步校正對 `SIM` 的信任度。
    """
    with closing(_connect(db_path)) as conn:
        conn.execute(
            "INSERT INTO escalate3_log "
            "(kg_id, rel_type_llm, rel_type_sim, sim_score, rel_type_final) "
            "VALUES (?, ?, ?, ?, ?)",
            (kg_id, rel_type_llm, rel_type_sim, sim_score, rel_type_final),
        )
        conn.commit()


def sim_agreement_rate(db_path: Path, rel_type_sim: str, window: int) -> float | None:
    """該關係型別（`SIM` 建議值）最近 `window` 筆 `ESCALATE3` 仲裁事件中，
    最終判定與 `SIM` 建議一致的比例——比照 `expand_governance_service.
    recent_agreement_rate()` 的 Kappa 穩定度停止準則精神。比例穩定夠高，
    代表 `SIM` 對這個型別的判斷可信度已追上甚至超過 `LLM_SVO` 自報，是
    「`SIM` 畢業」（見設計文件）的量化依據。候選數不足 `window` 時回傳
    `None`，代表尚無法計算穩定的一致率。
    """
    with closing(_connect(db_path)) as conn:
        rows = conn.execute(
            # 用 id（自增主鍵）而非 logged_at 排序——logged_at 只有秒級精度，
            # 短時間內連續寫入會撞期，id 才能可靠反映真正的插入順序。
            "SELECT rel_type_final FROM escalate3_log WHERE rel_type_sim = ? "
            "ORDER BY id DESC LIMIT ?",
            (rel_type_sim, window),
        ).fetchall()
    if len(rows) < window:
        return None
    agreed = sum(1 for (final,) in rows if final == rel_type_sim)
    return agreed / window
