# 39：七路檢索比較標準化測試 harness 任務書

> 狀態：📋 任務書（2026-09-10 建立）。供另一個終端機視窗在 master 上直接執行。
> 目的：把「七條檢索 arm 都能對同一題組跑通、變因乾淨、結果可比」做完。
> **非目標**：不跑正式 RQ1 實驗（那要 DRAIN-DONE + 完整 KG#4 + ×3 + 完整指標）；本任務只交付可重複執行的比較 harness 與前導測試能力。

---

## 0. 背景

現況（見 `docs/論文/05_實驗設計與評估.md` §5.2／§5.4.1、`docs/報告/35`、`docs/報告/18`）：

- 已跑過的比較（報告 18/25/26）只有 4 條件：A/B「KG Agent」（BFS ∪ Fact-RAG ∪ RRF 融合 ∪ 接地/2b **整包**）、C「標準化 RAG MVP」（句子級，非中性 baseline）、D「純 LLM」。
- **Fact-RAG（`vector_search_facts()`）從來沒有被單獨拉出來當一條對照** —— `chat()` 只有 `use_svo=false`（全不檢索）與 `use_svo=true`（BFS + Fact 都跑），無法單獨關一邊。
- B0/B1 檢索側程式已存在（`build_baseline_chunk_index.py` + `services/baseline_rag_service.py`），但**不做生成**，也還沒接上 `chat()` 的共用生成路。

本任務補上「−BFS / Fact-RAG only / K−2b」等消融所需的開關與 harness。

---

## 1. 七條 arm 定義

| # | arm | 檢索內容 | 生成端 | 隔離出什麼 |
|---|---|---|---|---|
| **D** | 純 LLM | 不檢索 | 同一生成 stack（無 context） | 檢索有沒有用 |
| **B0** | chunk-RAG（naive） | 原文 chunk（`sentence_aware_chunking`）dense top-k | 同一生成 stack | 最低文字 RAG 基準 |
| **B1** | chunk-RAG（strong） | B0 + BM25 混合 RRF + 選配 cross-encoder rerank | 同一生成 stack | 調校過的當代文字 RAG（RQ1 硬前提） |
| **F** | Fact-RAG only | `vector_search_facts()`，**關掉 `bfs_query()`** | 同一生成 stack | 「文字→Fact 層」向量檢索，不走圖 |
| **G** | BFS only | `bfs_query()`，**關掉 `vector_search_facts()`** | 同一生成 stack | 純圖遍歷 |
| **K** | KG full | BFS ∪ Fact-RAG ∪ RRF 融合 ∪ 接地核對 ∪ 2b | 同一生成 stack | 現行完整 KG 路徑（= 報告 18 條件 A） |
| **K−2b** | KG full 但關掉限制性重生 | 同 K，不做接地觸發的重新生成 | 同一生成 stack | 2b 定向修訂的邊際效果（報告 38 partial-KG 說「無感」，此處驗證） |

**核心原則（§5.4.1）**：B0/B1/F/G/K/K−2b **只差餵進去的 context lines**，生成端逐位元相同 —— 否則分不出「贏在檢索」還是「贏在生成端機制」。

B2（Agentic RAG）**不在本任務範圍**：`services/agentic_baseline_service.py` 的真實 reflect prompt 尚未寫，另案處理。

---

## 2. 實作前的可行性盤點（★ 必做，先於任何程式改動）

交付物：`check_comparison_readiness.py`（見 §3.5）。先手動確認以下各項，再把檢查邏輯寫進腳本。

### 2.1 各種向量化是否有被持久化保存

逐一確認下列向量在**目標測試 KG**（見 §2.3）是否真的存在、可讀：

| 向量 | 哪條 arm 需要 | 確認方式 | 已知陷阱 |
|---|---|---|---|
| **原文 chunk 向量**（`.npy`） | B0、B1 | `build_baseline_chunk_index.py` 是否已對目標 KG 跑過、`.npy` 檔在不在（檔名帶 chunk_size） | ⚠️ **不能用 Neo4j `Chunk.chunk_embedding_vector`** —— 那 embed 的是「標準化 SVO chunk 文字」（軌道 2 = 專案貢獻，`embed_svo_chunks()` 的 `"\n".join(normalized_slice)`），不是原文。B0/B1 一定要自建 `.npy`。 |
| **Fact 節點 `fact_embedding`** | F、K、K−2b | Neo4j `MATCH (f:Fact {kg_id}) RETURN count(f), count(f.fact_embedding)` | ⚠️ `merge_triples_to_graph()` 抽取時若 `embedding_provider=None`，**完全不建 Fact 節點**（見該函式 docstring）。確認目標 KG 抽取時有帶 provider。 |
| **Entity `name_embedding`** | G（語意 fallback seed，`vector_search_entities()`） | Neo4j `MATCH (e:Entity {kg_id}) RETURN count(e), count(e.name_embedding)` 非空比例 | 純字面 seed（`_find_seed_entities()`）在真實測試命中率常為 0，語意 fallback 是必要路徑；`name_embedding` 缺了 G 幾乎無種子。 |
| **關係型別 35 類描述句向量** | K/F/G 的 §3.2§c 關係連結（`resolve_query_relation_type()`） | 索引存在性查詢 | 缺了會走 QNOMATCH → 退回不篩選（優雅降級，不致命，但要記錄）。 |
| **ConceptNode 向量** | （路由未接線，本任務不用） | 順手確認 | — |

