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

### 2.3 報表層改動（✅ 2026-09-15 已實作）

`scripts/eval/run_rq1_comparison.py::_render_pareto_summary()`新增「## 2. Context Quality矩陣」區塊（Context Recall／SNR／Chain Completeness，僅對有跨文件`atomic_gold_facts`的題目計入Chain Completeness平均，並標示樣本數n），插在原本的Pareto矩陣之後、場景梯度細分之前，原有「場景梯度細分」「典型缺陷血統歸因」依序改編號為3/4——**兩組矩陣並列、不互相取代**，維度II（生成端指標）仍是判斷系統整體可用性的必要條件。新增1個單元測試（`tests/scripts/test_rq1_harness_failures.py`），涵蓋單文件題（chain_completeness=None，不計入平均）與跨文件題（0命中→0.0%，n=1）兩種情境，全套946 pytest綠燈。

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

| 標籤 | 定義 | 原現況（verified題數） | 目標新增 | **✅ 2026-09-15 實際完成** |
|---|---|---|---|---|
| `single_fact` | 單一事實直接命中 | 3 | 0（已足夠當基準線） | 未動 |
| `multi_fact_assembly` | 同文件內多事實組裝 | 4 | +2（從既有unverified挑題驗證） | **+3**（18-Q6／17-Q6回頭驗證＋57-COREF1/COREF3附掛此標籤） |
| `cross_doc_multihop` | 跨文件多跳 | 1（26-Q5，已知失敗案例） | +4 | 0（依規劃排除在本次範圍外，待任務C Stage 0） |
| `alias_mapping` | 民間用語↔法律用語 | 0 | +4 | **+3**（57-ALIAS1/2/3，逐字核對真實條文） |
| `coreference_resolution` | 代名詞/隱含主詞消解 | 0 | +3 | **+3**（57-COREF1/2/3） |
| `global_aggregation` | 全域聚合列舉 | 0 | +4 | 0（依規劃排除，見§4 Stage 0） |
| `interval_lookup` | 數值→區間→係數查表推理 | 1（unverified） | +2 | **0，明確放棄**——26-Q8（N0060004§3）原文變量係數表是ASCII box-drawing表格格式，無法產生乾淨prose式`exact_span`，維持`unverified`，未強行湊數 |
| `segmented_enumeration` | 分段列舉完整性 | 1（unverified） | +2 | **+1**（26-Q1回頭驗證，N0060029§4三段休息時間） |
| `distractor_adjacent` | 鄰近條文陷阱 | 0 | +3 | **+3**（57-DIST1/2/3，含D0080015直轄市vs全國性、N0030006配偶父母vs自己父母） |
| `canary_refusal` | 防偽拒答 | 2（皆「完全不存在」型） | +2 | **+2**（57-CANARY1/2，近似誤導型：法規確實存在但問題暗示的延展/金額不存在） |

**題庫從32題擴充到43題，verified從10題增加到24題**（`docs/附錄A題庫.json`＝`data/eval/test_cases.json`，兩檔已核對byte-identical）。全部14題異動的`atomic_gold_facts.exact_span`皆已由我直接查詢Neo4j（KG#4）原文逐字核對過，抽樣8題（含全部5個新維度各1題以上）100%通過，無虛構。`interval_lookup`的放棄理由也已獨立核實屬實（真的是ASCII表格，非偷懶）。

**✅ 18-Q7 side finding 已查明並修正（2026-09-15）**：查N0030018§2原文後確認**不是單純文件標籤錯誤，是題目設計本身混淆了兩種不同請假類型**——「事假得以小時為請假單位」確實出自N0030006§7（事假彈性）；但「因子女生病、停托、停課等原因得於一日前提出」實際出自N0030018§2（**育嬰留職停薪**申請提前日數的但書，跟事假無關），報告18原始整理把兩者誤併為一題。已更新`gold_answer`記錄此發現，`verification_status`改為`disputed`（沿用既有enum，不影響`evaluation_eligibility.py`既有排除邏輯——非verified本來就會被排除，只是狀態更精確）。若未來要用這題，應拆成兩題分別對應N0030006§7與N0030018§2。

**✅ mechanism_tags 已回填原始10題verified題目**（17-Q1/17-Q2=single_fact；18-Q1/18-Q2/18-Q3=multi_fact_assembly；18-Q4=single_fact；18-Q5=multi_fact_assembly+distractor_adjacent（D0080015§2/§3/§4三級距與57-DIST1/DIST2同一種鄰接陷阱結構）；26-Q5=cross_doc_multihop；canary-P1/canary-P4=canary_refusal）。現在全部24題verified題目皆有至少1個mechanism_tags，無遺漏。

### 3.3 不需要重抽的部分（✅ 已完成，見上表）

---

