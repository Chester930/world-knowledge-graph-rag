# 64 Codex SDD 任務書：T2 進行期間可並行執行的工作

> **建立日期**：2026-09-21
> **交接對象**：Codex（或其他接續工程師／Agent）
> **專案路徑**：`D:\Users\666\Desktop\world knowledge graph rag`
> **建議基底分支**：`worktree-report-gemini-review`（`2749518`，已含 `master` `b1c620e`＋報告 63／64＋文獻資料夾 37）；若使用者已將它 ff 併入 `master`，改用 `master`。
> **前導文件**：`docs/報告/63_Gemini評測報告查證與改進項評估.md`（本任務書所有工作的依據）、`docs/報告/62_…`（T0–T4，位於 `worktree-sdd-retrieval-comparison` 分支）、`docs/報告/33_設定分層與領域可插拔化設計報告.md`
> **性質**：任務書（SDD），**不是結果**。§8 留給執行者回填。

---

## 0. 定位與使用方式

1. 使用者要在 **T2 Stage A 跑評測期間**（另一個終端機、`sdd-retrieval-comparison` worktree，佔用 Ollama 與 Neo4j）並行推進可做的工作，並交給 Codex。
2. 本文件先做**就緒度判定**（§1）：哪些現在能做、哪些不能、為什麼。再對**可立即派工**的三項各寫一份完整規格（§3–§5）。**不能做的不派工**，只記阻塞條件（§6）。
3. 三個任務**彼此獨立**，可分別派給不同執行者或分批執行；各自有驗收清單與停止條件。
4. **任何任務都不得因為「順手」而擴大範圍。** 範圍外的發現，寫進 §8 回報，不要動手。

## 1. 就緒度矩陣（為什麼是這三項）

判定依據：① 是否需要 Ollama／LLM（T2 佔用中）；② 是否與 T2 使用的 sdd 分支檔案衝突；③ 是否需要使用者先裁示；④ 是否已有前置條件缺口。

sdd 分支相對 `master` 改動的檔案（`git diff --stat master...worktree-sdd-retrieval-comparison`，2026-09-21）含 `routers/agent.py`、`models/eval_schema.py`、`models/document.py`、`services/{atomic_scorer,lineage_tracker,interval_lookup_service}.py`、`scripts/eval/*`、多份 `docs/`；**未動** `services/svo_service.py`、`core/kg_config/`、`services/extraction_worker.py`。

| 項目 | 來源 | 現在可做？ | 阻塞／衝突 | 判定 |
|---|---|---|---|---|
| F 修過時註解 | 報告63 §8.1 | 已完成（`49fdc64`） | — | 略 |
| **TASK-1** 抽取端已宣告門檻接線（零行為變化） | 報告63 §10.2「Gemini 漏列的真實待辦」、報告33 §6「抽取端半」 | **可** | 原阻塞 `Blocker.EXTRACTION_SIDE`（`stages.py:27`「動到抽取碼，drain 期間不宜」）；drain 已完成（`HANDOVER.md` 2026-09-20：KG#4 佇列 3307/3307 `completed`；`frozen_manifest.json` `kg_queue_status`）。與 sdd 分支**無檔案衝突**；測試全離線 | **派工** |
| **TASK-2** 文獻登錄一致性補齊 | 報告63 §8.5 | **可** | 純文件；sdd 分支也動 `docs/論文/*`（RefusalBench 校正）→ **只做加法**，避免衝突 | **派工（低優先）** |
| **TASK-3** 來源歧義盤點（A 案適用範圍） | 報告63 §8.4、§9.6 | Phase 1 **可**；Phase 2 須等 T2 Stage A 完成 | Phase 1 只需 Neo4j 唯讀＋既有檔案，**不需 LLM**；Phase 2 讀 T2 輸出（唯讀） | **派工（分兩階段）** |
| TASK-A A 案：事實行加來源標籤（實作＋評測） | 報告63 §8.4、§10.5 | **不可** | ① 需 T2 完成（Ollama）；② 需使用者裁示（§6）；③ 與 sdd 分支 `routers/agent.py` 衝突（T0 已改 `_build_prompt(trace_sink=)`）；必須從 sdd 最新狀態接續 | 暫不派工 |
| TASK-B few-shot 參數化（報告33「3b」） | 報告63 §10 斷點1 | **不可** | R4 風險（空 few-shot 使 qwen 抽取變差）需 eval；需 Ollama；`KGConfig` 目前全為 scalar，首個 list 欄位須設計為 `tuple`（§6）；需使用者裁示 | 暫不派工 |
| TASK-C 實體型別「概念」成因診斷 | 報告63 §9.4 | **不可** | 需以現行 prompt＋`qwen2.5:7b` 小樣本重抽（不寫入）→ 需 Ollama 空閒 | 待 T2 完成 |
| TASK-D Fact 層級雙時態（RQ5） | 報告63 §9.6 | **不啟動** | 資料先於模型：`Document.effective_date` 僅 15/64 有值（AGGR18 涉及的兩部法皆為 `None`）、`law_histories` 未匯入 | 不派工 |
| TASK-E Worker／`trigger_extraction()` 讀取 per-KG 設定 | 報告63 §10 斷點2 | **不可** | 需 TASK-1 完成；且改變產線讀設定行為，需使用者裁示 | 暫不派工 |
| TASK-F 三份 Gemini 檔案整理入庫／校正版缺口紀錄表 | 報告63 §9.5 | **需使用者決策** | 是否入庫、是否編號 | 待裁示 |

