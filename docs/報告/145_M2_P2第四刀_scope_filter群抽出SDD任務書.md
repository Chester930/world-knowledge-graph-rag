# 報告145：M2 P2 第四刀——抽出 scope／filter 純函式群至 `services/retrieval/scope.py` SDD 任務書（純搬移、行為零變動、不跑 K 臂快照）

> **日期**：2026-09-30
> **執行者**：Codex｜**設計與審核**：Claude Code
> **上位文件**：[報告143](143_M2_P2第三刀_遙測群telemetry抽出SDD任務書.md)／[144](144_P2第三刀結果.md)（第三刀，本任務沿用其模式）、[報告138](138_agent_py拆分盤點結果.md)（Q4、Q7、Q9）
> **成果檔**：`docs/報告/146_P2第四刀結果.md`（Codex 建立）
> **性質**：P2 第四個搬移，**也是最後一批「依賴封閉的純函式」**。使用者已於 2026-09-30 同意「依建議做 A：scope／filter 群搬進新的 `services/retrieval/`」，並維持快照頻率 (b)（純函式搬移不跑 K 臂快照、不需 Neo4j／Ollama；**本任務不得啟動或使用它們**）。單一 commit。

---

## 0. 範圍與依賴（Claude 已讀碼確認）

### 要搬的 7 個函式（行號為目前的 `routers/agent.py`）

| # | 名稱 | 行號 | 說明 | 依賴 |
|---|---|---|---|---|
| 1 | `_relevant_doc_ids_from_facts` | 186–219 | 由語意 Fact 推導 `source_doc_id` 集合 | `UUID` |
| 2 | `_intersect_doc_scopes` | 222–242 | 合併語意範圍與明確範圍 | `UUID` |
| 3 | `_resolve_doc_scope` | 278–303 | 種子優先，再套明確範圍 | `_intersect_doc_scopes` |
| 4 | `_scope_by_source_doc_ids` | 306–324 | 依允許範圍排除篩選的共用邏輯（含歸零守衛） | `UUID` |
| 5 | `_filter_triples_by_source_doc_ids` | 327–335 | 過濾 BFS 三元組 | `SVOTriple`、`_scope_by_source_doc_ids` |
| 6 | `_filter_facts_by_source_doc_ids` | 338–357（含巢狀 `_doc_id`） | 過濾語意 Fact | `UUID`、`_scope_by_source_doc_ids` |
| 7 | `_filter_triples_by_relation_type` | 501–510 | 依 canonical relation type 後篩選 | `SVOTriple` |

全部是純函式：無 I/O、不讀寫模組狀態、不呼叫 LLM／DB；型別依賴僅 `uuid.UUID` 與 `models.knowledge_graph.SVOTriple`。

### **明確不搬（留在 `agent.py`，原樣不動）**
| 名稱 | 原因 |
|---|---|
| `_relevant_doc_ids_from_seeds`（245–275，夾在第 2 與第 3 個函式之間） | **Neo4j async 函式**；且是 `tests/routers/test_agent.py` 中 **17 個補丁的目標**（報告138 Q4） |
| `_find_seed_entities`、`_drop_hub_seeds` | Neo4j／embedding；大量補丁目標 |
| `_expand_facts_by_article`、`_fetch_document_map` | Neo4j／repository |
| **`_DOC_SCOPE_TOP_N_FACTS`（183 行，含其上方 178–182 行註解）** | 模組常數；`tests/core/test_kg_config.py:54` 以 `agent._DOC_SCOPE_TOP_N_FACTS` 作為 `KGConfig().bfs.doc_scope_top_n_facts` 的**預設值錨點**，且 `chat()` 內使用；**必須留在 `agent.py`** |

### `agent.py` 內的呼叫端（**保持原樣、不得修改**）
`chat()`／`_stream` 內對這些函式的呼叫；`_relevant_doc_ids_from_seeds`（留下）的 docstring 中提到本次搬走函式的名稱；各處 docstring／註解中的名稱。重新匯出後仍解析到同一函式物件。

