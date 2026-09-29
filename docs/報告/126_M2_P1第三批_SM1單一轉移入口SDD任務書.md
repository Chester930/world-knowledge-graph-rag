# 報告126：M2 P1 第三批——SM-1 單一轉移入口 SDD 任務書（兩段式：先出替換對照表、等 Claude 核准再實作）

> **日期**：2026-09-29
> **執行者**：Codex｜**設計與審核**：Claude Code
> **上位文件**：[報告97](97_專案目標與BT_SM工作流設計.md) §6.2 D2／§6.5 P1、[報告120](120_狀態機現況轉移盤點結果.md)、[報告121](121_M2_P1第一批_狀態機Enum轉移表與特性測試SDD任務書.md)、[報告123](123_M2_P1第二批_SM2佇列詞彙統一SDD任務書.md)（兩段式流程範本）
> **成果檔**：`docs/報告/127_P1第三批替換對照表.md`（第一段）、`docs/報告/128_P1第三批結果.md`（第二段）
> **性質**：**P1 的實質內容**——`document_record_service` 內所有對 `extraction_status`／`normalization_status` 的寫入，集中到**單一私有入口**，由 `state/document_sm` 的轉移表決定結果。**行為零變動**：X1（`failed → processing`）、X3（缺記錄靜默回 `None`）、`update_normalization_progress` 的任意→任意**全部照現況保留**（使用者已於 2026-09-29 決定「不修，另案」）。第一段結束**必須停下**，收到 Claude 核准前不得進入第二段。不啟動 Neo4j／Ollama／server。

---

## 0. 設計（Claude 已讀碼確認，決定範圍）

SM-1 與 SM-2 不同：`_record.json` 是 JSON 檔，寫入是「讀出→改欄位→整檔原子寫回」（`_write_record()` 已用暫存檔＋`os.replace`），**沒有 SQL 併發原子性問題**，所以適合在 Python 端集中轉移。

### 現有寫入點（報告120 §1 Q1 已盤點；本任務要處理的）

| 現有位置（`services/document_record_service.py`） | 目前寫法 | 對應事件（`state.document_sm`） |
|---|---|---|
| `reset_extraction_progress()` 第 185 行 | `record.extraction_status = "pending"` | `DocumentEvent.RESET` |
| `record_chunk_completed()` 第 211-213 行 | `= "completed" if total and len(completed) >= total else "processing"` | `CHUNK_COMPLETED_FULL`（當 `total and len(...) >= total`）／`CHUNK_COMPLETED_PARTIAL`（其餘，含 `total` 為 0／`None`） |
| `mark_extraction_failed()` 第 223 行 | `= "failed"` | `MARK_FAILED` |
| `append_assignment()` 第 250 行 | `= "pending"` | `REASSIGN` |
| `update_normalization_progress()` 第 157 行 | `record.normalization_status = status` | `NormalizationEvent.SET_STATUS`（`target=status`） |
| `init_record()` 第 97 行（僅在 `total_chunks` 改變時） | `existing.normalization_status = "not_started"` | `NormalizationEvent.REPARSE_CHUNK_COUNT_CHANGED` |

（新建 `DocumentRecord` 的預設 `pending`／`not_started` 由 pydantic 模型預設值決定，不屬於「轉移」，**不動**。）

### 目標設計

在 `document_record_service.py` 新增**兩個私有函式**，成為這兩個欄位**唯一的賦值點**：

```python
def _transition_extraction(record: DocumentRecord, event: DocumentEvent) -> None:
    """SM-1 單一轉移入口（報告126）：extraction_status 只能在此被寫入。"""
    record.extraction_status = document_next_status(
        ExtractionStatus(record.extraction_status), event
    ).value

def _transition_normalization(
    record: DocumentRecord, event: NormalizationEvent, target: str | None = None,
) -> None:
    """SM-1b 單一轉移入口（報告126）：normalization_status 只能在此被寫入。"""
    record.normalization_status = normalization_next_status(
        NormalizationStatus(record.normalization_status), event,
        NormalizationStatus(target) if target is not None else None,
    ).value
```

（`.value` 使寫回 `record` 的仍是與現況相同的純 `str`；`_write_record` 序列化結果必須與現況逐位元組相同。以上簽章為**建議**，Codex 若有更小的等價做法可在第一段對照表提出，由 Claude 核准。）

### 硬性行為約束

