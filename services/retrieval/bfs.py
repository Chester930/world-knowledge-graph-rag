"""N9 的 BFS 走訪純輔助（Cypher 字串組裝、記錄轉三元組、預設值常數）；報告168 W1 自 ``services.svo_service`` 搬入，行為不變。"""
from __future__ import annotations

import json
from uuid import UUID

from models.knowledge_graph import SVOTriple

# 報告27 L0：`bfs_query` 的懶惰擴展門檻——1-hop 結果去重後少於這麼多筆，
# 才擴展到 2-hop（僅在呼叫端允許 `hops >= 2` 時）。共用高頻實體（雇主／
# 被保險人）當種子時，1-hop 通常已足夠且遠快於 2-hop 的組合爆炸（報告26
# §4 #4：Q5/6/7 各 330–440 秒）。初值 8，待報告27 §6 敏感度測試校準。
# 2026-09-08：`= KGConfig().bfs.expand_when_below`；本常數現為 golden test
# 錨點（`tests/core/test_kg_config.py`），`bfs_query()` 已改讀 `cfg`。
_BFS_EXPAND_WHEN_BELOW = 8

# 報告27 L2（向量引導 prize 剪枝，2026-09-08 prototype）：懶惰擴展觸發時，
# 不再對 1-hop frontier 做無差別 2-hop 走訪，改對每條候選 2-hop 邊算
# `cosine(問題向量, 邊 natural_text 向量)`，只保留分數 top-k 條。G-Retriever
# prize 機制（He et al. 2024）的扁平化簡化——無 Steiner tree 最佳化、無 GNN。
# 預設關（`bfs_query(prize_top_k=None)`）＝零行為變化；需三個參數齊備才啟用。
# 初值 10，待報告27 §6 敏感度測試校準（k ∈ {5, 10, 20}）。
_BFS_PRIZE_TOP_K = 10


def _bfs_pass_cypher(rel_types: str, min_hop: int, max_hop: int, *, scoped: bool, per_seed_limit: bool) -> str:
    """組一趟 BFS 走訪的 Cypher（報告27 L1）。

    - `scoped=True`：鄰居必須經 `(:Chunk)-[:HAS_ENTITY]->` 連到 `source_doc_id`
      在 `$scope_doc_ids` 內的文件——把 `routers/agent.py` 語意 Fact 推導出的
      文件範圍下推到走訪階段，遍歷不出離題文件。⚠️ `HAS_ENTITY` 只出現在
      這個 `EXISTS {}` 範圍子查詢裡，**不在** `*min..max` 變長走訪型別清單中
      （2026-08-19 迴歸：走訪本身行經 HAS_ENTITY 會把端點解析成 Chunk 節點）。
    - `per_seed_limit=True`：每個 seed 的展開路徑數上限 `$per_seed_limit`
      （CALL 子查詢內 LIMIT），限制樞紐種子的扇出。
    """
    scope_clause = (
        "\n            WHERE EXISTS {\n"
        "                MATCH (c:Chunk {kg_id: $kg_id})-[:HAS_ENTITY]->(neighbor)\n"
        "                WHERE c.source_doc_id IN $scope_doc_ids\n"
        "            }"
        if scoped else ""
    )
    limit_clause = "\n            RETURN path LIMIT $per_seed_limit" if per_seed_limit else "\n            RETURN path"
    return f"""
        MATCH (seed:Entity {{kg_id: $kg_id}})
        WHERE seed.name IN $seed_entities
        CALL (seed) {{
            MATCH path = (seed)-[:{rel_types}*{min_hop}..{max_hop}]-(neighbor:Entity {{kg_id: $kg_id}}){scope_clause}{limit_clause}
        }}
        UNWIND relationships(path) AS rel
        WITH DISTINCT startNode(rel) AS s, rel, endNode(rel) AS o
        RETURN
            s.name AS subject,
            coalesce(s.type, "概念") AS subject_type,
            type(rel) AS rel_type,
            coalesce(rel.confidence, 1) AS confidence,
            rel.citations_json AS citations_json,
            rel.natural_text AS natural_text,
            o.name AS object,
            coalesce(o.type, "概念") AS object_type
    """


def _bfs_records_to_triples(records) -> list[SVOTriple]:
    triples: list[SVOTriple] = []
    for record in records:
        payload = dict(record)
        citations_json = payload.pop("citations_json", None)
        citations = json.loads(citations_json) if citations_json else []
        latest = citations[-1] if citations else {}
        payload["verb"] = latest.get("verb", payload["rel_type"])
        payload["source_doc_id"] = UUID(latest["source_doc_id"]) if latest.get("source_doc_id") else None
        payload["source"] = latest.get("source")
        payload["source_svo_chunk_index"] = latest.get("source_svo_chunk_index")
        payload["source_svo_chunk_file"] = latest.get("source_svo_chunk_file")
        payload["source_sentence_start"] = latest.get("source_sentence_start")
        payload["source_sentence_end"] = latest.get("source_sentence_end")
        triples.append(SVOTriple(**payload))
    return triples