### 外部使用者（靠重新匯出維持相容，**不得修改**）
- `compare_doc_scope_retrieval.py:55`：`from routers.agent import _filter_triples_by_source_doc_ids, _find_seed_entities, _intersect_doc_scopes, _relevant_doc_ids_from_facts`（**直接以名稱 import**，重新匯出必須支援）；
- `scripts/eval/diagnose_retrieval_failures.py:29`：`from routers.agent import _find_seed_entities, _relevant_doc_ids_from_seeds, _resolve_doc_scope`；
- `_trace_aggr16_candidate_path_20260918.py`、`.claude/tmp/rq1_*.py` 等腳本；
- `tests/routers/test_agent.py` 的直接測試：`_intersect_doc_scopes`（5）、`_relevant_doc_ids_from_facts`（5）、`_filter_triples_by_source_doc_ids`（4）、`_filter_facts_by_source_doc_ids`（3）、`_resolve_doc_scope`（5）、`_filter_triples_by_relation_type`（3）。
**這 7 個名稱都不是任何測試的補丁目標**（報告138 Q4 的 13 個補丁名稱不含它們），沒有 re-export 陷阱。

### 新套件與模組
- 新增套件 `services/retrieval/`：`services/retrieval/__init__.py` **只有一行模組 docstring，不做任何 re-export**；新增 `services/retrieval/scope.py`。
- **注意**：`services/retrieval_service.py` 是**既有的獨立模組**，與新套件 `services/retrieval/` 名稱相近但**無關**；**不得修改或搬動 `retrieval_service.py`**，也不得讓新模組 import 它。
- `scope.py` 以**去底線的公開名稱**定義 7 個函式：`relevant_doc_ids_from_facts`、`intersect_doc_scopes`、`resolve_doc_scope`、`scope_by_source_doc_ids`、`filter_triples_by_source_doc_ids`、`filter_facts_by_source_doc_ids`、`filter_triples_by_relation_type`。函式本體、docstring、型別標註、巢狀函式 `_doc_id` **逐字保留**；僅需把內部呼叫改為公開名稱（`_intersect_doc_scopes`→`intersect_doc_scopes`、`_scope_by_source_doc_ids`→`scope_by_source_doc_ids`）。函式順序建議：1、2、3、4、5、6、7（與依賴順序一致）。
- **匯入依賴僅限**：`from uuid import UUID`、`from models.knowledge_graph import SVOTriple`（可另有 `from __future__ import annotations`）。**不得** import `routers`、`repositories`、`core`、`services` 下任何模組（含 `services.context.*`）。檔頭 docstring 說明：本模組是 P2 第四刀自 `routers.agent` 抽出的檢索範圍／過濾純函式群、無 I/O、引用報告145。

### `routers/agent.py` 的修改（最小）
1. **刪除**上表 7 個函式的原定義（連同其間空行）；夾在中間的 `_relevant_doc_ids_from_seeds` 與 `_DOC_SCOPE_TOP_N_FACTS` 及其註解**原樣保留**（刪除後注意保持與相鄰程式碼的空行數量合理，但**不得**改動保留段落的任何文字）。
2. 在前三刀的 import 區塊**之後**新增：

```python
# P2 第四刀（報告145）：檢索範圍／過濾純函式群已抽出至 services/retrieval/scope.py；
# 此處以原私有名稱重新匯出，維持既有引用（含腳本的 from routers.agent import …）與 agent.py 內部呼叫不變。
from services.retrieval.scope import (
    filter_facts_by_source_doc_ids as _filter_facts_by_source_doc_ids,
    filter_triples_by_relation_type as _filter_triples_by_relation_type,
    filter_triples_by_source_doc_ids as _filter_triples_by_source_doc_ids,
    intersect_doc_scopes as _intersect_doc_scopes,
    relevant_doc_ids_from_facts as _relevant_doc_ids_from_facts,
    resolve_doc_scope as _resolve_doc_scope,
    scope_by_source_doc_ids as _scope_by_source_doc_ids,
)
```

3. `UUID`、`SVOTriple` 在 `agent.py` 內仍有大量使用，**兩個 import 必須保留**。除此之外**不得改動 `agent.py` 的任何其他行**。

### 為什麼安全（需以證據證實）
純函式，函式本體 AST 逐字比對；有直接單元測試；差分行為測試補強。**這批函式決定檢索範圍（影響 K 臂 L1）**，因此差分測試除 `==` 外，還必須比對**回傳物件的身分行為**（「原樣回傳」的分支回傳的是同一個輸入物件），見 S4-3。

