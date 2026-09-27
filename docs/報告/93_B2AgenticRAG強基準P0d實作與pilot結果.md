# 93．B2 Agentic RAG 強基準 P0d 實作與 pilot 結果

**日期**：2026-09-27
**文件性質**：實作＋真實pilot跑測結果報告。對應報告36 §8「落地待辦」最後一項（P0d：生成端＋真實reflect LLM prompt＋harness併入，本報告完成前狀態為「未做」）。
**執行者**：Claude Code（背景fork），使用者已核准「啟動B2實作，跑完整個流程再彙整結果」。

---

## 0. 一頁摘要

P0d的程式碼實作（真實LLM反思、harness B2臂接線、成本profile）**已完成並通過pytest（1170 passed，本輪新增14個測試）**。真實pilot跑測**因系統記憶體壓力被背景任務保護機制中途終止**，不是程式或跑測本身的錯誤——在被中止前已完整跑完8題的B0/B1/B2三臂真實比較（另有1題只跑完B0/B1，B2未及執行），全部來自真實Neo4j/Ollama呼叫、無mock資料。

**8題真實比較結果（n=8，非常小樣本，僅供pilot參考，不是正式RQ1結論）**：B0（M1）平均atomic_accuracy 0.938、B1（M2）0.812、B2 0.917；B2平均延遲98.7秒／題（B0/B1約77秒）、平均5.9次LLM呼叫／題（B0/B1固定約1.1次）、平均context 1304 tokens（B0/B1約660 tokens）。B2在1題（18-Q3）救回了B0/B1都答錯一半的案例，但在另1題（18-Q5）明顯退步（0.33 vs B0的1.0），根因是report 36設計的`retrieval_budget=8`被前面子問題耗盡，導致第3個子問題完全沒有機會檢索（`rounds_per_subquestion=[5,3,0]`）——這是本次pilot發現的**新confounder**，報告36原設計沒有預期到。

**誠實評估**：8題樣本量太小，不足以判斷B2是否值得投入更大規模的正式RQ1對照；但已經證明（1）P0d的程式碼路徑真實可跑通、生成端與B0/B1逐位元共用同一套堆疊；（2）B2的多輪檢索確實在至少1個案例展現出「救回」能力；（3）也確實發現了`retrieval_budget`分配不均的新風險，需要在報告36的設計上補一條「budget在子問題間如何分配」的規則才能公平比較。**不建議在沒有解決這個budget分配問題之前，把本次8題數字當成B2的代表性結論。**

---

## 1. 實作內容

### 1.1 `services/agentic_baseline_service.py`：新增 `gather_evidence_agentic_async()`

既有的 `gather_evidence_agentic()`（P0c，同步）保持不動，13個既有單元測試不受影響。新增一個 async 孿生函式，簽名與行為逐行對應，差異只在於 `retrieve`/`reflect` 兩個依賴注入改成 `async` callable、內部改用 `await`。

**為什麼需要這個孿生版本**：B2 在一題裡會對*多個不同的 query*（原始子問題＋依 reflect 缺口精煉後的新 query）各自呼叫一次 `retrieve()`，每次都要重新 `emb.encode()`（這是 async）。同步函式內不能 `await`，所以另立 async 版本，供 harness（`retrieve`/`reflect` 需要 await 的呼叫端）使用。

新增6個async單元測試（`tests/services/test_agentic_baseline_service.py`），逐一對應既有同步版測試覆蓋的規則（simple 路徑退回單次、complex 路徑多輪、reflect 提前結束、max_rounds／retrieval_budget 上限、證據去重）。

### 1.2 `scripts/eval/run_rq1_comparison.py`：`_b2_reflect()` 真實 LLM 反思

新增 `_b2_reflect(llm_provider, sub_question, evidence_texts) -> ReflectVerdict`：用「generator 固定」那顆模型（呼叫端傳入 `counting`，即 `_CountingLLM` 包裝的 provider）呼叫 `generate_json()`，prompt 輸入＝子問題＋目前證據文字（超過4000字截斷），輸出要求 JSON `{"sufficient": bool, "missing": str}`。

