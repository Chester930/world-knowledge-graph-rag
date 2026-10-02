# 報告250：下一階段任務規劃——G3「`resync_fact_flat_properties` 正式模組化」（新增模組、預設 `dry_run`、零接線、附測試）（交新開的 Claude 實作對話）

> **日期**：2026-10-02
> **性質**：階段任務規劃。分工：**規劃對話決定與獨立驗證、Claude 實作對話執行、規劃對話只記錄**。**本文件只由規劃對話修改（§10 執行紀錄）。**
> **依據**：[報告244](244_Fact扁平屬性與實體名稱不同步缺口_量測根因與修復設計.md) §5 方案 B；[報告246](246_G1重同步方案B臨時容器驗證執行紀錄.md)／[報告245](245_下一階段任務規劃_G1重同步方案B臨時容器驗證_交Codex.md) §10（G1 已驗證原型成立）；[報告249](249_KG4冷備份執行紀錄與還原程序.md)（備份已完成）。使用者「同意建議，繼續」＝採用規劃對話建議：做 G3。
> **基準**：HEAD ≥ `89eddb4`；全量 pytest **1906 passed**（`-q` 約 68 秒）。
> **本任務的性質**：把 G1 驗證過的原型**搬成正式模組**。**不是新設計**——演算法、統計欄位、寫入規則以原型為準，只做搬移、整理與補測試。**本任務絕不連 KG#4、不啟動任何 docker、不執行回填。**

---

## 1. 背景（一句話）

Fact 節點的扁平屬性 `subject`／`object`／`rel_type` 是建立時從實體抄來的，實體之後被改名就會過時（KG#4 目前 `subject` 過時 1,102 筆、`object` 764 筆、`rel_type` 0 筆）。方案 B＝獨立、冪等、預設 `dry_run` 的重同步函式，**不改任何既有熱路徑**。原型現在寫在 `scripts/analysis/disposable_resync_solution_b_validation.py:172–285`（`_fact_sync_rows`／`_plan_resync_updates`／`_apply_updates`／`resync_fact_flat_properties`／`_new_stats`），G1 已在臨時容器證明：`dry_run` 統計＝實際變更數、冪等、只改三個屬性、規模 17,000 Fact 約 1 秒。

## 2. 需要使用者確認的事項

**無**（純程式碼與單元測試，不碰任何 Neo4j 或 docker）。若實作中想用臨時容器做整合測試，**停止並回報**，不要自行啟動（見 §7）。

## 3. 任務總覽

| 步驟 | 內容 | 產出 |
| --- | --- | --- |
| **R0** | 前置：`git fetch`、確認 HEAD、跑基準測試、`ls docs/報告`、讀原型與其測試 | 基準數字 |
| **R1** | 新模組 `services/fact_flat_resync.py`（§4） | 新檔 |
| **R2** | 單元測試 `tests/services/test_fact_flat_resync.py`（§5；沿用既有測試目錄慣例，先 `ls tests` 確認） | 新檔 |
| **R3** | 結構守衛測試（零接線、只寫三屬性、dry_run 不寫）（§5-C） | 同 R2 或另檔 |
| **R4** | 報告 251＋索引＋`HANDOVER.md` 頂部條目（§8） | 文件 |
| **R5** | 全量 pytest、節點卡檢查、commit（不 push 以外的動作見 §9） | 回報 |

## 4. R1 規格（模組）

1. **位置**：`services/fact_flat_resync.py`（純新增）。公開函式簽名與原型**完全一致**：
   `async def resync_fact_flat_properties(driver, kg_id: UUID, *, dry_run: bool = True, sync_rel_type: bool = False) -> dict[str, int]`
