# 63 Gemini 評測報告查證與改進項評估

**日期**：2026-09-21
**文件性質**：調查報告（非設計提案、不含任何程式碼變更）。回答使用者的問題：「Gemini 對本專案的評測報告，指出的欠缺是否真的存在？」
**方法**：把 Gemini 報告拆成四項可檢驗的主張，逐項對照（1）當前 `master`（`b1c620e`）的程式碼、（2）論文與報告已有的設計記錄、（3）凍結基準評測（`data/eval/baseline_runs/20260920_frozen/`）的實際存檔。不憑 Gemini 的敘述、也不憑記憶引用。
**來源**：Gemini 報告為使用者貼入對話的文字，**未存檔於 repo**；本報告 §1 的主張摘要即為本報告所依據的版本。
**決策權**：本報告只提供查證結果與評估，**是否採用任何改進項由使用者決定**（見 §6）。

## 0. 結論（先講重點）

1. Gemini 的四項主張中，**只有「缺 Fact 層級時態欄位」大致成立**，而且那本來就是論文 §3.5 的 RQ5 設計提案（自稱「設計中、非現行行為」），不是新發現。
2. **「實體型別貧血」——本報告初版判為「不成立」，§9.4 實測後更正為「部分屬實」**：Gemini 讀錯了模組（暫存區 `entity_registry_service.py`），且主管線確實有 Schema.org 型別機制（52 類核心庫＋939 類擴充庫）；**但 KG#4 實測 12,290 個實體中 65.3% 的型別是預設的「概念」、6.5% 為空**，機制存在不等於覆蓋率足夠。初版只核對程式碼路徑、未連資料庫，結論下得太快。
3. **「缺 Relator 導致 AGGR18 新舊法寫反」的診斷與證據不符**。檢索是滿分，問題出在生成端；而且存檔顯示，留存的 gold span（事實句）**不帶法規名**，因此更可能的真因是「prompt 缺來源標籤」（推論，尚待用 T0 trace 直接驗證），這比新增 Relator 節點便宜得多（§3）。
4. **Gemini 建議的 `governing_status='active'` 硬過濾會破壞現有題目**：AGGR18、AGGR19 就是要同時比較新舊法。
5. 查證過程附帶發現一個**部分過時的註解**（`entity_extraction_service.py:43-48` 括號內「未定義任何實體類型常數」與現況矛盾；已於 §8 修正）。
6. **第二份 Gemini 報告（《本體抽取與系統落地工程缺口紀錄表 v1.0》，9 個 GAP）已於 §9 查證**：✅ 3／⚠️ 3／❌ 3。最重要的兩點：（a）**GAP-06 的診斷與 KG 實查相反**——AGGR18 的 4 筆 Fact 都能經 `SUPPORTED_BY→LawArticle→Document` 回溯到正確法規名與條號，歸屬資訊在圖中完整，只是沒進 prompt（強化 A 案）；（b）**本報告初版對「型別貧血」的判斷需更正**——實測 65.3% 實體型別為預設「概念」（§9.4）。

## 1. 被查證的四項主張

| # | Gemini 主張 | 它建議的解法 |
|---|---|---|
| ① | 實體型別「貧血」：所有實體型別預設「概念」，無語意範疇 | 聚類提升時掛 Schema.org Canonical Type，加 `ontoclean_category` |
| ② | 關係型別被 ConceptNet 35 類綁住，缺義務／權利／條件 | （未給具體改法，暗示需 Relator／Obligation 語意） |
| ③ | 57-AGGR18「原子評分不檢查歸屬」是因為圖譜沒有 Relator（關係載體）節點 | 引入 Relator |
| ④ | 缺雙時態，新舊法 Fact 共存、檢索時混在一起 | `SVOTriple` 加 `valid_from`／`valid_to`／`governing_status`，BFS 加 `WHERE governing_status='active'` |

## 2. 逐項查證

### 2.1 主張①：實體型別貧血 —— ⚠️ 部分屬實（初版判「不成立」，已於 §9.4 更正）

> **更正（2026-09-21，§9.4）**：以下「不成立」的推論只依據程式碼路徑。實測 KG#4（`236903cf`）後發現 12,290 個實體中 8,021 個（65.3%）型別為預設值「概念」、804 個（6.5%）為空，「雇主」本身即為「概念」。機制存在，但**覆蓋率與品質不足**，Gemini 的「貧血」描述對**實際資料**有相當程度的道理。以下保留原文以維持追溯，結論以 §9.4 為準。

**Gemini 看對的部分**：`services/entity_registry_service.py:48,138` 的 `entity_type` 預設確實是 `"概念"`，`services/entity_extraction_service.py:49-55` 的 spaCy 標籤對應也只涵蓋 人物／組織／地點，其餘一律歸「概念」。

**Gemini 沒看到的部分**：那條路徑只是**暫存區（別名登記）**。主管線的型別標註是另一套：

- `core/constants.py:247` `ENTITY_TYPES`：52 類核心庫（依 Brinkmann et al. 2023 WDC 統計實測排序，註解有文獻依據）。
- `data/schema_org_entity_types.json`：939 類 schema.org 官方完整清單（擴充庫）。
- `services/svo_service.py:153-208`：`_ENTITY_TYPE_GUIDE` 把型別清單放進 SVO 抽取 prompt，`resolve_entity_type()` 對 LLM 輸出的 `subject_type`／`object_type` 先比核心庫、再比擴充庫，查不到就保留原字串（不強制驗證，對應論文 3.1.4「實體型別選填」定案）。
- `services/svo_service.py:488-492`：抽取結果逐筆呼叫 `resolve_entity_type()`；`:1348-1376` 寫入 Neo4j 的 `e.type`；`:1176` 實體去重的候選比對用 `_type_set()`，即型別**已參與去重判斷**。

**所以 Gemini 提議的 `schema_org_type` 欄位，等於重複提出已經存在的機制。**

**但有一個 Gemini 沒講到、確實存在的真缺口**（先前已在對話記錄中討論過，非本次新發現）：ENTITY_TYPES 的排序來源是商業網頁（Offer、Restaurant、Recipe、Hotel…），對法規文本的**抽象法律角色**（雇主、勞工、主管機關）貼合度差。`core/constants.py` 註解已誠實聲明這個取捨。這是「型別清單不合領域」，不是「沒有型別」。

**附帶發現（過時註解）**：`services/entity_extraction_service.py:43-48` 寫著「`entity_type` 目前系統全域無強制分類清單（`core/constants.py` 未定義任何實體類型常數…）」——括號內「未定義任何實體類型常數」與 `ENTITY_TYPES` 已存在的事實矛盾，是註解沒跟上程式碼；但「無**強制**分類清單」這半句仍然正確（`ENTITY_TYPES` 是非強制參考清單，不做白名單驗證）。**§8 已只修正錯的那一半。**

**限制（初版）**：我只核對程式碼路徑，**沒有連 Neo4j 抽樣統計 `e.type` 實際填充率與分布**。「主管線有型別」是程式碼層級的結論，實際 KG 裡有多少實體帶型別、品質如何，未驗證。**→ §9.4 已補做，結果顯示覆蓋率差。**

### 2.2 主張②：關係詞彙受限 —— ⚠️ 屬實，但影響未被證實

