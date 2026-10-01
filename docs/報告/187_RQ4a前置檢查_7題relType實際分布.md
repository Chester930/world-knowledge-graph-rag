# 報告187：RQ4a 前置檢查——7 題相關事實的 `rel_type` 實際分布（唯讀 Neo4j；報告185 C1）

> **日期**：2026-10-01
> **性質**：只讀。對 KG#4（`236903cf-055a-40a8-8923-b9d06601f3b7`）只執行 `MATCH … RETURN`；**未寫入、未啟動 Ollama／LLM、未呼叫 embedding、未重抽、未改題庫、未產 gold、未改論文**。腳本為一次性唯讀腳本（未入庫；全部 Cypher 逐條列於附錄，供檢查）。

## 0. 前置防護紀錄

| 項目 | 結果 |
| --- | --- |
| 其他 session 是否使用同一 Neo4j／Ollama | `ListAgents`（執行前）：僅 `project refactor review sdd`（bg、idle，規劃對話，不碰 Neo4j）在線；其餘 4 個 Remote Control session 皆 offline。**無其他 session 使用該 Neo4j／Ollama**。（本機另有 Windows `ollama` 行程在跑，非本 session 啟動，本次**未連線、未使用**。） |
| 容器 | 既有 `kg2-neo4j`（Up、healthy；`17990→7687`），**未啟動／改動任何容器或設定** |
| 連線方式 | `neo4j` Python driver，`session(default_access_mode="READ")`；腳本內建關鍵字檢查，Cypher 含 `CREATE／MERGE／SET／DELETE／DETACH／DROP／REMOVE／LOAD／FOREACH／INDEX／CONSTRAINT` 即中止，且每條必須以 `MATCH／UNWIND／CALL db.` 開頭（無一觸發） |
| 資料量與紀載相符（停止條件 2） | KG#4 Fact **16,826**＝`frozen_manifest.json` `kg_fact_total`（兩份皆 16,826）；Entity **12,296**＝`20260923_rebased` manifest `kg_entity_total`（`20260920_frozen` 為 12,290，差異屬 rebase 後的紀錄，非本次造成）。**相符，未觸發停止** |

### 執行前後總數（須相同）

| 時點 | 資料庫總節點數 | 資料庫總關係數 | KG#4 Fact | KG#4 Entity |
| --- | --- | --- | --- | --- |
| 執行前 | 57,451 | 137,873 | 16,826 | 12,296 |
| 執行後 | 57,451 | 137,873 | 16,826 | 12,296 |

**結果：完全相同。**

## 1. 資料事實（皆為〔事實〕；Cypher 見附錄 A，標題後括號為編號）

### 1.1 KG#4 全部 Fact 的 `rel_type` 分布（Q3）

- 總計 16,826 筆；**`RELATED_TO` 14,994 筆（89.1%）**；其餘 27 種型別合計 1,832 筆。前幾名：`HAS_PREREQUISITE` 413、`USED_FOR` 388、`MOTIVATED_BY_GOAL` 205、`RECEIVES_ACTION` 193、`OBSTRUCTED_BY` 142、`CAPABLE_OF` 123、`HAS_PROPERTY` 69、`CAUSES` 58。

- 全部 Fact 的 distinct `verb` 9,209 種、distinct `rel_type` 28 種（`verb` 保留 LLM 原始措辭，`rel_type` 是受控型別）。

- `RELATED_TO` Fact 的 `verb` 前 12 名：「屬於」1102、「（空）」547、「包括」106、「不在此限」96、「應包括」94、「指」89、「由」85、「包含」84、「準用」74、「辦理」66、「依」64、「為」59。

### 1.2 各來源文件的 Fact `rel_type` 分布（Q4 系列；`source_doc_id`＝文件資料夾名的 UUID5）

