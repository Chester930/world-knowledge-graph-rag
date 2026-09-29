# 報告138：`agent.py` 拆分盤點結果

> 日期：2026-09-30 ｜ 基準 commit：`ff3ab7d` ｜ 執行者：Codex（依報告137）

## 1. 總結

`routers/agent.py` 為 1,904 行、36 個頂層函式加 1 個頂層 class；`chat()`（268 行）內含 217 行的 `_stream()`，生成尾段另有 195 行。外部引用不只 `from routers.agent import X`，還有 290 個 `agent.X` 屬性存取，測試有 158 個 monkeypatch。最大風險是 re-export 只保留名稱時，搬走呼叫端會讓既有 patch 靜默失效；本次 158 個測試補丁逐條判定均屬 (b)。純函式 `_rrf_order`／`_litm_reorder` 是低風險候選，然而它們的外部快照覆蓋薄弱；是否作為第一刀及如何保留相容性，留待使用者決定。本報告不作實作決定。

基準回歸：`python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py` → **1309 passed，8 warnings，44.11s**。本任務沒有啟動或使用 Neo4j、Ollama、server、harness 或任何評測。

## 2. Q1 函式盤點表

靜態腳本以 `ast` 讀取目前 `routers/agent.py`；表中行數包含起訖行。純度欄的「純」表示函式本身沒有外部 I/O；「組合」表示會呼叫其他 I/O／LLM／embedding 函式。

| 頂層定義（職責） | 行號／行數 | 大節點 | 純度與 async |
|---|---:|---|---|
| `_find_seed_entities`：字面種子、必要時 embedding fallback | `routers/agent.py:93-134`／42 | N9 檢索 | Neo4j、embedding；async |
| `_drop_hub_seeds`：按 degree 剔除樞紐種子 | `routers/agent.py:137-157`／21 | N9 檢索 | Neo4j；async |
| `_relevant_doc_ids_from_facts`：由 Fact 推導文件集合 | `routers/agent.py:168-201`／34 | N9 檢索 | 純；sync |
| `_intersect_doc_scopes`：合併語意與明確文件範圍 | `routers/agent.py:204-224`／21 | N9 檢索 | 純；sync |
| `_relevant_doc_ids_from_seeds`：由 HAS_ENTITY 邊找文件 | `routers/agent.py:227-257`／31 | N9 檢索 | Neo4j；async |
| `_resolve_doc_scope`：種子優先、再套明確範圍 | `routers/agent.py:260-285`／26 | N9 檢索 | 純；sync |
| `_scope_by_source_doc_ids`：共用來源文件過濾與歸零守衛 | `routers/agent.py:288-306`／19 | N9 檢索 | 純；sync |
| `_filter_triples_by_source_doc_ids`：過濾 BFS triples | `routers/agent.py:309-317`／9 | N9 檢索 | 純；sync |
| `_filter_facts_by_source_doc_ids`：過濾語意 Facts | `routers/agent.py:320-339`／20 | N9 檢索 | 純；sync（含巢狀 `_doc_id`） |
| `_expand_facts_by_article`：按 LawArticle 補同條文 Fact | `routers/agent.py:342-480`／139 | N9 檢索 | Neo4j；async |
| `_filter_triples_by_relation_type`：按 canonical relation type 後篩 | `routers/agent.py:483-492`／10 | N9 檢索 | 純；sync |
| `_fetch_document_map`：查來源 Document 並建 map | `routers/agent.py:495-525`／31 | N13 遙測／來源 | repository／Neo4j；async |
| `_serialize_document`：LawDocument 轉 dict | `routers/agent.py:528-536`／9 | N13 遙測／來源 | 純；sync |
| `_build_retrieval_telemetry`：計數與延遲遙測 | `routers/agent.py:539-558`／20 | N13 遙測 | 純；sync |
| `_build_retrieval_trace`：建立 rank、prompt 命中 trace | `routers/agent.py:561-617`／57 | N13 遙測 | 純；sync（含 `_in_prompt` 閉包） |
| `_serialize_sources`：序列化 triples、facts、文件與遙測 | `routers/agent.py:620-680`／61 | N13 遙測 | 純；sync，呼叫 `_serialize_document` |
| `_strip_type_markers`：移除受控型別標記 | `routers/agent.py:705-706`／2 | N10 上下文 | 純；sync |
| `_is_contentful_line`：判斷渲染後事實列是否有效 | `routers/agent.py:709-724`／16 | N10 上下文 | 純；sync |
| `_split_fact_lines`：分層、去重、渲染 BFS／Fact 行 | `routers/agent.py:727-814`／88 | N10 上下文 | 純；sync（含兩個巢狀 helper） |
| `_merge_fact_lines`：扁平合併事實行 | `routers/agent.py:817-823`／7 | N10 上下文 | 純；sync |
| `_wants_full_enumeration`：判斷是否要求完整列舉 | `routers/agent.py:843-844`／2 | N11 生成 | 純；sync |
| `_fact_verb`：由 fact_text 推導謂語 | `routers/agent.py:847-857`／11 | N11 生成 | 純；sync |
| `_detect_tier_families`：建立分級／分段事實族 | `routers/agent.py:860-886`／27 | N11 生成 | 純；sync |
| `_missing_tier_members`：找答案未涵蓋的族成員 | `routers/agent.py:889-899`／11 | N11 生成 | 純；sync |
| `_score_lines_by_embedding`：依 cosine 排序事實行 | `routers/agent.py:928-966`／39 | N10 上下文 | embedding；async |
| `_litm_reorder`：LITM zigzag 重排 | `routers/agent.py:969-988`／20 | N10 上下文 | 純；sync |
| `_rrf_order`：按兩組 rank 做 RRF | `routers/agent.py:991-1012`／22 | N10 上下文 | 純；sync |
| `_arrange_fact_lines`：剪枝、名額、RRF、LITM | `routers/agent.py:1015-1072`／58 | N10 上下文 | embedding；async |
| `_split_into_subquestions`：按問號規則分解 | `routers/agent.py:1080-1111`／32 | N11 生成 | 純；sync |
| `_generate_decomposed_answer`：逐子問題生成 | `routers/agent.py:1114-1153`／40 | N11 生成 | LLM、呼叫上下文；async |
| `_generate_decomposed_constrained_answer`：逐子問題限制性重生 | `routers/agent.py:1156-1189`／34 | N11 生成 | LLM；async |
| `_targeted_correction`：只重寫未接地主張 | `routers/agent.py:1195-1256`／62 | N11 生成 | LLM、embedding 排序；async |
| `_build_prompt`：一般 prompt 與 trace sink | `routers/agent.py:1259-1348`／90 | N10/N11 | embedding 排序、讀設定；async |
| `_build_constrained_prompt`：限制性重生 prompt | `routers/agent.py:1351-1429`／79 | N10/N11 | embedding 排序、讀設定；async |
| `_GenerationResult`：生成尾段的 NamedTuple 結果載體 | `routers/agent.py:1432-1436`／5 | N11 生成 | 純資料型別；非 async |
| `_generate_from_context_lines`：生成、接地、重生、列舉守門 | `routers/agent.py:1439-1633`／195 | N11 生成 | LLM／judge／設定；async generator |
| `chat`：HTTP SSE route，包裝 `_stream` | `routers/agent.py:1637-1904`／268 | HTTP 路由 | Neo4j、repository、embedding、LLM、SSE；async |

以上恰為 36 個頂層 function 加 1 個頂層 class，共 37 個頂層定義。`chat` 內的巢狀 `_stream` 是 `routers/agent.py:1686-1902`／217 行，不另計入 37。

### 模組層級物件（不計入 37 個頂層定義）

