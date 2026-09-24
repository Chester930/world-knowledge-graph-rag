# 76 guard_profile 領域可插拔化SDD任務書（報告33「第4步」落地，**交付 Codex**）

**建立日期**：2026-09-25
**文件性質**：交付 Codex 執行用任務書。設計成冷啟動可用——不需要本對話的上下文即可接手。
**分支／工作區**：`worktree-sdd-retrieval-comparison`，`D:\Users\666\Desktop\world knowledge graph rag\.claude\worktrees\sdd-retrieval-comparison`
**前置依賴**：報告66（`svo_fewshots` 領域包參數化，2026-09-22 已完成，`KGConfig.domain.svo_fewshots`）——本任務延續同一條「設定分層」Track，是 `core/kg_config/model.py` 模組 docstring 明寫的「第4步：guard_profile token 清單」。**不依賴**任何進行中的 natural_text／組裝端修復（報告67/68/69），但**會編輯同一份 `services/svo_service.py`**——動手前先確認該檔案沒有其他背景流程正在編輯，避免衝突。

---

## 0. 一頁摘要

**要解決的問題**：`services/svo_service.py:544-604` 有 4 組模組層級的正則常數（`_MEASURE_PATTERN`／`_RANGE_COMPARATOR_PATTERN`／`_ENUM_GUARD_PATTERN`／`_SCOPE_MODIFIER_PATTERN`），對所有 KG 一視同仁地寫死。它們是 `resolve_entity_name()`（模糊合併早退守衛）與 `_naturalization_dropped_quantity()`（自然語言化遺漏核對）共用的「量詞／比較詞／列舉格式／範圍修飾詞」安全網，目前只服務台灣勞基法語料。這是專案自己已記錄在案的已知缺口（`core/kg_config/model.py` 模組 docstring：「`guard_profile` token 清單仍留待第4步」；報告33 §4.3 插圖）。

**⚠️ 跟報告66不同，這不是單純的文字塊替換**——這 4 組正則背後是報告20／26／29／32 四份報告的**真實迴歸案例**（見 §1.2），每一條都對應一次曾經發生過的錯誤模糊合併或內容遺漏。本任務的風險核心是：抽出「哪部分是可依 KG 客製化的 domain token 清單」時，**絕對不能讓任何一個既有案例重新失效**。

**設計原則（本任務書拍板，非既有慣例延伸——因為報告33/45的插圖只是概念示意，未曾實際定案切法）**：

- **可配置（domain token 清單，隨 KG 客製）**：
  - `_MEASURE_PATTERN` 的單位詞清單（`個月／個年／個星期／日／月／年／次／小時／分鐘／百分之／％／%／元／倍／等級／歲／人／名／週／度／種／類／條／款／項／點`）
  - `_RANGE_COMPARATOR_PATTERN` 的比較詞（後置：`以上／以下／以內`；前置：`未滿／超過`）
  - `_SCOPE_MODIFIER_PATTERN` 的修飾詞（`增加／增列／額外／追加／新增／另計／加計／超出`）
  - `_ENUM_GUARD_PATTERN` 裡的封閉列舉值部分（`顯著／中度／低度風險` ——這是職業安全風險分級的具體業務詞彙，不是通用中文格式）
- **維持結構不變（CJK 通用格式，不隨 KG 客製）**：
  - 中文數字字元類、比較句式的「數字與比較詞間隔至多12個非標點字元」樣式（`_RANGE_COMPARATOR_PATTERN` v2，報告32 §9.3 F2）
  - `_ENUM_GUARD_PATTERN` 的序數／分數／小數／附表／「之N」結尾格式（這些是中文列舉書寫慣例，不是台灣勞基法特有的詞彙，其他中文法規領域大概率一樣適用）

若你（Codex）在實作時判斷這個切法有問題，**可以調整，但必須在 commit message 說明理由**，比照報告66 T1 的慣例。

**驗收標準**：shipped defaults（不載入任何 domain pack）組出來的 4 組正則，對 §1.2 列出的**每一個**歷史迴歸案例，比對結果必須跟目前程式碼完全一致（golden test，非人工比對）。

---

## 1. 現況（已用程式碼逐一查證，非推測）

### 1.1 四組正則現況

