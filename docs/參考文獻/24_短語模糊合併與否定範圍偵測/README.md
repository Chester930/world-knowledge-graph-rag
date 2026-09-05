# 24_短語模糊合併與否定範圍偵測

對應 `docs/論文/02_文獻探討.md` § 2.4.5（RQ4b，`resolve_entity_name()` 模糊合併守衛
文獻定位段落）；`docs/論文/03_系統設計與方法論.md` § 3.4 `DEDUP4`／`GUARD4`；
`docs/報告/25_擴大版新舊KG問答品質比對報告.md` § 4 發現3／發現C（真實案例來源）。

## 問題陳述

`resolve_entity_name()`（`DEDUP4`）用編輯距離／cosine 相似度判斷兩個 `Entity.name`
是否為同一實體，對「表面相似、語意不同」的短語會誤判：

- **量詞類**（發現3）：`新臺幣四千元` vs `新臺幣八千元`，`_edit_ratio`＝0.833；`五日`
  vs `十日`；`三十日以上` vs `未滿三十日`。已用 `_QUANTITY_PATTERN`／`_MEASURE_PATTERN`
  守衛攔截（數字＋單位樣式命中即跳過模糊比對）。
- **範圍修飾詞類**（尚未涵蓋，設計討論中）：`每一型式` vs `每增加一種型式`，
  `_edit_ratio`＝0.727，**不含任何數字**，現行守衛的樣式規則抓不到——「增加」這個
  詞把「基礎量」改成「遞增量」，語意相反但表面極相似。

## 內容清單

| 檔案 | 文獻 | 來源 | 狀態 |
|---|---|---|---|
| `mrksic-et-al-2016-counter-fitting.pdf` | Mrkšić, Ó Séaghdha, Thomson, Gašić, Rojas-Barahona, Su, Vandyke, Wen & Young (2016), *Counter-fitting Word Vectors to Linguistic Constraints*，ACL 2016 | [arXiv:1603.00892](https://arxiv.org/abs/1603.00892)；[GitHub nmrksic/counter-fitting](https://github.com/nmrksic/counter-fitting) | ✅ 已下載全文（7 頁） |
| `tosun-et-al-2026-antonym-intrusion-synonym-graph.pdf` | Tosun, Buldur, Ezerceli & ElHussieni (2026), *Beyond Cosine Similarity: Taming Semantic Drift and Antonym Intrusion in a 15-Million Node Turkish Synonym Graph* | [arXiv:2601.13251](https://arxiv.org/abs/2601.13251) | ✅ 已下載全文（11 頁） |
| （未下載）Chapman, Bridewell, Hanbury, Cooper & Buchanan (2001), *A Simple Algorithm for Identifying Negated Findings and Diseases in Discharge Summaries*（**NegEx**），*Journal of Biomedical Informatics* 34, 301-310 | [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S1532046401910299) | ⚠️ 付費牆（ScienceDirect），查無合法免費全文（ResearchGate／Academia.edu 為第三方上傳、非本專案慣例採用來源），僅依 WebSearch 查得之摘要與量化結果（specificity 85.3%→94.5%、PPV 68.4%→84.5%）引用，比照 Fellegi & Sunter (1969) 的既有處理慣例 |

## 各文獻在本設計中的角色

### 1. Mrkšić et al. (2016) —— 確立「表面相似掩蓋語意相反」是已知現象

Distributional embedding 常把反義詞判定高相似度（因常出現在相同句法框架，如
「the water is hot/cold」）。本論文報告25 §4 發現3/發現C 的真實案例（中文法規
量詞：`四千元`/`八千元`、`未滿六歲`/`未滿十五歲`）是這個現象的中文短語版本——
**佐證問題真實存在**，非本專案獨有的孤立缺陷。解法（counter-fitting，用已知
反義詞典把向量空間拉開）**依賴語言學約束詞典**（WordNet／PPDB），本專案沒有
對應的中文法規量詞反義詞典，不直接複用，官方碼 [nmrksic/counter-fitting](https://github.com/nmrksic/counter-fitting)
僅供架構參考。

### 2. Tosun et al. (2026) —— 幾乎逐字對應的知識圖譜情境

大規模（1500萬節點）土耳其語**知識圖譜**同義詞聚類系統同樣因 cosine 相似度
誤把反義/對立詞聚在一起，甚至遞移鏈式擴大錯誤（"hot → spicy → pain →
depression"）。解法：語義關係分類器（同義/反義/共下位詞三分類，90% F1）+
拓撲感知的軟到硬剪枝。**證實這是 2026 年現行研究問題**，但需要訓練分類器，
規模遠超本專案（64 份文件、量詞短語級別）需求，僅作問題真實性與嚴重性佐證。

### 3. Chapman et al. (2001, NegEx) —— 支持「規則式路線」的關鍵先例

臨床文本否定語意偵測，用**簡單觸發詞清單 + 正規表示式**（非訓練模型），在
1235 個真實案例測試中把精確率從 68.4%（baseline）提升到 84.5%，特異度
85.3%→94.5%。證實「觸發詞表 + regex」這種輕量規則法在「否定/範圍修飾詞
偵測」這類問題上有實證效果，是本論文選擇延伸 `_QUANTITY_PATTERN`／
`_MEASURE_PATTERN` 既有架構（而非訓練分類器）處理範圍修飾詞類別的方法論
依據。

## 誠實聲明

三篇文獻皆為**問題定位**與**方法論路線選擇**的佐證，本論文的守衛規則本身
（`_QUANTITY_PATTERN`／`_MEASURE_PATTERN`／範圍修飾詞清單，若後續實作）查無
直接文獻先例，是針對本語料實測案例逐步歸納出的工程設計，屬於第三章 3.8 節
「本論文自行設計的工程決策」分類，非直接複用任一篇文獻的演算法或程式碼。

## 尚未查證／待辦

- [ ] NegEx 全文若後續找到合法免費來源（例如作者機構典藏），應補下載精讀。
- [ ] 範圍修飾詞守衛（增加／額外／再／又／另等）本身尚未實作，設計討論中——
      若實作，另立報告記錄（比照報告27/28 的模式）。