### 2.2 抽取過程中是否有東西被捨棄 / 遺失

- `workspace/<kg_id>/<doc>/original.md` 是否完整存在（B0/B1 自建索引要 re-chunk 原文）。
- `sentences.json`（SVO 前處理用的穩定句子清單）是否還在。
- `task_queue.db` 與 workspace 目錄是否健在（避免重演 c15949bf 被 `git worktree remove` 清掉的事故，見 `docs/報告/32`）。
- 目標 KG 的 `pending` 任務數（`task_queue_service`）—— 前導測試要求 `pending = 0`。

### 2.3 目標測試 KG 選定

DRAIN 未完成 → **不要用還在抽的 KG#4 全量**（對 KG arm 不公平，報告 32/37/38 已踩過）。做法二選一：

1. **重建小型專用 KG**：比照報告 18 的「請假小場景」5 份文件（勞工請假規則、育嬰留職停薪實施辦法、外國人請假返國辦法、召集請假費用加成減除辦法、警察人員特別休假辦法），新 `kg_id`，抽取時**務必帶 embedding provider**（`OLLAMA_EMBEDDING_NUM_GPU=0`，bge-m3 走 CPU），跑到 `pending=0`。
2. 或指定 KG#4（`236903cf-055a-40a8-8923-b9d06601f3b7`）內**已 100% 抽完**的文件子集，用 `scope_doc_ids` 限定。

選定後把 `kg_id` 記進本任務書 §8。

---

## 3. 需要的程式改動

### 3.1 `chat()` 加檢索開關（隔離 F / G / K−2b）

- **現況**：`routers/agent.py::chat()` 約 1123 行 `if payload.use_svo:` 區塊內同時呼叫 `vector_search_facts()`（約 1131）與 `bfs_query()`（約 1148）；grounding 觸發重生在約 1225 行 `if payload.use_svo and ungrounded_claims:`。行號以實際檔案為準。
- **新增**（`models/knowledge_graph.py::ChatRequest` 選填欄位，預設值 = 現行行為，不得回歸）：
  - `retrieval_mode: Literal["both", "bfs_only", "fact_only"] = "both"`
  - `disable_grounding_regen: bool = False`
- **接線**：
  - `retrieval_mode == "fact_only"` → 跳過 `bfs_query()` 呼叫，`triples = []`。
  - `retrieval_mode == "bfs_only"` → 跳過 `vector_search_facts()` 呼叫，`fact_results = []`（注意 §3.2§c 關係連結、`_relevant_doc_ids_from_facts()` L1 範圍下推都依賴 fact_results，bfs_only 時這些要一併退化為「不下推、不篩選」，並記錄）。
  - `disable_grounding_regen == True` → 約 1225 行條件補 `and not payload.disable_grounding_regen`。
- **測試**：`tests/routers/test_agent.py` 各模式各一；**必測 `retrieval_mode="both"` + `disable_grounding_regen=False` 與現行 `chat()` 逐位元相同**（既有測試不得回歸）。

### 3.2 生成端共用：baseline arm 走 `chat()` 同一生成路

- **現況**：`services/baseline_rag_service.py` 只到 `build_context_lines()`，不生成。
- **最小改動**：把 `chat()` 內「context lines → `_build_prompt()` / 生成 / 接地核對 / 方案 B+2b / 回傳」這段抽成一個內部可呼叫函式，暫定：
  ```
  async def _generate_from_context_lines(
      question, context_lines, cfg, llm_provider, *,
      enable_grounding=True, ...
  ) -> ChatResponse 級結果
  ```
  `chat()` 自己也改呼叫它（確保零回歸）；harness 的 B0/B1/D arm 也呼叫它。
- **⚠️ §5.4.1**：完整生成端共用函式重構（P0b 第 2 項）建議等 T2/DRAIN。本任務做「前導夠用」版即可，但 **harness 輸出必須註明生成端對齊程度**（是否已 100% 共用同一函式，或仍有差異）。
- **不改** `bfs_query()` / `vector_search_facts()` 本身簽章。

### 3.3 harness：`run_retrieval_comparison.py`（放 repo root，比照 `run_chunk_size_sweep.py` / `run_t1_*.py` 慣例，不寫單元測試）