| 文件 | Fact 總數 | `RELATED_TO` | 占比 | 其他型別（前 4） |
| --- | --- | --- | --- | --- |
| N0060079 重返職場補助辦法（AGGR5） | 123 | 117 | 95.1% | `HAS_PREREQUISITE` 4、`MOTIVATED_BY_GOAL` 2 |
| N0090058 失業中高齡者就業促進辦法（AGGR7 子法） | 279 | 249 | 89.2% | `CAPABLE_OF` 6、`RECEIVES_ACTION` 5、`USED_FOR` 5、`HAS_PREREQUISITE` 5 |
| N0090055 中高齡者及高齡者就業促進法（AGGR7 母法） | 191 | 165 | 86.4% | `MOTIVATED_BY_GOAL` 12、`CAPABLE_OF` 5、`RECEIVES_ACTION` 4、`CAUSES` 2 |
| N0090025 就業促進津貼實施辦法（AGGR9） | 130 | 105 | 80.8% | `HAS_PREREQUISITE` 11、`USED_FOR` 5、`RECEIVES_ACTION` 4、`MOTIVATED_BY_GOAL` 3 |
| N0090001 就業服務法（AGGR9／13 母法） | 476 | 427 | 89.7% | `RECEIVES_ACTION` 9、`HAS_PREREQUISITE` 8、`OBSTRUCTED_BY` 7、`MOTIVATED_BY_GOAL` 7 |
| N0030022 勞工退休金條例年金保險實施辦法（AGGR11） | 322 | 299 | 92.9% | `HAS_PREREQUISITE` 8、`RECEIVES_ACTION` 3、`MOTIVATED_BY_GOAL` 3、`MANNER_OF` 2 |
| N0030020 勞工退休金條例（AGGR11／12 母法） | 325 | 293 | 90.2% | `MOTIVATED_BY_GOAL` 13、`USED_FOR` 6、`HAS_PREREQUISITE` 2、`DEFINED_AS` 2 |
| N0090002 私立就業服務機構許可及管理辦法（AGGR13） | 306 | 263 | 85.9% | `HAS_PREREQUISITE` 26、`MOTIVATED_BY_GOAL` 8、`USED_FOR` 3、`DESIRES` 2 |
| N0060027 職業安全衛生管理辦法（AGGR15） | 578 | 529 | 91.5% | `HAS_PREREQUISITE` 23、`CAPABLE_OF` 7、`HAS_PROPERTY` 6、`RECEIVES_ACTION` 4 |
| N0060001 職業安全衛生法（AGGR15 母法） | 484 | 450 | 93.0% | `CAPABLE_OF` 7、`RECEIVES_ACTION` 6、`CAUSES` 5、`HAS_PREREQUISITE` 3 |
| N0060041 職業災害勞工保護法（AGGR19 舊法） | 166 | 143 | 86.1% | `RECEIVES_ACTION` 5、`DEFINED_AS` 4、`CAPABLE_OF` 4、`PART_OF` 2 |
| N0050031 勞工職業災害保險及保護法（AGGR19 新法） | 621 | 558 | 89.9% | `RECEIVES_ACTION` 19、`HAS_PREREQUISITE` 12、`MOTIVATED_BY_GOAL` 9、`HAS_LAST_SUBEVENT` 8 |

### 1.3 與題目答案直接相關的 Fact（以文件＋`source_svo_chunk_index` 定位）

> `source_svo_chunk_index` 與 `svo_index.json` 的 chunk `index` 同為 1 起算（授權句所在 chunk 1 各回傳 1 筆，與該 chunk 的授權句一致，視為對上）。

**57-AGGR5｜N0060079 chunk 1（授權句所在）**

| subject | `rel_type` | verb | object |
| --- | --- | --- | --- |
| 本辦法 | `RELATED_TO` | 依 | 勞工職業災害保險及保護法第六十九條第二項規定訂定 |

**57-AGGR7 授權句｜N0090058 chunk 1（授權句所在）**

