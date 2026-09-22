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
| 07 | P0 | Fact 缺雙時態；且稱 Fact 有 `source_article_no` | ✅／⚠️ | 缺口屬實，且已在論文 §3.5 RQ5 規劃。**但**：Fact 節點屬性實查為 `kg_id, source_doc_id, verb, confidence, fact_embedding, fact_text, subject, rel_type, source_svo_chunk_index, object`——**沒有 `article_no`**（條號在 `SUPPORTED_BY→LawArticle`）；且 **AGGR18 涉及的兩部法（4 筆 Fact）的 `Document.effective_date` 皆為 `None`**（全 KG 64 個 Document 中僅 15 個有值，見 §11.2），依施行日的機制對這兩部法拿不到值。*（2026-09-21 更正：初版誤寫「這 4 部法」——實為 2 部法、4 筆 Fact；並補上全 KG 分布。）* |
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
2. **§8.4 待裁示 (c)「標籤第一版只用法規名＋條號」**：實測 AGGR18 涉及的兩部法（新法與舊法）`effective_date` 皆為 `None`（全 KG 64 個 Document 僅 15 個有值），**對這兩部法放施行日無資料可用**，所以第一版只放法規名＋條號是**資料面的必然，不只是偏好**。建議裁示為同意。*（更正：初版誤寫「這 4 部法」，實為 2 部法。）*
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

## 11. 第四份 Gemini 報告查證：《法規 KG 時序支援實作計畫（Temporal Awareness Plan）》（2026-09-21）

### 11.1 來源與性質

- **來源**：使用者於對話貼上，**未存檔於 repo**。內容是三個 Phase 的實作計畫：Phase 1 資料層（`SVOTriple`／Fact 節點加 `law_effective_date`／`law_repealed_date`／`law_version_tag`，`vector_search_facts()` 加 `active_only`，`ingestion_service` 由檔名推導版本）；Phase 2 查詢層（`QueryClassifier` 加 Type-F，`ScenarioType` 加 `TYPE_F`）；Phase 3 守衛層（`DeterministicGuardService` 加 `check_version_conflict()`）。自稱「Phase 1 單獨上線即可解決 80% 的版本混答問題」。
- **性質**：這是報告 63 §9 GAP-07（缺 Fact 層時態）的具體施工方案；它**沒有**先驗證資料面能否支撐。
- **方法**：對照 `master` 程式碼；唯讀 Neo4j 查 KG#4 的 `Document` 節點；把它的 Type-F 正則實際套用到 65 題題庫。全程唯讀，未呼叫 LLM。

### 11.2 判定

