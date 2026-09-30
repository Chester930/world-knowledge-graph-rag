"""N9 的 Fact 候選純處理函式（RRF 融合、來源範圍過濾、同來源上限、去重）；報告168 W1 自 ``services.svo_service`` 搬入，行為不變。"""
from __future__ import annotations

import math
from typing import Collection
from uuid import UUID

def _rrf_fuse_fact_ids(id_rankings: list[list[str]], *, k: int = 60) -> list[str]:
    """Reciprocal Rank Fusion（Cormack, Clarke & Büttcher, 2009, SIGIR）——
    與 `baseline_rag_service.rrf_fuse()`／`routers.agent._rrf_order()` 同一
    演算法，這裡另寫一份操作 `elementId` 字串（而非 list index）的版本。
    三處各自保留一份小型複製、不互相 import，是本專案既有的分層慣例
    （見 `baseline_rag_service.rrf_fuse()` docstring：避免 services 反向
    import routers／跨 service 模組耦合），非本次新引入的重複。
    """
    scores: dict[str, float] = {}
    for ranking in id_rankings:
        for rank, fid in enumerate(ranking):
            scores[fid] = scores.get(fid, 0.0) + 1.0 / (k + rank)
    order_hint = {fid: pos for pos, fid in enumerate(id_rankings[0])} if id_rankings else {}
    return sorted(scores, key=lambda fid: (-scores[fid], order_hint.get(fid, math.inf)))


def _filter_fact_candidates_by_source_scope(
    records: list[dict], allowed_source_doc_ids: Collection[UUID] | None,
) -> list[dict]:
    """先在 over-fetch 候選中套用來源範圍，再做去重與 top-k 截斷。

    候選全都明確不在範圍內時保留原清單，以延續 agent 的 zero-out fail-open
    保護；缺少來源 ID 的舊 Fact 也保留，因為無法證明它在範圍外。
    """
    if not allowed_source_doc_ids:
        return records
    allowed = {str(doc_id) for doc_id in allowed_source_doc_ids}
    scoped = [
        record for record in records
        if record.get("source_doc_id") is None
        or str(record["source_doc_id"]) in allowed
    ]
    return scoped or records


def _apply_source_doc_cap(
    records: list[dict], top_k: int, source_doc_cap: int | None
) -> list[dict]:
    """`vector_search_facts()` 最終截斷層——`source_doc_cap` 為 `None` 時
    行為與先前完全一致（純 `records[:top_k]`）。非 `None` 時依既有分數
    排序貪婪走訪：同一 `source_doc_id` 累計達上限即跳過該筆、留給名額給
    其他來源；`source_doc_id` 缺席的記錄視為各自獨立來源，不受上限限制
    （比照 `_dedupe_facts_by_key()` 對缺欄位記錄的處理原則，缺 provenance
    的舊資料不強行歸併）。若依上限選完仍不足 `top_k`（候選池裡本來就
    沒有足夠的來源多樣性），第二輪按原順序把被跳過的記錄依序補滿——
    與 `routers/agent.py::_arrange_fact_lines()` 既有的「任一側不足時
    把餘額讓給另一側」同一設計精神，不因為湊不滿多樣性名額而讓清單
    比 `top_k` 短。文獻依據見 `docs/參考文獻/35_同來源Fact冗餘去噪與
    多樣性檢索/`（MMR／DF-RAG 固定 λ baseline 精神的規則式簡化版）。
    """
    if source_doc_cap is None:
        return records[:top_k]

    kept: list[dict] = []
    overflow: list[dict] = []
    doc_counts: dict[str, int] = {}
    for record in records:
        doc_id = record.get("source_doc_id")
        if doc_id is not None and doc_counts.get(doc_id, 0) >= source_doc_cap:
            overflow.append(record)
            continue
        kept.append(record)
        if doc_id is not None:
            doc_counts[doc_id] = doc_counts.get(doc_id, 0) + 1
        if len(kept) >= top_k:
            return kept[:top_k]

    for record in overflow:
        if len(kept) >= top_k:
            break
        kept.append(record)
    return kept[:top_k]


def _dedupe_facts_by_key(records: list[dict]) -> list[dict]:
    """`vector_search_facts()` 查詢輸出層去重：以 `(subject, rel_type,
    object)` 為鍵，同一鍵只保留分數最高的一筆，維持原始分數排序。任一欄位
    為 `None`（例如 2026-08-18 schema 修正前建立、尚未跑過 §b 回填批次的
    舊 Fact 節點）時視為無法安全去重，一律原樣保留——與
    `routers/agent.py::_merge_fact_lines()` 既有的同名情境處理原則一致。
    """
    best_by_key: dict[tuple, dict] = {}
    order: list[tuple | dict] = []

    for record in records:
        key = (record.get("subject"), record.get("rel_type"), record.get("object"))
        if not all(key):
            order.append(record)
            continue
        existing = best_by_key.get(key)
        if existing is None:
            best_by_key[key] = record
            order.append(key)
        elif record.get("score", 0) > existing.get("score", 0):
            best_by_key[key] = record

    deduped: list[dict] = []
    seen_keys: set[tuple] = set()
    for item in order:
        if isinstance(item, dict):
            deduped.append(item)
            continue
        if item in seen_keys:
            continue
        seen_keys.add(item)
        deduped.append(best_by_key[item])
    return deduped
