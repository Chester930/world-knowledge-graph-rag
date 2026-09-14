# 31_Fact-RAG語意排名健壯性

對應 `docs/報告/41_檢索文件範圍改用實體錨定設計報告.md` §9（26-Q5 真因診斷：`vector_search_facts()` 全域語意排名把正解事實擠到第 41 名，被 34 條跨文件同義雜訊擠出 `top_k=20`）；`docs/報告/43_Fact-RAG語意排名健壯性設計報告.md`（本問題的設計提案）。交叉引用 `docs/參考文獻/12_三元組事實層級向量化與檢索/`（Fact 節點的原始 KAPING 式扁平檢索設計，本資料夾要修的正是這個設計的已知侷限）、`docs/參考文獻/21_圖遍歷與向量檢索結果融合/`（RRF 融合機制，本資料夾直接沿用）、`docs/參考文獻/27_當代RAG強基準/`（DPR，B1 已落地的 hybrid dense+BM25 前例）。

## 查證背景（2026-09-14）

報告41 §9 用真實資料查證，26-Q5「當月一日」這條 Fact 確實存在於 KG（抽取沒問題），也確實不在任何錯誤的文件範圍篩選之外（文件範圍本身是對的）——但它在 `vector_search_facts()`（純 cosine 語意相似度 KNN）的全域排名只有第 41 名，被 34 條「其他 7 部勞工保險相關法規的『X 自 Y 起算』」近義但答非所問的事實擠出 `top_k=20` 候選池。這是一個**在文件範圍推導、BFS 遍歷之前就已經發生**的上游檢索缺陷，本專案既有的 Fact 節點設計（KAPING 式扁平 embedding 相似度排序，見 `docs/參考文獻/12/`）本身沒有任何機制能區分「語意相近但屬於不同文件、不同精確語境」的近義事實。

本資料夾查證兩篇 2025 年關於「法律領域混合檢索」與「法律 RAG 檢索可靠性」的文獻，評估是否有可直接借用的方法論。

## 內容清單