- 沒有任何證據（第一輪檢索前）時，**不呼叫 LLM**，直接視為「明確不足」，缺口就是子問題本身——這是刻意設計，避免第一輪就浪費一次 LLM 呼叫問「有沒有證據」（答案顯然沒有）。
- JSON 解析失敗（parse 錯誤、非 dict、缺欄位）時，安全預設 `sufficient=True` 直接結束該子問題的檢索迴圈，並印警告到 stderr——避免反思本身壞掉時無限耗用 `retrieval_budget`。
- 新增7個單元測試（`tests/scripts/test_rq1_b2_reflect.py`），覆蓋正常解析、markdown fence 包裹、JSON array（非 object）、malformed JSON、缺欄位等情境。

### 1.3 `_run_single_query()`：新增 `elif raw_arm == "B2":` 分支

邏輯：`gather_evidence_agentic_async()` 用 B1 檢索前端（`hybrid=True`）當 `retrieve`、`_b2_reflect` 當 `reflect`，取得 `AgenticResult` 後，把 `context_lines` 餵進**跟 B0/B1 完全相同**的 `agent._generate_from_context_lines(...)` 呼叫（同樣的 `llm_provider=counting, judge_llm_provider=judge_counting or counting, kg_id=kg_id, use_svo=True`）——生成端逐位元相同，滿足報告36 §3.8 的單一變因控制，**不需要另外重構**（這點跟報告36當初預期「P0b 第2項重構尚未完成」不同——查證後發現 B0/B1 早就已經在用共用的 `_generate_from_context_lines()`，這個重構其實已經隱含存在，本次只是多接一個呼叫點）。

額外記錄 `agentic_trace`（`complexity`／`sub_question_count`／`retrieval_calls`／`reflect_calls`／`rounds_per_subquestion`）到每筆 record，供效率／穩定性分析使用。`llm_calls` 沿用既有的 `counting.calls` 計數（`_b2_reflect` 的呼叫自然被計入，不需要額外接線）。

其餘接線：`raw_arms.intersection({"B0", "B1", "B2"})` 補上 B2（否則載入 baseline index 的判斷會漏掉 B2）；`services/evaluation_preflight.py::SUPPORTED_ARMS` 補上 `"B2"`（否則 CLI `--arms B2` 會被 preflight 直接擋下，這是實際跑pilot時第一次踩到的問題，已修正並補一個正面測試）。

### 1.4 `services/cost_analyzer.py::get_baseline_profile()`：新增 B2 成本 profile

離線建構成本比照 B1（重用同一份 chunk 索引，增量≈0）；serving latency／avg_tokens 標高反映多輪呼叫，**docstring 明確標註這是工程估計、不是實測，正式數字要用本報告 §2 的真實 pilot 結果覆蓋**（沿用既有函式對 B0/B1/M4 estimate 的誠實聲明慣例）。

---

## 2. pytest 結果

新增 6（async gather）＋7（`_b2_reflect`）＋1（preflight B2 arm 正面測試）＝**14個新測試**。全套 `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py` **1170 passed**（實作前基準1156 passed）。

---

## 3. 真實 pilot 跑測

### 3.1 環境與範圍

- KG#4（`236903cf-055a-40a8-8923-b9d06601f3b7`），generator/judge 皆 `qwen2.5:7b`（`--allow-shared-judge`，明確標記為pilot非正式評測），embedding `bge-m3`。
- Baseline chunk 索引（`baseline_rag_index_236903cf-..._cs500.npy`）已涵蓋KG#4全部64份文件、1181個chunk，不需要重建。
- 題目範圍：沿用報告62/72既有凍結基準的23份`scope_doc_ids`（即報告72/S0-S3系列一路用的同一個scope），從65題題庫自動篩出42題eligible（`verification_status=VERIFIED`且有`atomic_gold_facts`）。
- 先跑2題smoke test（`17-Q4`簡單題＋`17-Q1`複雜題）確認B2臂能跑通，`17-Q1`真實跑出`complexity=complex`、2個子問題、6次檢索、7次LLM呼叫、88.2秒、正確答案（atomic_accuracy=1.0，逐字命中「勞工結婚者給予婚假八日，工資照給」並正確引用N0030006第2條）。
- smoke test通過後，啟動`--arms M1,M2,B2 --runs 1`的42題全量比較，背景執行。