| 物件 | 位置與用途 |
|---|---|
| `router` | `routers/agent.py:46`，`APIRouter(prefix="/agent", tags=["agent"])`；模組載入時建立路由物件 |
| `logger` | `routers/agent.py:48`，`logging.getLogger(__name__)`；`chat` 的 `bfs_only` 訊息使用 |
| `_SEED_ENTITY_LIMIT`、`_SEED_MAX_DEGREE`、`_BFS_PER_SEED_LIMIT` | `routers/agent.py:55,67,74`；目前是 `KGConfig` 預設值的 golden anchor，測試直接讀 |
| `_TAIWAN_CONTEXT_INSTRUCTION` | `routers/agent.py:85-90`；文字常數，`KGConfig` 預設 prompt 前綴 anchor |
| `_DOC_SCOPE_TOP_N_FACTS` | `routers/agent.py:165`；文件範圍推導上限 anchor |
| `_CONTROLLED_TYPE_TOKEN_PATTERN`、`_CONTROLLED_TYPE_LIST_PATTERN`、`_TYPE_MARKER_RE` | `routers/agent.py:688-703`；載入時由 `ENTITY_TYPES` 組 regex、編譯 regex |
| `_TIER_MIN_MEMBERS`、`_FULL_ENUM_RE` | `routers/agent.py:832,837-841`；列舉 guard 常數與 regex |
| `_FACT_LINE_TRUNCATE_K`、`_FACT_LINE_REORDER_THRESHOLD_K` | `routers/agent.py:907-908`；Fact list golden anchor |
| `_BFS_KEEP_MAX`、`_MIN_BFS_SLOTS`、`_RRF_K` | `routers/agent.py:923-925`；Fact list golden anchor |
| `_MAX_SUBQUESTIONS` | `routers/agent.py:1077`；分解上限 |
| `_TARGETED_FIX_RE` | `routers/agent.py:1192`；定向修訂輸出 parser |

目前沒有 `lru_cache`、模組級 cache dict、`global` 或 `nonlocal` 寫入。`settings` 只是 `routers/agent.py:15` 匯入的共享設定物件，實際在 `chat`／`_generate_from_context_lines` 執行時讀取，不在 import time 讀檔。

## 3. Q2 檔內呼叫圖

AST 輸出以「函式 → agent.py 內頂層定義」表示；巢狀 helper 也納入。沒有發現回到祖先的邊，因此沒有檔內循環呼叫。

```text
_find_seed_entities -> _drop_hub_seeds
_resolve_doc_scope -> _intersect_doc_scopes
_filter_triples_by_source_doc_ids -> _scope_by_source_doc_ids
_filter_facts_by_source_doc_ids -> _scope_by_source_doc_ids
_build_retrieval_trace -> _strip_type_markers
_serialize_sources -> _serialize_document
_is_contentful_line -> _strip_type_markers
_split_fact_lines -> _strip_type_markers, _is_contentful_line
_merge_fact_lines -> _split_fact_lines
_detect_tier_families -> _fact_verb
_arrange_fact_lines -> _score_lines_by_embedding, _rrf_order, _litm_reorder
_generate_decomposed_answer -> _build_prompt
_generate_decomposed_constrained_answer -> _build_constrained_prompt
_targeted_correction -> _split_fact_lines, _arrange_fact_lines
_build_prompt -> _split_fact_lines, _arrange_fact_lines
_build_constrained_prompt -> _split_fact_lines, _arrange_fact_lines
_generate_from_context_lines -> _split_into_subquestions, _merge_fact_lines,
  _build_prompt, _build_constrained_prompt, _targeted_correction,
  _generate_decomposed_answer, _generate_decomposed_constrained_answer,
  _wants_full_enumeration, _detect_tier_families, _missing_tier_members,
  _GenerationResult
chat -> _find_seed_entities, _relevant_doc_ids_from_seeds,
  _relevant_doc_ids_from_facts, _resolve_doc_scope,
  _filter_triples_by_relation_type, _filter_triples_by_source_doc_ids,
  _filter_facts_by_source_doc_ids, _expand_facts_by_article,
  _build_retrieval_telemetry, _generate_from_context_lines,
  _fetch_document_map, _serialize_sources, _build_retrieval_trace
```

葉節點是沒有指向另一個本檔頂層定義的節點：`_drop_hub_seeds`、`_relevant_doc_ids_from_facts`、`_intersect_doc_scopes`、`_relevant_doc_ids_from_seeds`、`_scope_by_source_doc_ids`、`_expand_facts_by_article`、`_filter_triples_by_relation_type`、`_fetch_document_map`、`_serialize_document`、`_build_retrieval_telemetry`、`_strip_type_markers`、`_wants_full_enumeration`、`_fact_verb`、`_missing_tier_members`、`_score_lines_by_embedding`、`_litm_reorder`、`_rrf_order`、`_split_into_subquestions`。這裡的「葉」只指本檔呼叫圖，不代表沒有 Neo4j、embedding 或 LLM I/O；例如 `_fetch_document_map` 是 Neo4j repository I/O（`routers/agent.py:495-525`）。

`_split_fact_lines` 有 `_add_bfs`（`routers/agent.py:766-782`）與 `_add_fact`（`784-801`）；`_filter_facts_by_source_doc_ids` 有 `_doc_id`（`330-337`）；`_build_retrieval_trace` 有 `_in_prompt`（`585-586`）；`_expand_facts_by_article` 有 `_source_key`、`_fact_key`、`_record_get`（`361-421`）。這些閉包沒有呼叫本檔其他頂層函式以外的新邊。

`_generate_from_context_lines` 的直接子集合如上，實際順序為：先分解／建 prompt，接著 `_merge_fact_lines` 後做 grounding；必要時走 `_build_constrained_prompt`、`_targeted_correction` 或分解式 constrained 生成；最後列舉 guard 會讀 `_wants_full_enumeration`、`_detect_tier_families`、`_missing_tier_members`，產出 `_GenerationResult`（`routers/agent.py:1439-1633`）。`chat` 的本檔直接呼叫集中在巢狀 `_stream`，HTTP route 本身只建立 `StreamingResponse`（`routers/agent.py:1904`）。

### `_stream` 捕獲的外層／模組名稱

AST 列出的捕獲／模組名稱為 `ConfigLoader`、`EmbeddingProvider`、`FileConfigSource`、`KGRepository`、`SVOTriple`、`UUID`、`bfs_query`、`get_driver`、`get_embedding_provider`、`get_judge_llm_provider`、`get_llm_provider`、`json`、`logger`、`payload`、`resolve_query_relation_type`、`settings`、`time`、`vector_search_facts`（`routers/agent.py:1686-1902`）。其中 `payload` 是 `chat` 的參數，其餘為模組 import 或模組物件；`triples`、`fact_results`、`cfg`、`embedding_provider`、`question_vector` 等則是在閉包內建立／更新的局部狀態。這說明把 `_stream` 機械搬出時，至少要明確傳入 payload、driver/provider/config 與可變的檢索結果，不能只靠 re-export。

## 4. Q3 外部引用完整清單

### AST 的 import 形式

下表涵蓋 `from routers.agent import X`、`from routers import agent`、`import routers.agent`。路徑為 git 相對路徑；同一檔同一 import 行的多個名稱合併列出。

| 檔案:行 | 形式 | 名稱 |
|---|---|---|
| `.claude/tmp/rq1_aggr16_fact_topk_extension.py:18` | from routers.agent | `_find_seed_entities`, `_relevant_doc_ids_from_seeds`, `_resolve_doc_scope` |
| `.claude/tmp/rq1_fact_topk_retrieval_sweep.py:32` | from routers.agent | 同上 |
| `.claude/tmp/rq1_scope_control_runner.py:31` | from routers | `agent` |
| `_run_ablation_arm.py:16`; `_run_ablation_arm_g4.py:14`; `_run_bfs_slots_eval_20260919.py:60`; `_run_fact_boundary_swap_3q_eval_20260919.py:76`; `_run_fact_boundary_swap_eval_20260919.py:55`; `_run_fact_boundary_swap_matched_v2.py:76`; `_run_fact_rank_eval_20260918.py:117`; `_run_fact_rerank_control_matched_v2.py:76`; `_run_fact_side_rerank_eval_20260919.py:63`; `_trace_aggr16_candidate_path_20260918.py:23` | import routers.agent | `routers.agent` |
| `ask_question.py:31`; `run_demo_report.py:24`; `run_demo_report_batch2.py:18`; `run_demo_report_batch3.py:17`; `run_demo_report_extra.py:19`; `run_t2_acceptance.py:20`; `verify_314_fix.py:21` | from routers.agent | `chat` |
| `compare_doc_scope_retrieval.py:55` | from routers.agent | `_filter_triples_by_source_doc_ids`, `_find_seed_entities`, `_intersect_doc_scopes`, `_relevant_doc_ids_from_facts` |
| `main.py:23`; `run_retrieval_comparison.py:57`; `scripts/eval/diagnose_prompt_noise.py:37`; `scripts/eval/gap_s3_01_context_ablation.py:23`; `scripts/eval/run_rq1_comparison.py:56` | from routers | `agent` |
| `scripts/eval/diagnose_retrieval_failures.py:29` | from routers.agent | `_find_seed_entities`, `_relevant_doc_ids_from_seeds`, `_resolve_doc_scope` |
| `tests/core/test_kg_config.py:33`; `tests/routers/test_agent.py:9`; `tests/scripts/test_rq1_metric_judge.py:14` | import routers.agent / from routers | `agent` |

