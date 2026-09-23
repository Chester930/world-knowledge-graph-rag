# 38_檢索embedding非決定性與可重現性

對應 HANDOVER.md 2026-09-22「獨立judge pilot（n=1）」段落——`57-CANARY5` 的 Stage 1 檢索 recall 在 judge 模型不變、KG不變的情況下，兩次執行間從1.0掉到0.5，判定為跟待測變因（judge）無關的雜訊，疑似檢索/embedding層的非決定性。本資料夾記錄查證結果。

本資料夾不另存 PDF，僅 README 記角色＋WebSearch 即時查證（2026-09-22），比照 `32_法規結構感知切塊與主旨錨定/`、`37_三元組條件限定詞與超關係表示/` 的輕量作法。

## 查證結果

### 1. 根因假說：非決定性來自 embedding 生成階段，不是向量搜尋演算法本身

> **Wang, Zhao, Tallent & Guo (2025)**，*On The Reproducibility Limitations of RAG Systems*，arXiv:2509.18869（2025年9月）

系統性研究RAG檢索管線的可重現性，提出 ReproRAG 開源評測框架，量化四個不確定性來源：
1. **Embedding 模型選擇**——不同embedding模型（BGE/E5/Qwen）之間一致性極低（Overlap Coefficient僅0.43–0.54），是**最主要**的不可重現性來源。
2. **數值精度**——FP32/FP16/BF16/TF32不同浮點格式造成「embedding drift」（雖然量級較小，FP32 vs FP16的L2距離約5.74e-04）。
3. 動態資料插入、硬體/分散式因素。

**關鍵發現，直接對應本專案觀察到的現象**：論文明確指出「**核心ANN檢索演算法與分散式協定，在條件控制得當時可達到完全的run-to-run可重現性**」——也就是說，向量搜尋（Neo4j的HNSW索引查詢）本身通常是決定性的，**真正的雜訊來源是每次重新呼叫embedding model時的生成變異**，跟本專案報告20已經引用、用於解釋LLM生成非決定性的根因（Horace He/Thinking Machines Lab，batch size依賴的reduction kernel）屬於同一個機制家族，只是發生在embedding這一端而非文字生成那一端。

**建議解法（論文明確提出）**：**Embedding caching**——預先計算並儲存embedding，避免每次重新生成造成的變異。這是唯一一項不需要改動底層模型/推論引擎、可以直接在應用層實作的緩解措施（其餘如精度標準化、硬體環境紀錄，多屬診斷/文件化措施，不直接消除雜訊）。

⚠️ **誠實聲明**：ReproRAG 宣稱是開源專案，但本次查證**未能找到可獨立驗證的GitHub連結／star數**，不列入「已查證開源專案」等級，僅引用論文本身內容。

### 2. 補充根因機制：與LLM推論非決定性同源的數值/硬體config敏感性

> **Yuan, Li, Ding, Xie, Li, Zhao, Wan, Shi, Hu & Liu (2025)**，*Understanding and Mitigating Numerical Sources of Nondeterminism in LLM Inference*，arXiv:2506.09501（Rice University／University of Minnesota／Adobe）

延伸（非取代）本專案已引用的 Horace He／Thinking Machines Lab 分析：浮點運算非結合律，疊加batch size／GPU數量／GPU版本等系統配置差異，會造成神經網路推論輸出的顯著變化（例：BF16精度下的推理模型，僅因硬體配置不同就出現最高9%準確率差異）。提出 **LayerCast**（權重存16-bit、運算走FP32）作為免重訓練即可部署的緩解方案。**誠實適配度**：LayerCast需要修改推論引擎內部運算精度，本專案透過Ollama黑盒呼叫，無法直接套用這個方案本身，但其根因分析（config敏感性）佐證問題的普遍性，支持本專案觀察到的現象並非個案或程式錯誤。

### 3. 為什麼「排名邊界」特別容易被雜訊翻轉：高維embedding空間的對比度塌縮

> **Lopez Fune (2026)**，*High-Dimensional Concentration and Retrieval Instability in Embedding Spaces: Implications for Retrieval-Augmented Generation*，arXiv:2606.28330（2026年5月，⚠️ 單一作者、非peer-reviewed期刊/會議，僅arXiv預印本）

以受控數值實驗研究高維向量空間裡的距離集中（distance concentration）、cosine集中、對比度塌縮（contrast collapse）、hubness等現象，證實**相似度分數的訊噪比會隨維度上升而系統性降低**，導致最近鄰檢索排序不穩定、且有結構性偏誤。**與本專案的對應**：這解釋了為什麼觀察到的雜訊剛好體現在「排名邊界的gold fact掉出top-k」這種模式，而非隨機亂跳——高維空間裡本來就是排名邊界的候選對微小擾動最敏感，不是巧合。⚠️ **誠實聲明**：這篇僅是預印本、單一作者、機構為商業公司（Data Empirix）而非學術機構，佐證強度弱於前兩篇，只作為機制性解釋的旁證，不是本專案設計決策的主要依據。

## 對本專案的具體建議

1. **短期（低成本，可行）**：在評測harness層面加一層**query embedding cache**——同一題目在同一次比較（例如今天的「共用judge vs獨立judge」對照）裡，只算一次query embedding，兩個臂共用，不要各自重新呼叫embedding provider。這樣才能把「judge效果」和「embedding非決定性雜訊」這兩個變因分開，不需要改Ollama或任何底層模型。
2. **中期**：若要正式測試任何「固定檢索、只換生成端」類型的對照實驗，優先使用報告62 T0已有的 `prompt_context_lines` 重放機制（已經是「固定住檢索結果」的等價做法，只是原本是為了排除prompt組裝變因設計的，剛好也能排除這裡發現的embedding變因）——不需要新開發，只是要把它的用途擴展到這類pilot。
3. **不建議**：不建議嘗試修改Ollama或bge-m3本身的推論精度／批次設定去追求完全決定性——本專案透過Ollama黑盒呼叫，沒有掌控這層的能力，且文獻顯示即使做到（如LayerCast），仍需要修改推論引擎內部，成本遠高於上述應用層的緩解方式。
