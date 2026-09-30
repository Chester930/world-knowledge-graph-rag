# 報告167：GraphSchemaPort 第一步、N9 只讀盤點、trace 欄位修補——階段結果彙整（報告164 V1–V4）

> **日期**：2026-09-30 ｜ **基準**：`worktree-sdd-retrieval-comparison` @ `6f89247`（起點 `0be8e09`）
> **執行**：執行對話；規劃：[報告164](164_下一階段任務規劃_GraphSchemaPort與N9盤點與trace修補.md)（不修改）。**本報告只列事項，不代替決定**。編號：V3＝165、V2＝166、V4＝本文 167（V1 無獨立報告；156 保留）。**報告索引已補列 164–167**。

## 1. 各任務驗收結論

| ID | 結論 | commit | 成果 | 關鍵數字 |
| --- | --- | --- | --- | --- |
| V3 | 有條件通過 | `5d9679b` | [報告165](165_build_retrieval_trace三元組欄位修補調查與結果.md)：`telemetry.py` 三元組填入 chunk 索引；`compare_p2_snapshots.py` 選用旗標 | 調查：`SVOTriple` 已帶 chunk 索引 975／975、**未帶** `source_article_no`；差分 1200 組（`json.dumps` 逐字相同）；pytest 1508 |
| V1 | 有條件通過 | `808ec01` | `core/ports/{graph_schema,fake_graph_schema}.py`＋`services/graph_store/neo4j_schema.py`＋41 個測試 | 只新增 7 檔、既有 `.py` 零修改；方法縮為 5 個；三項故意破壞皆失敗；依賴快照 168→173 模組、471→479 邊、無循環；pytest 1549 |
| V2 | 通過 | `2d09f76` | [報告166](166_N9依賴與副作用只讀盤點結果.md)＋`n9_dependency_inventory.py` | N9＝30 符號；8 個依賴封閉群；補丁全綁 `routers.agent`；發現查詢路徑含冪等 DDL |
| V4 | 本文 | — | 報告索引補列 164–167；報告162 加註 | 最終 pytest **1549 passed**（基準 1503；+5＋41）；卡檢查 3 張 0 警告 |

`svo_service.py` 全程**零修改**；V1 既有 `.py` 零修改（`git status` 只有新增）；`git add` 逐檔指定，`HANDOVER.md` 先看 `git diff -U0`。

## 2. 偏離報告164 與更正（請規劃對話知悉）

1. **V1 方法清單縮為 5 個**（規劃對話已接受）：報告164 給的 7 個方法中，`list_vector_indexes`／`drop_indexes`／`read_embedding_meta`／`register_embedding_meta` 在現有程式**沒有可忠實委派的單一函式**（現有只有 `migrate_vector_indexes`［SHOW＋依維度／退役名稱 DROP 合併］與 `check_and_register`［比對＋首次登記合併］）。為守「委派、不複製邏輯、不改既有函式」，宣告的 5 個是：`ensure_entity_uniqueness`、`ensure_vector_index(spec)`、`ensure_fulltext_index(spec)`、`migrate_vector_indexes`、`check_embedding_meta`。`FakeGraphSchema` 放在 `core/ports/`（只依賴標準庫）。
2. **V3 為部分修補**（規劃對話已接受）：`article_no` 未被 `_bfs_records_to_triples` 帶出，只修 chunk 索引；規劃對話另記錄：U3 資料中 975 筆三元組的最後一筆引用有 973 筆帶 `article_no`，補上屬 `svo_service.py` 修改與 `SVOTriple.source_article_no` 行為變更，本階段不做。
3. **對報告162（U3）的加註與更正**：報告162 及我先前回報稱 U3「唯讀 Neo4j」。V2 發現 `vector_search_facts` 每次查詢先執行**冪等的 `CREATE VECTOR INDEX … IF NOT EXISTS`**（`svo_service.py:1544`；hybrid 另於 try 內建全文索引 `:1570`）。**實際情況：只讀取資料、無任何節點／關係寫入，但檢索路徑含 `IF NOT EXISTS` 的冪等索引建立語句（索引已存在＝無變更）；U3 的結論與數字不受影響。** 已在報告162 頭部加註（本 V4 commit）。這是我當時只檢查腳本自身 Cypher、沒檢查它呼叫的 production 函式所致；規劃對話在報告160 §8 亦已補註。
4. **報告163 §3 #2／報告161 §7 稱 P-A 的 DDL 函式「單一呼叫端 `main.py`」不正確**（規劃對話已更正於報告160 §9.2）：`create_fact_vector_index` 等在 `svo_service` 內部另有多處呼叫（含 `vector_search_facts` 惰性呼叫）。V1 不遷移呼叫端故不受影響；日後遷移須逐處評估（報告166 §7 G4 已列）。

## 3. 建議使用者裁示的事項（只列、不代決定）

| # | 事項 | 資料 |
| --- | --- | --- |
| 1 | **`GraphSchemaPort` 是否進一步**：(a) 補 `list_vector_indexes`／`drop_indexes`／`read/register_embedding_meta`（需新寫 Cypher，非委派）；(b) 開始遷移呼叫端（先 `main.py` 啟動流程；`svo_service` 內部呼叫與 `vector_search_facts` 的惰性建索引須另行處理） | 報告161、V1、報告166 §8 #1 |
| 2 | **查詢路徑內的惰性 DDL**（`vector_search_facts` 每次查詢建索引）是否要改由啟動時建立、查詢只讀（屬行為變更；對唯讀帳號會失敗，未實測） | 報告166 §1、§8 |
| 3 | **N9 是否搬移與切法**（G1–G8；G1／G2 純函式只需差分；G3–G8 須重跑 K 臂快照，需 Neo4j＋Ollama；`chat()` 內嵌 N9.1／N9.2 抽出需保計時邊界與 `use_svo=False` 不變量）；**搬 `chat()` 會使 ≥170 處 `<agent>.*` 補丁與 3 個賦值式根目錄腳本失效** | 報告166 §4–§7 |
| 4 | **`article_no` 是否讓 BFS 帶出**（改 `svo_service.py::_bfs_records_to_triples`，影響 `SVOTriple.source_article_no`；資料端 973／975 有值） | 報告165 §4、報告164 V3 |
| 5 | **N4 事件契約語意**（E1–E5，前次已列，仍待裁示） | 報告158 §6、報告163 §3 #1 |
| 6 | **11 個共用輔助（`services/extraction/`）的節點歸屬**、**N5 是否接著搬**（前次已列） | 報告163 §3 #3–#4 |
| 7 | **來源回取是否繼續**（兩次探測皆不支持；三元組現在的 trace 已帶 chunk 索引可直接用，`article_no` 仍空） | 報告162 §7 |
| 8 | **論文位置同步**（N4 已搬移；P3 後需同步一次；本階段不改論文） | `services/extraction/NODE.md` §10 |

## 4. 未觸發報告164 §4 停止條件

無需改變行為（V3 只在有值時填入，差分證明等價；V1 純新增）、無需改 `svo_service.py`、未對未裁示項目做決定、回歸未低於基準（1549≥1503）、工作區無他人未提交檔案（`git add` 逐檔）；發現的事實落差（V1 方法清單、V3 `article_no`、V2 惰性 DDL）皆已即時回報。
