# 06：SVO 抽取管線調整任務書（累積進度與待辦）

> 狀態：🟡 進行中——本檔案彙整 2026-07-21 針對「3.1.1 之後、SVO 抽取正式開始之前」這段管線的討論與程式調整，供下次接續討論/實作時快速回顧現況，避免重新推導已定案的部分。
>
> 背景：使用者審視 `docs/論文/03_系統設計與方法論.md` 3.1.2 時，發現「標準化 Chunk 已就緒」（`CHUNKREADY`）是一個沒有畫出處理過程的「憑空產生」狀態，進一步追問後確認：① 3.1.1 現有的 RAG 切塊（`sentence_aware_chunking`，500 字元/50 重疊）不該被 SVO 抽取沿用，需要對原文重新設計獨立的切塊/標準化流程；② 這條新流程目前只有「標準化」本身有完整設計（3.4 §a），「切塊」與「原句子/標準化句子/Chunk 三者的關聯索引」都還是空白。本檔案記錄目前為止的調整與待辦。

---

## 1. 已完成的程式調整（依實作順序）

1. **`parser/core.py::split_into_sentences()`（新增）**——把原本分散兩處、規則不一致的句子切分邏輯（`sentence_aware_chunking()` 內嵌版 vs. `05_指代消解與前處理任務書.md` 自訂的 `SENTENCE_SPLITTER`）合併成單一共用函式，正則同時保留兩邊的規則（中日文標點＋分號＋刪節號＋換行，並排除縮寫 e.g./i.e./vs. 與小數點誤判）。`sentence_aware_chunking()` 改為呼叫它，不再重複邏輯。測試見 `tests/test_parser.py`（4 個新測試：基本切分、精確重組、縮寫/小數點防護、分號斷句）。

2. **`docs/報告/05_指代消解與前處理任務書.md`（校正）**——移除自訂的 `SENTENCE_SPLITTER`，改為呼叫 `parser.core.split_into_sentences()`；因為該共用函式刻意不 strip 個別句子（RAG 切塊需要保留原始間距做精確重組），指代消解管線自己的需求（乾淨句子）改用新增的 `split_and_clean_sentences()` 包裝函式處理。

3. **`parser/__init__.py`（新增）**——`parser/` 原本是隱式命名空間套件（無 `__init__.py`），改為一般套件，重新匯出對外公開介面（`DocumentParser`／`URLParser`／`sentence_aware_chunking`／`split_into_sentences`／`document_folder_path`／`write_chunks_as_markdown`／`write_original_text`／`ImagePipeline` 等）。理由是避免命名空間套件在 `sys.path` 上若出現同名目錄時被靜默合併的風險，非修 bug，屬主動補強。

4. **`parser/chunk_writer.py::write_original_text()`（新增）**——把解析完成、切塊之前的原始純文字另存一份至文件資料夾內的 `original.md`（固定檔名，重複處理同一 `source` 時直接覆寫）。動機：查證 `services/ingestion_service.py::chunk_and_stage()` 後發現，`parse_document()` 解析出的原文只是函式內暫時變數，切完 RAG chunk 後就丟棄、沒有落地存檔——若 SVO 流程要對原文重新處理，先前只能重新解析原始上傳檔案（掃描 PDF 需重跑 OCR，成本高）。測試見 `tests/test_chunk_writer.py`（4 個新測試）。

5. **`services/ingestion_service.py::chunk_and_stage()`（修改）**——接上 `write_original_text()` 呼叫，現在每次歸檔都會同時產出 `chunk-NNN-of-MMM.md`（RAG 用）與 `original.md`（原文備份）。測試擴充見 `tests/services/test_ingestion_service.py`。

以上五項全數通過測試（累計新增/擴充約 13 個測試案例，全套 165 項測試通過），已提交並推送至 `master`。

---

## 2. 已完成的論文文件調整（`docs/論文/03_系統設計與方法論.md`）

