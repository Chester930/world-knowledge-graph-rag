# 報告242：下一階段任務規劃——P4「寫入端風險驗證」（W1 新建、W4 簡繁合併、W5 改邊型別），在臨時 Neo4j 上以真實行為驗證（交 Codex）

> **日期**：2026-10-02
> **性質**：階段任務規劃。分工：**規劃對話（Claude）決定與獨立驗證、Codex 執行、規劃對話只記錄**。**本文件只由規劃對話修改（§10 執行紀錄）。**
> **依據**：使用者「同意建議 繼續」＝採用規劃對話在報告241 驗證後的建議：往**寫入端**做設計與小型驗證，仍只在臨時容器、不碰 KG#4。
> **背景**：[報告234](234_關係狀態機落地設計說明_Fact層儲存方案.md) §3 把 W4（簡繁合併）、W5（改邊型別）標為〔未驗證〕；[報告241](241_P3拋棄式Neo4j驗證Fact層狀態設計風險執行紀錄.md) 已驗證讀取端五個風險並建立安全閘門腳本。
> **基準**：全量 pytest **1877 passed／0 failed**；HEAD ≥ `60e2347`。
> **邊界（與報告240 相同，缺一不可）**：**絕不連 KG#4／`kg2-neo4j`（17990）**；只用臨時容器 `kg2-throwaway-neo4j`（埠 27474／27687，`neo4j:5.26-enterprise`，3 GB，無 volume／mount，不 pull）；**不修改任何 production 檔**（所有「提案」行為只寫在驗證腳本內）；不啟動 Ollama／LLM、不連外網；不改論文與題庫；報告236／237／239／241 原文不改。

---

## 1. 規劃對話讀碼後的現況與「預測」（先寫下，避免事後偏見；Codex 的結果與預測不符時**如實回報，不要硬湊**）

〔事實，讀碼〕
- `backfill_traditionalize_entity_names`（`services/svo_service.py:2071–2197`）對實體**純改名**時只 `SET e.name`；**撞名**時用「`-[r]->(x)`／`(x)-[r]->`」兩個**泛用**樣式（所有關係型別）把邊搬到繁體節點，最後 `DETACH DELETE` 簡體節點。Fact 節點本身不在此函式內被處理。
- 全檔 `SET f.` 只出現在 `fact_text`／`fact_embedding`（`:1898`、`:1978`）；**沒有任何程式在實體改名／合併後更新 Fact 的扁平屬性 `subject`／`object`／`rel_type`**。
- `backfill_related_to_edges`（`:2237–2329`）改邊型別＝刪舊邊、建新型別邊並複製 `citations_json`／`confidence`；**不更新 Fact 的 `rel_type`**。
- `split_fact_lines`（`services/context/fact_lines.py`）與 `vector_search_facts` 的去重鍵都是 `(subject, rel_type, object)`，Fact 側取自**扁平屬性**，BFS 側取自邊的型別與端點名稱。

〔預測，**未驗證**〕
- **H1**：實體改名或簡繁合併後，Fact 的 `HAS_SUBJECT`／`HAS_OBJECT` 邊仍連到（改名後或繁體的）實體節點、Fact 節點與其自訂屬性（含 `lifecycle_state`／`lifecycle_events_json`）**存活**；但 Fact 的扁平 `subject`／`object` 仍是**舊名稱**（過時）。
- **H2**：因此同一個實體對上的兩個 Fact（一個用舊簡體名、一個用繁體名）去重鍵不同，`vector_search_facts` 的去重**不會**把它們視為同一事實。
- **H3**：`backfill_related_to_edges` 改型別後，Fact 的 `rel_type` 仍是 `RELATED_TO`（過時）。
- **H4**：同一事實在 BFS 側（新型別）與 Fact 側（`RELATED_TO`）的 `split_fact_lines` 去重鍵不同，兩條文字行**都會保留**（跨層重複）。
- **H5**：以 `HAS_SUBJECT`／`HAS_OBJECT` 反查實體名稱、再回寫 Fact 扁平屬性的「同步」Cypher（只寫在驗證腳本內）能修復 H1／H3 的過時。
- **H6（W1）**：在 `CREATE` Fact 時額外帶入 `lifecycle_state`／`lifecycle_events_json` 兩個屬性，不影響 `vector_search_facts`、`revoke_chunk_facts` 與 `backfill_fact_text_embeddings` 等既有函式（額外屬性被忽略或保留）。

