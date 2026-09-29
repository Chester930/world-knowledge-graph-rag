# 報告117：`build_graph` 清空前虛擬成員防護 SDD 任務書（防護性最小修補）

> **日期**：2026-09-29
> **執行者**：Codex｜**設計與審核**：Claude Code
> **上位文件**：[報告116](116_虛擬成員盲點追查結果.md)（風險1）、[報告110](110_A8虛擬歸屬抽取路徑修正SDD任務書.md)（流程範本）
> **成果檔**：`docs/報告/118_build_graph防護修補結果.md`（Codex 建立）
> **性質**：**防護性最小修補**，使用者已於 2026-09-29 同意（「先做 a 再 c」）。**不是**讓 `build_graph()` 支援虛擬成員（那屬 M2 設計，見 §5）；只確保「清空 Neo4j 之後會有成員無法重抽」的情況下**先中止、不清空**。不啟動 Neo4j／Ollama／server。

---

## 0. 背景（已由 Claude 讀碼與實地驗證）

- `build_graph(force_rebuild=True, doc_ids=None)` 在 `services/knowledge_graph_service.py:111-112` 先執行 `MATCH (n {kg_id:$kg_id}) DETACH DELETE n`，之後只對 `kg_folder.iterdir()` 找到、且 `read_record()` 讀得到記錄檔的子資料夾重抽（114-122 行）。
- 虛擬歸屬成員（`kg_folder/_members.json` 的 `assigned_documents`）沒有 `kg_folder/<doc_id>/_record.json`（文件只存一份於暫存區／中央池），所以清空後**不會被重抽**——資料損失路徑（報告116 Q3，已用 mock 重現）。
- 已驗證：KG#4 與本機所有 KG 目前都沒有 `_members.json`（HANDOVER 2026-09-29），此路徑目前是潛在風險；本任務把它堵住。
- 既有先例：同函式 97-109 行的 `ArticleStructureLossError` 防呆——**在任何破壞性動作之前**整批檢查、寧可直接拋出。本任務沿用同一模式與位置。
- 判定「無法重抽」的規則：manifest 中每個 `assigned_documents` 的 `doc_id`，若 `document_record_service.read_record(kg_folder / doc_id)` 為 `None`，即為「build_graph 無法重抽的虛擬成員」。（實體搬移模式不寫 manifest；混合情況下，manifest 內的成員若在 KG 端仍有 `_record.json` 則視為可重抽。）

## 1. 步驟

### S1　確認乾淨基準
`git status -s` 為空；記錄 `git rev-parse HEAD`；`python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py` 記錄基準（預期 1180 passed）。

### S2　先寫失敗測試（不改任何非測試檔）
在既有的 `tests/services/test_knowledge_graph_service.py` **末尾新增**（不得改動既有測試）三個測試，風格參照該檔第 178-203 行附近 `ArticleStructureLossError` 的既有測試（fake driver 記錄 `execute_query` 呼叫、`tmp_path` 建 KG 資料夾、mock `KGRepository.get` 與 `svo_service.trigger_extraction`）：

| 測試 | 設定 | 斷言 |
|---|---|---|
| `test_force_rebuild_aborts_before_delete_when_virtual_members_exist` | KG 資料夾放 `_members.json`（含一個 `doc_id`，無對應 `_record.json`）＋一個有 `_record.json` 的實體子資料夾 | `build_graph(driver, kg_id, force_rebuild=True)` 拋 `svc.VirtualMembersNotRebuildableError`；訊息含該 `doc_id`；fake driver **沒有**收到任何 `DETACH DELETE`；`trigger_extraction` **0 次**；實體子資料夾的記錄檔進度**未被重設**（防護須在 `reset_extraction_progress` 之前） |
| `test_force_rebuild_ok_when_manifest_members_have_kg_side_record` | `_members.json` 的成員在 `kg_folder/<doc_id>/` 下有 `_record.json` | 不拋例外；`DETACH DELETE` 被呼叫；對該成員 `trigger_extraction` 被呼叫 |
| `test_non_force_build_with_virtual_members_logs_warning_and_continues` | 同第一個設定，但 `force_rebuild=False` | 不拋例外、不清空；對實體子資料夾的行為與現況相同；`caplog` 有一則 WARNING 含該 `doc_id` |

**自我檢查**：跑 `python -m pytest tests/services/test_knowledge_graph_service.py -q -p no:cacheprovider`，**第一與第三個必須失敗**（第一個因 `VirtualMembersNotRebuildableError` 不存在而 AttributeError／ImportError、第三個因無 warning），第二個應通過（現況行為）。記下失敗訊息摘要。不符預期就停下檢查測試寫法，不要製造假失敗。

### S3　實作（僅限 §2 的檔案）

**(a) `services/knowledge_graph_service.py`**：
1. 在 `ArticleStructureLossError` 之後新增例外類別（逐字）：

```python
class VirtualMembersNotRebuildableError(RuntimeError):
    """`build_graph(force_rebuild=True, doc_ids=None)` 會先清空該 KG 在 Neo4j 的
    全部節點，但 manifest（`_members.json`）內有成員在 KG 資料夾底下沒有
    `_record.json`（虛擬歸屬：文件只存一份於暫存區／中央池），本函式無法重抽
    它們——清空後這些成員的圖譜內容將永久遺失。見報告116 §1／報告117。
    """
```

2. 新增私有函式（放在 `build_graph` 之前，逐字）：

