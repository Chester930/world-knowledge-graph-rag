# 報告209：K2 Phase 0 派生報表與標示基準線

> **日期**：2026-10-01
> **性質**：執行報告；只讀查詢與純運算，不把派生結果寫回 KG。
> **依據**：[報告207](207_下一階段任務規劃_註解更正與Phase0派生報表與標註材料.md) §3.2、[報告201](201_未知不適用尚未處理標示設計方案.md)、[報告208](208_K2K3接手筆記.md)。
> **資料**：KG#4 `236903cf-055a-40a8-8923-b9d06601f3b7`，`bolt://localhost:17990`；密碼未寫入本報告。

## 1. 本次做了什麼

本次重跑 `scripts/analysis/phase0_marking_baseline.py`，輸出暫存結果後，與既有 `docs/報告/208_K2_phase0_raw結果.json` 逐行比對，`Compare-Object` 沒有輸出差異。原始結果檔保留為 [208_K2_phase0_raw結果.json](208_K2_phase0_raw結果.json)；腳本重用 `scripts/analysis/semantic_layer_invariants.py` 的 `ReadOnlyRunner`、`assert_read_only()`、`classify_type_tokens()` 與總數檢查。

匯入腳本沒有改 `os.environ`，也沒有在匯入階段載入 `neo4j`、`core` 或 `services`。每一條 Cypher 先經既有 `assert_read_only()`；每次 query session 由 `ReadOnlyRunner` 以 `default_access_mode="READ"` 建立。沒有啟動 Ollama／WSL、沒有呼叫 LLM／embedding、沒有寫入 KG。

報告208 已記錄開始前其他 peer 為 idle／offline、無人使用同一 Neo4j／Ollama。本次工具環境沒有提供可再次呼叫 `ListAgents` 的介面，因此這裡只沿用該既有紀錄，不把它寫成此次新增的獨立 peer 查詢。

## 2. 前後總數

| 時點 | 節點 | 關係 | Fact | Entity |
| --- | ---: | ---: | ---: | ---: |
| 查詢前 | 57,451 | 137,873 | 16,826 | 12,296 |
| 查詢後 | 57,451 | 137,873 | 16,826 | 12,296 |

腳本輸出 `totals_identical: True`。總數是查詢前後各執行一次 `MATCH` 計數的結果。

```cypher
MATCH (n) RETURN count(n) AS v
MATCH ()-[r]->() RETURN count(r) AS v
MATCH (f:Fact {kg_id: $k}) RETURN count(f) AS v
MATCH (e:Entity {kg_id: $k}) RETURN count(e) AS v
```

## 3. 四個對象的派生數字

三種標示的操作型定義沿用報告201 §0：**不適用**＝空是對的；**未知**＝空是缺的；**尚未處理**＝空是暫時的。本報告只從現有值做派生，不替使用者決定欄位名、值域或資料回填方式。

### 3.1 實體型別

母體為 12,296 個 Entity；分類以實體數計：標準型別 2,481、空值 805、schema.org 之外原字串 987、「概念」單獨出現 8,023；標準＋概念混合為 0。

```cypher
MATCH (e:Entity {kg_id: $k}) RETURN e.type AS t, count(*) AS n
MATCH (e:Entity {kg_id: $k}) WHERE e.type = '概念' RETURN count(*) AS v
```

| 現值分類 | 數量 | Phase 0 嚴格處理 |
| --- | ---: | --- |
| 標準（核心 52／擴充 939） | 2,481 | 已解決 |
| 空值 | 805 | 未知 |
| schema.org 之外原字串 | 987 | 尚未處理（但無法只靠原值分辨「尚未對應」與「已判定非 schema.org」） |
| `概念` 單獨值 | 8,023 | 無法由現有資料判定 |

「概念」不替使用者選，並列兩種算法：

| 算法 | 未知 | 已解決 | 尚未處理 | 不適用 | 無法由現有資料判定 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 嚴格：概念維持不可判定 | 805 | 2,481 | 987 | 0 | 8,023 |
| **A：視為未知佔位** | **8,828** | 2,481 | 987 | 0 | 0 |
| **B：視為真的概念（已解決）** | 805 | **10,504** | 987 | 0 | 0 |

