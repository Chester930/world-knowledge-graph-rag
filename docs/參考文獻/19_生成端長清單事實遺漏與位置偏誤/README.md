# 19_生成端長清單事實遺漏與位置偏誤

對應 `docs/報告/22_乾淨重跑新舊KG問答品質比對報告.md` §5、§5.1；`docs/論文/02_文獻探討.md` § 2.4.7（自我精煉檢索迴圈，RQ3）；`docs/論文/03_系統設計與方法論.md` § 3.6。

## 起點

報告22題3真實線上驗證（2026-09-01）：直接攔截`/agent/chat`檢索管線的中間結果，確認「事假 得以 小時為請假單位」這筆三元組**確實被正確抽取、正確通過型別/文件範圍篩選、也確實出現在送給LLM的28行事實清單裡**——但LLM兩次真實重跑都沒有引用它。已排除抽取與檢索管線的問題，缺陷在生成階段：把跟問題最相關的事實排到清單前段（`_sort_lines_by_relevance()`，bigram重疊度排序）雖然把目標事實從第16名推到第11名，但真實重跑仍未解決——查證後發現這對應已知的文獻現象，而非本專案獨有的怪異行為。

## 內容清單

| 檔案 | 文獻 | 來源 | 狀態 |
|---|---|---|---|
| `liu-et-al-2023-lost-in-the-middle.pdf` | Liu, Lin, Hewitt, Paranjape, Bevilacqua, Petroni & Liang (2023), *Lost in the Middle: How Language Models Use Long Contexts* | arXiv [2307.03172](https://arxiv.org/abs/2307.03172)；後刊登於 TACL 2024（[ACL Anthology](https://aclanthology.org/2024.tacl-1.9/)） | ✅ 🟢 已下載並精讀核心章節（2026-09-01） |
| `jin-et-al-2025-long-context-rag.pdf` | Jin, Yoon, Han & Arık (2025), *Long-Context LLMs Meet RAG: Overcoming Challenges for Long Inputs in RAG* | arXiv [2410.05983](https://arxiv.org/abs/2410.05983)，後刊登於 ICLR 2025（[會議PDF](https://proceedings.iclr.cc/paper_files/paper/2025/file/5df5b1f121c915d8bdd00db6aac20827-Paper-Conference.pdf)），作者UIUC與Google Cloud | ✅ 🟢 已下載並精讀 §3、§4「Retrieval Reordering」核心章節（2026-09-01）；官方無程式碼釋出（已查證） |
| `nogueira-cho-2019-passage-reranking-bert.pdf` | Nogueira & Cho (2019), *Passage Re-ranking with BERT* | arXiv [1901.04085](https://arxiv.org/abs/1901.04085)，MS MARCO passage ranking 榜首、確立 cross-encoder rerank 為業界標準做法 | ✅ 🟢 已下載並精讀摘要與核心方法（2026-09-01） |

## 核心發現

**Liu et al. (2023/2024)**：LLM 對長輸入內容的效能呈 U 形曲線——相關資訊出現在輸入**開頭或結尾**時效能最好，出現在**中段**時效能顯著下降，即使是明確支援長上下文的模型也一樣。這與報告22的真實觀察**高度吻合**：目標事實被bigram排序推到第11名（28行清單中，約在中段偏前），仍落在效能低谷區間，未能被穩定引用。

**Jin et al. (2025, ICLR)**——比 Liu et al. 更進一步，直接給出**正式的緩解演算法**與**演算法邊界條件**的實證資料，兩者都對報告22的後續建議有直接影響：

1. **檢索段落越多不必然越好**：長上下文LLM在RAG中，輸出品質隨檢索段落數增加「先升後降」，根因是「hard negatives」（表面相關但實際無助於回答的段落）的稀釋效應——直接呼應報告22 §5「限制事實清單長度」這個建議方向，且給出了具體因果機制解釋（不只是「訊噪比」這種籠統說法）。
2. **正式的 Retrieval Reordering 演算法**（論文式1）：給定依相關性分數遞減排序的段落 $d_1, d_2, \ldots, d_k$，重排後的位置為

   $$\text{Order}(d_i) = \begin{cases} \frac{i+1}{2} & \text{if } i \bmod 2 = 1 \\ \frac{(k+1)-i}{2} & \text{if } i \bmod 2 = 0 \end{cases}$$

   效果是把最相關的段落交替放到序列的**開頭和結尾**，讓「hard negatives」自然被擠到中段的效能低谷區——與 LangChain `LongContextReorder`（[原始碼](https://sj-langchain.readthedocs.io/en/latest/_modules/langchain/document_transformers/long_context_reorder.html)，MIT授權）的zigzag演算法邏輯完全一致，等於是同一個緩解策略同時有**開源程式碼參考**（LangChain）與**正式peer-reviewed驗證**（Jin et al. 2025）雙重佐證。
3. **⚠️ 關鍵邊界條件（對報告22的建議有直接修正作用）**：論文實證發現「retrieval reordering **在檢索集合較小時效果不明顯**，只有在檢索段落數量較大時才顯著且穩定優於原始排序」。這代表報告22 §5原先提出的「(a) 更準的相關性排序＋(b) LiTM重排＋(c) 截斷到前K筆」**不是單純可以疊加的三件事**——截斷到很小的K（如3-7筆）之後，清單已經沒有夠大的「中段」可以造成低谷效應，此時再疊加LiTM重排的邊際效益很低；LiTM重排真正發揮效果的情境，是「清單長度仍然偏大、無法大幅截斷」的場合（例如本專案BFS檢索常一次撈回30-50+筆三元組，若因涵蓋率考量不願大砍K值）。**修正後建議**：優先評估能不能安全截斷到小K值（若可以，問題直接消失，不需要額外實作重排邏輯）；若因涵蓋率／召回率顧慮不能大幅截斷，才需要疊加LiTM重排。

**Nogueira & Cho (2019)**：確立 cross-encoder（query 與 passage 串接後由 BERT 直接判斷相關性）作為 passage re-ranking 的標準做法，MS MARCO 榜首、多篇後續 rerank 工作的基礎引用。與本專案現況的落差：cross-encoder需要額外一個模型服務與較高延遲成本（每個候選都要重新過一次encoder），比embedding-cosine-similarity（複用既有 `EmbeddingProvider`）成本高得多——列為報告22「相關性訊號升級」路徑的**進階選項**，非優先實作項目，優先仍是embedding cosine similarity（複用既有基礎設施，成本低很多）。

## 實作參考（2026-09-01 補齊，見報告23）

**Jin et al. (2025) 本身無官方程式碼釋出**（已查證，2026-09-01）——查無對應GitHub倉庫。改用兩個互補的LangChain開源元件作為截斷與重排兩個步驟各自的程式參考（皆MIT授權）：

- **`LongContextReorder`**（`langchain_community.document_transformers`）——zigzag重排步驟的參考，演算法已完整擷取於本README「核心發現」段落。
- **`EmbeddingsFilter`**（`langchain_community.retrievers.document_compressors`，[原始碼](https://sj-langchain.readthedocs.io/en/latest/_modules/langchain/retrievers/document_compressors/embeddings_filter.html)）——**截斷**步驟的參考。核心邏輯：

  ```python
  similarity = self.similarity_fn([embedded_query], embedded_documents)[0]
  if self.k is not None:
      included_idxs = np.argsort(similarity)[::-1][: self.k]
  if self.similarity_threshold is not None:
      included_idxs = [i for i in included_idxs if similarity[i] > self.similarity_threshold]
  ```

  用 `numpy.argsort` 取得依相似度由高到低的索引、切前 `k` 筆，選填再疊加一個相似度門檻做二次過濾。**參數預設值 `k=20`**——與報告23 §3.4 理論推導的初始建議值（15-20）相近，屬獨立來源的交叉印證，非互相抄襲。

## 待辦

- [x] ~~依上方「關鍵邊界條件」修正報告22 §5.1 的建議順序~~——已完成，見報告23。
- [ ] 依報告23設計＋上方兩個開源元件的演算法邏輯，實作 `routers/agent.py` 的截斷與條件式zigzag重排函式（尚未動工，待使用者確認）。
- [ ] embedding相似度排序（複用現有`EmbeddingProvider`）列為近期可實作項目；cross-encoder rerank（Nogueira & Cho路線）列為長期進階選項，非當前優先。
