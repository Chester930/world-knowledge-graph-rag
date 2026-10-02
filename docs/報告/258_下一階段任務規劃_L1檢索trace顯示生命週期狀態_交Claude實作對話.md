# 報告258：下一階段任務規劃——L1「檢索 trace 顯示 Fact 生命週期狀態」（預設關閉、零行為變更）（交 Claude 實作對話）

> **日期**：2026-10-02
> **性質**：階段任務規劃。分工：**規劃對話決定與獨立驗證、Claude 實作對話執行、規劃對話只記錄**。**本文件只由規劃對話修改（§10 執行紀錄）。**
> **依據**：[報告257](257_關係狀態機落地設計審查_依最新證據更新報告234.md) §5 L1、[報告234](234_關係狀態機落地設計說明_Fact層儲存方案.md) §4 R5；使用者「同意」＝同意做 **L1**，並採納報告257 §8 對 D1／D5／D6 的建議（D3 待使用者提供資料口徑、D4 排在 L2 之後，**本任務都不涉及**）。
> **基準**：HEAD ≥ `bb28027`；全量 pytest **1973 passed**。
> **本任務的性質**：**只讀、只顯示**。在既有 `TRACE_SEMANTIC_MARKS` 旗標下，讓 `include_retrieval_trace` 的 trace 為每筆 **Fact** 多顯示一個 `lifecycle_state` 標示（目前所有 Fact 都沒有這個屬性，故顯示「尚未處理」）。**不寫入任何屬性、不依狀態過濾或排序、不改 prompt、不改 API 回傳（SSE `sources`）。**

---

## 1. 背景（〔事實〕，規劃對話已讀碼；請自行重新核對）

- `services/context/telemetry.py:46–156` 的 `build_retrieval_trace(..., include_semantic_marks=False, ...)`：旗標為 True 時每筆 fact／triple 多一個 `semantic_marks` 鍵；False 時輸出與新增前完全相同。fact 的標示在 `:126–130` 以 `_marks(...)` 組成。伺服器旗標＝`settings.trace_semantic_marks`（`core/config.py:81`，預設 False），由 `routers/agent.py:1444` 經 `services/context/trace_marks.py::semantic_marks_trace_kwargs` 傳入。
- `services/semantic_marks.py`（純運算、無 I/O）已有標示常數：`PENDING = "尚未處理"`、`UNKNOWN = "未知"`、`INDETERMINATE = "無法由現有資料判定"` 等（`:21–26`）。
- `vector_search_facts`（`services/svo_service.py:1457–1580`）有**兩處** Cypher `RETURN`（dense：`:1534–1538`；hybrid fulltext：`:1559–1563`），目前都沒有回傳 `lifecycle_state`。
- `serialize_sources`（`telemetry.py:207–218`）對 fact **只挑固定欄位**，所以在 fact 結果 dict 多一個鍵**不會改變 SSE `sources` 內容**。
- `services/relation_lifecycle.py` 是已驗證的純運算原型，**零接線**；`CORE_STATES`（六個狀態字串）在 `:23–29`。**本任務不得讓它被任何 production 模組匯入。**
- KG#4 目前**沒有任何 Fact 帶 `lifecycle_state`**，因此顯示值一律是「尚未處理」。

## 2. 任務限制（實作對話必讀）

1. **不得連 KG#4（17990）、不得操作 docker、不得讀 `.env`**（你的使用者硬規則）。Cypher 以**假 driver** 測試；**真實 Neo4j 上的行為（含 Neo4j 對「不存在的屬性鍵」可能發出的 `UnknownPropertyKey` 通知）由規劃對話在驗收時以唯讀方式驗證**——你不需要也不應該自己驗。
2. **不得修改既有測試的預期**（若既有測試因新增鍵而失敗，表示你的實作改變了既有輸出，應改實作而非改測試；唯一例外見 §4-T3，需在報告列出）。
3. **不得新增設定項**（沿用 `TRACE_SEMANTIC_MARKS`）、不得新增寫入 `lifecycle_state`／`lifecycle_events_json` 的任何程式、不得讓檢索依狀態過濾或排序、不得匯入 `services.relation_lifecycle`（見 §4-T2 的漂移測試例外）。

## 3. 任務總覽

