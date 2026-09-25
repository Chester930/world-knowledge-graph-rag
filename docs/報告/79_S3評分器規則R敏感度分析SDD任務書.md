# 79 S3評分器規則R敏感度分析SDD任務書（GAP-S3-02，**交付 Codex，純離線分析、不改production程式碼**）

**建立日期**：2026-09-25
**文件性質**：交付 Codex 執行用任務書。**離線重算任務**——重用報告62 §14 已建立的規則 R 敏感度分析機制，套到報告72 §9（S3 chunk-RAG 對照組）的資料上，不重跑評測 harness、不需要 Neo4j／Ollama、不改動 `services/atomic_scorer.py` 等 production 程式碼。
**分支／工作區**：`worktree-sdd-retrieval-comparison`，`D:\Users\666\Desktop\world knowledge graph rag\.claude\worktrees\sdd-retrieval-comparison`
**前置依賴**：報告78（S3落差題根因診斷，2026-09-25 已完成，commit `ddbc4ac`）——§10.6 提出「暫名 GAP-S3-02：semantic span scorer 的表面形式脆弱性」，本任務書是它的落地。

---

## 0. 一頁摘要

**要回答的問題**：報告72 §9 顯示 S0 K（KG）13/42、B1（hybrid chunk-RAG）21/42，淨差 KG −8 題，McNemar `p=0.0215`。報告78 §10 逐題核實後發現，9 題落差裡至少 `18-Q6`／`57-DIST2` 兩題是「答案語意已經正確，但跟 gold span 逐字不符，被評分器判未命中」（表面形式脆弱性），不是真的內容遺漏。**這個 −8 的落差數字，有多少是評分器假陰性造成的假象、多少是真的？**

**不要重新設計評分規則**——報告62 §14 已經建好一套「規則 R」敏感度分析機制（`scripts/eval/scorer_rule_sensitivity.py` + `scripts/eval/audit_scorer_disagreements.py`）：gold span 與答案 bigram 重疊 ≥ 0.7、gold 的數字/序號都在答案裡出現、答案沒有否定用語，就把該筆「missing」重判為「supported」。這是**樣本內設計的敏感度分析工具，不是新的正式評分器**，報告62 §14.11 已裁示「暫不採用為預設，保留當診斷工具」——本任務就是用這個診斷工具，不是要建立新規則。

**技術重點**：現有腳本 `arms = {"base": load("baseline_runs/20260920_frozen", BASE_STAGES), "cand": load("candidate_runs", CAND_STAGES)}` 是**寫死指向舊的09-20凍結基準與舊的T2候選跑**，不能直接套用在 S3 資料上。本任務要寫一個新的小腳本，**重用**（import，不要複製貼上）`scorer_rule_sensitivity.py` 的 `flip()`／`perfect_prime()`／`meets_standard()`／`scope_ok()` 與 `audit_scorer_disagreements.py` 的 `load()`／`overlap()`，只是換成指向 S3 的資料路徑。

---

## 1. 現況（已查證的資料路徑與函式介面）

### 1.1 S3 各 arm 的 stage 資料夾（已用 `git show --stat 4c7cb69` 確認實際存在）

| Arm | `stages_root` | stage 資料夾清單 |
|---|---|---|
| S0（K，KG 新基準） | `baseline_runs/20260923_rebased` | `stage_s0_r1`、`stage_s0_r1_resume1`、`stage_s0_r2` |
| B0（naive chunk-RAG，`M1`） | `candidate_runs` | `s3_chunk_rag_b0_stage_a`、`s3_chunk_rag_b0_stage_b`、`s3_chunk_rag_b0_stage_c` |
| B1（hybrid chunk-RAG，`M2`） | `candidate_runs` | `s3_chunk_rag_b1_stage_a`、`s3_chunk_rag_b1_stage_b` |
| D（無檢索 control，選配） | `candidate_runs` | `s3_chunk_rag_d_stage_a`、`s3_chunk_rag_d_stage_b` |

`audit_scorer_disagreements.py::load(stages_root, stages)` 讀取 `data/eval/<stages_root>/<stage>/records.json`，過濾掉 `error` 非空的記錄——這個函式簽章本來就接受任意 `stages_root`／`stages`，**不需要修改這個函式本身**，只需要用正確參數呼叫它。

### 1.2 `eligible_ids`

`data/eval/baseline_runs/20260923_rebased/frozen_manifest.json` 的 `eligible_ids` 欄位已確認存在，42 筆，跟 S0-S3 全程使用的題庫一致（雜湊 `23f8c06f…`）——用這份，**不要用 `20260920_frozen` 那份舊的**（`scorer_rule_sensitivity.py` 目前寫死讀取的就是舊的那份，這是要修正的地方之一）。

### 1.3 `test_cases.json`

