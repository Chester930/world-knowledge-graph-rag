"""P2 第三刀自 ``routers.agent`` 抽出的檢索遙測／來源序列化純函式群。

本模組無 I/O，只依賴 ``models.knowledge_graph``、``models.law_document`` 與
同層的 ``services.context.fact_lines``，不依賴 ``routers``、``repositories``
或其他 ``services`` 模組。引用報告143。
"""

from models.knowledge_graph import SVOTriple
from models.law_document import LawDocument
from services.context.fact_lines import strip_type_markers


def serialize_document(doc: LawDocument | None) -> dict | None:
    if doc is None:
        return None
    return {
        "title": doc.title,
        "update_date": doc.update_date,
        "effective_date": doc.effective_date,
        "effective_note": doc.effective_note,
    }


def build_retrieval_telemetry(
    triples: list[SVOTriple],
    fact_results: list[dict],
    latency_s: float,
) -> dict:
    """報告57 §6-1 裁示：正式 `chat()` 路徑加的檢索量體遙測，刻意不算
    SNR／chain_completeness（那兩個指標需要 gold_spans，真實使用者問題沒有
    ——見 `services/lineage_tracker.py` 與 `chat()` 內對應註解）。這裡只算
    不需要正解就能算的量體：檢索到的文字量、triple／fact 筆數、檢索耗時，
    供之後接生產環境監控時有東西可看；不影響既有 `_serialize_sources()`
    呼叫端（欄位是新增，非取代）。"""
    combined_text = "".join(
        [t.natural_text or "" for t in triples] + [f.get("fact_text") or "" for f in fact_results]
    ).replace(" ", "").replace("\n", "")
    return {
        "retrieved_char_count": len(combined_text),
        "triple_count": len(triples),
        "fact_count": len(fact_results),
        "retrieval_latency_ms": round(latency_s * 1000, 1),
    }


def build_retrieval_trace(
    triples: list[SVOTriple],
    fact_results: list[dict],
    prompt_lines: list[list[str]] | None,
) -> dict:
    """報告62 T0：把「檢索到什麼、排第幾、有沒有進 prompt」整理成可序列化的 trace。

    **純記錄，不改動任何檢索／排序／截斷結果。** `fact_results`／`triples` 傳入的是
    `chat()` 範圍過濾後、`_arrange_fact_lines()` 截斷**之前**的完整清單，所以
    `rank` 是檢索順位（Fact＝`vector_search_facts()` 順序、triple＝`bfs_query()`
    走訪順序，兩者不共用名次）；`in_prompt` 才反映截斷結果。

    `prompt_lines`：`_build_prompt(trace_sink=)` 收集的實際 prompt 事實行（每次
    prompt 組裝一份）。`None`（呼叫端沒有收集）時 `in_prompt` 一律為 None，
    表示「未量測」而不是「沒進 prompt」。判斷方式是比對渲染後的行文字
    （`- ` + 去型別標記後的文字，與 `_split_fact_lines()` 一致）；被
    `_split_fact_lines()` 去重／過濾掉的證據本來就不會出現在任何 prompt 行，
    因此 `in_prompt=False`，不等於「被截斷」——兩種情況要看 `prompt_lines`
    與 rank 一起判讀。
    """
    prompt_set = (
        {ln for lines in prompt_lines for ln in lines} if prompt_lines is not None else None
    )

    def _in_prompt(rendered: str) -> bool | None:
        return None if prompt_set is None else rendered in prompt_set

    fact_entries = []
    for rank, f in enumerate(fact_results):
        text = f.get("fact_text") or ""
        idx = f.get("source_svo_chunk_index")
        fact_entries.append({
            "kind": "fact",
            "rank": rank,
            "text": text,
            "score": f.get("score"),
            "source_doc_id": str(f["source_doc_id"]) if f.get("source_doc_id") is not None else None,
            "source_svo_chunk_index": int(idx) if idx is not None else None,
            "article_no": f.get("article_no"),
            "in_prompt": _in_prompt(f"- {strip_type_markers(text)}"),
        })

    triple_entries = []
    for rank, t in enumerate(triples):
        raw = t.natural_text if t.natural_text else f"{t.subject} {t.verb} {t.object}".rstrip()
        triple_entries.append({
            "kind": "triple",
            "rank": rank,
            "text": raw or "",
            "score": None,
            "source_doc_id": str(t.source_doc_id) if t.source_doc_id is not None else None,
            # 報告164 V3：`bfs_query()` 回傳的 SVOTriple 已帶 `source_svo_chunk_index`（取自邊上
            # citations_json 最後一筆）；`source_article_no` 目前 BFS 路徑不會填入（恆為 None），
            # 仍照實讀取，讓日後 BFS 帶出時自然生效。無值時維持 None（與修補前逐位元相同）。
            "source_svo_chunk_index": (
                int(t.source_svo_chunk_index) if t.source_svo_chunk_index is not None else None
            ),
            "article_no": t.source_article_no,
            "in_prompt": _in_prompt(f"- {strip_type_markers(raw or '')}"),
        })

    return {"facts": fact_entries, "triples": triple_entries, "prompt_lines": prompt_lines}


