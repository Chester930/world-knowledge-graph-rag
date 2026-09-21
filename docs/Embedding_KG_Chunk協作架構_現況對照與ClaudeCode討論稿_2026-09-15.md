# Embedding × KG × Chunk 協作架構

## 現況對照與 Claude Code 討論稿

> 更新日期：2026-09-15  
> 用途：把目前討論的理論主張，對照 World Knowledge Graph RAG 現有程式，作為後續與 Claude Code 討論、拆任務與驗收的共同基準。  
> 性質：架構討論稿，不是論文正式正文，也不是已完成能力的宣稱。

## 1. 一頁結論

本專案目前已經具備「Embedding 找相關候選、KG 提供結構化拓撲、最後把證據送入 LLM」的混合檢索雛形，但還不是完整的：

```text
Embedding 定點空降
  → KG 沿邏輯邊導航
    → 每一層用問題向量剪枝
      → 依路徑提領原始 Chunk
        → LLM 生成與接地核對
```

目前更精確的描述是：

```text
問題向量
  ├─ Fact 向量檢索 ───────────────┐
  ├─ Entity 名稱語意 fallback ────┤
  └─ 句子向量檢索（獨立 RAG 路徑） ─┘

Entity seed
  → 限深、限扇出的 SVO 關係 BFS
  → 文件範圍下推／Hub seed 排除
  → 2-hop prototype 或 BFS 結果後排序

Fact + BFS 三元組
  → 事實行排列、RRF、context 組裝
  → LLM 生成 → grounding verification → 必要時限制性重生
```

因此，你提出的核心方向與現有程式是**高度相容的下一步架構**，但不能把 HippoRAG、LightRAG、SAGE 或 KAG 的完整方法寫成目前已採用。現況是「部分機制已落地、部分仍為 prototype、部分尚未建立」。

## 2. 本次討論的架構主張

### 2.1 角色分工

| 元件 | 應負責的工作 | 不應單獨承擔的工作 |
|---|---|---|
| Embedding | 模糊語句對齊 Entity／Fact／Sentence；在候選爆炸時做相關性排序與剪枝 | 單獨判定否定、但書、數字真偽或完整因果鏈 |
| KG | 保存 Entity、Fact、關係型別、來源與拓撲；沿明確邊跨越語意距離 | 解決所有口語、別名、錯字與未建圖實體 |
| Chunk／原文 | 提供 LLM 最終閱讀的可追溯證據，保留條件、數字、否定與但書 | 直接取代結構化 KG 的拓撲與去重 |
| LLM | 根據證據組織答案、處理需要語言理解的表達 | 補造 KG 沒有的事實；決定未被檢索到的邏輯鏈 |

### 2.2 目標查詢流程

```text
Q: 使用者自然語言問題
        │
        ├─ q_vec = embed(Q)
        │
        ├─ Seed resolution
        │    ├─ 字面／別名／全文索引
        │    └─ Entity embedding fallback
        │
        ├─ Graph navigation
        │    ├─ 只走允許的語意關係邊
        │    ├─ 每個 seed 限制 fan-out
        │    ├─ 每個 frontier 以 q_vec 做 beam/prize pruning
        │    └─ 記錄 path、hop、edge type、source citation
        │
        ├─ Evidence harvesting
        │    ├─ path 上的 Fact／Citation
        │    ├─ source_doc_id／article_no／chunk_index
        │    └─ 回填完整原始 Chunk
        │
        ├─ evidence ranking
        │    ├─ dense／BM25／cross-encoder（可選）
        │    └─ rank-level fusion（RRF）
        │
        └─ LLM generation + grounding verification
```

其中「KG 找路，Chunk 閱讀」是本專案最應保留的主軸；Fact／SVO 是圖上可排序與可解釋的中間證據，不應取代原文證據。

## 3. 現有程式實際做法

### 3.1 查詢入口與模式

主要入口是 `routers/agent.py::chat()`，請求模型在 `models/document.py::ChatRequest`。

目前支援：

| 模式 | 實際行為 |
|---|---|
| `both` | Fact 向量檢索 + Entity seed／BFS，兩者共同組裝 context |
| `fact_only` | 只做 Fact 語意檢索，跳過 BFS |
| `bfs_only` | 只做純圖遍歷，跳過 Fact 語意檢索與語意文件範圍下推 |
| `use_svo=False` | 不使用 SVO 檢索，直接進生成流程 |

