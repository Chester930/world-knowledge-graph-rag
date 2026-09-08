# 28_Agentic檢索強基準

對應 `docs/報告/36_B2AgenticRAG強基準設計.md`；支撐第五章 §5.4.1 的 **B2（Agentic RAG 強基準）** 設計——RQ1 的第二個非圖對照組（在 B1 之上加 agentic 多輪迴圈）。**B2 為 optional：B1 才是 RQ1 硬前提。**

查證日期 2026-09-09（session `01SHVuNWkSt2PQSEh2Snp73A`）。arXiv ID、頁數、作者經 WebSearch / WebFetch / 本地 PDF 抽取驗證；GitHub star / license 經 `gh api` 即時查證。

---

## A. B2 評估設計的直接先例

| 文獻 | 出處 / 狀態 | 內容（WebFetch arxiv HTML v1，2026-09-09） | 對 B2 的意義 |
|---|---|---|---|
| **Fan, Xue, Liu, Tan (2026)** *Do We Still Need GraphRAG? Benchmarking RAG and GraphRAG for Agentic Search Systems* | arXiv:[2604.09666](https://arxiv.org/abs/2604.09666)；另有 GEM 2026 版《Is GraphRAG Needed? From Basic RAG to Graph-/Agentic Solutions with Context Optimization》（[aclanthology.org/2026.gem-main.40](https://aclanthology.org/2026.gem-main.40/)）。**PDF 已在 `02_RAG與GraphRAG/fan-et-al-2026-do-we-still-need-graphrag.pdf`**（本資料夾不重複存） | **RAGSearch benchmark**：把 dense RAG / GraphRAG 當「agentic search 下的檢索 infrastructure」評估。**標準化 LLM backbone（含 Qwen2.5-7B-Instruct、Qwen2.5-32B-Instruct）＋檢索預算（≤ **5 search turns**、**top-5**，Appendix B）＋推理協定**。報告三類 accuracy 以外指標：**① 離線建構成本**（construction time / cost per 1M tokens，Table 8 / Appendix E）**② 線上效率**（平均檢索延遲、context 長度）**③ 穩定性**（Contain-EM 的 mean 與 variance，§5.5.1 Table 3）。prompt-based agent 例：**Search-o1**（ReAct 式 `<think>`/`<search>` 標籤迴圈）、**GraphSearch**（Query Decomposition + Evidence Verification 模組，皆 prompting）。**RL 版**：Search-R1 / Graph-R1，用 GRPO 學檢索策略（§4.3）。頭條結論（§5.2.2–5.2.3 + 摘要）：agentic search「大幅改善 dense RAG、縮小與 GraphRAG 的差距，RL 版尤甚」，但 GraphRAG「在複雜多跳推理仍佔優」、且「離線成本攤提後 agentic search 行為更穩定」 | **B2 的評估框架直接照搬**：成本 + 效率 + 穩定性，非只看準確率；backbone Qwen2.5-7B 與本專案生成端一致；≤5 輪 / top-5 直接採為 B2 界限 |

## B. Agentic 迴圈機制文獻

| 文獻 | 出處 / 狀態 | 本機檔案 | 角色 |
|---|---|---|---|
| **Yao, Zhao, Yu, Du, Shafran, Narasimhan, Cao (2023)** *ReAct: Synergizing Reasoning and Acting in Language Models* | 🟢 **ICLR 2023**（arXiv:[2210.03629](https://arxiv.org/abs/2210.03629)）；官方 repo [`ysymyth/ReAct`](https://github.com/ysymyth/ReAct)（⭐4,159、MIT、pushed 2024-02-06，gh api 2026-09-09） | **`yao-et-al-2023-react.pdf`（📥 已下載 2026-09-09，33 頁，首頁「Published as a conference paper at ICLR 2023」＋作者已核）** | thought→action→observation 交錯迴圈；LLM agent 呼叫外部檢索工具（HotpotQA + Wikipedia API）的基礎範式。＝B2 迴圈骨架。⚠️ 尚未精讀全文，僅摘要層級＋WebSearch 查證核心機制 |
| **Trivedi, Balasubramanian, Khot, Sabharwal (2022)** *Interleaving Retrieval with Chain-of-Thought Reasoning for Knowledge-Intensive Multi-Step Questions*（IRCoT） | 🟢 ACL 2023，已收錄 `02_RAG與GraphRAG/trivedi-et-al-2022-ircot.pdf`（論文 §2.4.7 已引）；repo `StonyBrookNLP/ircot` | 已有 | 檢索與 CoT 交錯做多跳推理；**Han et al. (2025)《RAG vs. GraphRAG》即用 IRCoT 當其迭代檢索 baseline**——B2 多輪檢索的直接對照做法 |
| **Press, Zhang, Min, Schmidt, Smith, Lewis (2022)** *Measuring and Narrowing the Compositionality Gap*（Self-Ask） | 🟢 Findings of EMNLP 2023，已收錄 `23_複合問題分解與自相矛盾修正/`（§2.4.7、報告 28 已引） | 已有 | 顯式子問題分解；專案已有規則式 `_split_into_subquestions()`（報告 28）可重用為 B2 的分解步驟 |
| **Jiang, Xu, Gao, Sun, Liu, Dwivedi-Yu, Yang, Callan, Neubig (2023)** *Active Retrieval Augmented Generation*（FLARE） | 🟢 EMNLP 2023，已收錄 `02_RAG與GraphRAG/jiang-et-al-2023-flare.pdf`（§2.4.7 已引） | 已有 | 生成低信心 token 時觸發再檢索——B2 「資訊不足才續查」的觸發依據 |
| **Asai, Wu, Wang, Sil, Hajishirzi (2023)** *Self-RAG*（reflection tokens） | 🟢 ICLR 2024，已收錄（§2.4.7 已引）；repo `AkariAsai/self-rag` | 已有 | 反思/critique：判「檢索到的證據夠不夠、是否支持回答」——B2 每輪的證據充分性判斷 |

## C. 治理：何時該 agentic

| 文獻 | 出處 / 狀態 | 本機檔案 | 角色 |
|---|---|---|---|
| **Jeong, Baek, Cho, Hwang, Park (2024)** *Adaptive-RAG: Learning to Adapt Retrieval-Augmented Large Language Models through Question Complexity* | 🟢 **NAACL 2024**（[aclanthology.org/2024.naacl-long.389](https://aclanthology.org/2024.naacl-long.389/)，pp. 7036–7050）；官方 repo [`starsuzi/Adaptive-RAG`](https://github.com/starsuzi/Adaptive-RAG)（⭐409、Apache-2.0、pushed 2024-05-02，gh api 2026-09-09） | **`jeong-et-al-2024-adaptive-rag.pdf`（📥 已下載 2026-09-09，15 頁，首頁標題／作者已核）** | 用小 LM 訓練的 query 複雜度分類器，動態路由 **no-retrieval / single-step / multi-step（iterative）**。→ B2 用它讓**簡單題退回 B1**，避免每題都付 N× LLM 呼叫使成本對照失真。⚠️ 尚未精讀全文；本專案可用**規則式簡化版**（問號數／實體數／連接詞計數）代替訓練式分類器 |

## D. 分類法

| 文獻 | 出處 / 狀態 | 角色 |
|---|---|---|
| **Singh, Ehtesham, Kumar, Khoei (2025)** *Agentic Retrieval-Augmented Generation: A Survey on Agentic RAG* | 🟡 arXiv:[2501.09136](https://arxiv.org/abs/2501.09136)，已收錄 `02_RAG與GraphRAG/singh-et-al-2025-agentic-rag-survey.pdf`（§2.3 索引已列）；repo [`asinghcsu/AgenticRAG-Survey`](https://github.com/asinghcsu/AgenticRAG-Survey)（⭐1,726、no-license、pushed 2025-10-20，gh api 2026-09-09） | agentic RAG 分類：single-agent / multi-agent / hierarchical / corrective / **adaptive** / graph-based；設計 pattern＝reflection、planning、tool use、multi-agent。**B2 ＝ single-agent + adaptive**（不做 multi-agent——scope 外） |

## E. 專案內既有資產（B2 大量重用）

| 資產 | 對 B2 的關係 |
|---|---|
| B1 的檢索前端（`Chunk` 級 dense + BM25 + RRF + 選配 rerank，報告 35） | B2 每一輪檢索直接呼叫它，只是查詢由 agent 逐輪精煉 |
| `_split_into_subquestions()`（規則式分解，報告 28） | B2 的分解步驟 |
| §3.6 grounding 核對（`verify_fact_grounding`）＋ 方案 B / 2b 限制性重生 stack | B2 綜合答案後走**與 B0/B1/Full-System 完全相同**的這條 stack |
| `run_rag_comparison.py` / （報告 35 規劃的）`run_rq1_comparison.py` | 擴一條 B2 路徑即可 |

## F. 明確排除（寫進報告 36 / §5.4.1）

- **無 RL 訓練 / 無微調**：Search-R1 / Graph-R1（GRPO）是 Fan (2026) §4.3 顯示縮小差距最多的變體，但需 RL 訓練基建——B2 定義為 **prompt-based agentic**，論文明確聲明「RL 版是已知更強、未評估的 bar」。
- **單 agent**，非 multi-agent（MA-RAG 等）——scope 外。
- **檢索-only agent**：不加 web 搜尋 / 計算器 / 其他工具，維持與 KG 路徑的公平對照。
- B2 為 **optional**：時間不足時 RQ1 至少對照到 B1，第七章限制章聲明未對照完整 Agentic RAG。

## G. 尚未取得 / 待深讀

- [ ] ReAct（Yao 2023）、Adaptive-RAG（Jeong 2024）僅 📥 已下載，尚未 📖 精讀——B2 定版前需精讀 ReAct §prompt 設計、Adaptive-RAG §複雜度標籤收集。
- [ ] Fan (2026) §4.3（RL 版）/ §5.5.1（穩定性指標定義）/ Appendix B（檢索預算）/ Appendix E（成本表）目前經 WebFetch HTML 取得，寫作定稿前需對 PDF 逐字複核。
- [ ] Singh (2025) survey 的 adaptive / corrective 章節（若 B2 要引其具體 pattern 命名）。