| 步驟 | 內容 |
| --- | --- |
| **T0** | 前置：`git pull`、基準 pytest（應 1973 passed）、`ls docs/報告`（確認自 259 起）、讀 §1 所列位置與其既有測試 |
| **T1** | `services/semantic_marks.py`：新增 `mark_lifecycle_state`（§4-T1） |
| **T2** | 漂移測試：標示用的狀態字串與 `relation_lifecycle.CORE_STATES` 逐項相同（§4-T2） |
| **T3** | `services/svo_service.py::vector_search_facts`：兩處 `RETURN` 都多帶 `lifecycle_state`（§4-T3） |
| **T4** | `services/context/telemetry.py`：fact 的 `semantic_marks` 多一個 `lifecycle_state` 鍵（§4-T4） |
| **T5** | 結構守衛與零行為變更測試（§5） |
| **T6** | 報告 259＋索引＋`HANDOVER.md` 頂部條目 |
| **T7** | 全量 pytest、`scripts/analysis/check_node_cards.py`、commit＋push，並以 SendMessage 回報規劃對話 |

## 4. 規格

### T1　`mark_lifecycle_state(state: object) -> str`（純函式）

- `None`、空字串或只有空白 → `PENDING`（「尚未處理」）；
- 字串且（去空白後）屬於**六個核心狀態**之一（`"候選"`、`"有效"`、`"已被取代"`、`"已終止"`、`"爭議"`、`"已駁回"`）→ 原樣回傳；
- 其他任何值（非字串、未知字串）→ `UNKNOWN`（「未知」），**不得拋例外**。
- 六個狀態字串在 `semantic_marks.py` 內以**本地常數** `LIFECYCLE_STATES`（tuple）定義，**不得匯入 `relation_lifecycle`**（維持 `semantic_marks` 純運算且 `relation_lifecycle` 零接線）。
- 把 `LIFECYCLE_STATES` 內每個值納入 `MARKS` 之外的獨立常數即可，**不要改動 `MARKS` 既有內容與順序**（既有測試會逐項檢查）。

### T2　漂移測試（只在測試檔內匯入 `relation_lifecycle`）

`tests/services/` 新增測試：`set(LIFECYCLE_STATES) == set(relation_lifecycle.CORE_STATES)`；沿用 `tests/services/test_semantic_marks_name_shape.py` 的「逐項比對守住兩處不漂移」寫法。

### T3　`vector_search_facts` 的兩處 `RETURN`

- 兩處（dense、hybrid fulltext）都新增 `lifecycle_state` 欄位，讓回傳 dict 多一個鍵 `lifecycle_state`（Fact 沒有該屬性時值為 `None`）。
- **屬性存取方式請避免對「資料庫裡根本不存在的屬性鍵」產生 Neo4j 通知**：不要寫 `node.lifecycle_state`；改用不觸發此通知的存取（建議 `properties(node)['lifecycle_state']`，其他等價寫法亦可，**請在報告 259 寫明選用的語法與理由**）。規劃對話會在 KG#4 上唯讀驗證通知與結果。
- **其餘一律不變**：欄位順序、`score`、`fact_id`、去重（`_dedupe_facts_by_key`）、範圍過濾、`source_doc_cap` 都不動；dense／hybrid 兩條路徑回傳的**其他鍵與值**與修改前逐位元相同。
- 若既有測試因 dict 多一個鍵而失敗（例如對回傳 dict 做完全相等比較），**先確認是否真的是新鍵造成**；只有這種情況可以改該測試的預期（加入 `lifecycle_state: None`），並在報告 259 列出每一處改動與原因（T3 例外）。

### T4　`build_retrieval_trace`：fact 的 `semantic_marks` 多一個 `lifecycle_state`

- 僅在 `include_semantic_marks=True` 時；`fact_entries[-1]["semantic_marks"]["lifecycle_state"] = mark_lifecycle_state(f.get("lifecycle_state"))`（附加於既有鍵之後）。
- **triple（BFS 邊）不加此鍵**（邊不存狀態；報告234 §6）；`include_semantic_marks=False` 時整個輸出與修改前**逐位元相同**。
- 不改 `serialize_sources`、不改 `routers/agent.py`、不改 `core/config.py`。

## 5. 測試要求（T5）

