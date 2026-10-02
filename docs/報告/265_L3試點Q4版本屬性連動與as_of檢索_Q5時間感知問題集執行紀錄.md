# 報告265：L3′ 試點 Q4（版本屬性與連動＋`as_of` 檢索原型）與 Q5（時間感知問題集與判準）——執行紀錄（Claude 實作對話；待規劃對話驗證）

> **日期**：2026-10-03
> **依據**：[報告264](264_下一階段任務規劃_L3試點Q4版本屬性與連動_Q5時間感知問題集_交Claude實作對話.md)。
> **性質**：離線程式、測試與題庫。**未連 KG#4／試點 Neo4j（28687）／`kg2-neo4j`／Ollama／docker、未讀 `.env`；`--execute` 全部未執行。** 題庫驗證器只讀 manifest 與 collector 檔（唯讀）。不自稱已驗證——驗證由規劃對話做。

## 1. 基準與交付

HEAD `3705db6`（含報告264）；全量 pytest 基準 **2114 passed**；報告自 265 起。

| 檔案 | 內容 |
| --- | --- |
| `scripts/kg/pilot_apply_versions.py`（新增） | Q4-A：版本屬性、`SUPERSEDED_BY` 譜系、Fact 事件連動、事後稽核；`--plan`（離線）／`--execute` |
| `scripts/kg/pilot_asof_search.py`（新增） | Q4-B：`asof_search(...)` 與 CLI（`mode="asof"`／`"naive"`） |
| `scripts/analysis/pilot_time_questions_validator.py`（新增） | Q5：決定性選題規則、判準常數、離線驗證器 |
| `data/eval/pilot_time_questions.json`（新增） | Q5：34 題＋meta（含預先寫死的判準） |
| `tests/scripts/test_pilot_apply_versions.py`／`test_pilot_asof_search.py`／`test_pilot_time_questions_validator.py`（新增） | 21＋24＋24＝**69** 個測試 |
| `tests/services/test_trace_lifecycle_state.py` | **改動既有測試的一個守衛（偏離，見 §6-1）** |
| 報告265、索引一行、`HANDOVER.md` 頂部條目 | 文件 |

## 2. Q4-A `pilot_apply_versions.py`

- **閘門重用**：`--execute` 以 `pi.validate_environment`／`pi.validate_target_uri` 呼叫 `scripts/kg/pilot_import.py` 的函式（埠 28687、禁 17990／27687／7687、拒 `kg2-neo4j`、`kg_id`＝`pilot_kg_id`、拒 KG#4 id），閘門通過後才匯入 `core`；有效設定與行程環境變數不一致即停止。
- **配對**：manifest 版本以 (`source_doc_id`, `law_article_no`) 精確配對 `LawArticle`；缺少或重複＝`MatchError` 停止（測試含「他法同號條文不得誤配」；`LAW_ARTICLE_NODES_CYPHER` 不使用法規或版本屬性）。
- **版本屬性**：`law_id`／`version_id`／`valid_from`／`valid_to`（＝推導值，最新版 `null`）／`valid_to_original`／`diff_to_next`／`diff_from_previous`／`is_conflict`／`pilot_roles_json`。
- **譜系**：對 manifest 相鄰版本對 `MERGE (old)-[:SUPERSEDED_BY {diff_class, effective_date=新版 valid_from}]->(new)`（下一版不在 manifest 者記入 `pairs_skipped`，不是錯誤；真實 manifest 為 0）。
- **事件連動**（沿用報告260 S4 原型）：無事件的 Fact 寫 `[抽取完成, 驗證通過]@valid_from`（`trigger_kind="事件"`、`reason="試點：以條文版本生效日建立"`、`evidence_ref="LawArticle:<law_id>:<第 N 條>:<valid_from>"`）；舊版 Fact 追加「新版取代」（`effective_date`＝下一版 `valid_from`，`evidence_ref` 含新版 `valid_from`；重用 `plan_supersede_events`，追加後重播非法者跳過並計入 `skipped_illegal`）；`lifecycle_state`＝`replay(events).final_state`；**冪等**（第二次 `updated`＝0、`superseded_appended`＝0）。`<article_no>` 我採 manifest 的 `law_article_no`（`第 N 條`）。
- **事後稽核**（純函式 `audit_facts`，`--execute` 結束印出）：事件重播＝快取（無漂移）、無事件 Fact 數＝0、各狀態數、舊版全「已被取代」／最新版全「有效」（由 manifest 推得預期）。
- **`--plan`**（對真實 Q1 輸出，`connects:false`，子行程測試確認不載入 `neo4j`／`core.config`／`svo_service`／S4 原型模組）：版本屬性 128 筆、`SUPERSEDED_BY` 64 條（`substantive` 44／`format_only` 10／`same_hash` 10）、舊版 64／最新版 64（衝突版本 4）；事件：每個最新版 Fact 2 筆、舊版 Fact 3 筆；若每條文恰 1 個 Fact 則下界 2×64＋3×64＝**320** 筆，上界＝3×實際 Fact 數（Fact 數需連線才知道）；第二次執行預期追加 0。

