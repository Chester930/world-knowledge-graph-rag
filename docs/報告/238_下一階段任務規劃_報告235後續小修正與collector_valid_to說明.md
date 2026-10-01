# 報告238：下一階段任務規劃——報告235 後續兩項小修正（交 Codex）＋給使用者的 collector `valid_to` 說明

> **日期**：2026-10-02
> **性質**：階段任務規劃。分工：**規劃對話決定與獨立驗證、Codex 執行、規劃對話只記錄**。**本文件只由規劃對話修改（§7 執行紀錄）。**
> **依據**：報告235 §9 規劃對話驗證後指出的三項後續建議；使用者「同意建議」＝**修正項 1、2 交 Codex**；項 3（collector `valid_to`）只通知使用者（見附錄），**不修改 collector**；P3（拋棄式 Neo4j 驗證）本次**不做**，修正完成後再單獨詢問。
> **基準**：全量 pytest **1861 passed／0 failed**；HEAD ≥ `e88632e`。
> **邊界不變**：不連 Neo4j、不啟動 Ollama／LLM、不連外網、不執行 collector 程式、**不修改 collector 專案**、不改 production 其他檔、不接線、不改論文與題庫。報告236／237 是 Codex 的歷史報告，**不改寫**；改在新報告（239 起）說明更正。

---

## 1. 任務

| ID | 任務 | 性質 |
| --- | --- | --- |
| **F1** | `services/law_version_events.py`：把「不同快照的重複版本」收斂成一個版本，並讓互斥／current 異常不再被鏈序掩蓋 | 小幅修改（純運算、零接線）＋測試 |
| **F2** | 以來源**逐字**重建 `tests/fixtures/law_version_real_sample.json`，並如實更新 README／`fixture_scope`；加自洽測試 | fixtures＋測試 |

順序：F2 → F1（F1 的測試材料依賴逐字 fixtures）。

## 2. F1 規格

**問題（規劃對話已驗證）**：勞動基準法第 86 條與勞工請假規則第 12 條，因不同快照的 `version_id` 不同，被當成 7–8 個版本（多筆相同 `valid_from`、多筆 `is_current=True`）；原型把較早的 `is_current=True` 依鏈序標成「已被取代」，使 `check_exclusivity` 顯示 0 違規，實質上被掩蓋。

**要求**：
1. **收斂規則**：同一 `(pcode, article_no, valid_from)` 且「正規化內容」（沿用現有 `normalize_content`：NFKC＋移除導覽雜訊＋移除空白）相同者，視為**同一版本的重複快照**，收斂為一個版本；代表記錄取 `retrieved_at` 最大者（欄位選用；缺席時取輸入順序最後一筆，並在輸出註明）。同 `(pcode, article_no, valid_from)` 但正規化內容**不同**者，**保留為不同版本**並標示異常 `same_valid_from_different_content`（不得靜默合併）。
2. **收斂過程必須可稽核**：輸出新增 `snapshot_collapses`（每條文：收斂前筆數、收斂後版本數、被收斂的 `version_id` 清單、代表記錄 `version_id`）與 `snapshot_field_conflicts`（同一版本的重複快照之間 `valid_to`／`is_current`／`valid_from_basis` 等欄位不一致的明細；**只回報、不修正**）。
3. **current 旗標異常獨立回報**：新增頂層摘要 `current_flag_anomalies`：列出「收斂**前**」同一條文有多筆 `is_current=True`，以及「收斂**後**」仍有 0 筆或多筆 `is_current=True` 的條文；**不得再讓狀態推導掩蓋這類異常**。`check_exclusivity` 的語意維持（只看「有效」狀態），但輸出須同時帶 `current_flag_anomalies`，並在文件字串寫明兩者的差別。
4. **既有行為不退步**：雙版本且無快照重複的條文，結果必須與改動前**完全相同**（用原 fixtures 與完整來源資料各比對一次：對這類條文逐版本比對 `final_state`、事件序列）；既有函式簽章若需新增參數，須預設保持舊行為並說明。
5. **預期結果（供我驗證；若實際不同請如實回報原因，不要硬湊）**：以完整來源資料（4 個 history 檔，來源專案唯讀）跑原型，勞基法第 86 條應收斂為 2 版（1984 原版、2024 現行）、請假規則第 12 條應收斂為 2 版（2023、2025）；其餘 96 條雙版本與 13 條單版本不變；`exclusivity_violations` 仍為 0，但 `current_flag_anomalies` 應列出第 86 條與第 12 條（收斂前多筆 current）。
6. **測試**：快照重複（同 valid_from 內容只差排版／導覽雜訊）、同 valid_from 內容不同、重複快照間 `valid_to` 不同（衝突回報）、收斂前多筆 current／收斂後 0 筆 current／多筆 current、無 `retrieved_at` 的輸入、既有案例不退步、決定性、不就地修改輸入、純運算（仍零接線、匯入不新增非標準庫）。

