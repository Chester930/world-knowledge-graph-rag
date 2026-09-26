# 89 worktree 分支合併 master 前差異摘要結果

**分析日期**：2026-09-27  
**分析工作區**：`D:\Users\666\Desktop\world knowledge graph rag\.claude\worktrees\sdd-retrieval-comparison`  
**分析分支**：`worktree-sdd-retrieval-comparison`  
**比較對象**：`origin/master`  
**文件性質**：唯讀 Git 歷史與 diff 摘要，供使用者與 Claude Code 後續判斷處理方式；本文件不執行合併，也不替人決定合併策略。

## 0. 執行邊界與快照

本次只讀取 Git refs、commit history、name-only/name-status/numstat/stat diff 及既有文件，並新增本結果報告。沒有執行 `git merge`、`git rebase`、`git checkout master`、`git reset` 或任何 push；沒有呼叫 Neo4j、Ollama，也沒有執行測試。

分析時的 refs：

| 項目 | 值 |
|---|---|
| merge-base | `b1c620eac23dadce4b70d079cc83993c25de78ee` |
| `HEAD` | `74872a4be1a147097b9023708fbc91fc75942adb`（報告89任務書） |
| `origin/master` | `c57f7dd957d3cd4a8a6809334531fa29d82383c8` |
| `origin/worktree-sdd-retrieval-comparison` | `74872a4be1a147097b9023708fbc91fc75942adb` |
| `origin/master..HEAD` commit 數 | **98** |
| `HEAD..origin/master` commit 數 | **54** |

任務書建立時記載分支領先 97 個 commit；目前實際查得 98 個。多出的 1 個是任務書自身的 `74872a4`，因此本報告同時記錄任務書快照數字 97 與目前可重現數字 98，不把兩者混為一談。

## 1. T1：分岔基準與 master 端 54 個 commit

### 1.1 `origin/master` 領先本分支的 54 個 commit

以下依 `git log HEAD..origin/master --oneline --reverse` 的拓撲順序列出；這是本分支目前沒有的 master 端進度。