## 2. 使用者必須明確確認的事項（Codex 開工前**必須**取得；未確認不得執行任何 docker 指令）

與報告240 §2 相同的三項（本任務是**另一次**臨時容器執行，需重新確認）：①允許對名為 `kg2-throwaway-neo4j` 的臨時容器執行 `docker run`／`stop`／`rm`（參數固定，見報告240 §4）；②同意接受企業版授權旗標（同現有容器）；③確認目前沒有其他 session 在使用這台機器的 Docker／Neo4j／Ollama。

## 3. 任務總覽

| ID | 任務 | 性質 |
| --- | --- | --- |
| **V0** | 重用報告241 的安全閘門與容器生命週期（**import** `scripts/analysis/disposable_fact_state_validation.py` 的閘門／起／拆函式，**不得複製貼上、不得修改該檔**；若函式不可 import 請說明並以最小方式處理，優先回報） | 新增驗證腳本＋單元測試 |
| **V1** | W1 驗證（H6）：新建 Fact 帶入生命週期屬性 | 真實 Neo4j 驗證 |
| **V2** | W4 驗證（H1、H2）：簡繁合併（純改名與撞名兩支） | 真實 Neo4j 驗證 |
| **V3** | W5 驗證（H3、H4）：改邊型別 | 真實 Neo4j 驗證 |
| **V4** | 同步提案驗證（H5）：反查實體名稱回寫 Fact 扁平屬性（只在腳本內） | 真實 Neo4j 驗證 |
| **V5** | 拆除、證明 `kg2-neo4j` 未受影響、報告 | 報告＋HANDOVER |

## 4. V0 規格

- 新驗證腳本放 `scripts/analysis/`，沿用報告240 §4 全部安全要求（連線閘門拒絕 17990／KG#4／非 27687、docker 指令白名單、密碼只在記憶體、前後 `kg2-neo4j` 的 `State.Status`／`StartedAt` 快照、`finally` 拆除）。**基準啟動時間（規劃對話記錄）：`2026-10-01T12:36:49.303373783Z`**（報告241 驗證期間未變）。
- **純運算（參數檢查、命令組裝、比對邏輯）與 docker／DB 存取分離並附單元測試**；docker 相關測試預設跳過，一般測試不得依賴 docker。
- 匯入 production 函式時沿用報告241 的作法（切換 cwd 避免讀專案 `.env`）。

## 5. V1–V4 規格（資料全為合成；向量 8 維決定性假向量；盡量以 production 既有函式與路徑建立資料以測真實行為）

**V1（W1／H6）**：以 production `_create_fact_node` 建一個「現況 Fact」，再以腳本內自寫的 Cypher（鏡像 `_create_fact_node` 的 CREATE，**僅多兩個屬性**）建一個「提案 Fact」。比對兩者的屬性集合差異；對兩者各跑 `vector_search_facts`、`backfill_fact_text_embeddings`、`revoke_chunk_facts`，記錄是否有行為差異、額外屬性是否被保留／忽略／造成錯誤。

**V2（W4／H1、H2）**：兩個子情境（都附 Fact，並在 Fact 上放 `lifecycle_state`／`lifecycle_events_json`）：
- *(a) 純改名*：簡體名稱實體無繁體孿生 → 呼叫 production `backfill_traditionalize_entity_names`；
- *(b) 撞名*：繁體孿生已存在 → 同上。
`kg_folder` 需要一個包含合成繁體來源文字的暫存資料夾（腳本內建立於系統暫存目錄、結束刪除，不得用 `D:\Users\666\Desktop\kg-runtime` 的真實資料夾）。記錄：Fact 節點是否存活、`HAS_SUBJECT`／`HAS_OBJECT` 是否連到預期實體、`lifecycle_*` 屬性是否保留、Fact 的扁平 `subject`／`object` 是否過時；以及（b）中**兩個**指向同一實體對、扁平名稱不同的 Fact 在 `vector_search_facts` 的去重行為。

