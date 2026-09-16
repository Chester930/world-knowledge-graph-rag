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

### 4.3 ✅ 已修復：canary_refusal評分假陽性（2026-09-15發現，2026-09-16設計+落地）

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

**✅ 已落地（2026-09-16）**：

**文獻查證發現這個問題本專案已經打過一輪**——`docs/參考文獻/22_生成端過度保守與選擇性拒答/README.md`已精讀過RefusalBench（Muhamed et al. 2025）、RAGAS Faithfulness（Es et al. 2023）、Context-faithful Prompting（Zhou et al. 2023），且已因同一個「Qwen家族選擇性拒答判斷準確率全尺寸<17%」發現，把`services/interval_lookup_service.py`的區間查表判斷刻意改成確定性Python邏輯（G2方案E），**不交給LLM judge**。這推翻了上面寫的「較有希望的方向是重用ClaimGrounding語意判斷」——正確方向反而是**維持確定性判斷，但把判斷範圍縮小到題目核心主張**，不是換成語意fallback。

**設計＝新增`trap_claim_spans`欄位**（`models/eval_schema.py::TestCase`）：Type-E題目可選填一組「陷阱結論」固定字串，答案裡出現任一則即強制判定拒答失敗，即使拒答關鍵字也同時出現在文字別處。純字串比對，不新增LLM呼叫。

**5題既有canary題目回填結果**：
- `57-CANARY3`：填入實際觀察到的陷阱句「精密作業的勞工需要做特殊健康檢查」——**唯一有固定可檢查陷阱結論的題目**（類別混淆型陷阱）。
- `canary-P1`／`canary-P4`／`57-CANARY1`／`57-CANARY2`：刻意留空——這4題是「開放式捏造具體數字」型陷阱（罰鍰金額、火星旅遊次數、留停延長期限、獎金金額），陷阱關鍵詞（如「億元」）在正確拒答時也會自然出現（用來否定它），加字串比對反而會製造假陰性，不強行湊數。

**驗證結果（真實資料，非模擬）**：
- `services/atomic_scorer.py::evaluate()`／`evaluate_async()`加`trap_claim_spans`參數；新增3個單元測試（`tests/services/test_evaluation_metrics.py`），全套**952 pytest綠燈**。
- 對`57-CANARY3`重跑真實harness：模型答案不變（仍確信斷言「精密作業的勞工需要做特殊健康檢查」），但這次正確判定`is_perfect=False`，`details`顯示`"Failed to Refuse on Type-E Canary (Trap Claim Asserted)"`——漏洞已堵住。
- 對全部5題canary做回歸測試：`canary-P4`／`57-CANARY2`維持100%通過（`trap_claim_spans=[]`，數學上零影響，已確認）；`canary-P1`／`57-CANARY1`維持0%——讀答案內容確認這兩題模型直接編造具體數字（「一百五十萬元」「不少於六個月」），答案裡完全沒出現任何拒答關鍵字，走的是修復前後完全相同的判定路徑（`details`為舊版文字，未觸發trap分支），證實無回歸、這兩題的失敗跟本次修復無關（是模型本身選擇性拒答能力不足，呼應RefusalBench的實證發現）。

**尚未處理**：`services/interval_lookup_service.py::is_refusal_text()`（正式`chat()`生產路徑）維持不動——這是數值區間查表這個更窄、已經走過A/B/A′/C/E正式驗證流程（`run_refusal_canary.py`的FRR/MRR門檻）的獨立子系統，若要修，應另外排程、走同一套探針驗證流程，不跟這次的eval評分修復混在一起。

**Stage 1（小樣本設計驗證）**：在這2-3份文件切片上，出1-2題`global_aggregation`題＋人工核實gold，用§2新指標小規模跑一次（1-2題×少數arm），確認Context Recall/SNR/Chain Completeness算得出合理數字——**新指標從未在真實資料上跑過，這步是要在小規模發現設計問題，而不是等26題全出完才發現**。

**Stage 2（正式擴大批次）**：Stage 0+1都過，才對其餘2組聚合題材做正式重抽，完成剩餘題目出題與驗證。

