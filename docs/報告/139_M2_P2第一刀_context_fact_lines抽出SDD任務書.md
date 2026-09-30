# 報告139：M2 P2 第一刀——抽出 `services/context/fact_lines.py` SDD 任務書（純搬移、行為零變動）

> **日期**：2026-09-30
> **執行者**：Codex｜**設計與審核**：Claude Code
> **上位文件**：[報告97](97_專案目標與BT_SM工作流設計.md) §6.3–§6.5、[報告138](138_agent_py拆分盤點結果.md)（盤點）、[報告136](136_K臂凍結快照結果.md)（K 臂快照與 P2 驗收判準）
> **成果檔**：`docs/報告/140_P2第一刀結果.md`（Codex 建立）
> **性質**：**這是 P2 的第一個搬移**，使用者已於 2026-09-30 同意「第一刀採 A、新模組放 `services/context/`」。**純搬移＋保留舊名稱相容**：函式本體與常數**逐字不變**。單一 commit。Neo4j＋Ollama 已由使用者維持開啟（見 §S6 前置檢查，任一不符即停下回報）。

---

## 0. 範圍（Claude 讀碼後的**修訂**：比原先口頭同意的 A 少一個函式）

原本口頭提的 A 有 4 個函式（`_strip_type_markers`、`_is_contentful_line`、`_merge_fact_lines`、`_litm_reorder`）。Claude 讀原始碼後發現 **`_merge_fact_lines`（`routers/agent.py:817-823`）會呼叫 `_split_fact_lines()`（`:822`），而後者不在本次範圍**：若只搬 `_merge_fact_lines`，新模組就必須反過來 import `routers.agent`（service 依賴 router 的反向依賴，違反本次要建立的分層）。所以**第一刀縮為 3 個函式＋其專屬常數**；`_merge_fact_lines` 與 `_split_fact_lines` 兩者一起留到第二刀（屆時它們依賴的 `_strip_type_markers`／`_is_contentful_line` 已搬走，成為依賴封閉的一組）。（報告138 Q7 把 `_merge_fact_lines` 評為「低」漏看了這個依賴，Claude 責任。）

### 要搬的東西（逐項，行號為修改前的 `routers/agent.py`）

| # | 名稱 | 行號 | 說明 | 依賴 |
|---|---|---|---|---|
| 1 | `_CONTROLLED_TYPE_TOKEN_PATTERN`、`_CONTROLLED_TYPE_LIST_PATTERN`、`_TYPE_MARKER_RE`（含上方 683-687、695-698 的註解） | 683-702 | 型別標記正規表示式常數 | `re`、`core.constants.ENTITY_TYPES`；**全 repo 只有 `_strip_type_markers` 用到**（Claude 已 grep 確認，無其他引用，含測試與腳本） |
| 2 | `_strip_type_markers` | 705-706 | 移除型別標記 | #1 |
| 3 | `_is_contentful_line` | 709-724 | 判斷事實行是否有內容 | #2 |
| 4 | `_litm_reorder` | 969-988 | Lost-in-the-Middle 的 zigzag 重排 | 無 |

### 新模組

- 新增套件 `services/context/`（`__init__.py` 只有一行模組 docstring，**不做任何 re-export**）與 `services/context/fact_lines.py`。
- **`services/context/fact_lines.py` 的內容**：檔頭 docstring（說明本模組是 P2 第一刀自 `routers/agent.py` 抽出的「事實行渲染」純函式群、無 I/O、不依賴 `routers`／`services` 其他模組；引用報告139）；上表 #1 的常數（**原註解逐字保留**）；三個函式以**去掉底線的公開名稱**定義：`strip_type_markers`、`is_contentful_line`、`litm_reorder`——函式本體、docstring、型別標註**逐字保留**（僅函式名稱不同；`is_contentful_line` 內對 `_strip_type_markers` 的呼叫改為 `strip_type_markers`）。
- **匯入依賴僅限**：`re`、`from core.constants import ENTITY_TYPES`。**不得** import `routers`、`services` 下其他模組、`models`、`repositories`。

