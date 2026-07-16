# 參考文獻資料夾

存放論文引用文獻的原始文檔（PDF），依論文章節主題分類到子資料夾。命名規則：`第一作者-年份-關鍵詞.pdf`（小寫、連字號分隔）。

## 分類與章節對應

| 資料夾 | 對應論文章節 | 狀態 |
|---|---|---|
| `01_AGI與智慧定義/` | 01_緒論.md § 1.1.1-1.1.4 | 🟢 已下載 13 篇 |
| `02_RAG與GraphRAG/` | 02_文獻探討.md § 2.1.1-2.1.2，01_緒論.md § 1.1.1、1.1.4；`docs/報告/04_GraphRAG深度文獻回顧.md` | 🟢 已下載 25 篇 |
| `03_資訊抽取與本體設計/` | 02_文獻探討.md § 2.1.3；01_緒論.md § 1.2 RQ4（預留） | 🟡 已下載 2 篇，1 篇付費未下載 |
| `04_圖遍歷與大節點問題/` | 02_文獻探討.md § 2.1.4 | ⚪ 待下載 |
| `05_評估方法論/` | 02_文獻探討.md § 2.1.5 | ⚪ 待下載 |
| `06_多模態輸入與網頁擷取/` | `parser/README.md`（Ingestion Parser 模組工程實作支撐文獻） | 🟢 已下載 2 篇 |
| `07_文件分群與知識庫自動建立/` | 03_系統設計與方法論.md § 3.1.1（暫存區 AI 自動分群建立 KG） | 🟡 已下載 2 篇，皆僅 arXiv 預印本 |

## 01_AGI與智慧定義 內容清單

| 檔案 | 文獻 | 來源 |
|---|---|---|
| `legg-hutter-2007-universal-intelligence.pdf` | Legg & Hutter (2007), *Minds and Machines* 17(4) | arXiv:0712.3329 |
| `chollet-2019-measure-of-intelligence.pdf` | Chollet (2019) | arXiv:1911.01547 |
| `marcus-2020-next-decade-in-ai.pdf` | Marcus (2020) | arXiv:2002.06177 |
| `garcez-lamb-2020-neurosymbolic-ai-3rd-wave.pdf` | Garcez & Lamb (2020/2023), *Artificial Intelligence Review* | arXiv:2012.05876 |
| `morris-et-al-2023-levels-of-agi.pdf` | Morris et al. (2023/2024, Google DeepMind), ICML 2024 | arXiv:2311.02462 |
| `morris-et-al-2023-levels-of-agi-v5.pdf` | Morris et al. (2023/2025, v5 最新修訂版) | arXiv:2311.02462v5 |
| `ha-schmidhuber-2018-world-models.pdf` | Ha & Schmidhuber (2018) | arXiv:1803.10122 |
| `hu-shu-2023-law-language-agent-world-models.pdf` | Hu & Shu (2023)，LAW 框架 | arXiv:2312.05230 |
| `lecun-2022-path-towards-autonomous-machine-intelligence.pdf` | LeCun (2022), *A Path Towards Autonomous Machine Intelligence* | OpenReview |
| `legg-et-al-2026-from-agi-to-asi.pdf` | Legg et al. (2026, Google DeepMind), *From AGI to ASI* | arXiv:2606.12683 |
| `huang-et-al-2023-hallucination-survey.pdf` | Huang et al. (2023), *A Survey on Hallucination in LLMs* | arXiv:2311.05232 |
| `dziri-et-al-2023-faith-and-fate.pdf` | Dziri et al. (2023), *Faith and Fate: Limits of Transformers on Compositionality*, NeurIPS 2024 | arXiv:2305.18654 |
| `liu-et-al-2023-lost-in-the-middle.pdf` | Liu et al. (2023), *Lost in the Middle: How Language Models Use Long Contexts*（原誤標為 Huang et al. 2023，已查證更正） | arXiv:2307.03172 |

**未下載（版權，不下載全文）**：Goertzel & Pennachin (Eds.) (2007), *Artificial General Intelligence*（Springer 專書）——無公開免費 PDF。引用時僅使用書目資訊（見 `../論文/附錄與參考文獻.md`）。

## 02_RAG與GraphRAG 內容清單

