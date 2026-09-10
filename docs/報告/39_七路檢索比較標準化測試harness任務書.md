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

### 2.3 目標測試 KG（前導版 —— 已定案）

DRAIN 未完成（2026-09-10 查：KG#4 `236903cf-055a-40a8-8923-b9d06601f3b7` = 1979/3303 chunk ≈ 60%，64 份文件裡 32 份 `pending=0`），**不用等 DRAIN-DONE 才能做前導比較**。

**定案：前導比較用 KG#4 的「6 份題目來源文件」子集**（報告 18/25/26 的題目來源，皆在 KG#4 已完成清單內）：

| 文件 | 對應題目 |
|---|---|
| `N0030006_勞工請假規則` | 報告 18 Q1／Q6／Q7 |
| `N0030018_育嬰留職停薪實施辦法` | 報告 18 Q2 |
| `N0090051_受聘僱從事就業服務法第四十六條第一項第八款至第十款規定工作之外國人請假返國辦法` | 報告 18 Q3 |
| `F0040034_員工接受召集請假期間薪資費用加成減除辦法` | 報告 18 Q4 |
| `D0080015_警察人員特別休假辦法` | 報告 18 Q5 |
| `N0050030_災區受災勞工保險與勞工職業災害保險及就業保險被保險人保險費支應及傷病給付辦法` | 報告 37／38 Q5 |

- harness 用 `--scope-doc-ids` 限定這 6 份 → KG arm（F/G/K）的 BFS／Fact 檢索被 `scope_doc_ids` 下推限定，不會撈到其他半抽文件，對照公平。
- 需要更大題面時再擴到 KG#4 的 32 份完成子集（同樣 `--scope-doc-ids`）。
- **不要用**主 checkout `workspace/` 的 `2ae9d28b`（69 docs）／`deb24e7c`（56 docs）—— 那是 2026-08-07~08-20 era 抽的，落後現行管線一大票修正（發現 3/4/C、naturalization 之前），不能代表「現行系統」。

選定的 `kg_id` 與實際 6 份文件清單記進本任務書 §8。

### 2.4 抽取新鮮度硬性前置（★ 跑比較前必做）

**問題**：`task_queue` 標 `completed` 只代表「該 chunk 到了終態」，**不代表「用最新修正的管線抽的」**。report 37 的後續修正（`num_predict` 1024→4096、timeout 300→600，commit `94b9b9a`；`N0050030` c3、`N0060016` c2 曾是 `num_predict=1024` 長列舉截斷案例）是在 drain 開始後才進的 —— KG#4 早期抽的 chunk 可能仍是截斷版。

**為什麼這會讓「新版方法」不可信**：抽取截斷**不對稱**地影響各 arm ——

| arm | 讀什麼 | 受抽取截斷影響 |
|---|---|---|
| B0／B1（chunk RAG） | `original.md` 原文 | ❌ 完全不受影響 |
| F／G／K（KG 路徑） | Fact 節點／關係邊（從三元組來） | ✅ 截斷 → 少事實 → 表現被低估 |

若前導報告出現「chunk RAG ≈ 或 > KG 路徑」，審查者可一句話推翻：「你的 KG 弱只是因為抽取沒抽完，不是方法問題。」

**硬性前置步驟**：

1. §2.3 的 6 份（或 32 份）比較用文件，在 `reextract-v2` **最新 HEAD** 上以 `force_rebuild=True` **重抽一次**（6 份 ~ 30–60 分鐘，`OLLAMA_EMBEDDING_NUM_GPU=0`；抽取須帶 embedding provider 讓 Fact 節點與 `fact_embedding` 一併重建）。
2. `check_comparison_readiness.py` 必須檢查：每份比較文件的**所有 chunk** 在 `task_queue.updated_at` 上都**晚於最後一個 extraction-side commit 的日期**（用 `git log -1 --format=%cI -- services/svo_service.py core/constants.py` 之類取基準，或直接接受「本次 force_rebuild 的時間戳」）。任一 chunk 較舊 → FAIL，指示 `force_rebuild` 該份。
3. §8 記錄實際重抽所在的 `reextract-v2` commit hash 與重抽完成時間。

