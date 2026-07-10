# Zep (Graphiti)

## 一、定位與背景

Zep 是一個面向 AI Agent 的長期記憶層服務（memory layer），核心引擎為 **Graphiti**——一個具時間感知能力（temporally-aware）的知識圖譜引擎。學術論文為 Rasmussen et al. (2025)《Zep: A Temporal Knowledge Graph Architecture for Agent Memory》，arXiv:2501.13956。Zep 定位為企業級、開箱即用（turnkey）的記憶平台；Graphiti 則是其底層開源核心，可獨立使用、自行架設與維運。

## 二、核心技術架構

**雙時態模型（Bi-Temporal Model）**：每一條事實（graph edge）維護一組「有效期間」（validity window），標記該事實何時成立、何時被取代——分別對應「事實何時進入系統」與「事實何時失效」兩個時間維度，讓系統可以查詢「現在為真的是什麼」與「過去曾經為真的是什麼」，而不需要刪除舊資料。

**矛盾處理**：當新資訊與既有事實衝突時，Graphiti**不依賴 LLM 自行判斷取捨**，而是採用自動事實失效機制（automatic fact invalidation）——新事實使舊事實失效，但保留完整的時序歷史與來源譜系（從衍生事實回溯到原始 episode/資料來源）。

**資料庫後端**：支援多種圖資料庫——Neo4j（主要，預設資料庫名 `neo4j`）、FalkorDB（含適合 Python 3.12+ 的內嵌版 FalkorDB Lite）、Amazon Neptune（搭配 OpenSearch Serverless 做全文檢索）；Kuzu 後端已棄用（上游專案停止維護）。

**增量建構**：新資料進來即時整合，不需批次重新運算，圖譜即時演化。

**混合檢索**：結合語意嵌入、BM25 關鍵字搜尋與圖遍歷，達成次秒級查詢延遲，不依賴 LLM 摘要生成檢索結果。

**Ontology 設計**：開發者可透過 Pydantic 模型預先定義實體/邊的型別（schema-controlled），也可以讓結構從資料模式中有機浮現。

## 三、關鍵特色功能（含查證過的 benchmark 數據）

- **Deep Memory Retrieval (DMR) 基準測試**：Zep 準確率 94.8%，優於 MemGPT 的 93.4%（arXiv:2501.13956）。
- **LongMemEval 基準測試**：相較 baseline 實作，準確率提升最高達 18.5%，同時回應延遲降低 90%（arXiv:2501.13956）。
- **企業級規格**：SOC2 合規，通過 S&P Market Intelligence 驗證。
- **Observations（觀察模式偵測）**：分析圖結構以主動浮現規律、重複出現的模式與共現關係，而非被動等待查詢。

## 四、開源狀態

- **Graphiti 引擎：Apache 2.0 授權，完全開源**（[github.com/getzep/graphiti](https://github.com/getzep/graphiti)），這是 Zep 目前開源策略的核心（[官方公告](https://blog.getzep.com/announcing-a-new-direction-for-zeps-open-source-strategy/)）。
- **Zep Community Edition：已停止維護**——曾以 Apache 2.0 授權提供，但官方已宣布不再更新與支援，程式碼移至 legacy 資料夾，僅保留歷史版本可用，不建議新專案採用。
- **Zep 商業雲端服務**：closed-source SaaS，提供開箱即用的企業級平台（安全性、效能、技術支援），與 Graphiti 開源核心並存的 open-core 商業模式。
- **選型建議（官方立場）**：想要「開箱即用、企業級」選 Zep 商業服務；想要「彈性、自建自維運的開源核心」選 Graphiti。

## 五、值得借鏡的技術點（對本專案的優化啟發）

本專案目前的時序處理僅有 `svo_service.py` 內建的**時序衰減**機制（`_temporal_decay()`，讓過期知識的權重隨時間流逝而淡出）——這是**連續、隱性**的衰減，沒有明確記錄「這條事實何時失效」「被什麼取代」。Graphiti 的雙時態模型提供了一個更嚴謹、更可解釋的替代/補充方案：

1. **顯式有效期間 vs 隱性權重衰減**：Graphiti 讓每條邊都有明確的 `t_valid`/`t_invalid` 時間戳，可以直接回答「這個事實在 X 時間點是否成立」，這比單純衰減權重更適合需要**時間點查詢**與**稽核追溯**的企業場景（呼應本專案 1.1.4 節「可解釋的知識問答」目標）。
2. **非破壞性更新（Non-destructive Update）**：新事實使舊事實「失效」而非「刪除」或「覆寫」，保留完整歷史——這與本專案 v1 文件提到的「精確 CRUD」目標互補：CRUD 處理使用者主動修正，Graphiti 的機制處理**系統自動偵測到矛盾時**的處理方式，兩者可以並存。
3. **混合檢索架構**：向量 + BM25 + 圖遍歷三路混合，是比本專案目前「向量索引 + BFS 圖遍歷」雙軌更完整的檢索組合，BM25 關鍵字精確匹配對法規名稱、專有名詞等場景可能比純向量檢索更準確，值得評估納入。
4. **Prescribed & Learned Ontology 的彈性**：本專案目前是純 Prescribed（固定 T-Box：19 實體/31 關係），Graphiti 允許結構「有機浮現」的模式，若本專案未來要支援使用者自訂領域本體，這是可參考的設計方向。

## 六、與本專案的具體差距或相似點

| 面向 | 本專案 | Zep/Graphiti |
|---|---|---|
| 時序管理 | 隱性權重衰減（`_temporal_decay()`） | 顯式雙時態有效期間 + 非破壞性失效 |
| 圖資料庫 | Neo4j | Neo4j / FalkorDB / Amazon Neptune（多選） |
| 檢索方式 | 向量索引 + BFS 圖遍歷 | 語意嵌入 + BM25 + 圖遍歷混合 |
| Ontology | 固定 T-Box（19 實體/31 關係） | 可預先定義（Pydantic）或有機浮現 |
| 建圖延遲 | 全量 LLM 抽取（v1 文件點名的弱點） | 增量即時整合，無需批次重算 |
| 開源狀態 | 本專案本身即為開源學術實作 | 引擎（Graphiti）開源，平台（Zep）商業閉源 |

## 七、來源

- Rasmussen et al. (2025), "Zep: A Temporal Knowledge Graph Architecture for Agent Memory", arXiv:2501.13956 — https://arxiv.org/abs/2501.13956
- Graphiti GitHub repository — https://github.com/getzep/graphiti
- Graphiti README（架構細節） — https://github.com/getzep/graphiti/blob/main/README.md
- Zep 官方開源策略公告 — https://blog.getzep.com/announcing-a-new-direction-for-zeps-open-source-strategy/
- Zep 官網 — https://www.getzep.com/
