# 21_圖遍歷與向量檢索結果融合

對應 `docs/報告/25_擴大版新舊KG問答品質比對報告.md` § 4 發現6；`docs/論文/03_系統設計與方法論.md` § 3.6（`_arrange_fact_lines()` 事實清單排列）；交叉引用 `docs/參考文獻/19_生成端長清單事實遺漏與位置偏誤/`（截斷／zigzag 重排）、`docs/參考文獻/04_圖遍歷與大節點問題/`（鄰居爆炸／大節點）、`docs/參考文獻/12_三元組事實層級向量化與檢索/`（G-Retriever PCST）。

## 起點（2026-09-02，報告25 發現6）

報告25 Q8（N0080016 原住民職前訓練補助）在發現1＋5 修正後，`vector_search_facts()` 已把三筆答案事實正確撈回（scoped-13 裡 #4／#8／#11），但真實診斷（`diagnose_finding2_q8.py`，3 輪，事實清單完全確定性）發現：進到 LLM prompt 的 18 行事實清單**一筆答案事實都沒有**，被 N0080016 第 5 條「訓練計畫書應包括…」的 8 行列舉樣板 + 程序性 BFS 三元組佔滿。

追查 `routers/agent.py::_arrange_fact_lines()`：它把 `_merge_fact_lines()` 合併後的 ~35 行（BFS 三元組在前、語意 Fact 附在後）**整批用 `_score_lines_by_embedding()` 重新算一次 cosine 排序、截斷到 `_FACT_LINE_TRUNCATE_K=18`**——這一步**丟棄了 `vector_search_facts()` 已經算好、對問題有意義的 KNN 檢索排名**，改用一個對「短答案事實 vs 冗長樣板」不利的第二次 embedding pass。根本問題：**語意 Fact 經過真正的問題相關性檢索（KNN），BFS 三元組沒有任何問題相關性排序（`bfs_query()` 無 `LIMIT`、無評分，見 3.2 §b 文件更正），但兩者被丟進同一個池子、用較差的訊號重排，讓有相關性訊號的語意 Fact 被沒有相關性訊號的 BFS 樣板擠掉。**

## 內容清單