## 2. 全域約束（三個任務都適用）

### 2.1 環境保護（最重要）

T2 Stage A 正在執行（42 題、`top_k=40`、每題 1 次；輸出 `…\.claude\worktrees\sdd-retrieval-comparison\data\eval\candidate_runs\t2_k1_topk40_stage_a\records.json`，逐題寫入，可用 `remaining` 續跑）。因此：

- **禁止**：呼叫任何 LLM／embedding provider（含 Ollama、WSL）；啟動、重啟、停止 Ollama／WSL／`kg2-neo4j` 容器；啟動 `main.py`、extraction worker、drain、`rebuild_from_records`；對 Neo4j **任何寫入**（含建索引、`MERGE`、`SET`）；修改、`git checkout`、`git stash` 或在 `sdd-retrieval-comparison` worktree 內做任何寫入。
- **允許**：離線 `pytest`（使用 fake／mock provider）；Neo4j **唯讀** Cypher（`READ` session、小批量、不回傳 `fact_embedding` 等向量欄位、不並行大量查詢）；讀取 sdd worktree 的輸出檔（**只讀**）；文件編輯。
- 若不確定某動作是否會碰到 Ollama／Neo4j 寫入，**視為禁止並回報**。

### 2.2 Git

- 在**自己的 worktree** 工作：`git worktree add .claude/worktrees/<name> -b codex/<name> <基底分支>`。分支名見各任務。
- **不要** push `master`、不要 force push、不要 merge 進任何共用分支；完成後 commit，並 push 自己的 `codex/*` 分支即可，是否合併由使用者決定。
- **`git add` 只加明確路徑**，不要 `git add -A` / `git add .`（`HANDOVER.md` 第7點：共用目錄的未提交檔案會被夾帶）。主 checkout 的 `docs/報告/` 下目前有**未追蹤**的 Gemini 檔案，**不得**加入任何 commit。
- Commit 訊息用 conventional 前綴（`feat`／`fix`／`refactor`／`test`／`docs`），中文描述。

### 2.3 品質與慣例

- 語言：文件與註解一律繁體中文；程式碼沿用 repo 既有 Python `snake_case`、CommonJS 規則僅適用 `scripts/*.js`（本任務無）。
- 測試：動工前在基底 commit 上**實跑一次** `python -m pytest -q`，記錄通過數作為基準；完成後再跑一次，回報前後數字。**不得修改或刪除既有測試來讓它通過**（TASK-1 只可新增測試）。
- 注釋密度與風格沿用鄰近程式碼（本專案註解偏長、附設計依據與日期，新增註解請對齊）。
- 文件變更後執行 `npx markdownlint-cli <檔>`；本專案沒有 `.markdownlint` 設定，MD013（行長）與 MD060（表格風格）是既有報告共有的噪音，**不要為此改寫既有內容**，只確認沒有新增其他類型錯誤。
- **凍結物件不得修改**：`data/eval/baseline_runs/20260920_frozen/**`、`data/eval/test_cases.json`（題庫雜湊 `404cde9f…`）、`docs/附錄A題庫.json`。
- 誠實原則：查不到／沒驗證的事，就寫「未驗證」，不要推測成事實；引用文獻須即時查證（不憑記憶）；發現與本任務書描述不符的現況，**以現況為準並回報差異**。

### 2.4 停止條件（通用）

遇到下列任一情況，**停止並回報，不要自行決定**：任務書假設的函式／行號／檔案與現況不符到需要重新設計；需要修改既有測試；需要 LLM／Ollama／Neo4j 寫入；發現範圍外的缺陷；不確定是否會影響 T2。

---

## 3. TASK-1：抽取端已宣告門檻接線（零行為變化）

**分支**：`codex/task1-extraction-cfg-wiring`　**預估**：S–M　**優先級**：中（純接線、最低風險）

### 3.1 背景與問題陳述

`core/kg_config/model.py` 的 `KGConfig` 已宣告下列欄位，且 golden test 保證預設值等於 `core/constants.py`／`svo_service.py` 的現行常數，但 **`services/` 內沒有任何一處讀取它們**（查證：搜尋 `cfg.dedup`／`cfg.extraction`／`compare_cosine_threshold` 皆無命中；只有 `reltype.qsim_*` 在查詢端 `svo_service.py:362-365` 被讀取）：

| 欄位（`KGConfig` 內路徑） | 預設值 | 仍被直接讀取的常數 |
|---|---|---|
| `dedup.edit_ratio_threshold` | 0.70 | `ENTITY_DEDUP_EDIT_RATIO_THRESHOLD`（`svo_service.py:1271`） |
| `dedup.cosine_threshold` | 0.88 | `ENTITY_DEDUP_COSINE_THRESHOLD`（`:1292`） |
| `dedup.escalate_low_threshold` | 0.75 | `ENTITY_DEDUP_ESCALATE_LOW_THRESHOLD`（`:1295`） |
| `reltype.compare_cosine_threshold` | 0.75 | `COMPARE_COSINE_THRESHOLD`（`_reconcile_rel_type` `:411`；`backfill_related_to_edges` `:3146`） |
| `extraction.uncovered_sentence_threshold` | 0.6 | `UNCOVERED_SENTENCE_THRESHOLD`（`_find_uncovered_sentences` 預設參數 `:525`） |

這就是報告33 §6「抽取端半 ⏳」，也是 `stages.py` 中被標為 `EXTRACTION_SIDE`／`DRAIN_DONE` 阻塞的階段的前置。**本任務只做「讓這五個欄位可被讀取」，不改變任何預設行為，也不改任何呼叫端讀取來源。**

