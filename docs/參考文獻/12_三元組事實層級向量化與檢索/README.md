對應 `../../論文/03_系統設計與方法論.md` § 3.1.4 §a「事實層級向量化 Behavior Tree（三元組向量化）」——查詢時對三元組本身做語意層級檢索的設計提案（🟡 尚未實作）。

## 查證背景（2026-07-29）

使用者盤點後發現，系統目前只有切塊向量化（`Chunk.embedding`）與 `ConceptNode` 路由層向量，完全沒有針對三元組/事實本身做向量化，查詢時只能靠實體名稱命中、`rel_type` 命中與 BFS 走訪。討論後定案：新增 `Fact` 節點，以「每筆 citation」為粒度（而非每條 MERGE 後的邊）產生獨立 `fact_embedding`，與現行「事實層級去重」的邊 MERGE／`citations_json` 設計脫鉤並存。本資料夾收錄查證後找到的四篇核心文獻/專案，全部已逐字精讀全文（含附錄），非僅讀摘要。

## 內容清單

| 檔案 | 文獻 | 來源 |
|---|---|---|
| `baek-et-al-2023-kaping.pdf` | Baek, Aji & Saffari (2023), *Knowledge-Augmented Language Model Prompting for Zero-Shot Knowledge Graph Question Answering*（KAPING），NLRSE workshop @ ACL 2023 | arXiv:2306.04136 |
| `gutierrez-et-al-2024-hipporag.pdf` | Gutiérrez, Shu, Gu, Yasunaga & Su (2024), *HippoRAG: Neurobiologically Inspired Long-Term Memory for Large Language Models*，NeurIPS 2024 | arXiv:2405.14831 |
| `he-et-al-2024-g-retriever.pdf` | He, Tian, Chen, Chawla, Ferber, Wang, Duan, Liu, Konjević & Zhu (2024), *G-Retriever: Retrieval-Augmented Generation for Textual Graph Understanding and Question Answering*，NeurIPS 2024 | arXiv:2402.07630 |
| （交叉引用，PDF 已存於 `../02_RAG與GraphRAG/guo-et-al-2024-lightrag.pdf`） | Guo, Xia, Yu, Ao & Huang (2024), *LightRAG: Simple and Fast Retrieval-Augmented Generation*，EMNLP 2025 | arXiv:2410.05779 |

## 四篇文獻在本設計中的角色

### 1. KAPING——本節設計的核心方法論先例

全文精讀確認：KAPING 先以問題中的實體匹配出 KG 中該實體的關聯三元組，再將這些三元組 verbalize 成文字（subject-relation-object 直接串接，稱為 *linear verbalization*），以現成 sentence embedding 模型（MPNet／TAS-B）向量化後與問題向量算 cosine 相似度，取 top-K 做 zero-shot 檢索，完全不需訓練。這正是本節「三元組文字化→embedding→cosine 相似度檢索」設計的直接方法論來源。

**全文精讀新增細節（Appendix B.5 消融實驗）**：作者比較「簡單串接」與「訓練過的 graph-to-text 轉換模型」兩種 verbalization 方式，結果簡單串接的檢索表現反而更好——複雜轉換模型有時會生成語意偏離原三元組的文字。這直接佐證本節選擇「subject＋原始 `verb`＋object」直接串接、不引入額外轉換模型的設計是有實證支持的，非隨意簡化。

**誠實侷限**：KAPING 的檢索範圍限定在「先匹配問題實體、再從其關聯三元組中挑選」，而非對全圖三元組做開放式向量搜尋。G-Retriever（見下）的消融實驗直接指出 KAPING 這種檢索方式 *"is chosen in isolation from the graph"*（未利用圖結構鄰接關係）——本節 `Fact` 節點目前的檢索設計（比對所有 `fact_embedding` 找最相關候選）同樣屬於這種「與圖結構脫鉤」的扁平檢索，是本設計目前未解決的已知侷限，非 KAPING 特有的問題。

### 2. LightRAG——「關係邊獨立向量化」的生產級驗證