這是 39 個 AST import record；同一行的 alias 分開計數。`main.py:23` 的 production 用法是 `agent.router`，不是私有函式。

### AST 的 `agent.X` 屬性存取

下表是 290 個屬性 AST 節點按檔案／名稱合併後的完整清單；同一名稱的多個行號全部保留。

| 檔案 | 屬性與行號 |
|---|---|
| `.claude/tmp/rq1_scope_control_runner.py` | `agent.chat`:85,164；`agent.vector_search_facts`:167,173；`agent.get_llm_provider`:215,217,225；`agent.get_judge_llm_provider`:216,218,226 |
| `_run_ablation_arm.py` | `agent.chat`:23,43；`agent.vector_search_facts`:24,42 |
| `_run_ablation_arm_g4.py` | `agent.chat`:21,41；`agent.vector_search_facts`:22,40 |
| `_run_bfs_slots_eval_20260919.py` | `agent._arrange_fact_lines`:63,73 |
| `_run_fact_boundary_swap_3q_eval_20260919.py` | `agent.chat`:79,200；`agent._split_fact_lines`:80,198；`agent._arrange_fact_lines`:81,199；`agent._strip_type_markers`:106；`agent._score_lines_by_embedding`:133 |
| `_run_fact_boundary_swap_eval_20260919.py` | `agent.chat`:58,153；`agent._split_fact_lines`:59,151；`agent._arrange_fact_lines`:60,152；`agent._strip_type_markers`:79；`agent._score_lines_by_embedding`:105 |
| `_run_fact_boundary_swap_matched_v2.py` | `agent.chat`:79,200；`agent._split_fact_lines`:80,198；`agent._arrange_fact_lines`:81,199；`agent._strip_type_markers`:106；`agent._score_lines_by_embedding`:133 |
| `_run_fact_rank_eval_20260918.py` | `agent.chat`:119,145；`agent.vector_search_facts`:120,144 |
| `_run_fact_rerank_control_matched_v2.py` | `agent.chat`:79,200；`agent._split_fact_lines`:80,198；`agent._arrange_fact_lines`:81,199；`agent._strip_type_markers`:106；`agent._score_lines_by_embedding`:133 |
| `_run_fact_side_rerank_eval_20260919.py` | `agent.chat`:66,151；`agent._split_fact_lines`:67,149；`agent._arrange_fact_lines`:68,150；`agent._strip_type_markers`:88；`agent._score_lines_by_embedding`:99 |
| `_trace_aggr16_candidate_path_20260918.py` | `_find_seed_entities`:63；`_relevant_doc_ids_from_seeds`:71；`_resolve_doc_scope`:72,140；`_arrange_fact_lines`:128,177；`_split_fact_lines`:127,152,159,174；`_relevant_doc_ids_from_facts`:137；`bfs_query`:143；`_filter_triples_by_relation_type`:160,171；`_filter_triples_by_source_doc_ids`:170；`_score_lines_by_embedding`:185 |
| `main.py` | `agent.router`:121 |
| `run_retrieval_comparison.py` | `agent.chat`:162；`agent._generate_from_context_lines`:220；`agent._GenerationResult`:225；`agent.get_llm_provider`:394,395,419；`agent.get_judge_llm_provider`:394,396,419 |
| `scripts/eval/diagnose_prompt_noise.py` | `agent._build_prompt`:94 |
| `scripts/eval/gap_s3_01_context_ablation.py` | `agent._split_into_subquestions`:104；`agent._build_prompt`:118 |
| `scripts/eval/run_rq1_comparison.py` | `agent.chat`:174；`agent._generate_from_context_lines`:330,382；`agent._GenerationResult`:336,388 |
| `tests/core/test_kg_config.py` | `_SEED_ENTITY_LIMIT`:51；`_SEED_MAX_DEGREE`:52；`_BFS_PER_SEED_LIMIT`:53；`_DOC_SCOPE_TOP_N_FACTS`:54；`_FACT_LINE_TRUNCATE_K`:55；`_FACT_LINE_REORDER_THRESHOLD_K`:56；`_BFS_KEEP_MAX`:57；`_MIN_BFS_SLOTS`:58；`_RRF_K`:59；`_MAX_SUBQUESTIONS`:60；`_TIER_MIN_MEMBERS`:61；`_TAIWAN_CONTEXT_INSTRUCTION`:68 |
| `tests/routers/test_agent.py` | `agent.__file__`:1113；`agent._strip_type_markers`:13,19,27,33,36；`agent._merge_fact_lines`:51,65,117,124,206,214,226,227,233,245,258,268,279,289；`agent._split_fact_lines`:82,89,104,1670；`agent._expand_facts_by_article`:174；`agent._build_prompt`:329,341,354,370,431,648,962,968,984,1687,1690,1708；`agent._build_constrained_prompt`:390,414,663；`agent._targeted_correction`:448；`agent._detect_tier_families`:471,477,486,495,501,508；`agent._missing_tier_members`:503,510；`agent._wants_full_enumeration`:515,516,518,519；`agent._score_lines_by_embedding`:532,542,553；`agent._litm_reorder`:561；`agent._arrange_fact_lines`:577,589,603,606,618,633；`agent._find_seed_entities`:860,882,896,931,942,950；`agent._SEED_ENTITY_LIMIT`:876；`agent._SEED_MAX_DEGREE`:929；`agent._drop_hub_seeds`:999,1001；`agent._BFS_PER_SEED_LIMIT`:1052；`agent._TAIWAN_CONTEXT_INSTRUCTION`:969,1163；`agent.KGConfig`:1101,2795,2820,2838,2856；`agent.settings`:1068,1114；`agent._filter_triples_by_relation_type`:1310,1320,1326；`agent._relevant_doc_ids_from_facts`:1340,1354,1360,1431,1432；`agent._filter_triples_by_source_doc_ids`:1374,1386,1401,1415；`agent._filter_facts_by_source_doc_ids`:1447,1460,1461；`agent._build_retrieval_telemetry`:1552,1561；`agent._serialize_sources`:1574,1591,1601,1615,1733,1749；`agent._build_retrieval_trace`:1629,1646,1655,1671,1697；`agent._fetch_document_map`:1765,1793；`agent._GenerationResult`:2783；`agent._generate_from_context_lines`:2794,2819,2837,2855；`agent._intersect_doc_scopes`:2425,2426,2431,2436,2442；`agent._relevant_doc_ids_from_seeds`:2471,2482；`agent._resolve_doc_scope`:2491,2499,2503,2510,2518; `agent.chat`:1047,1098,1157,1162,1204,1248,1286,1298,1498,1539,1830,1876,1927,1968,2010,2052,2101,2122,2143,2173,2218,2247,2279,2315,2343,2359,2375,2563,2599,2637,2657,2681,2714,2740,2760 |
| `tests/scripts/test_rq1_metric_judge.py` | `agent._GenerationResult`:147 |

特別注意 `scripts/eval/run_rq1_comparison.py:56` 是 `from routers import agent`，其屬性使用位於 `:174` 的 `agent.chat`、`:330,382` 的 `agent._generate_from_context_lines`、`:336,388` 的 `agent._GenerationResult`；這是未涵蓋單純字串搜尋「from routers.agent import」的私有 fan-in。

以名稱看，production 真正使用的是 `main.py:121 agent.router`；`services/` 沒有 runtime `agent` 屬性依賴，只有 `services/svo_service.py:2349` 的說明文字。腳本／harness 使用 `chat`、`_generate_from_context_lines`、`_GenerationResult`、檢索與 context helpers；測試則直接觸及幾乎所有純 helper 及大量模組常數。

### getattr／字串形式

AST 沒有找到任何 runtime `getattr(agent, "...")` 或 `getattr(routers.agent, "...")`。找到 4 個含 `routers.agent` 的字串／docstring：`_run_ablation_arm.py:1`、`_run_bfs_slots_eval_20260919.py:1`、`scripts/eval/gap_s3_01_context_ablation.py:1`、`services/svo_service.py:2349`。前 3 個是腳本說明文字，後者是 RRF 複製的 docstring，均不是 runtime dependency。這明確區分了任務要求的 getattr／字串形式，而沒有把文字引用誤報成呼叫。