### 3.2 目標與非目標

**目標**
1. 上表五個門檻，改由 `cfg: KGConfig | None = None` 參數提供；`cfg=None` 時行為與現況**逐位元相同**。
2. 新增測試證明：`cfg` 覆蓋值確實改變決策；`cfg=None` 與 `KGConfig()` 等價。

**非目標（明確不做）**
- **不**讓 `extraction_worker.py`／`trigger_extraction()`／`build_graph()`／任何路由**載入或傳入**真實 `cfg`（那是 TASK-E，需使用者裁示）。呼叫端一律維持不傳 `cfg`。
- **不**動 `_svo_prompt()`／few-shot（TASK-B）。
- **不**刪除或改值 `core/constants.py`／`UNCOVERED_SENTENCE_THRESHOLD`：它們仍是 golden test 的比對來源。
- **不**新增 `KGConfig` 欄位、**不**新增 list 欄位、**不**動 `frozen` 設定。
- **不**修改 `stages.py` 的語意；若發現其中 `blocked_by` 標記因本任務而過時，**只在回報中建議**。

### 3.3 現況（As-Is，行號以 `2749518` 為準，動工時請重新核對）

- 已有先例可照抄：`resolve_query_relation_type()`（`svo_service.py:330-365`）簽章含 `cfg: KGConfig | None = None`，函式內 `_cfg = cfg or KGConfig()`，並以 `_cfg.reltype.qsim_*` 取代常數；報告33 §6 第 4 步查詢端半為 as-built 範例。
- 需接線的函式：
  - `_reconcile_rel_type()`（`:376`，僅有 `embedding_provider`、`llm_provider`、`kg_id`、`calibration_db_path`，**無** `cfg`）
  - `_find_uncovered_sentences()`（`:520`，`threshold: float = UNCOVERED_SENTENCE_THRESHOLD`）
  - `resolve_entity_name()`（`:1190`，無 `cfg`）
  - 以上三個函式名稱在全專案的引用合計（搜尋結果，未逐一分類）：`services/svo_service.py` 15 處、`tests/services/test_svo_service.py` 41 處、`services/expand_worker.py` 1 處、`services/baseline_rag_service.py` 1 處、專案根目錄 `compare_entity_candidate_recall.py` 4 處。**各處實際呼叫哪一個、是否需要改動，請自行逐一確認。**
  - `backfill_related_to_edges()`（`:3098`，把 `COMPARE_COSINE_THRESHOLD` 當關係向量索引查詢的 `score` 門檻）
- 上游呼叫鏈（需貫穿 `cfg`）：`extract_svo_triples()`（`:444`）→ `_reconcile_rel_type()`；`extract_svo_triples_with_completeness_check()`（`:950`）→ `_find_uncovered_sentences()`；`merge_triples_to_graph()`（`:1911`）→ `_upsert…`／`resolve_entity_name()`。**實際呼叫鏈以程式碼為準，請自行追蹤完整。**

### 3.4 設計（To-Be）

- 每個受影響函式新增 keyword-only `cfg: KGConfig | None = None`，函式內 `_cfg = cfg or KGConfig()`，門檻改讀 `_cfg.<section>.<field>`。
- `_find_uncovered_sentences()`：**優先順序＝明確傳入的 `threshold` 引數 > `cfg` > 常數**。因此 `threshold` 預設改為 `None`；`None` 時取 `_cfg.extraction.uncovered_sentence_threshold`。既有以位置或關鍵字傳入 `threshold` 的呼叫與測試必須維持相同結果。
- 貫穿的上游函式一律 `cfg` 選填、預設 `None`、**只是轉傳**，不在內部做任何依 `cfg` 的額外分支。
- `backfill_related_to_edges()`：`threshold=_cfg.reltype.compare_cosine_threshold`。**這是「重用 COMPARE 門檻」的既有設計**（見該函式 docstring），沿用同一來源即可；若你認為兩者語意不同而不該共用，**不要自行拆欄位**，回報即可。
- 注意 import：`svo_service.py` 已 `from core.kg_config import KGConfig`（`resolve_query_relation_type` 在用），不需新增依賴、不會造成循環 import。

### 3.5 測試計畫（只新增，不改既有）

新增檔案 `tests/services/test_svo_service_cfg_wiring.py`（或併入既有檔的新區塊，二選一，說明理由）。全部離線，使用 fake `EmbeddingProvider`／`LLMProvider`。

| 測試 | 斷言 |
|---|---|
| `resolve_entity_name`：cosine 門檻 | 構造 fake embedding 使 mention 與候選 cosine＝0.90（非數量／金額實體）：預設 `cfg` → 回傳既有候選名；`cfg=KGConfig(dedup=DedupConfig(cosine_threshold=0.95, escalate_low_threshold=0.95))` → 回傳原名（不合併） |
| `resolve_entity_name`：edit ratio 門檻 | 「台積電」對「台積電公司」（`core/constants.py:44` 註解 ratio≈0.75）：預設 0.70 → 編輯距離命中；`edit_ratio_threshold=0.90` → 不由編輯距離命中（走後續路徑） |
| `resolve_entity_name`：escalate 灰色地帶 | cosine 落在 `[escalate_low, cosine)`：有 `llm_provider` 時呼叫 LLM 仲裁；調高 `escalate_low_threshold` 使其落到門檻外 → 不呼叫（用 fake 記錄呼叫次數） |
| `_reconcile_rel_type` | embedding 最相似型別＝LLM 型別且分數 0.80：預設 → 直接採信、不呼叫 ESCALATE3；`compare_cosine_threshold=0.90` → 觸發第二次 LLM 仲裁（fake 記錄） |
| `_find_uncovered_sentences` | 優先順序三條：僅傳 `threshold` → 用之；僅傳 `cfg` → 用 `cfg`；兩者皆傳 → `threshold` 勝；皆無 → 0.6 |
| `backfill_related_to_edges` | 用 fake driver 攔截 `execute_query` 的 kwargs，斷言 `threshold` 等於 `cfg.reltype.compare_cosine_threshold`（預設 0.75；覆蓋時等於覆蓋值）。不得連真實 Neo4j |
| 等價性 | 對每個接線函式，`cfg=None` 與 `cfg=KGConfig()` 輸出相同（參數化） |
| 不變式 | `tests/core/test_kg_config.py::test_kgconfig_defaults_match_live_module_constants` 原封不動通過 |

