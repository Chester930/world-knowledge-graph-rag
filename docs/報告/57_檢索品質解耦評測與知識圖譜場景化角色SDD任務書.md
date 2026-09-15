# 57 檢索品質解耦評測與知識圖譜場景化角色 SDD 任務書

**建立日期**：2026-09-15
**文件性質**：架構級 SDD 任務書（使用者主導的重新設計，非延續報告51敘事）
**前置討論**：本任務書由使用者在 `sdd-retrieval-comparison` worktree 一次對話中逐步定案，過程中已核實報告48/49/51的可信部分與已過時部分，並實測查證題庫標註現況、corpus規模、程式碼現況，非直接照搬先前任一份報告的結論。

---

## 0. 問題定義（不是「KG贏不贏」，是「評測系統誠不誠實」）

這次架構調整的起點不是「知識圖譜的答案有沒有贏過 chunk-RAG」，而是：**目前的評測系統沒有能力誠實回答「知識圖譜在哪裡有不可取代的價值」**。證據鏈：

- 報告42（B0/B1贏KG）→ 報告49/51（懷疑7B小模型消化不良拖累KG，提出評測解耦假說）→ 報告52（發現真正元兇之一是**字面比對評分工具本身對KG系統性不利**）→ 報告55（修字面比對後差距收斂但方向未反轉，KG仍落後）。
- 報告51本身雖然提出了正確的方向（評測解耦、KG角色收斂到特定場景），但其核心論據（26-Q5生成端診斷、18-Q4案例）已被本worktree的報告41§9/報告50查證推翻或張冠李戴，數字/雷達圖多為未經量測的示意主張（見報告51開頭的核實記錄）。

**本SDD的任務**：設計並落地一套不受生成端雜訊、不受字面比對偏誤污染、能按場景分層的評測架構，用它誠實測出「知識圖譜相對於一個做得夠好的chunk-RAG，在哪些具體場景下有可驗證的增益」——測出來的結果會反過來決定KG在系統裡該扮演什麼角色，不是先射箭再畫靶。

---

## 1. 現況盤點（避免重做已完成的工作）

這次 merge（`0fa5f36` → `5a37fac`，含SDD-48評測管線硬化）已經落地以下基礎設施，比報告51 §6清單描述的現況新很多：

| 項目 | 狀態 | 位置 |
|---|---|---|
| `ScenarioType` Type-A~E 正式 enum | ✅ 已存在（含 Type-D 定義，但**0題實際使用**） | `models/eval_schema.py:15-21` |
| `TestCase`/`AtomicGoldFact` Pydantic schema | ✅ 已存在 | `models/eval_schema.py:31-55` |
| 三階段血統追蹤（Retrieval/ContextAssembly/Generation） | ✅ 已存在 | `models/eval_schema.py:66-107` |
| **Context Recall**（`recall_rate`，語意NLI fallback版） | ✅ 已計算，報告55已修字面比對偏誤 | `services/lineage_tracker.py:35-96` |
| Context組裝存活率（retained/dropped exact_spans） | ✅ 已計算 | `services/lineage_tracker.py:98-138` |
| 正式評測資格檢查（verified/no-pending/atomic_gold_facts齊全） | ✅ 已實作 | `services/evaluation_eligibility.py` |
| 啟動前靜態 preflight（重複ID、文件範圍、獨立judge、dataset hash） | ✅ 已實作 | `services/evaluation_preflight.py` |
| 確定性守衛接線（`deterministic_guard_service`） | ✅ 已接線（報告51 §6項目4已完成） | `scripts/eval/run_rq1_comparison.py:57,295` |
| 獨立judge強制要求 | ✅ 已接線（報告51 §6項目3已完成） | `scripts/eval/run_rq1_comparison.py:560-563` |
| BGE-M3 1024維embedding升級 | ✅ 已完成（報告54目標已達成） | `.env`/`main.py` 動態傳入 |
| **Noise Rate / SNR 指標** | ✅ 已實作（2026-09-15） | `services/lineage_tracker.py::_compute_snr()` |
| **Chain Completeness 指標** | ✅ 已實作（2026-09-15，`source_law`分組，Type-E synthetic排除，單文件題回傳None不算0分） | `services/lineage_tracker.py::_compute_chain_completeness()` |
| **Context Quality 是否為主要回報指標** | ❌ 否——`recall_rate`已算出但`_render_pareto_summary()`只彙總`atomic_score`，Context Recall從未進入summary.md | `scripts/eval/run_rq1_comparison.py:348-420` |
| 題庫場景標籤（複選） | ❌ 目前`scenario_type`是單值欄位，無法一題掛多場景 | `models/eval_schema.py:47` |
| Type-D（全域聚合）題目 | ❌ 32題中0題 | `docs/附錄A題庫.json` |
| 別名映射/代名詞消解/鄰接陷阱 獨立場景標籤 | ❌ 不存在 | — |

**結論**：這次SDD不需要從零開始，「評測解耦」的資料層基礎（血統追蹤、Context Recall）已經有人做了大半，真正缺的是（a）補上SNR/Chain Completeness兩個指標、（b）把Context Quality拉成主要回報指標而非埋在原始JSON裡的副產品、（c）題庫場景標籤改複選＋擴充新場景題目。