### 3.2 ⚠️ 背景任務因系統記憶體壓力被中止

執行36分鐘、跑完9題（27次查詢：9×M1、9×M2、8×B2，其中第9題`18-Q6`的B2查詢尚未開始）後，**Claude Code背景shell保護機制偵測到系統記憶體嚴重不足，自動終止了這個背景任務**——系統通知明確指出「這不是指令本身的失敗，不代表指令或其記憶體使用有問題」，且明確指示不要自行重新啟動（「memory may still be short」），需等使用者要求才重跑。已完成的8題資料完整、有效（`records.json`為合法JSON，無截斷損毀，`error`欄位全部為`null`，無任何查詢失敗）。

**本報告不重新啟動這個背景跑測**，依指示把已完成的8題資料視為本輪pilot的最終成果並如實回報，較大規模的完整42題跑測留待使用者另外指示。

### 3.3 真實數字（n=8，B0/M1、B1/M2、B2三臂完整配對）

| 臂 | mean atomic_accuracy | mean atomic_recall | is_perfect（滿分題數） | mean latency_s | mean llm_calls | mean context tokens（估） |
|---|---:|---:|---:|---:|---:|---:|
| B0（M1，純dense chunk） | 0.938 | 0.938 | 7/8 | 77.4（32.7–254.4） | 1.12 | 660 |
| B1（M2，dense+BM25 RRF） | 0.812 | 0.812 | 6/8 | 76.0（34.7–273.9） | 1.12 | 655 |
| B2（Agentic，本報告新接） | 0.917 | 0.917 | 7/8 | 98.7（55.0–192.2） | 5.88 | 1304 |

逐題明細：

| 題號 | B0 acc | B1 acc | B2 acc | B2複雜度 | B2 rounds_per_subquestion | B2 llm_calls | B2延遲(s) |
|---|---:|---:|---:|---|---|---:|---:|
| 17-Q1 | 1.0 | 1.0 | 1.0 | complex | [1, 1] | 3 | 59.6 |
| 17-Q2 | 1.0 | 1.0 | 1.0 | complex | [5, 3] | 9 | 106.6 |
| 17-Q6 | 1.0 | 1.0 | 1.0 | simple | [1] | 1 | 64.0 |
| 18-Q1 | 1.0 | 1.0 | 1.0 | complex | [1, 5, 2] | 9 | 86.7 |
| 18-Q2 | 1.0 | 1.0 | 1.0 | complex | [1, 5] | 7 | 64.8 |
| 18-Q3 | 0.5 | 0.5 | **1.0** | complex | [1, 5] | 7 | 160.8 |
| 18-Q4 | 1.0 | 1.0 | 1.0 | simple | [1] | 1 | 55.0 |
| 18-Q5 | 1.0 | 0.0 | **0.33** | complex | [5, 3, 0] | 10 | 192.2 |

**18-Q3（B2救回B0/B1都只答對一半的案例）**：B0/B1單次檢索只抓到部分證據，B2多輪檢索+反思補齊了缺口，最終答對全部。這是B2設計初衷（Fan et al. 2026式「agentic多輪檢索誘導出隱式證據結構」）的一個正面實例。