1. **`_MEASURE_PATTERN`**（`services/svo_service.py:544-553`）：中文數字（含「至」連接的範圍）+ 單位詞清單，用於 ① `resolve_entity_name()` 早退守衛（`services/svo_service.py:1200-1205`）② `_naturalization_dropped_quantity()` 逐欄位抓量詞核對（`services/svo_service.py:1729-1737`，供 `_naturalize_triple()` 呼叫，`services/svo_service.py:1814`）。
2. **`_RANGE_COMPARATOR_PATTERN`**（`services/svo_service.py:573-576`）：v2（報告32 §9.3 F2）允許數字與比較詞之間至多12個非標點字元。只用於 `resolve_entity_name()` 早退守衛。
3. **`_ENUM_GUARD_PATTERN`**（`services/svo_service.py:589-596`）：序數／分數／小數／附表／「之N」結尾／風險等級六選一。只用於 `resolve_entity_name()` 早退守衛。
4. **`_SCOPE_MODIFIER_PATTERN`**（`services/svo_service.py:604`）：修飾詞清單，用於 `resolve_entity_name()` 的**雙向過濾**（不是早退，見 `services/svo_service.py:1207` 之後的邏輯，需自行讀取完整範圍確認雙向過濾實作細節，本任務書不代為摘錄以免與實際程式碼有出入）。

### 1.2 每組正則的既有真實迴歸案例（golden test 必須逐一覆蓋，不可省略任何一項）

以下全部抄錄自 `services/svo_service.py` 現行程式碼註解，**不是本任務新發現**，是既有防護的存在理由：

| 案例 | 對應正則 | 來源 |
|---|---|---|
| `四千`／`八千`、`五日`／`十日`、`三十日以上`／`未滿三十日` 不可模糊合併 | `_MEASURE_PATTERN`（前身 `_QUANTITY_PATTERN`） | 2026-08-?? |
| `年齡未滿六歲者`／`六歲以上未滿十二歲者`／`十二歲以上未滿十五歲者` 三段工時上限不可合併 | `_MEASURE_PATTERN`（擴大版，含「歲」） | 發現C／診斷Q3 |
| `三個月為限`／`六個月為限` 期程分段 | `_MEASURE_PATTERN`（`個月／個年／個星期`） | 報告32 §9.3 E3 |
| `血中鉛濃度十μg/dl以上者` vs `五μg/dl以上未達十μg/dl（第一級）` 不可合併 | `_RANGE_COMPARATOR_PATTERN` v2（間隔12字元） | 報告32 §9.3 F2，Q6 |
| `1以上，未滿10` vs `100以上，未滿1000`（變量係數表5段被誤併成2個節點案例，N0060004） | `_RANGE_COMPARATOR_PATTERN` | 報告29 §2.4／§4.3，報告26 §4 #3 Q8 |
| `二十公尺以上`、`五百平方公尺以上` | `_RANGE_COMPARATOR_PATTERN` v2 | 報告32 §9.3 F2 |
| `第三級管理` vs `第一級管理` | `_ENUM_GUARD_PATTERN`（序數） | 報告32 §9.3 F3b |
| `二分之一`／`五分之一` | `_ENUM_GUARD_PATTERN`（分數） | 同上 |
| `30.6℃`／`32.6℃`（WBGT溫度） | `_ENUM_GUARD_PATTERN`（小數） | 同上 |
| `附表一`／`附表二` | `_ENUM_GUARD_PATTERN`（附表） | 同上 |
| `精密作業之一`／`精密作業之三` | `_ENUM_GUARD_PATTERN`（「之N」結尾） | 同上 |
| `具顯著／中度／低度風險者` 三值互不可合併 | `_ENUM_GUARD_PATTERN`（風險等級列舉） | 任務C第9組真實重抽，2026-09-18 |
| `每一型式` vs `每增加一種型式`（`_edit_ratio`＝0.727） | `_SCOPE_MODIFIER_PATTERN` | 報告29 §4.1／報告32 §9.3 §4.1 |
| `災害發生之當月一日起` 改寫後「一日」不可消失 | `_MEASURE_PATTERN`（`_naturalization_dropped_quantity` 路徑） | 報告26 §4 #6 |

### 1.3 現有 DI 慣例可直接複製

