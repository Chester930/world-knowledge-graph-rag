# 35_同來源Fact冗餘去噪與多樣性檢索

對應 `docs/報告/57_檢索品質解耦評測與知識圖譜場景化角色SDD任務書.md` §7.4待辦「同一來源文件的Fact在top-k裡的多樣性上限（diversity cap）」——2026-09-16針對`57-AGGR2`案例（N0060015一份文件的342個Fact，主題相近但答非所問的內容霸佔`vector_search_facts()`top_k=20的名額，稀釋掉真正需要的2-3筆跨文件事實）重新查證的文獻。

## 內容清單

| 檔案 | 文獻 | 來源 | 全文狀態 |
|---|---|---|---|
| `goldstein-carbonell-1998-mmr.pdf` | Goldstein & Carbonell (1998)，*Summarization: (1) Using MMR for Diversity-Based Reranking and (2) Evaluating Summaries*，TIPSTER Text Program Phase III（同一方法另有SIGIR '98 2頁短文版，本檔為ACL Anthology開放取用的完整版） | [ACL Anthology X98-1025](https://aclanthology.org/X98-1025/)；SIGIR版DOI [10.1145/290941.291025](https://dl.acm.org/doi/10.1145/290941.291025) | 📥 已下載（15頁，2026-09-16，首頁標題/作者/機構已核）；🟡 python解析全文核對動機段落，公式段落因PDF數學符號提取失真未能逐字核對（見下方誠實侷限），公式本身為業界廣泛引用的標準形式，非本次查證產生 |
| `ross-et-al-2026-retriever-redundancy-diversity-rag.pdf` | Ross, Koopman, van der Vegt & Zuccon（University of Queensland／CSIRO，2026），*How retriever redundancy and diversity impact RAG effectiveness* | [arXiv:2608.13956](https://arxiv.org/abs/2608.13956) | 📥 已下載（9頁，2026-09-16，首頁標題/作者/機構已核）；🟡 WebFetch查證核心數據 |
| `khan-et-al-2026-df-rag.pdf` | Khan, Hong, Wu, Lybarger, Yin, Babinsky & Liu（George Mason University + Capital One，2026），*DF-RAG: Query-Aware Diversity for Retrieval-Augmented Generation* | [arXiv:2601.17212](https://arxiv.org/abs/2601.17212) | 📥 已下載（22頁，2026-09-16，首頁標題/作者/機構已核）；🟢 python直接解析方法章節（§3.1-3.4），公式逐式核對 |

## 各文獻在本設計中的角色

### 1. MMR（Goldstein & Carbonell, 1998）——經典源頭，動機案例與本專案的情境近乎逐字對應

python解析全文確認開頭動機案例：使用者查詢「airline crash」，IR引擎回傳前100篇文件，第一篇是TWA-800空難的高度相關文件，但接下來30篇「同樣關於TWA-800、內容高度重複」——"Relevant? Yes. Useful? Decreasingly so."——**這跟N0060015的342個Fact裡許多同主題（防護具/監測設備）不同細項擠滿top-20、稀釋掉真正需要的跨文件事實，是同一種現象的不同領域案例**。核心主張：純相關性排序在候選池高度冗餘時不夠用，必須額外考慮「跟已選項目的新穎度/差異度」。

標準MMR公式（廣泛引用之形式，非本次從PDF逐式核對，見下方誠實侷限）：
```
MMR = argmax_{Di∈R\S} [ λ·Sim1(Di,Q) − (1−λ)·max_{Dj∈S} Sim2(Di,Dj) ]
```
`λ`是相關性與多樣性的權衡係數，`Sim1`是候選項與查詢的相似度，`Sim2`是候選項與「已選集合S中每個項目」的相似度、取最大值（懲罰跟已選項目太像的候選）。

**誠實侷限**：這是1998年方法，PDF公式段落因數學符號在pypdf解析下失真（非本次能逐字核對），但上方公式是被DF-RAG（見下方）等大量後續論文逐式引用確認的標準形式，非本次自行推導。MMR本身沒有「同一來源文件」這個維度的設計——它是對「候選項與候選項」的相似度做懲罰，不是對「候選項與其來源文件」做懲罰；若要直接套用在「同一份文件的Fact互相擠壓名額」這個具體場景，需要額外設計（例如把`Sim2`换成「與同文件已選Fact的相似度」或直接做「同文件名額上限」這種更陽春的規則式版本）。

### 2. Ross et al. 2026（arXiv:2608.13956）——直接證實「同來源冗餘內容對答案準確度沒有幫助」，但沒給解法

WebFetch查證核心數據：控制實驗顯示——**完全重複的文件、LLM改寫版本的重複文件，對答案準確度都沒有顯著幫助；但提供跨文件/跨類型的多樣化文件，能讓答案準確度提升17%-47%**，改善主要來自「不同文件類型間的多樣性」而非單純「有更多相關答案可用」。這直接支持本專案「N0060015內部同主題但答非所問的Fact是純粹噪聲、不是有效冗餘」這個診斷——即使這些Fact字面上跟問題有點相關，重複的同源內容並不會增加答案正確率。

**誠實侷限**：這是一篇**現象診斷/實證研究，論文本身沒有提出具體的技術解法**——摘要只提到這個發現「為未來的多樣性感知重排序方法提供動機」，不能拿來當作「該怎麼做」的依據，只能當作「這個問題值得解決」的實證佐證。

### 3. DF-RAG（Khan et al., 2026）——把MMR用在RAG上的直接先例，含具體公式與两個複雜度層級

python直接解析§3.1-3.4方法章節，確認**兩個層級的設計，複雜度差異大，需要分開評估**：

**層級A（簡單，零額外LLM呼叫）——`gMMR`固定`λ`版本**（論文§3.2「Baseline」）：
```
gMMR(c) = λ·cos(q⃗, c⃗) + (1−λ)·√(2 − 2·cos(c⃗, c⃗_S))
```
`c⃗_S`是「已選集合S」的centroid（平均向量），用歐氏距離變體取代標準MMR的pairwise cosine懲罰（論文聲稱此變體實測效果更好，見附錄B.2）。貪婪逐步選取：第一筆選純相關性最高者，之後每一步從剩餘候選中選`gMMR`分數最高者。**這個版本只需要embedding cosine計算，不需要額外LLM呼叫，符合本專案「簡單版本、不搶Ollama資源」的原則**——`λ`在`[0,1]`區間固定值，論文用網格搜尋找每個資料集的最佳值。

**層級B（複雜，需要額外LLM呼叫）——DF-RAG完整架構**（論文§3.4）：在層級A的`gMMR`外面包一層「LLM-based Planner與Evaluator」，於測試時**動態**幫每個查詢決定最適合的`λ`，不需要額外訓練/微調，但**每個查詢會多打LLM呼叫**（Planner規劃、Evaluator評估）。論文聲稱F1比固定`λ`基準再提升，但沒有查證具體提升幅度（本次未精讀實驗章節數字）。

**對本專案的意義**：層級A（固定`λ`的geometric MMR）完全符合「先做簡單版本、不消耗額外Ollama LLM呼叫」的原則——只是在`_arrange_fact_lines()`現有的embedding cosine計算基礎上，多算一個「跟已選Fact集合的centroid距離」，純數學運算。層級B（動態λ的LLM Planner/Evaluator）**會增加每次查詢的LLM呼叫數，正是這次資源競爭問題想避免的方向**，若要採用需另外評估延遲/資源成本，不應該是第一步。

## 對報告57 §7.4的結論

**建議路線**：先實作MMR層級A的簡化版——不是完整的candidate-vs-candidate pairwise懲罰，而是**針對本專案的具體症狀（同一`source_doc_id`的Fact霸佔名額）做規則式簡化**：對`vector_search_facts()`回傳的候選池，比照`_arrange_fact_lines()`現有的`_BFS_KEEP_MAX`精神，加一個「同一`source_doc_id`最多佔`N`個top-k名額」的硬上限，或更接近DF-RAG精神的「候選與『已選同文件Fact集合』的cosine距離」懲罰——兩者都不需要額外LLM呼叫，可以在檢索完成後、`_arrange_fact_lines()`之前的環節加一道規則式後處理。**動態λ（DF-RAG完整版）留待簡單版本驗證有效後，再評估是否值得付出額外LLM呼叫的成本。**

## 待辦

- [ ] 若排入實作，MMR公式的PDF逐式核對（因本次pypdf解析數學符號失真而跳過）需要用其他方式補齊（例如查另一份OCR品質較好的版本，或人工開啟PDF閱讀器核對），目前只核對到文字動機段落與被DF-RAG引用的轉述公式，未達到本repo其他核心文獻的逐式精讀標準。
- [ ] DF-RAG實驗章節（F1提升具體數字、與固定λ基準的差距）尚未精讀，若要引用其動態λ設計的效果數字需要另外查證。
- [ ] Ross et al. 2026是2026年剛發表的實證研究，尚未有其他論文引用驗證其結論可重現性，需留意這是新發表文獻、非久經考驗的定論。
