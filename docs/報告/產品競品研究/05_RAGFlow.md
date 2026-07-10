# RAGFlow

## 一、定位與背景

RAGFlow（[github.com/infiniflow/ragflow](https://github.com/infiniflow/ragflow)）是由中國團隊 InfiniFlow 開發的開源 RAG 引擎，訴求是「基於深度文件理解的 RAG」，將 RAG 與 Agent 能力融合，作為 LLM 的「context 層」。專案始於 2023 年 12 月，主要開發語言為 Go（後端）搭配 Python（文件解析/模型層），持續高頻更新至今（2026 年 7 月仍在活躍發版）。

## 二、核心技術架構

**文件理解管線**：核心賣點是「Deep Document Understanding」——支援 Word、投影片、Excel、純文字、圖片、掃描件、結構化資料、網頁等格式，2025 年 10 月起新增 MinerU 與 Docling 作為文件解析方法（MinerU 正是智慧知識庫 v1 對標文件中提到的「世界級高精度 PDF 提取引擎」，兩個專案都盯上了同一個開源解析工具，可視為業界共識）。

**知識圖譜建構（GraphRAG 功能，v0.9 起）**：
- 屬於**選配**的前處理步驟，在語意分塊（chunking）之後、索引之前執行，抽取實體（人物、組織、概念、事件）與其關係
- 提供兩種抽取模式：「General」（沿用 Microsoft GraphRAG 的 prompt 設計）與「Light」（沿用 LightRAG 的 prompt 設計，為預設模式，運算成本較低）
- **內建實體去重**：官方文件明確指出原始 GraphRAG 論文的做法會把「2024」與「Year 2024」、「IT」與「Information Technology」當成不同實體，RAGFlow 額外加了去重步驟解決這個問題——這是一個具體、可驗證的工程改進點
- 查詢時提供兩種模式：**Global Search**（利用社群摘要回答全局性問題，對應 Microsoft GraphRAG 的社群摘要檢索）與 **Local Search**（從實體向外擴散鄰居節點，回答特定實體問題，對應本專案的 BFS 圖遍歷路線）

**Agent 整合**：以「converged context engine」+ 預建 Agent 模板為核心，2025-2026 陸續加入 agentic workflow、MCP（Model Context Protocol）支援、Python/JavaScript 程式碼執行元件、Agent 記憶（2025-12-26 上線）。

## 三、關鍵特色功能

- 多格式文件解析（含掃描件），MinerU/Docling 雙引擎可選
- 選配的 GraphRAG（可開關，非強制），General/Light 兩種抽取策略可調
- 實體去重機制（解決同義詞重複建點問題）
- Global/Local 雙模式查詢（呼應 Microsoft GraphRAG 論文的檢索範式）
- 多聊天通路整合（Feishu、Discord、Telegram、Line 等）
- 多資料來源同步（Confluence、S3、Notion、Discord、Google Drive）
- Agent 記憶、程式碼執行元件、MCP 協定支援

## 四、開源狀態

- **License**：Apache License 2.0（寬鬆授權，商用友善）
- **GitHub Star 數**：84,718（截至查證時）
- **Open Issues**：2,322（社群規模大、活躍度高的訊號）
- **建立時間**：2023-12-12，持續高頻更新至 2026-07（查證當下仍在更新）
- 結論：這是本次競品研究中**規模最大、最活躍的開源專案**，Apache 2.0 授權下可直接參考甚至复用其部分設計思路。

## 五、值得借鏡的技術點

1. **實體去重機制**——本專案目前 SVO 抽取若也存在「同義詞被當成不同節點」的問題（例如「勞基法」vs「勞動基準法」），RAGFlow 的去重步驟設計值得直接參考，這是一個具體、低成本、高投資報酬率的優化點。
2. **GraphRAG 設為選配而非強制**——RAGFlow 把知識圖譜建構做成「可開關」的選配步驟，這正好呼應本專案 1.1.3 節已識別的「建圖冷啟動成本過高」缺口（v1 對標文件的頭號弱點）：如果知識圖譜建構本來就是選配，就能對應到「向量先行、圖譜非同步/選配建構」的雙軌設計，不用每次都全量抽取。
3. **Global/Local 雙模式查詢**——直接對應本專案目前只有「BFS 局部遍歷（Local）」、缺乏「社群摘要全局查詢（Global）」的缺口，RAGFlow 已經是這個模式的成熟工業實作案例，架構可參考。
4. **MinerU/Docling 雙引擎解析**——若本專案要解決「多模態表格解析缺失」的缺口，MinerU 是業界公認的高精度開源方案，RAGFlow 已驗證其工業可用性，降低導入風險。

## 六、與本專案的具體差距或相似點

| 面向 | RAGFlow | 本專案 |
|---|---|---|
| 知識圖譜建構 | 選配、General/Light 雙策略、有去重 | 全量必做（SVO 抽取）、封閉式 30 種關係類型、無明確去重機制 |
| 查詢模式 | Global（社群摘要）+ Local（鄰居擴散） | 僅 Local（BFS 圖遍歷），Global 尚未實作 |
| 文件解析 | MinerU/Docling 多模態解析 | pypdf/pdfminer/PaddleOCR 純文字管線，無表格/版面還原 |
| 多租戶/多知識庫 | 未特別強調此定位 | 本專案明確主打的核心賣點（1.1.4） |
| 授權/開源程度 | 完全開源（Apache 2.0） | 本專案為學術論文實作載體，開源與否未定 |

## 七、來源

- [github.com/infiniflow/ragflow](https://github.com/infiniflow/ragflow)（GitHub API 查證：84,718 stars, Apache-2.0, 建立於 2023-12-12）
- [raw README](https://raw.githubusercontent.com/infiniflow/ragflow/main/README.md)
- [ragflow.io/docs/construct_knowledge_graph](https://ragflow.io/docs/construct_knowledge_graph)
- [ragflow.io/blog/ragflow-support-graphrag](https://ragflow.io/blog/ragflow-support-graphrag)
- [milvus.io/ai-quick-reference/what-is-ragflow-graphrag-feature](https://milvus.io/ai-quick-reference/what-is-ragflow-graphrag-feature)
- [zilliz.com/ai-faq/how-does-ragflow-build-knowledge-graphs](https://zilliz.com/ai-faq/how-does-ragflow-build-knowledge-graphs)