- `resolve_entity_name()`（`services/svo_service.py:1153`）**目前不接受 `cfg` 參數**——這是本任務要補上的缺口，比照報告66 T3 的 `cfg: KGConfig | None = None`（keyword-only）慣例。
- `_naturalize_triple()`（`services/svo_service.py:1764`）與 `_naturalization_dropped_quantity()`（`services/svo_service.py:1720`）同樣**不接受 `cfg`**。
- `services/extraction_worker.py` 已經在報告66落地了 `_load_kg_config(kg_id, domain_pack)` 這個 helper（見該檔案 `_load_kg_config` 函式），**直接重用，不要重新發明**——本任務只需要把已經載入的 `cfg` 再往下傳一層到上述三個函式。
- `resolve_entity_name()` 的呼叫端在 `services/svo_service.py:1418` 附近（`merge_triples_to_graph()` 或其呼叫鏈，需自行確認函式邊界），`_naturalize_triple()` 的呼叫端在 `services/svo_service.py:2039` 與 `2672` 附近——這幾處都需要補上 `cfg` 傳遞。
- `core/kg_config/model.py` 現有子模型（`RelTypeConfig`／`ExtractionConfig`／`DomainConfig`）都是 `frozen=True`、每個欄位附「對應現行模組常數」的註解，golden test 逐欄位比對——本任務新增的 `GuardConfig` 必須遵循同一慣例。

---

## 2. 任務清單

### T1（M）：`core/kg_config/model.py` 新增 `GuardConfig`

```python
class GuardConfig(BaseModel):
    """實體模糊合併與自然語言化核對的 CJK 守衛 token 清單
    （`services/svo_service.py` `_MEASURE_PATTERN`／`_RANGE_COMPARATOR_PATTERN`／
    `_SCOPE_MODIFIER_PATTERN`／`_ENUM_GUARD_PATTERN` 的可配置部分）。

    只收「domain 詞彙清單」，不收正則的結構性樣式（中文數字字元類、比較句式
    間隔長度、序數/分數/小數/附表格式）——那些是 CJK 通用書寫慣例，維持
    寫死在 svo_service.py，不隨 KG 客製化。
    """

    model_config = _FROZEN

    # services/svo_service.py::_MEASURE_PATTERN 單位詞清單
    measure_units: tuple[str, ...] = Field(default_factory=lambda: _DEFAULT_MEASURE_UNITS)
    # services/svo_service.py::_RANGE_COMPARATOR_PATTERN 後置比較詞（數字在前）
    range_trailing_comparators: tuple[str, ...] = Field(
        default_factory=lambda: _DEFAULT_RANGE_TRAILING_COMPARATORS
    )
    # services/svo_service.py::_RANGE_COMPARATOR_PATTERN 前置比較詞（數字在後）
    range_leading_comparators: tuple[str, ...] = Field(
        default_factory=lambda: _DEFAULT_RANGE_LEADING_COMPARATORS
    )
    # services/svo_service.py::_SCOPE_MODIFIER_PATTERN 修飾詞清單
    scope_modifier_words: tuple[str, ...] = Field(
        default_factory=lambda: _DEFAULT_SCOPE_MODIFIER_WORDS
    )
    # services/svo_service.py::_ENUM_GUARD_PATTERN 封閉列舉值部分（風險等級）
    enum_closed_values: tuple[str, ...] = Field(default_factory=lambda: _DEFAULT_ENUM_CLOSED_VALUES)
```

- 5 個 `_DEFAULT_*` 常數放在 `model.py`（跟 `_DEFAULT_SVO_FEWSHOTS` 同一種模式），內容**逐字對應現行 `services/svo_service.py` 正則裡的 token**，禁止漏抄或改寫用字。
- 加進 `KGConfig`：`guard: GuardConfig = Field(default_factory=GuardConfig)`。
- **不要**把 `_ENUM_GUARD_PATTERN` 的序數／分數／小數／附表／「之N」結尾部分做成可配置——那是本任務書 §0 拍板維持結構不變的部分，混進去會讓正則組裝邏輯複雜度失控，且沒有任何 KG 客製化的實際需求佐證。

### T2（L）：4 組正則改為「結構固定＋token 清單注入」的組裝函式

- 每組正則從模組層級常數，改成 `_build_xxx_pattern(cfg: GuardConfig) -> re.Pattern` 函式（或等效的惰性建構＋快取，避免每次呼叫重新 `re.compile`——同一個 `cfg` 值應該只編譯一次，可用 `functools.lru_cache` 但注意 `GuardConfig` 是 frozen pydantic model，需確認可雜湊，否則改用簡單的模組層級 dict 快取，key 用 `cfg.guard` 的 tuple 欄位組成的 tuple）。
- shipped defaults（`GuardConfig()`）建出來的 4 個 `re.Pattern`，其 `.pattern` 字串必須跟目前 `services/svo_service.py:544-604` 現行常數的 `.pattern` **逐字相同**——這是本任務唯一不可妥協的回歸保證，寫成 golden test（比對 `.pattern` 字串，不是比對行為，兩者都要有）。
- **不要**改動 `_RANGE_COMPARATOR_PATTERN` 的「間隔至多12個非標點字元」樣式、`_ENUM_GUARD_PATTERN` 的序數/分數/小數/附表/「之N」子樣式、`_MEASURE_PATTERN` 開頭的中文數字字元類與「至」範圍連接——這些維持模組層級寫死常數，`_build_xxx_pattern()` 只負責把 token 清單用 `|`.join() 插入固定模板的對應位置。