def serialize_sources(
    triples: list[SVOTriple],
    fact_results: list[dict],
    resolved_rel_type: str | None,
    document_map: dict[str, LawDocument] | None = None,
    retrieval_telemetry: dict | None = None,
    retrieval_trace: dict | None = None,
) -> dict:
    """把本次檢索到的原始來源（BFS 三元組 + 語意 Fact）整理成可序列化的
    結構，隨 SSE `sources` 事件一併送出——讓呼叫端（CLI 工具、之後的前端）
    能顯示「答案根據哪些圖譜資料」，供人工審核，而不必只信任 LLM 自己在
    回答文字裡宣稱的來源。

    `document_map`（2026-08-25 新增，見 `_fetch_document_map()`）：選填。
    提供時依 `source_doc_id` 附加 `document`（法規層級 `effective_date`／
    現況），讓來源標註能顯示「此規定出自哪份法規、現行是否有效」，不需要
    人工再去查一次原始法規；`None`（既有呼叫端未升級）或查無對應
    `Document` 節點時該筆來源的 `document` 為 `None`，行為與新增前一致。

    `retrieval_telemetry`（報告57 §6-1 新增，選填）：`_build_retrieval_telemetry()`
    產物，`None`（既有呼叫端未升級，如 harness 的 `_serialize_sources()` 呼叫）
    時該欄位為 `None`，行為與新增前一致。

    `retrieval_trace`（報告62 T0 新增，選填）：`_build_retrieval_trace()` 產物，
    只有 `ChatRequest.include_retrieval_trace=True` 才有值，否則為 `None`。
    """
    document_map = document_map or {}
    return {
        "resolved_rel_type": resolved_rel_type,
        "retrieval_telemetry": retrieval_telemetry,
        "retrieval_trace": retrieval_trace,
        "triples": [
            {
                "subject": t.subject,
                "subject_type": t.subject_type,
                "verb": t.verb,
                "object": t.object,
                "object_type": t.object_type,
                "rel_type": t.rel_type,
                "source": t.source,
                "source_svo_chunk_file": t.source_svo_chunk_file,
                "natural_text": t.natural_text,
                "document": serialize_document(
                    document_map.get(str(t.source_doc_id)) if t.source_doc_id is not None else None
                ),
            }
            for t in triples
        ],
        "facts": [
            {
                "fact_id": f.get("fact_id"),
                "fact_text": f.get("fact_text"),
                "subject": f.get("subject"),
                "object": f.get("object"),
                "rel_type": f.get("rel_type"),
                "score": f.get("score"),
                "document": serialize_document(document_map.get(f.get("source_doc_id"))),
            }
            for f in fact_results
        ],
    }
