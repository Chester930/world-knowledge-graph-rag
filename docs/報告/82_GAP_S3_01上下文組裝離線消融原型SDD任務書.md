# 82 GAP-S3-01 上下文組裝離線消融原型SDD任務書（**交付 Codex，需呼叫本機 Ollama，不改 `chat()`**）

**建立日期**：2026-09-26
**文件性質**：交付 Codex 執行用任務書。**這是低成本的離線消融原型，不是報告58的完整架構實作**——不建立 `ContextBundle`、不動 `routers/agent.py::chat()`、不寫 Manifest source resolver。目的是先用最小成本驗證報告58的核心假說是否成立，再決定要不要投入那份報告的完整工程。
**分支／工作區**：`worktree-sdd-retrieval-comparison`，`D:\Users\666\Desktop\world knowledge graph rag\.claude\worktrees\sdd-retrieval-comparison`
**前置依賴**：報告78（S3落差題根因診斷）、報告58（雙軌上下文組裝設計，**設計未實作**）。2026-09-26 已用 ListAgents 確認無其他 session 同時使用 Neo4j/Ollama。

---

## 0. 一頁摘要

**為什麼要縮小範圍**：報告58 提出的「雙軌上下文組裝」（Fact清單邏輯摘要 + 原始法規段落並陳）架構完整，但該報告**自己已經誠實訂正過**——文獻佐證（KAG、Think-on-Graph 2.0、HippoRAG）都不是「加入原始段落必然有效」的控制變因消融證據，具體參數（提領上限3~5個chunk等）是未驗證的假設值。如果直接照報告58的完整規格實作（`ContextBundle`、Manifest source resolver、`chat()` 接線、config開關），是一次大工程投入，但**目前沒有任何證據顯示這個方向真的能修好報告78診斷出的失敗案例**。

**本任務要做的事**：用報告78已經診斷過的 5 題「Stage 3 生成端事實遺漏/抹平」案例（`18-Q1`／`18-Q6`／`57-AGGR14`／`57-COREF3`／`57-DIST2`——這 5 題已確認 gold span 對應的事實**確實在 K arm 的 prompt 裡**，只是被生成端遺漏或抹平），做一次**離線、最小成本**的消融：把這些題目原本的 K arm 事實清單 prompt，加上 B1（chunk-RAG）當時實際檢索到、且成功讓 B1 答對的**原始法規段落**，重新呼叫生成模型一次，看答案是否改善。**這不需要建立任何新的生產架構**——只需要重用已經存在的資料（S3 的 K arm prompt、B1 的 chunk 檢索結果）跟已經存在的函式（生成 provider、`AtomicScorer`）。

**如果這個小規模消融顯示明確改善**，才有理由投入報告58的完整工程（走另一個獨立任務書）；**如果沒有改善或效果不明確**，就此打住，不建立 `ContextBundle`，把結論誠實記錄下來，避免投入大工程做一個文獻與初步證據都不支持的方向。

---

## 1. 現況（已查證，供直接引用）

1. **報告58的完整設計不在本任務範圍**：`ContextBundle`、Manifest source resolver、`chat()` 的 `enable_chunk_augmentation` 開關全部**不要做**，那是報告58未來若要正式實作時的範圍，本任務只是前置的小規模驗證。
2. **B1 的 chunk 還原方法已有先例**：報告72 §11.1 已經示範過「B1 record 的 `stage2_context.prompt_context_lines` 本身為空，但 `stage1_retrieval.retrieved_chunk_ids` 已保留；用既有 `baseline_rag_index_236903cf-055a-40a8-8923-b9d06601f3b7_cs500.json` 按 chunk id 離線還原 B1 原始段落」——**直接沿用同一個方法**，不要重新設計還原機制。
3. **K arm 的既有 prompt 內容**：`data/eval/baseline_runs/20260923_rebased/stage_s0_r1*/records.json` 每筆 record 的 `lineage.stage2_context` 已包含 K arm 當時送進生成模型的完整事實清單（欄位名稱可能是 `prompt_context_lines` 或類似，**先自行確認實際欄位結構，不要假設**）。
4. **生成 provider 取得方式**：比照既有評測 harness 或 `routers/agent.py::chat()` 內部呼叫生成模型的既有模式（`core/providers/factory.py::get_llm_provider()`），沿用相同的 `qwen2.5:7b` 設定、相同的 `system_context`（`DomainConfig.system_context` 預設值），確保跟原本 K arm 生成時的條件一致，只換上下文內容本身。
5. **評分方式**：`services/atomic_scorer.py::AtomicScorer` 已有 `evaluate()`／`evaluate_async()`，直接重用來對新答案評分，不需要透過完整評測 harness。

