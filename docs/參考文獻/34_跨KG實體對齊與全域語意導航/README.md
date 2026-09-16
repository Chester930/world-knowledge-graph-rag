# 34_跨KG實體對齊與全域語意導航

對應 `docs/報告/59_跨KG實體對齊與全域語意導航設計概念記錄.md`（2026-09-16 針對「跨資料庫（不同kg_id）之間的語意實體對齊」這個具體問題的文獻查證）。

## 查證背景

報告59開頭列的「相關文獻」（CESI、Incremental Multi-source Entity Resolution、Confidence-Based Cascade Deferral）經2026-09-15核實確認全部真實存在，但2026-09-16複查發現**這三篇都是從其他既有子問題借來的**——CESI／Saeedi et al. 2020原本是為3.4節「單一KG內部、隨文件擴增的別名聚類」找的佐證，Jitkrittum et al. 2023原本是為3.1.3節「關係型別embedding信心不足才交LLM仲裁」找的佐證。報告59要解決的「兩個完全獨立的KG資料庫之間，Entity是否語意等價」是學界正式稱為 **Entity Alignment (EA) / Knowledge Graph Alignment** 的獨立研究領域，先前查證沒有真的找過這個領域的文獻。本資料夾是針對這個缺口重新查證的結果。

## 內容清單

