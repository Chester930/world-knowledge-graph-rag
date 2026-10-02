# 報告245：下一階段任務規劃——G1「Fact 扁平屬性重同步（方案 B）」在臨時 Neo4j 上的驗證（交 Codex）

> **日期**：2026-10-02
> **性質**：階段任務規劃。分工：**規劃對話（Claude）決定與獨立驗證、Codex 執行、規劃對話只記錄**。**本文件只由規劃對話修改（§10 執行紀錄）。**
> **依據**：使用者對[報告244](244_Fact扁平屬性與實體名稱不同步缺口_量測根因與修復設計.md) §9 的裁示（全部「同意建議」）：**方案 B 為主**（獨立、冪等、預設 `dry_run` 的重同步維護函式，之後重跑既有 `backfill_fact_text_embeddings`）；**接受「備份與還原演練」為寫入 KG#4 的硬性前提**；改邊型別漏複製 `verb_embedding`／`natural_text` **等真的要用到那個功能時再處理**；**同意進入 G1**（臨時容器驗證）。
> **基準**：全量 pytest **1887 passed／0 failed**；HEAD ≥ `8c96462`。
> **邊界（與報告240／242 相同，缺一不可）**：**絕不連 KG#4／`kg2-neo4j`（17990）**；只用臨時容器 `kg2-throwaway-neo4j`（埠 27474／27687，`neo4j:5.26-enterprise`，3 GB，無 volume／mount，不 pull）；**不修改任何 production 檔**（方案 B 的函式**先寫在驗證腳本內**，G3 才會正式加入）；不啟動 Ollama／LLM、不連外網；不改論文與題庫；報告236／237／239／241／243 原文不改。

---

## 1. 背景（報告244 已量測與讀碼的事實，Codex 請自行重新核對讀碼部分）

- KG#4 量測（唯讀）：Fact 扁平 `subject` 過時 1,102／16,826、`object` 過時 764；去重鍵分組依扁平屬性 14,229 vs 依實體名稱 14,021（至少 208 組同一事實沒去重）；`rel_type` 過時 0。
- 根因（讀碼）：建立 Fact 時扁平屬性＝當下實體名稱（`services/svo_service.py:1295–1309`）；之後 `merge_entity` 的**標準名提升**（`:760–776`，`SET e.name = $final_name`）與 `backfill_traditionalize_entity_names`（`:2071–2197`）改實體名稱，Fact 抄本不更新；全檔無任何程式更新 Fact 的 `subject`／`object`／`rel_type`。
- 「標準名提升」由跨文件頻率決定：`_aggregate_alias_counts` **以獨立文件數計**（見 `:673` 起），且 `merge_entity` 須提供 `source_doc_id`＋`source_svo_chunk_index` 才會做頻率判斷（`:723` 起說明）。**要在臨時容器重現提升改名，必須用多個不同的 `source_doc_id` 讓別名的文件數超過現名**——這是本任務要驗證的「根因推論」。

## 2. 使用者必須明確確認的事項（Codex 開工前**必須**取得；未確認不得執行任何 docker 指令）

與報告240 §2 相同的三項（本任務是**另一次**臨時容器執行，需重新確認）：①允許對名為 **`kg2-throwaway-neo4j`**（只有這一個名稱）的臨時容器執行 `docker run`／`stop`／`rm`，參數固定（映像 `neo4j:5.26-enterprise`、埠 27474／27687、3 GB、無 volume／mount、不 pull，見報告240 §4）；對其他任何容器（含 `kg2-neo4j`）**不得**執行任何 docker 指令（唯一例外：`docker inspect --format` 僅取 `kg2-neo4j` 的 `State.Status`／`State.StartedAt`）；②同意接受企業版授權旗標（同現有容器）；③確認目前沒有其他 session 在使用這台機器的 Docker／Neo4j／Ollama。

## 3. 任務總覽

| ID | 任務 | 性質 |
| --- | --- | --- |
| **W0** | 重用報告241／243 的安全閘門；新驗證腳本定義**新基準**（見 §4）；單元測試 | 新增驗證腳本＋測試 |
| **W1** | **根因重現**：用 production 寫入路徑（`merge_entity`／`merge_triples_to_graph`）造出「標準名提升改名後 Fact 抄本過時」 | 真實 Neo4j 驗證（驗證報告244 §3 的〔推論〕） |
| **W2** | **方案 B 原型**：`resync_fact_flat_properties(driver, kg_id, *, dry_run=True, sync_rel_type=False)`（**寫在驗證腳本內**）；驗證 `dry_run`、套用、冪等、保守規則 | 真實 Neo4j 驗證 |
| **W3** | **同步後鏈**：重跑 production `backfill_fact_text_embeddings`，驗證 `fact_text`／向量更新、去重鍵對齊、BFS 與 Fact 鍵對齊 | 真實 Neo4j 驗證 |
| **W4** | **不變量與隔離**：節點／邊數與其他屬性不變、他 KG 不受影響、邊界案例、規模與耗時 | 真實 Neo4j 驗證 |
| **W5** | 拆除、證明 `kg2-neo4j` 未受影響、報告 | 報告＋HANDOVER |