| subject | `rel_type` | verb | object |
| --- | --- | --- | --- |
| 本辦法 | `RELATED_TO` | 依 | 中高齡者及高齡者就業促進法第二十七條規定訂定 |

**57-AGGR9｜N0090025 chunk 1（授權句所在）**

| subject | `rel_type` | verb | object |
| --- | --- | --- | --- |
| 本辦法 | `RELATED_TO` | 依 | 就業服務法第二十三條第二項及第二十四條第四項規定訂定 |

**57-AGGR11｜N0030022 chunk 1（授權句所在）**

| subject | `rel_type` | verb | object |
| --- | --- | --- | --- |
| 本辦法 | `RELATED_TO` | 依 | 勞工退休金條例第三十五條第三項及第三十七條規定 |

**57-AGGR13｜N0090002 chunk 1（授權句所在）**

| subject | `rel_type` | verb | object |
| --- | --- | --- | --- |
| 本辦法 | `RELATED_TO` | 依 | 就業服務法第三十四條第三項及第四十條第二項規定訂定 |

**57-AGGR15｜N0060027 chunk 1（授權句所在）**

| subject | `rel_type` | verb | object |
| --- | --- | --- | --- |
| 本辦法 | `RELATED_TO` | 依 | 職業安全衛生法第二十三條第五項規定訂定 |

**57-AGGR7｜母法 N0090055 chunk 24（補助基礎）**

| subject | `rel_type` | verb | object |
| --- | --- | --- | --- |
| 雇主 | `DESIRES` | 依僱用人力需求 | 得自行或委託辦理所僱用之中高齡者及高齡者在職訓練 |
| 中央主管機關 | `MOTIVATED_BY_GOAL` | 為提升 | 中高齡者及高齡者工作技能 |
| 中央主管機關 | `MOTIVATED_BY_GOAL` | 為促進 | 就業 |
| 中央主管機關 | `RELATED_TO` | 應辦理 | 職業訓練 |
| 中央主管機關 | `RELATED_TO` | 依前項規定 | 訓練費用補助 |
| 雇主 | `RELATED_TO` | 依前項規定 | 規劃辦理職業訓練 |

**57-AGGR7｜母法 N0090055 chunk 27（授權子法）**

| subject | `rel_type` | verb | object |
| --- | --- | --- | --- |
| 利息補貼 | `RELATED_TO` | 由中央主管機關定之 | （空） |
| 津貼 | `RELATED_TO` | 由中央主管機關定之 | （空） |
| 獎助 | `RELATED_TO` | 由中央主管機關定之 | （空） |
| 補助 | `RELATED_TO` | 由中央主管機關定之 | （空） |

**57-AGGR7｜子法 N0090058 chunk 6（具體門檻）**

| subject | `rel_type` | verb | object |
| --- | --- | --- | --- |
| 最低開班人數 | `RELATED_TO` | （雇主依本法第二十四條第二項規定辦理訓練並申請訓練費用補助時）應達 | 五人 |
| 訓練時數 | `RELATED_TO` | （雇主依本法第二十四條第二項規定辦理訓練並申請訓練費用補助時）不得低於 | 八十小時 |
| 雇主 | `RELATED_TO` | 依本法第二十四條第二項規定辦理 | 訓練 |

**57-AGGR19｜含「準用」的 Fact（舊法 N0060041）**

| chunk | subject | `rel_type` | verb | object |
| --- | --- | --- | --- | --- |
| 12 | 職業疾病認定委員會 | `RELATED_TO` | 之組織、認定程序及會議 | 準用第十四條至第十六條之規定 |
| 26 | 職業災害勞工 | `RELATED_TO` | 依第二十四條第一款規定終止勞動契約時 | 準用勞動基準法規定預告雇主 |

**57-AGGR19｜含「準用」的 Fact（新法 N0050031；題庫 source_article 為新法 §84、§85 第2項）**