```python
def _unrebuildable_virtual_members(kg_folder: Path) -> list[str]:
    """回傳 manifest 內「KG 資料夾底下沒有 `_record.json`」的成員 doc_id
    （build_graph 無法重抽的虛擬成員）。無 manifest 時回傳空清單。"""
    manifest = classify_service._read_members_manifest(kg_folder)
    missing: list[str] = []
    for entry in manifest.get("assigned_documents", []):
        if not isinstance(entry, dict):
            continue
        doc_id = entry.get("doc_id")
        if doc_id and document_record_service.read_record(kg_folder / doc_id) is None:
            missing.append(str(doc_id))
    return missing
```

   並在檔頭 import 區加入 `import logging`、`from services import classify_service`（併入既有的 `from services import document_record_service, svo_service` 那一行）與 `logger = logging.getLogger(__name__)`（若檔內已有 logger 則沿用）。**先檢查是否造成循環 import**（`python -c "import services.knowledge_graph_service"`）；若失敗，停下回報，不要自行搬動模組。

3. 在 `build_graph()` 內，緊接在現有 `ArticleStructureLossError` 檢查（`if force_rebuild:` 區塊，第 97-109 行）**之後**、`if force_rebuild and doc_ids is None:` 清空**之前**，新增：

```python
    virtual_missing = _unrebuildable_virtual_members(kg_folder)
    if virtual_missing:
        if force_rebuild and doc_ids is None:
            raise VirtualMembersNotRebuildableError(
                f"KG {kg_id} 有 {len(virtual_missing)} 個虛擬歸屬成員在 KG 資料夾底下沒有 "
                f"_record.json（{virtual_missing[:5]}…），force_rebuild 全庫清空後無法重抽，"
                "已中止且未清空任何資料。請先讓 build_graph 支援虛擬成員（見報告116 §5），"
                "或改用 doc_ids 局部重建。"
            )
        logger.warning(
            "[build_graph] KG %s 有 %d 個虛擬歸屬成員不在 build_graph 的處理範圍內：%s",
            kg_id, len(virtual_missing), virtual_missing[:5],
        )
```

4. `build_graph()` docstring「誠實侷限」段落末尾補一段（比照既有 `ArticleStructureLossError` 段落格式）：說明虛擬成員盲點與本防呆；**不要**改動其他既有文字。

**(b) `routers/knowledge_graph.py::build_graph`**：把呼叫包成 try/except，將 `knowledge_graph_service.VirtualMembersNotRebuildableError` 轉為 `HTTPException(status_code=409, detail=str(exc))`；**不要**處理 `ArticleStructureLossError`（維持現況，另案）。

### S4　驗證
1. `python -m pytest tests/services/test_knowledge_graph_service.py -q -p no:cacheprovider` → 全過（含 3 個新測試）。
2. 完整回歸 `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py` → **1183 passed、0 failed**（1180＋3）。既有測試若失敗：**不要修改既有測試**，回報是哪個、為何。
3. 相依快照 `python scripts/analysis/import_graph_snapshot.py . data/analysis/import_graph_20260929_after_guard.json` → `cycles=0`；與 `data/analysis/import_graph_20260929.json` 比對列出差異（預期新增 `services.knowledge_graph_service → services.classify_service`；A8 那次已新增的邊也會出現，需區分）。**該 after 快照檔驗完刪除、不 commit**。

### S5　成果報告
建立 `docs/報告/118_build_graph防護修補結果.md`：修改摘要表、S2 失敗證據、S4 數字、已知限制（明確寫出：本修補只「擋住」，不讓 build_graph 支援虛擬成員；`doc_ids` 局部重建仍會靜默略過虛擬成員；`ArticleStructureLossError` 在 router 仍未映射）。無佔位符。

### S6　提交
只提交 §2 的檔案；commit 訊息 `fix(build_graph): force_rebuild 清空前偵測虛擬成員並中止（報告117）`。**不 push。**

## 2. 允許修改的檔案

| 檔案 | 性質 |
|---|---|
| `services/knowledge_graph_service.py` | 新例外、私有函式、清空前防護、docstring |
| `routers/knowledge_graph.py` | 例外→HTTP 409 |
| `tests/services/test_knowledge_graph_service.py` | **僅末尾新增** 3 個測試 |
| `docs/報告/118_build_graph防護修補結果.md` | 新增 |

## 3. 驗收（Claude Code 審核）

| # | 檢查 |
|---|---|
| A1 | `git diff --stat HEAD~1` 只有 §2 的 4 個檔案；測試檔只有新增行、無刪改 |
| A2 | 防護位置正確：在 `ArticleStructureLossError` 檢查之後、`DETACH DELETE` 與 `reset_extraction_progress` 之前（Claude 逐行看 diff） |
| A3 | 報告118 有第一、三測試修正前失敗的證據 |
| A4 | 完整回歸 1183 passed、0 failed（Claude 獨立重跑） |
| A5 | Claude 以自寫的離線腳本（虛擬 KG＋fake driver）確認 force_rebuild 拋錯且無 DETACH DELETE；實體 KG 行為不變 |
| A6 | 相依快照 cycles=0，差異僅預期新增邊 |

## 4. 禁止事項

- 不得修改既有測試；不得改 `trigger_extraction`、`extraction_worker`、`classify_service`、`task_queue_service`、匯入腳本。
- 不得順手讓 `build_graph()` 支援虛擬成員（那是 M2 的設計工作）。
- 不得順手處理 `ArticleStructureLossError` 的 router 映射或其他風格調整。
- 不啟動 Neo4j／Ollama／server；不 push。

## 5. 未納入本任務（另案，M2 一併設計）

報告116 §5 的其餘方向：讓 `build_graph()`／`rebuild_from_records()`／`_kg_source_charset()` 真正以 manifest resolver 支援虛擬成員、匯入腳本改用明確的 staging／KG output 參數、評測工具 scope resolver。

## 6. 回填區（Codex 填寫）

- commit SHA：
- S1–S6 自我檢查結果：
- 意外狀況：
