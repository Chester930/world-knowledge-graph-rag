# 77 法律模態關係型別 per-KG 擴充SDD任務書（**交付 Codex**）

**建立日期**：2026-09-25
**文件性質**：交付 Codex 執行用任務書。設計成冷啟動可用——不需要本對話的上下文即可接手。
**分支／工作區**：`worktree-sdd-retrieval-comparison`，`D:\Users\666\Desktop\world knowledge graph rag\.claude\worktrees\sdd-retrieval-comparison`
**前置依賴**：報告76（guard_profile 領域可插拔化，2026-09-25 已完成，`KGConfig.guard`）——本任務同樣延續「設定分層」Track，但是**新的一個分區**（`DomainConfig.rel_type_extensions`），不是報告76 guard 的延伸，也**不**依賴報告76的程式碼路徑，可以獨立進行。

---

## 0. 一頁摘要

**要解決的問題**：`services/svo_service.py::_svo_prompt()` 目前把「應（強制義務）」「得（裁量權）」「不得（禁止）」「視為（法定擬制）」全部壓進通用 ConceptNet 關係型別（多半落在 `RELATED_TO`／`CAUSES`），在法遵檢索情境下分不清「雇主一定要做」還是「雇主可以選擇做」。

**⚠️ 關鍵限制（本任務書拍板，經與使用者討論確認）**：`core/constants.py::SVO_REL_TYPES` **不可修改**——這個集合被 `docs/論文/02_文獻探討.md` 明文定義為「恰好等於 ConceptNet 5.5 官方現行核心關係清單，35 個，逐一可追溯到 Speer et al. (2017) 與官方 wiki」，論文裡有完整的即時查證訂正紀錄（35→33→35，皆附查證日期與理由）。直接把新型別塞進這個集合會破壞這個學術主張。

**設計方向**：新增一個**獨立的、per-KG 可覆蓋的關係型別擴充機制**——`DomainConfig.rel_type_extensions`，shipped defaults 帶 4 個台灣勞基法法律模態型別（`OBLIGATES`／`PERMITS`／`PROHIBITS`／`DEEMS`），所有需要用到「合法關係型別集合」或「型別描述句」的地方，一律改用「`SVO_REL_TYPES` ∪ 該 KG 的 `rel_type_extensions`」這個**有效集合（effective set）**，`SVO_REL_TYPES` 本身完全不動。`generic` domain pack 明確覆寫成空清單（法律模態是台灣勞基法網域特定概念，中性 pack 不該繼承）。

**⚠️ 文獻誠實聲明（必須遵守，不可妥協）**：這 4 個型別名稱的發想來自使用者提供的另一份研究資料夾裡對 LKIF-Core 的描述，**本專案從未對 LKIF-Core 做過 live 文獻查證**。程式碼註解、commit message、任何文件都**不可以**寫成「依據 LKIF-Core」或暗示這是已查證的文獻依據，只能誠實記為「本專案原創設計的法律模態關係型別擴充，命名靈感來源未經查證」。**不要修改 `docs/論文/` 任何檔案**——是否正式寫入論文第二章、要不要補文獻查證，是後續獨立決定的事，不在本任務範圍。

---

## 1. 現況（已用程式碼逐一查證，非推測）

### 1.1 `SVO_REL_TYPES` 在程式碼裡被三個地方共用（全部要改成「有效集合」）

