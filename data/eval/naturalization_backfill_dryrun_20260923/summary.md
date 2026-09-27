# natural_text 型別洩漏 backfill dry-run（20260923）

本報告只讀查詢 Neo4j，並以修法後 `_naturalize_triple()` 離線產生建議文字；未執行任何 Neo4j `SET`/`CREATE`/`DELETE`。

## T0 範圍

- 掃描資料庫：neo4j
- 已登錄 KG 掃描數：2
- 離線 LLM：`ollama` / `qwen2.5:7b`
- `kg54f8cdfa` 雖為 online standard database，但沒有 `KnowledgeGraph` 登錄、沒有 `kg_id` 屬性且 `natural_text` 邊數為 0；已列在 `t0_kg_inventory.json`，未納入自然化重算。

## 各 KG 統計

| KG | database | natural_text 邊總數 | 受影響 | 比例 | 重算成功 | 跳過 | 殘留洩漏 |
|---|---|---:|---:|---:|---:|---:|---:|
| `236903cf-055a-40a8-8923-b9d06601f3b7` | `neo4j` | 11011 | 96 | 0.87% | 49 | 47 | 0 |
| `76bc98ff-2cbd-447e-a087-7f2df6898655` | `neo4j` | 0 | 0 | 0.00% | 0 | 0 | 0 |

- 完整受影響清單：`affected_edges.json`（包含可重算與安全跳過案例）
- 可重算結果：`49` 筆；安全跳過：`47` 筆（`subject_type` 缺漏 23、`object_type` 缺漏 5、最新 citation `verb` 缺漏 19）。
- 重算後仍殘留型別標記：`0` 筆。

## 嚴重案例範例

- `236903cf-055a-40a8-8923-b9d06601f3b7` / edge `5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:1152927002165035802` / `RELATED_TO`
  - 舊：PLACE應與第七十九條規定之灌氣容器放置場所分設厚度十二公分以上鋼筋混凝土造或具有同等以上強度結構之防護牆。
  - 新：使用每平方公分一百公斤以上之壓力灌注壓縮氣體於容器之場所 與第七十九條規定之灌氣容器放置場間 應分設厚度在十二公分以上鋼筋混凝土造或具有與此同等以上強度結構之防護牆
- `236903cf-055a-40a8-8923-b9d06601f3b7` / edge `5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:1152927002165037197` / `RELATED_TO`
  - 舊：Service為FUND來源。
  - 新：服務收入為經費來源。
- `236903cf-055a-40a8-8923-b9d06601f3b7` / edge `5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:1152927002165040978` / `RELATED_TO`
  - 舊：經中央主管機關指定之PRODUCT應對其全長依中央主管機關規定之方法實施TEST。
  - 新：經中央主管機關指定者應對其全長依中央主管機關規定之方法實施放射線檢查。
- `236903cf-055a-40a8-8923-b9d06601f3b7` / edge `5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:1152927002165022256` / `RELATED_TO`
  - 舊：根據國家標準CNS15030分類，屬於致癌物質第一級、生殖細胞致突變性物質第一級或生殖毒性物質第一級的化學品（PRODUCT）應優先管理。
  - 新：(跳過：latest_citation_verb_missing)
- `236903cf-055a-40a8-8923-b9d06601f3b7` / edge `5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:1152927002165040460` / `RELATED_TO`
  - 舊：PLACE 由金屬構材組成之室外升降機升降路塔或導軌支持塔所使用的鋼構為第一項所定之 PRODUCT 。
  - 新：(跳過：latest_citation_verb_missing)

## T2 狀態

本輪停在 T1；沒有執行任何 backfill 寫入。需人工審閱本 dry-run 後另行核准。