| chunk | subject | `rel_type` | verb | object |
| --- | --- | --- | --- | --- |
| 6 | 勞動基準法規定之技術生 | `RELATED_TO` | 準用第一項規定參加本保險 | 本保險 |
| 6 | 事業單位之養成工 | `RELATED_TO` | 準用第一項規定參加本保險 | 本保險 |
| 6 | 見習生及其他與技術生性質相類之人 | `RELATED_TO` | 準用第一項規定參加本保險 | 本保險 |
| 6 | 高級中等學校建教合作實施及建教生權益保障法規定之建教生 | `RELATED_TO` | 準用第一項規定參加本保險 | 本保險 |
| 6 | 其他有提供勞務事實並受有報酬，經中央主管機關公告者 | `RELATED_TO` | 準用第一項規定參加本保險 | 本保險 |
| 9 | 受僱於經中央主管機關公告之第六條第一項規定以外雇主之員工 | `RELATED_TO` | 得準用 | 本法規定參加本保險 |
| 9 | 實際從事勞動之雇主 | `RELATED_TO` | 得準用 | 本法規定參加本保險 |
| 9 | 參加海員總工會或船長公會為會員之外僱船員 | `RELATED_TO` | 得準用 | 本法規定參加本保險 |
| 13 | 依第九條規定參加本保險者 | `RELATED_TO` | 其保險效力之開始或停止 | 準用第二項、第三項第一款及前項規定 |
| 22 | 投保單位 | `RELATED_TO` | 應準用前條第一項規定，代為加收滯納金彙繳保險人 | （空） |
| 30 | 受益人, 請領人, 法定繼承人 | `RELATED_TO` | 前二項給付返還規定，於其準用之 | 給付返還規定 |
| 84 | 雇主 | `RELATED_TO` | 預告終止勞動契約時 | 準用勞動基準法規定預告勞工 |
| 85 | 職業災害勞工 | `RELATED_TO` | 終止勞動契約時 | 準用勞動基準法規定預告雇主 |
| 95 | 雇主 | `RELATED_TO` | 違反第八十四條第二項規定，未準用勞動基準法規定預告勞工終止勞動契約。 | 勞工 |

### 1.4 既有資料：問句經 `resolve_query_relation_type` 實際被解析成什麼型別（**未重跑，讀既有紀錄**）

- 檔案：`data/eval/candidate_runs/kg_source_recall_probe_v2/retrieval_rerun.json`（已入庫，commit `84c0209`，2026-09-30 的 U3 探測；該腳本第 86 行以 `resolve_query_relation_type(question, emb, llm_provider=None, cfg=cfg)` 解析，**不經 LLM 仲裁**，再依 `chat()` 同樣的 `_filter_triples_by_relation_type` 後篩）。**本次未呼叫任何 embedding／LLM，只讀此 JSON。**
- 42 題（凍結 42 題）的解析結果：**全部為 `None`**（`Counter({'None': 42})`）。`filter_triples_by_relation_type(triples, None)` 原樣回傳、**不篩選**（`services/retrieval/scope.py:160-161`）。

| 題號 | 解析出的 `rel_type` | 取回 Fact | 取回 BFS 三元組 | 三元組的 `rel_type` 分布 |
| --- | --- | --- | --- | --- |
| 57-AGGR5 | None | 20 | 45 | `RELATED_TO` 40、`USED_FOR` 2、`CAPABLE_OF` 1、`RECEIVES_ACTION` 1、`PART_OF` 1 |
| 57-AGGR7 | None | 20 | 45 | `RELATED_TO` 33、`USED_FOR` 5、`HAS_PREREQUISITE` 5、`CAUSES` 1、`RECEIVES_ACTION` 1 |
| 57-AGGR9 | None | 20 | 17 | `RELATED_TO` 15、`MOTIVATED_BY_GOAL` 2 |
| 57-AGGR11 | None | 20 | 31 | `RELATED_TO` 28、`RECEIVES_ACTION` 1、`CAUSES` 1、`AT_LOCATION` 1 |
| 57-AGGR13 | None | 20 | 38 | `RELATED_TO` 29、`MOTIVATED_BY_GOAL` 4、`HAS_PREREQUISITE` 3、`DEFINED_AS` 1、`HAS_LAST_SUBEVENT` 1 |
| 57-AGGR15 | None | 4 | 7 | `RELATED_TO` 7 |
| 57-AGGR19 | None | 20 | 38 | `RELATED_TO` 29、`HAS_LAST_SUBEVENT` 5、`DEFINED_AS` 1、`CAPABLE_OF` 1、`OBSTRUCTED_BY` 1、`MOTIVATED_BY_GOAL` 1 |

