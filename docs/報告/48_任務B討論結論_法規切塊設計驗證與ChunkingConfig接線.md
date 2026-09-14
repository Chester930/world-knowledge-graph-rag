# 48 任務B討論結論：法規切塊設計驗證與 `ChunkingConfig` 接線

> **建立日期**：2026-09-14
> **對應**：`docs/報告/47_Claude_Code交接任務書.md` 任務 B；`docs/參考文獻/32_法規結構感知切塊與主旨錨定/README.md`
> ⚠️ **編號風險**：本專案有多個並行 session 同時寫報告，編號可能衝突（見報告 44/45 前例），入庫前請先確認 47 之後沒有其他 session 也用了 48。

## 0. 背景與範圍修正

報告 47 任務 B 原始指示「將 `ChunkingConfig` 主旨錨定接上實際抽取管線」隱含一個未經查證的假設：現有法規 KG 會經過 `build_svo_chunks()`（`header_anchored`「款式斷頭防護」的實作所在）。實測發現此假設**不成立**——目前評測用 KG（`236903cf`）走的是完全不同的 `ArticleAwareChunking`（一條法條＝一個 chunk）路徑，`build_svo_chunks()` 對它從未被呼叫過。本報告依使用者指示「都要做，依序討論」，把任務 B 拆成三個子問題逐一查證，並補上文獻與資料佐證。

## 1. 子問題一：`ArticleAwareChunking` 是否已經免疫「款式斷頭」？

**結論：是，by design。** `services/svo_chunking.py::build_article_aware_chunks()`（`ArticleAwareChunking`）按 `ArticleNo` 邊界切、一條對一塊，**不做固定句數上限、不做相鄰塊重疊窗**——沒有「一條法規全文被攔腰截斷到兩個 chunk」的機制存在，所以「款式斷頭」（母條文主旨與子款項被拆到不同 chunk）這個問題對此路徑架構上不成立。這不是本專案獨有猜測：Prior et al. (2026, arXiv:2605.19806) 在德國民法典上比較 7 種切塊法，結論「依法規固有結構切塊之召回率最高」；Ford et al. (2026, arXiv:2604.25448) 的多法域 RAG 系統也採用保留法規結構的類型專屬切塊。詳見文獻 32 §A。

**行動**：不改程式碼，僅記錄本結論（本報告即為該記錄）。

## 2. 子問題二：是否需要對過長法條做二次切分？

**結論：目前沒有實證需求，不做。** 即時查詢現有評測 KG（`236903cf`）與其前身（`76bc98ff`）共 3303 個 `LawArticle` 節點的 `article_content` 長度分布：

| 統計量 | 數值 |
|---|---|
| 平均長度 | 145 字元 |
| p95 | 397 字元 |
| 最長（第313條，全庫最長條文） | 2143 字元 |

2143 字元遠低於 `bge-m3`（8192 token 上限）或 `qwen2.5:7b` 的任何實務長度限制，也遠低於 `ChunkingConfig.max_chunk_chars` 的預設軟上限（1000 字元，但此軟上限目前也未在 `ArticleAwareChunking` 中被檢查/套用）。在沒有任何一條法規全文接近造成問題的長度之前，替 `ArticleAwareChunking` 新增二次切分機制屬於「為假設性未來需求設計」，違反本專案一貫原則（`CLAUDE.md`「不要為假設性未來需求設計」）。

**行動**：不改程式碼。若未來匯入的法規全文出現遠超過現有分布的超長條文（建議門檻：單條 >3000 字元，約為現有最大值的 1.4 倍），才需要回頭評估是否要擴充 `ArticleAwareChunking`。

## 3. 子問題三：`ChunkingConfig`／`header_anchored` 的接線與驗證

**現況修正前**：`services/svo_preprocessing_service.py::prepare_svo_ready_chunks()` 呼叫 `build_svo_chunks()` 時完全沒有傳入 `config=`（永遠用函式自己的 `max_sentences`/`overlap_sentences` 參數，等同 `strategy="sliding_window"`）；`services/svo_service.py::trigger_extraction()` 也從未載入或接受任何 `KGConfig`。且經查，目前系統裡的兩個既有 KG 都是透過 `create_clean_leave_scheduling_kg.py`／`import_leave_scheduling_dataset.py` 等專用匯入腳本傳入 `articles=` 建立，皆走 `ArticleAwareChunking`——**系統中目前沒有任何一個走 `SVOGROUP`/`build_svo_chunks()` 路徑的真實 KG**，`header_anchored` 此前只有 `tests/services/test_svo_chunking.py` 的合成資料覆蓋，從未在真實文件/KG 上被觸發過。

