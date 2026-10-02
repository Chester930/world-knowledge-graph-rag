# 報告252：下一階段任務規劃——「方案 B 套用後 `backfill_fact_text_embeddings` 要重算多少向量」估算（對 KG#4 **唯讀**；交 Claude 實作對話）

> **日期**：2026-10-02
> **性質**：階段任務規劃。分工：**規劃對話決定與獨立驗證、Claude 實作對話執行、規劃對話只記錄**。**本文件只由規劃對話修改（§9 執行紀錄）。**
> **依據**：[報告244](244_Fact扁平屬性與實體名稱不同步缺口_量測根因與修復設計.md) §4／§8（「重跑回填即可修復」「重算數約等於過時 Fact 數」皆為〔推論〕未量測）；[報告250](250_下一階段任務規劃_G3重同步方案B正式模組化_交Claude實作對話.md) §10（G3 已驗證；`services/fact_flat_resync.py` 可用）；使用者「同意建議，繼續」。
> **基準**：HEAD ≥ 本文件 commit；全量 pytest **1936 passed**。
> **新基準（重要）**：Docker 於約 11:09Z 整體重啟，`kg2-neo4j` **StartedAt＝`2026-10-02T11:09:32.79429649Z`**（使用者已同意採用）。規劃對話已做重啟後唯讀指紋複驗：**與備份前十項指紋逐項相同**、16 個索引全 `ONLINE`（`data/analysis/kg4_fingerprint_after_docker_restart_20261002.json`）。
> **本任務的性質**：**純估算、純唯讀**。回答「若對 KG#4 套用方案 B（G4），之後重跑 `backfill_fact_text_embeddings` 需重新 `encode()` 幾個 Fact、約多少字元」。**不寫入 KG#4、不呼叫任何 embedding provider、不啟動任何 docker 容器。**

---

## 1. 背景

`backfill_fact_text_embeddings`（`services/svo_service.py:1827–1911`）逐筆以 `f.subject`／`f.verb`／`f.object`（扁平屬性）重建 `fact_text`（`_to_traditional_selective(_verbalize_fact(subject,"",verb,object,""), source_charset)`），**只在與現存 `fact_text` 不同時才 `encode()`**。方案 B 先把 `subject`／`object` 同步成目前實體名稱，所以重算數＝「同步後重建文字與現存 `fact_text` 不同」的 Fact 數。這不一定等於 1,789（需更新扁平屬性的筆數）：有些過時 Fact 的 `fact_text` 可能本來就已不同（舊版括號格式、簡體殘留），有些扁平屬性變了但 `fact_text` 不受影響則不會（不會發生，因主詞／受詞都在文字內，但仍以實算為準）。

## 2. 使用者確認事項

使用者已同意：①採用新基準；②唯讀指紋複驗（已做）；③進行本估算（「同意建議，繼續」）。**不需再確認**；但仍受 §7 停止條件約束。

## 3. 任務總覽

| 步驟 | 內容 |
| --- | --- |
| **E0** | 前置：`git pull`、基準 pytest、`docker inspect kg2-neo4j --format "{{.State.StartedAt}}"` 必須等於新基準，否則**停止詢問**；`ListAgents` 確認無其他 session 正在寫 KG#4 |
| **E1** | 純函式 `plan_reencode(rows, *, source_charset) -> stats`（見 §4），放新腳本 `scripts/analysis/kg4_backfill_reencode_estimate.py` |
| **E2** | 單元測試 `tests/scripts/test_kg4_backfill_reencode_estimate.py`（假資料；不連 Neo4j） |
| **E3** | 對 KG#4 **唯讀**取資料並計算，輸出 `data/analysis/kg4_backfill_reencode_estimate_20261002.json` |
| **E4** | 報告 253＋索引＋`HANDOVER.md` 頂部條目 |
| **E5** | 全量 pytest、節點卡、commit、push、以 SendMessage 回報規劃對話 |

## 4. E1 規格（計算）

1. **資料列來源**：沿用規劃對話先前對 KG#4 的做法（見 `data/analysis/kg4_resync_dryrun_20261002.json`）：以 `scripts.analysis.semantic_layer_invariants.ReadOnlyRunner`（內建 `assert_read_only`，**不得放寬**）執行**純 MATCH／RETURN**（不可含 `CALL {}` 子查詢，會被守衛拒絕）的等價查詢，取得每個 Fact 的：`subject`、`verb`、`object`、`fact_text`、`HAS_SUBJECT`／`HAS_OBJECT` 實體名稱、（供 `sync_rel_type=False` 不需邊資訊）。`kg_id` 用 `KG_ID_DEFAULT`。
2. **同步後的扁平屬性**：呼叫 `services.fact_flat_resync._plan_resync_updates(rows, sync_rel_type=False)`（純函式，不連線）取得 `updates["subject"]`／`updates["object"]`，把新值套到記憶體中的列（不寫回）。
3. **重建文字**：用生產函式 `services.svo_service._verbalize_fact` 與 `services.extraction.traditional._to_traditional_selective`；`source_charset` 用 `_kg_source_charset(<KG 資料夾名>)`（先讀 `services/extraction/traditional.py:50` 與 `scripts/analysis/semantic_layer_invariants.py` 看資料夾名稱怎麼取；若找不到來源檔會回傳空集合＝全轉，**須在報告揭露實際使用的是哪一種**）。
4. **統計欄位**（全部以 Fact 數計）：
   - `facts_total`；
   - `would_reencode_without_resync`：不做方案 B、直接跑回填現在就會重算的數量（基線；若不為 0，表示回填曾漏跑／格式過期）；
   - `would_reencode_after_resync`：套用方案 B 後跑回填會重算的數量（**主要答案**）；
   - `resync_changed_facts`：方案 B 會動到的 Fact 數（應為 **1,789**，與先前量測交叉核對）；
   - `reencode_caused_by_resync_only`：僅因方案 B 才需重算者（`after` 與 `without` 的差集大小）；
   - `reencode_overlap`：兩者都需重算者；
   - `text_chars_total_after`：`would_reencode_after_resync` 那批新 `fact_text` 的字元總數、平均、P95、最大；
   - 分頁預估：`ceil(facts_total / 200)` 頁（回填以 `SKIP/LIMIT` 掃全部 Fact，與重算數無關——這點要在報告寫明，因為掃描成本＝全 KG 掃描一遍）。
