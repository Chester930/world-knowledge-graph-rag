# 報告164：下一階段任務規劃——`GraphSchemaPort` 第一步、N9 只讀盤點、trace 欄位修補

> **日期**：2026-09-30
> **性質**：階段任務規劃。分工同報告155／160：**規劃對話決定、執行對話執行、規劃對話只記錄**。
> **依據**：使用者 2026-09-30 指示「按照建議繼續」——採用報告160 §9 的建議（見 §9.1）；[報告163](163_N4獨立化與來源回取再探測階段結果彙整.md)、[報告161](161_GraphStorePort設計提案_語意介面與分階段.md)、[報告162](162_KG來源回取再探測結果.md)。
> **基準**：`worktree-sdd-retrieval-comparison` @ `fa322a6` 之後；pytest 基準 **1503 passed**（帶 `--ignore=tests/core/test_embedding_migration.py`），**執行前先重測**。
> **本文件只由規劃對話修改**（§8 執行紀錄）。

---

## 1. 本階段決定了什麼、沒決定什麼

| 採用的建議（報告160 §9） | 本階段的落實 |
| --- | --- |
| #2 `GraphStorePort` 位置 A（`core/ports/`），開工 P-A **第一步**（只宣告＋轉接） | **V1** |
| #4 **N9 先於 N5**；沒有介面前不急著搬 N5 | **V2**：N9 **只讀盤點**（不搬移）；N5 不動 |
| #6 修 `build_retrieval_trace`，獨立小任務 | **V3**（**有條件**：只在不必改 `bfs_query` 時才改） |
| #1 N4 事件契約不急、#3 共用輔助不裁定、#5 暫停來源回取、#7 論文同步等下一次搬移後 | **無任務** |

**規劃對話為 V1 暫定的三項實作細節**（依使用者「按建議」的授權，皆可逆，執行對話**不要再回頭問**）：

1. **`VectorIndexSpec` 值物件採用**（報告161 §5 問題 2）：以一個值物件表達 6 種向量索引目標，不做 6 個方法。
2. **多資料庫管理方法（`create/drop/list_kg_databases`）本輪不納入 Port**（問題 3）。規劃對話查得：三者**都沒有測試**；`create_kg_database`、`list_kg_databases` 在非測試程式**沒有任何呼叫者**；`drop_kg_database` 只有 `repositories/kg_repo.py` 一處呼叫者。
3. **轉接層（adapter）放在 `services/graph_store/`**：`core/ports/` 只放抽象（與 `core/providers/base.py` 平行），具體實作由 services 層包裝既有函式——這樣依賴方向合法（`services → core`），`core` 不會反向 import `services`。

**報告163／161 的一項事實更正**（規劃對話已記入報告160 §9.2）：P-A 的 DDL 函式**不是單一呼叫端 `main.py`**——`create_fact_vector_index`、`create_sentence_vector_index`、`create_fact_fulltext_index`、部分 `create_entity_index` 在 `svo_service.py` 內部被呼叫，另有根目錄腳本。**本輪不遷移任何呼叫端，故不受影響**；但日後遷移呼叫端時要逐處評估。

## 2. 階段總覽

| ID | 任務 | 性質 | 依賴 | 建議執行者 |
| --- | --- | --- | --- | --- |
| **V1** | `GraphSchemaPort` P-A 第一步：宣告＋轉接＋契約測試（**不遷移呼叫端**） | 新增檔案，既有程式**零修改** | 無 | 執行對話自訂 |
| **V2** | N9 依賴與副作用**只讀盤點** | 只讀報告（比照報告158） | 無 | 執行對話／Codex |
| **V3** | `build_retrieval_trace` 三元組 chunk 索引與 `article_no` 修補 | **有條件**的小型程式修補 | 無 | 執行對話 |
| **V4** | 階段驗收與彙整 | 報告 | V1–V3 | 執行對話 |

**順序**：V1、V2、V3 **互相獨立、可並行**（V1 新增 `core/ports/` 與 `services/graph_store/`；V2 只讀；V3 只動 `services/context/telemetry.py` 與其測試）。**本階段任何任務都不得修改 `svo_service.py`。**

## 3. 各任務規格

### V1：`GraphSchemaPort` P-A 第一步

**目標**：把報告161 §2.1 的 P-A（DDL／索引群）宣告成 Protocol，並提供包裝既有函式的轉接層與假實作，**現有函式與呼叫端一律不動**。

**範圍**：

