# 36．B2 Agentic RAG 強基準設計報告

**日期**：2026-09-09（設計）
**狀態**：**設計定案，未實作**（使用者指示「僅設計、找文獻與專案參考」）。本報告只定義 B2 的定位、元件、單一變因控制、評估與明確排除；agent 迴圈程式碼、harness、依賴引入皆未動手。B2 為 **optional**——B1（報告 35）才是 RQ1 硬前提。
**關聯**：論文 05 §5.2／§5.4.1（B2 對照組）、§5.5（新增穩定性列）、§3.8（單一變因、可追溯性）；報告 35（B1，B2 建於其檢索前端之上）；報告 28（規則式子問題分解，B2 重用）；論文 §3.6（RQ3 自我精煉迴圈，與 B2 交叉連結但不混淆）；文獻 `docs/參考文獻/28_Agentic檢索強基準/`（含 📥 已下載的 Yao 2023 ReAct、Jeong 2024 Adaptive-RAG）。
與 DRAIN-DONE 的關係：**設計不卡 drain**；B2 **實作碼**不卡 drain（純查詢/評估端）；跑 RQ1 對照卡 DRAIN-DONE（需完整 KG#4）＋卡 §5.3（chunk-size）＋卡 B1 先落地。

---

## 1. 定位：B2 是什麼、要回答什麼

B2＝在 B1（報告 35：dense + BM25 + RRF + 選配 cross-encoder rerank 的 chunk 檢索前端）之上，包一層 **single-agent、prompt-based 的 agentic 多輪迴圈**。

**要回答的問題**（呼應 §5.4.1）：**即使不加 agent 迴圈，顯式 KG-BFS 是否仍在「可追溯性／離線成本／線上效率／穩定性／複雜多跳品質」上勝過一個完整的 agentic chunk-RAG？**

**直接動機——Fan et al. (2026)《Do We Still Need GraphRAG?》**（arXiv:2604.09666，另 GEM 2026 版）：其 RAGSearch benchmark 發現「agentic search over dense RAG 透過多輪檢索 + 推理誘導出**隱式證據結構**，大幅縮小與 GraphRAG 的差距（RL 版尤甚）；但 GraphRAG 在複雜多跳仍佔優，且離線成本攤提後 agentic 行為**更穩定**」。B2＝在本專案技術棧（繁中勞動法規、qwen2.5:7b 生成端）重現這個對照，作為 RQ1 的上限對照組。

## 2. 文獻與專案參考（2026-09-09 live 查證，細節見 `docs/參考文獻/28_Agentic檢索強基準/README.md`）

### 2.1 評估設計先例

**Fan et al. (2026)**（PDF 已在 `02_RAG與GraphRAG/`）：RAGSearch 標準化 **LLM backbone（含 Qwen2.5-7B-Instruct，與本專案一致）＋檢索預算（≤ 5 search turns、top-5，Appendix B）＋推理協定**；報告 accuracy 以外的 **離線建構成本 / 線上效率（延遲、context 長度）/ 穩定性（Contain-EM mean+variance，§5.5.1）**。prompt-based agent 例：Search-o1（ReAct 式 `<think>`/`<search>`）、GraphSearch（query 分解 + 證據驗證）；RL 版 Search-R1/Graph-R1（GRPO，§4.3）。

### 2.2 Agentic 迴圈機制

- **ReAct**（Yao et al. 2023，🟢 ICLR 2023，📥 `28_.../yao-et-al-2023-react.pdf` 33 頁，未精讀；`ysymyth/ReAct` ⭐4,159 MIT）——thought→action→observation 交錯迴圈，B2 迴圈骨架。
- **IRCoT**（Trivedi et al. 2022，🟢 ACL 2023，已在 §2.4.7）——檢索與 CoT 交錯做多跳；**Han et al. 2025 用 IRCoT 當其迭代檢索 baseline**。
- **Self-Ask**（Press et al. 2022，已在 §2.4.7／報告 28）——顯式子問題分解；專案 `_split_into_subquestions()` 可重用。
- **FLARE**（Jiang et al. 2023，已在 §2.4.7）——生成低信心時觸發再檢索。
- **Self-RAG**（Asai et al. 2023，已在 §2.4.7）——反思 critique：判證據充分性。

### 2.3 治理：何時 agentic