---

## 2. 任務清單

### T1（M）：組出「K + C」新 prompt

對 5 題（`18-Q1`／`18-Q6`／`57-AGGR14`／`57-COREF3`／`57-DIST2`），各自：

1. 從 S0 K arm 對應 record 取出原始事實清單 context（現況 §1.3）。
2. 用報告72 §11.1 的方法（現況 §1.2），從 B1 對應 record 的 `retrieved_chunk_ids` 還原出 B1 實際用到的原始法規段落文字。
3. 組出新 prompt：**保留 K arm 原本的事實清單區塊不變**，額外新增一個區塊（比照報告58 §2.2 格式，但只需要陽春版，不用做花俏排版）：
   ```
   === 依據法規原文段落 ===
   【參考段落】（來源：<document/chunk 識別資訊>）
   <B1 還原出的段落文字>
   ```
4. **只加 1 個最相關的段落**（B1 該題實際用到、排名最高或唯一的那個 chunk），不要按報告58原稿的「3~5個」設計值——本任務是最小驗證，不是要重現報告58的完整提領策略，範圍越小越容易判讀因果。

### T2（M）：重新生成並記錄

- 用相同的生成 provider／模型／`system_context`，把 T1 組出的新 prompt 送進去，取得新答案。
- 每題至少跑 **2 次**（同一題重複，因為報告26已載明 `qwen2.5:7b` temperature 0 不保證決定性），記錄每次的完整答案原文。
- **不要**修改任何 production 程式碼來做這件事——直接寫一個一次性腳本（`scripts/eval/gap_s3_01_context_ablation.py` 或你認為合適的檔名），呼叫既有 provider 函式，不要繞道改 `routers/agent.py`。

### T3（S）：離線評分並比較

- 用 `AtomicScorer.evaluate()`（或 `evaluate_async()`）對每次新答案評分，用跟 S3 相同的 gold `missing_spans` 當比對目標。
- 逐題列出：K arm 原答案（is_perfect / missing_spans）→「K+C」新答案（is_perfect / missing_spans，每次重複分別列出）。
- 明確標註：這題原本缺失的 span，在「K+C」條件下是否被答案涵蓋。

### T4（S）：附帶檢查——有沒有新的副作用

- 檢查「K+C」新答案有沒有新增報告58原始設計擔心的風險：答案長度暴增、對段落內容的其他部分產生幻覺、或者因為多了一大段原文而導致答案結構變得雜亂難讀。**不需要正式的量化指標**，人工看過 5 題 × 2 次的答案，簡短記錄有沒有觀察到這類副作用。

### T5（M）：結論——值不值得投入報告58的完整工程

- 彙整 5 題結果，給明確判定：「K+C」相對「K」，這 5 題裡有幾題的原本缺失事實被補上了？
- **如果多數題目有改善且沒有明顯副作用**：明確建議「值得排一個獨立任務書，依報告58規格縮小範圍做正式的 `ContextBundle` 實作與完整消融」。
- **如果改善有限、不一致、或伴隨明顯副作用**：明確建議「目前證據不支持投入報告58的完整工程，此方向擱置，除非有新證據」。
- **兩種結論都要如實寫**，樣本只有 5 題 × 2 次，不能誇大成定論，但足以當作「要不要繼續投入」的初步判斷依據——比照這次一路下來的紀律（報告76/77/79/81 皆同）。