| 檔案 | 文獻 | 來源 | 全文狀態 |
|---|---|---|---|
| `suchanek-et-al-2011-paris.pdf` | Suchanek, Abiteboul & Senellart (2011)，*PARIS: Probabilistic Alignment of Relations, Instances, and Schema*，**VLDB 2011**（Proceedings of the VLDB Endowment, Vol 5, No 3, pp.157-168） | [arXiv:1111.7164](https://arxiv.org/abs/1111.7164)；[官方repo dig-team/PARIS](https://github.com/dig-team/PARIS) | 📥 已下載（12頁，2026-09-16，首頁標題/作者已核）；🟢 已用python直接解析全文核對關鍵機制段落（非逐字精讀全文，但核心機制段落已逐字核對） |
| `cheng-et-al-2025-easyea.pdf` | Cheng, Lu, Yang, Chen & Zhang（東北大學，2025），*EasyEA: Large Language Model is All You Need in Entity Alignment Between Knowledge Graphs*，**ACL Findings 2025**（pp.20981-20995） | [ACL Anthology 2025.findings-acl.1080](https://aclanthology.org/2025.findings-acl.1080/) | 📥 已下載（15頁，2026-09-16，首頁標題/作者/會議頁碼已核）；🟢 已用python直接解析全文，含方法章節與全文關鍵字掃描（confidence/reject/threshold等） |

## 各文獻在本設計中的角色

### 1. PARIS（Suchanek et al. 2011，VLDB）——訓練式方法出現前的經典先例，直接支持「機率門檻決定對齊、允許不對齊」

python直接解析PDF全文核對（非透過摘要轉述）確認：

- **完全不需要訓練資料或種子對齊**——原文："It does not need training data and it does not require any parameter tuning."
- **核心是機率估計，不是二元分類**——每一對候選實體/關係/類別都算出一個equivalence機率 `Pr(x≡x′)`，"our implementation thresholds the probabilities and assumes every value below θ to be zero"。
- **明確證明機率分數是有效的信心訊號**——Figure 1 直接畫出「機率門檻 vs 人工核實precision」的關係，**precision隨門檻θ提高而顯著上升**（實測於YAGO⊆DBpedia），這是報告59「高信心直接對齊、灰區才需要仲裁」這個設計假設**目前找到最直接的實證支持**：機率分數確實跟人工核實的正確率正相關，不是拍腦袋假設。
- **原生支援「不是每個實體都有對應」（open-world）**——README與論文設計本身都是「找出有對應的部分」而非強制每個實體都要配對，跟報告59「應拒絕對齊的近義詞與上下位詞」這類P0黃金測試集需求的架構精神一致。

**誠實侷限**：這是2011年、深度學習/LLM出現前的方法，核心靠字串/結構共現統計（functionality-based reasoning），沒有embedding、沒有LLM仲裁這個現代機制；報告59設計的「canopy字串→embedding→LLM仲裁灰區」三階段裡，只有「機率門檻決定要不要進一步處理」這個大原則跟PARIS一致，具體演算法完全不同代。且PARIS在論文裡的實測案例（YAGO/DBpedia/IMDb，百科全書型通用知識庫）跟本專案的法規領域KG性質差異很大，precision數字（90%+）不能直接當作本專案的預期值。

### 2. EasyEA（Cheng et al. 2025，ACL Findings）——LLM仲裁候選選擇的直接先例，但缺少報告59最需要的「拒絕對齊」機制

python直接解析PDF全文（非透過網頁摘要轉述，因ScienceDirect/PDF網頁摘要皆抓取失敗，改用pypdf本地解析）確認三階段方法：

1. **Information Summarization**：LLM把entity name/attribute triples/relation triples摘要成一段文字，代表該實體的語意。
2. **Embedding and Feature Fusion**：把摘要文字embedding，融合多種特徵表示。
3. **Candidate Selection**：階層式策略，先用embedding相似度篩出top-10候選（依Hits@10慣例選定），再由LLM在這10個候選裡做最終選擇。

架構上跟報告59 §3.2規劃的「字串canopy→embedding canopy→型別/領域過濾→高信心直接對齊→灰區LLM/人工仲裁」高度相似（都是「先用便宜的方法縮小候選、再用LLM做精細判斷」的兩階段/三階段設計）。在DBP15K／ICEWS等標準跨語言benchmark上Hits@1達到0.99+，全面超越BootEA/RDGCN/ChatEA等訓練式方法。

**⚠️ 重大誠實侷限（對報告59而言是關鍵缺口）**：對全文做關鍵字掃描確認——**"confidence"／"reject"／"null"／"not aligned" 在全文zero命中，"threshold"僅1次、"unmatched"僅1次**。EasyEA評測用的DBP15K/ICEWS是**封閉世界、強制1:1對齊的benchmark**（每個來源實體都假設在目標KG裡「一定有」一個正確答案，任務只是從候選裡選出哪一個，不是判斷「要不要對齊」）。**這代表EasyEA的方法完全沒有處理報告59 P0黃金測試集裡最關鍵的一類案例——「應拒絕對齊的近義詞與上下位詞」「同名異義」**：EasyEA的LLM Candidate Selection階段設計上一定會從top-10候選裡選一個出來，沒有「這10個都不是」的選項。若要採用EasyEA的三階段架構，報告59必須自己在Candidate Selection後面**額外加一道「這個候選是否真的等價，還是只是最相似但不該對齊」的判斷**，這件事在EasyEA原文裡完全沒有先例可循，是本專案要填的真正空白，不能假裝EasyEA已經解決了這個問題。

## 對報告59的結論

**修正後的誠實結論**：跟報告58的情況類似——文獻確實存在且方向對題，但沒有一篇能直接複製貼上解決報告59的核心設計問題。PARIS佐證「機率/信心分數可以有效區分該不該對齊」這個大方向有超過10年的實證基礎、且天然支援拒絕對齊；EasyEA佐證「embedding候選+LLM精細判斷」這個兩階段架構在最新benchmark上有效，但**完全沒有處理「該不該對齊」這個報告59最在意的問題**，只處理「在確定要對齊的前提下選哪一個」。

**報告59 §4 P0規劃的黃金測試集**（跨KG近義、同名異義、字面相似數值不同、型別不一致但實體相同、應拒絕對齊的近義詞與上下位詞）——這五類裡，只有「跨KG近義」「型別不一致但實體相同」這兩類在EasyEA的benchmark任務範式下有直接對應（DBP15K/ICEWS本質上就是在測這個）；「應拒絕對齊」這一類在兩篇找到的文獻裡都沒有直接的方法論先例（PARIS雖然架構上允許no-match，但論文沒有專門設計/評測「刻意混入近義詞/上下位詞陷阱」這種對抗性測試），**必須靠本專案自己設計驗證方式，不是借用既有方法就能過關**。

## 待辦

- [ ] 若報告59排入實作，PARIS原文的機率計算公式（functionality-based reasoning，Equation 12/17一帶）需要逐式精讀，確認是否可以簡化成本專案「canopy+embedding cosine」場景下的可操作規則，而非直接照搬其relation functionality前提（本專案的SVO三元組關係型別數量、性質跟PARIS原文的通用RDF關係不同，需另外評估）。
- [ ] EasyEA的Information Summarization階段（LLM把entity的attribute/relation摘要成文字再embedding）跟本專案`Entity.name_embedding`的產生方式（見`services/svo_service.py`）路數不同——本專案目前只embedding實體名稱字串，未整合attribute/relation上下文；若採用EasyEA精神，需評估是否要換成「摘要後embedding」，這是與現行架構的落差，需要另外設計成本效益評估。
- [ ] OAEI（Ontology Alignment Evaluation Initiative）作為業界標準黃金測試集建構方法論，本次查證範圍未涵蓋，若P0黃金測試集要有更嚴謹的方法論依據，可作為下一步查證方向。