## 2. 逐題結論

**判斷的兩個層次**：(i) **圖內容**——若改用開放式臂（忽略 `rel_type`、保留原始 `verb`），這題答案所需的邊本身會不會不同？(ii) **檢索過程**——`rel_type` 後篩（`routers/agent.py:1366-1369`）會不會把這條邊濾掉？

| 題號 | (i) 圖內容會不會變 | (ii) 後篩是否影響 | 結論 |
| --- | --- | --- | --- |
| 57-AGGR5 | 〔事實〕授權邊 `本辦法 -依→ 勞工職業災害保險及保護法第六十九條第二項規定訂定` 已是 `RELATED_TO`＋原始 verb「依」；開放式臂的 (subject, verb, object) **完全相同**，只差型別標籤 | 〔事實〕既有紀錄解析為 `None`＝不篩；〔推論〕若生產環境的 LLM 仲裁把它解析成非 `None`、非 `RELATED_TO` 的型別，BFS 分支會丟掉這條邊（開放式臂不會）；**未跑 LLM，無資料** | **答案路徑不變（在無 LLM 仲裁的解析下）；開放式臂至多不劣於現行** |
| 57-AGGR7 | 〔事實〕子法授權邊（chunk 1）、門檻邊（chunk 6：最低開班人數／訓練時數）、母法 chunk 24 的補助邊與 chunk 27 的「由中央主管機關定之」邊**全是 `RELATED_TO`＋原始 verb**；母法 chunk 27 的 4 筆 object 皆為空 | 同上 | **同上** |
| 57-AGGR9 | 〔事實〕授權邊（chunk 1）為 `RELATED_TO`＋verb「依」，object 含母法兩個條項 | 同上 | **同上** |
| 57-AGGR11 | 〔事實〕同上（object：`勞工退休金條例第三十五條第三項及第三十七條規定`，未帶「訂定」二字，與原文句尾略異；原文為逐字比對見報告183） | 同上 | **同上** |
| 57-AGGR13 | 〔事實〕同上 | 同上 | **同上** |
| 57-AGGR15 | 〔事實〕同上 | 同上 | **同上** |
| 57-AGGR19 | 〔事實〕舊法 chunk 26「職業災害勞工 依第二十四條第一款規定終止勞動契約時 → 準用勞動基準法規定預告雇主」與新法 chunk 84／85 對應的「準用…預告」邊皆為 `RELATED_TO`＋原始 verb | 同上；另此題涉及新舊法歸屬，評分器不檢查歸屬（報告179 §5），與詞彙無關 | **同上** |

**彙總（只陳述，不建議）**：