1. `e233664` docs(報告63): Gemini 評測報告查證與改進項評估
2. `49fdc64` docs+fix: 報告63 §8 後續查證、生成端來源標註文獻入庫、修正過時註解
3. `1c667d2` docs(報告63 §9): 查證第二份 Gemini 報告（缺口紀錄表 v1.0）並更正型別貧血判斷
4. `2749518` docs(報告63 §10): 查證第三份 Gemini 報告（分層客製化架構現況與接續任務）
5. `26362c3` docs(報告64): Codex SDD 任務書——T2 進行期間可並行工作（抽取端門檻接線／文獻登錄／來源歧義盤點）
6. `074052f` feat: 接線關係型別門檻 cfg
7. `ab409a5` feat: 轉傳關係門檻 cfg 至抽取
8. `c9c92d6` feat: 接線句子涵蓋門檻 cfg
9. `a8fbf23` feat: 轉傳抽取完整性檢查 cfg
10. `a90683c` feat: 接線實體去重門檻 cfg
11. `ec26675` feat: 轉傳實體去重 cfg
12. `5b72e7b` feat: 轉傳實體去重設定至圖合併
13. `6141de2` feat: 接線關係邊回填門檻 cfg
14. `95898d8` feat: 轉傳回填門檻 cfg
15. `2adcdd9` refactor: 移除已接線門檻常數匯入
16. `421bfca` fix: 保留回填門檻常數模組別名
17. `a8c7cbb` style: 整理 cfg wiring 測試匯入
18. `75f1777` docs: 更新抽取端 cfg 接線現況
19. `fd208b6` docs(報告63 §11): 查證第四份 Gemini 報告（時序 Temporal Awareness Plan）並記錄自動執行查核
20. `a2f3882` feat: 新增來源歧義 Phase 1 盤點器
21. `4e063f2` fix: 完整回報 AGGR18 相鄰條號配對
22. `39b7301` docs: 回填來源歧義 Phase 1 結果
23. `d8a20f7` docs(報告63 §12): Codex TASK-1/TASK-3 審核紀錄；更正 effective_date 全 None 的錯誤說法
24. `6661684` test: guard TASK-3 source ambiguity metrics
25. `129efbe` docs(報告63 §12.5): Codex TASK-3 小修複驗——11/11 突變被抓到，驗收通過
26. `fad7116` docs(報告63 §13, 64): 更正 T2 進度判斷；補 AGGR18 實際 prompt 行的直接證據
27. `e59ec50` docs(報告63 §14): T2 最終結果；補充發現三個新增題（AGGR6/18/19）為評分器盲點造成的假性達標
28. `952cfa9` feat: add TASK-3 Phase 2 prompt source audit
29. `c8366d4` data: record TASK-3 Phase 2 Stage A audit
30. `b6443eb` docs: record TASK-3 Phase 2 results in taskbook
31. `ec3ac9e` test: cover Phase 2 trace source edge cases
32. `bde7b5c` docs(報告63 §16): Codex TASK-3 Phase 2 審核紀錄——驗收通過，含一項殘留低風險測試缺口
33. `904b46c` Merge remote-tracking branch 'origin/codex/task1-extraction-cfg-wiring'
34. `b629282` Merge remote-tracking branch 'origin/codex/task3-source-ambiguity-audit'
35. `1ac1ebe` feat(eval)+docs(報告57 §4.21): 拒答事後重算與20題檢索失敗歸因複核
36. `d0068d7` docs(code): 修正 RefusalBench 引用範圍（僅註解，行為不變）
37. `71f3229` feat(eval): 報告62 T0 檢索 trace（順位／分數／來源／是否進 prompt），純記錄不改行為
38. `9c2a822` feat(svo): 報告65方向A——規則10要求共同條件複述進每筆衍生三元組
39. `2ad13ec` feat(guardrails): 報告65 §7選項4——已知簡體詞組修正＋定向重抽內容流失防護閘門
40. `821ddf6` feat(svo): parameterize domain few-shot examples
41. `3ff6d44` feat(agent): 報告65 §10——57-AGGR19去重根因定位，prefer_fact_on_collision旗標（預設關閉）
42. `c7e3a5e` fix(報告67): 完成 T2/T3 型別標記雙重防護
43. `3e34ebe` fix(報告67 T3複驗): 修正_TYPE_MARKER_RE裸字分支缺開頭邊界的真實bug
44. `7e67f2b` chore: ignore all pytest basetemp directories
45. `41697bb` feat(報告68): 加入評測 embedding cache
46. `c8f9184` feat(eval): decouple fixed metric judge from test arm judge
47. `a58086c` docs: add report 68 and 69 integration references
48. `12d2308` test(eval): align report69 regression with master harness API
49. `bc37b61` chore(eval): normalize integrated file endings
50. `83d77ff` audit(eval): preserve naturalization backfill dry-run
51. `e175949` audit(eval): classify naturalization dry-run quality
52. `59801a0` audit(eval): backfill approved naturalization edges
53. `be17cf0` docs(eval): record T2 naturalization follow-up issues
54. `c57f7dd` docs(eval): add missing T2 follow-up issues

### 1.2 master 端進度的主題分組

- **報告63／64查證與任務並行安排（1–5）**：查證三份 Gemini 報告、建立並行處理任務背景。
- **抽取端 cfg wiring（6–18）**：將關係型別、句子涵蓋、實體去重、回填等門檻逐步傳入抽取與圖合併流程，並整理別名與測試匯入。
- **來源歧義 Phase 1 與 TASK-3 audit（19–34）**：新增來源歧義盤點器、prompt source audit、資料與 taskbook 紀錄、突變測試，以及兩個遠端分支合併 commit。
- **評測追蹤與抽取／防護分支（35–43）**：補報告57 §4.21、報告62 trace、報告65 規則10與 guardrail、報告65 去重旗標、報告67 型別標記防護及邊界修正。
- **評測基礎設施整合（44–49）**：pytest 暫存目錄忽略、embedding cache、固定 metric-judge、報告整合參考、測試 API 對齊與檔案結尾整理。
- **naturalization backfill 與後續問題（50–54）**：保留 dry-run、品質分級、回灌核准案例，並記錄仍需後續人工處理的問題。

## 2. T2：本分支相對 merge-base 的分類摘要

依任務書指定的 `git diff --stat origin/master...HEAD`（三個點，實際以 merge-base 為比較起點）：

```text
259 files changed, 531050 insertions(+), 249 deletions(-)
```

這個統計包含兩邊都曾做過、但目前內容可能已相同的檔案；因此不能把每一列都當成與 master 的未解衝突。

### 2.1 production 程式碼：`core/`、`models/`、`routers/`、`services/`

