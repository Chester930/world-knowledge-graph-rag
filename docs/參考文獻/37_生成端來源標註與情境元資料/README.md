# 37_生成端來源標註與情境元資料

對應 `docs/報告/63_Gemini評測報告查證與改進項評估.md` §2.3／§4 A 案（`57-AGGR18` 新舊法歸屬寫反：檢索 Recall 100%，但 prompt 事實行不帶來源法規名）。交叉引用 `docs/參考文獻/31_Fact-RAG語意排名健壯性/`（Reuter et al. 2025 SAC：在被嵌入文字前注入文件層級上下文，本資料夾是它在**生成端**的對應問題）、`docs/報告/57_…` §4.19。

## 查證背景（2026-09-21）

報告63 的診斷：AGGR18 的兩個 gold 事實都進了 context，模型卻把「新法／舊法」配反。凍結基準存檔與 T0 trace（`sdd-retrieval-comparison` 分支，`prompt_context_lines`）顯示，實際送進 LLM 的事實行是**不帶法規名、條號、施行日的裸句**，例如 `- 雇主 對高空工作車應每月依下列規定定期實施檢查一次 …`；但同一份 trace 的每筆證據已帶 `source_doc_id` 與 `article_no`，只是沒有進 prompt。

本資料夾回答：**「在給 LLM 的每筆 context 前標示來源」有沒有文獻／專案先例？先例證明了什麼、沒有證明什麼？**

## 內容清單

