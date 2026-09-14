# 32_法規結構感知切塊與主旨錨定

對應 `docs/報告/46_領域可插拔切塊參數化與主旨錨定SDD.md`；`docs/報告/47_Claude_Code交接任務書.md` 任務 B。
支撐 `services/svo_chunking.py::ArticleAwareChunking`（法規一條一塊）與 `build_svo_chunks()` 的
`header_anchored`／`prepend_header_to_children`（款式斷頭防護）兩個既有設計，以及任務 B 範圍修正的資料依據。

查證日期 2026-09-14（`sdd-retrieval-comparison` worktree，Claude Code session）。arXiv 論文以 WebFetch
讀取摘要頁核實；GitHub 專案 star/license/pushed 皆經 `gh api` 即時查證。

---

## A. 法規/法條邊界感知切塊 —— 優於固定視窗的實證文獻

| 文獻 | 事實 | 在本設計中的角色 |
|---|---|---|
| Prior, M., Milanova, N., & Schultz, A. (2026). "Chunking German Legal Code." *Eighth Workshop on Automated Semantic Analysis of Information in Legal Texts* @ ICAIL 2026. arXiv:2605.19806 | WebFetch 核實摘要：以德國民法典為語料，比較 7 種切塊法（結構單元 section/subsection/sentence/proposition、固定視窗、contextual chunking、語意聚類、Lumber-style、RAPTOR 階層檢索）於法律問答檢索表現；結論「依法規固有結構（尤其 section/subsection）切塊之召回率最高」，且結構保留法在效果與運算成本上都優於更複雜的 LLM 密集技術 | 直接支撐 `ArticleAwareChunking`「按 `ArticleNo` 邊界切、一條對一塊」優於固定句數聚合套用在法規全文的設計選擇——不是本專案獨有猜測，是同年（2026）同主題的實證結論 |
| Ford, C., Rane, O., & Leavy, S. (2026). "Navigating Global AI Regulation: A Multi-Jurisdictional Retrieval-Augmented Generation System." *PoliticalNLP Workshop* @ LREC 2026. arXiv:2604.25448 | WebFetch 核實摘要：涵蓋 68 法域、242 份法規文件的 RAG 系統，採用「保留跨異質文件法規結構之類型專屬切塊（type-specific chunking that preserve legal structure）」，faithfulness 0.87、answer relevancy 0.84 | 佐證「依文件類型（法規 vs 一般文件）採不同切塊策略」是生產級系統既有做法，對應本專案 `prepare_svo_ready_chunks()` 依 `articles is not None` 分派 `ArticleAwareChunking` 或通用 `SVOGROUP` 的**雙路徑設計**。⚠️ 摘要層級未明確揭露是否嚴格「一條文＝一塊」，此點不可過度引用（見下方待深讀） |

## B. 跨塊邊界資訊流失與主旨前綴注入 —— 「款式斷頭防護」的方法學先例

| 來源 | 事實 | 角色 |
|---|---|---|
| Anthropic. "Contextual Retrieval." Anthropic Engineering Blog（2024 發表，持續引用至今） | WebFetch 核實：對每個 chunk 前綴注入 50–100 token 的說明性上下文後再 embedding／建 BM25 索引，解決「chunk 被抽離原文後遺失『屬於哪個時間/主體/文件』」的問題；實測 top-20 檢索失敗率降低 35%（5.7%→3.7%），疊加 contextual BM25 達 49%，再疊加 reranker 達 67%（→1.9%） | 直接支撐 `header_anchored`「款式斷頭防護」的核心方法學：**前綴注入父層上下文以修補 chunk 邊界資訊流失**是已有實測效益的通用手法。⚠️ **關鍵差異**：Anthropic 版本用 LLM 現場生成上下文摘要（非決定性、有 LLM 呼叫成本）；本專案 `prepend_header_to_children` 是**規則式**直接前綴母條文既有主旨句（零 LLM 呼叫、完全決定性），呼應本專案「確定性接地守衛」與「Zero Code-Gen」鐵律——是同一概念的**去 LLM 化簡化版**，非照搬 |
| LangChain (`langchain-ai/langchain`)，`MarkdownHeaderTextSplitter` | `gh api` 2026-09-14 核實：⭐146,273，MIT license，pushed 2026-09-14（查證當日仍活躍維護）。依標題層級切分 markdown，並將父層標題保留為每個子 chunk 的 metadata，讓子 chunk 檢索後仍可還原其所屬章節脈絡 | 佐證「保留/前綴父層標題資訊到子 chunk」在主流生產級 RAG 函式庫中是**成熟、非新創**的模式，只是實作位置不同：LangChain 存獨立 metadata 欄位，本專案 `prepend_header_to_children` 直接注入 `chunk.text` 本體——因為下游 SVO 抽取（`LLM_SVO` 三元組抽取）目前只吃純文字、沒有獨立 metadata 通道可傳遞 |