## 3. F2 規格

1. 以來源檔 `moj_history_20260819T093233Z-history.json`（只讀；sha256 `3a8aceb9c176fb98ea6cc5cacbba0843daa46385ce08d30b538de62448129d40`）**逐字**重建 12 筆 fixtures（相同條文：勞基法第 2、3、8 條兩版；請假規則第 7、9、12 條兩版）：**所有欄位與 `content` 完整照抄，包含 `law_name` 的「 EN」後綴與請假規則第 12 條完整內容（含導覽雜訊尾巴）**。不再為了「小型」裁剪（完整約數十 KB，可接受）。
2. 加自洽測試：每筆 fixture 的 `content_hash` 必須等於 `sha256(content)`；`version_id` 與 `(pcode|article_no|valid_from|content_hash)` 的雜湊關係若成立（`version_id = sha256(f"{pcode}|{article_no}|{valid_from}|{content_hash}")`，collector 的建構方式見其程式註解〔你只可讀，不可執行〕），也加測試驗證；`README` 逐筆列出來源檔、`version_id`、sha256 與「逐字、未裁剪」聲明，並更新 `fixture_scope`。
3. 為了展現導覽雜訊處理，可**另外**以測試內手寫字串（明確標示為合成材料）驗證 `strip_navigation_noise`，**不得**再用來冒充真實材料。
4. 重跑示範並重產 `data/analysis/law_version_events_demo_20261001.json`（輸出描述性差異於新報告），確認示範的真實案例（請假規則第 7、9、12 條；勞基法至少 3 條）仍成立。

## 4. 驗收（規劃對話自行驗證）

- 範圍：`git diff --name-only` 僅允許 `services/law_version_events.py`、其測試、示範腳本與輸出、`tests/fixtures/`、新報告（239 起）／索引／`HANDOVER.md` 頂部條目；**不得動** `relation_lifecycle.py`（除非為了修 bug 並說明）、其他 production 檔、規劃文件（報告155–238 規劃部分、Lumori v0.2）、論文、題庫、報告236／237 原文，**也不得改動 collector 專案**（我會檢查其 `moj_laws` 資料檔修改時間與 `git status`）。
- `ast.dump`：`law_version_events.py` 的變動僅限收斂邏輯與新增輸出；零接線、匯入無新增非標準庫。
- **我自己用完整來源資料重跑原型**，核對 §2-5 的預期結果與「雙版本不退步」；我自己重算 fixtures 與來源逐字一致（`content`、`content_hash`、`version_id` 全部相同）；
- 全量 pytest ≥1861 passed／0 failed；`check_node_cards` 不新增警告；密碼外洩比對 0 命中。

## 5. 停止條件

1. 需要連 Neo4j／外網／Ollama，或執行／修改 collector；
2. 收斂規則在完整來源資料上產生**意外結果**（例如把真正不同的版本併掉、或某條文收斂後版本數與預期差很多）——停止回報，不要調規則湊數字；
3. 需要修改 `relation_lifecycle.py` 的核心轉換；
4. 工作區出現非自己的未提交檔：逐檔指定路徑 commit，不得 `git add -A`；`HANDOVER.md` 先看 `git diff -U0`；commit／push 後以 `git rev-list --left-right --count origin/worktree-sdd-retrieval-comparison...HEAD` 確認 `0 0`。

## 6. 編號、約定與回報

本文為 **238**；執行者新報告自 **239** 起（先 `ls docs/報告`）。Codex 無法傳訊，結果寫進報告與 `HANDOVER.md`，由使用者貼回；**不得自稱已驗證**。回報格式：`F1／F2｜結論｜commit SHA｜關鍵數字｜偏離報告238之處（無則寫無）`。同一時間只能一個執行者。

## 附錄　給使用者：collector 專案 `valid_to` 的觀察（規劃對話唯讀查證；**本專案不修改 collector**）

**現象（已驗證）**：`data/processed/moj_laws/moj_history_2026081…` 四個檔案中，舊版 `valid_to` 與新版 `valid_from` 的差距：
- 第一輪（`…092044Z`，只有勞工請假規則 12 對）：**差 1 天（銜接）**；
- 後三輪（`…092148Z`、`…092240Z`、`…093233Z`）：**全部差 2 天**（勞基法 86 對＋請假規則 12 對＝98 對），中間空出一天沒有任何有效版本。
- 120 組「同一 `version_id` 卻內容有衝突」的記錄，**衝突欄位全部只有 `valid_to`**，就是這個差異造成的。

