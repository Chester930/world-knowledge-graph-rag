# 35．B1 當代文字 RAG 強基準設計報告

**日期**：2026-09-09（設計）
**狀態**：**設計定案，未實作**（使用者本輪指示「僅設計、找文獻與專案參考」）。本報告只定義 B1 的定位、元件、單一變因控制、校準計畫與明確排除；管線程式碼、harness、依賴引入皆未動手。落地待第五章排期（且 §5.3 chunk-size 校準為前置）。
**關聯**：論文 05 §5.2／§5.4.1（B1／B0 對照組）、§5.3（chunk-size 前置校準）、§3.8（單一變因控制、可追溯性）；文獻 `docs/參考文獻/27_當代RAG強基準/`（含 📥 已下載的 Karpukhin 2020 DPR、Gao 2023 RAG Survey）；報告 08（三軌檢索消融規劃，本報告訂正其 baseline 命名）、報告 18（RAG-MVP 真實先例）。
與 DRAIN-DONE 的關係：**設計不卡 drain**；B1 **實作碼**不卡 drain（純查詢/評估端）；B1 **跑 RQ1 對照** 卡 DRAIN-DONE（要完整 KG#4）＋卡 §5.3。

---

## 1. 定位：B1 是什麼、為什麼非做不可

RQ1 的承諾是「界定 KG-BFS 相較**當代 RAG 強基準**仍有優勢的查詢任務類型」。但截至目前：

- 所有真實測試（報告 13／14／18／25／26／32 T1）的非圖對照組是 **pure-LLM（完全不檢索）**。
- **報告 18 條件 C（標準化 RAG MVP）在 5 題單文件事實題上 8/10 分，直接贏過 KG-Agent（A 4/10、B 5/10）、pure-LLM（D 2/10）。**
- 文獻共識（Han et al. 2025《RAG vs. GraphRAG》、Xiang et al. 2025《When to use Graphs in RAG》、Fan et al. 2026《Do We Still Need GraphRAG?》，皆已在論文 §2.3／§2.4.3）：**GraphRAG 的優勢具任務依賴性，在許多真實任務上不如、甚至輸給調校過的一般 RAG。**

**結論**：目前所有「KG 系統有價值」的證據都只支撐「勝過不檢索的 LLM」，**不支撐「勝過當代 RAG」**。沒有一個調校過的向量 RAG 對照組，第六、七章對 RQ1 的任何「優勢」宣稱都不成立。**B1 就是補這個對照組。**（此段對應論文 §5.4.1 已寫入的「勝過 pure-LLM ≠ RQ1 成立」界線。）

## 2. 文獻與專案參考（2026-09-09 live 查證，細節見 `docs/參考文獻/27_當代RAG強基準/README.md`）

### 2.1 直接先例——GraphRAG 比較論文的 plain-RAG baseline 怎麼配