## 4. 任務C：`global_aggregation`專屬——分階段corpus擴充

### 4.1 Corpus查證結果

KG#4（`236903cf`）實際有**64份文件**（非僅目前harness用的6份），涵蓋勞基法/就業服務法/職安法/勞保條例等母法+大量施行細則，主題橫跨請假、職災保護、性別平等、中高齡就業、危險作業安全、健康檢查規範等子領域。已識別3組天然可聚合題材：

1. **健康檢查頻率**（`勞工健康保護規則`／`高溫作業勞工作息時間標準`／`精密作業勞工視機能保護設施標準`／`特定化學物質危害預防標準`）——可與26-Q7（高溫作業canary）連動，一題同時掛`global_aggregation`+`canary_refusal`。**優先選這組做Stage 0**。
2. 請假期間工資是否照給對照（`勞工請假規則`／`性別平等工作法`／`職業災害勞工保護法`）
3. 重大災害/職災勞工保護辦法（`災區受災勞工保險...辦法`／`職業災害勞工保護法`／`勞工職業災害保險及保護法`／`勞工職業災害保險職業傷病審查準則`）

**限制**：這3組用到的文件都在「另外58份未做`check_comparison_readiness.py`驗證」的範圍內——需要重抽（新鮮度/embedding/關係型別索引）才能正式進harness。

**✅ 2026-09-15 已對第1組（健康檢查頻率）4份文件實跑`check_comparison_readiness.py`（不重抽，純檢查）**：
```
NEO4J_URI=bolt://localhost:17990 NEO4J_PASSWORD=kg2_test_2026 WORKSPACE_DIR="D:/Users/666/Desktop/kg-runtime" \
python check_comparison_readiness.py --kg-id 236903cf-055a-40a8-8923-b9d06601f3b7 \
  --doc-ids "N0060022_勞工健康保護規則,N0060007_高溫作業勞工作息時間標準,N0060012_精密作業勞工視機能保護設施標準,N0060015_特定化學物質危害預防標準" --arms K
```
結果：**只有「抽取新鮮度」一項FAIL**（4份文件最舊chunk皆為2026-09-07，早於現行基準）；其餘全過——`fact_embedding`16736/16736=100%、`Entity.name_embedding`12096/12096=100%、4份文件皆有Fact節點、關係型別向量索引存在、KG與這4份文件皆pending=0。**這代表Stage 0的重抽範圍很窄，只需要針對這4份文件的新鮮度做`force_rebuild=True`重抽（帶embedding provider、`OLLAMA_EMBEDDING_NUM_GPU=0`，在`reextract-v2` HEAD執行），不需要重建embedding/索引基礎設施**——下次要動手時可以直接執行這個補救指令，不用重新盤點現況。

### 4.2 分階段執行（沿用報告30/37/38的 T0/T1/T2 模式）

**Stage 0（先導切片）：✅ 重抽動作已完成（2026-09-15），內容驗證發現原始假設需要修正**：

對4份候選文件中最小的2份（`N0060007_高溫作業勞工作息時間標準`11 chunk／`N0060012_精密作業勞工視機能保護設施標準`12 chunk，共23 chunk）在`reextract-v2` HEAD（`kg-reextract` worktree）跑安全模式重抽（`task_queue_service.enqueue()`終態→pending＋逐chunk `revoke_chunk_facts()`+`_process_one()`，`OLLAMA_EMBEDDING_NUM_GPU=0`）。**23/23成功，耗時59.6分**。重跑`check_comparison_readiness.py`全PASS（含新鮮度）。

**讀Neo4j核對條文內容（Go/No-Go判斷）——原始假設「4份文件都各自載明健康檢查頻率、可直接跨文件比較」不成立**：