- `core/ports/__init__.py`、`core/ports/graph_schema.py`：`GraphSchemaPort`（Protocol）與值物件（`VectorIndexSpec`、`FulltextIndexSpec`、`IndexInfo`、`EmbeddingMeta`）。方法取報告161 §2.1 的清單**去掉三個多資料庫管理方法**（即 `ensure_entity_uniqueness`、`ensure_vector_index(spec)`、`ensure_fulltext_index(spec)`、`list_vector_indexes`、`drop_indexes`、`read_embedding_meta`、`register_embedding_meta`）。`VectorIndexSpec` 須能表達現有 6 種目標，**包含 per-KG 動態標籤（`Fact_<kg>`、`Sentence_<kg>`）與關係屬性索引（`RELATED_TO.verb_embedding`）**，並帶 `kg_id`（需要時）與維度。
- `services/graph_store/neo4j_schema.py`：Neo4j 轉接層，**逐一委派**到既有函式（`svo_service.create_*`、`core/vector_migration.py`、`core/database.py` 等）。**委派，不複製邏輯；既有函式的簽名、行為、錯誤處理不得改。**
- 假實作（供測試與日後節點獨立測試使用），例如 `FakeGraphSchema`（記憶體內記錄呼叫）。

**驗收**：

- `git diff` **只有新增檔案**（`core/ports/`、`services/graph_store/`、對應測試）；**既有 `.py` 零修改**（以 `git diff --stat` 與 AST 比對證明）。
- **委派測試**：對轉接層的每個方法，以 spy 驗證它呼叫**同一個既有函式、相同引數**（不連 Neo4j）。
- **契約測試**：同一套契約測試對「假實作」與「轉接層（帶 spy）」**各跑一次**。
- **依賴方向 AST 測試**：`core/ports/` 不得 import `services`／`repositories`／`routers`；`services/graph_store/` 不得被任何 production 模組 import（本輪沒有呼叫者）。
- 依賴快照（以動工前 commit 重建）：預期新增 2 個套件、無循環。
- **三項故意破壞**：例如 (a) 轉接層某方法改呼叫錯誤函式 → 委派測試失敗；(b) `core/ports` import `services` → AST 測試失敗；(c) `VectorIndexSpec` 缺一種現有目標 → 契約測試失敗。
- 完整回歸不低於 1503。

**停止條件**：需要修改任何既有函式才能轉接；需要納入多資料庫管理；轉接需要改變行為；發現依賴方向無法合法。

### V2：N9 依賴與副作用只讀盤點

**目的**：為日後搬移 N9 提供資料（比照報告158 對 N4 的做法）。**本任務不搬移、不建議與 N5 的先後。**
**範圍**：`services/retrieval/NODE.md` 登記的 N9 成員，**不論現在在哪裡**：`routers/agent.py`（`_find_seed_entities`、`_drop_hub_seeds`、`_relevant_doc_ids_from_seeds`、`_expand_facts_by_article` 等）、`services/svo_service.py`（`vector_search_facts`、`vector_search_entities`、`bfs_query`、`resolve_query_relation_type`、`_rrf_fuse_fact_ids`、`_apply_source_doc_cap` 及其輔助）、`services/retrieval/scope.py`，以及 **`chat()` 內嵌的 N9.1／N9.2**（標出行號範圍，以及它們與 `chat()` 其餘部分共用哪些區域變數）。
**產出**：報告——對每個符號：`檔案:行號`；檔內相依的輔助函式與常數；import 與對 `KGConfig`／`core.config` 的讀取；**Neo4j 存取**（沿用報告157 的分類與 `GraphStorePort` 的 P-B／P-C 對應）、embedding／LLM 使用；**外部呼叫者與測試補丁目標**（re-export 陷阱：補丁 `svo_service.X`／`routers.agent.X` 而呼叫者已搬走時補丁會失效）；**最小封閉集與可切的依賴封閉群（僅列群與相依，不排順序）**；從 `chat()` 抽出 N9.1／N9.2 所需的改動面；**哪些搬移涉及 I/O（須重跑 K 臂快照，需 Neo4j＋Ollama）**；隱性耦合（路徑、全域狀態、模組載入時編譯的常數）。
**驗收**：抽樣 5 個符號回原碼核對；外部呼叫者以兩種搜尋方式交叉；**程式碼零變更**。
**禁止**：不搬移；不建議 N9 與 N5 的先後；不設計 `GraphStorePort` 的 P-B／P-C。

### V3：`build_retrieval_trace` 三元組欄位修補（有條件）

**緣起**：報告162 發現 `services/context/telemetry.py` 第 97–98 行把三元組的 `source_svo_chunk_index`／`article_no` **寫死為 `None`**（規劃對話已核對）；而 `bfs_query` 的說明寫明 `SVOTriple` 的 `source_*` 欄位取自 `citations_json` **最後一筆**。
**步驟**：

