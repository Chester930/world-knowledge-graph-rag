# 參考文獻資料夾

存放論文引用文獻的原始文檔（PDF），依論文章節主題分類到子資料夾。命名規則：`第一作者-年份-關鍵詞.pdf`（小寫、連字號分隔）。

## 分類與章節對應

> **2026-07-23 更新**：`02_文獻探討.md` 已重新架構（先依 RQ 彙整核心文獻，再依第三章系統流程階段逐一補充方法層級佐證），下表章節對應已同步校正；同時補上先前遺漏的 `08_`／`09_` 兩個資料夾（皆已有實際下載內容，此前僅未列入本索引，非文獻本身有缺）。

| 資料夾 | 對應論文章節（2026-07-23 起） | 狀態 |
|---|---|---|
| `01_AGI與智慧定義/` | 01_緒論.md § 1.1.1-1.1.4 | 🟢 已下載 13 篇 |
| `02_RAG與GraphRAG/` | 02_文獻探討.md § 2.4.2／2.4.3（GraphRAG，RQ1/RQ2）、§ 2.4.6（T-GRAG，RQ5）、§ 2.4.7（RAG 演進，RQ3）、§ 2.5（評估方法論）；01_緒論.md § 1.1.1、1.1.4；`docs/報告/04_GraphRAG深度文獻回顧.md` | 🟢 已下載 25 篇 |
| `03_資訊抽取與本體設計/` | 02_文獻探討.md § 2.4.4（RQ4a）；01_緒論.md § 1.2 RQ4a（預留） | 🟡 已下載 2 篇，1 篇付費未下載 |
| `04_圖遍歷與大節點問題/` | 02_文獻探討.md § 2.4.8（RQ6） | ⚪ 待下載 |
| `05_評估方法論/` | 02_文獻探討.md § 2.5（評估方法論的橫向文獻回顧） | ⚪ 待下載 |
| `06_多模態輸入與網頁擷取/` | `parser/README.md`（Ingestion Parser 模組工程實作支撐文獻）；02_文獻探討.md § 2.6.1 摘要收錄 | 🟢 已下載 2 篇 |
| `07_文件分群與知識庫自動建立/` | 03_系統設計與方法論.md § 3.1.1（暫存區 AI 自動分群建立 KG）；02_文獻探討.md § 2.4.1 | 🟡 已下載 2 篇，皆僅 arXiv 預印本 |
| `08_向量化與語意表示/` | `core/providers/embedding/README.md`（向量化模組工程實作支撐文獻）；02_文獻探討.md § 2.6.2 摘要收錄 | 🟢 已下載 5 篇 |
| `09_SVO抽取切塊策略與指代消解/` | 02_文獻探討.md § 2.4.5（RQ4b，切塊策略與指代消解前置）；03_系統設計與方法論.md § 3.4 | 🟢 已下載 4 篇 |
| `10_跨文件實體別名消解與增量聚類/` | 02_文獻探討.md § 2.4.5（RQ4b，跨文件增量別名聚類架構）；03_系統設計與方法論.md § 3.4；`docs/報告/09_實體別名登記與動態標準名提升機制設計報告.md` | 🟡 已下載 3 篇，皆待精讀方法章節 |

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

## 08_向量化與語意表示 內容清單

| 檔案 | 文獻 | 來源 |
|---|---|---|
| `reimers-gurevych-2019-sentence-bert.pdf` | Reimers & Gurevych (2019), *Sentence-BERT*，EMNLP-IJCNLP 2019 | arXiv:1908.10084 |
| `chen-et-al-2023-dense-x-retrieval.pdf` | Chen et al. (2023/2024), *Dense X Retrieval*，EMNLP 2024 | arXiv:2312.06648 |
| `bhat-et-al-2025-rethinking-chunk-size.pdf` | Bhat et al. (2025), *Rethinking Chunk Size for Long-Document Retrieval* | arXiv:2505.21700 |
| `muennighoff-et-al-2023-mteb.pdf` | Muennighoff et al. (2022/2023), *MTEB*，EACL 2023 | arXiv:2210.07316 |
| `khattab-zaharia-2020-colbert.pdf` | Khattab & Zaharia (2020), *ColBERT*，SIGIR 2020 | arXiv:2004.12832 |

## 09_SVO抽取切塊策略與指代消解 內容清單

| 檔案 | 文獻 | 來源 |
|---|---|---|
| `qu-et-al-2025-semantic-chunking-cost.pdf` | Qu, Tu & Bao (2025), Findings of NAACL 2025，固定字數切塊 vs. 語意切分實證比較 | ACL Anthology 2025.findings-naacl.114 |
| `mihindukulasooriya-et-al-2023-text2kgbench.pdf` | Mihindukulasooriya et al. (2023), *Text2KGBench*，ISWC 2023 | arXiv:2308.02357 |
| `meher-et-al-2025-core-kg.pdf` | Meher, Domeniconi & Correa-Cabrera (2025), *CORE-KG*，KDD '25 Workshop SKnow-LLM | arXiv:2506.21607 |
| `meher-domeniconi-2025-core-kg-ablation.pdf` | Meher & Domeniconi (2025), CORE-KG 消融研究 | arXiv:2510.26512 |

## 10_跨文件實體別名消解與增量聚類 內容清單

| 檔案 | 文獻 | 來源 |
|---|---|---|
| `rao-et-al-2010-streaming-cross-document-coref.pdf` | Rao, McNamee & Dredze (2010), *Streaming Cross Document Entity Coreference Resolution*，COLING 2010: Posters | ACL Anthology C10-2121 |
| `ji-et-al-2011-tac-kbp-overview.pdf` | Ji, Grishman & Dang (2011), *Overview of the TAC2011 Knowledge Base Population Track* | https://blender.cs.illinois.edu/paper/kbp2011.pdf |
| `saeedi-et-al-2020-incremental-multi-source-er.pdf` | Saeedi, Peukert & Rahm (2020), *Incremental Multi-source Entity Resolution for Knowledge Graph Completion*，ESWC 2020 | DOI: 10.1007/978-3-030-49461-2_23 |

**與 03_資訊抽取與本體設計 的交叉引用**：本資料夾 3 篇僅佐證「跨文件增量別名聚類架構」，標準名選取規則（出現頻率優先）的文獻依據仍在 `03_資訊抽取與本體設計/`（Wikidata、CESI）——完整的兩層佐證分工說明見 `10_跨文件實體別名消解與增量聚類/README.md`。

## 下載原則


- 只下載**公開合法**的版本（arXiv 預印本、開放取用期刊、作者自存版）。有版權限制、需訂閱或付費的正式出版版本不下載全文，僅記錄書目資訊供引用查證。
- 每次新增文獻，同步更新 `../論文/附錄與參考文獻.md` 的信任分級表，並在此 README 的清單中補上一列。