`scorer_rule_sensitivity.py::main()` 用 `bank = {q["id"]: q for q in json.loads((DATA / "test_cases.json")...)}` 取得每題的 `scenario_type`（判斷是否為 Type-E，`perfect_prime()` 需要這個資訊）——`test_cases.json` 是現行檔案，跟 S0-S3 使用的版本一致（報告62 §14.10 已修正過），**直接沿用，不需要另外處理版本問題**。

### 1.4 `--cand-fail`／`--require-qty` 兩個既有旗標

這兩個旗標是**針對舊資料集的特定事後修正**（`57-AGGR18` 新舊法寫反強制判失敗、`57-DIST1/2` 要求含特定天數字串）。S3 用的是新題庫（`57-DIST1/2` 已在報告62 §14.10 修正過原文），**預設不要套用這兩個旗標**——如果分析中發現 `57-AGGR18` 這題也適用類似情況，記錄下來但不要自作主張套用舊旗標，那是另一個獨立追蹤中的問題（`role_mismatch` 規則泛化，報告72 §3 已明確排除在外）。

---

## 2. 任務清單

### T1（M）：新增 `scripts/eval/s3_scorer_rule_sensitivity.py`

- **import 而非複製**：`from scorer_rule_sensitivity import flip, perfect_prime, meets_standard, scope_ok`、`from audit_scorer_disagreements import load, overlap, DATA`（注意 `scorer_rule_sensitivity.py` 檔案本身也 import 了 `audit_scorer_disagreements` 的東西，兩者都在 `scripts/eval/` 底下，`sys.path` 處理比照 `scorer_rule_sensitivity.py` 開頭的既有寫法）。
- 用 §1.1 的四組（或至少 S0／B0／B1 三組，`D` 選配）路徑呼叫 `load()`，組出 `arms: dict[str, list[dict]]`。
- 用 §1.2 的 `20260923_rebased/frozen_manifest.json::eligible_ids`（不是 `20260920_frozen` 那份）當題目範圍。
- 對每個 arm 的每筆 record，套用 `perfect_prime(r, tc, t=0.7)` 算出規則R重判結果，`meets_standard(r)` 算出原始判定，比照既有腳本「每題結論用該題有效執行的多數決」的規則（跟 `adaptive_repeat.py`／`t2_topk40_judgement.py`／既有 `scorer_rule_sensitivity.py` 一致，不要另外發明新的多數決邏輯）。
- **預設不套用 `--cand-fail`／`--require-qty`**（§1.4），但保留這兩個旗標的 CLI 介面以防之後需要（比照既有腳本的參數命名）。

### T2（M）：輸出規則R重判前後的並列比較

- 對 S0-vs-B0、S0-vs-B1（若含 D，也做 S0-vs-D）各輸出：原評分器達標題數、規則R重判後達標題數、新增題、退步題、淨差、exact McNemar p——格式比照既有 `scorer_rule_sensitivity.py::main()` 最後印出的表格，或用更適合寫進報告的表格形式，兩者擇一但要跟報告72既有章節（§9.2/§9.3）的表格風格一致，方便直接比對。
- **`--out`**：把每筆執行的原判定與規則R判定寫成 JSON（比照既有腳本的 `--out` 慣例），存到 `data/eval/candidate_runs/s3_rule_r_rejudge.json`（或你認為更合適的路徑，需在報告裡說明）。

### T3（S）：專項驗證報告78點名的兩題

明確檢查 `18-Q6`／`57-DIST2` 這兩題在規則R重判下，S0 K arm 的判定是否從「未達標」翻成「達標」——這是報告78 §10.6 GAP-S3-02 的具體假說，直接驗證比籠統看整體數字更有說服力。逐一寫出：這兩題的 `missing_spans`、答案文字、`overlap()` 算出的重疊分數、`flip()` 的三個條件（重疊≥0.7／數字都在／無否定詞）各自是否成立。

### T4（M）：結論——KG 相對 chunk-RAG 的落差，規則R下還剩多少？

把 T2 的結果對照報告72 §9.4 原本的結論（「目前沒有顯示 KG 相對於做得夠好的 chunk-RAG 有整體增益」）：

- 若規則R重判後，S0-vs-B1 的淨差顯著縮小或 McNemar `p` 不再顯著，明確寫「§9.4 的結論在規則R敏感度分析下不穩定，落差可能部分是評分器假陰性造成」。
- 若規則R重判後，淨差幾乎不變（規則R主要影響的是其他題、不是這 9 題落差的主因），同樣明確寫「§9.4 的結論在規則R下依然穩健」。
- **兩種結果都要如實寫，不要為了呼應報告78的假說而選擇性強調規則R讓落差變小的部分**——規則R也可能讓 B0/B1 自己的達標數一起往上調（因為規則R對三個arm都適用，不是只對S0有利），淨差不一定會縮小，需要實際算出來才知道。

