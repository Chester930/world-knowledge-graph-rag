# KG 來源回取「召回優先」離線探測 SDD 任務書 v0.1（**交付 Codex；唯讀、離線、不呼叫任何 LLM、不改 `chat()`**）

> **日期**：2026-09-30
> **性質**：交付 Codex 執行用任務書。**尚未編號**（報告 146 已預留給報告 145 的成果；由主流程在派工時指派編號）。
> **基準 commit**：`e40e512` 之後的 `worktree-sdd-retrieval-comparison`。
> **來源**：使用者 2026-09-30 對 KG 兩種回覆模式的說明（見 [BT_SM節點化結構設計草案_v0.1](BT_SM節點化結構設計草案_v0.1.md) §3.6）。
> **與報告 82 的關係**：報告 82（GAP-S3-01）只把「B1 檢索到的、且包含缺失答案片段的 chunk」附加到 K 的事實清單，**選段時參考了缺失的 gold span，且來源不是 KG**，因此**沒有測到「KG 關係取回來源原文」**。本任務書是第一個直接測這件事的探測，且**只量檢索召回，不做生成**。

---

## 0. 一段話說明目標

使用者的設計：**預設由 KG 返回精練的原文組合，交給模型分析；只有多跳超出模型負荷時，才用 KG 邏輯鏈作答。** 這個設計成立的第一個前提是：**把 K 已檢索到的事實對應回它的來源原文後，能否比 K 現行的事實文字、以及 B1 的 chunk 檢索，取回更多 gold 原子事實？** 這個問題只需要量 **Context Recall**，不需要生成。

## 1. 已核對的資料現況（Claude 於 2026-09-30 核對）

| 項目 | 事實 |
| --- | --- |
| K 凍結記錄 | `data/eval/baseline_runs/20260923_rebased/stage_s0_r1/`、`stage_s0_r1_resume1/`、`stage_s0_r2/` 各有 `records.json`（合計 75 筆，42 題，部分題目多 run） |
| K 的 `retrieval_trace` | 位於 `record["lineage"]["stage1_retrieval"]["retrieval_trace"]`；每筆候選欄位為 `kind`（`fact`／`triple`）、`rank`、`text`、`score`、`source_doc_id`、`source_svo_chunk_index`、`article_no`、`in_prompt` |
| ⚠️ K 的 `retrieved_chunk_ids`／`retrieved_fact_ids` | **全是空字串**，不可用；一律改用 `retrieval_trace` |
| B1 記錄 | `data/eval/candidate_runs/s3_chunk_rag_b1_stage_*/records.json`（67 筆）；`stage1_retrieval.retrieved_chunk_ids` 為如 `N0030006_勞工請假規則_0` 的 chunk id |
| B1 索引 | 根目錄 `baseline_rag_index_236903cf-055a-40a8-8923-b9d06601f3b7_cs500.json`（chunk 文字），**不得搬移或修改** |
| 既有召回計算 | `services/lineage_tracker.py`（約 90–150 行）以 gold `exact_span` 是否出現在檢索文字中判定 `hit_exact_spans`／`recall_rate`；本任務**必須重用同一判定邏輯**，不得另寫 |
| 題庫 | 以 `data/eval/baseline_runs/20260923_rebased/frozen_manifest.json` 記錄的題庫雜湊為準（65 題題庫，凍結 42 題）；每題有 `scenario_type` 與 gold `exact_span` |

## 2. 任務

### T1：建立來源解析器（只讀）

把 K 的每筆候選對應到「來源原文段落」：

1. 以 `source_doc_id`（UUID5）找到文件資料夾（使用既有 `services/document_record_service.py` 的 `document_uuid`／`resolve_document_folder`，**不得自行推導路徑**）。
2. 有 `article_no`（法規條文感知切塊）者：取該條文的原文；否則以 `source_svo_chunk_index` 取 `svo_index.json` 對應 chunk 的文字。
3. 無法解析的候選**不得靜默略過**：計數並在報告列出（依題、依原因）。
4. **解析結果需去重**（同一文件同一 chunk／條文只算一次），並保留「首次出現的 K 排名」以維持排序。

### T2：三個檢索面向的召回比較（全離線）

對凍結 42 題（每題取 run 1；若缺 run 1 則取最小 run 並註明），計算下列面向，各自以**既有判定邏輯（重用 `lineage_tracker`）**算 `recall_rate`、`hit_exact_spans`、`missed_exact_spans`、`retrieved_char_count`、SNR：

| 面向 | 檢索文字 | 說明 |
| --- | --- | --- |
| **R0** | K 現行：`in_prompt=true` 的候選 `text` | **必須重現記錄中既有的 `recall_rate`**（驗證用，容許 0 差異；若有差異須說明原因） |
| **R1** | K 候選 → 來源原文（T1），依首次出現排名取前 m 個**相異來源段落** | m 取 **3、5、8** 三種；**另加「字元預算對齊 B1」版本**：累加到不超過該題 B1 記錄的 `retrieved_char_count` 為止 |
| **R2** | B1 現行：`retrieved_chunk_ids` 對應的 chunk 文字 | 重現記錄的 `recall_rate` |
| （選配）**R3** | R0 ∪ R1（事實清單加來源段落，對應「both」模式） | 只在 R1 有明顯訊號時才做 |

**硬性約束**：