---

## 1. 步驟

### S1　基準
`git status -s` 為空；記錄 HEAD；完整回歸 `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py`（Claude 獨立基準 **1344**；若被既有 UMAP 三測試卡住，用 `--deselect` 排除並註明實際數字，預期 1341）。把**修改前**的 `routers/agent.py` 存到暫存目錄（`baseline_agent.py`，供 S4 使用）。

### S2　先寫新測試（RED）
新增 `tests/services/test_retrieval_scope.py`（**新增檔案，不改任何既有測試**）：

| 測試 | 內容 |
|---|---|
| `test_scope_names_reexported_as_same_function_objects` | 7 個舊名稱與新函式的 `is` 比較（`agent._resolve_doc_scope is scope.resolve_doc_scope` 等），**另加一個測試斷言 `agent._relevant_doc_ids_from_seeds`、`agent._find_seed_entities`、`agent._DOC_SCOPE_TOP_N_FACTS` 仍在 `agent` 上定義（`agent._DOC_SCOPE_TOP_N_FACTS == 5`）**，證明「明確不搬」的東西沒被誤動 |
| `test_relevant_doc_ids_from_facts_cases` | `source_doc_id` 為 `UUID`／合法字串／非法字串（`ValueError` 被吞掉）／`None`／空字串；`top_n` 為 `None`／0／1／大於長度；空清單；期望值**先用修改前實作取得** |
| `test_intersect_and_resolve_doc_scope_cases` | `intersect_doc_scopes`：明確範圍為 `None`／空／有值；語意範圍為空／有值；交集為空時回傳明確範圍本身；`resolve_doc_scope`：種子非空（語意範圍不參與）／種子為空 fallback 語意／再與明確範圍交集；期望值先用修改前實作取得 |
| `test_scope_by_source_doc_ids_cases` | `allowed` 為空→原樣回傳（**同一物件**）；三值邏輯（`get_doc_id` 回 `None` 的保留）；**歸零守衛**（篩選會把非空清單清成空→原樣回傳）；部分重疊照常篩選；空清單輸入 |
| `test_filter_triples_and_facts_by_source_doc_ids_cases` | `SVOTriple.source_doc_id` 為 `UUID`／`None`；Fact 的 `source_doc_id` 為 `UUID`／字串／非法字串／`None`／缺鍵；巢狀 `_doc_id` 行為；歸零守衛在兩個函式上各驗證一次；期望值先用修改前實作取得 |
| `test_filter_triples_by_relation_type_cases` | `rel_type=None`→原樣回傳（同一物件）；命中／不命中；空清單 |
| `test_scope_module_has_no_reverse_dependency` | 用 `ast` 解析 `services/retrieval/scope.py`：所有 import 的**完整模組名稱**集合必須 ⊆ `{"__future__", "uuid", "models.knowledge_graph"}`；並明確斷言不含 `routers`、`repositories`、`core`，且不含任何 `services.*` |

`SVOTriple` 建構欄位以 `models/knowledge_graph.py::SVOTriple` 與 `tests/routers/test_agent.py` 既有相關測試寫法為準（必要欄位 `subject`、`verb`、`object`，其餘有預設），**不要憑印象**。

**自我檢查**：先只建立測試檔（`services/retrieval/` 尚不存在），執行 `python -m pytest tests/services/test_retrieval_scope.py -q -p no:cacheprovider`：**全部應失敗**（ImportError／ModuleNotFoundError）；「明確不搬」那個測試若寫成只 import `routers.agent`，此時可能通過——這是允許的，但要在報告 RED 摘要中說明。

### S3　實作搬移
依 §0 建立 `services/retrieval/__init__.py`、`services/retrieval/scope.py`，並修改 `routers/agent.py`。**用 Edit 做精確刪除與新增，不要重寫整個檔案。**

