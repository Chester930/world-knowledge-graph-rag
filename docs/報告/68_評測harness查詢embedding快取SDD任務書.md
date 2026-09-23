# 68 評測harness查詢embedding快取SDD任務書（交付Codex）

**建立日期**：2026-09-22
**文件性質**：任務書，交付 Codex 執行，完成後由 Claude Code 複驗。
**觸發脈絡**：今天的獨立judge pilot（`57-CANARY5`）發現 Stage 1 檢索 recall 在 judge 模型不變、KG不變的情況下，兩次獨立執行間從1.0掉到0.5——查證文獻（`docs/參考文獻/38_檢索embedding非決定性與可重現性/README.md`，Wang et al. 2025 *On The Reproducibility Limitations of RAG Systems*）確認根因：**向量搜尋演算法本身通常可完全重現，雜訊來源是每次重新呼叫embedding model的生成變異**（與本專案報告20已引用的LLM生成非決定性根因同一機制家族，發生在embedding端）。文獻建議的低成本解法：**embedding caching**。

---

## 0. 一頁摘要

**目標**：讓評測harness（`scripts/eval/run_rq1_comparison.py`／`scripts/eval/frozen_baseline_stage.py`）在做A/B對照實驗（例如今天的獨立judge pilot、之後任何「固定其他變因、只換一個」的pilot）時，**同一題目的query embedding只算一次、跨臂/跨次執行共用**，避免embedding生成本身的變異污染比較結果。

**範圍**：**只動評測harness層，不動 `routers/agent.py::chat()` 或任何production程式碼**——`chat()` 目前在每次呼叫時都會重新 `embedding_provider.encode(payload.question)`（`routers/agent.py:1600`），這是正確的production行為（不應該對正式使用者請求做跨request快取，語意上也不需要），本任務書**不改這裡**。做法是在 `core/providers/factory.py` 加一個明確標示「僅供評測/測試使用」的override hook，讓harness能把`_embedding`替換成一層快取包裝，`chat()`透過`get_embedding_provider()`拿到的仍是同一個全域provider，**不需要修改`chat()`本身任何一行**。

**預設行為**：不啟用快取時（不傳新CLI旗標），**完全零行為變化**。

---

## 1. 現況（已查證，供直接引用）

1. `core/providers/base.py::EmbeddingProvider`（第22-61行）：抽象介面只有4個成員——`dim`（property）、`model_name`（property）、`async encode(text) -> list[float]`、`async encode_batch(texts) -> list[list[float]]`（預設逐一呼叫`encode`，provider可覆寫）。
2. `core/providers/factory.py`：模組層級單例 `_embedding: EmbeddingProvider | None`（第9行），由 `init_providers()`（約第62-90行）依 `settings.embedding_provider` 建立；`get_embedding_provider()`（第127-130行）直接回傳這個全域單例，未初始化時 raise。**目前沒有任何override/替換機制**。
3. `routers/agent.py::chat()`（第1600行）：`question_vector = await embedding_provider.encode(payload.question)`，`embedding_provider = get_embedding_provider()`（第1599行）——每次呼叫都是全新的 `encode()` 呼叫，沒有任何快取。**本任務書不改這裡**；只要 `factory._embedding` 被換成快取包裝版，這裡自動受益，不需要動這個檔案。
4. `scripts/eval/run_rq1_comparison.py`：第648行呼叫 `init_providers()`；第247行 `emb = get_embedding_provider()`（供harness自己的其他用途，例如 `_score_lines_by_embedding` 這類離線分析，不是`chat()`內部路徑）。harness對每一題透過 `_drain_chat()`（實際發送請求走 `chat()` 路徑，經SSE串流）取得答案，也就是**`chat()`內部的`encode()`呼叫，harness本身完全看不到、也無法從外部注入預先算好的向量**——這是為什麼必須在`factory._embedding`這一層動手，而不是在harness端自己算好向量卻沒有管道傳進`chat()`。

---

## 2. 設計

### 2.1 `CachingEmbeddingProvider`（新檔案，建議 `scripts/eval/embedding_cache.py`）

包裝任一個 `EmbeddingProvider` 實例，實作相同介面：
- `dim`／`model_name`：直接轉發底層 provider。
- `encode(text)`：快取鍵為 `(self.model_name, text)` 的雜湊（例如 `hashlib.sha256`）；命中就回傳快取值，未命中才呼叫底層 `encode()` 並寫入快取。
- `encode_batch(texts)`：**不要**直接用父類別預設的逐一呼叫（會繞過快取的批次效率），改成先查快取分出「已命中」與「未命中」兩組，只對未命中的文字呼叫底層 `encode_batch()`，回填快取後按原順序組回完整結果。

