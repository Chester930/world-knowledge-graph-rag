# 報告216：M1——`build_retrieval_trace` 預設關閉的 `semantic_marks` 影子欄位

> **日期**：2026-10-01　**依據**：報告215 §3 M1　**性質**：執行紀錄（新增程式，production 只動 `build_retrieval_trace`）

## 1. 改動

`services/context/telemetry.py::build_retrieval_trace()` 新增四個選用參數，預設皆不改變輸出：

| 參數 | 預設 | 用途 |
| --- | --- | --- |
| `include_semantic_marks` | `False` | 為 True 時每筆 fact／triple 多一個 `semantic_marks` 鍵 |
| `concept_scheme` | `"A"` | 「概念」佔位處理（A／B／strict），僅啟用時檢查合法性 |
| `type_lookups` | `None` | `(core_lookup, ext_lookup)`；未提供則省略 `subject_type`／`object_type` 標示 |
| `document_article_applicable` | `None` | `source_doc_id`→文件是否適用條號 |

`semantic_marks` 內容：`fields`（`mark_fact_fields`）、`relation_type`（`mark_relation_type`）、`article_no`、（triple 且有 lookups 時）`subject_type`／`object_type`。`services/semantic_marks` 於旗標分支內才匯入（模組層 AST 不變）。

**決策**：無條號且查無該文件的適用資訊時標「無法由現有資料判定」，不猜「未知」或「不適用」（trace 內只有檢索到的片段，無法得知文件層是否有條號）。`routers/agent.py` 未改、未傳入新參數，沿用關閉。

## 2. 驗證

- 新測試 `tests/services/test_context_telemetry_semantic_marks.py`：10 項（預設＝顯式 False 的 `==` 與 `json.dumps` 逐字相同、鍵順序不變；開啟只多 `semantic_marks` 一鍵；空值／空 verb／RELATED_TO／概念三方案／無 lookups／無效 scheme／空輸入）。
- 全量 pytest：**1656 passed／0 failed**（基準 1646＋10）。
- `check_node_cards.py`：3 張、0 警告。
- `ast.dump` 前後（HEAD vs 工作樹）：函式集合相同、**唯一有變動的函式為 `build_retrieval_trace`**、非函式模組層節點相同。
- 未改 `strip_type_markers`／`split_fact_lines`／`_arrange_fact_lines`／`bfs.py`／Cypher／請求欄位；未連 Neo4j、未啟動 Ollama。

## 3. 偏離報告215

無。