**Go/No-Go判準**：Stage 0若發現該組文件內容其實撐不起聚合題（例如各文件其實各管各的，沒有真正共通屬性），改選第2或第3組候選題材，不強行湊題。Stage 1若新指標算出來的數字明顯不合理（如Chain Completeness對單文件題也大量報告<100%），先修指標邏輯再繼續。

### 4.4 第2組候選：請假期間工資對照 Stage 0（2026-09-16）

**框架修正**：原始假設N0030006勞工請假規則／N0030014性別平等工作法／N0060041職業災害勞工保護法三方對照。讀三份文件`original.md`全文查證後**部分不成立**：

| 文件 | 內容 |
|---|---|
| N0030006 勞工請假規則 | 婚假8日/喪假8·6·3日/公假：工資照給；普通傷病假：30日內折半；事假：不給工資。工資數字最豐富 |
| N0030014 性別平等工作法 | 生理假：薪資減半；產檢假·陪產假：工資照給；家庭照顧假：比照事假；產假/安胎休養：「依相關法令之規定」——未寫死數字 |
| N0060041 職業災害勞工保護法 | ❌ 本文完全沒有請假工資數字規定，第29條只是程序橋樑：「職災未認定前先請普通傷病假（引N0030006§4），認定後轉公傷病假」 |

追查N0030014§15「相關法令」與N0060041§29的轉銜實際指向**N0030001 勞動基準法**（原不在候選名單）：§50產假工資（滿6個月照給/未滿6個月減半）、§59②職災醫療期間原領工資全額補償。**修正後框架**：核心工資對照＝N0030006+N0030014+N0030001；N0060041§29作跨文件橋接/`canary_refusal`候選（可測系統是否誤把普通傷病假半薪規則套用到轉銜後的公傷病假全薪）。

**Readiness check（唯讀）**：4份文件（含新增N0030001）fact_embedding/entity_embedding/關係型別索引皆100%就緒，只有新鮮度FAIL（皆2026-09-07舊管線抽取）。

**⚠️ 抽取單位算錯兩次**：`_record.json`的`svo_total_chunks`（SVO實際抽取chunk數）跟資料夾`chunk-XXX-of-NNN.md`檔名數（3.1.1 RAG chunk數）是兩組不同數字。一開始把N0030006/N0030014的RAG chunk數(3/21)當SVO chunk數報給使用者（「24 chunk pilot」），實際是62（13+49）；N0060041/N0030001同樣誤植(11/35)，實際是41/98。已修正估算方法，一律讀`svo_total_chunks`欄位。

**✅ Stage 0 pilot（N0030006單一文件13 SVO chunk）已完成，發現新的抽取品質bug類別**：`reextract_leave_wage_pilot.py`（`kg-reextract`worktree，安全模式——`task_queue_service.enqueue()`終態重置為pending＋逐chunk`revoke_chunk_facts()`+`_process_one()`，不重跑CHUNKREADY）13/13成功，`check_comparison_readiness.py`轉PASS。**內容核對發現兩個真實缺陷**：

1. **決定性幻覺**：§7事假「事假期間不給工資」被抽成「**產假**期間不給工資」；§8公假「工資照給」被抽成「**產假**期間照給工資」——N0030006全文根本沒有「產假」一詞。重跑c3/c7/c8這3個chunk驗證是否為隨機雜訊，**結果完全零改變**——temperature=0+固定seed下可重現/決定性，非雜訊，單純重試無法修正。懷疑是qwen2.5:7b對「XX假期間{不給/照給}工資」句型的訓練偏見（產假是最常見範例）蓋掉了原文實際假別名詞。
2. **列舉漏抽**：§3喪假三個等級（八/六/三日）原文都各自寫「工資照給」，但44筆Fact裡完全沒有對應「工資」的邊，只抽到天數——婚假(§2)的「工資照給」正確抽到，喪假卻被漏掉，可能是既有列舉守衛把重複子句誤判成冗餘濾掉。

**使用者裁示（2026-09-16）**：先記錄為已知限制，任務C繼續往下走，不深入修根因——這是全新的「假別entity-level幻覺」類別，現有抽取guard都只針對數量/quantity grounding，沒有覆蓋entity替換這類錯誤。若要修需設計「請假類型entity grounding guard」（比照數量guard核對抽出的假別名詞是否逐字出現在原文），非本次任務C範圍，獨立排程。**出`57-AGGR`類題目時，N0030006的§3喪假、§7事假、§8公假這3個chunk的工資Fact不可信，若要用這些條文出題必須直接讀`original.md`核實，不能信任KG裡的Fact**；婚假(§2)、普通傷病假(§4)工資規則可信。

