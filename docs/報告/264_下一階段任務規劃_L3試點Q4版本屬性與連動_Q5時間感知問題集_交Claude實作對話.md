# 報告264：下一階段任務規劃——L3′ Q4「版本屬性與連動＋`as_of` 檢索原型」與 Q5「時間感知問題集與評測規則」（交 Claude 實作對話；離線程式與題庫，連線由規劃對話執行）

> **日期**：2026-10-03
> **性質**：階段任務規劃。分工：**規劃對話決定、執行所有資料庫連線與抽取、獨立驗證；Claude 實作對話寫離線程式／測試／題庫**（其使用者規則禁止碰 docker／Neo4j／Ollama／`.env`）。**本文件只由規劃對話修改（§9 執行紀錄）。**
> **依據**：[報告262](262_下一階段任務規劃_L3試點KG條文版本_計畫與前置任務_交Claude實作對話.md)（Q1／Q2 已驗證）；[報告260 §11](260_下一階段任務規劃_L2補驗_as_of時間維度與L1真實資料庫行為_交Claude實作對話.md)（`state_as_of`、先過濾後去重、條文連動識別鍵須含法規識別、BFS 邊無法區分版本）；使用者「同意 繼續」＝同意 Q3 與後續。
> **基準**：HEAD ≥ `e850f01`；全量 pytest **2114 passed**。
> **目前進度（規劃對話，2026-10-03）**：試點容器 `kg2-pilot-neo4j`（埠 28687）已起、匯入完成（4 `Document`／128 `LawArticle`／128 `Chunk`）、抽取 worker 已啟動（最初 6 個區塊約每塊 20 秒至 2 分鐘，預估全部約 1.5–2 小時；抽樣 Fact 均正確連到對應版本的 `LawArticle`）。**抽取完成前你不需要等；你的工作全是離線。**
> **本任務的性質**：**離線**。不得連 KG#4（17990）、試點 Neo4j（28687）、`kg2-neo4j`、Ollama、docker，不得讀 `.env`；所有會連線的腳本寫 `--plan`（離線可測）與 `--execute`（**你不得執行**）。

---

## 1. 目標

在試點 KG 驗證報告257 L3′ 的核心主張：**條文層版本譜系＋事件連動＋`as_of` 先過濾後去重，能讓檢索回答「某時點的規定」而不混入其他版本**。需要三樣東西：①把版本資訊與「新版取代」連動寫進試點圖（Q4-A）；②可呼叫的 `as_of` 檢索原型（Q4-B）；③預先寫死判準的時間感知問題集（Q5）。

## 2. Q4-A 規格：`scripts/kg/pilot_apply_versions.py`（`--plan`／`--execute`）

輸入：`pilot_manifest.json`（Q1 輸出）；目標試點 Neo4j（行程環境變數，閘門**重用** `scripts/kg/pilot_import.py` 的 `validate_environment`／`validate_target_uri`／`validate_kg_id`，不得放寬；埠 28687、禁 17990／27687／7687、拒 `kg2-neo4j`、`kg_id`＝`pilot_kg_id`）。