## 5. Q4 測試補丁點與 re-export 陷阱判斷

AST 掃描 `tests/` 找到 **158 條**替換，全部是 `tests/routers/test_agent.py` 的 `monkeypatch.setattr(agent, "名稱", fake)`；沒有 `monkeypatch.setattr("routers.agent...", ...)`、`unittest.mock.patch`、`patch.object`，也沒有 fixture 對 `agent.X` 的賦值。每一列下方的名稱順序與來源行一一對應；`(b)` 表示若呼叫端與名稱一起搬走、agent.py 只留 re-export，patch 會靜默失效。這些判斷是逐段閱讀每個列出的測試／fixture 後作成，不是只由 AST 名稱推測。

| 測試檔:行號 | 被替換名稱（逐行順序） | 測試／fixture | 判斷 |
|---|---|---|---|
| `tests/routers/test_agent.py:857` | `vector_search_entities` | `test_find_seed_entities_prefers_literal_match_over_vector_fallback` | **(b)** |
| `tests/routers/test_agent.py:879` | `vector_search_entities` | `test_find_seed_entities_falls_back_to_vector_search_when_no_literal_match` | **(b)** |
| `tests/routers/test_agent.py:1036-1044` | `_find_seed_entities`; `_relevant_doc_ids_from_seeds`; `bfs_query`; `vector_search_facts`; `resolve_query_relation_type`; `_fetch_document_map`; `get_driver`; `get_embedding_provider`; `get_llm_provider` | `test_chat_runs_semantic_search_before_bfs_and_passes_scope` | **(b) ×9** |
| `tests/routers/test_agent.py:1088-1096` | `_find_seed_entities`; `_relevant_doc_ids_from_seeds`; `bfs_query`; `vector_search_facts`; `resolve_query_relation_type`; `_fetch_document_map`; `get_driver`; `get_embedding_provider`; `get_llm_provider` | `test_chat_applies_per_kg_profile_from_file_config_source` | **(b) ×9** |
| `tests/routers/test_agent.py:1144-1154` | `KGRepository`; `_find_seed_entities`; `_relevant_doc_ids_from_seeds`; `bfs_query`; `vector_search_facts`; `resolve_query_relation_type`; `_fetch_document_map`; `_build_prompt`; `get_driver`; `get_embedding_provider`; `get_llm_provider` | `test_chat_selects_domain_pack_from_kg_node` | **(b) ×11** |
| `tests/routers/test_agent.py:1194-1201` | `_find_seed_entities`; `_relevant_doc_ids_from_seeds`; `bfs_query`; `vector_search_facts`; `get_driver`; `get_embedding_provider`; `get_llm_provider`; `resolve_query_relation_type` | `test_chat_wires_vector_search_facts_with_question_embedding_and_top_k` | **(b) ×8** |
| `tests/routers/test_agent.py:1238-1246` | `_find_seed_entities`; `_relevant_doc_ids_from_seeds`; `bfs_query`; `vector_search_facts`; `resolve_query_relation_type`; `_fetch_document_map`; `get_driver`; `get_embedding_provider`; `get_llm_provider` | `test_chat_passes_resolved_doc_scope_to_fact_search` | **(b) ×9** |
| `tests/routers/test_agent.py:1280-1283` | `vector_search_facts`; `get_driver`; `get_embedding_provider`; `get_llm_provider` | `test_chat_skips_semantic_search_when_use_svo_is_false` | **(b) ×4** |
| `tests/routers/test_agent.py:1488-1495` | `_find_seed_entities`; `_relevant_doc_ids_from_seeds`; `bfs_query`; `vector_search_facts`; `resolve_query_relation_type`; `get_driver`; `get_embedding_provider`; `get_llm_provider` | `test_chat_filters_bfs_triples_by_resolved_relation_type` | **(b) ×8** |
| `tests/routers/test_agent.py:1529-1536` | `_find_seed_entities`; `_relevant_doc_ids_from_seeds`; `bfs_query`; `vector_search_facts`; `resolve_query_relation_type`; `get_driver`; `get_embedding_provider`; `get_llm_provider` | `test_chat_keeps_all_triples_when_relation_type_unresolved` | **(b) ×8** |
| `tests/routers/test_agent.py:1763` | `LawDocumentRepository` | `test_fetch_document_map_dedupes_and_skips_lookup_when_no_doc_ids` | **(b)** |
| `tests/routers/test_agent.py:1789` | `LawDocumentRepository` | `test_fetch_document_map_returns_map_keyed_by_source_doc_id_string` | **(b)** |
| `tests/routers/test_agent.py:1820-1827` | `_find_seed_entities`; `_relevant_doc_ids_from_seeds`; `bfs_query`; `vector_search_facts`; `resolve_query_relation_type`; `get_driver`; `get_embedding_provider`; `get_llm_provider` | `test_chat_yields_sources_event_after_answer_stream` | **(b) ×8** |
| `tests/routers/test_agent.py:1866-1873` | `_find_seed_entities`; `_relevant_doc_ids_from_seeds`; `bfs_query`; `vector_search_facts`; `resolve_query_relation_type`; `get_driver`; `get_embedding_provider`; `get_llm_provider` | `test_chat_yields_grounding_event_after_sources` | **(b) ×8** |
| `tests/routers/test_agent.py:1917-1924` | `_find_seed_entities`; `_relevant_doc_ids_from_seeds`; `bfs_query`; `vector_search_facts`; `resolve_query_relation_type`; `get_driver`; `get_embedding_provider`; `get_llm_provider` | `test_chat_converts_simplified_chinese_in_final_answer_to_traditional` | **(b) ×8** |
| `tests/routers/test_agent.py:1958-1965` | `_find_seed_entities`; `_relevant_doc_ids_from_seeds`; `bfs_query`; `vector_search_facts`; `resolve_query_relation_type`; `get_driver`; `get_embedding_provider`; `get_llm_provider` | `test_chat_grounding_check_includes_bfs_triples_not_just_vector_facts` | **(b) ×8** |
| `tests/routers/test_agent.py:1999-2006` | `_find_seed_entities`; `_relevant_doc_ids_from_seeds`; `bfs_query`; `vector_search_facts`; `resolve_query_relation_type`; `get_driver`; `get_embedding_provider`; `get_llm_provider` | `test_chat_uses_dedicated_judge_provider_for_grounding_when_configured` | **(b) ×8** |
| `tests/routers/test_agent.py:2042-2049` | `_find_seed_entities`; `_relevant_doc_ids_from_seeds`; `bfs_query`; `vector_search_facts`; `resolve_query_relation_type`; `get_driver`; `get_embedding_provider`; `get_llm_provider` | `test_chat_yields_empty_grounding_event_when_no_facts_retrieved` | **(b) ×8** |
| `tests/routers/test_agent.py:2078-2085` | `_find_seed_entities`; `_relevant_doc_ids_from_seeds`; `bfs_query`; `vector_search_facts`; `resolve_query_relation_type`; `get_driver`; `get_embedding_provider`; `get_llm_provider` | `_chat_common_monkeypatch` fixture helper | **(b) ×8** |
| `tests/routers/test_agent.py:2411-2419` | `_find_seed_entities`; `_relevant_doc_ids_from_seeds`; `bfs_query`; `vector_search_facts`; `resolve_query_relation_type`; `_fetch_document_map`; `get_driver`; `get_embedding_provider`; `get_llm_provider` | `_instrumented_chat_monkeypatch` fixture helper | **(b) ×9** |
| `tests/routers/test_agent.py:2553-2561` | `_find_seed_entities`; `_relevant_doc_ids_from_seeds`; `bfs_query`; `vector_search_facts`; `resolve_query_relation_type`; `_fetch_document_map`; `get_driver`; `get_embedding_provider`; `get_llm_provider` | `test_chat_seed_anchored_scope_overrides_noisy_semantic_scope` | **(b) ×9** |
| `tests/routers/test_agent.py:2591-2597` | `_find_seed_entities`; `_relevant_doc_ids_from_seeds`; `bfs_query`; `_fetch_document_map`; `get_driver`; `get_embedding_provider`; `get_llm_provider` | `test_chat_bfs_only_now_gets_seed_anchored_scope_pushdown` | **(b) ×7** |
| `tests/routers/test_agent.py:2629-2635` | `_find_seed_entities`; `vector_search_facts`; `resolve_query_relation_type`; `_fetch_document_map`; `get_driver`; `get_embedding_provider`; `get_llm_provider` | `test_chat_fact_only_does_not_compute_seeds` | **(b) ×7** |

