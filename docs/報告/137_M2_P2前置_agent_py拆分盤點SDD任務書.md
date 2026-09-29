# 報告137：M2 P2 前置——`routers/agent.py` 拆分盤點 SDD 任務書（只讀盤點、靜態分析）

> **日期**：2026-09-30
> **執行者**：Codex｜**設計與審核**：Claude Code
> **上位文件**：[報告97](97_專案目標與BT_SM工作流設計.md) §6.2 D5、§6.3–§6.5 P2（拆 `agent.py`）、[報告136](136_K臂凍結快照結果.md)（K 臂凍結快照與 P2 驗收判準）、[報告108](108_M2_P0回歸基準結果.md)（相依基準）
> **成果檔**：`docs/報告/138_agent_py拆分盤點結果.md`（Codex 建立）
> **性質**：**只讀盤點**。使用者已於 2026-09-30 同意「先只讀盤點，再由使用者確認第一刀拆哪一塊」。**不得修改任何既有檔案、不得移動或重構任何程式碼**；分析腳本放系統暫存目錄。**不需要也不得啟動 Neo4j／Ollama／server／harness**（本任務純靜態，不跑評測）。

---

## 0. 目的與已知背景

`routers/agent.py`（1,904 行，fan-in 24，fan-out 15）是檢索與生成的核心，也是專案最大的耦合點（報告96 §19 #1）。P2 要在**行為零變動**的前提下把它拆開。動手之前要先回答：**哪些東西能安全地先拆、拆的時候會踩到什麼**。

### Claude 已量測的事實（供定位；Codex 需驗證、不必重做）

| 項目 | 量測結果 |
|---|---|
| 規模 | 1,904 行；37 個頂層定義（36 個私有 `_x`、1 個公開 `chat`） |
| 最大的函式 | `chat`（L1637，268 行）、`_generate_from_context_lines`（L1439，195 行）、`_expand_facts_by_article`（L342，139 行）、`_build_prompt`（L1259，90 行）、`_split_fact_lines`（L727，88 行）、`_build_constrained_prompt`（L1351，79 行）、`_targeted_correction`（L1195，62 行）、`_serialize_sources`（L620，61 行）、`_arrange_fact_lines`（L1015，58 行）、`_build_retrieval_trace`（L561，57 行） |
| 外部引用（粗估，**不完整**） | 至少 28 個檔案引用 `routers.agent`；`scripts/eval/run_rq1_comparison.py:56` 以 `from routers import agent` 後用 `agent._xxx` **屬性方式**取用私有函式（Claude 的簡單搜尋抓不到屬性用法，本任務必須完整盤點）；`services/svo_service.py:2350` 只是 docstring 註解，**不是**真依賴 |
| P2 驗收工具（已就緒） | pytest **1309 passed**（帶 `--ignore=tests/core/test_embedding_migration.py`）＋相依快照 `data/analysis/import_graph_20260929.json`（基準 148 模組，之後多了 `state/`）＋K 臂凍結快照（6 題，L1 檢索軌跡全確定、僅 `17-Q1` 的 L2 不穩定） |

### 最大的技術陷阱（本任務必須用證據回答，不可憑推論）

**re-export 陷阱**：報告97 §6.5 P2 計畫是「舊名稱在 `routers/agent.py` 保留 re-export」。但若測試用 `monkeypatch.setattr(agent, "_foo", fake)` 替換 `routers.agent._foo`，而 `_foo` 被搬走後，原本在 `agent.py` 內呼叫它的函式也一起被搬到別的模組，那麼 patch 只換掉了 `agent` 模組上那個 re-export 的**名稱**，搬走後的呼叫端仍然呼叫**原始實作**——測試會**靜默失去效力**（仍然通過，但已不再測試它以為在測的東西）。這類測試比失敗的測試更危險。

---

## 1. 要回答的問題（每題附 `檔案:行號` 證據）

