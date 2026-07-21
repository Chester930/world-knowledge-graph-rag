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

6. **`parser/chunk_writer.py::write_sentences_index()`（新增）**——把 `split_into_sentences()` 對原文切分出的句子清單另存成文件資料夾內的 `sentences.json`（固定檔名，重複處理同一 `source` 時直接覆寫）。動機：句子切分雖是純規則運算、隨時可重算，但若切分規則日後調整，之前存的「第 N 句」索引會對不上重算後的邊界；存一份穩定清單供 3.4 §a 與未來的斷點續傳/SVO Chunk 對應索引引用，避免下游各自重算。`chunk_and_stage()` 已接上此呼叫。測試見 `tests/test_chunk_writer.py`（4 個新測試）與 `tests/services/test_ingestion_service.py`（擴充）。

以上六項全數通過測試（累計新增/擴充約 17 個測試案例，全套 169 項測試通過），已提交並推送至 `master`。

---

## 2. 已完成的論文文件調整（`docs/論文/03_系統設計與方法論.md`）

1. **拆分變更歷程與已取代設計方案至 `docs/論文/03_變更紀錄.md`**——章節開頭原本累積成上千字的流水帳，以及已被取代的滑動視窗草案（原 3.1.2 §a），移出主要閱讀路徑，正文只留一句連結。

2. **3.1 拆分為完整流程小節 3.1.1–3.1.4，確立「3.1 描述流程／3.x 描述 RQ 原理與文獻」的分工原則**：
   - 新增 **3.1.3 抽取過程**——原 3.3（RQ4a）的 Behavior Tree 與 `SVO_REL_TYPES` 事實描述搬入，作為純流程說明；3.3 保留「為什麼選受控詞彙」的理論動機與文獻佐證（Vashishth CESI、Schema.org、Wikidata），指回 3.1.3 看機制本身。
   - 新增 **3.1.4 抽取後續**——原本散落在 3.1 總覽圖與舊版 3.1.2 `WRITE` 節點的寫入知識圖譜/實體對齊去重步驟，集中展開；RQ4b 的 LLM 仲裁擴充（`ESCALATE`）與別名記錄（`surface_form`）維持在 3.4 §b，3.1.4 只做指標引用。
   - **RQ 對應維持不變**（3.2→RQ1/RQ2、3.3→RQ4a、3.4→RQ4b、3.5→RQ3、3.6→RQ6、3.7→方法論），未觸發連鎖章節重編號。

3. **3.1.2 補上原文/句子清單取得判斷節點，銜接「文字前處理」與「SVO 專用切塊」的空白**：
   - 初版新增判斷：文件資料夾內是否已有 `original.md`？有就直接讀取，沒有才重新解析——並誠實標註 `REPARSE` 分支的侷限（查證 `routers/documents.py::upload_document()` 發現上傳來源的暫存檔在解析後即被刪除，「重新解析」實際上只有 URL 來源可行）。
   - **後續校正為三層判斷（`GETSENT`）**：使用者指出 3.4 §a 實際要查的不是原始文章，而是「已經切成句子的集合」——改為優先檢查 `sentences.json`（3.1.1 順手存的句子清單）是否存在，有就直接讀；沒有但 `original.md` 存在，就對 `original.md` 重新呼叫 `split_into_sentences()` 補回來（純規則運算，成本低，不需重新解析）；兩者皆無才需要走原本的 `REPARSE`（僅 URL 來源可行）。
   - 3.4 §a 圖同步校正：`RAW` 節點改指向 `sentences.json`／3.1.2 `GETSENT`（移除重複的 `SPLIT` 節點，切分已在上游完成）；收尾的 `COMBINE` 改名 `STDSENTS`，明確輸出「標準化句子清單」而非重新拼接的全文字串——3.4 §a 輸入輸出皆維持句子集合形態。

