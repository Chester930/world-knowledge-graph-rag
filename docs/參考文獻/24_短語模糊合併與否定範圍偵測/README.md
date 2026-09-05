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
- **範圍修飾詞類**（設計已提案，尚未實作——見 `docs/報告/29_實體模糊合併範圍修飾詞與數字比較詞守衛設計報告.md`）：
  `每一型式` vs `每增加一種型式`，`_edit_ratio`＝0.727，**不含任何數字**，
  現行守衛的樣式規則抓不到——「增加」這個詞把「基礎量」改成「遞增量」，
  語意相反但表面極相似。
- **數字比較詞類**（同上報告 §2.4/§4.4，2026-09-05 真實診斷確認——**現在進行式**，
  非歷史遺留）：法規門檻/級距表常見的「`1 以上，未滿 10 的容許濃度`」vs
  「`100 以上，未滿 1000 的容許濃度`」，數字後面接的是「以上」「未滿」，不是
  `_MEASURE_PATTERN` 認得的單位，同樣抓不到——報告26 §4 #3（Q8，變量係數表）
  拒答的真正根因，非生成端推理缺口。

## 內容清單

| 檔案 | 文獻 | 來源 | 狀態 |
|---|---|---|---|
| `mrksic-et-al-2016-counter-fitting.pdf` | Mrkšić, Ó Séaghdha, Thomson, Gašić, Rojas-Barahona, Su, Vandyke, Wen & Young (2016), *Counter-fitting Word Vectors to Linguistic Constraints*，ACL 2016 | [arXiv:1603.00892](https://arxiv.org/abs/1603.00892)；[GitHub nmrksic/counter-fitting](https://github.com/nmrksic/counter-fitting) | ✅ 已下載全文（7 頁） |
| `tosun-et-al-2026-antonym-intrusion-synonym-graph.pdf` | Tosun, Buldur, Ezerceli & ElHussieni (2026), *Beyond Cosine Similarity: Taming Semantic Drift and Antonym Intrusion in a 15-Million Node Turkish Synonym Graph* | [arXiv:2601.13251](https://arxiv.org/abs/2601.13251) | ✅ 已下載全文（11 頁） |
| `chapman-et-al-2001-negex.pdf` | Chapman, Bridewell, Hanbury, Cooper & Buchanan (2001), *A Simple Algorithm for Identifying Negated Findings and Diseases in Discharge Summaries*（**NegEx**），*Journal of Biomedical Informatics* 34, 301-310 | [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S1532046401910299)；全文取自共同作者 [Will Bridewell 官方主頁存檔](https://paravidya.com/publication/jbi2001/jbi2001.pdf)（非第三方轉載） | ✅ 已下載全文（2026-09-05，13頁），已精讀 |

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

### 3. Chapman et al. (2001, NegEx) —— 支持「規則式路線」的關鍵先例（2026-09-05 全文精讀）

臨床文本否定語意偵測，用**簡單觸發詞清單 + 正規表示式**（非訓練模型）。
1000 句出院病摘（1235 個 UMLS 詞次）測試中，NegEx 對比 baseline：
specificity 85.27%→94.51%、PPV 68.42%→84.49%（sensitivity/NPV 略降，
77.84% vs 88.27%、91.73% vs 93.01%，作者判斷為可接受取捨）。

全文精讀後，兩個設計細節與本論文的範圍修飾詞守衛直接相關：

- **觸發詞分兩類**——「偽否定詞」（pseudo-negation，如 `no further`／
  `gram negative`，表面像否定詞但不是）與「真否定詞」，且真否定詞再依
  「詞在前」（`no` * `UMLS詞`）／「詞在後」（`UMLS詞` * `without`）分兩條
  正規表示式，**中間允許 0–5 個詞的間隔**。本論文 `_SCOPE_MODIFIER_PATTERN`
  目前只做「詞是否出現在候選字串中」的整體比對（無此間隔窗口設計），是
  比 NegEx 更簡化的版本——因為本專案的候選字串本身就是短法律語素（通常
  5-10字），不像臨床病歷句子需要在長句中定位觸發詞與目標詞的相對位置。
- 論文誠實列出失敗案例（如「hepatitis」在「Hepatitis A negative」誤判、
  「versus」PPV僅0%）並提出後續應對——這種「規則清單非窮盡、依真實案例
  逐步擴充」的立場，與本論文 `_QUANTITY_PATTERN`→`_MEASURE_PATTERN`→
  `_SCOPE_MODIFIER_PATTERN` 的擴充脈絡一致，是選擇規則式路線（而非訓練
  分類器）時參考的既有先例，而非本論文守衛規則本身的直接來源。

## 誠實聲明

三篇文獻皆為**問題定位**與**方法論路線選擇**的佐證，本論文的守衛規則本身
（`_QUANTITY_PATTERN`／`_MEASURE_PATTERN`／範圍修飾詞清單，若後續實作）查無
直接文獻先例，是針對本語料實測案例逐步歸納出的工程設計，屬於第三章 3.8 節
「本論文自行設計的工程決策」分類，非直接複用任一篇文獻的演算法或程式碼。

## 尚未查證／待辦

- [x] NegEx 全文合法免費來源已找到並精讀（2026-09-05，共同作者官方主頁存檔）。
- [ ] 範圍修飾詞守衛（`_SCOPE_MODIFIER_PATTERN`：增加／額外／追加／新增）設計已定案
      （見報告29），程式碼尚未實作——需等 c15949bf 全量重抽完成、抽取端凍結後才動。