**下一步（已規劃，見§5）**：N0030014（49 SVO chunk全文重抽，核心比較文件）+ 2個targeted chunk（N0030001 chunk 57=§50產假工資、chunk 66=§59職災工資補償）+ 1個targeted chunk（N0060041 chunk 29=§29橋接）——不需要重抽N0030001全部98 chunk或N0060041全部41 chunk，用`grep -l "第 50 條"` svo-chunk檔案的`article_no` frontmatter找出對應chunk編號即可精準定位。

**✅ 第二批重抽已全部完成（2026-09-16）**：

- **N0030014全文49 chunk**：49/49成功、0失敗，耗時240.5分。用兩個平行worker執行——worker1循序跑N0030014，worker2同時跑N0030001（chunk 57/66）+N0060041（chunk 29）這3個獨立chunk（3/3成功，23.2分），兩者互不重疊、零碰撞風險。
- **內容核對（worker2的3個chunk）**：全部正確無誤，沒有重演N0030006的「產假幻覺」——N0030001 chunk 57（§50產假工資：滿6個月照給/未滿6個月減半）、chunk 66（§59職災工資補償：原領工資全額）、N0060041 chunk 29（§29轉銜：普通傷病假→留職停薪→認定職災後轉公傷病假）皆逐字對應原文。可推測該幻覺bug是特定句型觸發（「XX假期間{不給/照給}工資」＋短促主詞），不是普遍性問題。
- **⚠️ 中途事故並已修復**：worker1完成N0030014後開始要重做N0030001（worker2已完成的部分，因worker1腳本的`TARGETS`清單裡本來就包含這2份文件，且沒有atomic claim保護，重複執行是已知會發生但預期無害的行為）。介入`Stop-Process`的時機比預期晚了一步——worker1已對chunk 57跑完`revoke_chunk_facts()`但還沒來得及`_process_one()`重新寫入就被強制終止，短暫清空了chunk 57的4筆Fact。已立即發現（核對Neo4j時筆數從19變15）並用獨立腳本`fix_c57.py`重新處理，核對後4筆Fact正確恢復。**教訓**：多worker平行重抽若其中一個worker的清單有意圖之外的重疊範圍，「等它自然重複執行完」比「掐時間點介入」更安全——介入本身才是這次唯一造成短暫資料遺失的動作。
- **Readiness check發現一個工具設計限制（非內容問題）**：`check_comparison_readiness.py`的新鮮度基準預設抓`services/svo_service.py`等抽取端檔案的**最新git commit時間**，但該檔案同時也放了查詢端函式（`vector_search_facts`）——peer session提交的`source_doc_cap`prototype（查詢端功能，非抽取邏輯）commit把基準時間推到`2026-09-16T15:27:42`，讓明明用同一套抽取管線做的N0030006/N0030014兩份文件顯示假性FAIL。用`--baseline-time`明確指定抽取端實際最後一次相關commit（`f1bda80`，`2026-09-15T14:47:19+08:00`）重跑後，N0030006／N0030014兩份PASS。N0030001／N0060041因為是只做局部targeted重抽的大型母法（分別98／41個SVO chunk，只碰了2／1個），該檢查是抓「整份文件最舊chunk」的粗粒度判斷，其餘未觸碰的chunk仍是舊時間戳，會**恆常顯示FAIL**——這不代表內容有問題（§50/§59/§29這3個目標chunk已手動核對逐字正確），只是這個檢查工具沒有「只驗證特定chunk子集新鮮度」的粒度，屬於已知限制、非本次任務C範圍去修。

**✅ Go/No-Go結論（2026-09-16）**：**Go**。核心工資對照框架（N0030006+N0030014為主體，N0030001§50/§59+N0060041§29作橋接）內容驗證通過，可進Stage 1出題。已知限制：N0030006的§3喪假/§7事假/§8公假這3個chunk有前述決定性幻覺/漏抽bug，出題時必須直接讀`original.md`核實、不能信任KG裡的Fact；其餘章節（§2婚假、§4普通傷病假、N0030014全部、N0030001§50/§59、N0060041§29）皆可信任KG內容。