---

## 3. 明確不要做的事

- **不要**建立 `ContextBundle`、Manifest source resolver、或任何報告58 §3 描述的正式架構。
- **不要**修改 `routers/agent.py::chat()`——所有新的生成呼叫都在獨立腳本裡做，不接線進生產路徑。
- **不要**修改 `services/atomic_scorer.py`、`services/retrieval_service.py`、`services/svo_service.py`——只讀取、重用既有函式。
- **不要**對任何 KG 執行重抽或寫入 Neo4j——B1 的段落還原完全走離線 JSON（既有 `baseline_rag_index_*.json`），不需要即時查 Neo4j。
- **不要**擴大測試題目範圍到 5 題以外——這是刻意縮小的驗證範圍，不是要重現報告58的完整 K vs K+C 消融（那需要 42 題全跑，成本高很多，等這個小規模原型有明確訊號再考慮）。
- **不要**修改 `docs/論文/`——本次是純驗證原型，是否回灌論文留待後續決定。

## 4. 完成定義

1. 5 題 × 2 次「K+C」重新生成與評分結果完整記錄。
2. T5 的判定明確、不迴避，附具體題數證據。
3. 結果寫成新章節，附加進 `docs/報告/72_報告62殘留待辦新基準與K1b_T3_chunkRAG任務書.md`（新增 §13），不建立獨立報告檔案。
4. `git diff --stat` 只顯示：新腳本、（若有）新的中間資料輸出檔、報告72 一處——沒有 `routers/agent.py`、`services/atomic_scorer.py`、`docs/論文/` 被觸碰。
5. **不需要**、也**不應該**對任何 KG 執行重抽或改變 Neo4j 資料。

---

## 5. 給 Codex 的指令（可直接貼上）

> 請執行 `docs/報告/82_GAP_S3_01上下文組裝離線消融原型SDD任務書.md` 的 T1-T5。這是報告58「雙軌上下文組裝」設計的最小成本驗證原型，**不是完整架構實作**——不建立 `ContextBundle`，不動 `routers/agent.py::chat()`，只用一個獨立腳本測試核心假說：把 B1（chunk-RAG）成功還原出的原始法規段落，加進 K arm（KG）原本的事實清單 prompt 裡，重新生成一次，看報告78診斷出的 5 個生成端遺漏案例（`18-Q1`／`18-Q6`／`57-AGGR14`／`57-COREF3`／`57-DIST2`）是否因此改善。
>
> B1 段落還原方法沿用報告72 §11.1 已經示範過的做法（`baseline_rag_index_236903cf-055a-40a8-8923-b9d06601f3b7_cs500.json` 按 `retrieved_chunk_ids` 離線還原），不要重新設計。每題只加 1 個段落（不是報告58原稿的3~5個），每題重複生成 2 次，用既有 `AtomicScorer` 離線評分。
>
> 最後給出明確、不迴避的結論：這 5 題的初步結果值不值得投入報告58的完整工程？如果改善有限或不一致，要如實寫「目前證據不支持投入」，不要為了讓任務有個好交代就誇大訊號。
>
> 結果寫成新章節（§13）附加進 `docs/報告/72_報告62殘留待辦新基準與K1b_T3_chunkRAG任務書.md`，不要建立新報告檔案，不要修改 `routers/agent.py`、`services/atomic_scorer.py` 或 `docs/論文/`。開工前用 ListAgents 確認沒有其他 session 同時使用 Neo4j/Ollama。完成後確認 `git diff --stat` 範圍正確。commit 前不需要額外詢問，但 push 需要使用者另行同意。
