# 報告168：下一階段任務規劃——N9 純函式搬移（G1／G2）與 `source_article_no` 下游盤點

> **日期**：2026-09-30
> **性質**：階段任務規劃。分工同報告155／160／164：**規劃對話決定、執行對話執行、規劃對話只記錄**。
> **依據**：使用者 2026-09-30 指示「依照建議繼續」——採用報告164 §9 的建議與預案（見報告164 §9.1）；[報告167](167_GraphSchemaPort與N9盤點與trace修補階段結果彙整.md)、[報告166](166_N9依賴與副作用只讀盤點結果.md)。
> **基準**：`worktree-sdd-retrieval-comparison` @ `dd92790` 之後；pytest 基準 **1549 passed**（帶 `--ignore=tests/core/test_embedding_migration.py`），**執行前先重測**。
> **本文件只由規劃對話修改**（§8 執行紀錄）。

---

## 1. 本階段決定了什麼、沒決定什麼

| 採用的建議（報告164 §9） | 本階段的落實 |
| --- | --- |
| #3 N9 **只做 G1、G2（純函式）**，G3–G8 與 `chat()` 抽出暫緩 | **W1** |
| #4 `article_no` 值得評估，**先做下游盤點** | **W2**（只讀） |
| #2 惰性 DDL 先不改、**登記進節點卡** | **W3**（純文件） |
| #1、#5、#6、#7 暫緩／暫停；#8 論文同步等本階段搬完 | **無任務**；論文同步**不在本階段**（W1 完成後由使用者決定何時做一次） |

**規劃對話已核對的事實（供 W1 使用，不必重做）**：G1（`_rrf_fuse_fact_ids`、`_filter_fact_candidates_by_source_scope`、`_apply_source_doc_cap`、`_dedupe_facts_by_key`）與 G2（`_bfs_pass_cypher`、`_bfs_records_to_triples`、`_BFS_EXPAND_WHEN_BELOW`、`_BFS_PRIZE_TOP_K`）這 **8 個符號對 `svo_service.py` 內其他頂層符號皆無依賴**（AST 的 Name 載入分析）；外部使用者：`core/kg_config/model.py`、`scripts/eval/run_rq1_comparison.py`、根目錄 `_trace_aggr16_candidate_path_20260918.py`、`tests/core/test_kg_config.py`、`tests/services/test_svo_service.py`；**N9 的補丁全綁 `routers.agent`，`svo_service` 名稱在 N9 沒有補丁**（報告166 §6），所以搬移這 8 個符號**不會使補丁失效**。

## 2. 階段總覽

| ID | 任務 | 性質 | 依賴 | 建議執行者 |
| --- | --- | --- | --- | --- |
| **W1** | N9 G1＋G2 共 8 個符號搬入 `services/retrieval/`（**行為不變**） | 重構，會修改 `svo_service.py` | 無 | 執行對話自訂（可拆刀） |
| **W2** | `source_article_no` 下游使用者**只讀盤點** | 只讀報告 | 無 | 執行對話／Codex |
| **W3** | 節點卡登記「N9 檢索路徑含冪等 DDL」並更新 W1 搬移後的位置 | 純文件 | W1 | 執行對話 |
| **W4** | 階段驗收與彙整 | 報告 | W1–W3 | 執行對話 |

**順序**：W1 與 W2 **互相獨立、可並行**（W2 只讀）；W3 等 W1；W4 最後。

## 3. 各任務規格

### W1：N9 G1＋G2 搬移（行為不變）

**目標**：把上述 8 個符號從 `services/svo_service.py` 搬進既有節點資料夾 `services/retrieval/`（已有 `scope.py`），`svo_service.py` 以**重新匯出**保留舊名稱（同一物件；兩個常數值須逐位元相同）。**模組命名與分刀由執行對話決定**（建議 G1 一個模組、G2 一個模組；可分 1–2 刀；每刀獨立 commit、獨立驗收）。

**已決定的設計**：

