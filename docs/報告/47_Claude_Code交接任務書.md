# 47 Claude Code 交接任務書（Handover Document）

> **建立日期**：2026-09-14  
> **交接對象**：CLAUDE CODE  
> **專案路徑**：`d:\Users\666\Desktop\world knowledge graph rag`  
> **專案狀態**：SDD 階段一至五的核心模組已實作，66 項指定關鍵單元測試 100% 通過；但階段五的 `ChunkingConfig` 主旨錨定尚未完成實際抽取管線接線。論文核心章節已同步記錄設計與模組狀態，正式端到端評測數據仍待任務 A 產出。

> ⚠️ **編號訂正 + 完成狀態核實結果（2026-09-14，入庫時補記，審查已完成）**：本文件原編號 46，建立時只存在主要 checkout 目錄、從未 `git commit`，因與已入庫報告衝突改編號 47。
>
> **審查結論**：「SDD 階段一至五核心模組已實作、66/66 測試通過」——**66/66 測試通過屬實**，已把全部檔案複製進 git worktree 實際重跑一次確認；程式碼架構乾淨，`ChunkingConfig`／`header_anchored` 與既有 `KGConfig`／`SVOChunk` 慣例整合良好。跑全套既有 877 題 pytest 時額外發現並修復 1 個真迴歸（新 `chunking` 分區未登記進 `core/kg_config/stages.py` 的 `STAGE_REGISTRY` 一致性檢查）。全套測試現為 897 passed。
>
> **審查中發現三個需要留意的問題（已標註在對應檔案，未全部改動邏輯）**：
> 1. `services/cost_analyzer.py::get_baseline_profile()` 回傳的延遲/儲存/成本數字皆為寫死的**估計值**，docstring 原文「依據…實測數據」與實作不符，已加註記，使用前務必用真實跑測結果覆蓋。
> 2. `services/query_classifier.py::MULTI_HOP_PATTERNS`（Type-C 多跳判斷）是題庫特定題目主題字串的硬編碼，屬於對已知題庫的過擬合，不是可泛化分類器，已加註記，不可用於任何正式評測結論。
> 3. `data/eval/test_cases.json` 原始版本 `canary-P1`／`canary-P4` 各重複出現兩次、內容矛盾（草稿版 Type-A/unverified vs 定版 Type-E/verified）——**已修復**，並在 `scripts/eval/upgrade_benchmark_dataset.py` 補上防重複 id 的過濾邏輯（根因：`CANARY_QUESTIONS` 無條件附加，未濾掉 legacy 檔案裡已存在的同 id 條目，重跑腳本會再犯）。
>
> **`scripts/eval/run_rq1_comparison.py` 未完整**：`main()` 目前只寫 `manifest.json` 並印一行訊息，`_run_single_query()`／`_render_pareto_summary()` 等實際跑測函式都已寫好但**從未被呼叫**——直接執行本腳本不會產出任何比較結果，已在該檔案頂部加上誠實註記，串接邏輯留給下一輪任務決定。

---

## 0. 文件角色、資料真值與閱讀順序

### 文件角色

- `HANDOVER_CLAUDE_CODE.md`：快速入口、目前狀態與不可違反的執行限制。
- 本文件：Claude Code 的工程任務、執行順序、檔案導引與交接驗收。
- `docs/報告/44_黃金版Benchmark與評測修正任務書.md`：Gold schema、Benchmark 資格、評分規則與驗收標準。

建議閱讀順序：先讀根目錄導引，再讀本文件，最後依報告 44 執行評測與 Gold 相關工作。

### 資料真值層級

```text
原始法規文件／鎖定版本與 hash = 法律真值來源
docs/附錄A題庫.json          = legacy 題目來源
data/eval/test_cases.json    = derived evaluation dataset
KG Fact／chunk／模型答案       = 系統產物，不得作為 gold truth
```

修改題目或 Gold 時，必須先回到原始法規，再更新衍生評測資料；不得只修改 `data/eval/test_cases.json` 後宣稱來源已同步。

## 1. 核心架構原則與鐵律（Core Principles & Guardrails）

接手工程師 / Agent 請務必遵守以下三大核心架構鐵律，**絕不可破壞**：

1. **零代碼生成哲學（Zero Code-Gen & Universal Engine）**：
   - **核心 Python 演算法與程式碼保持 100% 固化通用**。
   - **嚴格禁止**每當新增一個領域或新建一個 KG 就動態自動生成（Generate）新的 Python 程式碼或腳本。
   - 所有領域差異、法條結構特徵、切塊大小、正則式、提示詞範例、守衛門檻，**全部由結構化、型別化（Pydantic）的宣告式參數檔（JSON/YAML Profiles, `DomainPack`, `ChunkingConfig`）驅動**。通用引擎在執行期動態套用不可變之 `KGConfig`。
