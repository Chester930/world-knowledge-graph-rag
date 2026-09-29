# 報告133：X1-A——文件 `failed` 狀態黏性修復 SDD 任務書（含 X3-A 收尾簡化；兩個獨立 commit）

> **日期**：2026-09-29
> **執行者**：Codex｜**設計與審核**：Claude Code
> **上位文件**：[報告130](130_X1_X3影響評估結果.md)（§5.1 選項 A、§4.2 推演）、[報告131](131_X3-A缺失目標警告日誌SDD任務書.md)／[132](132_X3-A修復結果.md)（X3-A 與其待簡化項）、[報告126](126_M2_P1第三批_SM1單一轉移入口SDD任務書.md)／[128](128_P1第三批結果.md)（SM-1 單一入口與驗證方法）
> **成果檔**：`docs/報告/134_X1-A修復結果.md`（Codex 建立，涵蓋兩個 commit）
> **性質**：**這是有意的行為變更**（P1 之後第一個）。使用者已於 2026-09-29 同意「X1 採選項一」。本任務含**兩個獨立 commit，順序固定**：
> **Commit 1**＝X3-A 收尾簡化（純重構，行為零變動，可用「逐字相同」驗收）；
> **Commit 2**＝X1-A 修復（行為變更，**不能**用逐字相同驗收，改用「前後對照表＋唯一差異」驗收）。
> 兩者絕不混在同一個 commit。不啟動 Neo4j／Ollama／server。

---

## 0. 設計（已定，不需 Codex 再判斷）

### 0.1 Commit 1：簡化 `_RowcountTrackingConnection`
報告132 的 X3-A 為了讓 diff 保持純新增，在 `services/task_queue_service.py` 新增了 12 行的 `_RowcountTrackingConnection` 包裝類別，僅為讀一個 `rowcount`。改為直接寫法（逐字採用）：

```python
    with closing(_connect(db_path)) as conn:
        cursor = conn.execute(
            "UPDATE task_queue SET status = ?, updated_at = datetime('now') "
            "WHERE kg_id = ? AND source = ? AND chunk_index = ?",
            (status, kg_id, source, chunk_index),
        )
        conn.commit()
        if cursor.rowcount == 0:
            status_value = status.value if isinstance(status, StateTaskStatus) else status
            logger.warning(...)   # 訊息與參數與現況完全相同，不改
```

並**刪除** `_RowcountTrackingConnection` 整個類別。SQL 文字一字不改、日誌訊息一字不改、回傳值仍為 `None`。

### 0.2 Commit 2：X1-A（`failed` 黏性至全量完成）
**語意**：某 chunk 失敗（文件狀態 `failed`）之後，其他 chunk 成功**不再**把狀態洗回 `processing`；只有完成集合涵蓋 total（FULL 事件）才轉 `completed`。無新增欄位、`_record.json` 格式不變。

**狀態轉移表的差異只有一格**（Claude 已核對 `state/document_sm.py` 現況）：

| 來源 | 事件 | 現況 | 修復後 |
|---|---|---|---|
| `FAILED` | `CHUNK_COMPLETED_PARTIAL` | `PROCESSING` | **`FAILED`** |

其餘 24 格**完全不變**（特別是：`FAILED + CHUNK_COMPLETED_FULL → COMPLETED` 保持；`RESET`／`REASSIGN`（任意→`PENDING`）保持——這是使用者重新歸屬或強制重建時清除失敗的既有管道；`MARK_FAILED`（任意→`FAILED`）保持）。

因為 P1 已把 `extraction_status` 的所有賦值集中到 `_transition_extraction()`，**production 邏輯的修改只有 `state/document_sm.py` 的那一格**；`document_record_service.py` 只需更新 `record_chunk_completed` 的 docstring（其 193-203 行原本聲稱「不再覆寫 failed」，修復後才與行為一致，措辭需微調使其準確描述「failed 黏性、FULL 才完成」）。**不得**在 `record_chunk_completed` 內另外加判斷邏輯。

**不變的部分（明確）**：`chunk_progress`／`completed_chunk_indices` 的更新、`failed` 之後 FULL 仍能完成、X3（缺記錄回 `None`＋警告）、`update_normalization_progress`、SM-2（佇列）全部不動。

### 0.3 為什麼這樣夠安全（Claude 的分析，需 Codex 以測試證實）
黏性 `failed` 的風險是「失敗 chunk 沒被重試時文件永遠停在 `failed`」（那正是我們要的訊號），但**可恢復路徑必須仍通**。報告130 §4／§5.1 指出讀取端 `build_graph`（`knowledge_graph_service.py:158-166`）與 `_reconcile_doc`（`task_queue_service.py:272-295`）都只略過 `completed`、對 `failed` 與 `processing` 一視同仁；因此修復前後的**重排行為應完全相同**，差別只在文件狀態欄位顯示 `failed` 而非 `processing`。本任務要用離線測試**證明**這一點，而不是只靠推論。

