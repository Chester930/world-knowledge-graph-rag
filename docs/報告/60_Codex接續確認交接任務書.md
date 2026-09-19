# 60 Codex 接續確認交接任務書（Handover Document for Codex）

> **建立日期**：2026-09-18  
> **交接對象**：CODEX / 接續工程師  
> **專案路徑**：`d:\Users\666\Desktop\world knowledge graph rag`  
> **Worktree 目錄**：`d:\Users\666\Desktop\world knowledge graph rag\.claude\worktrees\sdd-retrieval-comparison`  
> **Worktree 分支**：`worktree-sdd-retrieval-comparison`  
> **前導任務書**：`docs/報告/57_檢索品質解耦評測與知識圖譜場景化角色SDD任務書.md`

---

## 0. 文件目的與交接定位

本文件專為接續工程師（或 Codex Agent）設計，提供清楚明確的接手脈絡、已完成項目、資料真值驗收點以及確認指令。

**重要定調**：
1. 本文件建立時的交接範圍是驗證 AGGR13-16；使用者於 2026-09-18 另行核准一項後續工作：修復第三類風險 Fact、增加回歸題 AGGR17、跑一題 pilot、記錄並 commit。
2. 這項後續工作已提交並依使用者明確同意推送至 `origin/worktree-sdd-retrieval-comparison`。目前遠端 HEAD 為 `a808391`，包含風險分級修復 `819472a` 與範圍檢索修正 `a808391`；本地與遠端 ahead/behind 為 0/0。
3. 使用者另核准 2026-09-18 後續最佳化評估：完成 AGGR15/16/17 scope on/off ×3，以及 Fact-only `top_k=5/10/15/20` 掃描與 AGGR16 排名延伸查證。結果記於報告57 §4.13；本階段沒有修改產品程式碼或 Neo4j 圖資料。

---

## 1. 專案現況與最新 Commit 狀態

### 1.1 原交接時 Git Commit 歷史
```text
f16c00e docs(報告57/論文05附錄A): 補完第8/9組候選§4.11/§4.12(AGGR13-16 harness真實結果)+附錄A擴充至62題/43 verified(AGGR3-16全題目)
d219493 docs+data(報告57任務C第8/9組候選): 私立就業服務機構許可雙來源授權鏈+職安衛管理辦法風險分級+新增4題(AGGR13-16)
```
以上是建立交接文件時的歷史狀態；後續風險分級修復與 AGGR17 回歸題已另行提交，當前版本請以 worktree 的 `git log -1`／`git status -sb` 為準。

### 1.2 異動檔案詳細清單
| 檔案路徑 | 異動性質 | 內容摘要 |
|---|---|---|
| `data/eval/test_cases.json` | 修改 | 新增 `57-AGGR13` ~ `57-AGGR16`，題目總數自 58 增至 62 題，`verified` 數自 39 增至 43 題。 |
| `docs/附錄A題庫.json` | 修改 | 同步更新，維持與 `test_cases.json` 之 byte-identical 鏡像關係。 |
| `docs/報告/57_檢索品質解耦評測與知識圖譜場景化角色SDD任務書.md` | 修改 | 撰寫完畢 `§4.11`（第8組候選）與 `§4.12`（第9組候選），填入 pilot_v2 真實 harness 評測數據，更新 `§5` 進度清單。 |
| `docs/論文/05_附錄A_測試題庫.md` | 修改 | A.2.5 表格自 14 題擴充至 30 題（收納 AGGR3-16 與 CANARY4/5），更新 A.3.3 `mechanism_tags` 分佈統計，狀態標為 🟢。 |

### 1.3 2026-09-18 後續修復與回歸題

