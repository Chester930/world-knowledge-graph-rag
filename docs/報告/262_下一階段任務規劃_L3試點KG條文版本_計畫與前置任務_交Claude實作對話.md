# 報告262：下一階段任務規劃——L3′「條文版本試點 KG」計畫與前置任務（Q1 語料建構器、Q2 匯入偵察；交 Claude 實作對話；皆不連資料庫）

> **日期**：2026-10-03
> **性質**：階段計畫＋首批任務書。分工：**規劃對話決定、起／管試點容器、實跑匯入與抽取、獨立驗證；Claude 實作對話寫離線程式與測試**（其使用者規則禁止碰 docker／Neo4j／`.env`）。**本文件只由規劃對話修改（§9 執行紀錄）。**
> **依據**：[報告257](257_關係狀態機落地設計審查_依最新證據更新報告234.md) §5 L3′；[報告260 §11](260_下一階段任務規劃_L2補驗_as_of時間維度與L1真實資料庫行為_交Claude實作對話.md)（L2′ 通過）；[報告236](236_P1條文版本真實資料盤點.md)／[237](237_P2條文版本轉狀態機事件原型與真實案例示範.md)；使用者「依照建議繼續」＝採納規劃對話對 D3／D5 等的建議（見 §2）。
> **基準**：HEAD ≥ `991590f`；全量 pytest **2064 passed**；`kg2-neo4j` 基準 StartedAt＝`2026-10-02T11:09:32.79429649Z`（**試點全程不連它**）。
> **本任務的性質**：離線程式與測試。**不得連 KG#4（17990）、不得操作 docker、不得讀 `.env`、不得連 Ollama／Neo4j。**

---

## 1. 為什麼做試點、範圍多大（〔事實〕，來自 P1 盤點 `data/analysis/law_version_inventory_20261001.json`）

KG#4 只有現行版（報告257 §3），無法驗證 Fact 層「被取代」。collector 的歷史檔有真實修法資料，**規模很小**：4 個 snapshot 檔 → 去重後 220 筆條文版本、**111 條文章**（N0030001 勞基法 189 筆、N0030006 勞工請假規則 31 筆）；98 條有多版本（96 條 2 版、1 條 7 版、1 條 8 版——後兩者是 snapshot 不一致造成的 `version_id` 差異，見 §2）；109 組相鄰版本對：**23 組雜湊相同、42 組僅排版、44 組實質修改**。**44 組實質修改是試點的核心**；其餘作對照。

**試點範圍（建議）**：44 組實質修改的「舊版＋新版」（約 88 個條文版本）＋ 約 10 組「僅排版」與 10 組「雜湊相同」當對照（控制組：驗證不誤判為修法）。合計約 **100 個條文版本、預估 100–200 個 SVO chunk**；以先前全量重抽約每 chunk 近 1 分鐘（本機 `qwen2.5:7b`，CPU）估，**抽取約數小時**（〔推論〕，實際由 Q3 量測）。

## 2. 使用者已採納的決定（「依照建議繼續」）與我的處理

| 項目 | 決定 |
| --- | --- |
| **D3 資料口徑** | 條文版本身分＝（pcode, **正規化條號**, `valid_from`）；以**最新的 snapshot 檔**（`moj_history_20260819T093233Z-history.json`）為權威；`version_id` 在不同 snapshot 不一致的條文（勞基法第 86 條、請假規則第 12 條）**不裁決**，列入 manifest 的 `conflicts` 並**排除出試點對照組**（保留供報告揭露）。collector 的 `valid_to` 缺口（相鄰版本日期全不銜接，109 組中 0 組銜接）**不修**——試點以 `valid_from` 鏈推導舊版 `valid_to`（＝下一版 `valid_from`），並在 manifest 記錄原始值與推導值 |
| **D5 試點容器** | 允許規劃對話另起專用容器 `kg2-pilot-neo4j`（具名磁碟區 `kg2-pilot-data`、埠 28474／28687、3 GB；**不碰 `kg2-neo4j`／`kg2_neo4j_data`／KG#4**），並由規劃對話操作 docker |
| **D6 可檢索集合** | 維持 `{缺席, 候選, 有效, 爭議}` |
| **D1／D2** | 時間感知檢索需要（以試點驗證）；L1 已完成 |
| **仍待確認** | 試點抽取為數小時的本機 Ollama 工作；我開跑前會再確認無其他對話佔用 Ollama／記憶體（dify／n8n 目前為 Exited）。Ollama 目前 **0.35.0**（凍結評測時為 0.34.2），**版本漂移須在報告揭露**，試點結果**不與凍結基準直接比較** |

