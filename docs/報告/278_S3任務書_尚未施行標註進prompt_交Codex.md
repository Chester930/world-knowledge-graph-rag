# 報告 278：S3 任務書——「尚未施行」標註進 prompt（交 Codex，含交接指令）

> 規劃對話，2026-10-04。依據：報告 276（暴露量測）、277（評測題與採用規則，使用者已同意）、271/275（S2/S2b）。
> **硬規則**：KG#4（`kg2-neo4j`，bolt 17990）執行者不得連線／操作 docker／Ollama／`.env`；全程離線測試；不 push、不 merge；報告編號自下一個空號起（本報告為 278，Codex 用 279+）；commit 結尾加 `Co-Authored-By` 行並只 add 明確路徑。論文不動。

## 0. 目標與邊界

在 `_build_prompt` 加一段**選填、預設關**的「尚未施行提示」，讓模型知道 prompt 內證據中哪些條文／附表已公布但尚未施行。**不排除任何證據、不改檢索、不改排序**。

- 新旗標：`PROMPT_EFFECTIVE_NOTES`（`core/config.py` 的 `Settings`，預設 `False`；與 `TRACE_SEMANTIC_MARKS` 獨立）。
- **旗標關＝與現況 bit-identical，且零額外查詢**（比照 S2）。
- 只標註 `pending_whole`、`pending_partial`；`in_force`／`no_information`／`INDETERMINATE` 不出現在提示中（避免對照題 C 類被誤導）。勞動契約法（文件層 undetermined）本階段**不加提示**。

## 1. 任務

### T1 資料來源重用（不新增查詢型別）
S2b 已有 `_fetch_article_effective_inputs`、`article_effective_marks`、`effective_marks_kwargs`（`routers/agent.py`、`services/context/trace_marks.py`）。S3 重用之：旗標開啟時，即使 `include_retrieval_trace=False` 也要算 marks；失敗隔離（try/except，失敗＝不加提示、不影響回答、log 一行）。

### T2 純函式 `build_effective_note_block(marks, locators…) -> str`
放 `services/context/trace_marks.py`（或新 `services/context/effective_prompt.py`，純函式、僅 stdlib）。輸入：prompt 內證據對應的條文層 marks。輸出：空字串（無 pending）或一段文字，格式固定：

```
【施行狀態提醒】下列條文已公布但尚未施行，回答時請註明其施行日，不要當成現行有效規定：
- 勞工健康保護規則 第 13 條（第 3 項）：自 2027-07-01 施行
- 勞工健康保護規則 第 21 條：自 2028-01-01 施行
```
- 同一文件條文去重、依條號排序；`pending_partial` 附 `locators`（項／附表）；`pending_whole` 不附括號。
- 措辭中性，不寫「無效」「廢止」。**只列實際進 prompt 的證據所屬條文**（用 `_build_prompt` 的 `trace_sink`／`in_prompt` 判定，不得把未進 prompt 的條文列入）。

### T3 接進 `_build_prompt`
新增選填參數 `effective_note: str | None = None`；非空時把該區塊置於 `context_block` 之後、`history_block` 之前。`None`/空字串＝輸出與修改前逐位元相同（需有 differential 測試，對照 `git show fd80972:routers/agent.py` 的舊函式，隨機輸入 ≥200 組）。`_build_constrained_prompt` 本階段**不動**。

### T4 `chat()` 接線
旗標開 → 算 marks → 以 T2 組字串 → 傳 `effective_note`。旗標關 → 路徑不呼叫任何新函式、不多任何查詢（測試用 mock 計數驗證）。

### T5 評測題入庫（`data/eval/s3_effective_questions_20261004.json`）
照報告 277 §2 的 8 題（S3-A1…D1），格式比照 `data/eval/pilot_time_questions.json`。欄位含 `id`、`category`（A/B/C/D）、`question`、`expected_behavior`、`gold_dates`（A 類只填 `effective_note` 已載明的日期）。**B/C 類的 `gold_points` 一律留 `null`，由規劃對話對照官方條文填寫——執行者不得自行編造法規內容**。另加 `adoption_rule` 欄，逐字複製報告 277 §3。

### T6 測試與驗收
- 離線單元測試：block 純函式（空／僅 partial／僅 whole／混合／去重排序／locators）、旗標關 bit-identical、失敗隔離、旗標開不影響 `fact_results` 與檢索輸出。
- AST 守衛：新純函式模組只允許 stdlib；零接線 grep（旗標關時無新呼叫）。
- 全部 pytest、node 卡片、secret 掃描通過。
- 執行紀錄寫成新報告（279 起），列：改動檔、測試數、旗標關差分結果、未做事項、遇到的停止條件。

## 2. 停止條件（遇到即停、寫停止紀錄，不自行放寬）
1. 需要連 KG#4／docker／Ollama 才能完成。
2. 無法在不改檢索下判斷「哪些條文實際進 prompt」。
3. 旗標關時發現任何輸出差異。
4. 需要修改 `_build_constrained_prompt`、檢索、排序、`.env`。

## 3. 規劃對話驗收（Codex 完成後我做）
差分／隨機等價、KG#4 唯讀端到端（用 S2b 同一批 21 條確認提示列出的條文＝真實 pending 且皆在 prompt）、pytest 全跑、秘密掃描；之後才跑 8 題 A/B 臂評測（需使用者同意開跑，Ollama 由我協調）。

## 4. 交接指令（請整段貼給 Codex）

```
你是執行者（Codex）。請讀 docs/報告/278_S3任務書_尚未施行標註進prompt_交Codex.md，依 T1–T6 實作。
重點：旗標 PROMPT_EFFECTIVE_NOTES 預設關，關閉時與現況 bit-identical 且零額外查詢；只標註 pending_whole/pending_partial，不排除證據、不改檢索；不動 _build_constrained_prompt；B/C 類 gold_points 留 null，不得自行編造法規內容。
硬規則：不得連 KG#4／docker／Ollama／.env；不 push／merge；commit 只 add 明確路徑並加 Co-Authored-By 行；報告編號自 279 起；遇 §2 停止條件即停並寫停止紀錄。
完成後把最終報告貼回給我。
```
