# 報告123：M2 P1 第二批——SM-2 任務佇列詞彙統一 SDD 任務書（兩段式：先出替換對照表、等 Claude 核准再實作）

> **日期**：2026-09-29
> **執行者**：Codex｜**設計與審核**：Claude Code
> **上位文件**：[報告97](97_專案目標與BT_SM工作流設計.md) §6.5 P1、[報告120](120_狀態機現況轉移盤點結果.md)、[報告121](121_M2_P1第一批_狀態機Enum轉移表與特性測試SDD任務書.md)／[122](122_P1第一批結果.md)（`state/` 與 103 個對等測試）
> **成果檔**：`docs/報告/124_P1第二批替換對照表.md`（第一段）、`docs/報告/125_P1第二批結果.md`（第二段）
> **性質**：**這是 M2 第一次改動 production 程式碼**，使用者已同意（2026-09-29）並要求「Codex 先輸出替換點前後對照表，Claude 審過才准實作」。因此本任務分**兩段**，**第一段結束必須停下回報，未收到 Claude 的核准前不得進入第二段**。不啟動 Neo4j／Ollama／server。

---

## 0. 設計結論（Claude 已讀碼確認，決定範圍）

`services/task_queue_service.py` 中 SM-2 的狀態語意**寫在原子 SQL 語句裡**，不是散落的 Python 字串：

| 位置 | 語句 | 原子性要求 |
|---|---|---|
| `enqueue()` 78-87 | `INSERT … ON CONFLICT DO UPDATE … WHERE status IN ('completed','failed')` | 單一 UPSERT |
| `claim_next_pending()` 153-162 | `UPDATE … SET status='processing' WHERE (…)=(SELECT … 'pending' …) RETURNING` | **多 Worker 併發安全依賴這一句原子語句**（docstring 127-146 明說） |
| `reset_stuck_processing()` 184-190 | SELECT＋UPDATE `'processing'→'pending'` | 同一連線內 |
| `_reconcile_doc()` 279-289 | `INSERT OR IGNORE … 'pending'` | — |
| `update_status()` 91-103 | 依主鍵 UPDATE，任意→任意（報告120 §3.3.2） | — |

因此：**不得**把這些語句改成「Python 端 `transition()` 讀出舊值→查表→寫回」（會破壞 `claim_next_pending` 的併發原子性，並可能改變 `update_status` 的任意→任意行為）。SM-2 的「單一入口」語意由 SQL 本身承擔，`state/task_sm` 的轉移表是**規格與驗證依據**（已由 103 個對等測試綁定到真實函式）。

所以第二批的正確、風險最小的範圍是「**詞彙統一**」：

1. Python 端對狀態的寫入（目前只有 `extraction_worker.py` 的 4 個 `update_status(...)` 呼叫，見上表所引的 78／146／161／163 行）改用 `state.task_sm.TaskStatus` 成員（`StrEnum`，值與原字串逐字相同）；
2. `task_queue_service.update_status()` 的型別標註改為同時接受 `TaskStatus`（保留既有 `Literal` 別名不刪，避免破壞 `tests/state/test_task_sm.py::test_task_enum_values_match_service_literal`）；
3. **SQL 語句文字一律不改**（一個字元都不改）；
4. 這是 `state/` 的**第一個 production import**——同時驗證接線與相依圖沒有循環。

「SM-1 單一 `transition()` 入口」才是 P1 實質內容，留到第三批（`document_record_service` 是 JSON 記錄、無併發原子性問題，適合 Python 端轉移）。

## 1. 第一段：替換對照表（**只讀，不改任何程式碼**）

### S1　確認基準
`git status -s` 為空；記錄 HEAD；執行完整回歸 `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py`（Claude 獨立基準 = **1286 passed**）。**若 Codex 環境因既有 UMAP 測試（`tests/services/test_cluster_service.py::TestReduceDimensionality`）卡住，請用 `--deselect` 排除那 3 個並在報告註明實際數字（預期 1283）**；驗收時以 Claude 獨立完整回歸為準。

