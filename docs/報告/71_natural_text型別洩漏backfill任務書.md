# 71 natural_text型別洩漏backfill任務書（交付Codex）

**建立日期**：2026-09-23
**文件性質**：任務書，交付 Codex 執行，完成後由 Claude Code 複驗。
**觸發脈絡**：[報告67](67_事實自然語言化品質問題SDD任務書.md) T1-T3已修好`_naturalize_triple()`／`_TYPE_MARKER_RE`的型別標記洩漏成因（commit `7ed651d`／`6bc644e`），T4唯讀估算KG#4（`236903cf-055a-40a8-8923-b9d06601f3b7`）有**96/11,011筆（0.87%）**帶`natural_text`的邊仍殘留修法前的洩漏內容（部分案例嚴重，例如整句崩壞、型別詞取代主詞）。報告67明確標注「本次只完成統計，不執行backfill，需要使用者另外決定」。本任務書把backfill決策落地成可執行、可審查的兩階段流程。

---

## 0. 一頁摘要

**目標**：對受影響的KG邊，用修法後的`_naturalize_triple()`重新產生`natural_text`並回填，同時先確認**除了KG#4以外，其他production KG是否也受同一個共用程式碼的bug影響**（報告67 T4只掃描了KG#4）。

**兩階段設計，寫入是不可逆的KG資料異動**：
- **階段A（唯讀）**：擴大掃描範圍到所有production KG，產出dry-run diff報告（受影響筆數、before/after樣本），**不寫入**。
- **階段B（寫入，需明確核准後才執行）**：只在階段A報告經人工抽驗確認合理後才執行，採批次＋交易安全＋完整前後值稽核紀錄。

---

## 1. 現況（已查證，供直接引用）

1. `_naturalize_triple()`（`services/svo_service.py:1740`）已修法：`_naturalization_leaked_type_marker()`核對「型別標記洩漏」，命中時退回`_verbalize_fact()`樣板拼接（不會再洩漏）。`routers/agent.py::_TYPE_MARKER_RE`也已修好裸字分支缺開頭邊界的bug（`6bc644e`）。
2. 報告67 T4只掃描了**KG#4**（`236903cf-055a-40a8-8923-b9d06601f3b7`）。本專案已知還有其他production KG（例如`c15949bf`系列舊KG、勞動基準相關示範KG——實際清單需在T0查詢Neo4j `dbms.listDatabases()`或既有`core/database.py`的KG管理介面確認，不要憑記憶假設）。
3. `_naturalize_triple()`是**共用程式碼**（沒有per-KG分支），理論上洩漏bug在所有曾經用這個函式產生`natural_text`的KG上都可能發生，不是KG#4特有。
4. 既有可參考的backfill模式：`backfill_fact_text_embeddings()`（先前報告的既有函式，具體位置需T0時用Grep確認）——「唯讀先篩選、再視使用者決定要不要回填」的批次工具設計慣例。

---

## 2. 任務清單

### T0（S，先決）：確認production KG清單與掃描範圍

- 查詢目前系統實際存在的KG清單（哪些是production KG、哪些是過期／測試用途），不要只憑`.env`或報告記憶假設。
- 對每個production KG統計「有`natural_text`欄位的邊」總數，作為階段A的掃描母體。

### T1（M，唯讀）：全KG範圍dry-run掃描＋重新產生對照

- 比照報告67 T4的做法，對T0列出的**所有**production KG的每一筆帶`natural_text`的邊套用`_naturalization_leaked_type_marker()`，找出受影響筆數。
- 對每一筆受影響的邊，**離線重新呼叫**修法後的`_naturalize_triple()`（用該邊既有的`subject`/`predicate`/`object`/`subject_type`/`object_type`等既有欄位重建輸入，不需要重新呼叫LLM抽取，只重跑自然語言化這一步；若欄位不足以重建輸入，如實記錄「無法重建，需另案處理」，不要臆測填空），產生**建議的新`natural_text`**，但**不寫入**。
- 輸出dry-run報告（建議放`data/eval/naturalization_backfill_dryrun_<日期>/`，比照專案既有`data/eval/`存放慣例）：每KG受影響筆數、全部受影響案例的(邊ID、舊文字、新文字)清單（不只是樣本，因為96筆規模不大，全量列出成本低，抽驗更完整）、以及新文字仍無法通過`_naturalization_leaked_type_marker()`核對的殘留案例（若有，代表這批邊本身有更深層問題，需要另案處理而非直接backfill）。