2. **因果血統不變式（Lineage Invariant & Three-Phase Isolation）**：
   - 嚴格隔離 Phase 1（離線建圖）、Phase 2（查詢檢索）、Phase 3（答案生成）三階段之延遲、Token 消耗與錯誤歸因。
   - 切塊前綴注入主旨時，`source_sentence_start` 與 `source_sentence_end` 必須嚴格維持原始實體文字行號，絕不可因前綴注入造成索引位移。
3. **確定性接地守衛（Deterministic Grounding Guard）**：
   - 法律與法規關鍵事實（時效起算點、法條條號跨文覆核、數值查表缺口）**絕不可單純依賴同質弱 LLM 裁判（NLI）**。
   - 必須由確定性規則守衛（正則提取、精確字面錨定比對、區間解析器）在生成草稿後進行硬攔截，防止起算點被平滑化（如「當月一日」被改寫為「當日」）。

---

## 2. 目前已完成模組與驗收狀態（66/66 Tests PASSED，⚠️ 見文首訂正——此聲稱尚待入庫後審查驗證）

本專案剛完成多階段 SDD（報告 45、46）架構改造，所有模組均已通過自動化測試驗證：

| 階段 / 模組 | 核心檔案 | 功能說明 | 測試檔案與狀態 |
| :--- | :--- | :--- | :--- |
| **階段一：血統追蹤** | `services/lineage_tracker.py` | 三階段因果隔離血統追蹤器（`PhaseLineageTracker`），快照保留與根因標準化歸因。 | `tests/services/test_lineage_tracker.py`<br/>✅ **4 passed** |
| **階段二：評分與成本** | `services/atomic_scorer.py`<br/>`services/cost_analyzer.py` | 原子事實精確評分器（`AtomicScorer`，字面 F1 + NLI 懲罰平滑化）、生命週期成本攤提分析器（`CostAnalyzer`）。 | `tests/services/test_evaluation_metrics.py`<br/>✅ **4 passed** |
| **階段三：確定性守衛** | `services/deterministic_guard_service.py`<br/>`services/refusal_guard.py` | 起算日錨點守衛、條號覆核守衛、數值區間查表守衛、兩階段（檢索前 Canary / 檢索後零召回）拒答護欄。 | `tests/services/test_deterministic_guards.py`<br/>✅ **6 passed** |
| **階段四：自適應路由** | `services/query_classifier.py`<br/>`services/adaptive_retrieval_service.py` | 查詢特徵意圖分類器（法規/時效/概念/混合）、自適應行為樹調度器（Cypher BFS、向量 Fact、Fallback 降級）。 | `tests/services/test_adaptive_behavior_tree.py`<br/>✅ **5 passed** |
| **階段五：切塊參數化** | `core/kg_config/model.py`<br/>`services/svo_chunking.py` | `ChunkingConfig` 宣告式參數；`build_svo_chunks()` 支援 `header_anchored` 模式，自動修復「款式斷頭」，保持血統不變式。**核心演算法已完成，但尚未接入實際 `prepare_svo_ready_chunks()` 抽取路徑。** | `tests/core/test_kg_config.py`<br/>`tests/services/test_svo_chunking.py`<br/>✅ **47 passed** |
| **題庫升級與真值** | `data/eval/test_cases.json`<br/>`docs/附錄A題庫.json` | 共 34 題；目前 10 題標記 `verified`（其中 8 題法律題、2 題 Canary），24 題仍為 `unverified`。目前 8 題法律題的 15 個 atomic exact spans 已通過 baseline corpus 字串核對；Canary 的拒答標記不是法規原文 span。 | `scripts/eval/upgrade_benchmark_dataset.py` |

### 2.1 驗收狀態的解讀限制

- 66/66 通過只代表指定核心單元測試通過，不代表端到端抽取管線已完成接線。
- `taiwan-labor-law.json` 目前只宣告 domain name，沒有明確覆寫 `chunking.strategy`；不能假設實際管線已使用 `header_anchored`。
- `data/eval/test_cases.json` 不得在未加入 eligibility filter 前直接把全部 34 題視為正式金標題目。

---

## 3. 文檔與論文同步現況