**持久化**：快取寫入使用者指定的**單一JSON檔案路徑**（不是自動衍生自`--out`目錄）——這樣才能讓今天這種「兩次獨立subprocess呼叫（`run1`、`run2`）需要共用同一份快取」的情境成立。JSON結構：`{"<model_name>": {"<sha256(text)>": [向量...]}}`，每次新增命中就整份重寫（這個檔案預期很小，題目數量級，不需要考慮效能，寫清楚比效能重要）。初始化時檔案不存在就視為空快取，正常運作。

### 2.2 `core/providers/factory.py` 新增 override hook

新增函式（**docstring需明確標示「僅供評測/測試使用，不要在production程式碼路徑呼叫」**）：

```python
def override_embedding_provider_for_eval(wrap) -> None:
    """僅供離線評測harness使用：用 wrap(現有的_embedding) 替換全域單例。
    呼叫時機必須在 init_providers() 之後。不要在 routers/ 或任何正式請求
    處理路徑呼叫這個函式——它改的是行程層級的全域狀態，正式服務不應該
    在請求處理中途替換 provider。"""
    global _embedding
    if _embedding is None:
        raise RuntimeError("先呼叫 init_providers()")
    _embedding = wrap(_embedding)
```

### 2.3 harness 佈線（`scripts/eval/run_rq1_comparison.py` 與 `frozen_baseline_stage.py`）

- `run_rq1_comparison.py` 新增選填 CLI 參數 `--embedding-cache <path>`（預設不傳＝`None`＝完全不啟用，行為零變化）。`init_providers()` 呼叫後，若有傳這個參數，才呼叫 `override_embedding_provider_for_eval(lambda p: CachingEmbeddingProvider(p, cache_path))`。
- `frozen_baseline_stage.py`（`cmd_run`，約第77-104行）的 `cmd` 組裝清單，新增選填 `--embedding-cache` 透傳（同樣預設不傳）。

---

## 3. 任務清單

### T1（S）：`CachingEmbeddingProvider` 實作＋單元測試

- 依 §2.1 設計實作，測試涵蓋：cache miss後cache hit不再呼叫底層provider（用假的fake provider、計數呼叫次數斷言）、`encode_batch`部分命中部分未命中時只呼叫底層一次且只含未命中的文字、持久化（寫入後用新的`CachingEmbeddingProvider`實例讀同一個檔案能拿到快取值，不需要底層provider）、`model_name`不同時視為不同快取鍵（避免換模型後沿用舊向量）。

### T2（S）：`factory.py` override hook＋單元測試

- 依 §2.2 實作，測試涵蓋：`init_providers()`前呼叫會raise、呼叫後`get_embedding_provider()`回傳的是包裝後的實例、**production呼叫路徑（`routers/agent.py`）完全沒有引用這個新函式**（用grep或import檢查確保沒有被production code誤用）。

### T3（S）：harness 佈線＋回歸測試

- 依 §2.3 佈線兩個腳本。測試涵蓋：不傳`--embedding-cache`時行為與現況逐字相同（golden-test精神，比照報告66的做法）；傳了之後，同一題目跑兩次（模擬兩個獨立subprocess呼叫`frozen_baseline_stage.py run`）確認第二次沒有觸發底層`encode()`（可以用一個記錄呼叫次數的fake embedding provider驗證，或至少驗證快取檔案內容符合預期）。

### T4（S，驗證用，不要自動執行大規模實驗）：小範圍複驗

用今天的7題（`.claude/tmp/report65_targeted_karm_20260922/questions.json`）**重跑一次同一問題兩次**（不需要換judge，單純驗證「同一題連續跑兩次，有快取vs沒快取，檢索結果是否穩定」這件事本身），確認有快取時兩次執行的 Stage 1 Context Recall **完全一致**（沒快取時可能像今天一樣不一致）。**只需要驗證這個機制本身有效，不需要重新做獨立judge的pilot**——那是之後使用者決定要不要繼續投入的獨立任務。

---

## 7. 2026-09-22 T1–T4 執行結果

### 實作

- T1：新增 `scripts/eval/embedding_cache.py` 的 `CachingEmbeddingProvider`。快取鍵為
  `model_name + SHA-256(text)`，支援 `encode()`、`encode_batch()`，只把未命中的唯一文字送到底層 provider，並以 JSON 持久化；輸出順序維持呼叫端輸入順序。
- T2：`core/providers/factory.py` 新增明確標示 eval/test-only 的
  `override_embedding_provider_for_eval()`。它只能在 `init_providers()` 後包裝全域 embedding
  provider；未初始化時會 raise。沒有修改 `routers/agent.py`，正式 `chat()` 路徑仍使用既有的
  `get_embedding_provider()`。