| 檔案 | 文獻 | 來源 | 狀態 |
|---|---|---|---|
| `louis-et-al-2024-know-when-to-fuse.pdf` | Louis, van Dijck & Spanakis (2024), *Know When to Fuse: Investigating Non-English Hybrid Retrieval in the Legal Domain* | [arXiv:2409.01357](https://arxiv.org/abs/2409.01357) | 🟡 已下載；abstract + 摘要頁查證（WebFetch，2026-09-14），未逐字精讀全文 |
| `reuter-et-al-2025-reliable-retrieval-legal-rag.pdf` | Reuter, Lingenberg, Liepiņa, Lagioia, Lippi, Sartor, Passerini & Sayin (2025), *Towards Reliable Retrieval in RAG Systems for Large Legal Datasets*，NLLP 2025 @ EMNLP | [arXiv:2510.06999](https://arxiv.org/abs/2510.06999) | 🟡 已下載；abstract + 摘要頁查證（WebFetch，2026-09-14），未逐字精讀全文 |

**誠實聲明**：本次執行環境無 `poppler-utils`，無法用專案慣用的逐頁精讀流程處理下載的 PDF；下方引述皆來自 arXiv 摘要頁（WebFetch），比照本專案既有慣例標記為 🟡（如報告41 §2 對 ChainRAG/CS-RAG 的處理）。若後續要把本資料夾的方法論當作機制層級的實質依據（不只是方向性佐證），需要在有 `poppler-utils` 的環境補逐字精讀。

## 兩篇文獻在本設計中的角色

### 1. Louis et al. (2024)——非英語法律領域「何時該做混合檢索融合」的直接實證依據

🟡 摘要層級：本篇專門研究法律領域（法文）的 dense/sparse 混合檢索融合何時有效。關鍵發現（WebFetch 摘要頁）：

- **「fusing different domain-general models consistently enhances performance compared to using a standalone model, regardless of the fusion method」**——本專案的 embedding provider（Ollama `bge-m3`）是通用多語模型、未針對中文勞動法規領域微調，屬於這裡講的 "domain-general model" 情境，論文結論指向**融合能穩定帶來提升**。
- **但**「when models are trained in-domain, we find that fusion generally diminishes performance relative to using the best single system, unless fusing scores with carefully tuned weights」——**誠實侷限**：若本專案未來改用領域微調過的 embedding 模型，融合的效益可能反轉，需要重新評估、不能假設「混合永遠更好」。

**可遷移原則**：在本專案目前的組態（通用 embedding、未微調）下，加入 sparse（BM25/詞面）訊號做混合檢索、融合，有直接的法律領域實證支持；但若日後微調領域 embedding，需重新評估融合權重，不能沿用未調校的 RRF 假設它必然有效。

### 2. Reuter et al. (2025)——命名了本專案正在發生的失效類型：Document-Level Retrieval Mismatch (DRM)

🟡 摘要層級：本篇針對大規模法律資料集的 RAG 檢索可靠性，明確定義並命名 **「Document-Level Retrieval Mismatch (DRM)」**——結構相似的法律文件之間，檢索器選到完全錯誤來源文件的失效模式（WebFetch 摘要：「a specific failure mode in legal RAG systems...where retrievers select information from entirely wrong documents—a challenge in legal domains with structurally similar documents」）。

**與本專案 Q5 案例的對應**：26-Q5 的失效本質上是 DRM 的變體——目標事實所屬文件（N0050030）本身沒有被誤判排除，但**其他 7 部「結構相似」的勞工保險法規（都含『X 自 Y 起算』條文樣板）的近義事實在全域排名中壓過了正解**，效果等同於檢索器被結構相似文件的雜訊帶走注意力，只是發生在 Fact 層級而非文件層級。

**論文提出的解法（Summary-Augmented Chunking, SAC）與本專案的適用性**：SAC 的做法是在每個 chunk 的嵌入文字前**額外注入文件層級的摘要**，把原本會在切塊後遺失的全域上下文找回來（WebFetch 摘要：「enhances each text chunk with a document-level synthetic summary, thereby injecting crucial global context that would otherwise be lost」），且發現「通用摘要策略優於注入法律專業知識的摘要策略」。**誠實侷限**：SAC 是為 chunk 級檢索設計的，本專案的 `Fact` 節點已經是比 chunk 更細顆粒的原子事實，直接套用「注入摘要」不完全對應；但其**核心原則可遷移**——「在被嵌入的文字本身注入能區分來源文件身分的上下文，而非只嵌入孤立的原子內容」——具體到 `Fact` 節點，對應到 `_verbalize_fact()` 目前只嵌入「主詞＋動詞＋受詞」（見 `docs/參考文獻/12/` 記載的 KAPING 式串接，且已在報告25 移除型別括號以避免雜訊 token），完全沒有任何文件身分/法規名稱的訊號——這正是「災害發生之當月一日起…」與另外 7 部法規的「…效力之開始…起算」在 embedding 空間裡幾乎無法區分的直接原因之一。

## 兩篇合起來的設計啟示

1. Louis et al. 支持「加 sparse/BM25 訊號做 hybrid 檢索」——**方向與本專案 B1（報告35，已落地 `services/baseline_rag_service.py`）完全一致**，只是這次要用在 `Fact` 節點而非 chunk，且 Fact 文字比 chunk 短很多（純 SVO 串接，通常 10-30 字），BM25 對短文字的鑑別力是否足夠需要實測，不能直接假設跟 chunk 級一樣有效。
2. Reuter et al. 的 DRM 命名與 SAC 的「注入文件身分上下文」原則，指向另一條**互補、非互斥**的路徑——讓 `fact_text` 在嵌入前帶有能區分「這是哪部法規的規定」的訊號（例如法規簡稱或代碼前綴），而不只是裸的 SVO 三元組串接。

兩者可以合併使用（hybrid 檢索 + 上下文增強嵌入），也可以先做成本較低的一項再視效果決定要不要疊加。設計選項細節見 `docs/報告/43_Fact-RAG語意排名健壯性設計報告.md`。

## 尚未查證/待辦

- [ ] 兩篇論文皆僅 abstract 層級查證，若確認長期採用其方法論作為機制依據，需在有 `poppler-utils` 的環境補逐字精讀（尤其 Reuter et al. 的 SAC 演算法細節、Louis et al. 的融合權重調校方法）。
- [ ] Louis et al. 的「融合方法」具體是哪幾種（RRF／線性加權／其他）未在摘要層級確認，精讀時需核對是否包含本專案已用的 RRF，或需要額外實作別的融合法。
- [ ] BM25 對本專案 `Fact` 節點這種短文字（10-30 字 SVO 串接）的實際鑑別力，未有現成文獻直接量化，屬於本專案需要自行實測校準的部分（非文獻既有結論）。
