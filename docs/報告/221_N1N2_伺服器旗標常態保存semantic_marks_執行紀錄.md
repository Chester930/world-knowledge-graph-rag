# 報告221：N1／N2——以伺服器端旗標讓評測 trace 常態保存 `semantic_marks`（只記錄，不改回答）

> **日期**：2026-10-01　**依據**：報告220 §3–§5（使用者決定：概念採 A、殘缺事實只記錄、做法一＝伺服器端旗標、不新增公開請求欄位）　**性質**：小幅 production 變更（預設零行為變更）＋驗證，N1／N2 同一份報告。

## 1. 改動

| 檔案 | 改動 |
| --- | --- |
| `core/config.py` | `Settings` 新增 `trace_semantic_marks: bool = False`（環境變數 `TRACE_SEMANTIC_MARKS`）、`trace_semantic_marks_concept_scheme: str = "A"`（`TRACE_SEMANTIC_MARKS_CONCEPT_SCHEME`）。**預設關閉、預設 A。** |
| `services/context/trace_marks.py`（新） | `load_type_lookups()`：讀 `core.constants.ENTITY_TYPES` ＋ `data/schema_org_entity_types.json`，以 `normalize_type_key` 建 `(core_lookup, ext_lookup)`，`lru_cache` 程序內只載入一次；擴充表缺檔／壞檔／缺欄位 → **降級為空 `ext_lookup`＋log，不崩潰**。`semantic_marks_trace_kwargs(enabled, concept_scheme)`：旗標關閉回 `{}`（**不載任何檔**）；開啟回 `include_semantic_marks=True`、`concept_scheme`、`type_lookups`，**不含 `document_article_applicable`（不查 DB）**；無效 scheme 立即 `ValueError`（只在旗標開啟時檢查）。 |
| `routers/agent.py` | 僅 `chat()` 內 `_build_retrieval_trace(...)` 呼叫處加 `**semantic_marks_trace_kwargs(settings.trace_semantic_marks, settings.trace_semantic_marks_concept_scheme)`；另加一行 import（`from services.context.trace_marks import semantic_marks_trace_kwargs`）。 |
| `.env.example` | 補兩個設定項說明。 |

**位置理由**：`services/semantic_marks.py` 必須維持純運算，故讀檔放在同為 N10 遙測周邊的 `services/context/trace_marks.py`（與 `telemetry.py` 同層）；「旗標→參數」的條件邏輯放在該模組而非 `agent.py`，使 `routers/agent.py` 不新增函式、呼叫處只多一個 `**` 展開（旗標關閉時展開為空，關鍵字參數與修改前完全相同）。**未修改** `services/context/NODE.md`（其「資料夾現有檔案」描述略過時，屬規劃對話文件，未動）。

**無效 scheme 的行為（明確取捨）**：選「旗標開啟且要 trace 時才 `ValueError`」而非在 `Settings` 驗證——避免引入 `Literal` 等 config 結構改動。後果：若環境變數寫錯且旗標開啟，要求 `include_retrieval_trace` 的請求會在串流中拋例外（明確失敗而非靜默用錯誤 scheme）；未要求 trace 的請求不受影響。

## 2. 驗證（N2）

- **新測試**：`tests/routers/test_agent_trace_marks.py` 9 項（路由層，假 provider／假 Neo4j，無 LLM／DB）、`tests/services/test_context_trace_marks.py` 5 項。
- **旗標關閉（預設）**：路由組出的 `retrieval_trace` 每筆**不含** `semantic_marks`；型別表載入函式被換成「一呼叫就失敗」仍通過（**證明未載入**）；旗標開啟但未要求 trace 時同樣不載入。`Settings(_env_file=None)` 預設為 `False`／`"A"`。
- **旗標開啟**：每筆 fact／triple 含 `semantic_marks`；`concept_scheme` A／B／strict 各有測試（triple 主詞型別「概念」→ 未知／已解決／無法由現有資料判定）；Fact 因 trace 內無法查 Entity 而不附實體型別標示（預期，M1 行為）。
- **回答／sources／prompt 不受旗標影響（路由整合層證明）**：同一假資料以關閉／開啟各跑一次 `chat()`，**整串 SSE chunk（回答 token、事件順序、其他事件）與 `sources` 中 triples／facts 清單與順序、以及送進 LLM 的 `prompts` 逐字相同**；僅 `retrieval_trace` 內多出的 `semantic_marks` 鍵與計時值 `retrieval_latency_ms` 被正規化後比較。**證明範圍**：路由整合層、假 provider；未涵蓋真實 LLM／Neo4j／真實檢索資料。
- **AST 比對（HEAD vs 工作樹）**：`core/config.py` 只有 `Settings` 類別新增上述兩個欄位；`routers/agent.py` 66 個具名節點中僅 `chat` 有變動，且將 `_build_retrieval_trace` 呼叫的關鍵字參數去除後，`chat` 與修改前 `ast.dump` 完全相同；未命名模組層節點僅新增那一行 `ImportFrom`，無移除。
- **全量 pytest**：見回報（基準 1671）；`check_node_cards.py`：見回報。

## 3. 未動範圍與偏離

未動：`ChatRequest`／回應模型、公開請求欄位、`strip_type_markers`／`split_fact_lines`／`_arrange_fact_lines`／`bfs.py`／任何 Cypher、prompt／排序／截斷、`services/semantic_marks.py` 標示規則、儲存資料、KG#4（本任務完全未連 Neo4j）、未啟動 Ollama、無密碼。**偏離報告220：無**（兩項設計取捨已於 §1 說明：位置、無效 scheme 行為）。

## 4. 使用方式（下一次評測）

評測啟動伺服器前設 `TRACE_SEMANTIC_MARKS=1`（可選 `TRACE_SEMANTIC_MARKS_CONCEPT_SCHEME=A|B|strict`），評測請求維持 `include_retrieval_trace=true`，即可在保存的 `retrieval_trace` 中取得每筆事實的 `semantic_marks`；與「進 prompt／答對答錯」交叉的分析屬後續（報告220 §6）。限制：Fact 的實體型別標示與條號的文件層適用性在 trace 層無法取得（不查 DB），後者標為「無法由現有資料判定」（使用者已認可的取捨）；如需這兩項，沿用報告218 的離線 join。
