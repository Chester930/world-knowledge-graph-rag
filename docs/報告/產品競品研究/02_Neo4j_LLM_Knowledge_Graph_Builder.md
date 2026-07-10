# Neo4j LLM Knowledge Graph Builder

## 一、定位與背景

Neo4j Labs（Neo4j 官方實驗性專案團隊）推出的開發者/企業向工具，讓使用者無需寫程式即可將非結構化資料（PDF、DOC、TXT、YouTube 影片、網頁等）轉為 Neo4j 知識圖譜。定位是「Neo4j 生態的 GraphRAG 入口工具」，介於純技術函式庫與完整產品之間——提供網頁介面與後端 API，但核心目的是降低 Neo4j GraphRAG 的導入門檻，而非做成獨立商業產品。

## 二、核心技術架構

- **前後端分離**：前端 React（TypeScript 佔 24.9%），後端 Python FastAPI（Python 3.12+），部署可用 Docker Compose（本地）或 Google Cloud Run（雲端）。
- **抽取管線**：基於 **LangChain** 框架適配多種 LLM（OpenAI、Gemini、Llama3、Diffbot、Claude、Qwen 等 11+ 供應商）與資料載入器；FastAPI 提供非同步支援以平行處理多文件上傳與查詢。
- **雙層圖結構**：抽取後同時產生「詞彙圖（Lexical Graph）」——文件與 chunk 節點（含 embedding）——以及「實體圖（Entity Graph）」——節點與關係，兩者都寫入同一個 Neo4j 資料庫並互相連結。
- **社群摘要**：需搭配 Neo4j Graph Data Science（GDS，AuraDS 或自架）啟用，執行社群偵測演算法後，為每個社群樹狀結構生成摘要（Community Summarization），供全局查詢使用。
- **多重檢索模式**：向量搜尋（Vector）、圖-向量混合（Graph-Vector）、純圖檢索（Graph-based / GraphRAG）、全文檢索（Fulltext）、Text2Cypher（LLM 直接生成 Cypher 查詢）——介面上可並行比較不同模式的回答品質。
- **後處理清理**：用 LLM 對抽取後的圖進行清理（去重、修正）。

## 三、關鍵特色功能

- 自訂 Schema：使用者可指定要抽取的實體類型與關係類型，控制圖的結構（對應本專案的 T-Box 概念，但是使用者手動指定而非固定本體）。
- Neo4j Bloom 圖視覺化整合。
- 對話介面內建來源中繼資料追蹤（回答會標示來自哪個 chunk/文件）。
- 逐使用者 Token 用量監控。
- Embedding 模型可選（OpenAI、Gemini、Amazon Titan、Sentence Transformers 等）。
- 2025 年新增：社群摘要、本地/全局檢索器、自訂 prompt 指令；2026 年新增：文件來源的 chunk/entity/community 節點數量細分統計、從 Neo4j Console Preview 匯入圖模型的 Data Importer、Claude 4 Sonnet 正式上線支援。

## 四、開源狀態

- **License**：Apache-2.0（寬鬆授權，可自由參考、修改、商用）。
- **GitHub Star 數**：約 4.7k-4.9k（不同查詢時間點略有差異，數字持續成長中）。
- **活躍度**：1,356+ commits，17+ 次正式 release，最新版 v0.8.6（2026 年 6 月），屬於仍在積極維護的專案，非停滯的實驗品。
- **可參考程度**：Apache-2.0 授權下可直接參考其後端 FastAPI + LangChain 的抽取管線設計、雙層圖結構（Lexical Graph + Entity Graph）的 schema 設計，甚至可以直接借用部分程式碼架構思路（非逐字複製，但架構模式可學習）。

## 五、值得借鏡的技術點（對本專案的優化啟發）

這是目前調查的 8 個競品中，**技術棧與本論文系統最接近**的一個（同樣是 Neo4j + LLM 抽取 + GraphRAG），值得逐項比對：

1. **雙層圖結構（Lexical Graph + Entity Graph）**：本專案目前的知識圖譜主要是實體圖層（SVO 三元組），沒有明確的「文件/chunk 節點」與實體圖分離並顯式關聯。Neo4j Builder 把兩者都建模進圖資料庫、並用邊連結，這讓「回答可追溯到哪個原始 chunk」變成圖遍歷的一部分，而不是額外的中繼資料查詢——**這對本專案 1.1.4 節已主張的「可解釋知識問答」是直接可借鏡的實作模式**。
2. **多重檢索模式並行比較介面**：讓使用者/開發者同時看到 Vector、GraphRAG、Text2Cypher 三種模式對同一問題的回答，是很實用的除錯與評估工具，本專案的實驗設計（論文第五章）可以參考這種「多模式並排比較」的呈現方式。
3. **社群摘要需要顯式啟用 GDS**：這代表 Neo4j 官方也把「全局查詢（社群摘要）」視為可選的進階功能，而非核心必要能力——這可以佐證本專案將「階層式社群摘要全局檢索」（v1 報告方案七）列為次要優先級是合理的產品判斷，不是偷懶。
4. **沒有明確的實體對齊/消歧管線**：查證過程沒找到 Neo4j Builder 有處理「同一實體不同名稱寫法」的機制（entity resolution/disambiguation），這反而是本專案如果已有相關設計（如 `ConceptRepository`）可以強調的差異化優勢，而非本專案的缺口。
5. **後處理 LLM 清理**：用 LLM 對已抽取的圖做二次清理，是簡單但有效的品質提升手段，本專案的 SVO 抽取管線若尚未有這道後處理，值得評估加入。

## 六、與本專案的具體差距或相似點

| 面向 | Neo4j LLM Graph Builder | 本專案 |
|---|---|---|
| 底層資料庫 | Neo4j | Neo4j（相同） |
| 抽取方式 | LLM 開放式抽取（依 schema） | SVO 三元組，封閉 30 種關係類型（更嚴謹但較不彈性） |
| 多知識庫/租戶 | 未見明確多租戶設計 | 本專案明確以此為 RQ1 |
| 全局摘要 | 需另外啟用 GDS 社群偵測 | 尚未實作（v1 報告方案七，未列入正式 RQ） |
| 圖剪枝 | 未見 Hub Node 專門處理機制 | 本專案 RQ4（尚未實作） |
| 開源/授權 | Apache-2.0，公開專案 | 本專案授權待確認 |

## 七、來源

- [github.com/neo4j-labs/llm-graph-builder](https://github.com/neo4j-labs/llm-graph-builder)
- [neo4j.com/labs/genai-ecosystem/llm-graph-builder](https://neo4j.com/labs/genai-ecosystem/llm-graph-builder/)
- [neo4j.com/blog/developer/llm-knowledge-graph-builder-back-end](https://neo4j.com/blog/developer/llm-knowledge-graph-builder-back-end/)
- [neo4j.com/blog/developer/llm-knowledge-graph-builder-release](https://neo4j.com/blog/developer/llm-knowledge-graph-builder-release/)