| # | 問題 |
|---|---|
| Q1 | **函式盤點表**：對 `routers/agent.py` 的**每一個**頂層定義（含 `class`、路由物件 `router`、模組層級常數／全域狀態／快取），列出：起訖行、行數、一句話職責、對應的大節點（依報告97 §6.4：N9 檢索／N10 上下文／N11 生成／N13 遙測／HTTP 路由／其他）、**純度**（純函式無 I/O／使用 Neo4j driver／使用 LLM／embedding provider／讀寫模組全域狀態／其他副作用）、`async` 與否。 |
| Q2 | **檔內呼叫圖**：`agent.py` 內部「誰呼叫誰」的邊（用 `ast` 靜態分析，涵蓋函式內的巢狀函式／閉包）。指出：(a) 葉節點（不呼叫檔內其他函式）；(b) `chat()`／`_generate_from_context_lines()` 直接呼叫哪些；(c) 是否存在檔內循環呼叫；(d) `chat()` 內有沒有巢狀函式（例如 `_stream()`）及其捕獲的外層變數清單（這決定 `chat()` 能否機械地拆）。 |
| Q3 | **外部引用完整清單**：全專案（含 `scripts/`、根目錄 `.py`、`tests/`、`main.py`）對 `routers.agent` 的所有引用，**必須涵蓋四種形式**：`from routers.agent import X`、`from routers import agent` 後的 `agent.X` 屬性存取、`import routers.agent`、以及 `getattr(agent, "...")`／字串形式。列出（引用檔案:行號、被引用的名稱、production／腳本／測試）。**以名稱為單位彙整**：每個被外部使用的 `agent` 名稱有幾個外部使用者、分別是誰。特別標出：production 路徑（`main.py`、`services/`）與 `scripts/eval/run_rq1_comparison.py` 用了哪些私有函式（D5 要解決的耦合）。 |
| Q4 | **測試補丁點盤點（re-export 陷阱）**：`tests/` 內所有對 `routers.agent` 的**替換行為**：`monkeypatch.setattr(agent, "名稱", …)`、`monkeypatch.setattr("routers.agent.名稱", …)`、`unittest.mock.patch("routers.agent.名稱")`、`patch.object(agent, …)`、fixture 中對 `agent` 模組屬性的賦值。逐條列出（測試檔:行號、被替換的名稱、測試名稱）。**再逐條判斷**：若該名稱被搬到別的模組（`agent.py` 只保留 re-export），這條測試會 (a) 仍有效（呼叫端仍在 `agent.py` 內、經模組全域名稱查找）、(b) **靜默失效**（呼叫端隨之搬走）、(c) 直接失敗。標出所有 (b)。 |
| Q5 | **模組層級狀態與匯入副作用**：`agent.py` 的所有模組層級變數、常數、`lru_cache`／快取字典、載入時讀取設定（`settings`／`KGConfig`）、匯入時執行的程式；哪些函式讀寫它們。拆檔時哪些狀態必須「跟著搬」、哪些必須留在原處共享。同時列出 `agent.py` 的所有 import（fan-out 15）及其中是否有匯入時副作用或循環風險。 |
| Q6 | **`chat()` 與 `_generate_from_context_lines()` 的流程地圖**：對這兩個最大的函式，按執行順序切成「步驟」（每步給起訖行、輸入變數、輸出變數、是否 I/O、對應報告97 BT-5 的哪個節點），並標出**步驟之間傳遞的共享狀態**（區域變數、閉包、可變物件）。目的：判斷哪些步驟能被機械地抽成獨立函式而不改變行為。 |
| Q7 | **候選「第一刀」評估**：針對下列候選逐一評估，並補充你發現的其他候選（欄位：純度、行數、外部使用者數、直接單元測試有無、Q4 補丁點涉及數、一旦出錯哪一層快照能偵測 L1／L2／L3／pytest、預估風險 低／中／高與理由）：`_rrf_order`、`_litm_reorder`、`_split_fact_lines`、`_merge_fact_lines`、`_arrange_fact_lines`、`_build_prompt`、`_build_constrained_prompt`、`_serialize_sources`、`_build_retrieval_trace`、`_build_retrieval_telemetry`、`_find_seed_entities`／`_drop_hub_seeds`、`_expand_facts_by_article`、`_split_into_subquestions`。**只列選項與風險，不下最終決定。** |
| Q8 | **既有測試覆蓋盤點**：`tests/` 中哪些檔案測 `agent.py`（列檔名）、哪些私有函式有**直接**單元測試（列測試名稱）、哪些只被 `chat()` 端到端測試間接覆蓋、哪些完全沒有測試。標出「拆分時最缺安全網」的函式。 |
| Q9 | **相依分層草案**：依報告97 §6.3–§6.4 的目標（`services/retrieval/`、`services/context/`、`services/generation/`、`workflows/chat.py`），根據 Q2 的呼叫圖與 Q5 的狀態，提出**無循環**的分層方案（誰可以 import 誰），並指出目前有哪些函式若照 §6.4 的歸屬搬走，會造成新模組之間的循環或反向依賴（例如某個「context」函式呼叫「generation」函式）。**只提案，不實作。** |
| Q10 | **P2 驗收流程可行性**：K 臂快照（報告136）能偵測哪些類型的拆分錯誤、偵測不到哪些（例如：不覆蓋的路徑——種子字面→語意 fallback；`17-Q1` 的 L2 不穩定；只覆蓋 6 題）。列出**快照盲區**，並針對每個候選第一刀說明應搭配哪些額外測試補強。 |

---

## 2. 步驟