- 根因：原文正確抽出的「具低度風險者」在 Entity 去重時，被一字之差的「具中度風險者」模糊合併。已為顯著／中度／低度風險標籤加入精確比對守衛，並保留抽取端的相鄰列舉錯配過濾。
- Neo4j：定向重抽 N0060027 §2 chunk 3 後重建 4 筆 Fact／來源引用；第一類＝顯著、第二類＝中度、第三類＝低度。移除一條先前留下的低度 surface form→中度 Entity 舊 `HAS_ENTITY` 別名；文件記錄為 completed。
- 題庫：新增 `57-AGGR17`，只測三類風險分級完整配對；三個 `exact_span` 逐字核對原文及修復後圖譜。`data/eval/test_cases.json` 與 `docs/附錄A題庫.json` 維持 byte-identical；總數63題、verified 44題。
- Pilot：K arm 1題×1次，輸出 `.claude/tmp/rq1_aggr17_risk_repair_pilot/`；preflight通過，Context Recall 66.7%、SNR 6.2%、Atomic Accuracy／Recall 66.7%，204.34秒。第二類「具中度風險者」未命中；共享 generator/judge，僅供 pilot，不是正式評測。
- 後續診斷：查明 compact enumeration「第一類、第二類及第三類事業」的字面種子只命中第三類；第二類中度 Fact 的原始 dense 排名第22，被 top-20 截斷。Neo4j 的四筆 §2 Fact／來源 chunk 仍正確。
- 修正：`chat()` 將已知明確／種子文件範圍傳給 Fact vector search，在 4× over-fetch 候選上先過濾來源，再去重／top-k；若候選全不在範圍內則保留舊 fail-open 行為。新增服務層範圍排序、zero-out 與 chat 傳遞測試。
- 範圍 pilot v2：輸出 `.claude/tmp/rq1_aggr17_scoped_fact_topk_v1/`；Context Recall／Atomic Accuracy **100%（3/3）**、SNR **4.9%**、延遲 **506.77秒**。共享`qwen2.5:7b` generator/judge，單次非正式pilot；context由127增至246 tokens，延遲高於首次pilot，勿視為正式效能結論。
- 驗證：完整 pytest **976 passed**；兩個受影響測試檔 **389 passed**；`git diff --check` 通過。此紀錄建立時，修正已提交為 `a808391`；之後已推送至 `origin/worktree-sdd-retrieval-comparison`，目前本地與遠端同步。

### 1.4 2026-09-18 檢索精準度最佳化評估

- **完整 K-arm scope A/B（AGGR15/16/17，各 on/off ×3）**：AGGR17 scope-on 的 Context Recall／Atomic Accuracy 皆100%，但 SNR 4.86%、context 246 tokens、K-arm延遲中位數524秒；scope-off 為 Recall／Accuracy 66.7%、SNR 6.21%、127 tokens、218秒。AGGR16 scope-on Recall 100%但 Accuracy 25%，scope-off為75%／50%；AGGR15兩種範圍設定均為Recall 100%／Accuracy 50%，scope-on SNR更低、context更大。結論是範圍過濾具題型差異，不能無條件當成全域預設優化。
- **Fact-only top_k sweep**：每題單次，固定解析後的來源範圍，不跑 BFS／答案生成；用與RQ1 harness相同的語意 span matcher，另記逐字診斷。AGGR15與AGGR17在top_k=10已由judge判定覆蓋全部gold，Fact文字分別比top_k=20少42%與51%，SNR較高；AGGR16在top_k=20尚缺第二類中度風險Fact，唯讀延伸確認它排範圍內第21，top_k=25才涵蓋四項必要內容。AGGR16 judge同時漏判top-20清單中可人工辨識的第一類顯著風險Fact；AGGR15 judge在top_k=15/20的Recall亦不單調。top_k=35才又帶入第三類低度風險相關Fact。故以上只作候選值探索，必須人工覆核原始Fact並以重複實驗驗證，不能作正式評測結論。
- **報告58（來源Chunk雙軌組裝）**：仍為設計提案，尚需 provenance／Manifest-aware resolver、ContextBundle、grounding與sources端到端支援及K vs K+C消融。本輪 Fact 檢索顯示加大上下文會降低SNR，先做 Fact-side 排序／精煉，再評估是否回補Chunk，避免把更多噪音送入prompt。
- **報告59（跨KG實體對齊）**：仍為概念記錄，尚無全域對齊資料模型與查詢實作。本輪題目都是單一KG內問題，未顯示跨KG導航的當前需求；等建立跨KG對齊正反例黃金集及明確使用案例後再排入。
- **接續 pilot 結果（2026-09-18）**：原建議的 dense selected-k（AGGR15/17 top_k=10、AGGR16 top_k=25）與 Hybrid RRF（top_k=20）已各跑 AGGR15/16/17 ×3，兩組皆 9/9 完成、零 harness error/timeout，詳報告57 §4.14。Dense selected-k 在 AGGR15/17 分別將 tokens 減少約42.5%／47.2%、SNR提高7.63／4.40個百分點，Recall／Accuracy不變；AGGR16則由 baseline Recall 100%跌至75%，SNR下降且連續三次漏掉第二類中度風險 Fact。Hybrid RRF 的 AGGR16 Atomic Accuracy由25%升至50%，AGGR15/17與baseline相同；但 AGGR16 Recall仍降至75%，只有AGGR15 SNR微升（10.54%→11.40%），AGGR16/17 SNR下降。不建議全域接線。未修改產品程式或Fact資料；Hybrid呼叫路徑可能惰性確保fulltext schema index。
- **修訂後下一步**：先用唯讀檢索對齊 Fact-only 掃描與完整 chat 路徑，追蹤 AGGR16 的 scope IDs、top-候選 Fact/score、來源過濾、去重及截斷；Fact-only 顯示中度風險 Fact 排第21且 top_k=25可納入，但完整 chat dense top_k=25與 Hybrid top_k=20皆三次漏失。釐清後再固定候選池測 query-aware reranking，評估是否同時保住必要span與SNR。暫不改全域 top_k、無條件啟用 scope filter／Hybrid／source_doc_cap，也先不做報告58 Chunk augmentation；報告59仍待跨KG黃金對齊集與明確用例。

