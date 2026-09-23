# T2 natural_text backfill 寫入與核對結果（20260923）

## 範圍

- 目標 KG：`236903cf-055a-40a8-8923-b9d06601f3b7`
- 資料庫：`neo4j`
- 精確 allowlist：27 個 `edge_id`，來源為本目錄 `quality_grading.md` 的「安全（建議 backfill）」清單。
- 未處理：17 個「需人工複核」邊、5 個「建議排除」邊。
- Neo4j 寫入型態：只執行 `SET r.natural_text = $new_text`；沒有 `CREATE`、`DELETE`，沒有更新 Entity 或其他關係屬性。

## 執行結果

| 項目 | 筆數 |
|---|---:|
| 精確目標數 | 27 |
| 寫入並逐筆讀回一致 | 27 |
| 寫前因欄位變動跳過 | 0 |
| 寫入 guard 失敗 | 0 |
| 寫後核對失敗 | 0 |

工具在每筆寫入前重新讀取並比對：`natural_text` 舊值、兩端 Entity 名稱／型別、最新 citation `verb`、KG ID 與關係型別；同時以當下 `citations_json` 作 compare-and-set guard。若任何欄位在 dry-run 後變動，該筆會跳過而不覆蓋。

## 獨立讀回核對

寫入完成後再次查詢 T1 全部 96 筆受影響邊：

- 27 筆 allowlist 邊的實際 `natural_text` 均等於 `t2_write_log.json` 的 `new_value`。
- 其餘 69 筆均仍等於 `affected_edges.json` 的 `old_text`；其中包含17筆需複核、5筆建議排除，以及47筆原本因欄位不足而跳過的案例。
- 稽核 log：27 筆，狀態全部為 `written_verified`。

完整逐筆前值／新值／實際讀回值見 `t2_write_log.json`。
