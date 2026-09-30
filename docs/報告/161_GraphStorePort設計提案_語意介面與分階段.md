# 報告161：`GraphStorePort` 設計提案（語意介面、分階段；報告160 U2）

> **日期**：2026-09-30 ｜ **性質**：**純文件設計提案，不寫任何 `.py`，不決定介面檔案位置，不把 `bfs_query` 納入設計**。規劃對話核可後才會另開實作任務。
> **依據**：[報告157](157_Neo4j操作只讀盤點結果.md)（74 函式／120 執行點；§7 量化觀察）、[報告160](160_下一階段任務規劃_N4獨立化準備與來源回取再探測.md) U2、[BT_SM草案](BT_SM節點化結構設計草案_v0.1.md) §5.2、§7。使用者／規劃已定：**語意介面、分階段**（報告155 §10 #1）。
> **事實基準**：報告157 的位置與行號取自 `80077e6` 之前；U1 已搬動 N4（`svo_service.py` 3923→3013 行），**本文引用的 `svo_service.py` 行號以報告157 為準，實作前需重新核對**。

## 1. 範圍與分階段

| 階段 | 涵蓋 | 函式數（報告157） | 本提案 |
| --- | --- | --- | --- |
| **P-A** | **DDL／索引／資料庫管理群** | 14 | §2.1 草案 |
| **P-B** | **單純 CRUD 群**（KG 中繼、文件／條文節點、抽取寫入、查詢端輔助讀取） | 約 26（含已在 `repositories/` 內的 9） | §2.2 草案 |
| P-C | 向量／全文檢索群（`vector_search_facts` 等 4＋1） | 5 | 只列方法名（§2.3），不設計 |
| P-D | 回填維護群 | 9 函式／27 處 | 不在本提案 |
| **最後** | **`bfs_query`（圖遍歷）** | 2（含 `_bfs_pass_cypher`） | §3 只寫「為何最後」 |

每階段獨立可驗收、可停；P-A、P-B 之間沒有相依，可任意順序。

## 2. 語意介面草案

**命名與風格**：方法名表達**領域語意**（不暴露 Cypher、`driver`、`elementId`）；參數用 `kg_id: UUID`＋值物件；回傳用既有 `models/` 型別或簡單 `dict`。以下用 Python `Protocol` 語法**僅為說明簽名**，非程式碼。

### 2.1 P-A：DDL／索引群（14 個函式）

```text
class GraphSchemaPort(Protocol):
    async def ensure_entity_uniqueness(self) -> None                    # Entity(kg_id,name) 唯一約束
    async def ensure_vector_index(self, spec: VectorIndexSpec) -> None   # 維度不符時的處理見 §4.3
    async def ensure_fulltext_index(self, spec: FulltextIndexSpec) -> None
    async def list_vector_indexes(self) -> list[IndexInfo]
    async def drop_indexes(self, names: Sequence[str]) -> list[str]      # 回傳實際移除者
    # 多資料庫管理（Enterprise 專屬）：是否納入待裁示，見 §5 問題 3
    async def create_kg_database(self, name: str) -> None
    async def drop_kg_database(self, name: str) -> None
    async def list_kg_databases(self) -> list[DatabaseInfo]
    # 嵌入設定登記（_EmbeddingMeta 節點）
    async def read_embedding_meta(self) -> EmbeddingMeta | None
    async def register_embedding_meta(self, meta: EmbeddingMeta) -> None
```

`VectorIndexSpec(target: NodeProp | RelProp, dim: int, name: str)`：以**值物件**表達現有 6 種目標，避免 6 個方法：

| 現有函式（位置） | `VectorIndexSpec` 目標 | 已有 `repositories/` 內同類實作？ |
| --- | --- | --- |
| `svo_service.create_chunk_vector_index`（`:82`） | `Chunk.embedding` | 否 |
| `svo_service.create_entity_name_vector_index`（`:101`） | `Entity.name_embedding` | 否 |
| `svo_service.create_fact_vector_index`（`:2295`） | `Fact_<kg>.fact_embedding`（**per-KG 動態標籤**） | 否 |
| `svo_service.create_sentence_vector_index`（`:3457`） | `Sentence_<kg>.sentence_embedding`（per-KG） | 否 |
| `svo_service.create_related_to_vector_index`（`:3200`） | `RELATED_TO.verb_embedding`（**關係屬性**索引） | 否 |
| `ConceptRepository.create_vector_index`（`repositories/concept_repo.py:21`） | `ConceptNode.q_vector` | **是（唯一一個）** |

