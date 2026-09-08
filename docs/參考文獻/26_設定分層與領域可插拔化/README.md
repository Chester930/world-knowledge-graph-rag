# 26_設定分層與領域可插拔化

對應 `docs/報告/33_設定分層與領域可插拔化設計報告.md`；memory `project-per-kg-config-architecture`。
支撐「通用 vs per-KG 參數化」重構：三層 config 疊合、可插拔 config 來源、domain pack、
per-stage 評分閘控客製化生命週期。**開源前置 + 一台裝置多 KG 需求。**

查證日期 2026-09-08（session `01SHVuNWkSt2PQSEh2Snp73A`）。star / license / pushed 皆經 `gh api` 即時查證。

---

## A. 分層 config 組合 —— 生產級先例（此模式非新創、非高風險）

| 專案 | 事實（gh api 2026-09-08） | 在本設計中的角色 |
|---|---|---|
| **Hydra**（`hydra-ecosystem/hydra`，前 `facebookresearch/hydra`） | ⭐10,639，MIT，pushed 2026-09-08。Meta AI Research 出品 | 「**動態以組合建立階層式 config，再以 config 檔／CLI 覆蓋**」＝本設計「defaults → domain pack → per-KG profile → request」逐層疊合的直接對應。Config Groups（model/optimizer/dataset 各有多個選項可換）＝本設計的 domain pack 可插拔。⚠️ Hydra 綁 YAML + 自己的 CLI/`@hydra.main` 進入點，本專案是 FastAPI 服務、不採用其框架，只借其**組合語意** |
| **OmegaConf**（`omry/omegaconf`） | ⭐2,430，BSD-3-Clause，pushed 2026-09-07。Hydra 的底層 | 階層式 config 的 **merge / resolve 引擎**（多來源合併、變數插值）。本設計的 `ConfigLoader` deep-merge 語意等同 `OmegaConf.merge()`；可直接用它當合併實作，或自寫等價的淺層版 |
| **Kustomize**（`kubernetes-sigs/kustomize`） | ⭐12,155，Apache-2.0，pushed 2026-09-06 | **base + overlays** 模式：base 放共用定義，overlay 對每個環境（dev/staging/prod）套 patch。＝本設計「shipped defaults（base）+ domain pack / per-KG profile（overlay）」。**strategic merge patch**（部分 YAML 併入 base，陣列依 key 併）＝本設計「profile 只寫要覆蓋的 key」的併法 |
| **spaCy config 系統**（`explosion/spaCy` v3，Thinc） | 官方文件查證 | **語言專屬 factory 帶前綴 + fallback**：`en.token_normalizer` 找不到就退回 `token_normalizer`（依 `nlp.lang` 分派）。＝本設計 domain pack 覆蓋 generic、找不到就 fallback 的直接對應；也正是本專案既有 `KnowledgeGraph.pronoun_lexicon_exclude`（per-KG 覆蓋預設詞庫）的一般化。config 用 pydantic + type hints 驗證、「single config file，no hidden defaults」 |

## B. 可插拔 / 多來源 config（使用者要求：不綁單一檔案/格式）

| 專案 | 事實 | 角色 |
|---|---|---|
| **Dynaconf**（`dynaconf/dynaconf`） | ⭐4,326，MIT，pushed 2026-09-01 | 「**code 與 settings 之間的抽象層**，統一介面從檔案或外部系統取參數」。內建多來源：TOML/YAML/JSON/INI/Python **＋ 環境變數 ＋ Redis ＋ HashiCorp Vault**，且**可自訂 loader 讀任何資料源**。遵循 Twelve-Factor。＝本設計 `ConfigSource` 協定 + `FileConfigSource`（副檔名分派）/`Neo4jNodeConfigSource`/`SqliteConfigSource`/`DictConfigSource` 的成熟先例。可直接採用或作為介面設計藍本 |
| **pydantic-settings**（`pydantic/pydantic-settings`） | ⭐1,450，MIT，pushed 2026-09-07 | `settings_customise_sources()`：回傳一個 callable tuple，**順序決定優先序**（第一個最高）；可改順序、加自訂來源、移除內建來源。預設序（低→高）：model defaults → secrets → `.env` → env vars → init args。本專案**已在用 `pydantic-settings`（`core/config.py::Settings`）**→ `ConfigSource` 層可直接建在這個既有機制上，遷移摩擦最小 |

## C. 依 metric 對「每個 stage」優化 prompt/參數

| 專案 / 文獻 | 事實 | 角色 |
|---|---|---|
| **DSPy**（`stanfordnlp/dspy`） | ⭐37,849，MIT，pushed 2026-09-05。Stanford NLP | 「**把手寫 prompt 模板換成對 metric 的程式化優化**」。teleprompter（BootstrapFewShot / COPRO / MIPROv2）拿 program + 訓練例 + metric function，搜尋 prompt/few-shot 變體使 dev-set metric 最大化，**在 module 層級**進行。＝本設計「per-stage 評分閘控客製化」的直接對應，且**印證難點1**：few-shot 不是純 config，是要對 metric 優化的對象（DSPy 整個框架就是為此而生）。⚠️ DSPy 是 opt-in 的重框架，本專案先做「人工掃參數 + gate」，DSPy 式自動化留後 |
| **A Comparative Study of DSPy Teleprompter Algorithms**（Sharma et al., 2024，arXiv:2412.15298） | 搜尋結果層級 | teleprompter 演算法把 LLM 輸出對齊人工評測 metric 的比較研究；佐證「metric-driven per-module 優化」是有方法學支撐的方向 |

