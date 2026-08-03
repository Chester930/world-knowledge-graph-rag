# 參考文獻資料夾

存放論文引用文獻的原始文檔（PDF），依論文章節主題分類到子資料夾。命名規則：`第一作者-年份-關鍵詞.pdf`（小寫、連字號分隔）。

## 分類與章節對應

> **2026-07-23 更新**：`02_文獻探討.md` 已重新架構（先依 RQ 彙整核心文獻，再依第三章系統流程階段逐一補充方法層級佐證），下表章節對應已同步校正；同時補上先前遺漏的 `08_`／`09_` 兩個資料夾（皆已有實際下載內容，此前僅未列入本索引，非文獻本身有缺）。

| 資料夾 | 對應論文章節（2026-07-23 起） | 狀態 |
|---|---|---|
| `01_AGI與智慧定義/` | 01_緒論.md § 1.1.1-1.1.4 | 🟢 已下載 13 篇 |
| `02_RAG與GraphRAG/` | 02_文獻探討.md § 2.4.2／2.4.3（GraphRAG，RQ1/RQ2）、§ 2.4.6（T-GRAG，RQ5）、§ 2.4.7（RAG 演進，RQ3）、§ 2.5（評估方法論）；01_緒論.md § 1.1.1、1.1.4；`docs/報告/04_GraphRAG深度文獻回顧.md` | 🟢 已下載 25 篇 |
| `03_資訊抽取與本體設計/` | 02_文獻探討.md § 2.4.4（RQ4a）；01_緒論.md § 1.2 RQ4a（預留）；03_系統設計與方法論.md § 3.1.3／3.1.4／3.2 §b（2026-07-24 擴充；2026-07-26 補充抽取分工文獻與 cascade deferral 文獻；2026-07-27 補充描述句 embedding 文獻與背景任務執行模型文獻） | 🟡 已下載 20 篇，1 篇付費未下載，另有數篇標註規範/社群方針頁面非論文（僅記書目） |
| `04_圖遍歷與大節點問題/` | 02_文獻探討.md § 2.4.8（RQ6） | ⚪ 待下載 |
| `05_評估方法論/` | 02_文獻探討.md § 2.5（評估方法論的橫向文獻回顧） | ⚪ 待下載 |
| `06_多模態輸入與網頁擷取/` | `parser/README.md`（Ingestion Parser 模組工程實作支撐文獻）；02_文獻探討.md § 2.6.1 摘要收錄 | 🟢 已下載 2 篇 |
| `07_文件分群與知識庫自動建立/` | 03_系統設計與方法論.md § 3.1.1（暫存區 AI 自動分群建立 KG）；02_文獻探討.md § 2.4.1 | 🟡 已下載 2 篇，皆僅 arXiv 預印本 |
| `08_向量化與語意表示/` | `core/providers/embedding/README.md`（向量化模組工程實作支撐文獻）；02_文獻探討.md § 2.6.2 摘要收錄 | 🟢 已下載 5 篇 |
| `09_SVO抽取切塊策略與指代消解/` | 02_文獻探討.md § 2.4.5（RQ4b，切塊策略與指代消解前置）；03_系統設計與方法論.md § 3.4 | 🟢 已下載 4 篇 |
| `10_跨文件實體別名消解與增量聚類/` | 02_文獻探討.md § 2.4.5（RQ4b，跨文件增量別名聚類架構）；03_系統設計與方法論.md § 3.4；`docs/報告/09_實體別名登記與動態標準名提升機制設計報告.md` | 🟡 已下載 3 篇，皆待精讀方法章節 |
| `11_事實層級去重與知識融合/` | 02_文獻探討.md § 2.6.3（事實層級去重，工程實作合理性佐證）；03_系統設計與方法論.md § 3.1.4「事實層級去重」 | 🟢 已下載 1 篇，另交叉引用 03 資料夾既有文獻 |
| `12_三元組事實層級向量化與檢索/` | 03_系統設計與方法論.md § 3.1.4 §a（事實層級向量化，RQ1/RQ3，即時路徑已實作，§b 回填仍為設計提案） | 🟢 已下載 3 篇，另交叉引用 02 資料夾既有的 LightRAG，四篇皆已全文精讀 |
| `13_實體節點向量化去重開源專案/` | 03_系統設計與方法論.md § 3.1.4「實體對齊/去重」（`DEDUP4`／`resolve_entity_name()`，Entity 節點 `name_embedding` 效能改造，2026-08-03 已定案並實作） | ✅ 機制已實作；文獻查證仍為 🟡 初步層級，已下載 2 篇，另查證 3 個 1000★+ 開源專案，皆僅初步查證未全文精讀 |

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
| `hovy-et-al-2006-ontonotes.pdf` | Hovy et al. (2006), *OntoNotes: The 90% Solution*，NAACL 2006（OntoNotes 計畫背景書目——⚠️ 2026-07-26 訂正：全文不涉及 NER，不再作為實體類型庫依據） | [ACL Anthology N06-2015](https://aclanthology.org/N06-2015/) |
| `pradhan-et-al-2013-conll-ontonotes.pdf` | Pradhan et al. (2013), *Towards Robust Linguistic Analysis Using OntoNotes*，CoNLL 2013（歷史記錄——曾短暫作為 18 類 NER 標籤依據，因未列出具體標籤名稱，2026-07-26 同日改採 Brinkmann et al. 2023） | [ACL Anthology W13-3516](https://aclanthology.org/W13-3516/) |
| `weischedel-et-al-2011-ontonotes-handbook-chapter.pdf` | Weischedel et al. (2011), *OntoNotes: A Large Training Corpus for Enhanced Processing*，Springer Handbook chapter（歷史記錄，理由同上） | Eduard Hovy 個人網站開放取用 |
| `brinkmann-et-al-2023-wdc-schemaorg-dataset-series.pdf` | Brinkmann, Primpeli & Bizer (2023), *The Web Data Commons Schema.org Data Set Series*，WWW '23 Companion（公用實體類型庫現行依據——與同一 2022 release 官方統計頁聯集去重後共 52 個 schema.org 實測類型，供 3.1.3／3.1.4 使用，2026-07-26 新增並擴充，取代 OntoNotes 18 類） | DOI: [10.1145/3543873.3587331](https://doi.org/10.1145/3543873.3587331) |
| `speer-et-al-2017-conceptnet.pdf` | Speer, Chin & Havasi (2017), *ConceptNet 5.5*，AAAI 2017（公用關係庫依據，供 3.1.3 使用；論文正文自稱 36 個核心關係，逐字核對實際列出 35 個；2026-07-27 再查證官方 wiki 發現 `Entails`／`InstanceOf` 已棄用，`core/constants.py::SVO_REL_TYPES` 已改按 33 個落地，誠實聲明見子資料夾 README） | [arXiv:1612.03975](https://arxiv.org/abs/1612.03975) |
| `chen-li-2021-zs-bert.pdf` | Chen & Li (2021), *ZS-BERT*，NAACL 2021（`SIM` 描述句 embedding 設計依據，2026-07-27 新增） | [arXiv:2104.04697](https://arxiv.org/abs/2104.04697) |
| `zaharia-et-al-2013-discretized-streams-spark-streaming.pdf` | Zaharia et al. (2013), *Discretized Streams*，SOSP 2013（3.1.3 §a 背景任務執行模型通用架構原則佐證，2026-07-27 新增） | [開放取用全文](https://people.eecs.berkeley.edu/~matei/papers/2013/sosp_spark_streaming.pdf) |
| `aguilar-et-al-2014-ace-ere-tackbp-framenet-comparison.pdf` | Aguilar et al. (2014)，ACL 2014 EVENTS workshop（ACE/ERE/TAC-KBP/FrameNet 關係本體比較，供 3.1.3 使用） | [ACL Anthology W14-2907](https://aclanthology.org/W14-2907/) |
| `yih-et-al-2015-staged-query-graph-generation.pdf` | Yih et al. (2015), *STAGG*，ACL-IJCNLP 2015（查詢時關係連結核心文獻，供 3.2 §b 使用） | [ACL Anthology P15-1128](https://aclanthology.org/P15-1128/)；[GitHub scottyih/STAGG](https://github.com/scottyih/STAGG)（111★） |
| `sakor-et-al-2020-falcon2.pdf` | Sakor et al. (2020), *Falcon 2.0*，CIKM '20（關係連結任務佐證，供 3.2 §b 使用） | [arXiv:1912.11270](https://arxiv.org/abs/1912.11270)；[GitHub SDM-TIB/falcon2.0](https://github.com/SDM-TIB/falcon2.0)（120★） |
| `mihindukulasooriya-et-al-2020-sling-relation-linking.pdf` | Mihindukulasooriya et al. (2020), *SLING*，ISWC 2020（關係連結任務佐證，供 3.2 §b 使用） | [arXiv:2009.07726](https://arxiv.org/abs/2009.07726)；[GitHub IBM/kbqa-relation-linking](https://github.com/IBM/kbqa-relation-linking)（22★，2026-07-26 訂正原誤植的 `IBM/neuro-symbolic-ai`） |
| `xue-et-al-2024-autore-doc-level-re.pdf` | Xue et al. (2024), *AutoRE*，ACL 2024 System Demonstrations（抽取分工設計佐證，供 3.1.3 使用） | [ACL Anthology 2024.acl-demos.20](https://aclanthology.org/2024.acl-demos.20/)；[GitHub THUDM/AutoRE](https://github.com/THUDM/AutoRE)（85★） |
| `mo-et-al-2025-kggen.pdf` | Mo et al. (2025), *KGGen*，NeurIPS 2025（抽取分工設計佐證，供 3.1.3 使用） | [arXiv:2502.09956](https://arxiv.org/abs/2502.09956)；[GitHub stair-lab/kg-gen](https://github.com/stair-lab/kg-gen)（1,233★） |
| `bloodgood-vijay-shanker-2009-stopping-active-learning.pdf` | Bloodgood & Vijay-Shanker (2009), *Stabilizing Predictions 停止 AL 方法*，CoNLL 2009（3.1.3 §a 人機一致率畢業機制的支持文獻，2026-07-26 新增） | [ACL Anthology W09-1107](https://aclanthology.org/W09-1107/)；[arXiv:1409.5165](https://arxiv.org/abs/1409.5165) |
| `bloodgood-grothendieck-2013-analysis-stopping-active-learning.pdf` | Bloodgood & Grothendieck (2013), *Analysis of Stopping Active Learning*，CoNLL 2013（上述方法的理論分析，2026-07-26 新增） | [ACL Anthology W13-3502](https://aclanthology.org/W13-3502/)；[arXiv:1504.06329](https://arxiv.org/abs/1504.06329) |
| `jitkrittum-et-al-2023-confidence-cascade-deferral.pdf` | Jitkrittum et al. (2023, Google Research), *When Does Confidence-Based Cascade Deferral Suffice?*，NeurIPS 2023（3.1.3 主圖 `SIM`／`ESCALATE3` 機制核心理論依據，2026-07-26 新增） | [arXiv:2307.02764](https://arxiv.org/abs/2307.02764) |
| `madras-et-al-2018-learning-to-defer.pdf` | Madras, Pitassi & Zemel (2018), *Predict Responsibly: Learning to Defer*，NeurIPS 2018（learning-to-defer 術語與理論定位，2026-07-26 新增） | [arXiv:1711.06664](https://arxiv.org/abs/1711.06664) |

**未下載（付費，不下載全文）**：Guha et al. (2016), *Schema.org: Evolution of Structured Data on the Web*（*Communications of the ACM* 59(2)）——ACM 需付費/機構帳號，無公開免費 PDF。引用時僅使用書目資訊（見 `../論文/附錄與參考文獻.md`）。

**未下載（標註規範非期刊論文，僅記書目）**：ACE 2005 Relation Extraction Task 標註規範（LDC）——6 個粗類、18 個細類，透過 Aguilar et al. (2014) 查證存在性，未取得 LDC 原始規範全文。

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

## 11_事實層級去重與知識融合 內容清單

| 檔案 | 文獻 | 來源 |
|---|---|---|
| `dong-et-al-2014-knowledge-vault.pdf` | Dong et al. (2014, Google), *Knowledge Vault: A Web-Scale Approach to Probabilistic Knowledge Fusion*，KDD 2014 | https://www.cs.ubc.ca/~murphyk/papers/kv-kdd14.pdf |

**與 03_資訊抽取與本體設計 的交叉引用**：本資料夾同時引用已存於 `03_資訊抽取與本體設計/vrandecic-krotzsch-2014-wikidata.pdf` 的 Wikidata 論文「Citation Needed」段落——完整查證與兩篇文獻各自的誠實適配度分析見 `11_事實層級去重與知識融合/README.md`。

## 12_三元組事實層級向量化與檢索 內容清單

| 檔案 | 文獻 | 來源 |
|---|---|---|
| `baek-et-al-2023-kaping.pdf` | Baek, Aji & Saffari (2023), *KAPING*，NLRSE workshop @ ACL 2023 | arXiv:2306.04136 |
| `gutierrez-et-al-2024-hipporag.pdf` | Gutiérrez et al. (2024), *HippoRAG*，NeurIPS 2024 | arXiv:2405.14831 |
| `he-et-al-2024-g-retriever.pdf` | He et al. (2024), *G-Retriever*，NeurIPS 2024 | arXiv:2402.07630 |

**與 02_RAG與GraphRAG 的交叉引用**：本資料夾同時引用已存於 `02_RAG與GraphRAG/guo-et-al-2024-lightrag.pdf` 的 LightRAG 論文 §3.1/§3.2 relation 向量化機制——完整查證見 `12_三元組事實層級向量化與檢索/README.md`。

## 13_實體節點向量化去重開源專案 內容清單

| 檔案 | 文獻 | 來源 |
|---|---|---|
| `enamorado-fifield-imai-2019-fastlink.pdf` | Enamorado, Fifield & Imai (2019), *Using a Probabilistic Model to Assist Merging of Large-Scale Administrative Records*，American Political Science Review 113(2) | https://imai.fas.harvard.edu/research/files/linkage.pdf |
| `linacre-et-al-2022-splink.pdf` | Linacre et al. (2022), *Splink: Free software for probabilistic record linkage at scale*，International Journal of Population Data Science 7(3) | DOI: 10.23889/ijpds.v7i3.1794 |

**開源專案查證（不下載全文，僅 `gh api` 驗證真實性）**：`neo4j-labs/llm-graph-builder`（4,979★，Entity 節點 embedding+向量索引+去重機制，同構於本專案 DEDUP4 設計選項）、`moj-analytical-services/splink`（2,310★，上列兩篇文獻的生產級落地）、`zinggAI/zingg`（1,233★，查無學術文獻依據，僅工程參考價值）——完整查證細節與誠實限制見 `13_實體節點向量化去重開源專案/README.md`。

## 下載原則


- 只下載**公開合法**的版本（arXiv 預印本、開放取用期刊、作者自存版）。有版權限制、需訂閱或付費的正式出版版本不下載全文，僅記錄書目資訊供引用查證。
- 每次新增文獻，同步更新 `../論文/附錄與參考文獻.md` 的信任分級表，並在此 README 的清單中補上一列。