目前要求呼叫端提供單一 `kg_id`；沒有接通 ConceptNode 的跨 KG 自動路由。`kg_id=None` 會直接回錯誤，提示「尚未實作跨 KG 自動路由」。

### 3.2 Embedding 已落地的位置

1. `routers/agent.py::_find_seed_entities()`：先做 Entity 名稱字面包含比對；無命中時呼叫 `services/svo_service.py::vector_search_entities()` 做同 KG 的 Entity embedding fallback。
2. `services/svo_service.py::vector_search_facts()`：對 per-KG Fact 向量索引做 KNN；可與 fulltext 結果以 RRF 融合，再依 `(subject, rel_type, object)` 去重。
3. `services/svo_service.py::vector_search_sentences()`：對標準化句子向量做 KNN，供獨立的標準化 RAG 路徑使用。
4. `routers/agent.py::_arrange_fact_lines()`：對沒有問題相關性排序的 BFS 事實行再做 embedding 排序，並與 Fact rank 做 RRF。
5. `services/svo_service.py::bfs_query()`：介面中已有 2-hop prototype，可對候選邊的 `natural_text`（缺席時 fallback 為 subject/verb/object）編碼後，以問題向量做 `prize_top_k` 選擇；但目前 `routers/agent.py::chat()` 沒有傳入 `question_vector`、`embedding_provider`、`prize_top_k`，所以正式 agent 查詢尚未啟用這段 traversal-time prize pruning。
6. `core/providers/embedding/`：提供 local、OpenAI、Ollama 多種 provider；實際模型與維度由設定決定，不應在文件中把 BGE-M3 寫成唯一固定實作。

### 3.3 KG／圖遍歷已落地的位置

目前 KG 主要由 SVO 抽取建立：

```text
Entity --[受控 SVO_REL_TYPES 關係]--> Entity
   ▲                                      ▲
   │                                      │
Chunk --[:HAS_ENTITY]--------------------┘

Fact --[:HAS_SUBJECT]--> Entity
Fact --[:HAS_OBJECT]----> Entity
Fact --[:SUPPORTED_BY]--> Chunk 或 LawArticle
```

`services/svo_service.py::bfs_query()` 目前具備：

- 只沿 `SVO_REL_TYPES` 的 Entity-to-Entity 關係走訪，避免穿過 `HAS_ENTITY`、`SUPPORTED_BY` 等結構邊。
- `hops` 最大深度控制；實際先跑 1-hop，結果不足 `expand_when_below` 才擴展。
- 每個 seed 的 `per_seed_limit` 扇出上限。
- 由 `scope_doc_ids` 把來源文件範圍下推到 Cypher；scoped 結果為空時，為相容舊 KG 會退回無範圍查詢。
- `prize_top_k + question_vector + embedding_provider` 三者同時存在時，對 2-hop 候選做向量 prize 剪枝。

`routers/agent.py` 另有：

- `_drop_hub_seeds()`：依 degree 排除高連結度 Hub seed；目前是 seed 層級的 hub 防護，不是完整的 traversal-time hub control。
- `_relevant_doc_ids_from_seeds()`：透過 `Chunk-[:HAS_ENTITY]->Entity` 把 seed 錨定到來源文件。
- `_resolve_doc_scope()`：seed 文件範圍優先；沒有 seed 範圍時才 fallback 到 Fact 語意結果推導的文件範圍。
- `_filter_triples_by_relation_type()`：查詢關係型別解析後做 BFS 結果後篩選；不是 traversal path 的邊型別限制器。

### 3.4 Chunk／原文回填已落地的位置

目前有兩種不同粒度的回填流程，必須分清楚：

#### A. Agent 的 Fact／BFS 路徑

`chat()` 目前把 `triples` 與 `fact_results` 轉成事實文字行，透過 `_split_fact_lines()`、`_arrange_fact_lines()`、`_merge_fact_lines()` 組成 prompt context。這條路徑目前**不是**「沿每一條 selected path 統一回填完整 Chunk」；來源欄位仍透過 citation／`source_doc_id`／`source_svo_chunk_file` 傳遞，供來源標示與部分治理使用。

#### B. 標準化 RAG 路徑