**✅ Stage 1出題已完成（2026-09-16，commit `771312b`）**：題庫從46題擴充到**49題**。新增3題，6個`exact_span`皆已直接grep `original.md`逐字核對通過，958 pytest綠燈，`docs/附錄A題庫.json`同步保持byte-identical：

| 題號 | mechanism_tags | 內容 |
|---|---|---|
| `57-AGGR3` | `global_aggregation`+`multi_fact_assembly` | 婚假(§2工資照給)/普通傷病假(§4折半)/產假(N0030001§50依年資)三類工資規則對照，刻意選規則互不相同的假別測混淆 |
| `57-AGGR4` | `cross_doc_multihop` | 職災認定前後工資轉銜，N0060041§29橋接N0030006§4(認定前折半)+N0030001§59第2款(認定後全額)，真正的3文件推理鏈 |
| `57-CANARY4` | `distractor_adjacent` | 故意選N0030006§7（已知KG幻覺chunk，Fact被抽成「產假期間不給工資」而非「事假期間不給工資」）出題，測系統實際檢索到的是原始chunk文字還是被污染的衍生Fact——正是本任務整個評測解耦關切的核心 |

**✅ Stage 1 harness實跑驗證已完成（2026-09-16）**：

過程中Ollama基礎設施出了兩個獨立問題並修復——① 殘留的`netsh interface portproxy`規則把`0.0.0.0:11434`轉發到失效的WSL2內部IP，導致連線被重置，使用者以系統管理員權限刪除規則後解決；② 修好連線後發現`qwen2.5:7b`/`bge-m3`兩個模型完全消失（版本從0.11.4自動升級到0.34.1過程中清掉），使用者同意後重新`ollama pull`兩個模型補齊。

**真實跑出的結果（`rq1_stage1_leave_wage_pilot_v3`，K arm，pilot用`--allow-shared-judge`）**：

| 題號 | atomic_accuracy | 診斷 |
|---|---|---|
| `57-AGGR3` | 67%（2/3命中） | 漏N0030001§50產假規則；答案裡的「產假期間照給工資」很可能就是N0030006§8已知幻覺Fact被檢索命中（該bug在另一題裡被真實觸發，證實§4.4記錄的警告確有其事） |
| `57-AGGR4` | 33%（1/3命中） | 只抓到N0030001§59，橋接條文N0060041§29與N0030006§4皆未檢索到，典型跨文件多跳檢索缺口 |
| `57-CANARY4` | 0%（1/1命中失敗） | 檢索完全沒抓到「事假不給工資」正解，模型誤用一條語意模糊的「工資照給」Fact答反結論——跟原本設計假設的機制略有不同（不是命中被污染的Fact本身，是retrieval完全沒找到相關Fact），但同樣印證了report57「檢索品質vs生成品質」解耦框架的核心價值：錯誤可精確歸因到Stage 1檢索失敗（recall_rate=0%） |

這是SNR/Chain Completeness/Context Recall三個新指標第二次在真實資料上跑出可信數字（第一次是健康檢查頻率組），累積驗證指標設計合理。

### 4.5 第3組候選：職災新舊法交替陷阱 Stage 0+1（2026-09-16）

**框架查證**：N0050031（勞工職業災害保險及保護法，2022年新法）§106/§107明文「自本法施行之日起，職業災害勞工保護法不再適用」，§101/§104/§105/§106另列了「本法施行前」的過渡期grandfather clause（舊案件仍依舊法辦理）。框架查證成立。

**Targeted重抽（6 chunk，26.3分，6/6成功）**：N0060041 chunk 8（§8生活津貼）+ N0050031 chunk 101/104/105/106/107。**逐chunk內容核對發現比前兩組更嚴峻的抽取品質問題**，6個chunk命中3種不同類型的錯誤：

1. **chunk 8**：數字幻覺（原文「第一等級至**七**等級」被抽成「至**十**等級」）+ 跨條文片語嫁接（object文字疑似逐字取自完全不同的第34條）
2. **§104**：多子句混淆嫁接——原文兩段意思相反的子句被錯配在一起
3. **§105**：漏抽關鍵結論——只抽到「遭遇職業傷害」，法律效果「應依本法施行前職業災害勞工保護法規定申請補助」完全沒被抽出
4. **§107**：主客體顛倒，容易讀反