1. **只搬這 8 個**；`bfs_query`（G3）、`vector_search_facts`（G4）、`vector_search_entities`（G5）、`resolve_query_relation_type`（G6）、`routers/agent.py` 內 N9 成員（G7）、`chat()` 內嵌 N9.1／N9.2（G8）**一律不動**。
2. `services/retrieval/` 內的模組**不得 import `svo_service`**（避免循環；以 AST 測試斷言，沿用 `services/extraction` 的做法）。
3. `svo_service.py` 內 `bfs_query` 與 `vector_search_facts` **照舊呼叫這些名稱**（改由匯入取得）；兩個 `_BFS_*` 常數在 `core/kg_config` 的 golden test 中與 `KGConfig` 預設值比對，必須維持相等。
4. 搬移**不得改變任何函式內容**（允許差異僅限 import 與其直接相關行，須逐項列出）。

**驗收（沿用 P2／N4 的獨立驗收方法）**：

- **AST 逐字比對**：8 個符號與搬移前逐字相同。
- **`svo_service.py` diff 形狀**：只有刪除被搬移的定義、新增匯入區塊。
- **重新匯出身分測試**：8 個舊名稱 `is` 新模組同一物件（常數用值相等＋同一物件）。
- **差分行為測試**（舊實作 vs 新模組，各 ≥1000 組，假資料、不連網路）：`_rrf_fuse_fact_ids`、`_filter_fact_candidates_by_source_scope`、`_apply_source_doc_cap`、`_dedupe_facts_by_key` 輸出 `==` 且**順序相同**（含平手、空輸入、重複鍵、`None`）；`_bfs_pass_cypher` 產生的**字串逐字相同**（涵蓋參數組合）；`_bfs_records_to_triples` 產生的 `SVOTriple` 清單 `==`（含 citations 多筆、缺欄位）；期望值**先用搬移前實作取得**。
- **外部使用者檢查**：`core/kg_config/model.py`、`scripts/eval/run_rq1_comparison.py`、根目錄 `_trace_aggr16_candidate_path_20260918.py` 所引用的名稱在搬移後**仍可由 `svo_service` 取得**（以 AST 檢查 import 名稱存在，**不要執行**那些腳本）；`tests/core/test_kg_config.py` 的 golden 錨點測試必須全綠。
- **依賴快照**（以搬移前 commit 自行重建）：預期 `services/retrieval` 新增模組與邊、無循環；另以 AST 測試斷言 `services/retrieval/` 不得 import `svo_service`。
- **三項故意破壞**：例如 (a) 讓 `services/retrieval` 新模組 import `svo_service` → AST 測試失敗；(b) 某個重新匯出改成本地包裝 → 身分測試失敗；(c) 修改 `_BFS_EXPAND_WHEN_BELOW` 的值 → golden 測試失敗。
- 完整回歸**不低於 1549**；`services/retrieval/NODE.md` 的成員位置同步更新為「已搬移」，`check_node_cards.py` 0 警告。
- **不需要**重跑 K 臂快照（純函式，差分測試即足夠；與 P2 前兩刀同）。

**前置檢查**：確認**沒有抽取 drain／Worker 正在使用本工作樹的程式碼**（行程檢查）。
**禁止**：不動 `chat()`／`routers/agent.py`；不搬 G3–G8；不改任何函式內容；不做 `GraphSchemaPort` 遷移；不改事件契約；不改論文。

### W2：`source_article_no` 下游使用者只讀盤點

**背景**：報告165 發現 `bfs_query` 回傳的 `SVOTriple` **未帶 `source_article_no`**（`_bfs_records_to_triples` 沒把引用的 `article_no` 對應過去），而資料庫中 975 筆三元組有 973 筆最後一筆引用帶 `article_no`。是否讓 BFS 帶出是**行為變更**，必須先知道影響面。
**產出**：報告——

1. **所有讀取 `SVOTriple.source_article_no`／`article_no` 的位置**（檢索→組裝→生成→評測→遙測→寫入路徑，含 `routers/agent.py`、`services/`、`scripts/eval/`、根目錄腳本）：`檔案:行號`、函式、它拿這個值做什麼。
2. 對每個位置回答：**若 BFS 三元組從 `None` 變成有值，這個位置的行為會不會改變？怎麼改變？**（例如：顯示「第 X 條」標示、去重鍵、排序、`natural_text` 選擇、prompt 內容、評分或 scope audit 判定。）列出**具體的行為差異情境**；讀程式判定不了者標「需實測」。
3. 寫入路徑：`merge_triples_to_graph` 與 citation 的 `article_no` 如何寫入，以確認「資料端有值」的來源。
4. **資料面**：報告162 的重跑資料（`data/eval/candidate_runs/kg_source_recall_probe_v2/retrieval_rerun.json`）中，`article_no` 有值的比例與分布；**其他 KG（非法規）是否必為 `None`**（以程式碼與可取得的資料佐證，不啟動服務）。
5. 若要改 `_bfs_records_to_triples`，**列出會被連動修改的測試與快照比對基準**（不要改）。