### T3（M）：`resolve_entity_name()`／`_naturalization_dropped_quantity()`／`_naturalize_triple()` 新增 `cfg` 參數

- 比照報告66 T3 的 DI 慣例：`cfg: KGConfig | None = None`（keyword-only），內部 `_cfg = cfg or KGConfig()`，用 `_cfg.guard` 取得（或組出）4 組正則。
- `_naturalization_dropped_quantity()` 目前是同步純函式（`def`，非 `async def`）——維持同步，只加 `cfg` 參數，不要順便改成 async。
- `resolve_entity_name()` 呼叫端（`services/svo_service.py:1418` 附近）與 `_naturalize_triple()` 呼叫端（`2039`／`2672` 附近）都要補上 `cfg=cfg` 傳遞——這幾處函式呼叫鏈往上追，最終應該接到 `extraction_worker.py::_process_one()` 已經載入的 `cfg`（報告66落地），**不要另外重新查詢一次 `domain_pack`**。
- 若某個呼叫鏈（例如即時查詢路徑而非抽取路徑）目前沒有 `kg_id` 可用來查 `domain_pack`，比照報告66「查無或例外一律退回 `None`（＝shipped defaults，安全降級）」的既有慣例，不要讓抽取因為 config 查詢失敗而中斷。

### T4（S）：`extraction_worker.py` 確認 `cfg` 已傳遞到位

- 報告66已經讓 `extraction_worker.py` 載入 `cfg` 並傳給 `extract_svo_triples_with_completeness_check()`。本任務要確認同一個 `cfg` 也傳到 T3 新增的三個函式的呼叫點（如果它們的呼叫發生在 `extraction_worker.py` 能觸及的範圍內；若呼叫發生在 `svo_service.py` 內部更深層，`cfg` 應該已經透過函式參數鏈路傳下去，不需要 `extraction_worker.py` 額外處理）。
- **不要**重新設計 `extraction_worker.py` 的整體結構，只補齊參數傳遞。

### T5（S）：domain pack 檔案

- `config/domain_packs/taiwan-labor-law.json`：不需要改動——shipped defaults 已經逐字等於現行 4 組正則的 token 清單。
- `config/domain_packs/generic.json`：確認「不覆蓋 `guard` 欄位 = 沿用 shipped defaults（含台灣勞動法規詞彙）」的行為符合預期，比照報告66 T5 補一句 `_note` 說明（例如「`guard` 尚未客製化，沿用 shipped defaults」）。**不需要**決定 `generic` 該用什麼中性 token 清單，留給後續任務。

### T6（L，使用者明確要求加強）：迴歸測試套件

這是本任務**驗收權重最高**的部分，不可簡化：

1. **§1.2 表格逐條轉成 parametrized pytest**（`tests/services/test_svo_service.py`）：每一列案例的關鍵字串，用 shipped defaults 建出的正則實際跑一次，斷言匹配／不匹配的結果跟表格描述的既有行為一致（例如「`四千`／`八千`必須觸發早退、不進入模糊合併」）。每個測試案例的 docstring 或 test id 要標註來源報告編號，方便未來追溯。
2. **`GuardConfig()` 逐欄位 golden test**（`tests/core/test_kg_config.py`）：比照 `test_kgconfig_defaults_match_live_module_constants()` 的既有模式，逐一比對 5 個 `_DEFAULT_*` 常數與 `services/svo_service.py` 現行正則裡實際使用的 token 是否完全一致（不是「看起來差不多」，是逐字比對）。
3. **4 組 `.pattern` 字串 golden test**：`_build_xxx_pattern(GuardConfig())` 的 `.pattern` 屬性必須跟改動前 `services/svo_service.py` 對應常數的 `.pattern` 屬性完全相同（可在改動前先跑一次存成 fixture 字串）。
4. **`resolve_entity_name()` 行為未變測試**：用 fake candidates（不需要真實 `embedding_provider`/`llm_provider`，因為早退路徑不會走到那兩者），對 §1.2 表格中至少 5 個代表性案例（跨 4 組正則各挑至少1個），驗證 `cfg=None` 與 `cfg=KGConfig()`（shipped defaults）兩種呼叫方式，回傳結果完全相同，且跟改動前的行為一致。
5. 全套 `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py` 必須維持全綠。