5. **抽樣（最多 20 筆）**：「僅因方案 B 才需重算」的 Fact，列 `舊 fact_text → 新 fact_text`（Fact 文字是法規事實內容，非密碼，可入報告；**不得**列任何連線資訊）。另抽 ≤10 筆「回填基線本來就會重算」者。
6. **成本估算**：只做算術——重算數×平均字元數；**不得呼叫 embedding provider、不得連 Ollama**（Ollama 在 WSL，Docker 剛重啟過，狀態未知）。報告註明「實際耗時未實測，取決於 provider（本機 Ollama bge-m3／其他）」，並列出尚需決定的 provider 與批次策略。
7. 腳本 ≤200 行；不自行建立連線以外的副作用；連線埠硬限 `17990`（唯讀），沿用既有腳本做法讀 `.env` 密碼，**絕不印出**。

## 5. E2 規格（測試）

純函式 `plan_reencode` 表格驅動：①扁平屬性過時且文字因此改變→計入 after、計入 caused_by_resync_only；②扁平屬性過時但舊 `fact_text` 本來就等於新文字（罕見）→不計；③文字本來就過期（無 resync 也不同）→計入 `without` 與 `overlap`；④全一致→皆 0；⑤`subject`／`object` 為 `None` 的處理與 `backfill_fact_text_embeddings` 一致（`or ""`）；⑥`source_charset` 為 `None` 與非 `None` 兩種；⑦統計恆等式：`after = overlap + caused_by_resync_only`（若成立；若發現不成立請如實說明原因，不要硬湊）。另加結構守衛：腳本原始碼不含寫入關鍵字之 Cypher（`SET`／`CREATE`／`MERGE`／`DELETE`／`REMOVE`）、不 import 任何 embedding provider 或 `core.providers`；腳本唯一允許的 docker 指令是 `docker inspect kg2-neo4j`（以 `subprocess` 參數列表呼叫），其他 docker 子指令一律不得出現。

## 6. 驗收（規劃對話自行驗證）

- `git diff` 範圍：僅新增腳本、測試、輸出 JSON、報告 253、索引、`HANDOVER.md`；**既有 production、既有 `disposable_*`、規劃文件零變動**；
- 我讀碼確認：只經 `ReadOnlyRunner`、純 MATCH、無 `CALL {}`、無 embedding 呼叫、無連 17990 以外埠、無密碼外洩；
- **我獨立重算**：用我自己的方式（不同查詢組合）對 KG#4 再算一次 `resync_changed_facts`（應＝1,789）與 `would_reencode_after_resync`，必須逐項一致；
- 執行前後 KG#4 總數不變（`totals_stable`）與 `kg2-neo4j` StartedAt 仍＝新基準；
- 全量 pytest ≥ 1936＋新增數、`check_node_cards.py` 0 警告、密碼外洩掃描 0 命中。

## 7. 停止條件（遇到即停止並回報）

1. `kg2-neo4j` StartedAt ≠ `2026-10-02T11:09:32.79429649Z`，或 `ListAgents` 顯示有 session 正在對 KG#4 寫入；
2. 任何寫入、`CALL {}` 被守衛擋下後想「放寬守衛」；
3. 需要呼叫 embedding provider／Ollama、啟動 docker 容器、讀密碼以外的憑證；
4. `resync_changed_facts` ≠ 1,789（與先前量測不符）——如實回報並說明差異，**不要調整程式去符合**；
5. 需修改既有 production 檔。

## 8. 編號、約定、回報

新報告自 **253** 起（先 `ls docs/報告`）。繁體中文；conventional commit（例 `feat(analysis): ...`、`docs(報告253): ...`）；commit 後 push 本分支（不動 master）。不得自稱「已驗證」。完成後**直接以 SendMessage 回報規劃對話 `project refactor review sdd`**，格式：`E0–E5｜結論｜commit SHA｜facts_total／resync_changed_facts／would_reencode_without_resync／would_reencode_after_resync／caused_by_resync_only／overlap｜新 fact_text 平均與 P95 字元數｜source_charset 實際使用情形｜KG#4 前後總數與 StartedAt｜是否呼叫過 embedding provider（應為否）｜偏離報告252之處（無則寫無）`。

## 9. 執行紀錄（僅規劃對話更新）

⏳ 任務書已寫成，將以 SendMessage 派給實作對話「fact-rag vector search implementation」。KG#4 仍無任何寫入核准。