| 檔案 | 主要變更與對應脈絡 | 預設行為／風險核對 |
|---|---|---|
| `core/config.py` | 報告62／T-A：新增 `ollama_llm_think: bool | None` 設定。 | `None` 時不送 Ollama `think` 欄位，保留既有 payload；明確設定才改變行為。 |
| `core/providers/llm/ollama.py` | 報告62 T-A：集中建立 generate payload，支援 `think`，同時保留 `generate`、`generate_json`、stream 的既有選項。 | `think=None` 為條件式 opt-in；本身不是所有 production 行為零變化的證明，需與環境設定一起看。 |
| `core/providers/factory.py` | 報告62 T-A；報告68 embedding cache；報告69 fixed metric-judge。新增 eval-only provider 建構／替換入口。 | `make_llm_provider_for_eval()` 與 `override_embedding_provider_for_eval()` 是 harness/test-only 入口；`_make_llm_provider()` 的 `think` 只在設定非 `None` 時有效。 |
| `core/kg_config/__init__.py` | 報告76／77：匯出 `GuardConfig`、`RelTypeExtension`。 | 設定模型 API 擴充；真正是否改預設語意要與 `model.py`、`svo_service.py` 一起核對。 |
| `core/kg_config/model.py` | 報告66／72／76／77：SVO few-shot、`article_expand`、GuardConfig token 清單、法律模態 relation extensions。 | `article_expand` 是預設關閉；但 shipped default 的 guard 與 relation extensions 會被 production 抽取路徑使用，不能概括成全部零行為變化。 |
| `core/kg_config/stages.py` | 報告76：加入 `dedup.guard` stage 描述、參數與 metrics。 | stage registry 記錄用途，不直接執行抽取；預設無 gate。 |
| `models/document.py` | 報告62 T0、報告72：`ChatRequest` 增加 `include_retrieval_trace` 與 `article_expand`。 | trace 預設 `False`；article expansion `None`，沿用 per-KG 設定且 shipped `False`。兩者均為 opt-in。 |
| `models/eval_schema.py` | 報告62／57 §4.16：加入 retrieval trace、scope／claim audit 相關評測 schema。 | 評測資料契約；不直接改正式 `chat()` 預設。 |
| `routers/agent.py` | 報告62 T0 trace；報告65 `prefer_fact_on_collision`；報告67 型別標記防護；報告72 `article_expand`。 | trace、article expansion、Fact collision preference 都有關閉預設；型別標記清除／防護與錯誤輸出 fallback 是條件式 production 邏輯修正，不是完全零行為變化。 |
| `services/atomic_scorer.py` | 報告57 §4.21：拒答事後重算相關的評測／診斷支援。 | 目前與 master 最終內容相同；屬評測判定邏輯，不能只按檔名推論與正式 chat 無關。 |
| `services/extraction_worker.py` | 報告66／76：背景 worker 載入 per-KG config，將 cfg 傳給 completeness extraction 與 graph merge。 | 缺設定時 fallback `KGConfig()`；但 `cfg` 會進 production 抽取與合併路徑，這是需人工確認的實際行為接線。 |
| `services/interval_lookup_service.py` | 報告61／RefusalBench 引用範圍校正，主要是文件／註解。 | 本比較最後與 master 內容相同，沒有額外可見程式差異。 |
| `services/lineage_tracker.py` | 報告62 T0：記錄 retrieval trace／prompt context 的評測 lineage。 | 目前與 master 最終內容相同；偏評測記錄，不改檢索結果。 |
| `services/svo_service.py` | 報告65 規則10、報告66 few-shot 注入、報告67 naturalization type-marker 防護、報告76 guard profile、報告77 relation extensions。 | 這裡不是單純 opt-in：規則10、shipped default relation extensions、guard/fallback 會影響抽取與實體處理預設路徑，是本分支 production 差異的最高風險區之一。 |

### 2.2 預設行為的總結核對

已確認的「預設關閉／只記錄」項目：

- `ChatRequest.include_retrieval_trace=False`：只在明確開啟時收集 trace。
- `ChatRequest.article_expand=None` 且 `FactListConfig.article_expand=False`：不補同條文兄弟 Fact。
- `prefer_fact_on_collision=False`：不改既有 BFS 優先的 collision 行為。
- `--embedding-cache`、`--metric-judge-provider`、`--metric-judge-model`、`--k-top-k` 與 `--article-expand`：均是評測 CLI 選填旗標。
- `ollama_llm_think=None`：不向 Ollama 傳 `think` 欄位。

不能標為「全部零行為變化」的項目：

- `services/svo_service.py` 的規則10與 shipped default relation/guard 設定會進抽取端；這不是只新增離線記錄。
- `routers/agent.py` 的型別標記清除、naturalization fallback 與相關品質守門，會在特定殘留型別標記／內容缺陷出現時改變輸出。
- `services/extraction_worker.py` 已將 cfg 傳到 production 抽取與圖合併流程；雖有設定失敗 fallback，仍屬 production path 接線。