**18-Q5（B2明顯退步、且是本輪唯一發現的新confounder）**：`rounds_per_subquestion=[5, 3, 0]`——第一個子問題用掉5輪、第二個用掉3輪，兩者合計已達`retrieval_budget=8`的上限，**第三個子問題完全沒有機會做任何檢索就被迫結束**（0輪）。這代表report 36原始設計的「總檢索次數上限」是**跨子問題共用同一個扁平predet算**，沒有規則保證每個子問題至少分到一定額度——複雜度越高（子問題越多）、越容易讓後面的子問題被前面的「餓死」。B0（純dense單次）反而因為不會被這個機制拖累而拿到滿分，B1（hybrid）則本身檢索品質較弱直接掛零。

**無任何查詢失敗或例外**（`error`欄位全部為`null`），確認P0d的程式碼路徑本身穩定，這次的退步是**演算法設計層面**的問題，不是實作bug。

### 3.4 未執行的部分（誠實記錄）

- 只跑了`--runs 1`，**沒有穩定性（×3 run variance）數據**——報告36 §5要求的「穩定性」評估欄本輪完全空白，不是被跳過而是連1輪都還沒跑完42題就被中止。
- 只跑完9/42題（8題B0/B1/B2三臂齊全），**遠低於正式RQ1對照需要的規模**，n=8的差異（尤其18-Q5的退步）有相當機率是題目本身的特性而非B2的普遍行為，不能外推。
- 離線建構成本、線上效率的「p50/p95延遲」等總體統計因樣本太小未計算（本報告只給mean，p50/p95在n=8下沒有統計意義）。
- 未執行B2 vs 既有K（Full System）/F/G臂的對照——本次pilot範圍限定B0/B1/B2三臂內部比較，沒有重跑K臂（沿用既有凍結基準數字沒有意義，因為那是不同批次/環境跑的，不可直接放在同一張表比較延遲/成本，只能引用其準確率數字當定性參考：報告62記錄凍結基準K臂42題12/42達標，是完全不同的評分口徑（達標題數而非atomic_accuracy平均），不可直接跟本表比較）。

---

## 4. 誠實評估：B2值不值得投入更大規模的正式RQ1對照？

**目前證據不足以下結論，維持report 36「B2為optional」的定位不變**：

1. **正面訊號**：P0d程式碼路徑完整可跑、生成端與B0/B1共用同一套堆疊確實成立（不需要額外重構），至少1個真實案例（18-Q3）展現出B2設計初衷預期的「多輪檢索救回」能力。
2. **新發現的設計缺陷（confounder）**：`retrieval_budget`在多子問題間的扁平共用會讓後面的子問題被前面「餓死」，這在report 36原始設計（§3/§6）沒有被考慮到。**在解決這個問題之前，任何B2 vs B0/B1/K的正式比較都可能被這個假影響（artifact）污染**，不是真正的「agentic檢索有沒有用」的訊號。建議修法方向（僅記錄、未實作）：改成每子問題有各自的最低保底輪數（例如`retrieval_budget // len(sub_questions)`打底、剩餘額度再依需要動態分配），或提高`retrieval_budget`預設值。
3. **成本代價確認存在**：B2的LLM呼叫數（5.88次/題）是B0/B1（1.12次/題）的**5倍以上**、延遲高28%、context長度高約2倍——這個成本代價是真實測到的，不是report 36 §5表格裡的估計值。
4. **樣本量**：n=8遠不足以支撐任何統計顯著的結論，8題的atomic_accuracy平均差異（0.938 vs 0.917）落在雜訊範圍內（比照報告62/79系列一貫的「±2題屬量測噪音」判斷原則）。

**建議下一步（供使用者參考，不是自動下一步）**：(a) 先修`retrieval_budget`分配規則再考慮擴大跑測規模；或(b) 若使用者認為現有8題證據已經足夠形成初步判斷（例如「B2值得記錄在論文限制/未來工作章節，但不值得投入正式RQ1對照組」），可以直接依本報告的誠實評估收斂，不必等budget修法。兩條路都需要使用者裁示，本報告不擅自選邊。

---