---

## 3. 明確不要做的事

- **不要**把 `_ENUM_GUARD_PATTERN` 的序數／分數／小數／附表／「之N」結尾子樣式做成可配置（§0／T1 已說明理由）。
- **不要**改動 `_RANGE_COMPARATOR_PATTERN` 的「間隔至多12個非標點字元」結構樣式，或 `_MEASURE_PATTERN` 開頭的中文數字字元類。
- **不要**調整任何既有門檻數值（`ENTITY_DEDUP_EDIT_RATIO_THRESHOLD`、cosine 門檻等）——本任務只處理 guard 正則的 token 清單參數化，不涉及模糊合併的判定門檻。
- **不要**對任何既有 KG 執行重抽或修改 Neo4j 資料。
- **不要**同時處理報告67／68／69 涉及的 `natural_text` 型別標記洩漏、embedding cache 等問題——雖然同在 `services/svo_service.py`，但屬於不同函式、不同任務範圍，混在一起會讓 PR 難審查。
- **不要**決定 `generic` domain pack 該放什麼樣的中性 guard token 清單（T5 已註明，留給後續任務）。
- 若 T2 的「結構固定＋token 清單注入」拆法在實作中發現行不通（例如某個 token 清單其實跟結構樣式糾纏在一起無法乾淨分離），**停下來在 commit message 或任務書回填說明，不要為了硬套本任務書的設計而犧牲既有迴歸防護**。

## 4. 完成定義

1. `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py` 全綠。
2. §1.2 表格所有案例都有對應 golden test，且全部通過。
3. shipped defaults 建出的 4 組正則 `.pattern` 字串與改動前逐字相同（T6.3）。
4. `resolve_entity_name()`／`_naturalization_dropped_quantity()`／`_naturalize_triple()` 都能接受 `cfg` 參數，`cfg=None` 時行為與改動前完全一致。
5. `extraction_worker.py` 的既有 `cfg` 正確傳遞到新的 guard 相關呼叫點，`domain_pack` 查無或讀取失敗時安全退回 shipped defaults。
6. commit message 清楚交代：`GuardConfig` 的 5 個欄位切法是否有調整、為什麼；T2 的結構固定部分若有調整也要說明。
7. **不需要**、也**不應該**在本任務內對任何 KG 執行實際重抽或改變 Neo4j 資料。

---

## 5. 給 Codex 的指令（可直接貼上）

> 請執行 `docs/報告/76_guard_profile領域可插拔化SDD任務書.md` 的 T1-T6。這是報告33「設定分層」Track 的第4步：把 `services/svo_service.py:544-604` 目前寫死的 4 組正則（`_MEASURE_PATTERN`／`_RANGE_COMPARATOR_PATTERN`／`_ENUM_GUARD_PATTERN`／`_SCOPE_MODIFIER_PATTERN`）拆成「結構固定＋domain token 清單」，token 清單透過新的 `KGConfig.guard`（`GuardConfig`）依 domain pack 覆蓋，結構樣式（中文數字字元類、間隔長度、序數/分數/小數/附表格式）維持寫死不變——任務書 §0/§1 已詳細說明切法與理由。
>
> **這不是單純的文字替換任務**：這 4 組正則背後有報告20/26/29/32 共 14 個真實迴歸案例（任務書 §1.2 表格已逐條列出），你的首要工作是先讀完 §1.2，理解每一條防護在保護什麼，再動手。**驗收的最高權重項是 T6 迴歸測試**：§1.2 表格每一條案例都要有對應 golden test，且必須全部通過，不能只跑既有 pytest 就結案。
>
> 已有的 DI 慣例可直接複製：報告66（`svo_fewshots`）已經在 `extraction_worker.py` 建立 `_load_kg_config()` helper，`resolve_entity_name()`／`_naturalize_triple()`／`_naturalization_dropped_quantity()` 目前都不接受 `cfg`，比照報告66 T3 補上 `cfg: KGConfig | None = None` 慣例即可，不要另外發明機制。
>
> 完成後跑 `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py` 確認全綠並回報結果，commit message 要交代 `GuardConfig` 欄位切法（若跟任務書 §1 建議不同要說明理由）。commit 前不需要額外詢問，但**不要**對任何 KG 執行重抽或改動 Neo4j 資料，也不要處理報告67/68/69 涉及的其他函式。若在實作中發現 §0 的「結構固定 vs 可配置」切法有問題，可以調整，但必須在 commit message 說明理由，並確保 T6 的所有既有迴歸案例仍然通過。