1. **版本屬性**（對每個 manifest `versions` 項，以（`source_doc_id`, `law_article_no`）精確配對到 `LawArticle`，**不用「條號＋版本」**——報告260 S4 已證明會誤抓他法同號條文）：`law_id`（pcode）、`version_id`、`valid_from`、`valid_to`（＝`valid_to_derived`，最新版為 `null`）、`valid_to_original`、`diff_to_next`、`diff_from_previous`、`is_conflict`、`pilot_roles_json`（manifest 的 `roles`）。配對不到、或同一識別配到多個節點＝停止並回報（不得略過）。
2. **譜系**：對 manifest 的每個相鄰版本對建立 `(:LawArticle old)-[:SUPERSEDED_BY {diff_class, effective_date}]->(:LawArticle new)`（`effective_date`＝新版 `valid_from`；MERGE 冪等）。所有相鄰版本對都建立（含 `same_hash`／`format_only`，以 `diff_class` 區分）。
3. **Fact 事件連動**（沿用報告260 S4 的原型與冪等做法，**可重用** `scripts/analysis/disposable_lifecycle_l2_validation.py` 的 `plan_supersede_events`／`parse_events`／`dump_events` 與 `services/relation_lifecycle`；不得修改這些既有檔）：
   - 對**每個**由試點 `LawArticle` 支持的 Fact（`SUPPORTED_BY`）：若尚無事件，寫入 `[抽取完成@valid_from, 驗證通過@valid_from]`（`trigger_kind="事件"`，`reason="試點：以條文版本生效日建立"`，`evidence_ref="LawArticle:<law_id>:<article_no>:<valid_from>"`）。**所有事件都用該版本的 `valid_from`**（報告260 §2：這樣尚未生效的版本在 `as_of` 之前判為 `not_yet_effective`）。
   - 對舊版 `LawArticle` 支持的 Fact 追加「新版取代」事件（`effective_date`＝下一版 `valid_from`，`evidence_ref`＝`LawArticle:<law_id>:<article_no>:<新版 valid_from>`）。
   - `lifecycle_state` 快取＝`replay(events).final_state`；**冪等**（第二次執行追加 0 筆）；追加後重播非法者跳過並計入統計。
4. **事後稽核**（寫成可離線測試的純函式，`--execute` 結束時呼叫並印出）：每個 Fact 事件重播＝快取（無漂移）；無事件的 Fact 數＝0；各狀態的 Fact 數；舊版 Fact 全為「已被取代」、最新版全為「有效」（以 manifest 推得預期並比對）。
5. **`--plan`**：只讀 manifest，列出將執行的步驟與數量（版本屬性筆數、譜系關係數、預期事件數的上下界），`connects:false`。
6. **測試**（離線，假 driver／純函式）：配對規則（含「同號條文不同法規不得誤配」）、譜系建立、事件計畫（冪等、非法跳過）、事後稽核、閘門重用（拒 17990、拒 `kg2-neo4j`、`kg_id` 比對）、`--plan` 不連線（子行程不得載入 `neo4j`／`core.config`）、不含 `DELETE`／`DETACH`。

## 3. Q4-B 規格：`scripts/kg/pilot_asof_search.py`（as_of 檢索原型）

提供可 `import` 的函式與 CLI：

```
async def asof_search(driver, kg_id, query_vector, as_of, top_k, *, mode="asof", retrievable=DEFAULT_RETRIEVABLE_STATES) -> list[dict]
```
- `mode="naive"`：直接呼叫 production `services.svo_service.vector_search_facts`（現行行為，作對照）。
- `mode="asof"`：以向量索引取 `top_k × FACT_SEARCH_CANDIDATE_MULTIPLIER` 候選（Cypher 取回 `lifecycle_state`、`lifecycle_events_json`、`source_doc_id`、`source_svo_chunk_index` 及該 Fact 所屬 `LawArticle` 的 `law_id`／`article_no`／`valid_from`——透過 `SUPPORTED_BY`），解析事件，用 `disposable_lifecycle_l2_validation.filter_as_of_then_dedupe`（**import 重用**）先過濾後去重，再截斷 `top_k`；回傳 dict 含 `law_id`、`article_no`、`valid_from`、`lifecycle_state`、`as_of_status`（`replayed`／`not_yet_effective`／`no_events`／`illegal`）。
- **識別鍵注意**：`filter_as_of_then_dedupe` 以 `<source_doc_id>#<source_svo_chunk_index>` 當 Fact 識別（`record_fact_id`）；試點中**同一區塊（＝同一條文）會有多個 Fact**，它們的事件**由條文決定而完全相同**，所以鍵相同無妨——但原型必須**斷言**「同一識別鍵下的事件序列一致」，不一致就拋錯（不得靜默覆蓋），並加測試。
- CLI：`--query <文字> --as-of <YYYY-MM-DD> --mode asof|naive --top-k N`（`--execute` 旗標才連線，並重用 Q2 的閘門；embedding 以 `core.providers` 的 Ollama `bge-m3`，由我執行）。
- 離線測試：假 driver（回傳預設候選列）驗證過濾／去重／截斷與回傳欄位；`mode="naive"` 的呼叫簽名；Cypher 結構（只讀、含 `kg_id` 範圍）；不引入新的 production 修改。