- **2026-09-19 校正（取代上面 pilot 的 baseline 對照與下一步）**：目前 worktree HEAD `8afb1e5` 以 dense `top_k=20` 重跑 AGGR15/16/17 K-arm ×3，9/9 完成、零錯誤；每題中位數為 Recall/Accuracy、SNR、context tokens、延遲：AGGR15 100%/50%、10.54%、254、23.74秒；AGGR16 75%/50%、8.65%、265、50.38秒；AGGR17 100%/100%、5.10%、236、119.39秒。§4.13原scope-on baseline出自主要 checkout HEAD `682917d`，早於 `a808391` 的來源先過濾再top-k修正，不可用該舊數字判定 selected-k／Hybrid 的 Recall 退步。AGGR16唯讀追蹤結果：單方法文件 Fact-only 排第21；完整 chat 方法＋母法 scope 去重後排第24，初始20 Fact＋11 BFS候選被18行上限分為14 Fact＋4 BFS，目標 Fact 第24與等價 BFS 第5均未入 context。另以程序內 monkeypatch 將 `min_bfs_slots` 4→5、固定18行預算跑 K-arm ×3：AGGR16 Context Recall仍75%、SNR 8.65%、265 tokens，Atomic Accuracy中位數50%→100%（2/3次全答對、1/3次50%）；AGGR15/17的 Recall、Accuracy、SNR、tokens中位數不變。AGGR16延遲中位數升至108.37秒，僅記為本輪觀察值。下一步改測固定18行下的 Fact-side query-aware reranking／候選替換，讓第24名逐字必要 Fact 進 context；目前不調全域 top_k、scope filter、Hybrid、source_doc_cap 或 BFS 預設名額，報告58/59仍維持設計／待用例狀態。

本輪 scope/top-k 輸出位於主要 checkout 的 `.claude/tmp/rq1_scope_ab_20260918_n3/`、`.claude/tmp/rq1_fact_topk_sweep_20260918_semantic/`、`.claude/tmp/rq1_fact_topk_aggr16_extension_20260918/`。後續兩組 K-arm pilot 輸出位於 `.claude/tmp/rq1_fact_ranking_20260918/{dense_selected_k,hybrid_rrf}/`，執行包裝器為 worktree `_run_fact_rank_eval_20260918.py`。本次只更新本交接文件與報告57；測試程式碼未變，文件差異以 `git diff --check` 驗證。

2026-09-19 新增同版本 dense baseline 與 BFS名額 pilot 輸出於 `.claude/tmp/rq1_fact_ranking_20260918/{current_dense_top_k20,bfs_slots_5}/`；AGGR16追蹤輸出 `.claude/tmp/rq1_fact_candidate_trace_20260918.json`，runner 為 worktree `_run_bfs_slots_eval_20260919.py`。本輪產品程式、KG設定及 Fact 資料皆未修改。

2026-09-19 後續完成 Fact embedding rerank 與一格邊界交換診斷（取代上一段預定的 rerank 工作）。top-25候選經同鍵 Fact 優先去重與既有 query embedding scorer 排序後，AGGR16目標 Fact 紀錄由rank24升至15，仍超過14條 Fact 名額；K-arm ×3 的 Context Recall均75%、Atomic Accuracy中位數75%（50%／75%／75%）、SNR 7.52%、306 tokens、延遲中位數145.03秒。固定18行下再交換入rank14、擠出第三類3000人門檻 Fact，三次 Atomic Accuracy均100%，但 Context Recall仍75%、SNR 7.52%、306 tokens，延遲中位數47.54秒。目標 Fact 是自然語言化表述，不是 gold 逐字 span；答案三次皆加入500人門檻，且把僅適用於設有總機構時的第二類500人「一級管理單位」錯稱為「專責一級」。Atomic scorer未懲罰 gold 外錯誤主張，故不構成乾淨的品質提升。詳報告57 §4.14；下一步先增加額外主張與條件錯置評分，再以更多題驗證，暫不接線或修改全域設定。

