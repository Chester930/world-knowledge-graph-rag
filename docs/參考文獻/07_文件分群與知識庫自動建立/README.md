對應 `../../論文/03_系統設計與方法論.md` § 3.1.1（暫存區分類與資料夾歸檔，含分類分數計算與功能④ AI 自動分群建立 KG）。與第二章文獻探討的 2.1.x 章節無直接對應——3.1 屬 🔧 工程借鏡型機制、不對應任何 RQ，此資料夾的文獻是工程實作合理性佐證，性質同 `06_多模態輸入與網頁擷取/`（供 `parser/README.md` 使用），非正式研究問題的核心引用；但與 06 不同的是，本資料夾另收錄第二章 2.4 節查證過的可信任專案背書來源。

| 檔案 | 文獻 | 來源 |
|---|---|---|
| `snell-et-al-2017-prototypical-networks.pdf` | Snell, Swersky, Zemel (2017), *Prototypical Networks for Few-shot Learning* | arXiv:1703.05175，🟢 發表於 **NeurIPS 2017**（pp. 4077-4087） |
| `mcinnes-et-al-2017-hdbscan.pdf` | McInnes, Healy, Astels (2017), *hdbscan: Hierarchical density based clustering* | DOI: 10.21105/joss.00205，🟢 發表於 ***Journal of Open Source Software*** 2(11), 205 |
| `grootendorst-2022-bertopic-neural-topic-modeling.pdf` | Grootendorst (2022), *BERTopic: Neural topic modeling with a class-based TF-IDF procedure* | arXiv:2203.05794，🟡 尚無正式會議/期刊發表版本 |
| `khandelwal-2025-llm-topic-labeling.pdf` | Khandelwal (2025), *Using LLM-Based Approaches to Enhance and Automate Topic Labeling* | arXiv:2502.18469，🟡 尚無正式會議/期刊發表版本 |

**用途**：`services/classify_service.py` 的分類分數計算（centroid cosine 相似度）直接依據 Snell et al.（2017）原型網路的 centroid 精神；`services/cluster_service.py` 的暫存區 AI 自動分群機制（HDBSCAN + LLM 命名）直接依據 McInnes et al.（2017）HDBSCAN 演算法與 Khandelwal（2025）驗證過的主導子群命名輸入篩選法。這兩個 v2 服務模組已於 2026-07-16 完整實作並通過測試（見 `tests/services/`），**不再是** v1（智慧知識庫）簡化實作的類比對照——v1 用的是門檻式連通分量分群＋兩兩配對加權分類公式，v2 已改採本資料夾四篇文獻描述的方法本身。BERTopic（Grootendorst, 2022）作為「embedding → HDBSCAN → LLM 命名」整條管線的獨立產業實作，於 2026-07-17 補充查證為可信任專案背書（見第二章 2.4.2、第三章 3.1.1 §a 對應段落），與 HDBSCAN／Khandelwal 兩篇演算法文獻互為佐證，非取代關係。四篇文獻皆已查證作者/存在性；Snell et al. 與 McInnes et al. 已有正式出版版本（🟢），BERTopic 與 Khandelwal 尚僅見 arXiv 預印本（🟡），尚未逐篇精讀方法章節細節。

**另有兩項專案背書非傳統論文、無 PDF 可下載**：semantic-router（Aurelio Labs，驗證 embedding 相似度離散路由的產業實例）與 Paperless-ngx（驗證/反證三層信心分級介面設計），查證來源與 URL 見第二章 2.4 節文末 Sources 清單，性質為開源軟體專案而非學術文獻，故不比照上表建立本地 PDF 檔案。
