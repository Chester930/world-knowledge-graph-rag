# 報告190：RQ4a 區分題盤點——題庫 65 題的答案路徑 `rel_type` 分類（唯讀 Neo4j；報告189 D1）

> **日期**：2026-10-01
> **性質**：只讀。對 KG#4（`236903cf-055a-40a8-8923-b9d06601f3b7`）只執行 `MATCH … RETURN`；**未寫入、未啟動 Ollama／LLM、未呼叫 embedding、未重抽、未改題庫、未產 gold、未判斷法規正確性、未改論文**。

## 0. 前置防護紀錄

| 項目 | 結果 |
| --- | --- |
| 其他 session 是否使用同一 Neo4j／Ollama | 執行前 `ListAgents`：僅 `project refactor review sdd`（bg、idle，規劃對話）在線，其餘 4 個 Remote Control session 皆 offline；**無他人使用**。（本機有 Windows `ollama` 行程非本 session 啟動，**未連線、未使用**。） |
| 容器 | 既有 `kg2-neo4j`（Up、healthy，未動）；KG#4 為唯一副本，**未 wipe／清空／重建** |
| 連線方式 | `neo4j` driver `session(default_access_mode="READ")`；腳本沿用報告187 的寫入關鍵字攔截（`CREATE／MERGE／SET／DELETE／DETACH／DROP／REMOVE／LOAD／FOREACH／INDEX／CONSTRAINT` 即中止；每條須以 `MATCH／UNWIND／CALL db.` 開頭），無觸發；腳本另在執行前**斷言**資料量等於 57,451／137,873／16,826／12,296，不符即停 |
| LLM／embedding | **無任何呼叫** |

| 時點 | 總節點 | 總關係 | KG#4 Fact | KG#4 Entity |
| --- | --- | --- | --- | --- |
| 執行前 | 57,451 | 137,873 | 16,826 | 12,296 |
| 執行後 | 57,451 | 137,873 | 16,826 | 12,296 |

**結果：完全相同，且等於預期值。**

## 1. 方法與限制（先讀）

**定位法**（沿用報告187 的「文件＋chunk」法並加強到 gold 句層級）：
1. 取題庫每題 `atomic_gold_facts[]` 的 `source_law`（＝KG 文件資料夾名）與 `exact_span`；在該資料夾 `svo_index.json` 各 chunk 的 `original_sentences`（去空白後）中找包含整句 `exact_span` 的 chunk（SVO chunk 為滑動視窗、會重疊，可能多個）。
2. 查這些 chunk 內的 Fact（`source_doc_id`＝資料夾名的 UUID5、`source_svo_chunk_index`＝chunk 索引，已於報告187 驗證與 chunk `index` 同為 1 起算）。
3. **「與 gold 事實直接相關的邊」判定（嚴格版，作為分類依據）**：Fact 的 `subject`（去空白，≥2 字）出現在 `exact_span` 內，**且**（`object` 為空，或 `object`（≥2 字）也出現在 `exact_span` 內）。
4. 分類：該題所有已定位 gold 句的「對上 Fact」中，**任一 `rel_type` ≠ `RELATED_TO`** → 「含非 `RELATED_TO`」；有對上但全是 `RELATED_TO` → 「全部 `RELATED_TO`」；其餘 → 「無法定位」（含：題庫無 `atomic_gold_facts`、gold 句所屬資料夾不存在或原文找不到、chunk 已定位但沒有 Fact 對得上）。
**限制（粒度誤差）**：(a) 嚴格版要求 subject／object 字面落在 gold 句內；Fact 的 object 常被正規化或改寫，對不上就被丟掉，所以嚴格版會**低估**「含非 `RELATED_TO`」（例：`57-AGGR7`、`57-AGGR11`、`57-AGGR19` 嚴格版只對上 `RELATED_TO`，但放寬版在同 chunk 找到非 `RELATED_TO` 邊）。(b) chunk 層級（該 chunk 內任何 Fact）則會**高估**。因此本報告給「嚴格／放寬／chunk 層級」三個數字當作**區間**，不給單一點。(c) 「題目答案路徑」＝gold 句所在 chunk 內的事實，**不含**需要跨文件拼接時的橋接事實。(d) gold 取自題庫現有 `atomic_gold_facts`，**未判斷其法規正確性**。

## 2. 彙總（可由 §3 逐題表重算）

| 分類（嚴格版） | 題庫 65 題 | 凍結 42 題內 |
| --- | --- | --- |
| 含非 RELATED_TO | 9 | 7 |
| 全部 RELATED_TO | 25 | 24 |
| 無法定位 | 31 | 11 |
| 合計 | 65 | 42 |