- **輸入**：`--kg-id`、`--questions <json 路徑 或 題號清單>`、`--arms D,B0,B1,F,G,K,K-2b`（可子集）、`--runs 3`、`--chunk-size 500`、`--out <dir>`。
- **對每 (題 × arm × run)**：呼叫對應路徑，收集
  `{answer, latency_s, llm_calls, bfs_triple_count, semantic_fact_count, retrieved_passages, grounding_stats}`。
- **輸出**：
  - 每 run 一個 JSON（原始輸出，未刪減，比照報告 18 §5 的記錄粒度）。
  - 一份彙總 Markdown：題 × arm 矩陣，含 mean/variance 欄，**人工評分欄留空**（0/1/2 grounded）。
- **每次跑記錄**：git commit hash、`kg_id`、各 arm 參數、embedding provider/model/dim、時間戳（§1.2 實驗可追溯性承諾）。

### 3.4 題組載入

- `docs/論文/05_附錄A_測試題庫.md` 目前是 Markdown。另存 / 轉出一份 `docs/附錄A題庫.json`：
  每題 `{id, question（逐字題幹）, gold_answer, source_article, complexity_label, dup_map}`。
- P0a-2 標註層（應取回事實 → KG#4 Fact ids、18-Q7 gold 待核、題幹口語化定版）尚未定版 → 先用現有 30 題的題幹 + gold + 複雜度標籤，`gold_facts` 欄留空待補。
- harness 支援 `--complexity single|multi|all` 過濾。

### 3.5 可行性檢查腳本：`check_comparison_readiness.py`（放 repo root）

- **輸入**：`--kg-id`、`--arms`。
- 對選定 arm 逐一檢查 §2.1／§2.2 所需資產：
  Fact 節點數與 `fact_embedding` 非空比例／`Entity.name_embedding` 非空比例／關係型別索引存在／`original.md` 存在／baseline `.npy` 是否已建／`pending` 任務數。
- **輸出**：PASS/FAIL 清單，每個 FAIL 附補救指令（例如「跑 `build_baseline_chunk_index.py --kg-id ... --chunk-size 500`」）。

---

## 4. 使用者跑比較測試的流程（交付後）

1. 選題組（附錄 A 全部 / 子集 / `--complexity` 過濾）。
2. 選 arm 子集。
3. `python check_comparison_readiness.py --kg-id <id> --arms <...>` → 確認需要的向量都在，補齊 FAIL 項。
4. `python run_retrieval_comparison.py --kg-id <id> --questions docs/附錄A題庫.json --arms <...> --runs 3 --out <dir>`。
5. 人工填 0/1/2 grounded 評分（前導）；或跑自動指標（正式版另議）。
6. 產出比較報告（下一個報告編號，`docs/報告/40_...`）。

---

## 5. 驗收標準

- [ ] `check_comparison_readiness.py` 能正確辨識缺失資產並給補救指令。
- [ ] 7 條 arm 都能對 §2.3 選定的小型測試 KG 跑通，同一題產出可比結果 JSON + 彙總表。
- [ ] `retrieval_mode="both"` + `disable_grounding_regen=False` 與現行 `chat()` 逐位元相同（既有 `tests/routers/test_agent.py` 全綠）。
- [ ] 新增開關各有單元測試。
- [ ] `pytest` 全套綠。
- [ ] harness 輸出註明生成端對齊程度。
- [ ] ⚠️ **不要改動 `docs/報告/36_*.md`**（使用者有長期未提交的 markdownlint 修改，見 memory）。

---

## 6. 明確不做

- 不跑正式 RQ1（等 DRAIN-DONE + 完整 KG#4）。
- 不實作 B2 Agentic RAG（reflect prompt 另案）。
- 不做完整生成端共用函式重構（等 T2；本任務只做前導夠用版）。
- 不改 `bfs_query()` / `vector_search_facts()` 簽章。
- 不動 §5.2 論文正文（消融組別的正式增修留待 L15 / 使用者定奪，本任務只交付 harness）。

---

## 7. 交接備註（環境）

- Neo4j：Docker 容器 `kg2-neo4j`。
- Ollama：在 WSL2 Ubuntu-24.04（systemd + netsh portproxy）。Windows 側重啟無效，用
  `wsl -d Ubuntu-24.04 -- sudo systemctl restart ollama`。
- 8GB VRAM → embedding 要 `OLLAMA_EMBEDDING_NUM_GPU=0`（bge-m3 走 CPU）。`EMBEDDING_PROVIDER=local` 已知壞，用 ollama。
- 主 drain 若仍在跑：**不要**併跑會吃 RAM 的東西（vmmemWSL 已 ~11GB）；不要跑 `rebuild_from_records` / `main.py` global worker；code deploy 後要跟 peer session 確認 drain 是否需重啟。
- git：master 直接做，ff-merge，commit 訊息尾附
  `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` 與 `Claude-Session` 行。

---

## 8. 執行紀錄（實作視窗填寫）

- 目標測試 KG id：`________`
- 目標測試 KG 內容：`________`
- 完成的 commit：`________`
- 生成端對齊程度：`________`
- 已知 caveat：`________`