### `routers/agent.py` 的修改（最小）

1. **刪除**上表 #1–#4 的原定義（連同其上方註解）。
2. 在原 import 區加入（**保留舊名稱**，使既有的 `agent._strip_type_markers`、`agent._is_contentful_line`、`agent._litm_reorder` 全部仍可用且**是同一個函式物件**）：

```python
# P2 第一刀（報告139）：事實行渲染純函式群已抽出至 services/context/fact_lines.py；
# 此處以原私有名稱重新匯出，維持既有引用（tests／harness／腳本）與 agent.py 內部呼叫不變。
from services.context.fact_lines import (
    is_contentful_line as _is_contentful_line,
    litm_reorder as _litm_reorder,
    strip_type_markers as _strip_type_markers,
)
```

3. 刪除定義後，`from core.constants import ENTITY_TYPES`（原第 16 行）若在 `agent.py` 內已無其他使用就移除，否則保留（**先用 `ast` 或 `git grep` 確認**；Claude 已確認 `ENTITY_TYPES` 在 `agent.py` 只出現在被搬走的第 689 行，`re` 仍被其他處使用故保留）。除此之外**不得**改動 `agent.py` 的任何其他行。
4. `agent.py` 內所有對這三個名稱的呼叫（例如 `_split_fact_lines` 內的 `_strip_type_markers`／`_is_contentful_line`、`_arrange_fact_lines` 內的 `_litm_reorder`、`_build_retrieval_trace` 內的 `_strip_type_markers`）**保持原樣不改**——它們現在透過 import 進來的同名綁定運作。

### 為什麼安全（Claude 的分析，需以測試／證據證實）
- 三個函式與一組常數**不是任何測試的補丁目標**（報告138 Q4 的 13 個補丁名稱不含它們），且呼叫端仍在 `agent.py`、以模組全域名稱查找，所以**沒有 re-export 陷阱**（該陷阱只在連同 `chat`／`_stream` 一起搬走時才成立）。
- 函式本體逐字不變，可用 AST 比對機械證明。

---

## 1. 步驟

### S1　基準
`git status -s` 為空；記錄 HEAD；完整回歸 `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py`（Claude 獨立基準 **1309**；若被既有 UMAP 三測試卡住，用 `--deselect` 排除並註明實際數字，預期 1306）。同時把**修改前**的 `routers/agent.py` 內容存到暫存目錄（`baseline_agent.py`，供 S4 的 AST 比對）。

### S2　先寫新測試（RED）
新增 `tests/services/test_context_fact_lines.py`（**新增檔案，不改任何既有測試**），內容：

| 測試 | 內容 |
|---|---|
| `test_reexported_names_are_the_same_function_objects` | `import routers.agent as agent` 與 `from services.context import fact_lines`：`agent._strip_type_markers is fact_lines.strip_type_markers`；`agent._is_contentful_line is fact_lines.is_contentful_line`；`agent._litm_reorder is fact_lines.litm_reorder`（三個都是 **`is`** 比較，證明舊名稱是同一個物件、不是複製） |
| `test_strip_type_markers_cases` | 至少涵蓋：`（概念）`、括號內型別清單（例如 `（PERSON,PERSON）`、含逗號空白變體）、裸型別詞（`PERSON`）、**邊界回歸**（報告67 T3 複驗：`XORGANIZATION` 這類合法詞尾端剛好是受控型別詞時**不得**被誤砍成 `X`）、無標記字串原樣回傳、前後空白被 `.strip()`；期望值由 Codex **先用修改前的 `agent._strip_type_markers`（尚未搬移時）實際執行取得**再寫死，不得憑推測撰寫 |
| `test_is_contentful_line_cases` | 空字串→False；只有 `- ` 前綴→False；內容等於 `subject`（含前後空白差異）→False；正常事實行→True；`subject=None` 的行為；含型別標記的行（標記被清除後只剩 subject→False）。期望值同樣先用修改前程式實際取得 |
| `test_litm_reorder_cases` | 空清單→`[]`；單元素；偶數／奇數長度的具體輸出（例如輸入 `[1,2,3,4,5]` 對應的字串清單 → 期望 zigzag 結果，**以修改前實作實際輸出為準**）；不修改輸入清單（回傳新清單、原清單不變） |
| `test_fact_lines_module_has_no_reverse_dependency` | 用 `ast` 解析 `services/context/fact_lines.py`：所有 `import`／`from … import` 的頂層模組名稱集合必須 ⊆ `{"re", "core"}`，且明確斷言**不含** `routers`、`services`（防止日後有人讓此模組反向依賴 router／其他 service） |