合計核對：`1+1+9+9+11+8+9+4+8+8+1+1+8+8+8+8+8+8+8+9+9+7+7 = 158`。沒有 (a) 或 (c) 的實際替換行；所有 (b) 都特別以粗體標出。原因是這些 patch 都控制「搬走後的 retrieval／generation／`_stream` 呼叫端」或其直接依賴；單純把舊名稱 re-export 到 `agent` 不會改變新模組內的全域名稱解析。`agent.chat` 本身在這 158 條中沒有被替換；route 仍可能留在 agent，但不會挽救其搬走的 `_stream` 內依賴。

## 6. Q5 模組層級狀態與匯入

### 匯入清單

`routers/agent.py` 的 import（靜態腳本完整輸出）如下：

```text
from __future__ import annotations
import asyncio, json, logging, re, time
from pathlib import Path
from typing import NamedTuple
from uuid import UUID
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from neo4j import AsyncDriver
from core.config import settings
from core.constants import ENTITY_TYPES
from core.database import get_driver
from core.kg_config import ConfigLoader, FileConfigSource, KGConfig
from core.providers.base import EmbeddingProvider, LLMProvider
from core.providers.factory import get_embedding_provider, get_judge_llm_provider, get_llm_provider
from models.document import ChatMessage, ChatRequest
from models.knowledge_graph import SVOTriple
from models.law_document import LawDocument
from repositories.kg_repo import KGRepository
from repositories.law_document_repo import LawDocumentRepository
from services.classify_service import cosine_similarity
from services.svo_service import _kg_source_charset, _to_traditional_selective,
    bfs_query, resolve_query_relation_type, vector_search_entities, vector_search_facts
from services.interval_lookup_service import evaluate_lookup_override, is_refusal_text
from services.verification_service import ClaimGrounding, verify_fact_grounding
```

標稱的 15 個 fan-out 方向可歸納為 stdlib（`asyncio/json/logging/re/time/pathlib/typing/uuid`）、FastAPI、Neo4j、`core`、`models`、`repositories`、`services`；上表保留每個 import symbol，避免把同一 package 的風險誤算成少數依賴。

### import-time 行為與共享狀態

- `router` 與 `logger` 在 `routers/agent.py:46,48` 建立；router decorator 在 `chat` 定義時登錄 route。這是最重要的 HTTP 副作用，應留在路由層。
- 文字／數值常數與 regex 在 `routers/agent.py:55-90,165,688-703,832-841,907-925,1077,1192` 建立。它們沒有檔案、Neo4j、Ollama 或網路讀取。
- `settings` 在 `routers/agent.py:15` 匯入；真正使用位置是 `_generate_from_context_lines:1629-1630` 的 workspace path 與 `chat:1699-1716` 的 KG config 讀取。這不是載入 agent 時讀完整設定檔的行為；拆分時要共享同一 settings 物件或明確傳入。
- `KGConfig()`、provider、repository 都在函式執行時建立／取得（例如 `chat:1694-1716`、`_build_prompt:1280`、`_generate_from_context_lines:1439-1633`）；沒有模組級 cache。
- 沒有 `global`／`nonlocal` 寫入；函式內的 lists/dicts 是局部狀態。真正需要跟著流程傳遞的是 `payload`、`cfg`、`driver`、providers、`triples`、`fact_results`、`resolved_rel_type`、`prompt_trace` 及 `gen_result`。

最值得注意的匯入風險是 `services.svo_service` 一次帶入 BFS、向量檢索、關係解析與轉繁工具（`routers/agent.py:31-37`）；若新的 context／retrieval 模組又被 `svo_service` 反向引用，會形成 cycle。`services.verification_service` 與 `interval_lookup_service` 也會被 generation stack 使用，不能讓 context 層反向 import generation。

## 7. Q6 `chat`／`_generate_from_context_lines` 流程地圖

### `chat`／`_stream`（`routers/agent.py:1637-1904`）

| 步驟 | 行號 | 輸入 → 輸出 | I/O／BT 節點 |
|---|---:|---|---|
| HTTP route 建立 `_stream` | 1637-1686、1904 | `payload` → `StreamingResponse` | HTTP，入口／出口 |
| 缺 KG 立即送 error SSE | 1687-1692 | `payload.kg_id` → error event | 無外部 I/O，BT guard |
| 取得 driver、生成 LLM、judge LLM | 1694-1699 | provider factories → providers | driver/provider I/O；N11 前置 |
| 讀 KG metadata、domain pack、cfg | 1700-1716 | `kg_id`, settings → `kg_meta`, `cfg` | Neo4j + config 檔；BT config |
| 初始化 embedding、vector、triples、facts、relation、計時器 | 1717-1743 | cfg/payload → 可變區域狀態 | 無外部 I/O；檢索前 |
| encode 問題與決定 `run_bfs`／`run_facts` | 1744-1754 | question → `question_vector`, mode flags | embedding I/O；N9 |
| BFS 種子與種子文件範圍 | 1755-1763 | driver/question/vector/cfg → `seeds`, `seed_doc_ids` | Neo4j + embedding；N9 |
| Fact 檢索前置範圍 | 1764-1784 | seed scope + explicit scope → fact scope → facts | Neo4j/vector search；N9 |
| 語意文件範圍與 BFS | 1785-1808 | facts/seeds → `semantic_doc_ids`, `relevant_doc_ids`, triples | Neo4j；N9 |
| relation type 解析與三元組後篩 | 1809-1818 | question/providers/triples → `resolved_rel_type`, triples | LLM/embedding + 純過濾；N9 |
| 來源範圍兜底與 article expand | 1819-1838 | triples/facts/scope → final retrieval lists | 純過濾；可選 Neo4j article expand；N9 |
| 建遙測 | 1839-1843 | final lists + timer → telemetry | 純；N13 |
| 共用生成產生器 | 1844-1862 | payload/cfg/providers/lists → SSE status + `gen_result` | LLM/judge；N11 |
| 將最終答案送出 | 1863-1867 | `gen_result.final_answer` → token SSE | HTTP |
| 查文件、序列化 sources／trace | 1868-1888 | lists + telemetry + prompt_trace → sources SSE | Neo4j repository + 純序列化；N13 |
| grounding 與 done 狀態 | 1889-1902 | grounding/regenerated → grounding/done SSE | HTTP |

步驟之間共享的可變物件包括 `triples`、`fact_results`（先檢索、再過濾、可能 article expand，最後給 generation 與 sources）、`prompt_trace`（可選 list，由 generation 填入、trace 讀取）、`cfg`、providers、`resolved_rel_type`、`gen_result`。`_stream` 直接捕獲 `payload`，也是搬出時最容易漏傳的狀態。

### `_generate_from_context_lines`（`routers/agent.py:1439-1633`）

| 步驟 | 行號 | 輸入 → 輸出 | I/O／BT 節點 |
|---|---:|---|---|
| 判 baseline、正規化 lists、拆子問題 | 1476-1482 | `context_lines`, triples/facts → flags/lists/subquestions | 純；N10→N11 |
| 送 generating 狀態並產草稿 | 1484-1503 | question/context/providers → `draft_answer` | LLM；N11 |
| 形成 grounding text | 1505-1510 | baseline lines 或 `_merge_fact_lines` → `fact_texts`, context flag | 純；N10 |
| 送 verifying、第一次接地核對 | 1512-1517 | draft/facts/judge → grounding claims | judge LLM；N11 |
| 確定性 interval override | 1519-1548 | question/facts/draft/grounding → `ungrounded_claims`, extra note | 純規則；N11 |
| 未接地時選重生路徑 | 1550-1601 | mode、claims、subquestions、lists → final answer | LLM；targeted／constrained／decomposed |
| 重生後再次核對 | 1602-1604 | final answer/facts/judge → grounding | judge LLM |
| 完整列舉 guard | 1606-1626 | question/families/final → supplement 或再次生成 | 純 + LLM；N11 |
| 轉繁與結果 yield | 1628-1633 | final + workspace/source charset → `_GenerationResult` | 可能依服務讀取 charset；N11 |