新增結果位於主要 checkout `.claude/tmp/rq1_fact_ranking_20260918/{fact_side_embedding_rerank,fact_boundary_swap}/`；runner 為 worktree `_run_fact_side_rerank_eval_20260919.py` 與 `_run_fact_boundary_swap_eval_20260919.py`。統計依 `records.json` 及 `swap_diagnostics.json`；raw prompt/context lines 未保存。未修改正式產品程式、KG設定或 Neo4j Fact 資料。

2026-09-19 已把風險審查規則納入題庫契約：`TestCase` 新增 `answer_scope`、`required_claims`、`claim_audit_rules`，AGGR15/16/17 已填入題目範圍與條件／角色規則；新增 `services/claim_scope_auditor.py`，RQ1 runner 每筆輸出新增 `scope_audit`。`data/eval/test_cases.json` 與 `docs/附錄A題庫.json` 已確認鏡像相等（63題）。新增 auditor 測試 3/3 通過，harness failure tests 在工作區暫存目錄 2/2 通過。這是離線評測基礎設施，沒有改正式 `chat()`、AtomicScorer、KG或全域設定。

2026-09-19 依上述結論新增 deterministic gold 外主張／條件錯置閘門，離線審查既有 AGGR15/16/17 輸出：原子正確且無範圍風險的通過數為 current dense 1/9、BFS slots 5 為3/9、Fact embedding rerank 為2/9；boundary-swap 僅跑 AGGR16，為0/3。這不是替代 AtomicScorer 的正式指標，而是確認100% Atomic Accuracy不能掩蓋額外法律主張。規則與逐筆結果位於 `.claude/tmp/rq1_fact_ranking_20260918/claim_risk_audit.json`，執行器為 `_audit_aggr16_claim_risk_20260919.py`。下一步先把條件錯置規則整理成可審核題庫欄位，再擴充多題 boundary-swap；暫不接線。

### 1.5 2026-09-19 題庫 scope audit 與多題 boundary-swap

- AGGR15/16/17 K-arm ×3 已重新執行，9/9完成、零錯誤；三題 scope audit 通過數依序為3/3、0/3、1/3。新批次詳報告57 §4.17，包含 Recall、Atomic Accuracy、SNR、tokens及逐題風險結果。
- 另以相同 top-25 候選、Fact-first 去重、embedding rerank及18行context上限，跑 no-swap matched control與一格 boundary-swap，兩組各9/9完成。AGGR16 是唯一觸發交換的題：目標 Fact 排第15、Fact budget=14，交換後入第14並擠出第三類三千人門檻 Fact。AGGR15目標已在rank5/budget16；AGGR17目標已在rank1/budget14，兩題均不交換。
- matched control vs swap：AGGR16 Atomic Accuracy中位數75%→100%，Context Recall仍75%、SNR 7.52%、306 tokens不變；scope audit仍0/3通過，因答案繼續漏列500人規則的「事業設有總機構」前提，並把第二類500人管理單位寫成「專責」。AGGR15/17兩組結果相同；AGGR17 scope audit的3/3通過來自 top-25 rerank control，不能歸功於交換。
- 結論：固定名額交換在 AGGR16 有原子正確率訊號，卻未改善 Recall/SNR，也未消除法條範圍與角色風險；仍不符合接線門檻，不改正式 `chat()`、全域檢索預設或 Neo4j。三組使用共享 generator/judge，屬 pilot；診斷記錄按 prompt 組裝呼叫列項，複合題及重生可能令每個 harness run 產生多列。
- 輸出：主要 checkout `.claude/tmp/rq1_scope_audit_20260919/{k_baseline,fact_rerank_control_3q,fact_boundary_swap_3q}/`；runner為 worktree `_run_fact_boundary_swap_3q_eval_20260919.py`，`--control`執行 no-swap control。測試：scope auditor 3/3、harness failure tests 2/2通過，相關腳本 `py_compile` 通過；完整 pytest 本輪未重跑。
- **接續建議**：暫停正式接線討論；下一輪先擴大自動 scope audit 契約覆蓋的已驗證題目，再累積跨題配對樣本。報告58 Chunk雙軌組裝與報告59跨KG仍維持待用例／待驗證狀態。