| 計畫內容 | 查證 | 判定 |
|---|---|---|
| **資料來源**：`law_repealed_date`、`law_effective_date` 要從哪裡來 | KG#4 的 64 個 `Document` 節點屬性鍵為 `content_hash, effective_date, effective_note, kg_id, record_type, source, source_doc_id, source_url, title, update_date`——**沒有任何廢止／現行狀態欄位**；`update_date`（公布／異動日）64/64 有值，`effective_date` 只有 15/64。舊法「職業災害勞工保護法」`effective_date=None`、`update_date=20181121`；新法「勞工職業災害保險及保護法」`effective_date=None`、`update_date=20210430` | ❌ **`law_repealed_date` 目前沒有資料來源**，全部會是 `None`；欄位加了也填不出值 |
| Phase 1b：`ingestion_service` 由檔名（如 `勞基法_2024修正.pdf`）推導版本 | `services/ingestion_service.py` 的內容是文件解析與 `chunk_and_stage()` 暫存區銜接；法規語料是**結構化 JSON（`pcode`）經匯入腳本進入**，不是檔名帶版本的 PDF。`SVOTriple` 由抽取 Worker 依 chunk 產生（`source_article_no` 亦是如此填入），不由 `ingestion_service` 建立 | ❌ 落點與資料形態都不符 |
| Phase 1a：把三個版本欄位放在每個 Fact 上 | Fact 已可經 `SUPPORTED_BY→LawArticle→Document` 回溯到文件層級中繼資料（報告63 §9.3(b) 實查）。**且 `vector_search_facts()` 已有 `allowed_source_doc_ids` 參數**（`svo_service.py:2255`；over-fetch 候選後依來源過濾）——要做「只檢索現行法規」，只需在 Document 層級補一個狀態屬性、算出允許的 `source_doc_id` 集合傳入，**不必改動 16,826 筆既有 Fact**。計畫的 Fact 欄位只有**新抽取**才會有值，既有 KG 需重抽或回填 | ⚠️ 與既有結構重複，且更貴 |
| Phase 1a 的回填路徑 | 計畫提醒「即時路徑與 `backfill_fact_nodes` 共用 `_create_fact_node()`」（正確），但回填是從邊上的 `citations_json` 重建 Fact；citation 內容由 `_citation_payload` 組成（`svo_service.py` 約 1570–1582 行，含 `article_no` 但無版本欄位）。計畫**沒有列入 citation 欄位**，回填出的 Fact 會遺失版本標注 | ⚠️ 遺漏 |
| Phase 1c：`vector_search_facts` 加 `active_only`，Cypher 寫 `WHERE (f.law_repealed_date IS NULL)` | 函式位置（`:2246`）正確、選填旗標預設關符合專案慣例。但實際查詢的節點別名是 **`node`**（不是 `f`），且有 **dense 與 hybrid fulltext 兩條查詢路徑**（`:2319`、`:2345`）需要一致處理；`RETURN` 子句**沒有**版本欄位，Phase 3 守衛讀 `f.get("law_version_tag")` 會恆為 `None` | ⚠️ 細節不符，Phase 3 因此拿不到資料 |
| Phase 2：`QueryClassifier` 加 Type-F、推薦 `M4_TEMPORAL` | `QueryClassifier` 只被 `services/adaptive_retrieval_service.py` 使用，而後者**除測試外沒有任何匯入者**——不在 `chat()` 路徑。該檔 docstring 自承其 Type-C 正則是「對已知題庫的過擬合」；新增的 Type-F 是同一類手寫正則。`ScenarioType` 定義在 `models/eval_schema.py`，是**題庫題型標籤**；sdd 分支同檔已改動（+43 行），加值會衝突 | ⚠️ 落在休眠程式碼 |
| **Phase 2 的正則實測（65 題題庫）** | 計畫的四條 Type-F 正則共命中 **3 題，全在凍結 42 題內**：`57-AGGR6`、`57-AGGR18`、`57-AGGR19`——**全是「新法（勞工職業災害保險及保護法）與舊法（職業災害勞工保護法）」對照題**（命中的是規則 [1]「新法／舊法」）。這三題**需要同時檢索新舊兩部法規**，被導向 `M4_TEMPORAL`＋`active_only=True` 後，舊法事實會被過濾掉。**真正的「現行／目前…規定」型題目在題庫中命中 0 題** | ❌ **會把最需要新舊並陳的三題導向會排除舊法的路徑**；且題庫沒有它想解決的題型 |
| Phase 3：`check_version_conflict()` | `verify_draft()` 簽章為 `(context_text, fact_lines, question, draft_answer, allowed_articles)`，**沒有 `retrieved_facts` 參數**，計畫未提簽章變更；回傳型別 `GuardVerificationResult` 只有 `is_valid／guard_name／failure_reason／extra_constrained_note`，「不阻斷、只注入警示」需要新機制；`DeterministicGuardService` 同樣只被 `adaptive_retrieval_service` 與評測腳本呼叫，**不在 `chat()`**；測試檔實際名稱是 `tests/services/test_deterministic_guards.py`（計畫寫 `test_deterministic_guard_service.py`）；現有資料沒有任何 `law_version_tag`，守衛**不會觸發** | ⚠️ 介面不符、資料面缺、不在產線 |
| 「Phase 1 單獨上線即可解決 80%」 | 無任何計算或評測依據。我查閱的評測（報告57 §4.19／§4.20、凍結基準）中，**沒有「因引用已廢止規定而答錯」的已確認案例**；新舊法對照題（AGGR6/18/19）的失敗屬歸屬寫反（報告63 §2.3）與檢索失效，不是版本過濾能解 | ❌ 無依據 |
| 「不引入雙時態，單時態即可」 | 與論文 §3.5 RQ5（T-GRAG／Graphiti 雙時態設計）取向不同，屬論文範圍決定，不是工程細節 | 需使用者裁示 |
| 可取之處 | 新欄位全選填（None＝舊資料）、`active_only` 預設關（符合零行為變化慣例）、`_create_fact_node()` 兩條路徑共用的判斷、三個 Phase 可獨立上線、明確排除不改 BFS 與去重鍵 | ✅ |

### 11.3 我的評估與較務實的替代（建議，非查證結論）

