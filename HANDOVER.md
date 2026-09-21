# 跨 Agent 接續進度

> **適用對象**：Claude Code、Codex、Gemini CLI，以及其他接續本專案的 agent。此文件是目前進度的唯一權威交接來源；舊的 `HANDOVER_CODEX.md`／`HANDOVER_CLAUDE_CODE.md` 僅保留歷史脈絡。
> **最後更新**：2026-09-20

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
