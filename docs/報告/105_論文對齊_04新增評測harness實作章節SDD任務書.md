# 報告105：論文對齊——04 新增「4.12 評測 Harness 實作」章節 SDD 任務書

> **日期**：2026-09-29
> **執行者**：Codex｜**設計、撰寫與審核**：Claude Code
> **基準 commit**：本任務書檔案被加入版控時的那個 commit（見 §6 開頭指示，不寫死 hash）
> **工作目錄**：`D:\Users\666\Desktop\world knowledge graph rag\.claude\worktrees\sdd-retrieval-comparison`
> **上位文件**：[報告96](96_程式流程與論文03_04登記缺漏盤點.md) §3（「評測管線在04幾乎無章節」）；[報告95](95_專案節點流程總覽與設計說明.md) §15（N13）；[報告97](97_專案目標與BT_SM工作流設計.md) §4.7（BT-6 EVAL）——本任務內容整理自這兩份已核對過程式碼的文件，非重新研究
> **性質**：**只改一份論文檔案，在檔案末尾新增一整節**。不改程式碼、不改資料、不跑評測。

---

## 0. 給 Codex 的重點

1. 這次是**附加一整個新章節**在 `04_系統實作.md` **檔案最末尾**（目前檔案共 340 行，§4.11 是最後一節），風險最低的插入方式——不需要在既有內容中間找插入點，直接接在檔案末尾即可。
2. §2 給的整節文字是**最終版本**，逐字複製貼上，不要自行改寫、不要自行補充或刪減內容。
3. 完成後在本機 commit，**不要 push**。

---

## 1. 背景

論文第六、七章的所有 RQ1 實驗結果（B0/B1/K 三臂比較、B2 全量 pilot）都是由 `scripts/eval/run_rq1_comparison.py` 這套評測 harness 產出，但第四章目前完全沒有章節描述這套 harness 本身怎麼運作——04 §4.11 只提到五個評測相關模組「已入庫」，但沒有說明評測的整體流程、各臂定義、評分方式。本任務新增一節補上這個缺口。

---

## 2. 已定案的內容（Claude Code 設計，請逐字採用）

以下是**要附加在檔案末尾的完整新章節**：