1. **拆分變更歷程與已取代設計方案至 `docs/論文/03_變更紀錄.md`**——章節開頭原本累積成上千字的流水帳，以及已被取代的滑動視窗草案（原 3.1.2 §a），移出主要閱讀路徑，正文只留一句連結。

2. **3.1 拆分為完整流程小節 3.1.1–3.1.4，確立「3.1 描述流程／3.x 描述 RQ 原理與文獻」的分工原則**：
   - 新增 **3.1.3 抽取過程**——原 3.3（RQ4a）的 Behavior Tree 與 `SVO_REL_TYPES` 事實描述搬入，作為純流程說明；3.3 保留「為什麼選受控詞彙」的理論動機與文獻佐證（Vashishth CESI、Schema.org、Wikidata），指回 3.1.3 看機制本身。
   - 新增 **3.1.4 抽取後續**——原本散落在 3.1 總覽圖與舊版 3.1.2 `WRITE` 節點的寫入知識圖譜/實體對齊去重步驟，集中展開；RQ4b 的 LLM 仲裁擴充（`ESCALATE`）與別名記錄（`surface_form`）維持在 3.4 §b，3.1.4 只做指標引用。
   - **RQ 對應維持不變**（3.2→RQ1/RQ2、3.3→RQ4a、3.4→RQ4b、3.5→RQ3、3.6→RQ6、3.7→方法論），未觸發連鎖章節重編號。

3. **3.1.2 補上 `GETORIG` 判斷節點，銜接「原文取得」與「SVO 專用切塊」的空白**：
   - 新增判斷：文件資料夾內是否已有 `original.md`？有就直接讀取，沒有才重新解析——並誠實標註 `REPARSE` 分支的侷限（查證 `routers/documents.py::upload_document()` 發現上傳來源的暫存檔在解析後即被刪除，「重新解析」實際上只有 URL 來源可行）。
   - 3.4 §a 圖同步校正：`RAW` 節點改指向 `original.md`／3.1.2 `GETORIG`；`COMBINE` 節點收尾從「進入 3.1.1 一般切塊流程」改為「交給 SVO 專用切塊（尚未定案）」。

4. **3.1.2／3.1.3 依「佇列生產者端／消費者端」重新分工**：
   - 3.1.2 只保留生產者端：資料夾搬移、記錄檔初始化/重新歸屬、`GETORIG`、`CHUNKREADY`、`ENQUEUE`，加上程式重啟的索引完整性檢查與恢復（`RESTART`／`TRUST`／`SCAN`／`REBUILD`——此分支本質是佇列索引本身的完整性問題，判定留在生產者端）。終點從「開始抽取」改為「佇列已就緒」。
   - 3.1.3 新增消費者端開頭：`WORKER`（挑出下一個 pending Chunk）→ `PROC`（狀態→processing），取代原本入口的「開始抽取」假設；同時移除重複的 `CHUNK[文字切塊]` 節點——Chunk 早在 3.1.2 的 `CHUNKREADY` 就已切好，3.1.3 不需要再切一次。
   - 3.1.4 兩處重試回退節點原本誤寫「回 3.1.2 WORKER」，已更正為「回 3.1.3 WORKER」。

以上調整皆已提交並推送至 `master`（共 4 次 commit，涵蓋文件重組、程式重構、圖表調整）。

---

## 3. 尚未定案、待討論的設計問題（建議依此順序討論）

### 3.1 SVO 專用切塊的演算法與粒度（🔴 最優先，其餘待辦多半依賴此項先定案）

3.4 §a 的 `COMBINE` 節點產出「依句子順序排列、已完成指代消解＋別名前處理的標準化全文」之後，要怎麼切成一個一個 SVO 專用 Chunk（登記進 `task_queue.db` 的最小單位）——目前完全空白。已明確排除的做法：直接沿用「前 4 後 2」（7 句）這個數字（那是代名詞消解的上下文視窗大小，跟切塊粒度是兩個不同參數，不可混用）。需要決定：切塊依句數、字數、還是其他規則；是否需要重疊；粒度大小是否需要留給第五章消融實驗校準（比照 `CLASSIFY_AUTO_THRESHOLD` 現行做法）。

