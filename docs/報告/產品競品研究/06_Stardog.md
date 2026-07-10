# Stardog

## 一、定位與背景

Stardog 是一套企業級「語意 AI 平台」（Semantic AI Platform），核心是一個原生 RDF 圖資料庫，主打將知識圖譜（Knowledge Graph）與 LLM 融合，鎖定大型企業的資料治理、跨系統資料整合與知識問答場景。與本專案（面向多知識庫、輕量部署）不同，Stardog 定位偏向重量級企業基礎設施。

## 二、核心技術架構

### 本體／Schema 建模方式
Stardog 建立在標準語意網（Semantic Web）技術棧之上，**非自建本體格式**：完整支援 RDF（資料模型）、OWL（本體語言，用於定義類別、屬性、邏輯公理）、SPARQL（查詢語言，含 SPARQL*）、SHACL（資料形狀驗證）。這代表 Stardog 的本體是業界標準格式，可與其他語意網工具互通，而非像本專案的 T-Box 是專案內部自訂的 19 實體/31 關係封閉集合。

### 推理引擎（Inference Engine）機制
Stardog 的推理不只是本體公理推導，而是分層的：
1. **RDFS/OWL 推理**：根據本體定義的類別階層與屬性公理，自動推導出資料中未明確寫出但邏輯上成立的事實。
2. **SWRL（Semantic Web Rule Language）規則**：可額外定義 IF-THEN 形式的規則，補足 OWL 描述邏輯表達力不足之處。
3. **使用者自訂規則（User-defined Rules）**：以 SPARQL 語法撰寫的 Datalog 風格規則——IF 子句比對資料中的樣式，比對成功則 THEN 子句觸發、推導出新事實並寫回圖譜。
4. **推理設定（Reasoning Types）**：可組合 RDFS、QL、RL、EL 等不同表達力/效能權衡的公理集合，加上 SWRL 規則（統稱 SL 設定）。

這與本專案目前的封閉式關係抽取（LLM 直接抽取 30 種預定義關係，無推理層）是本質不同的技術路徑：Stardog 是「顯式資料 + 規則推導出隱式資料」，本專案是「LLM 直接抽取顯式三元組，無額外邏輯推導層」。

### 資料虛擬化（Graph Data Virtualization）
Stardog 可直接查詢外部資料來源（資料湖、資料倉儲、其他資料庫）而不需要先搬移或複製資料，官方宣稱效能可達 57 倍價格/效能比提升（此數字未進一步查證細節，來源為官方行銷頁面，需保守看待）。

## 三、關鍵特色功能（詳細）

- **Voicebox（自然語言查詢層）**：機制是「翻譯」而非「生成」——LLM 先辨識使用者自然語言問題中的核心概念，透過向量資料庫比對到知識圖譜中實際存在的概念，再將問題轉譯為 SPARQL 查詢，直接對圖譜執行查詢取得答案。因為答案是查詢結果而非 LLM 生成內容，官方宣稱可消除幻覺風險。
- **來源追蹤**：Voicebox 會標記每則資訊是來自 RAG 檢索、程式執行、外部 LLM 生成、還是直接查詢知識圖譜取得，區分「有依據的事實」與「LLM 生成內容」。
- **機器學習整合**：內建相似度搜尋與預測分析（分類、迴歸）。
- **企業規模**：宣稱可擴展至約 1 兆個三元組，支援 Kubernetes 部署，ACID 相容。

## 四、開源狀態

**Stardog 本身不是完全開源專案**，是商業產品，但提供 **Stardog Free（社群版）**——官方說明為「免費授權」，可在無商業限制下探索使用（確切的免費層級功能/資料量上限未在本次查證中確認，需要之後直接查閱其定價頁面 stardog.com/pricing 核實）。核心技術棧（RDF/OWL/SPARQL/SHACL）本身是 W3C 開放標準，但 Stardog 的具體實作（推理引擎、Voicebox、虛擬化引擎）是閉源商業軟體。

## 五、值得借鏡的技術點

本專案目前的 T-Box 本體設計（19 實體/31 關係）是一個**扁平封閉集合**，SVO 抽取後沒有推理層——抽出什麼就是什麼，無法從已知事實推導出新的隱式事實。Stardog 的分層推理架構提供幾個可能的借鏡方向：

1. **使用者自訂規則（最容易落地）**：不需要引入完整 OWL 推理，可以先實作類似 Stardog「使用者自訂規則」的簡化版——用簡單的 IF-THEN 樣式規則（例如「A REGULATES B 且 B PART_OF C ⟹ A INDIRECTLY_REGULATES C」），在 BFS 圖遍歷後做一層輕量規則推導，補充圖譜的隱式連結，不需要引入完整語意網技術棧。
2. **本體分層的長期方向**：若本專案的 T-Box 未來需要更嚴謹的邏輯一致性驗證，可以參考 OWL 的類別階層與屬性公理設計方式（例如定義關係之間的傳遞性、互斥性），而不用真的遷移到 RDF/OWL 技術棧。
3. **來源追蹤機制**：Voicebox 標記「答案來自查詢結果 vs LLM 生成」的做法，跟本專案 1.1.4 已經在做的「可追溯推理路徑」目標方向一致，可以參考其分類粒度（RAG / 程式執行 / 外部 LLM / 直接查詢四種來源類型）設計本專案的答案溯源標記系統。

## 六、與本專案的具體差距

- **推理能力**：Stardog 有正式的邏輯推理層，本專案沒有——本專案的「推理」目前指的是圖遍歷（BFS 找路徑），不是邏輯推導出新事實，兩者是不同概念，論文寫作時需注意不要混淆這兩種「推理」的用詞。
- **標準化程度**：Stardog 用開放標準（RDF/OWL/SPARQL），本專案用自訂 schema，換取的是本專案更輕量、更容易客製化，但犧牲了與其他語意網工具的互通性——這是一個值得在論文範圍限制（1.4 節）中明確聲明的設計取捨。
- **規模與部署重量級程度差異大**，不是同一量級的直接競品，比較時應強調「技術路徑參考」而非「市場定位競爭」。

## 七、來源

- [stardog.com/platform](https://www.stardog.com/platform/)
- [stardog.com/pricing](https://www.stardog.com/pricing/)
- [docs.stardog.com/inference-engine](https://docs.stardog.com/inference-engine/)
- [docs.stardog.com/inference-engine/user-defined-rules](https://docs.stardog.com/inference-engine/user-defined-rules)
- [docs.stardog.com/voicebox](https://docs.stardog.com/voicebox/)
- [stardog.com/blog/stardog-voicebox-faq](https://www.stardog.com/blog/stardog-voicebox-faq-how-llm-generative-ai-and-knowledge-graphs-are-the-future-of-data-management/)
- [venturebeat.com — Stardog launches Voicebox](https://venturebeat.com/ai/stardog-launches-voicebox-an-llm-powered-layer-to-query-enterprise-data)
