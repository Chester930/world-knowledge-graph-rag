# 報告141：M2 P2 第二刀——抽出 `_split_fact_lines`＋`_merge_fact_lines` SDD 任務書（純搬移、行為零變動、不跑 K 臂快照）

> **日期**：2026-09-30
> **執行者**：Codex｜**設計與審核**：Claude Code
> **上位文件**：[報告139](139_M2_P2第一刀_context_fact_lines抽出SDD任務書.md)／[140](140_P2第一刀結果.md)（第一刀，本任務沿用其模式）、[報告138](138_agent_py拆分盤點結果.md)（Q4 補丁點、Q7 候選）
> **成果檔**：`docs/報告/142_P2第二刀結果.md`（Codex 建立）
> **性質**：P2 第二個搬移。使用者已於 2026-09-30 同意「第二刀採 `_split_fact_lines`＋`_merge_fact_lines`」與「快照頻率選 (b)」：**依賴封閉的純函式搬移只做 AST 逐字比對＋差分行為測試，不跑 K 臂快照**（不需要 Neo4j／Ollama，**本任務不得啟動或使用它們**）。單一 commit。

---

## 0. 範圍與依賴（Claude 已讀碼確認）

### 要搬的東西（行號為目前的 `routers/agent.py`）

| # | 名稱 | 行號 | 說明 | 依賴 |
|---|---|---|---|---|
| 1 | `_split_fact_lines` | 690–777（含 docstring 與兩個巢狀函式 `_add_bfs`、`_add_fact`） | 分層、去重、渲染 BFS／Fact 行 | `SVOTriple`（`models.knowledge_graph`，pydantic 純資料模型，只 import `pydantic`／標準庫）、`_strip_type_markers`、`_is_contentful_line`（**第一刀已搬到 `services/context/fact_lines.py`**） |
| 2 | `_merge_fact_lines` | 780–786 | `_split_fact_lines` 的扁平版本 | `_split_fact_lines`、`SVOTriple` |

兩者搬進**既有的** `services/context/fact_lines.py`（與其依賴的 `strip_type_markers`／`is_contentful_line` 同一模組，成為同模組內的直接呼叫）。搬完後這兩個函式與第一刀的三個函式構成**依賴封閉**的一組。

### `agent.py` 內的呼叫端（**保持原樣、不得修改**）
`_split_fact_lines` 被呼叫於 1162、1221、1341 行；`_merge_fact_lines` 被呼叫於 1447 行（皆為 `agent.py` 內的函式，經模組全域名稱查找，重新匯出後仍解析到同一函式物件）。docstring／註解中提到這兩個名稱的地方（583、584、698、781、915、1213、1614 等）**不得修改**。

### 外部使用者（靠重新匯出維持相容，**不得修改**）
`agent._split_fact_lines`：7 個腳本檔（根目錄的 `_run_fact_*` 等）與 `tests/routers/test_agent.py`；`agent._merge_fact_lines`：`tests/routers/test_agent.py` 的 14 個直接測試。**這兩個名稱都不是任何測試的補丁目標**（報告138 Q4：13 個補丁名稱不含它們），所以沒有 re-export 陷阱。

### 新模組的依賴規則放寬（有意的、需同步更新第一刀的測試）
第一刀規定 `fact_lines.py` 只能 import `re` 與 `core`。本次它必須 import `models.knowledge_graph.SVOTriple`（用於型別標註，且 `_split_fact_lines` 內有 `SVOTriple` 的型別使用）。新規則：**只可 import `re`、`core`、`models`**；**仍不得** import `routers`、`services`（其他模組）、`repositories`。同步修改第一刀新增的測試 `tests/services/test_context_fact_lines.py::test_fact_lines_module_has_no_reverse_dependency`：允許集合由 `{"re","core"}` 改為 `{"re","core","models"}`，並**明確斷言不含** `routers`、`services`、`repositories`。（這是本任務唯一被允許修改的既有測試，理由：依賴規則因本刀合理放寬；在報告142 的「測試變更清單」列出。）

### 為什麼安全
兩函式都是**純函式**（無 I/O、不讀寫模組狀態、不呼叫 LLM／DB），函式本體可用 AST 逐字比對機械證明未變；有直接單元測試（`test_split_fact_lines_*`、`test_merge_fact_lines_*`，見 `tests/routers/test_agent.py`），且有差分行為測試補強。

---

## 1. 步驟

