# Codex 接手確認導引（Handover Guide for Codex）

> **目前進度請先讀**：[跨 Agent 接續進度 HANDOVER.md](HANDOVER.md)。本檔案記錄較早的 Codex 交接狀態與 checklist；若狀態或建議與 HANDOVER.md 不同，以 HANDOVER.md 及最新報告為準，不要照舊 checklist 直接推送。

> **建立日期**：2026-09-18  
> **交接對象**：CODEX / 接續工程師  
> **目標 Worktree**：`d:\Users\666\Desktop\world knowledge graph rag\.claude\worktrees\sdd-retrieval-comparison`  
> **目標 Branch**：`worktree-sdd-retrieval-comparison`  
> **詳細交接任務書**：[`docs/報告/60_Codex接續確認交接任務書.md`](docs/報告/60_Codex接續確認交接任務書.md)  
> **核心報告文件**：[`docs/報告/57_檢索品質解耦評測與知識圖譜場景化角色SDD任務書.md`](docs/報告/57_檢索品質解耦評測與知識圖譜場景化角色SDD任務書.md)

---

## 1. 快速狀態摘要（Executive Summary）

- **目前狀態**：任務 C（第 8 組、第 9 組候選題目，AGGR13-16）的法規查證、targeted Neo4j 重抽、題庫擴充、K arm harness 評測、報告 57 寫入與論文附錄 A 擴充已**全數完工**。
- **本輪任務本質**：**純確認與驗證（Verification & Sanity Check）**。不需要撰寫新代碼或新題目。確認無誤後即可執行 `git push`。
- **目前 Commit 進度**：
  - `f16c00e` `docs(報告57/論文05附錄A): 補完第8/9組候選§4.11/§4.12(AGGR13-16 harness真實結果)+附錄A擴充至62題/43 verified(AGGR3-16全題目)`
  - `d219493` `docs+data(報告57任務C第8/9組候選): 私立就業服務機構許可雙來源授權鏈+職安衛管理辦法風險分級+新增4題(AGGR13-16)`
  - 本地領先遠端 `origin/worktree-sdd-retrieval-comparison` 2 個 commits。

---

## 2. 異動檔案一覽

1. **`data/eval/test_cases.json`**：新增 `57-AGGR13` ~ `57-AGGR16`，題庫總數由 58 增至 62 題，verified 題數由 39 增至 43 題。
2. **`docs/附錄A題庫.json`**：同步更新（與 `test_cases.json` 保持 byte-identical 鏡像）。
3. **`docs/報告/57_檢索品質解耦評測與知識圖譜場景化角色SDD任務書.md`**：
   - 補完 `§4.11`（第 8 組候選：私立就業服務機構許可雙來源授權鏈，AGGR13/14，真實 harness 評測結果）。
   - 補完 `§4.12`（第 9 組候選：職安衛管理辦法風險分級，AGGR15/16，真實 harness 評測結果）。
   - 更新 `§5` 進度清單第 4 條。
4. **`docs/論文/05_附錄A_測試題庫.md`**：
   - A.2.5 表格從 14 題擴充至 30 題（完整收錄 AGGR3-16 與 CANARY4/5）。
   - A.3.3 `mechanism_tags` 分佈統計更新（verified 總數 43 題），文件狀態標註 🟢。

---

## 3. 核心實證亮點（論文焦點）

### `57-AGGR15`：論文最具說服力的評測解耦案例
- **數據**：Context Recall **100%**、SNR **10.7%**、Chain Completeness **100%**，但 Atomic Accuracy 為 **0%**。
- **意涵**：在 9 組候選題中，這是唯一的「Context Quality 完美但最終答案為零」案例。所有必要法源條文皆已完整送進 Prompt，但 LLM（Stage 3）在生成時產生平滑化/幻覺。若無報告 57 的評測解耦指標，將被誤判為檢索失敗。

---

## 4. Codex 接續確認檢核清單（SOP）

請 Codex 依序執行以下 4 項確認工作：

### 優先級 1：數據一致性確認
- [ ] 核對 `docs/報告/57_...SDD任務書.md` §4.11 / §4.12 的評測數據與 `.claude/tmp/rq1_aggr13_16_pilot_v2/summary.md` 吻合：
  - `57-AGGR13`: Acc 0%, Context Recall 33.3%, SNR 3.7%, Chain 50.0%, latency 286.6s
  - `57-AGGR14`: Acc 67%, Context Recall 66.7%, SNR 4.1%, Chain N/A, latency 145.2s
  - `57-AGGR15`: Acc 0%, Context Recall 100%, SNR 10.7%, Chain 100%, latency 125.3s
  - `57-AGGR16`: Acc 25%, Context Recall 75.0%, SNR 9.3%, Chain N/A, latency 593.2s
- [ ] 核對 `docs/論文/05_附錄A_測試題庫.md` A.2.5 表格中 AGGR3~16 的 `mechanism_tags` 與 `scenario_type` 是否與 `data/eval/test_cases.json` 吻合。
- [ ] 確認 `data/eval/test_cases.json` 與 `docs/附錄A題庫.json` 內容完全同步（可用 PowerShell `Compare-Object (Get-Content ...) (Get-Content ...)` 快速比對）。

### 優先級 2：報告 57 結構檢查
- [ ] 確認報告 57 中的 `## 6. 使用者裁示結果` 僅出現一次（目前位於 line 526，無重複段落）。

### 優先級 3：推送遠端分支
- [ ] 確認上述各項無誤後，執行 Git Push：
  ```bash
  git -C "d:\Users\666\Desktop\world knowledge graph rag\.claude\worktrees\sdd-retrieval-comparison" push origin worktree-sdd-retrieval-comparison
  ```

### 優先級 4（可選後續工作，非本次阻礙）
- [ ] 論文 `docs/論文/05_實驗設計與評估.md` §5.5.1a 區塊可視使用者需求補入 AGGR1-16 全量總表（可從各 `.claude/tmp/rq1_*` 及報告 57 §4.3~§4.12 彙整）。目前維持待填狀態。
