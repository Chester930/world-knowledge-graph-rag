# 04_圖遍歷與大節點問題

對應 `../../論文/02_文獻探討.md` § 2.4.8（RQ6）／§ 3.7（向量引導圖剪枝，2026-07-23
第二章重組前為 § 2.1.4）；`../../報告/27_圖遍歷向量引導剪枝機制設計報告.md`
（2026-09-04，把 §3.7「預留」轉為分層實作設計，報告26 §4 #4 為實測觸發）。

交叉引用：`../21_圖遍歷與向量檢索結果融合/`（鄰居爆炸、Han 綜述、SAGE、RRF）、
`../12_三元組事實層級向量化與檢索/`（G-Retriever 全文已收錄於該資料夾）、
`../02_RAG與GraphRAG/`（PathRAG、LightRAG 全文已收錄於該資料夾）。

## 問題陳述

`services/svo_service.py::bfs_query()` 的 Cypher 變長路徑
`MATCH path=(seed)-[:<SVO_REL_TYPES>*1..hops]-(neighbor)` **無 `LIMIT`、無問題相關性、
無文件範圍**。勞動法語料裡共用高頻實體（雇主／被保險人／投保單位）出邊數達數百，
`hops=2`（`ChatRequest.svo_hops` 預設）時 2-hop 幾乎覆蓋整個知識層——報告26 §4 #4
實測 Q5/6/7 各 330–440 秒、回傳 79–100 條三元組、離題事實佔多數。此即業界所稱
supernode／hub node 的「fanning-out problem」在 GraphRAG 檢索階段的具體表現。

## 內容清單

本資料夾**不另存 PDF**——RQ6 的核心文獻（CatRAG／PathRAG／LightRAG／G-Retriever／
Han 綜述／SAGE）全文皆已收錄於 `02_RAG與GraphRAG/`、`12_三元組事實層級向量化與
檢索/`、`21_圖遍歷與向量檢索結果融合/`，本節僅記各文獻在 RQ6／報告27 中的角色與
交叉引用路徑（比照 G-Retriever 收於 `12_`、PathRAG/LightRAG 收於 `02_` 的既有模式）。

| 文獻 | 全文位置 | 在 RQ6／報告27 中的角色 |
|---|---|---|
| **CatRAG**（Lau, Zhang, Ruan, Zhou, Guo, Zhang & Zhou, 2026，*Breaking the Static Graph: Context-Aware Traversal for Robust RAG*，Findings of ACL 2026，arXiv:2602.01965） | `../02_RAG與GraphRAG/lau-et-al-2026-catrag-static-graph-fallacy.pdf`（2026-08-25 收錄；官方碼 [kwunhang/CatRAG](https://github.com/kwunhang/CatRAG)） | 命名 **「Static Graph Fallacy」**：索引階段固定的轉移機率忽略邊相關性的**查詢相依**本質 → semantic drift，隨機游走被高度數 hub 節點吸走、還沒走到關鍵下游證據就偏航。建於 HippoRAG 2 的 Personalized PageRank 上，三機制：① **Symbolic Anchoring**（§3.2，具名實體注入為權重 ε 的弱種子）；② **Query-Aware Dynamic Edge Weighting**（§3.3，Stage I 拓撲粗篩 top-K_edge → Stage II **LLM 對邊做離散分級** {Irrelevant,Weak,High,Direct} 算動態權重）；③ Key-Fact Passage Weight Enhancement（§3.4，純算法）。與報告26 §4 #4「共用實體把 BFS 灌爆、離題事實佔多數」近乎逐字對應。🟢 全文已收錄並精讀方法章節（2026-09-05，§3.1-3.5）。 |
| **G-Retriever**（He et al., 2024, NeurIPS 2024，arXiv:2402.07630） | `../12_三元組事實層級向量化與檢索/he-et-al-2024-g-retriever.pdf` | 子圖檢索形式化為 PCST（Prize-Collecting Steiner Tree）：node／edge 依查詢相似度給 prize，求最大化 Σprize − Σcost 的連通子圖。**嚴謹上界方法**；報告27 L2 的「向量引導 prize 剪枝」是其扁平化簡化（無 Steiner tree 最佳化、無 GNN），第五章需聲明差距。 |
| **PathRAG**（Chen et al., 2025，arXiv:2502.14902） | `../02_RAG與GraphRAG/chen-et-al-2025-pathrag.pdf` | 命名「retrieved subgraph 的**冗餘**」為核心問題；flow-based pruning ＋ 只取關鍵關聯路徑不取任意子圖。官方碼 [BUPT-GAMMA/PathRAG](https://github.com/BUPT-GAMMA/PathRAG)。 |
| **LightRAG**（Guo et al., 2024, EMNLP 2025，arXiv:2410.05779） | `../02_RAG與GraphRAG/guo-et-al-2024-lightrag.pdf` | dual-level 檢索，local 層只取 **one-hop** 鄰居——報告27 L0「`svo_hops` 預設 2→1」的先例。 |
| **Han et al. GraphRAG 綜述**（2024/2025，arXiv:2501.00309） | `../21_圖遍歷與向量檢索結果融合/han-et-al-2025-rag-with-graphs-survey.pdf` | 鄰居隨跳數指數成長、稀釋 LLM 焦點、需 graph-based reranking——確立「遍歷結果需問題相關性剪枝」為領域共識。 |
| **SAGE**（Titiya et al., 2026，arXiv:2602.16964） | `../21_圖遍歷與向量檢索結果融合/`（🟡 摘要層級） | expand first-hop → dense+sparse 過濾鄰居 → 只選 top-k' → union seeds。「展開後剪枝」先例。 |

**參考專案（不下載全文，僅記書目）**：

- **microsoft/graphrag** local search（35,774★，論文已引 Edge et al. 2024）——bounding
  recipe：top-10 entity（embedding）→ 加 relationship 至 token 達 context ½ → 加原文
  chunk 至滿。**以 token 預算為界、非以 hop 為界**，報告27 §3 列為對照。
- **David Allen**, *Graph Modeling: All About Super Nodes*（Neo4j Developer Blog）——
  supernode／fanning-out 的實務命名。
- **APOC** `apoc.path.expandConfig`（`limit`／`maxLevel`／`labelFilter`／`bfs:true`／
  `filterStartNode`）——Neo4j 原生 bounded-traversal primitive。⚠️ 本專案 Neo4j 未裝
  APOC（`requirements.txt` 僅 `neo4j~=6.0`、全用 raw Cypher），報告27 設計以純 Cypher
  為主、APOC 列替代路線。

## 尚未查證／待辦

- [x] CatRAG（arXiv:2602.01965）方法章節逐字精讀（2026-09-05，§3.1-3.5）——
      symbolic anchoring、query-aware dynamic edge weighting 的兩階段權重公式、
      key-fact passage enhancement 皆已確認；與本專案「seed degree 上限 +
      Cypher 範圍約束」的精確方法論差距見報告27 §3 誠實聲明段。
- [x] PathRAG flow-based pruning 方法章節精讀（2026-09-05）——資源分配傳播
      公式（Eq.2-4）、early stopping 剪枝、路徑可靠度升冪排列（Eq.6）皆已確認。
- [ ] 報告27 §6.2 敏感度測試（2026-09-05）已針對 Q6 單題校準 θ_deg（200→100）、
      per_seed_limit（60→30）；θ_hop 在 `hops=1` 預設下是 dead code path（見
      commit `7b6d208`）。⚠️ 僅單題驗證，非窮舉全題組，待全量重抽完成後隨
      報告27 §6.2 完整題組重新驗證。