## 4. W0 規格

- 新驗證腳本放 `scripts/analysis/`，沿用報告240 §4 全部安全要求（連線閘門拒絕 17990／KG#4／非 27687、docker 指令白名單、密碼只在記憶體、前後 `kg2-neo4j` 的 `State.Status`／`StartedAt` 快照、`finally` 拆除）；以 `import` 重用 `scripts/analysis/disposable_fact_state_validation.py` 與 `scripts/analysis/disposable_write_path_validation.py` 的**已審閱**閘門／容器函式，**不得複製貼上、不得修改這兩個檔**。
- **基準啟動時間（規劃對話 2026-10-02 唯讀記錄，派工前再次確認未變）**：`kg2-neo4j` `status=running`、**`StartedAt=2026-10-02T04:10:38.389676557Z`**。新腳本**自行定義**此常數；**不得呼叫** P3／P4 腳本中會檢查舊基準的 `_run_with_password`／`run_with_password`；若開工時實測值與此不同（例如 Docker 又被重啟），**停止並詢問使用者**，不要自行更新。
- **純運算與 docker／DB 存取分離並附單元測試**；docker 相關測試預設跳過，一般測試不得依賴 docker。

## 5. W1–W4 規格（資料全為合成；向量 8 維決定性假向量；盡量以 production 路徑建立資料）

**W1（根因重現）**：以 production `merge_triples_to_graph`（假 `EmbeddingProvider`，不給 `llm_provider`）建立含 Fact 的小圖；再以 production `merge_entity` 搭配**多個不同 `source_doc_id`** 讓較常見的別名勝出，使現有實體被**提升改名**。記錄：實體是否改名、`HAS_SUBJECT`／`HAS_OBJECT` 是否仍連到它、Fact 扁平屬性與 `fact_text` 是否過時（預期過時）；**若無法以 production 路徑重現提升改名，如實回報並說明原因，不要改用手動 `SET e.name` 冒充**（手動改名可另列為對照，需明標）。

**W2（方案 B 原型，寫在驗證腳本內）**：`resync_fact_flat_properties(driver, kg_id, *, dry_run=True, sync_rel_type=False)`：
1. 以 `HAS_SUBJECT`／`HAS_OBJECT` 反查，**只在扁平值與實體名稱不同時**才寫入 `f.subject`／`f.object`；
2. `sync_rel_type=True` 時**保守規則**：只有 `(s)-[r]->(o)` 之間「帶 `kg_id` 且帶 `citations_json` 的 SVO 邊」**恰好一條**時才同步 `f.rel_type`＝該邊型別；多條或零條 → 跳過並計入統計（KG#4 有 1,684 筆 Fact 兩端有多種邊型別）；
3. 回傳統計：`subject_changed`／`object_changed`／`rel_type_changed`／`rel_type_skipped_multi_edge`／`rel_type_skipped_no_edge`／`unchanged`／`facts_without_links`；`dry_run=True` **不得寫入任何東西**，且其統計**必須等於**緊接著 `dry_run=False` 的實際變更數（驗證此等式）；
4. **冪等**：第二次執行全 0；
5. **只改這三個屬性**：用前後屬性集合比對，證明 `lifecycle_*`、`fact_text`、`fact_embedding`、`source_*`、`confidence`、`verb` 等一個都沒被動到。

**W3（同步後鏈）**：W2 套用後，呼叫 production `backfill_fact_text_embeddings(driver, kg_id, embedding_provider, source_charset=…)`（`source_charset` 的取得方式沿用報告243 的暫存資料夾作法，**不得使用真實 `kg-runtime`**）。驗證：①`fact_text` 已由新的扁平屬性重建、`fact_embedding` 僅在文字改變的 Fact 重算（用假 provider 計數 `encode` 呼叫次數＝實際改變數）；②第二次呼叫回傳 0；③W1／報告243 H2 的「兩個因名稱不同而未去重的 Fact」經 W2＋W3 後，`vector_search_facts` **會**去重為一筆；④報告243 H4 的 BFS 側與 Fact 側同一事實，經 W2（`sync_rel_type=True`）後 `split_fact_lines` 會去重（或如實記錄不會，並說明原因，例如 `fact_text` 措辭不同）。