### 1.6 2026-09-19 無逐題人工審查的自動離線判定

- 已新增可重跑的 `scripts/eval/compare_scope_audit_runs.py`，直接重評 §1.5 三組已保存輸出，不重跑生成、不做人工逐題審查。按題號與重複次數自動彙總 Atomic Accuracy、Context Recall、SNR、scope audit，完整結果見報告57 §4.18；新增測試6/6通過。
- 自動採用閘門判定 boundary-swap **NO-GO**：AGGR16 Atomic Accuracy雖由 matched control 的75%升至100%，Context Recall仍75%、scope audit仍0/3；AGGR15/17沒有因 swap 變好。最新 matched-v2 的 control 與 swap 均9/9完成且題庫雜湊相同（`46b7…a035`）；dense baseline 重跑仍為另一雜湊（`a638…bae2`），因此工具將 baseline comparison 標為不可比，沒有據此推論跨組變化。
- 題庫共63題，其中只有3題有 `required_claims`／`claim_audit_rules`，自動範圍判定目前限 AGGR15/16/17。此流程免除每一輪人工覆核，但評分依賴既有 gold 與規則，不能宣稱自動驗證了規則本身的法律正確性。
- **新接續建議**：matched control／swap 已重跑完成，兩者同資料集可直接比較；gate 仍因 AGGR16 scope audit 0/3 判 NO-GO。下一個有效離線實驗應固定檢索 context，測試生成端條件完整性修正／拒答或再生成，並用同 hash control/candidate 各跑×3後自動 gate。若需和 dense baseline 比較，先凍結單一題庫快照再重跑全部組別。擴大 scope 契約覆蓋前，保持離線，不改正式 `chat()`／全域預設。報告58與59仍維持待用例／待驗證。

---

## 2. 任務 C（AGGR1-17）與回歸題總覽

報告 57 任務 C 規劃之 9 組跨文件/聚合題材候選已全數完成 Stage 0 查證與 Stage 1 出題評測：

| 組別 | 題號 | 法規家族代號 | 主要 mechanism_tag | 核心特徵 |
|:---:|:---:|:---:|:---:|:---|
| 1 | 57-AGGR1, 57-AGGR2 | N0060022 (附表一) | `cross_doc_multihop`, `global_aggregation` | 特殊健檢頻率規則 |
| 2 | 57-AGGR3 | N0030006 + N0030001 | `global_aggregation` | 假別工資對照跨文組裝 |
| 3 | 57-AGGR4 | N0060041 + N0050031 | `cross_doc_multihop` | 職災新舊法認定銜接 |
| 4 | 57-AGGR5, 57-AGGR6 | N0060079 + N0050031 | `cross_doc_multihop`, `global_aggregation` | 重返職場補助辦法授權鏈與新舊法退休例外 |
| 5 | 57-AGGR7, 57-AGGR8 | N0090058 + N0090055 | `cross_doc_multihop`, `global_aggregation` | 中高齡就業促進辦法法源與措施清單 |
| 6 | 57-AGGR9, 57-AGGR10 | N0090025 + N0090001 | `cross_doc_multihop`, `global_aggregation` | 就業促進津貼雙授權鏈與三項津貼金額 |
| 7 | 57-AGGR11, 57-AGGR12 | N0030022 + N0030020 | `cross_doc_multihop`, `global_aggregation` | 勞退條例年金保險雙來源授權鏈與專戶提繳比率 |
| 8 | 57-AGGR13, 57-AGGR14 | N0090002 + N0090001 | `cross_doc_multihop`, `segmented_enumeration` | 私立就服機構寬窄不對稱雙授權鏈 + 3 級距人員配置 |
| 9 | 57-AGGR15, 57-AGGR16, 57-AGGR17 | N0060027 + N0060001 | `cross_doc_multihop`, `global_aggregation`, `segmented_enumeration` | 職安衛管理辦法授權長句 + 事業風險等級與門檻配對 + 修復後三類風險分級回歸題 |

---

## 3. 核心實驗結論與論文關鍵案例

