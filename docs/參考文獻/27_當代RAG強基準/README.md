# 27_當代RAG強基準

對應 `docs/報告/35_B1當代文字RAG強基準設計.md`；支撐第五章 §5.4.1 的 **B1（當代文字 RAG 強基準）** 設計——RQ1 的非圖對照組。

查證日期 2026-09-09（session `01SHVuNWkSt2PQSEh2Snp73A`）。arXiv ID、頁數、作者經 WebSearch / WebFetch / 本地 PDF 抽取驗證；GitHub star / license 經 `gh api` 即時查證。

---

## A. B1 組態的直接先例（GraphRAG 比較論文怎麼建 plain-RAG baseline）

| 文獻 | 出處 / 狀態 | plain-RAG baseline 組態（查證來源） | 在本設計中的角色 |
|---|---|---|---|
| **Han, Shomer, Wang, Lei, Guo, Hua, Long, Liu, Tang (2025)** *RAG vs. GraphRAG: A Systematic Evaluation and Key Insights* | arXiv:[2502.11371](https://arxiv.org/abs/2502.11371)；v3；WebSearch 查得已收錄 **ACM SIGKDD 2026 (KDD'26) Proceedings**（[dl.acm.org/doi/10.1145/3770855.3817575](https://dl.acm.org/doi/10.1145/3770855.3817575)）。**PDF 已在 `02_RAG與GraphRAG/han-et-al-2025-rag-vs-graphrag.pdf`**（本資料夾不重複存） | §3.1「standard dense-retrieval RAG pipeline」；§3.4：embedding `text-embedding-ada-002`、chunk ≈ **256 tokens**、**top-k=10**、選配 cross-encoder reranker **`BAAI/bge-reranker-large`**、迭代檢索用 IRCoT、生成 Llama-3.1-8B / 70B、**明確「no query rewriting or decomposition」以隔離圖結構的影響**（WebFetch arxiv HTML v3，2026-09-09） | **B1 結構的權威操作型定義**：dense 檢索 + 選配 cross-encoder rerank、不做 query 改寫（改寫/多輪＝B2）。本專案 B1 直接對標此組態，僅換成中文 embedding／繁中法規語料／與 KG 路徑相同的 generator |
| **Zhou, Su, Sun, Wang, Wang, He, Zhang, Liang, Liu, Ma, Fang (2025)** *In-depth Analysis of Graph-based RAG in a Unified Framework* | arXiv:[2503.04338](https://arxiv.org/abs/2503.04338)；**PVLDB Vol.18**（[vldb.org/pvldb/vol18/p5623-zhou.pdf](https://www.vldb.org/pvldb/vol18/p5623-zhou.pdf)）；repo [`JayLZhou/GraphRAG`](https://github.com/JayLZhou/GraphRAG)。**PDF 已在 `02_RAG與GraphRAG/zhou-et-al-2025-graph-rag-unified-framework.pdf`** | §7.1 Setup：非圖 baseline＝**「ZeroShot」+「VanillaRAG」**；所有方法共用 **BGE-M3** embedding、chunk **1,200 tokens**（未由標註者預切時）、**top-k=4**、生成 **Llama-3-8B**、greedy decoding、max token 8,096（WebFetch arxiv HTML v2，2026-09-09） | 第二個獨立先例；佐證「VanillaRAG＋ZeroShot 是圖 RAG 論文的標準對照組配置」。本專案 B0≈ZeroShot 之上一層、B1≈VanillaRAG＋rerank |

> ⚠️ 兩篇的 chunk 單位是英文 **token**，本專案 `chunk_size` 計中文 **字元數**——不可直接套數值，只借「dense + 選配 cross-encoder rerank + 固定 top-k + 不改寫 query」這個**結構**。實際 chunk_size 由第五章 §5.3 掃描實測定案。

## B. 方法元件文獻（B1 的檢索前端）

| 文獻 | 出處 / 狀態 | 本機檔案 | 角色 |
|---|---|---|---|
| **Lewis, Perez, Piktus, Petroni, Karpukhin, Goyal, Küttler, Lewis, Yih, Rocktäschel, Riedel, Kiela (2020)** *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks* | 🟢 NeurIPS 2020，arXiv:2005.11401 | `02_RAG與GraphRAG/lewis-et-al-2020-rag.pdf`（已有） | **B0 定義**：單次 dense 檢索 + 生成，檢索發生在生成前、生成中不重評估 |
| **Karpukhin, Oğuz, Min, Lewis, Wu, Edunov, Chen, Yih (2020)** *Dense Passage Retrieval for Open-Domain Question Answering* | 🟢 **EMNLP 2020**（[aclanthology.org/2020.emnlp-main.550](https://aclanthology.org/2020.emnlp-main.550)）；官方 repo [`facebookresearch/DPR`](https://github.com/facebookresearch/DPR) | **`karpukhin-et-al-2020-dpr.pdf`（📥 已下載 2026-09-09，13 頁，本地抽取首頁標題／作者已核）** | dual-encoder（問句／段落各自編碼進共用向量空間、內積打分）＝B0/B1 dense 檢索器的原始出處；§「hybrid」用 **dense（DPR）＋sparse（BM25）分數線性組合** 對兩組聯集重排，top-20 檢索準確率比 BM25 高 9–19%——＝B1 混合檢索（dense+BM25，RRF 融合）的依據。⚠️ 尚未精讀全文，僅摘要層級＋WebSearch 查證核心主張 |
| **Gao, Xiong, Gao, Jia, Pan, Bi, Dai, Sun, Wang, Guo, Wang (2023)** *Retrieval-Augmented Generation for Large Language Models: A Survey* | 🟡 arXiv:[2312.10997](https://arxiv.org/abs/2312.10997)（尚無正式會議/期刊版；RAG 分類法的標準引用來源） | **`gao-et-al-2023-rag-survey.pdf`（📥 已下載 2026-09-09，21 頁，本地抽取首頁標題／作者已核）** | **Naive / Advanced / Modular RAG** 三範式；RAG 流程四階：pre-retrieval / retrieval / **post-retrieval（含 rerank）** / generation。用來定位：**B1 ＝ Naive RAG ＋ 檢索後重排（post-retrieval）≈ Advanced RAG 去掉 query 轉換（query transformation 屬 B2）**。⚠️ 尚未精讀全文，僅摘要層級＋WebSearch 查證分類法 |
| **Nogueira & Cho (2019)** *Passage Re-ranking with BERT* | 🟢，已收錄 `19_生成端長清單事實遺漏與位置偏誤/`（見論文 §2.4.7，列為「cross-encoder rerank 進階選項」） | 已有 | B1 二階 cross-encoder 重排的先例；MS MARCO passage ranking 榜首 |
| **Cormack, Clarke & Büttcher (2009)** *Reciprocal Rank Fusion* | 🟢 SIGIR 2009，已收錄 `21_圖遍歷與向量檢索結果融合/`（論文 §2.4.7／§3.6 已用，`_RRF_K=60`） | 已有 | B1 混合檢索（dense rank + BM25 rank）免尺度融合 |
| **Bhat et al. (2025)** *Rethinking Chunk Size* / **Chen et al. (2023)** *Dense X Retrieval* | 🟡/🟢，已收錄 `08_向量化與語意表示/`（論文 §2.6.2、第五章 §5.3） | 已有 | B0/B1 共用的 chunk 粒度校準依據（§5.3） |

## C. 具體 reranker / embedding 模型（若 B1 採 cross-encoder 版）

| 專案 / 模型 | 事實（gh api 2026-09-09） | 角色 |
|---|---|---|
| **`FlagOpen/FlagEmbedding`**（BGE 家族：`bge-m3` embedding、`bge-reranker-v2-m3` cross-encoder reranker） | ⭐12,148，**MIT**，pushed 2026-08-24 | B1 若採具體多語 cross-encoder reranker，`bge-reranker-v2-m3`（繁中法規可用）是預設選擇；`bge-m3` 為多語 embedding 選項。Han (2025) 用同家族的 `bge-reranker-large`、Zhou (2025) 用 `BGE-M3`——**同家族有兩篇圖 RAG 論文的使用先例**。⚠️ 引入新模型依賴（`FlagEmbedding` 或 `sentence-transformers` CrossEncoder）；若 §5.3 校準顯示 rerank 邊際效益低，B1 退回「dense+BM25 RRF」無新模型版 |
| **`bge-m3` / `bge-reranker-v2-m3` 模型論文**（Chen et al. 2024, *BGE M3-Embedding*；Xiao et al. *C-Pack*） | 待查證後決定是否正式收錄（目前僅需引 repo 作參考專案存在性） | 若第五章正式採用具體模型，補下載模型論文並升級查核層級 |

## D. 專案內既有資產（B1 不是全新）

| 檔案 / 文件 | 內容 | 對 B1 的關係 |
|---|---|---|
| `standardized_rag.py`／`build_standardized_rag_index.py`／`run_rag_comparison.py`（主 checkout ＋ `kg-reextract` worktree） | 單句 brute-force cosine → chunk 上下文擴展（依 chunk 去重）→ top_k=5 → `build_prompt`（已比照 `_build_prompt` 的 taiwan_context ＋ 誠實侷限風格）→ LLM stream；**與 `chat()` 完全獨立** | B1 harness 的骨架；但 B1 要改：檢索走 **`Chunk` 級 Neo4j 原生索引**（非 `.npy` brute-force、非句子級、**無 coref**）、加 BM25+RRF、選配 rerank、生成端改共用 `chat()` 的 post-retrieval pipeline |
| `services/retrieval_service.py::search_standardized_rag()` | Neo4j 原生句子索引版，**含指代消解** | ⚠️ 屬報告 08「軌道 2」＝**專案自己的貢獻**（coref 屬 RQ4b），**不是 B1**；B1 需明確排除 coref 以維持中性 |
| `docs/報告/08` §2/§4 | 三軌檢索消融規劃；§2 表把「軌道 1（粗 chunk、無 coref、dense）」叫 Baseline、「軌道 2」叫「前處理增強」 | 對映論文：**B0＝軌道 1**、**B1＝軌道 1 ＋ rerank ＋ 校準 top-k/chunk**；報告 35 訂正此命名 |
| `docs/報告/18` | 真實測試：條件 C（RAG-MVP）在 5 題單文件事實題 **8/10、贏過 KG-Agent（4–5/10）** | RQ1 需要 B1 的實證動機；報告 13/14 的 30 題可作題庫種子 |
| `Chunk` 節點的 `chunk_embedding_vector` Neo4j 原生向量索引（報告 08 Phase 1） | 已存在 | B1 dense 檢索直接重用，不建新索引、不跑 coref |

---

## E. 尚未取得 / 待深讀

- [ ] DPR（Karpukhin 2020）、RAG Survey（Gao 2023）僅 📥 已下載，尚未 📖 全文精讀——第五章 B1 定版前需精讀 DPR §hybrid 與 Gao §post-retrieval，確認引用的具體機制與數字。
- [ ] Han (2025) §3.4 / Zhou (2025) §7.1 的 baseline 細節目前經 WebFetch arxiv HTML 取得，寫作定稿前需對 PDF 逐字複核。
- [ ] `bge-reranker-v2-m3` 模型論文（若正式採用具體 reranker）。
- [ ] BM25 實作選型：`rank_bm25`（純 Python）vs Neo4j full-text index——實作時定案。
