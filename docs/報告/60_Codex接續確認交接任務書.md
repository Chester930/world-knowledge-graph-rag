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
1. **本輪已完成所有核心出題、抽圖、harness 評測與文檔撰寫工作**，無需繼續擴充題目或撰寫新文檔。
2. **Codex 的核心任務為「接續確認（Verification）」**：驗證文檔與實驗數據、題庫標註的一致性，確認無誤後將工作成果推送（`git push`）至遠端分支。

---

## 1. 專案現況與最新 Commit 狀態

### 1.1 Git Commit 歷史（最新兩筆為本輪成果）
```text
f16c00e docs(報告57/論文05附錄A): 補完第8/9組候選§4.11/§4.12(AGGR13-16 harness真實結果)+附錄A擴充至62題/43 verified(AGGR3-16全題目)
d219493 docs+data(報告57任務C第8/9組候選): 私立就業服務機構許可雙來源授權鏈+職安衛管理辦法風險分級+新增4題(AGGR13-16)
```
目前本地分支領先遠端 `origin/worktree-sdd-retrieval-comparison` 2 個 commits。

### 1.2 異動檔案詳細清單
| 檔案路徑 | 異動性質 | 內容摘要 |
|---|---|---|
| `data/eval/test_cases.json` | 修改 | 新增 `57-AGGR13` ~ `57-AGGR16`，題目總數自 58 增至 62 題，`verified` 數自 39 增至 43 題。 |
| `docs/附錄A題庫.json` | 修改 | 同步更新，維持與 `test_cases.json` 之 byte-identical 鏡像關係。 |
| `docs/報告/57_檢索品質解耦評測與知識圖譜場景化角色SDD任務書.md` | 修改 | 撰寫完畢 `§4.11`（第8組候選）與 `§4.12`（第9組候選），填入 pilot_v2 真實 harness 評測數據，更新 `§5` 進度清單。 |
| `docs/論文/05_附錄A_測試題庫.md` | 修改 | A.2.5 表格自 14 題擴充至 30 題（收納 AGGR3-16 與 CANARY4/5），更新 A.3.3 `mechanism_tags` 分佈統計，狀態標為 🟢。 |

---

## 2. 任務 C（AGGR1-16）全 9 組候選完成總覽

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
| 9 | 57-AGGR15, 57-AGGR16 | N0060027 + N0060001 | `cross_doc_multihop`, `global_aggregation` | 職安衛管理辦法授權長句 + 事業風險等級與門檻配對 |

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
- `57-AGGR16` 執行前於 Neo4j 稽核發現：N0060027 第三類事業風險等級被抽成「具中度風險者」（原文為低度風險），屬於相鄰列舉項數值複製誤植（累計第 7 個獨立案例，已記入報告 57 §3.1.3 與 §4.12）。出題時已刻意避開第三類，僅採第一、二類作為評測對象。

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

### 步驟 2：核對題庫與附錄 A 一致性
- [x] `docs/論文/05_附錄A_測試題庫.md` 之 A.2.5 表格包含 AGGR3 至 AGGR16。
- [x] 每題之 `mechanism_tags` 與 `scenario_type` 與 `data/eval/test_cases.json` 保持完全一致。
- [x] 題庫總數統計正確：Verified = 43 題，Unverified = 19 題，合計 62 題。

### 步驟 3：檢查報告 57 之結構完好性
- [x] 確認 `## 6. 使用者裁示結果` 僅出現一次（行號 526 附近），且下方子項目無重複段落。

### 步驟 4：執行推送（Git Push）
確認工作區無任何異常或未提交之暫存檔案後，在 worktree 執行：
```powershell
git -C "d:\Users\666\Desktop\world knowledge graph rag\.claude\worktrees\sdd-retrieval-comparison" push origin worktree-sdd-retrieval-comparison
```

### 步驟 5（可選後續工作）
- 論文 `docs/論文/05_實驗設計與評估.md` 之 §5.5.1a 目前為留空狀態，若後續需將 AGGR1-16 彙總成大表，可自報告 57 §4.3~§4.12 萃取填入。

---

## 5. 運行環境與約束規範
- **嚴格遵守不可變性原則**：所有 `exact_span` 必須逐字對應 `original.md`，禁止擅自修改語意。
- **測試與環境依賴**：本地測試套件共 964 tests 通過；Harness 執行僅依賴 Neo4j 與 Ollama（qwen2.5:7b, bge-m3:latest），不需啟動 FastAPI 伺服器。
