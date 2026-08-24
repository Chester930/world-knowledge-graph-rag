# World Knowledge Graph RAG 論文與產品架構交接文件

> 更新日期：2026-08-24
>
> 用途：提供 Claude Code 接續本次對話與文件整理工作。本文是工作交接紀錄，不是正式論文正文。

## 1. 專案與論文定位

本專案不是單純學術型論文，而是：

> **World Knowledge Graph RAG 完整產品架構與實作方法的對標論文。**

論文需要同時記錄：

1. 完整產品架構。
2. 產品能力背後的理論與文獻依據。
3. 研究問題（RQ）與驗證方法。
4. 實際程式模組、檔案位置與測試。
5. 尚未完成的產品功能與未來研究路線。

重要原則：

- 產品模組不必全部變成研究問題。
- RQ 是產品能力中的學術驗證軸，不等於產品全部功能。
- 有程式底層機制，不代表 RQ 已完成正式驗證。
- 只有設計文件，不得在第四章宣稱為已實作。

## 2. 論文章節分工

| 文件 | 正確職責 |
|---|---|
| `01_緒論.md` | 說明研究背景、問題缺口、RQ、貢獻、研究與產品範圍 |
| `02_文獻探討.md` | 分成兩部分：一是對應 01 RQ 的理論文獻，二是對應 03 方法與產品模組的文獻佐證；不是單純介紹完整產品 |
| `03_系統設計與方法論.md` | 說明 RQ 如何執行、方法、架構、流程、設計理由與限制 |
| `04_系統實作.md` | 將第三章方法對應到實際專案程式、檔案位置、API、資料模型、測試與目前實作邊界 |
| `05_實驗設計與評估.md` | 定義資料集、baseline、消融組別、評估指標與實驗流程；目前仍是主要缺口 |
| `06_結果與討論.md` | 等第五章實驗完成後填寫，目前為空白大綱 |
| `07_結論與未來工作.md` | 等實驗與結果完成後撰寫，目前為大綱 |
| `附錄與參考文獻.md` | 保存完整書目、來源查核、本地 PDF 與附錄；已有實質內容，但正式格式與正文交叉檢查尚未完成 |

## 3. 目前 RQ 狀態

| RQ | 主題 | 目前狀態 |
|---|---|---|
| RQ1 | KG-BFS 與純向量／當代 RAG 的任務依賴性差異 | BFS＋Fact 檢索已有接線；正式 baseline 與比較實驗未完成 |
| RQ2 | 多知識庫路由的效能與取捨 | ConceptNode 向量索引基礎存在；`route_kgs()` 尚未完成，正式路由未完成 |
| RQ3 | 自我精煉檢索是否降低幻覺 | 有 confidence、bounded BFS、Fact 檢索等基礎；尚無「評估→改變檢索→再次生成」迴圈 |
| RQ4a | 受控關係詞彙標準化與未知型別治理 | `SVO_REL_TYPES`、cosine 比對、LLM 仲裁、`EXPAND` 工程機制已有；正式消融實驗未完成 |
| RQ4b | 實體指代、別名與跨文件對齊 | 別名、`HAS_ENTITY`、`RECHECK` 等機制與測試已有；NER 上游與正式端到端流程仍有限制 |
| RQ5 | 事實時序保留與查詢過濾 | 只有一般系統時間戳；Fact／關係有效起訖、衝突偵測與時態查詢尚未實作 |
| RQ6 | Hub Node 向量引導圖剪枝 | 目前只有 BFS hops／候選數限制；Hub 偵測與向量剪枝尚未實作 |

狀態定義：

- **已實作**：程式入口與測試可核對。
- **部分實作**：底層機制存在，但正式流程、上游接線或端到端研究功能尚未完成。
- **設計預留**：01–03 有設計與文獻，但沒有可執行完整程式入口。
- **已驗證**：已完成正式資料集、比較實驗與結果分析；單元測試不等於已驗證。

## 4. RQ4a 的重要定案

曾經評估過的設計：

```text
STRUCT（結構驗證）→ SEMANTIC（語意驗證）
```

此設計已於 2026-07-24 放棄，不是尚未實作，而是設計本身已變更。

目前正式描述應統一為：

```text
ConceptNet 33 類受控關係型別
→ cosine 相似度比對
→ 灰色地帶 LLM 仲裁
→ EXPAND 治理與人工審核
```