- 逐條查看`N0060007`（47 facts）與`N0060012`（41 facts）的全部Fact，**兩者皆未包含任何健康檢查頻率數字**——內容分別是高溫作業的暴露時量/工時分配、精密作業的照明/工作姿態規範，是「作業類別定義」文件，不是「健檢頻率規定」文件。
- 查`N0060015_特定化學物質危害預防標準`（342 facts，沿用既有未重抽資料，僅供內容核對）與`N0060022_勞工健康保護規則`（169 facts，同）：**只有`N0060022`載明實際頻率數字**——一般健康檢查依年齡分級（60歲以上每年、40-59歲每二年、40歲以下每三年）＋特別危害健康作業每年或變更作業時實施特殊健康檢查（§19）。`N0060015`同樣沒有自己的頻率數字，只有「健康指導及管理」等定性描述。
- **但發現一個可能成立的跨文件推理鏈**：`N0060022`定義「特別危害健康作業＝符合附表一之物理性及化學性危害之作業」，且另有一則Fact明確提到「本法第十九條規定之高溫度、異常氣壓、高架、精密或重體力勞動作業」——而`N0060007`/`N0060012`正是依「職業安全衛生法第十九條」訂定的子法規。這暗示一個可能的跨文件聚合題：「高溫作業／精密作業的勞工依規定應多久實施特殊健康檢查？」，答案要靠`N0060022`§19（頻率規則）+`N0060007`/`N0060012`（確立其屬於第十九條高溫/精密類別）跨文件組裝。
- **關鍵未解驗證項**：直接查`N0060022`的`original.md`原文（非透過Fact抽取，避免表格抽取遺漏風險）——**附表一本身的實際條列內容沒有被收錄進本repo的`original.md`**（文件在第29條後即結束，只有「附表一」字樣的引用，沒有附表本身的表格內容）。無法在repo內直接證實附表一是否真的把`高溫作業勞工作息時間標準`/`精密作業勞工視機能保護設施標準`列為附表一項目——這是強烈的法律常識推論（職安法第19條類別與附表一設計上本應對應），但**不是本repo可查證的既有事實**，不能直接拿來當gold answer依據。

**Go/No-Go結論：有條件GO，卡在一個外部驗證缺口**——原本「4文件各自比較頻率」的題型不成立，但重新框架為「跨文件推理鏈」題型有機會成立，前提是先能證實附表一內容。尚未執行Stage 1（出題）。

**Stage 1（小樣本設計驗證）**：在這2-3份文件切片上，出1-2題`global_aggregation`題＋人工核實gold，用§2新指標小規模跑一次（1-2題×少數arm），確認Context Recall/SNR/Chain Completeness算得出合理數字——**新指標從未在真實資料上跑過，這步是要在小規模發現設計問題，而不是等26題全出完才發現**。

**Stage 2（正式擴大批次）**：Stage 0+1都過，才對其餘2組聚合題材做正式重抽，完成剩餘題目出題與驗證。

**Go/No-Go判準**：Stage 0若發現該組文件內容其實撐不起聚合題（例如各文件其實各管各的，沒有真正共通屬性），改選第2或第3組候選題材，不強行湊題。Stage 1若新指標算出來的數字明顯不合理（如Chain Completeness對單文件題也大量報告<100%），先修指標邏輯再繼續。

---

## 5. 執行順序建議與進度

1. ✅ **已完成**：任務B §3.3（5個維度、14題異動，逐字核對）、任務A §2.2（SNR/Chain Completeness指標）、任務A §2.3（報表層整合）、18-Q7題目設計混淆訂正、mechanism_tags回填24題verified題目、任務C Stage 0前置檢查（`check_comparison_readiness.py`唯讀確認，補救指令已備妥）。全套946 pytest綠燈，全部commit並push上`worktree-sdd-retrieval-comparison`分支。
2. ✅ **已完成（2026-09-15追加）**：§6-1「是否接上正式`chat()`路徑」裁示結果為「加檢索量體遙測」——`routers/agent.py::chat()`新增`_build_retrieval_telemetry()`，在`event: sources` SSE事件多帶`retrieval_telemetry`欄位（`retrieved_char_count`／`triple_count`／`fact_count`／`retrieval_latency_ms`），不需要gold answer即可算，對正式使用者問題也能即時輸出。**明確範圍限縮**：SNR／chain_completeness本身仍**不**在`chat()`即時算——這兩個指標依設計需要`atomic_gold_facts`（見`services/lineage_tracker.py::_compute_snr()`/`_compute_chain_completeness()`），真實使用者問題沒有正解可比對，維持只在離線harness（`scripts/eval/run_rq1_comparison.py`）算。新增3個單元測試，全套**949 pytest綠燈**。
3. ✅ **已完成（2026-09-15）**：任務C Stage 0實際重抽（2/4份文件，23 chunk，見§4.2詳述）＋內容驗證。**發現原始「4文件各自比較頻率」假設不成立，重新框架為跨文件推理鏈題型（N0060022§19頻率規則+N0060007/N0060012確立第十九條類別身分）有機會成立，但卡在附表一實際內容本repo未收錄，無法直接查證**——待使用者裁示如何處理這個外部驗證缺口，見§6。Stage 1（出題）尚未開始。

## 6. 使用者裁示結果（2026-09-15）

- **§2.4「是否接上正式`chat()`路徑」**：接上，但範圍限定於gold-independent的檢索量體遙測（見上方§5.2）；SNR/chain_completeness兩個真正的品質指標維持離線only。
- **任務B §3.2的場景維度與新增題數配額**：仍可再擴充，目前43題（verified 24）非終版。
- **任務C 3組候選聚合題材**：核准「健康檢查頻率」為Stage 0優先選項，但實際重抽動作使用者選擇稍後執行。