只有**§101**與**§106核心廢止句**逐字核對完全正確。累計本session已發現4種不同類型的抽取缺陷（實體幻覺/數字幻覺+跨條文嫁接/多子句混淆/漏抽關鍵結論），且第3組6個chunk命中3種問題的密度高於第1、2組——**值得未來獨立排查的抽取端系統性風險信號，目前仍完全依賴人工逐字核對原文抓出，無自動化偵測機制**。

**使用者裁示**：縮小範圍只用§101+§106出題。

**Stage 1出題（`57-CANARY5`，cross_doc_multihop+distractor_adjacent）**：「《職業災害勞工保護法》現在還適用嗎？」，2個exact_span逐字核對通過。題庫從49題擴充到**50題**，958 pytest綠燈。

**Harness驗證結果**：atomic_accuracy 50%（1/2命中）——核心廢止句正確答對，過渡期例外（§101）完全沒被檢索到。**額外發現一個生成端新錯誤類型**：模型把答案裡的「本法」自我指涉用語誤解讀成指《勞動基準法》，實際上原文的「本法」指N0050031自己——跟先前發現的檢索缺口、抽取幻覺都不同，屬於生成端對法律文件自我指涉代稱的理解問題。

---

## 5. 執行順序建議與進度

1. ✅ **已完成**：任務B §3.3（5個維度、14題異動，逐字核對）、任務A §2.2（SNR/Chain Completeness指標）、任務A §2.3（報表層整合）、18-Q7題目設計混淆訂正、mechanism_tags回填24題verified題目、任務C Stage 0前置檢查（`check_comparison_readiness.py`唯讀確認，補救指令已備妥）。全套946 pytest綠燈，全部commit並push上`worktree-sdd-retrieval-comparison`分支。
2. ✅ **已完成（2026-09-15追加）**：§6-1「是否接上正式`chat()`路徑」裁示結果為「加檢索量體遙測」——`routers/agent.py::chat()`新增`_build_retrieval_telemetry()`，在`event: sources` SSE事件多帶`retrieval_telemetry`欄位（`retrieved_char_count`／`triple_count`／`fact_count`／`retrieval_latency_ms`），不需要gold answer即可算，對正式使用者問題也能即時輸出。**明確範圍限縮**：SNR／chain_completeness本身仍**不**在`chat()`即時算——這兩個指標依設計需要`atomic_gold_facts`（見`services/lineage_tracker.py::_compute_snr()`/`_compute_chain_completeness()`），真實使用者問題沒有正解可比對，維持只在離線harness（`scripts/eval/run_rq1_comparison.py`）算。新增3個單元測試，全套**949 pytest綠燈**。
3. ✅ **已完成（2026-09-15）**：任務C Stage 0實際重抽（2/4份文件，23 chunk，見§4.2詳述）＋內容驗證＋外部查證（`law.moj.gov.tw`官方附表一PDF）。**結論**：`N0060007`高溫作業＋`N0060015`特定化學物質＋`N0060022`頻率規則三份文件的跨文件推理鏈題型確認成立；`N0060012`精密作業確認**不**適用特殊健康檢查頻率（附表一12項查無精密作業），但這個「查無」結果本身適合另設計一題`canary_refusal`測試系統是否誤套職安法第十九條的廣泛分類。詳見§4.2。Stage 1（實際出題）尚未開始，待使用者確認範圍後執行。

## 6. 使用者裁示結果（2026-09-15）

- **§2.4「是否接上正式`chat()`路徑」**：接上，但範圍限定於gold-independent的檢索量體遙測（見上方§5.2）；SNR/chain_completeness兩個真正的品質指標維持離線only。
- **任務B §3.2的場景維度與新增題數配額**：仍可再擴充，目前43題（verified 24）非終版。
- **任務C 3組候選聚合題材**：核准「健康檢查頻率」為Stage 0優先選項，但實際重抽動作使用者選擇稍後執行。

## 7. KG角色再收斂：從「推理鏈建構者」變成「上下文精煉與路由者」（2026-09-16）