### 3.6 驗收清單

- [ ] 動工前基準與完成後 `python -m pytest -q` 的通過數已回報；**沒有任何既有測試被修改或刪除**（`git diff --stat` 中 `tests/` 只有新增）。
- [ ] 五個門檻在 `svo_service.py` 的函式本體內不再直接引用上表常數（`UNCOVERED_SENTENCE_THRESHOLD` 僅可作為文件／golden 對照存在；請附 `grep` 結果列出殘留引用與理由）。
- [ ] 所有呼叫端（`routers/`、`services/extraction_worker.py`、`services/knowledge_graph_service.py`、`services/expand_worker.py`、`services/baseline_rag_service.py`、`scripts/`）**行為不變**：沒有任何呼叫端新增傳入 `cfg`。
- [ ] 新增測試涵蓋 §3.5 全部列，且各自能因「移除接線」而失敗（請在回報中說明如何確認測試不是恆真，例如暫時還原一行看它失敗）。
- [ ] 報告33 §6「抽取端半」段落更新為 as-built（注明**只讀取、尚未由 Worker 載入**）；`config/README.md` 若列出「哪些鍵已生效」則同步；若沒有則不新增。
- [ ] 沒有任何 LLM／Ollama／Neo4j 呼叫（測試日誌可佐證）。

### 3.7 工作步驟

1. 建 worktree；跑基準 pytest。
2. 追蹤五個門檻的完整呼叫鏈，**先把清單貼進 §8**（每個函式、簽章、呼叫者）。
3. 逐函式接線＋對應測試，**一個函式一個 commit**（便於回退）。
4. 全套測試；grep 殘留；更新報告33。
5. 回報。

### 3.8 風險與回退

- 風險：簽章新增參數時漏傳，造成上游函式仍讀常數（測試以等價性＋覆蓋值雙向抓）。
- 風險：把 `threshold` 預設改 `None` 影響既有呼叫（以「既有測試零修改通過」把關）。
- 回退：每函式獨立 commit，可逐個 `git revert`。
- **停止條件（本任務專屬）**：追蹤呼叫鏈時發現有函式需要**改變行為**才能接線；或 `resolve_entity_name()` 的呼叫者超過預期且分佈在需要改動 Worker 的路徑。

### 3.9 給 Codex 的一句話指令

> 依 `docs/報告/64_Codex_SDD任務書_T2進行期間可並行工作.md` §2、§3 執行 TASK-1：從 `worktree-report-gemini-review` 建 `codex/task1-extraction-cfg-wiring`，只新增 `cfg` 選填參數與測試，不改任何呼叫端與既有測試，不得呼叫 LLM／Ollama／Neo4j，完成後把結果回填 §8。

---

## 4. TASK-2：文獻登錄一致性補齊

**分支**：`codex/task2-reference-registry`　**預估**：S　**優先級**：低

### 4.1 背景

`docs/參考文獻/README.md`「下載原則」要求：每次新增文獻，同步更新 `docs/論文/附錄與參考文獻.md` 的信任分級表，並在該 README 補一列。報告63 §8.5 已發現：資料夾 31 的 Reuter et al. (2025)、Louis et al. (2024) 未出現在 `附錄與參考文獻.md`（該檔對它們的搜尋無命中），屬既有落差；本輪新增的資料夾 `37_生成端來源標註與情境元資料`（ALCE、Feng & Steinhardt、Anthropic Contextual Retrieval、dsRAG、LlamaIndex）也尚未登錄。

### 4.2 目標與非目標

**目標**：對基底分支中 `docs/參考文獻/` 下編號 **26～37** 的每個資料夾，逐條檢查其列出的文獻／專案是否已登錄於兩份索引表，缺者**補列**。索引表以實際檔案為準（先確認是哪些檔案承載「信任分級表」——可能是 `docs/論文/附錄與參考文獻.md`，也可能含 `docs/論文/文獻與專案查核表.md`；**先查清楚再動手，並在回報中寫明判定依據**）。

**非目標**
- **不新增任何文獻、不下載任何 PDF、不上網查證新來源。**
- **不調整任何既有列的信任等級或敘述。**
- **不處理 sdd 分支才有的文獻**（`ru-et-al-2024-ragchecker`、`miller-2024-error-bars-for-evals`、`pipitone-alami-2024-legalbench-rag`，以及資料夾 36）：它們在基底分支不存在，待 sdd 併入後另行處理。
- 不改論文正文（`02_文獻探討.md` 等）。

### 4.3 規則