```markdown

## 4.12 評測 Harness 實作

本節說明 `scripts/eval/run_rq1_comparison.py` 這套評測 harness 的實際運作方式——它是第六、七章所有 RQ1 實驗結果（S0–S3 對照、B2 全量 pilot）的產出來源。§4.11 已入庫的五個模組（`lineage_tracker.py`／`atomic_scorer.py`／`cost_analyzer.py`／`deterministic_guard_service.py`／`refusal_guard.py`／`adaptive_retrieval_service.py`／`query_classifier.py`）皆為此 harness 的組成部分；本節補齊整體流程與各臂定義，取代 §4.11 末段「`main()` 尚未串接實際跑測迴圈」這句已過時的敘述（見該段 2026-09-28 更新註記）。

### 4.12.1 臂定義與別名

Harness 支援的檢索臂與 05 §5.2.1 的方法矩陣命名對照如下：

| 臂 | 別名 | 檢索前端 | 說明 |
|---|---|---|---|
| D | — | 無檢索 | 純 LLM，`use_svo=False`，作為無檢索下限對照 |
| B0 | M1 | chunk dense KNN | Naive chunk-RAG（`services/baseline_rag_service.py`） |
| B1 | M2 | chunk dense＋BM25，RRF 融合 | Hybrid chunk-RAG 強基準，RQ1 主要比較對象 |
| B2 | — | B1 檢索前端＋複雜度路由＋子問題分解＋逐子問題「檢索→反思→精煉」迴圈 | Agentic RAG 強基準（`services/agentic_baseline_service.py`；`_b2_reflect()` 為真實 LLM 反思實作，見 `run_rq1_comparison.py`） |
| F | M3 | 完整 `chat()` 流程，`retrieval_mode=fact_only` | 消融：只用語意 Fact 檢索 |
| G | — | 完整 `chat()` 流程，`retrieval_mode=bfs_only` | 消融：只用 BFS 圖遍歷 |
| K | M4 | 完整 `chat()` 流程，`retrieval_mode=both` | 本論文 KG-BFS 目標配置 |
| K-2b | — | 同 K，但 `disable_grounding_regen=True` | 消融：關閉方案B／2b 定向修正的生成端貢獻 |

`ARM_ALIAS_MAP`（`run_rq1_comparison.py`）把 M1–M4 映射回 B0／B1／F／K，兩套命名可互換使用。B0／B1／B2 三臂共用同一份 `services/baseline_rag_service.py::load_baseline_index()` 建立的 chunk 索引；F／G／K／K-2b 四臂透過 `_build_kg_chat_request()` 組出對應的 `ChatRequest`（`retrieval_mode` 依上表對映），實際呼叫完整的 `chat()` 路徑（`_drain_chat()` 收集 SSE 串流結果）。B0／B1／B2 三臂則繞過 `chat()`，直接呼叫 3.6／04 §4.7.3 所述的共用生成堆疊 `agent._generate_from_context_lines(context_lines=...)`，確保生成端與 F／G／K／K-2b 逐位元相同，是單一變因控制（見 3.8）的實作依據。

### 4.12.2 逐題執行與例外處理

Harness 主迴圈對「題目 × 臂 × run」三層巢狀執行，每次呼叫皆包在 `asyncio.wait_for(..., timeout=args.query_timeout_s)` 之內：

- **正常完成**：記錄答案、延遲、`llm_calls`（生成端與 judge 端分開計數）、`estimated_tokens`，並執行 4.12.3 所述的評分管線。
- **逾時（`asyncio.TimeoutError`）**：`_build_timeout_record()` 產生一筆 `failure_attribution="Harness Timeout after {N}s"` 的記錄，`atomic_accuracy` 計為 0。
- **其他例外**：`_build_exception_record()` 記錄例外訊息與已耗費時間，同樣不中斷整個迴圈，僅該筆記錄失敗。

前置檢查（`services/evaluation_preflight.py`）在迴圈開始前執行：核對題庫雜湊是否符合凍結 manifest、確認 `settings.judge_llm_provider` 與生成端 provider 不同（正式評測強制獨立 judge；`--allow-shared-judge` 僅供明確標記的 pilot 使用，見報告69／70）。B0／B1／B2 任一臂在場時，另外呼叫 `_load_scoped_baseline_index()` 依 `--chunk-size` 載入或建立 chunk 索引。

### 4.12.3 評分管線

每筆完成的執行，依序經過：

1. **血統追蹤（`services/lineage_tracker.py::LineageTracker`）**：分三階段記錄——`record_retrieval_async()`（Stage 1 檢索，含 SNR、Context Recall，語意 fallback 版）、`record_context_assembly_async()`（Stage 2 上下文組裝）、`record_generation()`（Stage 3 生成，記錄是否觸發 `regenerated`、確定性守衛是否觸發）；`build_full_lineage_async()` 彙總後產生 `failure_attribution`（明確標示失效發生在哪一階段），是 Context Quality 矩陣（Context Recall／SNR／Chain Completeness，05 §5.5.1a）的資料來源。
2. **確定性法律守衛（`services/deterministic_guard_service.py::DeterministicGuardService.verify_draft()`）**：在最終答案產生後執行，只影響 `is_perfect` 判定，不覆寫或修改答案本身；用於區分「檢索覆蓋率足夠但法律關鍵詞被改寫」與「根本沒有召回證據」兩種失效模式。
3. **原子事實評分（`services/atomic_scorer.py::AtomicScorer.evaluate_async()`）**：以 `exact_span` 逐字包含比對為主，未命中才呼叫獨立 judge 做語意蘊含核對（`services/semantic_span_matcher.py`）；`refusal_expected`（Type-E 拒答題）走關鍵字比對與 `trap_claim_spans` 陷阱主張檢查；`deterministic_guard_passed`／`guard_failures` 由上一步傳入，僅影響 `is_perfect`、不改動 `atomic_accuracy`／`atomic_recall`。
4. **範圍稽核（`services/claim_scope_auditor.py::audit_answer_scope()`）**：檢查新舊法歸屬、角色互換等 `role_mismatch` 風險（報告84／85）。

每筆記錄同時保存 `agentic_trace`（僅 B2 臂有值，含 `complexity`／`retrieval_calls`／`reflect_calls`／`rounds_per_subquestion`）供 B2 專屬診斷使用。

### 4.12.4 自適應重跑與配對判定

`scripts/eval/adaptive_repeat.py` 依 LLM 推論非決定性（報告20 已 root-cause 為批次大小依賴）設計三態判定：單次執行結果為 `[pass]` 時標記 `single_pass`（列入抽查候選，`pick_audit_sample()` 依比例抽樣）；`[pass, pass]`／`[fail, fail]`（第二輪重跑）分別收斂為 `stable_pass`／`stable_fail`。題目「確定通過」的口徑為 `single_pass ∪ stable_pass`。跨臂比較時另以 exact McNemar 檢定做逐題配對判定（見 06 §6.2.1 的具體套用）。

### 4.12.5 已知量測限制

- 評分器偽陰性下界 ≥7.2%、偽陽性下界 ≥3.4%（報告62 §14，人工複核樣本估計）；**達標題數 ±2 屬量測噪音範圍**，不應過度解讀微小差異。
- **逾時目前與真正的生成失敗一樣被計入 `atomic_accuracy=0`**，harness 本身未提供逾時排除統計選項（報告94 已記錄此限制，未修改 harness 程式碼）。
- 規則 R（bigram overlap 敏感度分析）與評分器 v2 僅為診斷工具，非正式評分依據（報告62 §14.11 使用者已裁示不採用為預設）。
- B0／B1／B2 三臂共用生成堆疊，但 B0／B1／B2 執行時**不**套用 3.6 節的複合問題分解、2b 定向修正、G3 列舉完整性 guard——這是刻意的「前導夠用版」簡化（見 04 §4.7.3），代表 harness 對 chunk-RAG 臂的生成端強化程度低於 K 臂，構成 RQ1 單一變因控制上的一項已知不對稱，尚未消除。
```