1. **先補資料，再談機制**：在 `Document` 層級補「現行／已廢止」屬性（來源：`law_histories`、法規主管機關的狀態資料；對應 schema.org `legislationLegalForce`，見既有討論）。沒有這個資料，計畫的三個 Phase 都只是空欄位。
2. **用既有的 `allowed_source_doc_ids` 做 opt-in 的「僅現行」過濾**：由 Document 狀態算出允許集合，不改 Fact、對既有 16,826 筆立即生效；**預設關閉**。
3. **對照題必須排除在過濾之外**：AGGR6／AGGR18／AGGR19 應作為「**不得被過濾**」的回歸守衛。時序處理對這類題應是「標示版本」，不是「排除舊版」（與報告 §8 A 案的來源標籤是同一方向；`update_date` 64/64 有值，可作版本線索，**但它是公布／異動日、不是施行日**）。
4. Phase 2、3 落在不在 `chat()` 路徑的休眠程式碼，且 Type-F 正則對題庫的實測結果為負面，**不建議現在做**。

### 11.4 「好像剛剛有自動執行」的查核（2026-09-21 17:14）

- **沒有任何人實作這份計畫**：全專案搜尋 `law_version_tag`、`law_effective_date`、`law_repealed_date`、`active_only`、`check_version_conflict`、`M4_TEMPORAL`、`_extract_law_version_meta` 的唯一命中是 `svo_service.py` 的 `_LEAVE_TYPE_FAMILY`（`TYPE_F` 子字串巧合，與時序無關）。
- 主 checkout 在 15:25（兩份未追蹤的 Gemini 檔案）之後**沒有任何檔案被修改**；`master` 仍為 `b1c620e`；本分支乾淨且與 origin 同步。
- **預期內的活動**：Codex 已把 `codex/task1-extraction-cfg-wiring` 推送到 origin（`75f1777`，依先前指示）；`codex-task3` worktree 與分支**尚未建立**（TASK-3 未開始）。我這邊的背景驗證（完整 pytest、突變測試）只在 job 暫存目錄操作，不影響任何分支。
- **T2 Stage A**：records 已寫入 28/42 題（最後一題 `57-AGGR5`；`57-AGGR18` 尚未輪到；`17-Q2` 有 `error` 欄位），檔案最後寫入 16:30:40，距查核時已 44 分鐘。**我無法判斷是仍在跑慢題還是已中斷**（`57-AGGR5/6` 先前單題可達數百秒），該終端機不是我控制的，未做任何操作。

### 11.5 本輪未做

未實作任何項目；未檢查該計畫所稱的「手動驗證」情境；未查 `law_histories` 是否可取得；未評估 `legislationLegalForce` 類屬性的實際資料來源。

## 12. Codex 任務審核紀錄（依報告 64；審核者：Claude，2026-09-21）

審核方式：把 Codex 的分支以 `git archive` 匯出到暫存目錄（不動其分支），**獨立重跑完整測試、對關鍵邏輯做突變測試、獨立重算輸出數字**。未修改 Codex 的分支。

### 12.1 TASK-1 抽取端門檻接線（`codex/task1-extraction-cfg-wiring`，`75f1777`，已推送）——**驗收通過**

| 項目 | 結果 |
|---|---|
| 完整測試 | 動工前 1011 → 完成後 **1022 passed**（獨立重跑相同） |
| 既有測試 | `tests/` 只新增 1 檔（325 行）、0 行刪除 |
| 接線 | 五個門檻全改讀 `cfg`（`cfg=None`＝`KGConfig()`＝原常數）；兩次補抽共用同一 `cfg`；只有 `expand_worker.commit_and_backfill()` 增加選填轉傳；外部呼叫端皆未傳 `cfg` |
| **突變測試** | 破壞 10 處（還原 6 個門檻讀取、拆掉 4 個轉傳）→ **10/10 被新測試抓到**，無存活 |
| 額外檢查 | 移除 `svo_service` 對 `ENTITY_DEDUP_*` 的 import（超出任務書明文）：搜尋 sdd、reextract-v2、Codex 分支，無 `svo_service.ENTITY_DEDUP_*` 的引用 |
| 小問題 | ① Codex 回報「台積電／台積電公司 編輯比率註解為 0.833」不成立——0.833 是「新臺幣四千元／八千元」的註解，台積電的比率為 0.75，任務書無誤；② `COMPARE_COSINE_THRESHOLD` 在 `svo_service.py` 只剩為既有測試保留的 import；③ 每次呼叫新建 `KGConfig()`（含逐實體的 `resolve_entity_name`），未量測成本，與既有 `resolve_query_relation_type` 同寫法 |