### 2.3 `data/eval/test_cases.json`

相對 merge-base，本分支對此檔案有 2 次修改：

| commit | 內容 | `bank_sha256` |
|---|---|---|
| `b8d1553` | 報告62 §14.10：為 `57-DIST1`／`57-DIST2` 各補入第2條「給予一至三日之特別休假」與第3條「給予二至五日之特別休假」兩個必要 span，修正鄰接陷阱題的 gold 定義。 | `404cde9f3dbe261c69fc31c59c28d7b6f3c9e60b1ae9e8cf8db64869d9494427` → `23f8c06fa7f4459e2bc64531ef80c62f6e00a25b779a0abb7eb4e81933b3aa84` |
| `2f8ddab` | 報告85：依實際觀察到的錯答，為 `57-AGGR6` 與 `57-AGGR19` 新增精確、低召回的 `role_mismatch` pilot 規則。 | `23f8c06fa7f4459e2bc64531ef80c62f6e00a25b779a0abb7eb4e81933b3aa84` → `77c293ed4b75cfd44ac4fe36d9b529566ce669d4dc7c960cbac5a3e5161ee48a` |

`docs/附錄A題庫.json` 亦有同步鏡像變更（28 行新增）；目前本分支的兩份題庫鏡像內容一致。這些 hash 變化是題庫內容確實變更，不是格式或執行環境雜訊。

### 2.4 `docs/論文/`

本分支改動 7 個論文檔案；此範圍內 master 沒有改動 `docs/論文/`，所以它們不屬於雙方共同改檔，但 `00` 是長期累積檔案，後續處理仍需保留其追溯內容。

| 檔案 | 變更內容／對應報告 |
|---|---|
| `00_研究追溯對映表.md` | 報告80 S3 RQ1 回灌、報告76／77 RQ4a/RQ4b 進度同步；保留 RQ4b 範圍修飾缺口描述。 |
| `02_文獻探討.md` | RefusalBench 引用範圍校正、報告65 抽取粒度文獻脈絡、參考文獻38 的 embedding 非決定性查證。 |
| `03_系統設計與方法論.md` | RefusalBench 引用範圍校正。 |
| `04_系統實作.md` | RefusalBench 引用範圍校正。 |
| `05_實驗設計與評估.md` | 回灌 S3 對照組設計。 |
| `06_結果與討論.md` | 回灌 S3 RQ1 結果與 B0/B1/D 對照解讀。 |
| `07_結論與未來工作.md` | 回灌 S3 結果與 GAP-S3-01/02 消融結果。 |

### 2.5 `docs/報告/`

相對 merge-base 新增 **28 份**報告檔案；依任務書要求只列檔名，不在此重複各報告內容：

- `61_做法與文獻來源查證報告.md`
- `62_下一階段任務書_檢索排名與條文擴充驗證.md`
- `65_抽取粒度修復設計SDD任務書.md`
- `66_SVO抽取少樣本領域包參數化SDD任務書.md`
- `67_事實自然語言化品質問題SDD任務書.md`
- `68_評測harness查詢embedding快取SDD任務書.md`
- `69_評測harness固定metric-judge與受測arm-judge解耦SDD任務書.md`
- `70_報告68_69批次整合進master任務書.md`
- `71_natural_text型別洩漏backfill任務書.md`
- `72_報告62殘留待辦新基準與K1b_T3_chunkRAG任務書.md`
- `73_報告69殘餘judge非決定性緩解任務書.md`
- `74_報告72執行接續報告_20260923.md`
- `75_本體論設計資料夾專案整合候選盤點.md`
- `76_guard_profile領域可插拔化SDD任務書.md`
- `77_法律模態關係型per-KG擴充SDD任務書.md`
- `78_S3落差題逐題根因診斷SDD任務書.md`
- `79_S3評分器規則R敏感度分析SDD任務書.md`
- `80_S3結果回灌論文RQ1章節SDD任務書.md`
- `81_S3落差題獨立模型盲審交叉驗證SDD任務書.md`
- `82_GAP_S3_01上下文組裝離線消融原型SDD任務書.md`
- `83_GAP_S3_0102試驗結果回灌未來工作SDD任務書.md`
- `84_role_mismatch風險題庫全面掃描SDD任務書.md`
- `84_role_mismatch風險題庫全面掃描結果.md`
- `85_AGGR6與AGGR19歸屬錯置精確pilot規則SDD任務書.md`
- `86_RQ4a4b追溯表同步報告76_77SDD任務書.md`
- `87_本體論設計資料夾尚待詳讀清單掃描SDD任務書.md`
- `88_18Q6與57DIST2人工法規語意判定資料包.md`
- `89_worktree分支合併master前差異摘要SDD任務書.md`