`FulltextIndexSpec`：`svo_service.create_entity_name_fulltext_index`（`:119`）、`create_fact_fulltext_index`（`:2329`）。`ensure_entity_uniqueness` ← `svo_service.create_entity_index`（`:57`）。其餘：`core/database.py` 三個資料庫管理函式、`core/vector_migration.py::ensure_vector_index`／`migrate_vector_indexes`（**既有的「維度不符→刪除重建」邏輯**）、`core/embedding_guard.py::check_and_register`。**per-KG 標籤與索引名稱的命名規則**（`_kg_fact_label`、`_fact_vector_index_name`…）屬**轉接層實作細節**，不出現在介面。

### 2.2 P-B：單純 CRUD 群

依「領域物件」分組（每組一個小 Port 比一個大 Port 好審、好假造）：

```text
class KGCatalogPort(Protocol):            # 現有 KGRepository，介面幾乎可原樣採用
    async def create / get / list_all / update / delete   # 5 方法（repositories/kg_repo.py）

class DocumentGraphPort(Protocol):        # 現有 LawDocumentRepository
    async def merge_document / merge_law_articles / get_document / list_law_articles   # 4 方法

class ExtractionWritePort(Protocol):      # 抽取寫入（現分散在 svo_service）
    async def merge_entity(...) -> str                        # ← merge_entity（含別名更新；內含唯一約束衝突重試）
    async def record_chunk_mention(kg_id, chunk, entity_name, surface_form) -> None   # ← _merge_chunk_mention
    async def merge_relation(kg_id, triple, ...) -> None      # ← merge_triples_to_graph 內的邊合併（動態關係型別）
    async def create_fact(kg_id, fact) -> None                # ← _create_fact_node
    async def store_chunk_embedding(...) / store_sentence_embedding(...)   # ← embed_svo_chunks／embed_standardized_sentences
    async def revoke_chunk(kg_id, source_doc_id, chunk_index) -> RevokeResult   # ← revoke_chunk_facts（4 個執行點）
    async def clear_kg_graph(kg_id) -> None                   # ← knowledge_graph_service.build_graph 的整庫 DETACH DELETE

class QueryReadPort(Protocol):            # 查詢端輔助讀取（現在 routers/agent.py 內直接寫 Cypher）
    async def list_entity_names(kg_id) -> list[str]           # ← _find_seed_entities
    async def entity_degrees(kg_id, names) -> dict[str, int]  # ← _drop_hub_seeds
    async def source_docs_of_entities(kg_id, names) -> set[UUID]   # ← _relevant_doc_ids_from_seeds
    async def sibling_facts_by_article(kg_id, seeds, limit) -> list[dict]   # ← _expand_facts_by_article
    async def alias_counts(kg_id, entity_name) -> dict[str, int]            # ← _aggregate_alias_counts
    async def entity_candidates(kg_id, name) -> list[EntityCandidate]       # ← _fetch_entity_candidates（全掃描）
```

- **已在 `repositories/` 的部分（9 個函式）**：`KGCatalogPort`、`DocumentGraphPort` 幾乎是把現有 repository 宣告成 Protocol；`ConceptRepository` 同理。
- **現在在 `services/`、`routers/` 直接寫 Cypher 的部分**：`ExtractionWritePort`（約 8 函式）、`QueryReadPort`（6 函式，其中 4 個在 `routers/agent.py`）——這是「層次違反」的主要收斂目標（報告157 §4.4）。
- **`entity_candidates`（`_fetch_entity_candidates` 全掃描）與 `_fetch_entity_candidates_canopy`（含全文／向量）** 屬「實體候選檢索」，歸 P-C。
- **有意不抽象的**：`merge_triples_to_graph` 內把「LLM 抽取結果＋去重＋自然化＋Fact 建立」串起來的協調邏輯（N5 的職責）**不屬 Port**；Port 只暴露其中每個**單一資料動作**。

### 2.3 P-C：檢索群（只列名）

