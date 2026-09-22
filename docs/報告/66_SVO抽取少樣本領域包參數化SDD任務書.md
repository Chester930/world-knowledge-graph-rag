# 66 SVO 抽取少樣本領域包參數化SDD任務書（報告33 §6「3b步」落地，**交付 Codex**）

**建立日期**：2026-09-22
**文件性質**：交付 Codex 執行用任務書。設計成冷啟動可用——不需要本對話的上下文即可接手，但**必須等報告65的定向重抽驗證（背景 fork）完全跑完、且沒有未預期問題後才開始**，因為本任務會編輯 `services/svo_service.py::_svo_prompt()`，跟驗證 fork 讀取的是同一份檔案，同時動會互相汙染結果判讀。
**分支／工作區**：`worktree-sdd-retrieval-comparison`，`D:\Users\666\Desktop\world knowledge graph rag\.claude\worktrees\sdd-retrieval-comparison`
**前置依賴**：報告65（`docs/報告/65_抽取粒度修復設計SDD任務書.md`）方向A已核准並完成 prompt 修改（commit `35f95ab`，新增規則10）；本任務接續處理報告65 §3.1 補記段落點出的架構缺口——目前 `_svo_prompt()`（含規則1-10）是單一全域寫死函式，沒有per-KG覆蓋機制。

---

## 0. 一頁摘要

**要解決的問題**：`services/svo_service.py::_svo_prompt()` 目前對所有 KG 一視同仁，規則1-10（含規則6-10各自附帶的具體例句，皆使用台灣勞動法規詞彙如婚假、事假、特別休假、中高齡職訓補助）寫死在單一 Python 函式裡。這是專案自己已記錄在案的已知缺口（`docs/論文/04_系統實作.md`「尚未做」清單，報告33 §6 稱為「3b步」；`config/domain_packs/generic.json` 的 `_note` 欄位也明講「svo 抽取少樣本…仍為第 3b–4 步待抽項」）。

**設計原則（使用者已拍板，報告65 §3.1 補記）**：通用與特定的關係應該是**參數注入到共用骨架**，不是「每個 domain 各自整份複製 `_svo_prompt()`」。落地方式：

- **共用骨架（不變、所有 domain 共用）**：JSON 輸出格式、`rel_type`／實體型別參考清單、規則1-5（皆為無例句的通則）。
- **可注入參數（`svo_fewshots`，per-domain 可覆蓋）**：規則6-10**各自的「規則說明＋反例＋正確做法」整塊**（這五塊全部都用台灣勞動法規詞彙舉例，是真正domain-specific的部分）。

**驗收標準**：`taiwan-labor-law` domain pack（含「不載入任何 pack」的 shipped defaults）組出來的最終 prompt 字串，必須跟修改前**逐字相同**（golden test 比對）；`generic` domain pack 可以用不同的 `svo_fewshots`（含空清單），但本任務**不需要**同時解決報告33 §5 R4「空 few-shot 拖累 qwen 遵循度」這個已知風險——只要求機制本身正確、有測試覆蓋、行為對現有 KG 零變化，`generic` 的具體 few-shot 內容選擇留給後續任務。

---

## 1. 現況（已用程式碼逐一查證，非推測）

