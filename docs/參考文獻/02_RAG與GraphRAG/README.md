# 02_RAG與GraphRAG

對應 `../../論文/02_文獻探討.md`（2026-07-23 第二章重組後）§ 2.4.7（RAG 演進與自我精煉，原 § 2.1.1）、§ 2.4.2／§ 2.4.3（知識圖譜與 GraphRAG，RQ2 路由／RQ1 BFS，原 § 2.1.2）、§ 2.4.6（T-GRAG，RQ5 事實時序保留策略，新增）。

## 內容清單
| 檔案 | 文獻 | 來源 |
|---|---|---|
| `lewis-et-al-2020-rag.pdf` | Lewis et al. (2020), Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks | arXiv:2005.11401 |
| `edge-et-al-2024-graphrag.pdf` | Edge et al. (2024), From Local to Global: A Graph RAG Approach to Query-Focused Summarization | arXiv:2404.16130 |
| `zhang-et-al-2025-graphrag-survey.pdf` | Zhang et al. (2025), A Survey of Graph Retrieval-Augmented Generation for Customized LLMs | arXiv:2501.13958 |
| `singh-et-al-2025-agentic-rag-survey.pdf` | Singh et al. (2025), Agentic Retrieval-Augmented Generation: A Survey on Agentic RAG | arXiv:2501.09136 |
| `rashkin-et-al-2021-measuring-attribution-ais.pdf` | Rashkin et al. (2021/2023), Measuring Attribution in Natural Language Generation Models（AIS 框架，供 01_緒論.md § 1.1.4 使用） | arXiv:2112.12870 |
| `shuster-et-al-2021-retrieval-reduces-hallucination.pdf` | Shuster et al. (2021), Retrieval Augmentation Reduces Hallucination in Conversation（供 01_緒論.md § 1.1.4 使用） | arXiv:2104.07567 |
| `ma-et-al-2026-retrieval-drift-graphrag.pdf` | Ma et al. (2026), Toward Robust GraphRAG: Mitigating Retrieval Drift and Hallucination from Imperfect Knowledge Graphs（供 01_緒論.md § 1.1.1 使用） | arXiv:2603.14828 |
| `zhu-et-al-2025-lost-in-retrieval.pdf` | Zhu et al. (2025), Mitigating Lost-in-Retrieval Problems in Retrieval Augmented Multi-Hop Question Answering，ACL 2025（供 01_緒論.md § 1.1.1 使用） | arXiv:2502.14245 |

### GraphRAG 深度文獻回顧補充（2026-07-13，供 `docs/報告/04_GraphRAG深度文獻回顧.md` 使用）

| 檔案 | 文獻 | 來源 |
|---|---|---|
| `guo-et-al-2024-lightrag.pdf` | Guo et al. (2024), LightRAG: Simple and Fast Retrieval-Augmented Generation，EMNLP 2025 | arXiv:2410.05779 |
| `han-et-al-2025-rag-vs-graphrag.pdf` | Han et al. (2025), RAG vs. GraphRAG: A Systematic Evaluation and Key Insights | arXiv:2502.11371 |
| `chen-et-al-2025-pathrag.pdf` | Chen et al. (2025), PathRAG: Pruning Graph-based RAG with Relational Paths | arXiv:2502.14902 |
| `fan-et-al-2026-do-we-still-need-graphrag.pdf` | Fan et al. (2026), Do We Still Need GraphRAG? | arXiv:2604.09666 |
| `hong-et-al-2025-fg-rag.pdf` | Hong et al. (2025), FG-RAG，CIKM 2025 | arXiv:2504.07103 |
| `xu-et-al-2025-noderag.pdf` | Xu et al. (2025), NodeRAG | arXiv:2504.11544 |
| `xiang-et-al-2025-when-to-use-graphs-in-rag.pdf` | Xiang et al. (2025), When to use Graphs in RAG，ICLR 2026 | arXiv:2506.05690 |
| `lau-et-al-2026-catrag-static-graph-fallacy.pdf` | Lau et al. (2026), Breaking the Static Graph（CatRAG） | arXiv:2602.01965 |
| `zhang-et-al-2025-erarag.pdf` | Zhang et al. (2025), EraRAG | arXiv:2506.20963 |
| `xiao-et-al-2025-graphrag-bench.pdf` | Xiao et al. (2025), GraphRAG-Bench | arXiv:2506.02404 |
| `li-et-al-2025-t-grag.pdf` | Li et al. (2025), T-GRAG，ACM Multimedia 2025 | arXiv:2508.01680 |
| `zhou-et-al-2025-graph-rag-unified-framework.pdf` | Zhou et al. (2025), In-depth Analysis of Graph-based RAG in a Unified Framework | arXiv:2503.04338 |
| `dong-et-al-2025-kg-rag-evaluation-framework.pdf` | Dong et al. (2025), Knowledge-Graph Based RAG System Evaluation Framework | arXiv:2510.02549 |
| `guo-et-al-2026-why-rag-fails-graph-perspective.pdf` | Guo et al. (2026), Why RAG Fails: A Graph Perspective | arXiv:2605.14192 |

### RQ3 支撐文獻（2026-07-13，自我精煉迴圈）

| 檔案 | 文獻 | 來源 |
|---|---|---|
| `asai-et-al-2023-self-rag.pdf` | Asai et al. (2023), *Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection*, ICLR 2024 | arXiv:2310.11511 |
| `jiang-et-al-2023-flare.pdf` | Jiang et al. (2023), *Active Retrieval Augmented Generation (FLARE)*, EMNLP 2023 | arXiv:2305.06983 |
| `trivedi-et-al-2022-ircot.pdf` | Trivedi et al. (2022), *Interleaving Retrieval with Chain-of-Thought Reasoning (IRCoT)*, ACL 2023 | arXiv:2212.10509 |

*待二次核實、未下載*：Right Answer at the Right Time（arXiv:2510.16715）、VersionRAG（arXiv:2510.08109）、RAG Meets Temporal Graphs（arXiv:2510.13590）——僅確認標題/arXiv ID 存在，作者未獨立核實。

*查證未通過、未下載*：一篇 MDPI 企業 RAG／多知識庫系統性文獻回顧，因作者名稱查證出現矛盾結果、無法確認真實作者，未下載也未引用。
