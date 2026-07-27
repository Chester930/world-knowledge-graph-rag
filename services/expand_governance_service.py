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

CREATE TABLE IF NOT EXISTS expand_cluster_proposal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kg_id TEXT NOT NULL,
    member_verbs TEXT NOT NULL,
    suggested_type_name TEXT NOT NULL,
    suggested_description TEXT NOT NULL,
    reused_from_registry INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'awaiting_review',
    llm_judged_at TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_expand_proposal_status ON expand_cluster_proposal (kg_id, status);
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


def create_proposal(
    db_path: Path,
    kg_id: str,
    member_verbs: list[str],
    suggested_type_name: str,
    suggested_description: str,
    *,
    reused_from_registry: bool = False,
    auto_approved: bool = False,
) -> int:
    """`LLMJUDGE`／`REGCHECK` 判定出候選型別後，寫入一筆提案，回傳其 `id`。

    `GATE` 已畢業（`auto_approved=True`）時，狀態直接以 `auto_approved`
    建立、`resolved_at` 立刻蓋上時間戳——不進入 `awaiting_review`，因為根本
    沒有人工審核這一步，`recent_agreement_rate()` 也因此不會把這類提案納入
    一致率計算（見該函式 docstring）。否則預設 `awaiting_review`，等待
    `HUMANCHECK` 介面呼叫 `resolve_proposal()`。
    """
    with closing(_connect(db_path)) as conn:
        cursor = conn.execute(
            """
            INSERT INTO expand_cluster_proposal
                (kg_id, member_verbs, suggested_type_name, suggested_description,
                 reused_from_registry, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                kg_id,
                json.dumps(member_verbs, ensure_ascii=False),
                suggested_type_name,
                suggested_description,
                1 if reused_from_registry else 0,
                "auto_approved" if auto_approved else "awaiting_review",
            ),
        )
        proposal_id = cursor.lastrowid
        if auto_approved:
            conn.execute(
                "UPDATE expand_cluster_proposal SET resolved_at = datetime('now') WHERE id = ?",
                (proposal_id,),
            )
        conn.commit()
        return proposal_id


def _row_to_proposal(row: tuple) -> dict:
    (proposal_id, kg_id, member_verbs, suggested_type_name, suggested_description,
     reused_from_registry, status, llm_judged_at, resolved_at) = row
    return {
        "id": proposal_id,
        "kg_id": kg_id,
        "member_verbs": json.loads(member_verbs),
        "suggested_type_name": suggested_type_name,
        "suggested_description": suggested_description,
        "reused_from_registry": bool(reused_from_registry),
        "status": status,
        "llm_judged_at": llm_judged_at,
        "resolved_at": resolved_at,
    }


def get_proposal(db_path: Path, proposal_id: int) -> dict | None:
    """單筆提案查詢，供 `HUMANCHECK` 核准端點在呼叫 `resolve_proposal()`
    （只更新狀態、不回傳內容）之前，先取得觸發 `COMMIT`／`BACKFILL` 所需的
    完整內容（`kg_id`／`member_verbs`／`suggested_type_name` 等）。查無資料
    回傳 `None`，不拋例外，比照 `KGRepository.get()` 既有慣例。"""
    with closing(_connect(db_path)) as conn:
        row = conn.execute(
            "SELECT id, kg_id, member_verbs, suggested_type_name, suggested_description, "
            "reused_from_registry, status, llm_judged_at, resolved_at "
            "FROM expand_cluster_proposal WHERE id = ?",
            (proposal_id,),
        ).fetchone()
    return _row_to_proposal(row) if row else None


def list_awaiting_review(db_path: Path, kg_id: str | None = None) -> list[dict]:
    """`HUMANCHECK` 審核介面的資料來源：所有 `status='awaiting_review'` 的
    提案，依判定時間由舊到新排序（先產生的先審）。`kg_id` 省略時查詢所有
    KG（比照 `task_queue_service.next_pending()` 省略 `kg_id` 的既有慣例）。
    """
    query = (
        "SELECT id, kg_id, member_verbs, suggested_type_name, suggested_description, "
        "reused_from_registry, status, llm_judged_at, resolved_at "
        "FROM expand_cluster_proposal WHERE status = 'awaiting_review'"
    )
    params: tuple = ()
    if kg_id is not None:
        query += " AND kg_id = ?"
        params = (kg_id,)
    # 用 id 而非 llm_judged_at 排序——同一秒內產生多筆提案時，id 才能可靠
    # 反映真正的產生順序（見 recent_agreement_rate() 同一類修正的說明）。
    query += " ORDER BY id ASC"

    with closing(_connect(db_path)) as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_proposal(row) for row in rows]


def resolve_proposal(db_path: Path, proposal_id: int, decision: str) -> None:
    """人工核准／駁回一筆待審提案（`HUMANCHECK` 的 `核准`／`駁回` 分支）。

    `decision` 必須是 `"approved"` 或 `"rejected"`——這兩個值本身就是
    `GATE` 滾動窗口人機一致率的原始資料，不需要額外欄位記錄「LLM 判斷結果」
    （提案存在即代表 `LLMJUDGE` 已判定為「是」，`DISCARD` 分支從不建立提案）。
    """
    if decision not in ("approved", "rejected"):
        raise ValueError(f"decision 必須是 'approved' 或 'rejected'，收到：{decision}")
    with closing(_connect(db_path)) as conn:
        conn.execute(
            "UPDATE expand_cluster_proposal SET status = ?, resolved_at = datetime('now') "
            "WHERE id = ?",
            (decision, proposal_id),
        )
        conn.commit()


def recent_agreement_rate(db_path: Path, kg_id: str, window: int) -> float | None:
    """`GATE`：該 KG 最近 `window` 筆**人工已審核**提案中，核准的比例
    （= 人機一致率，因為提案存在即代表 LLM 判斷為「是」，人工核准就是與
    LLM 一致）。只計入 `status IN ('approved', 'rejected')`，`auto_approved`
    的提案未經人工審核、不計入一致率的分子分母——這也是為什麼一旦某類判斷
    真的畢業自動核准，`GATE` 不會因為「全部自動核准」而讓一致率虛高失真。
    候選數不足 `window` 時回傳 `None`，代表尚無法計算穩定的一致率。
    """
    with closing(_connect(db_path)) as conn:
        rows = conn.execute(
            # 用 id 而非 resolved_at 排序——resolved_at 只有秒級精度，短時間內
            # 連續審核多筆提案會撞期，id（自增主鍵）才能可靠反映真正的處理順序。
            "SELECT status FROM expand_cluster_proposal "
            "WHERE kg_id = ? AND status IN ('approved', 'rejected') "
            "ORDER BY id DESC LIMIT ?",
            (kg_id, window),
        ).fetchall()
    if len(rows) < window:
        return None
    approved = sum(1 for (status,) in rows if status == "approved")
    return approved / window