2. **內容**：由原型搬移 `_new_stats`、`_fact_sync_rows`、`_plan_resync_updates`、`_apply_updates` 與主函式；`SYNC_ATTRIBUTES` 常數（原型已有，值為 `("subject","object","rel_type")`；先讀原型確認）。**Cypher 語句與判定邏輯不得改動**，除非發現確切缺陷——發現就**停止並回報**，不要自行「改良」。
3. **統計欄位**（與原型相同）：`subject_changed`、`object_changed`、`rel_type_changed`、`rel_type_skipped_multi_edge`、`rel_type_skipped_no_edge`、`unchanged`、`facts_without_links`。
4. **driver 介面**：只使用 `driver.execute_query(statement, **params)`，回傳物件有 `.records`（與原型 `cypher()` 輔助函式相同）。不 import `core.database` 的全域單例、不讀 `.env`、不建立連線——**driver 由呼叫者傳入**。
5. **讀寫分離**：計畫階段（`_fact_sync_rows` 讀、`_plan_resync_updates` 純函式）與寫入階段（`_apply_updates`）分開；`dry_run=True` 時**絕不呼叫** `_apply_updates`，也不得送出任何含 `SET`／`CREATE`／`MERGE`／`DELETE`／`REMOVE` 的語句。
6. **寫入守衛**：`_apply_updates` 的 `attribute` 必須檢查在白名單 `SYNC_ATTRIBUTES` 內，否則 `ValueError`（因為屬性名是用 f-string 插入 Cypher，白名單是防注入的唯一保證）；寫入筆數與預期不符時 `RuntimeError`（原型已有）。
7. **範圍隔離**：所有語句的 `MATCH (f:Fact {kg_id: $kg_id})` 不得省略；`kg_id` 以 `str(kg_id)` 傳入。
8. **docstring**（繁體中文）須寫明：用途、預設 `dry_run`、冪等、`sync_rel_type` 的保守規則（端點間恰好一條邊且一種型別才同步；多條略過；無邊略過）、**同步後必須再跑既有 `backfill_fact_text_embeddings` 才會重建 `fact_text`／向量**（本函式不碰 `fact_text`、`fact_embedding`、`natural_text`、`verb_embedding`）、**對 KG#4 套用前須備份並取得使用者同意（見報告244 §6、報告249）**。
9. **零接線**：不得被 `main.py`、任何 router、任何既有 service、worker、hook 或 script import（`scripts/analysis/disposable_resync_solution_b_validation.py` **不改**，仍保留自己的原型副本）。≤200 行（含 docstring）為宜；超過就再拆。

## 5. R2／R3 規格（測試；無 Neo4j、無 docker）

測試用**假 driver**（自寫小類別，記錄每次 `execute_query` 的語句與參數，並依語句回傳預先給定的 `records`）。

**A. 純計畫函式 `_plan_resync_updates`**（表格驅動，逐列對照）：
- 主詞過時／受詞過時／兩者皆過時／兩者一致（`unchanged`）；
- `subject_name`／`object_name` 為 `None` 時不更新（原型規則）；
- 缺 `HAS_SUBJECT` 或 `HAS_OBJECT`（`subject_exists`／`object_exists` 為 False）→ `facts_without_links`，且**不產生任何更新**；
- `sync_rel_type=False` 時 `rel_type_*` 全 0 且 `updates["rel_type"]` 為空，即使 `edge_count`／`edge_types` 有值；
- `sync_rel_type=True`：單邊單型別且不同→更新；相同→不更新；`edge_count>1`→`rel_type_skipped_multi_edge`；`edge_count==0`→`rel_type_skipped_no_edge`；邊數 1 但 `edge_types` 為空或 2 個以上的異常組合→必須有明確且被測試鎖住的行為（先讀原型確認現行行為，**照現行行為鎖住**，不要改）；
- 冪等：把計畫結果套回輸入列（測試內模擬）後再算一次，三個 `*_changed` 全 0。

**B. 主函式（假 driver）**：
- `dry_run=True`（預設）：回傳統計正確；**所有送出的語句都不含寫入關鍵字**（大小寫不敏感，含 `SET`、`CREATE`、`MERGE`、`DELETE`、`REMOVE`）；
- `dry_run=False`：只對有更新的屬性送出寫入語句；每個寫入語句只 `SET f.<白名單屬性>`；沒有任何變更時**零寫入語句**；
- 寫入回傳筆數與預期不符→`RuntimeError`；
- `_apply_updates` 傳入非白名單屬性名（如 `"fact_text"`、`"name) DETACH DELETE (n"`）→`ValueError`，且不送出任何語句；
- `kg_id` 以字串傳入、每個語句都含 `kg_id` 參數與 `{kg_id: $kg_id}` 範圍。

