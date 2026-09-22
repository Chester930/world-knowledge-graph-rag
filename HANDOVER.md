# 跨 Agent 接續進度

> **適用對象**：Claude Code、Codex、Gemini CLI，以及其他接續本專案的 agent。此文件是目前進度的唯一權威交接來源；舊的 `HANDOVER_CODEX.md`／`HANDOVER_CLAUDE_CODE.md` 僅保留歷史脈絡。
> **最後更新**：2026-09-22

## 先讀這裡

接手前先執行 `git status -sb`、`git branch --show-current`、`git log -1 --oneline`，再讀本文件及下方報告。不要只依賴對話摘要或舊 handover。

### 工作目錄與分支

- 專案主要 checkout：`D:\Users\666\Desktop\world knowledge graph rag`，目前在 `master`，含使用者既有異動；不要在此 checkout 編輯、stage 或 commit 本任務檔案。
- 本任務工作區：`D:\Users\666\Desktop\world knowledge graph rag\.claude\worktrees\sdd-retrieval-comparison`。
- 工作分支：`worktree-sdd-retrieval-comparison`。
- **2026-09-20：使用者已明確授權，本分支已推送並與 `origin/worktree-sdd-retrieval-comparison` 同步**（推送時最新為 `b2c03da`，含先前 Codex 的3個本地 commit 一併推送）。此後的推送仍須取得使用者明確同意。請重新查 `git log` 和 ahead/behind，勿使用此段推算最新 SHA。
- 此前已推送的程式 commit：`a808391`，包含風險修復 `819472a` 與 source-scope Fact 檢索修正。
- 目前已有的根目錄 `CLAUDE.md` 與歷史 handover 有部分過時的架構／進度描述；本文件及報告57 §4.13、報告60 §1.4 優先作為目前狀態依據。

### 最近完成的階段

使用者已核准並完成 AGGR15／16／17 的 source-scope on/off ×3 K-arm A/B，以及固定文件範圍下 Fact-only `top_k=5/10/15/20` 掃描，並對 AGGR16 延伸至 top_k=35。實驗期間只讀取 Neo4j；沒有修改產品程式碼、圖資料或全域預設值。摘要與數據表已記入：