### S4　機械證據（全部必須通過；任何差異停下回報，不得自行判定無害）
1. **AST 逐字比對**：暫存腳本比對 S1 存的 `baseline_agent.py` 中 7 個函式與新 `scope.py` 的 7 個函式（`ast.dump(..., include_attributes=False)`），**比對前正規化名稱**（7 個函式名稱與其內部互相呼叫的名稱）。必須逐字相同（含 docstring、型別標註、預設值、巢狀 `_doc_id`）。**同時確認 `services/context/fact_lines.py` 與 `services/context/telemetry.py` 兩個檔案整個模組的 AST 與修改前完全相同（未被意外改動）。** 腳本全文貼進報告146 附錄 A。
2. **`agent.py` 的 diff 形狀**：`git diff` 對 `routers/agent.py` 只能有：(a) 刪除 7 個函式定義；(b) 新增上述 import 區塊。`_relevant_doc_ids_from_seeds`、`_DOC_SCOPE_TOP_N_FACTS` 與其註解、`_find_seed_entities`、`_drop_hub_seeds`、`_expand_facts_by_article`、`_fetch_document_map` 等**原樣不動**。**不得有任何其他變動。** 貼出 `git diff --stat` 與逐段說明。
3. **差分行為測試（暫存腳本，不進版控）**：從 `baseline_agent.py` 以 `importlib`／`exec` 載入**修改前**的 7 個函式（及必要依賴），與新模組函式，對**固定亂數種子產生的 ≥1000 組輸入**比對輸出：`==` 必須相等；**且對「原樣回傳」的分支，比對身分行為**——`(舊輸出 is 舊輸入) == (新輸出 is 新輸入)`（例如 `allowed_doc_ids` 為空時回傳同一個 list 物件）；對會拋例外的輸入，比對例外型別與訊息相同。輸入生成需涵蓋：Fact dict（`source_doc_id` 為 `UUID`／合法字串／非法字串／`None`／空字串／缺鍵）、`SVOTriple`（`source_doc_id` 為 `UUID`／`None`、`rel_type` 多值）、`top_n`（`None`／0／1／5／超長）、`allowed_doc_ids`／`semantic_doc_ids`／`seed_doc_ids`／`explicit_doc_ids`（空集合／單一／多個／有交集／無交集／`None` 與空 list）、空輸入。另加 ≥20 組手寫邊界案例（歸零守衛觸發、部分重疊、三值邏輯全 `None` 等）。比對筆數與結果貼進報告146。腳本全文貼附錄 B。
4. `python -m pytest tests/services/test_retrieval_scope.py tests/routers/test_agent.py tests/core/test_kg_config.py -q -p no:cacheprovider` 全過（`tests/routers/test_agent.py` 與 `tests/core/test_kg_config.py` **不得修改**）。
5. 完整回歸：**1344＋新增測試數 passed、0 failed**（新增測試數請在報告146 列明）。
6. **相依快照**：先以**搬移前的乾淨 HEAD** 重建基準（不要用歷史快照；`git show <HEAD>:` 匯出到暫存目錄再跑），再跑搬移後：`cycles=0`；預期差異恰為：新增模組 `services.retrieval`、`services.retrieval.scope`；新增邊 `routers.agent → services.retrieval.scope`、`services.retrieval.scope → models.knowledge_graph`；其餘不變。**`services.retrieval.scope` 不得有其他出邊。** 快照檔驗完刪除、不 commit。
7. **不跑 K 臂快照、不啟動或使用 Neo4j／Ollama**（頻率 (b)）。報告146 需寫明此點與理由，並註明：「本刀是純函式搬移的最後一批；**下一個涉及 embedding／Neo4j 的搬移必須重跑 K 臂快照**；建議在進入該階段之前先做一次**累計 K 臂快照**，一次驗證第一至第四刀的整體效果」。

### S5　成果報告與提交
建立 `docs/報告/146_P2第四刀結果.md`：修改摘要、S2 RED 證據、S4 各項數字（AST 比對、差分測試筆數與涵蓋情境、`git diff --stat`、新增測試數、相依快照差異）、已知限制（本刀無 K 臂快照；`_relevant_doc_ids_from_seeds`、`_DOC_SCOPE_TOP_N_FACTS` 等留在 `agent.py` 的原因；`_rrf_order` 仍無直接單元測試）。附錄 A＝AST 比對腳本、附錄 B＝差分行為測試腳本。無佔位符。