### 3.1 核心成果：`57-AGGR15`（解耦評測的黃金證明）
- **實驗數據**（K arm，真實執行於 2026-09-18 10:54，`.claude/tmp/rq1_aggr13_16_pilot_v2/`）：
  - **Context Recall**：**100%**（檢索端完美召回所有法源條文）
  - **SNR（信噪比）**：**10.7%**
  - **Chain Completeness**：**100%**（推理鏈 100% 完整）
  - **Atomic Accuracy**：**0%**（最終答案 0 分）
- **根因確診**：Stage 3 LLM 生成端幻覺／平滑化。檢索端已將正解完整提供至 Prompt Context，但生成端未採用精準條號。
- **論文價值**：若無報告 57 之解耦三指標，本案例將被粗暴歸咎於檢索失敗。此案例直接佐證解耦框架之必要性與診斷精度。

### 3.2 抽取缺陷記錄（KG Extraction Defect）
- `57-AGGR16` 執行前於 Neo4j 稽核發現：N0060027 第三類事業風險等級被抽成「具中度風險者」（原文為低度風險），屬於相鄰列舉項數值複製誤植（累計第 7 個獨立案例，已記入報告 57 §3.1.3 與 §4.12）。當時`57-AGGR16`刻意避開第三類；2026-09-18完成修復後另以`57-AGGR17`涵蓋三類映射，K-arm pilot仍漏召回第二類中度span（詳§1.3）。

---

## 4. Codex 驗收與確認檢核步驟（Checklist）

請接手人員或 Codex 依下列步驟執行核實：

### 步驟 1：核對 Harness 評測數字
讀取 `.claude/tmp/rq1_aggr13_16_pilot_v2/summary.md` 與 `docs/報告/57_檢索品質解耦評測與知識圖譜場景化角色SDD任務書.md` 之 §4.11 / §4.12：
- [x] AGGR13: Acc 0%, Context Recall 33.3%, SNR 3.7%, Chain 50.0%
- [x] AGGR14: Acc 67%, Context Recall 66.7%, SNR 4.1%, Chain N/A
- [x] AGGR15: Acc 0%, Context Recall 100%, SNR 10.7%, Chain 100.0%
- [x] AGGR16: Acc 25%, Context Recall 75.0%, SNR 9.3%, Chain N/A
- [x] 整體（4題×1次）：Acc 22.9%, Context Recall 68.8%, SNR 6.9%, Chain 75.0%
- [x] AGGR17修復回歸pilot（K，1題×1次）：Acc／Recall 66.7%，Context Recall 66.7%，SNR 6.2%；漏召回第二類中度span，非正式評測。
- [x] AGGR17範圍過濾pilot（K，1題×1次）：Acc／Recall與Context Recall 100%，SNR 4.9%，context 246 tokens，延遲506.77秒；召回改善但context與延遲增加，單次非正式結果。

### 步驟 2：核對題庫與附錄 A 一致性
- [x] `docs/論文/05_附錄A_測試題庫.md` 之 A.2.5 表格包含 AGGR3 至 AGGR17。
- [x] 每題之 `mechanism_tags` 與 `scenario_type` 與 `data/eval/test_cases.json` 保持完全一致。
- [x] 題庫總數統計正確：Verified = 44 題，Unverified = 19 題，合計 63 題。

### 步驟 3：檢查報告 57 之結構完好性
- [x] 確認 `## 6. 使用者裁示結果` 僅出現一次（行號 526 附近），且下方子項目無重複段落。

### 步驟 4：執行推送（Git Push）
已於 2026-09-18 依使用者明確同意完成推送；推送後驗證本地與遠端 ahead/behind 為 0/0。該次推送指令如下，僅供歷史紀錄：
```powershell
git -C "d:\Users\666\Desktop\world knowledge graph rag\.claude\worktrees\sdd-retrieval-comparison" push origin worktree-sdd-retrieval-comparison
```

### 步驟 5（可選後續工作）
- 論文 `docs/論文/05_實驗設計與評估.md` 之 §5.5.1a 目前為留空狀態，若後續需將 AGGR1-17 彙總成大表，可自報告 57 §4.3~§4.12 萃取填入。

---

## 5. 運行環境與約束規範
- **嚴格遵守不可變性原則**：所有 `exact_span` 必須逐字對應 `original.md`，禁止擅自修改語意。
- **測試與環境依賴**：本地測試套件共 976 tests 通過；Harness 執行僅依賴 Neo4j 與 Ollama（qwen2.5:7b, bge-m3:latest），不需啟動 FastAPI 伺服器。
