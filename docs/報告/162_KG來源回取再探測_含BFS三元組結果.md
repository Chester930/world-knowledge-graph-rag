# 報告162：KG 來源回取再探測——納入 BFS 三元組（報告160 U3）

> **日期**：2026-09-30 ｜ **基準**：`worktree-sdd-retrieval-comparison` @ `4cf2b7b` ｜ 任務書即本文（U3 任務書由執行對話編號）。
> **性質**：只做檢索、**唯讀 Neo4j、不呼叫任何 LLM**、不改 production 程式、**禁止以 gold 選段**。承接 T5（[任務書](任務書_KG來源回取召回優先探測_v0.1.md)「結果」節）：T5 只能用 Fact 候選（46%），BFS 三元組候選（54%）因記錄沒有 chunk 索引被排除，結論只是下界。
> **腳本與輸出**：`scripts/eval/kg_source_recall_probe_v2.py`；`data/eval/candidate_runs/kg_source_recall_probe_v2/`（`retrieval_rerun.json`＝42 題重跑檢索原始結果含邊上 `citations_json`、`per_question.json`＝逐題逐面向）。

> **更正（2026-09-30，報告166 §10）**：下文「唯讀 Neo4j」指**只讀取資料、沒有任何節點／關係寫入**。但被呼叫的 `vector_search_facts` 每次查詢會先執行冪等的 `CREATE VECTOR INDEX … IF NOT EXISTS`（`svo_service.py:1544`；索引早已存在＝無變更；hybrid 時另建全文索引），本探測當時未查到這一點，措辭因此不夠精確。結論與數字不受影響。

## 0. 結論（先看這裡）

- **不支持「納入三元組後，來源回取優於 B1」。** 預算對齊（以 B1 記錄的 `retrieved_char_count` 為上限）下，Fact＋三元組→來源（R1'）recall==1 為 **25／42**，與 T5 只用 Fact 的 R1 **完全相同**（25／42、平均 recall 0.724），B1 為 **29／42**（0.817）。Type-C＋D：R1' **7／21**、B1 **11／21**。
- **三元組的來源確實能解析（100%，0 筆無法解析），但在預算內沒有增加任何命中**：預算對齊下三元組相對僅 Fact「新增命中 0、失去命中 0」。原因：排序為「Fact 段落在前、三元組段落在後」，B1 的字元預算多半被 Fact 段落用完；三元組只能填剩下的空間（平均字元 1,689→1,899，SNR 0.0315→0.0275）。
- **三元組單獨來源回取明顯弱於 Fact**：僅三元組（預算對齊）recall==1 為 12／42（last citation）或 15／42（全部 citations），對 Fact 的 25／42。
- **不設預算的上限**（看三元組的來源本身有沒有額外 gold）：僅 Fact 26／42（0.736，平均 1,958 字元）→ Fact＋三元組 28／42（0.796，3,364～3,645 字元）；三元組多帶回 **8 個 gold span**（Type-C 5→6、Type-D 3→4 題達 1.0），代價是字元增加約 1.7 倍（SNR 0.0288→0.0171–0.0189）。**即使不設預算，28／42 仍不高於 B1 的 29／42（B1 僅 2,095 字元）。**
- **與 T5 結論的關係**：T5 的「偏不支持」**在納入三元組後仍成立**，且 T5 結論中「三元組被排除可能使 R1 偏低」這個疑慮**已被檢驗：在預算對齊下影響為 0，不設預算時影響為 +2 題／+8 span 但代價高**。仍保留的限制：本探測**沒有**模擬以關係遍歷取得更多相關來源（BFS 為現有 L0/L1、hops=1），不是模式二的上界。

## 1. 環境與前置檢查（報告160 §3 U3）