**驗收**：抽樣 5 個使用位置回原碼核對；以兩種搜尋方式交叉確認沒有漏掉使用者；**程式碼零變更**。
**禁止**：不改任何 `.py`；**不建議要不要改**（只列影響）；不啟動 Neo4j／Ollama（以離線資料與程式碼為據）。

### W3：節點卡登記（純文件）

在 `services/retrieval/NODE.md` 的「已知缺口／事實」登記：**N9 檢索路徑含冪等 DDL**——`vector_search_facts` 每次查詢都會先呼叫 `create_fact_vector_index`（`IF NOT EXISTS`，維度取 `len(query_vector)`），hybrid 時另於 try 區塊內呼叫 `create_fact_fulltext_index`；含義：N9 並非純讀取、對 KG 唯讀帳號會失敗（**未實測**）、與 `GraphSchemaPort` P-A 有相依（依報告166 §1、§8）。同時把 W1 搬移後的成員位置更新為「已搬移」。`check_node_cards.py` 0 警告。**禁止**改任何 `.py`。

### W4：階段驗收與彙整

彙整 W1–W3：各任務結論、commit、偏離、**待使用者裁示的事項（只列、不代決定）**。編號由執行對話自 **169** 起依序使用（168 為本規劃，156 保留）。完成後補列報告索引（`docs/報告/00_報告索引.md`）。

## 4. 停止條件（遇到下列情況**停止並回報，不自行處理**）

1. 任何任務需要**改變行為**才能完成。
2. W1 發現這 8 個符號**其實依賴 `svo_service.py` 的其他符號**（規劃對話以 AST 核對為無，若與事實不符請直接回報）。
3. 需要動 `chat()`／`routers/agent.py`、或搬移 G3–G8。
4. W1 的補丁失效**無法以機械方式修復**，或差分測試出現任何不一致。
5. 需要對未裁示事項做決定（事件契約、共用輔助歸屬、N5、`article_no` 是否改、`GraphSchemaPort` 遷移、R3–R6、目錄結構…）。
6. 發現報告或草案引用的事實不正確（**請直接回報，規劃對話會更正**）。
7. 完整回歸低於基準。
8. 工作區出現非自己的未提交檔案：commit 前逐檔指定路徑，**不得 `git add -A`**；`git add HANDOVER.md` 前先看 `git diff -U0` 確認只有自己的 hunk。

## 5. 編號與約定

- 本文為 **168**；執行對話自 **169** 起；**156 保留**。
- 本階段**不修改論文**（Q7）、**不修改** `BT_SM節點化結構設計草案_v0.1.md`、報告155／160／164／168。
- 驗證建議沿用：共用工作樹常有進行中的修改，必要時以隔離 worktree 驗證。

## 6. 回報方式

每個任務（W1 為**每一刀**）驗收並 push 後，以 `SendMessage` 回報規劃對話（名稱：`project refactor review sdd`）：

```text
W?｜結論（通過／有條件通過／失敗／停止）｜commit SHA｜關鍵數字｜偏離報告168 之處（無則寫無）
```

並依既有習慣在 HANDOVER.md 頂部新增一條。**規劃對話只記錄，不介入執行**；我會獨立抽查（隔離環境驗證）並在 §8 記錄。

## 7. 階段結束後

我會依結果向使用者提出下一個決策點（`article_no` 是否讓 BFS 帶出、N9 的 G3–G8 是否繼續、論文位置同步時機、`GraphSchemaPort` 遷移），**不自行排程**。

## 8. 執行紀錄（僅規劃對話更新）

| ID | 狀態 | 結論 | commit | 備註 |
| --- | --- | --- | --- | --- |
| W1 | ⏳ 待執行 | — | — | 分刀由執行對話決定 |
| W2 | ⏳ 待執行 | — | — | — |
| W3 | ⏳ 待執行（等 W1） | — | — | — |
| W4 | ⏳ 待執行 | — | — | — |