### 12.2 TASK-3 Phase 1 來源歧義盤點（`codex/task3-source-ambiguity-audit`，`39b7301`，已推送）——**有條件通過：需一次小修（小修已完成並複驗通過，見 §12.5）**

**獨立驗證通過的部分**
- 完整測試 **1025 passed**（動工前 1011＋新增 14），獨立重跑相同。
- 安全面：Neo4j 只用 `READ_ACCESS` session、串流分批、無寫入語句；輸出檔不含憑證或向量欄位。
- **獨立重算 P1-a**：我以不同方法（不經 `LawArticle` join，改用 `Fact.source_doc_id`；另用 Codex 的 join 母體各算一次）重算，**同文異源文字 189、涉及 Fact 439 兩種母體都吻合**；相異正規化文字 16,180（join 母體）吻合。
- AGGR18 驗算基準（Jaccard 0.489／0.262、frame_overlap 0.806／0.632 等）在**真實 KG** 上與預期一致；四個主配對條號 §23／§24／§84／§85 正確。
- 我先前手算的推論成立且被如實回報：舊法 §23 的 span 會額外配到同法 §24（並另配到 §18），新法 §84 的 span 會配到舊法 §18。

**突變測試：11 個突變中 3 個存活（新測試的缺口，需補）**

| 存活突變 | 意義 |
|---|---|
| M3：配對最短長度 8→1 | 任務書 §5.5 要求「長度 <8 → 不配對」的測試，實際沒有涵蓋 |
| M5：跨文件度量改為只比同文件的配對 | 「同文件不計入跨文件度量」沒有被測試保護（真實輸出正確，但回歸時抓不到） |
| M11：單一法規題也計算跨文件度量 | 任務書 §5.5 要求「`n_source_laws=1` → 三個跨法度量為 `null`」的測試，實際沒有涵蓋 |

其餘 8 個突變（frame_overlap 的上限與後綴、主配對條號反轉、候選門檻、同文異源門檻、正規化空白、Jaccard 分母、候選排序方向）皆被抓到。

**輸出內容的問題與發現**
1. **summary 的限制聲明有誤**：寫「`Document.effective_date` 全 `None`」。這是**我任務書的錯誤**（§11 實查為 15/64 有值），Codex 照抄。已於報告 64 更正；Codex 的 `summary.md` 也需更正。
2. **53 筆 Fact 差異未診斷**：全 KG 16,826 筆、Codex 取得 16,773 筆。我查出：**這 53 筆全來自同一份文件（`source_doc_id=c8298529-91e4-56b3-bf2b-32e847635de4`），沒有 `SUPPORTED_BY→LawArticle`，因此被 join 排除**；內容含「附表一之項次…」「有機溶劑作業場所 包含…」等附表類事實（與報告 63 §9.3(e) 的附表跡象同一類）。碰撞數字不受影響（兩種母體皆 189／439），但 summary 應記載原因。
3. **`gold_exact_collision` 為真的題只有 `57-AGGR10`**，但它不是候選（`n_source_laws<2`），summary 沒有單獨列出。這是「gold 事實本身在另一部法規有同文」的直接暴露案例，應另列。
4. **span 配對覆蓋不完整**：101 個 gold span 中 **35 個（34.7%）未配對**；19 題全配對、23 題有未配對、**8 題完全沒配對**（例如 `57-AGGR5`、`57-AGGR17` 的多個 span）。配對規則刻意保守（互相包含且 ≥8 字、不用 embedding），**未配對不等於 KG 沒有該事實**——可能是抽取後措辭與原文句子不同。
5. **A 案可評測的題目只有 3 題，且全是同一對法規**：候選（`n_source_laws≥2` 且題目含對照字眼）為 `57-AGGR18`（frame_overlap 0.806）、`57-AGGR19`（0.467）、`57-AGGR6`（無跨文件度量——其舊法側 2 個 span 未配對）。**A 案評測不會再只有 n=1，但是 n=3，而且全是「職業災害勞工保護法 vs 勞工職業災害保險及保護法」這一對**，外推性很弱。要擴充需新增題目，而新增題目會改變題庫雜湊（`HANDOVER.md` 第 8 點凍結條件）。
6. 全域碰撞的量級：涉及碰撞的 Fact 439／16,773＝**2.6%**；前幾名多為跨法規的樣板句（「本法施行細則 由 中央主管機關定之」8 部法、「主管機關 在中央為 勞動部」7 部法）。**這是「無標籤裸行」在 KG 全域確實同文異源的量化證據，但比例不大**；AGGR18 這類「同句框不同槽位」的歧義不在這 2.6% 之內。