`services/retrieval_service.py::search_standardized_rag()` 明確實作：

```text
Sentence KNN
  → 依 (source, chunk_index) 去重
    → 讀取 svo_index.json 的完整 chunk text
      → 回傳 source、chunk_index、matched_sentence、chunk_text、score
```

這比較接近你描述的「最後提領 Chunk」，但它目前是獨立的 `Sentence` 路徑，沒有自動接在 `bfs_query()` 選出的圖路徑之後。

## 4. 理想架構與現況差異矩陣

| 目標能力 | 現有狀態 | 判定 | 主要缺口 |
|---|---|---|---|
| 問題向量化 | `chat()` 取得 question vector | 已實作 | provider/model 簽章與查詢快取仍需明確化 |
| 模糊問題對齊 Entity | 字面命中，失敗才 Entity embedding fallback | 部分實作 | 尚非正式 ConceptNode 路由；別名／NER 上游仍有限制 |
| Fact 語意召回 | per-KG Fact KNN，另有 fulltext + RRF | 已實作 | 不是完整 path-aware retrieval |
| Entity → Entity 拓撲導航 | bounded BFS | 部分實作 | 目前以 SVO_REL_TYPES 泛化走訪，沒有完整 `CITES/REQUIRES/EXCEPTS` 邏輯 schema |
| 1-hop／2-hop 控制 | lazy expansion、per-seed limit | 已實作 | `hops > 2` 的一般化策略尚未成熟 |
| traversal-time 向量剪枝 | `bfs_query()` 有 2-hop prototype；agent 另有 BFS 結果後 embedding 排序 | 部分實作／主流程未接線 | `chat()` 尚未啟用 `prize_top_k` 參數；尚非每層 frontier 的通用 beam search；k 值未完整校準 |
| Hub node 防爆 | seed degree 排除 | 部分實作 | 只處理 seed，不處理所有中間 frontier／edge |
| 文件範圍治理 | seed 文件優先、Fact fallback、Cypher 下推、歸零守衛 | 已實作 | 舊 KG fallback 可能放行離題結果；需評估召回與精度 trade-off |
| Path provenance | triple／Fact 帶 source/citation 欄位 | 部分實作 | 尚未形成可序列化的 path object 與 path-to-chunk 契約 |
| 完整 Chunk 提領 | `search_standardized_rag()` 有；agent KG 路徑未統一接上 | 部分實作 | 需依 source_doc_id + chunk_index + article_no 統一回填 |
| RRF | Fact fulltext/dense 與 BFS/fact 行排列均有局部實作 | 已實作但分散 | 尚未有單一 hybrid retrieval contract 與融合診斷輸出 |
| 跨 KG 路由 | ConceptRepository 向量索引骨架 | 設計預留 | `route_kgs()`／ConceptNode runtime 尚未接到 chat |
| 邏輯否定／但書保護 | prompt、受控關係、grounding guard 等局部防護 | 部分實作 | KG schema 未把 `EXCEPTS` 等邏輯關係作為專門可驗證路徑 |
| 自我精煉 | grounding verification + 一次限制性重生 | 部分實作 | 不是「低信心 → 改變檢索 → 再檢索」的閉環 |

## 5. 與推薦文獻／專案的正確對位

本節只描述「可借鏡的概念」，不宣稱本專案已完整複製這些專案。

| 參考方向 | 可借鏡的概念 | 本專案目前對位 | 不可過度宣稱 |
|---|---|---|---|
| HippoRAG | Entity／Passage 二分圖、圖擴散後回到 passage evidence | 本專案已有 Entity、Chunk、Fact、`HAS_ENTITY`、`SUPPORTED_BY` 等來源鏈 | 尚未實作 HippoRAG 的 PPR／完整二分圖檢索流程 |
| LightRAG | Entity／Relation 圖與 source id 回填、低／高層檢索思路 | 本專案已有 Entity／SVO relation／source citation，另有標準化 RAG | 尚未採用 LightRAG runtime 或 dual-level query implementation |
| KAG | 結構化邏輯與文字證據分工、嚴格 provenance | 本專案有受控關係、Fact、Chunk、grounding verification | 尚未有獨立 KG Solver／完整邏輯符號引擎 |
| SAGE | 先取候選，再用問題向量保留 Top-K' 鄰居 | `bfs_query()` 的 2-hop prize prototype 與 `_arrange_fact_lines()` 最接近 | 尚未完成每一層候選邊的通用 rerank/pruning |
| RRF | 不直接比較 cosine、BM25、hop 分數，改融合排名 | Fact dense/fulltext 與 fact/BFS 行排列各自已有 RRF | 尚未把所有路徑、Fact、Chunk 融合成單一可解釋排名 |
| PathRAG／CatRAG | 路徑可靠度、Hub node／semantic drift 控制 | Hub seed 排除、bounded BFS、prize prototype | 目前不是 PathRAG flow reliability 或 CatRAG 完整 Stage I/II |

