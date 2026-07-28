## 完成兩題後：開始介紹本專案

### 介紹策略

前面兩題已經回答：

```text
為什麼不能只用 RAG？
-> 因為需要可驗證的關係結構。

為什麼要驗證三元組？
-> 因為 GraphRAG 的可信度取決於圖上的邊是否正確。
```

所以開始介紹專案時，不需要立刻深入程式架構。先用緒論方式說明即可：

```text
研究背景
-> 問題缺口
-> 研究目標
-> RQ
-> 專案如何作為研究載體
```

### 專案一句話定位

World Knowledge Graph RAG 是一套以論文研究為目標的 GraphRAG 系統實作，核心目標是驗證「SVO 知識圖譜 + KG-BFS 圖遍歷 + 多知識庫路由」是否能在多跳問答、可追溯性與查詢效率上補足當代 RAG 與 2024 GraphRAG 的不足。

### 研究背景

本研究的背景可以從三個層次說明：

1. **LLM 的限制**：大型語言模型本身有靜態知識、幻覺與推理路徑不透明的問題。
2. **RAG 的補強與邊界**：RAG 能把外部文件引入回答流程，但主要仍以文字 chunk 為檢索單位，對明確關係、多跳路徑與關係層級可追溯仍有不足。
3. **GraphRAG 的機會與缺陷**：GraphRAG 嘗試結合 RAG 與知識圖譜，但 2024 代表性架構仍有建圖成本高、LLM 建圖品質不穩、偏向全局摘要、Hub Node 路徑爆炸與評估困難等問題。

簡報講法：

> 因此我的研究不是單純做一個聊天系統，而是要驗證：當我們把文件轉成可追溯的三元組知識圖譜後，是否能讓 RAG 在多跳推理與可解釋性上更可靠。

### 研究缺口

依緒論脈絡，本專案主要承接以下缺口：

| 缺口 | 說明 | 對應專案方向 |
|------|------|--------------|
| 多跳推理不穩 | 當答案需要串接多個片段，純文字 RAG 容易漏掉中間證據或發生 retrieval drift。 | KG-BFS 圖遍歷 |
| 多知識庫可擴展性不足 | 多個 KG 並存時，若每次都查全部資料，延遲與成本會上升。 | ConceptNode 輕量路由 |
| 幻覺與來源不明 | LLM 回答可能流暢但缺乏明確依據。 | 自我精煉與來源回補 |
| 關係語意不一致 | 開放式抽取容易把相同語意寫成不同關係。 | 受控關係詞彙與 SVO 驗證 |
| 實體重複與指代問題 | 同一實體可能被不同名稱表示，造成節點分裂。 | 實體別名與指代消解 |
| Hub Node 路徑爆炸 | 高連結節點會讓 BFS 找到太多無關路徑。 | 向量引導剪枝 |

### 研究目標

本研究的目標不是泛稱「GraphRAG 比 RAG 好」，而是要界定它在特定任務上的成立條件：

```text
目標一：驗證 KG-BFS 在多跳推理任務上是否優於當代強化版 RAG。
目標二：驗證多知識庫場景下，輕量路由是否能降低延遲並維持準確率。
目標三：驗證自我精煉與來源回補是否能降低幻覺並提升可追溯性。
目標四：延伸評估三元組關係標準化、實體別名消解、時序更新與 Hub Node 剪枝。
```

簡報講法：

> 這個研究的重點不是宣稱 GraphRAG 全面勝過 RAG，而是找出它在哪些問題類型上真的有用、代價是什麼、哪些元件會影響結果。

### 研究問題 RQ

目前緒論採用「一個核心貢獻、六個研究問題」的架構，其中 RQ1–RQ3 是核心承諾，RQ4–RQ6 是預留/延伸研究問題。