### 12.3 待 Codex 的一次小修（TASK-3 收尾，建議一個 commit）

1. 補三個測試（§12.2 M3／M5／M11），並在回報中證明它們能抓到對應突變。
2. 更正 `summary.md`：`effective_date` 為 15/64 有值（AGGR18 兩部法為 `None`）。
3. `summary.md` 補：53 筆 Fact 差異的原因（單一文件、無 `LawArticle`、含附表類事實，對碰撞統計無影響）；單獨列出 `gold_exact_collision` 題（`57-AGGR10`）；明列「35/101 span 未配對、8 題完全未配對」為主要限制。
4. 不需要重新查詢 Neo4j（以上皆可由既有輸出與本節資訊補充）；若需要重跑腳本，請維持原有唯讀約束。

### 12.4 對報告 §8 A 案的影響

- 評測題目：見 §12.2 第 5 點——**n=3、單一法規對**，比原本 n=1 好，但仍窄。
- **全 KG 有 2.6% 的 Fact 與他法同文**，標籤對這類事實的作用是確定的；對 AGGR18 型「同句框」的作用仍需靠對照實驗。
- 這些量化結果**不能證明標籤有效**，只界定了「哪裡可能有效」與「能用幾題檢驗」。

### 12.5 TASK-3 小修複驗（`6661684`，已推送）——**驗收通過**

| 項目 | 結果 |
|---|---|
| 新增測試 | 3 個；新測試檔 **17 passed**（原 14＋3） |
| **突變測試（重跑同一組 11 個）** | **11/11 被抓到，無存活**（原 M3、M5、M11 現在都失敗） |
| summary 更正 | `effective_date` 改為「全 KG 64 個 Document 中 15 個有值；AGGR18 涉及的兩部法皆為 `None`」；補 53 筆 Fact 差異原因（單一文件 `c8298529-…`、無 `SUPPORTED_BY→LawArticle`、含附表類事實）；單獨列出 `gold_exact_collision` 題（`57-AGGR10`，未列候選原因：`n_source_laws=1` 且題目無對照字眼）；明列「101 個 span 中 35 個（34.7%）未配對，23 題，其中 8 題全未配對」 |
| 範圍 | 只動 `summary.md`、產生器、測試三檔；`kg_wide.json`／`questions_frozen42.json` 未變動；**未重跑 Neo4j 查詢**（由既有輸出離線重建，符合小修指示） |
| 小問題 | 產生器把兩個資料事實**寫死在樣板文字裡**：「全 KG 64 個 Document 中有 15 個 `effective_date` 有值」與 53 筆差異的 `source_doc_id`。日後若 KG 內容變動並重跑，summary 會照舊寫出這兩句而不反映新資料。屬可接受的一次性報告，但若要長期重用此腳本，應改為由查詢結果計算 |

**Phase 1 結論**：TASK-3 Phase 1 完成並驗收；Phase 2（讀取 T2 Stage A 的 `prompt_context_lines`／`retrieval_trace`）待 T2 完整結束後另行通知。

## 13. T2 進度更正與 AGGR18 的直接證據（2026-09-21 22:20）

### 13.1 更正：§11.4 對 T2 的判斷不成立

§11.4 依據單一資料夾 `t2_k1_topk40_stage_a/records.json` 的最後寫入時間（16:30）推論「44 分鐘沒寫入、可能中斷」。**這個推論是錯的**：T2 被拆成多個輸出資料夾續跑。22:16 查核（唯讀）：

| 資料夾 | 題數 | 最後寫入 |
|---|---|---|
| `stage_a` | 28 | 16:30 |
| `stage_a2` | 14（含 `57-AGGR18`） | 18:13 |
| `stage_a3` | 1（`57-AGGR19`） | 20:51 |
| `stage_b` | 12 | 21:25 |
| `stage_b2a` | 5（仍在寫入） | 22:09 |

機器 18:22 開機、Ollama 20:31 重新啟動，T2 於 21:48 由另一終端機以 `frozen_baseline_stage.py run … --out …stage_b2a --k-top-k 40` 續跑（程序仍存活）。各資料夾題數加總大於 42，表示有重跑／補跑的重複題。**結論：T2 仍在進行，尚未結束；單看某一資料夾的寫入時間無法判斷整體進度。** 報告 64 的 Phase 2 輸入已改為讀取全部 `t2_k1_topk40_stage_*` 資料夾。