---

## 2. 任務A：評測解耦——Context Quality 升格為主要指標

### 2.1 維度切分（延續報告51 §2的框架，重新核實過依據）

```
【維度 I：純檢索 Context 品質】──不受生成端干擾，本SDD的新增重點
  • Context Recall  = 已實作（record_retrieval_async 的 recall_rate）
  • Noise Rate/SNR  = 待實作
  • Chain Completeness = 待實作

【維度 II：受控端到端生成指標】──已有基礎設施，本SDD只需要接上報表
  • Atomic Fact Accuracy = 已實作（atomic_scorer.py）
  • Deterministic Guard Pass Rate = 已實作（deterministic_guard_service）
  • Canary Refusal Accuracy = 已有Type-E題目可測
```

### 2.2 指標設計（✅ 2026-09-15 已實作）

**Noise Rate / SNR**：
```
SNR = Σ(len(hit_exact_span)) / len(combined_retrieved_text)
```
`RetrievalStageLineage`新增`retrieved_char_count: int`／`snr: float`兩欄位（`models/eval_schema.py`），`record_retrieval()`/`record_retrieval_async()`計算`combined_text`時順手記錄長度並算SNR，夾在[0,1]內。非破壞性schema新增，預設0不影響既有記錄反序列化。

**Chain Completeness**（僅對`atomic_gold_facts`橫跨 ≥2 個`source_law`的題目有意義，即Type-C/D）：
```
Chain Completeness = 命中至少一個essential fact的 distinct source_law 數 / 該題所需的 distinct source_law 總數
```
不需要schema改動——`AtomicGoldFact.source_law`已存在，`_compute_chain_completeness()`依`source_law`分組再算覆蓋率，用既有的`hit_spans`聚合。單文件題目（僅1個distinct source_law）或未傳入`atomic_gold_facts`回傳`None`（不適用，非0分，避免懲罰單文件題）；Type-E拒答題的synthetic `source_law="None"`比照`evaluation_eligibility.py`慣例排除在分組外。

兩者皆已接線進`scripts/eval/run_rq1_comparison.py`的兩處`record_retrieval()`呼叫點（正常路徑與例外failure record路徑），新增8個單元測試（`tests/services/test_lineage_tracker.py`），全套945 pytest綠燈。

### 2.3 報表層改動

`scripts/eval/run_rq1_comparison.py::_render_pareto_summary()`（348-420行）目前只彙總`atomic_score`。改動：新增一組「Context Quality矩陣」與現有「Atomic Accuracy矩陣」並列輸出，**兩組都保留、不互相取代**——因為使用者確認的立場是「用檢索資料評價取代答案評分」，但維度II（生成端指標）本身仍是判斷KG系統整體是否可用的必要條件，不能只看檢索端就下產品結論。兩組矩陣分開看，才能回答「檢索是否夠好」跟「整條pipeline是否夠好」這兩個不同但都重要的問題。

### 2.4 明確排除範圍（避免SDD膨脹）

- ❌ **不決定是否接上正式`chat()`路徑**——這是上一輪對話（清空前）留下、使用者尚未答覆的分歧點，本SDD**維持只做離線harness**，正式上線留給未來有實測數據支撐後再開新SDD決定。
- ❌ **不重新調查26-Q5根因**——已有報告41§9/報告50的結論，本SDD不重複驗證，26-Q5會自然被新指標覆蓋到（它就是一個Chain Completeness/Context Recall雙低的活案例）。
- ❌ **不動`atomic_scorer.py`既有邏輯**——報告55的語意NLI fallback修正已經是穩定狀態，本SDD只加新指標，不碰現有的。

---

## 3. 任務B：題庫schema擴充——場景標籤改複選

### 3.1 Schema改動

`models/eval_schema.py::TestCase`新增欄位：
```python
mechanism_tags: List[str] = Field(default_factory=list, description="檢索機制挑戰標籤（複選），見§3.2清單")
```
**保留**既有`scenario_type`單值欄位不變（向下相容，`evaluation_eligibility.py`/`evaluation_preflight.py`既有邏輯都靠它，不能動）。`mechanism_tags`是新增的正交維度，舊32題可以先都留空陣列（不強制回填，回填是加分項不是必要項）。

### 3.2 十大場景維度（`mechanism_tags`可用值）