## D. 穩定性 —— 風險與緩解的文獻依據

| 文獻 / 來源 | 事實 | 對應風險 |
|---|---|---|
| **Czitrom, V. A. (1999), "One-Factor-at-a-Time versus Designed Experiments", *The American Statistician* 53(2):126–131**（Lucent Technologies；~488 citations；`czitrom-1999-ofat-vs-designed-experiments.pdf` 已下載，PDF-1.1 掃描版） | 🟢 全文下載（citation 經 tandfonline / Semantic Scholar 查證）。核心：**OFAT 只能估主效應、估不到因子交互作用**，交互作用顯著時會導向**假的最佳點**；且 OFAT 要更多 run 才達同樣精度。Full factorial 是唯一能有系統研究交互作用的方法 | **R2**：`run_theta_sweep.py` 預設「一次動一軸」＝OFAT。本專案已實測到耦合（θ sweep 調 X 使 Y/Z 退步、canary FRR/MRR 消長）→ OFAT 只能當**篩選**，動過的軸要再跑小型 factorial / 交互作用檢查 |
| **Configuration Drift**（Puppet、IBM Think、AWS Well-Architected "Anti-patterns for everything as code"） | 🟡 業界文件層級 | 「實際 config 狀態逐漸偏離預期 baseline → 系統不穩定、維護低效」。**R1**：per-KG profile 累積 → config sprawl。緩解＝使用者的 gate-and-retreat 生命週期（只客製過不了 gate 的環節；generic 重新過 gate 就退回） |
| **Harness engineering / 過度 vs 不足設定**（aipatternbook.com/harness-engineering） | 🟡 社群文件 | 「**Under-configuration 與 over-configuration 以不同方式失敗**：薄 harness 產出通用、使用者受挫；厚 harness 產出僵化、維護債，harness 自己變成一個專案。」直接支撐「只客製失敗環節」為 sprawl 的解方 |
| **Immutable / frozen config for concurrency**（Working With Ruby "Thread-safety and Immutability"、Python `dataclass(frozen=True)`、C# Frozen Collections 等綜整） | 🟡 多來源綜整 | 「多執行緒可安全存取不可變物件、不需鎖」；「啟動時建好、存 singleton，不要 per-request 重建」；⚠️「**淺層 freeze 不夠**，內層可變就破功」。**支撐**：frozen `KGConfig` → 一個 process 服務多 KG 時 concurrency-safe。**R3**：`KGConfig` 必須 deep-frozen（巢狀 dict → frozen） |
| **多租戶 SaaS per-tenant 設定**（Clerk、Brocoders、Make IT Simple 等 2026 guides） | 🟡 業界 guide | 「SaaS 獲利的紀律是**把客戶需求變成 config 而非 code 分支**」；客製只該有三類：**settings（旗標/上限/流程選項）、theming、extension points（webhook/API）**。直接支撐本設計「客製三強度：param-override > capability-toggle > code fork（要罕見且顯眼）」 |

## E. 尚未取得全文 / 待深讀

- [ ] Czitrom 1999 PDF 是掃描版、程式無法抽文字 —— citation 已從 tandfonline 查證，若第五章要引其 case study 數據需人工讀圖
- [ ] DSPy MIPROv2 論文（Opsahl-Ong et al. 2024，arXiv:2406.11695）—— 若之後要做「自動 per-stage 優化」再補
- [ ] OmegaConf merge 語意的邊角（list 併法、struct mode、插值 resolver）—— 實作 `ConfigLoader` 時對照官方文件

---

## 各文獻/專案在本設計中的定位總結

1. **模式非新創、非高風險**：分層 config 組合（Hydra 10.6k / OmegaConf / Kustomize 12k / spaCy）與可插拔多來源（Dynaconf 4.3k / pydantic-settings，後者本專案已用）都是**生產環境長期驗證**的成熟模式。本設計是這些模式在「per-KG 知識圖譜 pipeline」的套用，不是發明新機制。
2. **per-stage 評分閘控**：DSPy（37.8k）證明「對 metric 程式化優化每個 module 的 prompt/few-shot」是可行且有社群的方向；本專案先做人工版（掃參數 + gate），保留升級空間。
3. **穩定性**：主要風險是 config sprawl（R1）與 OFAT 盲於交互作用（R2）—— 兩者都有明確緩解（gate-and-retreat 生命週期、OFAT 只當篩選 + 事後 factorial 檢查）。frozen `KGConfig` 給多 KG 併發安全，但必須 deep-frozen（R3）。