4. **3.1.2／3.1.3 依「佇列生產者端／消費者端」重新分工**：
   - 3.1.2 只保留生產者端：資料夾搬移、記錄檔初始化/重新歸屬、`GETSENT`、`CHUNKREADY`、`ENQUEUE`，加上程式重啟的索引完整性檢查與恢復（`RESTART`／`TRUST`／`SCAN`／`REBUILD`——此分支本質是佇列索引本身的完整性問題，判定留在生產者端）。終點從「開始抽取」改為「佇列已就緒」。
   - 3.1.3 新增消費者端開頭：`WORKER`（挑出下一個 pending Chunk）→ `PROC`（狀態→processing），取代原本入口的「開始抽取」假設；同時移除重複的 `CHUNK[文字切塊]` 節點——Chunk 早在 3.1.2 的 `CHUNKREADY` 就已切好，3.1.3 不需要再切一次。
   - 3.1.4 兩處重試回退節點原本誤寫「回 3.1.2 WORKER」，已更正為「回 3.1.3 WORKER」。

5. **`services/svo_chunking.py`／`services/svo_service.py` 實作（來自另一個 Gemini 討論分支，2026-07-21）**：使用者另外與 Gemini 討論出一批更完整的 SVO 切塊/抽取實作（含語意切塊演算法研析、三軌混合檢索、實體別名動態標準名提升、代名詞雙軌檢測等 4 份報告，見 `docs/報告/07-10`），並已落地部分程式碼。**使用者決定 07-10 先暫緩**（部分文獻引用需要重新查證，08 的三軌檢索架構與現有 RQ1/RQ2 範圍的關係也需要另外討論），這批改動目前**未提交**，暫時擱置於工作目錄，不在本任務書「已完成」範圍內。

以上調整（不含第 5 項）皆已提交並推送至 `master`（共 5 次 commit，涵蓋文件重組、程式重構、圖表調整）。

---

## 3. 設計問題（2026-07-21 第二輪：查證＋使用者決策＋實作，見下方各小節「已定案並實作」標記）

### 3.1 SVO 專用切塊的演算法與粒度（✅ 已定案並實作）

3.4 §a 的 `STDSENTS`／`SENTEMBED` 節點產出「依句子順序排列、已完成指代消解＋別名前處理、且逐句已算好 embedding 的標準化句子清單」之後，要怎麼組成一個一個 SVO 專用 Chunk（登記進 `task_queue.db` 的最小單位）——目前完全空白。已明確排除的做法：直接沿用「前 4 後 2」（7 句）這個數字（那是代名詞消解的上下文視窗大小，跟切塊粒度是兩個不同參數，不可混用）。需要決定：切塊依句數、字數、還是其他規則；是否需要重疊；粒度大小是否需要留給第五章消融實驗校準（比照 `CLASSIFY_AUTO_THRESHOLD` 現行做法）。

`docs/報告/07_SVO切塊粒度與句子級語意分塊研析報告.md` 已針對此題提出一版設計（embedding cosine 距離斷點＋句數/字數安全繩）。文獻引用重新查證結果（2026-07-21）：
- 引用 Qu, Tu & Bao（2025）支持語意切分——**確認矛盾**，本 repo 已查證過的同一篇論文結論其實是「固定字數切塊表現持平或優於語意切分」，方向相反，不可用。
- 引用 GraphRAG（Edge et al., 2024）消融實驗證實小 chunk 抽取密度較高——**已實際查證原文（附錄 A.2 / Figure 3）：方向性真實存在**（HotPotQA 範例：600 token 切塊抽出的實體參照數約為 2400 token 的兩倍），但 07 報告有誇大：①這只是附錄裡單一資料集的示例，不是正式消融實驗章節；②論文自己真正推薦的解法是引入 **self-reflection**（讓 LLM 自我檢查撿回漏抽的實體），藉此可以**繼續用大 chunk**（省 API 成本）又不犧牲品質，07 報告完全沒提這個關鍵反轉；③「大 chunk 只抓 2-3 個主要關係」這個具體說法在論文中找不到對應內容，疑似加油添醋。

**目前定案方向**：句子已逐句算好 embedding（`SENTEMBED`，見下方 §3.2），但「怎麼組塊」本身傾向先採**簡單固定聚合**（依句數/字數上限分組，小 chunk 為主，呼應 GraphRAG 附錄的方向性發現），語意斷點式分組（07 報告的核心演算法）因文獻支撐不足暫緩，是否採用留給第五章消融實驗實測比較，而非直接採信文獻宣稱。