- **無法定位占比**：題庫 31/65＝47.7%（**未超過報告189 的 50% 停止門檻，但接近**）；凍結 42 題內 11/42＝26.2%。無法定位的原因分解見 §3 表。
- **「含非 `RELATED_TO`」題數區間（凍結 42 題內）**：嚴格版 **7** 題；放寬版（subject 或 object 任一落在 gold 句內）**10** 題；chunk 層級上界 **17** 題。題庫 65 題：嚴格 9、放寬 12、chunk 層級 20。

- 嚴格版「含非 `RELATED_TO`」題（凍結內）：`18-Q3`（RECEIVES_ACTION 1）、`57-AGGR4`（HAS_PREREQUISITE 1）、`57-AGGR6`（RECEIVES_ACTION 2）、`57-AGGR8`（CAPABLE_OF 3）、`57-AGGR10`（USED_FOR 2、RECEIVES_ACTION 1）、`57-AGGR13`（HAS_PREREQUISITE 1）、`57-AGGR18`（ANTONYM 1）；題庫內未進凍結：`57-ALIAS2`、`57-DIST3`。

## 3. 逐題結果（65 題）

> 「frozen」＝在凍結 42 題內（manifest `eligible_ids`）；「verified」＝題庫 `verification_status`；「定位依據」＝文件代碼＋chunk 索引（`svo_index.json` chunk `index`）；「非 RT 邊」＝嚴格版對上的非 `RELATED_TO` Fact（型別 數量）；「chunk 內非 RT」＝gold 句所在 chunk 內所有非 `RELATED_TO` Fact 數（上界，供對照）。

