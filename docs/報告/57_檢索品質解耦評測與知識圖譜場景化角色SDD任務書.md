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

**✅ 附表一外部查證已完成（2026-09-15，`law.moj.gov.tw` PCode=N0060022 官方PDF《第二條附表一修正規定》，`FileId=0000420146`）**——附表一共12項特別危害健康作業，逐項核對結果：

| 候選文件 | 附表一結果 | 判定 |
|---|---|---|
| `N0060007`高溫作業 | **第一項明文列出**：「高溫作業勞工作息時間標準所稱之高溫作業」——直接點名本標準 | ✅ 確認屬特別危害健康作業，跨文件推理鏈成立 |
| `N0060015`特定化學物質 | 第九項「特定化學物質作業」對應本標準規範範圍（23種物質，重量比>1%） | ✅ 確認屬特別危害健康作業，跨文件推理鏈成立（細項物質清單是否逐一對應本標準內容，Stage 1出題時需再核對） |
| `N0060012`精密作業 | **附表一12項全查無精密作業或視機能保護相關項目** | ❌ **不成立**——精密作業不在附表一內，不適用特殊健康檢查頻率規定 |

**修正後的結論**：`N0060022`提到「本法第十九條規定之高溫度、異常氣壓、高架、精密或重體力勞動作業」是**母法（職安法）第十九條的廣泛保護措施分類**（一般性安全衛生措施），但「附表一」（決定誰要做特殊健康檢查）是**窄化後的獨立清單**——精密作業屬於前者但不屬於後者，兩層分類不能混為一談。原先「精密作業→附表一→特殊健康檢查」的推論是**誤判**，已被官方原文推翻。

**Go/No-Go最終結論：有條件GO，範圍修正**——
1. `N0060007`（高溫）+ `N0060015`（特定化學物質）+ `N0060022`（頻率規則）三份文件的跨文件推理鏈題型**成立**，可進Stage 1。
2. `N0060012`（精密作業）**不適合**用在「特殊健康檢查頻率」這個聚合題——但這個「查無」結果本身很適合另外設計一題`canary_refusal`／`distractor_adjacent`題：「精密作業的勞工多久要做一次特殊健康檢查？」正解應是「不適用特殊健康檢查頻率規定，精密作業未列入附表一，仍依一般年齡分級規則辦理一般健康檢查」——測試系統是否會被職安法第十九條的廣泛分類誤導、錯誤套用特殊健檢頻率。
3. `N0060015`的23項物質清單是否與該標準規範的化學物質逐一對應，Stage 1出題時需再花時間核對（本次只確認品項9與其規範範圍**性質**相符，非逐字比對）。

**✅ 附表一內容已匯入KG補足語料庫缺口（2026-09-15）**：把附表一12項＋銜接第十九條頻率規則的一句話改寫成prose句子（文字全部逐字/緊密改寫自官方PDF與N0060022已核實條文，未新增法律實質內容），當成新文件`N0060022_附表一_特別危害健康作業`（獨立document_uuid，不改動既有N0060022本體，`articles=None`預設句子切塊）匯入KG#4，4個chunk全數抽取成功、產生53個Fact，含關鍵橋接事實「符合本附表所列作業之勞工依勞工健康保護規則第十九條規定...每年或於變更其作業時...實施特殊健康檢查」。

**✅ Stage 1出題完成（2026-09-15）**：新增3題寫入`data/eval/test_cases.json`＋`docs/附錄A題庫.json`（46題，verified 27題）：

- `57-AGGR1`（`cross_doc_multihop`，Type-C）：「高溫作業的勞工多久要做一次特殊健康檢查？」——跨N0060022_附表一（項次一）+N0060022正文（第19條）2份文件。
- `57-AGGR2`（`global_aggregation`+`multi_fact_assembly`，Type-D）：「高溫作業和特定化學物質作業的勞工，做特殊健康檢查的頻率一樣嗎？」——跨3個atomic_gold_facts，答案是「一樣」（統一頻率規則不分項次）。
- `57-CANARY3`（`canary_refusal`+`distractor_adjacent`，Type-E）：「精密作業的勞工需要做特殊健康檢查嗎？」——正解「不適用」，測試系統是否誤把職安法第十九條的廣泛分類當成附表一的窄化特殊健檢清單。