### 13.2 AGGR18 的實際 prompt 行（`stage_a2`，`top_k=40`，n=1）

補上報告 §9.6 第 1 項一直缺的直接證據（已完成的單題紀錄，唯讀）：

- prompt 共 35 行。兩條 gold 事實在 prompt 中的實際樣子是**不帶法規名的裸行**：
  - `- 職業災害勞工 經醫療終止後，經公立醫療機構認定身心障礙不堪勝任工作`
  - `- 職業災害勞工 經中央衛生福利主管機關醫院評鑑合格醫院認定身心障礙不堪勝任工作`
- 同一份 `retrieval_trace` 的來源是**正確且可區分的**：前者 `source_doc_id` 開頭 `b90844e9`（職業災害勞工保護法，舊法），後者 `a4c0d396`（勞工職業災害保險及保護法，新法）（對照 Codex 的 summary 中兩部法的 `source_doc_id`）。也就是資料在手、沒進 prompt。
- **答案再次把新舊法配反**（新法→公立醫療機構；舊法→中央衛生福利主管機關醫院評鑑合格醫院），並多出一句無依據的「疑似有身心障礙」。這是第二次觀察到同一種歸屬錯誤（第一次為凍結基準 `top_k=20`），仍是單題、`qwen2.5:7b`、共享 judge。
- **對 A 案設計的新約束**：trace 中 `kind=fact` 的證據 **`article_no` 為 `None`**——`vector_search_facts()` 的 RETURN 只帶 `source_doc_id`、不帶條號（條號在 `SUPPORTED_BY→LawArticle`）。所以「法規名」可由 `source_doc_id`→`Document.title` 直接取得，**「條號」需要額外查詢或修改該 Cypher**。§8.4 待裁示 (c)「法規名＋條號」因此**多了一個成本因素**：若只放法規名，第一版幾乎零成本；加條號需多一次 join。這是設計權衡，仍待使用者裁示。

### 13.3 這些證據的定位

補強了「prompt 缺來源標籤」的診斷（現在是**兩次觀察、兩種 `top_k`、含 prompt 行的直接證據**），但**仍未證明加標籤會修正錯誤**——那必須靠對照實驗。且候選題只有 3 題（§12.2 第 5 點）。

## 14. T2 最終結果與評分器盲點（2026-09-21 23:50 查核）

### 14.1 T2 狀態：已完成

- 凍結 42 題**全部有紀錄**（分散於 `t2_k1_topk40_stage_a/a2/a3/b/b2a/b2b/b2c/c`）；`stage_c` 已產出 `summary_final.json`、`next_questions_final.json`、`judgement_output.txt`；T2 相關程序已不存在，Ollama 沒有載入任何模型（閒置）。
- 該終端機已把判定寫入 sdd worktree 的報告 62 §12（是否已 commit 我未查）：**「需更多證據；且不建議把 `top_k=40` 設為預設行為」**。
- 最後一份寫入為 23:27，判定文件 23:30。

### 14.2 T2 主要數字（引自 `judgement_output.txt`，K1＝`top_k=40` 對凍結基準 `top_k=20`）

| 項目 | 基準 | K1 |
|---|---|---|
| 達標題數 | 12 | 14（新增 6、退步 4，淨增 2） |
| 配對檢定 | — | exact McNemar 雙尾 p = 0.7539；配對差 +4.8 pp，95% CI −10.1～+19.6 pp |
| Context Recall／SNR／Atomic Accuracy | 68.3%／3.79%／50.2% | 74.0%／3.01%／50.8% |
| Type-C（跨文件）達標 | 0/13 | 4/13 |
| Type-B／Type-E 達標 | 5／2 | 3／1 |
| prompt 組成（K1 每次） | Fact 約 19、BFS 約 16 | Fact 約 29.8（其中 14.0 筆來自第 20 名之後）、BFS 約 6.6 |

新增：`18-Q1`、`18-Q6`、`26-Q5`、`57-AGGR6`、`57-AGGR18`、`57-AGGR19`；退步：`18-Q4`、`canary-P1`、`57-DIST1`、`57-DIST2`。

### 14.3 我的補充發現：三個「新增」題的達標不可靠

該終端機的判定把 6 題新增當作真實進步，並指出它們不來自「第 21–40 名 Fact」。我另外對照三題答案與標準答案（快速人工判讀，見限制）：