**自我檢查**：先只建立測試檔（`services/context/` 尚不存在），執行 `python -m pytest tests/services/test_context_fact_lines.py -q -p no:cacheprovider`：**全部應失敗**（ImportError／ModuleNotFoundError）。記下摘要。

### S3　實作搬移
依 §0 建立 `services/context/__init__.py`、`services/context/fact_lines.py`，並依 §0 修改 `routers/agent.py`。**用 Edit 做精確刪除與新增，不要重寫整個檔案**（避免意外改動其他行）。

### S4　機械證據（全部必須通過；任何差異停下回報，不得自行判定無害）
1. **AST 逐字比對**：用暫存腳本，把 S1 存的 `baseline_agent.py` 與新的 `services/context/fact_lines.py` 比對：
   - 三個函式：以 `ast.dump(node, annotate_fields=True, include_attributes=False)` 比對函式節點，**比對前把函式名稱正規化為相同字串**，並把 `is_contentful_line` 內對 `strip_type_markers` 的呼叫名稱正規化（`_strip_type_markers`↔`strip_type_markers`）。必須逐字相同（含 docstring、型別標註、預設值）。
   - 三個常數的賦值節點：`ast.dump` 逐字相同。
   - 腳本全文貼進報告140 附錄 A。
2. **`agent.py` 的 diff 形狀**：`git diff` 對 `routers/agent.py` 只能有：(a) 刪除上表 #1–#4 的行（含其註解與相鄰多餘空行）；(b) 新增上述 import 區塊；(c)（若適用）刪除 `from core.constants import ENTITY_TYPES`。**不得有任何其他變動**。在報告140 貼出 `git diff --stat` 與逐段說明。
3. **差分行為測試（暫存腳本，不進版控）**：從 `baseline_agent.py` 以 `importlib` 載入**修改前**的三個函式（可只 exec 這三個函式與常數所需的最小片段），與新模組的函式，對下列輸入逐一比對輸出**完全相等**：(a) 報告136 快照 `data/eval/p2_snapshot_20260929/run1/records.json` 與 `run2/records.json` 中所有 `lineage.stage1_retrieval.retrieval_trace` 的行文字與 `lineage.stage2_context.prompt_context_lines` 的所有字串（真實資料）；(b) 額外 500 筆由固定亂數種子產生的合成字串（混合型別標記、全形括號、英文詞邊界）。比對筆數與結果貼進報告140。
4. `python -m pytest tests/services/test_context_fact_lines.py tests/routers/test_agent.py -q -p no:cacheprovider` 全過（既有 `test_agent.py` **不得修改**）。
5. 完整回歸：**1309＋新增測試數 passed、0 failed**（新增測試數請在報告140 列明）。
6. **相依快照**：`python scripts/analysis/import_graph_snapshot.py . data/analysis/import_graph_20260930_after_cut1.json`：`cycles=0`；與當前基準（前次快照為 151 模組／420 邊）比對：預期新增 2 個模組（`services.context`、`services.context.fact_lines`）與邊 `routers.agent → services.context.fact_lines`、`services.context.fact_lines → core.constants`，`routers.agent → core.constants` 邊若因移除 import 而消失需說明；**`services.context.fact_lines` 不得有任何指向 `routers`／`services`（其他）／`models`／`repositories` 的邊**。快照檔驗完刪除、不 commit。