以下核心文檔已經完成全面更新，具備完整的一致性：
1. **論文章節**：
   - `docs/論文/03_系統設計與方法論.md`：
     - §3.1.2：補充「法規領域專屬切塊策略與參數化主旨錨定（Header Anchoring）」與血統不變式。
     - §3.2 §d：補充「自適應檢索行為樹（BT）動態調度架構」。
     - §3.6 §d：補充「四道確定性接地守衛與兩階段拒答護欄」。
     - §3.9：全面重構擴充為「全生命週期參數驅動與領域可插拔架構（Zero Code-Gen）」，內含 7 大關卡通用代碼 vs 宣告式參數對映矩陣、Mermaid 端到端流程圖與參數生成生命週期。
   - `docs/論文/04_系統實作.md`：
     - §4.11：新增「評測守衛與切塊參數化落地」，登記 SDD-44/45 落地模組。
   - `docs/論文/05_實驗設計與評估.md`：
     - §5.1：收錄 M1~M4 四大核心方法、三階段生命週期矩陣、原子事實評測指標。
   - `docs/論文/05_附錄A_測試題庫.md`：收錄完整標定之 26 題測試題庫與真值來源。
   - `docs/論文/00_研究追溯對映表.md`：追溯條目與實作對應更新。
2. **SDD 任務書**：
   - `docs/報告/45_多階段SDD改善任務書.md`：四階段架構規範。
   - `docs/報告/46_領域可插拔切塊參數化與主旨錨定SDD.md`：切塊參數化與主旨錨定專屬規格。

---

## 4. 關鍵程式碼與設定檔案導引（File Map）

```text
world knowledge graph rag/
├── core/
│   ├── kg_config/                  # 宣告式參數核心套件
│   │   ├── model.py                # KGConfig, ChunkingConfig, RoutingConfig, BfsConfig, FactListConfig
│   │   ├── loader.py               # 四層 Deep-Merge 載入器 (shipped -> domain -> per-kg -> request)
│   │   └── stages.py               # 管線階段登記表 (Stage Registry)
│   └── constants.py                # 系統底層常數
├── services/
│   ├── svo_chunking.py             # SVO 切塊引擎（支援 header_anchored 主旨前綴注入）
│   ├── lineage_tracker.py          # 三階段因果隔離血統追蹤器
│   ├── atomic_scorer.py            # 原子事實精確評分器（含平滑化懲罰）
│   ├── cost_analyzer.py            # 查詢端與建圖攤提成本分析器
│   ├── deterministic_guard_service.py # 四道確定性接地守衛（日期起算日、條號覆核、區間查表）
│   ├── refusal_guard.py            # 兩階段拒答護欄（檢索前 Canary / 檢索後零召回）
│   ├── query_classifier.py         # 查詢特徵意圖分類器
│   ├── adaptive_retrieval_service.py # 自適應檢索行為樹動態調度器
│   └── svo_service.py              # BFS 圖查詢、Fact 向量化與寫入
├── config/
│   ├── domain_packs/               # 領域包（如 generic.json, taiwan-labor-law.json）
│   └── kg/                         # Per-KG 設定覆蓋檔
├── data/
│   └── eval/
│       └── test_cases.json         # 最新升級之金標評測題庫（含 exact_span 真值）
└── scripts/
    └── eval/
        ├── upgrade_benchmark_dataset.py # 題庫校驗升級腳本
        └── run_rq1_comparison.py        # M1~M4 評測比對 Harness 執行腳本
```

---

## 5. Claude Code 接手後的下一步任務清單（Next Actions）

請依序推進以下三個具體任務：

### 優先任務 A：執行端到端評測實驗 Harness
- **前置條件**：先完成評測題目 eligibility filter，只納入 `verification_status=verified` 的題目；不得把 24 題 `unverified` 題目混入正式分數。Canary 題目需依拒答評測規則另行統計。
- **目標**：利用已完成核驗的題目與評測框架，執行 M1~M4 四路比對實驗。
- **執行方式**：
  ```bash
  python scripts/eval/run_rq1_comparison.py \
    --questions data/eval/test_cases.json \
    --out reports/rq1_benchmark/
  ```
  注意：腳本實際參數名稱是 `--questions` 與 `--out`，不是 `--test-cases` 與 `--output-dir`。若 eligibility filter 尚未完成，不得執行正式實驗。
- **產出要求**：
  - 產出原子事實精確度（Atomic F1）、起算點接地率（Grounding Acc）、拒答率與延遲/Token 成本數據。
  - 測量「確定性接地守衛」是否能阻斷 26-Q5 的起算日平滑化幻覺，不得在實驗前預設結果。
  - 保存每筆結果的 retrieval lineage、context lineage、generation lineage。