| 檔案 | 文獻 | 來源 |
|---|---|---|
| `lewis-et-al-2020-rag.pdf` | Lewis et al. (2020), *Retrieval-Augmented Generation* | arXiv:2005.11401 |
| `edge-et-al-2024-graphrag.pdf` | Edge et al. (2024), *From Local to Global: A Graph RAG* | arXiv:2404.16130 |
| `zhang-et-al-2025-graphrag-survey.pdf` | Zhang et al. (2025), *A Survey of Graph Retrieval-Augmented Generation for Customized LLMs*（原誤標為機構名「PolyU et al.」，已查證更正） | arXiv:2501.13958 |
| `singh-et-al-2025-agentic-rag-survey.pdf` | Singh et al. (2025), *Agentic Retrieval-Augmented Generation: A Survey on Agentic RAG* | arXiv:2501.09136 |
| `rashkin-et-al-2021-measuring-attribution-ais.pdf` | Rashkin et al. (2021/2023), *Measuring Attribution in Natural Language Generation Models*，AIS 框架 | arXiv:2112.12870 |
| `shuster-et-al-2021-retrieval-reduces-hallucination.pdf` | Shuster et al. (2021), *Retrieval Augmentation Reduces Hallucination in Conversation*，EMNLP 2021 Findings | arXiv:2104.07567 |
| `ma-et-al-2026-retrieval-drift-graphrag.pdf` | Ma et al. (2026), *Toward Robust GraphRAG*，提出「Retrieval Drift」 | arXiv:2603.14828 |
| `zhu-et-al-2025-lost-in-retrieval.pdf` | Zhu et al. (2025), ACL 2025，提出「Lost-in-Retrieval」 | arXiv:2502.14245 |
| `guo-et-al-2024-lightrag.pdf` | Guo et al. (2024), *LightRAG*，EMNLP 2025（供 `04_GraphRAG深度文獻回顧.md` 使用，下同） | arXiv:2410.05779 |
| `han-et-al-2025-rag-vs-graphrag.pdf` | Han et al. (2025), *RAG vs. GraphRAG: A Systematic Evaluation* | arXiv:2502.11371 |
| `chen-et-al-2025-pathrag.pdf` | Chen et al. (2025), *PathRAG* | arXiv:2502.14902 |
| `fan-et-al-2026-do-we-still-need-graphrag.pdf` | Fan et al. (2026), *Do We Still Need GraphRAG?* | arXiv:2604.09666 |
| `hong-et-al-2025-fg-rag.pdf` | Hong et al. (2025), *FG-RAG*，CIKM 2025 | arXiv:2504.07103 |
| `xu-et-al-2025-noderag.pdf` | Xu et al. (2025), *NodeRAG* | arXiv:2504.11544 |
| `xiang-et-al-2025-when-to-use-graphs-in-rag.pdf` | Xiang et al. (2025), *When to use Graphs in RAG*，ICLR 2026 | arXiv:2506.05690 |
| `lau-et-al-2026-catrag-static-graph-fallacy.pdf` | Lau et al. (2026), *Breaking the Static Graph*（CatRAG），命名「Static Graph Fallacy」 | arXiv:2602.01965 |
| `zhang-et-al-2025-erarag.pdf` | Zhang et al. (2025), *EraRAG* | arXiv:2506.20963 |
| `xiao-et-al-2025-graphrag-bench.pdf` | Xiao et al. (2025), *GraphRAG-Bench* | arXiv:2506.02404 |
| `li-et-al-2025-t-grag.pdf` | Li et al. (2025), *T-GRAG*，ACM Multimedia 2025 | arXiv:2508.01680 |
| `zhou-et-al-2025-graph-rag-unified-framework.pdf` | Zhou et al. (2025), *In-depth Analysis of Graph-based RAG in a Unified Framework* | arXiv:2503.04338 |
| `dong-et-al-2025-kg-rag-evaluation-framework.pdf` | Dong et al. (2025), *Knowledge-Graph Based RAG System Evaluation Framework* | arXiv:2510.02549 |
| `guo-et-al-2026-why-rag-fails-graph-perspective.pdf` | Guo et al. (2026), *Why Retrieval-Augmented Generation Fails: A Graph Perspective* | arXiv:2605.14192 |
| `asai-et-al-2023-self-rag.pdf` | Asai et al. (2023), *Self-RAG*，ICLR 2024（供 1.2 節 RQ3 使用） | arXiv:2310.11511 |
| `jiang-et-al-2023-flare.pdf` | Jiang et al. (2023), *FLARE*，EMNLP 2023（供 1.2 節 RQ3 使用） | arXiv:2305.06983 |
| `trivedi-et-al-2022-ircot.pdf` | Trivedi et al. (2022), *IRCoT*，ACL 2023（供 1.2 節 RQ3 使用） | arXiv:2212.10509 |

## 03_資訊抽取與本體設計 內容清單

| 檔案 | 文獻 | 來源 |
|---|---|---|
| `vashishth-et-al-2018-cesi-canonicalize-open-kb.pdf` | Vashishth et al. (2018), *CESI*，WWW 2018（供 1.2 節 RQ4 使用） | arXiv:1902.00172 |
| `angeli-et-al-2015-stanford-openie.pdf` | Angeli et al. (2015), *Stanford OpenIE*，ACL 2015（供 1.2 節 RQ4 使用） | ACL Anthology P15-1034 |

**未下載（付費，不下載全文）**：Guha et al. (2016), *Schema.org: Evolution of Structured Data on the Web*（*Communications of the ACM* 59(2)）——ACM 需付費/機構帳號，無公開免費 PDF。引用時僅使用書目資訊（見 `../論文/附錄與參考文獻.md`）。

## 06_多模態輸入與網頁擷取 內容清單

| 檔案 | 文獻 | 來源 |
|---|---|---|
| `radford-et-al-2022-whisper-robust-speech-recognition.pdf` | Radford et al. (2022/2023), *Robust Speech Recognition via Large-Scale Weak Supervision*，ICML 2023（PMLR 202） | arXiv:2212.04356 |
| `barbaresi-2021-trafilatura.pdf` | Barbaresi (2021), *Trafilatura: A Web Scraping Library and Command-Line Tool for Text Discovery and Extraction*，ACL-IJCNLP 2021 System Demonstrations, pp. 122-131 | ACL Anthology 2021.acl-demo.15 |

## 07_文件分群與知識庫自動建立 內容清單

| 檔案 | 文獻 | 來源 |
|---|---|---|
| `grootendorst-2022-bertopic-neural-topic-modeling.pdf` | Grootendorst (2022), *BERTopic: Neural topic modeling with a class-based TF-IDF procedure* | arXiv:2203.05794 |
| `khandelwal-2025-llm-topic-labeling.pdf` | Khandelwal (2025), *Using LLM-Based Approaches to Enhance and Automate Topic Labeling* | arXiv:2502.18469 |

## 下載原則


- 只下載**公開合法**的版本（arXiv 預印本、開放取用期刊、作者自存版）。有版權限制、需訂閱或付費的正式出版版本不下載全文，僅記錄書目資訊供引用查證。
- 每次新增文獻，同步更新 `../論文/附錄與參考文獻.md` 的信任分級表，並在此 README 的清單中補上一列。