全部7個`atomic_gold_facts`的`exact_span`已用獨立腳本逐字核對三份文件的`original.md`原文（非憑空核對，非透過Fact抽取），全數通過；`models.eval_schema.EvaluationDataset` schema驗證通過；全套**949 pytest維持綠燈**（資料檔異動不影響既有測試）。

**✅ Stage 0剩餘82 chunk重抽已完成（2026-09-15，346.9分）**：82/82成功，`check_comparison_readiness.py`對全部4份文件（`N0060007`/`N0060012`/`N0060015`/`N0060022`）+附表一新文件PASS。

**✅ Stage 1 small-scale驗證已跑通（2026-09-15）**：對`57-AGGR1`/`57-AGGR2`/`57-CANARY3`三題跑`K` arm ×1 run。

**過程中發現並修復一個harness既有bug（非本次新增內容造成，先前批次剛好沒觸發）**：`scripts/eval/run_rq1_comparison.py`第262-264行用`dict.get(key, default)`從JSON往返解碼出的dict取`natural_text`/`source_doc_id`/`fact_text`/`fact_id`，但這些鍵在JSON裡永遠存在（`_serialize_sources()`的`fact_id`欄位依`services/svo_service.py::vector_search_facts()`的既有設計本來就恆為null，不外洩內部`elementId`——見該函式測試`test_rrf_fuse_fact_ids...`的「內部欄位不外洩」契約），值為`None`時`dict.get(key, default)`不會套用default——導致`"".join(retrieved_texts)`炸`TypeError`、`RetrievalStageLineage`因`List[str]`欄位收到`None`炸pydantic `ValidationError`。改用`x.get(key) or default`修復，949 pytest維持綠燈，已commit。

**修復後跑出的真實結果（有意義，非崩潰）**：

| 題號 | 檢索recall_rate | 最終答案atomic_recall | 診斷 |
|---|---|---|---|
| `57-AGGR1` | 0.0%（literal exact_span無命中） | 50%（語意fallback判定1/2命中） | 答案本身語意正確（「高溫作業每年做一次特殊健康檢查」），但檢索到的Fact文字（SVO自然化後）跟`exact_span`（原始法規逐字文字）不是逐字相同——例如Fact是「雇主使勞工從事特別危害健康作業 每年或於變更其作業時...」（無「，應」、無句號），原文exact_span是「雇主使勞工從事特別危害健康作業，應每年或於變更其作業時...」——語意層fallback判定命中，但lineage_tracker的Stage 1檢索追蹤用的是嚴格逐字比對（`record_retrieval()`同步版，非`record_retrieval_async()`語意fallback版），兩層量測基準不一致 |
| `57-AGGR2` | 0.0% | 答案內容混亂（「特定化學物質本標準不適用」等不連貫敘述），非retrieval記錄問題，是真實生成品質問題 | 可能是top_k帶進太多N0060015無關的化學物質細項Fact稀釋掉了真正需要的3個關鍵事實（SNR/雜訊問題，正是報告57整個任務A要測的東西） |
| `57-CANARY3` | 0.0% | 逾時180秒 | 未查明是單純生成較慢還是卡住，需要更長timeout或加log重跑診斷 |

**✅ 使用者裁示「統一用語意fallback」已完成（2026-09-15）**：`scripts/eval/run_rq1_comparison.py`的`tracker.record_retrieval()`/`record_context_assembly()`/`build_full_lineage()`（同步、嚴格逐字）改為對應的`_async()`版本（語意fallback，同`AtomicScorer.evaluate_async()`同一套判準，帶`judge_llm_provider=judge_counting or counting`／`question=tc.question`）；`_build_failure_record()`（harness例外時的空白failure record，`retrieved_texts=[]`本來就沒東西可語意比對）維持同步版不動。949 pytest維持綠燈，commit `?`（待補）。

同時把`--query-timeout-s`從預設180拉長到300秒重跑，`57-CANARY3`不再逾時。

**修復後v3跑出的真實結果（已是可信數字）**：

| 方法代號 | Context Recall | SNR | Chain Completeness |
|---|---|---|---|
| K | 27.8% | 7.7% | 33.3% (n=3) |