1. **公開函式的簽章、回傳值、副作用、例外全部不變**。特別是：記錄不存在時仍靜默回 `None`（X3）；`update_normalization_progress` 的 `ValueError` 檢查順序不變；`record_chunk_completed` 的 `chunk_progress`／`completed_chunk_indices` 更新順序不變。
2. **`update_normalization_progress` 傳入非法 `status` 字串**：現況直接寫進去（pydantic 於下次讀取或寫入時才可能報錯）。改用 `NormalizationStatus(target)` 會在此處提早拋 `ValueError`，這是**行為變更**——第一段對照表必須明確判斷這一點，並提出**保持現況**的做法（例如先確認函式簽章上 `status` 已是 `Literal`，型別上不允許非法值；若要保持逐字相同行為，需說明測試如何證明）。**不得**在未經 Claude 核准下引入新的提前失敗。
3. 記錄檔的 JSON 輸出必須與現況**逐欄相同**（時間欄位如 `assigned_at` 除外，比對時正規化）。

---

## 1. 第一段：替換對照表（**只讀，不改任何程式碼**）

### S1　基準
`git status -s` 為空；記錄 HEAD；完整回歸 `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py`（Claude 獨立基準 **1286 passed**；若 Codex 環境被既有 UMAP 三測試卡住，用 `--deselect` 排除並註明實際數字）。

### S2　建立記錄快照基準（暫存目錄、不進版控）
寫一支腳本，對一組固定情境跑 `document_record_service` 的公開函式，**每個操作之後讀出 `_record.json` 的完整內容**存成 JSON（`assigned_at` 等時間欄位正規化為固定字串）。情境須涵蓋：
- `chunk_and_stage`→`append_assignment`→`set_svo_chunk_total(3)`→`record_chunk_completed(1)`→`(2)`→`(3)`→`reset_extraction_progress`；
- X1 序列：`mark_extraction_failed`→`record_chunk_completed(2)`；
- `total` 為 0（不設 `set_svo_chunk_total`，`total_chunks` 也為 0）時 `record_chunk_completed` 的結果（`processing`）；
- `update_normalization_progress` 四種狀態（含 `progress` 邊界）；
- `init_record` 在 `total_chunks` 改變時（重新解析）的 normalization 重設；
- `completed` 狀態下再 `append_assignment`。
**在改任何程式碼之前**先跑一次，輸出 `baseline_record_snapshots.json`；連跑兩次確認確定性（兩次相同）。腳本全文之後貼進報告127 附錄。

### S3　撰寫 `docs/報告/127_P1第三批替換對照表.md`
固定結構：

```markdown
# 報告127：P1 第三批替換對照表
> 日期 ｜ 基準 commit ｜ 執行者：Codex（依報告126）

## 1. 全專案 extraction_status／normalization_status 寫入點盤點（重新 git grep 確認）
## 2. 替換對照表
| # | 檔案:行號 | 目前程式碼 | 擬替換為 | 對應事件 | 行為是否改變？（必須為「否」） | 對應的既有對等測試 | 風險 |
## 3. 行為約束逐項判斷（§0 硬性約束 1–3）
（尤其第 2 項：非法 status 字串的處理，提出保持現況的具體做法）
## 4. 明確不替換的位置與理由
## 5. 驗證計畫
- 記錄快照逐字比對方式；將跑的測試；新增的「結構性守門測試」（見 §2 S5-3）
## 6. Claude 需要確認的問題
## 附錄 A：快照腳本全文
```

**第一段硬性規定**：除 `docs/報告/127_…md` 與本任務書 §5 回填區外，不得新增或修改 repo 內任何檔案；不得修 X1／X3；commit 報告127（訊息 `docs(報告127): P1 第三批替換對照表`），**不 push，然後停下回報等 Claude 核准。**

## 2. 第二段：實作（**僅在收到 Claude 明確核准後執行**）

### S4　實作
依**已被核准**的對照表修改 `services/document_record_service.py`（預期只有這一個 production 檔案）：新增兩個私有轉移函式、把 §0 表中 6 處賦值改為呼叫它們、新增 `from state.document_sm import …` import。原則：
- **公開函式簽章與行為零變動**（含 X1／X3）；
- 不改任何呼叫端（`extraction_worker`、`knowledge_graph_service`、`classify_service` 等）與既有測試；
- 若對照表中經核准的做法需要在 `state/document_sm.py` 增補內容，只可**新增**，不可改動既有 Enum／表／函式。

