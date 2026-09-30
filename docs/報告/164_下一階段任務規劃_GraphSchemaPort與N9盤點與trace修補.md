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
| V1 | ✅ **有條件通過（方法清單 7→5；規劃對話接受此偏離，並承認規格不足）** | `core/ports/{__init__,graph_schema,fake_graph_schema}.py`（`GraphSchemaPort` Protocol＋`VectorIndexSpec`／`FulltextIndexSpec`／`EmbeddingMeta`／`VectorTarget` 6 種目標，含 per-KG 動態標籤 Fact／Sentence 與關係屬性 `RELATED_TO_VERB`）＋`services/graph_store/neo4j_schema.py`（逐一委派，呼叫當下以模組屬性查找）＋`tests/core/test_graph_schema_port.py` 41 個；`git diff` 只有 7 個新增檔、既有 `.py` 零修改；契約測試對假實作與轉接層（spy）各跑；委派測試驗證 11 種呼叫皆為同一既有函式同引數；三項故意破壞皆使測試失敗；依賴快照 168→173 模組、471→479 邊、循環 0；**pytest 1549 passed**。**宣告的 5 個方法**：`ensure_entity_uniqueness`、`ensure_vector_index(spec)`、`ensure_fulltext_index(spec)`、`migrate_vector_indexes`、`check_embedding_meta` | `808ec01` | **規劃對話獨立驗證**：① 相對前一 commit，**6 個 `.py` 全為新增（A），既有 `.py` 零修改**；② `core/ports/graph_schema.py` **不 import 任何非標準庫模組**，`fake_graph_schema.py` 只 import 同套件的 `core.ports.graph_schema`（`graph_store` 字串僅出現在 docstring），**無 production 模組 import `services.graph_store`**；③ **我自寫「簽名綁定檢查」**（spy 測試抓不到的風險：轉接層傳給既有函式的引數若與真實簽名不相容，只有連真實 Neo4j 才會炸）：14 個委派呼叫形狀（含 `dim=None` 省略、per-KG 的 `kg_id`、`ConceptRepository(driver).create_vector_index`）**全部能 `inspect.signature().bind()` 到真實函式，0 個不相容**；④ **核對「沒有可忠實委派的單一函式」成立**：`core/embedding_guard.py` 的讀取（`MATCH … RETURN`）與登記（`CREATE`）在同一個函式內、`core/vector_migration.py` 的列出（`SHOW VECTOR INDEXES`）與刪除（`DROP INDEX`）在同一個函式內；⑤ **隔離 worktree 完整回歸 1549 passed（104.79 秒）**，與回報一致。**偏離與我的判斷**：報告164 §3 V1 指定 7 個方法（報告161 §2.1 去掉多資料庫三者），執行對話發現其中 `list_vector_indexes`／`drop_indexes`／`read_embedding_meta`／`register_embedding_meta` **沒有可忠實委派的單一函式**（現有只有 `migrate_vector_indexes`［SHOW＋依維度／退役名稱 DROP 合併］與 `check_and_register`［比對＋首次登記合併］），為守「委派、不複製邏輯、不改既有函式」而縮為 5 個。**我接受，且這是規劃對話的規格不足**：7 個方法清單是我直接取自報告161 的草案，**沒有逐一核對每個方法是否真有可委派的既有函式**；執行對話守住了我自己寫的約束，做法正確。**若日後要拆成 list／drop／read／register，需新寫 Cypher（新邏輯、非委派），屬另一個需使用者裁示的任務**。**附帶**：`FakeGraphSchema` 放在 `core/ports/`（只依賴標準庫＋同套件，供日後節點抽離測試），**規劃對話接受此位置**，不必改到 `tests/` |
| V2 | ✅ 通過（**附一項重要發現，見下**） | [報告166](166_N9依賴與副作用只讀盤點結果.md)＋可重跑唯讀腳本 `scripts/analysis/n9_dependency_inventory.py`（218 行）：**N9＝30 符號**（`routers/agent.py` 8、`svo_service.py` 15、`scope.py` 7）；`chat()` 內嵌 N9.1＝`agent.py:1265-1274`、N9 區塊＝`:1296-1396`（都在 `_stream` 內；區塊後仍讀 `embedding_provider`／`question_vector`／`fact_results`／`triples`／`resolved_rel_type`＋`cfg`；抽出需保住計時邊界與 `use_svo=False` 不觸碰 embedding 的不變量）；Neo4j 執行點 agent 4＋svo 7；**補丁全綁 `routers.agent`**（`_find_seed_entities`×18、`vector_search_facts`×18、`bfs_query`×17、`resolve_query_relation_type`×17、`_relevant_doc_ids_from_seeds`×17、`vector_search_entities`×2）——**與 N4 方向相反：搬 `svo_service` 定義不會使補丁失效，搬 `chat()`／N9 區塊才會**；3 個根目錄腳本以「賦值」替換 `routers.agent.vector_search_facts`（AST 抓不到、grep 補出，`chat()` 的 N9 搬走會靜默失效）；**8 個依賴封閉群 G1–G8**與哪些須重跑 K 臂快照（G3–G8 涉 I/O；G1、G2 純函式只需差分）；N9→N4（`resolve_query_relation_type` 依賴 `services/extraction`）、N9→P-A（`vector_search_facts` 依賴 `create_fact_*_index`）的跨節點匯入 | `2d09f76` | **規劃對話獨立驗證**：① commit 只含報告166、盤點腳本與 HANDOVER；**正式程式自 V1 以來零變更**；② **核實最重要的發現成立**：`vector_search_facts` 內 AST 找到 `create_fact_vector_index`（`svo_service.py:1544`）與 `create_fact_fulltext_index`（`:1570`）兩個呼叫，皆為 `IF NOT EXISTS` 的冪等 DDL；③ **3 個根目錄腳本賦值替換 `agent.vector_search_facts` 屬實**（`_run_ablation_arm.py:42`、`_run_ablation_arm_g4.py:40`、`_run_fact_rank_eval_20260918.py:144`）；④ **補丁計數抽查**：我以較粗樣式重算，`vector_search_facts` 18、`bfs_query` 17、`resolve_query_relation_type` 17、`vector_search_entities` 2 **與報告完全一致**；`_find_seed_entities`（25 對 18）與 `_relevant_doc_ids_from_seeds`（20 對 17）我的樣式會把直接引用也算進去所以偏多，**不構成矛盾**（我的樣式不是專抓補丁）；⑤ `agent.py:1265` 為 `domain_pack` 宣告（對應 N9.1 載入設定）、`:1296` 為 `if payload.use_svo:`（N9 區塊起點），與報告所述一致。**偏離**：無。**重要發現（執行對話揭露）**：`vector_search_facts` **每次查詢都會先執行冪等的 `CREATE VECTOR INDEX … IF NOT EXISTS`**（hybrid 另在 try 內建全文索引）——N9「唯讀」路徑含冪等 DDL。報告162（U3）與先前回報寫的「唯讀 Neo4j」需加註：**只讀取資料、無任何節點／關係寫入，但檢索函式內含 `IF NOT EXISTS` 的索引建立語句**（索引已存在＝無變更）。**規劃對話的更正**：我在 160 §8 記錄 U3 時寫「腳本審查：無任何寫入 Cypher…Neo4j 僅 `execute_query` 讀取」，**只檢查了腳本自身的 Cypher，沒有檢查它呼叫的 production 檢索函式**，與執行對話同樣漏了這點，已在 160 §8 U3 列補註；並**核准**執行對話在報告162 加註（V4 一併處理） |
| V3 | ✅ **有條件通過（部分修補；規劃對話接受此偏離，不必還原）** | 報告165（調查）＋`services/context/telemetry.py`（7 行）＋`compare_p2_snapshots.py` 新增選用旗標 `--ignore-trace-triple-source-fields`（預設關、既有行為不變）＋測試（+3 比對腳本、`test_context_telemetry_trace_v3.py`）。**調查**：`bfs_query` 回傳的 `SVOTriple` **已帶 `source_svo_chunk_index`**（實測 975／975，與 `citations_json` 最後一筆逐條相同），但**未帶 `source_article_no`**（`_bfs_records_to_triples` 沒把 citation 的 `article_no` 對應過去，要帶需改 `svo_service.py`，本階段禁止）。**修補**：只改 `build_retrieval_trace` 三元組分支——chunk 索引填入、`article_no` 讀 `t.source_article_no`（BFS 下仍 `None`）；鍵名與順序不變。差分 1200 組：無來源值時 `json.dumps` 逐字相同，有值時僅兩欄變化；**pytest 1508 passed**；節點卡 0 警告 | `5d9679b` | **規劃對話獨立驗證**：① commit 只動 `telemetry.py`（+7／−2）、`compare_p2_snapshots.py`（旗標）、測試、報告165、HANDOVER；**`bfs_query`／`svo_service.py` 完全沒動**；比對腳本新旗標預設 `False`，既有路徑不變；② **我自寫差分測試 1500 組**（舊版 `telemetry.py` 取自 `5d9679b~1` 對新版，隨機三元組與 Fact）：**0 違規**——無來源值 873 組 `json.dumps` 逐字相同；有來源值 627 組僅兩個三元組欄位不同，鍵名順序、Fact 區塊、`prompt_lines` 皆相同；③ **資料核對**（U3 的 `retrieval_rerun.json`）：975 筆三元組**全部**有 `source_svo_chunk_index`，且 **975／975 與最後一筆引用相同**；④ **隔離 worktree 完整回歸 1508 passed（107.82 秒）**，與回報一致。**偏離與我的判斷**：報告164 §3 V3 條件寫「已帶 chunk 索引**與** `source_article_no`」，實際只滿足前者。**我接受此偏離**：條件的目的是「不必改 `bfs_query`」；U3 證明缺的是 chunk 索引；修補是單純穿透且差分證明等價；`article_no` 在修補前後 BFS trace 都是 `None`，沒有退步，且 `telemetry.py` 已照實讀取，日後 BFS 帶出時自然生效。執行對話誠實揭露並提出可還原，**規劃對話判斷不需還原**。**新發現（供日後裁示）**：資料庫中 975 筆三元組的最後一筆引用有 **973 筆帶 `article_no`**——資料有、但 `_bfs_records_to_triples` 沒對應；補上屬 `svo_service.py`（N9 區域）且會改變 `SVOTriple.source_article_no`，下游可能影響呈現，**須當成另一個有評估的行為變更任務** |
| V4 | ⏳ 待執行 | — | — | — |