**使用者定調**：下一輪方法測試與分析的重點不再局限於「最終答案是否正確」，而是「回答前到底引用了哪些參考資料、這個上下文本身夠不夠精準且完整」。背景判斷：現代LLM在小範圍文字內的邏輯推理能力已經足夠，不一定需要KG建立推理鏈；KG真正的價值在於把「足夠精準且完整」的材料送到LLM面前，推理交給LLM自己做。這個定調正是§2的Context Quality矩陣（Context Recall／SNR／Chain Completeness）本來就在量測的東西，只是先前是「診斷用」，現在要把它變成「可介入的優化目標」——在檢索組裝完成、送進LLM之前，主動精煉／篩噪，而不只是事後觀察。

### 7.1 診斷：BFS側精煉已存在，Fact側完全沒有

查證`routers/agent.py::_arrange_fact_lines()`（report25 §4發現6，2026-09-02落地）確認：BFS三元組確實已有問題相關性embedding排序＋截斷（`_score_lines_by_embedding()`＋`_BFS_KEEP_MAX`）、RRF融合（Cormack et al. 2009）、zigzag重排（Jin et al. 2025／Liu et al. 2023 Lost-in-the-Middle）；文獻依據見`docs/參考文獻/21_圖遍歷與向量檢索結果融合/README.md`（SAGE、Han et al. GraphRAG綜述）。但**語意Fact側（`vector_search_facts()`回傳的20筆）完全信任原始dense cosine KNN排序，沒有對應的精煉機制**——`_arrange_fact_lines()`裡`sem_ranked = list(fact_lines)`這行直接照單全收。

### 7.2 根因追蹤：57-AGGR2的低SNR不是BFS造成的

追蹤harness程式碼確認`57-AGGR2`（K arm）是透過`_drain_chat()`直接打生產環境`agent.chat()`，`_arrange_fact_lines()`的BFS精煉機制**確實有執行、不是被繞過**。真正的噪聲來源是`routers/agent.py:1505`的`vector_search_facts(driver, payload.kg_id, question_vector, top_k=payload.top_k)`——`ChatRequest.top_k`預設20，一旦N0060015（342個Fact，內容涵蓋大量同主題但不相關的防護具/監測細項）被判定在文件範圍內，其中主題相近但答非所問的Fact會在dense cosine上跟真正需要的2-3筆事實差不多高，一起擠進20個名額，稀釋掉正解。這是「同一份文件內部主題鄰近噪聲」，跟BFS鄰居爆炸是不同機制，現有精煉對它沒有防禦。

### 7.3 初步實驗：`vector_search_facts(hybrid=True)` 的檢索端驗證（2026-09-16）

`services/svo_service.py::vector_search_facts()`已有一個**現成但預設關閉的prototype**（報告43選項A，2026-08）：`hybrid=True`時額外對`Fact.fact_text`跑一趟BM25式fulltext查詢（CJK analyzer），與dense cosine候選池以RRF融合，動機正是打「dense cosine對高頻樣板虛詞造成的語意過度聚類」（原本為26-Q5案例設計，`docs/論文/02_文獻探討.md`§2.6.2有文獻脈絡）。`routers/agent.py:1505`呼叫時從未傳入`hybrid=True`，此機制此前從未在真實chat()路徑跑過。

**直接單元測試（繞過LLM生成，只測檢索）**：對57-AGGR2的問題直接呼叫`vector_search_facts(..., hybrid=True)`，0.09秒回傳，**top-20命中3個gold fact中的2個**（「雇主使勞工從事特別危害健康作業...實施特殊健康檢查」＋附表一橋接事實），對照純dense基準版本（同一天重跑）**0/3命中**——證實hybrid確實能把被同主題Fact稀釋掉的關鍵句子撈回來，檢索端改善是真實的，不是猜測。

**端到端驗證受阻**：把`hybrid=True`暫時接進`routers/agent.py::chat()`跑完整RQ1 harness（K arm，57-AGGR2），在300秒逾時——檢索本身只花0.09秒，瓶頸在後續LLM生成階段，高度懷疑是跟同時段另一終端機執行的N0030014重抽任務搶Ollama資源（該任務當時已連續執行超過4小時的LLM抽取呼叫），非hybrid機制本身的問題。