### S1　基準
`git status -s` 為空；記錄 HEAD；完整回歸 `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py`（Claude 獨立基準 **1314**；若被既有 UMAP 三測試卡住，用 `--deselect` 排除並註明實際數字，預期 1311）。把**修改前**的 `routers/agent.py` 與 `services/context/fact_lines.py` 存到暫存目錄（`baseline_agent.py`、`baseline_fact_lines.py`，供 S4 比對）。

### S2　先寫新測試（RED）
在既有測試檔 `tests/services/test_context_fact_lines.py` **末尾新增**測試（並依 §0 更新反向依賴測試）：

| 測試 | 內容 |
|---|---|
| `test_split_merge_reexported_as_same_function_objects` | `agent._split_fact_lines is fact_lines.split_fact_lines`；`agent._merge_fact_lines is fact_lines.merge_fact_lines`（`is` 比較） |
| `test_split_fact_lines_cases`（參數化） | 至少涵蓋：BFS 三元組與語意 Fact 各自渲染成 `- …` 行；`(subject, rel_type, object)` 三欄皆非空時預設 **BFS 優先**去重；object 為空時改以**渲染後文字**去重；空 subject 的三元組／Fact 被略過；`prefer_fact_on_collision=True` 時 Fact 優先，但 **`verb` 為空字串的 Fact 讓出碰撞鍵**（報告65 §10 品質守門）；型別標記（`（概念）`、`（PERSON,PERSON）`、裸型別詞）被清除；只有 subject 的殘缺行被 `is_contentful_line` 過濾。**期望值必須先用「修改前的 `agent._split_fact_lines`」實際執行取得再寫死，不得憑推測撰寫。** |
| `test_merge_fact_lines_is_bfs_then_fact_concatenation` | `merge_fact_lines(t, f) == split[0] + split[1]`（對多組輸入，含空輸入、只有 BFS、只有 Fact）；期望值同樣先用修改前實作取得 |
| `test_fact_lines_module_has_no_reverse_dependency`（**更新既有**） | 依 §0：允許 `{"re","core","models"}`，並明確斷言不含 `routers`、`services`、`repositories` |

`SVOTriple` 的建構欄位請參照 `tests/routers/test_agent.py` 既有 `_split_fact_lines`／`_merge_fact_lines` 測試的寫法（第 46–130 行附近），**不要憑印象**；必要欄位以 `models/knowledge_graph.py::SVOTriple` 定義為準。

**自我檢查**：先只改測試檔（尚未搬移），執行 `python -m pytest tests/services/test_context_fact_lines.py -q -p no:cacheprovider`：新增的兩個身分／函式測試因 `fact_lines` 尚無 `split_fact_lines`／`merge_fact_lines` 而**失敗**（AttributeError）；更新後的反向依賴測試此時**應通過**（目前只 import `re`、`core`，符合放寬後的規則）。記下摘要。

### S3　實作搬移
1. 在 `services/context/fact_lines.py` 新增 `from models.knowledge_graph import SVOTriple` 與兩個函式，以**去底線的公開名稱** `split_fact_lines`、`merge_fact_lines` 定義：函式本體、docstring、型別標註**逐字保留**；僅需把內部呼叫改為同模組的公開名稱（`_strip_type_markers`→`strip_type_markers`、`_is_contentful_line`→`is_contentful_line`；`merge_fact_lines` 內的 `_split_fact_lines`→`split_fact_lines`）。兩個巢狀函式 `_add_bfs`、`_add_fact` **名稱與內容不變**。更新模組檔頭 docstring 的依賴說明（僅依賴 `re`、`core`、`models`；不依賴 `routers` 或其他 `services` 模組）。函式放置順序：`strip_type_markers`、`is_contentful_line`、`split_fact_lines`、`merge_fact_lines`、`litm_reorder`（或其他合理順序，但不得改動既有三個函式的內容）。
2. 在 `routers/agent.py`：**刪除** `_split_fact_lines` 與 `_merge_fact_lines` 的原定義（連同它們之間的空行）；把第一刀加入的 import 區塊擴充為：

```python
from services.context.fact_lines import (
    is_contentful_line as _is_contentful_line,
    litm_reorder as _litm_reorder,
    merge_fact_lines as _merge_fact_lines,
    split_fact_lines as _split_fact_lines,
    strip_type_markers as _strip_type_markers,
)
```