**C. 結構守衛（讀碼測試）**：
- 用 `ast` 解析 `services/fact_flat_resync.py`：不 import `core.database`、`core.config`、`dotenv`、`os.environ` 之類；
- 用 `git grep` 等價的檔案掃描（`pathlib` 遍歷 repo 內 `*.py`，排除 `tests/`、`docs/`、`.claude/`）：**只有**本模組檔案自己與（若你選擇匯入以重用）**無人**引用 `fact_flat_resync`——即零接線；
- 本模組原始碼不含 `17990`、`bolt://`、`neo4j://`、密碼樣式字串；
- 模組內所有 `SET` 只針對 `f.{attribute}`，且 `fact_text`／`fact_embedding`／`natural_text`／`verb_embedding` 字樣只出現在 docstring／註解，不出現在 Cypher 字串。

## 6. 驗收（規劃對話自行驗證）

- `git diff --name-only 89eddb4..HEAD` 僅允許：新增 `services/fact_flat_resync.py`、新增測試檔、報告 251＋索引一行、`HANDOVER.md` 頂部條目；**既有 production 檔、既有 `scripts/analysis/disposable_*` 與其測試、規劃文件（含本報告）、論文、題庫、歷史報告原文零變動**；
- 我用 `ast.dump` **對照原型逐函式**：Cypher 字串、判定條件、統計鍵、寫入檢查必須逐字相同（差異須在報告 251 逐項解釋）；
- 我 `git grep fact_flat_resync` 確認零接線；
- 我另以**原型自帶的臨時容器驗證**不重跑（原型未變，G1 已證）——但會用我自己的測試對照：把原型與新模組的 `_plan_resync_updates` 餵同一批隨機列（含邊界），輸出必須相同（等價性測試，由我加，不要求你寫）；
- 全量 pytest ≥ **1906 + 新增測試數** passed／0 failed；`check_node_cards.py` 不新增警告；密碼外洩掃描（`.env` 值＋43 字元 token）0 命中；
- 工作區乾淨、無殘留暫存檔（`.pytest-tmp-*` 屬被忽略者除外）。

## 7. 停止條件（遇到即停止並回報）

1. 需要連 17990、啟動／停止／操作任何 docker 容器，或讀 `.env` 密碼；
2. 需要修改任何既有 production 檔或既有驗證腳本才能完成；
3. 發現原型有確切缺陷（結果與報告246 所述行為不符，或 Cypher 有錯）——如實回報、**不要自行改邏輯**；
4. 全量 pytest 出現非本任務造成的失敗（先確認基準 1906 passed；基準本身就失敗要如實說）；
5. 想以臨時容器做整合測試（需使用者另行同意，且須自訂新基準 `kg2-neo4j` StartedAt `2026-10-02T09:14:47.91915022Z`）。

## 8. 文件與約定

- 新報告編號自 **251** 起（先 `ls docs/報告`）：內容含 R0 基準、R1 與原型的逐函式對照表（相同／差異）、R2/R3 測試清單與數量、限制與誠實揭露、**待使用者裁示清單（只列不代決）**；補 `00_報告索引.md` 一行與 `HANDOVER.md` 頂部條目（不改舊條目）。
- 限制須寫明：**未對任何真實或臨時 Neo4j 實跑**（以假 driver 驗證）；G4（對 KG#4 套用）、`backfill_fact_text_embeddings` 重算向量數與成本估算、方案 C、`natural_text`／`verb_embedding` 改邊型別漏複製（使用者決定暫不處理）皆**未做**。
- 繁體中文；conventional commit（例 `feat(fact-resync): ...`、`test(...)`、`docs(報告251): ...`）；遵守 `rules/node.md` 以外本 repo 慣例（先看相鄰檔案風格）。
- 不得自稱「已驗證」：驗證由規劃對話做。同一時間只能一個執行者。

## 9. 回報格式

`R0–R5｜結論｜commit SHA｜新模組行數與公開函式簽名｜與原型逐函式差異（無則寫無）｜新增測試數與全量 pytest 結果｜零接線掃描結果｜是否連過 Neo4j／docker（應為否）｜偏離報告250之處（無則寫無）`。

## 10. 執行紀錄（僅規劃對話更新）

⏳ 任務書已寫成，**尚未派工**；待使用者開新 Claude 實作對話並貼上交接指令。KG#4 仍無任何寫入核准。
