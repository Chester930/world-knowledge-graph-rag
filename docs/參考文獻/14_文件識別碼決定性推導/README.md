對應 `../../論文/03_系統設計與方法論.md` § 3.1.4 §c「文件識別碼決定性推導機制（Document UUID）」——為什麼選擇 `uuid5(NAMESPACE, source)` 決定性推導而非隨機 UUID4＋持久化欄位（選項 A）或直接沿用 `source` 字串當鍵（選項 C）的文獻與專案查證紀錄。

> **狀態：✅ 2026-08-18 已實作**（`core/constants.py::DOCUMENT_ID_NAMESPACE`／`services/document_record_service.py::document_uuid()`，接線於 `services/extraction_worker.py::_process_one()`，測試見 `tests/services/test_document_record_service.py`）。本資料夾三份來源皆已在實作前查證完成（RFC 全文下載、Kimball Group 官方技術文章確認、langchain-ai/langchain 原始碼實際讀取＋`gh api` 即時星數查證），非事後補citation。

## 查證背景（2026-08-18）

規劃 § 3.1.4 §b／`/agent/chat` 語意檢索接線時，追蹤 `services/extraction_worker.py::_process_one()` 發現 `SVOTriple.source_doc_id` 在正式抽取迴圈裡從未被賦值過——系統裡沒有任何一處真的會產生文件 UUID（`DocumentRecord` 無 UUID 欄位；看似對應的 `Document.id` 屬於整個是 `NotImplementedError` stub 的 `DocumentRepository`）。使用者要求：任何設計決策要有文獻背書、任何實作做法要有專案背書，且兩者都要有可驗證的可信度指標（星數、正式標準地位等），比照本論文一貫的查證標準——本資料夾即該次查證的完整記錄。

## 內容清單