| 題號 | 題型 | frozen | verified | 分類 | 非 RT 邊（嚴格） | chunk 內非 RT／chunk 內 Fact 總數 | 定位依據 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 17-Q1 | Type-A | 是 | verified | 全部 RELATED_TO | — | 0／3 | N0030006 chunk 2 |
| 17-Q2 | Type-A | 是 | verified | 全部 RELATED_TO | — | 0／5 | N0030006 chunk 7 |
| 17-Q3 | Type-B | 否 | unverified | 無法定位 | — | 0／0 | 題庫無 atomic_gold_facts（無 gold 句可定位） |
| 17-Q4 | Type-A | 否 | unverified | 無法定位 | — | 0／0 | 題庫無 atomic_gold_facts（無 gold 句可定位） |
| 17-Q5 | Type-A | 否 | unverified | 無法定位 | — | 0／0 | 題庫無 atomic_gold_facts（無 gold 句可定位） |
| 17-Q6 | Type-B | 是 | verified | 無法定位 | — | 0／8 | D0080015 chunk 2（gold 句所在 chunk 已定位，但 chunk 內沒有 subject＋object 都落在 gold 句內的 Fact） |
| 17-Q7 | Type-B | 否 | unverified | 無法定位 | — | 0／0 | 題庫無 atomic_gold_facts（無 gold 句可定位） |
| 18-Q1 | Type-B | 是 | verified | 全部 RELATED_TO | — | 0／21 | N0030006 chunk 4 |
| 18-Q2 | Type-B | 是 | verified | 無法定位 | — | 4／32 | N0030018 chunk 2（gold 句所在 chunk 已定位，但 chunk 內沒有 subject＋object 都落在 gold 句內的 Fact） |
| 18-Q3 | Type-A | 是 | verified | 含非 RELATED_TO | RECEIVES_ACTION 1 | 4／8 | N0090051 chunk 3 |
| 18-Q4 | Type-B | 是 | verified | 無法定位 | — | 1／4 | F0040034 chunk 3（gold 句所在 chunk 已定位，但 chunk 內沒有 subject＋object 都落在 gold 句內的 Fact） |
| 18-Q5 | Type-B | 是 | verified | 全部 RELATED_TO | — | 0／12 | D0080015 chunk 2；D0080015 chunk 3；D0080015 chunk 4 |
| 18-Q6 | Type-A | 是 | verified | 全部 RELATED_TO | — | 0／15 | N0030006 chunk 7 |
| 18-Q7 | Type-B | 否 | disputed | 無法定位 | — | 0／0 | 題庫無 atomic_gold_facts（無 gold 句可定位） |
| 25-Q1 | Type-A | 否 | unverified | 無法定位 | — | 0／0 | 題庫無 atomic_gold_facts（無 gold 句可定位） |
| 25-Q2 | Type-B | 否 | unverified | 無法定位 | — | 0／0 | 題庫無 atomic_gold_facts（無 gold 句可定位） |
| 25-Q3 | Type-B | 否 | unverified | 無法定位 | — | 0／0 | 題庫無 atomic_gold_facts（無 gold 句可定位） |
| 25-Q4 | Type-B | 否 | unverified | 無法定位 | — | 0／0 | 題庫無 atomic_gold_facts（無 gold 句可定位） |
| 25-Q5 | Type-B | 否 | unverified | 無法定位 | — | 0／0 | 題庫無 atomic_gold_facts（無 gold 句可定位） |
| 25-Q6 | Type-B | 否 | unverified | 無法定位 | — | 0／0 | 題庫無 atomic_gold_facts（無 gold 句可定位） |
| 25-Q7 | Type-B | 否 | unverified | 無法定位 | — | 0／0 | 題庫無 atomic_gold_facts（無 gold 句可定位） |
| 25-Q8 | Type-B | 否 | unverified | 無法定位 | — | 0／0 | 題庫無 atomic_gold_facts（無 gold 句可定位） |
| 26-Q1 | Type-B | 是 | verified | 全部 RELATED_TO | — | 0／12 | N0060029 chunk 4 |
| 26-Q2 | Type-B | 否 | unverified | 無法定位 | — | 0／0 | 題庫無 atomic_gold_facts（無 gold 句可定位） |
| 26-Q3 | Type-C | 否 | unverified | 無法定位 | — | 0／0 | 題庫無 atomic_gold_facts（無 gold 句可定位） |
| 26-Q4 | Type-B | 否 | unverified | 無法定位 | — | 0／0 | 題庫無 atomic_gold_facts（無 gold 句可定位） |
| 26-Q5 | Type-C | 是 | verified | 無法定位 | — | 0／6 | N0050030 chunk 3；N0050030 chunk 2（gold 句所在 chunk 已定位，但 chunk 內沒有 subject＋object 都落在 gold 句內的 Fact） |
| 26-Q6 | Type-B | 否 | unverified | 無法定位 | — | 0／0 | 題庫無 atomic_gold_facts（無 gold 句可定位） |
| 26-Q7 | Type-B | 否 | unverified | 無法定位 | — | 0／0 | 題庫無 atomic_gold_facts（無 gold 句可定位） |
| 26-Q8 | Type-B | 否 | unverified | 無法定位 | — | 0／0 | 題庫無 atomic_gold_facts（無 gold 句可定位） |
| canary-P1 | Type-E | 是 | verified | 無法定位 | — | 0／0 | gold 句所屬文件資料夾不存在或原文找不到 |
| canary-P4 | Type-E | 是 | verified | 無法定位 | — | 0／0 | gold 句所屬文件資料夾不存在或原文找不到 |
| 57-ALIAS1 | Type-A | 否 | verified | 全部 RELATED_TO | — | 0／2 | N0030006 chunk 6 |
| 57-ALIAS2 | Type-A | 否 | verified | 含非 RELATED_TO | RECEIVES_ACTION 2 | 4／8 | N0090051 chunk 3 |
| 57-ALIAS3 | Type-B | 否 | verified | 無法定位 | — | 1／4 | F0040034 chunk 3（gold 句所在 chunk 已定位，但 chunk 內沒有 subject＋object 都落在 gold 句內的 Fact） |
| 57-COREF1 | Type-B | 是 | verified | 全部 RELATED_TO | — | 6／48 | N0030018 chunk 2 |
| 57-COREF2 | Type-A | 是 | verified | 無法定位 | — | 0／4 | N0030006 chunk 10（gold 句所在 chunk 已定位，但 chunk 內沒有 subject＋object 都落在 gold 句內的 Fact） |
| 57-COREF3 | Type-B | 是 | verified | 全部 RELATED_TO | — | 0／10 | N0030006 chunk 7 |
| 57-DIST1 | Type-B | 是 | verified | 無法定位 | — | 0／16 | D0080015 chunk 2；D0080015 chunk 3（gold 句所在 chunk 已定位，但 chunk 內沒有 subject＋object 都落在 gold 句內的 Fact） |
| 57-DIST2 | Type-B | 是 | verified | 無法定位 | — | 0／16 | D0080015 chunk 3；D0080015 chunk 2（gold 句所在 chunk 已定位，但 chunk 內沒有 subject＋object 都落在 gold 句內的 Fact） |
| 57-DIST3 | Type-B | 否 | verified | 含非 RELATED_TO | RECEIVES_ACTION 2 | 2／12 | N0030006 chunk 3 |
| 57-CANARY1 | Type-E | 是 | verified | 全部 RELATED_TO | — | 0／2 | N0030006 chunk 5 |
| 57-CANARY2 | Type-E | 是 | verified | 無法定位 | — | 0／6 | D0080015 chunk 6（gold 句所在 chunk 已定位，但 chunk 內沒有 subject＋object 都落在 gold 句內的 Fact） |
| 57-AGGR1 | Type-C | 是 | verified | 全部 RELATED_TO | — | 0／8 | N0060022 chunk 1；N0060022 chunk 19 |
| 57-AGGR2 | Type-D | 是 | verified | 全部 RELATED_TO | — | 0／41 | N0060022 chunk 1；N0060022 chunk 3；N0060022 chunk 19 |
| 57-CANARY3 | Type-E | 是 | verified | 全部 RELATED_TO | — | 0／8 | N0060012 chunk 1；N0060022 chunk 2 |
| 57-AGGR3 | Type-D | 是 | verified | 全部 RELATED_TO | — | 0／14 | N0030006 chunk 2；N0030006 chunk 4；N0030001 chunk 57 |
| 57-AGGR4 | Type-C | 是 | verified | 含非 RELATED_TO | HAS_PREREQUISITE 1 | 1／25 | N0060041 chunk 29；N0030006 chunk 4；N0030001 chunk 66 |
| 57-CANARY4 | Type-A | 是 | verified | 全部 RELATED_TO | — | 0／5 | N0030006 chunk 7 |
| 57-CANARY5 | Type-C | 是 | verified | 全部 RELATED_TO | — | 2／5 | N0050031 chunk 106；N0050031 chunk 101 |
| 57-AGGR5 | Type-C | 是 | verified | 全部 RELATED_TO | — | 2／6 | N0060079 chunk 1；N0050031 chunk 69；N0060079 chunk 6 |
| 57-AGGR6 | Type-C | 是 | verified | 含非 RELATED_TO | RECEIVES_ACTION 2 | 6／24 | N0060041 chunk 25；N0050031 chunk 86 |
| 57-AGGR7 | Type-C | 是 | verified | 全部 RELATED_TO | — | 3／10 | N0090055 chunk 24；N0090058 chunk 1；N0090058 chunk 6 |
| 57-AGGR8 | Type-D | 是 | verified | 含非 RELATED_TO | CAPABLE_OF 3 | 6／16 | N0090055 chunk 24；N0090055 chunk 25；N0090055 chunk 26；N0090055 chunk 27 |
| 57-AGGR9 | Type-C | 是 | verified | 全部 RELATED_TO | — | 1／26 | N0090025 chunk 1；N0090001 chunk 22；N0090001 chunk 23 |
| 57-AGGR10 | Type-D | 是 | verified | 含非 RELATED_TO | USED_FOR 2、RECEIVES_ACTION 1 | 4／16 | N0090025 chunk 8；N0090025 chunk 12；N0090025 chunk 20 |
| 57-AGGR11 | Type-C | 是 | verified | 全部 RELATED_TO | — | 1／10 | N0030022 chunk 1；N0030020 chunk 37；N0030020 chunk 41 |
| 57-AGGR12 | Type-D | 是 | verified | 全部 RELATED_TO | — | 0／19 | N0030020 chunk 15；N0030020 chunk 40 |
| 57-AGGR13 | Type-C | 是 | verified | 含非 RELATED_TO | HAS_PREREQUISITE 1 | 3／29 | N0090002 chunk 1；N0090001 chunk 34；N0090001 chunk 40 |
| 57-AGGR14 | Type-D | 是 | verified | 全部 RELATED_TO | — | 0／18 | N0090002 chunk 7 |
| 57-AGGR15 | Type-C | 是 | verified | 無法定位 | — | 1／9 | N0060027 chunk 1；N0060001 chunk 27（gold 句所在 chunk 已定位，但 chunk 內沒有 subject＋object 都落在 gold 句內的 Fact） |
| 57-AGGR16 | Type-D | 是 | verified | 全部 RELATED_TO | — | 0／14 | N0060027 chunk 3；N0060027 chunk 4 |
| 57-AGGR17 | Type-D | 是 | verified | 全部 RELATED_TO | — | 0／12 | N0060027 chunk 3 |
| 57-AGGR18 | Type-C | 是 | verified | 含非 RELATED_TO | ANTONYM 1 | 8／36 | N0060041 chunk 23；N0060041 chunk 23,24；N0050031 chunk 84；N0050031 chunk 84,85 |
| 57-AGGR19 | Type-C | 是 | verified | 全部 RELATED_TO | — | 5／17 | N0060041 chunk 26；N0050031 chunk 84；N0050031 chunk 85 |

