# 19_生成端長清單事實遺漏與位置偏誤

對應 `docs/報告/22_乾淨重跑新舊KG問答品質比對報告.md` §5、§5.1。

## 起點

報告22題3真實線上驗證（2026-09-01）：直接攔截`/agent/chat`檢索管線的中間結果，確認「事假 得以 小時為請假單位」這筆三元組**確實被正確抽取、正確通過型別/文件範圍篩選、也確實出現在送給LLM的28行事實清單裡**——但LLM兩次真實重跑都沒有引用它。已排除抽取與檢索管線的問題，缺陷在生成階段：把跟問題最相關的事實排到清單前段（`_sort_lines_by_relevance()`，bigram重疊度排序）雖然把目標事實從第16名推到第11名，但真實重跑仍未解決——需要查證這是否對應已知的文獻現象，而非本專案獨有的怪異行為。

## 內容清單

| 檔案 | 文獻 | 來源 | 狀態 |
|---|---|---|---|
| `liu-et-al-2023-lost-in-the-middle.pdf` | Liu, Lin, Hewitt, Paranjape, Bevilacqua, Petroni & Liang (2023), *Lost in the Middle: How Language Models Use Long Contexts* | arXiv [2307.03172](https://arxiv.org/abs/2307.03172)；後刊登於 TACL 2024（[ACL Anthology](https://aclanthology.org/2024.tacl-1.9/)） | ✅ 🟢 已下載（2026-09-01） |

**核心發現**：LLM 對長輸入內容的效能呈現 U 形（有時稱「峽谷型」）曲線——相關資訊出現在輸入**開頭或結尾**時效能最好，出現在**中段**時效能顯著下降，即使是明確支援長上下文的模型也一樣。這與報告22的真實觀察**高度吻合**：目標事實被bigram排序推到第11名（28行清單中，約在中段偏前），仍落在效能低谷區間，未能被穩定引用。這給了報告22 §5.1「低成本方案方向正確但沒解決問題」一個文獻層級的解釋，而非單純歸咎於LLM隨機性。

**現成程式參考**：LangChain 的 `langchain_community.document_transformers.LongContextReorder`（[原始碼](https://sj-langchain.readthedocs.io/en/latest/_modules/langchain/document_transformers/long_context_reorder.html)，MIT授權，可直接參考演算法邏輯）直接實作此論文的緩解對策——**不是單純由高到低線性排序**，而是把「已依相關性排序」的清單做 zigzag 重新分佈，讓最相關的項目落在**首尾兩端**、最不相關的落在正中央：

```python
def _litm_reordering(documents):
    """documents 須已依相關性由高到低排序。"""
    documents.reverse()
    reordered_result = []
    for i, value in enumerate(documents):
        if i % 2 == 1:
            reordered_result.append(value)      # 次相關的依序疊加到尾端
        else:
            reordered_result.insert(0, value)   # 更相關的依序疊加到開頭
    return reordered_result
```

追蹤7筆輸入（依相關性 rank1~7）後可驗證：rank1落在position 0（開頭）、rank2落在position 6（結尾）、rank7（最不相關）落在position 3（正中央）——確實把「首尾強、中段弱」的注意力曲線納入排列設計。

**與報告22現況的落差**：本專案目前的 `_sort_lines_by_relevance()` 只做了「由高到低線性排序」，沒有做LiTM風格的首尾分佈——即使排序訊號本身準確，rank11這種中段名次依然會落在效能低谷。且排序訊號本身（bigram重疊度）也偏弱，目標事實只被推到第11名（28筆中），距離「排進前3名」還有相當落差，反映的是**兩個獨立缺口**：(1) 相關性訊號不夠準（bigram vs. 更精確的embedding相似度或cross-encoder rerank）、(2) 即使排序準了，線性排序本身也不是LiTM文獻建議的最佳擺放方式。

**額外背景（非正式論文引用，屬業界實務共識，不套用🟢/🟡分級）**：cross-encoder rerank + truncate-to-top-K 是業界常見的兩段式RAG檢索標準做法（先廣後精：粗篩50筆→rerank→只留K=3~7筆送進LLM context），多篇部落格/技術文章（如 [Towards Data Science](https://towardsdatascience.com/advanced-rag-retrieval-cross-encoders-reranking/)、[Vstorm](https://vstorm.co/rag/advanced-rag-pipeline-part-1-rerankers/)）皆有記載，但未查得單一權威同行評審論文可對應引用，故不下載存檔，僅供設計參考。

## 待辦

- [ ] 評估是否要把 `_sort_lines_by_relevance()` 升級為：(a) embedding相似度排序取代bigram（更準的訊號）＋(b) 移植上方LiTM zigzag重排演算法（更好的擺放策略）＋(c) 截斷到前K筆（降低整體清單長度、間接縮小「中段低谷」的範圍）。三者可分階段驗證。