---

## 3. 明確不要做的事

- **不要**修改 `services/atomic_scorer.py` 或任何 production 評分邏輯——規則R維持是離線診斷工具，不上線、不影響 `chat()` 或既有評測 harness 的預設行為。
- **不要**重跑任何評測 harness、不要呼叫 Neo4j 或 Ollama——所有需要的資料已經在 `data/eval/` 底下。
- **不要**修改 `scripts/eval/scorer_rule_sensitivity.py` 或 `scripts/eval/audit_scorer_disagreements.py` 本身（除非發現它們有明確的 bug 擋住本任務，若真的需要修改，要在報告裡說明改了什麼、為什麼，且不能影響這兩個檔案原本服務報告62 §14 的既有用途）。
- **不要**套用 `--cand-fail 57-AGGR18` 這類舊旗標到 S3 資料上（§1.4 已說明理由）。
- **不要**修改 `docs/論文/` 任何檔案。
- **不要**把規則R重判的結果拿去覆蓋報告72 §9 的原始數字——§9 保留原樣，本次結果是新增的 §11 對照分析，兩者並存。

## 4. 完成定義

1. 新腳本 `scripts/eval/s3_scorer_rule_sensitivity.py` 能正確執行，重用（import）既有函式，沒有複製貼上重複邏輯。
2. T2-T4 結果寫成新章節，附加進 `docs/報告/72_報告62殘留待辦新基準與K1b_T3_chunkRAG任務書.md`（新增 §11，比照既有 §6/§7/§9/§10 格式），不建立獨立報告檔案。
3. T3 對 `18-Q6`／`57-DIST2` 的專項驗證有明確結論，附具體數字（重疊分數等），不是只給「是/否」。
4. T4 的結論誠實反映規則R重判前後的實際差異，不論結果是否符合報告78的假說方向。
5. `git diff --stat` 應顯示：新增一個腳本檔案（`scripts/eval/s3_scorer_rule_sensitivity.py`）、一份新的 JSON 輸出（`data/eval/candidate_runs/s3_rule_r_rejudge.json` 或你選擇的路徑）、`docs/報告/72_...md` 的異動——沒有其他 production 程式碼或 `docs/論文/` 被改動。

---

## 5. 給 Codex 的指令（可直接貼上）

> 請執行 `docs/報告/79_S3評分器規則R敏感度分析SDD任務書.md` 的 T1-T4。這是純離線重算任務，不寫 production 程式碼、不重跑評測、不需要 Neo4j/Ollama——目的是用報告62 §14 已建立的規則R敏感度分析工具（`scripts/eval/scorer_rule_sensitivity.py`），重新評估報告72 §9 的 S3 對照結果（S0 K 13/42 vs B1 21/42，淨差 −8），看這個落差有多少是評分器表面形式假陰性造成的假象。
>
> 現有腳本 `scorer_rule_sensitivity.py` 是寫死指向舊的 `20260920_frozen` 基準跟舊的 T2 候選跑，**不能直接套用**——請新增一個腳本 `scripts/eval/s3_scorer_rule_sensitivity.py`，import（不要複製貼上）既有的 `flip()`／`perfect_prime()`／`meets_standard()`／`scope_ok()`／`load()`／`overlap()`，換成任務書 §1.1 列出的 S3 資料路徑（S0 用 `baseline_runs/20260923_rebased` 底下三個 stage，B0/B1 用 `candidate_runs` 底下對應的 `s3_chunk_rag_*_stage_*` 資料夾），`eligible_ids` 改用 `20260923_rebased/frozen_manifest.json` 那份（不是舊的 `20260920_frozen`）。
>
> **重點驗證項**：報告78 已指出 `18-Q6`／`57-DIST2` 疑似是評分器表面形式脆弱性（答案語意正確但逐字不符 gold span），請針對這兩題專項驗證規則R重判後是否翻盤，附具體重疊分數等證據（任務書 T3）。最後給出明確結論：規則R重判後，KG 相對 chunk-RAG 的落差還剩多少，報告72 §9.4「KG 沒有顯示整體增益」這個結論是否穩健——**不論規則R讓落差變大還是變小，都要如實寫出來，不要挑對報告78假說有利的方向強調**。
>
> 結果寫成新章節（§11）附加進 `docs/報告/72_報告62殘留待辦新基準與K1b_T3_chunkRAG任務書.md`，不要建立新報告檔案，也不要修改 `services/atomic_scorer.py` 或任何 production 評分邏輯（規則R維持離線診斷工具身分）。完成後確認 `git diff --stat` 只涉及新腳本、新 JSON 輸出、報告72 三處。commit 前不需要額外詢問，但 push 需要使用者另行同意。
