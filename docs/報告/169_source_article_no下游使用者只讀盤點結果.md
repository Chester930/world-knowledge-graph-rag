# 報告169：`SVOTriple.source_article_no` 下游使用者只讀盤點（報告168 W2）

> **日期**：2026-09-30 ｜ **基準**：`worktree-sdd-retrieval-comparison` @ `e057c70`
> **性質**：只讀盤點；**不建議要不要改**，只列「BFS 三元組的 `source_article_no` 從 `None` 變成有值」時各處的影響。程式碼零變更；未啟動 Neo4j／Ollama，以程式碼與離線資料（報告162 的 `retrieval_rerun.json`、KG 資料夾 `svo_index.json`）為據。

## 1. 背景（已核對）

`services/svo_service.py::_bfs_records_to_triples`（現於 `services/retrieval/bfs.py`）取邊上 `citations_json` **最後一筆**，設定 `source_doc_id`、`source`、`source_svo_chunk_index`、`source_svo_chunk_file`、`source_sentence_start/end`，**沒有**讀 citation 的 `article_no`，因此 BFS 回傳的 `SVOTriple.source_article_no` 恆為 `None`。若要讓它有值，修改點就是該函式（加一行 `payload["source_article_no"] = latest.get("article_no")`），本報告不建議是否做。

## 2. 寫入路徑：「資料端有值」的來源

| 步驟 | 位置 | 說明 |
| --- | --- | --- |
| chunk 帶條號 | `services/svo_chunking.py`（`SVOChunk.article_no`，`:49`）。**兩個來源**：① **法條感知切塊 `ArticleAwareChunking`**（`:230-245`；一條文一個 chunk，需要 `articles` payload，來自法規匯入腳本如 `import_leave_scheduling_dataset.py`）；② **`build_svo_chunks` 內的 `header_anchored` 路徑**（`:126-131`）：當設定了標題樣式（`KGConfig.chunking.strategy=header_anchored`，預設為 `sliding_window`）且區塊所屬主旨符合 `第X條`，以正則填入條號（`trigger_extraction` 經 `prepare_svo_ready_chunks(chunking_config=…)` 傳入設定） | 預設設定下一般文件（`SVOGROUP`／`sliding_window`）為 `None`；**若某 KG 設為 `header_anchored`，一般切塊路徑的 `article_no` 也可能有值** |
| chunk → 三元組 | `services/extraction_worker.py:134-137`：`triple.source_article_no = chunk.get("article_no")` | 抽取時逐筆指派 |
| 三元組 → citation | `services/svo_service.py:857-859`（`_new_citation`）：`"article_no": triple.source_article_no` | 累積在邊的 `citations_json`（每次抽取到同一關係追加一筆） |
| 三元組 → Fact／`SUPPORTED_BY` | `svo_service.py:1305`（`merge_triples_to_graph` → `_create_fact_node(article_no=triple.source_article_no)`，`:1085-1144`）；`backfill` 路徑 `:1720` 直接讀 `citation.get("article_no")` | 有值時 `SUPPORTED_BY` 連向 `(:LawArticle)`，否則連向 `Chunk` |
| 重抽守衛 | `services/knowledge_graph_service.py:130-136` | 偵測到先前用 `ArticleAwareChunking`（任一 chunk 有 `article_no`）就拒絕靜默覆寫 |

**其他 KG（非法規）是否必為 `None`**：**預設設定下為 `None`，但不是「必」**——`article_no` 有兩個填入來源（見上表）：`ArticleAwareChunking`（需 `articles` payload，目前只有法規匯入腳本提供）與 `header_anchored` 標題樣式（`KGConfig.chunking.strategy`，預設 `sliding_window`；某 KG 若設為 `header_anchored` 且主旨符合「第X條」，一般文件也會有值）。（2026-09-30 更正：本報告初稿寫成「只有 `ArticleAwareChunking` 會填、非法規 KG 必為 `None`」，經規劃對話指出 `svo_chunking.py:126-131` 而修正；不影響本報告的主結論，只影響「日後 BFS 帶出時哪些 KG 會有值」的描述。）本盤點未逐一檢視其他 KG 的實際資料（只有 KG#4 的資料可離線取得）。

## 3. 資料面（報告162 重跑資料，42 題、975 條 BFS 三元組）

