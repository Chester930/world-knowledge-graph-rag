# 報告235：下一階段任務規劃——條文版本真實資料盤點（P1）與「條文版本→狀態機事件」純運算原型（P2），**交 Codex 執行**

> **日期**：2026-10-01
> **性質**：階段任務規劃。分工：**規劃對話（Claude）決定與獨立驗證、Codex 執行、規劃對話只記錄**。**本文件只由規劃對話修改（§9 執行紀錄）**。
> **依據**：使用者在討論後的決定——**D1**：用姊妹專案 `labor-compliance-collector` 的**現有**多版本資料做真實驗證（P1 盤點＋P2 原型，**不重新收集、不連外網、不修改該專案**）；**D2**：民國日期正規化降級為「必要時再做」（該批資料日期已是 ISO）；**D3**：預設可檢索狀態集合＝{缺席, 候選, 有效, 爭議}（排除 已被取代／已終止／已駁回），**為參數、不寫死、不接線**；**D4**：新增獨立「撤銷」事件（轉已駁回）；**P3（拋棄式 Neo4j 驗證）放最後、P1／P2 完成後由使用者單獨決定，本任務不做**。
> **基準**：全量 pytest **1838 passed／0 failed**（`python -m pytest -q -p no:cacheprovider`，約 70 秒）。
> **背景**：[報告233](233_關係狀態機接進圖譜的位置盤點與儲存選項.md)、[報告234](234_關係狀態機落地設計說明_Fact層儲存方案.md)、記憶 `reference_labor_compliance_collector`（規劃對話已查證的資料事實，見 §2）。
> **本任務完全不需要連 Neo4j、不啟動 Ollama／LLM、不呼叫 embedding、不改任何 production 既有檔（除 P0 明列者）、不接線、不改 KG#4、不新增儲存欄位、不改論文與題庫。**

---

## 1. 任務總覽

| ID | 任務 | 性質 |
| --- | --- | --- |
| **P0** | `services/relation_lifecycle.py` 新增「撤銷」事件（D4）與預設可檢索狀態集合常數（D3）＋測試 | 小幅變更（純運算、零接線） |
| **P1** | 條文版本真實資料盤點（唯讀）＋報告 | 唯讀分析腳本＋報告 |
| **P2** | 「條文版本→狀態機事件」純運算原型＋以真實資料做測試材料＋示範 | 新增純運算模組＋測試＋示範 |

順序：P0 → P1 → P2；P1 與 P2 的發現若互相矛盾以 P1 為準並在報告說明。

## 2. 資料事實（規劃對話已查證；Codex 請先**自行重新核對**，不一致就回報）

來源專案（**唯讀**）：`D:\Users\666\Desktop\labor-compliance-collector`（使用者自己的獨立 git 專案）。

- 歷史條文檔：`data\processed\moj_laws\moj_history_20260819T0*-history.json` 共 4 檔，每筆欄位含 `pcode／law_name／article_no／content／version_date／valid_from／valid_to／is_current／valid_from_basis／version_id／content_hash／retrieved_at／source_url`（日期已是 ISO）。
- 規劃對話統計（請重算）：`moj_history_20260819T093233Z-history.json` 有 209 筆（`N0030001` 勞動基準法 184、`N0030006` 勞工請假規則 25）；`N0030001` 有 86 條含 2 個版本（`1984-07-30` 原版、`2024-07-31` 現行），其中 72 條 `content_hash` 不同；`N0030006` 有 12 條含 2 個版本（`2023-05-01`、`2025-12-09`），3 條（第 7、9、12 條）內容不同。另外 `moj_history_20260819T092044Z-history.json` 較早、`N0030001` 只有現行版本。
- **已知資料品質問題**：①部分「不同」只是排版或用詞（例如多一個空白、「辭」→「詞」、「左列」未改）；②內容混有網頁導覽雜訊（例如 `N0030006` 第 12 條含「::: 最新訊息 中央法規 司法解釋 條約協定…」）；③`N0030001` 只看到原版與現行兩版，**中間歷次修正是否缺漏尚未驗證**；④多個 history 檔內容可能重複（後三檔筆數相同）。
- 收集器自己的文件寫明：歷史條文**尚未批量收集**，`LawHistories` 只是沿革索引。

