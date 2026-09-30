# 報告143：M2 P2 第三刀——抽出遙測群 `services/context/telemetry.py` SDD 任務書（純搬移、行為零變動、不跑 K 臂快照）

> **日期**：2026-09-30
> **執行者**：Codex｜**設計與審核**：Claude Code
> **上位文件**：[報告141](141_M2_P2第二刀_split_merge_fact_lines抽出SDD任務書.md)／[142](142_P2第二刀結果.md)（第二刀，本任務沿用其模式）、[報告138](138_agent_py拆分盤點結果.md)（Q4、Q7、Q9）
> **成果檔**：`docs/報告/144_P2第三刀結果.md`（Codex 建立）
> **性質**：P2 第三個搬移。使用者已於 2026-09-30 同意「第三刀採遙測群、放 `services/context/telemetry.py`（方案 (a)）」，並維持快照頻率 (b)（依賴封閉的純函式搬移不跑 K 臂快照、不需 Neo4j／Ollama；**本任務不得啟動或使用它們**）。單一 commit。

---

## 0. 範圍與依賴（Claude 已讀碼確認）

### 要搬的四個函式（行號為目前的 `routers/agent.py`）

| # | 名稱 | 行號 | 說明 | 依賴 |
|---|---|---|---|---|
| 1 | `_serialize_document` | 537–545 | 把 `LawDocument` 轉 dict（`None` 回 `None`） | `LawDocument`（`models.law_document`，pydantic 純資料模型） |
| 2 | `_build_retrieval_telemetry` | 548–567 | 檢索量體遙測（字元數、筆數、耗時） | `SVOTriple` |
| 3 | `_build_retrieval_trace` | 570–626（含巢狀 `_in_prompt`） | 報告62 T0：檢索軌跡（rank、`in_prompt`）——**這正是 K 臂快照 L1 的資料來源** | `SVOTriple`、`_strip_type_markers`（第一刀已搬到 `services/context/fact_lines.py`） |
| 4 | `_serialize_sources` | 629–689 | 把來源整理成 SSE `sources` 事件結構 | `SVOTriple`、`LawDocument`、`_serialize_document` |

### **明確不搬**
`_fetch_document_map`（504–534 行）：它呼叫資料庫（`LawDocumentRepository`）、是 `tests/routers/test_agent.py` 中 **8 個補丁的目標**（報告138 Q4：`_fetch_document_map` 被替換 8 次，`LawDocumentRepository` 被替換 2 次）。**本次絕對不動**，留在 `agent.py`。

### `agent.py` 內的呼叫端（**保持原樣、不得修改**）
`chat()` 內：`_build_retrieval_telemetry`（1684 行）、`_serialize_sources`（1724 行）、`_build_retrieval_trace`（1728 行）。重新匯出後仍解析到同一函式物件。docstring／註解中提到這些名稱的地方（508、557、648、652 等）**不得修改**。

### 外部使用者（靠重新匯出維持相容，**不得修改**）
`tests/routers/test_agent.py` 的直接測試：`_serialize_sources`（6 個）、`_build_retrieval_trace`（5 個）、`_build_retrieval_telemetry`（2 個）。**這四個名稱都不是任何測試的補丁目標**（報告138 Q4 的 13 個補丁名稱不含它們），所以沒有 re-export 陷阱。

### 新模組
- 新增 `services/context/telemetry.py`，以**去底線的公開名稱**定義四個函式：`serialize_document`、`build_retrieval_telemetry`、`build_retrieval_trace`、`serialize_sources`。函式本體、docstring、型別標註、巢狀函式 `_in_prompt` **逐字保留**；僅需把內部呼叫改為公開名稱（`_strip_type_markers`→`strip_type_markers`，從 `services.context.fact_lines` import；`_serialize_document`→`serialize_document`）。
- **匯入依賴僅限**：`from models.knowledge_graph import SVOTriple`、`from models.law_document import LawDocument`、`from services.context.fact_lines import strip_type_markers`（**同套件的兄弟模組，唯一允許的 `services` 依賴**）。**不得** import `routers`、`repositories`、`services` 下其他模組、`core` 以外的其他東西。檔頭 docstring 說明：本模組是 P2 第三刀自 `routers.agent` 抽出的檢索遙測／來源序列化純函式群、無 I/O、引用報告143。
- `services/context/__init__.py` **不改**（維持只有一行 docstring、不做 re-export）。

### `routers/agent.py` 的修改（最小）
1. **刪除**上表四個函式的原定義（連同它們之間的空行）；`_fetch_document_map` 原樣保留。
2. 在第一、二刀的 import 區塊**之後**新增一個 import 區塊（保留舊名稱重新匯出，同一函式物件）：