現有本地查核表與參考資料位置：

- `docs/論文/文獻與專案查核表.md`
- `docs/論文/附錄與參考文獻.md`
- `docs/參考文獻/21_圖遍歷與向量檢索結果融合/`
- `docs/參考文獻/02_RAG與GraphRAG/`

使用者本次提到的 `SAGE arXiv:2602.16964`、`Han et al. arXiv:2501.00309`、以及 HippoRAG／LightRAG／KAG 的具體版本與方法細節，若要寫進論文正文，仍應依專案既有查核規則確認作者、出版狀態、全文與官方 repository；本文件先把它們當成討論輸入，不把未核實敘述當成實驗結論。

## 6. 建議的下一版實作邊界

### Phase 1：先建立統一 evidence contract

先不要立即重寫整個 `chat()`。新增一個內部資料契約，至少包含：

```python
Evidence = {
    "kind": "fact" | "triple" | "chunk",
    "score": float | None,
    "rank": int | None,
    "path": [
        {"entity": str, "rel_type": str, "hop": int}
    ],
    "source_doc_id": str | None,
    "source": str | None,
    "chunk_index": int | None,
    "article_no": str | None,
    "text": str,
    "provenance": {...},
}
```

目標是讓 Fact、BFS triple、Sentence 命中最後都能轉成同一種 evidence，再由一個 context assembler 決定排序、去重、截斷與 Chunk 回填。這會先解決目前「agent 路徑」和「標準化 RAG 路徑」分裂的問題。

### Phase 2：把 traversal pruning 變成明確策略

建議把目前 `bfs_query()` 裡的 prototype 拆成可測試策略，而不是繼續增加條件參數：

```text
SeedSelector
  → FrontierExpander
    → EdgeScorer(question, edge, provenance)
      → BeamSelector(top_k', diversity, hub_penalty)
        → PathRecorder
```

最低限度要記錄：候選數、保留數、每條邊的 score、被剪掉原因、實際 hop、查詢延遲。這些欄位才足以驗證「剪枝降低噪音」是否以召回率為代價。

### Phase 3：以來源定位回填完整 Chunk

建議固定來源定位優先序：

```text
source_doc_id + article_no
  → source_doc_id + source_svo_chunk_index
    → source + source_svo_chunk_file
      → legacy source/chunk fallback
```

回填結果必須保留：原文、來源文件、條號／chunk index、命中的 Fact／path，以及不能回填時的原因。不能只回傳一段沒有 provenance 的文字。

### Phase 4：再決定是否接 ConceptNode 跨 KG 路由

ConceptNode 是產品路由層，不應和單一 KG 內的 Entity seed 混為一談。建議先完成：

1. KG prototype／ConceptNode 的資料來源與更新規則。
2. query → candidate KG 的 recall／precision 測試。
3. 只有候選 KG 明確選定後，才進入本文件的 seed → graph → chunk pipeline。

## 7. 需要與 Claude Code 逐題確認的問題

### 架構問題

1. `Fact`、SVO relation 與 `Sentence` 是否都視為 evidence source，還是只把 Chunk 視為唯一最終 evidence？
2. `CITES`、`REQUIRES`、`EXCEPTS` 是否要新增為受控關係型別，或先以現有 `SVO_REL_TYPES` 加 relation metadata 表達？
3. 2-hop prize prototype 是否應升級成通用 beam search，還是目前資料規模下維持 bounded BFS 即可？
4. 路徑排序要以 edge-level score、path-level score，還是「path score + source quality + diversity」組合？
5. 完整 Chunk 回填應直接改造 `chat()`，還是先讓 `search_standardized_rag()` 成為共用 service？

### 資料與正確性問題

