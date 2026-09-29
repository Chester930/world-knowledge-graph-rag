# 報告121：M2 P1 第一批——狀態機 Enum、轉移表與特性測試 SDD 任務書（純新增、不替換任何既有寫入）

> **日期**：2026-09-29
> **執行者**：Codex｜**設計與審核**：Claude Code
> **上位文件**：[報告97](97_專案目標與BT_SM工作流設計.md) §3／§6.2 D2／§6.5 P1、[報告120](120_狀態機現況轉移盤點結果.md)（**本任務唯一的行為依據**）
> **成果檔**：`docs/報告/122_P1第一批結果.md`（Codex 建立）
> **性質**：**純新增**。使用者已於 2026-09-29 選定 P1 切分選項 C（先只新增 Enum／事件／轉移表與特性測試，不替換任何 writer；之後分兩小批替換 SM-2、SM-1）。**不得修改任何既有的 production 檔案。** 不啟動 Neo4j／Ollama／server。

---

## 0. 目的與設計

M2 鐵則是「整理前後行為完全不變」。本批建立**行為的安全網與詞彙表**，而不動任何既有寫入：

1. 新增 `state/` 套件：狀態 Enum、事件 Enum、**照現況寫的**轉移表（來自報告120 §3 的三張矩陣）、兩個純函式（查表）。
2. 新增**對等測試（parity tests）**：對每個（來源狀態 × 事件）組合，呼叫**真正的既有函式**（`document_record_service`、`task_queue_service`），把觀察到的結果與轉移表逐格比對。轉移表若與現況不符，測試即失敗——這就是後續兩批替換寫入時的回歸網。
3. **本批不接線**：沒有任何 production 程式 import `state/`（模組 docstring 註明 `STATUS: characterization only, not wired (P1 batch 1)`）。

### 設計決定（已定，不需 Codex 再判斷）

| 項目 | 決定 |
|---|---|
| 位置 | 頂層新套件 `state/`（報告97 §6.3 目標結構），含 `__init__.py`、`document_sm.py`、`task_sm.py` |
| Enum 型別 | `enum.StrEnum`（Python 3.13 可用；值與現有 Literal 字串**逐字相同**，使日後替換可直接相容 JSON／SQLite） |
| 轉移表形式 | 純資料 `dict`，鍵為 `(來源狀態, 事件)`，值為目標狀態；**完整列舉、不留空格**（「不變」也要明寫成原狀態） |
| 查表函式 | 純函式、無 I/O、不 import `services/`、`models/`、`repositories/`、`core/`（`state/` 保持零依賴，避免 P1 之後產生循環） |
| 行為依據 | 只依報告120 §3.1／§3.2／§3.3 與 §5.2；**不得依「理想狀態機」自行增刪轉移** |
| 已知缺陷（X1／X3） | **照現況寫入表中並加註解**「既有行為（報告120 X1），另案再修」，測試鎖定它；**不得**在表中修掉 |

---

## 1. 要新增的內容（規格）

### 1.1 `state/document_sm.py`（SM-1、SM-1b）

檔頭 docstring 必須包含：`STATUS: characterization only, not wired (P1 batch 1)`、指向報告120／121、以及「轉移表描述**現況**而非理想；X1（`failed → processing`）為既有行為」。

需包含：

```python
class ExtractionStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    PENDING_UPLOAD = "pending_upload"   # 型別允許但 production 不可達（報告120 X2）

class DocumentEvent(StrEnum):
    RESET = "reset"                              # reset_extraction_progress()
    REASSIGN = "reassign"                        # append_assignment()
    CHUNK_COMPLETED_PARTIAL = "chunk_completed_partial"  # record_chunk_completed()，完成集合未達 total
    CHUNK_COMPLETED_FULL = "chunk_completed_full"        # record_chunk_completed()，完成集合達 total
    MARK_FAILED = "mark_failed"                  # mark_extraction_failed()

DOCUMENT_TRANSITIONS: dict[tuple[ExtractionStatus, DocumentEvent], ExtractionStatus]  # 5×5＝25 格，依報告120 §3.1

def document_next_status(current: ExtractionStatus, event: DocumentEvent) -> ExtractionStatus: ...

class NormalizationStatus(StrEnum):   # not_started / processing / completed / failed
class NormalizationEvent(StrEnum):
    SET_STATUS = "set_status"          # update_normalization_progress(status=...)
    REPARSE_CHUNK_COUNT_CHANGED = "reparse_chunk_count_changed"  # init_record() 於 total_chunks 改變時

def normalization_next_status(
    current: NormalizationStatus, event: NormalizationEvent, target: NormalizationStatus | None = None,
) -> NormalizationStatus: ...
```