**誠實邊界**：就算 DRAIN-DONE 也不是「終版」（管線仍在改：G4 的 Q5 起算日生成側、E3 的 Q2 二次為限、`_SCOPE_MODIFIER_PATTERN` 待上線）。「可信」的定義 = **所有 arm 跑在同一份、統一用當前 HEAD 抽的 KG 上，且報告明說 commit／範圍／正式版在報告 40**，不是「用最終管線」。

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

- **輸入**：`--kg-id`、`--arms`、`--doc-ids`（比較用文件清單）。
- 對選定 arm 逐一檢查 §2.1／§2.2 所需資產：
  Fact 節點數與 `fact_embedding` 非空比例／`Entity.name_embedding` 非空比例／關係型別索引存在／`original.md` 存在／baseline `.npy` 是否已建／`pending` 任務數。
- **★ 抽取新鮮度檢查（§2.4）**：對每份 `--doc-ids` 文件，查 `task_queue` 內該 `source` 的**所有 chunk** 的 `updated_at`，全部須晚於基準時間（最後一個 extraction-side commit 日期，或指定的 force_rebuild 時間戳）。任一較舊 → FAIL。
- **輸出**：PASS/FAIL 清單，每個 FAIL 附補救指令（例如「跑 `build_baseline_chunk_index.py --kg-id ... --chunk-size 500`」、「在 reextract-v2 HEAD 對 `<doc>` 跑 `force_rebuild=True` 重抽」）。

---

## 4. 使用者跑比較測試的流程（交付後）

0. （前導版一次性）在 `reextract-v2` HEAD 對 §2.3 的 6 份比較文件跑 `force_rebuild=True` 重抽（§2.4），記下 commit hash。
1. 選題組（附錄 A 全部 / 子集 / `--complexity` 過濾）。
2. 選 arm 子集。
3. `python check_comparison_readiness.py --kg-id <id> --doc-ids <...> --arms <...>` → 確認需要的向量都在、抽取新鮮度 PASS，補齊 FAIL 項。
4. `python run_retrieval_comparison.py --kg-id <id> --doc-ids <...> --questions docs/附錄A題庫.json --arms <...> --runs 3 --out <dir>`。
5. 人工填 0/1/2 grounded 評分（前導）；或跑自動指標（正式版另議）。
6. 產出比較報告（下一個報告編號，`docs/報告/40_...`），標題掛「前導」，正文載明抽取 commit／文件範圍／正式版在 DRAIN-DONE 後。

> **執行時序**：§4／§4.1 是 harness **交付驗收後**才做的動作，不在本任務書的實作範圍。實作視窗做完 SDD-1～SDD-5（完整測試路徑跑通、pytest 全綠、§8 填妥），使用者才依 §4.1 的批次策略跑前導測試、之後 DRAIN-DONE 再跑正式測試。

### 4.1 批次化比較策略（跑測試時參考，非 harness 實作項）

**原則**：一個比較 = 一個主張 + 它需要的 arm 子集 + 題面規模。不同主張需要的證據量差很多，不必每次都 7 arm × 全題 × ×3。

**三種規模**：

| 規模 | 配置 | 用途 |
|---|---|---|
| 快篩 | 2–3 arm，5–8 題，×1 | 看形狀——這條路值不值得深究 |
| 標準對照 | 2–4 arm，按複雜度分層各 6–10 題，×3 | 下「A > B」結論 |
| 等價（證「沒差」） | 需預定義等價界 + 更大樣本 | 通常不值得單獨做，引報告 38 + 標 caveat |

**跨批次錨定紀律**（否則不同批不能互比）：

1. 所有批用**同一個 KG（同一次 force_rebuild 的 commit）**、**同一份題庫 JSON**、**同一個生成 stack commit**。
2. **每批固定放一條共同 arm 當錨**（建議 `B1`）。不同批分數靠它對齊——B1 在批 1 拿 7.2、批 2 拿 5.1，就知道兩批題面難度不對等、不能直接跨比。
3. harness 每次記 commit／kg_id／題號清單／時間戳。

