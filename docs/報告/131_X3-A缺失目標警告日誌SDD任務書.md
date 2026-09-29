# 報告131：X3-A——缺失目標的警告日誌 SDD 任務書（可觀測性補強，控制流與回傳值零變動）

> **日期**：2026-09-29
> **執行者**：Codex｜**設計與審核**：Claude Code
> **上位文件**：[報告130](130_X1_X3影響評估結果.md)（§5.2 選項 A）、[報告120](120_狀態機現況轉移盤點結果.md)（X3）、[報告123](123_M2_P1第二批_SM2佇列詞彙統一SDD任務書.md)／[126](126_M2_P1第三批_SM1單一轉移入口SDD任務書.md)（SQL 軌跡／記錄快照驗證方法）
> **成果檔**：`docs/報告/132_X3-A修復結果.md`（Codex 建立）
> **性質**：**一個單獨的小修復**（使用者已於 2026-09-29 選定「先 X3-A，再 X1-A，兩者各自單獨」）。**只新增日誌，不改任何回傳值、不新增任何 raise、不改任何控制流。** 本任務**不處理 X1**（另案，任務書 133）。不啟動 Neo4j／Ollama／server。單段執行（風險低，不設核准關卡），但驗證比一般更嚴（見 §2 S4）。

---

## 0. 設計（已定，不需 Codex 再判斷）

X3＝「目標不存在就靜默 no-op」，使 A8 的 B3 長時間無人察覺。X3-A 只讓這類事件**留下可搜尋的訊號**。

### 範圍（共 6 個函式，逐個明確）

| # | 函式（位置） | 目前的缺失行為 | 修改 |
|---|---|---|---|
| 1 | `services/document_record_service.py::set_svo_chunk_total`（約 199-207 行） | `read_record()` 回 `None` → `return None` | 在 `return None` **之前**加一則 `logger.warning` |
| 2 | 同檔 `reset_extraction_progress` | 同上 | 同上 |
| 3 | 同檔 `record_chunk_completed` | 同上 | 同上 |
| 4 | 同檔 `mark_extraction_failed` | 同上 | 同上 |
| 5 | 同檔 `update_normalization_progress` | 同上（注意：其 `ValueError` 檢查在 `read_record` 之前，順序不變） | 同上 |
| 6 | `services/task_queue_service.py::update_status` | `UPDATE` 影響 0 列，靜默 | 取得執行結果的 `rowcount`；為 0 時在 `commit` 之後（或不影響順序處）加一則 `logger.warning`；**函式仍回傳 `None`、SQL 文字一字不改** |

### 明確不改的

- **`set_document_vector`**（同檔）：雖有相同的缺失 no-op，但它寫的是分類用的**快取欄位**，不是狀態轉移；對沒有記錄檔的文件呼叫屬常態，加日誌只會產生雜訊。**不加。**
- `read_record()`、`_write_record()`、`init_record()`、`append_assignment()`（後者缺記錄時會**建立**新記錄，不屬 no-op）。
- 任何呼叫端（`extraction_worker`、`svo_service`、`knowledge_graph_service` 等）、`state/` 套件、既有測試。

### 日誌規格

- 使用模組層級 logger：`logger = logging.getLogger(__name__)`（`task_queue_service.py` 已有；`document_record_service.py` 若無則新增 `import logging` 與 `logger`）。
- 等級固定 **WARNING**。
- 訊息格式（繁體中文＋前綴，沿用專案既有 `[ExtractionWorker]` 風格）：
  - 記錄類：`"[DocumentRecord] %s：記錄檔不存在，寫入被略過（folder=%s）——可能是 resolver／虛擬歸屬路徑錯置（見報告109／112）"`，參數為函式名稱與 `folder`。
  - 佇列類：`"[TaskQueue] update_status：查無對應列，狀態更新被略過（kg_id=%s source=%s chunk_index=%s status=%s）"`。
- 每次缺失事件恰好**一則**日誌（不重複、不加迴圈）。
- `status` 參數若為 `StateTaskStatus`（`StrEnum`）成員，日誌中以 `str(status)` 或 `.value` 呈現字面值，**不得**出現 `TaskStatus.PENDING` 之類的 repr。

### 硬性行為約束

1. **回傳值、例外、副作用（含檔案／資料庫寫入內容與順序）與現況完全相同**——唯一新增的可觀察行為是 WARNING 日誌。
2. `task_queue_service.update_status` 的 SQL 文字**一字不改**；以 `cursor = conn.execute(...)` 取得 `cursor.rowcount` 僅讀取，不得新增任何 SQL 語句（SQL 軌跡必須逐字相同，見 S4-3）。
3. 不得讓日誌呼叫本身在任何情況下拋例外（參數皆為現成變數，不做額外 I/O）。

