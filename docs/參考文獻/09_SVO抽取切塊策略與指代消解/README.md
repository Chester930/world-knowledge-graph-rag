對應 `../../論文/03_系統設計與方法論.md` § 3.1.2 §a（切塊粒度整合：向量索引 vs. SVO 抽取視窗）。與第二章文獻探討的 2.1.x 章節無直接對應——3.1 屬 🔧 工程借鏡型機制、不對應任何 RQ，此資料夾的文獻是工程實作合理性佐證，性質同 `06_多模態輸入與網頁擷取/`／`07_文件分群與知識庫自動建立/`。**與 07 的分工**：07 是 3.1.1（分類/分群）的文獻，本資料夾是 3.1.2（切塊粒度與 SVO 抽取準備）的文獻，兩者處理不同的功能節點，不可混用。

2026-07-20 新增：查證起點是「3.1.1 現有 chunk（500 字元）該不該同時服務向量索引與 SVO 抽取」這個問題——先查了開放式抽取的產業慣例（GraphRAG／LightRAG），發現不適用受控詞彙場景後，改查本體論式（ontology-guided）／受控詞彙抽取的專門文獻。

2026-09-10 新增：論文 Pass 2 逐層程式碼審視（L1／L2）過程中，回頭補查「§3.1.2『法規領域專屬切塊策略：結構化資料優先直接映射』（`services/svo_chunking.py::ArticleAware`，按 `ArticleNo` 逐條切、一條一塊）」這個既有設計決策的檢索側文獻佐證——先前此決策的依據僅為「法規全文已是結構化資料」的直觀論述，缺乏「結構對齊切塊在檢索任務上確實優於 fixed-size」的實證引用。新增 3 篇：`prior-et-al-2026`（法規領域直接對應，結論與 `ArticleAware` 同型）、`sarthi-et-al-2024`（RAPTOR，結構感知檢索已發表代表作、亦為前者對照組）、`reuter-et-al-2025`（NLLP 2025，法規 RAG 切塊策略為檢索品質主因）。**此次僅佐證既有 `ArticleAware` 設計，不引入新機制**；RAG 向量索引軌（`chunk-NNN.md`）目前在管線中僅供分類/分群的文件代表向量取平均、無任何檢索消費者，不在本次改動範圍。

## 內容清單

| 檔案 | 文獻 | 來源 |
|---|---|---|
| `qu-et-al-2025-semantic-chunking-cost.pdf` | Qu, Tu & Bao (2025), *Is Semantic Chunking Worth the Computational Cost?* | 🟢 **Findings of NAACL 2025**，pp. 2155-2177，ACL Anthology |
| `mihindukulasooriya-et-al-2023-text2kgbench.pdf` | Mihindukulasooriya, Tiwari, Enguix & Lata (2023), *Text2KGBench: A Benchmark for Ontology-Driven Knowledge Graph Generation from Text* | 🟢 **ISWC 2023**（The Semantic Web，Springer LNCS），DOI: 10.1007/978-3-031-47243-5_14；亦見 arXiv:2308.02357 |
| `meher-et-al-2025-core-kg.pdf` | Meher, Domeniconi & Correa-Cabrera (2025), *CORE-KG: An LLM-Driven Knowledge Graph Construction Framework for Human Smuggling Networks* | 🟡 **KDD '25 Workshop SKnow-LLM**（Structured Knowledge for Large Language Models），2025 年 8 月，Toronto；arXiv:2506.21607 |
| `meher-domeniconi-2025-core-kg-ablation.pdf` | Meher & Domeniconi (2025), *Inside CORE-KG: Evaluating Structured Prompting and Coreference Resolution for Knowledge Graphs* | 🟡 arXiv 預印本 2510.26512，尚未查到正式會議/期刊發表版本；CORE-KG 的量化消融驗證（上一篇的後續研究） |
| `prior-et-al-2026-chunking-german-legal-code.pdf` | Prior, Milanova & Schultz (2026), *Chunking German Legal Code* | 🟡 arXiv 預印本 2605.19806（2026-05），尚未查到正式會議/期刊發表版本 |
| `sarthi-et-al-2024-raptor.pdf` | Sarthi, Abdullah, Tuli, Khanna, Goldie, Manning (2024), *RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval* | 🟢 **ICLR 2024**；arXiv:2401.18059 |
| `reuter-et-al-2025-reliable-legal-retrieval-sac.pdf` | Reuter, Lingenberg, Liepiņa, Lagioia, Lippi, Sartor, Passerini, Sayin (2025), *Towards Reliable Retrieval in RAG Systems for Large Legal Datasets* | 🟢 **NLLP 2025**（7th Natural Legal Language Processing Workshop, co-located with EMNLP 2025）；arXiv:2510.06999 |

