# 報告113：A8 補修——`resolve_document_folder` 判斷順序 SDD 任務書

> **日期**：2026-09-29
> **執行者**：Codex｜**設計與審核**：Claude Code
> **上位文件**：[報告110](110_A8虛擬歸屬抽取路徑修正SDD任務書.md)、[報告112](112_A8修正結果.md) §4 第二項限制
> **成果檔**：`docs/報告/114_A8補修結果.md`（Codex 建立）
> **性質**：小範圍程式補修。**缺陷出自報告110 §S3(a) 的規格（Claude 設計疏漏），不是 Codex 實作錯誤**；Codex 已在報告112 §4 誠實記錄此邊界。

---

## 0. 缺陷（Claude 已獨立重現）

`resolve_document_folder()` 目前先判斷 `kg_folder/<doc_id>` 是否為目錄。但虛擬歸屬下 `trigger_extraction()` 寫出 SVO 輸出後，`kg_folder/<doc_id>/` **就會存在**（只含 `svo_index.json` 等輸出，沒有 `_record.json`）。於是 worker 在真實流程中解出的是 KG 輸出目錄而非原文件資料夾，`record_chunk_completed`／`mark_extraction_failed` 仍靜默回 None——報告110 的 B3 在真實流程並未真正修好。

重現（輸出目錄建立後解析結果錯誤）：staging 建文件→虛擬 assign→`(kg_folder/doc).mkdir()`→`resolve_document_folder(kg_folder, doc.name)` 回傳 `kg_folder/doc`，預期應為原文件資料夾。報告110 的測試 `test_virtual_assign_record_updated_in_original_folder` 因為在輸出目錄建立**之前**呼叫 resolver，所以沒抓到。

## 1. 修正規格

判斷依據由「目錄是否存在」改為「該目錄是否持有記錄檔」。

**(a) `services/classify_service.py::resolve_document_folder`**：把函式本體改為（docstring 保留並補一句說明順序理由）：

```python
    physical = kg_folder / doc_id
    if document_record_service.read_record(physical) is not None:
        return physical
    manifest = _read_members_manifest(kg_folder)
    for entry in manifest.get("assigned_documents", []):
        if isinstance(entry, dict) and entry.get("doc_id") == doc_id:
            source_path = Path(str(entry.get("source_path", "")))
            if source_path.is_dir():
                return source_path
    return physical
```

docstring 補：「以 `_record.json` 存在與否判定實體位置（虛擬歸屬下 KG 端目錄只有 SVO 輸出、沒有記錄檔，不能以目錄存在與否判斷）。」

**(b) 測試**（只能**新增**，不得改既有測試）：在 `tests/services/test_virtual_assign_extraction_path.py` 末尾新增兩個測試：

| 測試 | 斷言 |
|---|---|
| `test_resolver_prefers_manifest_when_kg_side_has_only_svo_output` | 虛擬 assign 後，在 `kg_folder/<doc>/` 放一個 `svo_index.json`（模擬輸出已存在、無 `_record.json`），`resolve_document_folder` 回傳**原文件資料夾** |
| `test_full_flow_record_written_back_after_output_exists` | 走完整流程：`chunk_and_stage`→虛擬 assign→`trigger_extraction(..., kg_folder=kg_folder)`（輸出目錄此時已存在）→用與 worker 相同的解析方式 `resolve_document_folder(kg_folder, document_folder_path(source, kg_folder).name)` 取得資料夾→`document_record_service.record_chunk_completed(該資料夾, 1)`→斷言 `read_record(staging/<doc>)` 的 `completed_chunk_indices` 含 1，且 `kg_folder/<doc>/_record.json` 不存在 |

## 2. 步驟

1. **S1**：`git status -s` 必須為空。
2. **S2 先測後修**：先只新增 §1(b) 兩個測試，跑 `python -m pytest tests/services/test_virtual_assign_extraction_path.py -q -p no:cacheprovider`——**兩個新測試都必須失敗**（其餘 5 個仍過），記下失敗訊息。任一新測試意外通過就停下檢查測試寫法。
3. **S3**：套用 §1(a)。
4. **S4 驗證**：新測試檔 7 passed；完整回歸 `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py` 須 **1180 passed、0 failed**（1178＋2）；`test_physical_move_behavior_unchanged` 與 `test_resolve_document_folder_cases` 必須仍通過（若後者因情境 (a) 的建構方式在新順序下失敗，**不要改它**，回報失敗原因）。
5. **S5**：寫 `docs/報告/114_A8補修結果.md`（修正摘要、S2 失敗證據、S4 數字、已知限制）；無佔位符殘留。
6. **S6**：commit `fix(A8): resolve_document_folder 改以記錄檔判定實體位置（報告113）`，**不 push**。

## 3. 允許修改的檔案

`services/classify_service.py`、`tests/services/test_virtual_assign_extraction_path.py`（僅新增測試）、`docs/報告/114_A8補修結果.md`（新增）。其餘一律不動。

## 4. 驗收（Claude Code 審核）

| # | 檢查 |
|---|---|
| A1 | diff 僅上述 3 個檔案 |
| A2 | resolver 本體與 §1(a) 一致 |
| A3 | 報告114 有兩個新測試修正前失敗的證據 |
| A4 | 完整回歸 1180 passed、0 failed（Claude 獨立重跑） |
| A5 | Claude 以自己的重現腳本（輸出目錄建立後）確認解析結果為原文件資料夾 |

## 5. 禁止事項

- 不得修改既有測試；不動 `svo_service.py`、`extraction_worker.py`、`routers/staging.py`、`build_graph()`。
- 不 push、不啟動 Neo4j／Ollama／server。

## 6. 回填區（Codex 填寫）

- commit SHA：
- 自我檢查結果：
- 意外狀況：