另有既有檔案 `42_全量重抽三階段方法比較與報告39七路評分報告.md`、`57_檢索品質解耦評測與知識圖譜場景化角色SDD任務書.md` 被修改；其中報告57 也是 T3 的雙方共同修改檔案。

### 2.6 測試檔案

本分支變更 **17 個測試檔案**：4 個新增、13 個修改。以 diff 中新增的 `test_*` function 定義計算約 **92 個**；參數化測試的實際 case 數可能高於 function 定義數。

新增檔案：

- `tests/core/test_ollama_llm_think.py`
- `tests/scripts/test_embedding_cache.py`
- `tests/scripts/test_posthoc_diagnostics.py`
- `tests/scripts/test_rq1_metric_judge.py`

主要修改檔案：

- `tests/core/test_kg_config.py`、`tests/core/test_kg_config_stages.py`、`tests/core/test_providers_factory.py`
- `tests/routers/test_agent.py`
- `tests/scripts/test_frozen_baseline_stage.py`、`test_reextract_chunks.py`、`test_rq1_harness_failures.py`
- `tests/services/test_claim_scope_auditor.py`、`test_evaluation_metrics.py`、`test_extraction_worker.py`、`test_lineage_tracker.py`、`test_svo_service.py`

測試變更涵蓋設定 schema、Ollama `think` payload、評測 cache／metric judge、retrieval trace、article expansion、抽取 worker cfg、SVO guard／relation extensions／type marker 防護與既有評測診斷。

### 2.7 `data/eval/` 產生型資料：依資料夾統計

`data/eval/` 共 **158 個檔案**變更；以下不逐檔展開 records JSON：

| 分類 | 檔案數 | 來源與用途 |
|---|---:|---|
| `baseline_runs/20260920_frozen/analysis/` | 2 | 報告57 §4.21 的拒答事後重算與 20 題 retrieval failure diagnosis；兩份也出現在 master 端。 |
| `baseline_runs/20260923_rebased/` | 17 | 報告72 S0 新題庫 42 題基準，包含 frozen manifest、adaptive summaries、questions、stage records 與 summary。 |
| `candidate_runs/s1_k1b_topk40_bfs16_*` | 10 | 報告72 S1：top-k=40 並維持 BFS 名額的 K1b 候選臂。 |
| `candidate_runs/s2_k1_topk40_*` | 15 | 報告72 S1/K1 候選臂的重跑、audit、stage A/B/C 與摘要。 |
| `candidate_runs/s2_k2_article_expand_*` | 15 | 報告72 S2 K2：`article_expand` 條文層級擴充候選臂。 |
| `candidate_runs/s2_k3_article_expand_topk40_*` | 15 | 報告72 S2 K3：top-k=40 與 article expansion 組合候選臂。 |
| `candidate_runs/s3_chunk_rag_b0_*` | 16 | 報告72 S3 B0 naive chunk-RAG 對照組。 |
| `candidate_runs/s3_chunk_rag_b1_*` | 10 | 報告72 S3 B1 hybrid chunk-RAG 對照組。 |
| `candidate_runs/s3_chunk_rag_d_*` | 10 | 報告72 S3 D direct-LM control。 |
| `candidate_runs/s3_blind_crosscheck.json`、`s3_rule_r_rejudge.json` | 2 | 報告78／79 的 S3 盲審與規則 R 敏感度資料。 |
| `candidate_runs/t0_trace_check_20260921/` | 3 | 報告62 T0 retrieval trace 核對。 |
| `candidate_runs/t2_*` 與 `t2_probe_topk40_20260921/` | 35 | 報告62 T2 top-k=40 各階段、暫停／續跑、diagnostic 與 probe 產物。 |
| `candidate_runs/gap_s3_01_context_ablation.json` | 1 | 報告82 GAP-S3-01 context ablation 原型。 |
| `scorer_audit_20260922/` | 5 | 報告62 §14 的評分器盲點盲審／人工複核交叉資料。 |
| `scorer_v2_20260922/` 與 summary | 2 | 報告62 §14 的離線 scorer v2 重判資料。 |
| `test_cases.json` | 1 | 題庫本體；內容變更與 hash 演進見 §2.3。 |

上述數字合計 158；其中大部分是評測 records／manifest／summary 產物，不宜當成 158 個獨立 production 功能。

### 2.8 其他分支側變更