---

## 1. 步驟

### S1　基準
`git status -s` 為空；記錄 HEAD；完整回歸 `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py`（Claude 獨立基準 **1298**；若被既有 UMAP 三測試卡住，用 `--deselect` 排除並註明實際數字，預期 1295）。

### S2　Commit 1 前：確認驗證工具
確認你的暫存目錄仍有：SQL 軌跡腳本與 `baseline_sql_trace.json`（報告123／124）、記錄快照腳本與 `baseline_record_snapshots.json`（報告126／127）。若不存在，依報告124／127 附錄重建**但要用「修改前的程式碼」重新產生基準**（在 Commit 1 修改前先跑一次並保存）。

### S3　Commit 1：簡化（行為零變動）
1. 依 §0.1 修改 `services/task_queue_service.py`（只此一檔）。
2. 驗證（全部必須通過）：
   - `python -m pytest tests/services/test_missing_target_warnings.py tests/services/test_task_queue_service.py tests/services/test_extraction_worker.py tests/state -q -p no:cacheprovider` 全過；
   - **SQL 軌跡**：用軌跡腳本在修改後重跑（輸出 `after_sql_trace_c1.json`），`operations` 與 `trace` 兩欄與 baseline **逐字相同**，並含「對不存在列呼叫 `update_status`」的操作；
   - 完整回歸 **1298 passed**（與基準相同，無新增測試）；
   - 相依快照 `cycles=0`、420 邊不變（快照檔驗完刪除）；
   - `git diff` 確認：只刪除 `_RowcountTrackingConnection` 類別與其在 `update_status` 內的兩處使用，改為 `cursor = conn.execute(...)`／`cursor.rowcount`；日誌訊息文字與參數逐字不變。
3. commit：`refactor(task_queue): 簡化 update_status 的 rowcount 讀取，移除包裝類別，行為零變動（報告133 commit 1）`。**不 push。** 記下 SHA。

### S4　Commit 2 前：建立「修復前」行為對照基準（不改任何程式碼）
在系統暫存目錄寫一支腳本，用真實 `document_record_service` 函式在 `tmp` 資料夾對 **5 個來源狀態 × 5 個事件**（同 `tests/state/test_document_sm.py` 的參數化）逐格記錄實際結果，輸出 `x1_before_matrix.json`。**在改任何程式碼之前**先跑並保存。之後修復完成再跑一次得到 `x1_after_matrix.json`，兩者比對必須**恰有一格不同**（`failed × CHUNK_COMPLETED_PARTIAL`：`processing`→`failed`）。腳本全文貼入報告134 附錄。

### S5　Commit 2 先寫測試（RED）
1. **更新既有測試**（僅限這些，每一處都必須在報告134 §「測試變更清單」逐條列出理由）：
   - `tests/state/test_document_sm.py::test_x1_failed_then_partial_completion_is_processing`：預期改為 `FAILED`；函式名稱與 docstring 改為反映「已修復」（例如 `test_failed_stays_failed_on_partial_completion`，docstring 註明「報告130 X1 已於報告133 修復」）。**這是唯一允許改名的既有測試。**
   - 若 `tests/services/test_document_record_service.py` 等處有斷言「`failed` 後部分完成為 `processing`」的既有測試（報告130 Q6 指出 `::test_record_chunk_completed_does_not_falsely_complete_when_a_lower_index_is_missing`，**請先閱讀確認它是否真的涉及 `failed` 起點**，不涉及就不要動），依實際內容最小幅度更新。
   - **不得**改動其他任何既有測試；`test_document_sm_parity_with_real_functions` 讀表比對，表改了它自然會跟著驗證，**不需也不得改動**。
2. **新增重排路徑測試檔** `tests/state/test_x1a_retry_paths.py`（`tmp_path`、離線、不用 LLM／Neo4j；worker 行為以直接呼叫 `task_queue_service` 與 `document_record_service` 的函式來模擬，狀態呼叫序列與 `extraction_worker._process_one` 的失敗／成功分支一致）：