## 4.1 追加：`retrieval_budget`分配缺陷已修正並驗證（2026-09-27，使用者裁示「先修retrieval_budget分配規則」）

### 修正內容

`services/agentic_baseline_service.py`的`gather_evidence_agentic()`／`gather_evidence_agentic_async()`原本用單一遞減計數器`retrieval_calls < retrieval_budget`跨子問題共用，前面子問題可以把預算全部用完（§3.3的18-Q5案例）。改為「每子問題保底＋剩餘額度動態分配」：

- `floor_per_sq = max(1, retrieval_budget // 子問題數)`：每個子問題的保底輪數，即使`retrieval_budget`小於子問題數也至少保底1輪（此時總消耗可能超過`retrieval_budget`，這是刻意取捨——保底優先於嚴格封頂，已在docstring註明）。
- 除法無法整除的餘數、以及前面子問題沒用完的保底額度，累積成共用池`shared_pool`動態分給後面子問題；仍受`max_rounds`封頂。

同步／async兩版本同步修正。新增3個單元測試（含1個直接重現18-Q5的`[5,3,0]`退化形狀、驗證修正後沒有子問題是0輪），既有19個測試斷言**全數不變通過**（因為這些測試只斷言`retrieval_calls`總數或`max_rounds`封頂情境，不受內部分配方式改變影響）。全套`pytest`1170→**1173 passed**。Commit `cb3be26`。

### 真實重跑18-Q5驗證（非mock）

用同一題（`18-Q5`）、同一份KG、同樣的B2臂設定（`max_rounds=5, retrieval_budget=8`）重新跑一次：

| 指標 | 修正前（§3.3記錄） | 修正後 |
|---|---|---|
| `rounds_per_subquestion` | `[5, 3, 0]`（第三子問題完全沒檢索） | `[4, 2, 2]`（三個子問題都有檢索，與手算預期完全吻合） |
| `atomic_accuracy` | 0.33 | **1.0** |
| `is_perfect` | 否 | **是** |
| 答案內容 | 明顯退步 | 正確涵蓋三個級距（1-3日／2-5日／3-7日），與gold facts逐一對應 |
| latency_s | 192.2 | 171.9 |
| retrieval_calls | 8 | 8（總消耗相同，只是分配方式改變） |

**修正確認有效**：本次pilot發現的confounder已經解決，18-Q5從「B2明顯退步的唯一反例」變成「B2正確作答」。輸出：`data/eval/candidate_runs/b2_budget_fix_validation/`。

**仍待使用者決定**：是否要用修正後的程式碼重新擴大跑測規模（例如補完先前因記憶體壓力中止的42題全量比較），或現階段先以「budget分配缺陷已修正並經單題驗證」的狀態收斂，本報告不自動決定。

---

## 5. 版控狀態

- Commit `c791cbf`（P0d實作：async孿生函式、`_b2_reflect()`、harness B2臂接線、cost_analyzer profile，14個新測試，pytest 1170 passed）。
- Commit `eabcfc0`（preflight SUPPORTED_ARMS修正＋本報告8題pilot結果）。
- Commit `0981014`（HANDOVER記錄）。**以上3筆commit已於2026-09-27由使用者確認並push**（`origin/worktree-sdd-retrieval-comparison`）。
- Commit `cb3be26`（§4.1：`retrieval_budget`每子問題保底＋動態分配修正，3個新測試，pytest 1173 passed）——依使用者裁示「先修retrieval_budget分配規則」執行，**已commit，push待使用者確認**。
- pilot輸出：`data/eval/candidate_runs/b2_pilot_smoke/`（2題smoke test）、`data/eval/candidate_runs/b2_pilot_full/`（9題部分完成，被記憶體壓力中止前的真實records）、`data/eval/candidate_runs/b2_pilot_full_stdout.log`（背景執行log）、`data/eval/candidate_runs/b2_budget_fix_validation/`（§4.1修正後18-Q5單題重跑驗證）。
- **push留待使用者與主session確認**，本報告不自行push。