1. **`_svo_prompt()`**（`services/svo_service.py:211-306`，行號可能因報告65改動略有偏移）：純函式，只吃 `text: str` 一個參數，內部字串常數包含規則1-10全部內容（含每條規則的反例／正確做法）。
2. **`extract_svo_triples()`**（`services/svo_service.py:462` 起）：呼叫 `_svo_prompt(text)`（無其他參數），本身**沒有** `cfg: KGConfig` 參數——這跟同檔案其他函式（`_reconcile_rel_type()`、`bfs_query()`）已有的 `cfg: KGConfig | None = None` DI 慣例不一致，是本任務要補上的缺口之一。
3. **`extract_svo_triples_with_completeness_check()`**（`services/svo_service.py:950` 起）：包一層 `extract_svo_triples()`，同樣沒有 `cfg` 參數。
4. **呼叫端**：`services/extraction_worker.py:83` 呼叫 `extract_svo_triples_with_completeness_check(chunk["text"], ..., kg_id=kg_id, calibration_db_path=db_path)`，**沒有載入或傳遞任何 `KGConfig`**——目前抽取 Worker 完全不知道 domain pack 這回事。
5. **查詢端（`chat()`）已有的對照範例**——`routers/agent.py:1516-1534`：
   ```python
   domain_pack: str | None = None
   try:
       kg_meta = await KGRepository(driver).get(payload.kg_id)
       if kg_meta is not None:
           domain_pack = kg_meta.domain_pack
   except Exception:
       domain_pack = None
   cfg = ConfigLoader([FileConfigSource(settings.kg_config_dir)]).load(
       payload.kg_id, domain_pack=domain_pack,
   )
   ```
   這是**唯一需要複製到抽取端的模式**：KG 節點本身有 `domain_pack` 欄位（`KnowledgeGraph` model，經 `KGRepository.get()` 讀出），查無或讀取失敗一律退回 `None`（＝shipped defaults，安全降級），不是抽取端要另外發明一套機制。
6. **`KGConfig` 目前的欄位分區**（`core/kg_config/model.py`）：`DomainConfig` 已有 `name`／`system_context`／`target_language`；`ExtractionConfig` 目前只有 `uncovered_sentence_threshold` 一個數值欄位，兩者都**沒有** `svo_fewshots` 欄位。
7. **domain pack 檔案實際佈局**（`core/kg_config/sources.py::FileConfigSource`）：**單一檔案**，`<root>/domain_packs/<name>.json`（或 `.toml`/`.yaml`），內容是巢狀 mapping 直接對應 `KGConfig` 欄位樹（例：`{"domain": {"system_context": "..."}}`）——**不是**報告33 §3 插圖畫的「domain pack 資料夾底下 `pack.json` + 獨立 `svo_fewshots.json` 兩個檔案」那種佈局，那張圖只是概念示意，實際實作是攤平進同一份 JSON。`config/domain_packs/generic.json`、`config/domain_packs/taiwan-labor-law.json` 兩份現存檔案可直接參考格式。
8. **golden test 慣例**（`tests/core/test_kg_config.py`）：`test_kgconfig_defaults_match_live_module_constants()` 逐欄位比對 shipped defaults 是否等於「重構前」的模組常數／字串；`test_shipped_domain_pack_files_parse()` 驗證 `taiwan-labor-law.json` 套用後 `== KGConfig()`（等於沒套任何 pack）。**新欄位一律要延續這個慣例**：shipped default 必須逐字等於現行硬編碼內容，並新增對應 golden test。

---

## 2. 任務清單

### T1（S）：`KGConfig` 新增 `svo_fewshots` 欄位

- 在 `core/kg_config/model.py::DomainConfig` 新增：
  ```python
  svo_fewshots: tuple[str, ...] = Field(default_factory=lambda: _DEFAULT_SVO_FEWSHOTS)
  ```
  `_DEFAULT_SVO_FEWSHOTS` 是一個模組層級常數（放在 `model.py` 或 `svo_service.py`，擇一，但**只能有一份、另一邊 import**，不可重複定義兩份字串造成漂移），內容為**5 個字串**，逐字對應現行規則6/7/8/9/10各自的「規則說明＋反例＋正確做法」整塊文字（**不含開頭的數字編號**，例如規則7的內容應以「若一句話常常包含不只一件事實…」開頭，不含「7. 」前綴——編號由組裝端動態加，見T2）。
- 為什麼放 `DomainConfig` 而不是 `ExtractionConfig`：`ExtractionConfig` 目前的角色是「抽取完整性自檢的數值門檻」（報告19），`svo_fewshots` 屬於「domain 具體內容」，跟 `system_context`／`target_language` 同一類，放 `DomainConfig` 概念上一致；若你評估後認為放 `ExtractionConfig` 更好，需在 commit message／本報告回填說明理由，不要求死守，但要有交代。
- **不要**同時處理 `guard_profile`——那是另一個獨立的待辦項（CJK 守衛正則），不在本任務範圍，混在一起會讓 diff 難審查。

### T2（M）：`_svo_prompt()` 改為吃 `fewshots` 參數並動態編號