**組塊上限（✅ 2026-07-21 定案並實作）**：最多 5 句或最多 300 字元，先到者為準（沿用 `sentence_aware_chunking()` 既有的句數/字數雙重上限手法，超長單句獨立成 Chunk）。300 字元沒有直接文獻依據，是比 3.1.1 現行 500 字元 RAG 切塊更小的工程判斷（方向呼應 GraphRAG 附錄「切塊越小抽取密度越高」的查證結果，GraphRAG 測試範圍為 600/1200/2400 token，與中文字元換算不精確，僅供粗略參考），最終數值仍留給第五章消融實驗校準，但已是可執行的預設值。**實作**：`services/svo_chunking.py::build_svo_chunks()` 新增 `max_sentences`（預設 5）參數，與既有 `max_chars`（已改為預設 300）並行判斷，先到者觸發切分；測試見 `tests/services/test_svo_chunking.py::test_max_sentences_cap_splits_before_char_limit_is_reached` 等。

### 3.2 原句子／標準化句子／SVO Chunk 的關聯索引設計（✅ 已定案並實作）

使用者已確認一個關鍵設計原則：**RAG 檢索查找用原句子（`original.md`／`chunk-NNN-of-MMM.md`），SVO 抽取/圖譜查找用標準化後句子**——兩者是同一份文件的不同「版本」，各自獨立可查，不是同一份文字的兩種標記。`sentences.json`（見上方第 1 節第 6 項）已把「原句子」這一半的穩定清單準備好。

**新增定案（2026-07-21）**：標準化句子清單產出後，逐句計算 embedding（3.4 §a 的 `SENTEMBED` 節點，與 3.1.1 的 RAG chunk 向量分開計算、分開索引）。用途分兩層：① 作為未來 SVO 切塊分組的候選依據來源之一（不代表分組規則已定案採語意切分）；② 讓 `docs/報告/08_三軌混合檢索架構與標準化RAG設計報告.md` 提出的「標準化 RAG」檢索軌道具備可實測的基礎建設，第五章消融實驗可實際比較傳統 RAG vs. 標準化 RAG，而非僅依賴文獻宣稱。

**✅ 落地存檔＋追溯欄位（2026-07-21 使用者決策：兩項皆採推薦方案）**：
- 標準化句子/SVO Chunk 落地存檔——`services/svo_chunking.py::write_svo_chunks()` 已寫出 `svo_index.json`（含每個 SVO chunk 的 `original_sentences`／`normalized_sentences`／句子範圍），達成「標準化句子落地存檔、可隨時查詢、不需重跑 LLM」的目標，不另立與 `sentences.json` 平行的獨立檔案。
- 雙向追溯欄位——`models/knowledge_graph.py::SVOTriple` 已新增 `source_svo_chunk_index`／`source_svo_chunk_file`／`source_sentence_start`／`source_sentence_end` 四個欄位（1-based，閉區間），`services/svo_service.py::merge_triples_to_graph()` 已將這些欄位一併寫入 Neo4j 關係邊屬性，`bfs_query()` 查詢時一併讀回，達成「從三元組找回原文句子範圍」的雙向追溯，測試見 `tests/services/test_svo_service.py::test_merge_triples_to_graph_passes_sentence_trace_fields`／`test_bfs_query_maps_records_to_triples`。

### 3.3 標準化流程本身缺乏斷點續傳（✅ 已定案並實作）

3.4 §a 的指代消解/別名前處理原本是「整份文件一次做完」才會產生 `CHUNKREADY`，中途沒有任何 checkpoint。**2026-07-21 使用者決策：要做斷點續傳（推薦方案）**。實作：
- `models/knowledge_graph.py::DocumentRecord` 新增 `normalization_status`／`normalization_progress`／`normalization_total_sentences`／`svo_total_chunks` 四個欄位，追蹤方式與現有 SVO 抽取五態狀態機分開（標準化是文件級一次性前處理，SVO 抽取因重新歸屬可能重跑，兩者生命週期不同，各自獨立追蹤）。
- `services/document_record_service.py::update_normalization_progress()`／`set_svo_chunk_total()` 提供讀寫介面，沿用既有 `_record.json` 原子寫入模式（暫存檔＋`os.replace`），測試見 `tests/services/test_document_record_service.py`。
- `services/entity_registry_service.py`（3.4 §a 文件內別名登記表本體，2026-07-21 新增）額外提供 `write_registry_snapshot()`／`read_registry_snapshot()`，持久化登記表狀態（`entity_registry.json`），使中斷後可從 `normalization_progress` 對應的句子索引＋已恢復的登記表繼續處理，不需整份文件重跑；`apply_registry()` 支援傳入既有 registry 與 `start_idx` 從中斷處繼續，測試見 `tests/services/test_entity_registry_service.py::test_apply_registry_resumes_from_checkpoint`。