- T3：`run_rq1_comparison.py` 與 `frozen_baseline_stage.py` 新增選填
  `--embedding-cache`。未傳參數時不建立 wrapper、不寫快取檔，也不增加新的呼叫路徑；既有命令
  介面保持相容。新增測試涵蓋 cache hit/miss、batch 去重、跨 instance 持久化、model 隔離、factory
  override，以及兩個 harness 的 default/optional CLI 行為。

### T4 小規模驗證

使用 7 題 `.claude/tmp/report65_targeted_karm_20260922/questions.json`，以相同的 frozen
baseline、KG、生成／judge 設定連續執行兩次；兩次都使用同一個快取檔
`.claude/tmp/report68_embedding_cache_20260922/embedding_cache.json`。本次沒有重跑獨立 judge
pilot；兩次使用預設共用 judge，`OLLAMA_LLM_THINK=false` 僅避免思考模型設定造成額外變因。

| 題目 | run1 Stage 1 Context Recall | run2 Stage 1 Context Recall | 是否一致 |
|---|---:|---:|---|
| 18-Q5 | 1.0 | 1.0 | 是 |
| 57-DIST1 | 1.0 | 1.0 | 是 |
| 57-DIST2 | 1.0 | 1.0 | 是 |
| 57-CANARY5 | 1.0 | 1.0 | 是 |
| 57-AGGR7 | 0.3333 | 0.3333 | 是 |
| 57-AGGR8 | 0.75 | 0.75 | 是 |
| 57-AGGR19 | 0.25 | 0.25 | 是 |

兩次均完成 7/7 records，沒有 harness error 或逾時；逐題 recall exact match。這只證明在此
7 題與此快取設定下 Stage 1 recall 可重現，不對獨立 judge 是否改善生成端問題下結論。

---

## 4. 明確不做的事

- **不修改 `routers/agent.py::chat()` 或任何production行為**——這個任務書全程只動 `core/providers/factory.py`（新增一個明確標示eval-only的函式）與 `scripts/eval/` 下的檔案。
- 不把快取機制接進 `KGConfig`／domain pack——這是評測工具，不是產品功能。
- 不自動重跑今天的獨立judge pilot——T4只驗證快取機制本身有效，是否要重跑judge pilot由使用者另外決定。
- 不處理LLM生成端的非決定性（那是既有、已知、有不同因應方式如`--runs`多次執行取眾數的問題，跟這次要解決的embedding非決定性是不同層次）。

---

## 5. 驗收標準

1. `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py` 全綠，新增測試反映T1-T3實際新增的邏輯。
2. `--embedding-cache` 不傳時，兩個腳本行為與目前逐字相同（可用既有golden-test精神驗證，或至少確認沒有新增的呼叫路徑被觸發）。
3. T4的複驗結果（有快取時兩次執行檢索結果一致）附在commit message或本報告新增小節。
4. 不需要對KG做任何寫入；commit前不需要額外詢問，但完成後不要自動接著做T4以外的任何延伸實驗。

---

## 6. 給 Codex 的指令（可直接貼上）

> 請執行 `docs/報告/68_評測harness查詢embedding快取SDD任務書.md` 的 T1-T4。背景：今天的獨立judge pilot發現同一題目、judge與KG都不變的情況下，兩次執行的Stage 1檢索recall不一致，查證文獻（`docs/參考文獻/38_檢索embedding非決定性與可重現性/README.md`）確認根因是每次重新呼叫embedding model的生成變異，不是向量搜尋演算法本身，文獻建議的解法是embedding caching。**範圍限定**：只動 `core/providers/factory.py`（新增明確標示eval-only的 `override_embedding_provider_for_eval()`）與 `scripts/eval/` 下的檔案（新增 `embedding_cache.py`、佈線 `run_rq1_comparison.py`／`frozen_baseline_stage.py` 的`--embedding-cache`選填參數），**完全不要修改 `routers/agent.py` 或任何production程式碼**——`chat()` 透過現有的 `get_embedding_provider()` 全域單例自動受益，不需要改它。預設（不傳`--embedding-cache`）必須是零行為變化。T1/T2/T3依報告§3實作＋單元測試；T4用今天已有的7題questions.json做一次「同一題連續跑兩次，有快取確認Stage 1 Context Recall完全一致」的小驗證即可，**不要自動重跑獨立judge pilot**，那是使用者之後另外決定的事。完成後跑 `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py` 確認全綠並回報結果；commit前不需要額外詢問，但**不要**對KG執行任何寫入。