- `57-AGGR1`：recall 0.5（2個gold fact命中1個，附表一項次一「高溫作業」連結事實仍未被檢索到，即使語意fallback也判定沒命中——這是真實的檢索缺口，不是量測方法問題）。
- `57-AGGR2`：recall 0.33、**SNR僅8.5%**——最終答案內容混亂矛盾（先說「特定化學物質本標準不適用」，後又說「雇主使勞工從事特定化學物質作業者...應實施勞工特殊健康檢查」），跟低SNR高度吻合：`top_k`檢索帶進大量`N0060015`裡無關的化學物質細節（防護具、設備監測等），把真正需要的3個關鍵事實稀釋掉，佐證報告57整個SNR指標設計要抓的正是這種「檢索到很多東西但訊號被雜訊淹沒」現象。

### 4.3 🚨 已記錄未修復：canary_refusal評分假陽性（2026-09-15發現，使用者裁示先記錄+收集資料，暫不修復）

**觸發案例**：`57-CANARY3`摘要表顯示100%通過，但讀完整答案發現**模型實際上答錯了**——明確說「精密作業的勞工需要做特殊健康檢查」且編造頻率「每年或於變更其作業時」（正是這題設計要測的陷阱：誤把職安法第十九條的廣泛分類當成附表一窄化清單，模型真的掉進去了），但答案結尾附帶一句跟核心問題無關的「其他部分資料未明確記載，無法確認」。

**根因（兩個獨立call site，同一套naive邏輯）**：

1. `services/atomic_scorer.py::evaluate()`第59-76行——Type-E拒答檢核：
   ```python
   refusal_patterns = ["未記載", "無法確認", "無相關規定", "資料未提及", "查無相關",
                        "未能提供", "並未記載", "沒有提到", "無法提供確定答覆"]
   refused = any(p in clean_ans for p in refusal_patterns)
   ```
   只要答案全文**任何位置**出現這些字樣就判定整題拒答成功，不要求拒答內容對應到題目實際問的核心主張。`57-CANARY3`的答案結尾「無法確認」是針對一個跟題目無關的枝節點，觸發假陽性。

2. `services/interval_lookup_service.py::is_refusal_text()`第57-64行——**同一組標記**（docstring明講「與`run_refusal_canary.py`／報告32 §9 C用的同一組標記一致」），但這個是**正式生產路徑**、非僅評測用：`routers/agent.py:1272`的`evaluate_lookup_override()`在`chat()`的grounding覆核階段呼叫`is_refusal_text(draft_answer)`（僅在題目能解析出「數值區間→對應值」查表結構時介入，`57-CANARY3`這類非數值查表題不會觸發這條路徑，但其他區間查表型canary題可能會）。同樣的假陽性風險若在生產路徑觸發，可能導致`force_supported`覆核誤判，跳過本該觸發的重生成修正。

**範圍**：目前題庫（`data/eval/test_cases.json`）共5題`scenario_type=Type-E`（等同`canary_refusal`）：`canary-P1`、`canary-P4`、`57-CANARY1`、`57-CANARY2`、`57-CANARY3`，全部`verification_status=verified`，但historical/未來評分都可能受這個假陽性影響。

**為什麼不是簡單換成LLM judge就好**：`services/interval_lookup_service.py`開頭docstring明講這個領域已有前例——`run_refusal_canary.py`（報告32 §9 C，2026-09-13）端到端驗證過「純judge判斷是否拒答」，準確率**RefusalBench顯示Qwen家族全尺寸<17%**，才改用現在這套確定性關鍵字比對當退而求其次的方案。單純把判斷換成「問judge這是不是真拒答」不保證更好，且會重蹈已驗證過效果不佳的舊路。

**較有希望的修復方向（未實作，供之後評估）**：`services/verification_service.py::ClaimGrounding`已有逐句/逐主張細粒度分析（`verify_fact_grounding()`回傳每個claim的`statement`/`supported`/`is_claim`），`chat()`正式生成路徑已經在算這份資料。若Type-E拒答檢核改成「檢查題目核心主張對應的那個claim是否被正確判定為不支持/拒答」而非對整段答案文字做關鍵字掃描，理論上能避開「答案其他枝節夾帶拒答用語」的假陽性——但需要先解決「怎麼知道哪個claim對應題目的核心主張」這個新的子問題（目前`AtomicGoldFact`／`TestCase`schema沒有結構化欄位標記這件事），非一行修補。