### S2　建立 SQL 執行軌跡基準（暫存目錄，不進版控）
在系統暫存目錄寫一支腳本，用 `unittest.mock.patch.object(task_queue_service, "_connect", …)` 包裝連線，對每個新連線呼叫 `conn.set_trace_callback(記錄函式)`，把**實際執行的 SQL 語句（已展開綁定參數）依序記錄**。腳本跑一組固定情境：`enqueue([1,2,3])`→`claim_next_pending`×2→`update_status(pending_upload)`→`update_status(completed)`→`update_status(failed)`→`reset_stuck_processing`→再次 `enqueue`；另用 mock `driver` 與 fake `_process_one` 依賴不便時，可直接依序呼叫 worker 內那 4 個 `update_status` 對應的呼叫形式（`processing`→`failed`；`processing`→`pending_upload`→`completed`）。**在改任何程式碼之前**先跑一次並把軌跡存成暫存 JSON（`baseline_sql_trace.json`）。腳本全文之後貼進報告124 附錄。

### S3　撰寫 `docs/報告/124_P1第二批替換對照表.md`
固定結構：

```markdown
# 報告124：P1 第二批替換對照表
> 日期 ｜ 基準 commit ｜ 執行者：Codex（依報告123）

## 1. 全專案 SM-2 狀態寫入點盤點
（`git grep` 結果：所有對 task_queue.status 的 Python 端寫入與 SQL 寫入；標註 production／腳本／測試）

## 2. 替換對照表
| # | 檔案:行號 | 目前程式碼 | 擬替換為 | 改變 SQL 文字？（必須為「否」） | 對應的既有對等測試 | 風險 |

## 3. 明確不替換的位置與理由
（例如各 SQL 語句、`Literal` 別名、測試與腳本內的字串）

## 4. 驗證計畫
- SQL 軌跡比對方式（S2 基準 vs 第二段完成後）
- 將跑哪些測試

## 5. Claude 需要確認的問題
（任何你認為範圍或設計需要調整的地方）

## 附錄 A：SQL 軌跡腳本全文
```

**第一段的硬性規定**：
- 除 `docs/報告/124_…md` 外不得新增或修改 repo 內任何檔案（暫存腳本在系統暫存目錄）。
- 對照表**必須涵蓋 §0 所述 4 個 worker 呼叫與 `update_status` 型別標註**；若你發現 §0 遺漏的 Python 端寫入點（例如 `main.py`、`scripts/`、`routers/`），列入表中並標明是否在範圍內，**不要自行擴大範圍**。
- commit 報告124（訊息 `docs(報告124): P1 第二批替換對照表`），**不 push，然後停下回報，等 Claude 核准。**

## 2. 第二段：實作（**僅在收到 Claude 明確核准後執行**）

### S4　實作
依**已被核准**的對照表修改（預期只有 `services/extraction_worker.py` 與 `services/task_queue_service.py` 的型別標註，可能加上必要的 `from state.task_sm import TaskStatus`）。原則：
- **SQL 文字零變動**；`Literal` 別名保留；
- 值以 `TaskStatus.X` 成員傳入。若 `sqlite3` 綁定 `StrEnum` 成員遇到任何行為差異（例如綁定失敗或存成非預期值），**改傳 `.value`** 並在報告說明；
- 不改任何既有測試；如需補測，只能在 `tests/state/` 或新檔案**新增**。

### S5　驗證
1. `python -m pytest tests/state tests/services/test_task_queue_service.py tests/services/test_extraction_worker.py -q -p no:cacheprovider` 全過。
2. **SQL 軌跡逐字比對**：以 S2 同一腳本重跑，產生 `after_sql_trace.json`，與 `baseline_sql_trace.json` **必須逐字相同**（順序、語句、展開後參數）。任何差異都要停下回報，不得自行判定「無害」。
3. 完整回歸：預期 **1286 passed、0 failed**（同 S1 的 UMAP 說明）。
4. 相依快照：`python scripts/analysis/import_graph_snapshot.py . data/analysis/import_graph_20260929_after_p1b2.json`：`cycles=0`；`state.task_sm` 的 fan-in 應為 1 或 2（`extraction_worker`，若 `task_queue_service` 也 import 則為 2），`state` 仍不得 import services／models／repositories／core；**該快照檔驗完刪除、不 commit**。
5. `git grep -n "update_status(" -- "*.py"` 確認 production 內已無字串字面量參數（測試檔內可保留）。