**W4（不變量、隔離、邊界、規模）**：
1. **不變量**：W2／W3 前後節點數、邊數、實體名稱、邊的屬性（`citations_json`／`confidence`／型別）完全不變；
2. **隔離**：另建第二個合成 KG（不同 `kg_id`）含過時 Fact，對 KG-A 執行 W2 後 KG-B 的 Fact **一個都沒變**；
3. **邊界案例**：Fact 缺 `HAS_SUBJECT`／`HAS_OBJECT`（跳過並計數）、扁平值為空字串或 `None`、名稱含空白、已一致者不寫入（以 `dry_run` 與實際寫入的計數驗證）；
4. **規模與耗時**：約 **17,000 個合成 Fact**（其中約 1,800 個過時，貼近 KG#4 量測）上，量測 `dry_run`、套用、冪等第二次的耗時；在 3 GB 容器內須能完成，**若超時或記憶體不足，如實回報，不要放寬資源上限**；耗時僅供量級參考。

每個情境輸出：預期（見本文）、實際結果、是否相符、**未預期發現**。**不得宣稱「方案 B 已可套用到 KG#4」**——本任務只驗證邏輯與行為。

## 6. W5 規格（收尾與報告）

1. 無論成敗都拆除臨時容器並**證明已拆除**；
2. `kg2-neo4j` 的 `StartedAt`／`Status` 與基準相同；**不得為此連線 17990**；
3. 報告（編號自 **246** 起）：確認事項、W0–W4 結果（含預期對照表）、限制與誠實揭露、**待使用者裁示清單（只列不代決）**；補列報告索引與 `HANDOVER.md` 頂部條目。
4. 限制須寫明：合成資料；單一小圖與一個 17k 規模圖；**未驗證**備份／還原（G2）、正式模組化（G3）、對 KG#4 的套用（G4）、讀取端以實體名稱去重（方案 C）、改邊型別漏複製 `verb_embedding`／`natural_text`（使用者決定暫不處理）；Neo4j 5.26 企業版。

## 7. 驗收（規劃對話自行驗證）

- 範圍：`git diff --name-only` 僅允許新增驗證腳本／測試／輸出 JSON／報告／索引／`HANDOVER.md` 頂部條目；**`services/`、`routers/`、`core/` 等既有 production 檔零變動**；**不得修改** P3／P4 的兩個驗證腳本與其測試；規劃文件、論文、題庫、歷史報告原文不動；
- **我讀碼檢查閘門**：新腳本無可達的 17990 連線或寫死密碼、docker 指令僅限白名單、自訂新基準、不呼叫舊基準執行器；
- **docker／`kg2-neo4j`**：交付後 `docker ps -a` 無 `kg2-throwaway-neo4j` 殘留；`kg2-neo4j` 的 `StartedAt` 等於基準；
- **我自行重跑一次**（輸出導到暫存目錄）並對照 W1–W4 結果，特別核對 W2 的「`dry_run` 統計＝實際變更數」「冪等」「只改三個屬性」與 W3 的「去重對齊」；
- 密碼外洩比對（`.env` 密碼對所有新檔 0 命中，並掃描疑似隨機 token）；全量 pytest ≥1887 passed；`check_node_cards.py` 不新增警告。

## 8. 停止條件（遇到即停止並回報，並先確保臨時容器已拆除）

1. 需要連 17990／讀取現有容器密碼，或對 `kg2-neo4j` 執行任何指令；
2. 同名容器已存在、連接埠被占用、記憶體不足、docker 權限被拒；
3. 需要修改 production 檔才能完成驗證；
4. 結果與預期**嚴重不符**（例如 `dry_run` 與實際變更數不一致、冪等不成立、17k 規模無法在 3 GB 內完成）——如實回報並說明對設計的影響，不要調整測試去符合預期；
5. 使用者未明確確認 §2。

## 9. 編號、約定與回報

本文為 **245**；Codex 新報告自 **246** 起（先 `ls docs/報告`）。Codex 無法傳訊：結果寫進報告與 `HANDOVER.md`，由使用者貼回；**不得自稱已驗證**。回報格式：`W0–W5｜結論｜commit SHA｜W1 根因是否以 production 路徑重現｜W2 dry_run=實際／冪等／只改三屬性｜W3 去重是否對齊｜W4 17k 耗時｜臨時容器是否已拆除｜kg2-neo4j 是否未變｜偏離報告245之處（無則寫無）`。同一時間只能一個執行者。

