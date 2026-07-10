# WhyHow.ai

## 一、定位與背景

WhyHow.ai 是一家專注於「RAG 原生知識圖譜」（RAG-native Knowledge Graphs）的新創，主張純向量 RAG 缺乏結構化推理能力，而傳統知識圖譜建構門檻高、難以自動化，因此提供工具鏈讓開發者能以**受控（controlled）而非完全開放（open-ended）**的方式，將非結構化資料自動轉換為知識圖譜，用於強化 RAG 系統的檢索精確度。

產品線分兩層：
- **`whyhow` SDK**（Python 用戶端函式庫）——**已標記為 deprecated（棄用）**，官方已將重心轉移到下方的 Studio。
- **Knowledge Graph Studio**（後端 API 服務 + 雲端託管 UI）——目前主力產品，`whyhow` SDK 是呼叫這個服務的用戶端。

## 二、核心技術架構

### Schema-controlled 建圖流程
官方 README 描述的抽取管線為：**本體定義（ontology definition）→ 實體/關係抽取（entity/relationship extraction）→ 三元組建構（triple construction）→ 依定義好的樣式生成圖譜（graph generation）**。核心主張是「先定義好要抽取什麼，再抽取」，而非開放式、無約束地讓 LLM 自由決定抽取什麼實體與關係。

### 三種建圖模式
1. **Schema-Based（結構化 schema 模式）**：使用者提供 JSON schema，明確定義實體、關係與抽取樣式；適用於圖結構必須保持一致、文件格式已知的場景。
2. **Seed-Question（種子問題模式）**：開發者提供代表資訊需求的自然語言問題，系統據此建立一套引導抽取方向的本體（ontology），適用於需求尚不明確的探索型場景。
3. **CSV-Based（結構化資料模式）**：使用者提供含（可選）schema 的表格資料，系統從欄位標題與數值直接抽取實體與關係，適用於本來就已結構化的資料。

### 技術棧
- 後端：Python（FastAPI/Uvicorn）
- 資料庫：MongoDB Atlas（NoSQL，官方註明「資料庫無關」架構，目前實作為 MongoDB）
- LLM/Embedding：OpenAI API（SDK 舊版另支援 Azure OpenAI、Pinecone 向量儲存、Neo4j 圖資料庫）
- 部署：提供 Docker 支援

## 三、關鍵特色功能

- **命名空間（Namespace）隔離**：以 namespace 組織不同的 KG 專案，作為輕量的多專案／多租戶隔離機制。
- **規則式實體解析（Rule-based entity resolution）**：Studio 版本強調規則式而非純統計式的實體對齊。
- **模組化資料攝取（Modular data ingestion）**：支援結構化與非結構化資料混合輸入。
- **API-first 設計**：所有功能皆可透過 REST API 操作，SDK 只是其中一種用戶端封裝。
- 雲端託管版本另提供圖形化 UI（whyhow.ai）。

## 四、開源狀態

| 項目 | `whyhow-ai/whyhow`（SDK，已棄用） | `whyhow-ai/knowledge-graph-studio`（主力產品） |
|---|---|---|
| License | MIT | MIT |
| Stars | 127 | 929 |
| Forks | 23 | 107 |
| 語言 | Python 100% | Python 99.4% |
| 活躍度 | 已停止維護，最後版本 v0.0.7（2024-06-02） | 活躍（main 分支 38 次 commit，持續開發） |
| 商業化邊界 | 純開源 | 開源後端 + 商業雲端託管 UI（whyhow.ai） |

**開源程度判斷**：核心後端服務（Knowledge Graph Studio）本身是 MIT 授權、完全開源可自架，商業模式建立在「雲端託管版」而非閉源核心——這是常見的 open-core 模式，值得注意的是他們連 UI 都選擇開源（而非只開源 API），比多數 open-core 專案更開放。

## 五、值得借鏡的技術點

本專案目前是**封閉式 30 種語意關係類型**的 schema-controlled SVO 抽取（見論文 1.2 節 RQ2），跟 WhyHow 的「Schema-Based 模式」理念高度相似，但有幾個具體差異值得參考：

1. **本專案目前只有一種抽取模式（固定 schema），WhyHow 提供三種模式並存**——特別是「Seed-Question 模式」值得借鏡：讓使用者用自然語言描述想問的問題，系統據此動態調整本體/抽取重點，而不是永遠套用同一套固定的 30 種關係類型。這對「使用者不確定自己需要哪些關係類型」的冷啟動場景會更友善，可以作為本專案封閉式抽取之外的一個**互補模式**，而非取代。
2. **Namespace 隔離機制**——WhyHow 用 namespace 做輕量多專案隔離，這跟本專案 1.1.4 節「多知識庫管理」的設計目標方向一致，可以參考其 namespace 粒度設計（是否比本專案目前規劃的知識庫層級更細）。
3. **Open-core 商業模式**——WhyHow 連 UI 都開源、只靠託管服務收費，這個開源策略若本專案未來要走開源路線，是一個可行的參考範本（比只開源 API/SDK 更能建立社群信任）。
4. **反面教材**：SDK 版本已棄用、轉向 Studio，顯示「純 SDK/函式庫」形式的知識圖譜工具，商業與維護動能不如「服務化（API + UI）」形式——這點對本專案「要不要做成 SDK 還是完整服務」的產品決策有參考價值。

## 六、與本專案的具體差距或相似點

| 面向 | WhyHow.ai | 本專案 |
|---|---|---|
| Schema 控制 | JSON schema 使用者自訂，彈性高 | 固定 30 種關係類型（T-Box），一致性高但彈性低 |
| 建圖模式數量 | 3 種並存 | 1 種（固定抽取） |
| 多租戶/命名空間 | 有（namespace） | 規劃中，未實作（見 1.1.4） |
| 圖資料庫 | 原設計含 Neo4j 選項，現主力用 MongoDB | Neo4j（原生圖資料庫，關聯查詢效能理論上優於 NoSQL 存 graph） |
| 開源狀態 | 完全開源（MIT），open-core 商業化 | 尚未公開（本論文專案本身） |

## 七、來源

- SDK 倉庫：https://github.com/whyhow-ai/whyhow
- Studio 倉庫：https://github.com/whyhow-ai/knowledge-graph-studio
- 相關工具 Knowledge Table：https://github.com/whyhow-ai/knowledge-table
- 官方部落格（案例與技術文章）：https://medium.com/enterprise-rag