**建議批次（前導版，6 份題目文件 + 附錄 A 對應題）**：

| 批 | arm | 題面 | runs | 目的 |
|---|---|---|---|---|
| 批 1 檢索基線（快篩） | D / B0 / **B1** | 5–8 題 | ×1 | 「檢索有用」+「B1 站得住」+ B0→B1 有無增益跡象。若 B0≈B1，B1 之後可退回 dense-only 省事 |
| 批 2 圖 vs 向量（核心） | **B1** / F / G / K | 單跳／多跳各 6–8 題 | ×3 | 回答 RQ1「KG 贏在哪類題」+「Fact-RAG 單獨多強」。主戰場，值得吃樣本 |
| 批 3 生成端消融（小） | K / K−2b | 同批 2 的題 | ×3 | 預期效果 ≈ 0，不新增題，搭批 2 多跑一條 arm |

**何時可停**：

- 效果大且方向一致（D vs 其他）：5 題同向即可，不必 ×3。
- 效果中等：分層後每層 ×3，`mean 差距 > 2 × run-to-run variance` 且 n ≥ 6 → 可下結論。
- 效果小／接近：老實寫「前導未觀察到顯著差異，正式版 report 40 加大樣本」。

⚠️ `qwen2.5:7b` 非決定性（batch-size 依賴，見 memory）→ 任何要下「A > B」結論的比較，那條 arm **至少 ×3**；純「看形狀」的快篩可 ×1。

---

## 5. 驗收標準

- [ ] §2.3 的 6 份比較文件已在 reextract-v2 HEAD `force_rebuild` 重抽，§8 記錄 commit 與時間。
      → **⏳ 待主 drain DRAIN-DONE 後執行**（RAM 衝突）；`check_comparison_readiness.py` 已
      確認這 6 份的抽取新鮮度 FAIL（2026-09-07 版，早於抽取端基準）→ 重抽確有必要。
- [x] `check_comparison_readiness.py` 能正確辨識缺失資產與**抽取過舊**的文件，並給補救指令。
      （`c26e05a`；已對 KG#4 6 份實跑：original.md ✅、pending=0 ✅、新鮮度 FAIL ＋ 補救指令 ✅）
- [ ] 7 條 arm 都能對 §2.3 選定的 6 份文件子集跑通，同一題產出可比結果 JSON + 彙總表。
      → harness (`run_retrieval_comparison.py`, `2c64bd9`) 已交付、`--dry-run` 驗證 126 次呼叫
      計畫解析正確；實際跑通卡 force_rebuild ＋ DRAIN-DONE ＋ baseline `.npy`。
- [x] `retrieval_mode="both"` + `disable_grounding_regen=False` 與現行 `chat()` 逐位元相同
      （既有 `tests/routers/test_agent.py` 101 個全綠；SDD-3 抽取後仍 114 全綠含 status-phase 順序測試）。
- [x] 新增開關各有單元測試（`efde509`：三開關各自行為 + `_intersect_doc_scopes` 四邊界 +
      `scope_doc_ids=None` 零回歸錨點；`6ebbb22`：baseline 模式共用生成路四測試）。
- [x] `pytest` 全套綠（801 passed）。
- [x] harness 輸出註明生成端對齊程度（`manifest.json` 的 `generation_alignment` 欄）。
- [x] ⚠️ **不要改動 `docs/報告/36_*.md`**（本次未觸碰）。

---

## 6. 明確不做

- **不在本任務內跑前導/正式比較測試本身** —— harness 交付驗收（SDD-1～5）後，才由使用者依 §4／§4.1 執行；本任務只交付「測試路徑」。
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

- 目標測試 KG id：`236903cf-055a-40a8-8923-b9d06601f3b7`（KG#4，前導版用 §2.3 的 6 份文件子集）
- 實際比較文件清單（force_rebuild 後）：以 §2.3 的 6 份資料夾名為準——
  `D0080015_警察人員特別休假辦法`、`F0040034_員工接受召集請假期間薪資費用加成減除辦法`、
  `N0030006_勞工請假規則`、`N0030018_育嬰留職停薪實施辦法`、
  `N0050030_災區受災勞工保險與勞工職業災害保險及就業保險被保險人保險費支應及傷病給付辦法`、
  `N0090051_受聘僱從事就業服務法第四十六條第一項第八款至第十款規定工作之外國人請假返國辦法`
  （對應題號 18-Q1~Q5、26-Q5，見 `docs/附錄A題庫.json` 的 `pilot=true`）