| 論文 | plain-RAG baseline 組態 | 對 B1 |
|---|---|---|
| **Han et al. (2025)**《RAG vs. GraphRAG》(§3.1／§3.4，arXiv:2502.11371 v3，現 KDD'26) | dense retrieval、`text-embedding-ada-002`、chunk ≈ **256 tokens**、**top-k=10**、**選配** cross-encoder reranker `BAAI/bge-reranker-large`、生成 Llama-3.1-8B/70B、**明確「no query rewriting or decomposition」以隔離圖結構影響** | **B1 結構直接對標**：dense（可加混合）＋選配 cross-encoder rerank、**不改寫 query**（改寫／多輪＝B2） |
| **Zhou et al. (2025)**《Unified Framework》(§7.1，PVLDB Vol.18，repo `JayLZhou/GraphRAG`) | 非圖 baseline＝「ZeroShot」＋「VanillaRAG」；共用 **BGE-M3** embedding、chunk **1,200 tokens**、**top-k=4**、生成 Llama-3-8B、greedy | 第二個獨立先例；B0≈ZeroShot 之上、B1≈VanillaRAG＋rerank |

> ⚠️ 兩篇 chunk 單位是英文 token，本專案 `chunk_size` 計中文字元——**只借結構，不借數值**；chunk_size 由 §5.3 掃描定案。

### 2.2 元件文獻（B1 檢索前端）

- **Lewis et al. (2020)** RAG（🟢 NeurIPS 2020，已收錄）——**B0 定義**（單次 dense 檢索＋生成）。
- **Karpukhin et al. (2020)** DPR（🟢 EMNLP 2020，📥 已下載 `27_.../karpukhin-et-al-2020-dpr.pdf`，13 頁；官方 repo `facebookresearch/DPR`）——dual-encoder dense 檢索的原始出處；**dense（DPR）＋sparse（BM25）分數線性組合**對聯集重排，top-20 準確率比 BM25 高 9–19%＝**B1 混合檢索的依據**。
- **Gao et al. (2023)** RAG Survey（🟡 arXiv:2312.10997，📥 已下載，21 頁）——Naive／Advanced／Modular RAG 三範式；四階 pre-/retrieval/**post-retrieval(rerank)**/generation。定位：**B1 ＝ Naive RAG ＋ 檢索後重排 ≈ Advanced RAG 去掉 query 轉換**。
- **Nogueira & Cho (2019)** Passage Re-ranking with BERT（🟢，已在 §2.4.7）——cross-encoder 重排先例。
- **Cormack et al. (2009)** RRF（🟢 SIGIR，已在 §2.4.7／§3.6，`_RRF_K=60`）——dense rank＋BM25 rank 免尺度融合。
- **Bhat et al. (2025)** / **Chen et al. (2023)** Dense X（已在 §2.6.2、§5.3）——chunk 粒度校準。

### 2.3 具體模型（若採 cross-encoder 版）

- **`FlagOpen/FlagEmbedding`**（BGE 家族，⭐12,148、MIT、活躍，gh api 2026-09-09）——`bge-reranker-v2-m3`（繁中可用 cross-encoder）／`bge-m3`（多語 embedding）。Han (2025) 用同家族 `bge-reranker-large`、Zhou (2025) 用 `BGE-M3`——**同家族有兩篇圖 RAG 論文使用先例**。引入新模型依賴；若校準顯示 rerank 邊際效益低，退回無新模型版。

### 2.4 專案內既有資產（B1 不是全新）

- `standardized_rag.py`／`build_standardized_rag_index.py`／`run_rag_comparison.py`——MVP 骨架（單句 brute-force cosine → chunk 擴展 → top_k=5 → `build_prompt` 已比照 `_build_prompt` 風格 → LLM stream；與 `chat()` 完全獨立）。**但其索引來自 `sentence_embeddings.json`＝指代消解前的句子向量、且是句子級**——折衷版，非本報告要的乾淨 chunk 級 baseline。
- `services/retrieval_service.py::search_standardized_rag()`——Neo4j 原生句子索引版，**含指代消解 → 屬報告 08「軌道 2」＝專案貢獻，不是 B1**。
- ~~`Chunk` 節點的 `chunk_embedding_vector` Neo4j 原生向量索引——B1 dense 檢索直接重用。~~ **✗ 訂正（見 §8）：該索引 embed 的是標準化 SVO chunk（軌道 2），不能當中性 baseline。B0/B1 改用 `build_baseline_chunk_index.py` 對原文自建 `.npy` 索引。**
- 報告 08 §2/§4 三軌消融規劃；報告 18 真實先例＋報告 13/14 的 30 題題庫種子。

## 3. 報告 08 baseline 命名訂正

報告 08 §2 表把「軌道 1（原始文件／500 字粗 chunk／dense 向量檢索）」標為「系統基準 (Baseline)」、「軌道 2（句子級＋指代消解）」標為「前處理增強」。對映到論文第五章：

| 報告 08 | 論文第五章 | 說明 |
|---|---|---|
| 軌道 1 | **B0（floor）** | raw doc → 500-char chunk → chunk 級 dense KNN → top-k → 同一份生成 stack |
| 軌道 1 ＋ reranker ＋ 校準 top-k/chunk_size | **B1（strong baseline）** | 本報告定義；§5.2 表的「B1 當代文字 RAG 強基準」列 |
| 軌道 2（句子級＋coref） | 專案自身貢獻，≈「−前處理」消融（RQ4b 相關） | **不是中性 baseline**，B1 明確排除 coref |
| 軌道 2 ＋ 軌道 3（KG） | **Full System** | RQ1 的目標配置 |

報告 08 §4「實驗組 A (Baseline)＝僅軌道 1」＝ B0；「實驗組 B (前處理增強)」＝軌道 2 消融，非 B1。

## 4. B0 / B1 定義與元件

```
B0：raw doc → 500-char chunk (sentence_aware_chunking) → chunk 級 dense KNN (chunk_embedding_vector)
     → top-k → 【與 KG 路徑完全相同的生成+grounding stack】
B1：B0 + ① 混合檢索 (dense + BM25，RRF 融合)
        + ② 選配 cross-encoder rerank (bge-reranker-v2-m3；預設關，校準決定)
        + ③ chunk_size 取 §5.3 勝出值
        + ④ top-k 校準
```

| 元件 | B0 | B1 | 依據 |
|---|---|---|---|
| 索引單位 | `Chunk`（現行 500 字元） | 同，chunk_size 取 §5.3 勝出值 | Bhat 2025／Han(256tok)／Zhou(1200tok) |
| 一階檢索 | dense KNN（`chunk_embedding_vector`，與 KG 路徑同一 embedding model） | **dense + BM25 混合，RRF 融合** | Karpukhin 2020（hybrid）、Cormack 2009（RRF） |
| 二階重排 | 無 | **選配** `bge-reranker-v2-m3` cross-encoder（(query,passage)→score，對一階候選重排）；預設關 | Nogueira & Cho 2019、Han 2025 |
| top-k | 固定（暫 5） | 校準 ∈ {3, 5, 10} | Han(10)／Zhou(4) |
| query 處理 | 原樣 | **原樣**（不改寫、不分解＝B2） | Han 2025「no query rewriting or decomposition」 |
| 生成端 | **與 KG 路徑逐位元相同**：同 `llm_provider`(qwen2.5:7b)、同 `cfg.domain.system_context`、`_arrange_fact_lines` 的 retrieval-agnostic 部分（截斷／RRF／zigzag）、grounding 核對＋方案 B/2b 重生 | 同 B0 | §3.8 單一變因控制；Han 2025 同 generator |

**核心原則**：B0／B1／Full System **只差檢索前端**。生成端（prompt 組裝、`cfg.domain`、grounding、限制性重生）完全相同——否則 RQ1 分不清「贏在圖檢索」還是「贏在生成端機制」。B1 的「retrieved context lines」餵進同一條 post-retrieval pipeline。

## 5. 單一變因控制（§3.8）

| 對照 | 唯一變因 | 固定 |
|---|---|---|
| B0 vs B1 | 有無 hybrid + rerank + 校準 | chunk 語料、embedding model、generator、生成 stack、題組 |
| **B1 vs Full System (KG-BFS)** | 檢索前端＝chunk 向量 vs entity-BFS + Fact | generator、`cfg.domain`、`_arrange_fact_lines` 下游、grounding、方案 B/2b、題組、每題 ×3、§5.5 評分 rubric |

## 6. 校準計畫（依附 §5.3，非平行消融）

1. **前置**：§5.3 chunk-size 掃描（{150,300,500,800,1200} 字元，附實測 token 數）先定案——B0／B1 共用勝出值。
2. **B1 內部校準**（鎖定 chunk_size 後，OFAT，§3.8「門檻常數敏感度」方法）：`top_k ∈ {3,5,10}` × `reranker ∈ {off, bge-reranker-v2-m3}` × `hybrid ∈ {dense-only, dense+BM25 RRF}`，對 §5.4 題組量 Precision@k／Recall@k（§5.5）＋答案 F1，挑一組進 RQ1 正式對照。
3. **B1 定版組態鎖進 manifest**（§3.8 可追溯性：commit hash、參數快照、題組版本、輸出路徑）。

## 7. 明確排除（誠實聲明，寫進 §5.4.1）

- **B1 ≠ B2**：B2（多輪／agentic／critic／query 分解）另計。時間不足時 RQ1 至少對照到 B1，並在第六、七章聲明「未對照完整 Agentic RAG」。
- **B1 不做 coref／標準化句子**：那是軌道 2＝專案貢獻，非中性 baseline，納入會混淆 RQ4b。
- **B1 不做受控關係詞彙、不做 query 改寫**：分屬 RQ4a／B2。
- **reranker 引入新模型依賴**：若校準顯示邊際效益低，B1 退回「dense+BM25 RRF」無新模型版，並在論文說明。

## 8. 實作考量

> **⚠️ 訂正（2026-09-10）：不能重用 `chunk_embedding_vector`**。§2.4／原 §8 假設 Neo4j 的
> `chunk_embedding_vector` 索引是乾淨的 chunk 級 dense 索引、可直接重用。查證 `embed_svo_chunks()`
> 後排除：它 embed 的是 `SVOChunk.text` ＝ `"\n".join(normalized_slice)`（**標準化句子**，
> `services/svo_chunking.py` 第 105 行）——即報告 08「軌道 2＝專案貢獻」，§5／§7 明確要 B1 排除。
> 因此 B0／B1 dense 檢索改為對 `workspace/<kg>/<doc>/original.md` 的**原文**重新
> `sentence_aware_chunking()`（無標準化、無 coref、無型別標籤）建一份自有 `.npy` 索引；demo
> 規模下 brute-force cosine 足夠，Neo4j 原生索引不是必要。

**檢索側（P0b 第 1 項，✅ 2026-09-10 落地）**：

- `build_baseline_chunk_index.py`：讀原文 → `sentence_aware_chunking(chunk_size, chunk_overlap)` →
  embedding provider → `baseline_rag_index_<kg>_cs<size>.npy` ＋ meta。`chunk_size` 帶進檔名，
  供 §5.3（P1a）掃 {150,300,500,800,1200}。
- `services/baseline_rag_service.py`：`search_baseline(question, question_vector, vectors, meta, *,
  top_k, hybrid, reranker)`——① dense brute-force cosine；② `hybrid=True` 加 BM25（`rank_bm25`，
  字元 bigram 斷詞）＋ 本地 `rrf_fuse()`（Cormack 2009，與 `routers/agent.py::_rrf_order()` 同演算法，
  避免 services 反向 import router）；③ `reranker` 選配（`CrossEncoder` 相容介面，預設 None、不加依賴）。
  `B0 = hybrid=False, reranker=None`；`B1 = hybrid=True, reranker=<選配>`。`build_context_lines()`
  轉 context 行。依賴：`rank-bm25~=0.2`（進 `requirements-dev.txt`）。12 項單元測試、全套 775 passed。

**生成側（P0b 第 2 項，未做）**：把 `chat()` 內「retrieval 之後」抽成可吃任意 `context_lines`
的共用函式（中等重構，須不動既有 KG 路徑行為、golden 對照）。**建議等 DRAIN-DONE／T2 之後再做**
——T2（報告 27 §6.2）要在 `chat()` 上跑，其 baseline 是特定 commit，現在插重構 commit 會讓
T2 跑在改過的版本上（即使 golden test 保證行為零變化）。

**harness（P0d，未做）**：`run_rq1_comparison.py`——同題組跑 B0／B1／Full-System ×3，輸出對齊
§5.5 rubric ＋ §3.8 manifest。**不碰抽取端、不碰 drain。**

## 9. 落地待辦（本報告產出後）

- [x] 下載 DPR（Karpukhin 2020）、RAG Survey（Gao 2023）進 `docs/參考文獻/27_當代RAG強基準/`（📥，未精讀）。
- [x] `docs/參考文獻/27_當代RAG強基準/README.md`。
- [x] 論文 §5.4.1 擴寫（B0/B1 定義表 ＋ 校準計畫 ＋ 排除聲明）；§5.2 表「B1」列補元件細節（commit `ee24b49`）；§5.7 時程把「§5.3 → B0/B1 建置 → RQ1 對照」序列釘死（2026-09-09，§5.7.1/§5.7.2 分階段 DAG）。
- [ ] 論文 §2.3 比較表或 §2.6 新增小節，收 DPR／RAG Survey 兩篇（B1 的方法定位）。
- [ ] `文獻與專案查核表.md` 補 DPR／Gao 兩列（標 📥 已下載、未精讀）。
- [ ] （實作階段）DPR §hybrid、Gao §post-retrieval 全文精讀；Han §3.4／Zhou §7.1 對 PDF 逐字複核。