- **屬實的部分**：`core/constants.py:90-102` 的 `SVO_REL_TYPES` 確為 35 個（7 對稱＋28 非對稱），無「義務／權利／條件」這類法律語意型別。
- **被 Gemini 忽略的緩衝**：`rel_type` 只是粗分類。`SVOTriple` 保留原始 `verb`，並有 `natural_text`（`models/knowledge_graph.py`），prompt 也是用 `natural_text` 組成事實行（`routers/agent.py:539`）。「雇主應給付工資」的「應」字語意留在動詞／自然語句裡，沒有因為 rel_type 被歸到 `RELATED_TO` 之類就消失。
- **證據面**：在我查閱的 `HANDOVER.md`（2026-09-20／21 段）、報告57 §4.19、§4.20 中，**沒有任何失敗題被歸因到關係詞彙不足**。已記錄的失敗型態是：檢索失效（跨文件題 0/13）、抽取漏抽（同句多筆事實其中一句消失，論文 3.1.3 已累計 6 個案例）、評分器盲點（拒答漏判、不檢查歸屬）。
- **限制**：我**沒有**逐份讀完報告 18–62，所以「全專案沒有任何證據」不能這樣斷言，只能說「我查閱的近期評測報告中沒有」。

### 2.3 主張③：AGGR18 寫反是因為缺 Relator —— ⚠️ 現象屬實，診斷與證據不符

**事實（來自報告57 §4.19 與凍結基準 `stage_b4/records.json`）**：

| 面向 | 觀察 |
|---|---|
| 檢索 | Stage 1 Recall 100%，4 個 gold span 全命中，`missed_exact_spans` 為空 |
| Context | Stage 2 `retained_exact_spans` 4 個全保留，`dropped_exact_spans` 為空 |
| 生成 | qwen2.5:7b 把兩部法的機構寫反：「新法規定由公立醫療機構認定，舊法則規定由中央衛生福利主管機關醫院評鑑合格醫院」 |
| 評分 | Atomic Accuracy 100%（4/4）——評分器只看 span 文字出現，不看歸屬 |
| 接地核對 | `grounding_passed: true`——因為兩句話單獨看都能在事實清單裡找到，**接地核對同樣抓不到「句子對、歸屬錯」** |
| scope_audit | 觸發 `aggr18-institution-swapped`（`role_mismatch`）——這是報告57 依「實際觀察到的錯答」補的子字串規則，高精確度、低召回 |

**Gemini 的診斷（缺 Relator 節點）與此不符**：兩造事實都已被完整檢索並送進 context，圖譜的結構沒有造成資訊遺失。

**更可能的真因（間接證據，未經實驗證實）**：

1. `routers/agent.py:508-549` `_split_fact_lines()` 產生的 prompt 行格式是 `- {natural_text}`，`:1037` 組成「以下是從知識圖譜檢索到、可能與問題相關的事實：」後直接列出。**這條路徑上沒有任何來源法規名、條號、施行日的標示。**
2. AGGR18 存檔的 `retained_exact_spans` 是：
   - 「職業災害勞工經醫療終止後，經公立醫療機構認定身心障礙不堪勝任工作。」
   - 「職業災害勞工經醫療終止後，經中央衛生福利主管機關醫院評鑑合格醫院認定身心障礙不堪勝任工作。」

   兩句**都不含法規名**。對 LLM 而言，這兩句是兩條無標籤的並列事實，題目卻問「新法與舊法各由哪種機構認定」——模型要在完全沒有歸屬線索的情況下配對，等於猜。
3. 佐證一個弱訊號：答案的配對順序（先寫「新法＝公立醫療機構」）恰與題目提到「新法」在前、事實清單第一句是公立醫療機構的順序一致，符合「依位置猜」的形狀。這只是相容，**不是證明**。

**限制（重要）**：
- lineage 只存 gold span 是否留存，**沒有存實際送進 LLM 的完整 prompt 行**，所以「事實行不帶法規名」是從程式碼＋span 內容**推論**，不是直接看到 prompt。
- **路徑差異**：凍結基準的 K 臂走的是 harness 路徑，依報告62 §10.2 是把「檢索到的文字」原樣當 `context_lines` 傳給 `_build_prompt()`，**並不經過** `_split_fact_lines()`。所以上面 (1) 引用的 `_split_fact_lines()` 是**正式 `chat()` 路徑**的行為；AGGR18 這次錯答發生在 harness 路徑。兩條路徑都沒有額外加來源標籤，但**harness 路徑實際送進去的檢索文字是否含法規名，仍未直接看到**。
- **可直接驗證的工具已存在，但不在 `master`**：報告62 §10.1 記載 T0（`include_retrieval_trace`，記錄 `prompt_context_lines`＝實際組進 prompt 的事實行）已於 2026-09-21 完成，位於 `worktree-sdd-retrieval-comparison` 分支，並且只新增紀錄欄位、不改檢索／評分。用它對 AGGR18 重跑 K arm 一次，即可直接讀到 prompt 行。
- 僅 n=1，且同題重複結果可能不同（報告57 §4.11）。
- `natural_text`／`fact_text` 在個別 Fact 上是否已含法規名，我沒有逐筆檢查；只能說 span 內容沒有。

**因此 Gemini 的解法（Relator）與這個較便宜的替代解法，是兩條不同層級的路**：

| | Gemini：引入 Relator 節點 | 替代：事實行加來源標籤 |
|---|---|---|
| 改動層 | 圖譜 schema＋抽取＋檢索 | 只在 `chat()` prompt 組裝 |
| 需要重抽 | 是（3307 個 chunk） | 否 |
| 資料是否已具備 | 否 | 是：`source_doc_id`、`source_article_no`（`models/knowledge_graph.py:222`）、Document 的 `title`／`effective_date` 都已在圖裡 |
| 風險 | 大幅擴大範圍 | 動到 `chat()` 行為，須依報告57 附錄D 與凍結基準對照 |

### 2.4 主張④：缺雙時態 —— ✅ 缺口屬實，但已在規劃，且 Gemini 的過濾建議有問題

**缺口屬實**：對 `models/`、`services/`、`repositories/`、`routers/`、`scripts/` 搜尋 `valid_from`／`valid_to`／`governing_status`，**只有** `models/law_document.py`、`repositories/law_document_repo.py`、`routers/agent.py` 出現 `effective_date`（Document 層級，僅用於引用顯示，見 `routers/agent.py:356-393`）。**Fact 層級沒有任何時態欄位，`bfs_query()` 與 `vector_search_facts()` 也沒有時態過濾。**

**但這不是新發現**：論文 `docs/論文/03_系統設計與方法論.md` §3.5（約 1188–1226 行）已有完整的雙時態設計提案（`valid_from`／`valid_to`、衝突偵測、依查詢時間點篩選），並明文標註「`CONFLICT`／`TAGOLD`／`CREATENEW`／`QTIME`／`QAS` 皆為設計提案，非現行系統行為」，文獻依據是 T-GRAG（Li et al. 2025）與 Zep/Graphiti（Rasmussen et al. 2025），另有 SAT-Graph RAG（de Martim 2025）作為法規領域對照。Gemini 提出的欄位與流程，與此設計實質相同。

**已有的相關基礎**：`Document`／`LawArticle` 節點已實作（`Fact -[:SUPPORTED_BY]-> LawArticle -[:PART_OF]-> Document`），Document 有 `effective_date`／`effective_note`；設計上明確定位為「粗粒度時間錨點」，Fact 層級雙時態邊是「更細粒度、留待需要時」（論文 §3.5「與上方雙時態邊設計的關係」）。