## 10. 執行紀錄（僅規劃對話更新）

| ID | 狀態 | 結論 | commit | 備註 |
| --- | --- | --- | --- | --- |
| W0–W5 | ✅ 通過（Codex 完成；規劃對話獨立驗證，含自行重跑與補做真實 KG#4 唯讀 dry-run）。報告246＋`scripts/analysis/disposable_resync_solution_b_validation.py`＋測試；使用者已確認 §2 三項（貼上指令）；全量 pytest 1897 passed | `e5d3821`（實作、報告246、HANDOVER） | **我驗**：①範圍＝新增腳本／測試／輸出 JSON／報告246／索引／HANDOVER；**`core／routers／repositories／models／services` 零變動，P3／P4 腳本與測試未動**。②**讀碼**：以 `import` 重用 P3／P4 的閘門與容器函式；自訂 `EXPECTED_KG4_STARTED_AT="2026-10-02T04:10:38.389676557Z"`；唯一一處建立驅動且在 `validate_connection_target` 之後；`17990` 在新檔完全不出現；resync 函式**分「規劃（純運算，不收 driver）」與「寫入」兩階段**，`dry_run=True` 不進寫入階段；唯一寫入敘述是 `SET f.{attribute}`，`attribute` 取自固定常數 `SYNC_ATTRIBUTES=("subject","object","rel_type")`；`rel_type` 同步規則為「`(s)-[r]->(o)` 帶 `kg_id` 與 `citations_json` 的邊恰好一條才改，多條／零條跳過並計數」。③**我自行重跑一次（輸出導到暫存目錄，56 秒）**：W1＝production 路徑 `merge_triples_to_graph→merge_entity`、3 個不同 `source_doc_id`、實體提升改名成立（「勞動法規」→「勞動法」）、3 筆 Fact 中 2 筆扁平主詞與 `fact_text` 過時，**證實報告244 根因推論**；W2＝`dry_run`＝實際（2／0／0）、不寫入、冪等、只改三屬性；W3＝回填 `encode` 次數＝文字更新數（2）、第二次 0、`vector_search_facts` 去重 2→1、`split_fact_lines` 後 BFS 1／Fact 0；W4＝邊界案例 `dry_run`＝實際、冪等、節點邊數不變、跨 KG 隔離（KG-B 摘要雜湊前後相同）——**全部重現**。④重跑與唯讀量測後：`kg2-neo4j` `StartedAt` 仍為新基準、`docker ps -a` 無殘留、`git status` 乾淨。⑤密碼外洩 0 命中、疑似隨機 token 0 個；全量 pytest 我重跑＝**1897 passed／0 failed**；節點卡 0 警告。**我補充的限制與補做**：**(a)** Codex 的 17,000 Fact 規模測試（`create_scale_facts`，`:411–435`）把全部 Fact 掛在**單一實體對**（`規模主體`／`規模物件`）、**未建立任何關係邊**、且**只開名稱同步**（`sync_rel_type=False`），所以其耗時（0.85／0.97／0.67 秒，我重跑 1.36／1.38／1.16 秒）只代表最簡拓撲，**不代表真實圖**——這是我任務書 §5 W4-4 沒要求拓撲真實性與型別同步規模的缺口。**(b)** 補做：以 `ReadOnlyRunner` 對**真實 KG#4** 唯讀（原語句含 `CALL {}` 子查詢被 `assert_read_only` 拒絕，**我沒有放寬防護**，改用等價純 `MATCH`／`OPTIONAL MATCH` 查詢）取得 16,826 筆資料列（1–3 秒），再交原型的純運算 `_plan_resync_updates`：**`subject_changed=1,102`、`object_changed=764`、`rel_type_changed=0`、`rel_type_skipped_multi_edge=1,684`、`unchanged=15,037`（需更新的 Fact＝1,789）**，與我先前獨立量測逐項吻合；前後總數相同、未寫入（`data/analysis/kg4_resync_dryrun_20261002.json`）。**(c)** 偏離（Codex 已揭露，我同意）：腳本先以 production 函式建立並等待 vector index ONLINE，不影響結論。**未驗證**：備份／還原（G2）、正式模組化（G3）、對 KG#4 套用（G4）、`backfill_fact_text_embeddings` 實際重算向量數（可能多於 1,789）與成本、改邊型別漏複製欄位（使用者決定暫不處理）。 |
| 基準 | 派工前記錄 | — | — | `kg2-neo4j` `StartedAt=2026-10-02T04:10:38.389676557Z`（派工前再次確認未變；驗收時比對結果：完全相同）；KG#4 唯讀量測見報告244 |