---

## 1. 步驟

### S1　基準
`git status -s` 為空；記錄 HEAD；完整回歸 `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py`（Claude 獨立基準 **1289**；若被既有 UMAP 三測試卡住，用 `--deselect` 排除並註明實際數字，預期 1286）。

### S2　先寫測試（RED）
新增測試檔 `tests/services/test_missing_target_warnings.py`（**新增，不改任何既有測試**），用 `caplog`（level=WARNING）與 `tmp_path`：

| 測試 | 內容 |
|---|---|
| `test_document_record_missing_writes_log_one_warning_each`（參數化 5 個函式） | 對不存在的資料夾呼叫該函式：回傳 `None`；**不 raise**；`tmp_path` 下該資料夾**未被建立**；`caplog` 中恰有**一則** WARNING，內含函式名稱與 folder 路徑字串 |
| `test_update_status_missing_row_logs_warning_and_returns_none` | 用 `tmp_path` sqlite：對不存在的 `(kg_id, source, chunk_index)` 呼叫 `update_status`：回傳 `None`、不 raise、該列**仍不存在**；恰有一則 WARNING，內含 `kg-…`、`source`、`chunk_index` 與狀態字面值（例如 `completed`，**不含** `TaskStatus.`） |
| `test_update_status_existing_row_logs_nothing` | 對**存在**的列呼叫 `update_status`（傳字串與傳 `StateTaskStatus` 成員各一次）：狀態被正確更新且 `caplog` **無** WARNING |
| `test_document_record_existing_writes_log_nothing` | 記錄存在時呼叫該 5 個函式：行為與現況相同、`caplog` 無 WARNING（防止誤報） |
| `test_set_document_vector_missing_record_stays_silent` | 鎖定「不改」的範圍：對不存在記錄呼叫 `set_document_vector`，回傳 `None` 且 `caplog` **無** WARNING |

**自我檢查**：執行 `python -m pytest tests/services/test_missing_target_warnings.py -q -p no:cacheprovider`：**缺失類的測試必須失敗**（尚未加日誌），「existing／stays silent」類應通過。記下失敗摘要。若任一缺失類測試意外通過，停下檢查測試寫法。

### S3　實作（僅限 §3 的檔案）
依 §0 的範圍表與日誌規格修改 `services/document_record_service.py` 與 `services/task_queue_service.py`。