```python
# P2 第三刀（報告143）：檢索遙測／來源序列化純函式群已抽出至 services/context/telemetry.py；
# 此處以原私有名稱重新匯出，維持既有引用與 agent.py 內部呼叫不變。
from services.context.telemetry import (
    build_retrieval_telemetry as _build_retrieval_telemetry,
    build_retrieval_trace as _build_retrieval_trace,
    serialize_document as _serialize_document,
    serialize_sources as _serialize_sources,
)
```

3. `SVOTriple`、`LawDocument` 在 `agent.py` 內仍有使用（`_fetch_document_map` 簽章等），**兩個 import 都必須保留**。除此之外**不得改動 `agent.py` 的任何其他行**。

### 為什麼安全（需以證據證實）
純函式、無 I/O、不讀寫模組狀態；函式本體 AST 逐字比對；有直接單元測試；且**回傳的是 dict／list 結構（SSE payload），鍵順序與 JSON 序列化結果也必須逐字相同**（見 S4-3）。**注意：`build_retrieval_trace` 的輸出就是 K 臂快照 L1 比對的內容**，因此本刀雖不跑快照，差分測試必須額外驗證輸出的 JSON 字串（含鍵順序）逐字相同。

---

## 1. 步驟

### S1　基準
`git status -s` 為空；記錄 HEAD；完整回歸 `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py`（Claude 獨立基準 **1332**；若被既有 UMAP 三測試卡住，用 `--deselect` 排除並註明實際數字，預期 1329）。把**修改前**的 `routers/agent.py` 存到暫存目錄（`baseline_agent.py`，供 S4 使用）。

### S2　先寫新測試（RED）
新增 `tests/services/test_context_telemetry.py`（**新增檔案，不改任何既有測試**）：

| 測試 | 內容 |
|---|---|
| `test_telemetry_names_reexported_as_same_function_objects` | 四個舊名稱與新函式的 `is` 比較：`agent._serialize_document is telemetry.serialize_document` 等 |
| `test_serialize_document_cases` | `None`→`None`；有值時四個鍵 `title`／`update_date`／`effective_date`／`effective_note` 與**鍵順序** |
| `test_build_retrieval_telemetry_cases` | 空輸入；`natural_text` 為 `None`／空字串；`fact_text` 缺失／`None`；含空格與換行的文字（被移除後計字元數）；`latency_s` 四捨五入到 0.1 ms（`round(latency_s*1000, 1)`）；期望值**先用修改前實作取得** |
| `test_build_retrieval_trace_cases` | `prompt_lines=None` 時 `in_prompt` 全為 `None`（未量測）；有 `prompt_lines` 時 `in_prompt` 為 True／False；Fact 與 triple 的 `rank` 各自從 0 起算；`source_doc_id` 為字串／UUID／`None`；`source_svo_chunk_index` 為 int／字串數字／`None`；含型別標記的文字經 `strip_type_markers` 後比對；`text` 為空字串；期望值**先用修改前實作取得** |
| `test_serialize_sources_cases` | `document_map` 為 `None`／空／含 `LawDocument`；triple 的 `source_doc_id` 為 `None`（`document` 為 `None`）與有值；`retrieval_telemetry`、`retrieval_trace` 為 `None` 與有值；Fact 以 `f.get("source_doc_id")` 取 map；輸出頂層鍵順序 `resolved_rel_type`、`retrieval_telemetry`、`retrieval_trace`、`triples`、`facts`；期望值**先用修改前實作取得** |
| `test_telemetry_module_has_no_reverse_dependency` | 用 `ast` 解析 `services/context/telemetry.py`：所有 import 的**完整模組名稱**集合必須 ⊆ `{"models.knowledge_graph", "models.law_document", "services.context.fact_lines"}`；並明確斷言不含 `routers`、`repositories`，且除 `services.context.fact_lines` 外不含任何 `services.*` |

`LawDocument` 的建構欄位請以 `models/law_document.py`（`LawDocumentCreate`／`LawDocument`）與 `tests/routers/test_agent.py` 既有 `_serialize_sources`／`_fetch_document_map` 測試的寫法為準，**不要憑印象**。

**自我檢查**：先只建立測試檔（尚未有 `telemetry.py`），執行 `python -m pytest tests/services/test_context_telemetry.py -q -p no:cacheprovider`：**全部應失敗**（ImportError／ModuleNotFoundError）。記下摘要。