同時把該區塊上方註解更新為涵蓋兩刀（例如「P2 第一、二刀（報告139／141）：…」）。`SVOTriple` 在 `agent.py` 仍有大量使用，**其 import 必須保留**。**用 Edit 做精確刪除與新增，不要重寫整個檔案**；除此之外不得改動 `agent.py` 任何其他行。

### S4　機械證據（全部必須通過；任何差異停下回報，不得自行判定無害）
1. **AST 逐字比對**：用暫存腳本，把 S1 存的 `baseline_agent.py` 中的 `_split_fact_lines`、`_merge_fact_lines` 與新 `fact_lines.py` 的 `split_fact_lines`、`merge_fact_lines` 比對（`ast.dump(..., include_attributes=False)`），**比對前把下列名稱正規化**：`_split_fact_lines`↔`split_fact_lines`、`_merge_fact_lines`↔`merge_fact_lines`、`_strip_type_markers`↔`strip_type_markers`、`_is_contentful_line`↔`is_contentful_line`（函式名稱與呼叫名稱）。必須逐字相同（含 docstring、型別標註、預設值、兩個巢狀函式）。**同時確認第一刀的 3 個函式與 3 個常數在新 `fact_lines.py` 中仍與 `baseline_fact_lines.py` 逐字相同（未被意外改動）。** 腳本全文貼進報告142 附錄 A。
2. **`agent.py` 的 diff 形狀**：`git diff` 對 `routers/agent.py` 只能有：(a) 刪除兩個函式定義；(b) import 區塊擴充與其上方註解更新。**不得有任何其他變動。** 貼出 `git diff --stat` 與逐段說明。
3. **差分行為測試（暫存腳本，不進版控）**：從 `baseline_agent.py` 以 `importlib` 載入**修改前**的 `_split_fact_lines`／`_merge_fact_lines`（及其依賴，可 exec 最小片段），與新模組的函式，對**固定亂數種子產生的 ≥1000 組輸入**逐一比對輸出**完全相等**。輸入生成需涵蓋：`triples`（`SVOTriple`，含空 subject、空 object、空 verb、有／無 `natural_text`、含 `（概念）`／`（PERSON,PERSON）`／裸型別詞／`XORGANIZATION` 類邊界字串、相同 `(subject,rel_type,object)` 的重複、相同渲染文字的重複）與 `fact_results`（dict：`subject`、`verb`、`object`、`rel_type`、`fact_text`，含 subject 為空白、verb 為空字串、與 triples 碰撞／不碰撞），並對每組輸入分別以 `prefer_fact_on_collision` 為 `False`／`True` 各跑一次（`_split_fact_lines`），`_merge_fact_lines` 對同組輸入比對。另加 ≥20 組**手寫邊界案例**（空輸入、單筆、全部被過濾等）。比對筆數與結果貼進報告142。腳本全文貼附錄 B。
4. `python -m pytest tests/services/test_context_fact_lines.py tests/routers/test_agent.py -q -p no:cacheprovider` 全過（`tests/routers/test_agent.py` **不得修改**）。
5. 完整回歸：**1314＋新增測試數 passed、0 failed**（新增測試數請在報告142 列明）。
6. **相依快照**：`python scripts/analysis/import_graph_snapshot.py . data/analysis/import_graph_20260930_after_cut2.json`：`cycles=0`。**先以搬移前的乾淨 HEAD 重建基準**（不要用歷史快照），差異預期為：新增邊 `services.context.fact_lines → models.knowledge_graph`；其餘不變（`routers.agent → models.knowledge_graph` 邊仍在，因 `agent.py` 仍使用 `SVOTriple`）。**`services.context.fact_lines` 不得有任何指向 `routers`／`services`（其他）／`repositories` 的邊。** 快照檔驗完刪除、不 commit。
7. **不跑 K 臂快照、不啟動或使用 Neo4j／Ollama**（依使用者決定的頻率 (b)）。報告142 需寫明此點與其理由，並註明「下一個涉及 embedding／Neo4j 的搬移（例如 `_arrange_fact_lines`、`_score_lines_by_embedding`）必須重跑 K 臂快照」。

### S5　成果報告與提交
建立 `docs/報告/142_P2第二刀結果.md`：修改摘要、S2 RED 證據、S4 各項數字（AST 比對結果、差分行為測試筆數與涵蓋情境、`git diff --stat`、新增測試數、相依快照差異）、**測試變更清單**（更新的反向依賴測試與理由）、已知限制（明確寫出：本刀無 K 臂快照，靠 AST 逐字＋差分行為測試＋既有 18 個以上直接單元測試；`_rrf_order` 仍無直接單元測試，另案）。附錄 A＝AST 比對腳本、附錄 B＝差分行為測試腳本。無佔位符。