### 3.4 `SVOTriple` 追溯粒度不足（✅ 已隨 3.2 一併實作）

`SVOTriple` schema 已擴充句子/chunk 層級來源欄位（見 3.2），`services/svo_service.py::merge_triples_to_graph()`／`bfs_query()` 皆已支援讀寫，達成「附來源標記的回答可精確指回原文特定句子範圍」的目標。

---

## 4. 實作項目狀態（2026-07-21 更新）

- [x] SVO 專用切塊函式——`services/svo_chunking.py::build_svo_chunks()`，已支援 `max_sentences`／`max_chars` 雙重上限
- [x] 原句子/標準化句子/Chunk 關聯索引的寫入與讀取機制——`svo_index.json`＋`SVOTriple` 句子層級欄位
- [x] 標準化進度的 checkpoint 機制——`DocumentRecord.normalization_*` 欄位＋`entity_registry_service` 登記表快照
- [x] `SVOTriple` schema 擴充句子/chunk 層級來源欄位
- [x] 文件內實體別名登記表（3.4 §a，PK 動態提升機制）——`services/entity_registry_service.py`（新增），含頻率優先＋長度次要規則、規則式別名比對（子字串/縮寫）、LLM 仲裁 hook、斷點續傳快照，測試見 `tests/services/test_entity_registry_service.py`（17 項）
- [x] `svo_service.py` 實體對齊/去重（3.1.4 DEDUP4／3.4 §b ESCALATE＋RECHECK）——`resolve_entity_name()`（編輯距離→cosine→LLM 仲裁三段式）、`merge_entity()`（含跨文件標準名動態更新），測試見 `tests/services/test_svo_service.py`（14 項，含 `InMemoryEntityDriver` 模擬完整 MERGE／rename 狀態）
- [ ] `Entity.aliases` 陣列屬性的查詢介面（已寫入 `alias_counts_json`／`aliases` 屬性，尚無對外查詢 API，非阻斷性待辦）
- [ ] `RECHECK` 效能優化（每次合併皆同步重新聚合全部邊，見 3.4 §b「效能待決策」，留給第四章/第五章評估）

---

## 5. 07-10 報告狀態（2026-07-21：09/07/10 文獻已修訂並解除暫緩；08 仍暫緩）

使用者另外與 Gemini 討論產出四份報告（`docs/報告/07-10`），涵蓋 SVO 切塊粒度、三軌混合檢索、實體別名動態標準名提升、代名詞雙軌檢測，並已落地部分程式碼（`services/svo_chunking.py`、`svo_service.py`／`document_record_service.py`／`models/knowledge_graph.py` 的擴充、對應測試）。原先「07-10 先暫緩」的決定，經 2026-07-21 完整查證與訂正後，**09／07／10 三份報告的文獻佐證已修訂為誠實框架，機制設計本身已落地實作並通過測試，解除暫緩**；08 報告因涉及 RQ1/RQ2 範疇界定問題（非文獻問題），**仍維持暫緩**，需獨立討論。