行為規則（必須與報告120 一致）：
- `RESET`、`REASSIGN` → 任意來源皆 `PENDING`。
- `CHUNK_COMPLETED_PARTIAL` → 任意來源皆 `PROCESSING`（含 `FAILED → PROCESSING`，即 X1，加註解）。
- `CHUNK_COMPLETED_FULL` → 任意來源皆 `COMPLETED`（含 `FAILED → COMPLETED`）。
- `MARK_FAILED` → 任意來源皆 `FAILED`。
- `SET_STATUS` → 回傳 `target`（`target` 必須提供，否則 `ValueError`；任意來源→任一目標，報告120 §3.2）。
- `REPARSE_CHUNK_COUNT_CHANGED` → 任意來源皆 `NOT_STARTED`。

### 1.2 `state/task_sm.py`（SM-2）

檔頭 docstring 同上規則（`STATUS: characterization only, not wired (P1 batch 1)`）。

```python
class TaskStatus(StrEnum):   # pending / processing / completed / failed / pending_upload

class TaskEvent(StrEnum):
    ENQUEUE = "enqueue"                # enqueue()：不存在→pending；僅 completed／failed 重置為 pending；pending／processing／pending_upload 不變
    CLAIM = "claim"                    # claim_next_pending()：pending→processing；其餘不變
    RESET_STUCK = "reset_stuck"        # reset_stuck_processing()：processing→pending；其餘不變
    RECONCILE_INSERT = "reconcile_insert"  # _reconcile_doc() 的 INSERT OR IGNORE：不存在→pending；既有列不變
    SET_STATUS = "set_status"          # update_status()：既存列任意→任一目標；不存在則無動作

# 「來源」用 TaskStatus 或 None（None＝該列不存在）
TASK_TRANSITIONS: dict[tuple[TaskStatus | None, TaskEvent], TaskStatus | None]
def task_next_status(current: TaskStatus | None, event: TaskEvent, target: TaskStatus | None = None) -> TaskStatus | None: ...
```

行為規則（必須與報告120 §3.3 一致）：
- `SET_STATUS`：`current is None` → 回傳 `None`（靜默 no-op，X3，加註解）；否則回傳 `target`（`target` 必須提供，否則 `ValueError`）。**`SET_STATUS` 不放進 `TASK_TRANSITIONS`**（它依 `target` 而定），由 `task_next_status()` 特判；其餘四個事件 × 6 個來源（5 狀態＋`None`）＝24 格完整列舉在表中。
- `CLAIM`／`RESET_STUCK` 對 `None` → `None`；`ENQUEUE`／`RECONCILE_INSERT` 對 `None` → `PENDING`。

### 1.3 `state/__init__.py`
空檔或只有一行 docstring；**不做 re-export**（避免日後 import 圖出現不必要的邊）。

---

## 2. 對等測試（規格）

### 2.1 `tests/state/test_document_sm.py`（並新增 `tests/state/__init__.py`，比照 `tests/services/__init__.py`）