## 4. 檢定力回答（〔推論〕；公式與假設同報告179 §3：精確 McNemar＝雙尾二項符號檢定，α=0.05；所需不一致對 12／20／49 為檢定力 ≥0.8 時 q=0.9／0.8／0.7 的最少不一致對數）

設 *k*＝凍結 42 題內「答案路徑含非 `RELATED_TO` 邊」的題數（區間：嚴格 **7**、放寬 **10**、chunk 層級上界 **17**）。

| *k*（相關題池） | 池內全部題都不一致時的最大不一致對數 | 顯著所需最少勝數（該 *k* 下） | 檢定力（d=不一致率；q=新臂勝率） |
| --- | --- | --- | --- |
| 7（嚴格） | 7 | 7（7:0；p=0.0156） | d=0.5：q=.9→0.03／q=.8→0.02；d=1.0：q=.9→0.48／q=.8→0.21 |
| 10（放寬） | 10 | 9（p=0.0215） | d=0.5：0.19／0.09；d=1.0：0.74／0.38 |
| 17（chunk 層級上界） | 17 | 13 | d=0.5：0.58／0.29；d=1.0：0.98／0.76 |

**〔推論〕**：
1. 達到檢定力 ≥0.8 需 12（q=.9）／20（q=.8）／49（q=.7）個**不一致對**。*k*=7 與 *k*=10 的池**本身的題數就小於 12**，在任何 d、q 下都不可能達到 0.8（上表 d=1.0 也只有 0.48／0.74）；*k*=17（且為各種高估的上界）要達到 12 對不一致即需 12/17≈71% 的題在兩臂間翻轉，且新臂勝率≥0.9，屬不合理的樂觀情境。
2. 還要再打折：報告187 §2 已顯示（既有紀錄、不經 LLM 仲裁）凍結 42 題的問句解析 `rel_type` 皆為 `None`＝後篩不作用，且開放式臂的圖內容（subject／verb／object）與現行 KG 在這些邊上只差型別標籤；即使這 *k* 題的邊帶非 `RELATED_TO` 型別，**是否真會改變結果仍無證據**。本表給的是「池大小」的上限，不是預期效應。
3. 結論（〔推論〕）：**在現行題庫（凍結 42 題）上，RQ4a 無法達到統計顯著**；若仍要做，只能做描述／質化，或先**補題**（補到相關池 ≥30–40 題，且需先有「型別邊確實改變答案路徑」的證據）。