| 檔案 | 文獻／來源 | 查證方式 |
|---|---|---|
| `leach-mealling-salz-2005-rfc4122-uuid.txt` | Leach, Mealling & Salz (2005), *RFC 4122: A Universally Unique IDentifier (URN) Namespace*，IETF 正式標準 | [rfc-editor.org 官方文字版](https://www.rfc-editor.org/rfc/rfc4122.txt) 已下載全文（RFC 官方發布格式本身即為純文字，非排版 PDF，故副檔名與本資料夾其餘 PDF 慣例不同，屬文件類型差異非查證層級差異） |
| `langchain-ai/langchain` — 無 PDF，見下方原始碼查證 | 開源專案，非論文 | 🟢 `gh api repos/langchain-ai/langchain --jq '{stargazers_count, archived, pushed_at}'`（2026-08-18 執行）：144,437★、`archived: false`、`pushed_at` 為查證當日——活躍生產級專案，非掛名不維護 |
| Kimball Group「Surrogate Keys」／「Durable Super-Natural Keys」 | 網頁技術文章，非論文 | 官方網站直接引用，見下方查證方式說明 |

## RFC 4122（UUID version 5，命名式決定性 UUID）

**核心依據**：§4.3「Algorithm for Creating a Name-Based UUID」定義 version 5——用命名空間 UUID＋名稱字串做 SHA-1 雜湊，**同一輸入永遠得到同一輸出**，正是本節「同一份文件的 `source` 永遠推導出同一個 UUID，不需要額外持久化狀態」這個需求的標準機制來源。§4.3 並建議「若要為一個新的應用領域建立命名空間，應該先為這個命名空間本身產生一個 UUID」——`core/constants.py::DOCUMENT_ID_NAMESPACE` 的產生方式直接依此建議（執行期 `uuid.uuid4()` 產生一次，寫死為常數）。

**信任分級**：🟢——IETF 正式發布的標準文件（Standards Track RFC），不是預印本或部落格文章，是本論文所有文獻中信任層級最高的一類來源（與正式標準身分等價，不需要額外的同行評審佐證）。

## langchain-ai/langchain（機制先例，非理論依據）

**查證方式（不僅信搜尋摘要）**：先用 `WebSearch` 找到 `langchain_core.indexing.api` 模組疑似做決定性文件雜湊，接著用 `gh api repos/langchain-ai/langchain/contents/libs/core/langchain_core/indexing/api.py --jq '.download_url'` 取得原始碼直連網址，`curl` 抓下完整檔案後 `grep` 確認具體實作：

```python
def _hash_string_to_uuid(input_string: str) -> str:
    hash_value = hashlib.sha1(input_string.encode("utf-8"), usedforsecurity=False).hexdigest()
    return str(uuid.uuid5(NAMESPACE_UUID, hash_value))
```

`uuid.uuid5(NAMESPACE_UUID, hash_value)`——與本節機制逐字相同的 RFC 4122 UUID5 用法，用途是「文件索引要能在重跑索引（re-indexing）時保持一致識別、可判斷是否為同一份文件」，與本節「同一份文件重新解析／重新歸屬到別的 KG 時，識別碼不該變」的情境高度對應。

**誠實聲明**：這是**機制的生產級先例**，不是理論依據——LangChain 官方文件與程式碼皆未附上任何學術論文引用，這個雜湊模式本身是他們自行收斂的工程設計，與本節同樣獨立參考 RFC 4122 標準後得出相似解法，非同一篇文獻共同依據，性質上與 `13_實體節點向量化去重開源專案/README.md` 記錄的「neo4j-labs/llm-graph-builder 實體向量化去重機制查無對應學術文獻」是同一類型的誠實聲明。

**信任分級**：🟢——144,437★（2026-08-18 `gh api` 即時查證），Python 生態系最主流的 RAG／LLM 應用框架之一，非小眾或已停止維護專案。

## Kimball Group「Surrogate Keys」／「Durable Super-Natural Keys」

**來源**：[Design Tip #147 Durable "Super-Natural" Keys](https://www.kimballgroup.com/2012/07/design-tip-147-durable-super-natural-keys/)、[Surrogate Keys](https://www.kimballgroup.com/1998/05/surrogate-keys/)（Kimball Group 官方網站，資料倉儲維度建模方法論的權威來源，Ralph Kimball 為該領域奠基者之一，其技術文章被廣泛引用於資料工程實務與教材，非同行評審期刊論文，但屬該領域公認的方法論原始出處）。

**核心依據**：明確區分「自然鍵（natural key）穩定不變時可直接沿用」與「自然鍵可能改變時需要系統另外指派一個永不改變的替代/耐久鍵（surrogate/durable key）」兩種情境。查證本專案 `services/document_record_service.py::init_record()`／`append_assignment()` 確認 `DocumentRecord.source` 建立後從未被改寫過（包含文件重新歸屬到別的 KG，資料夾物理搬移但 `source` 字串不變）——本系統的自然鍵已被驗證穩定，這是本節選擇 B（UUID5 決定性推導，仍是自然鍵的函式）而非 A（隨機 UUID4，完全替代鍵）站得住腳的具體依據；也是選項 C（直接沿用 `source` 字串本身當鍵）同樣可行的依據。

**信任分級**：🟡——網頁技術文章而非同行評審論文，但為該方法論領域公認的權威原始出處，比照本論文既有慣例（例如 Wikidata `Property_proposal`／`Property_creation` 社群方針頁面，見 `03_資訊抽取與本體設計/README.md`）對「非論文但具權威性的官方技術文件」的分級方式，直接引用不下載 PDF（網頁本身即為權威版本，無另行排版的 PDF 供下載）。

## 與現有資料夾的關聯

本資料夾與 `13_實體節點向量化去重開源專案/` 性質相近——皆是「機制設計選項查證」而非單一理論文獻的深入精讀，查證層級對應本論文既有慣例中「初次查證」（`gh api` 驗星數、確認活躍度、讀原始碼確認機制）而非「逐字精讀全文含附錄」（見 `12_三元組事實層級向量化與檢索/`）。RFC 4122 屬正式標準，其權威性不需要「精讀程度」這個額外判準。