## 產業慣例查證（無 PDF，直接查證一手原始碼／官方文件，記錄於此供追溯）

| 專案 | 查證結果 | 來源 |
|---|---|---|
| **Microsoft GraphRAG**（Edge et al., 2024，已是本論文主要對照架構） | `ChunkingDefaults`：`size=1200`、`overlap=100`，**單位為 token**（非字元），直接讀取 `packages/graphrag/graphrag/config/defaults.py` 原始碼確認；並追蹤 `extract_graph.py`／`generate_text_embeddings.py` 兩個 workflow，確認兩者共用同一張 `text_units` 表——**向量索引與實體/關係抽取共用同一種切塊，未分開**。**適用性侷限**：GraphRAG 是開放式抽取（relationship_description 為自由文字），不是本論文 3.3 節的受控詞彙抽取，此慣例數值不能直接套用到受控場景。 | GitHub `microsoft/graphrag`，2026-07-20 直接查證原始碼 |
| **LightRAG**（Guo et al., 2024，本論文已引用） | 官方預設 `chunk_token_size=1200`、`chunk_overlap_token_size=100`，與 GraphRAG 完全相同——僅透過搜尋摘要確認，**未如 GraphRAG 直接查證原始碼**，信任等級較低，且同樣是開放式抽取，不直接適用受控場景。 | GitHub `HKUDS/LightRAG`，2026-07-20 查證（⚠️ 未讀原始碼，待補） |

## 各文獻在本節設計討論中的角色

- **Qu, Tu & Bao (2025)**：實證顯示固定 200 字切塊在檢索/生成任務上表現持平或優於語意切分，直接回應「切塊是否該依語意邊界」這個問題——但**這是檢索/生成任務的實證，非關係抽取任務**，不能直接當作「SVO 抽取也不需要語意切分」的證據，只能說「語意切分優越性」這個常見假設本身就有實證反例，需獨立看待。
- **Mihindukulasooriya et al. (2023) Text2KGBench**：目前查到**唯一一篇明確做「給定受控本體、從文字抽取符合本體之三元組」這個確切任務**的專門文獻，任務性質與本論文 3.3 節（RQ4）幾乎一致。其資料集以**句子級**對齊三元組，是本體論式抽取領域的既有學術慣例；但論文本身在資料清洗章節（Section 3.1）**明確承認**句子級抽取會因指代消解失敗而漏抽跨句關係（例："The film was also nominated for..." 因「the film」無法在單句內解析而被排除出高品質測試集），**未提出解決方案，而是選擇迴避**（排除此類句子）。這直接證實了本節切塊粒度討論最初提出的疑慮，且是從本體論式抽取的專門文獻內部證實，非本論文自行推論。
- **Meher, Domeniconi & Correa-Cabrera (2025) CORE-KG** ＋ **Meher & Domeniconi (2025) 消融研究**：目前查到**唯一一篇針對「切塊前先解決跨句指代消解」提出具體解法並量化驗證效果**的文獻。方法是**指代消解與切塊解耦**——先對整份文件跑「逐類型循序」的 LLM 指代消解（先解 Person、再 Location、再 Route...，避免一次解多類型導致注意力分散），把「Young」「the defendant」「the driver」等統一成單一標準形式，**產生「指代消解後的完整文字」，才進入下一步的切塊＋抽取**（切塊本身沿用 GraphRAG 的 300-token 重疊切塊，未改變切塊機制本身）。消融實驗（LLaMA 3.3 70B、20 份真實美國聯邦/州法院人口走私案件文件）量化證實：拿掉指代消解模組，節點重複率上升 28.25%（20.28%→26.01%）、雜訊節點增加 4.32%。**此法不是本論文原本設計的「滑動視窗擴大抽取時的上下文」，而是把指代消解完全移到切塊之前的獨立前處理步驟**——兩者是不同的技術路線，皆可能回應同一個問題（跨句指代消解導致漏抽），需要在 3.1.2 §a 正式定案時擇一或評估是否可以並用。
- ⚠️ **CORE-KG 的任務性質差異**：CORE-KG 做的是開放式實體/關係抽取（不受控詞彙），不是本論文 3.3 節的受控 30 類 SVO_REL_TYPES 抽取；其指代消解模組的設計（逐實體類型循序處理）本身與受控詞彙無關，方法可遷移，但量化效果數字（28.25%／4.32%）是在其開放式抽取＋法律文件領域測得，不可直接假設同樣幅度會發生在本論文的受控詞彙＋任意領域文件情境下。