| RQ | 研究問題 | 對應研究目標 | 報告時的簡化說法 |
|----|----------|--------------|------------------|
| RQ1 | KG-BFS 相較當代強化版 RAG，在多跳推理任務上是否仍有顯著優勢？優勢在哪類查詢上最明顯？ | 驗證 GraphRAG 使用前提 | 圖結構到底在哪些問題上真的比 RAG 有幫助？ |
| RQ2 | 多知識圖譜場景下，「輕量路由層 + BFS 知識層」能否在準確率不顯著下降的前提下改善查詢延遲與可擴展性？ | 驗證多 KG 路由效益 | 多個知識庫時，先路由再查圖是否比較有效？ |
| RQ3 | 相較單輪 BFS 檢索，低信心觸發的自我精煉迴圈能否降低幻覺率？延遲與 token 成本代價為何？ | 驗證可靠性與可追溯性 | 答案不確定時，回補原文再回答是否更可靠？ |
| RQ4 | 受控關係詞彙標準化與實體指代/別名消解，對語意一致性、多跳推理正確率與可追溯性有何影響？ | 驗證三元組品質 | 三元組的關係詞與實體名稱整理乾淨後，圖會不會更好用？ |
| RQ5 | 在事實更新場景中，時序保留策略相較直接覆蓋，對時態查詢與多跳推理有何影響？ | 驗證知識時效性 | 舊事實要刪掉，還是保留成歷史？ |
| RQ6 | 相較 naive 硬截斷，查詢引導的向量剪枝能否在 Hub Node 場景下提升相關性並控制延遲？ | 驗證圖遍歷效率 | 遇到超大節點時，怎麼避免 BFS 爆炸？ |

### RQ 理論基礎、外部專案實踐基礎與本專案落點

> 簡報講 RQ 時，每個 RQ 放三種資訊：一篇可信任論文作為**理論基礎**，一個外部可信專案/官方實作作為**實踐基礎**，最後才列本專案的**對應落點**。本專案程式不是來源，而是說明「我如何把外部理論與實踐模式落到自己的系統」。