**Gemini 的 `governing_status='active'` 硬過濾建議有兩個問題**：

1. **會破壞比較題**：AGGR18／AGGR19 的題面就是「新法與舊法」並列比較（報告57 §4.19）。若檢索只保留 `active`，舊法事實被過濾掉，這類題目的 gold fact 直接消失。過濾必須是「標示」或「排序依據」，不能是預設硬排除。
2. **技術細節不貼合**：BFS 走的是 `Entity--[SVO_REL_TYPES]-->Entity` 關係邊（`bfs_query()`），Fact 是獨立節點，Gemini 寫的 `WHERE r.governing_status = 'active'` 是把 Fact 屬性當成關係屬性，與實際圖結構不符（論文 §3.5 設計也是把時間戳掛在「關係邊」上，並明說需要改 `merge_triples_to_graph()`）。

**尚未匯入的資料**：真正逐條逐版本的歷史需要 `MOJ_LAW_HISTORY_HTML_API`（209 筆）與 `payload.law_histories`，目前未匯入；`effective_date` 只有整份法規層級精度（論文已誠實標註）。所以即使要做，也沒有現成的逐條時間資料可填。

**證據面**：我查閱的評測報告中，沒有「因為新舊版本混淆而答錯」的已確認案例——AGGR18 的錯誤是歸屬寫反（見 §2.3），不是把已廢止規定當現行。

## 3. Gemini 報告中其他值得註記的地方

- **事實面正確**：16,826 筆 Fact、3,307 個 completed chunk、35 個關係、`source_article_no`／`natural_text` 的存在、`role_mismatch` 規則屬「子字串、高精確度低召回」的 pilot——這些都與 `HANDOVER.md` 及程式碼一致。
- **對 `entity_registry_service` 的讚美**（暫存池、長度優先／頻次優先提升）：該模組確實實作了別名累積與提升，描述正確，但與本次四項主張無關。
- **語氣**：「現在完全可以照你的節奏先累積資料，再順勢補上 Schema.org 與時態」——建議方向與論文既有規劃一致，只是它把「已完成的部分」當成「待補」。

## 4. 改進項評估

圖例：成本＝實作＋驗證所需工作量；證據＝目前有多少資料顯示它是瓶頸。

| # | 改進項 | 針對的問題 | 成本 | 證據 | 建議 |
|---|---|---|---|---|---|
| A | **事實行加來源標籤**（法規名＋條號＋施行日） | AGGR18 歸屬寫反 | 低：只改 `chat()` prompt 組裝；資料已在圖中 | 間接（§2.3）：span 不含法規名、答案順序相容「依位置猜」 | **優先**。第一步只做診斷：用報告62 T0 的 trace 對 AGGR18 重跑 K arm 一次，讀 `prompt_context_lines`，不動 `chat()`（T0 在 sdd 分支，需先取得） |
| B | Fact 層級雙時態（RQ5） | 新舊版本 Fact 混雜 | 高：需匯入 `law_histories`、加衝突偵測、`bfs_query()` 時態過濾 | 無已確認失敗題 | 暫緩。若做，以 `effective_date` 當**標籤／排序依據**，不做預設硬過濾 |
| C | 實體型別加法律角色（雇主、勞工、主管機關） | ENTITY_TYPES 偏商業網頁，法律角色貼合度差 | 中 | 初版判「弱」；§9.4 實測後上修：65.3% 實體型別為預設「概念」、「雇主」＝「概念」，覆蓋率問題屬實。但型別對**檢索答對率**的影響仍無證據（型別只參與去重） | 由「低」上修為「低—中」。先處理便宜的一半（為何 LLM 常不給型別／預設值回填），再談法律角色型別；放進 per-KG config 較符合既有架構 |
| D | 擴充法律關係詞彙（義務／權利／條件） | 關係表達力 | 很高：改 `SVO_REL_TYPES`、抽取 prompt、`QSIM` 向量，牽動論文「以 ConceptNet 為依據」論述，並需全量重抽 | 無 | 不建議 |
| E | Relator／OntoClean 本體層 | Gemini 的理論解法 | 研究級 | 無 | 不建議：與論文「診斷 KG 何時有增益」（報告61）的定位相比，會大幅擴大範圍 |
| F | 修正過時註解 `entity_extraction_service.py:43-48` | 文件與程式碼矛盾 | 極低 | 已直接驗證 | ✅ 已於 §8 完成（僅註解，測試 5 項通過） |

### A 案的注意事項（若使用者決定推進）

- **這會改變 `chat()` 行為**，屬 `HANDOVER.md` 第6點所述「`chat()` 行為變更」類，風險最高的一塊。
- 與凍結基準對照時，必須遵守 `HANDOVER.md` 第8點：**程式碼 `e178c4c`、題庫 `404cde9f…`、Windows Ollama 0.34.2**，不可與其他來源混比。
- 報告62 T4／D3：**採用規則要在跑實驗之前先定**（報告62 列為建議值，需使用者裁示），不可看完結果再決定門檻。
- 評分器本身的盲點（不檢查歸屬）仍在；A 案若讓 AGGR18 變對，需確認是真的歸屬正確、不是碰巧不觸發 `aggr18-institution-swapped` 這條子字串規則。
- 標籤可能增加 token 用量與 prompt 長度，對 `top_k`／事實清單截斷（報告23）的互動需要一併看。

## 5. 本報告的限制

1. **§1–§8 撰寫時未連 Neo4j**：沒有抽樣 `e.type` 實際分布、沒有檢查個別 Fact 是否含法規名。**§9 補做了唯讀查詢**（KG#4 `236903cf`，2026-09-21）：實體型別分布、AGGR18 四筆 Fact 的文字與來源回溯、特休分段例句。仍未做的：其他 KG（`76bc98ff`）、`Fact` 全量統計。
2. **未做任何實驗**：A 案的「prompt 缺標籤是真因」是推論，尚未用對照驗證。
3. **未通讀全部報告**：只查了與四項主張直接相關的檔案（`HANDOVER.md`、報告57 §4.19／§4.20、論文 3.1.3／§3.5、相關程式碼、凍結基準存檔）。
4. **Gemini 原文未存檔**，§1 為摘要。
5. AGGR18 僅 n=1、單一 generator（qwen2.5:7b）。

## 6. 待使用者決定

1. **是否推進 A？** 建議先只做診斷（保存並檢視 AGGR18 實際 prompt），確認假說後再談實作與評測設計。
2. **B（雙時態）是否納入論文 RQ5 的實作範圍？** 屬論文範圍決定；本報告的立場是不因這份評測提前。
3. **是否處理 F（過時註解）？** 可獨立、零風險。
4. C／D／E 目前建議不啟動；若使用者對其中任一項有興趣，需先定義「什麼證據會讓它值得做」。

## 7. 關聯文件

- 報告57 §4.19（AGGR18／AGGR19）、§4.20（凍結基準與兩個評分器盲點）
- 報告61（做法與文獻來源查證；論文定位為診斷 KG 何時有增益）
- 報告62（下一階段任務書；T0 保存檢索 trace 已完成、T4 採用規則先定）

> **注意**：報告61、62 撰寫本報告時**只存在於 `worktree-sdd-retrieval-comparison` 分支**，尚未進入 `master`（`master` 最新編號為 60）；本報告 §2.3、§4 對它們的引用，是以該分支上的檔案內容核對過的。這兩份合併進 `master` 前，上述連結在 `master` 上是懸空的。
- 論文 `03_系統設計與方法論.md` §3.1.4（實體型別）、§3.5（RQ5 雙時態）
- `HANDOVER.md` 第4、6、8點
- `docs/參考文獻/37_生成端來源標註與情境元資料/`（本報告 §8 的文獻與專案查證）