| 項目 | 文獻／專案 | 來源 | 查證層級 |
|---|---|---|---|
| `gao-et-al-2023-alce.pdf` | Gao, Yen, Yu & Chen (2023), *Enabling Large Language Models to Generate Text with Citations*，EMNLP 2023 | [arXiv:2305.14627](https://arxiv.org/abs/2305.14627)；官方程式碼 [princeton-nlp/ALCE](https://github.com/princeton-nlp/ALCE) | ✅ prompt 格式**直接讀官方 repo 一手檔案**（`prompts/asqa_default.json`）；🟡 論文本身僅 abstract 頁查證（WebFetch），未逐字精讀全文 |
| `feng-steinhardt-2023-binding-ids.pdf` | Feng & Steinhardt (2023，2024-05-06 修訂), *How do Language Models Bind Entities in Context?* | [arXiv:2310.17191](https://arxiv.org/abs/2310.17191) | 🟡 abstract 頁查證（WebFetch）；📎 NeurIPS 2023 一說僅見搜尋結果（neurips.cc 頁面），**arXiv 頁面標示為 cs.LG，未親自核對錄取資訊** |
| （無 PDF，工程部落格） | Anthropic (2024-09-19), *Contextual Retrieval* | [anthropic.com/engineering/contextual-retrieval](https://www.anthropic.com/engineering/contextual-retrieval) | ✅ 內文即時核對（WebFetch）；⚠️ 非同儕審查、實驗為 Anthropic 自家設定 |
| （交叉引用） | Reuter et al. (2025), *Towards Reliable Retrieval in RAG Systems for Large Legal Datasets* | [arXiv:2510.06999](https://arxiv.org/abs/2510.06999)，PDF 在 `../31_Fact-RAG語意排名健壯性/` | 🟡 沿用資料夾31 的 abstract 層級查證，本次未重讀 |
| 專案 | `D-Star-AI/dsRAG`（AutoContext／contextual chunk headers） | [GitHub](https://github.com/D-Star-AI/dsRAG) | ✅ `gh api`（2026-09-21）：1,588★、MIT、`archived: false`、最後 push 2025-11-10；README 原文核對 |
| 專案 | `run-llama/llama_index`（`MetadataMode`） | [GitHub](https://github.com/run-llama/llama_index) | ✅ `gh api`（2026-09-21）：52,253★、MIT、最後 push 2026-09-19；`llama-index-core/llama_index/core/schema.py` 第 242–245 行原始碼核對 |

**誠實聲明**：執行環境無 `poppler-utils`，兩份 PDF 皆未逐頁精讀，沿用專案慣例標 🟡（同資料夾31）。下方引述只來自 abstract 頁、Anthropic 內文、以及官方 repo 檔案。

## 各項證明了什麼、沒有證明什麼

### 1. ALCE（Gao et al. 2023）——「每筆 context 前標示編號＋標題」是既有標準做法

- **一手證據**（官方 repo `prompts/asqa_default.json`，2026-09-21 直接讀取）：文件格式模板為 `Document [{ID}](Title: {T}): {P}`；指令要求「using only the provided search results … and cite them properly」。即 context 每筆都帶**編號與標題**，且要求模型依編號引用。
- **abstract 層級**：ALCE 是評測「帶引用生成」的 benchmark，三個面向為 fluency、correctness、citation quality；ELI5 上「最佳模型有 50% 的時間缺乏完整引用支持」（WebFetch）。
- **落差（重要）**：ALCE 標示來源的目的是**讓模型能產生可驗證的引用**，**不是**在測「標示來源能否減少跨來源張冠李戴」。它證明「標來源是標準 prompt 設計」，**沒有**證明「標了以後歸屬錯誤會下降」。

### 2. Feng & Steinhardt（2023）——為什麼「無標籤並列事實」對模型很難：實體—屬性綁定

- abstract 層級：語言模型必須把實體綁到屬性（例：「green square」「blue circle」→ 形狀對應顏色）；作者辨識出「binding ID」機制，觀察到於「every sufficiently large model from the Pythia and LLaMA families」，並以因果干預驗證。
- **與本專案的對應（類比，不是直接證據）**：「哪一條規定屬於哪一部法」是一個綁定問題；AGGR18 的兩句事實在 prompt 中除了位置以外沒有可區分的綁定線索。
- **落差（重要）**：該研究用**合成任務**（構造例句）與 **Pythia／LLaMA** 系列，**沒有**研究本專案使用的 `qwen2.5:7b`，也沒有研究中文法律文本或長 context 的事實清單。只能當作「問題確實有機制層面的研究基礎」，**不能**當作「本專案的錯誤就是這個機制造成」的證據。

### 3. Anthropic Contextual Retrieval（2024）——同一原則的**檢索端**版本

- 內文核對：在 chunk 嵌入與 BM25 索引前，前置 50–100 token 的 chunk 專屬情境說明（範例：「This chunk is from an SEC filing on ACME corp's performance in Q2 2023…」）。指標為「1 − recall@20」（未能取回的比例）：僅 Contextual Embeddings 5.7%→3.7%（−35%）；加 Contextual BM25 → 2.9%（−49%）；再加 reranking → 1.9%（−67%）。資料涵蓋 codebases、fiction、ArXiv papers、Science Papers；嵌入模型為 Gemini Text 004，top-20。
- **落差**：這是**檢索端**（改變被嵌入的文字），本專案 A 案是**生成端**（改變送給 LLM 的文字）。且非中文、非法律、非事實三元組，數字不可外推。它支持的是「給孤立片段補上來源情境」這個一般原則。
- 原文自陳的限制：chunk 邊界／大小、不同嵌入模型受益不同、reranking 有延遲代價、「更多 chunk 提高相關機率但可能分散模型注意力」。

### 4. Reuter et al. (2025) SAC（交叉引用）

在被嵌入的文字前注入文件層級摘要，對應法律 RAG 的 Document-Level Retrieval Mismatch。**也是檢索端**，且資料夾31 已記載其對 `Fact` 顆粒度不完全對應。本資料夾不重複，僅指出它與 Anthropic 是同一原則的兩個實例。

### 5. 專案先例

- **dsRAG**（AutoContext）：README 原文——AutoContext 產生「contextual chunk headers」，內含文件層級與段落層級情境，嵌入前前置於 chunk；標頭可以只是文件標題，或標題＋摘要＋章節階層。README 並聲稱此功能「reduces the rate at which the LLM misinterprets a piece of text in downstream chat and generation applications」——**專案自述，無公開數據**（本次未找到其對應的量化實驗，不可當證據引用）。
- **LlamaIndex `MetadataMode`**：`schema.py` 定義 `ALL／EMBED／LLM／NONE` 四種模式與 `excluded_embed_metadata_keys`／`excluded_llm_metadata_keys`——即業界主流框架**把「進嵌入的 metadata」與「進 LLM prompt 的 metadata」設計成兩個獨立開關**。這是工程慣例的直接佐證：來源／標題類 metadata 應可獨立決定是否送進生成端 prompt。

## 查了但不採用

- **Multi-Meta-RAG**（Poliakov & Shvai，[arXiv:2406.13213](https://arxiv.org/abs/2406.13213)，2024）：用 LLM 抽取 metadata 做**資料庫過濾**以改善多跳問答。abstract 頁未列具體 metadata 欄位與數字；它是**檢索前過濾**，與「生成端標籤」不同機制，且無法據 abstract 得出效果數字，故不列為 A 案依據。

## 綜合：文獻能支持到哪一步

| 命題 | 支持程度 |
|---|---|
| 「給 LLM 的每筆 context 標示來源（編號＋標題）」是既有標準做法 | ✅ ALCE 官方 prompt 一手證據；LlamaIndex 有獨立的 LLM-metadata 開關 |
| 「給孤立片段補上來源情境能提升**檢索**」 | 🟡 Anthropic（自家實驗）、Reuter 2025 |
| 「LLM 在無標籤並列事實間做歸屬是困難的（綁定問題）」 | 🟡 Feng & Steinhardt（合成任務、他系列模型），只能類比 |
| **「在本系統的事實行加來源標籤，會讓 `qwen2.5:7b` 的新舊法歸屬錯誤下降」** | ❔ **沒有任何文獻直接證明**，必須以本專案自己的對照實驗驗證（沿用報告61 的立場：文獻只支持方向，「有效」要靠自己的實驗） |