| RQ | 可信任論文：理論基礎 | 外部可信專案：實踐基礎 | 本專案對應落點 |
|----|----------------------|--------------------------|----------------|
| RQ1 | [Han et al. (2025), *RAG vs. GraphRAG*](https://arxiv.org/abs/2502.11371) | [Neo4j GraphRAG Python](https://github.com/neo4j/neo4j-graphrag-python) | [緒論 RQ1](../論文/01_緒論.md)；[SVO/BFS service](../../services/svo_service.py)；[SVO tests](../../tests/services/test_svo_service.py) |
| RQ2 | [Peng et al. (2026), *Graph Retrieval-Augmented Generation: A Survey*](https://doi.org/10.1145/3777378) | [LlamaIndex RouterQueryEngine](https://docs.llamaindex.ai/en/v0.10.19/examples/query_engine/RouterQueryEngine.html)；[RouterRetriever](https://docs.llamaindex.ai/en/stable/api_reference/retrievers/router/) | [緒論 RQ2](../論文/01_緒論.md)；[ConceptNode service](../../services/concept_engine.py)；[concept repo](../../repositories/concept_repo.py)；[classify service](../../services/classify_service.py)；[classify tests](../../tests/services/test_classify_service.py) |
| RQ3 | [Asai et al. (2023), *Self-RAG*](https://doi.org/10.48550/arXiv.2310.11511) | [Self-RAG official implementation](https://github.com/AkariAsai/self-rag) | [緒論 RQ3](../論文/01_緒論.md)；[agent router](../../routers/agent.py)；[架構設計紀錄：實驗可追溯性](../ARCHITECTURE.md) |
| RQ4 | [Mihindukulasooriya et al. (2023), *Text2KGBench*](https://arxiv.org/abs/2308.02357) | [Stanford OpenIE](https://www-nlp.stanford.edu/software/openie.shtml)；[Neo4j GraphRAG KG Builder Pipeline](https://neo4j.com/developer/genai-ecosystem/graphrag-python/) | [緒論 RQ4](../論文/01_緒論.md)；[SVO service](../../services/svo_service.py)；[entity registry](../../services/entity_registry_service.py)；[SVO preprocessing](../../services/svo_preprocessing_service.py)；[SVO tests](../../tests/services/test_svo_service.py) |
| RQ5 | [Li et al. (2025), *T-GRAG*](https://doi.org/10.1145/3746027.3755628) | [Graphiti temporal knowledge graph](https://github.com/getzep/graphiti)；[Graphiti docs](https://help.getzep.com/graphiti/getting-started/overview) | [緒論 RQ5](../論文/01_緒論.md)；[架構設計紀錄：時序管理](../ARCHITECTURE.md) |
| RQ6 | [Chen et al. (2025/2026), *PathRAG*](https://arxiv.org/abs/2502.14902) | [BUPT-GAMMA PathRAG implementation](https://github.com/BUPT-GAMMA/PathRAG) | [緒論 RQ6](../論文/01_緒論.md)；[SVO/BFS service](../../services/svo_service.py) |

### RQ2 外部實踐基礎與本專案落點

RQ2 的外部實踐基礎建議使用 LlamaIndex 的 RouterQueryEngine / RouterRetriever：它們不是知識圖譜產品，而是可信任開源框架中「從多個候選 query engines / retrievers 選擇合適目標」的路由實作。這可以支持本專案的 ConceptNode 路由設計。

| 類型 | 位置 | 對 RQ2 的作用 |
|------|------|---------------|
| 外部可信專案 | [LlamaIndex RouterQueryEngine](https://docs.llamaindex.ai/en/v0.10.19/examples/query_engine/RouterQueryEngine.html) | 展示如何在多個候選 query engines 中依查詢選擇合適引擎，支撐「先路由再檢索」的實踐模式。 |
| 外部可信專案 | [LlamaIndex RouterRetriever](https://docs.llamaindex.ai/en/stable/api_reference/retrievers/router/) | 展示如何在多個候選 retrievers 中選擇一個或多個 retriever，支撐多知識庫/多索引檢索前的輕量路由。 |
| 本專案落點 | [緒論 RQ2](../論文/01_緒論.md) | 定義研究問題：多知識圖譜場景下，「輕量路由層 + BFS 知識層」能否改善延遲與可擴展性。 |
| 本專案落點 | [架構設計紀錄：命名空間隔離](../ARCHITECTURE.md) | 明確決策使用 `kg_id` / namespace 做多知識庫隔離，這是 RQ2 的資料隔離基礎。 |
| 本專案落點 | [models/knowledge_graph.py](../../models/knowledge_graph.py) | 定義 `kg_id`、`matched_kg_id`、`assignment_history`、`ClassifyResult` 等多 KG 路由/歸屬資料模型。 |
| 本專案落點 | [repositories/kg_repo.py](../../repositories/kg_repo.py) | KG CRUD 與 `kg_id` 隔離；註解明確說明節點/邊以 `kg_id` 屬性區隔。 |
| 本專案落點 | [repositories/concept_repo.py](../../repositories/concept_repo.py) | ConceptNode 路由層存取，建立 `concept_q_vector` 向量索引，支援 query vector 對 ConceptNode 粗篩。 |
| 本專案落點 | [services/concept_engine.py](../../services/concept_engine.py) | ConceptNode 路由層計算，對應「問題概念提取 -> KG 路由」。 |
| 本專案落點 | [services/classify_service.py](../../services/classify_service.py) | 文件進入知識庫前的分類與自動歸屬，使用 KG prototype / cosine similarity；是多 KG 管理的 ingestion-side 路由。 |
| 本專案落點 | [services/cluster_service.py](../../services/cluster_service.py) | 對未分配文件池做 HDBSCAN/UMAP 分群與 KG 命名建議，支撐「多知識庫自動建立/擴展」。 |
| 本專案落點 | [services/document_record_service.py](../../services/document_record_service.py) | 記錄文件歸屬歷史與抽取進度，支撐文件被分配到不同 KG 後仍可追蹤。 |
| 本專案落點 | [routers/staging.py](../../routers/staging.py) | 暫存區 API：`/staging/classify`、`/staging/{filename}/assign`、`/staging/cluster/analyze`、`/staging/cluster/confirm`，把分類/分群/人工指派流程接到 API。 |
| 本專案落點 | [tests/services/test_classify_service.py](../../tests/services/test_classify_service.py) | 驗證文件分類、自動歸屬、prototype 更新、rollback 等行為，支撐 RQ2 程式設計可測試。 |
| 本專案落點 | [tests/services/test_cluster_service.py](../../tests/services/test_cluster_service.py) | 驗證分群與命名輸入篩選，支撐多 KG 自動建立流程。 |
| 本專案落點 | [tests/services/test_document_record_service.py](../../tests/services/test_document_record_service.py) | 驗證 assignment history 與文件歸屬紀錄，支撐多 KG 歸屬可追溯。 |
| 本專案落點 | [tests/repositories/test_kg_repo.py](../../tests/repositories/test_kg_repo.py) | 驗證 KG repository 行為，支撐 `kg_id` 隔離與 KG CRUD。 |

簡報講法：

> RQ2 的實踐基礎可以參考 LlamaIndex Router 的模式：先根據 query 在多個候選引擎或 retriever 中選擇目標，再進入實際檢索。本專案把這個路由概念落到多 KG 場景，用 ConceptNode、`kg_id`、文件分類、分群與測試來支撐自己的實作。

### 本次報告建議聚焦

明天報告不需要把六個 RQ 都講到同等深度。建議這樣分配：

| 層級 | RQ | 報告深度 |
|------|----|----------|
| 主線 | RQ1、RQ2、RQ3 | 需要清楚說明，這是核心研究目標。 |
| 鋪墊 | RQ4 | 和前面三元組驗證直接相關，要講，但可說是延伸/預留。 |
| 未來工作 | RQ5、RQ6 | 簡短帶過，說明是後續擴充方向。 |

簡報講法：

> 因為碩士論文工作量有限，目前核心承諾放在 RQ1 到 RQ3；RQ4 到 RQ6 是延伸研究問題。其中 RQ4 跟今天前面講的三元組驗證直接相關，所以我會特別說明它如何支撐圖譜品質。

### 專案作為研究載體

本專案不是單純 demo，而是用來支撐上述 RQ 的實作載體：

- `SVO 抽取與驗證`：支撐 RQ4，也支撐整個圖譜品質。
- `Neo4j 知識圖譜`：保存實體、關係與來源，支撐 RQ1 的 KG-BFS。
- `ConceptNode 路由`：支撐 RQ2 的多知識庫路由。
- `BFS 圖遍歷`：支撐 RQ1 的多跳推理檢索。
- `自我精煉迴圈`：支撐 RQ3 的幻覺降低與來源回補。
- `實驗紀錄與可追溯性規範`：支撐第五章實驗設計。

### 目前專案狀態

報告時要誠實說明：本專案目前是 v2 重構與論文實作載體，不是已完成產品。

- FastAPI 後端骨架已建立。
- `routers -> services -> repositories` 分層已接好。
- Neo4j 連線、設定、provider 工廠已有基礎。
- 前端已有基本聊天室、KG 側欄、暫存區與 API 串接骨架。
- 核心演算法仍在重整與逐步實作中，例如 SVO 抽取、ConceptNode 路由、BFS 圖遍歷與自我精煉。

報告時的定位句：

> 目前專案的價值，不是宣稱已經完成完整產品，而是把研究問題落到可實驗、可比較、可追溯的系統架構上。