## 8. 後續處理紀錄（2026-09-21，使用者要求「處理較好處理的項目、先收集文獻與專案」）

**執行環境約束**：另一個終端機正在跑 T2 Stage A（42 題、`top_k=40`，`sdd-retrieval-comparison` 分支，佔用 Ollama）。因此本輪**不跑任何 LLM 評測**，只做文獻／專案查證、唯讀診斷、文件與註解修正；所有改動都在本報告所在的獨立 worktree。

### 8.1 F：過時註解——已完成

`services/entity_extraction_service.py:43-48`：重讀後發現只有括號內「`core/constants.py` 未定義任何實體類型常數」是錯的；「全域無**強制**分類清單」仍正確。已只修正錯的那一半，並註明暫存區用的是另一套粗粒度中文標籤、與 `ENTITY_TYPES` 詞彙不同。**純註解變更**，`tests/services/test_entity_extraction_service.py` 5 項通過。

### 8.2 A：直接證據升級——prompt 事實行確實不帶來源

§2.3 原本只能從程式碼與 gold span「推論」。這輪讀了 T0 trace（`sdd-retrieval-comparison` 分支 `data/eval/candidate_runs/`，唯讀）的 `prompt_context_lines`——**實際送進 LLM 的事實行**：

- `57-AGGR1`（K arm）與 `17-Q1`（T2 Stage A 已寫入的第 1 題）的 prompt 行**全部是裸句**，例如 `- 雇主 對高空工作車應每月依下列規定定期實施檢查一次 作業裝置及油壓裝置有無異常`、`- 事假 一年內合計不得超過 十四日`：**沒有法規名、沒有條號、沒有施行日**。
- 同一份 trace 的每筆證據已帶 `source_doc_id` 與 `article_no`（欄位：`kind, rank, text, score, source_doc_id, source_svo_chunk_index, article_no, in_prompt`），**資料已在手，只是沒有進 prompt**。

**限制**：目前直接看到的是 AGGR1 與 17-Q1，**不是 AGGR18 本身**（Stage A 尚未跑到）。事實行由同一組函式產生、格式一致，所以「AGGR18 的行也不帶來源」是很強的推論，但直接證據要等 Stage A 寫入 `57-AGGR18` 的紀錄後讀取（免費，不需另跑 LLM；注意那是 `top_k=40` 而非凍結基準的 `top_k=20`，只能回答「行有沒有標籤」，不能拿來比較答對率）。

**這也是「接地核對抓不到歸屬錯誤」的另一個面向**：`grounding_passed: true`（§2.3 表格）——標籤缺失使兩句話單獨看都成立，核對機制沒有歸屬資訊可比。

### 8.3 文獻與專案（已入庫 `docs/參考文獻/37_生成端來源標註與情境元資料/`）

| 項目 | 一句話 | 查證層級 |
|---|---|---|
| ALCE（Gao et al. 2023, EMNLP） | 官方 prompt 模板 `Document [{ID}](Title: {T}): {P}`：每筆 context 都帶編號與標題——**標示來源是既有標準做法** | ✅ 讀官方 repo 一手檔案；論文本身 🟡 abstract 層級 |
| Feng & Steinhardt (2023) | 語言模型需把實體綁到屬性（binding ID 機制），為「並列無標籤事實難以歸屬」提供機制層面的研究基礎 | 🟡 abstract 層級；**合成任務、Pythia／LLaMA，非 qwen2.5:7b，僅能類比** |
| Anthropic Contextual Retrieval (2024-09-19) | 嵌入前前置 chunk 情境；失敗率 5.7%→3.7%（−35%）→2.9%（−49%）→1.9%（−67%，加 reranking） | ✅ 內文即時核對；⚠️ 自家實驗，**檢索端**、非中文非法律 |
| Reuter et al. (2025) SAC | 檢索端注入文件層級摘要（沿用資料夾31） | 🟡 |
| dsRAG（1,588★、MIT） | AutoContext 標頭前置；README 自稱可減少下游 LLM 誤解文字 | ✅ 專案存在與 README 原文；**無公開量化數據，不可當證據** |
| LlamaIndex（52,253★、MIT） | `MetadataMode`＋`excluded_llm_metadata_keys`：「進嵌入的 metadata」與「進 LLM prompt 的 metadata」是兩個獨立開關 | ✅ 原始碼 `schema.py:242-245, 294-298` |

**結論（與報告61 同一立場）**：文獻與專案支持「標示來源是標準做法」與「問題有研究基礎」，但**沒有任何一項直接證明「在本系統事實行加標籤會降低新舊法歸屬錯誤」**——該命題必須靠本專案自己的對照實驗。已查但不採用：Multi-Meta-RAG（檢索前資料庫過濾，非生成端標籤，abstract 無數字）。

### 8.4 A：設計草案與待裁示的採用規則（**尚未實作**）

**為什麼這輪不寫程式碼**：
1. 報告62 T0 已在 `sdd-retrieval-comparison` 分支改動 `_build_prompt()`（新增 `trace_sink`）；我在 `master` 基底的 worktree 改同一函式會產生合併衝突，且 T2 正在跑，那個分支不該被打擾。A 案應在 T2 完成後，**從 sdd 分支的最新狀態**接續。
2. 沒有 Ollama 可用來驗證，只寫碼不驗證不符合本專案「採用規則先定、再跑」的慣例（報告62 T4）。

**設計草案**（供裁示）：
- **標籤內容**：`【{Document.title} 第{article_no}條】`前綴於事實行。資料來源：`source_doc_id` → `_fetch_document_map()`（`routers/agent.py` 已有，供引用顯示用）；`article_no` 已在 trace 證據裡。**第一版不放施行日**（避免 token 膨脹與範圍蔓延；施行日屬 B 案）。
- **降級行為**：無 `Document`（一般文件、舊 KG）→ 不加標籤，與現行逐位元相同。
- **預設關閉**：旗標預設 `False`，使預設行為與凍結基準可比。**旗標放哪裡（更新於 §10.5）**：原草案是在 `ChatRequest` 新增 opt-in 欄位（比照 T0）；查證專案的四層設定後，**更貼合架構的做法是放進 `KGConfig.domain`**，評測時以 `ConfigLoader.load(..., request_overrides=)` 切換，不需改 API。此項併入待裁示。
- **兩條路徑都要處理**：正式 `chat()` 走 `_split_fact_lines()`；harness K 臂是把 `retrieved_texts` 原樣當 `context_lines`（報告62 §10.2）**繞過** `_split_fact_lines()`。標籤注入點必須讓兩條路徑一致，否則評測結果無法代表 `chat()`。
- **token 影響（估算，未實測）**：每行約多 15–25 個中文字，35 行約 +500–900 字元；AGGR18 基準的 context 約 368 tokens，比例不小，需要一併記錄。