### T2（S，明確待人工核准，**不要自動執行**）：實際backfill寫入

- **前置條件（必須先滿足才能執行）**：使用者或Claude Code已審閱過T1的dry-run報告並明確核准。**本任務書本身不構成執行T2的核准**——T1完成後應先回報，停下等待，不要接著自動做T2。
- 核准後，比照`backfill_fact_text_embeddings()`既有模式寫一支批次寫入工具：
  - 逐筆更新前先重新讀取當下的邊資料（避免覆蓋掉T1掃描之後、backfill執行之前這段期間可能發生的其他異動）。
  - 每筆更新前後值都寫進稽核紀錄檔（JSON，含時間戳、邊ID、KG ID、舊值、新值），供事後可追溯、必要時人工逐筆核對。
  - 批次執行，允許中斷續跑（比照`scripts/kg/reextract_chunks.py`的「讀回佇列狀態」精神，不要用「N/N成功」這種不可信的自我回報，backfill後應重新查詢Neo4j確認寫入值與稽核紀錄一致）。
  - 執行前對目標KG做輕量備份確認方式（例如確認Neo4j有既有的備份/快照機制，或至少確認稽核紀錄本身足以支援還原，因為Neo4j本身沒有簡單的單筆屬性復原機制）。

---

## 3. 明確不做的事

- **T1只做唯讀掃描與離線重算，不寫入任何KG**。
- **T2在未經明確核准前不得執行**——這是不可逆的KG資料異動，即使報告67已經技術上「知道怎麼修」，仍需要一次獨立的人工／Claude Code審閱關卡。
- **不臆測重建輸入**——若某筆邊的既有欄位不足以重跑`_naturalize_triple()`（例如`subject_type`/`object_type`缺漏），如實標記「無法安全重建」並跳過，不要用猜測值硬套。
- **不修改`_naturalize_triple()`或`_TYPE_MARKER_RE`本身**——報告67已經修好，本任務書只處理既有資料的回填，不重新開放程式碼變更範圍。
- **不擴大到KG之外的其他資料**（例如不動`docs/`論文文字、不動題庫）。

---

## 4. 驗收標準

1. T0產出的KG清單與掃描範圍有明確依據（查詢紀錄或指令輸出），不是憑空列舉。
2. T1的dry-run報告完整、可稽核，每筆受影響邊都有舊文字／新文字對照，且新文字都已重新通過`_naturalization_leaked_type_marker()`核對（或明確標記為無法重建）。
3. T1完成後**停在這裡回報**，不自動進入T2。
4. 若使用者事後核准T2並執行，稽核紀錄檔完整，且backfill後重新查詢確認Neo4j實際值與稽核紀錄一致。

---

## 5. 給 Codex 的指令（可直接貼上）

> 請執行 `docs/報告/71_natural_text型別洩漏backfill任務書.md` 的T0-T1（**T2明確不要自動執行，做完T1回報後停下等待核准**）。背景：報告67已修好`_naturalize_triple()`／`_TYPE_MARKER_RE`的型別標記洩漏bug（commit `7ed651d`／`6bc644e`），並唯讀估算KG#4有96/11,011筆（0.87%）帶`natural_text`的邊受影響，但**只掃描了KG#4一個KG**，而bug所在的`_naturalize_triple()`是所有KG共用的程式碼。**T0**：先查詢目前系統實際存在哪些production KG（不要假設，用Neo4j查詢或既有KG管理介面確認），統計每個KG有`natural_text`欄位的邊總數。**T1**：對T0列出的所有KG套用`_naturalization_leaked_type_marker()`找出受影響邊，對每一筆離線重新呼叫修法後的`_naturalize_triple()`用既有欄位重建輸入產生建議新文字（**不寫入KG**，只是離線計算），輸出到`data/eval/naturalization_backfill_dryrun_<日期>/`：每KG受影響筆數、全部受影響案例的(邊ID、舊文字、新文字)完整清單、以及重算後仍無法通過核對的殘留案例（如有）。若某筆邊欄位不足以安全重建輸入，如實標記跳過，不要臆測填空。**全程只讀查詢Neo4j，不執行任何寫入**。完成T1後，回報統計摘要（各KG受影響比例、幾個嚴重案例範例）並**明確停下**，不要自動接續執行寫入backfill（那是T2，需要另一輪明確核准）。
