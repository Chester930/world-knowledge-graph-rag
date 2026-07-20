對應 `../../論文/03_系統設計與方法論.md` § 3.1.2 §a（切塊粒度整合：向量索引 vs. SVO 抽取視窗）。與第二章文獻探討的 2.1.x 章節無直接對應——3.1 屬 🔧 工程借鏡型機制、不對應任何 RQ，此資料夾的文獻是工程實作合理性佐證，性質同 `06_多模態輸入與網頁擷取/`／`07_文件分群與知識庫自動建立/`。**與 07 的分工**：07 是 3.1.1（分類/分群）的文獻，本資料夾是 3.1.2（切塊粒度與 SVO 抽取準備）的文獻，兩者處理不同的功能節點，不可混用。

2026-07-20 新增：查證起點是「3.1.1 現有 chunk（500 字元）該不該同時服務向量索引與 SVO 抽取」這個問題——先查了開放式抽取的產業慣例（GraphRAG／LightRAG），發現不適用受控詞彙場景後，改查本體論式（ontology-guided）／受控詞彙抽取的專門文獻。

## 內容清單

| 檔案 | 文獻 | 來源 |
|---|---|---|
| `qu-et-al-2025-semantic-chunking-cost.pdf` | Qu, Tu & Bao (2025), *Is Semantic Chunking Worth the Computational Cost?* | 🟢 **Findings of NAACL 2025**，pp. 2155-2177，ACL Anthology |
| `mihindukulasooriya-et-al-2023-text2kgbench.pdf` | Mihindukulasooriya, Tiwari, Enguix & Lata (2023), *Text2KGBench: A Benchmark for Ontology-Driven Knowledge Graph Generation from Text* | 🟢 **ISWC 2023**（The Semantic Web，Springer LNCS），DOI: 10.1007/978-3-031-47243-5_14；亦見 arXiv:2308.02357 |
| `meher-et-al-2025-core-kg.pdf` | Meher, Domeniconi & Correa-Cabrera (2025), *CORE-KG: An LLM-Driven Knowledge Graph Construction Framework for Human Smuggling Networks* | 🟡 **KDD '25 Workshop SKnow-LLM**（Structured Knowledge for Large Language Models），2025 年 8 月，Toronto；arXiv:2506.21607 |
| `meher-domeniconi-2025-core-kg-ablation.pdf` | Meher & Domeniconi (2025), *Inside CORE-KG: Evaluating Structured Prompting and Coreference Resolution for Knowledge Graphs* | 🟡 arXiv 預印本 2510.26512，尚未查到正式會議/期刊發表版本；CORE-KG 的量化消融驗證（上一篇的後續研究） |

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