## C. 尚未取得全文 / 待深讀

- [ ] Ford et al. 2026 全文方法論章節 —— 確認是否真為「一結構單元＝一 chunk」或只是「保留結構邊界」，目前僅摘要層級查證，本 README 已標注不可過度引用
- [ ] Prior et al. 2026 全文的量化召回率數字（摘要只給定性結論：「結構單元切塊召回率最高」）—— 若第五章消融分析要引用精確數字需讀全文

---

## D. 任務 B 範圍修正的資料依據（非文獻，即時查詢 Neo4j 得出）

- 現有評測 KG（`236903cf-055a-40a8-8923-b9d06601f3b7`）與其前身（`76bc98ff`）共 3303 個 `LawArticle` 節點，`article_content` 長度分布：平均 145 字元、p95 397 字元、最長 2143 字元（2026-09-14 即時查詢，`MATCH (c:LawArticle) RETURN avg/max/percentileDisc(size(c.article_content))`）。
- 這兩個既有 KG 都是透過 `create_clean_leave_scheduling_kg.py`／`import_leave_scheduling_dataset.py` 等專用匯入腳本傳入 `articles=`，走 `ArticleAwareChunking` 路徑；目前系統中**沒有任何一個 KG** 是透過標準 `routers/staging.py` 上傳流程或 `knowledge_graph_service.build_graph()`（兩者皆不傳入 `articles=`，恆走通用 `SVOGROUP`／`build_svo_chunks()`）建立的，`ChunkingConfig.header_anchored` 因此從未在真實文件/KG 上被觸發過，僅有 `tests/services/test_svo_chunking.py` 的合成資料覆蓋。

---

## 各文獻在本設計中的定位總結

1. **`ArticleAwareChunking`（一條一塊）非本專案獨有猜測**：Prior et al. 2026 同年同主題實證「結構單元切塊優於固定視窗」，Ford et al. 2026 佐證法規/一般文件雙路徑分派是生產級系統既有做法。
2. **`header_anchored`／`prepend_header_to_children`（款式斷頭防護）方法學有先例**：概念上對應 Anthropic Contextual Retrieval（前綴上下文修補邊界資訊流失、實測有效）與 LangChain `MarkdownHeaderTextSplitter`（保留父層標題脈絡是主流函式庫既有模式）；本專案採**規則式、零 LLM 呼叫**的簡化實作，符合「確定性接地守衛」鐵律，代價是不像 Anthropic 版本能生成語意摘要，只能還原字面上的母條文主旨句。
3. **任務 B 範圍修正有資料依據**：現有法規 KG 全文長度遠低於任何切塊/embedding 長度限制（max 2143 字元），目前**沒有實證需求**要在 `ArticleAwareChunking` 內對過長法條做二次切分；`header_anchored` wiring 應該完成（供未來通用文件領域使用），但「在真實 KG 上驗證效果」目前無標的可測，只能以整合測試（呼叫 `trigger_extraction()` 端到端、斷言 `cfg.chunking` 確實傳到 `build_svo_chunks()`）替代，需待未來有真實通用文件 KG 匯入才能做上線驗證。