- 每個新增列的**信任等級、查證層級、限制聲明，逐字沿用該資料夾 README 已寫的內容**（例如資料夾 37 對 ALCE 標「✅ prompt 格式讀官方 repo 一手檔案；🟡 論文僅 abstract 頁查證」）。**README 沒寫明的欄位就寫「README 未載明」，不要推測補上。**
- 列格式**逐欄對齊既有表格**；先讀 5 個既有列再照樣寫。
- 僅新增列；`git diff` 不得出現既有列的刪改。

### 4.4 驗收清單

- [ ] 回報一份對照表：資料夾 26～37 × 每條文獻 × 「已登錄／本次新增／README 無法判定」。
- [ ] `git diff` 只有新增列（可用 `git diff --numstat` 檢查刪除行數為 0）。
- [ ] 每個新增列的等級與 README 一致（抽查全部新增列，不是抽樣）。
- [ ] `npx markdownlint-cli` 對被改檔案，與基底相比**沒有新增的錯誤類型**。
- [ ] 沒有下載檔案、沒有網路查證；沒有觸碰 `docs/參考文獻/*/` 內的 PDF 與 README。

### 4.5 停止條件

發現兩份索引表的**結構本身與 README 規則不符**（例如根本沒有「信任分級表」）、或某資料夾 README 對信任等級互相矛盾 → 停止並回報，由使用者決定。

### 4.6 給 Codex 的一句話指令

> 依 `docs/報告/64_…` §2、§4 執行 TASK-2：只補列、不改既有列、不新增文獻、不上網，信任等級逐字沿用各資料夾 README，完成後回填 §8。

---

## 5. TASK-3：來源歧義盤點（A 案適用範圍）

**分支**：`codex/task3-source-ambiguity-audit`　**預估**：M　**優先級**：中高（決定 A 案的評測題目不再只有 n=1）

### 5.1 背景與問題陳述

報告63 §8–§9 的 A 案（在事實行前加來源標籤）目前只有 `57-AGGR18` 一題（n=1）的觀察：其 4 筆 Fact 文字都不含法規名（`Fact.fact_text` 例如「經公立醫療機構認定身心障礙不堪勝任工作」），但可經 `SUPPORTED_BY→LawArticle→Document` 回溯到正確法規與條號。要判斷 A 案值不值得做、以及**該用哪些題目評測**，需要量化：

1. **KG 全域**：多少事實文字在**不同法規**中出現相同的字面？（同文異源，精確碰撞）
2. **題目層級**：42 題凍結題庫中，哪些題的 gold 事實跨越多部法規、且不同法規的 gold 事實**共用同一句框**（見下方警示）？

> **⚠️ 為什麼不能只看「同文碰撞」**：AGGR18 的舊法／新法 gold 事實**文字並不相同**——一個是「…經公立醫療機構認定身心障礙不堪勝任工作」、一個是「…經中央衛生福利主管機關醫院評鑑合格醫院認定身心障礙不堪勝任工作」。實算（NFKC、去空白與標點後）：**精確同文＝否**；字元 bigram Jaccard 僅 **0.26–0.49**；但**共用句框**（共同前綴長度＋共同後綴長度，占較短句長度的比例）達 **0.63–0.81**（例：舊法§23 對新法§84，前綴 13 字＋後綴 12 字，較短句 31 字→0.806；無關的兩條事實只有 0.07）。也就是歧義的形態是「**同一句框、不同槽位內容、來自不同法規**」，用「同文」或「高 Jaccard」都會漏掉它。因此本任務必須同時報告三種度量，並以「句框重疊」為主要排序依據。
3. **prompt 層級**（T2 完成後）：實際送進 LLM 的事實行中，有多少行與另一部法規的行文字相同？

本任務**只產出量化盤點與候選題清單**，不做任何檢索／生成改動，不評分答對率。

### 5.2 輸入（皆為既有資料，唯讀）

- `data/eval/test_cases.json`：`questions[]`，每題含 `id`、`question`、`scenario_type`、`atomic_gold_facts[]`（每筆含 `exact_span`、`source_law`（如 `N0060041_職業災害勞工保護法`）、`source_article`）、`mechanism_tags`。**共 65 題**。
- `data/eval/baseline_runs/20260920_frozen/frozen_manifest.json`：`eligible_ids`（**42 題**凍結範圍）、`kg_id`（`236903cf-055a-40a8-8923-b9d06601f3b7`）、`kg_fact_total`（16826）、`kg_entity_total`（12290）。**不得修改**。
- Neo4j（唯讀）：`Fact {kg_id}` 屬性有 `fact_text, subject, verb, object, source_doc_id, source_svo_chunk_index, rel_type, confidence`（**沒有 `article_no`**，條號在 `SUPPORTED_BY` 邊到 `LawArticle.article_no`；`Document.title` 為法規名；`Document.effective_date` 僅 15/64 有值，AGGR18 涉及的兩部法為 `None`）；`fact_embedding` 是大向量欄位，**查詢時不得回傳**。
- 連線設定：本 worktree 沒有 `.env`。請從主 checkout 的 `.env` 讀取 `NEO4J_URI`／`NEO4J_USER`／`NEO4J_PASSWORD`（目前 `bolt://localhost:17990`），**不得印出、記錄或 commit 任何憑證**；以環境變數或讀取後只留在記憶體使用。
- Phase 2 輸入：`…\.claude\worktrees\sdd-retrieval-comparison\data\eval\candidate_runs\t2_k1_topk40_stage_*\records.json`（**2026-09-21 更正：T2 Stage A 實際被拆成多個輸出資料夾**——`stage_a`、`stage_a2`、`stage_a3`、`stage_b`、`stage_b2a`…，因中斷續跑與分批而產生；原任務書只寫 `stage_a` 是錯的，例如 `57-AGGR18` 在 `stage_a2`。Phase 2 須**讀取全部 `t2_k1_topk40_stage_*` 資料夾**，以 `question_id` 合併；同一題出現在多個資料夾（重跑／補跑）時**全部保留並標示來源資料夾**，不得靜默擇一。**只讀**，且要等 T2 完整結束；每筆 `lineage` 內有 `prompt_context_lines` 與 `retrieval_trace[]`，欄位 `kind, rank, text, score, source_doc_id, source_svo_chunk_index, article_no, in_prompt`）。

