# 40_法規時間版本與事件規則框架

對應 [`../../報告/本體論計畫對接_待確認事項與資料收集清單_v0.1.md`](../../報告/本體論計畫對接_待確認事項與資料收集清單_v0.1.md)（2026-09-30，使用者要求討論本專案如何支援 `本體論設計` 專案：抽取缺漏、事件／規則節點、法規時間版本與適用）；與 [`../37_三元組條件限定詞與超關係表示/`](../37_三元組條件限定詞與超關係表示/README.md)（報告65 的條件限定詞方向）互補。

本資料夾不另存 PDF，僅 README 記角色＋**一手來源摘要層級**的查證（2026-09-30，以 arXiv／官方頁面摘要為準，**多數未讀全文**），比照 `32_`、`36_`、`37_` 的輕量作法。

> ⚠️ **總聲明**：以下文獻只支持「問題存在」與「結構可以這樣設計」，**沒有任何一篇證明「把節點分成事實／事件／規則就能減少本專案的抽取缺漏」**（與報告61 的結論一致：沒有文獻能證明具體做法有效）。多數為 2026 年預印本或工作坊論文，結果為作者自報，論域非台灣法規。

## 查證狀態圖例

✅ 已讀 arXiv／官方頁面摘要（一手）｜🟡 僅搜尋結果摘要，未取一手來源｜📎 專案內已登記於其他資料夾

## A. 抽取遺漏與召回

| 文獻 | 與問題的關係 | 狀態 |
| --- | --- | --- |
| Ding, Huang, Liang, Yang & Xiao，LREC-COLING 2024，*Improving Recall of Large Language Models: A Model Collaboration Approach for Relational Triple Extraction*，arXiv:2404.09593 | 指出 LLM 從複雜句子抽取時常有遺漏，提出小模型評估過濾的協作框架 | ✅ 摘要 |
| Ghanem & Cruz，KGSWC 2024，*Enhancing Knowledge Graph Construction: Evaluating with Emphasis on Hallucination, Omission, and Graph Similarity Metrics*，arXiv:2502.05239 | 把「遺漏」與「幻覺」視為 KG 建構的可量測品質指標；**遺漏的具體定義未核實** | ✅ 摘要（定義未核實） |
| Edge et al.，2024，*From Local to Global: A Graph RAG Approach*，arXiv:2404.16130 | 附錄 A.2「自我反思」：抽取後追問是否漏了實體，可多輪；報告 chunk 為 600 token 時抽到的實體提及數近乎更大 chunk 的兩倍（**更大 chunk 的數字在取得的片段中被截斷，未核實**） | 📎 已在專案內多處引用；本次補讀 HTML 版片段 |
| Zhang et al.，EMNLP 2024，*Extract, Define, Canonicalize: An LLM-based Framework for Knowledge Graph Construction*，arXiv:2404.03868 | 先開放抽取、再定義關係、事後正規化；概念上為「先捕捉、後結構化」 | 🟡 搜尋摘要 |

專案內既有的「涵蓋比對＋補抽」文獻（ProMem、VeriFact、`langextract`）見 [`../17_抽取完整性與召回率驗證/`](../17_抽取完整性與召回率驗證/)。

## B. 命題／原子事實粒度（先捕捉、後結構化的粒度依據）

| 文獻 | 與問題的關係 | 狀態 |
| --- | --- | --- |
| Chen et al.，*Dense X Retrieval: What Retrieval Granularity Should We Use?*，arXiv:2312.06648 | 命題＝原子的、自足的單一事實；以命題為索引單位的檢索表現顯著優於段落層級（**是檢索結論，非 KG 抽取召回結論**） | 📎 已在專案內引用 |
| Min et al.，EMNLP 2023，*FActScore*，arXiv:2305.14251 | 把生成拆成原子事實逐一驗證（本專案評測真值同為原子事實粒度） | 📎 已在專案內引用 |

## C. 事件／n 元結構（表達缺漏）

| 文獻 | 與問題的關係 | 狀態 |
| --- | --- | --- |
| Luo et al.，NeurIPS 2024，*Text2NKG: Fine-Grained N-ary Relation Extraction for N-ary relational Knowledge Graph Construction* | 支援四種 n 元結構：hyper-relational、event-based、role-based、hypergraph-based | ✅ NeurIPS 頁面摘要（未取 arXiv 編號） |
| Guan et al.，TKDE 2022，*What is Event Knowledge Graph: A Survey*，arXiv:2112.15280 | 事件為中心的知識表示，與實體為中心的 KG 是不同模型 | ✅ 摘要 |
| Cao, Lan, Zhai & Li，IJCNN 2024，*5W1H Extraction With Large Language Models*，arXiv:2405.16150 | ChatGPT 處理較長新聞與特定屬性有困難；在標註資料上微調的模型優於 ChatGPT（**顯示槽位抽取本身會出錯**） | ✅ 摘要 |
| Hamborg et al.，2019，*Giveme5W1H*，arXiv:1909.02766 | 規則式 5W1H 新聞事件抽取，整體精確度 0.73（前四個 W 為 0.82，搜尋摘要所述） | 🟡 搜尋摘要 |

