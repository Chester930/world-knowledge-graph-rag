# 85 `57-AGGR6`／`57-AGGR19` 歸屬錯置精確pilot規則SDD任務書（**交付 Codex，改 `test_cases.json`＋測試，不改production評分邏輯**）

**建立日期**：2026-09-26
**文件性質**：交付 Codex 執行用任務書。改動範圍：`data/eval/test_cases.json`（新增2條 `claim_audit_rules`）＋ `tests/services/test_claim_scope_auditor.py`（新增對應測試）。**不修改 `services/claim_scope_auditor.py`／`services/atomic_scorer.py` 本身**——沿用既有機制，只是替兩個已確認的真實案例補上跟 `57-AGGR18` 同款式的 pilot 規則。
**分支／工作區**：`worktree-sdd-retrieval-comparison`，`D:\Users\666\Desktop\world knowledge graph rag\.claude\worktrees\sdd-retrieval-comparison`
**前置依賴**：報告84（role_mismatch風險題庫全面掃描結果，已完成、已獨立複驗）。

---

## 0. 一頁摘要

報告84 §3.4／§3.5 確認 `57-AGGR6`、`57-AGGR19` 各自有一筆（或多筆）真實記錄，答案把同構事實的類別／版本歸屬弄錯，但因為所有必要 gold span 的文字仍逐字出現在答案裡，`AtomicScorer` 判定滿分或高分（`57-AGGR6` 的 B1 案例甚至 `is_perfect=True`）。這正是 `57-AGGR18` 已經示範過、`claim_audit_rules` 機制設計來抓的那種盲點。本任務比照 `57-AGGR18` 的既有做法（`aggr18-institution-swapped`），替這兩題各補一條**高精確度、低召回**的 pilot 規則。

**⚠️ 這會改變 `test_cases.json` 的 `bank_sha256`**——比照報告62 §14.10 已有的先例（當時修正 `57-DIST1/2` 也改了雜湊），這是**預期中、已核准的題庫修正**，不是意外。之後任何用舊雜湊（`23f8c06f…`）跑 `frozen_baseline_stage.py`／`verify_frozen.py` 之類的唯讀驗證，會如預期回報雜湊不一致——**這是正常現象，不是環境壞掉**，不需要因此排查別的問題。

---

## 1. 任務清單

### T1（M）：`57-AGGR6` 新增 `claim_audit_rules`

- 重新打開 `data/eval/candidate_runs/s3_chunk_rag_b1_stage_a/records.json`，找到 `question_id == "57-AGGR6"` 的那筆記錄，讀取完整答案原文（報告84 §3.4 已摘錄關鍵片段，但寫規則前務必看完整答案，不要只憑摘錄片段）。
- 針對答案裡「舊法第25條的資遣費分支，被在『退休金』分類底下重新列出、且動詞被改成『發給勞工退休金』」這個具體錯置模式，設計 `trigger_patterns`（比照 `aggr18-institution-swapped` 的做法：抓答案裡實際出現過的具體句型片段，不要寫成過度寬鬆、可能誤觸其他正確答案的通用規則）。
- 新增到 `test_cases.json` 裡 `57-AGGR6` 這筆的 `claim_audit_rules` 陣列，`kind` 設為 `role_mismatch`（沿用既有 kind 慣例），`id` 建議 `aggr6-branch-category-swapped`（或你認為更精確的命名，需在 commit message 說明理由）。
- `description` 欄位要清楚寫出這條規則在抓什麼、根據哪一筆真實觀察到的記錄（比照 `aggr18-institution-swapped` 的 description 寫法）。

### T2（M）：`57-AGGR19` 新增 `claim_audit_rules`

- 重新打開 `data/eval/candidate_runs/s3_chunk_rag_b0_stage_a/records.json`，找到 `question_id == "57-AGGR19"` 的那筆記錄，讀取完整答案原文（報告84 §3.5 已摘錄「以『新法』標題接第26條、卻列出舊法第23/24/25條內容；以『舊法』標題接第85/86條、卻列出新法內容」這個模式，同樣要看完整答案再動手）。
- 針對這個「新舊法標籤與條號/內容版本對調」的具體錯置模式設計 `trigger_patterns`，`id` 建議 `aggr19-version-label-swapped`（或你認為更精確的命名，需說明理由）。
- 同樣新增到 `test_cases.json` 裡 `57-AGGR19` 這筆的 `claim_audit_rules` 陣列。

### T3（M）：對應單元測試

比照 `tests/services/test_claim_scope_auditor.py` 既有的 `test_aggr18_swapped_institution_answer_is_flagged_even_when_atomic_facts_present()` 與 `test_aggr18_gold_answer_and_correct_paraphrase_pass()` 這一組配對寫法：