| 檢查 | 結果 |
| --- | --- |
| (a) Neo4j 可連、KG#4 可讀 | ✅ `kg2-neo4j` 容器（`localhost:17990`）可連；KG `236903cf-…` 可讀（`KGRepository.get`） |
| (b) Ollama 可連 | ✅ `localhost:11434`；embedding 模型 `bge-m3`（依 `kg-reextract/.env`） |
| (c) 不得啟動／重啟 Docker／WSL | ✅ 環境本來就在運行，**未啟動、未重啟任何服務** |
| (d) `ListAgents` 確認無他人使用同資源 | ✅ 其他對話皆離線或為規劃對話（只記錄）；執行前無抽取 drain／Worker 行程 |
| 唯讀 | ✅ 只呼叫 `vector_search_facts`、`bfs_query`、`_find_seed_entities` 等讀取函式與一條讀 `citations_json` 的 `MATCH…RETURN`（不含 `MERGE／CREATE／SET／DELETE`）；連線設定取自 `kg-reextract/.env`（僅讀取，未輸出密碼） |

## 2. 方法

- **檢索步驟鏡像 `chat()`**（`routers/agent.py`）：問題向量化→種子實體（`_find_seed_entities`）→種子文件範圍→`vector_search_facts(top_k=20)`→語意範圍→`bfs_query(hops=1, per_seed_limit=cfg.bfs.per_seed_limit, scope 下推)`→關係型別後篩→範圍兜底過濾。參數同凍結 K 臂：`top_k` 預設 20、`svo_hops` 預設 1、`retrieval_mode=both`、`scope_doc_ids`＝凍結 manifest 的 23 份文件（經 `document_uuid` 轉換，與 `run_rq1_comparison._resolve_scope` 同法）。
- **BFS 三元組的來源**：對每條三元組以 `(subject, rel_type, object)` 讀該邊的 `citations_json`（唯讀）；兩種取法：**last**＝最後一筆 citation（`bfs_query` 本身取的那筆）、**all**＝全部 citations 去重。以 T5 的 `SourceResolver`（`article_no`→`chunk_index`）解析為 KG 資料夾內 chunk 文字；同一 (文件, chunk) 只留首次出現。
- **排序（不得用 gold）**：Fact 依 `vector_search_facts` 排名在前，三元組依 BFS 走訪順序在後（BFS 無問題相關性排序），去重後取前 m 個（m＝3、5、8）或依 B1 字元預算累加。**這個「Fact 優先」排序是本探測的人工決定**，它是三元組在預算內沒有貢獻的直接原因之一；未測「三元組優先」或交錯排序（會需要為三元組設計排序訊號，超出本任務）。
- **比較面向**：R1 重跑（僅 Fact）、R1'（Fact＋三元組，last／all）、僅三元組、T5 R1（凍結 trace 的 Fact）、B1（R2）；嚴格逐字比對，重用 `LineageTracker.record_retrieval`；題庫、凍結 42 題、B1 記錄同 T5。

## 3. 偏離與需留意（誠實記錄）

| # | 事項 | 說明 |
| --- | --- | --- |
| 1 | **關係型別解析以 `llm_provider=None` 執行**（禁止 LLM） | 42 題結果皆為 `None`（＝不做關係型別後篩）。`chat()` 帶 LLM 時，灰色地帶可能解析出型別並篩掉部分三元組；本探測**無法量化**此差異（凍結 trace 三元組 975 筆對重跑 939 筆，差 36 筆，可能部分來自此處或 BFS 走訪的非決定性，未逐一歸因）。 |
| 2 | 重跑與凍結記錄的重疊 | Fact 文字 Jaccard 平均 **0.975**、中位 1.000、最小 0.905（完全相同 31／42 題；最低者 18-Q3、18-Q4、26-Q5、57-AGGR14、57-AGGR16 皆 0.905，即 top-20 中各有 1 筆進出；embedding 非決定性與 top-20 邊界）；三元組文字 Jaccard 平均 **0.895**、中位 0.900、最小 0.750（完全相同 9／42 題）。重跑的 Fact 總數與凍結相同（820）。**不要求逐字相同，差異已量化**。 |
| 3 | **凍結 trace 三元組沒有 chunk 索引的原因（事實）** | `services/context/telemetry.py::build_retrieval_trace` 對三元組把 `source_svo_chunk_index` 與 `article_no` **寫死為 `None`**（`triple_entries` 區塊）；並非資料庫缺資料——邊上 `citations_json` 都有（本探測 0 筆無法解析）。若日後要讓 trace 直接可用，需改 trace 格式（屬報告160 §4 停止條件 #1／#2，**本任務未改**）。 |
| 4 | 未使用 `retrieval_trace` 的 `in_prompt` | 重跑沒有走 `_arrange_fact_lines`／prompt 組裝，故無 R0（K 現行）面向；T5 已證明 R0 因語意 fallback 無法嚴格重現。 |
| 5 | 三元組 citation 的「歸屬」 | 一條邊可累積多筆 citations（不同文件／chunk 抽到同一關係）；`last` 只取最新一筆（`bfs_query` 的行為），`all` 取全部。兩者結果幾乎相同（預算對齊 25／42 相同；僅三元組 12 對 15）。 |

