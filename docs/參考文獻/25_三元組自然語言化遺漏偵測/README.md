# 25_三元組自然語言化遺漏偵測

對應 `docs/報告/26_修正後瓶頸探測問答比對報告.md` § 4 #6（自然語言化小失真，
真實案例來源）；`services/svo_service.py::_naturalize_triple()`（`docs/報告/
24_事實清單自然語言化機制設計報告.md`，索引時把三元組改寫成自然語句的機制）。

## 問題陳述

`_naturalize_triple()` 把結構化三元組（`subject`／`verb`／`object`）交給 LLM
改寫成一句自然語句（`natural_text`），prompt 已明確要求「不可以省略主詞或
受詞裡的關鍵資訊」，但真實案例仍會漏掉：

- **真實案例**（報告26 §4 #6，2026-09-05 直查 c15949bf 現行圖譜再次確認
  仍存在——N0050030 這次重抽已跑過，問題未消失）：
  - `subject`＝`災害發生之當月一日起`（正確保留「一日」）
  - `natural_text`＝「從**災害發生之當月起**計算前條所定災後六個月期間。」
    （**漏掉「一日」**）

這跟報告25 §4 發現3（SVO 抽取階段的數值誤綁定）、報告20（生成端答案的量詞
接地核對）是**同一種「輸出遺漏輸入內容」的失真**，但發生在**索引時的
LLM 改寫步驟**（`_naturalize_triple()`），不是抽取階段也不是問答生成階段——
是這條「壓縮輸出鏈」裡尚未覆蓋到的第三個環節。

## 內容清單

| 檔案 | 文獻 | 來源 | 狀態 |
|---|---|---|---|
| `kim-et-al-2024-fables.pdf` | Kim, Chang, Karpinska, Garimella, Manjunatha, Lo, Goyal & Iyyer (2024), *FABLES: Evaluating Faithfulness and Content Selection in Book-Length Summarization*，COLM 2024 | [arXiv:2404.01261](https://arxiv.org/abs/2404.01261)；[GitHub mungg/FABLES](https://github.com/mungg/FABLES) | ✅ 已下載全文（2026-09-05，41 頁） |
| `ji-et-al-2023-rho-entity-coverage.pdf` | Ji, Liu, Lee, Yu, Wilie, Zeng & Fung (2023), *RHO (ρ): Reducing Hallucination in Open-domain Dialogues with Knowledge Grounding*，ACL Findings 2023 | [arXiv:2212.01588](https://arxiv.org/abs/2212.01588)；[GitHub ziweiji/RHO](https://github.com/ziweiji/RHO) | ✅ 已下載全文（2026-09-05，17 頁） |
| （交叉引用，不重複下載）Baek, Aji & Saffari (2023), KAPING | 已存在於 `docs/參考文獻/12_三元組事實層級向量化與檢索/baek-et-al-2023-kaping.pdf` | 已下載（先前工作） |

**誠實查證修正**：搜尋階段一度查到「Maynez et al. (2020) 將 hallucination
與 omission 並列為 unfaithfulness 的兩種互補形式」的說法，**下載全文逐字
搜尋「omission」／「omit」後確認零命中**——該論文只討論 hallucination
（生成不存在於來源的內容），完全沒有討論 omission（遺漏來源內容），因此
**未採用**此文獻，改用下方兩篇經全文核實、確實討論 omission 的文獻。

## 各文獻在本設計中的角色

### 1. FABLES — Kim et al. (2024) —— 確立「遺漏」是現行 LLM 的普遍失效模式

全文核實：《FABLES》對 5 個 LLM（Claude-3-Opus／GPT-4-Turbo／GPT-4／
GPT-3.5-Turbo／Mixtral）產出的長篇書籍摘要做大規模人工標註（26 本書、
130 篇摘要、3158 則主張），**「首創書籍長度摘要的遺漏錯誤分類法」**
（"the first taxonomy of omission errors in book-length summarization"），
量化結果：受遺漏問題影響的摘要比例 Claude-3-Opus 52.0%、GPT-4-Turbo
80.8%、GPT-4 65.4%、GPT-3.5-Turbo 84.6%、Mixtral 65.4%（原文 Table 6），
且「關鍵事件、細節、主題」是最常被遺漏的內容類別。**佐證「輸出遺漏輸入
關鍵內容」是現行 LLM（含本專案使用的 `qwen2.5:7b`）的普遍、量化證實的
失效模式，非本專案獨有的孤立缺陷**——與報告29引用 Tosun et al. (2026)
的角色相同（證明問題真實且現行）。

### 2. RHO — Ji et al. (2023) —— 給出精確的方法論框架：Entity Coverage Recall

全文核實：RHO 是**知識圖譜對話生成**任務（背景與本專案高度相似——KG事實
→自然語句），論文用 **Entity Coverage（Precision／Recall／F1）** 當自動
評估指標之一（原文 Table，附完整數字）：Precision 量測「生成文字裡的實體
是否有 KG 依據」（幻覺方向，對應報告20 已實作的量詞接地核對），**Recall
量測「KG 裡的實體是否有被生成文字保留」**（遺漏方向，正是本設計要偵測的
方向）。官方碼 [ziweiji/RHO](https://github.com/ziweiji/RHO) 的 Entity
Coverage 計算依賴實體連結（entity linking）與訓練式模型，**規模遠超本專案
需求**（本專案只需要偵測「三元組裡的量詞/日期片語」這個窄類別，不需要
通用實體連結），不直接複用，僅借用其「Coverage Recall」這個評估框架，
確立本設計的偵測方向在方法論上有明確定位（不是憑空發明的檢查方向）。

## 誠實聲明

兩篇文獻皆為**問題定位**（遺漏是真實、現行、量化證實的失效模式）與
**方法論框架**（Coverage Recall 這個評估角度）的佐證，本設計的偵測機制
本身（正規表示式核對 `_QUANTITY_PATTERN`／`_MEASURE_PATTERN` 命中的片語
是否逐字留在 `natural_text` 裡）查無直接文獻先例——兩篇文獻的實作皆依賴
訓練式模型或實體連結，本專案改用與報告20「量詞接地核對」相同的規則式
比對，屬於本論文自行設計的工程決策（第三章 3.8 節分類），是報告20 機制
（比對輸出是否新增未依據內容）的**鏡像版本**（比對輸出是否遺漏應保留
內容）——同一個「比對輸出與輸入」架構家族的第三個實例（第一個是報告19
抽取完整性自我核對、第二個是報告20 量詞接地核對）。

## 尚未查證／待辦

- [ ] 若後續發現除量詞/日期外的其他遺漏類型（如地名、機關名稱），本設計
      的規則式清單需要擴充，比照 `_QUANTITY_PATTERN`→`_MEASURE_PATTERN`
      的既有擴充模式，非窮舉。