**建議的採用規則（建議值，需使用者裁示；比照報告62 T4，須在跑評測前定案）**：
1. **主要指標**：`57-AGGR18` 在重複執行（建議 ≥3 次）中，**歸屬正確**的比例高於無標籤版本。歸屬須以**人工／獨立核對**判定，**不可只靠** `aggr18-institution-swapped` 這條子字串規則（它是「已觀察錯答」的高精確度低召回規則，標籤可能讓模型改用規則沒涵蓋的句型犯錯）。
2. **不退步**：凍結基準 42 題同條件（`e178c4c`、題庫 `404cde9f…`、Windows Ollama 0.34.2）下，達標題數不低於 12，且原本達標的 12 題不得有新增失敗。
3. **成本只記錄不設門檻**：token 增量、延遲。
4. **對照方式**：同批題、同 `top_k`，只切換旗標（有／無標籤），避免與 T2 的 `top_k=40` 效果混淆。

**待使用者裁示**：（a）是否同意 A 案在 T2 完成後接續；（b）上列採用規則的數值與判定方式；（c）標籤第一版是否只用「法規名＋條號」。

### 8.5 未做與遺留

- 論文附錄的參考文獻信任分級表（`docs/論文/附錄與參考文獻.md`）**未更新**：專案慣例要求新增文獻時同步更新，但該表目前也未收錄資料夾31 的 Reuter／Louis 兩篇，屬既有落差；待使用者決定是否一併補齊。
- 兩份新入庫 PDF 皆 🟡（abstract 層級），因環境無 `poppler-utils`；若要當機制層級依據需補精讀。
- AGGR18 本身的實際 prompt 行：待 T2 Stage A 寫入後讀取（§9.3(b) 已用 KG 直接查證 Fact 文字，見該節）。

## 9. 第二份 Gemini 報告查證：《本體抽取與系統落地工程缺口紀錄表 v1.0》（2026-09-21）

### 9.1 檔案與性質

- **位置**：`docs/報告/本體抽取與系統落地工程缺口紀錄表_v1.0.md`（位於主 checkout，**未追蹤、無編號**；本報告**沒有**複製或 commit 它，僅記錄其內容摘要與查證結果）。
- **性質**：Gemini 產出的「Living Gap Log」，列 9 個缺口（GAP-01～GAP-09）、P0/P1/P2 分級，並訂定「重構前必須對應 GAP 編號」「有單元＋回歸測試才可改 `RESOLVED`」的維護協定。內容是第一份 Gemini 評測（§1）的擴充版，把先前四項主張拆成 9 條並加了 Phase 1、Phase 5 的新條目。
- **方法**：逐條對照 `master` 程式碼、報告 56／57、論文 §3.1.3；並對 KG#4（`236903cf-055a-40a8-8923-b9d06601f3b7`，16,826 筆 Fact）做**唯讀 Cypher 查詢**（腳本在 job 暫存目錄，不寫入任何資料、不呼叫 LLM）。

### 9.2 逐項判定

圖例：✅ 屬實　⚠️ 部分屬實　❌ 不成立。「Gemini 分級」為原表 P0/P1/P2。

| GAP | Gemini 分級 | 主張摘要 | 判定 | 關鍵證據（詳見 §9.3） |
|---|---|---|---|---|
| 01 | P1 | 切塊只靠「第X條」正則；項／款／目與附表被壓平；跨項引用被切斷 | ⚠️ | 切塊用的是 `payload.articles` 的結構欄位 `ArticleNo`，**不是正則**（`svo_chunking.py:229-237`）；一條一塊，項／款留在同一 chunk（報告56 §1；3,303 個 `LawArticle` 中最長為 2,143 字元、平均 145 字元），「跨項引用被切斷」對此路徑不成立。**無項款目階層樹屬實。** 表格列被壓平的跡象存在（見 (e)），但來源表格形態未驗證 |
| 02 | P1 | 「前項情事」被誤替換成實體 | ❌ | 法規路徑（`articles is not None`）**明文略過代名詞消解**（`svo_preprocessing_service.py:170-176, 189-196`）；詞庫不含「前項／前條」（`pronoun_resolution_service.py:27`）；POS 標註器沒有任何呼叫端傳入 |
| 03 | P0 | 「應／得／視為」被壓成 `RELATED_TO`／`CAUSES`，失去義務語意 | ⚠️ | `verb` 保留原文措辭（抽取 prompt 規則 2，範例含「得請」「不得超過」「應依規定辦理」）；**缺結構化義務欄位屬實**。所稱 LKIF-Core 標籤不實（見 (d)） |
| 04 | P0 | 條件與法效果割裂（舉特休分段句為例） | ❌ | **KG 實查**：「特別休假 五年以上十年未滿者 每年十五日」是**同一筆 Fact**，條件與天數已綁定（見 (c)）。通用的分段綁定弱點屬已知議題（論文 §3.1.3 三道守衛、報告32 分段），但 Gemini 舉的例子不成立 |
| 05 | P1 | 實體型別貧血 | ⚠️ | 機制存在（§2.1），但**實測 65.3% 為預設「概念」、6.5% 為空**（見 §9.4）——初版判「不成立」已更正。另：`entity_registry_service` 在法規路徑被略過（同 GAP-02 出處），Gemini 指的模組不是問題所在 |
| 06 | P0 | 缺 Relator，導致主體歸屬錯置（AGGR18 根因） | ❌ | **診斷不成立**：AGGR18 的 4 筆 Fact 都能經 `SUPPORTED_BY→LawArticle→Document` 回溯到正確法規名與條號（見 (b)）——**歸屬資訊完整存在於圖中，只是沒有送進 prompt**。所引 `HANDOVER.md` 該段只記載「評分器不檢查歸屬」，**沒有**「LLM 自行排列組合」這個因果論述，那是 Gemini 的推測 |
| 07 | P0 | Fact 缺雙時態；且稱 Fact 有 `source_article_no` | ✅／⚠️ | 缺口屬實，且已在論文 §3.5 RQ5 規劃。**但**：Fact 節點屬性實查為 `kg_id, source_doc_id, verb, confidence, fact_embedding, fact_text, subject, rel_type, source_svo_chunk_index, object`——**沒有 `article_no`**（條號在 `SUPPORTED_BY→LawArticle`）；且**這 4 部法的 `Document.effective_date` 全為 `None`**，依施行日的機制目前拿不到值 |
| 08 | P1 | 原子評分器不檢查歸屬 | ✅ | 屬實且已知（報告57 §4.19／§4.20），已有 `role_mismatch` pilot 規則；`atomic_scorer.py` 已有語意 fallback（報告55），Gemini 說「只比字串」略過時，但歸屬確實不檢查 |
| 09 | P2 | 範圍審查器僅規則式硬比對 | ✅ | 屬實且為刻意設計：`claim_scope_auditor.py:1-7, 36-37` 自述 deterministic、offline、never calls an LLM，正規化後子字串比對。加 NLI 二次複查的方向合理，可重用報告55 的語意比對層 |

**統計**：9 項中 ✅ 3（07 缺口部分、08、09）、⚠️ 3（01、03、05）、❌ 3（02、04、06）。Gemini 標 P0 的四項（03、04、06、07）**沒有一項有實測證據支持 P0**。

### 9.3 重點查證細節

**(a) 法規路徑略過的階段**——`svo_preprocessing_service.py:189-196`：`articles is not None` 時直接建 `ArticleAwareChunking` 後 return，**略過** `SVOGROUP`、別名登記表、代名詞消解、embedding；docstring 自承「法規全文目前不套用代名詞消解」。這使 GAP-02（代名詞誤消解）與 GAP-05 所指的 `entity_registry_service`（別名登記）**對法規 KG 的實際管線都不在執行路徑上**。Gemini 是以模組存在推論其影響。