- **Adaptive-RAG**（Jeong et al. 2024，🟢 NAACL 2024，📥 `28_.../jeong-et-al-2024-adaptive-rag.pdf` 15 頁，未精讀；`starsuzi/Adaptive-RAG` ⭐409 Apache-2.0）——複雜度分類器路由 no-retrieval / single-step / **multi-step**。B2 用它讓**簡單題退回 B1**（否則成本對照失真）。本專案可用規則式簡化版（問號數／實體數／連接詞計數）代替訓練式分類器。

### 2.4 分類法

- **Singh et al. (2025)** Agentic RAG Survey（🟡 arXiv:2501.09136，已在 §2.3 索引；`asinghcsu/AgenticRAG-Survey` ⭐1,726）——**B2 ＝ single-agent + adaptive**（不做 multi-agent）。

### 2.5 專案內既有資產（B2 大量重用）

B1 檢索前端（報告 35）／`_split_into_subquestions()`（報告 28）／§3.6 grounding + 方案 B/2b 重生 stack／`run_rag_comparison.py`（報告 18）。

## 3. B2 定義與元件

```
B2 = Adaptive 路由（複雜度分類：規則式簡化版或小 LM）
     ├─ 簡單題 → B1 單次（不進 agent 迴圈）
     └─ 複雜題 → single-agent ReAct/IRCoT 式迴圈，跑在 B1 檢索前端上：
          ① 分解（Self-Ask 式，重用 _split_into_subquestions）
          ② 逐步驟：用 B1 檢索前端（dense+BM25+rerank）取證據
          ③ 反思（Self-RAG critique）：「當前證據夠不夠回答本步驟？缺什麼？」
          ④ 不足 → 依缺口精煉查詢（FLARE 觸發），回到 ②；≤ N 輪、總檢索預算上限
          ⑤ 綜合各步驟證據 → 【與 B0/B1/Full-System 逐位元相同的 grounding + 方案 B/2b 重生 stack】
     界限：max_rounds = 5（Fan 2026）、每輪 top-k = 5、總檢索次數上限、generator 固定 qwen2.5:7b、無工具（只有檢索）
```

| 元件 | B1 | B2 | 依據 |
|---|---|---|---|
| 檢索前端 | dense + BM25 + rerank，**單次** | 同前端，**多輪、每輪查詢由 agent 精煉** | Fan 2026（同 infra + agentic wrapper） |
| query 處理 | 原樣 | **分解 + 逐輪改寫** | Trivedi 2022（IRCoT）、Press 2022（Self-Ask） |
| 迴圈控制 | 無 | thought→search→observe，≤ 5 輪；資訊不足才續查 | Yao 2023（ReAct）、Jiang 2023（FLARE） |
| 何時 agentic | — | 複雜度分類 → 簡單題退回 B1 | Jeong 2024（Adaptive-RAG） |
| 反思 | 無 | 每輪判證據充分性 | Asai 2023（Self-RAG） |
| 生成端 | **與 KG 路徑逐位元相同** | 同 | §3.8 單一變因 |

**核心原則**：B0／B1／B2／Full System **只差檢索前端**（B2 多一層 agentic wrapper），生成端（prompt 組裝、`cfg.domain`、grounding、方案 B/2b）完全相同。

## 4. 單一變因控制（§3.8）

| 對照 | 唯一變因 | 固定 |
|---|---|---|
| B1 vs B2 | 有無 agentic 多輪迴圈 | 檢索前端、generator、生成 stack、題組 |
| **B2 vs Full System (KG-BFS)** | agentic 多輪 chunk 檢索（隱式證據結構）vs 單次 KG-BFS（顯式圖結構） | generator、`cfg.domain`、`_arrange_fact_lines` 下游、grounding、方案 B/2b、題組、每題 ×3、§5.5 rubric |

### ⚠️ Confounder 誠實聲明（呼應稽核 F2）

Full System 的 **RQ3 自我精煉迴圈尚未實作**（只有單次 grounded regeneration，見 §3.6／§4.7.2／§4.9）。因此 B2 的多輪檢索**比現行 Full System 更 agentic**。RQ1 的提問因此精確化為 Fan (2026) 的框架：「即使 Full System 沒有 agent 迴圈，顯式 KG-BFS 是否仍在可追溯性／成本／穩定性／複雜多跳上勝過完整 agentic chunk-RAG？」——這正是「圖結構值不值得做」的核心。

**與 §3.6 RQ3 的關係（交叉連結，非混淆）**：B2 是一個**競爭架構的 baseline**，不是專案的 RQ3 機制；但 B2 的迴圈設計（分解 → 逐輪檢索 → 反思 → 再檢索）可直接回饋 §3.6 RQ3 目前**未實作**的「擴大 BFS 回補檢索 + 多輪迭代」分支——若 RQ3 未來實作，可沿用 B2 驗證過的迴圈控制與終止條件。