| 測試 | 內容 |
|---|---|
| `test_enum_values_match_model_literals` | `ExtractionStatus` 的值集合 = `typing.get_args` 取自 `models.knowledge_graph` 中 `extraction_status` 欄位的 Literal 型別參數；`NormalizationStatus` 同理對應 `normalization_status`（用 `DocumentRecord.model_fields[...].annotation` 取得） |
| `test_document_table_is_complete` | `DOCUMENT_TRANSITIONS` 恰有 25 個鍵，涵蓋所有（狀態×事件）組合 |
| `test_document_sm_parity_with_real_functions` | 以 `pytest.mark.parametrize` 覆蓋 5 狀態 × 5 事件：用 `chunk_and_stage()`（或既有測試用的 fixture 方式，參照 `tests/services/test_document_record_service.py`）在 `tmp_path` 建 `_record.json`，把 `extraction_status` 設為來源值後，呼叫對應的**真實函式**（RESET→`reset_extraction_progress`、REASSIGN→`append_assignment`、PARTIAL→`svo_total_chunks=3`＋完成集合為空時 `record_chunk_completed(folder,1)`、FULL→`svo_total_chunks=3`＋完成集合先為 `[1,2]` 再 `record_chunk_completed(folder,3)`、MARK_FAILED→`mark_extraction_failed`），斷言重新讀出的 `extraction_status` 等於 `document_next_status(來源, 事件)` |
| `test_x1_failed_then_partial_completion_is_processing` | 明確鎖定 X1：來源 `FAILED`＋`CHUNK_COMPLETED_PARTIAL` 的表值為 `PROCESSING`，且真實函式觀察一致；測試註解寫明「既有行為（報告120 X1），另案修復後此測試應同步更新」 |
| `test_normalization_parity` | 4 來源 × 4 目標：呼叫 `update_normalization_progress(folder, status=目標, progress=0)` 後狀態 = `normalization_next_status(來源, SET_STATUS, 目標)`；另測 `REPARSE_CHUNK_COUNT_CHANGED`：先建記錄、把 normalization_status 設成各來源值，再以**不同的** `total_chunks` 呼叫 `init_record()`，結果為 `NOT_STARTED` |
| `test_missing_record_writes_are_silent_noops` | 鎖定 X3：對不存在的資料夾呼叫 `record_chunk_completed`、`mark_extraction_failed`、`set_svo_chunk_total`、`reset_extraction_progress`、`update_normalization_progress` 皆回傳 `None` 且不拋例外、資料夾仍不存在（註解：既有行為，報告120 X3，另案） |
| `test_next_status_requires_target` | `normalization_next_status(..., SET_STATUS)` 未給 `target` 拋 `ValueError` |

### 2.2 `tests/state/test_task_sm.py`

| 測試 | 內容 |
|---|---|
| `test_task_enum_values_match_service_literal` | `TaskStatus` 值集合 = `typing.get_args(services.task_queue_service.TaskStatus)` |
| `test_task_table_is_complete` | `TASK_TRANSITIONS` 恰有 24 個鍵（4 事件 × 6 來源） |
| `test_task_sm_parity_with_real_functions` | 用 `tmp_path` 的 sqlite（`task_queue_service` 的既有函式，風格參照 `tests/services/test_task_queue_service.py`），對 6 來源（含 `None`＝該列不存在）× 4 事件（ENQUEUE、CLAIM、RESET_STUCK、RECONCILE_INSERT）比對表值；來源狀態以 `enqueue`＋`update_status` 建立；`RECONCILE_INSERT` 透過 `_reconcile_doc()` 觀察（若其前置條件過於複雜，可只觀察其 `INSERT OR IGNORE` 的最小等價路徑並在報告122 說明；**不得**為此修改 `task_queue_service`） |
| `test_set_status_accepts_any_transition_on_existing_row` | 5×5：對既存列 `update_status` 任意目標，結果 = `task_next_status(來源, SET_STATUS, 目標)`（含非法轉移 `completed→processing`、`failed→completed`、`pending→completed`，註解：既有行為，報告120 §5.2） |
| `test_set_status_on_missing_row_is_silent_noop` | 鎖定 X3：不存在的列，`update_status` 回傳 `None`、該列仍不存在；`task_next_status(None, SET_STATUS, 任一目標)` 為 `None` |
| `test_claim_and_reset_on_absent_row` | `None` 來源對 `CLAIM`／`RESET_STUCK` 的表值為 `None` |

---

## 3. 步驟

1. **S1**：`git status -s` 必須為空；記錄 `git rev-parse HEAD`；跑基準 `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py`（預期 1183 passed）。若系統暫存目錄有 `pytest-of-666` 權限殘留，改用全新的暫存根目錄（`--basetemp`），並在報告記錄。
2. **S2 先寫測試**：先建立 `state/` 的**空殼**（Enum 與函式簽章，函式先拋 `NotImplementedError`、表先留空 dict）與兩個測試檔，跑 `python -m pytest tests/state -q -p no:cacheprovider`：預期**大量失敗**（表未填），記下失敗數與摘要。
3. **S3 實作**：依 §1 填入 Enum、轉移表與函式。**先讀報告120 §3 再填表，每格必須對得上其證據**。
4. **S4 驗證**：
   - `python -m pytest tests/state -q -p no:cacheprovider` 全過；若對等測試失敗，代表表與現況不符——**修表，不要改既有 production 函式或既有測試**，並在報告122 記錄這格的差異與原因。
   - 完整回歸須 `1183 + 新增測試數` passed、0 failed（新增測試數請在報告122 明確列出；`test_document_sm_parity_with_real_functions` 等以 parametrize 展開的用例照 pytest 實際計數）。
   - 確認沒有任何 production 檔案 import `state`：`git grep -n "^from state\|^import state" -- '*.py'` 只應出現在 `tests/state/` 內。
   - 相依快照：`python scripts/analysis/import_graph_snapshot.py . data/analysis/import_graph_20260929_after_p1b1.json`：`cycles=0`；與 `data/analysis/import_graph_20260929.json` 比對，預期新增 `state.*` 模組（快照排除 tests）且 fan-in 為 0；其餘差異（A8 與 build_graph 防護已有的兩條新邊）需區分；**該 after 快照檔驗完刪除、不 commit**。