`search_facts`（`vector_search_facts`，含可選全文 hybrid、`allowed_source_doc_ids` 範圍）、`search_entities`（`vector_search_entities`）、`search_sentences`、`search_concepts`（`ConceptRepository.vector_search_concept_ids`）、`entity_candidates_canopy`。**簽名與 `hybrid`／`source_doc_cap` 等參數如何放進介面本提案不設計。**

## 3. 為何 `bfs_query` 最後（不設計）

- 與 Neo4j 語法**耦合最深**：Cypher 用 `CALL (seed) { … }` 範圍子查詢、`EXISTS { MATCH … }`、變長路徑 `*min..max`、範圍下推到走訪階段、每種子 `LIMIT`（報告157 §7）；且 Cypher 由 `_bfs_pass_cypher` 組字串（關係型別白名單以字串內插）。
- 是查詢延遲熱點（報告26／27 的 330–440 秒問題）；任何介面抽象都會影響**效能調校空間**。
- 有 L0／L1／L2（含 embedding 引導剪枝，`prize_top_k`）三層行為與 4 個執行點；測試綁在使用者模組名稱（`<agent>.bfs_query`×17），語意介面要先看 P-A／P-B 的實際成本再定。
- **結論僅為排序理由**，不含設計。

## 4. 介面檔案位置：選項與取捨（**不決定**）

草案 §7 主張「依節點分、`ports.py` 放在節點資料夾」，但目錄結構（草案 §10.2a #4）**尚未裁示**；`GraphStorePort` 又是**多節點共用**（N5、N6、N9 皆用），與「節點自己的 `ports.py`」有張力。

| 選項 | 位置 | 優點 | 缺點／風險 |
| --- | --- | --- | --- |
| **A** | `core/ports/graph_store.py`（與現有 `core/providers/base.py` 的 `LLMProvider`／`EmbeddingProvider` 並列；轉接實作放 `repositories/`） | 與既有 ports 的放置慣例一致；多節點共用自然；`core` 不依賴 `services` | `core/` 會多一個子套件；`core` 目前偏「設定＋provider」，圖儲存介面放這裡是否恰當待議 |
| **B** | `repositories/ports.py`（介面）＋`repositories/neo4j_graph_store.py`（轉接） | 介面與唯一實作同層，`repositories/` 本來就是 Neo4j CRUD 的家；改動最小 | 上層節點 import `repositories` 的介面檔會讓「節點依賴介面而非實作」的邊界不明顯；`repositories/` 現在有 4 個具體類別而非 Protocol |
| **C** | 各節點資料夾內 `ports.py`（如 `services/extraction/ports.py` 只宣告 N4 用得到的方法）＋`repositories/` 一份實作滿足多個 Protocol | 完全符合草案 §7、抽離測試最乾淨（每節點只帶自己要的最小介面） | 同一能力在多處宣告（重複）；跨節點一致性靠實作端；需先有節點資料夾（N5／N6／N9 尚未成形） |
| D（補充） | 先不放檔案：以 `typing.Protocol` 放在**第一個使用者**（P-A 的呼叫端 `main.py` 啟動流程）旁邊試行 | 最小承諾、可逆 | 之後要搬；易形成事實標準 |

**取捨線索（事實，不做選擇）**：P-A 的呼叫端只有 `main.py`（啟動時建索引，`main.py:71–84`）與 `core/`，**單一使用者**；P-B 的 `ExtractionWritePort` 主要使用者是 N5／N6（尚未成形為資料夾）；`QueryReadPort` 的使用者是 N9（`services/retrieval/` 已成形）。

## 5. 待裁示的問題（本提案不代決定）

1. 介面檔案位置（§4 A／B／C／D）。
2. `VectorIndexSpec` 的「值物件」形態是否接受（相對於每種索引一個方法）。
3. 多資料庫管理（`create/drop/list_kg_databases`）是否納入：這些是 **Enterprise 專屬**；本專案 `core/database.py` 註記「Community 版請改用 `kg_id` 屬性區隔」；**目前是否仍有呼叫者未核對**。
4. `ExtractionWritePort` 的粒度：是否接受「單一資料動作」（§2.2 最後一點）而不含協調邏輯。
5. P-C 檢索群是否先於 P-B 的 `QueryReadPort`。