這個 generator 的共享狀態是 `sub_questions`、`triples`、`fact_results`、`fact_texts`、`grounding`、`ungrounded_claims`、`final_answer`、`regenerated` 與可變 `prompt_trace`。尤其 `grounding` 的原始 supported 欄位與 interval override 產生的 `ungrounded_claims` 有刻意分離；拆分不能把兩者錯誤合併（`routers/agent.py:1528-1548`）。

## 8. Q7 候選第一刀評估

外部使用者數以目前 AST `agent.X`／直接 import 的檔案去重估算；「直接測試」指測試直接呼叫該名稱，不只經 `chat` 間接走到。快照欄位：L1=檢索軌跡與 prompt context、L2=答案／stage3、L3=atomic score；pytest=既有單元／路由測試。

| 候選 | 純度／行數 | 外部使用者；直接測試 | Q4 補丁 | 風險與補強 |
|---|---|---|---:|---|
| `_rrf_order` | 純／22，`991-1012` | 0；無直接測試，僅 `_arrange_fact_lines` 間接 | 0 | **低至中**：L1 可抓排序差異，但沒有直接 golden；先補 rank tie／missing rank 單元測試 |
| `_litm_reorder` | 純／20，`969-988` | 0；`test_litm_reorder_places_most_relevant_at_both_ends`（`tests/routers/test_agent.py:557`） | 0 | **低**：pytest 直接覆蓋，長清單仍需 L1；re-export 不會影響純測試本身但其 caller patch 仍有風險 |
| `_split_fact_lines` | 純／88，`727-814` | 7 個腳本檔；多個直接測試（`test_split_fact_lines_*`、`test_merge_fact_lines_*` 間接） | 0（caller patch 另計） | **中**：去重、空 object、型別標記可由 pytest，實際 prompt 順序由 L1；外部腳本是私有 API |
| `_merge_fact_lines` | 純／7，`817-823` | 0；14 個直接測試在 `tests/routers/test_agent.py:46-289` | 0 | **低**：單元安全網強，但 grounding text 變化需 pytest／L2；搬走後直接 import 仍需 re-export |
| `_arrange_fact_lines` | embedding／58，`1015-1072` | 8 個腳本檔；`test_arrange_fact_lines_*`（`570-633`） | 0 | **中至高**：涉及 embedding、K/名額/RRF/LITM；L1 最敏感，需固定 provider 的單元與完整 trace |
| `_build_prompt` | 組合／90，`1259-1348` | 3 個腳本檔；`test_build_prompt_*`（`323-431,640-984,1678-1708`） | 1 個 chat domain-pack patch | **中**：prompt 文字變更主要由 L1 prompt_context／pytest 抓；需 baseline context、history、trace sink golden |
| `_build_constrained_prompt` | 組合／79，`1351-1429` | 0；直接測試 `382-414,655` | 0 | **中**：L2/L3 才看得到限制性重生內容；需缺口 note、空 facts、history 單元 |
| `_serialize_sources` | 純／61，`620-680` | 0；直接測試 `1569-1749` | 0 | **低**：pytest 直接驗欄位，L1 sources 也可見；document 缺失與 telemetry/trace 要保持 |
| `_build_retrieval_trace` | 純／57，`561-617` | 0；直接測試 `1618-1671` | 0 | **低至中**：L1 會直接捕捉 trace，仍要保留 rendered-line 與 `None` 語義 |
| `_build_retrieval_telemetry` | 純／20，`539-558` | 0；直接測試 `1548-1561` | 0 | **低**：不納入報告136 L1 比對的耗時欄位；pytest 驗 count/latency rounding |
| `_find_seed_entities`／`_drop_hub_seeds` | Neo4j／42+21，`93-157` | 2 個腳本檔加 trace；直接測試 `847-1001` | 158 條 chat patch 中多條 | **高**：字面→語意 fallback、hub degree、scope 都是快照盲區；需 fake driver、fallback、all-hub、single candidate 測試與 L1 |
| `_expand_facts_by_article` | Neo4j／139，`342-480` | 0；`test_article_expand_adds_capped_deduped_siblings_per_article:140` | 0 | **中至高**：固定 6 題不保證 article expand 路徑；需離線 fake records、limit/dedupe 與 L1 |
| `_split_into_subquestions` | 純／32，`1080-1111` | 1 個腳本檔；直接測試 `674-700` | 0 | **低至中**：pytest 直接覆蓋，但 chat 端多子問題選路影響 L2；17-Q1 L2 本身不穩，應加生成器單元 |

其他可拆候選：`_serialize_document`（`528-536`）與 `_filter_*`／scope 純 helper（`204-339,483-492`）外部耦合較低；`_generate_from_context_lines`（`1439-1633`）雖是共用點但同時接 generation、verification、interval lookup、設定與 baseline contract，不建議把它當低風險第一刀。這裡只列選項與風險，沒有替使用者決定第一刀。

## 9. Q8 既有測試覆蓋

### 測試檔

AST import／git grep 顯示直接測 `agent.py` 的測試檔為：

- `tests/routers/test_agent.py`：純 helper、retrieval、chat SSE、generation baseline 的主要測試。
- `tests/core/test_kg_config.py`：讀取 agent 模組常數，驗證 `KGConfig` 預設 golden 值（`33,51-68`）。
- `tests/scripts/test_rq1_metric_judge.py`：讀 `agent._GenerationResult`（`14,147`）。

### 直接單元測試

`tests/routers/test_agent.py` 直接測的私有函式與測試群如下（同群的測試名稱以前綴表示）：

| 函式 | 直接測試名稱／行號 |
|---|---|
| `_strip_type_markers` | `test_strip_type_markers_*`：`12,18,24,30` |
| `_merge_fact_lines`、`_split_fact_lines` | `test_merge_fact_lines_*`：`46-289`；`test_split_fact_lines_prefer_fact_on_collision_*`：`71,95` |
| `_expand_facts_by_article` | `test_article_expand_adds_capped_deduped_siblings_per_article:140` |
| `_build_prompt`、`_build_constrained_prompt` | `test_build_prompt_*`：`323-431,640-700,956-984,1678-1708`；`test_build_constrained_prompt_*`：`382-414,655` |
| `_targeted_correction` | `test_targeted_correction_prompt_carries_tier_rule:441`，chat correction tests `2257-2325` 間接 |
| `_detect_tier_families`、`_missing_tier_members`、`_wants_full_enumeration` | `test_detect_tier_families_*:470-501`、`test_missing_tier_members_*:500-507`、`test_wants_full_enumeration_gate:513` |
| `_score_lines_by_embedding`、`_litm_reorder`、`_arrange_fact_lines` | `test_score_lines_by_embedding_*:527-550`、`test_litm_reorder_places_most_relevant_at_both_ends:557`、`test_arrange_fact_lines_*:570-633` |
| `_split_into_subquestions`、decomposed helpers | `test_split_into_subquestions_*:674-700`、`test_generate_decomposed_answer_*:706-750` |
| `_find_seed_entities`、`_drop_hub_seeds` | `test_find_seed_entities_*:847-950`、`test_drop_hub_seeds_uses_cfg_seed_max_degree:992` |
| relation／scope filters | `test_filter_triples_by_relation_type_*:1307-1330`、`test_relevant_doc_ids_from_facts_*:1332-1361`、`test_filter_*_by_source_doc_ids_*:1363-1463`、`test_intersect_doc_scopes_*:2423-2442`、`test_relevant_doc_ids_from_seeds_*:2464-2484`、`test_resolve_doc_scope_*:2487-2519` |
| `_build_retrieval_telemetry`、`_build_retrieval_trace`、`_serialize_sources`、`_fetch_document_map` | `1548-1793` 的對應 `test_*` 群 |
| `_generate_from_context_lines`、`_GenerationResult` | `test_generate_from_context_lines_*:2791-2868`；`_GenerationResult` 亦於 `tests/scripts/test_rq1_metric_judge.py:147` |

### 只有 chat 間接覆蓋／安全網最薄處

`_scope_by_source_doc_ids`（`288-306`）、`_serialize_document`（`528-536`）、`_fact_verb`（`847-857`）、`_is_contentful_line`（`709-724`）沒有獨立 test name，主要由 filter／serialize／tier／split 測試間接覆蓋。`_rrf_order` 也沒有直接 test，只有 `_arrange_fact_lines` 路徑間接覆蓋。`chat` 的 retrieval mode、SSE ordering、grounding、scope、domain pack 則有大量端到端式 fake-provider 測試（`1005-2760`）。這些是拆分時最缺安全網的函式；應在實作前補純離線單元或保留等價契約測試。