## 4. 結果

### 重疊率（重跑 vs 凍結 retrieval_trace）
- Fact 文字 Jaccard：平均 0.975、中位 1.000、最小 0.905；完全相同 31／42 題
- 三元組文字 Jaccard：平均 0.895、中位 0.900、最小 0.750；完全相同 9／42 題
- 重跑 Fact 數／三元組數（總和）：820／939；凍結：820／975（凍結三元組為去重後 trace 的 kind=triple）
- Fact 重疊最低 5 題：18-Q3(0.9048)、18-Q4(0.9048)、26-Q5(0.9048)、57-AGGR14(0.9048)、57-AGGR16(0.9048)
- 關係型別解析結果（llm_provider=None）：{'None': 42}

### 三元組來源解析（最後一筆 citation）未能解析：{}
相異來源段落數（42 題合計）：僅 Fact 493；僅三元組(last) 561、(all) 647；Fact＋三元組 last 937、all 1009

### 整體（42 題；嚴格逐字）：n／recall==1／平均 recall／平均字元／平均 SNR
| 面向 | n | recall==1 | 平均 recall | 平均字元 | 平均 SNR |
|---|---:|---:|---:|---:|---:|
| R1_rerun_m3 | 42 | 23 | 0.639 | 450 | 0.1081 |
| R1_rerun_m5 | 42 | 24 | 0.688 | 790 | 0.0668 |
| R1_rerun_m8 | 42 | 24 | 0.704 | 1291 | 0.0393 |
| R1_rerun_budget | 42 | 25 | 0.724 | 1689 | 0.0315 |
| R1p_last_m3 | 42 | 23 | 0.639 | 450 | 0.1081 |
| R1p_last_m5 | 42 | 24 | 0.688 | 792 | 0.0668 |
| R1p_last_m8 | 42 | 24 | 0.704 | 1308 | 0.039 |
| R1p_last_budget | 42 | 25 | 0.724 | 1899 | 0.0275 |
| R1p_all_m5 | 42 | 24 | 0.688 | 792 | 0.0668 |
| R1p_all_budget | 42 | 25 | 0.724 | 1904 | 0.0272 |
| R1_tri_only_budget_last | 42 | 12 | 0.397 | 1464 | 0.0274 |
| R1_tri_only_budget_all | 42 | 15 | 0.444 | 1560 | 0.0281 |
| T5 R1_m5（凍結 trace 的 Fact） | 42 | 24 | 0.688 | 790 | 0.0668 |
| T5 R1_budget（凍結） | 42 | 25 | 0.724 | 1692 | 0.0314 |
| B1(R2) | 42 | 29 | 0.817 | 2095 | 0.0304 |

### 分題型：R1_budget(T5)／R1_rerun_budget／R1p_last_budget／R1p_all_budget／B1（recall==1／平均 recall）
| 題型 | 題數 | T5 R1_budget | R1 重跑 | R1' last | R1' all | B1 |
|---|---:|---|---|---|---|---|
| Type-A | 6 | 6／1.0 | 6／1.0 | 6／1.0 | 6／1.0 | 6／1.0 |
| Type-B | 10 | 10／1.0 | 10／1.0 | 10／1.0 | 10／1.0 | 10／1.0 |
| Type-C | 13 | 4／0.59 | 4／0.59 | 4／0.59 | 4／0.59 | 6／0.731 |
| Type-D | 8 | 3／0.594 | 3／0.594 | 3／0.594 | 3／0.594 | 5／0.792 |
| Type-E | 5 | 2／0.4 | 2／0.4 | 2／0.4 | 2／0.4 | 2／0.5 |