全文精讀確認 §3.1「LLM Profiling for Key-Value Pair Generation」原文：使用 LLM profiling function 為每個 entity 節點與每條 relation 邊各自產生文字 key-value pair，"Entities use their names as the sole index key, whereas relations may have multiple index keys derived from LLM enhancements that include global themes from connected entities."；檢索時（§3.2）entity 與 relation 分別用獨立的向量資料庫比對（"match local query keywords with candidate entities and global query keywords with relations linked to global keys"）。這證實「關係邊獨立向量化、與實體向量分層索引」已在生產級開源專案（`HKUDS/LightRAG`）驗證可行，本節 `Fact` 節點設計理念與此一致。

**設計差異（誠實記錄）**：LightRAG 的 relation "value" 是 LLM 生成的**摘要段落**（summarizing relevant snippets），非原始動詞字串；本節 `fact_text` 選擇保留原始 `verb` 而非另外摘要——這是刻意的設計取捨（保留細緻語意優先於正規化摘要），與 LightRAG 的取捨方向不同，不算矛盾，但值得記錄供未來比較是否要引入摘要層。

### 3. HippoRAG——對照組，佐證「只做實體向量化」的侷限

全文精讀確認：其 dense retrieval encoder（Contriever/ColBERTv2）**只對 noun phrase 節點**算 embedding，用於建立 synonymy 邊（"we use M to add the extra set of synonymy relations E′...when the cosine similarity between two entity representations in N is above a threshold τ"，τ=0.8）；關係邊本身（如 "born in"、"located in"）全程只是純文字標籤、從未被向量化，查詢時靠問題實體匹配種子節點後跑 Personalized PageRank 傳播分數。完全未做事實/三元組層級向量化，佐證「只靠實體向量與 BFS/PPR 傳播，對語意相近但字面不同的事實召回較弱」這個本節動機。

**全文精讀新增細節**：其錯誤分析（Appendix F）顯示近半數錯誤來自 NER 遺漏（entity-centric 設計犧牲了 context 訊號），從反面實證佐證上述動機，不只是理論推測。

### 4. G-Retriever——PCST 子圖最佳化，未來延伸方向且有實證支持

全文精讀確認 §5.1-5.3：對 node 與 edge **各自獨立**用 Sentence-BERT 算 embedding（`z_n=LM(x_n)`、`z_e=LM(x_e)`），k-NN 相似度篩選候選後，用 Prize-Collecting Steiner Tree（PCST）最佳化把 node prize 與 edge prize 一併納入，選出「總 prize 減邊成本」最大的連通子圖，而非單純排序取 top-K。

**全文精讀新增關鍵佐證**：論文 Appendix D.4 直接拿自己與 KAPING 做實證比較（WebQSP 準確率：G-Retriever 70.49 vs. KAPING 60.81），並指出 KAPING 的檢索 *"is chosen in isolation from the graph"*。這證實本節「若未來要從扁平相似度排序升級為 PCST 子圖最佳化」不只是理論可能，而是已有實證支持的漸進路徑；同時 G-Retriever 與 LightRAG 從不同路徑都得出「edge 應獨立向量化」的結論，兩篇互相印證，強化本節 `Fact` 節點設計的正當性。**誠實聲明**：目前本設計採用的是 KAPING 式扁平檢索，尚未採用 PCST，僅記錄為第五章消融實驗或未來工作的候選方向，非本次已實作範圍。

## 整體查證結論

四篇文獻構成一條清晰的方法論光譜：KAPING（直接方法論來源）→ LightRAG（生產級驗證）→ HippoRAG（對照組，侷限性實證）→ G-Retriever（未來延伸方向，且有直接實證比較）。全文查證後四篇描述皆無錯誤需訂正，但發現本節現行設計與 KAPING 共享同一個已知侷限（扁平檢索、未利用圖結構），已誠實記錄於 `03_系統設計與方法論.md` 3.1.4 §a。

## 尚未查證/待辦

- [ ] G-Retriever 的 PCST 演算法若未來要正式採用為本論文機制，需進一步查證其計算複雜度與本論文圖規模（單一 KG 的節點/邊數量級）是否匹配，本次僅確認機制存在與其與 KAPING 的比較數據。
- [ ] KAPING、G-Retriever 皆針對 Wikidata/Freebase 這類已有 canonical 三元組的 KG 做實驗，本論文的三元組來自 LLM 抽取後累積、可能有雜訊，兩者的實驗前提是否完全可比，留待第五章實證評估時一併討論。
