# 17_抽取完整性與召回率驗證

對應 `docs/報告/19_SVO抽取完整性自我核對機制設計報告.md`（設計中，**尚未實作**）；`docs/論文/02_文獻探討.md` § 2.4.4（RQ4a 延伸）；`docs/論文/03_系統設計與方法論.md` § 3.1.3「附加規定完整性」段落。

## 起點

2026-08-31，報告18的追加驗證發現規則7（`services/svo_service.py::_svo_prompt()` 的 few-shot 反例／正例修補）遇到範例沒示範過的附加規定類別（如「以小時為請假單位」這種方式/單位彈性，規則7原本只示範數量上限/次數限制/期限/工資狀態四類）仍會漏抓。使用者指出這種「案例驅動、持續累積範例清單」的做法本質上不是通用架構，違背初衷，要求設計一個真正通用的解法。

報告19提議借用本專案已有的事實接地性核對機制（`docs/報告/16_事實接地性核對機制設計報告.md`，草稿→核對→修正）的架構精神，鏡像到「抽取內容有沒有少說（遺漏）」這個方向。初版設計（v1：整包把原文＋已抽三元組丟給LLM問「有沒有遺漏」）是憑直覺類比、無文獻依據；全文精讀本資料夾兩篇文獻後發現，兩篇實際做法都不是這樣——都是先用**非LLM/輕量機制**局部定位可能遺漏的片段，才**針對性**觸發LLM補抽，據以修正為v2設計。完整設計演變過程見報告19全文。

## 內容清單

| 檔案 | 文獻 | 來源 | 狀態 |
|---|---|---|---|
| `yang-et-al-2026-promem.pdf` | Yang, Sun, Wei & Hu (2026), *Beyond Static Summarization: Proactive Memory Extraction for LLM Agents* | arXiv:[2601.04463](https://arxiv.org/abs/2601.04463) | ✅ 已下載並精讀全文（2026-08-31）；🟡 尚未查證是否已通過同行評審，僅為 2026 年 1 月的 arXiv 預印本 |
| `liu-et-al-2025-verifact.pdf` | Liu, Zhang, Munir, Gu & Wang (2025), *VeriFact: Enhancing Long-Form Factuality Evaluation with Refined Fact Extraction and Reference Facts*，v2 (2025-09-26) | arXiv:[2505.09701](https://arxiv.org/abs/2505.09701) | ✅ 已下載並精讀全文（2026-08-31）；🟡 尚未查證是否已被正式會議/期刊接受，仍為 arXiv 預印本 |

## 各文獻角色

| 文獻 | 角色 |
|---|---|
| **Yang, Sun, Wei & Hu (2026) ProMem** | 報告19 §3「涵蓋比對＋針對性補抽」v2設計的**直接方法論來源**——其 Memory Completion 演算法：對每個來源單位（原論文情境為對話輪）計算與已抽記憶項目的 cosine 相似度，`>τmatch=0.6` 視為已涵蓋，未涵蓋單位收集後**只對這些**做第二次 LLM 抽取，再合併。本論文將「來源單位」由對話輪改為 chunk 內每句原文（`svo_index.json` 各chunk已有的 `original_sentences` 欄位），演算法結構直接沿用。實驗：GPT-4o-mini 主要抽取模型、GPT-4o 評判、Qwen3-Embedding-8B 語意比對，HaluMem／LongMemEval 資料集，Llama3-8B 小模型驗證。消融實驗（Table 2）比較 w/o MC／w/o MV／w/o MC&MV 三種變體，證實兩模組「both essential」；Memory Integrity 42.91%（Mem0基線）→73.80%（ProMem），單獨補完步驟貢獻 54.03%→73.80%。⚠️ **誠實聲明**：原論文情境為多輪對話記憶抽取，與本論文法規文本SVO抽取的領域與模型組合不同；`τmatch=0.6` 門檻值直接沿用，未針對本專案中文法規語料與 `bge-m3` embedding 模型重新校正；未見公開程式碼倉庫。本設計（報告19）**尚未實作**，此文獻目前僅支撐設計階段的方法論選擇，非已落地程式碼的依據 |
| **Liu, Zhang, Munir, Gu & Wang (2025) VeriFact** | 佐證「先用非LLM/輕量機制定位遺漏片段、再用LLM針對性補完」這個架構方向並非單一論文的孤立主張——在 SAFE 的 decompose-decontextualize-verify 流程中插入 Detect＋Refine 兩個新階段：不完整事實偵測用三個LLM（GPT-4o／Llama 3.3-70B／Qwen 2.5-32B）ensemble取union合併提升recall；遺漏事實偵測用 **word-mapping（最長公共子串）演算法**（非LLM，純字串比對）定位原文中未被抽取結果涵蓋的片段，再用LLM判斷是否構成有意義的遺漏（僅聚焦時間性/因果關係兩類PDTB一級關係），最後補寫。量化效果（Table 2）：不完整事實比例56.7%→22.5%（↓60.3%）、遺漏事實數1.22→0.76（↓37.7%）、人類事實覆蓋率77.5%→87.1%（↑12.4%）；人工精煉後24.9%的事實正確性標籤改變，證實遺漏context確實會導致對模型事實性的誤判。⚠️ **誠實聲明**：原論文情境為長篇LLM回應的事實性評估（非結構化SVO抽取），word-mapping演算法本身是字串比對，與本論文（報告19）改採的 embedding 相似度比對機制不同（選用 embedding 是為了與既有抽取管線的向量基礎設施一致，非直接套用 VeriFact 的字串比對法），僅佐證「兩階段：定位→補完」這個大方向有多篇獨立文獻支持，具體演算法不可直接套用；程式碼倉庫僅見 HuggingFace Space（`launch/factrbench`），未見完整GitHub開源。同上，本設計**尚未實作** |

## 對照組（不列入正式文獻，僅供設計取捨參考）

**Google `google/langextract`**（開源專案，即時查證 **38,512★**，`gh api`，2026-08-31，`archived: false`，4天前有新push）——Google官方維護的LLM結構化抽取函式庫，`extraction_passes=N` 參數官方文件明確標註「Improves recall through multiple passes」，用於解決長文件的「needle-in-a-haystack」召回問題，機制是對整份文件做N次**獨立完整重抽**再合併（ensemble式），**沒有先定位遺漏片段的步驟**——是報告19刻意不採用的對照組（暴力多次重抽，成本比ProMem/VeriFact的「先定位、再局部補抽」更高），見報告19 §3「比v1好在哪」。

## 待辦

- [ ] 若報告19的 v2 設計確認採用並進入實作，本資料夾兩篇文獻應在實作驗證後（真實觸發率、耗時增幅、5+2題品質比對）補上「已落地程式碼」的狀態更新，比照 `16_少樣本提示範例干擾/README.md` 的既有慣例
- [ ] ProMem／VeriFact 目前皆為 arXiv 預印本（🟡），若確認採用此設計方向，建議追蹤是否有後續正式發表版本（如 ACL/EMNLP/NeurIPS 系列 Rolling Review 結果），比照本論文對 Dhuliawala et al. (2023) 從 arXiv 追蹤到 ACL 2024 Findings 正式發表的既有做法
- [ ] `google/langextract` 目前僅查證 README/官方文件層級，未實際安裝測試其 `extraction_passes` 實際行為（是否真的完全獨立重抽、合併去重邏輯細節），若後續需要更精確的對照組描述可補齊