超關係（qualifier）表示法（StarE 等）見 [`../37_三元組條件限定詞與超關係表示/`](../37_三元組條件限定詞與超關係表示/README.md)。

## D. 法律規範（規則框架，非事件框架）

| 文獻 | 與問題的關係 | 狀態 |
| --- | --- | --- |
| Horner, Mateis, Governatori & Ciabattoni，*Toward Robust Legal Text Formalization into Defeasible Deontic Logic using LLMs*，arXiv:2506.08899 | 把複雜規範語言切成原子片段、抽取義務規則、再檢查語法與語意一致性；評估對象為澳洲電信消費者保護規範 | ✅ 摘要 |
| Guliani et al.，2026，*De Jure: Iterative LLM Self-Refinement for Structured Extraction of Regulatory Rules*，arXiv:2604.02276 | 四階段：正規化、語意分解為規則單元、19 維度 LLM 裁判、有限預算內迭代修復；作者稱三輪內達峰值（**預印本、作者自報**） | ✅ 摘要 |

## E. 法規時間版本與時點檢索

| 文獻 | 與問題的關係 | 狀態 |
| --- | --- | --- |
| de Martim，JURIX 2025，*An Ontology-Driven Graph RAG for Legal Norms: A Structural, Temporal, and Deterministic Approach*（SAT-Graph RAG），arXiv:2505.00039 | 區分抽象法律作品與其版本化表達；時點檢索、層級影響分析、可稽核溯源；案例為巴西憲法 | ✅ 摘要 |
| Cymbler, Guez & Fabre，ICML 2026 AI4Law Workshop，*Temporal Misgrounding in Legal RAG: A Versioned-Corpus Benchmark for French Tax Law*，arXiv:2608.09393 | 定義「時間誤接地」（引用現行版本但適用的是他版本）；32,436 個條文版本、209 題；僅現行版本的靜態 RAG 取到日期適用版本的比例 0%；作者的多版本索引系統 98.3%（**工作坊論文、作者自報、單一領域**） | ✅ 摘要 |
| Fan et al.，EMNLP NLLP 2026（頁面所載），*Can LLMs Time Travel? … Legal Agentic Search through Reinforcement Learning*，arXiv:2605.25920 | 指出模型對時間有訓練截止點偏誤；以強化學習提升時間一致性 | ✅ 摘要 |
| Li et al.，2026，*LexKairos: Benchmarking Legal Temporal Capabilities in LLMs*，arXiv:2608.09106 | 中國法律情境的時間能力基準；最強模型在精確法規時間中繼資料回憶與複雜時限推理上仍有明顯限制 | ✅ 摘要 |
| Rasmussen et al.，2025，*Zep: A Temporal Knowledge Graph Architecture for Agent Memory*（Graphiti），arXiv:2501.13956 | 雙時態（有效時間／記錄時間）；矛盾時使舊邊失效而非刪除 | 📎 已在專案內引用（`docs/報告/產品競品研究/03_Zep_Graphiti.md`）；本次補讀摘要 |

## 與本專案的對應

| 議題 | 文獻能支持的主張 | 文獻**不能**支持的主張 |
| --- | --- | --- |
| 抽取遺漏 | LLM 抽取常有遺漏；多輪／評估過濾／涵蓋比對可改善 | 本專案的遺漏率、以及節點分類能否降低它 |
| 事件／n 元結構 | 結構化槽位能表達時間、地點、角色等 | 對法規條文適用（法規是規範，不是事件）；5W1H 槽位抽取本身仍會出錯 |
| 法規時間版本 | 只用現行版本的 RAG 會系統性接地到錯誤版本；時點檢索需確定性的結構化處理 | 對台灣法規、對本專案語料的實際效果 |

## 待辦（依本資料夾規則）

- 每次新增文獻須同步更新 `../../論文/附錄與參考文獻.md` 的信任分級表。**本次未更新**：論文修改依 BT／SM 草案 Q7 的裁示（先不寫進論文）暫緩，待使用者決定是否納入論文再補。