1. **〔事實〕**：7 題答案直接相關的邊（授權句 6 筆、AGGR7 的門檻邊與母法補助／授權邊、AGGR19 的準用邊）**全部是 `RELATED_TO`**（母法 chunk 24 另有 `DESIRES`、`MOTIVATED_BY_GOAL` 邊，屬同 chunk 的其他事實，不是補助或授權邊）；KG#4 全部 Fact 中 `RELATED_TO` 占 **89.1%**，所以「現行受控詞彙」對這類事實**本來就等於「落到 `RELATED_TO`＋保留原始 verb」**，與開放式臂的圖內容幾乎相同。
2. **〔事實〕**：既有紀錄（凍結 42 題、不經 LLM 仲裁）顯示這 7 題的問句解析 `rel_type` 皆為 `None`，後篩不作用。
3. **〔推論〕**：因此對這 7 題，受控 vs 開放式在**圖內容**與（無仲裁時的）**檢索過程**上都**不會產生差異**；RQ4a 若以這 7 題當區分題，預期**無法區分**（效應≈0）。僅剩一個未驗證的缺口：生產環境若啟用 LLM 仲裁，問句可能被解析為非 `None` 型別而改變 BFS 後篩——需要 LLM，依停止條件未做，**無資料**。
4. **對 RQ4a 的含意（只陳述）**：現行 KG 的受控詞彙在法規語料上有 89% 退化為 `RELATED_TO`；RQ4a 能區分的對象更可能是**其餘 11%（有型別的邊）所涉題目**，而不是這 7 題（報告179 §2.2 的字面推論池）。哪些題屬於那 11% 的邊，**本檢查未盤點**。

## 3. 限制與誠實聲明

- 本檢查**沒有**執行 `resolve_query_relation_type` 的 LLM 仲裁分支（需 LLM），結論 (ii) 僅涵蓋「無 LLM 仲裁」的解析；引用的既有紀錄是 U3 當時的結果，**不是本次重跑**。
- 「答案直接相關的邊」以文件＋chunk 定位（授權句所在 chunk、母法 chunk 24／27、子法 chunk 6、含「準用」的 Fact），**不等於**題目 gold 的全部事實；題目還依賴語意 Fact 檢索排名（與 `rel_type` 無關）。
- AGGR19 的新法邊以 chunk 84／85 對應題庫標註的 §84／§85，**chunk 與條號的對應我只核對到 chunk 內容含「準用」，未逐條核對條號**。
- 資料量與紀載相符；執行前後總數相同。

## 附錄 A：全部 Cypher（唯讀；參數 `$k`＝KG#4 的 `kg_id`、`$d`＝文件資料夾名的 UUID5、`$ci`＝chunk 索引）