1. **抽取端 REJECT**（`services/svo_service.py:429-432`，在 `extract_svo_triples()` 內部）：`rel_type = rel_type if rel_type in SVO_REL_TYPES else "RELATED_TO"`。這個函式已經有 `_cfg = cfg or KGConfig()` 在同一個作用域內（`services/svo_service.py:423`附近）。
2. **BFS 圖遍歷的 Cypher 關係型別過濾**（`services/svo_service.py:3772`，在 `bfs_query()` 內部）：`rel_types = "|".join(sorted(SVO_REL_TYPES))`。`bfs_query()` 簽章已經有 `cfg: KGConfig | None = None`（`services/svo_service.py:3705`），不需要新增參數，只需要改內部邏輯。**這個變更是必要的，不是選配**——新型別的邊如果 BFS 走不到，等於白抽。
3. **`SIM`／`QSIM` embedding 比對**（`services/svo_service.py:269-274` `classify_relation_by_embedding()` + `services/svo_service.py:254-266` `_type_description_embeddings()`）：目前直接寫死 `SVO_REL_TYPE_DESCRIPTIONS`，且**快取 key 只有 `embedding_provider.model_name`**（`_TYPE_DESCRIPTION_EMBEDDING_CACHE[embedding_provider.model_name]`）——這是本任務最容易出錯的地方，見 T3。

### 1.2 `Cypher` 注入防線已經相容，不需要改

`_safe_rel_type_literal()`（`services/svo_service.py:1038-1051`）允許 `SVO_REL_TYPES` 內的值，**也允許格式合法（`^[A-Z][A-Z0-9_]*$`，見 `_SAFE_REL_TYPE_PATTERN`，`services/svo_service.py:1034`）但不在表內的值**——`OBLIGATES`／`PERMITS`／`PROHIBITS`／`DEEMS` 全部符合這個格式，**這個函式不需要任何修改**，本來就設計成能接受表外的合法格式值（原意是給 `EXPAND` 治理機制動態核准的新型別用，這次剛好也適用）。

### 1.3 `_reconcile_rel_type()` 與 `resolve_query_relation_type()` 現況

- `_reconcile_rel_type()`（`services/svo_service.py:333` 起）**目前不接受 `cfg` 參數**，呼叫 `classify_relation_by_embedding()` 時沒有傳遞任何 domain 資訊。`extract_svo_triples()` 呼叫它時也**沒有**傳 `cfg`（見 `services/svo_service.py:434-440` 附近）。
- `resolve_query_relation_type()`（`services/svo_service.py:287` 起）**已經**接受 `cfg: KGConfig | None = None`，docstring 明寫「重用 3.1.3 `classify_relation_by_embedding()`（`SIM`）」——這代表查詢端與抽取端共用同一份快取，**兩邊都要一起改，不能只改一邊**，否則查詢端跟抽取端用的有效描述集合會不一致，導致同一個型別在抽取時判得出來、查詢時卻連不上（或反過來）。

---

## 2. 任務清單

### T1（S）：`core/kg_config/model.py` 新增 `RelTypeExtension` 與 `DomainConfig.rel_type_extensions`

```python
class RelTypeExtension(BaseModel):
    """SVO_REL_TYPES 之外、per-domain 可覆蓋的關係型別擴充。

    ⚠️ 不是 ConceptNet 來源，SVO_REL_TYPES（core/constants.py，論文第二章
    明文定義＝ConceptNet 5.5 官方現行 35 個核心關係、逐一可追溯 Speer et al.
    2017）本身絕對不動。這裡收的是本專案原創設計的領域關係型別，`name`
    必須符合 `_SAFE_REL_TYPE_PATTERN`（大寫字母開頭＋大寫字母/數字/底線），
    且不得與 SVO_REL_TYPES 任何一個型別重名（測試強制驗證）。
    """

    model_config = _FROZEN

    name: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    description: str


# 報告77：台灣勞基法法律模態關係型別，命名靈感來自使用者提供研究資料夾對
# LKIF-Core 的描述，但本專案未對 LKIF-Core 做過 live 文獻查證——不可在任何
# 程式碼註解／commit message／文件宣稱「依據 LKIF-Core」，只能記為「本專案
# 原創設計，命名靈感來源未查證」。是否正式寫入論文、要不要補查證，是獨立
# 於本次實作的後續決定，本次不修改 docs/論文/ 任何檔案。
_DEFAULT_REL_TYPE_EXTENSIONS: tuple[RelTypeExtension, ...] = (
    RelTypeExtension(
        name="OBLIGATES",
        description="A 依法規定 B 為強制義務，法條用語通常是「應」，例如雇主應為勞工投保勞工保險",
    ),
    RelTypeExtension(
        name="PERMITS",
        description="A 依法規定得裁量選擇是否進行 B，法條用語通常是「得」，例如勞工得於休假期間出國旅遊",
    ),
    RelTypeExtension(
        name="PROHIBITS",
        description="A 依法規定禁止進行 B，法條用語通常是「不得」，例如雇主不得使童工從事危險性工作",
    ),
    RelTypeExtension(
        name="DEEMS",
        description="A 依法規定視為 B（法定事實擬制，不論實際情況為何皆依法認定），法條用語通常是「視為」，例如逾期未為反對之意思表示者視為同意",
    ),
)
```