- `scripts/eval/`：16 個新增評測／診斷工具，`frozen_baseline_stage.py` 與 `run_rq1_comparison.py` 修改；涵蓋 report57/62/68/69/72/78/79/82 的評測流程。
- `scripts/kg/reextract_chunks.py`：報告65 guardrail 與定向重抽內容流失防護。
- `config/domain_packs/generic.json`：generic domain pack 說明與 relation extension 設定。
- `config/kg/236903cf-055a-40a8-8923-b9d06601f3b7.json`：報告72 S1 的 opt-in `min_bfs_slots=16`。
- `docs/參考文獻/`：新增／更新評測方法、法律 RAG、三元組限定詞、embedding 可重現性、LLM judge 一致性資料，並新增數篇 PDF。
- `.gitignore`：pytest basetemp 忽略規則；此檔案兩邊最後內容相同。
- `HANDOVER.md`：相對 merge-base `+549/-2`，有 **55 次**相關 commit 更新，累積報告65–88、報告72 S0–S3、報告68/69、master 整合、backfill 與後續待辦等階段紀錄。

## 3. T3：雙方改檔交叉比對與衝突風險

### 3.1 清單統計

以共同祖先 `b1c620e...` 為基準：

| 清單 | 檔案數 |
|---|---:|
| `git diff --name-only b1c620e..origin/master` | 65 |
| `git diff --name-only b1c620e..HEAD` | 259 |
| 兩邊都改過的交集 | **39** |
| 交集檔案最後內容完全相同 | 21 |
| 交集檔案最後內容仍不同 | **18** |

master-only 的 26 個檔案主要是：

- `docs/參考文獻/37_.../README.md` 與兩份 PDF；
- `docs/報告/33_...md`、`63_...md`、`64_...md`；
- `data/analysis/source_ambiguity/` 4 個盤點結果檔；
- `data/eval/naturalization_backfill_dryrun_20260923/` 10 個 backfill／品質分級檔；
- `scripts/analysis/source_ambiguity_audit.py`、`scripts/kg/backfill_naturalization_safe_edges.py`；
- `services/entity_extraction_service.py`、`services/expand_worker.py`；
- `tests/scripts/test_source_ambiguity_audit.py`、`tests/services/test_svo_service_cfg_wiring.py`。

### 3.2 交集中最後內容相同的 21 個檔案

以下檔案雖然兩邊的 commit history 都碰過，但 `HEAD` 與 `origin/master` 最後內容比較為相同；目前可見的主要風險是後續若重新挑選 commit，可能重複套用，而不是檔案內容本身已呈現差異：

1. `.gitignore`
2. `data/eval/baseline_runs/20260920_frozen/analysis/rescore_refusal_posthoc.json`
3. `data/eval/baseline_runs/20260920_frozen/analysis/retrieval_failure_diagnosis.json`
4. `docs/參考文獻/38_檢索embedding非決定性與可重現性/README.md`
5. `docs/參考文獻/39_LLM評判者一致性與固定化評測量尺/README.md`
6. `docs/報告/68_評測harness查詢embedding快取SDD任務書.md`
7. `docs/報告/69_評測harness固定metric-judge與受測arm-judge解耦SDD任務書.md`
8. `models/eval_schema.py`
9. `scripts/eval/diagnose_retrieval_failures.py`
10. `scripts/eval/rescore_refusal_posthoc.py`
11. `scripts/kg/reextract_chunks.py`
12. `services/atomic_scorer.py`
13. `services/interval_lookup_service.py`
14. `services/lineage_tracker.py`
15. `tests/scripts/test_frozen_baseline_stage.py`
16. `tests/scripts/test_posthoc_diagnostics.py`
17. `tests/scripts/test_reextract_chunks.py`
18. `tests/scripts/test_rq1_metric_judge.py`
19. `tests/services/test_evaluation_metrics.py`
20. `tests/services/test_extraction_worker.py`
21. `tests/services/test_lineage_tracker.py`

其中報告68／69與兩份參考文獻 README 的「兩邊都有 commit」主要是不同歷史批次對同一內容的整合；實際 blob 相同仍應在任何後續操作前再核對，不宜只憑 commit subject 判定。

### 3.3 交集中最後內容不同的 18 個檔案

下表的 master-side 描述是 `b1c620e..origin/master` 的變更；worktree-side 描述是 `b1c620e..HEAD` 的變更。風險等級是內容重疊程度的客觀分級，不是合併核准結論。