| 檔案 | 文獻 | 來源 | 狀態 |
|---|---|---|---|
| `cormack-clarke-buettcher-2009-reciprocal-rank-fusion.pdf` | Cormack, Clarke & Büttcher (2009), *Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods*，SIGIR '09 | [DOI 10.1145/1571941.1572114](https://doi.org/10.1145/1571941.1572114)；[作者自存全文](https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf) | ✅ 🟢 已下載全文精讀（2 頁完整論文） |
| `han-et-al-2025-rag-with-graphs-survey.pdf` | Han, Wang, Shomer, Guo, …, Tang (2024/2025, v2)，*Retrieval-Augmented Generation with Graphs (GraphRAG)*（18 位作者，含 Jiliang Tang、Ryan Rossi、Neil Shah） | [arXiv:2501.00309](https://arxiv.org/abs/2501.00309) | ✅ 已下載；🟡 綜述性質、僅需精讀「圖遍歷／鄰居爆炸」段落佐證 |

**參考專案／文獻查證（不下載全文，僅記書目）**：
- **SAGE**（Titiya, Khoja, Wolfson, Gupta & Roth, 2026，[arXiv:2602.16964](https://arxiv.org/abs/2602.16964)）——🟡 摘要已查證（WebFetch，2026-09-02）：seed chunks → 展開 first-hop 鄰居 → **用 dense+sparse retrieval 過濾鄰居、只選 k' 個** → union of seeds + top-ranked neighbors；retrieval recall +5.7pp（OTT-QA）／+8.5pp（STaRK）。本設計「BFS 鄰居先用 embedding 對問題排序、只留 top `_BFS_KEEP_MAX`」的直接對應。
- **PhaseGraph / Calibrated Fusion**（Bacellar, 2026，[arXiv:2603.28886](https://arxiv.org/abs/2603.28886)）——🟡 摘要已查證：明確命名「vector 與 graph 分數分布不同、不可直接比較」的問題，提 percentile-rank 正規化後融合。本設計選 RRF（rank-only、更簡單、Cormack et al. 已證有效且不需尺度校準），此篇作為**問題陳述**與**保留分數幅度的替代方案**記錄。

## 各文獻在本設計中的角色

### 1. RRF（Cormack et al., 2009）——融合機制的直接方法論來源

全文精讀（2 頁）確認：`RRFscore(d) = Σ_{r∈R} 1/(k + r(d))`，**k=60** 在 pilot 固定、後續驗證未改（Table 1：MAP 在 k=10~100 幾乎持平，「choice was not critical」）。關鍵性質：

- **「combines ranks without regard to the arbitrary scores returned by particular ranking methods」**——直接解決本專案 `vector_search_facts()` 的 Neo4j 向量索引 `score`（約 0.82~0.89）與 `_score_lines_by_embedding()` 的原始 cosine（約 0.3~0.7）**尺度不一致、無法直接比較排序**的問題。
- **「One or two systems that rank a document highly can substantially improve its rank relative to the more popular documents」**——正是本案例要的：一筆只被 vector 檢索排在前面、BFS 完全沒有的答案事實，應該要能贏過「出現很多行」的 BFS 樣板列舉。
- 「ranks may be computed and summed one system at a time」——實作只需兩個排好序的清單，不需全域資訊。
- 實證：對 TREC／LETOR 3，RRF 比最佳單一系統、Condorcet Fuse、CombMNZ 都高 4~5% MAP，sign test 顯著。

**本設計的落地**：list A = `vector_search_facts()` 回傳順序（已依 KNN 對問題排序）；list B = BFS 三元組行用 `_score_lines_by_embedding()` 對問題 cosine 排序（給 BFS 一個它本身沒有的問題相關性排名）後、再依 SAGE 精神剪到 top `_BFS_KEEP_MAX`。兩清單 RRF 融合、排序、截斷、zigzag。

### 2. Han et al. GraphRAG 綜述（2024/2025）——鄰居爆炸稀釋 LLM 焦點的問題陳述

綜述全文（HTML 版）「圖遍歷」段落指出：隨跳數增加，retrieved subgraph 的鄰居指數成長，會「exponentially increase the context length in the prompt and dilute the focus of LLMs on task-relevant knowledge」，因此「poses a requirement for graph-based reranking mechanisms to prioritize the most important content within the retrieved graph」——與本案例（N0080016 第 5 條的 8 行「訓練計畫書應包括…」列舉佔滿 prompt、擠掉答案事實）近乎逐字對應。**誠實侷限**：綜述本身不提供本設計採用的具體演算法，只確立「BFS 遍歷結果需要問題相關性重排／剪枝、不能原樣全丟進 prompt」這個方向是領域共識，非本專案自創。

### 3. SAGE（2026）——展開後剪枝、只留 top-k' 鄰居的先例

🟡 摘要層級：expand first-hop neighbors → filter with dense+sparse retrieval, select k' → union with seeds。本設計「BFS 三元組行先對問題排序、只留 top `_BFS_KEEP_MAX`（初值 12）」是同一模式的簡化版（本專案只有 dense、無 sparse；`bfs_query()` 已完成展開，本步驟只做剪枝）。

### 4. PhaseGraph / Calibrated Fusion（2026）——同一問題的分數校準替代路線

🟡 摘要層級：與 RRF 是對同一個「異質 graph-vector 分數融合」問題的兩種解法——RRF 丟棄分數幅度只用 rank，PhaseGraph 用 percentile 正規化保留幅度。本設計選 RRF：更簡單、Cormack et al. 已有 15 年的實證背書、且本專案兩個來源的分數幅度可信度不對等（KNN score 有意義、BFS 的 embedding cosine 是事後補算的代理指標），rank-only 反而穩健。記錄 PhaseGraph 供第五章消融對照。

## 尚未查證／待辦

- [ ] Han et al. 綜述「圖遍歷／鄰居爆炸」段落的逐字精讀與頁碼定位（目前僅有 arXiv HTML 版搜尋命中的轉述）。
- [ ] `_BFS_KEEP_MAX=12`、RRF `k=60` 皆為初始值（k=60 有 Cormack et al. 背書，`_BFS_KEEP_MAX` 無）——留待報告25 §6 的 K 值敏感度測試與擴大題組重測校準。
- [ ] SAGE／PhaseGraph 目前僅摘要查證，若確認長期採用此方向，補全文精讀並確認實驗前提可比性。