## 5. 評估（擴 §5.5，Fan 2026 式）

| 面向 | 指標 | 說明 |
|---|---|---|
| 答案品質 | §5.5 既有（EM／F1 + 人工 rubric 正確性/完整性，每題 ×3） | 不變 |
| **離線建構成本** | KG 抽取（drain ~4 天 / 3303 chunk）vs B2 ≈ 0（只需 chunk embedding，B0/B1 已有） | 對照表：建構時間、每題攤提成本（Fan 2026 Table 8 式） |
| **線上效率** | 端到端延遲 p50/p95、每題 LLM 呼叫數、context 總長度 | B2 = N 次 LLM 呼叫/題（分解 + 每輪 reason + 綜合）；KG-BFS = 1 retrieval + 1 gen；B1 = 1 retrieval + 1 gen |
| **穩定性（新增 §5.5 列）** | 每題 ×3 run 的答案分數 mean 與 variance | Fan 2026 §5.5.1：agentic 系統的 run 間變異是其已知弱點；KG-BFS 的檢索是決定性的（Cypher），變異只來自生成端 |
| 可追溯性（AIS，質化） | B2 證據＝chunk 段落級；Full System＝Fact→LawArticle 條文級（結構化） | 質化 RQ1 軸；對「引用到具體法條」的能力差異 |

## 6. 明確排除（誠實聲明，寫進 §5.4.1）

- **無 RL 訓練／微調**：Search-R1／Graph-R1（GRPO）是 Fan 2026 §4.3 顯示縮小差距最多的變體，但需 RL 基建——B2 定義為 prompt-based agentic，論文明確聲明「RL 版是已知更強、未評估的 bar」。
- **單 agent**（非 multi-agent）。
- **檢索-only agent**：不加 web 搜尋／計算器／其他工具，維持與 KG 路徑的公平對照。
- **B2 為 optional**：時間不足時 RQ1 至少對照到 B1；第七章限制章聲明「未對照完整 Agentic RAG」。

## 7. 實作考量（僅列，本輪不做）

- Agent 迴圈編排：LangGraph（狀態圖）或自寫輕量 async 狀態機（thought/search/observe 三態 + 計數器）；重用 B1 檢索前端與 `_split_into_subquestions()`。
- 複雜度分類器：先做規則式（問號數 ≥ 2、或含「且/或/以及/並/分別」等連接詞、或抽出實體數 ≥ 3 → 判複雜），Adaptive-RAG 式訓練分類器留作後續。
- 反思 prompt：一次 LLM 呼叫，輸入=子問題 + 當前證據，輸出=`{sufficient: bool, missing: str}`；`sufficient=false` 時用 `missing` 組下一輪查詢。
- 終止：`max_rounds=5` 或 `sufficient=true` 或總檢索次數達上限。
- harness：擴報告 35 規劃的 `run_rq1_comparison.py`，加 B2 路徑，同題組 ×3、輸出對齊 §5.5 + 穩定性 + 成本/效率欄。
- 依賴：無新模型（規則式分類器版）；LangGraph 為選配。
- **不碰抽取端、不碰 drain。**

## 8. 落地待辦（本報告產出後）

- [x] 下載 ReAct（Yao 2023）、Adaptive-RAG（Jeong 2024）進 `docs/參考文獻/28_Agentic檢索強基準/`（📥，未精讀）。
- [x] `docs/參考文獻/28_Agentic檢索強基準/README.md`。
- [x] 論文 §5.4.1 補 B2 定義段（元件表 + 評估 + Confounder 聲明 + 排除）；§5.2 表「B2」列補元件細節；§5.5 新增「離線建構成本」「穩定性」列（commit `878b47d`）；§5.7 時程把「B1 → B2（optional）→ RQ1 對照」序列釘死（2026-09-09，§5.7.1/§5.7.2 分階段 DAG）。
- [ ] 論文 §2.3.1 擴（收 ReAct／Adaptive-RAG／IRCoT-as-baseline 譜系），或新增 §2.3.2「RQ1 agentic 對照組（B2）的方法定位」。
- [ ] `文獻與專案查核表.md` 補 ReAct／Adaptive-RAG 兩列（標 📥 已下載、未精讀）。
- [ ] （實作階段）ReAct §prompt、Adaptive-RAG §複雜度標籤、Fan 2026 §4.3/§5.5.1/App B/App E 全文精讀。