**處置**：`routers/agent.py`的實驗性改動已還原（`git checkout`），**未commit**——檢索端改善已用獨立測試證實，但完整端到端SNR/答案品質數字尚未拿到，不宜在部分驗證的狀態下改動生產路徑。待Ollama資源空出後（其他終端機重抽跑完），重跑完整RQ1 harness（K arm，`hybrid=True` vs baseline，涵蓋`57-AGGR1`/`57-AGGR2`/`57-CANARY3`三題）取得端到端數字後再決定是否正式接線＋commit。

### 7.4b `source_doc_cap`：規則式同源多樣性上限——已實作＋檢索端驗證有效（2026-09-16）

依§7.4文獻查證（`docs/參考文獻/35_同來源Fact冗餘去噪與多樣性檢索/`）的建議路線，實作MMR/DF-RAG baseline精神的規則式簡化版：`services/svo_service.py::vector_search_facts()`新增`source_doc_cap: int | None = None`參數（prototype，預設關，行為零變化），新增`_apply_source_doc_cap()`——依既有分數排序貪婪走訪，同一`source_doc_id`累計達上限即跳過、留名額給其他來源，若因多樣性不足湊不滿`top_k`則第二輪依原順序補滿（不因追求多樣性而讓清單比`top_k`短）。純計數邏輯，**零額外embedding／LLM呼叫**，比`hybrid=True`更輕量（不需要fulltext索引）。新增6個單元測試，全套**958 pytest綠燈**。

**直接檢索端驗證（繞過LLM生成、不搶Ollama資源）**：對57-AGGR2重跑`vector_search_facts(top_k=20, source_doc_cap=5)`對照無上限版本——

| 版本 | 命中文件數 | 最大單一文件佔比 | 含關鍵詞橋接事實命中 |
|---|---|---|---|
| 無上限（baseline） | 5份 | 8筆 | 0 |
| `source_doc_cap=5` | 8份 | 5筆 | 1（「符合本附表所列作業之勞工...每年或於變更其作業時...實施特殊健康檢查」） |

跟§7.3的`hybrid=True`實驗撈到同一筆關鍵橋接事實，但**這個機制連fulltext索引都不需要，純規則式計數更輕量**——證實「檢索到的來源分散、鑑別力不足」是兩個獨立但互補的噪聲成因，兩個機制原理不同（`hybrid`解決鑑別力、`source_doc_cap`解決來源集中），理論上疊加使用應該互補。

**尚未接線進`chat()`**——`routers/agent.py:1505`目前仍未傳入`source_doc_cap`，本次只驗證檢索端函式本身，跟§7.3的`hybrid=True`一樣需要等Ollama資源空出後，才能跑完整端到端K arm harness（含`hybrid=True`+`source_doc_cap`疊加版）取得SNR/atomic_score數字，再決定正式接線。

### 7.4 待辦（下一輪接續）

- [ ] Ollama資源空出後，重跑§7.3的完整端到端K vs K+hybrid消融（至少涵蓋57-AGGR1/AGGR2/CANARY3），取得SNR/Context Recall/atomic_score的完整對照數字。
- [ ] 若證實有效，正式接線`hybrid=True`進`routers/agent.py:1505`（需要同時傳入`question=payload.question`），補單元測試，並評估是否要做成`KGConfig`可調參數而非寫死True。
- [x] **文獻查證＋實作＋檢索端驗證已完成（2026-09-16）**——見§7.4b：`vector_search_facts(source_doc_cap=...)`已實作、958 pytest綠燈、直接測試證實對57-AGGR2有效（命中文件數5→8份、撈回1筆關鍵橋接事實）。**尚未接線進`chat()`**，待Ollama資源空出後跑完整端到端harness（`hybrid=True`+`source_doc_cap`疊加版）取得SNR/atomic_score數字再決定正式接線＋校準`source_doc_cap`實際數值（目前5是未校準的示範值）。
- [ ] 待Ollama資源允許時，把本節定調（KG角色＝上下文精煉與路由，非推理鏈建構）明確反映進報告58/59的設計原則——報告58的雙軌組裝若真的排入實作，補回原始Chunk的同時必須先做精煉，否則會重蹈57-AGGR2的覆轍（把更多噪聲一起塞進prompt）。