| 測試 | 情境 | 斷言 |
|---|---|---|
| `test_partial_success_after_failure_keeps_failed` | total=3；chunk 2 失敗（`mark_extraction_failed`＋queue `failed`）；chunk 1、3 成功 | 文件狀態 `failed`；完成集合 `[1,3]`；chunk 2 的 queue 列為 `failed` |
| `test_retry_via_enqueue_recovers_to_completed` | 承上；`enqueue(..., [2])` 重排 → queue 列 `pending` → 模擬 worker 成功處理 chunk 2 | 文件最終 `completed`，完成集合涵蓋 `[1,2,3]` |
| `test_retry_via_rebuild_from_records_recovers_to_completed` | 承第一個情境；刪除 queue DB 後呼叫 `rebuild_from_records` | 缺口 chunk 2 被重新排入 `pending`；模擬成功處理後文件 `completed` |
| `test_trusted_restart_leaves_existing_failed_queue_row` | 承第一個情境；`ensure_ready`（trusted 路徑，索引可信） | chunk 2 的 queue 列**仍為 `failed`**、文件仍 `failed`（**鎖定現況**：trusted restart 不自動重試 failed，見報告130 Q1；修復前後此行為相同） |
| `test_build_graph_does_not_skip_failed_documents` | 用 `test_knowledge_graph_service.py` 既有的 mock 手法（fake driver／`trigger_extraction` mock）：記錄狀態 `failed` 的文件，`build_graph(force_rebuild=False)` | `trigger_extraction` **被呼叫**（`failed` 不被「completed 略過」誤跳過） |
| `test_reset_and_reassign_still_clear_failed` | 文件 `failed` 後分別呼叫 `reset_extraction_progress`、`append_assignment` | 兩者都回到 `pending`（既有的清除管道未被黏性影響） |

3. 先在**尚未修改 `state/document_sm.py`** 時執行：`python -m pytest tests/state/test_document_sm.py tests/state/test_x1a_retry_paths.py -q -p no:cacheprovider`。預期：更新後的 X1 測試與 `test_partial_success_after_failure_keeps_failed` **失敗**（RED）；`retry_via_enqueue`／`rebuild`／`trusted_restart`／`build_graph`／`reset_and_reassign` 等在修復**前後**行為應相同，可能通過也可能因情境依賴而失敗——**如實記錄哪些失敗、哪些通過**，並解釋（尤其：`retry_via_*` 在修復前最終也應 `completed`，證明可恢復路徑不受黏性影響）。

### S6　Commit 2 實作
1. `state/document_sm.py`：把 `(FAILED, CHUNK_COMPLETED_PARTIAL)` 一格的值改為 `ExtractionStatus.FAILED`；同步更新該格上方註解與檔頭 docstring 中「X1 為既有行為」的說法，改為「X1 已於報告133 修復；`failed` 黏性至 FULL」。**只動這一格的值與相關註解。**
2. `services/document_record_service.py::record_chunk_completed` 的 docstring：微調使其準確描述行為（不改任何程式碼）。
3. 重新產生 `x1_after_matrix.json`，與 `x1_before_matrix.json` 比對：**恰有一格不同**。

### S7　Commit 2 驗證
1. 新增／更新的測試全過：`python -m pytest tests/state tests/services/test_document_record_service.py tests/services/test_task_queue_service.py tests/services/test_extraction_worker.py tests/services/test_knowledge_graph_service.py tests/services/test_missing_target_warnings.py -q -p no:cacheprovider`。
2. **行為矩陣比對**：`x1_before_matrix.json` vs `x1_after_matrix.json` 恰有一格不同（見 S4）。
3. **記錄快照比對（預期有差異，須完全符合預期）**：用報告127 附錄 A 的快照腳本在修復後重跑（輸出 `after_record_snapshots_x1a.json`），與 `baseline_record_snapshots.json` 比對。**預期唯一差異**是包含 X1 序列的情境中，「`failed` 之後完成 chunk」那一步的 `extraction_status`（`processing`→`failed`），以及其後續操作若受影響的欄位；其他 6 個情境必須逐字相同。請在報告134 用表格逐一列出**每一個**差異的（情境／操作／欄位／前值／後值），不得有預期之外的差異。若有預期之外的差異，停下回報。
4. **SQL 軌跡**：本批不改 SQL，`after_sql_trace_c2.json` 必須與 baseline 逐字相同。
5. 完整回歸：預期 **1298 ＋（新增測試數）passed、0 failed**（新增數請在報告134 列明；既有測試因更新而改名不改變總數）。
6. 相依快照：`cycles=0`；邊數與 Commit 1 後相同（新增測試不在快照內）。
7. commit：`fix(document_record): failed 狀態黏性，部分 chunk 成功不再洗回 processing，須全量完成才轉 completed（報告133 X1-A）`。**不 push。**

### S8　成果報告
建立 `docs/報告/134_X1-A修復結果.md`：兩個 commit 的 SHA 與摘要；**測試變更清單**（更新／改名／新增，逐條含理由）；S4 行為矩陣比對結果；S7-3 快照差異逐項表；重排路徑各測試的 RED／GREEN 記錄；回歸數字；**已知限制**（明確寫出：X3-C／X3-B 未做；trusted restart 不自動重試 `failed` chunk 的既有行為未動，因此「文件停在 `failed` 且無人重排」是可能且**預期**的狀態，需由 `enqueue`／`build_graph`／untrusted rebuild／重新歸屬處理；KG#4 全為 `completed` 不受影響）。無佔位符。