**單一 commit**：訊息 `refactor(context): 抽出 split/merge_fact_lines 至 services/context/fact_lines.py，agent.py 保留舊名稱重新匯出（報告141 P2第二刀）`。包含：`services/context/fact_lines.py`、`routers/agent.py`、`tests/services/test_context_fact_lines.py`、報告142。**不 push。**

---

## 2. 允許修改／新增的檔案（其餘一律不動）

| 檔案 | 性質 |
|---|---|
| `services/context/fact_lines.py` | 新增兩個函式、`SVOTriple` import、更新檔頭 docstring；**不得改動既有三個函式與三個常數的內容** |
| `routers/agent.py` | 只刪除兩個函式定義＋擴充 import 區塊與其註解 |
| `tests/services/test_context_fact_lines.py` | 末尾新增測試＋更新反向依賴測試（僅該一處既有內容） |
| `docs/報告/142_P2第二刀結果.md` | 新增 |
| 本任務書 §4 回填區 | 只可填寫該區 |

## 3. 驗收（Claude 審核）

| # | 檢查 |
|---|---|
| A1 | diff 只有 §2 的檔案；`routers/agent.py` 的 diff **只有**刪除兩個函式定義與 import 區塊／註解更新（Claude 逐行看）；`tests/routers/test_agent.py` 未被修改 |
| A2 | Claude 用自己的腳本獨立重做 AST 逐字比對：兩個新搬函式，**且**第一刀的 3 個函式＋3 個常數仍逐字未變 |
| A3 | 兩個舊名稱在 `routers.agent` 上仍存在且為同一物件；`fact_lines` 只 import `re`／`core`／`models`（AST 測試＋相依圖） |
| A4 | 新測試期望值「先用修改前實作取得」（報告142 有證據）；S2 有 RED 記錄；反向依賴測試的修改有列於測試變更清單 |
| A5 | Claude 獨立完整回歸 = 1314＋新增測試數 passed、0 failed |
| A6 | 相依快照 cycles=0；新增邊僅 `fact_lines → models.knowledge_graph`（相對乾淨 HEAD 基準） |
| A7 | Claude 用自己的差分腳本（不同亂數種子，≥1000 組）獨立重跑舊實作 vs 新模組比對，必須全數相等 |
| A8 | Claude 三項故意破壞：(a) 把 `split_fact_lines` 的去重鍵 `all(key) and key in seen_keys` 改壞（例如刪掉 `and key in seen_keys` 的判斷）→ 新單元測試與既有 `test_agent.py` 相關測試須失敗；(b) 在 `fact_lines.py` 加 `from services import svo_service` → 反向依賴測試須失敗；(c) 把 `agent.py` 的 `_merge_fact_lines` 重新匯出改為本地包裝函式 → 身分測試須失敗（驗完還原，不 commit） |

## 4. 回填區（Codex 填寫）

- commit SHA：本次唯一提交（最終回報列出）
- 自我檢查結果：S2 RED 為 18 failed／5 passed；S4 AST（第二刀 2 函式＋第一刀 3 函式／3 常數）、固定種子差分、agent.py diff 形狀與相依快照全通過；完整回歸 1332 passed、0 failed。
- 新增測試數：18
- 意外狀況：未啟動或使用 Neo4j／Ollama／server／harness，未跑 K 臂快照（依核定的依賴封閉純函式快照頻率 (b)）；完整回歸未遇 UMAP 阻塞，未使用 `--deselect`。

## 5. 禁止事項

- 不得搬移範圍以外的任何函式（**特別是 `_arrange_fact_lines`、`_score_lines_by_embedding`、`_rrf_order`、`_build_prompt` 本次不動**）；不得修改函式本體／docstring／型別標註；不得重新命名 `agent.py` 內的呼叫或修改其 docstring／註解中的名稱；不得改動任何既有測試（**唯一例外**：§0 指定的反向依賴測試）、`scripts/`、harness。
- `services/context/fact_lines.py` 不得 import `routers`、`services`（其他模組）、`repositories`。
- 不得啟動或使用 Neo4j、Ollama、server、harness；不得跑 K 臂快照。
- 不得 push。