5. **S5 成果報告**：`docs/報告/122_P1第一批結果.md`（修改摘要、S2 失敗證據、S4 數字含新增測試數、對等測試若發現表與現況差異的紀錄、已知限制）。無佔位符。
6. **S6**：commit，訊息 `feat(state): P1 第一批——SM Enum、現況轉移表與對等特性測試（報告121）`。**不 push。**

---

## 4. 允許修改／新增的檔案（其餘一律不動）

| 檔案 | 性質 |
|---|---|
| `state/__init__.py`、`state/document_sm.py`、`state/task_sm.py` | 新增 |
| `tests/state/__init__.py`、`tests/state/test_document_sm.py`、`tests/state/test_task_sm.py` | 新增 |
| `docs/報告/122_P1第一批結果.md` | 新增 |
| `docs/報告/121_…SDD任務書.md` 第 7 節「回填區」 | 只可填寫該區，不得動其他段落 |

## 5. 禁止事項

- **不得修改任何既有的 production 檔案與既有測試**（含 `document_record_service.py`、`task_queue_service.py`、`extraction_worker.py`、`models/`）。本批是純新增。
- 不得讓任何 production 程式 import `state/`（不接線；接線是下兩批）。
- 不得修 X1／X3 或收窄 `update_status()`；不得在轉移表中加入「理想」轉移。
- 不得讓 `state/` import `services/`、`models/`、`repositories/`、`core/`。
- 不啟動 Neo4j／Ollama／server；不 push。

## 6. 驗收（Claude Code 審核）

| # | 檢查 |
|---|---|
| A1 | diff 只有 §4 的檔案；**無任何既有檔案被修改**（`git diff --stat` 全為新增，回填區除外） |
| A2 | 轉移表逐格與報告120 §3 一致（Claude 逐格抽查，特別是 X1、`enqueue` 終態重置、`None` 來源） |
| A3 | 對等測試確實呼叫**真實函式**而非只驗表本身（Claude 讀測試碼確認） |
| A4 | 報告122 有 S2 失敗證據；完整回歸 = 1183＋新增測試數 passed、0 failed（Claude 獨立重跑） |
| A5 | `git grep` 確認 production 無人 import `state`；`state/` 無對 services／models／repositories／core 的 import |
| A6 | 相依快照 cycles=0；Claude 另做「故意破壞」驗證：暫時把表的一格改錯，對等測試會失敗（驗完還原，不 commit） |

## 7. 回填區（Codex 填寫）

- commit SHA：本批 S6 提交完成後的 SHA 於交付回報列出；基準 SHA 為 `f1d535f810def838c837ecabb04223c32f72b021`。
- S1–S6 自我檢查結果：S1 已確認 worktree clean、記錄基準 SHA，並因 `pytest-of-666` 權限殘留改用全新 `--basetemp`。S2 先建立空殼與測試，得到 `100 failed, 3 passed`；S3 再填入 Enum、現況轉移表與純查表函式，沒有修改既有 production／既有測試；S4 新增測試 `103 passed, 0 failed`，import 快照 `cycles=0` 且 state 三模組 fan-in=0，對等測試沒有發現表與真實函式差異。完整回歸已完成部分為 `1283 passed, 0 failed`；剩餘 3 個既有 UMAP 測試因環境超過 10 分鐘無輸出而未完成，詳見報告122 §5.3，未將其計為 passed。S5 已建立報告122並記錄 RED、對等測試、相依快照與回歸限制；S6 將提交允許檔案且不 push。
- 新增測試數：103（以 pytest 實際 collect／parametrize 展開計數）。
- 意外狀況：系統暫存目錄存在無法讀取的 `C:\Users\666\AppData\Local\Temp\pytest-of-666`，已改用全新 basetemp。既有報告95曾被編輯器格式化，已依指示 restore。既有 `tests/services/test_cluster_service.py` 的 3 個 UMAP 測試在本環境長時間無輸出；未為了跑通而修改任何既有檔案，結果與限制已如實記錄於報告122。