### S6　成果報告與提交
建立 `docs/報告/125_P1第二批結果.md`（修改摘要、SQL 軌跡比對結果、回歸數字、相依快照差異、已知限制）；commit 訊息 `refactor(task_queue): SM-2 狀態寫入改用 TaskStatus 詞彙，SQL 語意零變動（報告123）`；**不 push**。

## 3. 允許修改的檔案

| 段 | 檔案 |
|---|---|
| 第一段 | 只有 `docs/報告/124_P1第二批替換對照表.md`（新增）與本任務書 §5 回填區 |
| 第二段（核准後） | `services/extraction_worker.py`、`services/task_queue_service.py`（僅型別標註與 import）、`docs/報告/125_P1第二批結果.md`（新增）；如需補測只可**新增** `tests/state/` 下檔案 |

## 4. 驗收（Claude 審核）

| # | 檢查 |
|---|---|
| A1（第一段） | diff 只有報告124；對照表涵蓋 4 個 worker 呼叫＋型別標註；「改變 SQL 文字」欄全為「否」；附錄有可重跑的軌跡腳本；有列出 §0 以外的發現（即使結論是「沒有」） |
| A2（第二段） | diff 只有 §3 允許的檔案；`task_queue_service.py` 的 diff **不含任何 SQL 字串變動**（Claude 逐行看） |
| A3 | SQL 軌跡逐字相同（Claude 自己用同一支腳本獨立重跑一次） |
| A4 | 完整回歸 1286 passed、0 failed（Claude 獨立重跑）；`tests/state` 103 個不變 |
| A5 | 相依快照 cycles=0；`state` 零對外依賴 |
| A6 | Claude 另做「故意破壞」：把 worker 的一個 `TaskStatus.X` 改成錯的成員，`tests/services/test_extraction_worker.py` 須失敗（驗完還原，不 commit） |

## 5. 回填區（Codex 填寫）

- 第一段 commit SHA：本段報告124提交完成後的 SHA 於交付回報列出；基準 SHA 為 `95ddeba38823c8188fd835785928c1bd51c4a954`。
- 第二段 commit SHA：本段提交完成後的 SHA 於交付回報列出。
- 自我檢查結果：S4 僅修改核准的 `services/extraction_worker.py` 四個 `update_status` 呼叫與 `services/task_queue_service.py` 的型別標註／import；保留 service 端 `TaskStatus` Literal，沒有修改 SQL、既有測試、X1 或 X3。S5 targeted 回歸為 `141 passed、0 failed`；after 腳本複製 baseline、改傳 `TaskStatus.X` 並輸出獨立的 `after_sql_trace.json`，只比較 `operations` 與 `trace` 且均逐字相同；完整回歸為 `1286 passed、0 failed`。相依快照為 151 modules、419 edges、`cycles=0`、`state.task_sm` fan-in=2、fan-out=0，state 無 services/models/repositories/core 依賴；production grep 無字串狀態參數。S6 已產出報告125，待本段提交。
- 意外狀況：起始 worktree clean；先前存在的 `pytest-of-666`／`.pytest_cache` 權限警告未直接使用，所有本批 pytest 與 trace／快照均改用全新 `C:\Users\666\AppData\Local\Temp\codex_report125_sqltrace_20260929_01\`。UMAP 三測試未卡住、未排除；執行時僅出現既有 requests／pytest／UMAP／jieba warnings。未啟動 Neo4j／Ollama／server，未執行匯入／重抽，未 push。

## 6. 禁止事項

- 第一段：**任何程式碼變更**。第二段：未經核准的範圍擴大、任何 SQL 字串變動、把原子 SQL 改成 Python 端讀後寫、修 X1／X3、收窄 `update_status()`、修改既有測試。
- 不得 push；不啟動 Neo4j／Ollama／server。