### 3.2 原句子／標準化句子／SVO Chunk 的關聯索引設計（🟡 次優先）

使用者已確認一個關鍵設計原則：**RAG 檢索查找用原句子（`original.md`／`chunk-NNN-of-MMM.md`），SVO 抽取/圖譜查找用標準化後句子**——兩者是同一份文件的不同「版本」，各自獨立可查，不是同一份文字的兩種標記。因此登記進佇列時，不能只記 `chunk_index`/狀態，還需要記錄「這個 SVO Chunk 對應 `original.md` 的哪個句子範圍」，才能雙向追溯（從三元組找回原文、或反過來）。待決定：
- 具體資料結構——是否比照 `chunk-NNN-of-MMM.md` 的 YAML frontmatter 模式，在 SVO Chunk 檔案裡加欄位（例如 `source_sentence_range`）？
- 只存範圍索引，還是連原始/標準化兩份句子文字都各自存一份供直接比對？

### 3.3 標準化流程本身缺乏斷點續傳（🟡 次優先）

3.4 §a 的指代消解/別名前處理目前是「整份文件一次做完」才會產生 `CHUNKREADY`，中途沒有任何 checkpoint——若程式在標準化跑到一半（例如長文件跑到第 300 句）被中斷，重啟後只能整份重跑，跟 3.1.2/3.1.3/3.1.4 現有的五態斷點續傳保護等級不對等，兩者皆需要呼叫 LLM、皆有算力成本。待決定：
- 要不要幫標準化也做一套進度追蹤（例如以句子索引為單位的 checkpoint）？
- 追蹤資訊要記在哪——沿用同一份 `_record.json` 加欄位，還是獨立追蹤檔？（兩者生命週期不同：標準化是文件級一次性前處理，SVO 抽取可能因重新歸屬而重跑）

### 3.4 `SVOTriple` 追溯粒度不足（🟢 待 3.2 定案後一併處理）

目前 3.1.3 圖裡 `SVOTriple` 只有 `source_doc_id`（文件層級來源），若要支援「附來源標記的回答」（3.1 總覽圖問答流程已提及此功能）精確指回原文的特定句子而非整份文件，`SVOTriple` schema 需要擴充句子/chunk 層級的來源欄位——這項設計依賴 3.2 的關聯索引結構先定案，故排在其後。

---

## 4. 待實作項目（依賴上述設計定案，目前皆未動工）

- [ ] SVO 專用切塊函式（依 3.1 定案結果實作，可能落在 `parser/` 或新的 `services/svo_chunking.py`）
- [ ] 原句子/標準化句子/Chunk 關聯索引的寫入與讀取機制（依 3.2 定案結果）
- [ ] 標準化進度的 checkpoint 機制（依 3.3 定案結果，若決定要做）
- [ ] `SVOTriple` schema 擴充句子/chunk 層級來源欄位（依 3.4，待 3.2 完成後處理）
- [ ] `svo_service.py` 本體（目前仍為 stub，等待上述前置設計定案）

---

## 5. 相關檔案索引

| 檔案 | 角色 |
|---|---|
| `docs/論文/03_系統設計與方法論.md` § 3.1.1–3.1.4、3.4 | 本次調整的主要正文 |
| `docs/論文/03_變更紀錄.md` | 逐日變更歷程與已取代設計方案（含滑動視窗草案） |
| `docs/報告/05_指代消解與前處理任務書.md` | 代名詞消解機制的完整規格（3.4 §a 的一部分） |
| `docs/報告/06_SVO抽取管線調整任務書.md` | 本檔案 |
| `parser/core.py` | `split_into_sentences()`／`sentence_aware_chunking()` |
| `parser/chunk_writer.py` | `write_chunks_as_markdown()`／`write_original_text()` |
| `parser/__init__.py` | 套件公開介面 |
| `services/ingestion_service.py` | `chunk_and_stage()`，銜接 3.1.1 前段 |
| `services/document_record_service.py` | `_record.json` 讀寫，記錄檔真實狀態來源 |