- 簽名改為 `def _svo_prompt(text: str, *, fewshots: Sequence[str] | None = None) -> str`；`fewshots is None` 時 fallback 用 `_DEFAULT_SVO_FEWSHOTS`（T1 那份常數），確保**任何既有呼叫端不傳新參數時行為零變化**。
- 組裝時把規則1-5（骨架，維持現況不動）與 `fewshots` 動態編號串接：
  ```python
  fewshot_block = "\n\n".join(f"{6 + i}. {block}" for i, block in enumerate(fewshots))
  ```
  插入原本規則5之後、`文本：{text}` 之前。
- **驗收方式**：寫一個測試，`_svo_prompt("測試")` 用預設 `fewshots=None` 產出的字串，必須跟報告65修改後（commit `35f95ab`）當下的 `_svo_prompt("測試")` 輸出**逐字相同**——可以在改動前先跑一次舊版輸出存成 fixture 字串，改完後比對，這是本任務唯一不能妥協的回歸測試。

### T3（M）：`extract_svo_triples()`／`extract_svo_triples_with_completeness_check()` 新增 `cfg` 參數

- 比照 `bfs_query()`／`_reconcile_rel_type()` 既有慣例，新增 `cfg: KGConfig | None = None`（keyword-only），內部 `_cfg = cfg or KGConfig()`，呼叫 `_svo_prompt(text, fewshots=_cfg.domain.svo_fewshots)`。
- `extract_svo_triples_with_completeness_check()` 原樣把 `cfg` 往下傳給 `extract_svo_triples()`，不需要自己額外處理 `svo_fewshots`（完整性自我核對用的是既有 `ExtractionConfig.uncovered_sentence_threshold`，跟 few-shot 無關，兩者不要混在一起改）。

### T4（M）：`services/extraction_worker.py` 載入並傳遞 `KGConfig`

- 比照 `routers/agent.py:1516-1534` 的既有模式：抽取 chunk 前，查該 `kg_id` 的 `KGRepository(driver).get(kg_id)` 取出 `domain_pack` 欄位（查無或例外一律退回 `None`，比照既有「安全降級」慣例，不可讓抽取因為 config 查詢失敗而整批中斷），再用 `ConfigLoader([FileConfigSource(settings.kg_config_dir)]).load(kg_id, domain_pack=domain_pack)` 組出 `cfg`，傳入 `extract_svo_triples_with_completeness_check(..., cfg=cfg)`。
- 需要確認 `extraction_worker.py` 目前是否已經有 `driver`／`settings` 在作用域內可用（大概率有，因為要建 KG 連線本來就需要），若沒有現成的，找最小侵入的方式取得，不要為此重新設計 Worker 的依賴注入架構。
- **效能提醒**：`ConfigLoader().load()` 是同步、輕量的檔案讀取＋pydantic驗證，若抽取 Worker 是逐 chunk 迴圈呼叫，考慮每個 `kg_id` 只查一次 `domain_pack`／組一次 `cfg`（迴圈外快取），不要每個 chunk 都重新打一次 `KGRepository`，但這是效能優化、不是正確性要求，若時間有限可以先每次都查、正確性優先，效能优化留 TODO 註記即可。

### T5（S）：domain pack 檔案更新

- `config/domain_packs/taiwan-labor-law.json`：**不需要改動**——不覆蓋任何欄位＝沿用 shipped defaults，本來就等於現行規則6-10逐字內容，T1 已經把它們放進 shipped default。
- `config/domain_packs/generic.json`：目前完全沒有 `svo_fewshots` 欄位（＝套用後仍是 shipped defaults 的規則6-10，含勞動法規例句）。本任務**只需要**確認這個「不覆蓋 = 沿用預設」的行為符合預期並補一句 `_note` 說明（例如註明「svo_fewshots 尚未客製化，沿用 shipped defaults」），**不需要**在本任務內決定 `generic` 該放什麼樣的中性 few-shot 內容——那涉及報告33 §5 R4 的風險評估與可能的獨立實測，超出本任務範圍，留給後續任務處理，本任務只要求機制本身正確。

### T6（S）：測試