**(b) AGGR18 的 Fact 與來源回溯**（KG#4 唯讀查詢）：

| 法規（`Document.title`） | 條號 | `Fact.fact_text` | 文字含法規名？ | `Document.effective_date` |
|---|---|---|---|---|
| 職業災害勞工保護法（舊法） | 第 24 條 | 經公立醫療機構認定身心障礙不堪勝任工作 | 否 | None |
| 職業災害勞工保護法（舊法） | 第 23 條 | 職業災害勞工 經醫療終止後，經公立醫療機構認定身心障礙不堪勝任工作 | 否 | None |
| 勞工職業災害保險及保護法（新法） | 第 84 條 | 職業災害勞工經醫療終止後，經中央衛生福利主管機關醫院評鑑合格醫院認定身心障礙不堪勝任工作 | 否 | None |
| 勞工職業災害保險及保護法（新法） | 第 85 條 | 職業災害勞工 經中央衛生福利主管機關醫院評鑑合格醫院認定身心障礙不堪勝任工作 | 否 | None |

Fact 出邊為 `HAS_SUBJECT→Entity`、`HAS_OBJECT→Entity`、`SUPPORTED_BY→LawArticle`。**結論**：圖已經以 `Fact → LawArticle → Document` 表達了「哪一條事實屬於哪一部法、哪一條」，等於已存在輕量版的來源載體；缺的是**把它送進生成端 prompt**。這**直接反駁 GAP-06 的診斷**，並**支持報告 §8 的 A 案**（標籤資料一次兩跳查詢即可得，不需重抽、不需新節點）。

**(c) GAP-04 的例句**：`特別休假 三年以上五年未滿者 每年十四日`、`特別休假 五年以上十年未滿者 每年十五日`、`特別休假 十年以上者 每一年加給一日，加至三十日為止`——三筆分段 Fact 各自把條件與數值綁在一起。Gemini 稱此類綁定「遺失」，對這個實例不成立。