---

## 3. 任務清單

### T1　04 檔案末尾附加新章節

- **檔案**：`docs/論文/04_系統實作.md`
- **定位**：檔案最末尾（目前檔案共 340 行，最後一行是「完整審查記錄見 `docs/報告/47_Claude_Code交接任務書.md`。」）。
- **動作**：在檔案末尾（最後一行之後）附加 §2 給定的完整新章節，逐字複製，**注意保留章節開頭的空白行**（§2 的內容區塊本身以一個空行開頭，是刻意的段落間距，請一併複製）。
- **自我檢查**：
  1. `git diff` 該檔案應該**只有新增行**，原有 340 行內容完全不應出現在刪除行裡。
  2. 新章節標題應為 `## 4.12 評測 Harness 實作`，其下應有 5 個 `###` 子小節（4.12.1 至 4.12.5）。

### T2　03 變更紀錄新增條目（可選，若前次報告104的條目已是最新則接續）

- **檔案**：`docs/論文/03_變更紀錄.md`
- **動作**：依既有格式新增一筆 2026-09-29 條目：「依報告105在 04 新增『4.12 評測 Harness 實作』章節，說明評測 harness 的臂定義、逐題執行流程、評分管線與自適應重跑判定，取代 §4.11 末段『尚未串接跑測迴圈』的過時敘述；純新增章節，未改動任何既有文字。」

---

## 4. 全域禁止事項

- 不修改任何 `.py`、`.json`、`data/` 檔案；不執行 pytest 或評測。
- 不修改 04 既有的任何一個字——本任務是**純附加**在檔案末尾，不是在中間插入，風險最低，但仍須確認沒有意外觸碰既有內容。
- **不得**改寫 §2 給定文字的用詞或語氣、不得增刪其中的子小節。
- 使用繁體中文；沿用既有章節標題／粗體風格。
- 不 push。

---

## 5. 驗收標準（Claude Code 審核時逐項檢查）

| # | 檢查 | 方法 |
|---|---|---|
| A1 | 新章節逐字附加在檔案末尾，`## 4.12` 標題與 5 個 `###` 子小節皆存在 | 人工核對 |
| A2 | 04 原有 340 行內容一字未動 | `git diff` 核對（不應出現刪除行） |
| A3 | T2 變更紀錄新增一筆，位置正確 | 人工核對 |
| A4 | `git diff --stat` 只包含 `04_系統實作.md` 與 `03_變更紀錄.md`，`04_系統實作.md` 只有新增行、沒有刪除行 | `git diff --stat` 與 `git diff` |
| A5 | 新章節內提到的臂名稱（D／B0／B1／B2／F／G／K／K-2b）、模組路徑（`atomic_scorer.py` 等）與 §2 逐字一致 | 逐段核對 |

---

## 6. 回填區（Codex 填寫）

- **commit SHA**：
- **T1–T2 完成情況**：
- **發現但未處理的其他問題**：

---

## 7. 給 Codex 的指令（使用者可直接貼上）

```text
請在 D:\Users\666\Desktop\world knowledge graph rag\.claude\worktrees\sdd-retrieval-comparison
（分支 worktree-sdd-retrieval-comparison）執行
docs/報告/105_論文對齊_04新增評測harness實作章節SDD任務書.md。

開始前：
- 先執行 git status 與 git log -1 --oneline，確認 HEAD 為本任務書檔案被加入版控時的那個
  commit，且工作區乾淨；若不符，先 git pull 或回報後再確認是否繼續。

規則：
1. §2 給的整節文字是最終版本，逐字複製貼上到檔案末尾，不要自行改寫、增刪或補充內容。
2. 這是純附加在檔案末尾——git diff 應該只有新增行（+），不應該有刪除行（-）。
3. 只改 docs/論文/04_系統實作.md（T1）與 docs/論文/03_變更紀錄.md（T2）。
   不改任何程式碼、.json、data/ 檔案，不跑 pytest 或評測。
4. 完成T1後自行核對：新章節標題為「## 4.12 評測 Harness 實作」，
   其下有5個「###」子小節（4.12.1至4.12.5）。
5. 遇到任務書沒涵蓋的情況，記在任務書 §6 回填區，不要自行擴大修改範圍。

完成後：
- 填寫任務書 §6 回填區。
- 跑一次 git diff --stat 與 git diff，貼在回報中。
- 全部變更做成一個本機 commit，訊息開頭：docs(論文): 報告105 新增04評測harness實作章節
- 不要 push。
- 回報內容：commit SHA、T1-T2 各自完成情況、git diff --stat 的輸出、回填區摘要。
```