### S4　驗證（四項都要做）
1. 新測試全過：`python -m pytest tests/services/test_missing_target_warnings.py -q -p no:cacheprovider`。
2. **既有測試不改而全過**：`python -m pytest tests/state tests/services/test_document_record_service.py tests/services/test_task_queue_service.py tests/services/test_extraction_worker.py tests/services/test_knowledge_graph_service.py -q -p no:cacheprovider`。（`tests/state/test_document_sm.py::test_missing_record_writes_are_silent_noops` 與 `tests/state/test_task_sm.py::test_set_status_on_missing_row_is_silent_noop` 等既有測試因回傳值與例外行為未變仍應通過——其函式名稱中的「silent」已不完全準確，僅在報告 132 §已知限制註明，**不得改名或修改**。）
3. **零行為變動的機械證據（沿用前兩批的方法）**：
   - **SQL 軌跡**：用報告124 附錄 A 的軌跡腳本（`trace_task_queue_sql.py`，Codex 暫存目錄 `codex_report123_sqltrace_20260929_01\` 內已有；Claude 的副本亦有）在**修改後**重跑，輸出 `after_sql_trace_x3a.json`，與該目錄的 `baseline_sql_trace.json` 比對 `operations` 與 `trace` 兩欄，**必須逐字相同**（腳本用字串狀態參數即可，因為本批不涉及 enum 綁定）。另在軌跡腳本中**額外**加一個「對不存在列呼叫 `update_status`」的操作，確認新增 rowcount 讀取**沒有**多產生任何 SQL（該操作的軌跡與現況相同）。
   - **記錄快照**：用報告127 附錄 A 的快照腳本（`reproduce_record_snapshots.py`，暫存目錄 `codex_report126_record_snapshots_20260929_01\`）在修改後重跑，輸出 `after_record_snapshots_x3a.json`，`scenarios` 與 `time_normalization` 兩欄與 `baseline_record_snapshots.json` **必須逐字相同**。
   - 任何差異都停下回報，不得自行判定無害。
4. 完整回歸：`python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py` → **1289＋新增測試數 passed、0 failed**（新增測試數請在報告 132 明確列出，參數化用例照 pytest 實際計數）。
5. 相依快照：`python scripts/analysis/import_graph_snapshot.py . data/analysis/import_graph_20260929_after_x3a.json`：`cycles=0`，**邊數與修改前相同**（僅標準庫 `logging`，不應新增任何內部邊）；快照檔驗完刪除、不 commit。

### S5　成果報告
建立 `docs/報告/132_X3-A修復結果.md`：修改摘要（6 個函式各一行）、S2 RED 證據、S4 各項數字（含軌跡與快照比對結果、新增測試數）、**已知限制**（明確寫出：本修復只讓缺失可觀測，不修正資料遺失；X1 未動；`set_document_vector` 刻意不加；既有測試名稱中的「silent」不再完全準確；`caplog` 只在測試中驗證，實際 logger 是否被配置由部署環境決定）。無佔位符。

### S6　提交
只提交 §3 的檔案；commit 訊息 `feat(observability): 缺失記錄／佇列列的寫入略過改為輸出 WARNING，行為零變動（報告131 X3-A）`。**不 push。**

---

## 2. 允許修改的檔案

| 檔案 | 性質 |
|---|---|
| `services/document_record_service.py` | 加 logger（若無）與 5 處警告日誌 |
| `services/task_queue_service.py` | `update_status` 的 rowcount 讀取與警告日誌 |
| `tests/services/test_missing_target_warnings.py` | **新增** |
| `docs/報告/132_X3-A修復結果.md` | **新增** |
| `docs/報告/131_…SDD任務書.md` §5 回填區 | 只可填寫該區 |

## 3. 驗收（Claude 審核）

| # | 檢查 |
|---|---|
| A1 | diff 只有 §2 的檔案；**兩個 service 檔的 diff 全部是新增行**（`git diff` 無刪除行，除非 `import` 整理），且無任何 SQL 字串、回傳值、`raise`、控制流變動（Claude 逐行看） |
| A2 | 報告132 有 S2 RED 證據；缺失類測試先失敗 |
| A3 | SQL 軌跡與記錄快照與基準逐字相同（Claude 用自己的腳本副本獨立重跑各一次） |
| A4 | 完整回歸 = 1289＋新增測試數 passed、0 failed（Claude 獨立重跑）；既有測試未被修改 |
| A5 | 相依快照 cycles=0、邊數不變 |
| A6 | Claude 兩項故意破壞：(a) 刪掉 `mark_extraction_failed` 的一則警告 → 新增測試須失敗；(b) 把 `update_status` 缺失時改成 `return 0`（改回傳值）→ 既有 `test_set_status_on_missing_row_is_silent_noop` 等測試須失敗（驗完還原，不 commit） |

## 4. 回填區（Codex 填寫）

- commit SHA：`ed7c2c5`（`feat(observability): 缺失記錄／佇列列的寫入略過改為輸出 WARNING，行為零變動（報告131 X3-A）`；未 push）
- 自我檢查結果：基準 HEAD `1cb9985`、起始 worktree 乾淨；S2 RED 為 `6 failed, 3 passed`，實作後新增測試 `9 passed`；指定既有測試 `183 passed`；完整回歸 `1298 passed, 8 warnings`，沒有 UMAP 卡住，未使用 `--deselect`。SQL `operations`／`trace` 皆逐字相同；記錄快照 `scenarios`／`time_normalization` 皆逐字相同；相依快照 before/after 均 `151 modules, 420 edges, cycles=0`。兩個 service diff 均為 additions-only，既有測試未改，`set_document_vector` 未加日誌；repo 內 after import snapshot 已刪除。
- 新增測試數：9 個 pytest 實例（參數化 5 個 + 其他 4 個）。
- 意外狀況：基準 `data/analysis/import_graph_20260929.json` 是較早 checkout 的 148/415，不能直接作本次基準；已從本次 HEAD `1cb9985` 建立系統暫存 Git archive 取得正確 before `151/420`，並與 after 比對。執行 Git stage/commit 時 sandbox 需要核准的 worktree index 權限；未修改報告 95、未 push。

## 5. 禁止事項

- 不得改任何回傳值、不得新增 `raise`、不得改任何控制流或 SQL 文字。
- 不得處理 X1；不得改 `state/`、呼叫端、既有測試（含測試名稱）。
- 不得順手為 `set_document_vector` 加日誌。
- 不得 push；不啟動 Neo4j／Ollama／server。