### 5.3 目標與非目標

**目標**：產出可重跑的盤點腳本、測試、JSON／Markdown 結果，回答 §5.1 三個問題，並列出建議的 A/B 候選題（含 `57-AGGR18`）。

**非目標**：不呼叫 LLM／embedding；不改 `chat()`、檢索、評分；不改題庫；不寫 Neo4j；不評論「A 案該不該做」（只給數字，判斷留給使用者與報告）。

### 5.4 設計

**檔案**（全為**新增**，避免與 sdd 分支衝突）
- `scripts/analysis/source_ambiguity_audit.py`：CLI；**純函式與 I/O 分離**（正規化、分組、碰撞判定、分類皆為純函式，便於離線測試）。
- `tests/scripts/test_source_ambiguity_audit.py`：全離線，用小型假資料。
- 輸出：`data/analysis/source_ambiguity/{kg_wide.json, questions_frozen42.json, prompt_level_stageA.json, summary.md}`（新目錄；若 `data/analysis/` 已存在請沿用其慣例）。

**共同定義（請在腳本 docstring 與 summary 中逐字寫明，避免結果不可比）**
- **正規化 `norm(text)`**：`unicodedata.normalize("NFKC")` → 移除所有空白 → 移除中英文標點（至少 `，。、；：！？（）「」『』【】,.;:!?()[]<>"'` 與破折號）。**不做簡繁轉換、不做同義詞處理。**
- **同文**：`norm(a) == norm(b)`。
- **Jaccard**：`norm` 後字元 bigram 集合的 Jaccard 係數（連續值；**不設「碰撞」門檻**，只報數值與分佈）。
- **句框重疊 `frame_overlap(a,b)`**：對 `norm(a)`、`norm(b)`，`LCP`＝最長共同前綴長度、`LCS`＝最長共同後綴長度，`frame_overlap = min(LCP + LCS, min(len(a), len(b))) / min(len(a), len(b))`（前後綴不重疊計算，上限 1）。連續值，0～1。**此度量是為了描述 AGGR18 的形態而設計，屬探索性描述統計，不是已驗證的歧義判準；summary 中須如實標示。**
- **同文異源**：同一 `norm(fact_text)` 出現在 ≥2 個不同 `Document`（以 `Document.source_doc_id`／`title` 判定，寫明用哪個）。**這是精確碰撞，與上兩個連續度量分開報告，不得混為一談。**
- **驗算基準（必須進單元測試，見 §5.5）**：AGGR18 四筆 Fact 文字——舊法§24「經公立醫療機構認定身心障礙不堪勝任工作」、舊法§23「職業災害勞工 經醫療終止後，經公立醫療機構認定身心障礙不堪勝任工作」、新法§84「職業災害勞工經醫療終止後，經中央衛生福利主管機關醫院評鑑合格醫院認定身心障礙不堪勝任工作」、新法§85「職業災害勞工 經中央衛生福利主管機關醫院評鑑合格醫院認定身心障礙不堪勝任工作」。預期（允許 ±0.01）：舊§23×新§84 Jaccard 0.489、frame_overlap 0.806；舊§24×新§85 Jaccard 0.262、frame_overlap 0.632；舊§23×新§85 Jaccard 0.362；舊§24×新§84 Jaccard 0.255；舊§23×舊§24（同法）Jaccard 0.621；跨法精確同文＝否。

**Phase 1（現在可做）**
- **P1-a KG 全域**：以**單一唯讀查詢、分批串流**取出 `(fact_text, Document.title, Document.source_doc_id, LawArticle.article_no)`（不含向量欄位；批量 ≤2000；結束前印出實際列數並與 `kg_fact_total` 比對，不符則註明）。輸出：Fact 總數、`norm` 後相異文字數、同文異源的相異文字數與其占 Fact 的比例（**以 Fact 為分母**與**以相異文字為分母**兩種都報）、前 20 個範例（含涉及的法規名與條號）。**（選做）** 跨法規句框相近的事實對統計：以「`norm` 前 8 字相同或後 8 字相同」做 blocking 取候選對，再算 Jaccard 與 `frame_overlap`；blocking 群組大小 >200 者略過並在輸出註記略過的群組數，**不得為了算完而做全量 O(n²) 比對**。
- **P1-b 題目層級（42 題凍結）**：對 `eligible_ids` 每題：
  - `n_source_laws`：`atomic_gold_facts[].source_law` 相異數。
  - `q_mentions_multi_law`：題目文字是否含 ≥2 個法規名或「新法／舊法／修正前後」等對照字眼（**規則寫成常數清單，附於輸出**）。
  - 每個 `exact_span` 對應到 KG 的 Fact：以「`norm(fact_text)` 與 `norm(exact_span)` **互相包含**且較短者長度 ≥ 8 字」判定；輸出 `matched_fact_count`、`matched_documents`；**未配對的 span 要列出，不得略過或當作沒發生**。
  - `gold_exact_collision`：任一配對到的 gold Fact，其 `norm(fact_text)` 是否也出現在**另一部法規**（精確碰撞）。
  - `max_cross_doc_jaccard`、`max_cross_doc_frame_overlap`：該題配對到的 gold Fact 中，**來自不同 Document 的每一對**的最大值（連續值；只有一部法規則為 `null`，不是 0）。