- 加進 `DomainConfig`：`rel_type_extensions: tuple[RelTypeExtension, ...] = Field(default_factory=lambda: _DEFAULT_REL_TYPE_EXTENSIONS)`。
- shipped defaults **不是空的**——比照 `DomainConfig.name`／`system_context` 現行慣例（shipped default 本來就是 taiwan-labor-law 內容，`generic` pack 才覆寫成中性版），這次也一樣：`KGConfig()` 預設就帶 4 個法律模態型別，`taiwan-labor-law.json` 不需要動，`generic.json` 才要明確覆寫成空清單（見 T7）。**這跟報告66/76「shipped defaults 必須逐字等於改動前」的要求不同**——本任務是全新功能，改動前根本沒有這 4 個型別存在，不適用「零行為變化」golden test，測試重點改成「shipped defaults 精確等於任務書定義的這4筆」（T8）。

### T2（S）：有效集合 helper 函式

在 `services/svo_service.py`（或 `core/kg_config/model.py`，擇一但只能一份）新增：

```python
def _effective_rel_types(cfg: KGConfig) -> frozenset[str]:
    return frozenset(SVO_REL_TYPES) | {ext.name for ext in cfg.domain.rel_type_extensions}


def _effective_rel_type_descriptions(cfg: KGConfig) -> dict[str, str]:
    merged = dict(SVO_REL_TYPE_DESCRIPTIONS)
    merged.update({ext.name: ext.description for ext in cfg.domain.rel_type_extensions})
    return merged
```

- 兩個函式都是**純函式、同步**，不需要 async。
- **不要**加執行期防呆檢查「extension name 是否與 SVO_REL_TYPES 重複」——這是設定檔層級的靜態內容，用 T8 的測試把關即可，執行期每次呼叫都檢查是不必要的效能開銷。

### T3（M）：`classify_relation_by_embedding()`／`_type_description_embeddings()` 改為接受可覆蓋的描述字典，快取 key 一併修正

**這是本任務風險最高的部分，務必仔細處理快取 key。**