### 3.2 關係型別

母體為 16,826 個 Fact。

```cypher
MATCH (f:Fact {kg_id: $k})
RETURN f.rel_type AS t, trim(coalesce(f.verb, '')) = '' AS ev, count(*) AS n

MATCH (s:Entity {kg_id: $k})-[r]->(o:Entity {kg_id: $k})
WHERE r.citations_json IS NOT NULL
RETURN type(r) AS t, r.verb_embedding IS NOT NULL AS ve, count(*) AS n
```

| 分類 | 數量 | Phase 0 含意 |
| --- | ---: | --- |
| 非 `RELATED_TO` | 1,832 | 可確定為已解決的詞彙內型別 |
| `RELATED_TO` 且 `verb` 非空 | 14,447 | 來源不明 |
| `RELATED_TO` 且 `verb` 為空 | 547 | 來源不明 |
| `rel_type` 為 NULL | 0 | — |

因此嚴格口徑是「已解決 1,832；來源不明 14,994」，或把 `RELATED_TO` 一律視為「未知（來源不明）」的報表算法；兩者都不表示 `RELATED_TO` 一定是錯誤。

邊上的 `verb_embedding` 只作分布描述，不能當作兜底專屬旗標：`RELATED_TO` 有 11,818 條邊帶有、503 條沒有；其他型別 0 條帶有、1,700 條沒有。這裡的 `verb_embedding` 查詢也是上方第二段 Cypher。

### 3.3 `source_article_no`

母體為所有事實邊 `citations_json` 的 16,826 筆引用；判定在文件層，不使用哨兵字串。

```cypher
MATCH (s:Entity {kg_id: $k})-[r]->(o:Entity {kg_id: $k})
WHERE r.citations_json IS NOT NULL
RETURN r.citations_json AS c

MATCH (f:Fact {kg_id: $k})-[:SUPPORTED_BY]->(t)
RETURN labels(t)[0] AS l, count(*) AS n ORDER BY n DESC

MATCH (d:Document {kg_id: $k})
RETURN d.record_type AS rt, count(*) AS n
```

| 文件層派生分類 | 引用數 |
| --- | ---: |
| 已知（有條號） | 16,773 |
| 不適用（整份文件沒有條號） | 53 |
| 未知（適用條號的文件中缺值） | 0 |

補充：65 個來源文件中 64 個至少有一個 `article_no`；KG 內 64 個 `Document` 的 `record_type` 都是 `law`。Fact 的 `SUPPORTED_BY` 目標為 `LawArticle` 16,773、`Chunk` 53；這是目標標籤分布，不把 `Chunk` 寫成唯一目標。

### 3.4 空欄位

```cypher
MATCH (f:Fact {kg_id: $k})
RETURN trim(coalesce(f.subject, '')) = '' AS es,
       trim(coalesce(f.object, '')) = '' AS eo,
       trim(coalesce(f.verb, '')) = '' AS ev,
       count(*) AS n

MATCH (f:Fact {kg_id: $k})
RETURN sum(CASE WHEN f.subject IS NULL THEN 1 ELSE 0 END) AS null_subject,
       sum(CASE WHEN f.object IS NULL THEN 1 ELSE 0 END) AS null_object,
       sum(CASE WHEN f.verb IS NULL THEN 1 ELSE 0 END) AS null_verb
```

| 項目 | 數量 |
| --- | ---: |
| 空受詞 | 4,764 |
| 空 `verb` | 636 |
| 空主詞 | 59 |
| 至少一個空欄位 | 5,281 |
| 空受詞且空 `verb`（不論主詞） | 145 |
| NULL 主詞／受詞／verb | 0／0／0；實際是空字串 |

八種交集如下：

| 空主詞 | 空受詞 | 空 verb | Fact |
| ---: | ---: | ---: | ---: |
| 否 | 否 | 否 | 11,545 |
| 否 | 否 | 是 | 482 |
| 否 | 是 | 否 | 4,597 |
| 否 | 是 | 是 | 143 |
| 是 | 否 | 否 | 26 |
| 是 | 否 | 是 | 9 |
| 是 | 是 | 否 | 22 |
| 是 | 是 | 是 | 2 |

