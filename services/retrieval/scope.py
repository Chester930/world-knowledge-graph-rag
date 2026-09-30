"""P2 第四刀自 ``routers.agent`` 抽出的檢索範圍／過濾純函式群。

本模組無 I/O，只依賴 ``uuid`` 與 ``models.knowledge_graph``，不依賴
``routers``、``repositories``、``core`` 或任何其他 ``services`` 模組。引用報告145。
"""

from uuid import UUID

from models.knowledge_graph import SVOTriple


def relevant_doc_ids_from_facts(fact_results: list[dict], *, top_n: int | None = None) -> set[UUID]:
    """從語意 Fact 檢索結果（`vector_search_facts()`）取出出現過的
    `source_doc_id` 集合，供 `_filter_triples_by_source_doc_ids()`／
    `_filter_facts_by_source_doc_ids()` 當前置篩選範圍用。

    ✅ **2026-08-27 新增（64筆規模真實測試發現）**：語意 Fact 檢索本身常常
    已經正確找到問題對應的文件（真實測試兩次都在 Top-5 排第一、score 約
    0.80），但 BFS 圖遍歷不會借用這個訊號、仍照樣走訪整個 KG——64 筆規模
    下因通用實體（雇主／保險人／投保單位）連結數高，BFS 因此撈出大量離題
    結果（同一問題 456 筆，其中多數不相關）。與其另外設計一套「自然語言
    問題→結構化篩選條件」的解析機制（複雜、需要另外決定支援哪些條件
    類型），這裡直接重複利用語意 Fact 檢索**已經算好、已驗證有效**的
    來源文件訊號，成本低、不需要新的設計決策。

    **不是自然語言條件解析器**：只在語意 Fact 檢索確實找到結果時才有
    篩選範圍；`fact_results` 為空（語意檢索本身沒找到東西）時回傳空集合，
    呼叫端應視為「無範圍限制」，不強加篩選——避免語意檢索本身失準時，
    篩選反而放大既有的檢索缺陷。

    ✅ **`top_n`（2026-09-02，報告25 §4 發現1）**：只取分數最高的前 `top_n`
    筆推導範圍（`fact_results` 已依 score 遞減）。`top_n=None` 時沿用舊行為
    （全部）。理由見 `_DOC_SCOPE_TOP_N_FACTS` 常數註解。
    """
    considered = fact_results[:top_n] if top_n is not None else fact_results
    doc_ids: set[UUID] = set()
    for f in considered:
        raw = f.get("source_doc_id")
        if not raw:
            continue
        try:
            doc_ids.add(UUID(raw) if isinstance(raw, str) else raw)
        except ValueError:
            continue
    return doc_ids


def intersect_doc_scopes(
    semantic_doc_ids: set[UUID], explicit_doc_ids: list[UUID] | None
) -> set[UUID]:
    """報告39 §2.3：合併「語意 Fact 推導的文件範圍」（`_relevant_doc_ids_from_facts()`）
    與「呼叫端明確指定的範圍」（`ChatRequest.scope_doc_ids`，前導比較的 6 份子集）。

    - 明確範圍為 `None`／空 → 原樣回傳語意推導範圍（**零回歸**：未帶
      `scope_doc_ids` 的既有呼叫端行為完全不變）。
    - 語意推導範圍為空（`bfs_only`，或語意檢索本身沒找到來源）→ 用明確範圍。
    - 兩者都有值 → 取交集；交集為空代表語意檢索命中的來源不在指定子集內，
      回傳明確範圍本身（維持「限縮在子集」的意圖，不因語意雜訊放行全庫）。

    回傳空集合時呼叫端一律視為「無範圍限制」（`scope_doc_ids=None` 傳給
    `bfs_query()`、`_filter_*_by_source_doc_ids()` 的歸零守衛照舊）。
    """
    explicit = set(explicit_doc_ids or [])
    if not explicit:
        return semantic_doc_ids
    if not semantic_doc_ids:
        return explicit
    return (semantic_doc_ids & explicit) or explicit