### S1　基準與環境
`git status -s` 為空；記錄 HEAD；完整回歸 `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py`（Claude 獨立基準 **1309**；若被既有 UMAP 三測試卡住，用 `--deselect` 排除並註明實際數字，預期 1306）。**本任務不需要 Neo4j／Ollama，不得啟動或使用它們。**

### S2　靜態分析腳本（放系統暫存目錄，不進版控）
用標準庫 `ast` 寫分析腳本，產出 Q1、Q2、Q5、Q6（行範圍）所需的機械資料：
- 每個頂層定義的起訖行、行數、是否 async、docstring 首行；
- 檔內呼叫圖（含巢狀函式與閉包捕獲的自由變數）；
- 每個函式讀取／寫入的模組層級名稱（`global` 或直接引用）；
- 每個函式引用的外部模組名稱（來自 import）。
腳本全文貼進報告138 附錄 A。

### S3　全專案引用掃描（Q3、Q4）
用 `git grep` 與 `ast` 雙重確認（`git grep` 找字串，`ast` 找屬性存取與 `patch` 呼叫的字串參數），涵蓋 §Q3 的四種形式與 §Q4 的所有補丁形式。**兩種方法的結果需互相比對**，不一致處說明原因。掃描腳本貼進附錄 B。

### S4　閱讀與判斷（Q1、Q4 判斷、Q6、Q7、Q8、Q9、Q10）
對 `chat()`、`_generate_from_context_lines()` 與每個 Q7 候選**實際閱讀原始碼**（不要只靠 AST 統計），並閱讀 Q4 列出的每個補丁點所在測試，才能判斷 (a)／(b)／(c)。

### S5　成果報告
建立 `docs/報告/138_agent_py拆分盤點結果.md`，固定結構：

```markdown
# 報告138：agent.py 拆分盤點結果
> 日期 ｜ 基準 commit ｜ 執行者：Codex（依報告137）

## 1. 總結
（五行內：規模與結構、外部耦合、最大風險（含 re-export 陷阱的實際影響面）、建議的第一刀候選與理由（可提傾向，需列反對理由））
## 2. Q1 函式盤點表
## 3. Q2 檔內呼叫圖
## 4. Q3 外部引用完整清單
## 5. Q4 測試補丁點與 re-export 陷阱判斷
## 6. Q5 模組層級狀態與匯入
## 7. Q6 chat／_generate_from_context_lines 流程地圖
## 8. Q7 候選第一刀評估
## 9. Q8 既有測試覆蓋
## 10. Q9 相依分層草案
## 11. Q10 驗收流程可行性與快照盲區
## 12. 需要使用者／Claude 決定的事項
## 附錄 A：靜態分析腳本
## 附錄 B：引用掃描腳本
```

**自我檢查**：函式盤點表恰涵蓋 37 個頂層定義（或說明與 Claude 量測不同的原因）；每個結論有 `檔案:行號`；Q3 涵蓋四種引用形式並有 `git grep` 與 `ast` 兩種方法的比對；Q4 的每一條都有 (a)／(b)／(c) 判斷；無 `{`／`}` 佔位符。

### S6　提交
只提交報告138；訊息 `docs(報告138): agent.py 拆分盤點`；**不 push**；任務書 §3 回填區可直接填寫。

---

## 2. 禁止事項

- 不得修改任何既有檔案（含測試、`routers/agent.py`、`scripts/`）、不得移動或重構程式碼、不得新增 `__init__.py` 或目錄。
- 不得啟動或使用 Neo4j、Ollama、server、harness、任何評測；不得執行匯入或重抽腳本。
- **不下最終決定**：第一刀選哪一塊、如何分層，只列選項與風險，由使用者決定。
- 不得 push。

## 3. 回填區（Codex 填寫）

- commit SHA：
- 自我檢查結果：
- 意外狀況：

## 4. 驗收（Claude 審核）

| # | 檢查 |
|---|---|
| A1 | diff 只有報告138（＋回填區）；工作區乾淨 |
| A2 | Q1 涵蓋 37 個頂層定義與所有模組層級狀態；行號與現況相符（Claude 抽查 5 處） |
| A3 | Q3 外部引用完整：Claude 用自己的方法（`ast` 屬性存取掃描）獨立重掃，結果必須與報告一致，特別是 harness 的屬性形式引用 |
| A4 | Q4 補丁點完整：Claude 獨立掃描 `tests/` 的 `monkeypatch`／`patch` 目標，逐一核對；(a)／(b)／(c) 判斷有讀碼依據，(b) 類（靜默失效）抽查 2 條並實際閱讀測試確認 |
| A5 | Q6 流程地圖與 Q7 候選評估可作為下一份「第一刀」任務書的直接依據；Q10 明確列出快照盲區 |
| A6 | 附錄兩份腳本可重跑；無佔位符；報告內沒有替使用者做最終決定 |