### S5　K 臂快照驗收（真實服務）
#### S5-0　前置檢查（唯讀；任一項不符即停下回報，**不得啟動／重啟／停止任何服務**）
與報告135 S1 相同：`git status` 乾淨（搬移已完成但尚未 commit 的變更除外，請在檢查時說明）；連接埠 `17990`（Neo4j）與 `11434`（Ollama）皆開啟；Ollama `/api/tags` 含 `qwen2.5:7b` 與 `bge-m3` 且 digest 與報告136 §1 相同；沒有其他 harness／worker 在跑；KG#4 的 Fact／Entity／Document／LawArticle 計數與報告136 §1 相同（16826／12296／64／3303）；跑完後再查一次必須相同。**報告中不得出現密碼／金鑰。**

#### S5-1　執行
用報告136 §2 的**逐字相同指令**（僅輸出目錄不同）跑一輪，輸出到**系統暫存目錄**（例如 `…\Temp\report139_after_cut1\run1`，**不進版控**）：

```text
python -m scripts.eval.run_rq1_comparison --questions data/eval/p2_snapshot_questions_20260929.json --doc-ids D0080015_警察人員特別休假辦法,N0030006_勞工請假規則,N0030018_育嬰留職停薪實施辦法,N0050030_災區受災勞工保險與勞工職業災害保險及就業保險被保險人保險費支應及傷病給付辦法,N0060029_高架作業勞工保護措施標準 --arms M4 --runs 1 --query-timeout-s 600 --allow-shared-judge --out <暫存目錄>\run1
```

（若報告136 §2 記載的指令與此有出入，**以報告136 §2 為準**並說明。）跑測中**絕不可中斷**、全程只有一個 harness 行程、Ollama 無回應時等待並記錄，超過 20 分鐘無進展才停下回報。預估 13–18 分鐘。

#### S5-2　比對（依報告136 §6 的驗收判準）
用 `scripts/analysis/compare_p2_snapshots.py` 將新 run 與**基準 run1** 及**基準 run2** 各比對一次（共兩次），輸出存為 `data/eval/p2_after_cut1_20260930/compare_vs_baseline_run1.json` 與 `..._run2.json`（**這兩個小檔進版控**）。**驗收判準（因腳本「只改答案」退出碼仍為 0，必須逐題看表格，不能只看退出碼）**：
- **6 題 L1 全部 ✅**（對基準 run1 與 run2 都是）。
- `26-Q1`、`26-Q5`、`57-DIST1`、`57-COREF1`、`canary-P1` 的 **L2 必須 ✅**（逐字相同）。
- `17-Q1`：L2 允許 ❌（基準內已不穩定），但 **L3 必須 ✅**。
- 所有題 **L3 ✅**；無任何 `error`／逾時。
- 任何違反上述判準：**停下回報**，貼出差異，不得自行判定為雜訊（若 L2 在穩定題上不同，先用 `--runs` 相同的第二輪確認是否為新增的雜訊，並如實回報）。

### S6　成果報告與提交
建立 `docs/報告/140_P2第一刀結果.md`：修改摘要、範圍修訂說明（為何縮成 3 個函式）、S2 RED 證據、S4 各項數字（含 AST 比對結果、差分行為測試筆數、`git diff --stat`、新增測試數、相依快照差異）、S5 環境檢查與逐題三層表格（對 run1 與 run2）、已知限制。附錄 A＝AST 比對腳本、附錄 B＝差分行為測試腳本。無佔位符。

**單一 commit**：訊息 `refactor(context): 抽出事實行渲染純函式群至 services/context/fact_lines.py，agent.py 保留舊名稱重新匯出（報告139 P2第一刀）`。包含：`services/context/__init__.py`、`services/context/fact_lines.py`、`routers/agent.py`、`tests/services/test_context_fact_lines.py`、`data/eval/p2_after_cut1_20260930/compare_vs_baseline_run1.json`、`..._run2.json`、報告140。**不 push。**

---