- `_type_description_embeddings()`（`services/svo_service.py:254` 起）簽章改為 `async def _type_description_embeddings(embedding_provider, descriptions: dict[str, str] | None = None)`；`descriptions is None` 時 fallback `SVO_REL_TYPE_DESCRIPTIONS`（既有呼叫端不傳新參數時行為零變化）。
- **快取 key 不能只用 `embedding_provider.model_name`**——現在同一個 model 底下，不同 KG（不同 `rel_type_extensions`）需要各自獨立的快取，否則第一個載入的 KG 會把它的描述集合快取下來，後面不同 `rel_type_extensions` 的 KG 會拿到錯誤的快取結果（可能漏掉新型別，或用錯的描述句）。快取 key 改成 `(embedding_provider.model_name, tuple(sorted(descriptions.items())))`（tuple 可雜湊，dict 不行）。
- `classify_relation_by_embedding()`（`services/svo_service.py:269` 起）簽章比照新增 `descriptions: dict[str, str] | None = None`，往下傳給 `_type_description_embeddings()`；內部 `rel_types = sorted(type_vectors)` 這行不需要改（已經是從傳入的 `type_vectors` 動態算出，不是寫死 `SVO_REL_TYPE_DESCRIPTIONS`）。
- `_reconcile_rel_type()`（`services/svo_service.py:333` 起）新增 `cfg: KGConfig | None = None`（keyword-only），內部 `_cfg = cfg or KGConfig()`，呼叫 `classify_relation_by_embedding()` 時傳 `descriptions=_effective_rel_type_descriptions(_cfg)`（T2 helper）。
- `extract_svo_triples()`（`services/svo_service.py:401` 起）呼叫 `_reconcile_rel_type()` 的地方（`services/svo_service.py:434` 附近）補上 `cfg=_cfg`（函式內已有 `_cfg` 變數，直接用）。

### T4（S）：`extract_svo_triples()` REJECT 檢查與 `_svo_prompt()` 型別清單

- `extract_svo_triples()` 的 REJECT 行（`services/svo_service.py:432`）：`rel_type = rel_type if rel_type in SVO_REL_TYPES else "RELATED_TO"` 改成 `rel_type = rel_type if rel_type in _effective_rel_types(_cfg) else "RELATED_TO"`。
- `_svo_prompt()`（`services/svo_service.py:212` 起）簽章新增 `rel_type_extensions: Sequence[RelTypeExtension] | None = None`（跟 `fewshots` 參數同一種 keyword-only 模式）；`rel_types = ", ".join(sorted(SVO_REL_TYPES))`（`services/svo_service.py:213`）改成把 `rel_type_extensions` 的 `name` 併入排序清單，讓 LLM 看得到這些新型別可以選。`rel_type_extensions is None` 時只用 `SVO_REL_TYPES`（既有呼叫端不傳新參數時行為零變化——但 `extract_svo_triples()` 這個**主要**呼叫端會改成明確傳入 `_cfg.domain.rel_type_extensions`，見下）。
- `extract_svo_triples()` 呼叫 `_svo_prompt()` 的地方（`services/svo_service.py:424` 附近，`_svo_prompt(text, fewshots=_cfg.domain.svo_fewshots)`）補上 `rel_type_extensions=_cfg.domain.rel_type_extensions`。

### T5（S）：`bfs_query()` 的 Cypher 關係型別過濾

- `services/svo_service.py:3772`：`rel_types = "|".join(sorted(SVO_REL_TYPES))` 改成 `rel_types = "|".join(sorted(_effective_rel_types(cfg or KGConfig())))`（`bfs_query()` 已有 `cfg` 參數，直接用）。

### T6（S）：`resolve_query_relation_type()` 接上有效描述集合

- 該函式已有 `cfg` 參數（`services/svo_service.py:292`），內部呼叫 `classify_relation_by_embedding()` 的地方補上 `descriptions=_effective_rel_type_descriptions(_cfg)`（函式內應該已有或需要補上 `_cfg = cfg or KGConfig()` 這行，若尚未有請對齊既有慣例補上）。

### T7（S）：`config/domain_packs/generic.json` 明確覆寫成空清單

- `config/domain_packs/generic.json` 的 `domain` 區塊加上 `"rel_type_extensions": []`——法律模態型別是台灣勞基法網域特定概念，中性 pack 不該繼承，這點跟 `svo_fewshots`（報告66 T5 因為還沒決定中性內容、暫時沿用 shipped defaults）不同，這裡有明確答案（空清單本身就是合法的中性選擇），不需要留給後續任務。
- `_note` 補一句「`rel_type_extensions` 已覆寫為空（法律模態關係型別為台灣勞基法網域特定概念，不屬於中性 pack）」。
- `config/domain_packs/taiwan-labor-law.json` **不需要改動**——shipped defaults 已經是這 4 個型別。