- [報告57 §4.13：scope A/B 與 Fact top_k 精準度掃描](docs/報告/57_檢索品質解耦評測與知識圖譜場景化角色SDD任務書.md#413-source-scope-ab-與-fact-top_k-精準度掃描2026-09-18)
- [報告60 §1.4：接續評估摘要與建議](docs/報告/60_Codex接續確認交接任務書.md#14-2026-09-18-檢索精準度最佳化評估)

### 2026-09-21 最新進度與下一階段（本段優先於下方所有段落）

**下一階段請直接讀 [報告62 下一階段任務書](docs/報告/62_下一階段任務書_檢索排名與條文擴充驗證.md)**，它設計成冷啟動可用（含環境陷阱、任務清單、預先宣告的採用規則、決策點）。摘要：

1. **凍結基準已完成**（報告57 §4.20）：K arm、42 題 12/42 達標（拒答事後重算 14/42）、跨文件題 0/13。**後續分析**（§4.21）：20 題檢索失敗的 35 個 gold span 只有 1 個真的沒抽到，17 個抽到但排名太後、14 個抽到但被拆碎，**重抽 KG 不是主要方向**。文獻與專案證據強度見 [報告61](docs/報告/61_做法與文獻來源查證報告.md)：沒有文獻能證明具體做法有效，論文定位應是「診斷 KG 在什麼條件下有／無增益」。
2. **凍結後產品行為程式碼沒有變更**（`git diff e178c4c HEAD -- services routers core models` 只有註解與一個預設為空的 `extra_refusal_patterns` 參數；題庫 hash 與凍結時一致），所以新候選可直接與凍結基準對照。
3. **同分支上的其他工作**（提交者同為 `Chester930`，無法分辨 session，**未經我審查**）：本地生成模型初篩（結論：暫不替換 `qwen2.5:7b`；條件與凍結基準不同，不可比較）、Embedding×KG×Chunk 協作架構討論稿（其「`HybridEvidence`／`PathTrace`」第一個工程任務與報告62 T0 方向一致）、補入先前 untracked 的實驗輸出，以及 **`master` 已合進本分支（`b1c620e`）**——因此下方第 6 項 (b) 的「先把 master 合進本分支」已完成，只剩依路徑拆分與使用者確認。
4. **推送須取得使用者明確同意**；**合併 `master` 前須逐項詳細確認**（使用者明訂）。
5. **報告62 T0 已完成（本分支未推送）**：opt-in `ChatRequest.include_retrieval_trace` 記錄檢索順位／分數／來源與實際進 prompt 的行，不改行為（1 題實跑與凍結基準逐項相同）。**重要發現**：基準 stage-2／SNR 以「檢索到的全部」計算；prompt 截斷門檻非單調（池 >35 時放寬到 35 行），使 T2（top_k=40）同時會縮減 BFS 名額——詳見報告62 §10。T1（`--k-top-k`）已完成。**T2（K1＝top_k 40）已完成並判定**（報告62 §12）：達標 12→14（淨增 2，p=0.75），穩定通過的 `57-DIST1/2` 退步、Type-E 退步 → **需更多證據，不建議設為預設**；退步題的 gold 皆在 prompt 內（生成階段失敗），新增題也非來自第 21–40 名 Fact。使用者已同意 D3 採用門檻（§11.1，評測前已寫定）。**§13 生成診斷後修正**：`57-DIST1/2` 的退步是評分器對逐字引用 vs 改寫的敏感度（實質答案相同，KG 缺全國性天數）、`57-AGGR18` 的新增是評分器漏抓同一個新舊法寫反的錯——**達標題數 ±2 屬於量測噪音**。**§14 量測工具稽核已完成（2026-09-22，標註者是模型、需使用者抽驗）**：評分器偽陰性下界 ≥11.8%（23/195，主因是改寫／近逐字被判 missing）、偽陽性下界 ≥4.0%（7/174，含新舊法歸屬寫反）；確定性規則 R（高重疊＋數字條號守衛＋否定詞守衛）在樣本內救回 18/23 偽陰性、誤翻 1/18，**T2 的 +2 結論對此穩定**（重判後仍 +2）。**現行評分器未改動**（改了會與凍結基準不可比）；**§14.6–14.9（2026-09-22）**：用 `granite4.2:3b`／`qwen3.5:4b` 盲審交叉比對——只是弱佐證（一致率 52.8%／69.0%）；保守下界改為偽陰性 ≥7.2%（14/195）、偽陽性 ≥3.4%（6/174），另有約 5 題需人工複核（`data/eval/scorer_audit_20260922/contested_for_human_review.json`）。gold span 掃描只發現 `57-DIST1/2` 是真缺陷（法規原文已核對：全國性＝二至五日）。評分器 v2 已離線重判（`data/eval/scorer_v2_20260922/`）：事後情境淨差 +2～+4、p 0.29–0.75，**不翻轉 §12**。待使用者裁示：是否採用 v2 定義當之後候選的比較基準、是否修改 `test_cases.json` 的 DIST1/2、人工複核清單。**跑 Ollama 思考型模型（Granite 4.2、Qwen3/3.5）務必 `think:false`，否則 content 為空且極慢。** 再談 K1b／T3。**§14.10（2026-09-22，使用者已同意）：題庫已修正**——`57-DIST1/2` 各補兩個必要 span（第2條「給予一至三日之特別休假」、第3條「給予二至五日之特別休假」，逐字取自 KG 條文，已核對原文）；兩份鏡像 sha256 同步為 `23f8c06f…`（**與 09-20 凍結雜湊 `404cde9f…` 不同，這是預期變更**）。之後任何用 `frozen_baseline_stage.py` 重跑舊 `20260920_frozen` 流程，`verify_frozen.py` 會如預期回報 bank hash 不一致，**不是環境壞掉**。09-20 的「12/42」歷史數字語意不變（仍是舊題庫下的結果），但**下次要做 T2/T3 或任何新候選評測，一律改用新題庫 `23f8c06f…` 當基準**，不可與舊數字直接相加減。

### 2026-09-22 報告62 §14 量測工具稽核收尾：A（v2評分器）／B（人工複核）已裁示

使用者已就報告62 §14.9 的待裁示事項拍板，詳見報告62 §14.11：**暫不採用規則R／v2評分器為預設**（保留當診斷工具；理由與後續處理原則見§14.11）；**人工複核7筆（4題）已全部裁決**——`57-DIST1/2` 因§14.10題庫修正已自動解決不必另判、`26-Q5`維持支持（但標記答案自相矛盾）、`57-AGGR19`推翻原判改判不支持（丟了「依前項第一款規定」限定條件）。評分器程式碼與凍結基準數字皆未變動。

下一步依先前排定的優先序（A/B → F → C → D/E → G/H）進到 **F：抽取粒度修復設計**——針對 §4.21 類別B「抽到但破碎／丟失限定條件」（35個gold span中佔14個、40%，最新人工複核的`57-AGGR19`也是同型案例）設計修復方案。

### 2026-09-22 F：抽取粒度修復設計已完成文獻查證與任務書撰寫（**尚未實作，待使用者核准**）

依專案既定流程（先查文獻與參考專案、記錄查證結果、未確定內容以報告形式儲存，核准後才進論文與程式碼），已完成：

1. **診斷**：用報告57 §4.21 的 `retrieval_failure_diagnosis.json` 真實 Fact 文字定位根因——`services/svo_service.py::_svo_prompt()` 規則7（要求把附加規定拆成獨立三元組，report18/19/20時期為修「遺漏」問題設計）遇到「共同條件→多個結果」的複合法規句時，條件與結果被拆進互不相干的三元組，任一筆單獨看都不完整。`57-AGGR19` 排名第1名仍判未命中，證明這不是排序問題。
2. **文獻查證**（新資料夾 `docs/參考文獻/37_三元組條件限定詞與超關係表示/`，已同步登錄 `docs/論文/02_文獻探討.md` § 3.1.3 三筆新條目）：Chen et al. Dense X Retrieval 的「去脈絡化」判準、Galkin et al. (2020) StarE 超關係KG／qualifier、Krótkiewicz et al. (2026) 法律規範顯式範圍表示（摘要層級，全文付費牆未取得）。**誠實結論：沒有文獻直接研究這個具體取捨，僅能佐證「限定條件不該被丟」的大方向在相鄰領域被認真對待，不構成有效性證明**。
3. **任務書**：[報告65：抽取粒度修復設計SDD任務書](docs/報告/65_抽取粒度修復設計SDD任務書.md)——三個候選方向（A：修prompt條件複述進verb，成本低，建議優先；B：Fact補句子層級provenance＋檢索時撈同句兄弟Fact，成本中高，需schema+backfill；C：顯式qualifier/超關係表示，成本最高，僅記錄不評估實作），驗證計畫是**定向重抽**（`scripts/kg/reextract_chunks.py`，非全量重抽），不動全域設定。
4. **待使用者核准**：是否採用方向A並執行驗證計畫（報告65 §4/§5）；核准前不得修改 `_svo_prompt()` 或執行任何重抽。

### 2026-09-22 方向A已核准：prompt 修正已落地，定向重抽驗證進行中（背景），後續任務已交付 Codex（**須等驗證完成才可開始**）

1. **使用者已核准方向A**。`services/svo_service.py::_svo_prompt()` 新增**規則10**（commit `35f95ab`）：拆解「共同條件→一個或多個結果」的複合法規句時，條件須複述進每一筆結果三元組的 verb；另涵蓋列舉前言本身漏數量的情形（`18-Q5`/`57-DIST1/2` 同型）。全套 pytest 1043 passed。
2. **⚠️ 架構澄清（使用者要求，已補進報告65 §3.1）**：規則10目前**全域生效，非per-KG範圍**——`_svo_prompt()`（含規則1-10）仍是單一寫死函式，`KGConfig`／domain pack 機制尚未涵蓋抽取端 few-shot（報告33 §6「3b步」已知缺口）。**通用/特定的正確關係應是「共用骨架不動＋具體例句當參數注入」，不是每個 domain 整份複製 prompt**——已落地為[報告66](docs/報告/66_SVO抽取少樣本領域包參數化SDD任務書.md)，交付 Codex，任務書含完整技術方案（`KGConfig.domain.svo_fewshots` 新欄位、`_svo_prompt()` 動態編號組裝、`extraction_worker.py` 比照 `routers/agent.py:1516-1534` 既有 domain_pack 讀取模式）。**Codex 須等下一項的定向重抽驗證完全結束後才能開始**，因為兩者都會動 `services/svo_service.py`，同時進行會互相汙染結果判讀。
3. **✅ 定向重抽驗證已完成（2026-09-22）：好壞參半，判定「未達驗證通過」**，詳見報告65 §6-7。對 KG#4（`236903cf-055a-40a8-8923-b9d06601f3b7`，正式資料）9個chunk定向重抽，9/9 completed：
   - **4/9乾淨修復**（`57-AGGR7`教科書等級、`57-AGGR19`舊法、`D0080015` c3/c4天數回補）——證明規則10對「單一條件→結果」結構有效。
   - **原始診斷主要標的（`57-AGGR19`新法·勞工側，c85，先前排名第1名仍未命中的那筆）依然未修復**，且新增簡體字混入（「准用」「基准法」，既有防護`_to_traditional_selective`未攔到）。
   - **`57-CANARY5`（c101）嚴重退步**：重抽前雖破碎但仍帶部分條件細節，重抽後坍縮成1筆完全無條件的裸陳述，比修改前明顯更差。
   - `57-AGGR8`（c18）出現疑似角色互換的無關雜訊（中央主管機關→雇主）。
   - **判定**：方向A「部分驗證，需加固後才能推廣」，不是「驗證通過」。
5. **✅ 使用者已裁示選2+4，且已執行完成（commit `860654a`／`c190296`）**：
   - **選項4（確定性防護閘門）**：`services/svo_service.py::_fix_known_simplified_compounds()` 逐詞修正已知易錯簡體詞組（准用→準用、基准法→基準法），補救 `_to_traditional_selective()` 逐字白名單的結構性盲點；`scripts/kg/reextract_chunks.py` 新增重抽前後 `fact_text` 總字數比對，低於門檻（預設70%）印警告並寫入 `content_loss_flags.json`，不自動阻擋/回復。全套 pytest 1048 passed。
   - **選項2（修復c101）**：`57-CANARY5`（N0050031 c101）已修復——不是回復（fork的before.json因腳本bug被覆蓋，且重建的S-V-O字串不足以可靠回灌）也不是盲目重試（自動重抽只補回1/3條件），而是核對 `svo_index.json` chunk 101 的權威原文，透過與正常抽取相同的 `merge_triples_to_graph()` 管線寫入一筆完整自足的修正三元組（三個條件+結果全保留），已查詢驗證、無孤兒資料殘留。誠實標註為**人工修正、非LLM抽取結果**，`rel_type` 用 `RELATED_TO` 安全兜底。
   - **未處理項（明確不在本次範圍，需另外確認）**：`57-AGGR19`（c85）的簡體字混入尚未retroactively修補既有資料（新guard只對未來抽取生效）；c85的條件分裂問題本身（報告57/62最初診斷的主要標的）仍待規則10加固或方向B/C；c18的角色互換雜訊維持現狀。
   - 詳見報告65 §8。
6. **⚠️ 報告66（`svo_fewshots`領域包參數化）現況**：使用者尚未明確指示交付 Codex，**不要在沒有使用者明確指示的情況下直接把報告66交給Codex執行**。方向A目前判定仍是「部分驗證，需加固」（見上），若要繼續深化規則10（涵蓋多條件並列結構）建議先於報告66之前處理，避免 Codex 在報告66 T1-T6 過程中又要跟一個持續變動的 `_svo_prompt()` 打架。

### 2026-09-22 T-B：生成模型與接地核對 judge 解耦設計評估（已完成，僅評估未新增接線）

本節是依使用者要求對 T-B 的設計評估與成本盤點；本輪沒有修改
`routers/agent.py::chat()`、`services/verification_service.py` 或其他正式行為。
盤點後發現：T-B 的基本解耦能力其實已在既有提交 `ce84a77`
（2026-09-08）落地，本次工作不是再做一次接線，而是確認目前接線範圍、預設行為與採用成本。

#### 1. 現況呼叫鏈與目前實際行為

目前的路徑如下：

1. `routers/agent.py::chat()` 先以 `get_llm_provider()` 取得生成端 provider
   （目前預設 `qwen2.5:7b`），再以
   `get_judge_llm_provider(llm_provider)` 取得接地核對 provider；目前位置約為
   `routers/agent.py:1510-1515`。
2. `chat()` 將兩者分開傳入 `_generate_from_context_lines()`：
   `llm_provider` 用於初稿串流、分解式生成、限制性重生成與定向修正；
   `judge_llm_provider` 用於 grounding 核對。helper 的雙 provider 介面約在
   `routers/agent.py:1256-1263`。
3. helper 目前有三個 grounding 核對點，均傳入 `judge_llm_provider`：初稿核對約
   `routers/agent.py:1328-1329`、限制性重生成後複核約
   `routers/agent.py:1422-1423`、列舉完整性重生成後複核約
   `routers/agent.py:1436-1437`。
4. `services/verification_service.py::verify_fact_grounding()` 本身只接受一個
   provider 參數，並在約 `:148-150` 呼叫該 provider 的 `generate_json()`；它不會
   再自行取得或建立模型。因此「生成者＝核對者」與否是呼叫端 provider 選擇問題，
   不是 verification service 內部再拆分的問題。

目前設定與 fallback 語意已存在於 `core/config.py:16-21`、
`core/providers/factory.py:91-124`：

- `JUDGE_LLM_PROVIDER` 未設定（預設 `None`）時，`_judge_llm=None`，
  `get_judge_llm_provider()` 回傳生成端 provider；所以現行預設仍是同一顆模型自我核對，
  完全保留舊行為。
- 設定 `JUDGE_LLM_PROVIDER` 後，啟動時用同一個 `_make_llm_provider()` 建立獨立的
  `_judge_llm` 實例；可用 `JUDGE_LLM_MODEL` 覆蓋 judge model。`chat()` 會實際把
  grounding 核對改送至該獨立實例，生成與重生成仍留在生成端 provider。
- 因此，T-B 已具備「不同 provider／不同模型」以及「同 provider、同模型但不同
  Python provider 實例」兩種部署方式；後者只解除物件／路徑共用，不會消除同一模型
  權重與判斷偏差的相關性。

#### 2. 與離線 harness 的對照

離線 harness 已採相同的角色分離慣例：

- `scripts/eval/run_rq1_comparison.py:648-654` 初始化後分別取得 generator 與 judge，
  並在 `:659-664` 對正式評測禁止 shared judge（除非明確 `--allow-shared-judge`）。
- 每題的生成呼叫在約 `:259-263` 傳 `llm_provider=counting`、
  `judge_llm_provider=judge_counting or counting`；後續 lineage、AtomicScorer 等
  語意核對也沿用同一 judge。這與 `chat()` 的 provider 角色分工一致。
- 差異在於 harness 對「正式比較」強制不同 judge；正式 `chat()` 為了向後相容沒有
  這個強制閘門，未設定時仍允許 shared judge。這是部署策略差異，不是介面能力缺口。

#### 3. 設定方案與建議

不建議再新增 `verification_judge_provider`／`verification_judge_model` 這組重複設定；
現有 `judge_llm_provider`／`judge_llm_model` 名稱已涵蓋接地核對用途，且已被 factory、
router、測試與 harness 使用。三種操作模式如下：

| 模式 | 設定 | 可回答的問題 | 代價／限制 |
|---|---|---|---|
| 現行相容模式 | 不設 `JUDGE_LLM_PROVIDER` | 保持目前生產行為 | 仍有生成者自我審查的循環性 |
| 同模型獨立實例 | `JUDGE_LLM_PROVIDER=ollama`，model 同生成端 | 驗證角色與 provider 路徑是否正確分離 | 不是真正的模型多樣性，不能排除同模型偏差；通常沒有第二組權重 |
| 獨立 judge 模型 | 設定 provider，必要時設 `JUDGE_LLM_MODEL` | 直接測試「生成端與核對端不同模型」是否降低誤判／限制性重生成 | 可能多載入一組模型，增加 VRAM、模型切換與延遲風險 |

T-A 新增的 `OLLAMA_LLM_THINK` 目前是 Ollama 共用設定；若未來要讓生成端與 judge
各自使用不同 thinking 策略，還需另加角色級設定（例如 judge 專用 think），但這不屬
本輪 T-B 評估，也不應在沒有配對實驗前自行新增。

#### 4. 成本與測試影響估算

- **程式改動成本**：T-B 基本能力已完成，追加改動為 0 個正式程式檔。若從尚未有
  解耦能力的版本重做，實際範圍是 `core/config.py`、`core/providers/factory.py`、
  `routers/agent.py`、`tests/core/test_providers_factory.py`、
  `tests/routers/test_agent.py` 五個檔案；現有提交已包含這些變更與回歸測試。
- **呼叫數與延遲**：切換成獨立 judge 不會自動增加 LLM 呼叫數；每次 grounding
  pass 原本就有一次 `generate_json()`，若觸發重生成，原本也會再複核一次，列舉
  guard 另有既有複核路徑。變的是 judge 模型的單次速度與判定結果。若 judge 判定
  差異使重生成率上升，端到端延遲才會額外上升。
- **記憶體／載入**：同一 Ollama 模型的獨立 Python provider 物件本身成本很小；若
  judge 是另一模型，Ollama 可能同時保留兩組權重，也可能因 VRAM 不足反覆卸載／重載，
  造成明顯延遲。這是目前最主要的運行成本，尤其本專案已有 Ollama 記憶體壓力紀錄。
- **測試影響**：現有 `tests/core/test_providers_factory.py` 已覆蓋 fallback、獨立
  judge 實例與 model override；`tests/routers/test_agent.py` 已驗證生成走 generator、
  grounding 走 dedicated judge。若未來改動預設行為，至少要新增 shared／dedicated
  兩模式的 chat 回歸測試，並重跑完整 pytest；本輪沒有改正式程式，所以不需新增測試。
- **觀測成本**：factory 已記錄 judge provider/model；harness 也把 generator/judge
  provider、model、judge calls 寫入 record。正式 chat 若採用獨立 judge，建議後續補記
  judge identity、grounding pass、regeneration 次數與延遲，否則很難判斷改善來自模型
  能力還是只來自不同重生成率。

#### 5. T-B 結論與後續決策建議

T-B **技術上可行且基本接線已完成**；目前真正尚未決定的是是否在正式 `chat()` 環境
設定 dedicated judge，以及要選同模型實例還是不同模型。建議不要把「已能配置」直接當成
「已證明有效」：若要排除 self-judge 放大因素，應固定生成端 `qwen2.5:7b`、題庫、
檢索 context、timeout 與 `think:false`，只做 shared judge vs dedicated judge 的配對
比較，至少記錄 grounding 判定差異、regeneration rate、最終 Atomic Accuracy、拒答／
模糊拒答率、端到端延遲與 judge model load 次數。

因此，本輪不接線、不更換生產模型，也不執行 T-C；使用者可在確認這份評估後，直接以
現有 `JUDGE_LLM_PROVIDER`／`JUDGE_LLM_MODEL` 做受控比較，或另行提出角色級 thinking
設定與更細的 judge 失效分析。

### 2026-09-22 生成模型能力診斷與 Ollama `think` 參數缺陷（T-A 已完成；T-B 見上節）

**背景**：使用者要求確認「是否需要調整生成模型（目前 `qwen2.5:7b`）」。以下判斷依據報告62 §12–14（T2判定＋生成階段診斷＋量測工具稽核）與 `services/verification_service.py` 既有 docstring 記載的歷史 bug，非猜測。

**判斷結論**：

1. **已修復（與是否換模型無關的獨立程式缺陷）**：T-A 前曾確認 `core/providers/llm/ollama.py` 的 `generate()`／`generate_json()`／`stream()` 三個方法都沒有傳 Ollama `/api/generate` 的頂層 `think` 參數，污染了 2026-09-20 的本地生成模型初篩（`rq1_eval_results/local_model_screening_20260921.md`）。現已由提交 `2f2415a` 修復：`think=None` 不送 key，`think:false/true` 送至頂層；因此思考型模型初篩的舊結論仍不可信，但基礎設施缺陷已排除。
2. **尚未確認需要換掉 `qwen2.5:7b`**：現有唯一一次篩選（見上）條件跟凍結基準（K arm、42題、`qwen2.5:7b` generator/judge共用）不可比，又被(1)的bug污染，不能當「換或不換」的證據。同時，報告62 §13 診斷指出的生成端異常（`18-Q4` 限制性重生成變模糊拒答、`canary-P1` 罰鍰區間答錯）主因之一疑似是**接地核對機制用同一顆 7B 模型自我審查**（`services/verification_service.py` docstring 已記錄歷史 bug：qwen2.5:7b 常把問題原樣回貼，被自己的判官誤判成「未接地」觸發重生成）——換模型前應先排除「小模型自我審查放大雜訊」這個設計因素，否則換了模型也未必解決同一種現象。
3. **報告57 的既有教訓**：換生成模型是獨立於 KG 檢索評測的變因，一旦換了必須固定下來、在所有後續候選比較中維持一致，不可中途替換又互比（報告49/51 曾因此污染過結論）。

**交給 Codex 的任務（建議順序）**：

- **T-A（必做，S，純程式缺陷修復，與是否換模型無關；已完成）**：讓 `core/providers/llm/ollama.py` 支援 `think` 參數。
  - `OllamaLLMProvider.__init__` 新增 `think: bool | None = None` 參數；`generate()`／`generate_json()`／`stream()` 的 request payload 只在 `self._think is not None` 時加入**頂層**（不是 `options` 裡）`"think": self._think`——`None` 時完全不送這個 key，向後相容，不改變任何既有行為。
  - `core/config.py` 仿照 `ollama_llm_num_predict`（約第33行）新增 `ollama_llm_think: bool | None = None`（可用環境變數覆寫）。
  - `core/providers/factory.py::_make_llm_provider()`（約第22-29行，`case "ollama":` 分支）把新設定傳入 `OllamaLLMProvider(...)`。
  - 新測試比照既有 `tests/core/test_ollama_llm_num_predict.py` 的模式，新檔 `tests/core/test_ollama_llm_think.py`：驗證 `think=None`（預設）時 payload 不含 `think` key；`think=False`／`True` 時 payload 含對應值；`generate`／`generate_json`／`stream` 三個方法都要覆蓋。
  - 跑 `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py` 確認零回歸。
  - **不要**動 `_NUM_CTX`／`_TIMEOUT`／`_SEED` 等既有常數，也不要改變 `think` 未設定時的預設行為。
- **T-B（S，設計評估已完成；本輪不新增接線）**：現況已由既有 `ce84a77` 提供
  `judge_llm_provider`／`judge_llm_model` 與 `get_judge_llm_provider()`；未設定時仍與
  生成端共用，設定後 `chat()` 的三個 grounding 核對點改用獨立 judge。完整現況、離線
  harness 對照、成本與採用建議見上方「T-B：生成模型與接地核對 judge 解耦設計評估」。
- **T-C（M，需 T-A 完成後才有意義，非本次必做）**：用 T-A 修好的 `think:false` 重跑一次公平的模型篩選比較，比較對象至少含 `qwen2.5:7b`（現況）、`qwen3.5:4b/9b`、`granite4.2:3b/8b`。**必須對齊凍結基準的 K arm 42題（或已修正的新題庫 `23f8c06f…`）條件，不能沿用舊32題／不同judge／不同timeout**，否則結果一樣不可比。建議 T-A、T-B 完成並經使用者確認後才排入排程。

**明確不要做**：在沒有 T-C 這種公平比較之前，**不要**把生產 `chat()` 或評測 harness 的預設生成模型從 `qwen2.5:7b` 換掉。

### 2026-09-20 最新進度（本段優先於下方 09-19 段落）

1. **KG#4 抽取狀態已修復**：發現 `_process_one()` 內部吞例外、只標 `failed`，重抽腳本回報的「N/N 成功」不可信；KG 曾有 10 failed＋2 pending chunk（N0060041 §8/23/24/25/33/34、N0050031 §69/84/85/86、N0030006 chunk 3/8）。已用新工具重跑，12/12 首次即 `completed`，Fact 由 44 增為 82 筆，佇列現為 3307/3307 `completed`。詳見 [報告57 附錄C](docs/報告/57_附錄C_KG重抽來源清單與失敗chunk盤點.md)。**先前「終止條件比較子題抽取品質差」「請假規則 §3/§8 漏抽」的結論不成立**，已在報告57 §4.6 與論文 3.1.3§b 更正。
2. **新工具**（皆唯讀或讀回真實狀態）：`scripts/kg/reextraction_manifest.py`（列出被重抽的 chunk 與非 completed 的 chunk）、`scripts/kg/reextract_chunks.py`（重抽後讀回佇列狀態、失敗自動重試、保留日誌）。**今後重抽務必用後者或事後跑前者確認全為 `completed`。** 另從 `reextract-v2` 挑入 `claim_next_pending()`（原子認領）。
3. **兩條抽取分支互補**：抽取守衛（`_LEAVE_TYPE_FAMILY`、「等級」單位、風險三級）只在本分支；drain 工具在 `reextract-v2`。第5–9組 targeted 重抽當時是從 `reextract-v2`（`a72cbaa`）執行，**不含**這些守衛。不要整支互相 merge。
4. **題庫 65 題（verified 46）**：新增 `57-AGGR18`（新舊法認定機構寫反時 Atomic Accuracy 仍 100%）與 `57-AGGR19`（預告規定新舊法實質相同）。**發現原子評分不檢查歸屬**，故只為 AGGR18 依實際觀察到的錯答加了一條 `role_mismatch` 規則（子字串、高精確度低召回，pilot）與回歸測試。詳見報告57 §4.19。
5. **重測 `57-AGGR5`/`57-AGGR6`**（Fact 補齊後，n=1）：仍 0%，檢索失敗型態未消失；但同時經過 `a808391`，不可單獨歸因。報告57 §4.6 已標註。
6. **仍待決定**：(a) 擴大 scope audit 規則到更多題——規則應來自實際觀察到的失敗答案，且會改變題庫雜湊，須先與本文件記載的 matched-v2 對照協調並凍結題庫快照；(b) 合併 `master` 的方式——建議先把 `master` 合進本分支解掉兩份文件衝突（論文第3章、文獻查核表），再**依路徑**拆成「評測基礎／抽取守衛／`chat()` 行為變更（`a808391` 風險最高）／文件與論文」四塊，不要整支合併；(c) 主體/子句 grounding guard 設計討論（問題定義須涵蓋抽取後的實體去重階段）。
7. **協作注意**：本工作目錄由多個 agent 共用，**未 commit 的檔案會被其他 agent 的 `git add` 夾帶進他們的提交**。開工前先看 `git status`／`git log`，改完盡快 commit，並勿改動已被對照實驗使用的題目文字（例如 `57-AGGR16`，它有題庫雜湊比對與 `answer_scope` 規則）。

8. **✅ 凍結基準評測已於 2026-09-21 完成，凍結解除**：42 題最終 12 題達標（28.6%）、Context Recall 68.3%、Type-C 跨文件題 0/13。結果、限制與已確認的兩個評分器盲點（拒答關鍵字漏判、不檢查歸屬）見 [報告57 §4.20](docs/報告/57_檢索品質解耦評測與知識圖譜場景化角色SDD任務書.md)，資料與續跑紀錄在 `data/eval/baseline_runs/20260920_frozen/`（附錄D）。**後續分析（§4.21）**：拒答事後重算 14/42（敏感度分析，凍結正式數字仍為 12/42）；20 題檢索失敗的 35 個 gold span 只有 1 個真的沒抽到，17 個是抽到但排名太後、14 個是抽到但被拆碎或丟限定條件、2 個被種子錨定的範圍排除——結論是**重抽 KG 不是主要方向**。條文層級擴充（同條文兄弟 Fact）是尚未驗證的假說。**日後任何候選修法與此基準對照時，仍須以該凍結條件（程式碼 `e178c4c`、題庫 `404cde9f…`、Windows Ollama 0.34.2）為準，不可與其他來源混比。** 歷史說明：對 42 題合格題（65 題中 verified 46、其中 4 題 wording 標記為未逐字複核而被排除）做 K arm 基準。凍結資訊：程式碼 commit `e178c4c`、題庫雜湊 `404cde9f…`、KG 16826 筆 Fact 且佇列 3307/3307 completed、qwen2.5:7b／bge-m3、範圍為 23 份 gold 文件的聯集。**凍結期間請勿**：修改 `data/eval/test_cases.json`、改動 `services/`／`routers/`／`scripts/eval/` 的行為程式碼、重抽或修改 KG、同時使用 Ollama（會拖慢並污染延遲，也曾因記憶體壓力中止過背景工作）。重複次數採品質門檻式規則（`scripts/eval/adaptive_repeat.py`）：達標＝無錯誤且 `is_perfect` 且 scope audit 通過；只在結果尚不能判定時才補跑，最多3次，並抽查約25%的單次通過題。結果與解除凍結會記在報告57 §4.20。

### 2026-09-19 最新進度（09-19 段落，被上方 09-20 段落部分取代）

1. **同版本 baseline 校正完成**：在目前 worktree HEAD `8afb1e5` 重新跑 dense `top_k=20`，AGGR15/16/17 各 3 次，9/9 完成、零 harness error。中位數為：AGGR15 Recall/Accuracy 100%/50%、SNR 10.54%、254 tokens；AGGR16 75%/50%、8.65%、265 tokens；AGGR17 100%/100%、5.10%、236 tokens。這組數字取代舊 main HEAD `682917d` 的 scope-on baseline 作為後續比較基準。
2. **候選與組裝路徑唯讀追蹤完成**：AGGR16 單方法文件 Fact-only 目標 Fact 排第21；完整 chat 方法＋母法 scope 去重後排第24。18行上限分成14 Fact＋4 BFS，目標 Fact 與等價 BFS 第5名都被排除。Fact budget 與 BFS 名額是目前漏召回的組裝邊界。
3. **BFS 名額 pilot 完成**：程序內將 `min_bfs_slots` 4→5、固定18行、AGGR15/16/17 K-arm ×3。AGGR16 Recall仍75%、SNR 8.65%、265 tokens，Atomic Accuracy中位數由50%升至100%（2/3全答對）；AGGR15/17主要指標中位數不變。沒有修改產品程式、KG設定或 Fact 資料。
4. **Fact embedding rerank 完成**：top-25 Fact 候選先做同鍵 Fact 優先去重，再用既有 query embedding scorer 排序。AGGR16 目標 Fact rank 24→15，但 Fact budget=14；三次 Recall均75%、Atomic Accuracy 50%/75%/75%（中位數75%）、SNR 7.52%、306 tokens。
5. **一格 boundary-swap 診斷完成**：將 rerank 後第15名目標 Fact 換入第14名，擠出第三類3000人門檻 Fact；固定18行下三次 Atomic Accuracy均100%，但 Recall仍75%、SNR 7.52%、306 tokens。這是上界型診斷，不是正式規則。
6. **gold 外主張風險閘門完成**：新增 deterministic 離線檢查，審查 AGGR15/16/17 的題目範圍外主張與條件錯置。原子正確且無風險通過數：current dense 1/9、BFS slots 5 3/9、Fact rerank 2/9、boundary-swap 0/3。boundary-swap 三次都加入500人門檻，並把第二類500人條件寫成「專責」；評分器原本不會扣這類 gold 外錯誤。
7. **正式狀態**：以上全部是 offline pilot／diagnostic。沒有把 rerank、boundary-swap、風險閘門接入 `chat()`，沒有修改全域 `top_k`、scope filter、Hybrid、`source_doc_cap`、BFS 預設名額、題庫或 Neo4j。報告57 §4.14–§4.15、報告60 最新段落已同步記錄。
8. **評測契約欄位化完成**：`TestCase` 新增 `answer_scope`、`required_claims`、`claim_audit_rules`；AGGR15/16/17 已填入規則。新增 `services/claim_scope_auditor.py`，RQ1 runner 每筆輸出新增 `scope_audit`。兩份題庫鏡像（`data/eval/test_cases.json`、`docs/附錄A題庫.json`）已確認相等。這是 offline evaluation infrastructure，不會影響正式 `chat()`。
9. **scope audit 基準與多題 boundary-swap 完成**：K-arm baseline、top-25 rerank no-swap matched control、top-25 boundary-swap 各9筆，全部零 harness error/timeout。只有 AGGR16 的必要 Fact 正好在 rank15／budget14，三次交換均移到rank14；AGGR15目標在rank5／budget16、AGGR17在rank1／budget14，兩題均不交換。AGGR16 Atomic Accuracy在 matched control→swap 為75%→100%，Recall維持75%、SNR與tokens不變，但 scope audit仍0/3通過，三次答案都留下500人適用條件／管理角色錯置風險。AGGR17的scope audit由baseline 1/3升為top-25 control 3/3，並非swap造成。細節見報告57 §4.17與報告60 §1.5；所有組別共用 generator/judge，僅屬 pilot。
10. **無逐題人工審查的自動採用判定（matched-v2）**：新增 `scripts/eval/compare_scope_audit_runs.py`，核對 manifests、資料雜湊、模型設定、arm與run編號，自動彙總 Atomic Accuracy、Context Recall、SNR、scope audit並產生 GO/NO-GO JSON。control與boundary-swap重跑各9/9，題庫雜湊相同（`46b7…a035`）；AGGR16 Atomic Accuracy由control 75%升至100%，Recall仍75%、SNR仍7.52%、scope audit仍0/3，AGGR15/17沒有因swap改善，故候選為NO-GO。dense baseline重跑仍是不同題庫雜湊（`a638…bae2`），完整三組比較不可用。詳報告57 §4.18、報告60 §1.6；63題只有3題有自動範圍規則；比較器6/6、auditor 3/3，合計9/9 targeted pytest通過；完整pytest未重跑。

### 本機分支與未提交異動快照（2026-09-19）

以下為本機 `git status`／本機 remote-tracking refs 的觀察結果；尚未執行 fetch，遠端追蹤 refs 未必反映伺服器最新狀態。

| Worktree | 分支／commit | 相對上游／主要分支 | 工作樹狀態 |
|---|---|---|---|
| 主要 checkout | `master` `682917d` | 與本機 `origin/master` 相同 | 有 1 個修改文件及 2 個未追蹤文件；視為既有使用者異動，不要納入本任務 commit。 |
| 檢索比較 | `worktree-sdd-retrieval-comparison` 最新為 scope audit 自動 gate 本地 commit | 2026-09-20 已推送，與 `origin/worktree-sdd-retrieval-comparison` 同步 | 11個明確選取的 schema、scope auditor、比較器、測試、題庫與報告檔已提交；多個未追蹤 scratch runner／評測輸出仍留在工作樹，沒有 stage。 |
| KG 重抽 | `reextract-v2` `a72cbaa` | 有本機 remote ref `origin/reextract-v2` (`0dc579c`)，但尚未設定 tracking upstream；相對該 ref ahead 6／behind 0。相對 `origin/worktree-sdd-retrieval-comparison` ahead 16／behind 167；相對 `master` ahead 16／behind 119。 | tracked 工作樹乾淨；12個未追蹤檔案（drain／修復／重抽 runner、pilot 與 baseline embedding），不屬於檢索比較任務，勿移動或清除。 |

（2026-09-19 快照，已於 09-20 推送）檢索比較分支當時有3個本地 commit：`5893a65`、`8afb1e5` 與 scope audit 自動 gate commit。該功能提交經兩組 targeted pytest 共9/9通過。臨時 runner 與 `rq1_*` 評測輸出仍未提交，先保留原地，等確認保留價值後再分類。比較分支相對 `master` 為 ahead 52／behind 1；不可直接把整條分支合併進 `master`，應先按主題拆分評審。`reextract-v2` 對應遠端 ref 已存在且本地比該 ref 多6個 commit，但 tracking upstream 尚未設定；它與比較分支的歷史大量分歧，不應整支互相 merge/rebase。任何 push、merge、rebase、reset 或 branch delete 均需在核對目標與差異後再做。

### 關鍵結果與解讀限制

| 題目 | scope off：Recall／Accuracy／SNR／tokens／K 延遲中位數 | scope on：Recall／Accuracy／SNR／tokens／K 延遲中位數 |
|---|---|---|
| AGGR15 | 100%／50%／18.17%／146／45秒 | 100%／50%／10.54%／254／35秒 |
| AGGR16 | 75%／50%／11.51%／197／216秒 | 100%／25%／9.97%／263／600秒 |
| AGGR17 | 66.7%／66.7%／6.21%／127／218秒 | 100%／100%／4.86%／246／524秒 |

- 三題各條件為3次完整 K-arm 問答；共用 `qwen2.5:7b` generator/judge，屬 pilot，`formal_evaluation=false`。延遲、答案正確率有模型與執行環境變異。
- Fact-only 單次掃描中，AGGR15／AGGR17 的 top_k=10 已由 semantic span judge 判定全數召回；相較 top_k=20，檢索文字分別少約42%／51%，SNR較高。這不是正式 end-to-end 結論。
- AGGR16 第二類「具中度風險」Fact 在範圍內第21名：top_k=20 未取回，top_k=25 才納入，top_k=35又開始納入第三類低度風險等其他內容。先擴候選再精煉，比直接把更多Fact送入context值得測試。
- Semantic judge 單次輸出有漏判與非單調情況：AGGR15 top_k=15判50%、top_k=20判100%；AGGR16 judge 漏判 top-20 原始清單中人工可辨識的第一類顯著風險 Fact。檢視原始 Fact 文字；不要把這些單次 judge 數字當正式 Recall。
- 逐字 exact-span 對自然語言化 Fact 全部判0，該表示法不適用作單獨品質分數；Fact-only表格的 Recall/SNR 使用與 RQ1 harness 同款 semantic span matcher。

### 已完成與下一步

1. **已完成**：scope audit 題庫欄位、AGGR15/16/17 K-arm ×3重跑、top-25 rerank matched control，以及多題 boundary-swap 診斷；結果仍未達正式接線門檻。
2. **下一步**：control/swap matched-v2 已完成，不需再重跑。優先固定相同檢索 context，離線測試 AGGR16 生成端條件完整性修正／拒答或再生成策略，control與candidate各×3後使用自動 gate；scope audit通過前不接入正式 `chat()`。若要比較 dense baseline，先凍結同一題庫快照並重跑全部組別，再逐步擴大更多已驗證題目的自動評估契約。
3. **接線門檻**：多題下 Recall、Atomic Accuracy、SNR與 scope audit 必須一起改善或不退步；目前不調全域 top_k、scope filter、Hybrid、source_doc_cap 或 BFS 預設名額。
4. **報告58/59**：報告58來源 Chunk 雙軌組裝仍是設計提案，待 Fact 精煉與風險評分穩定；報告59跨 KG 對齊仍等待跨 KG 使用案例與正反例黃金集。

## 實驗檔案與重現環境

- 原始 scope A/B 輸出：主要 checkout 的 `.claude/tmp/rq1_scope_ab_20260918_n3/`。
- Fact top_k semantic sweep：主要 checkout 的 `.claude/tmp/rq1_fact_topk_sweep_20260918_semantic/retrieval_results.json`。
- AGGR16 rank extension：主要 checkout 的 `.claude/tmp/rq1_fact_topk_aggr16_extension_20260918/retrieval_results.json`。
- 目前 worktree dense matched baseline：主要 checkout 的 `.claude/tmp/rq1_fact_ranking_20260918/current_dense_top_k20/`。
- BFS 名額 pilot：主要 checkout 的 `.claude/tmp/rq1_fact_ranking_20260918/bfs_slots_5/`。
- Fact rerank pilot：主要 checkout 的 `.claude/tmp/rq1_fact_ranking_20260918/fact_side_embedding_rerank/`。
- Boundary-swap pilot：主要 checkout 的 `.claude/tmp/rq1_fact_ranking_20260918/fact_boundary_swap/`。
- Gold 外主張風險明細：主要 checkout 的 `.claude/tmp/rq1_fact_ranking_20260918/claim_risk_audit.json`；執行器為 worktree `_audit_aggr16_claim_risk_20260919.py`。
- 題庫欄位審查器：worktree `services/claim_scope_auditor.py`；單元測試為 `tests/services/test_claim_scope_auditor.py`。
- 新scope audit K-arm輸出：主要 checkout `.claude/tmp/rq1_scope_audit_20260919/k_baseline/`。
- 多題 no-swap matched control：主要 checkout `.claude/tmp/rq1_scope_audit_20260919/fact_rerank_control_3q/`。
- 多題 boundary-swap：主要 checkout `.claude/tmp/rq1_scope_audit_20260919/fact_boundary_swap_3q/`；診斷 JSON 每列代表一次 prompt 組裝呼叫，複合題或 grounding regeneration 可能令一次 harness run 出現多列。
- 評測包裝器：worktree `_run_fact_boundary_swap_3q_eval_20260919.py`；直接執行為 swap，帶 `--control` 為同候選池 no-swap 對照。
- scratch runners 位於工作分支 worktree 的 `.claude/tmp/`：`rq1_scope_control_runner.py`、`rq1_fact_topk_retrieval_sweep.py`、`rq1_aggr16_fact_topk_extension.py`。這些檔案被忽略，尚未納入 Git；輸出 JSON 也在主要 checkout 的忽略目錄，換機/乾淨 clone 後未必存在。
- 重新執行評測時，須以主要 checkout 作為 process CWD 以載入其 `.env` 與 `workspace`，但確保 Python import 的應用程式碼來自本工作分支 worktree。不要在兩個 checkout 間混用版本；先查看 scratch runner 的 `REPO_ROOT` 設定及 help。

## 驗證與工作樹注意事項

- `a808391` 的程式驗證：全套 pytest 976 passed；本輪只新增 scratch audit 與文件紀錄，audit script syntax check、`git diff --check` 通過，未重跑 pytest。
- 本輪新增 schema／auditor 變更後，focused auditor tests 3/3 通過；harness failure tests 以工作區 `--basetemp` 重跑 2/2 通過；baseline/swap runner與評測程式 `py_compile` 通過。完整 pytest 尚未重跑。
- 多個既有 `rq1_*` ablation 目錄和 `_run_ablation_*.py` 在 worktree 為使用者既有未追蹤檔案，不要清理、移動或 stage。stage 檔案時逐一指定。
- 2026-09-20 使用者已授權並完成一次推送；之後新增的 commit 推送前仍須取得使用者明確同意。

## 相關設計文件

- [報告57：檢索品質解耦與場景化角色](docs/報告/57_檢索品質解耦評測與知識圖譜場景化角色SDD任務書.md)
- [報告58：來源 Chunk 提領與雙軌上下文組裝](docs/報告/58_圖遍歷端到端關聯Chunk提領與雙軌上下文組裝SDD任務書.md)
- [報告59：跨 KG 實體對齊與全域語意導航](docs/報告/59_跨KG實體對齊與全域語意導航設計概念記錄.md)
- [報告60：Codex 接續確認任務書](docs/報告/60_Codex接續確認交接任務書.md)
- [報告62：下一階段任務書（檢索排名與條文擴充驗證）](docs/報告/62_下一階段任務書_檢索排名與條文擴充驗證.md)
- [報告65：抽取粒度修復設計SDD任務書（F，方向A已核准並落地，定向重抽驗證背景執行中）](docs/報告/65_抽取粒度修復設計SDD任務書.md)
- [報告66：SVO抽取少樣本領域包參數化SDD任務書（交付Codex，須等報告65驗證完成才開始）](docs/報告/66_SVO抽取少樣本領域包參數化SDD任務書.md)