Schema.org 與 Wikidata 的角色：

- 是受控詞彙、資料治理與來源追溯的文獻錨點。
- 不是目前 `STRUCT → SEMANTIC` runtime 的直接實作依據。
- ConceptNet 33 類是目前關係型別內容的實際起始依據。

不要再把「結構驗證→語意驗證」寫成現行 RQ4a 方法；只能在變更紀錄中作為已放棄方案保存。

## 5. 完整產品架構

產品分為七層：

1. 多型態資料輸入與文件處理。
2. 知識建構。
3. 語意與知識治理。
4. 儲存、索引與背景處理。
5. 多知識庫管理與路由。
6. GraphRAG 檢索與生成。
7. 產品介面與評估。

RQ 與產品模組是多對多關係：

- RQ1：GraphRAG 檢索。
- RQ2：多 KG 路由。
- RQ3：自我精煉。
- RQ4a／RQ4b：知識治理。
- RQ5：時序管理。
- RQ6：圖剪枝。
- 文件解析、背景 Worker、API、前端、資料來源管理等產品工程能力，不必強行新增 RQ。

## 6. 多型態資料來源的產品設計定案

### 6.1 設計原則

JSON、資料庫、API、RDF／KG 等來源不可先全部轉成自然語言，再把自然語言當成唯一真實來源。

必須保留：

- 原始內容。
- JSON path／欄位路徑。
- 主鍵／外鍵。
- 資料型別。
- 陣列、巢狀結構與 null。
- 單位與時間欄位。
- 來源版本與匯入時間。

`TextProjection` 只能作為文字檢索與 LLM context 的輔助表示。

### 6.2 四層資料模型

```text
RawSnapshot
  → SourceSchema
    → MappingPlan
      → CanonicalRecord
        → Entity / Event / Observation / Relation / Attribute / Value / Provenance
          → TextProjection
            → KG／向量索引
```

### 6.3 設計中的持久化位置

| 物件 | 規劃位置 | 狀態 |
|---|---|---|
| `RawSnapshot` | `data/source_snapshots/{source_id}/{snapshot_id}/raw`，metadata 進 `source_registry.db` | 尚未實作 |
| `SourceSchema` | `source_registry.db.source_schemas` | 尚未實作 |
| `MappingPlan` | `source_registry.db.mapping_plans` | 尚未實作 |
| `ValidationReport` | `source_registry.db.validation_reports` | 尚未實作 |
| `CanonicalRecord` | `source_registry.db.canonical_records`，以 JSON 保存 | 尚未實作 |
| `TextProjection` | Neo4j `Chunk`／`Fact` 與向量索引 | 尚未實作於結構化來源路徑 |
| Entity／Fact／Relation | Neo4j | 文件來源已有部分實作 |

這是 SDD 目標配置，不是現有程式已建立的資料表或 API。

### 6.4 統一介面

```text
SourceAdapter.read(config) -> RawSnapshot
SchemaProfiler.profile(snapshot) -> SourceSchema
SchemaRegistry.register(schema) -> schema_version
MappingPlanner.propose(schema, target_namespace) -> MappingPlan
MappingValidator.validate(snapshot, mapping_plan) -> ValidationReport
MappingRegistry.approve(mapping_plan, reviewer) -> approved_mapping_version
Projector.project(snapshot, mapping_plan) -> CanonicalRecord[] + TextProjection[]
KnowledgeWriter.commit(records, provenance) -> KGCommitReport
```

Adapter 不得直接寫 Neo4j；只有 `KnowledgeWriter` 可以把通過驗證與治理的 canonical records 寫入 KG。

### 6.5 來源處理狀態機

```text
RECEIVED
→ SNAPSHOTTED
→ PROFILED
→ MAPPING_PROPOSED
→ VALIDATED
→ APPROVED
→ PROJECTED
→ GOVERNED
→ KG_COMMITTED
```

未知欄位進入 `UnknownAttribute`／`REVIEW_REQUIRED`；錯誤必須保留 snapshot 與 validation report，不得靜默丟失資料。

## 7. 已完成的文件調整

本次已調整或補充：