### 優先任務 B：將切塊主旨錨定（`ChunkingConfig`）接上抽取管線
- **現狀**：`services/svo_chunking.py` 已實作 `header_anchored` 演算法並通過測試。
- **目標**：
  - 檢查 `services/svo_preprocessing_service.py::prepare_svo_ready_chunks()`、`services/svo_service.py::trigger_extraction()` 與 `services/extraction_worker.py`。
  - 將當前 KG 載入的 `cfg.chunking` 傳入實際的 `build_svo_chunks()` 呼叫。
  - 不得假設 `taiwan-labor-law` domain pack 已啟用 `header_anchored`；目前該 pack 沒有覆寫 chunking 設定，需依明確設定與測試決定是否啟用。
  - 確保在非同步建圖流程中，真實法規文件產出的 SVO Chunk 自動具備主旨前綴，同時維持 `source_sentence_start/end` 原始行號不變。
  - `extraction_worker.py` 目前主要消費已寫出的 `svo_index.json`；不要把它誤當成切塊設定的唯一接線點。

### 優先任務 C：評測閉環與論文第五章數據填補
- **目標**：
  - 將任務 A 跑出的真實數據填入 `docs/論文/05_實驗設計與評估.md`。
  - 比對報告 39 / 42 的歷史基準，撰寫消融分析（Ablation Study）。

### 5.1 Track A／Track B 分流規則

- **Track A**：凍結目前 KG、程式 commit、題庫版本與設定，取得現況端到端評測基準。
- **Track B**：接入 `ChunkingConfig` 主旨錨定並重新建圖，產出新的 KG ID 與 manifest。
- Track B 不得覆寫 Track A 的輸出；兩者必須以不同 output directory、KG ID 或 manifest version 保存。
- Track B 完成後，若要比較效果，必須重新執行相同題目、相同 arm、相同 runs 的 Track A 實驗設定。
- 任務 C 只有在 Gold、KG、程式 commit、題目 eligibility 與 run manifest 全部凍結後才可填入論文。

---

## 6. 專案重要執行與測試命令

- **啟動開發伺服器**：
  ```bash
  python -m uvicorn main:app --port 8010 --log-level info
  ```
- **執行全套防護與評測測試（19 項）**：
  ```bash
  pytest tests/services/test_lineage_tracker.py tests/services/test_evaluation_metrics.py tests/services/test_deterministic_guards.py tests/services/test_adaptive_behavior_tree.py
  ```
- **執行切塊與設定參數測試（47 項）**：
  ```bash
  pytest tests/core/test_kg_config.py tests/services/test_svo_chunking.py
  ```
- **執行全套 66 項關鍵驗證**：
  ```bash
  pytest tests/core/test_kg_config.py tests/services/test_svo_chunking.py tests/services/test_lineage_tracker.py tests/services/test_evaluation_metrics.py tests/services/test_deterministic_guards.py tests/services/test_adaptive_behavior_tree.py
  ```

---

## 7. 執行前必核對清單

- [ ] `run_rq1_comparison.py` 使用 `--questions` 與 `--out`。
- [ ] 評測 harness 已排除 `verification_status != verified` 的題目。
- [ ] Canary 題目未被當作一般法律 exact-span 題目計分。
- [ ] 任務 B 使用 `services/svo_preprocessing_service.py` 的實際切塊入口。
- [ ] `cfg.chunking` 已從 KG 設定一路傳到 `build_svo_chunks()`。
- [ ] 主旨注入沒有改變 `source_sentence_start/end`。
- [ ] 任務 A 或 B 執行前已保留現有 66/66 測試基線。

## 8. 停止條件與不可宣稱事項

遇到以下任一情況，Claude Code 必須停止目前任務並回報，不得自行猜測或繼續產出正式結論：

- verified 題數與題庫 manifest 不一致。
- exact span 找不到、source article 不一致，或來源版本／hash 未鎖定。
- 66 項基線測試失敗。
- retrieval lineage、context lineage 或 generation lineage 缺失。
- Track A 與 Track B 使用同一輸出位置或無法區分 KG／commit。
- 題庫版本、KG ID、程式 commit 與 run manifest 對不上。

不得宣稱：

- 66/66 單元測試等於端到端驗收完成。
- 兩個模型一致等於法律真值。
- `facts=1` 等於正確 Fact 已進入 final prompt。
- 六題 pilot 結果代表一般性結論。
- Canary exact span 是原始法規 exact span。
- 舊 KG 結果代表主旨錨定整合後的效果。