**估計工時**：**半天到一天（約4-8小時）的專注開發**——涵蓋（1）設計「核心主張claim辨識」機制、（2）改寫`atomic_scorer.py`與`interval_lookup_service.py`兩處call site、（3）新增單元測試、（4）重跑既有5題canary驗證是否有歷史假陽性被抓出來（可能發現更多既有「verified通過」的題目其實沒真的測到）。不是單一函式的小修補，牽動題庫既有canary題的歷史可信度重新核實，故估時偏保守。

**Stage 1（小樣本設計驗證）**：在這2-3份文件切片上，出1-2題`global_aggregation`題＋人工核實gold，用§2新指標小規模跑一次（1-2題×少數arm），確認Context Recall/SNR/Chain Completeness算得出合理數字——**新指標從未在真實資料上跑過，這步是要在小規模發現設計問題，而不是等26題全出完才發現**。

**Stage 2（正式擴大批次）**：Stage 0+1都過，才對其餘2組聚合題材做正式重抽，完成剩餘題目出題與驗證。

**Go/No-Go判準**：Stage 0若發現該組文件內容其實撐不起聚合題（例如各文件其實各管各的，沒有真正共通屬性），改選第2或第3組候選題材，不強行湊題。Stage 1若新指標算出來的數字明顯不合理（如Chain Completeness對單文件題也大量報告<100%），先修指標邏輯再繼續。

---

## 5. 執行順序建議與進度

1. ✅ **已完成**：任務B §3.3（5個維度、14題異動，逐字核對）、任務A §2.2（SNR/Chain Completeness指標）、任務A §2.3（報表層整合）、18-Q7題目設計混淆訂正、mechanism_tags回填24題verified題目、任務C Stage 0前置檢查（`check_comparison_readiness.py`唯讀確認，補救指令已備妥）。全套946 pytest綠燈，全部commit並push上`worktree-sdd-retrieval-comparison`分支。
2. ✅ **已完成（2026-09-15追加）**：§6-1「是否接上正式`chat()`路徑」裁示結果為「加檢索量體遙測」——`routers/agent.py::chat()`新增`_build_retrieval_telemetry()`，在`event: sources` SSE事件多帶`retrieval_telemetry`欄位（`retrieved_char_count`／`triple_count`／`fact_count`／`retrieval_latency_ms`），不需要gold answer即可算，對正式使用者問題也能即時輸出。**明確範圍限縮**：SNR／chain_completeness本身仍**不**在`chat()`即時算——這兩個指標依設計需要`atomic_gold_facts`（見`services/lineage_tracker.py::_compute_snr()`/`_compute_chain_completeness()`），真實使用者問題沒有正解可比對，維持只在離線harness（`scripts/eval/run_rq1_comparison.py`）算。新增3個單元測試，全套**949 pytest綠燈**。
3. ✅ **已完成（2026-09-15）**：任務C Stage 0實際重抽（2/4份文件，23 chunk，見§4.2詳述）＋內容驗證＋外部查證（`law.moj.gov.tw`官方附表一PDF）。**結論**：`N0060007`高溫作業＋`N0060015`特定化學物質＋`N0060022`頻率規則三份文件的跨文件推理鏈題型確認成立；`N0060012`精密作業確認**不**適用特殊健康檢查頻率（附表一12項查無精密作業），但這個「查無」結果本身適合另設計一題`canary_refusal`測試系統是否誤套職安法第十九條的廣泛分類。詳見§4.2。Stage 1（實際出題）尚未開始，待使用者確認範圍後執行。

## 6. 使用者裁示結果（2026-09-15）

- **§2.4「是否接上正式`chat()`路徑」**：接上，但範圍限定於gold-independent的檢索量體遙測（見上方§5.2）；SNR/chain_completeness兩個真正的品質指標維持離線only。
- **任務B §3.2的場景維度與新增題數配額**：仍可再擴充，目前43題（verified 24）非終版。
- **任務C 3組候選聚合題材**：核准「健康檢查頻率」為Stage 0優先選項，但實際重抽動作使用者選擇稍後執行。
