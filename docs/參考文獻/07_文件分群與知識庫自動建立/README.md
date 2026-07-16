對應 `../../論文/03_系統設計與方法論.md` § 3.1.1（暫存區分類與資料夾歸檔，功能④ AI 自動分群建立 KG）。與第二章文獻探討的 2.1.x 章節無直接對應——3.1 屬 🔧 工程借鏡型機制、不對應任何 RQ，此資料夾的文獻是工程實作合理性佐證，性質同 `06_多模態輸入與網頁擷取/`（供 `parser/README.md` 使用），非正式研究問題的核心引用。

| 檔案 | 文獻 | 來源 |
|---|---|---|
| `grootendorst-2022-bertopic-neural-topic-modeling.pdf` | Grootendorst (2022), *BERTopic: Neural topic modeling with a class-based TF-IDF procedure* | arXiv:2203.05794 |
| `khandelwal-2025-llm-topic-labeling.pdf` | Khandelwal (2025), *Using LLM-Based Approaches to Enhance and Automate Topic Labeling* | arXiv:2502.18469 |

**用途**：v1（智慧知識庫）`services/cluster_service.py` 的暫存區自動分群機制（門檻式連通分量分群 + LLM 生成建議名稱），是這兩篇文獻描述之標準流程（embedding → 分群 → 自動命名）的簡化版——BERTopic 用 UMAP+HDBSCAN 分群、c-TF-IDF 產生主題代表詞；v1 用門檻式連通分量分群、LLM 直接生成名稱。兩篇皆僅為 arXiv 預印本，尚未查到正式會議/期刊發表版本，且僅查證作者與存在性，尚未逐篇精讀方法章節。