## 5. 限制與誠實聲明

- 分類是**題庫 gold 句層級的 chunk 定位＋字面匹配**，不是對實際檢索結果的重放；`rel_type` 對檢索的真正影響需要重放 `chat()`（需 embedding／LLM，本階段不做）。
- 無法定位 31 題中，**19 題是題庫沒有 `atomic_gold_facts`**（均為 unverified，無 gold 句可供定位；其中沒有一題在凍結 42 題內）、2 題是拒答金絲雀（無來源文件），其餘為「chunk 已定位但沒有 Fact 對得上」。這些是定位法的限制，不代表它們的邊不是 `RELATED_TO`。
- 嚴格版對 object 被正規化的 Fact 會漏判（見 §1 限制 a），已以放寬版與 chunk 層級給出區間。
- 執行前後資料量相同，無寫入。

## 附錄 A：Cypher（全部唯讀；腳本內建關鍵字攔截，無觸發）

| # | Cypher | 執行次數 | 回傳行數合計 |
| --- | --- | --- | --- |
| Q1 | `MATCH (n) RETURN count(n) AS v` | 2 | 2 |
| Q2 | `MATCH ()-[r]->() RETURN count(r) AS v` | 2 | 2 |
| Q3 | `MATCH (f:Fact {kg_id: $k}) RETURN count(f) AS v` | 2 | 2 |
| Q4 | `MATCH (e:Entity {kg_id: $k}) RETURN count(e) AS v` | 2 | 2 |
| Q5 | `【逐 chunk 模板】MATCH (f:Fact {kg_id: $k, source_doc_id: $d, source_svo_chunk_index: $ci}) RETURN f.subject AS subject, f.rel_type AS rel_type, f.verb AS verb, f.object AS object` | 62 | 356 |

**唯讀檢查**：全部為 `MATCH … RETURN`／`count()`；參數 `$k`＝KG#4 的 `kg_id`、`$d`＝文件資料夾名的 UUID5、`$ci`＝chunk 索引。前 4 條在執行前後各跑一次（執行次數 2）。