| # | 用途 | Cypher | 回傳行數 |
| --- | --- | --- | --- |
| Q1 | before:總節點數 | `MATCH (n) RETURN count(n) AS nodes` | 1 |
| Q2 | before:總關係數 | `MATCH ()-[r]->() RETURN count(r) AS rels` | 1 |
| Q3 | before:KG#4 Fact 數 | `MATCH (f:Fact {kg_id: $k}) RETURN count(f) AS facts` | 1 |
| Q4 | before:KG#4 Entity 數 | `MATCH (e:Entity {kg_id: $k}) RETURN count(e) AS entities` | 1 |
| Q5 | KG#4 全 Fact 的 rel_type 直方圖 | `MATCH (f:Fact {kg_id: $k}) RETURN f.rel_type AS rel_type, count(*) AS c ORDER BY c DESC` | 28 |
| Q6 | N0060079 的 Fact rel_type 直方圖 | `MATCH (f:Fact {kg_id: $k, source_doc_id: $d}) RETURN f.rel_type AS rel_type, count(*) AS c ORDER BY c DESC` | 3 |
| Q7 | N0090058 的 Fact rel_type 直方圖 | `MATCH (f:Fact {kg_id: $k, source_doc_id: $d}) RETURN f.rel_type AS rel_type, count(*) AS c ORDER BY c DESC` | 9 |
| Q8 | N0090055 的 Fact rel_type 直方圖 | `MATCH (f:Fact {kg_id: $k, source_doc_id: $d}) RETURN f.rel_type AS rel_type, count(*) AS c ORDER BY c DESC` | 8 |
| Q9 | N0090025 的 Fact rel_type 直方圖 | `MATCH (f:Fact {kg_id: $k, source_doc_id: $d}) RETURN f.rel_type AS rel_type, count(*) AS c ORDER BY c DESC` | 7 |
| Q10 | N0090001 的 Fact rel_type 直方圖 | `MATCH (f:Fact {kg_id: $k, source_doc_id: $d}) RETURN f.rel_type AS rel_type, count(*) AS c ORDER BY c DESC` | 11 |
| Q11 | N0030022 的 Fact rel_type 直方圖 | `MATCH (f:Fact {kg_id: $k, source_doc_id: $d}) RETURN f.rel_type AS rel_type, count(*) AS c ORDER BY c DESC` | 11 |
| Q12 | N0030020 的 Fact rel_type 直方圖 | `MATCH (f:Fact {kg_id: $k, source_doc_id: $d}) RETURN f.rel_type AS rel_type, count(*) AS c ORDER BY c DESC` | 12 |
| Q13 | N0090002 的 Fact rel_type 直方圖 | `MATCH (f:Fact {kg_id: $k, source_doc_id: $d}) RETURN f.rel_type AS rel_type, count(*) AS c ORDER BY c DESC` | 9 |
| Q14 | N0060027 的 Fact rel_type 直方圖 | `MATCH (f:Fact {kg_id: $k, source_doc_id: $d}) RETURN f.rel_type AS rel_type, count(*) AS c ORDER BY c DESC` | 9 |
| Q15 | N0060001 的 Fact rel_type 直方圖 | `MATCH (f:Fact {kg_id: $k, source_doc_id: $d}) RETURN f.rel_type AS rel_type, count(*) AS c ORDER BY c DESC` | 12 |
| Q16 | N0060041 的 Fact rel_type 直方圖 | `MATCH (f:Fact {kg_id: $k, source_doc_id: $d}) RETURN f.rel_type AS rel_type, count(*) AS c ORDER BY c DESC` | 12 |
| Q17 | N0050031 的 Fact rel_type 直方圖 | `MATCH (f:Fact {kg_id: $k, source_doc_id: $d}) RETURN f.rel_type AS rel_type, count(*) AS c ORDER BY c DESC` | 13 |
| Q18 | N0060079 chunk 1 的 Fact（授權句所在 chunk） | `MATCH (f:Fact {kg_id: $k, source_doc_id: $d, source_svo_chunk_index: $ci}) RETURN f.subject AS subject, f.rel_type AS rel_type, f.verb AS verb, f.object AS object ORDER BY f.rel_type, f.subject LIMIT 40` | 1 |
| Q19 | N0090058 chunk 1 的 Fact（授權句所在 chunk） | `MATCH (f:Fact {kg_id: $k, source_doc_id: $d, source_svo_chunk_index: $ci}) RETURN f.subject AS subject, f.rel_type AS rel_type, f.verb AS verb, f.object AS object ORDER BY f.rel_type, f.subject LIMIT 40` | 1 |
| Q20 | N0090025 chunk 1 的 Fact（授權句所在 chunk） | `MATCH (f:Fact {kg_id: $k, source_doc_id: $d, source_svo_chunk_index: $ci}) RETURN f.subject AS subject, f.rel_type AS rel_type, f.verb AS verb, f.object AS object ORDER BY f.rel_type, f.subject LIMIT 40` | 1 |
| Q21 | N0030022 chunk 1 的 Fact（授權句所在 chunk） | `MATCH (f:Fact {kg_id: $k, source_doc_id: $d, source_svo_chunk_index: $ci}) RETURN f.subject AS subject, f.rel_type AS rel_type, f.verb AS verb, f.object AS object ORDER BY f.rel_type, f.subject LIMIT 40` | 1 |
| Q22 | N0090002 chunk 1 的 Fact（授權句所在 chunk） | `MATCH (f:Fact {kg_id: $k, source_doc_id: $d, source_svo_chunk_index: $ci}) RETURN f.subject AS subject, f.rel_type AS rel_type, f.verb AS verb, f.object AS object ORDER BY f.rel_type, f.subject LIMIT 40` | 1 |
| Q23 | N0060027 chunk 1 的 Fact（授權句所在 chunk） | `MATCH (f:Fact {kg_id: $k, source_doc_id: $d, source_svo_chunk_index: $ci}) RETURN f.subject AS subject, f.rel_type AS rel_type, f.verb AS verb, f.object AS object ORDER BY f.rel_type, f.subject LIMIT 40` | 1 |
| Q24 | N0090055 chunk 24 的 Fact | `MATCH (f:Fact {kg_id: $k, source_doc_id: $d, source_svo_chunk_index: $ci}) RETURN f.subject AS subject, f.rel_type AS rel_type, f.verb AS verb, f.object AS object ORDER BY f.rel_type, f.subject LIMIT 40` | 6 |
| Q25 | N0090055 chunk 27 的 Fact | `MATCH (f:Fact {kg_id: $k, source_doc_id: $d, source_svo_chunk_index: $ci}) RETURN f.subject AS subject, f.rel_type AS rel_type, f.verb AS verb, f.object AS object ORDER BY f.rel_type, f.subject LIMIT 40` | 4 |
| Q26 | N0090058 chunk 6 的 Fact | `MATCH (f:Fact {kg_id: $k, source_doc_id: $d, source_svo_chunk_index: $ci}) RETURN f.subject AS subject, f.rel_type AS rel_type, f.verb AS verb, f.object AS object ORDER BY f.rel_type, f.subject LIMIT 40` | 3 |
| Q27 | N0060041 含『準用』的 Fact | `MATCH (f:Fact {kg_id: $k, source_doc_id: $d}) WHERE f.verb CONTAINS '準用' OR f.object CONTAINS '準用' OR f.subject CONTAINS '準用' RETURN f.source_svo_chunk_index AS chunk, f.subject AS subject, f.rel_type AS rel_type, f.verb AS verb, f.object AS object ORDER BY chunk LIMIT 40` | 2 |
| Q28 | N0050031 含『準用』的 Fact | `MATCH (f:Fact {kg_id: $k, source_doc_id: $d}) WHERE f.verb CONTAINS '準用' OR f.object CONTAINS '準用' OR f.subject CONTAINS '準用' RETURN f.source_svo_chunk_index AS chunk, f.subject AS subject, f.rel_type AS rel_type, f.verb AS verb, f.object AS object ORDER BY chunk LIMIT 40` | 14 |
| Q29 | KG#4 RELATED_TO Fact 的 verb 前 15 名 | `MATCH (f:Fact {kg_id: $k, rel_type: 'RELATED_TO'}) RETURN f.verb AS verb, count(*) AS c ORDER BY c DESC LIMIT 15` | 15 |
| Q30 | KG#4 distinct verb／distinct rel_type 數 | `MATCH (f:Fact {kg_id: $k}) RETURN count(DISTINCT f.verb) AS distinct_verbs, count(DISTINCT f.rel_type) AS distinct_rel_types` | 1 |
| Q31 | after:總節點數 | `MATCH (n) RETURN count(n) AS nodes` | 1 |
| Q32 | after:總關係數 | `MATCH ()-[r]->() RETURN count(r) AS rels` | 1 |
| Q33 | after:KG#4 Fact 數 | `MATCH (f:Fact {kg_id: $k}) RETURN count(f) AS facts` | 1 |
| Q34 | after:KG#4 Entity 數 | `MATCH (e:Entity {kg_id: $k}) RETURN count(e) AS entities` | 1 |

**唯讀檢查**：以上每條皆為 `MATCH … RETURN`／`WHERE`／`ORDER BY`／`LIMIT`／`count()`／`DISTINCT`，不含 `CREATE／MERGE／SET／DELETE／DROP／CALL … WRITE`；session 為 `default_access_mode=READ`。