| 項目 | 數字 |
| --- | --- |
| 最後一筆 citation 帶 `article_no` | **973／975**（99.8%）；任一筆 citation 帶＝973 |
| 無值的 2 筆 | 皆來自 `N0060022_附表一_特別危害健康作業`（附表，無條號結構的文件） |
| 有值三元組的文件分布 | 21 份文件；前 6：勞動基準法 175、失業中高齡者及高齡者就業促進辦法 102、就業服務法 88、勞工職業災害保險及保護法 85、職業災害勞工保護法 71、勞工退休金條例 68 |
| **同一條邊的多筆 citations 對 `article_no` 不一致** | **69 條**（同一關係被不同文件／條文抽到；`bfs_query` 只取**最後一筆**，與取 chunk 索引同一語意，可能只反映最新一次抽取的條文） |
| 42 題中所有三元組皆有值的題數 | 40／42 |
| KG#4 的 65 份文件 | 64 份有法條感知 chunk、1 份無（即上述附表） |

## 4. 所有使用位置與「None → 有值」的行為差異

搜尋方式：**A**＝AST／grep 對 `source_article_no`、`article_no`（全庫 `.py`，31 個檔案 260 處）；**B**＝逐檔閱讀 A 命中的非測試檔，再交叉檢查「BFS 三元組（`SVOTriple`）流向哪裡」（`chat()`→`_split_fact_lines`／`merge_fact_lines`／`_arrange_fact_lines`／`_build_prompt`／`serialize_sources`／`build_retrieval_trace`／驗證與評分）。

| # | 位置 | 拿它做什麼 | 讀 BFS `SVOTriple.source_article_no`？ | None→有值的行為差異 | 判定 |
| --- | --- | --- | --- | --- | --- |
| 1 | `models/knowledge_graph.py:222` | 欄位定義（預設 `None`） | — | 無 | — |
| 2 | `services/extraction_worker.py:134-137` | 抽取時指派 | 否（寫入端，三元組來自抽取而非 BFS） | 無 | 讀程式 |
| 3 | `svo_service.py:857-859`（`_new_citation`） | 三元組→citation | 否（輸入為抽取出的三元組） | 無 | 讀程式 |
| 4 | `svo_service.py:1305`、`_create_fact_node`（`:1085-1144`） | `SUPPORTED_BY` 目標選擇 | 否（`merge_triples_to_graph` 的非測試呼叫者只有 `services/extraction_worker.py:139`，**未發現把 `bfs_query` 結果餵進去**） | 無；**若日後有人把 BFS 三元組再寫回圖，Fact 會改連向 `LawArticle`（行為改變）** | 讀程式（現況無此路徑） |
| 5 | `svo_service.py:1720`（backfill） | 直接讀 `citation.get("article_no")` | 否（讀 citation 原始 dict） | 無 | 讀程式 |
| 6 | **`services/context/telemetry.py:103`**（V3，報告165） | `build_retrieval_trace` 三元組條目的 `article_no` | **是** | trace 中 `kind=triple` 條目的 `article_no` 由 `null` 變為條號字串（**鍵已存在，只是值變**）；`retrieval_trace` 的 JSON 內容改變 | 讀程式 |
| 7 | `services/context/telemetry.py::serialize_sources`（`:109-`） | SSE `sources` 的三元組序列化 | **否**（輸出欄位只有 subject／verb／object／rel_type／source／`source_svo_chunk_file`／natural_text／document） | 無 → **對外 SSE 輸出不變** | 讀程式 |
| 8 | `services/context/fact_lines.py`（`split_fact_lines`／`merge_fact_lines`）、`routers/agent.py::_arrange_fact_lines`／`_build_prompt` | 組 prompt 事實行 | **否**（只用 `natural_text`／subject／verb／object） | 無 → **prompt 內容不變 → 生成答案不變**（讀程式判定；未實測） | 讀程式 |
| 9 | `services/verification_service.py`、`atomic_scorer.py`、`claim_scope_auditor.py`、`lineage_tracker.py`、`evaluation_*` | 接地核對、評分、scope audit、血統 | **否**（`grep article_no` 零命中） | 無 | 讀程式 |
| 10 | `routers/agent.py:287-357`（`_expand_facts_by_article`） | Cypher 從 Fact→`LawArticle` 讀 `article_no`（`SUPPORTED_BY`） | 否（讀圖上的條文節點與 `fact_results`，非 BFS 三元組） | 無 | 讀程式 |
| 11 | `models/eval_schema.py:143`（`RetrievedEvidence.article_no: Optional[str]`） | trace 條目的 pydantic 型別 | 是（承接 #6 的值） | 型別允許字串；無驗證問題 | 讀程式 |
| 12 | **`scripts/analysis/source_ambiguity_audit.py:365`（＋`:901` 等比對）** | 從 records 的 `retrieval_trace`（`in_prompt=True` 條目，**含 `kind=triple`**）取 `article_no` 併入 `trace_by_text`，之後與 Neo4j 引用的 `article_no` 比對（`citation.article_no == match["article_no"]`，`:901`；另有多處條號集合） | 是（讀 trace） | **對「新產生」的 records，三元組 trace 條目帶 `article_no`，該腳本的比對集合與 `matched` 結果可能改變**；凍結舊 records 仍為 `None` 不受影響 | **需實測**（讀程式無法判定輸出會不會改變） |
| 13 | `scripts/eval/kg_source_recall_probe.py`／`_v2.py`（`SourceResolver.resolve`） | 有 `article_no` 時**優先**以條號找 chunk，否則用 `source_svo_chunk_index` | 是（若餵入 trace 候選） | 對三元組候選改走條號路徑；同文件內條號對應唯一 chunk（法條感知切塊：一條一 chunk）時結果應與 chunk 索引路徑相同；**多筆 citations 不一致的邊（69 條）不受影響**（`_v2` 直接餵 citation） | 讀程式（相同）／少數情況**需實測** |
| 14 | `scripts/analysis/compare_p2_snapshots.py`（含 V3 旗標） | L1 比對 `retrieval_trace` | 是 | 新舊快照 L1 判為不同；`--ignore-trace-triple-source-fields` 已涵蓋 `article_no` | 已處理 |
| 15 | `scripts/eval/diagnose_retrieval_failures.py:106` | Cypher 直接讀 `a.article_no`（`LawArticle`） | 否 | 無 | 讀程式 |
| 16 | `import_leave_scheduling_dataset.py`、`svo_preprocessing_service.py`、`law_document_repo.py`、`models/law_document.py` | 匯入／`LawArticle` 節點 | 否 | 無 | 讀程式 |