### S3　實作搬移
依 §0 建立 `services/context/telemetry.py` 並修改 `routers/agent.py`。**用 Edit 做精確刪除與新增，不要重寫整個檔案。**

### S4　機械證據（全部必須通過；任何差異停下回報，不得自行判定無害）
1. **AST 逐字比對**：暫存腳本比對 S1 存的 `baseline_agent.py` 中四個函式與新 `telemetry.py` 的四個函式（`ast.dump(..., include_attributes=False)`），**比對前正規化名稱**：`_serialize_document`↔`serialize_document`、`_build_retrieval_telemetry`↔`build_retrieval_telemetry`、`_build_retrieval_trace`↔`build_retrieval_trace`、`_serialize_sources`↔`serialize_sources`、`_strip_type_markers`↔`strip_type_markers`。必須逐字相同（含 docstring、型別標註、預設值、巢狀 `_in_prompt`）。**同時確認 `fact_lines.py` 中前兩刀的 5 個函式與 3 個常數仍與修改前逐字相同（未被意外改動）。** 腳本全文貼進報告144 附錄 A。
2. **`agent.py` 的 diff 形狀**：`git diff` 對 `routers/agent.py` 只能有：(a) 刪除四個函式定義；(b) 新增上述 import 區塊。`_fetch_document_map` 原樣。**不得有任何其他變動。** 貼出 `git diff --stat` 與逐段說明。
3. **差分行為測試（暫存腳本，不進版控）**：從 `baseline_agent.py` 以 `importlib`／`exec` 載入**修改前**的四個函式（及其依賴：`SVOTriple`、`LawDocument`、`strip_type_markers`），與新模組函式，對**固定亂數種子產生的 ≥1000 組輸入**比對輸出，**要求 `==` 相等，且 `json.dumps(輸出, ensure_ascii=False)` 的字串也逐字相等（驗證鍵順序）**。輸入生成需涵蓋：`SVOTriple`（空 subject、空 object、`natural_text` 有／無／空字串、`source_doc_id` 為 UUID／`None`、型別標記與 `XORGANIZATION` 類邊界字串）、`fact_results`（`fact_text` 缺失／空／含型別標記、`source_doc_id` 為字串／UUID／`None`、`source_svo_chunk_index` 為 int／字串／`None`、`score` 為 float／`None`、`article_no`、`fact_id`）、`prompt_lines`（`None`、空清單、多批次多行、含與 triples／facts 渲染文字相符及不相符的行）、`document_map`（`None`／空／含 `LawDocument`，且其鍵與 `source_doc_id` 字串相符及不相符）、`latency_s`（0、小數、大數）。另加 ≥20 組手寫邊界案例（全部為空、單筆、`prompt_lines` 為空清單 vs `None` 等）。比對筆數與結果貼進報告144。腳本全文貼附錄 B。
4. `python -m pytest tests/services/test_context_telemetry.py tests/routers/test_agent.py -q -p no:cacheprovider` 全過（`tests/routers/test_agent.py` **不得修改**）。
5. 完整回歸：**1332＋新增測試數 passed、0 failed**（新增測試數請在報告144 列明）。
6. **相依快照**：先以**搬移前的乾淨 HEAD** 重建基準（不要用歷史快照；可用 `git show <HEAD>:` 匯出到暫存目錄後再跑，或先 stash 前跑一次），再跑搬移後：`cycles=0`；預期差異恰為：新增模組 `services.context.telemetry`；新增邊 `routers.agent → services.context.telemetry`、`services.context.telemetry → models.knowledge_graph`、`services.context.telemetry → models.law_document`、`services.context.telemetry → services.context.fact_lines`；其餘不變（`routers.agent → models.*` 邊仍在，因 `agent.py` 仍使用）。**`services.context.telemetry` 不得有其他出邊（尤其不得指向 `routers`、`repositories`、其他 `services.*`）。** 快照檔驗完刪除、不 commit。
7. **不跑 K 臂快照、不啟動或使用 Neo4j／Ollama**（頻率 (b)）。報告144 需寫明此點與理由，**並明確指出「本刀函式的輸出正是 K 臂 L1 的內容，因此以 JSON 字串逐字相同的差分測試補強」**，及「下一個涉及 embedding／Neo4j 的搬移（`_arrange_fact_lines`、`_score_lines_by_embedding`、`_find_seed_entities` 等）必須重跑 K 臂快照」。