### S5　驗證
1. `python -m pytest tests/state tests/services/test_document_record_service.py tests/services/test_task_queue_service.py tests/services/test_extraction_worker.py tests/services/test_knowledge_graph_service.py -q -p no:cacheprovider` 全過。
2. **記錄快照逐字比對**：用**同一支** S2 腳本在修改後重跑，輸出 `after_record_snapshots.json`（不得覆寫 baseline），與 baseline **逐字相同**；任何差異停下回報。
3. **新增結構性守門測試**（新檔案 `tests/state/test_document_sm_single_entry.py`）：讀取 `services/document_record_service.py` 原始碼，斷言 `extraction_status =` 與 `normalization_status =`（賦值，排除 `==` 與型別註解）**只出現在** `_transition_extraction`／`_transition_normalization` 兩個函式體內。測試須先在第二段開頭用「尚未替換」的狀態確認會失敗（RED），實作後通過（GREEN），並在報告128 記錄。
4. 完整回歸：預期 **1286 + 新增測試數 passed、0 failed**。
5. 相依快照：`python scripts/analysis/import_graph_snapshot.py . data/analysis/import_graph_20260929_after_p1b3.json`：`cycles=0`；預期新增 `services.document_record_service → state.document_sm` 一條邊；`state` 仍零對外依賴；快照檔驗完刪除、不 commit。

### S6　成果報告與提交
建立 `docs/報告/128_P1第三批結果.md`（修改摘要、快照比對結果、RED／GREEN 證據、回歸數字、相依差異、已知限制——明確寫出 X1／X3 仍在）。commit 訊息 `refactor(document_record): SM-1 狀態寫入集中為單一轉移入口，行為零變動（報告126）`；**不 push**。

## 3. 允許修改的檔案

| 段 | 檔案 |
|---|---|
| 第一段 | 只有 `docs/報告/127_P1第三批替換對照表.md`（新增）與本任務書 §5 回填區 |
| 第二段（核准後） | `services/document_record_service.py`、`tests/state/test_document_sm_single_entry.py`（新增）、`docs/報告/128_P1第三批結果.md`（新增）；`state/document_sm.py` 僅可新增內容（需在對照表中先經核准） |

## 4. 驗收（Claude 審核）

| # | 檢查 |
|---|---|
| A1（第一段） | diff 只有報告127；6 個寫入點全在表內；§0 硬性約束 2（非法 status）有具體且保持現況的做法；快照腳本涵蓋 §S2 全部情境並已驗證確定性 |
| A2（第二段） | diff 只有 §3 允許的檔案；`document_record_service.py` 的公開函式簽章、回傳、例外、副作用順序無改動（Claude 逐行看 diff） |
| A3 | 記錄快照逐字相同（Claude 用自己的腳本獨立重跑一次，含 X1 序列與 `total=0` 情境） |
| A4 | 結構性守門測試 RED→GREEN 有證據；完整回歸 1286＋新增測試數 passed、0 failed（Claude 獨立重跑） |
| A5 | 相依快照 cycles=0；`state` 零對外依賴 |
| A6 | Claude 另做兩項故意破壞：(a) 把 `_transition_extraction` 的事件映射改錯一個（例如 `record_chunk_completed` 的 FULL／PARTIAL 對調），既有測試須失敗；(b) 在 `document_record_service.py` 另一處偷偷加一行 `record.extraction_status = "x"`，結構性守門測試須失敗（驗完還原，不 commit） |

## 5. 回填區（Codex 填寫）

- 第一段 commit SHA：本段報告127提交完成後的 SHA 於交付回報列出；基準 SHA 為 `29e108c`。
- 第二段 commit SHA：尚未執行，等待 Claude 對報告127的明確核准。
- 自我檢查結果：S1 已讀完本任務書與報告120 SM-1／SM-1b 現況，重新執行全專案 `git grep` 並確認 production 只有 6 個指定 status 賦值點。S2 在全新系統暫存根目錄建立快照腳本，先於任何程式碼變更跑出 `baseline_record_snapshots.json`，每個操作後讀取完整 `_record.json` 並正規化時間欄位；涵蓋正常序列、X1、total=0、normalization 四狀態與非法 status、total_chunks 改變重設、completed 後 append_assignment、X3，連跑兩次 `full_equal=True`（7 情境／33 操作）。S3 已產出 6 點替換對照表與非法 status 的 raw compatibility branch 方案；未修改 production、既有測試或公開函式行為。完整回歸 `1286 passed、0 failed`。
- 意外狀況：起始 worktree clean；因既有 `pytest-of-666`／`.pytest_cache` 權限警告，快照與 pytest 均使用全新 `C:\Users\666\AppData\Local\Temp\codex_report126_record_snapshots_20260929_01\`。UMAP 三測試未卡住、未排除；執行時僅出現既有 requests／pytest／UMAP／jieba warnings。未啟動 Neo4j／Ollama／server，未執行匯入／重抽，未 push。

## 6. 禁止事項

- 第一段：**任何程式碼變更**。第二段：未經核准的範圍擴大、修 X1／X3、收窄 `update_normalization_progress`、改動任何公開函式簽章／回傳／例外、改動呼叫端或既有測試、提早失敗（見 §0 硬性約束 2）。
- 不得 push；不啟動 Neo4j／Ollama／server。