## 4. Q5 規格：時間感知問題集 `data/eval/pilot_time_questions.json`＋判準 `docs/報告/265_…`（實作者的報告）

1. **題目來源**（**決定性、不得挑選**）：把 manifest 的實質修改相鄰版本對依（pcode, 條號數值）排序，**每隔 4 對取 1 對**（從第 1 對起；勞基法 41 對→11 對）＋**請假規則全部 3 對**（含衝突的第 12 條，標 `is_conflict`）；另取對照組 `format_only` 與 `same_hash` 各 3 對（依同樣排序、每隔 3 對取 1）。
2. **每個實質修改對寫 2 題**：一題 `as_of` 在舊版有效期間內（舊版 `valid_from` ≤ `as_of` ＜ 新版 `valid_from`，取舊版 `valid_from` 之後 30 天）、期望舊版；一題 `as_of` 在新版 `valid_from` 之後 30 天、期望新版。對照組各 1 題（期望兩版皆可）。題目必須是**繁體中文自然問句、不提版本或年份用語**（例如「勞工…應如何…」，時點只放在 `as_of` 欄位），且問的是**兩版文字真正不同的那個要點**。
3. **欄位**：`id`、`question`、`as_of`、`law_id`、`article_no`（`第 N 條`）、`expected_valid_from`（期望版本的 `valid_from`）、`other_valid_from`（同條另一版）、`gold_exact_span`（取自期望版本 collector 原文的**逐字子字串**，去空白後比對）、`contrast_exact_span`（另一版中對應的不同文字，逐字子字串，對照組為 `null`）、`pair_kind`（`substantive`／`format_only`／`same_hash`）、`is_conflict`、`selection_index`（在排序序列中的序號，供稽核）。
4. **離線驗證器** `scripts/analysis/pilot_time_questions_validator.py`（＋測試）：逐題核對 `gold_exact_span` 確為期望版本原文的逐字子字串、`contrast_exact_span` 確為另一版原文的逐字子字串且與 `gold` 不同（實質修改題）、`as_of` 落在期望版本的有效期間內、`question` 不含 `年`／`版`／`修正前`／`修正後`／`舊`／`新` 等時點用語（可列出命中供人工複核）、題數與選取規則可重現。
5. **預先寫死的判準**（寫進實作者報告，**之後不得調整**；比較「`asof`」與「`naive`」兩種檢索，`top_k=20`，以 Fact 所屬 `LawArticle`（`law_id`＋`article_no`＋`valid_from`）判定，不看生成）：
   - `hit`：回傳的 Fact 中至少 1 個屬於「目標條文的期望版本」；
   - `leak`：回傳的 Fact 中至少 1 個屬於「目標條文的**另一版**」且該版在 `as_of` 當時**不應有效**（舊版已被取代、或新版尚未生效）；
   - **主要指標**（只計 `substantive` 且非 `is_conflict`）：`asof` 的 `leak` 率 ≤ 5%、`asof` 的 `hit` 率 ≥ `naive` 的 `hit` 率；**次要**：`naive` 的 `leak` 率（量化現行風險）、`hit` 率差；**控制組**：`asof` 與 `naive` 的 `hit` 不應有差（不誤殺）；衝突題另列、不計入主要指標。
   - 報告須同時列出各題逐項結果表與未達標題的原因（檢索缺漏／抽取缺漏／其他），**不得事後更動判準或題目**。