- **P1-c 候選題**：候選條件＝`n_source_laws ≥ 2` 且 `q_mentions_multi_law` 為真；**依 `max_cross_doc_frame_overlap` 由高到低排序**，並列出三個度量值，**不設「碰撞」門檻**（避免用單一題調出來的數字當判準）。`57-AGGR18` 必須在候選中且排名靠前（其基準值見 §5.4）；**若不在，回報原因，這本身是重要發現**。另附「僅 `n_source_laws ≥ 2` 但題目無對照字眼」的題目清單，供使用者判斷。

**Phase 2（T2 Stage A 完成後）**
- 對 Stage A 每題 `prompt_context_lines`（注意它是**巢狀 list**，複合問題每個子問題一份，請處理）：統計 prompt 內「與同題另一行同文、但 `source_doc_id` 不同」的行數與比例；有 ≥1 個碰撞的題數／占比；另報告跨文件行對 `frame_overlap` 的分位數（不設門檻）；並**逐字輸出 `57-AGGR18` 的實際 prompt 行**（報告63 §9.6 第 1 項尚缺的直接證據）。**注意**：`prompt_context_lines` 是純文字（帶 `- ` 前綴），**來源文件資訊在 `retrieval_trace[]`**（`in_prompt=true` 的項目，欄位 `text`、`source_doc_id`、`article_no`）；兩者需以正規化文字比對對應，**配不到的行要列為 unmatched 並計入統計，不得丟棄**。
- **可比性聲明（必須寫入 summary）**：Stage A 是 `top_k=40`，與凍結基準（`top_k=20`）不同；本統計只回答「行有沒有歧義」，**不得用來比較答對率**。
- 若 T2 尚未完整結束，Phase 2 **不要執行**（不要以尚在增加中的資料夾當結論），在 §8 標「Phase 2 待 T2 完成」。**是否結束以使用者通知為準**，不要自行判斷（各資料夾的最後寫入時間不代表整體進度）。

### 5.5 測試計畫

`tests/scripts/test_source_ambiguity_audit.py`（離線、無網路、無 Neo4j）：

| 測試 | 斷言 |
|---|---|
| `norm` | 全形／半形、空白、標點差異的同一句正規化後相等；不同句不相等；不做簡繁轉換 |
| 同文異源分組 | 構造 (文字, 文件) 列：同文跨 2 文件 → 計入；同文同文件重複 → **不**計入；分母兩種算法正確 |
| Jaccard 與 `frame_overlap` | 用 §5.4「驗算基準」的 AGGR18 四筆文字逐對斷言（容差 ±0.01）；無關對照「事假 一年內合計不得超過 十四日」對「特別休假 五年以上十年未滿者 每年十五日」的 `frame_overlap` 約 0.07（斷言 <0.15）；兩者皆不使用「碰撞門檻」 |
| 前後綴不重疊 | 兩句完全相同時 `frame_overlap = 1`（不因前後綴重疊超過 1）；一句是另一句的子字串時不超過 1 |
| span↔Fact 配對 | 互相包含且長度 ≥8 → 配對；長度 <8 → 不配對；一對多；**未配對要被列出** |
| 候選題判定 | `n_source_laws=1` → 非候選、三個跨法度量為 `null`；`≥2` 且題目有對照字眼 → 候選並依 `frame_overlap` 排序；`≥2` 但無對照字眼 → 列入「僅多法規」清單、非候選；**用 AGGR18 的資料構造一題，斷言它是候選且排名高於無關題** |
| `prompt_context_lines` 巢狀處理 | 巢狀 list 與扁平 list 都能處理；空 list 不崩潰 |
| 輸出不含向量欄位／憑證 | 掃描輸出 JSON，不得出現 `fact_embedding`、`NEO4J_PASSWORD` 字樣 |

### 5.6 驗收清單

- [ ] 腳本可重跑且**決定性**（同輸入同輸出；輸出含 git commit、`kg_id`、實際 Fact 列數、產出時間）。
- [ ] Neo4j 只用 READ session；沒有寫入、沒有建索引；查詢不回傳向量欄位；分批、總耗時與列數已記錄。
- [ ] Phase 1 三項產出齊全；**未配對 span、找不到的題目 ID 都有列出**。
- [ ] 42 題範圍以 `frozen_manifest.json` 的 `eligible_ids` 為準（不是 65 題）。
- [ ] `summary.md` 明列所有定義（正規化、Jaccard、句框重疊、同文異源、多法規字眼清單）與**限制**（例如：`Document.effective_date` 僅 15/64 有值（**2026-09-21 更正：原任務書誤寫「全 `None`」**）；Jaccard 與句框重疊都只是字面度量、未涵蓋語意相似；句框重疊是依 AGGR18 形態設計的探索性度量，未經驗證為歧義判準）。
- [ ] 沒有呼叫 LLM／embedding、沒有修改題庫或凍結目錄、沒有 commit 憑證或大量原始 KG 資料（輸出只含統計與範例）。
- [ ] 新增測試全通過，且全套 `pytest` 無新增失敗。

