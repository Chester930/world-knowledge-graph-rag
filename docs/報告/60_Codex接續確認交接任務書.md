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
- **建議下一步**：Fact 候選池擴大後做 query-aware reranking／精煉，優先讓AGGR16第21名必要Fact進入有限context；對AGGR15/17比較top_k 10與20，對AGGR16比較top_k 20與25，之後各跑K-arm ×3，量測Context Recall、SNR、Atomic Accuracy、tokens與延遲。未完成重複端到端驗證前，不改全域top_k、不無條件接入scope filter、hybrid、source_doc_cap或Chunk augmentation。

本輪輸出位於主要 checkout 的 `.claude/tmp/rq1_scope_ab_20260918_n3/`、`.claude/tmp/rq1_fact_topk_sweep_20260918_semantic/`、`.claude/tmp/rq1_fact_topk_aggr16_extension_20260918/`；文件修改僅涉及本交接文件與報告57。測試程式碼未變，採 `git diff --check` 驗證文件差異。

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