**(d) LKIF-Core**（GAP-03 稱「引入 LKIF-Core 頂層法律模態標籤 `OBLIGATES`／`PERMITS`／`PROHIBITS`／`DEEMS`」）：直接讀 [RinkeHoekstra/lkif-core](https://github.com/RinkeHoekstra/lkif-core)（175★、無 license 欄位、最後 push 2026-02-23）的 `norm.ttl`：`Obligation`、`Prohibition`、`Permission`、`Right`（含 `Obligative_Right`、`Permissive_Right` 等子類）是 **OWL 類別（`a owl:Class`）**，不是關係；**檔內找不到 `OBLIGATES`／`PERMITS`／`PROHIBITS`／`DEEMS`**，`norm.ttl` 中也未搜到 legal fiction／presumption 類別（其他 `.ttl` 檔未逐一查）。也就是 Gemini 把「概念存在」寫成「有這組關係標籤」，**名稱是它自創的**，不能說是 LKIF-Core 現成標籤。附帶：`norm.ttl` 把 `Obligation` 與 `Prohibition` 標為等價類（`owl:equivalentClass`），與 Gemini 把它們當兩個獨立關係標籤的設計不同。

**(e) GAP-01 的表格跡象**：T0 trace 的實際 prompt 行中有 `- 未滿四十歲者 每三年檢查一次`、`- 檢查 每年進行一次` 這類**缺少「檢查什麼」上下文的列**（`57-AGGR1`；這些列來自哪一部法規、是否確為附表，**我未逐一確認**）。這是「表格列被壓平後失去列首語境」的具體跡象，**但**我沒有查來源 JSON 中該表的原始形態，也不知道是抽取端還是資料端造成，只能說「有跡象、未定因」。

### 9.4 GAP-05 更正：實體型別實測（KG#4，唯讀）

| 型別 | 實體數 | 占比 |
|---|---|---|
| 概念（預設值） | 8,021 | 65.3% |
| （空） | 804 | 6.5% |
| PRODUCT | 703 | 5.7% |
| PERSON | 383 | 3.1% |
| ORGANIZATION | 302 | 2.5% |
| 其餘（Action、CREATIVE_WORK、PLACE、ACTIVITY、EVENT、…） | 約 2,077 | 約 16.9% |
| **合計** | **12,290** | |

- 抽樣：`勞工`＝PERSON、`中央主管機關`／`事業單位`／`勞動檢查機構`＝ORGANIZATION，但 **`雇主`＝概念**。
- **機制推論（未經重抽驗證）**：`models/knowledge_graph.py:196,200` 的 `SVOTriple.subject_type／object_type` 預設值就是 `"概念"`；抽取 prompt 規則 4 允許「清單中無合適選項時留空」，`svo_service.py:489-490` 只在 LLM 有給型別時才呼叫 `resolve_entity_type()`。所以 LLM 沒給型別時很可能落入預設「概念」。**另一種可能是 LLM 直接輸出「概念」**——兩者本次無法區分。
- `PRODUCT` 703 個在勞動法規 KG 中看起來不貼合（商業網頁型別清單的後遺症，見 §2.1），**但我沒有逐筆抽查，只是觀察**。
- **對評估的影響**：C 案證據由「弱」上修（見 §4）。**型別覆蓋率差**這件事屬實；**它是否影響檢索答對率**仍無證據（型別目前只參與實體去重）。所以「該不該修」和「有沒有問題」是兩個問題：前者仍無證據，後者已確認。

### 9.5 對 Gemini 缺口紀錄表的整體評估

- **可取的部分**：「Living Protocol」——重構前須對應缺口編號、有單元＋回歸測試才可結案——是好的流程紀律，與專案既有的採用規則先定（報告62 T4）方向一致。GAP-08／09 的描述正確。
- **不宜直接採用為重構依據的原因**：9 條中 3 條不成立、3 條部分屬實；**GAP-06（P0）的根因診斷與實測相反**，若照它「以 Relator 節點落地」，會做一個圖裡其實已有等價結構的東西。Gemini 的分級（P0）沒有評測證據支撐。
- **建議**：若使用者要把這份表當 Living Log 維持，**先依 §9.2 校正各 GAP 的現況與分級**再啟用；否則「重構前必須對應 GAP 編號」會把錯的診斷變成施工依據。本報告不代為修改該檔（它是未追蹤的 Gemini 產出）。
- **一個貫穿兩份 Gemini 報告的模式**：兩份都是**以模組／檔案存在推論影響**，並且**把設計提案當成缺失**（RQ5、Relator）或**把自創名稱掛在既有標準名下**（LKIF-Core）。它們有價值的地方是指出了真實的觀察面（型別覆蓋率、缺 Fact 層時態、評分器不檢查歸屬），但每一項的「原因」與「解法」都需要獨立查證。

### 9.6 對 §8 A 案與待裁示事項的影響

1. **診斷證據升級（§8.2）**：除 T0 trace 外，KG 層也確認 **Fact 文字本身不含法規名**（§9.3(b)），且來源可經兩跳取得。「prompt 缺來源標籤」由「程式碼推論＋trace 旁證」升為「KG 直接證據」。仍缺的是 AGGR18 **本題**的 `prompt_context_lines`（T2 Stage A 尚未跑到）與「加標籤會降低歸屬錯誤」的**因果驗證**（仍須對照實驗）。
2. **§8.4 待裁示 (c)「標籤第一版只用法規名＋條號」**：實測這 4 部法的 `effective_date` 皆為 `None`，**放施行日無資料可用**，所以第一版只放法規名＋條號是**資料面的必然，不只是偏好**。建議裁示為同意。
3. **B 案（雙時態）受資料限制**：`Document.effective_date` 為 `None` 且來源只到整份法規層級精度（論文 §3.5 已誠實標註）；要做逐條時態，必須先匯入 `law_histories`，這是**資料工程先於模型設計**。
4. **C 案優先序小幅上修**（§9.4），但仍在 A 之後。

### 9.7 本輪未做

- 未修改 Gemini 的缺口紀錄表，也未把它併入 repo。
- 未對其他 KG（`76bc98ff`）、`Fact` 全量做統計；型別「概念」的成因未以重抽驗證。
- 未逐條檢查 `PRODUCT` 等型別的實際內容品質。
- 未實作任何改進項；A 案仍待使用者裁示與 T2 完成（§8.4）。

## 10. 第三份 Gemini 報告查證：《知識圖譜分層客製化架構現況與接續任務報告書 v1.0》（2026-09-21）

### 10.1 檔案與性質

- **位置**：`docs/報告/知識圖譜分層客製化架構現況與接續任務報告書_v1.0.md`（主 checkout，**未追蹤、無編號**；本報告未複製或 commit）。
- **性質**：與前兩份不同，這份**不是評測缺陷清單，而是對「四層設定疊合（`core/kg_config/`）」的現況盤點與接續施工指引**：宣稱整體約 70%、四層引擎與查詢端 100%、抽取端 40%；列 4 個「斷點」（P0／P1／P1／P2）、3 個施工步驟（含程式碼草稿）與 3 條驗收標準。
- **重要背景**：專案**已有**這條路線的設計與逐步落地紀錄——`docs/報告/33_設定分層與領域可插拔化設計報告.md`（§6 逐步標註 as-built）。所以查證重點是：Gemini 的盤點與 33 相符幾成、哪些是它新增的、新增的對不對。
- **方法**：對照 `core/kg_config/{model,loader,sources,stages}.py`、`config/`、`routers/agent.py`、`services/{svo_service,extraction_worker,svo_preprocessing_service,knowledge_graph_service,deterministic_guard_service}.py`、`models/eval_schema.py`、報告 33／56；並實測一段最小 pydantic 程式驗證其草稿的一個風險。全程唯讀、不呼叫 LLM。

### 10.2 逐項判定

| 主張 | 判定 | 證據 |
|---|---|---|
| 四層疊合引擎「100% 完工」：遞迴合併、`schema_version` 相容檢查、`frozen` 不可變模型 | ✅ | `loader.py:90-122` 四層 deep-merge；`model.py:20` `_FROZEN = ConfigDict(frozen=True, extra="forbid")`；`config/README.md` 的 schema 版本表；golden test `tests/core/test_kg_config.py` |
| 查詢／生成端「100% 接線」：`BfsConfig`／`FactListConfig`／`DomainConfig` | ✅ 大致，⚠️ 細節有誤 | 報告33 §6 步驟 2、8b′、3a 皆標 ✅；`chat()` 於 `routers/agent.py:1451` 載入設定。**細節錯誤**：`BfsConfig` 沒有「走訪跳數」欄位（實際為 `seed_entity_limit`、`seed_max_degree`、`per_seed_limit`、`doc_scope_top_n_facts`、`expand_when_below`、`prize_top_k`）；「14 Fact＋4 BFS」實為 `truncate_k=18`、`min_bfs_slots=4` 的推算值 |
| 「已完工並跑通」 | ⚠️ 半數 | **第四層（per-request 覆蓋）只在引擎內**：`request_overrides` 全專案只出現在 `loader.py` 與一個測試，`chat()` 呼叫 `.load(kg_id, domain_pack=…)` **未傳入**，API 也沒有對應欄位。**per-KG 層目前沒有任何設定檔**：`config/kg/` 只有 `.gitkeep`（`config/README.md` 的 KG#4 範例不是真檔案）；只有 `generic`、`taiwan-labor-law` 兩個 domain pack。也就是四層中實際在產線上有內容的只有「預設值＋domain pack」兩層 |
| `KnowledgeGraph` 具 `domain_pack`、`pronoun_lexicon_exclude` | ✅ | `models/knowledge_graph.py:47` 起；報告33 §6 步驟 5 |
| **斷點1（P0）**：SVO 抽取 few-shot 硬寫在程式碼，無法依 KG 客製 | ✅ 屬實，但**就是報告33 §6 的「3b ⏳」** | `_svo_prompt(text)`（`svo_service.py:211`）規則 6–9 與範例寫死；`extract_svo_triples` 無 `cfg` 參數（`:444-451`）；`generic.json` 的 `_note` 也自承「svo 抽取少樣本…仍為第 3b–4 步待抽項」。**Gemini 沒提**報告33 §5 **R4**（空 few-shot 會讓 qwen 抽取品質下降，引文獻16「少樣本提示範例干擾」與報告32 §9.6「qwen 對 prompt 敏感」，結論是「不宣稱 generic 等同已驗證路徑，品質列入 per-stage eval gate」），也沒提該步驟的閘控（待 drain、待 eval suite）。標 P0 並暗示照 Step 1–2 即可，**低估了風險** |
| **斷點2（P1）**：`extraction_worker.py` 啟動切塊時不讀 `ChunkingConfig` | ⚠️ 事實對，**位置與影響有誤** | `extraction_worker.py` 沒有任何 `cfg`，但**它不切塊**——`_process_one`（`:54`）只處理已排隊的 chunk。切塊發生在 `svo_service.trigger_extraction()`→`prepare_svo_ready_chunks()`（`svo_service.py:3501`，已接受 `chunking_config=(cfg or KGConfig()).chunking`），其呼叫端 `routers/staging.py`（3 處）與 `knowledge_graph_service.py:122` **都不傳 `cfg`**。報告56 §3 **刻意**不改呼叫端（維持零行為變化，待有真實通用文件 KG 需求再接）。且對法規路徑（`articles is not None`）`cfg.chunking` **完全不生效**（`svo_preprocessing_service.py:181-187`），報告56 記錄「系統裡沒有走 SVOGROUP 路徑的 KG」→ **目前沒有任何受影響的 KG** |
| **斷點3（P1）**：`claim_audit_rules` 應抽成 `<name>.guard.json` 於線上常態攔截 | ❌ **與現行設計相反** | `models/eval_schema.py:40-43`：`ClaimAuditRule` docstring 明說「這些規則只供離線評測使用，不會改變正式 chat 的生成或接地流程」。規則是**逐題**的（id 如 `aggr18-institution-swapped`）且來自「已觀察到的錯答」（報告57 §4.19：子字串、高精確度低召回、pilot）——搬到線上等於把單題過擬合規則當通用護欄。專案**另有**線上向的 `DeterministicGuardService`（起算日／條號／區間三道守衛），但它由 `adaptive_retrieval_service` 與評測腳本呼叫，**不在 `routers/agent.py` 的 `chat()` 路徑**（`routers/` 內無引用）。該服務的正則是台灣法規專用、寫死的（`deterministic_guard_service.py:29-35`）——**這才是與「領域可插拔」相關的真缺口**，但 Gemini 指錯了對象；報告33 §6 我只確認到「抽取端 guard_profile」，**未見生成端守衛 config 化的條目**（未逐段通讀全文，僅讀 §6） |
| **斷點4（P2）**：`PosTagger`／`NerTagger` 無法在設定檔宣告（jieba／CKIP） | ⚠️ 屬實但無需求 | Protocol 存在，但 `SpacyPosTagger` **沒有任何呼叫端**建立或傳入 `pos_tagger`／`ner_tagger`（`svo_preprocessing_service.py:161-166` 自承 spaCy 未安裝驗證、尚未接進 `trigger_extraction()`），法規路徑又直接略過這兩階段（§9.3(a)）；`jieba`／CKIP 的實作在 repo 裡不存在。為休眠路徑加設定入口為時過早 |
| 整體進度「約 70%」、抽取端「40%」 | ❌ 無計算依據 | 報告33 §6 才是逐步標註的權威紀錄：✅ 步驟 1、2、8b′、3a、4（查詢半）、5、5b；⏳ 3b、4（抽取半）、per-stage eval suite（骨架 ✅、4 個 `MANUAL` 階段待做）。百分比是估的 |
| **Gemini 漏列的真實待辦** | — | ①**抽取端半**：`KGConfig` 已宣告 `dedup`（`edit_ratio`／`cosine`／`escalate_low`）、`reltype.compare_cosine_threshold`、`extraction.uncovered_sentence_threshold`，但 `services/` 內**沒有任何一處讀取**（搜尋 `cfg.dedup`／`cfg.extraction`／`compare_cosine` 皆無；只有 `reltype.qsim_*` 在查詢端 `svo_service.py:362-365` 被讀）——**已宣告未接線**，是最低風險的一步。②per-stage eval suite 的 4 個 `MANUAL` 階段（`stages.py`） |

### 10.3 施工草稿的問題（Step 1–3）

1. **Step 1 會破壞專案的深度不可變不變式（已實測）**：Gemini 草稿 `svo_fewshots: list[SvoFewShot] = Field(default_factory=list)` 放進 frozen 模型。我用最小 pydantic 程式驗證：frozen 模型內的 `list` 欄位**可以 `.append()` 成功**（`len` 由 1 變 2），只有整體重指派才拋 `ValidationError`。`model.py:3-5` 的設計宣稱「任一層（含巢狀）寫入都拋」，報告33 §5 R3 要求 deep-freeze 並有測試把關；`KGConfig` 目前**全部是 scalar**（`model.py:10`「第 1 步只收 scalar 常數」），這會是**第一個 list 欄位**。要用 `tuple[SvoFewShot, ...]`，並處理 `deep_merge`（`loader.py:70-86`）對非 mapping 值一律**整體取代**的語意（domain pack 與 per-KG profile 的 few-shot 清單會互相取代、不會串接，需決定這是否符合預期），以及 `model_dump()`→`model_validate()` 往返（`loader.py:107, 122`）。
2. **Step 2 的名稱與簽章與現況不符**：`_format_fewshots`、`_DEFAULT_FEWSHOTS`、`_build_svo_prompt` **都不存在**（實際是 `_svo_prompt(text)`，`svo_service.py:211`）；`extract_svo_triples` 的真實簽章含 `embedding_provider`、`kg_id`、`calibration_db_path`（`:444-451`），草稿省略了它們；另有 `extract_svo_triples_with_completeness_check`（`:950`）與其補抽路徑同樣要貫穿 `cfg`。且範例與規則交織在同一段 prompt（規則 6–9 每條含反例＋正例），不是可乾淨抽出的獨立清單，拆分本身就需要設計。
3. **Step 3（Worker 載入設定）**：模式與 `chat()`（`routers/agent.py:1451`）一致，可行；但落點應在 `trigger_extraction()`／`_process_one` 的呼叫鏈上，且 Worker 是**逐 chunk** 處理，需注意每個 chunk 都重新讀設定檔的成本（我沒有量測，僅提醒設計時要考量快取）。

### 10.4 驗收標準（DoD）評估

| DoD | 評估 |
|---|---|
| 1. 零設定向後相容，Golden Test 100%、benchmark 不退步 | golden test 已存在（`tests/core/test_kg_config.py`，逐欄位比對 live 常數，`model.py:7-8`）。但「benchmark 分數不得退步」**不適用抽取端**：抽取端改動只影響**新抽取**，既有 KG 不變，要比較必須重抽；且日後與凍結基準對照須守 `HANDOVER.md` 第 8 點的凍結條件，不可混比 |
| 2. 新增 `medical.json` 驗證「完全按醫療規則運行」 | 沒有醫療語料與評測，**只能驗「設定被讀取」的機制，不能驗品質**；報告33 R4 已明說不宣稱 generic 品質 |
| 3. 高併發兩個 domain pack 的 KG 互不污染 | 已由 frozen＋R3 測試支撐，但 Gemini 自己的 `list` 草稿會**削弱**它（§10.3 第 1 點） |

### 10.5 整體評估與對前面章節的影響

- **這份報告是報告33 §6 的現況摘要加改寫**，方向與 33 一致，核心盤點（引擎完成、查詢端接線、抽取端未接線）大致正確。**新增的部分品質較差**：斷點 2 位置錯、斷點 3 與現行設計相反、斷點 4 無需求、Step 1 程式碼會破壞不變式、進度百分比無依據；同時**漏掉**報告33 裡真正的兩項待辦（抽取端半、eval suite）與最重要的風險（R4）。
- **可採納**：斷點 1（=3b）的方向與報告33 一致；**最低風險的下一步是把已宣告的 `dedup`／`compare_cosine`／`extraction` 欄位接上讀取**（純接線、預設值等於現值、golden test 把關）。這是我的建議，不是查證結論。
- **關於 3b 的阻塞條件**：報告33 標「待 drain 完」。依 `HANDOVER.md`（2026-09-20）KG#4 佇列已 3307/3307 `completed`，**該條件字面上已滿足**；但 T2 與凍結基準對照仍在進行、R4（qwen 對 prompt 敏感）未解，且改動抽取 prompt 會使新抽取與凍結基準不可比。所以「可以開始」與「該現在做」是兩回事，仍需使用者裁示。
- **對 §8 A 案的設計啟發（重要）**：§8.4 原提議在 `ChatRequest` 新增 `include_source_labels` 旗標。既然專案已有四層設定，**更貼合架構的做法是把開關放進 `KGConfig.domain`**（預設 `False`＝零行為變化，符合報告33 不變式），評測時由 harness／評測腳本以 `ConfigLoader.load(..., request_overrides={...})` 切換——這些腳本本來就自己呼叫 `ConfigLoader`（`scripts/eval/run_rq1_comparison.py:645`、`run_retrieval_comparison.py:382`），**不需要改 API、不需要新增 `ChatRequest` 欄位**；日後若要對某 KG 常態開啟，再寫進該 KG 的 domain pack。附帶：此舉也自然補上了「第四層目前沒有任何呼叫端」的現況。**限制**：harness K 臂把 `retrieved_texts` 原樣當 `context_lines` 傳入（報告62 §10.2），標籤仍須在 harness 路徑與 `chat()` 路徑用**同一個格式函式**產生，否則兩邊不可比。此為設計建議，尚待使用者裁示（併入 §8.4 待裁示項）。

### 10.6 本輪未做

- 未逐段通讀報告33 全文（僅讀 §1、§5 風險表、§6 落地順序與相關搜尋命中），對「生成端守衛 config 化是否已有規劃」下的是「我未見」而非「沒有」。
- 未量測 Worker 逐 chunk 載入設定的成本。
- 未修改 Gemini 的報告書，也未實作任何接線。