嚴格 Phase 0 派生：空受詞且空 `verb` 的 145 筆列為「未知（可由現有欄位確定需要進一步處理）」；其餘有任一空欄位的 5,136 筆列為尚未處理，需人工／LLM 才能分辨不適用與未知。

## 4. 三個口徑差異（必讀）

1. **「其餘 4,619」與本次「需人工 5,136」不是同一母體。**「其餘 4,619」只看空受詞且 `verb` 非空：4,597（主詞非空／受詞空／`verb` 非空）＋22（主詞也空／受詞空／`verb` 非空）。本次 5,136 的母體是「至少一個空欄位且不是空受詞＋空 `verb`」；它另外包含空 `verb` 但有受詞者（482＋9＝491），以及只空主詞者（26），所以不能把 5,136 寫成報告200 的「只剩空受詞」。
2. **987 是實體數，不是型別 token 種數。**本次 987 指「含至少一個 schema.org 之外原字串 token 的 Entity 數」；報告201 的 **235 種**是另一個口徑（不同原字串 token 的種類數）。兩者不可相減或直接比較。
3. **「概念」有兩種算法。**A 視為未知，未知＝**8,828**；B 視為真的概念（已解決），已解決＝**10,504**。本報告並列，沒有替使用者選擇。

> 第 1 點中的「4,597＋22」兩項都屬空受詞且 `verb` 非空；22 同時有空主詞。5,136＝4,619＋491＋26。這裡特別把公式與較寬母體分開寫，避免把不同口徑混用。

## 5. 標示基準線

「已有明確標示」的 0 件，是以腳本掃描 Entity／Fact／邊／Chunk／LawArticle／Document／Sentence 的屬性鍵名稱候選（`status`／`state`／`origin`／`scope` 等）結果為空；這是鍵名粗篩的證據，不是對所有可能語意的形式化證明。四個對象的基準線如下：

| 對象／母體 | 已有明確標示 | 可由現有資料唯讀推算 | 需人工／LLM | 已標示比例 | 可推算比例 | 需人工／LLM 比例 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 實體型別／12,296（嚴格） | 0 | 4,273 | 8,023 | 0% | 34.75% | 65.25% |
| 關係型別／16,826（嚴格） | 0 | 1,832 | 14,994 | 0% | 10.89% | 89.11% |
| `source_article_no`／16,826 引用 | 0 | 16,826 | 0 | 0% | 100% | 0% |
| 空欄位／5,281 個至少一空的 Fact | 0 | 145 | 5,136 | 0% | 2.75% | 97.25% |

實體型別的 4,273＝2,481 標準＋805 空值＋987 原字串；「概念」8,023 不納入嚴格可推算而列需人工／LLM。空欄位基準線的母體不是全部 Fact；完整的 11,545 個 Fact 不需要空欄位標示。

## 6. 執行限制與偏離

- 本次只產出派生 JSON／本報告，沒有回寫資料、沒有重建／清空 KG#4。
- `outside_raw` 對應「尚未處理」是報告201 §1.2 的操作型派生；報告201 §1.1 同時說明，僅靠原字串無法區分尚未標準化與已判定非 schema.org。
- `RELATED_TO` 的 14,994 筆不能由現有資料分辨「LLM 刻意選的一般關聯」與各種兜底來源；本報告沒有替它們選一種來源。
- 「概念」的 A／B 不是兩次資料變更，只是同一批 8,023 筆的兩個報表假設。
- 報告207 要求的全量 pytest 重跑不在本報告的查詢步驟內，將在階段彙整與提交前記錄。

## 7. 本報告使用的新增檔案與重算方式

- 腳本：[phase0_marking_baseline.py](../../scripts/analysis/phase0_marking_baseline.py)
- 單元測試：[test_phase0_marking_baseline.py](../../tests/scripts/test_phase0_marking_baseline.py)
- 原始 JSON：[208_K2_phase0_raw結果.json](208_K2_phase0_raw結果.json)

重算命令（需要本機既有 `.env`；不把密碼放在命令列或輸出）：

```powershell
python scripts/analysis/phase0_marking_baseline.py --env-file .env --out <output.json>
```

執行輸出所見：前後總數相同；輸出 JSON 與既有 208 原始結果逐行比對沒有差異。