- `tests/services/test_svo_service.py`：新增/更新測試涵蓋
  - `_svo_prompt(text, fewshots=None)` 與明確傳入 `_DEFAULT_SVO_FEWSHOTS` 結果相同；
  - 傳入自訂 `fewshots`（例如只給2個字串）時，動態編號從 `6.`／`7.` 開始且沒有斷號；
  - `extract_svo_triples()` 未傳 `cfg` 時行為與修改前相同（可用既有 fake `LLMProvider` 斷言送給它的 prompt 字串內容）。
- `tests/core/test_kg_config.py`：新增 golden test，比對 `KGConfig().domain.svo_fewshots` 逐字等於 `_DEFAULT_SVO_FEWSHOTS`（跟現有 `test_kgconfig_defaults_match_live_module_constants()` 同一種模式，可以加進同一個測試函式或新增一個）。
- 全套 `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py` 必須維持全綠，且**新增測試數要能反映實際新增的行為**，不是形式上湊數。

---

## 3. 明確不要做的事

- 不處理 `guard_profile`（CJK 守衛正則 token 清單）——獨立待辦，不在本任務。
- 不處理 `_NATURALIZE_PROMPT_TEMPLATE` 的繁體假設（`docs/論文/04_系統實作.md` 同一條「尚未做」清單裡的另一項，跟 `svo_fewshots` 分屬不同函式，混在一起改會讓 PR 難審查）。
- 不決定 `generic` domain pack 的 `svo_fewshots` 具體內容該放什麼（T5 已註明）。
- 不對任何既有 KG 執行重抽——本任務只改程式與設定檔，不觸碰 Neo4j 資料；重抽驗證是報告65方向A的範圍，已由另一個背景流程處理，不要重複執行 `scripts/kg/reextract_chunks.py`。
- 不修改 `routers/agent.py` 的既有 `chat()` domain pack 載入邏輯——那段已經正確運作，本任務只是把同一套模式複製到抽取端，不是重構查詢端。

## 4. 完成定義

1. `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py` 全綠。
2. 對 `taiwan-labor-law`／未指定 domain pack（shipped defaults）兩種情況，組出的 `_svo_prompt()` 最終字串與報告65 commit `35f95ab` 當下逐字相同（golden test 保證，不是人工肉眼比對）。
3. `services/extraction_worker.py` 能正確依 `kg_id` 讀出 `domain_pack` 並組出對應 `KGConfig`，`domain_pack` 查無或讀取失敗時安全退回 shipped defaults（有測試覆蓋這條降級路徑）。
4. commit message／PR 描述清楚交代：新增了什麼欄位、放在哪個 Config 分區、為什麼（若偏離本報告 T1 的建議需說明理由）。
5. **不需要**、也**不應該**在本任務內對任何 KG 執行實際重抽或改變 Neo4j 資料。

---

## 5. 給 Codex 的指令（可直接貼上）

> 請執行 `docs/報告/66_SVO抽取少樣本領域包參數化SDD任務書.md` 的 T1-T6。這是報告33 §6「3b步」的落地：把 `services/svo_service.py::_svo_prompt()` 目前寫死的規則6-10少樣本例句，改成可透過 `KGConfig.domain.svo_fewshots` 依 domain pack 覆蓋的參數，規則1-5維持共用骨架不動。已有的查詢端對照範例在 `routers/agent.py:1516-1534`（`domain_pack` 讀取＋`ConfigLoader` 組裝），抽取端 `services/extraction_worker.py` 要比照同一套模式，不要另外發明機制。**驗收的唯一不可妥協項**：shipped defaults／`taiwan-labor-law` domain pack 組出來的最終 prompt 字串，必須跟目前 commit（`35f95ab`，含報告65規則10）逐字相同，用 golden test 保證，不能只靠人工比對。完成後跑 `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py` 確認全綠並回報結果；commit 前不需要額外詢問，但**不要**對任何 KG 執行重抽或改動 Neo4j 資料，也不要處理 `guard_profile`／`_NATURALIZE_PROMPT_TEMPLATE`（不在本任務範圍）。若對 T1「`svo_fewshots` 放 `DomainConfig` 還是 `ExtractionConfig`」有不同判斷，可以自行決定但要在 commit message 說明理由。