### 2026-09-10 新增三篇：結構對齊切塊的檢索側佐證（支撐既有 `ArticleAware`）

- **Prior, Milanova & Schultz (2026) Chunking German Legal Code**：目前查到**與本論文 `ArticleAware` 最直接對應**的文獻——對德國民法典（BGB）系統性比較多種切塊策略對檢索的影響，結論：「chunking strategies aligned with the inherent legal structure — particularly section and subsection-based retrieval — achieve the highest recall」，且**同時勝過 fixed-size 視窗與 RAPTOR／Lumber 式語意切塊**，運算效率還更高。本論文 `services/svo_chunking.py::ArticleAware`（按 `ArticleNo` 逐條切、一條一塊、不套用固定句數上限與重疊窗）正是「section/subsection 對齊」在中文法規（逐條）情境下的實例，此文提供了先前僅有直觀論述的實證支撐。⚠️ **適配度**：(1) 此文是 arXiv 預印本，尚未正式發表；(2) 其評測任務是**檢索**（給查詢找相關條文），本論文 `ArticleAware` 的直接用途是 **SVO 抽取單位**（一條一塊送 LLM 抽三元組），兩者都受益於「不跨越法規結構邊界」，但「檢索 recall 最高」不能直接等同於「抽取品質最高」，只能說「override 法規結構會損害下游任務」這個方向有跨任務的一致證據；(3) 德國民法典的 section/subsection 與中華民國法規的「條/項/款」層級對應非嚴格一對一，本論文取「條」為切塊單位是工程選擇。
- **Sarthi et al. (2024) RAPTOR**（ICLR 2024）：結構感知檢索的**已發表代表作**，遞迴地對 chunk 分群、摘要，由下而上建一棵多層摘要樹，檢索時可跨抽象層取用。在本資料夾的角色是**「結構感知 > 平鋪 fixed-size」這個大方向有頂級會議背書**的錨點，且是上述德國法規論文的對照組之一（該文結論為：在法規逐條結構已明確的場景，簡單的 section 對齊切塊反而勝過 RAPTOR 這類需 LLM 的複雜方法）。⚠️ **適配度**：RAPTOR 的樹是**演算法生成的摘要層級**（非文件既有結構），與本論文「直接沿用法規既有的條文邊界」是不同路線——本論文對法規採「結構化資料優先直接映射」（既有結構就是最好的切塊邊界，不需再生成），RAPTOR 適用於「文件本身沒有可靠結構、需要演算法補一層」的情境；兩者互補，非替代。
- **Reuter et al. (2025) Towards Reliable Retrieval in RAG Systems for Large Legal Datasets**（NLLP 2025 @ EMNLP）：正式 workshop 論文，主要貢獻是 **Summary-Augmented Chunking (SAC)**——為每個 chunk 補一段合成摘要以對抗 Document-Level Retrieval Mismatch（DRM，檢索到對的文件、卻是文件裡錯的 chunk）。在本資料夾的角色是**佐證「法規 RAG 的切塊策略是檢索品質的主因、值得專門處理」**這個前提，以及一個副發現：「a generic summarization strategy outperforms an approach that incorporates legal expert domain knowledge」——與 CORE-KG 消融「逐類型循序指代消解」的精神一致（領域知識不一定贏過通用策略）。⚠️ **適配度**：SAC 是在既有切塊上「加摘要」，不改切塊邊界本身，與 `ArticleAware`「換切塊邊界」是正交的兩件事；此文列入僅為前提佐證，非方法借鏡。
