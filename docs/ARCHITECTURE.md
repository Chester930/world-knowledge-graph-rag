# 架構設計紀錄

本文件記錄 v2 相較於 [v1](https://github.com/Chester930/knowledge-base-ai) 的架構決策與理由，供論文撰寫時追溯。

## 待決議事項

- [ ] 分層方式：是否採用明確的 domain / infrastructure / interface 分層
- [ ] SVO 提取邏輯的模組邊界與依賴注入方式
- [ ] 路由層（ConceptNode）與圖遍歷層（BFS）的介面設計
- [ ] 測試策略：單元測試與整合測試的分工
- [ ] 多型態資料來源的 Source Adapter／Schema Mapping Registry 詳細介面
- [ ] Raw Snapshot、Source Schema、Canonical Record 與 KG 節點的持久化位置
- [ ] 結構化資料的自然語言投影是否只作為輔助檢索表示，不作為唯一真實來源

## SDD 調整任務：完整產品架構與多型態資料來源（2026-08-24）

> 狀態：🟡 已完成架構討論，尚未進入程式實作。本節記錄 2026-08-24 與使用者確認的產品型 SDD 調整方向，作為後續 01–04 章與程式架構的共同依據。

### A. 產品定位與正式架構基準

- [x] 產品最高層定位確定為：**World Knowledge Graph RAG 的完整產品架構與實作方法**。
- [x] 研究問題是產品能力中的學術驗證軸，不等同於產品全部功能。
- [x] 正式產品模組分為七層：
  1. 多型態資料輸入與文件處理
  2. 知識建構
  3. 語意與知識治理
  4. 儲存、索引與背景處理
  5. 多知識庫管理與路由
  6. GraphRAG 檢索與生成
  7. 產品介面與評估
- [x] RQ 與產品模組的關係採多對多：RQ1 對應 GraphRAG 檢索，RQ2 對應多 KG 路由，RQ3 對應自我精煉，RQ4a／RQ4b 對應知識治理，RQ5 對應時序管理，RQ6 對應圖剪枝；其餘產品工程模組不必強行轉成 RQ。

### B. 第一層資料輸入的架構修正

- [x] 第一層不再只定義為文件／自然語言輸入，而是**多型態資料輸入與結構保留式處理**。
- [x] 產品需預留非結構化資料、半結構化資料、結構化資料、API 與既有 KG／RDF 等來源類型。
- [x] 結構化資料不得先全部轉成自然語言再建圖；自然語言只能是輔助投影，不能取代原始結構。
- [x] 不採用所有情境共用一個固定業務欄位 schema；不同資料集保留各自的 Source Schema，再透過 Canonical Semantic Layer 對接產品 KG。

### C. 四層資料保留模型

- [x] **Raw Layer（SDD 已定義，尚未實作）**：保存原始 JSON、資料表、API response、文件、版本、來源位置與匯入時間。
- [x] **Source Schema Layer（SDD 已定義，尚未實作）**：保存來源欄位、巢狀路徑、型別、主鍵／外鍵、欄位描述與 schema 版本。
- [x] **Canonical Semantic Layer（SDD 已定義，尚未實作）**：以少量可擴展的語意類型表達 `Entity`、`Event`、`Observation`、`Document`、`Relation`、`Attribute`、`Value` 與 `Provenance`，不強迫所有領域共用相同業務欄位。
- [x] **Knowledge Graph Layer（SDD 已定義，現有 KG 基礎已實作）**：將已驗證的語意記錄映射為 Entity、Fact、Relation、Citation、時間欄位與向量索引；多型態來源的完整映射尚未實作。
- [x] 所有層的追溯欄位已定義：`source_id`、`snapshot_id`、`record_id`、`source_path`／`json_path`、schema version 與原始資料關係；尚未建立對應完整資料表。

### D. Schema Mapping Registry 任務

- [x] 設計 `Source Adapter` 介面，隔離 JSON／JSON API、SQL／資料庫、CSV／XML、文件與既有 KG 的讀取差異；尚未建立可執行 adapter。
- [x] 設計 `Schema Profiler`，自動分析欄位名稱、型別、巢狀結構、主鍵／外鍵候選、單位與時間欄位；尚未實作 profiler。
- [x] 設計 `Schema Registry`，保存每個資料來源的 schema、版本與變更歷史；尚未建立 registry 儲存。
- [x] 設計 `Mapping Plan`，記錄 source field／path 到 canonical type／property／relation 的映射、identity key、value type、unit 與 confidence；尚未建立 mapping 執行器。
- [x] 設計 `Validation Layer`，檢查型別、必要欄位、主鍵、外鍵、單位、時間格式與映射結果；尚未建立驗證器。
- [x] 對未知或無法確認的欄位，先保存為 `UnknownAttribute` 或待審核項，不靜默丟棄，也不強行生成自然語言事實。
- [x] LLM 只能提出 schema／mapping 建議，最後需經規則驗證與人工確認，並將核准結果寫入 Registry；此為設計規則，尚未實作審核流程。

### E. 雙軌表示與建圖任務

- [x] 結構化來源走 `Source Schema → Canonical Record → Entity／Fact／Relation` 路徑；尚未實作。
- [x] 非結構化來源走 `Parser → Chunk → SVO／Entity／Relation` 路徑；目前已有部分實作。
- [x] 兩條路徑最後共用語意治理、Fact 去重、Citation 與 KG 儲存，但不得在前端輸入階段互相覆蓋原始表示。
- [x] 額外建立 `TextProjection` 供 LLM／文字檢索使用，並與 `source_record_id`、schema path、Fact／Chunk 建立雙向追溯；尚未實作。
- [x] 已定義 JSON nested object、SQL primary／foreign key、陣列、null、boolean、數值單位與時間欄位的映射原則；尚未實作各來源 adapter。

### F. 論文章節同步調整任務

- [ ] 01 緒論：將「多型態資料輸入與結構保留」納入完整產品能力架構與產品範圍。
- [x] 02 文獻探討：第一版已補充 JSON-LD／RDF、relational-to-KG mapping、SHACL、PROV-O、Data on the Web Best Practices 與 JSON Schema 的佐證；schema-aware integration 的產品化細節仍待後續擴充，本章只說明為什麼，不詳細介紹程式架構。
- [x] 03 系統設計與方法論：已新增 Source Adapter、Schema Profiler、Schema Registry、Mapping Plan、Raw Snapshot、Canonical Record、雙軌投影、持久化位置與驗證流程的設計細節；仍未進入程式實作。
- [ ] 04 系統實作：待 SDD 定案後，記錄實際 adapter、資料模型、mapping 設定、驗證流程、API 與測試；在此之前不得宣稱結構化資料匯入已完成。
- [ ] 05 實驗設計與評估：未來若納入，增加異質資料來源的 schema mapping 成功率、人工修正成本、型別保留率、來源可追溯率與建圖品質指標。

### G. 暫不執行範圍

- [x] 本次只記錄 SDD 調整任務，不立即實作 JSON／SQL adapter。
- [x] 不因異質資料來源議題立即新增 RQ；先作為完整產品架構的必要能力，待方法與評估指標成熟後再判斷是否形成新的研究問題。
- [x] 不把範例資料集當成唯一 schema；範例資料集後續應改作不同 Source Schema 與 Mapping Plan 的測試案例。

### H. 多型態來源 SDD 詳細定義（2026-08-24）

> 本節是設計決策，不代表程式已完成。`[x]` 表示 SDD 規則已定義；實作狀態仍以第四章與追溯表為準。

#### H.1 持久化分工

| 物件 | 設計位置 | 保存內容 | 目前狀態 |
|---|---|---|---|
| `RawSnapshot` | 本地 immutable object store：`data/source_snapshots/{source_id}/{snapshot_id}/raw`；metadata 進 `source_registry.db` | 原始內容、checksum、來源位置、匯入時間、來源版本 | 尚未實作 |
| `SourceSchema` | `source_registry.db.source_schemas` | 欄位／路徑、型別、陣列與巢狀結構、PK／FK 候選、schema version | 尚未實作 |
| `MappingPlan` | `source_registry.db.mapping_plans` | 映射規則、identity key、轉換、confidence、審核狀態與版本 | 尚未實作 |
| `ValidationReport` | `source_registry.db.validation_reports` | 錯誤、警告、未知欄位、檢查器版本與結果 | 尚未實作 |
| `CanonicalRecord` | `source_registry.db.canonical_records`，以 JSON 保存原始 canonical payload；通過治理後再寫入 Neo4j | `record_id`、canonical type、properties、provenance、mapping version | 尚未實作 |
| `TextProjection` | Neo4j `Chunk`／`Fact` 節點與既有向量索引 | 投影文字、`source_record_id`、source path、mapping version、projection version | 尚未實作 |
| KG record | Neo4j | Entity、Fact、Relation、Citation、時間與向量索引 | 現有文件路徑已有部分實作 |

設計原則是「原始內容與結構化 metadata 可重建、canonical record 可追溯、文字投影可重算」。不得只保存 TextProjection 而刪除 RawSnapshot 或 SourceSchema。

#### H.2 介面契約

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

所有輸出都必須帶有 `source_id`、`snapshot_id`、`record_id`、`schema_version`、`mapping_version` 與 `provenance_id`。Adapter 不得直接呼叫 Neo4j；`KnowledgeWriter` 是唯一負責把通過驗證的 canonical records 寫入 KG 的邊界。

#### H.3 來源處理狀態機

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

任何階段失敗都保存 `ValidationReport` 或 `IngestionError`，並保留原始 snapshot；未知欄位進入 `UnknownAttribute`／`REVIEW_REQUIRED`，不得靜默丟失。只有 `APPROVED` 的 MappingPlan 才能進入 `PROJECTED`，只有通過 canonical／provenance 檢查的資料才能進入 `KG_COMMITTED`。

#### H.4 最小 API 草案

| API | 作用 | 狀態 |
|---|---|---|
| `POST /sources` | 建立來源設定與來源類型 | SDD，尚未實作 |
| `POST /sources/{source_id}/snapshots` | 建立不可變 snapshot | SDD，尚未實作 |
| `POST /schemas/{schema_id}/mapping-plans:propose` | 產生 mapping 建議 | SDD，尚未實作 |
| `POST /mapping-plans/{id}:validate` | 執行規則驗證 | SDD，尚未實作 |
| `POST /mapping-plans/{id}:approve` | 人工核准 mapping version | SDD，尚未實作 |
| `POST /ingestions/{id}:run` | 執行投影與建圖 | SDD，尚未實作 |
| `GET /records/{record_id}/provenance` | 查詢來源、路徑、版本與投影關係 | SDD，尚未實作 |

#### H.5 測試與驗收條件

- 同一 snapshot 與同一 MappingPlan 必須產生 deterministic 的 CanonicalRecord。
- 任一 CanonicalRecord 必須可追溯回 `source_id`、snapshot、source path／JSON path 與 mapping version。
- 未知欄位不可消失，必須進入 `UnknownAttribute` 或人工審核狀態。
- TextProjection 被修改或重建時，不得改寫 RawSnapshot。
- schema version 變更時，舊 MappingPlan 必須保留，不能靜默覆寫歷史版本。
- JSON、SQL、CSV／XML、RDF 各至少需要一組 fixture、失敗案例與 provenance round-trip 測試。

## 決策紀錄

### 執行環境架構：本地抽取 + 雲端閘道（2026-07-10）

- **決策**：知識抽取（SVO 三元組）完全在使用者本地執行，問答生成則走雲端輕量模型；後端角色收斂為「對接管道」（Ingestion Gateway），負責實體對齊/去重與命名空間隔離，不再負擔抽取算力。
- **理由**：解決雲端 LLM 抽取的高額 Token 成本與批次任務中斷風險，同時保護使用者原始文件隱私（不需上傳雲端做抽取）。
- **細節**：本地模型分三檔（`Qwen-2.5-1.5B` 輕量 / `Qwen-2.5-7B` 平衡 / `GLiNER`+`REBEL` 極致低配）；Electron 主行程作為背景 Daemon，SQLite 任務隊列（`pending`/`processing`/`completed`/`failed`/`pending_upload`）支援斷點續傳。
- **完整規格**：見 `docs/報告/01_本地抽取與混合架構評估.md`

### 知識圖譜 Schema：雙層圖結構（Lexical + Entity Graph）（2026-07-10；2026-07-23 補齊佐證熱度指標）

- **決策**：Neo4j 中新增 `:Chunk` 節點與 `(Chunk)-[:HAS_ENTITY]->(Entity)` 邊，讓每個抽取出的實體都能反向追溯到原始文字片段。
- **理由**：解決「回答無法標明來源」的可解釋性缺口，對應論文 1.1.4 節「可解釋知識問答」的產品目標。
- **學術支撐**：Gutiérrez et al. (2024) *HippoRAG*，NeurIPS'24（詳見 `docs/報告/技術導入評估.md` 第一項）。**熱度佐證（2026-07-23 查證）**：官方程式碼 `OSU-NLP-Group/HippoRAG` 3,882★（GitHub API 查證）；正式出版版本（NeurIPS 2024 Proceedings）被引用 54 次（OpenAlex 查證，可能低估——多篇後續論文引用的是 arXiv 預印本而非正式出版版本，兩者在部分資料庫中分開計數）。**⚠️ 誠實侷限**：HippoRAG 全文 PDF 已存在於 `docs/參考文獻/12_三元組事實層級向量化與檢索/gutierrez-et-al-2024-hipporag.pdf`，但本決策紀錄不將「已下載」誤寫成「已完成全文核實」；寫作定稿前仍需確認 HippoRAG 的雙層圖設計與本專案 `(Chunk)-[:HAS_ENTITY]->(Entity)` 是否真正對應。
- **完整規格**：見 `docs/報告/02_競品借鏡與技術導入藍圖.md` 第二節之 1

### 實體對齊與去重（2026-07-10）

- **決策**：後端 Ingestion 收到本地端送來的實體時，先做字串編輯距離篩選，再做向量相似度篩選（餘弦相似度 > 0.88 且同類型則 Neo4j `MERGE`）。
- **理由**：避免同義詞/縮寫造成節點污染，維持圖譜品質與檢索召回率。
- **完整規格**：見 `docs/報告/02_競品借鏡與技術導入藍圖.md` 第二節之 2

### 建圖流程：雙軌非同步（2026-07-10）

- **決策**：文件上傳後立即完成向量化並可用（第一軌，即時），SVO 抽取則寫入 SQLite 隊列由背景 Worker 非同步處理（第二軌）。
- **理由**：解決建圖冷啟動延遲問題，這是 v1 對標文件與論文 1.1.3 節已識別的頭號弱點。
- **完整規格**：見 `docs/報告/02_競品借鏡與技術導入藍圖.md` 第二節之 3

### 時序管理：雙時態關係邊（進階，優先序中）（2026-07-10；2026-07-23 升級為 RQ5）

- **決策**：關係邊新增 `valid_from`/`valid_to` 屬性，新事實與舊事實衝突時不刪除舊邊，而是標記失效並新增新邊，保留完整歷史。
- **理由**：補強現有 `_temporal_decay()` 隱性衰減機制的稽核追溯能力；v2 目前連 `_temporal_decay()` 這個 v1 隱性衰減機制都尚未移植，現況比「靜默覆蓋」更原始——是「靜默並存矛盾」（MERGE 鍵不比對 object，新舊事實無關聯並存）。
- **學術支撐**：核心文獻已改為 T-GRAG（Li et al., 2025，🟢 ACM Multimedia 2025，已下載全文）；本節原引用的 Rasmussen et al. (2025) *Zep: A Temporal Knowledge Graph Architecture for Agent Memory* 僅 WebSearch 確認存在性、未下載全文，查證等級較低，詳見 `docs/論文/02_文獻探討.md` § 2.4.6。
- **狀態**：2026-07-23 已於 `01_緒論.md` § 1.2 正式升級為研究問題 **RQ5**（原為 🔧 工程借鏡型分類，見 `docs/報告/03_核心架構藍圖.md` 痛點 5 更正記錄），設計提案已補上 Behavior Tree（`docs/論文/03_系統設計與方法論.md` § 3.5），**仍未實作**，非首波實作範圍。

### 命名空間隔離與服務形態（2026-07-10）

- **決策**：多知識庫隔離採輕量 `namespace`（即 `kg_id`）鍵值區隔，不做複雜 RBAC；專案維持獨立 FastAPI 後端服務（API-first），不開發為純 SDK。
- **理由**：借鏡 WhyHow.ai 棄用純 SDK、轉向服務化的工程教訓（見 `docs/報告/產品競品研究/07_WhyHow_ai.md`）。

### 檢索補強：本地輕量向量與段落共現分析（優先序中，2026-07-10）

- **決策**：本地背景 Worker 搭載 `BAAI/bge-micro-v2` 做秒級向量化；同一 Chunk 內共現的實體直接建立 `CO_OCCURS` 邊，補足顯式 SVO 抽取的召回率盲點。

### 問答檢索：GraphRAG 語境生成（2026-07-10）

- **決策**：問答時先抽取 Query 中的核心實體，執行 2-hop BFS 找出關聯路徑，將三元組轉譯為結構化 Context（XML/JSON）注入 System Prompt，並依 `source_doc_id` 輸出來源標記。

### 實驗可追溯性規範（2026-07-13）

- **決策**：每次實驗執行皆須記錄以下四項資訊，並隨結果一併保存：
  1. **程式版本**：git commit hash 與分支名稱
  2. **參數設定**：完整參數快照（config 檔案或等效紀錄）
  3. **測試案例集**：使用的資料集/測試案例版本或 ID
  4. **原始輸出**：完整 log／回答輸出檔案路徑
- **理由**：過去測試 v1 時，測試結果無法回溯對應到「哪個程式版本、哪組參數、哪個測試案例」，導致除錯與結果重現困難。此規範同時支撐論文 1.2 節 RQ2/RQ3 的可追溯性次要指標評估，以及第五章實驗設計的可重現性要求。
- **實作方式**：不需要引入 MLflow 等重量級 MLOps 平台，以本專案實驗規模，每次實驗執行時產生一份 JSON/YAML manifest 記錄上述四項即可，manifest 與實驗輸出一併保存於實驗結果目錄。
- **對應論文章節**：01_緒論.md § 1.2（RQ2/RQ3 次要指標）、05_實驗設計與評估.md（方法論）。

### 跨 KG 關係型別登記表（2026-07-26）

- **決策**：關係型別的動態擴充（`EXPAND`，見 `docs/論文/03_系統設計與方法論.md` 3.1.3 §a）預設只在單一 KG 內生效，但新增一份**輕量的跨 KG 共用登記表**，記錄各 KG 已核准的擴充型別（canonical 名稱＋語意描述），供任何 KG 觸發 `EXPAND` 時查詢是否已有語意相近的既有型別可沿用命名，避免「同一概念在不同 KG 各自取不同名稱」的分裂。
- **理由**：這是本系統第一個處理「跨 KG 一致性」的機制——現行 DEDUP／MERGE 等既有去重機制皆僅限單一 KG 內運作，實體從未有跨 KG 對齊需求。關係型別擴充若各 KG 完全獨立命名，會使未來任何跨 KG 比對或共用型別 embedding 的需求（例如查詢路由到多個候選 KG 時）失去一致的比對基準。
- **架構定位**：獨立於任何單一 KG 的 Neo4j 資料庫，架構上類比現行 `task_queue.db`（橫跨多個 KG 的共用基礎設施），而非併入某個 KG 專屬的資料庫。
- **狀態**：設計提案，尚未實作；具體資料結構（獨立 SQLite 或其他形式）留待第四章實作 3.1.3 §a 治理機制時一併定案。
- **對應論文章節**：`docs/論文/03_系統設計與方法論.md` 3.1.3 §a、3.2 §c（查詢時比對範圍是否納入跨 KG 登記表的擴充型別，待決）。

### 未來工作：輕量語意推理（2026-07-10）

- **候選方向**：`owlready2`（OWL 本體推理）、`rdflib`（RDFS 推理），或在 Cypher/`NetworkX` 層手寫規則傳遞（如遞移律）。
- **狀態**：未來工作，非近期實作範圍，用於避免導入 Stardog 這類重量級閉源商業平台（見 `docs/報告/產品競品研究/06_Stardog.md`）。

> 以上決策的完整工程規格見 `docs/報告/01_本地抽取與混合架構評估.md` 與 `docs/報告/02_競品借鏡與技術導入藍圖.md`；技術選型的學術文獻查證與開源實作參考見 `docs/報告/技術導入評估.md`。