1. **先調查**：`bfs_query` 回傳的 `SVOTriple` 是否**已帶** `source_svo_chunk_index` 與 `source_article_no`（或等價欄位）？以程式碼與實測（可用報告162 的唯讀 Neo4j 環境）佐證，寫成短報告。
2. **若已帶**（不需要改 `bfs_query` 的查詢或回傳結構）：只修 `build_retrieval_trace` 的三元組分支——**欄位名稱與順序不變**（鍵早已存在為 `None`），僅在三元組有值時填入，其餘行為不變。
3. **若未帶**（修補需要改 `bfs_query`）：**停止並回報，不修改**。

**驗收（步驟 2）**：

- **差分測試**（舊函式 vs 新函式，≥1000 組隨機輸入，含 `None`／空值／多種型別）：輸出 `==`，且 **`json.dumps` 字串（含鍵順序）相同**，唯一差異是三元組在有值時兩欄由 `None` 變為該值。
- 與報告162 的 `citations_json` 解析結果（「last」變體）**對照**：重跑至少 5 題，確認 trace 新填入的 chunk 索引與 U3 的 last 解析一致（環境不可用則跳過這項並回報，不阻擋）。
- **K 臂快照比對**：先讀 `scripts/analysis/compare_p2_snapshots.py` 如何比對 L1；**不需要重跑含 LLM 的完整快照**，但須說明此修補對既有快照比對的影響，以及比對腳本是否需要允許這兩個欄位的差異（若要改比對腳本，屬允許範圍，但須逐項說明）。
- 完整回歸不低於 1503；`services/context/NODE.md` 如有描述此行為須同步更新，`check_node_cards.py` 0 警告。

**禁止**：不改 `bfs_query`；不改 `svo_service.py`；不做 K 臂含 LLM 的完整快照重跑；不改論文。

### V4：階段驗收與彙整

彙整 V1–V3：各任務結論、commit、偏離、**待使用者裁示的事項（只列、不代決定）**。編號由執行對話自 **165** 起依序使用（164 為本規劃，156 保留）。完成後補列報告索引（`docs/報告/00_報告索引.md`）。

## 4. 停止條件（遇到下列情況**停止並回報，不自行處理**）

1. 任何任務需要**改變行為**才能完成（V3 步驟 3 即為此例）。
2. 需要對草案 §10.2a 未裁示項目或報告163 §3 未裁示項目做決定（事件契約、共用輔助歸屬、N5 搬移、R3–R6、目錄結構…）。
3. V1 需要修改任何既有函式、或發現依賴方向無法合法。
4. 發現報告或草案引用的事實不正確（**請直接回報，規劃對話會更正**；本階段已更正過一次）。
5. 完整回歸低於基準。
6. 工作區出現非自己的未提交檔案：commit 前逐檔指定路徑，**不得 `git add -A`**；`git add HANDOVER.md` 前先看 `git diff -U0` 確認只有自己的 hunk。
7. 任何任務需要修改 `svo_service.py`。

## 5. 編號與約定

- 本文為 **164**；執行對話自 **165** 起；**156 保留**。
- 本階段**不修改論文**（Q7）、**不修改** `BT_SM節點化結構設計草案_v0.1.md`、報告155／160／164。
- Neo4j／Ollama 只在 V3 的選配驗證使用：**唯讀、不得啟動或重啟任何服務**；不可用就跳過並回報。

## 6. 回報方式

每個任務驗收並 push 後，以 `SendMessage` 回報規劃對話（名稱：`project refactor review sdd`）：

```text
V?｜結論（通過／有條件通過／失敗／停止）｜commit SHA｜關鍵數字｜偏離報告164 之處（無則寫無）
```

並依既有習慣在 HANDOVER.md 頂部新增一條。**規劃對話只記錄，不介入執行**；我會獨立抽查（隔離環境驗證）並在 §8 記錄。

## 7. 階段結束後

我會依 V1–V3 的結果向使用者提出下一個決策點（`GraphSchemaPort` 是否進一步遷移呼叫端、P-B 是否開工、N9 是否搬移與切法、N4 事件契約時機、是否需要新的檢索評測），**不自行排程**。

## 8. 執行紀錄（僅規劃對話更新）

| ID | 狀態 | 結論 | commit | 備註 |
| --- | --- | --- | --- | --- |
| V1 | ⏳ 待執行 | — | — | — |
| V2 | ⏳ 待執行 | — | — | — |
| V3 | ⏳ 待執行（有條件） | — | — | — |
| V4 | ⏳ 待執行 | — | — | — |