| 題 | T2 判定 | 我對照標準答案的觀察 |
|---|---|---|
| `57-AGGR18` | 達標（Atomic Accuracy 100%、scope audit `passed=true`） | **答案仍把新舊法配反**：寫「新法要求由公立醫療機構認定、舊法要求由中央衛生福利主管機關醫院評鑑合格醫院認定」，與標準答案相反（舊法＝公立醫療機構）。`scope_audit` 沒抓到，因為 `aggr18-institution-swapped` 規則只涵蓋先前觀察到的句型（報告57 §4.19 已標「高精確度、低召回、pilot」），這次的措辭不在其中。基準之所以判未達標，只是因為基準答案的措辭剛好命中該規則。**這是評分器盲點造成的假性進步** |
| `57-AGGR19` | 達標（Atomic Accuracy 100%，audit 規則數 0） | 答案實質上是**非答案**：把子問題「分別規定在哪些條文」答成一串不相關事實，並寫「資料未明確記載，無法確認」；**沒有給出標準答案的核心（舊法§26；新法§84 第2項、§85 第2項）**，也沒答出「實質相同、非新法新增」 |
| `57-AGGR6` | 達標（Atomic Accuracy 100%，audit 規則數 0） | 前 900 字是一串泛泛的資遣費／退休金事實，**未見標準答案的核心差異**（新法多一個勞基法第53條的例外、改領退休金）；回覆亦重複列出不相關段落 |

**原因**：原子評分只看 gold 事實的文字是否出現在答案（報告57 §4.20 已確認的盲點），不檢查歸屬與是否回答了題目；`57-AGGR6`、`57-AGGR19` 沒有 scope audit 規則（`checked_rule_count=0`）。

### 14.4 含意

1. **強化而非推翻該終端機的結論**：本來就是「不採用」，若這三題進步是假的，證據更不利於 `top_k=40`。
2. **T2 的標題數字對評分器盲點敏感**：Type-C 由 0/13 變 4/13，而這 4 題很可能就是 `26-Q5` 加上這三題（三題皆為 Type-C 的職災新舊法對照題）；若這三題不算，Type-C 的「正向訊號」幾乎只剩 `26-Q5`（其真實性我未查）。粗略把三題扣除後新增 3、退步 4（**未驗證退步四題是否同樣有評分器誤判**，不能據此下淨負的結論）。
3. **對 A 案（來源標籤）的直接影響**：新舊法對照題**正是評分器最不可靠的地方**。若評測 A 案只用原子評分＋現有 audit 規則，會出現「答案配反卻算達標」與「錯誤答案剛好避開規則而算進步」兩種偏差。所以報告 §8.4 的採用規則 (b)「歸屬必須**人工核對**，不可只靠 `aggr18-institution-swapped`」是必要條件，不是可選項。
4. 報告 §12.2 的「A 案候選題僅 3 題」與此一致：AGGR6／18／19 也是評分器最弱的三題，A 案評測的判定必須另建可靠的歸屬核對（人工或語意層）。

### 14.5 限制

- 三題答案只是**快速人工閱讀**，`57-AGGR6` 僅讀前 900 字；未逐字比對 gold span，也未通讀另外三個新增題（`18-Q1`、`18-Q6`、`26-Q5`）與四個退步題的答案。
- 每題僅 1 次（`57-AGGR6`、`57-AGGR19` 有補跑，最後一次見 `stage_c`）；同一 generator／judge 共用；仍是 pilot。
- 我未修改 sdd worktree 的任何檔案，也未動 T2 輸出。

### 14.6 對 TASK-3 Phase 2 的影響

T2 已結束，Phase 2 的前置條件（T2 完整結束）已滿足；**建議由使用者確認後再派**。Phase 2 須讀取全部 `t2_k1_topk40_stage_*` 資料夾（報告 64 已更正），`stage_a` 內的 `records.backup_before_resume.json` 為續跑前備份，**不得讀入**；同題出現在多個資料夾時全部保留並標示來源。

## 16. Codex TASK-3 Phase 2 審核紀錄（`952cfa9`／`c8366d4`／`b6443eb`，小修 `ec3ac9e`）——**驗收通過**

審核方式同 §12：`git archive` 匯出到暫存目錄，獨立重跑測試、對關鍵邏輯做突變測試、**另外獨立重寫一份重算腳本**直接對原始 T2 records 重算整套統計。

### 16.1 獨立重算：四個核心數字位元級吻合

用不依賴 Codex 程式碼的獨立腳本，對 8 個 `t2_k1_topk40_stage_*` 資料夾（42 題範圍）重算：