- `docs/論文/00_README.md`
- `docs/論文/01_緒論.md`
- `docs/論文/02_文獻探討.md`
- `docs/論文/03_系統設計與方法論.md`
- `docs/論文/03_變更紀錄.md`
- `docs/論文/04_系統實作.md`
- `docs/論文/附錄與參考文獻.md`
- `docs/ARCHITECTURE.md`
- `docs/論文/00_研究追溯對映表.md`
- `docs/論文/文獻與專案查核表.md`
- `docs/參考文獻/15_多型態資料來源與結構保留/README.md`

第四章現在已加入產品模組與研究追溯對映表，內容包含：

```text
產品模組 → RQ → 第三章方法 → 實際程式 → 測試／狀態
```

## 8. 文獻與專案查核狀態

目前的文獻與專案查核文件：

- `docs/論文/文獻與專案查核表.md`
- `docs/論文/附錄與參考文獻.md`
- `docs/參考文獻/*/README.md`

已確認並納入對映的方向包括：

- GraphRAG、KG-RAG、PathRAG、CatRAG。
- Self-RAG、FLARE、IRCoT。
- Schema.org、Wikidata、ConceptNet。
- Text2KGBench、CORE-KG、CESI。
- HotpotQA、Ragas。
- JSON-LD、R2RML、Direct Mapping、SHACL、PROV-O、Data on the Web Best Practices、JSON Schema。

多型態來源標準目前是「官方連結已查證，部分沒有本地 PDF」，不能寫成已下載或已全文精讀。標準文件是設計依據，不代表本專案已採用其 runtime。

## 9. 目前尚未完成的主要工作

### 優先級 A：論文狀態

1. 決定是否將多型態資料來源納入第五章實驗。
2. 確定第五章資料集：HotpotQA、自建資料集或混合方案。
3. 鎖定 RQ1–RQ3 的正式 baseline 與消融組別。
4. 完成 chunk size 與分類門檻校準。
5. 建立實驗 manifest、結果輸出與重現流程。

### 優先級 B：產品 SDD

1. 確定 `source_registry.db` 是否採 SQLite，以及實際檔案位置。
2. 設計 JSON Source Adapter 第一版。
3. 設計 JSON Schema／nested object／array／null 的 MappingPlan 格式。
4. 設計 SQL primary key／foreign key 的 canonical identity mapping。
5. 定義 provenance 在 Neo4j 節點與關係上的實際欄位。
6. 建立 schema version 與 mapping migration 規則。
7. 建立 JSON fixture、錯誤案例與 provenance round-trip 測試。

### 優先級 C：真正開始程式實作

目前尚未建立：

- `SourceAdapter` 程式模組。
- `SchemaProfiler` 程式模組。
- `SchemaRegistry` 儲存與 API。
- `MappingPlan` 執行器。
- `RawSnapshot` object store。
- `CanonicalRecord` 持久化。
- 結構化來源的 `TextProjection` 與 KG writer。

## 10. 建議 Claude Code 的接續順序

請依以下順序接續，不要直接跳到大量實作：

1. 先閱讀本交接文件。
2. 閱讀 `docs/論文/00_研究追溯對映表.md`。
3. 閱讀 `docs/論文/04_系統實作.md` 的 4.0 對映表。
4. 閱讀 `docs/ARCHITECTURE.md` 的 H 節。
5. 先提出 JSON Adapter 的最小資料模型與 MappingPlan 草案。
6. 確認 `source_registry.db` 的持久化方案後再修改程式。
7. 第一階段只實作 JSON fixture，不同時實作 SQL、API、RDF 全部來源。
8. 每個程式模組都要同步更新 03、04、追溯表與測試。
9. 若尚未有端到端測試，不得在 04 寫成已完成產品能力。

## 11. 驗證紀錄

- 文件檢查：`git diff --check` 通過。
- 先前完整 Python 測試：`466 passed, 6 warnings`。
- 本階段主要是文件與 SDD 調整，沒有新增結構化來源程式，因此不應把 SDD 視為測試已通過。

## 12. 給 Claude Code 的重要限制

- 不要重新引入已放棄的 `STRUCT → SEMANTIC` 現行方法描述。
- 不要把 JSON／SQL／API 支援寫成已完成。
- 不要把文獻存在性、GitHub repository 存在性誤寫成「本專案已採用」或「本專案已執行」。
- 不要把單元測試通過寫成 RQ 已完成驗證。
- 任何新設計都要標示「設計預留」或「尚未實作」。
- 修改文件時，保持 01 → 02 → 03 → 04 → 05 的章節責任分工。