## 3. 階段計畫

| 階段 | 內容 | 執行者 | 本文件是否派出 |
| --- | --- | --- | --- |
| **Q1** | 試點語料建構器（collector 歷史檔 → 試點文件資料夾＋ manifest），離線、可測 | 實作對話 | ✅ |
| **Q2** | 匯入偵察：以既有「請假與排班」匯入腳本為範本，寫出把試點文件資料夾匯入**指定 Neo4j＋kg_id**並入抽取佇列的可執行流程（含離線可測部分） | 實作對話 | ✅ |
| **Q3** | 起試點容器、匯入、抽取（本機 Ollama，數小時）、量測每 chunk 耗時 | 規劃對話 | ⏳（Q1／Q2 完成後） |
| **Q4** | 為 LawArticle 補版本屬性與 `SUPERSEDED_BY`、條文層連動事件、`as_of` 檢索原型 | 實作對話寫、規劃對話跑 | ⏳ |
| **Q5** | 時間感知問題集（約 12–20 題，由 44 組實質修改撰寫，gold 取自 collector 原文）與評測（有／無 `as_of` 過濾） | 實作對話寫題、規劃對話驗證與跑 | ⏳ |
| **Q6** | 報告與使用者裁示（是否進 L4） | 規劃對話 | ⏳ |

## 4. Q1 規格：試點語料建構器 `scripts/analysis/pilot_version_corpus_builder.py`

輸入：collector 的 4 個歷史檔（路徑預設 `D:\Users\666\Desktop\labor-compliance-collector\data\processed\moj_laws\moj_history_20260819T0*-history.json`；**只讀**，絕不修改 collector）。可重用 `scripts/analysis/law_version_inventory.py` 的載入／去重／差異分類函式（**不得修改它**，import 重用）。