**已完成的接線（本次入庫）**：

1. `prepare_svo_ready_chunks()` 新增 `chunking_config: ChunkingConfig | None = None` 參數，原樣轉交 `build_svo_chunks(..., config=chunking_config)`；`None`（預設）＝零行為變化。
2. `trigger_extraction()` 新增 `cfg: KGConfig | None = None` 參數（比照本模組既有的 `resolve_query_relation_type()`／`bfs_query()` DI 慣例），把 `(cfg or KGConfig()).chunking` 傳入 `prepare_svo_ready_chunks()`。
3. **刻意不修改**呼叫端（`routers/staging.py`、`services/knowledge_graph_service.py::build_graph()`）——它們目前都不傳 `cfg=`，維持「不明確指定→行為零變化」不變式；何時要讓標準上傳流程真的讀 per-KG domain pack 決定 `chunking.strategy`，留給有真實通用文件 KG 需求時再決定，屬於獨立的「接上呼叫端」步驟，不在本次範圍內。
4. 新增兩個整合測試（`tests/services/test_svo_service.py`）：
   - `test_trigger_extraction_wires_cfg_chunking_into_svogroup_path`：傳入 `KGConfig(chunking=ChunkingConfig(strategy="header_anchored", ...))`，端到端驗證產出的 chunk 檔案確實帶有母條文主旨前綴注入（非只是記憶體物件層級）。
   - `test_trigger_extraction_defaults_to_sliding_window_when_cfg_not_passed`：不傳 `cfg` 的回歸防護，確認維持 `sliding_window` 既有行為。
   - 全套 899 pytest（含既有 66/66 SDD 基線）通過。

**方法學佐證**（詳見文獻 32 §B）：`header_anchored`／`prepend_header_to_children` 概念上對應 Anthropic Contextual Retrieval（前綴上下文修補 chunk 邊界資訊流失，實測 top-20 檢索失敗率降低 35–67%）與 LangChain `MarkdownHeaderTextSplitter`（146,273★，保留父層標題脈絡是主流函式庫既有模式）。差異：本專案採**規則式、零 LLM 呼叫**的簡化實作（直接前綴母條文既有主旨句），符合「確定性接地守衛」與「Zero Code-Gen」鐵律，代價是不能像 Anthropic 版本生成語意摘要。

**未完成、留待未來**：「在真實 KG 上驗證 `header_anchored` 對通用文件領域的實際檢索效果」——目前無真實標的可測（系統裡沒有走 `SVOGROUP` 路徑的 KG），只能以本次的整合測試替代。待未來有真實通用文件領域的匯入需求時，才能做真正的線上驗證。

## 4. 對報告 47 §5 任務 B 檢查清單的回應

- [x] 檢查 `prepare_svo_ready_chunks()`／`trigger_extraction()`／`extraction_worker.py`——已檢查；`extraction_worker.py` 確認只消費已產生的 `svo_index.json`，非切塊設定接線點，與報告 47 註記一致。
- [x] `cfg.chunking` 已能從呼叫端一路傳到 `build_svo_chunks()`——**能力已具備**，但呼叫端（`build_graph()`／`staging.py`）尚未實際傳入非預設 `cfg`，故對現有生產行為零影響。
- [x] 主旨注入沒有改變 `source_sentence_start/end`——沿用既有 `build_svo_chunks()` 血統不變式，未修改該邏輯，新增測試亦驗證無偏移。
- [x] 任務 B 執行前已保留現有 66/66 測試基線——899 全套通過。
- [x] 不得假設 `taiwan-labor-law` domain pack 已啟用 `header_anchored`——確認未啟用，且確認其走 `ArticleAwareChunking` 路徑，`header_anchored` 對它無效，已在程式 docstring 與本報告記錄。
