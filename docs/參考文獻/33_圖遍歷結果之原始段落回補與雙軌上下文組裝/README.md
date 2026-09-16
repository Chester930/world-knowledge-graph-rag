# 33_圖遍歷結果之原始段落回補與雙軌上下文組裝

對應 `docs/報告/58_圖遍歷端到端關聯Chunk提領與雙軌上下文組裝SDD任務書.md`（2026-09-16 §1.0 核實訂正後的後續查證）。

## 查證背景

報告58 §1.0 原稿宣稱「已以 KAG、Think-on-Graph 2.0、LightRAG、PathRAG 與 Dense X Retrieval 做文獻／專案對照」，經 2026-09-16 複查發現 KAG、ToG-2 全 repo 查無、宣稱同步的論文章節編號不存在（見報告58開頭核實標注，commit `b747dc3`）。本資料夾是訂正後**真正針對「圖遍歷結束後，是否/如何把原始段落文本一併送回 LLM」這個具體問題**重新查證的結果，而非沿用原稿的未經查核清單。

## 內容清單

| 檔案 | 文獻 | 來源 | 全文狀態 |
|---|---|---|---|
| `ma-et-al-2024-think-on-graph-2.pdf` | Ma, Xu, Jiang, Li, Qu, Yang, Mao & Guo (2024/2025)，*Think-on-Graph 2.0: Deep and Faithful Large Language Model Reasoning with Knowledge-Guided Retrieval Augmented Generation*，**ICLR 2025**（首頁已核「Published as a conference paper at ICLR 2025」，IDEA Research 等） | [arXiv:2407.10805](https://arxiv.org/abs/2407.10805) | 📥 已下載（25 頁，2026-09-16，首頁標題/作者/會議已核）；🟡 透過 WebFetch 對 HTML 全文精讀關鍵章節（§3.3、§4.7、Table 4），非逐頁人工精讀 |
| `liang-et-al-2024-kag.pdf` | Liang, Sun, Gui, Zhu, Zhong, Zhao, Jiang, Qu, Bo, Yang, Xiong, Yuan, Xu, Wang, Zhang, Zhang, Chen（Ant Group + 浙江大學，2024/2025），*KAG: Boosting LLMs in Professional Domains via Knowledge Augmented Generation* | [arXiv:2409.13731](https://arxiv.org/abs/2409.13731) | 📥 已下載（33 頁，2026-09-16，首頁標題/作者已核）；🟡 WebFetch 查證摘要與核心機制，未逐頁精讀 |

**HippoRAG 交叉引用**：`docs/參考文獻/12_三元組事實層級向量化與檢索/gutierrez-et-al-2024-hipporag.pdf`（已下載，NeurIPS 2024）原本只標「全文核實狀態待補」，本次針對「圖節點分數是否回補passage文本」這個具體問題透過 WebFetch 查證其 §2.3 方法章節，結論見下方。本資料夾不重複下載，僅在此記錄新增的查證結果。

## 各文獻的具體機制查證結果

### 1. HippoRAG（Gutiérrez et al. 2024, NeurIPS）——圖分數映射回原始段落是既有先例，但不是「雙軌」而是「取代」

WebFetch 對 arXiv HTML 全文查證 §2.3：Personalized PageRank 在 KG 節點（OpenIE 抽出的 noun phrase）上算完分數 `π_n` 後，**不是直接把節點/三元組送給 LLM**，而是用一個 `P` 矩陣（`|N|×|P|`，記錄每個 noun phrase 在每個原始 passage 中出現的次數）把節點分數映射成 passage 分數 `π_p = π_n · P`，**最終送進 LLM 的是排名最高的原始段落文本，不是圖結構摘要**。

邊的建立：三元組邊（OpenIE 直接抽取）＋ 同義詞邊（cosine 相似度超過門檻 τ 時由 Contriever/ColBERTv2 加入），論文未建立獨立的「片語↔段落」contextual edge，靠 `P` 矩陣的共現次數連結。

**誠實侷限**：論文的消融分析（Table 5）測試的是替代元件（如不同 retriever encoder），**沒有做「只用圖結構摘要」vs「回補完整段落文本」的隔離消融**——HippoRAG 的架構本身就預設「圖只負責找出該讀哪個段落，實際內容一定來自原始段落」，沒有跟報告58設想的「圖摘要+段落文本雙軌並陳」這個變體直接比較過。這篇文獻能佐證的是「查完圖之後把結果映射回原始段落文本」這個大方向在頂會有明確先例，**不能佐證「原始段落+結構化摘要兩者都保留」比「只留段落」更好**。

### 2. Think-on-Graph 2.0（Ma et al. 2024/2025, ICLR 2025）——目前找到跟報告58雙軌設計最貼近的直接先例

WebFetch 對 arXiv HTML v7 全文查證 §3.3「Reasoning with Hybrid Knowledge」：論文原文明確描述送進 LLM 的 prompt 組成——

> "prompt LLM with all knowledge found, including Clues^(i-1), **triple paths**, top-K entities and the **corresponding context chunks**"

即三元組路徑（triple paths）與對應實體的原始文件段落（context chunks）**確實會一起送進同一個 prompt**，跟報告58「軌道A邏輯路徑摘要＋軌道B原始Chunk提領」的架構幾乎同構。

§4.7 有一份**人工案例分析**（非自動化消融實驗）：對隨機抽樣的正確回答分類，「雙重增強答案（triple+context 都用到）」占 32.26%，「僅文件增強」占 41.94%，論文原文評論「Both-enhanced Answer shows significant utilization, suggesting that the combination of triple-link reasoning and entity context documents is a highly effective pattern」。

**誠實侷限**：這是**人工分類案例統計，不是控制變因的消融實驗**——沒有「純三元組 vs 純段落 vs 兩者合併」三組對照的量化分數比較，論文本身也沒有宣稱這個組合模式已被嚴格消融驗證過，只呈現「這個模式在正確答案裡出現得夠頻繁、值得注意」。具體 prompt 格式範例在附錄 E（Table 18-19），本次查證未逐字核對格式細節，僅確認章節位置存在。

### 3. KAG（Liang et al. 2024/2025, Ant Group）——「mutual-indexing」明確支持圖與原始段落的雙向連結，但屬不同層次的整合

摘要與核心機制描述明確提到 **"mutual-indexing between knowledge graphs and original chunks"**——知識圖譜與原始 chunk 之間有雙向索引機制，這是報告58「三元組要能回頭找到來源 chunk」這個需求（`SVOTriple.source_svo_chunk_index` 之類欄位）在工業界系統裡的直接先例。KAG 在 2wiki／HotpotQA 上分別有 19.6%／33.5% 的 F1 相對提升，且已在螞蟻集團電子政務／醫療 QA 場景落地。

**誠實侷限**：本次僅透過 WebFetch 查證摘要層級描述，**未精讀方法章節確認 mutual-indexing 的具體實作方式**（例如索引粒度是段落級還是句子級、雙向查詢的觸發時機），也未確認 19.6%/33.5% 的提升是否包含「回補原始段落」這個子機制的獨立貢獻或是整體框架的綜合效果。待後續若要真正引用其具體演算法，需要進一步精讀全文方法章節（Word 檔已下載 33 頁）。

## 對報告58的結論

**修正後的誠實結論**：ToG-2 是目前找到最直接對應報告58「雙軌上下文組裝」設計的先例（三元組路徑＋原始段落同時入 prompt），KAG 佐證「圖與原始段落間應有雙向索引」這個架構需求，HippoRAG 佐證「圖遍歷結果映射回原始段落文本」是頂會認可的方向但走的是取代而非並陳路線。**三篇文獻沒有一篇提供嚴格控制變因的量化消融，證明「加入原始段落文本」相對於「只用結構化三元組摘要」有可重現的效果提升**——ToG-2 的支持證據是人工案例分類統計，HippoRAG 根本沒有做這個對比，KAG 只有整體框架的綜合分數。

這代表報告58若要真正動工，§4 驗收標準原本規劃的「K vs K+C 消融實驗」（純三元組 vs 三元組＋Chunk 擴展）**在文獻上找不到現成答案可以直接套用，必須靠本專案自己的消融實驗量出來**——這點原本§2.4已隱含此立場（「本版明確不做...把L2 prize prototype寫成已完成」），現在有了具體文獻查證的支持：業界先例（ToG-2/KAG）採用類似架構但都沒有嚴格消融證明其必要性，本專案的消融實驗因此有真正的文獻空白可以填補，而非重複造輪子。

## 待辦

- [ ] 若報告58排入實作，KAG方法章節（mutual-indexing具體實作）與ToG-2附錄E（prompt格式範例）需要逐頁精讀，目前僅WebFetch查證摘要與關鍵章節轉述。
- [ ] 確認 ToG-2 §4.7 案例分析的原始資料集/題型是否與本專案的勞基法QA場景性質相近（ToG-2 用的是通用領域多跳QA benchmark，非法規文件），避免直接套用其32.26%/41.94%這類數字到本專案脈絡。
