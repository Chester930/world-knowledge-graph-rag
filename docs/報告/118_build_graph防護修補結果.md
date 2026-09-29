# 報告118：`build_graph` 清空前虛擬成員防護修補結果
> 日期：2026-09-29 ｜ 基準 commit：5d0d147 ｜ 執行者：Codex（依報告117）

## 1. 總結

本次只加入清空前防護，不讓 `build_graph()` 支援虛擬成員。當 `_members.json` 有成員但 `kg_folder/<doc_id>/_record.json` 不存在時，`force_rebuild=True, doc_ids=None` 會在任何 `DETACH DELETE` 或抽取進度重設之前拋出 `VirtualMembersNotRebuildableError`；非 force 模式只記錄 warning 並維持原行為。router 將此例外轉為 HTTP 409。

防護的目的，是阻止報告116確認的「先清空 Neo4j、之後卻無法重抽虛擬成員」資料損失路徑；manifest resolver、佇列重建、來源 charset 與匯入腳本的完整虛擬成員支援仍留給 M2。

## 2. S1–S6 執行紀錄

### S1　乾淨基準

- 執行前 `git status -s` 為空。
- 分支：`worktree-sdd-retrieval-comparison`。
- 基準 HEAD：`5d0d14794f4a068dc9b27d799a56879c4edf78de`。
- 基準命令：`python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py`；完整測試集合加 `--maxfail=1`（無失敗，因此仍跑完整集合）結果為 **1180 passed, 8 warnings**。
- 既有 `tests/services/test_knowledge_graph_service.py` 基準為 **11 passed**。

### S2　先寫失敗測試

只在 `tests/services/test_knowledge_graph_service.py` 原檔末尾新增三個測試，沒有修改既有測試。修補前執行結果為 **2 failed, 12 passed**：

1. `test_force_rebuild_aborts_before_delete_when_virtual_members_exist`：因 `svc.VirtualMembersNotRebuildableError` 尚不存在而出現 `AttributeError`；這是預期的第一個 RED 證據。
2. `test_force_rebuild_ok_when_manifest_members_have_kg_side_record`：通過；現況對有 KG-side `_record.json` 的 manifest 成員會照常清空並觸發抽取。
3. `test_non_force_build_with_virtual_members_logs_warning_and_continues`：warning 斷言為 false；這是預期的第三個 RED 證據。

測試新增位置：`tests/services/test_knowledge_graph_service.py:314-433`。

### S3　最小實作

| 檔案 | 修改 |
|---|---|
| `services/knowledge_graph_service.py:6-57` | 加入 `logging`、`classify_service` import、logger、`VirtualMembersNotRebuildableError` 與 `_unrebuildable_virtual_members()`。import 前以 `python -c "import services.knowledge_graph_service"` smoke test，且 `classify_service.py` 沒有反向 import `knowledge_graph_service`，未發現循環 import。 |
| `services/knowledge_graph_service.py:104-151` | 在既有 `ArticleStructureLossError` 檢查後、`DETACH DELETE` 與 `reset_extraction_progress` 前檢查 manifest 缺少 KG-side record 的成員；force 全庫重建拋錯，非 force 記 warning。 |
| `routers/knowledge_graph.py:48-56` | 僅將 `VirtualMembersNotRebuildableError` 轉為 HTTP 409；沒有改動 `ArticleStructureLossError` 的映射。 |
| `tests/services/test_knowledge_graph_service.py:314-433` | 僅新增三個指定測試；沒有改既有測試。 |

沒有修改 `trigger_extraction`、`extraction_worker`、`classify_service`、`task_queue_service`、匯入腳本，也沒有讓 `build_graph` 解析 manifest source path 來支援虛擬成員。

### S4　驗證

- import smoke test：通過。
- `python -m pytest tests/services/test_knowledge_graph_service.py -q -p no:cacheprovider`：使用新的系統暫存根目錄重跑後 **14 passed**。
- 完整回歸：`python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py --maxfail=1`：**1183 passed, 8 warnings**。
- 相依快照：`modules=148 edges=417 cycles=0 syntax_errors=0`。
- 與 `data/analysis/import_graph_20260929.json` 比對：
  - 新增：`services.knowledge_graph_service → services.classify_service`（本任務）。
  - 新增：`services.extraction_worker → services.classify_service`（報告110／A8 已有的變更，與本任務分開識別）。
  - 移除：無。
- `data/analysis/import_graph_20260929_after_guard.json` 已在核對後刪除，沒有進版控。

### S5　成果報告

本文件建立完成，沒有未填佔位符；已記錄 RED 證據、回歸數字、快照差異與已知限制。

### S6　提交前檢查

提交前確認 diff 僅包含任務書 §2 的四個檔案，且測試檔只在 EOF 新增。commit 不 push。

## 3. 已知限制

- 本修補只「擋住」force 全庫清空，不讓 `build_graph()` 支援虛擬成員。
- `doc_ids` 局部重建仍會對 manifest 缺少 KG-side `_record.json` 的成員記錄 warning，並沿現況靜默略過；本次只保護 `force_rebuild=True, doc_ids=None` 的全庫清空路徑。
- `ArticleStructureLossError` 在 router 仍未映射，本次刻意不處理。
- `rebuild_from_records()`、`_kg_source_charset()`、匯入腳本與評測 scope resolver 的虛擬成員支援仍未實作，屬 M2／另案範圍。

## 4. 意外狀況

S1 的一次無 `--maxfail` 基準執行在早期輸出 `E` 且超過 19 分鐘未結束，已中止；之後同一測試集合以 `--maxfail=1` 完整完成並得到 1180 passed。S3 修補後第一次服務測試因系統暫存既有 `pytest-of-666` 權限殘留而出現 `3 passed, 11 errors`（`tmp_path` setup 的 `PermissionError`），沒有修改測試或 repo；改用全新系統暫存根目錄後得到預期的 14 passed。這些暫存目錄均不在版控。

## 5. 修改檔案

本次預期提交的四個檔案：

1. `services/knowledge_graph_service.py`
2. `routers/knowledge_graph.py`
3. `tests/services/test_knowledge_graph_service.py`
4. `docs/報告/118_build_graph防護修補結果.md`