## 3. Q4-B `pilot_asof_search.py`

- `asof_search(driver, kg_id, query_vector, as_of, top_k, *, mode="asof", retrievable=DEFAULT_RETRIEVABLE_STATES)`。`naive`：呼叫 production `svo_service.vector_search_facts(driver, kg_id, query_vector, top_k)`（測試鎖定位置參數簽名），再以只讀 Cypher 補上所屬 `LawArticle` 的 `law_id`／`article_no`／`valid_from`（評測歸屬用；`as_of_status` 為 `None`）。`asof`：向量索引取 `top_k×FACT_SEARCH_CANDIDATE_MULTIPLIER` 候選（`properties(node)['lifecycle_state']`／`['lifecycle_events_json']`＋`OPTIONAL MATCH (node)-[:SUPPORTED_BY]->(a:LawArticle {kg_id: $kg_id})`）→ `filter_as_of_then_dedupe`（import 重用 S4 原型，**先過濾後去重**）→ 截斷 `top_k`；回傳欄位固定為 `fact_text`／`subject`／`verb`／`object`／`rel_type`／`score`／`source_doc_id`／`source_svo_chunk_index`／`law_id`／`article_no`／`valid_from`／`lifecycle_state`／`as_of_status`（`replayed`／`not_yet_effective`〔不會出現在結果，被過濾〕／`no_events`／`illegal`）。與 production 一致地先 `create_fact_vector_index`（`IF NOT EXISTS`）。
- **識別鍵斷言**：同一 `<source_doc_id>#<chunk>` 下事件序列不一致（含 `None` 對非空）→ `InconsistentEventsError`（有測試；同一條文多個 Fact 但事件相同則通過）。
- CLI：`--query／--as-of／--mode／--top-k`；不帶 `--execute` 只印離線請求計畫（`connects:false`；子行程測試不載入 `neo4j`／`core.config`／`svo_service`／S4 原型）；`--execute` 才連線（重用 Q2 閘門，embedding＝`init_providers()` 的 Ollama `bge-m3`，由規劃對話執行）。

## 4. Q5 題庫與判準

### 4.1 選題（決定性、不得挑選；規則寫在 `pilot_time_questions_validator.py`，驗證器可重現）

實質修改相鄰版本對共 44（勞基法 41＋請假規則 3），依 (pcode, 條號數值, 舊版 `valid_from`) 排序，**每隔 4 對取 1 對**（序號 0、4、…、40＝11 對）＋請假規則全部 3 對（序號 41、42、43）＝**14 對，每對 2 題＝28 題**；對照組 `format_only`／`same_hash` 各 10 對，依同樣排序每隔 3 對取、各取前 3 對（序號 0、3、6）＝**6 題**。合計 **34 題**；衝突題 **4 題**（勞基法第 86 條、請假規則第 12 條各 2 題，`is_conflict=true`）。

| `pair_kind` | 題數 | `selection_index` |
| --- | --- | --- |
| `substantive` | 28（14 對×2） | 0、4、8、12、16、20、24、28、32、36、40（勞基法第 2、9、21、30、37、45、53、58、72、77、86 條）、41、42、43（請假規則第 7、9、12 條） |
| `format_only` | 3 | 0、3、6（勞基法第 1、13、20 條） |
| `same_hash` | 3 | 0、3、6（勞基法第 5、18、26 條） |

`as_of`：舊版題＝舊版 `valid_from`＋30 天（勞基法 `1984-08-29`、請假規則 `2023-05-31`）；新版題與對照題＝新版 `valid_from`＋30 天（勞基法 `2024-08-30`、請假規則 `2026-01-08`）。每對的兩題問句相同、`as_of` 與 gold／contrast 對調。問句為繁體中文自然問句，**不含**「年／版／修正前／修正後／舊／新」（驗證器逐題檢查；命中 0）；時點只放在 `as_of`。欄位除報告264 §4 所列外，另加 `acceptable_valid_froms`（期望版本集合；對照組含兩版）與 `expected_role`（`old`／`new`／`either`），供判準使用。

**題目撰寫時機**：題目由我讀 collector 原文與 manifest 撰寫，**撰寫時沒有看過任何檢索結果**（這個對話不連資料庫）。

### 4.2 預先寫死的判準（**之後不得調整**；與題庫 `meta.criteria` 完全相同，其 sha256＝`07648c6a7fe70024c3b767d1e772fe6960c873acd3134ee2a6306d864c08a1de`，由測試鎖定）