**Codex 對該專案的權限**：**只准讀** `data\processed\moj_laws\*.json` 與其根目錄的 `*.md` 說明文件。**嚴禁**：讀取或印出 `.env`、讀取 `.claude\`／`.git\`、執行該專案的任何程式（會寫檔且可能連外網）、在該專案內寫入或修改任何檔案。需要的資料**複製成小型測試材料**放進本專案 `tests/fixtures/`（只複製必要欄位與必要條文，並在 `README` 記錄來源檔名、筆數與 sha256）。

## 3. P0 規格

在 `services/relation_lifecycle.py`（**維持純運算、僅標準庫、仍零接線**）：
1. 新增事件常數 `REVOKED = "撤銷"`，納入 `CORE_EVENTS`；新增核心轉換：`(有效, 撤銷)→已駁回`、`(爭議, 撤銷)→已駁回`、`(已終止, 撤銷)→已駁回`。**「候選」不加撤銷**（從未採信者直接以「驗證不通過」或實體刪除，見報告234 W3）。其餘既有轉換**不得改動**，終點狀態仍不得轉出。
2. 新增常數 `DEFAULT_RETRIEVABLE_STATES`＝`frozenset({None, 候選, 有效, 爭議})`（`None`＝缺席＝尚未處理）與純函式 `is_retrievable(state, retrievable=DEFAULT_RETRIEVABLE_STATES)`；**僅常數與函式，不被任何現有程式使用**。docstring 寫明：這是參數、非定案，且在還沒有自動「驗證通過」流程前，不可把「候選」排除，否則檢索會消失（報告234 §4）。
3. 同步更新既有測試與示範：既有的「所有非允許的 狀態×事件 組合」參數化測試要隨新事件自動涵蓋；`scripts/analysis/relation_lifecycle_demo.py` 的輸出若因此改變，須**重產** `data/analysis/relation_lifecycle_demo_20261001.json` 並說明差異（預期只有「事件總數」之類的描述性數字）；補測：新轉換、撤銷在候選／終點被拒、擴充機制不得破壞新核心轉換、`is_retrievable` 各狀態。
4. 不得改變 `LifecycleSpec` 的驗證語意（擴充不得重述／刪除核心轉換等規則照舊）。

## 4. P1 規格（唯讀盤點）

新增唯讀腳本（`scripts/analysis/`，純標準庫；**純運算與檔案讀取分離並附單元測試**），輸出報告與 JSON。必須回答：
1. **盤點**：4 個 history 檔各自的筆數、`pcode` 分布、`is_current` 分布、不同 `version_date` 數；**跨檔去重後**共有多少 `(pcode, article_no, version_id)`（說明去重鍵與重複狀況）。
2. **版本鏈**：每條文有幾個版本（分布）；舊版的 `valid_to` 與新版的 `valid_from` 是否銜接（相差 1 天算銜接，其餘列出）；`is_current` 與 `valid_to is None` 是否一致；有多版本卻沒有 `is_current=True` 或有多個 `is_current=True` 的條文列出。
3. **差異分類**（對有 ≥2 版本的條文）：(a) `content_hash` 相同；(b) 去除導覽雜訊、全部空白與全形半形差異後相同（僅排版）；(c) 其餘文字不同。**對 (c) 類抽樣至少 15 筆逐筆人工檢視**並標註「實質修改／用詞或標點調整」，**明寫這是人工抽樣、非定論**；不得用 LLM。
4. **雜訊**：偵測並計數含網頁導覽雜訊（如「::: 最新訊息」）的記錄，說明雜訊起訖的判定規則與誤判風險。
5. **與本專案語料的對應（只用本機檔案，不連資料庫）**：本專案語料位於 `D:\Users\666\Desktop\kg-runtime\236903cf-055a-40a8-8923-b9d06601f3b7\<文件夾>\original.md`（文件夾名形如 `N0030001_勞動基準法`）。回報兩個 `pcode` 是否都有對應文件夾；以「條文現行版文字（正規化後）是否出現在 `original.md`」抽查至少 10 條，說明對應率。**做不到就明寫原因，不得為此連 Neo4j。**
6. **完整性結論**：這批資料能支撐什麼、不能支撐什麼（例如：勞基法只有兩版、中間修正是否缺漏如何判斷）；**不得宣稱資料完整**。

## 5. P2 規格（純運算原型）

新增純運算模組（建議 `services/law_version_events.py`，位置由執行者依專案架構與節點卡規範決定並說明理由；**僅標準庫＋可匯入 `services.relation_lifecycle`；無 I/O、無時間函式、無資料庫；匯入不改 `os.environ`**）：
1. 輸入：版本記錄（欄位至少 `pcode／article_no／content／content_hash／valid_from／valid_to／is_current／version_id`）。
2. **以「（pcode, article_no）」為單位**排序成版本鏈；每個版本是一個**關係實例**（僅此原型的輸入概念，非儲存結構）。
3. 為每個版本產生事件序列並以 `relation_lifecycle.replay` 重播得到狀態：官方來源版本一律 `抽取完成`→`驗證通過`（`evidence_ref=version_id`、`reason` 註明官方來源、`trigger_kind` 取 `事件`）；**非最新版本**追加 `新版取代`（`effective_date`＝**後繼版本的 `valid_from`**；`reason` 帶差異分類：實質修改／僅排版／相同，分類規則與 P1 (a)(b)(c) 一致，**重用或共用 P1 的純函式**，不得兩套邏輯）。
4. `check_exclusivity`：同一（pcode, article_no）同一時刻**最多一個「有效」**——對真實資料驗證，違規與資料異常（如 P1 發現的 `is_current` 不一致）要**回報而不是靜默修正**。
5. 提供「版本鏈→事件→最終狀態」的可讀說明（沿用 `explain`），並輸出**真實案例示範**：至少涵蓋 `N0030006` 勞工請假規則第 7、9、12 條（2023→2025 修法）與 `N0030001` 勞動基準法至少 3 條（含「實質修改」與「僅排版」各至少一條）。
6. 測試：以 `tests/fixtures/` 的小型真實材料（見 §2）＋少量手寫邊界資料；涵蓋：單一版本、兩版、三版、日期不銜接、`is_current` 異常、有雜訊、內容相同／僅排版／實質修改、`valid_to` 缺漏、決定性（同輸入同輸出）、不就地修改輸入。
7. **誠實限制須寫入報告**：①這只驗證**條文層**的版本取代；KG 裡只有現行條文抽出的 Fact，**沒有舊版 Fact**，所以 **Fact 層的取代無法用這批資料驗證**；②僅 2 部法規；③勞基法版本鏈可能缺漏；④差異分類是字面規則，**不是語意判定**；⑤未涵蓋 CORRECTION、矛盾偵測。

## 6. 驗收（規劃對話會自己驗，不採信自述）

- 範圍：`git diff --name-only` 僅允許：`services/relation_lifecycle.py`（P0）、其測試與示範輸出、新增 `services/law_version_events.py`（或執行者說明的位置）與其測試、P1／P2 腳本與測試、`tests/fixtures/`、報告／索引／`HANDOVER.md` 頂部條目；**不得動**其他既有 production 檔、規劃文件（報告155–235 規劃部分與 `Lumori簡報語意層對照與缺口檢查_v0.2.md`）、論文、題庫，**也不得在 `labor-compliance-collector` 內留下任何變更**（我會檢查該專案 `git status` 與檔案時間）。
- `ast.dump`：`relation_lifecycle.py` 只允許新增常數與函式、新增 3 條核心轉換與 1 個事件，**既有函式本體邏輯不變**；
- `git grep`：新模組與 `is_retrievable` 除測試與腳本外**沒有任何現有 `.py` 匯入**（零接線）；匯入只有標準庫與 `relation_lifecycle`；
- **數字我自己用 collector 原始檔重算**（筆數、版本數、差異分類、雜訊計數）；fixtures 的 sha256 與來源逐筆一致；
- 抽查至少 5 個轉換案例（含真實 `N0030006` 第 7、9 條）、至少 5 筆人工差異標註；
- 全量 pytest ≥1838 passed／0 failed（P0 的新測試應使數字上升）；`check_node_cards.py` 不新增警告；
- 密碼外洩比對（`.env` 密碼值對所有新檔 0 命中；Codex 不需讀 `.env`，本專案 `.env` 的 `NEO4J_PASSWORD` 由我比對）。

## 7. 停止條件（遇到即停止並回報）

1. 需要連 Neo4j、啟動 Ollama／LLM、連外網，或執行 collector 的程式；
2. 需要修改 collector 專案或本專案其他 production 檔；
3. §2 的資料事實與你重新核對的結果有重大出入（例如檔案不存在、欄位不同、版本數差很多）；
4. P0 發現新增撤銷轉換會破壞既有核心不變量；
5. 工作區出現非自己的未提交檔：逐檔指定路徑 commit，不得 `git add -A`；`HANDOVER.md` 先看 `git diff -U0`；commit／push 後以 `git rev-list --left-right --count origin/worktree-sdd-retrieval-comparison...HEAD` 確認 `0 0`。

## 8. 編號、約定與回報

本文為 **235**；執行者新報告自 **236** 起（先 `ls docs/報告`）。**Codex 無法傳訊**：把結果寫進報告與 `HANDOVER.md` 頂部條目、commit、push，並由使用者貼回最後回報；**不得自稱已驗證**。回報格式：`P0／P1／P2｜結論｜commit SHA｜關鍵數字｜偏離報告235之處（無則寫無）`。**同一時間只能有一個執行者**：Codex 動工期間請勿再對 Claude 執行對話（`fact-rag vector search implementation`）下新任務。

## 9. 執行紀錄（僅規劃對話更新）

| ID | 狀態 | 結論 | commit | 備註 |
| --- | --- | --- | --- | --- |
| P0 | ⏳ 待交 Codex | — | — | — |
| P1 | ⏳ | — | — | — |
| P2 | ⏳ | — | — | — |