- force_rebuild 所在 reextract-v2 commit：**⏳ 待執行**（`check_comparison_readiness.py` 已確認
  這 6 份的最舊 chunk `updated_at` 皆為 `2026-09-07T11:xx`，早於抽取端基準
  `2026-09-08T22:03:36+08:00` → §2.4 FAIL，force_rebuild 確有必要）。RAM-heavy、
  與主 drain 衝突 → 排在主 drain DRAIN-DONE 後執行，屆時補記 commit 與時間。
- force_rebuild 完成時間：**⏳ 待執行**（同上）
- harness / 開關 / 共用生成路完成的 commit：
  - SDD-2（chat() 檢索開關 `retrieval_mode`／`disable_grounding_regen`／`scope_doc_ids`）：`efde509`
  - SDD-3（抽出 `_generate_from_context_lines()` 共用生成路）：`6ebbb22`
  - SDD-1（`check_comparison_readiness.py`）：`c26e05a`
  - SDD-4（`docs/附錄A題庫.json` ＋ `run_retrieval_comparison.py`）：`2c64bd9`
  - 全套 pytest 801 綠（既有 797 ＋ 新增 13：SDD-2 九、SDD-3 四）；`chat()` 逐位元零回歸。
- 生成端對齊程度（是否 100% 共用同一函式）：**部分共用（前導夠用版）**。
  B0/B1/D 與 F/G/K/K−2b 共用 `_generate_from_context_lines()` ＋ 同一個
  `_build_prompt()`／`_build_constrained_prompt()`（`context_lines=` 參數）——同一 prompt
  模板、同一「draft → verify → 未接地重生 → 選擇性轉繁」尾段。**差異**：baseline arm
  （context_lines 模式）走**單次強約束重生**（＝ KG 路徑 `grounded_claim_count == 0` 的整份
  重寫分支），**不套** K 專屬的 2b 定向修訂、分解式重生、G3 列舉完整性 guard。
  完整生成端共用重構＝ P0b 第 2 項，建議延到 T2/DRAIN（§3.2、§6）。harness manifest.json
  的 `generation_alignment` 欄逐次記錄此程度。
- 已知 caveat：
  1. **抽取新鮮度**：force_rebuild 尚未執行前，F/G/K 讀到的 6 份 Fact 仍是 2026-09-07 版
     （可能含 `num_predict=1024` 長列舉截斷）→ 前導比較須等 force_rebuild 後才可信（§2.4）。
  2. **B0/B1 索引未建**：`build_baseline_chunk_index.py <kg> --chunk-size 500` 尚未對 KG#4 跑過
     （`check_comparison_readiness.py` 已標 FAIL ＋ 補救指令）。
  3. **關係型別向量索引**：`check_comparison_readiness.py` 對 KG#4 查該索引時尚未驗證
     （Neo4j 連線用預設 7687，KG#4 在 17990）；缺了 §3.2§c 走 QNOMATCH 優雅降級，報告 40 需記。
  4. **scope_doc_ids 交集歸零**：語意 Fact 命中的來源全在 6 份子集外時，`_filter_*` 的歸零
     守衛會放行範圍外事實（角落案例，6 份即題目來源，正常不會發生；`_intersect_doc_scopes()`
     此時回傳明確子集本身、bfs_query 仍下推 6 份）。
  5. **llm_calls 含核對呼叫**：harness 的 `_CountingLLM` 也包住 judge provider，`llm_calls`
     統計含 `verify_fact_grounding()` 的 JSON 呼叫（前導夠用；報告 40 要分開再拆）。
  6. `ChatRequest` 實際在 `models/document.py`（非任務書 §3.1 寫的 `models/knowledge_graph.py`）。