## 10. Q9 相依分層草案

這是只讀盤點的提案，不是實作決定。依報告97 §6.3-§6.4，可採以下單向依賴：

```text
routers/agent.py (router + compatibility facade)
                 |
          workflows/chat.py (SSE orchestration)
          /          |             \
 services/retrieval  services/context  services/generation
          |                |              |
 repositories/models  models/providers  verification/interval
```

- `routers/agent.py` 留 `router`、公開 `chat` route 與相容 facade/re-export；它不應再成為新 service 的依賴來源。
- `workflows/chat.py` 接收 payload、建立 cfg/providers，協調 retrieval → context/generation → sources/SSE；它可以依賴三個 service layer，但三個 service 不互相 import workflow。
- `services/retrieval/` 放 `_find_seed_entities`、`_drop_hub_seeds`、文件 scope、filter、`_expand_facts_by_article`，以及需要 repository 的 document map。它依賴 `svo_service`、models、repositories，不依賴 generation/context。
- `services/context/` 放 `_strip_type_markers`、`_is_contentful_line`、`_split_fact_lines`、`_merge_fact_lines`、`_score_lines_by_embedding`、`_litm_reorder`、`_rrf_order`、`_arrange_fact_lines`、`_build_prompt`、`_build_constrained_prompt`。它依賴 models、embedding provider、設定，不依賴 generation。
- `services/generation/` 放 `_split_into_subquestions`、decomposed helpers、`_targeted_correction`、`_generate_from_context_lines` 與 `_GenerationResult`；它可以依賴 context、verification、interval lookup、providers，但 context 不得反向 import generation。
- 遙測／來源序列化可放 workflow 的 telemetry 子模組或獨立 `services/telemetry`：`_build_retrieval_trace` 需使用 context 的渲染規則，應以明確 helper 依賴或注入 renderer，避免 telemetry→context→generation 的反向環。

目前最可能製造 cycle 的地方是：`_generate_from_context_lines` 同時呼叫 context prompt builders、verification 與 interval lookup；`_arrange_fact_lines` 需要 embedding；`_build_retrieval_trace` 需要 `_strip_type_markers`；`_stream` 同時持有 retrieval、generation、repository 與 SSE。若把它們照檔案段落直接搬，而不是依上述方向抽介面，會出現 context import generation 或 service import `routers.agent` 的反向依賴。

## 11. Q10 驗收流程可行性與快照盲區

報告136 的 K 臂快照對 6 題的 L1 以 `retrieved_fact_ids`、`retrieved_chunk_ids`、`retrieval_trace`、`prompt_context_lines` 做逐字比較；L2 對 5 個基準穩定題比 `answer` 與 stage3 四欄，17-Q1 的基準 L2 不穩定而改看 L3；L3 比 `is_perfect`、`supported_spans`、`missing_spans`。任一 record error 非空或缺題都應失敗。這足以抓到已覆蓋題目中的檢索排序、scope、prompt 行、答案與 atomic score 退化。

快照仍抓不到或不能單獨證明的項目：

1. 題組只有 6 題，不能代表所有 retrieval mode、空輸入、異常與長清單；沒有保證覆蓋種子字面命中、無命中後 embedding fallback、all-hub、single candidate、`fact_only`、`bfs_only`、`use_svo=False`、explicit scope、article expand、missing Document。
2. L1 是結果型契約，無法指出是哪個內部函式改錯，也無法驗證 import-time router registration、re-export patch 相容性、所有 scripts 的私有 API。
3. 17-Q1 L2 基準本來不穩定；只能用 L3 不退步，不能把生成文字差異誤判成拆分退化。
4. 固定題目不覆蓋所有 `chat()` 錯誤分支、provider exception、空 Facts、prompt trace `None`／baseline、document metadata 與 telemetry 欄位的每一種組合。
5. 快照不會自動檢查 module import cycle、模組載入副作用、`agent.X` monkeypatch 是否仍真正注入搬走後的 caller，也不會檢查外部 scratch scripts 未列入題目的呼叫。

各候選的額外補強：純重排候選補 tie、空清單、長短邊界的 deterministic unit；`_split_fact_lines`／`_merge_fact_lines` 補空 object、型別標記、collision、prefer flag；`_arrange_fact_lines` 補固定 embedding provider 的 K／BFS floor／RRF／LITM golden；prompt builders 補 history、baseline context、trace sink、constrained note；retrieval helpers 補 fake driver 的 literal/fallback/hub/scope/article records；`_generate_from_context_lines` 補四種 regeneration／enumeration／disable 分支。所有搬移都應另跑 import/re-export compatibility test，不能只依賴 K 快照。

## 12. 需要使用者／Claude 決定的事項

- 第一刀是否從 `_rrf_order`／`_litm_reorder` 這類純 helper 開始，或先處理一個更有外部價值但風險較高的 context/retrieval 邊界。
- re-export 是否只保留名稱，或改採明確 public facade／dependency injection；本報告的 Q4 證據顯示「只 re-export」會使 158 條測試 patch 靜默失效。
- `_build_prompt`、`_build_constrained_prompt` 是否同屬 context layer，及 telemetry trace 對 `_strip_type_markers` 的依賴要採直接 import 還是注入 renderer。
- 是否先補 Q8 列出的薄弱單元測試，再建立第一刀任務書；本報告沒有替使用者做最終拆分決定。

## 附錄 A：靜態分析腳本

以下是實際放在系統暫存目錄、未進版控的 `C:\Users\666\AppData\Local\Temp\report137_agent_ast_20260930_01.py` 全文：

```python
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


def assigned_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and child is not node:
            continue
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
            names.add(child.id)
        elif isinstance(child, ast.arg):
            names.add(child.arg)
        elif isinstance(child, ast.alias):
            names.add(child.asname or child.name.split(".")[0])
    return names


def calls_in(node: ast.AST, local_names: set[str]) -> list[dict]:
    calls = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        callee = None
        if isinstance(child.func, ast.Name):
            callee = child.func.id
        elif isinstance(child.func, ast.Attribute):
            callee = child.func.attr
        if callee in local_names:
            calls.append({"line": child.lineno, "callee": callee})
    return calls


def local_bindings(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names = {arg.arg for arg in (*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs)}
    if fn.args.vararg:
        names.add(fn.args.vararg.arg)
    if fn.args.kwarg:
        names.add(fn.args.kwarg.arg)
    for child in ast.walk(fn):
        if child is fn:
            continue
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(child.name)
            continue
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
            names.add(child.id)
        elif isinstance(child, ast.alias):
            names.add(child.asname or child.name.split(".")[0])
        elif isinstance(child, ast.ExceptHandler) and child.name:
            names.add(child.name)
    return names


def captured_names(fn: ast.FunctionDef | ast.AsyncFunctionDef, outer_names: set[str]) -> list[str]:
    local = local_bindings(fn)
    loaded: set[str] = set()
    for child in ast.walk(fn):
        if child is fn:
            continue
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            loaded.add(child.id)
    return sorted((loaded - local) & outer_names)


def function_record(fn, qualname: str, local_names: set[str], outer_names: set[str]) -> dict:
    nested = []
    for child in fn.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            nested.append(function_record(child, f"{qualname}.{child.name}", local_names, outer_names))
    local = local_bindings(fn)
    reads = sorted(
        {
            child.id
            for child in ast.walk(fn)
            if isinstance(child, ast.Name)
            and isinstance(child.ctx, ast.Load)
            and child.id in outer_names
            and child.id not in local
        }
    )
    writes = sorted(
        {
            child.id
            for child in ast.walk(fn)
            if isinstance(child, ast.Name)
            and isinstance(child.ctx, (ast.Store, ast.Del))
            and child.id in outer_names
        }
    )
    return {
        "name": qualname,
        "kind": "async def" if isinstance(fn, ast.AsyncFunctionDef) else "def",
        "start_line": fn.lineno,
        "end_line": getattr(fn, "end_lineno", fn.lineno),
        "lines": getattr(fn, "end_lineno", fn.lineno) - fn.lineno + 1,
        "docstring_first_line": (ast.get_docstring(fn) or "").splitlines()[0] if ast.get_docstring(fn) else "",
        "calls_to_agent_defs": calls_in(fn, local_names),
        "module_global_reads": reads,
        "module_global_writes": writes,
        "captured_from_outer_or_module": captured_names(fn, outer_names),
        "nested": nested,
    }


def main() -> None:
    source_path = Path(sys.argv[1]).resolve()
    output_path = Path(sys.argv[2]).resolve()
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    top_functions = [
        node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    top_classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    local_names = {node.name for node in (*top_functions, *top_classes)}
    imports = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.extend({"kind": "import", "module": alias.name, "as": alias.asname, "line": node.lineno} for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append({"kind": "from", "module": node.module, "names": [alias.name for alias in node.names], "line": node.lineno})
    module_assignments = []
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
            module_assignments.append({"line": node.lineno, "source": ast.get_source_segment(source_path.read_text(encoding="utf-8"), node) or ""})
    outer_names = assigned_names(tree) | {item["module"].split(".")[0] for item in imports if item.get("module")}
    result = {
        "source": str(source_path),
        "source_lines": len(source_path.read_text(encoding="utf-8").splitlines()),
        "top_level_function_count": len(top_functions),
        "top_level_class_count": len(top_classes),
        "top_level_definitions": [function_record(node, node.name, local_names, outer_names) for node in top_functions],
        "top_level_classes": [{"name": node.name, "start_line": node.lineno, "end_line": getattr(node, "end_lineno", node.lineno)} for node in top_classes],
        "module_assignments": module_assignments,
        "imports": imports,
        "agent_function_names": sorted(local_names),
    }
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
```

