# 報告165：`build_retrieval_trace` 三元組欄位修補——調查與結果（報告164 V3）

> **日期**：2026-09-30 ｜ **基準**：`0be8e09` ｜ 修補只動 `services/context/telemetry.py`（三元組分支）；**未改 `bfs_query`、未改 `svo_service.py`**。

## 1. 調查（步驟 1）

| 問題 | 結果（程式碼＋實測） |
| --- | --- |
| `bfs_query` 回傳的 `SVOTriple` 是否帶 `source_svo_chunk_index`？ | **是**。`_bfs_records_to_triples`（`services/svo_service.py`）取邊上 `citations_json` **最後一筆**，設定 `source_doc_id`、`source`、`source_svo_chunk_index`、`source_svo_chunk_file`、`source_sentence_start/end`。實測（報告162 的 42 題重跑）：**975／975 條三元組的 `source_svo_chunk_index` 皆非空**，且與該邊 `citations_json[-1].source_svo_chunk_index` 逐條相同（0 不符）。 |
| 是否帶 `source_article_no`？ | **否**。`_bfs_records_to_triples` **沒有**把 citation 的 `article_no` 對應到 `SVOTriple.source_article_no`（citation 內有 `article_no` 欄位，但轉換函式沒讀）。若要帶出，需改 `svo_service.py`（本階段禁止）。 |

**判定**：chunk 索引已帶、不需改 `bfs_query` → 可修補；`article_no` 未帶 → **不修**（列為待裁示）。因此本次是**部分修補**（報告164 §3 V3 的條件「已帶 chunk 索引與 `source_article_no`」只滿足前者）；我判斷 chunk 索引足以讓 trace 可用於來源回取，且修補本身不需改 `bfs_query`，故繼續；若規劃對話認為必須兩欄同時已帶才修，請告知，可還原。

## 2. 修補（步驟 2）

`build_retrieval_trace` 三元組分支：`source_svo_chunk_index` 由寫死 `None` 改為 `int(t.source_svo_chunk_index)`（有值時）；`article_no` 由寫死 `None` 改為 `t.source_article_no`（BFS 路徑下恆為 `None`，日後 BFS 帶出時自然生效）。**鍵名與順序不變；無值時輸出與修補前逐位元相同。**

## 3. 驗收

| 項目 | 結果 |
| --- | --- |
| 差分測試（`tests/services/test_context_telemetry_trace_v3.py`；修補前函式逐字副本 vs 新函式） | **1200 組**隨機輸入（含 `None`／空字串／字串型索引／有無 prompt_lines）：`facts`、`prompt_lines` 完全相同；三元組輸出＝舊輸出＋兩欄換成三元組實際值；無來源值時 `json.dumps`（含鍵順序）與舊版**逐字相同**；有來源值的 ≥300 組與預期字串相同 |
| 與報告162 `citations_json`「last」解析對照 | 用 42 題重跑的 975 條三元組（離線，讀 `retrieval_rerun.json`）：trace 新填入的 chunk 索引與 last citation **975／975 相同**（超過要求的 5 題；未重連 Neo4j） |
| K 臂快照比對影響 | `scripts/analysis/compare_p2_snapshots.py` 的 L1 直接比 `retrieval_trace` 全欄位。**修補後新快照 vs 舊快照的 L1 會因三元組兩欄由 `None` 變值而判為不同**（行為本身未變）。因此為比對腳本新增**選用旗標** `--ignore-trace-triple-source-fields`（函式參數 `ignore_trace_triple_source_fields`，**預設關閉，既有比對行為不變**）：只在 `kind=triple` 條目上忽略這兩欄，其餘欄位差異仍偵測；新增 3 個測試（預設仍標出差異、旗標只忽略該兩欄、旗標仍偵測其他差異）。**未重跑含 LLM 的完整快照**。 |
| 完整回歸 | **1508 passed**（基準 1503＋2＋3 個新測試）；`check_node_cards.py` 3 張卡 0 警告（`services/context/NODE.md` 未描述此行為，無需同步） |

## 4. 待裁示

1. `article_no` 是否要讓 BFS 帶出（需改 `svo_service.py::_bfs_records_to_triples`，把 citation 的 `article_no` 對應到 `source_article_no`；屬 `svo_service.py` 修改，本階段禁止）。
2. 日後要比對「修補後」與「凍結」快照時，使用 `--ignore-trace-triple-source-fields`。