## 5. 範圍與驗收

- 新增：`scripts/kg/pilot_apply_versions.py`、`scripts/kg/pilot_asof_search.py`、`scripts/analysis/pilot_time_questions_validator.py`、對應測試、`data/eval/pilot_time_questions.json`、報告 265、索引一行、`HANDOVER.md` 頂部條目。**既有 production、`core/config.py`、既有腳本與測試、規劃文件、論文、題庫（`data/eval/test_cases.json` 等）零變動。**
- 我驗收：讀碼閘門；**我自己用驗證器對題庫逐題重算**（逐字子字串、有效期間、問句用語）；對 `pilot_apply_versions.py --plan` 核對數量；**抽取完成後我實跑 `--execute` 並獨立稽核（事件重播＝快取、冪等第二次 0 筆、各版本狀態）**；再用 `asof_search` 與 `naive` 跑你的題庫並對照預寫判準；全量 pytest ≥ 2114＋新增數、節點卡 0 警告、`.env` 敏感值外洩掃描 0 命中。
- **停止條件**：需要連線或改 production／`core/config.py`；題目無法在不看資料庫輸出的前提下寫出（可只用 collector 原文與 manifest）；`LawArticle` 匹配規則在 manifest 中無法唯一決定；既有 `filter_as_of_then_dedupe` 等被重用函式的介面與本文描述不符（說明差異，不要自行修改）。

## 6. 編號、約定、回報

實作者報告自 **265** 起（先 `ls docs/報告`）。繁體中文；conventional commit；**commit 只 add 自己的檔案、不用 `git add -A`**（共用工作目錄）；push 本分支。**不得自稱已驗證。** 完成時 SendMessage 回報規劃對話，格式：`Q4-A／Q4-B／Q5｜結論｜commit SHA｜題庫摘要（題數／各 pair_kind 題數／衝突題數／選取序號清單）｜驗證器對題庫的結果（逐項通過數、命中用語的題）｜--plan 範例輸出｜新增測試數與全量 pytest｜是否連過資料庫／Ollama／docker／.env（應為否）｜偏離報告264之處（無則寫無）`。

## 7. 不在本任務範圍

起容器／匯入／抽取（規劃對話已做）、`--execute` 實跑、BFS 版本分離、生成階段評測、對 KG#4 的任何寫入。

## 8. 風險與限制（先寫明）

- 檢索層級評測**不等於**答案正確率；它回答「檢索是否混入錯誤版本、是否漏掉正確版本」。
- 試點內容全來自 collector（無換行），抽取品質與 KG#4 不可比；法規只有 2 部、勞基法中間歷次修正可能缺漏。
- 題目由實作者撰寫、規劃對話以驗證器與抽查審核；**題目與判準在看到任何檢索結果前即定稿**。

## 9. 執行紀錄（僅規劃對話更新）

✅ **Q4／Q5 已於 2026-10-03 由規劃對話獨立驗證通過**（實作者 commit `27800de`；紀錄見[報告265](265_L3試點Q4版本屬性連動與as_of檢索_Q5時間感知問題集執行紀錄.md)；**我實跑 `--execute` 與評測的完整結果見[報告266](266_L3試點KG執行與時間感知檢索評測結果.md)**）。摘要：題庫 34 題由我**不重用實作者驗證器**獨立核對 0 問題、選題集合與我重算完全一致；`pilot_apply_versions.py --execute` 寫入 128 版本屬性／64 條取代關係／757 個 Fact 事件（330 已被取代、427 有效），我獨立稽核 0 漂移、冪等；預先寫死判準的評測（雜湊 `07648c6a…`）：**主要指標通過**（`asof` leak 0%／hit 100%，`naive` leak 100%／hit 100%）。實作者對既有測試守衛（`test_no_writes_of_lifecycle_state_anywhere`）的一行例外：**接受**。全量 pytest 2190 passed。KG#4 仍無任何寫入核准。