執行方式：

```text
python C:\Users\666\AppData\Local\Temp\report137_agent_ast_20260930_01.py routers/agent.py C:\Users\666\AppData\Local\Temp\report137_agent_ast_20260930_01.json
```

## 附錄 B：引用掃描腳本

以下是實際放在系統暫存目錄、未進版控的 `C:\Users\666\AppData\Local\Temp\report137_reference_scan_20260930_01.py` 全文：

```python
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path


def source_line(path: Path, lineno: int) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    return lines[lineno - 1].strip() if 0 < lineno <= len(lines) else ""


def dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return None


def literal(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def ancestors(stack: list[ast.AST]) -> str:
    names = [node.name for node in stack if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    return ".".join(names) or "<module>"


def ast_scan(repo: Path) -> dict:
    imports = []
    attribute_accesses = []
    getattr_strings = []
    string_forms = []
    patch_points = []
    assignments = []
    parse_errors = []
    for path in sorted(repo.rglob("*.py")):
        if any(part in {".git", ".venv", "venv", "__pycache__"} for part in path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError) as exc:
            parse_errors.append({"file": str(path.relative_to(repo)), "error": str(exc)})
            continue
        stack: list[ast.AST] = []
        class Visitor(ast.NodeVisitor):
            def visit_FunctionDef(self, node):
                stack.append(node); self.generic_visit(node); stack.pop()
            def visit_AsyncFunctionDef(self, node):
                stack.append(node); self.generic_visit(node); stack.pop()
            def visit_ClassDef(self, node):
                stack.append(node); self.generic_visit(node); stack.pop()
            def visit_ImportFrom(self, node):
                if node.module == "routers.agent":
                    for alias in node.names:
                        imports.append({"file": str(path.relative_to(repo)), "line": node.lineno, "form": "from routers.agent import X", "name": alias.name, "scope": ancestors(stack), "source": source_line(path, node.lineno)})
                elif node.module == "routers":
                    for alias in node.names:
                        if alias.name == "agent":
                            imports.append({"file": str(path.relative_to(repo)), "line": node.lineno, "form": "from routers import agent", "name": alias.asname or alias.name, "scope": ancestors(stack), "source": source_line(path, node.lineno)})
                self.generic_visit(node)
            def visit_Import(self, node):
                for alias in node.names:
                    if alias.name == "routers.agent":
                        imports.append({"file": str(path.relative_to(repo)), "line": node.lineno, "form": "import routers.agent", "name": alias.asname or alias.name, "scope": ancestors(stack), "source": source_line(path, node.lineno)})
                self.generic_visit(node)
            def visit_Attribute(self, node):
                chain = dotted(node)
                if chain and (chain == "agent" or chain.startswith("agent.")):
                    attribute_accesses.append({"file": str(path.relative_to(repo)), "line": node.lineno, "form": "agent.X attribute access", "name": chain, "scope": ancestors(stack), "source": source_line(path, node.lineno)})
                self.generic_visit(node)
            def visit_Constant(self, node):
                if isinstance(node.value, str) and "routers.agent" in node.value:
                    string_forms.append({"file": str(path.relative_to(repo)), "line": node.lineno, "form": "string containing routers.agent", "name": node.value, "scope": ancestors(stack), "source": source_line(path, node.lineno)})
                self.generic_visit(node)
            def visit_Call(self, node):
                callee = dotted(node.func)
                if callee and callee.split(".")[-1] == "getattr" and len(node.args) >= 2:
                    obj = dotted(node.args[0])
                    name = literal(node.args[1])
                    if obj in {"agent", "routers.agent"} and name:
                        getattr_strings.append({"file": str(path.relative_to(repo)), "line": node.lineno, "form": "getattr(agent, string)", "name": f"{obj}.{name}", "scope": ancestors(stack), "source": source_line(path, node.lineno)})
                if callee and callee.split(".")[-1] in {"setattr", "patch", "patch.object"}:
                    args = node.args
                    target = None
                    name = None
                    if callee.endswith("patch.object") and len(args) >= 2:
                        target, name = dotted(args[0]), literal(args[1])
                    elif callee.endswith("setattr") and len(args) >= 2:
                        target, name = dotted(args[0]), literal(args[1])
                    elif callee.endswith("patch") and args:
                        target = literal(args[0])
                        name = target.rsplit(".", 1)[-1] if target else None
                    target_text = f"{target}.{name}" if target and name and not str(target).endswith(str(name)) else target
                    if target_text and ("routers.agent" in target_text or target == "agent"):
                        patch_points.append({"file": str(path.relative_to(repo)), "line": node.lineno, "form": callee, "name": target_text, "scope": ancestors(stack), "source": source_line(path, node.lineno)})
                self.generic_visit(node)
            def visit_Assign(self, node):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and dotted(target.value) == "agent":
                        assignments.append({"file": str(path.relative_to(repo)), "line": node.lineno, "form": "agent.X assignment", "name": target.attr, "scope": ancestors(stack), "source": source_line(path, node.lineno)})
                self.generic_visit(node)
        Visitor().visit(tree)
    return {"imports": imports, "attribute_accesses": attribute_accesses, "getattr_strings": getattr_strings, "string_forms": string_forms, "patch_points": patch_points, "assignments": assignments, "parse_errors": parse_errors}


def main() -> None:
    repo = Path(sys.argv[1]).resolve()
    output = Path(sys.argv[2]).resolve()
    grep = subprocess.run(["git", "grep", "-n", "-E", r"routers\.agent|from routers import agent|import routers\.agent|monkeypatch\.setattr|patch\.object|\.patch\(", "--", "*.py"], cwd=repo, text=True, capture_output=True, check=False)
    result = {"git_grep_exit": grep.returncode, "git_grep": grep.stdout.splitlines(), "git_grep_stderr": grep.stderr.splitlines(), "ast": ast_scan(repo)}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
```

執行方式：

```text
python C:\Users\666\AppData\Local\Temp\report137_reference_scan_20260930_01.py . C:\Users\666\AppData\Local\Temp\report137_reference_scan_20260930_01.json
```

### 附錄 B 掃描結果交叉核對

`git grep` exit code 為 0，共 475 行；AST parse errors 為 0，結果為 39 個 import record、290 個 `agent.X` 屬性節點、0 個 runtime getattr、4 個字串形式、158 個 patch point、30 個全專案 `agent.X` assignment 節點。30 個 assignment 不在 `tests/` 的替換範圍內；測試替換仍是 158 條 monkeypatch。

兩種結果不以行數直接相等：一行可含多個 AST 節點，`git grep` 也會命中 comments/docstrings、所有 `monkeypatch` 文字與 import 文字；AST 會辨識 alias、屬性鏈、patch 呼叫與字串常數。差異中的 4 個 `routers.agent` 字串已在 Q3 明確列出，均為說明文字；`getattr` 沒有實際命中。這就是兩種方法的差異來源，並非漏掃。