**小結**：BFS 三元組的 `source_article_no` **在正式問答路徑（prompt、生成、接地、評分、SSE 輸出）沒有下游讀取者**；唯一會讀取的是**遙測 trace（#6）**及讀 trace 的離線腳本（#12–#14）。因此對回答內容的影響為「讀程式判定：無」，對 trace／分析腳本的影響需依 #12、#13 評估（#12 需實測）。

## 5. 若要改 `_bfs_records_to_triples`：會連動的測試與比對基準（**不要改，只列**）

| 項目 | 影響 |
| --- | --- |
| `services/retrieval/bfs.py::_bfs_records_to_triples`（唯一修改點） | 加一行對應；`SVOTriple` 欄位早已存在 |
| `tests/services/test_n9_move.py`（逐字基準 `tests/services/fixtures/n9_symbol_source_baseline.json`） | 該符號原始碼會與基準不同 → 需更新基準（屬預期） |
| `tests/services/test_n9_differential.py` ＋ golden `n9_differential_golden.json` | `_bfs_records_to_triples` 的 1100 案中，citations 帶 `article_no` 者輸出會不同 → golden 需重新產生（屬預期） |
| `tests/services/test_svo_service.py` 的 BFS 相關測試 | 未見以 `article_no` 斷言 BFS 三元組的測試（`source_article_no` 只在 `_create_fact_node`／`merge_triples_to_graph` 測試中，`:3388-3408`）；**是否全綠需執行確認** |
| `tests/services/test_context_telemetry_trace_v3.py`／`test_context_telemetry.py` | 差分以 `SVOTriple` 物件驅動，不經 BFS；不受影響 |
| K 臂快照比對基準（`compare_p2_snapshots.py` L1） | 新快照的 `retrieval_trace` 三元組 `article_no` 會有值，與凍結快照 L1 不同；比對需帶 `--ignore-trace-triple-source-fields`（已有） |
| `scripts/analysis/source_ambiguity_audit.py` 與其測試 `tests/scripts/test_source_ambiguity_audit.py`（29 處 `article_no`） | 測試使用合成 trace；對新產生 records 的實際輸出需實測（見 §4 #12） |
| `kg_source_recall_probe`（v1／v2）結果 | 三元組候選的解析路徑可能由 chunk 索引改為條號（結果應相同，見 §4 #13） |

## 6. 驗收

| 驗收項 | 結果 |
| --- | --- |
| 抽樣 5 個使用位置回原碼核對 | ① `extraction_worker.py:134-137` 指派 `triple.source_article_no = chunk.get("article_no")` ✓；② `svo_service.py:857-859` `_new_citation` 寫入 `"article_no": triple.source_article_no` ✓；③ `telemetry.py:103` 讀 `t.source_article_no`、`serialize_sources` 輸出欄位不含條號 ✓；④ `source_ambiguity_audit.py:365` 自 trace 取 `article_no`、`:901` 比對 ✓；⑤ `routers/agent.py:287-357` 讀 `LawArticle.article_no`（Cypher），非三元組 ✓ |
| 兩種搜尋方式交叉 | A（全庫 grep／AST：31 檔 260 處）與 B（逐檔閱讀＋資料流追蹤）一致；無遺漏的非測試使用者 |
| 程式碼零變更 | 只新增本報告 |
| 未啟動 Neo4j／Ollama | ✅（離線資料） |