**collector 自己的規則（讀碼）**：`src/collect_moj_history_project.py:226` 寫 `valid_to = 後繼版本日期 − 1 天`，第 317 行的 `validity_rule` 也寫「next version valid_from minus one day」。**所以 2 天空隙違反它自己的規則。**

**可能原因（僅為推測，未驗證）**：該檔 213–218 行有一段特殊處理：當舊版頁面的日期恰等於現行版日期時，會把舊版日期往前挪 1 天（`old_date − 1`）。若某輪執行時現行版日期（公布日）與後來寫入的 `valid_from`（生效日）差 1 天，而 `valid_to` 在調整 `valid_from` **之前**就依舊日期算好，就會得到 2 天的差距。建議你在 collector 專案檢視：後三輪執行時 `current_date` 與寫入的 `valid_from` 是否不同，以及 `valid_to` 是在哪一步計算的。

**對本專案的影響**：本專案的 P2 原型以「後繼版本的 `valid_from`」當取代日，**不依賴 `valid_to`**，所以不受影響；但任何依 `valid_to` 判斷「某日適用哪一版」的功能（例如 collector 自己的 `legal_scenario_filter.py` 以 `valid_from`／`valid_to` 比對日期）在那一天會找不到有效版本。這是你專案的問題，由你決定要不要處理。

## 7. 執行紀錄（僅規劃對話更新）

| ID | 狀態 | 結論 | commit | 備註 |
| --- | --- | --- | --- | --- |
| F2 | ✅ 通過（Codex 完成；規劃對話獨立驗證） | 報告239：以來源檔 `moj_history_20260819T093233Z-history.json` 逐字重建 12 筆 fixtures（含 `law_name`「 EN」後綴與請假規則第 12 條完整導覽尾巴）；README 逐筆列來源與雜湊；新增自洽測試 | `5a719b9`（實作）；`2c074d4`（HANDOVER） | **我驗**：我自行重算——12 筆與來源**逐欄完全相同**、無多出欄位；`content_hash == sha256(content)` 12／12；`version_id == sha256(pcode｜條號｜valid_from｜content_hash)` 12／12；fixtures 內記載的來源 sha256 與實際檔案相符。解決了報告235 §9 指出的「6 筆內容被裁剪但雜湊仍為來源值」問題 |
| F1 | ✅ 通過 | `services/law_version_events.py`：依 `(pcode, 條號, valid_from, 正規化內容)` 收斂重複快照，代表列取最大 `retrieved_at`；同日期不同內容保留並標異常；新增 `snapshot_collapses`／`snapshot_field_conflicts`／`current_flag_anomalies`；全量 pytest 1868 passed（基準 1861＋7） | `5a719b9` | **我驗**：①範圍＝`services/law_version_events.py`、其測試、fixtures／README、示範輸出、報告239／索引／HANDOVER；**`relation_lifecycle.py`、`core／routers／repositories／models` 零變動**；零接線（`git grep` 無額外匯入）；匯入無新增非標準庫（`re／unicodedata／datetime／collections／typing`＋`services`）。②**我把「舊版（`859816f`）與新版模組」以同一份完整來源資料（220 筆）各跑一次比對**：111 條文鏈不變；**事件序列有變動的只有 2 條——勞基法第 86 條（7→2 版）與請假規則第 12 條（8→2 版）**，收斂後皆為（已被取代→有效）且 `is_current` 為（False, True）；**其餘 109 條逐版本（`version_id`、`final_state`、事件型別／日期／reason）完全相同**；總計版本 220→209、事件 549→516；互斥違規仍 0。③`snapshot_collapses` 4 群（86：1984 版 3→1、2024 版 4→1；12：2023 版 4→1、2025 版 4→1）；`snapshot_field_conflicts` 4 群（衝突欄位：`content_hash` 4、`valid_to` 3——前者即導覽雜訊差異，後者即 collector 的 `valid_to` 問題）；`current_flag_anomalies`：收斂前多筆 current 2 條、收斂後 0 筆 current 0、多筆 current 0。④鏈異常種類只剩 `date_not_contiguous` 98（collector `valid_to` 2 天空隙，本專案不改）。⑤重跑示範決定性（工作區零變動）；`check_node_cards` 0 警告；**全量 pytest 我重跑＝1868 passed／0 failed**；密碼外洩比對 0 命中（8 個變更檔）。⑥collector：`moj_laws` 7 個資料檔修改時間不變，tracked 變動檔清單與上次驗證相同（排程產物），**無 Codex 修改該專案的證據**。**結論**：報告235 的三項後續建議（快照收斂、fixtures 逐字、collector 說明）全部落實或通知完畢；**仍未驗證的是 Fact 層取代（需 P3）**，且只有 2 部法規 |