**單一 commit**：訊息 `refactor(retrieval): 抽出檢索範圍／過濾純函式群至 services/retrieval/scope.py，agent.py 保留舊名稱重新匯出（報告145 P2第四刀）`。包含：`services/retrieval/__init__.py`、`services/retrieval/scope.py`、`routers/agent.py`、`tests/services/test_retrieval_scope.py`、報告146。**不 push。**

---

## 2. 允許修改／新增的檔案（其餘一律不動）

| 檔案 | 性質 |
|---|---|
| `services/retrieval/__init__.py`、`services/retrieval/scope.py` | 新增 |
| `routers/agent.py` | 只刪除 7 個函式定義＋新增一個 import 區塊 |
| `tests/services/test_retrieval_scope.py` | 新增 |
| `docs/報告/146_P2第四刀結果.md` | 新增 |
| 本任務書 §4 回填區 | 只可填寫該區 |

（**不得修改** `services/context/*`、`services/retrieval_service.py`、任何既有測試、`scripts/`、`compare_doc_scope_retrieval.py`。）

## 3. 驗收（Claude 審核）

| # | 檢查 |
|---|---|
| A1 | diff 只有 §2 的檔案；`routers/agent.py` 的 diff **只有**刪除 7 個函式與新增 import 區塊（Claude 逐行看）；`_relevant_doc_ids_from_seeds`、`_DOC_SCOPE_TOP_N_FACTS`（含註解）未動；`test_agent.py`、`test_kg_config.py`、`services/context/*` 未被修改 |
| A2 | Claude 用自己的腳本獨立重做 AST 逐字比對（7 個新搬函式＋`services/context/` 兩檔整個模組未變） |
| A3 | 7 個舊名稱在 `routers.agent` 上仍存在且為同一物件；`scope.py` 只 import 允許的模組（AST 測試＋Claude 相依圖檢查）；`from routers.agent import _intersect_doc_scopes` 等直接 import 形式仍可用（Claude 實測） |
| A4 | 新測試期望值「先用修改前實作取得」（報告146 有證據）；S2 有 RED 記錄 |
| A5 | Claude 獨立完整回歸 = 1344＋新增測試數 passed、0 failed |
| A6 | 相依快照 cycles=0；差異恰為預期的 2 個新模組＋2 條新邊（Claude 自己以搬移前 commit 重建基準核對） |
| A7 | Claude 用**不同亂數種子**自寫差分腳本（≥1000 組，`==`＋身分行為＋例外皆比對）獨立重跑舊實作 vs 新模組，必須全數相等 |
| A8 | Claude 三項故意破壞：(a) 把 `scope_by_source_doc_ids` 的歸零守衛（`if items and not filtered: return items`）拿掉 → 新測試與既有 `test_agent.py` 的歸零守衛測試須失敗；(b) 在 `scope.py` 加 `from services.context.fact_lines import strip_type_markers` → 反向依賴測試須失敗；(c) 把 `agent.py` 的 `_resolve_doc_scope` 重新匯出改為本地包裝函式 → 身分測試須失敗（驗完還原，不 commit） |

## 4. 回填區（Codex 填寫）

- commit SHA：
- 自我檢查結果：
- 新增測試數：
- 意外狀況：

## 5. 禁止事項

- 不得搬移範圍以外的任何函式或常數（**特別是 `_relevant_doc_ids_from_seeds`、`_DOC_SCOPE_TOP_N_FACTS`、`_find_seed_entities`、`_drop_hub_seeds`、`_expand_facts_by_article`、`_fetch_document_map`、`_arrange_fact_lines`、`_score_lines_by_embedding`、`_rrf_order`、`_build_prompt` 本次不動**）；不得修改函式本體／docstring／型別標註；不得重新命名 `agent.py` 內的呼叫或修改其 docstring／註解中的名稱；不得改動任何既有測試、`services/context/*`、`services/retrieval_service.py`、`scripts/`、harness、`compare_doc_scope_retrieval.py`。
- `services/retrieval/scope.py` 只可 import `uuid` 與 `models.knowledge_graph`（及 `__future__`）。
- 不得啟動或使用 Neo4j、Ollama、server、harness；不得跑 K 臂快照。
- 不得 push。