1. **旗標關閉的黃金測試**：以固定的 fact／triple 輸入呼叫 `build_retrieval_trace(include_semantic_marks=False)`，輸出與修改前快照完全相同（可在 T0 先以現行程式碼產生並寫死於測試）。
2. **旗標開啟**：fact 的 `semantic_marks` 含 `lifecycle_state`——輸入 dict 沒有該鍵／值為 `None` → `"尚未處理"`；值為 `"有效"` 等六個狀態 → 原樣；值為 `"亂值"`、`123` → `"未知"`；既有 `semantic_marks` 的其他鍵與值不變；triple 的 `semantic_marks` **沒有** `lifecycle_state`。
3. **`vector_search_facts`（假 driver）**：兩處 `RETURN` 字串都含 `lifecycle_state`；假 driver 回傳含／不含該鍵兩種資料，函式輸出的每筆 dict 都有 `lifecycle_state` 鍵；排序、去重結果與修改前相同（以既有測試資料對照）。
4. **零行為變更結構守衛**（讀檔／`ast`）：
   - 全 repo `*.py`（排除 `tests/`、`docs/`、`.claude/`、`.git`）中，字串 `lifecycle_events_json` 不得出現；`SET f.lifecycle_state`／`SET node.lifecycle_state` 之類寫入不得出現；
   - `services/relation_lifecycle` 仍**只被**既有的 `law_version_events.py`、`scripts/analysis/*` 與測試匯入（不得被 `services/semantic_marks.py`、`services/context/*`、`services/svo_service.py`、`routers/*`、`core/*` 匯入）；
   - `DEFAULT_RETRIEVABLE_STATES` 不得出現在 `services/svo_service.py`、`services/retrieval/`、`routers/` 內（本任務不做狀態過濾）。
5. 全量 pytest 無回歸（≥ **1973＋新增數** passed、0 failed）；`check_node_cards.py` 不新增警告。

## 6. 驗收（規劃對話自行驗證）

- `git diff --name-only bb28027..HEAD` 只允許：`services/semantic_marks.py`、`services/svo_service.py`（僅兩處 `RETURN`＋docstring）、`services/context/telemetry.py`（僅 §4-T4 的幾行）、新增／微調的測試、報告 259、索引一行、`HANDOVER.md` 頂部條目；其餘 production 檔、`services/relation_lifecycle.py`、既有 `scripts/analysis/*`、規劃文件、論文、題庫、歷史報告原文**零變動**；
- 我讀碼逐行核對 §4 與 §5-4 的守衛；
- **我對 KG#4 唯讀驗證**：①把你選用的 `RETURN` 片段以 `ReadOnlyRunner` 對真實 `vector_search_facts` 等價查詢執行，檢查**回傳筆數與其他欄位與修改前相同、`lifecycle_state` 全為 `None`、Neo4j 回應無 `UnknownPropertyKey` 之類通知**；②用同一組查詢向量比較修改前後 `vector_search_facts` 輸出（排除新鍵後必須逐筆相同）；
- 我另以旗標開／關各跑一次 `build_retrieval_trace` 對真實 trace 樣本，核對關閉時逐位元不變、開啟時只多一個鍵；
- 全量 pytest、節點卡、`.env` 敏感值外洩掃描 0 命中。

## 7. 停止條件（遇到即停止並回報）

1. 需要連 KG#4／docker／讀 `.env`，或需要修改未列於 §6 的 production 檔；
2. 既有測試因新增鍵而失敗，且原因**不是**單純多一個鍵（表示改變了既有行為）；
3. 找不到不觸發 Neo4j 未知屬性通知的存取方式（只能寫 `node.lifecycle_state`）——如實回報並說明，**不要自行決定採用**；
4. 需要讓 `semantic_marks`／`telemetry` 匯入 `relation_lifecycle`。

## 8. 編號、約定、回報

新報告自 **259** 起（先 `ls docs/報告`）。繁體中文；conventional commit（例 `feat(trace): ...`、`test(...)`、`docs(報告259): ...`）；commit 後 push 本分支（不動 master）。**不得自稱已驗證**。完成或遇到停止條件時，**直接 SendMessage 回報規劃對話 `project refactor review sdd`**，格式：`T0–T7｜結論｜commit SHA｜RETURN 選用的語法與理由｜新增測試數與全量 pytest 結果｜改動檔清單（逐檔一行）｜改過的既有測試（無則寫無）｜是否連過 KG#4／docker／.env（應為否）｜偏離報告258之處（無則寫無）`。

## 9. 不在本任務範圍（避免越界）

寫入 `lifecycle_state`、依狀態過濾／排序、BFS 標示、`state_as_of`、條文層版本譜系、試點 KG、任何對 KG#4 的寫入——**皆屬 L2 之後**，需另行同意。

## 10. 執行紀錄（僅規劃對話更新）

⏳ 任務書已寫成，將以 SendMessage 派給實作對話「fact-rag vector search implementation」。KG#4 仍無任何寫入核准。