- 對 `57-AGGR6`：一個測試用 T1 找到的**真實觀察到的錯誤答案**（逐字或高度近似轉錄，來源標註出處），斷言 `audit_answer_scope()` 判定 `passed=False` 且 `issues[0]["rule_id"]` 是你設計的規則 id；另一個測試用 `case.gold_answer`（`_bank_case()` 讀出來的）與至少一個正確改寫版本，斷言兩者都 `passed=True`。
- 對 `57-AGGR19` 比照同樣的配對寫法。
- **這是本任務最重要的驗收項**——沒有這組配對測試，無法證明新規則「抓得到真的錯誤、放得過真的正確答案」，不能只新增規則不驗證。

### T4（S）：全套測試

- 執行 `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py`，確認全綠。
- 特別確認 `tests/services/test_claim_scope_auditor.py` 全部通過（含既有的 `57-AGGR18` 測試沒有被新規則意外影響）。

---

## 2. 明確不要做的事

- **不要**修改 `services/claim_scope_auditor.py`、`services/atomic_scorer.py`——機制本身已經足夠，只是新增資料層的規則。
- **不要**處理 `57-DIST1`／`57-DIST2`／`57-DIST3`——報告84已明確判定這三題「結構有風險但目前查無乾淨的成對角色對調證據」，不符合新增精確 pilot 規則的門檻，本任務不處理。
- **不要**擴大題庫或新增題目——只在既有兩題（`57-AGGR6`、`57-AGGR19`）已有的欄位上新增 `claim_audit_rules`，不改動 `question`／`gold_answer`／`atomic_gold_facts` 等其他欄位。
- **不要**重跑任何評測 harness 或連線 Neo4j／Ollama——這是純資料與測試編輯任務。
- **不要**修改 `docs/論文/`——本次是評測基礎設施修正，不涉及論文正文。
- **不要**設計成通用的「歸屬角色評分器」——比照 `57-AGGR18` 先例，維持「高精確度、低召回、只涵蓋已觀察到的具體句型」的 pilot 規則精神，不要試圖泛化成能抓所有可能錯置模式的通用機制。

## 3. 完成定義

1. `test_cases.json` 的 `57-AGGR6`、`57-AGGR19` 兩筆各新增一條 `claim_audit_rules`，格式與既有 `aggr18-institution-swapped` 一致。
2. `tests/services/test_claim_scope_auditor.py` 新增至少 4 個測試（每題一組「真實錯誤答案被抓到」＋「正確答案／改寫通過」配對），全部通過。
3. `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py` 全綠。
4. commit message 明確說明：這會改變 `bank_sha256`，是報告62 §14.10 先例下的預期題庫修正，不是意外。
5. `git diff --stat` 只顯示 `data/eval/test_cases.json`、`tests/services/test_claim_scope_auditor.py` 兩個檔案，沒有其他程式碼、`docs/論文/` 被觸碰。

---

## 4. 給 Codex 的指令（可直接貼上）

> 請執行 `docs/報告/85_AGGR6與AGGR19歸屬錯置精確pilot規則SDD任務書.md` 的 T1-T4。比照 `test_cases.json` 裡 `57-AGGR18` 既有的 `aggr18-institution-swapped` pilot 規則寫法，替 `57-AGGR6`（真實錯誤記錄在 `data/eval/candidate_runs/s3_chunk_rag_b1_stage_a/records.json`）與 `57-AGGR19`（真實錯誤記錄在 `data/eval/candidate_runs/s3_chunk_rag_b0_stage_a/records.json`）各新增一條 `claim_audit_rules`。
>
> 寫規則前務必自己重新讀取這兩筆記錄的完整答案原文（報告84 §3.4/§3.5 只是摘錄，不是完整內容），根據真實出現過的句型設計 `trigger_patterns`，維持 `57-AGGR18` 那種「高精確度、低召回、只涵蓋已觀察到的具體句型」的 pilot 規則精神，不要寫成可能誤觸其他正確答案的通用規則。
>
> 比照 `tests/services/test_claim_scope_auditor.py` 現有的 `test_aggr18_swapped_institution_answer_is_flagged_even_when_atomic_facts_present()`／`test_aggr18_gold_answer_and_correct_paraphrase_pass()` 配對寫法，替兩條新規則各寫一組測試（真實錯誤答案被抓到＋正確答案通過）。
>
> **不要**處理 `57-DIST1`／`57-DIST2`／`57-DIST3`（報告84已判定證據不足），**不要**修改 `services/claim_scope_auditor.py`／`services/atomic_scorer.py` 本身，**不要**修改 `docs/論文/`。
>
> 這會改變 `test_cases.json` 的 `bank_sha256`——commit message 要明確說明這是比照報告62 §14.10 先例的預期題庫修正，之後用舊雜湊跑唯讀驗證出現不一致是正常現象。完成後跑 `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py` 確認全綠，回報結果。commit 前不需要額外詢問，但 push 需要使用者另行同意。