### S5　成果報告與提交
建立 `docs/報告/144_P2第三刀結果.md`：修改摘要、S2 RED 證據、S4 各項數字（AST 比對、差分測試筆數與涵蓋情境、`git diff --stat`、新增測試數、相依快照差異）、已知限制（本刀無 K 臂快照；`_fetch_document_map` 留在 `agent.py`；`_rrf_order` 仍無直接單元測試）。附錄 A＝AST 比對腳本、附錄 B＝差分行為測試腳本。無佔位符。

**單一 commit**：訊息 `refactor(context): 抽出檢索遙測與來源序列化至 services/context/telemetry.py，agent.py 保留舊名稱重新匯出（報告143 P2第三刀）`。包含：`services/context/telemetry.py`、`routers/agent.py`、`tests/services/test_context_telemetry.py`、報告144。**不 push。**

---

## 2. 允許修改／新增的檔案（其餘一律不動）

| 檔案 | 性質 |
|---|---|
| `services/context/telemetry.py` | 新增 |
| `routers/agent.py` | 只刪除四個函式定義＋新增一個 import 區塊 |
| `tests/services/test_context_telemetry.py` | 新增 |
| `docs/報告/144_P2第三刀結果.md` | 新增 |
| 本任務書 §4 回填區 | 只可填寫該區 |

（**不得修改** `services/context/fact_lines.py`、`services/context/__init__.py`、任何既有測試。）

## 3. 驗收（Claude 審核）

| # | 檢查 |
|---|---|
| A1 | diff 只有 §2 的檔案；`routers/agent.py` 的 diff **只有**刪除四個函式與新增 import 區塊（Claude 逐行看）；`_fetch_document_map` 未動；`tests/routers/test_agent.py` 與 `fact_lines.py` 未被修改 |
| A2 | Claude 用自己的腳本獨立重做 AST 逐字比對（四個新搬函式＋前兩刀 5 函式 3 常數未變） |
| A3 | 四個舊名稱在 `routers.agent` 上仍存在且為同一物件；`telemetry.py` 只 import 允許的三個模組（AST 測試＋Claude 相依圖檢查） |
| A4 | 新測試期望值「先用修改前實作取得」（報告144 有證據）；S2 有 RED 記錄 |
| A5 | Claude 獨立完整回歸 = 1332＋新增測試數 passed、0 failed |
| A6 | 相依快照 cycles=0；差異恰為預期的 4 條新增邊＋1 個新模組（Claude 自己以搬移前 commit 重建基準核對） |
| A7 | Claude 用**不同亂數種子**自寫差分腳本（≥1000 組，`==` 與 `json.dumps` 字串皆比對）獨立重跑舊實作 vs 新模組，必須全數相等 |
| A8 | Claude 三項故意破壞：(a) 把 `build_retrieval_trace` 的 `in_prompt` 判斷中的 `strip_type_markers(...)` 拿掉 → 新測試與既有 `test_agent.py` 的 trace 測試須失敗；(b) 在 `telemetry.py` 加 `from repositories.kg_repo import KGRepository` → 反向依賴測試須失敗；(c) 把 `agent.py` 的 `_serialize_sources` 重新匯出改為本地包裝函式 → 身分測試須失敗（驗完還原，不 commit） |

## 4. 回填區（Codex 填寫）

- commit SHA：本次唯一提交（最終回報列出）
- 自我檢查結果：S2 RED 為 12 failed；S4 AST（第三刀 4 函式＋前兩刀 5 函式／3 常數）、固定種子 1000 組＋20 組邊界差分（`==` 與 `json.dumps(ensure_ascii=False)`）、agent.py diff 形狀與相依快照全通過；完整回歸 1344 passed、0 failed。
- 新增測試數：12
- 意外狀況：未啟動或使用 Neo4j／Ollama／server／harness，未跑 K 臂快照（依核定的依賴封閉純函式快照頻率 (b)）；完整回歸未遇 UMAP 阻塞，未使用 `--deselect`。

## 5. 禁止事項

- 不得搬移範圍以外的任何函式（**特別是 `_fetch_document_map`、`_arrange_fact_lines`、`_score_lines_by_embedding`、`_rrf_order`、`_build_prompt`、`_expand_facts_by_article` 本次不動**）；不得修改函式本體／docstring／型別標註；不得重新命名 `agent.py` 內的呼叫或修改其 docstring／註解中的名稱；不得改動任何既有測試、`fact_lines.py`、`scripts/`、harness。
- `services/context/telemetry.py` 只可 import `models.knowledge_graph`、`models.law_document`、`services.context.fact_lines`。
- 不得啟動或使用 Neo4j、Ollama、server、harness；不得跑 K 臂快照。
- 不得 push。