| 風險 | 檔案 | master 端改動 | 本分支改動 | 重疊判讀 |
|---|---|---|---|---|
| 中高 | `config/domain_packs/generic.json` | 報告66 few-shot 參數化後，generic pack 的說明／relation extension 設定被整理為不覆寫。 | 報告76／77 延伸 generic pack 說明，保留空 relation extension 的 domain 意圖。 | 同一 JSON `domain` 區塊；需決定 relation extension 空集合與 shipped default 的語意，非單純獨立行。 |
| 高 | `core/kg_config/model.py` | master 保留 few-shot schema，但沒有本分支的 `GuardConfig`、`RelTypeExtension`、`article_expand` 欄位。 | 報告72／76／77 新增 article expansion、guard token、法律模態 relation schema。 | 同一設定模型與同一 `DomainConfig`／`FactListConfig` 區段，且 master 端後續演進與本分支新增欄位直接重疊。 |
| 中高 | `core/providers/factory.py` | master 整合報告68／69 eval provider 功能。 | 另有報告62 T-A 的 `think` 參數接線。 | 同一 `_make_llm_provider()`；功能可分段，但 `OllamaLLMProvider` 呼叫簽名必須保留一致。 |
| 中高 | `docs/報告/57_檢索品質解耦評測與知識圖譜場景化角色SDD任務書.md` | master 回填 §4.21 拒答重算與 retrieval failure diagnosis。 | 本分支同樣回填 §4.21，另有報告62／RefusalBench 文字校正與進度紀錄。 | 長期累積報告且同一 §4.21 附近都有修改；需按章節核對，不宜整檔覆蓋。 |
| **高** | `HANDOVER.md` | master 端新增報告68/69整合參考及 naturalization backfill 後續紀錄。 | 本分支累積報告65–88、報告72 S0–S3、報告80–86 論文回灌與多段交接紀錄。 | 長期累積檔，兩邊都在尾端／近期狀態段落寫入；`HEAD` 與 master 最終差異為 546 行以上，人工逐段保留是必要的。 |
| 中高 | `models/document.py` | master 保留報告62 trace 欄位，但沒有 article expansion 欄位。 | 報告72 新增 `article_expand` per-request opt-in。 | 同一 `ChatRequest` 欄位區，且 router/harness 同時依賴；schema 與呼叫端必須成對看。 |
| **高** | `routers/agent.py` | master 整合報告62 trace、報告65 collision、報告67 type-marker 修正。 | 本分支在相同 production path 另加報告72 `_expand_facts_by_article()`／chat 接線，並保留上述功能。 | 同一 retrieval→arrange→prompt 與 `_split_fact_lines()` 區域；不是單純文件新增，且會影響 `chat()`。 |
| 低 | `scripts/eval/embedding_cache.py` | master 只做檔案結尾／整合批次整理。 | 本分支新增 cache implementation。 | 最終差異只有尾端空白行；內容層面不構成衝突。 |
| 中高 | `scripts/eval/frozen_baseline_stage.py` | master 整合 embedding cache／metric-judge／top-k 支援。 | 本分支另保留 report72 `article_expand` CLI 與參數轉傳。 | 同一 command builder 與 argparse；article expansion 旗標可能被一方覆蓋或遺失。 |
| **高** | `scripts/eval/run_rq1_comparison.py` | master 整合 trace、embedding cache、fixed metric judge。 | 本分支另有 `--k-top-k`、`article_expand`、`_build_kg_chat_request()` 與對應 manifest／record 欄位。 | 同一 harness 主流程、`ChatRequest` 組裝與 runner 參數；是高重疊評測基礎設施。 |
| 高 | `services/extraction_worker.py` | master 有 few-shot cfg 載入與 completeness extraction 傳遞。 | 本分支再將同一 cfg 傳到 `merge_triples_to_graph()`，並含 guard profile 接線。 | 最終只有 merge 呼叫的一行差異，但正好是 production 抽取／圖合併接線，需確認 API 與資料一致性。 |
| **高** | `services/svo_service.py` | master 已整合規則10、guardrail、few-shot 與多項抽取 cfg wiring。 | 本分支另有 report76 GuardConfig、report77 relation extensions、type-marker 防護與同一 prompt／cache／reconcile 路徑變更。 | 變更集中在 `_svo_prompt()`、relation type、guard pattern、extract／reconcile 多個共同函式；是最需要逐段人工處理的 production 檔案。 |
| 高 | `tests/core/test_kg_config.py` | master 測試 few-shot schema。 | 本分支增加 GuardConfig、relation extension、generic pack 與 article expansion 測試。 | 測試直接對應同一設定 schema；需跟採用的 model schema 同步，不能單獨保留一側。 |
| 中 | `tests/core/test_providers_factory.py` | master 測試 embedding／metric judge factory。 | 本分支另保留 `ollama_llm_think` wiring 測試。 | 同一 factory 測試檔，測試案例可並存，但 fixture／provider signature 需一致。 |
| 高 | `tests/routers/test_agent.py` | master 測試 trace、collision、type-marker 等 agent 行為。 | 本分支另增加 article expansion 及相關 trace／prompt tests。 | 同一 helper 與 chat 行為測試；若只取一側，容易漏掉另一側的 regression contract。 |
| 低 | `tests/scripts/test_embedding_cache.py` | master 與本分支測試內容相同，差異只是一個尾端空白行。 | 同左。 | 內容層面低風險。 |
| 中高 | `tests/scripts/test_rq1_harness_failures.py` | master 對齊 report69 harness API。 | 本分支保留報告62 top-k／article expansion request builder 測試。 | 測試引用的 helper 在 master 版本被移除；與 `run_rq1_comparison.py` 的 API 取捨直接耦合。 |
| 高 | `tests/services/test_svo_service.py` | master 測試 few-shot、guardrail 等已整合部分。 | 本分支另含 GuardConfig、relation extension、type-marker、報告76 guard regression 大量測試。 | 與 `services/svo_service.py`／`core/kg_config/model.py` 同步性最高；不能靠自動三方合併後直接視為通過。 |