| 標籤 | 定義 | 現況（verified題數） | 本SDD目標新增 |
|---|---|---|---|
| `single_fact` | 單一事實直接命中 | 3 | 0（已足夠當基準線） |
| `multi_fact_assembly` | 同文件內多事實組裝 | 4 | +2（從既有22題unverified裡挑題驗證，不必新出題） |
| `cross_doc_multihop` | 跨文件多跳（母法+子法+施行細則） | **1**（26-Q5，且是已知失敗案例） | **+4**（新出題，至少1題須是KG目前答得對的，避免樣本全是已知缺陷） |
| `alias_mapping` | 民間用語↔法律用語，題幹刻意不用法條原文詞彙 | **0** | **+4** |
| `coreference_resolution` | 代名詞/隱含主詞消解，答案所需事實主詞在另一句/另一條 | **0** | **+3** |
| `global_aggregation` | 全域聚合列舉，答案需跨多份文件蒐集 | **0** | **+4**（見§4，需搭配Stage 0重抽） |
| `interval_lookup` | 數值→區間→係數查表推理 | 1（unverified） | +2 |
| `segmented_enumeration` | 分段列舉完整性，需完整抓齊所有分段 | 1（unverified） | +2 |
| `distractor_adjacent` | 鄰近條文陷阱，測噪聲抗性 | 0（明確以此機制設計的題目） | +3 |
| `canary_refusal` | 防偽拒答 | 2（皆「完全不存在」型） | +2（新增「近似誤導型」canary） |

合計規劃新增約26題（多題可能同時掛2個標籤，實際出題數會少於26）。

### 3.3 不需要重抽的部分（可立即開始，不受Stage 0進度阻塞）

`alias_mapping`／`coreference_resolution`／`distractor_adjacent`／`multi_fact_assembly`補題／`interval_lookup`補題／`segmented_enumeration`補題／`canary_refusal`近似誤導型——**都能在現有64份已抽取文件（含已就緒的6份）裡找天然案例出題，不需要動KG#4資料**。這部分應該最先啟動。

---

## 4. 任務C：`global_aggregation`專屬——分階段corpus擴充

### 4.1 Corpus查證結果

KG#4（`236903cf`）實際有**64份文件**（非僅目前harness用的6份），涵蓋勞基法/就業服務法/職安法/勞保條例等母法+大量施行細則，主題橫跨請假、職災保護、性別平等、中高齡就業、危險作業安全、健康檢查規範等子領域。已識別3組天然可聚合題材：

1. **健康檢查頻率**（`勞工健康保護規則`／`高溫作業勞工作息時間標準`／`精密作業勞工視機能保護設施標準`／`特定化學物質危害預防標準`）——可與26-Q7（高溫作業canary）連動，一題同時掛`global_aggregation`+`canary_refusal`。**優先選這組做Stage 0**。
2. 請假期間工資是否照給對照（`勞工請假規則`／`性別平等工作法`／`職業災害勞工保護法`）
3. 重大災害/職災勞工保護辦法（`災區受災勞工保險...辦法`／`職業災害勞工保護法`／`勞工職業災害保險及保護法`／`勞工職業災害保險職業傷病審查準則`）

**限制**：這3組用到的文件都在「另外58份未做`check_comparison_readiness.py`驗證」的範圍內——需要重抽（新鮮度/embedding/關係型別索引）才能正式進harness。

### 4.2 分階段執行（沿用報告30/37/38的 T0/T1/T2 模式）

**Stage 0（先導切片）**：只選第1組（健康檢查頻率），重抽其中2-3份文件，跑`check_comparison_readiness.py`確認過關，直接讀Neo4j核對條文內容是否真的支撐假設的聚合題。**不寫任何評測程式碼，純驗證corpus假設**。

**Stage 1（小樣本設計驗證）**：在這2-3份文件切片上，出1-2題`global_aggregation`題＋人工核實gold，用§2新指標小規模跑一次（1-2題×少數arm），確認Context Recall/SNR/Chain Completeness算得出合理數字——**新指標從未在真實資料上跑過，這步是要在小規模發現設計問題，而不是等26題全出完才發現**。

**Stage 2（正式擴大批次）**：Stage 0+1都過，才對其餘2組聚合題材做正式重抽，完成剩餘題目出題與驗證。

**Go/No-Go判準**：Stage 0若發現該組文件內容其實撐不起聚合題（例如各文件其實各管各的，沒有真正共通屬性），改選第2或第3組候選題材，不強行湊題。Stage 1若新指標算出來的數字明顯不合理（如Chain Completeness對單文件題也大量報告<100%），先修指標邏輯再繼續。

---

## 5. 執行順序建議

1. **立即可做、互不相依**：任務B §3.3（別名/代名詞/鄰接陷阱/既有維度補題出題）＋ 任務A §2.2（SNR/Chain Completeness指標實作，可用既有verified題目的資料測試，不必等新題）。
2. **平行**：任務C Stage 0（健康檢查頻率組先導重抽，2-3份文件）。
3. **視1、2結果決定**：任務A §2.3報表整合（等指標穩定再接報表，避免報表格式跟著指標調整反覆改）；任務C Stage 1/2（視Stage 0是否驗證通過）。

## 6. 待使用者裁示事項

- §2.4提到的「是否接上正式`chat()`路徑」——上一輪對話遺留的分歧點，本SDD明確不處理，但需要使用者知道這個問題還在，之後某個時間點要回頭決定。
- 任務B §3.2的10個場景維度與新增題數配額，是否要調整（本任務書的數字是討論過程中的建議值，非鐵板一塊）。
- 任務C 3組候選聚合題材，是否認可「健康檢查頻率」為Stage 0優先選項，或想先看過3組的實際條文內容再決定。