| 指標 | Codex 回報 | 我獨立重算 |
|---|---|---|
| 總 prompt 行數 | 3993 | 3993 |
| 唯一歸屬 | 3981 | 3981 |
| 多來源合併 | 7 | 7 |
| unmatched | 5 | 5 |

**執行數的差異與解釋**：我第一次重算得到 78 次執行，Codex 回報 79。查出原因：`57-…／17-Q2` 在 `t2_k1_topk40_stage_a` 那次執行 T2 當時出錯（`error` 欄位非空），`prompt_context_lines` 為空清單；該題在 `stage_a2` 有成功重跑（70 行，與逐題分布表一致）。**Codex 正確地把這次零行但仍存在的執行算進 79**，我的重算腳本一開始把它漏算，不是 Codex 的錯誤，反而印證了它對邊界情況（空清單 vs 缺欄位）處理正確。

### 16.2 突變測試（首次 6 個、小修後全跑）

首次（`952cfa9`）：4 killed／2 survived（P2 前綴、P6 缺來源 ID）。要求 Codex 補測試後（`ec3ac9e`）：

| 突變 | 首次 | 小修後 |
|---|---|---|
| P1 多來源門檻 | killed | killed |
| P2 不去除「- 」前綴 | survived | **仍 survived（見 16.3，非真缺陷）** |
| P3 移除 `in_prompt=true` 篩選 | survived | **killed**（新測試 `test_prompt_analysis_ignores_matching_trace_when_in_prompt_is_false`） |
| P4 frame_overlap 跨文件排除條件反轉 | killed | killed |
| P5 獨立碰撞門檻 | killed | killed |
| P6 缺來源 ID 誤判為 unique | survived | **仍 survived（見 16.3，殘留真實缺口）** |

### 16.3 P2、P6 的進一步查證

- **P2（不成立）**：直接測試 `normalize_text("- 第一行") == normalize_text("第一行")` → `True`。`normalize_text` 本身會把 `-` 當標點（Unicode 類別 `P`）移除，所以 `_prompt_line_text_and_key()` 手動 `line[2:]` 的前綴去除是**縱深防禦，不是唯一防線**；移除它不影響實際行為。**P2 不是缺陷，撤回。**
- **P6（真實殘留缺口，已查證）**：Codex 補的 `test_prompt_analysis_marks_matching_trace_without_source_doc_id_as_unresolved` 只涵蓋「**兩筆 trace 都缺** `source_doc_id`」（`document_ids` 為空集合）。我的突變測的是**混合情境**——一筆有效來源＋一筆缺來源（`document_ids` 長度為 1、但 `has_missing_document=True`）。我另外寫了一個獨立腳本，對**未突變**的程式碼餵這個混合情境：正確結果是 `source_unresolved`（程式邏輯本身是對的），但**目前沒有任何測試守著這條路徑**，`_classify_trace_matches()` 的 `has_missing_document` 判斷仍可能被無聲破壞。

### 16.4 完整測試

獨立重跑：新測試 23 passed；完整測試 **1034 passed，0 failed**。與 Codex 回報一致。

### 16.5 結論

**TASK-3（Phase 1＋Phase 2）驗收通過，可視為完成。** P6 的殘留測試缺口風險低（程式邏輯已驗證正確，只是少一條回歸測試），不影響本次交付的統計結果可信度，**不要求立即再修**；記錄於此供之後任何人修改 `_classify_trace_matches()` 時參考。P2 已確認不是問題，不需處理。

### 16.6 對 A 案的最終資料基礎

至此，A 案（事實行加來源標籤）已有三層獨立驗證的資料基礎：
1. KG 唯讀查詢（報告 63 §9.3(b)）：AGGR18 四筆 Fact 可經 `SUPPORTED_BY→LawArticle→Document` 回溯正確法規名與條號。
2. T0/T2 trace 單題核對（§13）：AGGR18 實際 prompt 行不帶法規名，答案配反。
3. **Phase 1+2 的 42 題全量統計（本節與 §12）**：42 題中僅 `57-AGGR18`（frame_overlap 0.806）、`57-AGGR19`（0.467）、`57-AGGR6` 三題適合當 A 案候選；全 KG 有 2.6% 的 Fact 存在跨法規同文，但 AGGR18 型「同句框不同槽位」不在此列；prompt 層級的多來源合併行僅 0.18%（7/3993），且非 gold。

三層資料一致，沒有互相矛盾之處。A 案是否推進，仍待使用者對報告 §8.4、§10.5 待裁示項的裁決；本節只是把證據基礎補齊到可以做決策的程度。