## 6. 測試與搬移策略（在不改呼叫端的前提下）

1. **先宣告、再轉接、最後才換呼叫端**：每個 Port 先只宣告 Protocol，並提供 **Neo4j 轉接類別**，其方法**委派到現有函式**（`svo_service.create_chunk_vector_index` 等），呼叫端與測試**完全不動**。此時行為與現況逐位元相同（可用 U1 的差分 golden 方法對轉接層做驗證）。
2. **逐呼叫端遷移**：`main.py` 啟動流程先改用 `GraphSchemaPort`（P-A 單一使用者，風險最低）；每遷一個呼叫端一個 commit，附「行為不變」差分（假 driver 記錄 Cypher 字串與參數序列，遷移前後相同）。
3. **補丁目標**（報告157 §8）：測試補丁多綁在**使用者模組名稱**（`<main_module.svo_service>.create_entity_index` 等 6 個 P-A 函式被 `tests/test_main.py` 補丁）。遷移呼叫端時，補丁改為指向**注入的假 Port**（依賴注入取代 monkeypatch，這正是介面的價值之一）；轉接類別內委派的名稱**保留在 `svo_service` 重新匯出**，舊補丁在遷移完成前仍有效。
4. **假 Port 測試**：每個 Port 附一個 **in-memory 假實作**（記錄呼叫）供節點抽離測試（草案 §5.1 條件 4）；**不**以假 Port 模擬 Cypher 語意（那是整合測試的範圍）。
5. **`ensure_vector_index` 與 8 個索引建立函式的關係（事實＋選項，不做統一）**：事實——`core/vector_migration.py::ensure_vector_index`（維度不符時刪除重建，`legacy_index_names` 支援）**只被 `ConceptRepository.create_vector_index` 使用**；`svo_service.py` 的 8 個索引建立函式各自直接 `CREATE … IF NOT EXISTS`，**不處理維度不符**。選項：(i) `ensure_vector_index(spec)` 統一語意為「必要時重建」（會改變 8 個函式的行為：維度不符時由靜默沿用舊索引變成重建，**行為變更，需評估與 `migrate_vector_indexes` 啟動流程的關係**）；(ii) 介面提供兩個語意（`ensure_…_if_absent` 與 `ensure_…_matching_dim`），轉接層保持各函式現有行為；(iii) 介面只涵蓋現有行為的聯集，不統一。**本提案不選。**

## 7. 估計工作量

| 項目 | 函式 | 測試影響面 |
| --- | ---: | --- |
| P-A：`GraphSchemaPort`＋轉接（委派） | 14 | 補丁目標 6（全在 `tests/test_main.py`）；`tests/core/`、`repositories` 測試不受影響；新增 Port 契約測試約 14＋假 Port |
| P-A 遷移呼叫端（`main.py`） | 1 個呼叫端 | `tests/test_main.py` 的補丁改注入假 Port |
| P-B：`KGCatalogPort`／`DocumentGraphPort`（宣告既有 repository） | 9 | 幾乎為零（僅宣告） |
| P-B：`ExtractionWritePort` | 約 8 | 補丁（報告157 §3）：`<svc>._merge_chunk_mention`、`<svc>.merge_entity`、`<svc>._aggregate_alias_counts`、`<svc>._fetch_entity_candidates`、`services.extraction_worker.merge_triples_to_graph`×3；假 driver 測試以 `test_svo_service.py`（20 處 `execute_query`）為主 |
| P-B：`QueryReadPort` | 6 | `tests/routers/test_agent.py`（補丁 `<agent>._find_seed_entities`×18 等） |
| P-C（未設計） | 5 | 補丁 `<agent>.vector_search_facts`×18、`<agent>.vector_search_entities`×2 |

粗估（**僅函式數與測試檔數，非工時承諾**）：P-A 約 1 個任務書（宣告＋轉接＋`main.py` 遷移＋假 Port＋契約測試）；P-B 約 2–3 個；P-C、`bfs_query` 待 P-A／P-B 經驗後再估。

## 8. 未觸發報告160 §4 停止條件

未寫任何 `.py`、未決定位置、未納入 `bfs_query`；§5 的問題皆為「待裁示」。
