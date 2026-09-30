# 報告170：N9 純函式搬移（G1／G2）與 `source_article_no` 下游盤點——階段結果彙整（報告168 W1–W4）

> **日期**：2026-09-30 ｜ **基準**：`worktree-sdd-retrieval-comparison` @ `a98b43f`（起點 `3642098`）
> **執行**：執行對話；規劃：[報告168](168_下一階段任務規劃_N9純函式搬移與article_no下游盤點.md)（不修改）。**本報告只列事項，不代替決定**。編號：W2＝169、W4＝本文 170（W1、W3 無獨立報告；156 保留）。**報告索引已補列 168–170**。

## 1. 各任務驗收結論

| ID | 結論 | commit | 成果 | 關鍵數字 |
| --- | --- | --- | --- | --- |
| W1 前置 | — | `0b90a04` | 搬移前差分 golden（6 函式各 1100 案＋2 常數，共 6602 案）＋8 符號逐字基準 | 程式碼零變更 |
| W1 切法1 | 通過 | `e51b8fb` | G1：`services/retrieval/fact_candidates.py`（`_rrf_fuse_fact_ids`、`_filter_fact_candidates_by_source_scope`、`_apply_source_doc_cap`、`_dedupe_facts_by_key`） | `svo_service.py` 刪 109／加 8 行；依賴 +1 模組／+1 邊；pytest 1565 |
| W1 切法2 | 通過 | `f714f39` | G2：`services/retrieval/bfs.py`（`_bfs_pass_cypher`、`_bfs_records_to_triples`、`_BFS_EXPAND_WHEN_BELOW`、`_BFS_PRIZE_TOP_K`） | 刪 74／加 8 行；依賴累計 174→176 模組、479→482 邊、無循環；pytest 1574 |
| W3 | 通過 | `e057c70` | `services/retrieval/NODE.md`：8 符號登記已搬移；登記「N9 檢索路徑含冪等 DDL」 | 三張卡 0 警告 |
| W2 | 通過 | `a98b43f` | [報告169](169_source_article_no下游使用者只讀盤點結果.md) | 973／975 有條號；正式問答路徑無讀取者 |
| W4 | 本文 | — | 報告索引補列 168–170 | 最終 pytest **1574 passed**（基準 1549；+25：差分 3、搬移 22） |

**W1 驗收要點（沿用 N4 做法）**：逐字比對 8 符號全相同（無允許差異）；`svo_service.py` diff 只有刪除搬移區塊＋匯入區塊，被刪行全在新模組；差分（搬移前實作產生 golden，六函式各 1100 案含順序、平手、空輸入、`None`、例外型別與訊息；`_bfs_pass_cypher` 字串逐字相同）全一致；重新匯出身分 8／8（兩常數值與身分相同）；`services/retrieval` 不得 import `svo_service` 的 AST 測試；`tests/core/test_kg_config.py` golden 錨點全綠；外部使用者：`core/kg_config/model.py`、`run_rq1_comparison.py` 只在註解提及，根目錄 `_trace_aggr16…` 的 from-import 以 AST 測試確認仍可取得（未執行）；故意破壞（新模組 import `svo_service`、重新匯出改本地包裝、改動函式內容、改 `_BFS_EXPAND_WHEN_BELOW` 值）皆使測試失敗；補丁無需改（N9 補丁全綁 `routers.agent`）；不需 K 臂快照（純函式）。前置檢查無 drain／Worker 行程。`chat()`／`routers/agent.py`、G3–G8 全程未動。

## 2. 偏離報告168 或需留意之處

1. 無偏離（W1 分兩刀：G1 一個模組、G2 一個模組，符合建議）。
2. **W2 的重要事實**：BFS 三元組的 `source_article_no` **在正式問答路徑沒有下游讀取者**（prompt、生成、接地、評分、scope audit、SSE `sources` 皆不讀），只影響遙測 trace 與離線分析腳本；其中 `source_ambiguity_audit.py` 對新產生 records 的影響**需實測**（報告169 §4 #12）。
3. `git add HANDOVER.md` 前皆先看 `git diff -U0`；`svo_service.py` 僅被機械刪除搬移區塊（W1）。

## 3. 建議使用者裁示的事項（只列、不代決定）

| # | 事項 | 資料 |
| --- | --- | --- |
| 1 | **`article_no` 是否讓 BFS 帶出**（改 `bfs.py::_bfs_records_to_triples` 一行；資料端 973／975 有值；正式路徑無讀取者；連動：n9 golden／逐字基準重產、`source_ambiguity_audit` 需實測、快照 L1 用旗標） | 報告169 §1、§4、§5 |
| 2 | **N9 的 G3–G8 是否繼續**（G3 `bfs_query`、G4 `vector_search_facts`＋惰性 DDL、G5 `vector_search_entities`、G6 `resolve_query_relation_type`〔N9→N4〕、G7 routers 內 4 函式、G8 `chat()` 內嵌 N9.1／N9.2；均涉 I/O，須重跑 K 臂快照，需 Neo4j＋Ollama） | 報告166 §7 |
| 3 | **查詢路徑內的惰性 DDL** 是否改由啟動時建立、查詢只讀（行為變更） | 報告166 §8、`services/retrieval/NODE.md` §10 |
| 4 | **`GraphSchemaPort` 是否進一步**（補 4 個需新寫 Cypher 的方法／遷移呼叫端；`svo_service` 內部呼叫與惰性 DDL 須另行處理） | 報告167 §3 #1 |
| 5 | **N4 事件契約語意**（E1–E5）、**11 個共用輔助的節點歸屬**、**N5 是否接著搬**（前次已列，仍待裁示） | 報告158 §6、報告163 §3 |
| 6 | **來源回取是否繼續**（兩次探測皆不支持；trace 三元組已帶 chunk 索引） | 報告162 §7 |
| 7 | **論文位置同步**（N4 已搬移、N9 純符號亦已搬移；P3 後需同步一次；本階段不改論文） | `services/extraction/NODE.md` §10 |

## 4. 未觸發報告168 §4 停止條件

未改變行為（差分全一致）、8 符號皆不依賴 `svo_service.py` 其他頂層符號（與規劃對話 AST 核對一致）、未動 `chat()`／`routers/agent.py`／G3–G8、補丁無失效、回歸未低於基準（1574≥1549）、`git add` 逐檔指定且 `HANDOVER.md` 先看 `git diff -U0`。