1. `source_svo_chunk_index`、`chunk_index`、`article_no` 的 canonical key 是什麼？哪些舊資料缺欄位？
2. 舊 KG 的 `HAS_ENTITY`／`Fact`／`natural_text` 缺失時，允許哪些 fallback，如何在 trace 中標記降級？
3. 向量模型切換時，Entity／Fact／Sentence／Chunk 的 embedding signature 如何驗證，避免不同模型向量直接比較？
4. 否定詞、數字、但書的正確性要靠抽取時結構化欄位、檢索時 relation/path constraint，還是生成前 verification？
5. 如果圖譜漏邊，是否保留純 Fact／Sentence fallback，並在答案中標記「未取得完整圖路徑」？

### 評估問題

至少要做以下消融，才能支持「協作架構」而不是只支持某次 prompt 調校：

| 組別 | Seed | Graph | Vector pruning | Chunk harvest | 用途 |
|---|---|---|---|---|---|
| V0 | 無 | 無 | 無 | dense chunk | 純向量 baseline |
| V1 | Entity lexical/vector | 無 | 無 | Fact/Chunk | Embedding 對齊效果 |
| V2 | Entity seed | bounded BFS | 無 | Chunk | KG 導航效果 |
| V3 | Entity seed | bounded BFS | 有 | Chunk | 剪枝的 precision／latency trade-off |
| V4 | Entity seed | bounded BFS | 有 | Chunk + Fact | 完整混合架構 |
| V5 | ConceptNode | per-KG pipeline | 有 | Chunk + Fact | 跨 KG 路由效果 |

每組至少記錄：seed recall、gold fact／gold chunk recall、MRR／nDCG、context token 數、BFS candidate 數、保留路徑數、p50/p95 latency、grounding／abstention 結果，以及數字／否定／但書的 atomic accuracy。

## 8. 建議的第一個工程任務

若 Claude Code 要開始實作，建議第一個 task 不是直接加入更多關係型別，而是：

> 建立 `HybridEvidence`／`PathTrace` 內部模型，讓現有 `vector_search_facts()`、`bfs_query()`、`search_standardized_rag()` 都能輸出一致的來源定位與排序資訊；保持現有 API 行為不變，先新增單元測試與 trace。

完成條件：

- 現有 `both`／`fact_only`／`bfs_only` 測試不回歸。
- 每一筆 evidence 能指出 `source_doc_id`、chunk/article 定位或明確標示缺失。
- BFS path 至少記錄 seed、hop、rel_type、edge score／pruning reason。
- Chunk 回填失敗不靜默改成無來源文字。
- 能用同一份 trace 比較 V0–V4 的召回、噪音與延遲。

## 9. 相關程式與文件索引

| 目的 | 位置 |
|---|---|
| 問答入口、檢索編排、事實清單融合 | `routers/agent.py` |
| Fact／Entity／Sentence embedding、SVO graph、BFS | `services/svo_service.py` |
| Sentence → 完整 Chunk 回填 | `services/retrieval_service.py` |
| 純向量與 dense/BM25 baseline | `services/baseline_rag_service.py`、`standardized_rag.py` |
| ConceptNode 索引骨架 | `repositories/concept_repo.py` |
| Chunk／Fact／Entity schema | `models/knowledge_graph.py` |
| KG 建立與抽取觸發 | `services/knowledge_graph_service.py` |
| RQ 與產品實作邊界 | `HANDOVER_CLAUDE_CODE.md`、`docs/論文/04_系統實作.md` |
| 已知剪枝與檢索實驗 | `docs/參考文獻/21_圖遍歷與向量檢索結果融合/`、`report39_comparison/`、`rq1_eval_results/` |

## 10. 交接時不可混淆的三件事

1. 「有 vector index」不等於「已完成 Embedding-guided graph search」；目前只有 seed fallback、Fact KNN、結果後排序與 2-hop prototype。
2. 「有 BFS」不等於「已完成邏輯拓撲導航」；現有 BFS 主要沿受控 SVO relation 走訪，專門的 `CITES/REQUIRES/EXCEPTS` 語意與驗證尚未定案。
3. 「有 source 欄位」不等於「已完成 path-to-original-chunk」；標準化 Sentence 路徑已有完整 Chunk 回填，但 agent 的 Fact/BFS 路徑仍需統一 harvest contract。
