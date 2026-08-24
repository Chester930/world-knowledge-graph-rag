# 15_多型態資料來源與結構保留

本資料夾對應：

- `docs/論文/02_文獻探討.md` § 2.6.4
- `docs/論文/03_系統設計與方法論.md` § 3.1.5
- `docs/ARCHITECTURE.md`「完整產品架構與多型態資料來源」SDD 任務

本批來源以 W3C Recommendation、W3C 技術規格與官方標準文件為主。它們支撐的是資料結構保留、映射、驗證、版本與來源追溯的產品設計原則，不代表本專案已直接採用 RDF／SPARQL／SHACL 實作。

## 來源清單

| 來源 | 類型 | 支撐的產品設計 | 狀態 |
|---|---|---|---|
| [JSON-LD 1.1](https://www.w3.org/TR/json-ld/) | W3C Recommendation | JSON 語法與語意 context 分離；作為 JSON 結構保留與語意投影的標準參照 | ✅ 官方連結已查證；未下載本地 PDF |
| [R2RML](https://www.w3.org/TR/r2rml/) | W3C Recommendation | 關聯式資料庫欄位、主鍵／外鍵到 RDF／語意圖的可宣告映射 | ✅ 官方連結已查證；未下載本地 PDF |
| [Direct Mapping of Relational Data to RDF](https://www.w3.org/TR/rdb-direct-mapping/) | W3C Recommendation | 關聯式資料的預設結構映射與 foreign key 保留 | ✅ 官方連結已查證；未下載本地 PDF |
| [SHACL](https://www.w3.org/TR/shacl/) | W3C Recommendation | Canonical Semantic Layer／KG 寫入前的結構約束與驗證 | ✅ 官方連結已查證；未下載本地 PDF |
| [PROV-O](https://www.w3.org/TR/prov-o/) | W3C Recommendation | `source_id`、匯入活動、mapping 版本、產生代理者與 provenance 關係 | ✅ 官方連結已查證；未下載本地 PDF |
| [Data on the Web Best Practices](https://www.w3.org/TR/dwbp/) | W3C Recommendation | structural metadata、provenance、versioning、API、preservation 與多格式呈現 | ✅ 官方連結已查證；未下載本地 PDF |
| [JSON Schema Specification](https://json-schema.org/specification) | 官方規格 | JSON source schema 的型別、必要欄位與驗證規則 | ✅ 官方連結已查證；非 W3C 文獻 |

## 查證限制

- 本批目前是「官方連結與設計依據已準備」，不是「全文 PDF 已下載」。
- 這些標準不直接決定本專案的 Neo4j schema；本專案仍需自行設計 `RawSnapshot`、`SourceSchema`、`CanonicalRecord`、`MappingPlan` 與 `TextProjection`。
- R2RML 支撐關聯式資料映射的原則，不代表本專案會直接採用 R2RML 或建立完整 RDF endpoint。