- 比較 `asof` 與 `naive` 兩種檢索，`top_k=20`，以 Fact 所屬 `LawArticle`（`law_id`＋`article_no`＋`valid_from`）判定，不看生成。
- `hit`：回傳的 Fact 中至少 1 個屬於「目標條文的期望版本」（對照組：`acceptable_valid_froms` 內任一版）。
- `leak`：回傳的 Fact 中至少 1 個屬於「目標條文的另一版」，且該版在 `as_of` 當時不應有效（舊版已被取代、或新版尚未生效）。
- **主要指標**（只計 `substantive` 且非 `is_conflict`，即 12 對×2＝24 題）：`asof` 的 `leak` 率 ≤ 5%；`asof` 的 `hit` 率 ≥ `naive` 的 `hit` 率。
- **次要**：`naive` 的 `leak` 率（量化現行風險）、`hit` 率差（asof 減 naive）。**控制組**：`asof` 與 `naive` 的 `hit` 不應有差（不誤殺）。**衝突題**另列、不計入主要指標。
- 報告須同時列出各題逐項結果表與未達標題的原因（檢索缺漏／抽取缺漏／其他），不得事後更動判準或題目。

### 4.3 驗證器對題庫的結果（對真實 manifest 與真實 collector 檔唯讀實跑）

`python scripts/analysis/pilot_time_questions_validator.py`：`ok=true`；34 題中——`gold_exact_span` 為期望版本原文逐字子字串（去空白後）**34／34**；`contrast_exact_span` 為另一版原文逐字子字串（實質修改題；對照題為 `null`）**34／34**；`as_of` 落在期望版本有效期間 **34／34**；問句無時點用語 **34／34**（命中 0）；選題序號與規則重現一致、id 不重複、`meta.criteria` 與預先寫死的判準一致。

**須揭露（非失敗）**：①5 對「新增條款型」修正（勞基法第 9、30、58、86 條、請假規則第 12 條）在另一版沒有對應文字，只能引用相關的共同句，所以其舊版題的 gold 同時出現在新版（`gold_also_in_other_version`：`PTQ-N0030001-9-old`／`-30-old`／`-58-old`／`-86-old`、`PTQ-N0030006-12-old`），新版題的 contrast 同時出現在期望版本（`contrast_also_in_expected_version`：對應 5 個 `-new`）；②對照題 6 題的兩版去空白後相同，`gold_also_in_other_version` 為 true 屬預期。判準以 `LawArticle` 版本為準，不受此影響。

## 5. 測試與全量結果

新增測試 **69 個**（Q4-A 21、Q4-B 24、Q5 24）；全量 pytest **2183 passed**（基準 2114＋69）、0 failed；`check_node_cards.py`：3 張節點卡、0 警告。涵蓋重點：配對（含他法同號條文）、譜系、事件計畫冪等與非法跳過、事後稽核（漂移／缺事件／狀態不符）、假 driver 端對端兩次執行、Cypher 範圍（`{kg_id: $kg_id}`）與無 `DELETE`／`DETACH`、閘門重用與拒絕 17990／`kg2-neo4j`／27687／7687／KG#4 id 且不印密碼、`--plan` 不載入 `neo4j`／`core.config`、`asof` 先過濾後去重重現報告260 S2、識別鍵一致斷言、`naive` 呼叫簽名、驗證器各檢查項、選題數值排序、判準雜湊鎖定、題庫檔結構與（機器上有資料時）對真實資料的完整驗證。

## 6. 偏離報告264 之處與限制

1. **改動既有測試的一個守衛**：`tests/services/test_trace_lifecycle_state.py::test_no_writes_of_lifecycle_state_anywhere`（報告259 L1 的守衛，禁止 repo 內非 `disposable_*` 檔案出現 `lifecycle_events_json`）會被本任務依規格必須讀寫該屬性的試點腳本觸發失敗。我把 `scripts/` 下檔名以 `pilot_` 開頭者與 `disposable_*` 一併視為實驗 harness 排除（一行；production 路徑仍被禁止）。報告264 §5 要求既有測試零變動，此處需規劃對話確認接受。
2. 額外欄位 `acceptable_valid_froms`、`expected_role`（見 §4.1）。
3. 驗證器對「新增條款型」不要求 contrast 不在期望版本（改為揭露，見 §4.3），否則這 5 對無法在不編造文字的前提下通過。
4. `evidence_ref` 的 `<article_no>` 採 `第 N 條`（`law_article_no`）。
5. 限制：所有連線腳本的 Cypher 只以假 driver 與結構測試驗證，**未對任何 Neo4j 實跑**；`asof` 的 `OPTIONAL MATCH … SUPPORTED_BY` 候選查詢與 `attribute_records` 在真實圖上的行為待規劃對話驗收；檢索層級的評測不等於答案正確率；題目由我撰寫，已由驗證器與判準凍結機制約束。

## 7. 待規劃對話／使用者裁示（只列不代決）

1. 是否接受 §6-1 對既有 L1 守衛的一行改動。2. 抽取完成後的 `--execute`（Q4-A）與以本題庫對 `asof`／`naive` 的實跑與判準對照由規劃對話執行。
