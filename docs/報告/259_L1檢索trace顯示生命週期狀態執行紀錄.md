# 報告259：L1「檢索 trace 顯示 Fact 生命週期狀態」執行紀錄（Claude 實作對話；待規劃對話獨立驗證）

> **日期**：2026-10-02
> **依據**：[報告258](258_下一階段任務規劃_L1檢索trace顯示生命週期狀態_交Claude實作對話.md) T0–T7。
> **性質**：只讀、只顯示。`TRACE_SEMANTIC_MARKS` 旗標開啟時，trace 中每筆 fact 的 `semantic_marks` 多一個 `lifecycle_state`；`vector_search_facts` 兩處 `RETURN` 多帶該屬性。不寫入、不過濾、不排序、不改 prompt／SSE `sources`／設定。
> **未連 KG#4、未操作 docker、未讀 `.env`；Cypher 僅以假 driver 驗證，真實 Neo4j 行為（含未知屬性鍵通知）待規劃對話驗收。不自稱已驗證。**

## 1. T0 基準

HEAD `d37d47e`（含報告258）；全量 pytest 基準 **1973 passed**；報告編號自 259 起。

## 2. 改動（逐檔）

| 檔案 | 改動 |
| --- | --- |
| `services/semantic_marks.py` | 新增本地常數 `LIFECYCLE_STATES`（六個核心狀態）與純函式 `mark_lifecycle_state(state)`；`MARKS` 內容與順序未動；未匯入 `relation_lifecycle` |
| `services/svo_service.py` | `vector_search_facts` 的 dense 與 hybrid fulltext 兩處 `RETURN` 各在最後（`score` 之後）多一欄 `properties(node)['lifecycle_state'] AS lifecycle_state`；docstring 增一段說明；其餘一律未動 |
| `services/context/telemetry.py` | `include_semantic_marks=True` 時，fact 的 `semantic_marks` 末尾附加 `lifecycle_state`（4 行）；triple 不加 |
| `tests/services/test_trace_lifecycle_state.py`（新增） | 34 個測試（見 §4） |
| `tests/services/test_context_telemetry_semantic_marks.py` | **改動既有測試預期（T4 例外，見 §5）** |

## 3. `RETURN` 選用的語法與理由

選用 `properties(node)['lifecycle_state'] AS lifecycle_state`，不寫 `node.lifecycle_state`。理由：`node.lifecycle_state` 在資料庫完全沒有 `lifecycle_state` 屬性鍵時，Neo4j 會對每次查詢發出 UnknownPropertyKey 通知（報告258 §4-T3 的前提）；`properties(node)` 回傳整個屬性 map，再以鍵取值，缺鍵回傳 `null`，**預期**不觸發該通知（〔推論〕，未實測，由規劃對話對 KG#4 唯讀驗證）。已知取捨：`properties(node)` 會在查詢內物化該節點的完整屬性 map，**含 `fact_embedding` 向量**（1024 維），可能增加每個候選節點的處理成本——規劃對話驗收時請一併比較修改前後查詢耗時；若成本不可接受，需改別的寫法（本任務書指定只在「找不到可行寫法」時停下，故我採建議寫法並如實揭露此疑慮）。

## 4. 測試（新增 34 個，全在 `tests/services/test_trace_lifecycle_state.py`）

- `mark_lifecycle_state`：`None`／空／空白→「尚未處理」；六狀態原樣（含前後空白→回傳去空白後的狀態字串）；`"亂值"`、`123`、`0`、list、`True`→「未知」且不拋例外。
- 漂移測試：`set(LIFECYCLE_STATES) == set(relation_lifecycle.CORE_STATES)`（只在測試檔匯入）；`MARKS` 未變。
- trace：旗標關閉的黃金快照（輸入含／不含／為 `None` 的 `lifecycle_state` 皆與修改前相同輸出，且預設＝顯式 False）；旗標開啟：缺鍵／`None`／六狀態／亂值／數字對應預期、鍵位於最後、其餘鍵值與關閉時相同；triple 無此鍵。
- `vector_search_facts`（假 driver，模擬 `AS lifecycle_state` 投影）：dense 與 hybrid 兩處語句皆含 `properties(node)['lifecycle_state'] AS lifecycle_state` 且不含 `node.lifecycle_state`；回傳每筆含該鍵（缺值＝`None`）、無 `fact_id`；排序與去重結果與「不帶新欄位」時相同。
- 結構守衛：除既有 `disposable_*` 驗證腳本外，全 repo `*.py` 無 `lifecycle_events_json`、無 `SET x.lifecycle_state`；`relation_lifecycle` 不被 `semantic_marks`／`svo_service`／`services/context/*`／`routers/*`／`core/*` 匯入；`DEFAULT_RETRIEVABLE_STATES` 不出現在 `svo_service.py`／`services/retrieval/`／`routers/`。

## 5. 偏離報告258 之處（逐項）

1. **改動既有測試預期（T4 必然結果）**：`test_context_telemetry_semantic_marks.py::test_marks_values_and_edge_cases` 對 fact 的 `semantic_marks` 做完全相等比較，並鎖定鍵順序；T4 規格本身要求多一個鍵，故該測試必然失敗。失敗差異**只有** `lifecycle_state` 一個鍵（非行為改變）。我在 `f0`／`f1` 預期加入 `"lifecycle_state": sm.PENDING`，並把鍵順序清單末尾加上 `"lifecycle_state"`（沿用報告225 加名稱形態鍵時的同一做法）。報告258 §2-2 僅明列 T3 為例外；此處屬 T4，**需規劃對話確認接受**。
2. **結構守衛排除 `disposable_*` 腳本**：報告258 §5-4 要求全 repo 無 `lifecycle_events_json`／`SET x.lifecycle_state`，但既有三支 `scripts/analysis/disposable_{fact_state,write_path,resync_solution_b}_validation.py`（先前報告的臨時容器驗證腳本，不在 production 路徑）本來就含此字串，故守衛以檔名前綴 `disposable_` 排除；其餘檔案皆無。
3. 假 driver 的投影行為：報告258 §5-3 要求「假 driver 回傳不含該鍵的資料時輸出仍有 `lifecycle_state`」。函式本身只透傳記錄，真實 Neo4j 因 `RETURN` 含該欄位而永遠回傳該鍵（缺值＝null），故假 driver 在語句含 `AS lifecycle_state` 時補 `None` 模擬投影；這同時驗證了 `RETURN` 字串確實帶該欄位。
4. `mark_lifecycle_state` 對「前後有空白的合法狀態」回傳去空白後的標準字串（報告258 寫「原樣回傳」；對乾淨輸入兩者相同）。

## 6. 結果

- 全量 pytest：**2007 passed**（基準 1973＋34），0 failed；`check_node_cards.py`：3 張節點卡、0 警告。
- 未連 KG#4／docker／`.env`。

## 7. 限制與待規劃對話驗證

- Cypher 僅假 driver 驗證；`properties(node)['lifecycle_state']` 在 Neo4j 的實際行為（回 null、無 UnknownPropertyKey 通知）與查詢耗時（§3 取捨）**未實測**。
- 本任務不涉 L2（寫入狀態、過濾、排序、BFS 標示、`state_as_of`）。

## 8. 待使用者／規劃對話裁示（只列不代決）

1. 是否接受 §5-1 對既有測試預期的改動；2. 若 §3 的效能疑慮成立，改用何種不觸發通知的寫法。