1. **✅ 文獻引用問題已修訂**：
   - **09 報告**（實體別名動態標準名提升）：原「長度優先三規則 PK 比試」查無文獻先例（7 項原引用皆不支持，4 項明確矛盾），已改採「出現頻率優先，長度僅平手次規則」並換上真正吻合的架構層文獻（Rao 2010／TAC-KBP／Saeedi 2020，見 `docs/參考文獻/10_跨文件實體別名消解與增量聚類/`）；CORE-KG 期刊/會議名稱誤植已訂正。完整修訂見報告本身與 `docs/論文/03_變更紀錄.md` 「第三／四次調整」。
   - **10 報告**（代名詞雙軌檢測）：Stanford CoreNLP「過濾 80% 無代詞句子降低 LLM 呼叫成本」查證確認查無出處、2014 年語境不可能討論 LLM 成本，**已整條移除**；CORE-KG 機制描述（原稿誤植為「前置 Pronoun 掃描器搭配雙向 Context-window」）已訂正為其實際方法（逐實體類型循序 LLM prompt）；fastcoref／LangChain Guardrails 兩條開源專案佐證降級措辭。
   - **07 報告**（SVO 切塊粒度）：Qu, Tu & Bao（2025）方向相反的矛盾已於報告內訂正說明；GraphRAG 消融實驗的誇大之處（單一附錄示例非正式章節、未提 self-reflection 反轉、「2-3 個主要關係」查無出處）已訂正；LangChain `SemanticChunker`「業界廣泛驗證」與 GraphRAG「強烈建議依實體關係密度調整」兩條查無出處的宣稱已移除或降級。
2. **✅ 狀態標記已訂正**：07／09／10 原標示「🟢 定案」，已依查證結果降級為「🟡 設計提案／部分已實作」，符合本論文誠實分級慣例（🟢 僅給實際查證過全文的正式發表文獻）。
3. **🟡 08 報告仍暫緩**：08 提出在現有「雙層檢索架構」（3.2，RQ1/RQ2）之外新增第三條「標準化 RAG」檢索軌道，牽動 RQ1 既有範疇界定，**與文獻查證無關，需獨立討論**，本次調整不處理。
4. **✅ 實質機制已落地**：09 的頻率優先＋長度次要提升機制已實作為 `services/entity_registry_service.py`（文件內範圍）＋`services/svo_service.py::merge_entity()`（跨文件範圍，RECHECK 真正權威層）；10 的核心區分（實體別名登記 vs. 代名詞消解，各自需要不同的觸發/省成本機制）與 07 的「指代消解視窗≠SVO 抽取切塊」核心區分，皆與本論文既有設計一致，機制設計本身合理，只是原本的文獻佐證需要重做——現已重做完畢。10 報告的雙軌 POS/正則代名詞檢測本身**尚未實作**（僅完成文獻訂正，實作仍待與 `docs/報告/05_指代消解與前處理任務書.md` 整合時一併處理，非本次範圍）。

---

## 6. 相關檔案索引

| 檔案 | 角色 |
|---|---|
| `docs/論文/03_系統設計與方法論.md` § 3.1.1–3.1.4、3.4 | 本次調整的主要正文 |
| `docs/論文/03_變更紀錄.md` | 逐日變更歷程與已取代設計方案（含滑動視窗草案） |
| `docs/報告/05_指代消解與前處理任務書.md` | 代名詞消解機制的完整規格（3.4 §a 的一部分） |
| `docs/報告/06_SVO抽取管線調整任務書.md` | 本檔案 |
| `docs/報告/07_*.md`／`09_*.md`／`10_*.md` | ✅ 文獻已修訂，解除暫緩（見上方第 5 節） |
| `docs/報告/08_*.md` | 🟡 仍暫緩，涉及 RQ1/RQ2 範疇界定，需獨立討論 |
| `docs/參考文獻/10_跨文件實體別名消解與增量聚類/` | 09 報告修訂後新增的架構層文獻（Rao 2010／TAC-KBP／Saeedi 2020） |
| `parser/core.py` | `split_into_sentences()`／`sentence_aware_chunking()` |
| `parser/chunk_writer.py` | `write_chunks_as_markdown()`／`write_original_text()`／`write_sentences_index()` |
| `parser/__init__.py` | 套件公開介面 |
| `services/ingestion_service.py` | `chunk_and_stage()`，銜接 3.1.1 前段 |
| `services/document_record_service.py` | `_record.json` 讀寫，記錄檔真實狀態來源；新增 `update_normalization_progress()`／`set_svo_chunk_total()` |
| `services/svo_chunking.py` | SVO 專用切塊（`build_svo_chunks()`，5 句/300 字元雙重上限）與 `svo_index.json` 落地 |
| `services/entity_registry_service.py` | 3.4 §a 文件內實體別名登記表（頻率優先＋長度次要，斷點續傳快照） |
| `services/svo_service.py` | SVO 抽取／實體對齊去重（DEDUP4→ESCALATE）／跨文件標準名更新（RECHECK） |
