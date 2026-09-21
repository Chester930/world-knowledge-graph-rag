# 63 Gemini 評測報告查證與改進項評估

**日期**：2026-09-21
**文件性質**：調查報告（非設計提案、不含任何程式碼變更）。回答使用者的問題：「Gemini 對本專案的評測報告，指出的欠缺是否真的存在？」
**方法**：把 Gemini 報告拆成四項可檢驗的主張，逐項對照（1）當前 `master`（`b1c620e`）的程式碼、（2）論文與報告已有的設計記錄、（3）凍結基準評測（`data/eval/baseline_runs/20260920_frozen/`）的實際存檔。不憑 Gemini 的敘述、也不憑記憶引用。
**來源**：Gemini 報告為使用者貼入對話的文字，**未存檔於 repo**；本報告 §1 的主張摘要即為本報告所依據的版本。
**決策權**：本報告只提供查證結果與評估，**是否採用任何改進項由使用者決定**（見 §6）。

## 0. 結論（先講重點）

1. Gemini 的四項主張中，**只有「缺 Fact 層級時態欄位」大致成立**，而且那本來就是論文 §3.5 的 RQ5 設計提案（自稱「設計中、非現行行為」），不是新發現。
2. **「實體型別貧血」不成立**：Gemini 讀的是暫存區模組（`entity_registry_service.py`），沒看到主管線早已實作 Schema.org 型別標註（52 類核心庫＋939 類擴充庫）。
3. **「缺 Relator 導致 AGGR18 新舊法寫反」的診斷與證據不符**。檢索是滿分，問題出在生成端；而且存檔顯示，留存的 gold span（事實句）**不帶法規名**，因此更可能的真因是「prompt 缺來源標籤」（推論，尚待用 T0 trace 直接驗證），這比新增 Relator 節點便宜得多（§3）。
4. **Gemini 建議的 `governing_status='active'` 硬過濾會破壞現有題目**：AGGR18、AGGR19 就是要同時比較新舊法。
5. 查證過程附帶發現一個**過時註解**（`entity_extraction_service.py:43-48`），與程式現況矛盾。

## 1. 被查證的四項主張

| # | Gemini 主張 | 它建議的解法 |
|---|---|---|
| ① | 實體型別「貧血」：所有實體型別預設「概念」，無語意範疇 | 聚類提升時掛 Schema.org Canonical Type，加 `ontoclean_category` |
| ② | 關係型別被 ConceptNet 35 類綁住，缺義務／權利／條件 | （未給具體改法，暗示需 Relator／Obligation 語意） |
| ③ | 57-AGGR18「原子評分不檢查歸屬」是因為圖譜沒有 Relator（關係載體）節點 | 引入 Relator |
| ④ | 缺雙時態，新舊法 Fact 共存、檢索時混在一起 | `SVOTriple` 加 `valid_from`／`valid_to`／`governing_status`，BFS 加 `WHERE governing_status='active'` |

## 2. 逐項查證

### 2.1 主張①：實體型別貧血 —— ❌ 不成立

**Gemini 看對的部分**：`services/entity_registry_service.py:48,138` 的 `entity_type` 預設確實是 `"概念"`，`services/entity_extraction_service.py:49-55` 的 spaCy 標籤對應也只涵蓋 人物／組織／地點，其餘一律歸「概念」。

**Gemini 沒看到的部分**：那條路徑只是**暫存區（別名登記）**。主管線的型別標註是另一套：

- `core/constants.py:247` `ENTITY_TYPES`：52 類核心庫（依 Brinkmann et al. 2023 WDC 統計實測排序，註解有文獻依據）。
- `data/schema_org_entity_types.json`：939 類 schema.org 官方完整清單（擴充庫）。
- `services/svo_service.py:153-208`：`_ENTITY_TYPE_GUIDE` 把型別清單放進 SVO 抽取 prompt，`resolve_entity_type()` 對 LLM 輸出的 `subject_type`／`object_type` 先比核心庫、再比擴充庫，查不到就保留原字串（不強制驗證，對應論文 3.1.4「實體型別選填」定案）。
- `services/svo_service.py:488-492`：抽取結果逐筆呼叫 `resolve_entity_type()`；`:1348-1376` 寫入 Neo4j 的 `e.type`；`:1176` 實體去重的候選比對用 `_type_set()`，即型別**已參與去重判斷**。

**所以 Gemini 提議的 `schema_org_type` 欄位，等於重複提出已經存在的機制。**

**但有一個 Gemini 沒講到、確實存在的真缺口**（先前已在對話記錄中討論過，非本次新發現）：ENTITY_TYPES 的排序來源是商業網頁（Offer、Restaurant、Recipe、Hotel…），對法規文本的**抽象法律角色**（雇主、勞工、主管機關）貼合度差。`core/constants.py` 註解已誠實聲明這個取捨。這是「型別清單不合領域」，不是「沒有型別」。

**附帶發現（過時註解）**：`services/entity_extraction_service.py:43-48` 寫著「`entity_type` 目前系統全域無強制分類清單（`core/constants.py` 未定義任何實體類型常數…）」——這與 `ENTITY_TYPES` 已存在的事實矛盾，是註解沒跟上程式碼。屬於既有的 stale-doc 類問題。

**限制**：我只核對程式碼路徑，**沒有連 Neo4j 抽樣統計 `e.type` 實際填充率與分布**。「主管線有型別」是程式碼層級的結論，實際 KG 裡有多少實體帶型別、品質如何，未驗證。

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
| C | 實體型別加法律角色（雇主、勞工、主管機關） | ENTITY_TYPES 偏商業網頁，法律角色貼合度差 | 中 | 弱：型別目前只參與去重，未進檢索排序 | 低優先。放進 per-KG config 較符合既有架構；價值待驗證 |
| D | 擴充法律關係詞彙（義務／權利／條件） | 關係表達力 | 很高：改 `SVO_REL_TYPES`、抽取 prompt、`QSIM` 向量，牽動論文「以 ConceptNet 為依據」論述，並需全量重抽 | 無 | 不建議 |
| E | Relator／OntoClean 本體層 | Gemini 的理論解法 | 研究級 | 無 | 不建議：與論文「診斷 KG 何時有增益」（報告61）的定位相比，會大幅擴大範圍 |
| F | 修正過時註解 `entity_extraction_service.py:43-48` | 文件與程式碼矛盾 | 極低 | 已直接驗證 | 建議順手處理，可獨立進行 |

### A 案的注意事項（若使用者決定推進）

- **這會改變 `chat()` 行為**，屬 `HANDOVER.md` 第6點所述「`chat()` 行為變更」類，風險最高的一塊。
- 與凍結基準對照時，必須遵守 `HANDOVER.md` 第8點：**程式碼 `e178c4c`、題庫 `404cde9f…`、Windows Ollama 0.34.2**，不可與其他來源混比。
- 報告62 T4／D3：**採用規則要在跑實驗之前先定**（報告62 列為建議值，需使用者裁示），不可看完結果再決定門檻。
- 評分器本身的盲點（不檢查歸屬）仍在；A 案若讓 AGGR18 變對，需確認是真的歸屬正確、不是碰巧不觸發 `aggr18-institution-swapped` 這條子字串規則。
- 標籤可能增加 token 用量與 prompt 長度，對 `top_k`／事實清單截斷（報告23）的互動需要一併看。

## 5. 本報告的限制

1. **未連 Neo4j**：沒有抽樣 `e.type` 實際分布、沒有檢查個別 Fact 的 `natural_text` 是否含法規名。
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