---

## 2. 允許修改／新增的檔案

| Commit | 檔案 |
|---|---|
| 1 | `services/task_queue_service.py`（僅簡化 `update_status`／移除包裝類別） |
| 2 | `state/document_sm.py`（一格的值＋註解／docstring）、`services/document_record_service.py`（僅 `record_chunk_completed` docstring）、`tests/state/test_document_sm.py`（僅 X1 測試的更新與改名）、依 S5-1 確認後**必要**的其他既有測試最小更新、`tests/state/test_x1a_retry_paths.py`（新增） |
| 兩者之外 | `docs/報告/134_X1-A修復結果.md`（新增，隨 Commit 2）、本任務書 §4 回填區 |

## 3. 驗收（Claude 審核）

| # | 檢查 |
|---|---|
| A1 | 恰有兩個功能 commit（＋文件）；Commit 1 只動 `task_queue_service.py`；Commit 2 的 production 變更**只有** `state/document_sm.py` 一格與一個 docstring，無新增邏輯（Claude 逐行看 diff） |
| A2 | **`DOCUMENT_TRANSITIONS` 相較修改前恰有一格不同**（Claude 用 `git diff` 與自己的腳本核對）；`TASK_TRANSITIONS`、`NORMALIZATION_TRANSITIONS` 不變 |
| A3 | Commit 1：SQL 軌跡逐字相同（Claude 獨立重跑）；日誌文字未變 |
| A4 | Commit 2：快照差異**完全符合預期**（唯一預期差異），其餘逐字相同（Claude 用自己的腳本獨立重跑並逐項比對） |
| A5 | 重排路徑 6 個測試存在且通過，並有 RED／GREEN 記錄；`retry_via_*` 證明可恢復路徑通暢 |
| A6 | 測試變更清單完整：被改動的既有測試僅限 S5-1 允許者，每處有理由（Claude 逐一核對 `git diff` 中對 `tests/` 的既有檔案改動） |
| A7 | Claude 獨立完整回歸 = 1298＋新增測試數 passed、0 failed；相依快照 0 循環 |
| A8 | Claude 故意破壞：(a) 把該格改回 `PROCESSING` → 更新後的 X1 測試與 `test_partial_success_after_failure_keeps_failed` 須失敗；(b) 在 `record_chunk_completed` 偷加一行 `record.extraction_status = "x"` → 結構性守門測試須失敗；(c) 讓 `FAILED + CHUNK_COMPLETED_FULL` 也變成 `FAILED` → `retry_via_*` 測試須失敗（驗完還原，不 commit） |

## 4. 回填區（Codex 填寫）

- Commit 1 SHA：`cce9947`（完整 SHA：`cce99479f0913347040daa558903ad0a8aa3f9cd`）
- Commit 2 SHA：`b400614`（完整 SHA：`b40061433af7e9792f25b0a553800b4d5b4afc49`）
- 自我檢查結果：S1 基準與 Commit 1 完整回歸均為 1298 passed；Commit 1 SQL operations／trace 逐字相同（15／96，含不存在列操作）；S4 25 格矩陣恰一格差異；記錄快照 scenarios／time_normalization 相同且唯一差異為 X1 的 extraction_status processing→failed；targeted 198 passed；最終完整回歸 1304 passed、8 warnings；依賴快照 151 modules／420 edges／0 cycles；A8 三項故意破壞均按預期失敗並已還原。未使用 --deselect，未修改報告95，未 push。
- 新增測試數：6（`tests/state/test_x1a_retry_paths.py`）
- 意外狀況：報告127快照腳本的 X1 assertion 原本鎖定修復前 `processing`；在系統暫存腳本副本僅將該 assertion 更新為修復後 `failed` 後重跑，其他腳本內容與 7 個情境均未改動。未發生 UMAP 卡住或預期外快照／矩陣差異。

## 5. 禁止事項

- 兩個 commit 不得合併；Commit 1 不得夾帶任何行為變更；Commit 2 不得夾帶 `task_queue_service.py` 的任何改動。
- 不得新增欄位、不得改 `_record.json` 格式、不得改 `extraction_worker`／`knowledge_graph_service`／`task_queue_service` 的重排邏輯或 SQL、不得處理 X3-B／C、不得收窄 `update_status()`。
- 不得在 `record_chunk_completed` 內新增判斷邏輯（修復只透過轉移表那一格）。
- 不得修改 S5-1 允許範圍以外的既有測試。
- 不得 push；不啟動 Neo4j／Ollama／server。