- **不得以 gold `exact_span` 參與任何選段**（報告 82 的偏誤）。R1 的取捨只准依 K 的排名與去重。
- **必須並列字元量**：來源原文比事實文字長，召回較高是預期的；比較意義在於「相同字元預算下」的召回與 SNR，所以每個面向都要報 `retrieved_char_count`，並給出**預算對齊**的比較。

### T3：分題型與逐題拆解

1. 依 `scenario_type`（Type-A～E）彙總各面向的：平均 `recall_rate`、`recall_rate==1.0` 的題數、平均字元數、平均 SNR。
2. **重點題型**：Type-C（跨文件多跳）、Type-D（全域聚合）——K 的失敗多屬「檢索失敗」（Stage 1），這是使用者設計中「多跳才升級邏輯鏈」的關鍵區域。
3. 逐題列出三種名單：
   - **R1 補回、R0 漏掉**的 gold span（附題號、span、來源段落所在文件／chunk）；
   - **R1 與 R2 都漏掉**的 gold span；
   - **R2 補回、R1 漏掉**的 gold span。
4. 若 R1 比 R0 有補回，**分析補回的機制**：補回的 span 是否在「已檢索候選所屬的同一 chunk／條文」內？（預期機制：事實檢索命中一個，來源段落連帶帶出同段的其他事實。）

### T4：結構訊號描述統計（**只描述，不擬合門檻**）

為「多跳超出負荷」的偵測預備資料，**只做描述**：

- 對每題計算：`in_prompt` 候選涵蓋的**相異 `source_doc_id` 數**、前 20 名候選的相異文件數、`kind=triple` 與 `kind=fact` 的比例。
- 依 `scenario_type` 與「K 是否達標」列出這些數值的分布（最小／中位／最大）。
- **禁止**：訂定門檻、訓練分類器、依題庫題號寫規則（避免重蹈 Type-C 規則過擬合）。只需回答：「這些訊號與題型、達標之間**看起來**有沒有關聯」，樣本小，措辭須保守。

### T5：誠實結論

依預先設定的判準給出結論（**兩種結論都要如實寫**）：

- **支持投入 KG 來源回取的正式設計**：R1 在預算對齊下，整體或 Type-C／D 的 `recall_rate==1.0` 題數**明顯多於** R2（B1），或明顯多於 R0 且 SNR 沒有大幅下降。
- **不支持／不明確**：R1 在預算對齊下不優於 R2，或只是靠更多字元換來的召回。
- **本探測的天花板**：只測「K 現有檢索結果對應回來源」，**沒有模擬「以關係遍歷取得更多相關來源」**（那是更強的模式二），因此是**下界**而非上界。此限制須寫進結論。

## 3. 產出

| 產出 | 位置 |
| --- | --- |
| 一次性腳本 | `scripts/eval/kg_source_recall_probe.py`（唯讀；不改 production 程式） |
| 完整輸出 | `data/eval/candidate_runs/kg_source_recall_probe/`（逐題、逐面向 JSON，含無法解析候選清單） |
| 測試 | `tests/scripts/test_kg_source_recall_probe.py`：至少涵蓋來源解析器（含 `article_no` 與 `source_svo_chunk_index` 兩種路徑、去重、無法解析的計數）與 R0／R2 重現既有 `recall_rate` 的驗證 |
| 結果 | 寫回**本任務書末尾「結果」節**，格式比照報告 82／72 §13：方法、表格、逐題名單、結論 |

## 4. 禁止事項

- **不得**呼叫任何 LLM／embedding provider、不得連線 Neo4j 寫入、不得重跑 K 或 B1 檢索。
- **不得**修改 `routers/agent.py`、`services/`（含 `lineage_tracker.py`）、評分器、題庫、任何既有資料檔；只能新增腳本、測試與輸出資料夾。
- **不得**移動根目錄的 `baseline_rag_index_*`。
- **不得**用 gold span 參與選段；**不得**擬合門檻或依題號寫規則。
- 工作區若有他人未提交的檔案（例如 `services/retrieval/`、`tests/services/test_retrieval_scope.py`），**不得 `git add` 它們**；commit 只加入自己新增的檔案。
- 不要用 `git add -A`／`git add .`。

## 5. 驗收（Claude 將獨立複驗）

1. 重現：R0、R2 的 `recall_rate` 與記錄逐題相同。
2. 抽樣重算：隨機 5 題，手動追溯 R1 的來源段落並核對 gold span 命中。
3. 檢查「無 gold 參與選段」：讀腳本確認。
4. 預算對齊版本的字元上限是否確實逐題套用。
5. 完整 pytest 回歸不下降（目前基準 1344，另有進行中對話可能改變基準，以驗收時為準）。

## 6. 交接指令（貼給 Codex）

> 請執行 `docs/報告/任務書_KG來源回取召回優先探測_v0.1.md` 的 T1–T5。這是**唯讀、離線**的探測：不呼叫任何 LLM、不改 production 程式、不動根目錄索引檔。核心是用 `lineage.stage1_retrieval.retrieval_trace`（K 的 `retrieved_*_ids` 是空字串，不可用）把 K 的候選對應回來源原文，在**預算對齊**下比較 K／來源回取／B1 的召回，**不得用 gold span 選段**。無法解析的候選要計數列出，不可靜默略過。結論兩種都要如實寫，並註明本探測只是「K 現有結果對應回來源」的下界。完成後把結果寫回任務書末尾的「結果」節，commit 時只加你新增的檔案，不要 `git add -A`。

---

## 結果

（待 Codex 填寫）