### 3.4 特別檔案核對

- `HANDOVER.md`：確實是雙方共同修改，且本分支有 55 個相關 commit、master 端另有近期 backfill／integration 更新；列為最高人工保留風險。
- `docs/論文/00_研究追溯對映表.md`：在本次 `b1c620e..origin/master` 清單中沒有 master 端變更，只有本分支 3 個論文回灌 commit。因此它是長期累積檔，但不是這個雙向 diff 的「兩邊都改過」檔案。
- `docs/報告/57_...md`：兩邊都改，且同一份長期報告的 §4.21／後續進度都有內容，列為中高風險。
- `docs/報告/68_...md`、`69_...md`：兩邊 history 都有 commit，但最後 blob 相同；仍應以內容 hash 為準，不要用 commit 數量判定衝突。

## 4. T4：客觀總結與供人判斷的處理順序

### 4.1 差異性質

這不是「只有本分支超前、可視為單向快轉」的差異：目前實際為本分支相對 `origin/master` 領先 98 個 commit，而 master 相對本分支也有 54 個 commit。雙方改檔交集 39 個，且其中 18 個最後內容仍不同；因此不能把整體描述成無衝突檔案集合。

### 4.2 供後續人工評估的分層順序（不是合併指令）

以下只是依檔案耦合度整理的檢視順序，未在本任務執行：

1. 先獨立核對 `data/eval/` 產生物、報告新增檔、參考文獻新增檔與其他純新增內容；其中 158 個 `data/eval` 檔案應按資料夾與報告用途處理，不需逐檔人工閱讀 records。
2. 再核對 §3.2 所列 21 個最終內容相同檔案，確認是否確實是重複整合，而不是只因目前 refs 的工作樹呈現相同。
3. 接著處理 `config/domain_packs/generic.json`、`core/kg_config/model.py`、`models/document.py`、`services/extraction_worker.py` 與評測 harness 的 API 成對差異；這些檔案存在設定 schema／呼叫端／測試的互相依賴。
4. 將 `services/svo_service.py`、`routers/agent.py`、`scripts/eval/run_rq1_comparison.py` 及對應測試視為同一組 production／評測行為差異逐段核對。
5. `HANDOVER.md`、報告57與論文追溯檔最後按章節／日期人工保留兩邊紀錄；不宜用單一整檔版本取代另一邊的長期累積內容。

這些分層只描述後續人工檢視的依賴關係與風險位置，不代表採用任何一邊內容，也不代表已授權或執行任何 merge／rebase／push。

## 5. 本次唯讀完成狀態

- merge-base 已核對為任務書提供的 `b1c620e...`。
- master 端 54 個領先 commit 已完整列出。
- 本分支 production、題庫、論文、報告、測試、`data/eval` 分類與 `HANDOVER.md` 已摘要。
- 雙方改檔交集 39 個已列出；其中 18 個最後內容不同的檔案已逐一標註風險與重疊位置。
- 本結果報告是本次唯一新增的工作產物；沒有修改既有程式、設定、題庫、論文、報告或評測資料。
- master checkout 未被切換或寫入；本分析 worktree 的分支仍是 `worktree-sdd-retrieval-comparison`。push 未執行；任何後續 push 仍需另行明確同意。