### T8（L，測試，比照報告76慣例加強）：

1. **golden test**（`tests/core/test_kg_config.py`）：`KGConfig().domain.rel_type_extensions` 逐欄位比對等於任務書 T1 定義的 4 筆 `_DEFAULT_REL_TYPE_EXTENSIONS`（name 與 description 都要比對，不能只比對數量）。
2. **不重複測試**：4 個 extension name 與 `SVO_REL_TYPES` 完全無交集（`assert {"OBLIGATES", "PERMITS", "PROHIBITS", "DEEMS"}.isdisjoint(SVO_REL_TYPES)`），且 4 個名稱全部符合 `_SAFE_REL_TYPE_PATTERN`。
3. **REJECT 行為測試**（`tests/services/test_svo_service.py`）：兩組對照——(a) `cfg=KGConfig()`（預設含 4 個 extension）時，fake LLM 回報 `rel_type: "OBLIGATES"` 的三元組必須保留 `OBLIGATES`，不可退回 `RELATED_TO`；(b) `cfg` 傳入 `rel_type_extensions=()` 的自訂 `KGConfig`（模擬 `generic` 覆寫後的狀態）時，同樣的 LLM 回報必須被退回 `RELATED_TO`——這組對照才能證明機制真的有生效，不是裝飾。
4. **`_svo_prompt()` 測試**：預設 `cfg`／`rel_type_extensions` 時，輸出字串包含 `OBLIGATES`／`PERMITS`／`PROHIBITS`／`DEEMS`；傳入空 tuple 時不包含。
5. **BFS 可達性測試**：建一條 `rel_type="OBLIGATES"` 的邊（比照既有 `bfs_query()` 測試的 fixture 建法），預設 `cfg` 呼叫 `bfs_query()` 必須能走到這條邊；額外驗證 `cfg` 為空 extensions 時這條邊**不會**出現在遍歷結果裡（或至少不會被當成合法邊——需視既有測試對「非法 rel_type 的邊」的既有行為決定斷言方式，若既有 fixture 資料庫建邊本身就要求 `rel_type` 合法，這條負向測試可以簡化為「確認 `_effective_rel_types(空cfg)` 不含 `OBLIGATES`」，不必真的建一條不合法的邊）。
6. **快取 key 隔離測試**：用兩個不同的 `descriptions` 字典各呼叫一次 `_type_description_embeddings()`（同一個 `embedding_provider`），斷言兩次快取結果不同、且各自正確反映傳入的 `descriptions`（防止 T3 的快取 key 漏改導致互相污染）。
7. **`resolve_query_relation_type()` 測試**：比照既有測試慣例（用 `FakeEmbedding` 讓某個查詢動詞向量偏向 `OBLIGATES` 描述句），驗證預設 `cfg` 下能解析出 `OBLIGATES`；`cfg` 為空 extensions 時同一個查詢動詞不會被判定為 `OBLIGATES`（因為候選集合裡根本沒有這個型別）。
8. 全套 `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py` 必須全綠。

---

## 3. 明確不要做的事

- **不要**修改 `core/constants.py::SVO_REL_TYPES` 或 `SVO_REL_TYPE_DESCRIPTIONS`——這是論文第二章明文定義的 ConceptNet 35 個核心關係，本任務全程不碰這兩個常數本身。
- **不要**修改 `docs/論文/` 任何檔案。是否正式寫入論文、要不要補 LKIF-Core 查證，是後續獨立決定的事。
- **不要**在程式碼註解、commit message、或任何文件裡宣稱「依據 LKIF-Core」——只能寫「命名靈感來源未查證」這類誠實表述，比照任務書 §0／T1 的措辭。
- **不要**處理 `EXPAND` 治理機制（`services/expand_worker.py`）——那是另一套「從實際抽取動詞有機聚類發現新型別」的機制，跟本任務「人工預先定義好 4 個型別」是不同的路徑，不要混在一起改，也不要嘗試讓兩者互通。
- **不要**對任何既有 KG 執行重抽或改動 Neo4j 資料——新型別只影響「之後新抽取」的三元組，不回溯既有資料，既有邊的 `rel_type` 維持原樣。
- **不要**調整 `COMPARE_COSINE_THRESHOLD`／`QSIM_ASSIGN_THRESHOLD`／`QSIM_ESCALATE_LOW_THRESHOLD` 這幾個既有門檻數值——本任務只擴充候選型別集合，不涉及門檻校準。