**V3（W5／H3、H4）**：建立 `RELATED_TO` 邊與其 Fact，以 production `backfill_related_to_edges` 升級型別（需要 relationship 向量索引、`verb_embedding`、假 `EmbeddingProvider` 與假 `LLMProvider`——**假物件只放在驗證腳本內**，假 LLM 對確認請求固定回覆同意）；記錄 Fact 的 `rel_type` 是否過時；再把「BFS 側三元組（新型別）」與「Fact 側（`RELATED_TO`）」餵給 `services.context.fact_lines.split_fact_lines`，記錄是否兩行都保留。

**V4（H5）**：在腳本內寫一段「同步」Cypher（`MATCH (f:Fact)-[:HAS_SUBJECT]->(s), (f)-[:HAS_OBJECT]->(o) SET f.subject = s.name, f.object = o.name` 之類；`rel_type` 的同步另需對應邊型別，若無法只憑 Fact 取得，**明寫限制**），套用在 V2／V3 的過時資料上，驗證修復結果與冪等性（跑兩次結果相同）；**僅為驗證，不得提議直接改 production**。

每個情境輸出：預測（H?）、實際結果、是否相符、**未預期發現**；結論不得外推為「寫入端已可落地」。

## 6. V5 規格（收尾與報告）

1. 無論成敗都拆除臨時容器並**證明已拆除**；
2. `kg2-neo4j` 的 `StartedAt`／`Status` 與基準相同；**不得為此連線 17990**；
3. 報告（編號自 **243** 起）：確認事項、V0–V4 結果（含預測對照表）、限制與誠實揭露、**待使用者裁示清單（只列不代決）**；補列報告索引與 `HANDOVER.md` 頂部條目。
4. 限制須寫明：合成資料；單一小圖；只驗證 W1／W4／W5 三個寫入點，**未涵蓋** `merge_triples_to_graph` 全流程、抽取端、`backfill_fact_nodes` 回填、真實分布與效能；Neo4j 5.26 企業版。

## 7. 驗收（規劃對話自行驗證）

- 範圍：`git diff --name-only` 僅允許新增驗證腳本／測試／輸出 JSON／報告／索引／`HANDOVER.md` 頂部條目；**`services/`、`routers/`、`core/` 等既有 production 檔零變動**；**不得修改** `scripts/analysis/disposable_fact_state_validation.py`；規劃文件、論文、題庫、歷史報告原文不動；
- **我讀碼檢查閘門**：新腳本中不得有任何可達的 17990 連線或寫死密碼；docker 指令僅限白名單；
- **docker／kg2-neo4j**：交付後 `docker ps -a` 無 `kg2-throwaway-neo4j` 殘留；`kg2-neo4j` 的 `StartedAt` 等於基準；
- **我自行重跑一次**（輸出導到暫存目錄）並對照 H1–H6 的結果；
- 密碼外洩比對（`.env` 密碼對所有新檔 0 命中，並掃描疑似隨機 token）；全量 pytest ≥1877 passed；`check_node_cards.py` 不新增警告。

## 8. 停止條件（遇到即停止並回報，並先確保臨時容器已拆除）

1. 需要連 17990／讀取現有容器密碼，或對 `kg2-neo4j` 執行任何指令；
2. 同名容器已存在、連接埠被占用、記憶體不足、docker 權限被拒；
3. 需要修改 production 檔才能完成驗證（例如函式在無 `.env` 時無法匯入或需要真實資料夾）；
4. 結果與預測**嚴重不符**——如實回報並說明對設計的影響，不要調整測試去符合預測；
5. 使用者未明確確認 §2 三項。

## 9. 編號、約定與回報

本文為 **242**；Codex 新報告自 **243** 起（先 `ls docs/報告`）。Codex 無法傳訊：結果寫進報告與 `HANDOVER.md`，由使用者貼回；**不得自稱已驗證**。回報格式：`V0–V5｜結論｜commit SHA｜H1–H6 各自是否符合預測｜臨時容器是否已拆除｜kg2-neo4j 是否未變｜偏離報告242之處（無則寫無）`。同一時間只能一個執行者。

## 10. 執行紀錄（僅規劃對話更新）

| ID | 狀態 | 結論 | commit | 備註 |
| --- | --- | --- | --- | --- |
| V0–V5 | ⏳ 待使用者確認 §2 後交 Codex | — | — | 基準：`kg2-neo4j` `StartedAt=2026-10-01T12:36:49.303373783Z`（規劃對話於報告241 驗證時再次確認未變） |