## 2. 允許修改／新增的檔案（其餘一律不動）

| 檔案 | 性質 |
|---|---|
| `services/context/__init__.py`、`services/context/fact_lines.py` | 新增 |
| `routers/agent.py` | 只刪除搬走的定義＋新增一個 import 區塊（＋必要時刪除未使用的 `ENTITY_TYPES` import） |
| `tests/services/test_context_fact_lines.py` | 新增 |
| `data/eval/p2_after_cut1_20260930/compare_vs_baseline_run1.json`、`…_run2.json` | 新增 |
| `docs/報告/140_P2第一刀結果.md` | 新增 |
| 本任務書 §4 回填區 | 只可填寫該區 |

## 3. 驗收（Claude 審核）

| # | 檢查 |
|---|---|
| A1 | diff 只有 §2 的檔案；`routers/agent.py` 的 diff **只有**刪除搬走的行與新增 import 區塊（Claude 逐行看） |
| A2 | Claude 用自己的腳本獨立重做 AST 逐字比對（三個函式＋三個常數）：必須與報告一致 |
| A3 | 三個舊名稱在 `routers.agent` 上仍存在且為同一物件；`fact_lines` 模組零反向依賴（AST 測試＋Claude 的相依圖檢查） |
| A4 | 新測試的期望值是「先用修改前實作取得」（報告140 有證據）；S2 有 RED 記錄 |
| A5 | 完整回歸 = 1309＋新增測試數 passed、0 failed（Claude 獨立重跑）；既有測試未被修改 |
| A6 | 相依快照 cycles=0，新增邊與預期一致，`services.context.fact_lines` 無多餘出邊 |
| A7 | K 臂快照：Claude 用自己的方式重跑 `compare_p2_snapshots.py`（讀 Codex 回報的暫存目錄）核對兩份比對輸出；驗收判準全部成立；KG#4 計數前後相同；無密碼 |
| A8 | Claude 三項故意破壞：(a) 把 `litm_reorder` 的 `i % 2 == 1` 改成 `== 0` → 新單元測試與既有 `test_litm_reorder_places_most_relevant_at_both_ends` 須失敗；(b) 在 `fact_lines.py` 加一行 `from routers import agent` → 反向依賴測試須失敗；(c) 把 `agent.py` 的 `_strip_type_markers` 重新匯出改成本地另一個複製的函式 → 身分測試（`is`）須失敗（驗完還原，不 commit） |

## 4. 回填區（Codex 填寫）

- commit SHA：本次唯一提交（最終回報列出）
- 自我檢查結果：S2 先 RED（5 failed），S4 AST／差分行為／alias 身分／相依快照全通過；完整回歸 1314 passed、0 failed；K 臂兩次基準比對符合 S5-2，KG#4 前後計數相同。
- 新增測試數：5
- K 臂快照新 run 的暫存目錄路徑與起訖時間：`C:\Users\666\AppData\Local\Temp\report139_after_cut1_20260930_01\run1`；2026-09-30T08:19:30.3708403+08:00 ～ 2026-09-30T08:39:11.9890532+08:00。
- 意外狀況：完整回歸未遇 UMAP 阻塞；Neo4j 跑測期間僅出現既有不存在 relationship type warning，未修改查詢或資料；新 run 對基準 run2 的 17-Q1 L2 差異符合既定基準不穩定例外，其餘驗收均通過。

## 5. 禁止事項

- 不得搬移範圍以外的任何函式（**特別是 `_merge_fact_lines`、`_split_fact_lines` 本次不動**）；不得修改函式本體／常數內容；不得重新命名 `agent.py` 內的呼叫；不得改動任何既有測試、`scripts/`、harness。
- `services/context/fact_lines.py` 不得 import `routers`、`services` 其他模組、`models`、`repositories`。
- 不得啟動／重啟／停止 Neo4j、Ollama、WSL；跑測中不得中斷；Neo4j 只讀；不得寫入 Neo4j。
- 報告與提交檔案不得含密碼、金鑰。
- 不得 push。