### 三元組(last)相對僅 Fact 的預算對齊差異：新增命中 0、失去命中 0

R1' last recall==1：25；B1：29

## 5. 不設預算的上限（看三元組來源本身有沒有額外 gold）

| 面向（不設字元預算） | n | recall==1 | 平均 recall | 平均字元 | 平均 SNR |
|---|---:|---:|---:|---:|---:|
| R1_facts_unbounded | 42 | 26 | 0.736 | 1958 | 0.0288 |
| R1p_last_unbounded | 42 | 28 | 0.796 | 3364 | 0.0189 |
| R1p_all_unbounded | 42 | 28 | 0.796 | 3645 | 0.0171 |

不設預算時，三元組(all)相對僅 Fact 多帶回的 gold span：8 筆
- 57-AGGR1（Type-C）：勞工健康保護規則附表一（特別危害健康作業）之項次一為高溫作業勞工作息時間標準所稱之高溫作業。
- 57-AGGR10（Type-D）：第六條補助金，每人每次得發給新臺幣五百元。但情形特殊者，得核實發給，每次不得超過新臺幣一千二百五十元。
- 57-AGGR16（Type-D）：第一類事業：具顯著風險者。
- 57-AGGR16（Type-D）：第二類事業：具中度風險者。
- 57-AGGR2（Type-D）：勞工健康保護規則附表一（特別危害健康作業）之項次一為高溫作業勞工作息時間標準所稱之高溫作業。
- 57-AGGR7（Type-C）：雇主依本法第二十四條第二項規定辦理訓練，並申請訓練費用補助者，最低開班人數應達五人，且訓練時數不得低於八十小時。
- 57-AGGR8（Type-D）：雇主依前項規定辦理職業訓練，中央主管機關得予訓練費用補助。
- 57-AGGR8（Type-D）：前三條所定補助、利息補貼、津貼或獎助之申請資格條件、項目、方式、期間、廢止、經費來源及其他相關事項之辦法，由中央主管機關定之。

分題型 recall==1（僅 Fact／Fact＋三元組 all，不設預算）：
- Type-A（6）：6 → 6
- Type-B（10）：10 → 10
- Type-C（13）：5 → 6
- Type-D（8）：3 → 4
- Type-E（5）：2 → 2

## 6. 驗收記錄

| 驗收項 | 結果 |
| --- | --- |
| 抽樣回原始資料手算（不經腳本，直接讀 `retrieval_rerun.json` 與 `svo_index.json`） | 57-AGGR8：R1'(last) m5 手算命中 1／4、字元 576，與腳本一致；18-Q3：2／2、1,244 字元；26-Q1：3／3、594 字元——三題皆與腳本一致 |
| 無 gold 參與選段 | `retrieve_all` 與 `triple_candidates`／`dedup_sources`／`take_by_budget` 不接觸 gold；gold 只傳給 `measure` 計分 |
| 唯讀 | 只呼叫讀取函式；未執行任何寫入 Cypher；未啟動／重啟 Docker／WSL；未呼叫 LLM（關係型別解析 `llm_provider=None`） |
| production 程式零變更 | 只新增 `scripts/eval/kg_source_recall_probe_v2.py`、輸出資料夾與本報告 |
| 停止條件 | 未觸發（發現 trace 格式缺欄位屬事實記錄，未修改） |

## 7. 待裁示事項（只列、不代決定）

1. **是否值得繼續投入「KG 來源回取」**：兩次探測（T5、U3）在預算對齊下 R1／R1' 皆 25／42 對 B1 29／42；三元組不設預算時多帶回 8 個 span 但字元約增 1.7 倍。效率優勢（Type-A／B 用約 1/3 字元達 1.0）是否足以支持，屬使用者判斷。
2. **是否要讓 `build_retrieval_trace` 帶出三元組的 chunk 索引／`article_no`**（改 trace 格式；純記錄用途；屬需裁示的行為外變更）。
3. **若要繼續：三元組的排序訊號**（本探測 Fact 優先，未測其他排序；BFS 本身無相關性排序，若要讓三元組在預算內有貢獻需另設計，並注意過擬合）。