### 5.7 風險

- 全量拉 16,826 筆 Fact 的量不大，但**不要**帶 `fact_embedding`；請以小批量、循序執行，避免與 T2 搶 Neo4j 資源。
- `exact_span` 是原文整句、`fact_text` 是抽取後的短語，配對規則會有漏配；**以「列出未配對」代替「假設都配得到」**。
- Phase 2 的 `prompt_context_lines` 結構在 T0 之後才有，舊 records 沒有此欄位；缺欄位要明確標示。

### 5.8 停止條件（本任務專屬）

`kg_fact_total` 與實際查得列數差異 >1%（可能是 KG 在變動）；`57-AGGR18` 的 gold span 在 KG 中完全配不到、或配到的 Fact 與 §5.4 驗算基準的四筆不一致；或需要為了配對而改用 embedding／LLM。

### 5.9 給 Codex 的一句話指令

> 依 `docs/報告/64_…` §2、§5 執行 TASK-3 Phase 1：新增唯讀盤點腳本與離線測試，只讀 Neo4j（不回傳向量欄位）、不呼叫 LLM，產出 `data/analysis/source_ambiguity/`；Phase 2 等 T2 Stage A 完成才做；結果回填 §8。

---

## 6. 暫不派工項目：解鎖條件

這些**不要現在派**。列出條件，是為了 T2 完成後能立刻接手。

### TASK-A A 案（事實行加來源標籤）— 解鎖條件

1. T2 Stage A（含其依 `adaptive_repeat.py` 的補跑）已完成，Ollama 空閒。
2. **使用者裁示**（報告63 §8.4、§10.5）：(a) 是否接續；(b) 採用規則的數值與判定（AGGR18 ≥3 次且歸屬**人工核對**；凍結 42 題達標數不低於 12 且原達標 12 題不得新增失敗）；(c) 標籤第一版只放「法規名＋條號」（實測 AGGR18 涉及的兩部法 `effective_date` 皆為 `None`；全 KG 僅 15/64 有值）；(d) 旗標位置：建議放 `KGConfig.domain`、評測以 `ConfigLoader.load(..., request_overrides=)` 切換，而非新增 `ChatRequest` 欄位。
3. 基底必須是 **sdd 分支最新 commit**（不是 `master`），因為 `routers/agent.py` 的 `_build_prompt()` 已被 T0 改動。
4. TASK-3 的候選題清單可作為評測題目來源（避免 n=1）。
5. 必須用**同一個格式函式**同時服務 `chat()`（`_split_fact_lines()`）與 harness K 臂（把 `retrieved_texts` 原樣當 `context_lines`，報告62 §10.2）兩條路徑。

### TASK-B few-shot 參數化（報告33「3b」）— 解鎖條件

使用者裁示＋設計決定：① `KGConfig` 目前全為 scalar，list 欄位必須用 `tuple[...]`（我已實測 frozen 模型內的 `list` 可 `.append()` 成功，會破壞 `model.py:3-5` 與報告33 §5 R3 的深度不可變承諾）；② `deep_merge` 對非 mapping 值是**整體取代**（`tests/core/test_kg_config.py::test_deep_merge_replaces_lists_wholesale`），domain pack 與 per-KG profile 的清單不會串接，需決定是否符合預期；③ 需 per-stage eval（報告33 §5 R4）與 Ollama。

### TASK-C 型別「概念」成因診斷 — 解鎖條件

Ollama 空閒。方法（供日後派工）：以現行 prompt＋`qwen2.5:7b` 對 KG#4 抽樣 chunk **重抽但不寫入**，統計 LLM 輸出 `subject_type`／`object_type` 為空、為「概念」、為其他的比例，區分「LLM 未給型別而落入 `models/knowledge_graph.py:196,200` 預設值」與「LLM 直接輸出概念」。

### TASK-D、TASK-E、TASK-F

見 §1 矩陣。TASK-E 須先完成 TASK-1；TASK-F 須使用者決定三份 Gemini 檔案（`本體抽取與系統落地工程缺口紀錄表_v1.0.md`、`知識圖譜分層客製化架構現況與接續任務報告書_v1.0.md`，以及第一份評測報告——後者只存在於對話）是否入庫、是否編號、是否需要依報告63 §9.2 出校正版。

## 7. 回報格式（每個任務完成時，回填 §8 對應小節）

```text
任務：TASK-N
分支／worktree：
基底 commit：
最終 commit（清單）：
pytest：動工前 N passed → 完成後 M passed（失敗數）
新增／修改檔案（git diff --stat）：
是否觸碰禁止項（Ollama／Neo4j 寫入／sdd worktree／凍結物件）：否／是（說明）
與任務書描述不符的現況：
範圍外發現（未處理）：
驗收清單逐項結果：
未完成／未驗證：
```

## 8. 結果紀錄（由執行者回填）

### 8.1 TASK-1
（待填）

### 8.2 TASK-2
（待填）

### 8.3 TASK-3
（待填；Phase 1／Phase 2 分別記錄）

## 9. 使用者待裁示

1. 是否同意派工 TASK-1／TASK-2／TASK-3（可分批、可只派其中幾個）？
2. 基底分支：是否先把 `worktree-report-gemini-review` ff 併入 `master`？（不併也可，任務書已指定基底。）
3. TASK-3 Phase 2 是否等 T2 Stage A **完整結束**後再做（建議是）？
4. TASK-A 的裁示項 (a)–(d)（見 §6），可在 T2 期間先想，T2 完成後即可解鎖。