def resolve_doc_scope(
    seed_doc_ids: set[UUID],
    semantic_doc_ids: set[UUID],
    explicit_doc_ids: list[UUID] | None = None,
) -> set[UUID]:
    """報告41（L9 V1）§3.3：檢索文件範圍改用「錨定優先」——`seed_doc_ids`
    非空即直接採用（語意範圍**不參與**，避免雜訊稀釋，見報告41 §3.3
    「為何不做 seed ∪ semantic 聯集」）；`seed_doc_ids` 空（舊 KG 無
    `HAS_ENTITY` 邊、或 `_find_seed_entities` 字面+語意 fallback 都沒命中、
    或 `fact_only` 模式本來就不算種子）時 fallback 回 `semantic_doc_ids`
    （＝現行行為，零回歸）。再與 `payload.scope_doc_ids`（報告39 前導比較
    的明確子集）取交集，交集邏輯沿用 `_intersect_doc_scopes()`。

    ⚠️ 真實資料驗證（`compare_doc_scope_retrieval.py`，2026-09-13）：8 題
    中 7 題新舊皆命中 gold 文件、三元組召回提升 3~25 倍；1 題（26-Q7，
    誠實拒答 canary）機械化的「gold_doc_id 是否在範圍內」指標判定退步，
    但 2026-09-14 端到端 `chat()` 對照顯示答案未受影響（仍正確拒答，見
    memory `project_report39_retrieval_comparison_harness`）——該退步對
    最終答案是良性的。報告41 §1.2 的原始動機案例（26-Q5「當月一日」）
    經兩輪查證後確認**不成立**（真因是 `vector_search_facts()` 全域語意
    排名過低，發生在本函式處理的範圍下推**之前**，本函式救不回它，見
    報告41 §9）——本改造修的是另一個真實存在、有獨立驗證的問題（BFS
    範圍被跨文件雜訊帶偏），不再用 Q5 佐證。
    """
    base = seed_doc_ids if seed_doc_ids else semantic_doc_ids
    return intersect_doc_scopes(base, explicit_doc_ids)


def scope_by_source_doc_ids(items: list, allowed_doc_ids: set[UUID], get_doc_id) -> list:
    """依 `allowed_doc_ids` 做**排除篩選**的共用邏輯（`_filter_triples_by_
    source_doc_ids()`／`_filter_facts_by_source_doc_ids()` 共用）：

    - `allowed_doc_ids` 為空（語意檢索沒有找到任何範圍訊號）→ 原樣回傳，
      不強加篩選（優雅降級）。
    - 三值邏輯：`get_doc_id(item)` 回 `None`（無法判定來源）的一律保留，
      只排除**明確知道**來源、且不在允許範圍內的項目。
    - ⚠️ **歸零守衛（2026-09-02，報告25 §4 發現1）**：若套用篩選會把「原本
      非空的清單」清成空集合，代表語意檢索判定的來源範圍與這批項目完全
      不一致——不信任較小／較新的語意 top-K 訊號去零化，放棄篩選、原樣
      回傳。只擋「完全歸零」，部分重疊命中（2026-08-27 情境）仍照常篩選。
    """
    if not allowed_doc_ids:
        return items
    filtered = [it for it in items if get_doc_id(it) is None or get_doc_id(it) in allowed_doc_ids]
    if items and not filtered:
        return items
    return filtered


def filter_triples_by_source_doc_ids(triples: list[SVOTriple], allowed_doc_ids: set[UUID]) -> list[SVOTriple]:
    """依 `allowed_doc_ids` 對 `bfs_query()` 已回傳的三元組做排除篩選（見
    `_scope_by_source_doc_ids()` 的共用邏輯與歸零守衛說明）。

    2026-08-27 真實測試：同一問題套用此篩選後 BFS 從 52 筆降到 8 筆，
    回答的三個核心重點全部正確且完全接地（先前未篩選版本混雜了推測
    內容，接地率明顯較低）。
    """
    return scope_by_source_doc_ids(triples, allowed_doc_ids, lambda t: t.source_doc_id)


def filter_facts_by_source_doc_ids(fact_results: list[dict], allowed_doc_ids: set[UUID]) -> list[dict]:
    """依 `allowed_doc_ids` 對 `vector_search_facts()` 回傳的語意 Fact 做排除
    篩選（見 `_scope_by_source_doc_ids()` 的共用邏輯與歸零守衛說明）。

    ✅ **2026-09-02（報告25 §4 發現1）**：先前只有 BFS 三元組會套文件範圍
    過濾、語意 Fact 不套。`ChatRequest.top_k` 提高到 20 後，語意 Fact 清單
    混入大量跨文件的相似事實（Q8 真實案例：LLM 抓了跨文件的「訓練時數
    不得低於八十小時」答成錯誤數字）。此函式讓語意 Fact 也收斂到語意
    自身判定的來源文件。`source_doc_id` 為字串，解析失敗／`None` 一律保留。
    """
    def _doc_id(f: dict) -> UUID | None:
        raw = f.get("source_doc_id")
        if not raw:
            return None
        try:
            return UUID(raw) if isinstance(raw, str) else raw
        except ValueError:
            return None

    return scope_by_source_doc_ids(fact_results, allowed_doc_ids, _doc_id)


def filter_triples_by_relation_type(triples: list[SVOTriple], rel_type: str | None) -> list[SVOTriple]:
    """§ 3.2 §c `QFILTER`（2026-08-18 定案）：對 `bfs_query()` 已回傳的三元組
    做**後篩選**，只保留 `rel_type` 型別——不改變 BFS 走訪路徑本身的語意，
    避免漏掉需先經過其他型別的邊才能抵達目標型別的路徑（見設計文件同名
    段落的 recall 風險說明）。`rel_type` 為 `None`（`QNOMATCH`）時原樣回傳，
    不篩選——優雅降級，不因型別解析失敗就讓查詢端拿不到任何結果。
    """
    if rel_type is None:
        return triples
    return [t for t in triples if t.rel_type == rel_type]