1. **身分與去重**：（pcode, 正規化條號, `valid_from`）；正規化條號沿用 P1／P2 的做法（NFKC＋去空白）；衝突（同身分不同 `content_hash` 或 `version_id`）一律取最新 snapshot 檔，並寫入 `conflicts`；勞基法第 86 條與請假規則第 12 條（已知 snapshot 不一致）必須出現在 `conflicts` 且**不納入對照組**。
2. **選材**：全部「實質修改」相鄰版本對（P1 的 `substantive`）的舊版與新版；另取 `format_only` 與 `same_hash` 各最多 10 組當對照（依 pcode、條號排序的**決定性**選取，不得隨機）。
3. **雜訊處理**：條文文字中的 `::: 最新訊息…` 導覽雜訊要在輸出前截除（沿用 P1／P2 的「操作型截尾」規則）；截除筆數與原始／截後長度記入 manifest，**不得宣稱已清除所有雜訊**。
4. **輸出（均在 repo 之外，預設 `D:\Users\666\Desktop\kg-runtime-pilot\<pilot_kg_id>\`；`pilot_kg_id` 由參數給定或腳本以固定命名空間 `uuid5` 產生並寫入 manifest）**：
   - 每個（法規, 版本）一個資料夾，`source` 命名 `<pcode>_<法規名>@<valid_from>`（例 `N0030006_勞工請假規則@2023-05-01`），內含 `original.md`，**格式與 KG#4 的 `original.md` 完全一致**（前置 `---\nsource: "…"\n---\n\n`，每條 `第 N 條\n\n<條文>\n\n`，條號格式 `第 N 條`／`第 N-M 條`，與 `LawArticle.article_no` 一致）；
   - `pilot_manifest.json`：每個條文版本的身分、`valid_from`、推導 `valid_to`、原始 `valid_to`、`version_id`、`content_hash`、差異類別、選材角色（`substantive_old`／`substantive_new`／`control_format_only`／`control_same_hash`）、所屬資料夾、是否為衝突／雜訊截除；另有統計摘要與 `conflicts` 清單。
5. **決定性**：同輸入必得同輸出（含檔案內容、排序、`pilot_kg_id`）；寫入前檢查輸出目錄必須在 `kg-runtime-pilot` 之下且**不在 repo 內**，否則拒絕。
6. **測試**（`tests/scripts/test_pilot_version_corpus_builder.py`，用小型假歷史檔、不依賴 collector 實體路徑）：身分與去重、衝突處理與排除、選材決定性、雜訊截除、`original.md` 格式（與 KG#4 真實檔結構逐行比對一個範例：先以 `D:\Users\666\Desktop\kg-runtime\236903cf-055a-40a8-8923-b9d06601f3b7\N0030006_勞工請假規則\original.md` 的前 20 行建立測試期望，**只讀**）、輸出路徑守衛、manifest 欄位完整。
7. **實跑與報告**：實作者可以對真實 collector 檔**唯讀**實跑一次（這不連任何資料庫），把 manifest 摘要（各角色筆數、衝突清單、雜訊截除筆數）寫進報告；產出的語料資料夾**不得進 repo**。

## 5. Q2 規格：匯入偵察 `scripts/kg/pilot_import.py`（＋偵察報告）

**目標**：給定試點語料資料夾（Q1 輸出）與目標 Neo4j（以環境變數指定，**不改 `core/config.py`**）、目標 `kg_id`，完成「建立 KG→建立 `Document`／`LawArticle` 節點→產生 SVO chunk→入抽取佇列」，並說明如何啟動抽取 worker。

1. **偵察順序**（先讀碼，**寫進報告 263 §偵察**）：①`create_clean_leave_scheduling_kg.py`、`import_leave_scheduling_dataset.py`、`filter_leave_scheduling_dataset.py`（根目錄；先前「請假與排班」匯入的實際做法）；②`repositories/law_document_repo.py`、`models/law_document.py`（`Document` 的 `update_date`／`effective_date`／`effective_note`／`content_hash`／`source_url`／`record_type`）；③`services/svo_chunking.py`、`services/extraction_worker.py`（`_process_one`、佇列 `task_queue` 的鍵 `(kg_id, source, chunk_index)`）、`scripts/kg/reextract_chunks.py`；④`services/document_record_service.py`（`document_uuid`＝`uuid5(DOCUMENT_ID_NAMESPACE, source)`、`_record.json`）。要回答：**哪些既有函式／腳本已能完成哪幾步、哪幾步需要寫新程式**；Neo4j 連線如何由環境變數覆寫（`core/config.py` 的 `neo4j_uri`／`neo4j_user`／`neo4j_password`，pydantic-settings 環境變數優先於 `.env`）；工作目錄（`workspace_dir`、kg-runtime）如何指到試點資料夾；抽取用的 LLM／embedding provider 設定來源（Ollama `qwen2.5:7b`、`bge-m3`）。
2. **腳本**：`pilot_import.py` 支援 `--plan`（**只列出將執行的步驟與數量、不連線**，離線可測）與 `--execute`（真正連線；**實作者不得執行**，由規劃對話執行）；`--execute` 必須驗證目標 URI 的埠為 28687（或參數明確允許的非 17990／27687 埠）、拒絕 17990、拒絕 `kg2-neo4j` 相關名稱；`kg_id` 必須等於 manifest 的 `pilot_kg_id`。密碼只從環境變數讀入、**不得印出**。
3. **版本屬性**：`LawArticle` 目前沒有版本欄位。匯入後**不在本步驟寫版本屬性**（那是 Q4）；但 manifest 要提供 Q4 需要的對照（`LawArticle` 識別＝`source_doc_id`＋`article_no` → 版本身分）。
4. **測試**（離線）：`--plan` 輸出（步驟、筆數）、URI／埠／名稱閘門、`pilot_kg_id` 比對、密碼不外洩、對 `core/config.py` 零修改。
5. **回報偵察的不確定處**：任何「讀碼仍不確定能否直接重用」的步驟請列出（我在 Q3 會以真實小型試跑確認），不要自行猜測。

## 6. 共同限制與驗收

- **附帶小項（報告260 §11.5-1）**：`services/relation_lifecycle.py` 模組開頭 docstring 仍寫「不比較日期」，而 `state_as_of` 首次以 ISO 字串比較日期；請**只修正該 docstring 的敘述**（純文字、不改任何程式與常數），並在報告 263 註明。
- 範圍：新增 `scripts/analysis/pilot_version_corpus_builder.py`、`scripts/kg/pilot_import.py`、對應測試、報告 263、索引一行、`HANDOVER.md` 頂部條目，以及上述 docstring 一句文字修正；**其餘既有 production、既有腳本與測試、`core/config.py`、規劃文件、論文、題庫、歷史報告原文零變動**；collector 目錄零寫入。
- 我驗收：讀碼閘門；**我自行實跑 Q1 並與你的 manifest 逐項對照**（筆數、衝突、決定性）；對 `pilot_import.py --plan` 核對步驟；全量 pytest ≥ 2064＋新增數、節點卡 0 警告、`.env` 敏感值外洩掃描 0 命中。
- **停止條件**：需要連 Neo4j／Ollama／docker／讀 `.env`；需要修改 `core/config.py` 或任何既有 production 檔才能完成；讀碼發現既有匯入流程**無法**指向非預設 Neo4j（回報原因與最小可行改法，**不要自行改**）；collector 檔格式與 P1 盤點描述不符。

## 7. 編號、約定、回報

實作者報告自 **263** 起（先 `ls docs/報告`）。繁體中文；conventional commit；**commit 只 add 自己的檔案、不用 `git add -A`**（我們共用工作目錄）；push 本分支。**不得自稱已驗證。** 完成時 SendMessage 回報規劃對話，格式：`Q1／Q2｜結論｜commit SHA｜manifest 摘要（各角色筆數／衝突清單／雜訊截除筆數）｜偵察結論（哪些步驟可重用既有程式、哪些要新寫、不確定處）｜`--plan` 範例輸出｜新增測試數與全量 pytest｜是否連過資料庫／Ollama／docker／.env（應為否）｜偏離報告262之處（無則寫無）`。

## 8. 不在本任務範圍

起容器、匯入、抽取、版本屬性與連動、問題集、評測（Q3–Q6）；對 KG#4 的任何寫入。

## 9. 執行紀錄（僅規劃對話更新）

✅ **Q1／Q2 已於 2026-10-03 由規劃對話獨立驗證通過**（commit `f724562`；執行紀錄見[報告263](263_L3試點Q1語料建構器與Q2匯入偵察執行紀錄.md)）。**本階段全程未連 KG#4、未碰任何資料庫／docker／Ollama。**

**規劃對話驗證摘要**
1. **範圍**：`git diff d2866c6..HEAD` 為實作者自己的 9 個檔案；`core/` 零變動；`services/relation_lifecycle.py` 只改**一句模組 docstring＋一行註解**（純文字，附帶小項已完成）。
2. **獨立重算（不重用實作者的建構器，直接讀 collector 最新 snapshot 檔）**：身分（pcode, 正規化條號, `valid_from`）去重後 **209 版本／111 條文章／98 組相鄰版本對，無重複身分**；我自己的簡化分類（hash 相同／NFKC＋去空白後相同／其餘）得 **same_hash 23、format_only 31、substantive 44**，與 manifest 逐項相同；入選的 44 條實質修改條文集合＝我算出的集合；對照組 10＋10 皆為我分類下對應類別的子集。
3. **輸出檔內容抽查**：4 個資料夾（勞基法@1984-07-30 與 @2024-07-31 各 61 條、請假規則@2023-05-01 與 @2025-12-09 各 3 條）**128 個條文版本逐條與 collector 原文（去空白）比對 0 不一致**；4 個含導覽雜訊的版本（恰為衝突條文）截除一致；`original.md` 檔頭前綴與 KG#4 的 `original.md` **位元組相同**（僅 `source` 多 `@<valid_from>`）。
4. **決定性**：重跑建構器前後輸出目錄（5 個檔案）SHA-256 **完全相同**。
5. **`pilot_import.py --plan`（我自己跑）**：`connects:false`；4 份文件、128 個 `LawArticle` 節點、預期 128 個 SVO chunk；閘門讀碼：埠預設 28687、禁 17990／27687／7687、拒絕含 `kg2-neo4j` 的 URI、`--kg-id` 必須等於 manifest 的 `pilot_kg_id`。
6. 全量 pytest **2114 passed**（2064＋50）、節點卡 0 警告、`.env` 敏感值對 9 個檔 0 命中。

**對實作者決策點（報告263 §2.4）的裁定**
- 衝突條文（勞基法第 86 條、請假規則第 12 條）的實質修改對**仍入選**，manifest 以 `is_conflict` 標記；**評測的主要指標排除這 4 個版本**，另列為附帶觀察。
- 對照組全落在勞基法（依 pcode、條號排序取前 10 的副作用）：**接受**，但評測報告須揭露「請假規則沒有對照組」。
- 文件粒度＝（法規, `valid_from`）的選入條文子集；法規名去掉 ` EN` 後綴：接受。
- **重要發現（接受並列入限制）**：collector 歷史檔的 `content` **完全沒有換行**，而 KG#4 的 `original.md` 來自另一份有項目換行與章標題的資料——結構相同、內容空白不同，所以**試點的抽取輸入與 KG#4 不同，影響未量測**；試點內部新舊版同源同格式，故**時間感知驗證本身不受影響**，但試點的抽取品質**不可與 KG#4 比較**。

**待 Q3 小型試跑確認的三點**（實作者列出）：①`trigger_extraction` 的 `kg_folder` 參數（照 router 傳）；②「已匯入」以 `svo_index.json` 判斷；③`Document` 日期欄位留空（Q4 決定）。另：`--worker` 為實作者新增（`run_extraction_worker`＋同閘門），本 worktree 找不到註解提到的 `drain_queue.py`。