## 4. 完成定義

1. `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py` 全綠。
2. `SVO_REL_TYPES`／`SVO_REL_TYPE_DESCRIPTIONS` 兩個常數本身的 diff 為零（`git diff` 確認未被觸碰）。
3. `docs/論文/` 目錄下沒有任何檔案被改動（`git diff --stat -- docs/論文/` 為空）。
4. T8 §3 的兩組對照測試都通過，證明 `generic`（空 extension）與 `taiwan-labor-law`（4個extension）在抽取、BFS 遍歷、查詢端解析三處的行為確實不同，機制真的生效。
5. commit message 必須包含本任務書 §0 的文獻誠實聲明原文或等義表述（不可省略，這是使用者明確要求的紅線）。
6. **不需要**、也**不應該**在本任務內對任何 KG 執行實際重抽或改變 Neo4j 資料。

---

## 5. 給 Codex 的指令（可直接貼上）

> 請執行 `docs/報告/77_法律模態關係型per-KG擴充SDD任務書.md` 的 T1-T8。這是新增一個 per-KG 可覆蓋的法律模態關係型別擴充機制（`OBLIGATES`／`PERMITS`／`PROHIBITS`／`DEEMS`），解決「應/得/不得/視為」目前被壓扁成通用 `RELATED_TO`／`CAUSES` 的問題。
>
> **兩條紅線,不可妥協**：(1) `core/constants.py::SVO_REL_TYPES`／`SVO_REL_TYPE_DESCRIPTIONS` 兩個常數**完全不能改**——這是論文第二章明文定義的 ConceptNet 5.5 官方 35 個核心關係，有完整查證訂正紀錄，任何修改都會破壞這個學術主張。新型別一律透過新的 `DomainConfig.rel_type_extensions` 機制加入，所有需要「合法關係型別集合」或「型別描述句」的地方改用任務書 T2 定義的 `_effective_rel_types()`／`_effective_rel_type_descriptions()` 有效集合，不要直接動 `SVO_REL_TYPES`。(2) **不可在任何程式碼註解、commit message 或文件宣稱這 4 個型別「依據 LKIF-Core」**——本專案從未查證過這份文獻，只能誠實記為「命名靈感來源未查證，本專案原創設計」，且**不要修改 `docs/論文/` 任何檔案**。
>
> **技術重點在 T3**：`classify_relation_by_embedding()`／`_type_description_embeddings()` 的描述句 embedding 快取目前只用 `embedding_provider.model_name` 當 key，本任務要讓它同時支援不同 KG 用不同的描述集合（`SVO_REL_TYPES ∪ rel_type_extensions`），**快取 key 必須把描述集合內容也納入**，否則不同 domain pack 的 KG 會互相汙染快取結果——任務書 T8.6 有專門的隔離測試，務必確保通過。
>
> 完成後跑 `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py` 確認全綠並回報結果，並確認 `git diff --stat -- core/constants.py docs/論文/` 兩者皆為空（前者只能加新函式不能動常數本身內容，後者必須完全不動）。commit 前不需要額外詢問，但**不要**對任何 KG 執行重抽或改動 Neo4j 資料，也不要處理 `services/expand_worker.py`。commit message 需包含文獻誠實聲明（不可宣稱 LKIF-Core 已查證）。
