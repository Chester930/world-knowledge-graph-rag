# 報告185：下一階段任務規劃——RQ4a 前置檢查（只讀 Neo4j）、AGGR7 核對材料、腳本匯入期副作用根治

> **日期**：2026-10-01
> **性質**：階段任務規劃。分工同前：**規劃對話決定、執行對話執行、規劃對話只記錄**。**本文件只由規劃對話修改**（§7 執行紀錄）。
> **依據**：使用者「依照建議繼續」＝採用規劃對話對[報告184](184_組別定義入論文與補題準備階段結果彙整.md) §3 六項的建議（見 §1）。
> **基準**：`worktree-sdd-retrieval-comparison` 最新 HEAD；全量 pytest 基準 **1578 passed／0 failed**。
> **本階段不跑任何 RQ 實驗、不重抽、不啟動 Ollama／LLM、不新增題庫條目、不產生 gold、不改論文。**

---

## 1. 報告184 §3 六項：建議與本階段落實

| # | 事項 | 建議（規劃對話；把握度） | 本階段 |
| --- | --- | --- | --- |
| 1 | 別名實例確認後是否出題 | **等使用者逐項核對**（高把握：gold 只能使用者依法規原文核對）；本階段不動 | 不做 |
| 2 | RQ4a 前置檢查是否授權讀 Neo4j | **做，且限定唯讀 Cypher、不啟動 Ollama／LLM、不清空資料**（中把握：這是判斷 RQ4a 值不值得做的最便宜證據；風險在共用 Neo4j／資源衝突，故加防護） | **C1** |
| 3 | AGGR7 `source_article` N0090055 §24 vs N0090058 第二十七條 | **先把兩邊原文並排整理好給使用者核對**（高把握：只讀、降低使用者成本；最終判斷仍歸使用者） | **C2** |
| 4 | 根治 `kg_source_recall_probe_v2.py` 匯入期副作用 | **做**（高把握：scripts 內小修改、已有 7 個測試可驗；消除 B1 只在測試端還原的殘留） | **C3** |
| 5 | 是否跑實驗與重抽範圍 | **維持暫停** | 不做 |
| 6 | 先前未決項 | **維持暫停** | 不做 |

## 2. 階段總覽

| ID | 任務 | 性質 |
| --- | --- | --- |
| **C1** | RQ4a 7 題的 `rel_type` 實際分布（唯讀 Neo4j） | 只讀查詢＋新增報告 |
| **C2** | AGGR7 兩份來源條文並排核對材料 | 只讀＋新增報告 |
| **C3** | 根治 `scripts/eval/kg_source_recall_probe_v2.py` 模組層級 `load_env()` | 小型程式修改（scripts＋tests） |
| **C4** | 階段彙整 | 報告 |

C2、C3 不需任何服務，可先做；C1 需要 Neo4j（唯讀）。C4 最後。

## 3. 各任務規格

### C1：RQ4a 前置檢查（唯讀 Neo4j）

**目標**：把報告183 中 6 題「`rel_type` 分布＝無資料」變成資料，判斷「若改用邊上 `verb`／開放式關係，答案路徑會不會變」。
**前置防護（缺一不可，違反即停止）**：

1. 開始前先確認**沒有其他 session 正在使用同一個 Neo4j／Ollama**（`ListAgents`；必要時 `SendMessage` 詢問）；記錄結果。
2. 使用既有 `kg2-neo4j` 容器（KG#4 端點 `bolt://localhost:17990`，見記憶／`kg-reextract/.env`）。**KG#4（`236903cf`）的資料是唯一副本，絕對不得 wipe／清空／重建**（過往「測試前後 wipe」慣例**不適用**於此容器內的這個 KG）。若容器未啟動，只啟動它，不改任何設定。
3. **只執行唯讀 Cypher（`MATCH … RETURN`）**；不得出現 `CREATE`／`MERGE`／`SET`／`DELETE`／`DROP`／`CALL … WRITE`；腳本以唯讀 session（`default_access_mode=READ`）連線。
4. **不啟動 Ollama／WSL 模型、不呼叫任何 LLM／embedding**。若 `resolve_query_relation_type` 需要 LLM 才能跑，**不要跑**，改用「題目 gold 事實所對應邊的 `rel_type` 直方圖」＋明寫該限制。
**做法**：對報告179／183 的 RQ4a 7 題，依各題 gold 所涉文件／條號，在 KG#4 查：該文件的邊的 `rel_type` 分布（總數與前幾名）、含 `RELATED_TO` 兜底的比例、與題目答案直接相關的邊（以 `source_svo_chunk_index` 或 chunk 範圍定位）的 `rel_type`。逐題回答「答案路徑會不會因 `rel_type` 改用 `verb`／開放式而改變」，**〔推論〕要標明**；有明確資料者標〔事實〕。
**驗收**：每個數字附 Cypher 與回傳行數；Cypher 逐條列出供我檢查是否唯讀；執行前後 **KG#4 節點／關係總數不變**（前後各查一次並寫入報告）；沒有任何 LLM／embedding 呼叫；結論誠實（可能仍是「無法確定」）。
**禁止**：任何寫入；啟動 Ollama；重抽；改題庫；產 gold。
**停止條件**：發現有其他 session 正在使用該 Neo4j／Ollama；容器內 KG#4 資料量與報告記載（Fact／節點數）明顯不符（先回報，不要「修復」）；任何一步需要寫入。

### C2：AGGR7 兩份來源條文並排核對材料

**背景**：報告183 附帶觀察——題庫 `57-AGGR7` 的 `source_article` 列 `N0090055 §24`，而 `N0090058` 第 1 條授權句為「第二十七條」。**可能是題庫來源標錯，也可能是兩個不同條文的有意設計**。
**做法**（只讀）：

- 讀題庫中 `57-AGGR7` 的題幹、`source_article`、gold 片段、`verified` 狀態與來源註記（報告編號）。
- 從 KG 各文件的 `original.md` **逐字摘錄**：`N0090055` 的第 24 條全文、`N0090058` 第 1 條全文（含「依…第二十七條訂定」授權句）、第 27 條所屬的**母法**文件若在語料中（先查語料中是否有該母法，**沒有就明寫「語料內無此母法」，不要憑記憶補**）。
- 輸出並排表：各份摘錄／檔案路徑／chunk 位置／與題幹 gold 的對照（**只呈現文字對照，不下「哪個正確」的法規判斷**）。
**驗收**：每個摘錄逐字可在原檔找到（我會抽查）；明寫「需使用者依官方法規確認」；題庫檔零變更。
**禁止**：不判斷法規正確性；不改題庫；不憑記憶補條文。

### C3：根治腳本匯入期副作用

**問題**：`scripts/eval/kg_source_recall_probe_v2.py:41` 在**模組層級**呼叫 `load_env()`（`os.environ.setdefault` 寫入 kg-reextract 的 `.env`），匯入即汙染整個行程（B1 根因）。
**做法**：把 `load_env()` 呼叫移到 `main()`（或實際需要環境的函式）之內；確認匯入模組不再改變 `os.environ`；`from scripts.eval import kg_source_recall_probe as v1` 之後依賴環境的程式碼（若有模組層級讀環境者）一併檢查並改為延遲讀取，**行為不變**（以命令列執行時載入環境的時機與順序不變）。
**測試**：新增測試 `import` 前後 `os.environ` 不變；既有 `tests/scripts/test_kg_source_recall_probe_v2.py` 7 個仍通過；B1 在測試檔加的快照還原可保留（無害）或移除（若移除須說明並確認全量仍過）——**建議保留**，不增加變更面。
**驗收**：全量 pytest **≥1579 passed、0 failed**（新增測試）；刻意破壞（把 `load_env()` 放回模組層級）新測試必須失敗；`git diff` 僅動 `scripts/eval/kg_source_recall_probe_v2.py` 與 `tests/`；`scripts/eval/` 其餘腳本若有同樣模式**只列出、不改**。
**禁止**：不改 `core/`、`routers/`、`services/`；不改腳本行為；不啟動服務。

### C4：階段彙整

彙整 C1–C3，新增報告（編號接續）：結論、commit、偏離、**待使用者裁示（只列、不代決定）**；補列報告索引與 HANDOVER。

## 4. 停止條件（遇到下列情況停止並回報）

1. C1 發現其他 session 正在使用同一 Neo4j／Ollama，或需要任何寫入／LLM 才能完成。
2. C1 查詢結果顯示 KG#4 資料量與紀載明顯不符。
3. C2 需要判斷法規內容的正確性，或語料不足以並排（如缺母法）而需憑記憶補——**寫「無資料」即可，不要補**。
4. C3 需要改動 production 程式。
5. 工作區出現非自己的未提交檔案：commit 前逐檔指定路徑，不得 `git add -A`；`HANDOVER.md` 先看 `git diff -U0`；commit／push 後以 `git rev-list --left-right --count origin/<分支>...HEAD` 確認同步。

## 5. 編號與約定

本文為 **185**；執行對話自 **186** 起（156 保留）。論文本階段**零變更**。不修改設計草案與報告155／160／164／168／171／174／177／182／185。

## 6. 回報方式（循環派工）

每項驗收並 push 後，立即以 `SendMessage` 回報 `project refactor review sdd`：

```text
C?｜結論（通過／有條件通過／失敗／停止）｜commit SHA｜關鍵數字｜偏離報告185 之處（無則寫無）
```

我收到後獨立驗證、記入 §7 並派下一步。**即使使用額度重置後，也請接續未完成項目。**

## 7. 執行紀錄（僅規劃對話更新）

| ID | 狀態 | 結論 | commit | 備註 |
| --- | --- | --- | --- | --- |
| C1 | ✅ 通過（規劃對話核對 Cypher 與報告；未自行重查 Neo4j） | 前後 KG#4 資料庫總節點 57,451／總關係 137,873／Fact 16,826／Entity 12,296 **完全相同**（Fact 與 `frozen_manifest` 16,826 相符、Entity 與 `20260923_rebased` 12,296 相符）；防護：`ListAgents` 僅規劃對話在線、`kg2-neo4j` 容器 Up／healthy 未動、READ session＋腳本內建寫入關鍵字攔截（無觸發）、未啟動 Ollama／未呼叫 LLM／embedding。資料：Fact 16,826 筆中 `RELATED_TO` 14,994（89.1%）、其餘 27 種型別 1,832；distinct `verb` 9,209、distinct `rel_type` 28。7 題答案直接相關的邊（授權句 AGGR5/9/11/13/15 與 AGGR7 子法 chunk 1、AGGR7 門檻子法 chunk 6、母法 chunk 24／27 補助與授權邊、AGGR19「準用」邊）**全部是 `RELATED_TO`＋原始 `verb`**。既有 `retrieval_rerun.json`（commit 84c0209，`llm_provider=None`）中凍結42題 `resolve_query_relation_type` 結果**全為 None**→`filter_triples_by_relation_type(None)` 不篩選。結論：〔事實〕這 7 題在圖內容上受控 vs 開放式 (subject, verb, object) 幾乎相同；〔事實〕無 LLM 仲裁時後篩不作用；〔推論〕RQ4a 若以這 7 題當區分題，預期無法區分（效應≈0）；RQ4a 能區分的更可能是其餘 11% 有型別邊所涉的題（未盤點）。缺口：生產環境若啟用 LLM 仲裁，問句可能被解析為非 None 而改變後篩——需 LLM，依停止條件未做＝無資料。限制：AGGR19 新法 chunk↔條號只核對到 chunk 內含「準用」 | `c8fea4d`（報告187） | 我驗：commit 僅新增報告187（`.py`／題庫／論文零變更）；附錄 A 34 條 Cypher 全為 `MATCH…RETURN`、無寫入語句（寫入關鍵字僅出現在說明句）；前後各一組總數查詢，數字相同；Fact／Entity 數與兩份 manifest 吻合 |
| C2 | ✅ 通過（規劃對話獨立抽查） | 題庫 `57-AGGR7` verified／verbatim；頂層 `source_article`＝「N0090055 §24；N0090058 §1、§6」，但同題 `gold_answer`、`complexity_label`、`atomic_gold_facts` 明確是母法§24（補助基礎）、母法§27（授權）、子法§1（授權句）、子法§6（門檻）——**題庫內部兩欄粒度不同（文字事實，不判斷漏列或有意）**。語料內有母法 `N0090055_中高齡者及高齡者就業促進法`（名稱與子法第1條所寫一致），母法版本／修正日期無資料。報告並排逐字摘錄母法第24–27條、子法第1／3／6條全文；題庫 3 筆 `exact_span` 與原文逐字比對皆「是」。**唯一待使用者確認**：AGGR7 來源標註是否應含母法第27條 | `6542515`（報告186） | 我驗：僅新增報告186、題庫零變更；摘錄逐字抽查——3 條在 N0090055／N0090058 `original.md` 內確認存在（我的批次檢查因巢狀引用 `> >` 前綴誤報，已改查原檔確認）、其餘行為標題／路徑行 |
| C3 | ✅ 通過（規劃對話獨立驗證） | 因 v1（`kg_source_recall_probe`）匯入 `services.*`／`core.config` 依賴環境，不能只把 `load_env()` 搬進 `main()`（會改順序）；改為 `v1` 變成延遲代理 `_LazyV1`：首次存取 `v1.<屬性>` 才「`load_env()` → 匯入 v1」，命令列順序不變；`main()` 開頭另呼叫一次 `load_env()`（`setdefault`、冪等）。新增測試 `ImportHasNoEnvironSideEffectTest`（假 .env、不依賴本機有無該檔）＋證明明確呼叫 `load_env()` 仍會載入；刻意破壞（模組層級加回 `load_env()`）新測試失敗。全量 1580 passed／0 failed。`scripts/eval` 其餘同模式（只列未改）：`diagnose_prompt_noise.py:28-34` 模組層級 `os.environ.setdefault`（匯入即寫環境）；`kg_source_recall_probe_v2` 仍有模組層級 `sys.path.insert(0, REPO)` | `f7fd359` | 我驗：diff 僅 `scripts/eval/kg_source_recall_probe_v2.py`＋對應測試；實測匯入後 `os.environ` 不變；`--help` 正常；scripts＋core 兩個相關測試檔 9 passed。未重跑全量（採信 1580） |
| C4 | ✅ 通過（規劃對話核對） | 報告188 彙整 C1／C2／C3；索引補列 185–188、HANDOVER 加一條；§4 列 5 項待使用者裁示（AGGR7 來源標註是否含母法第27條；RQ4a 區分題是否改從有型別邊約11%所涉題目盤點；是否授權在可啟動 Ollama 時驗證 LLM 仲裁分支；`diagnose_prompt_noise.py:28-34` 同型副作用是否根治；別名實例出題／跑實驗與重抽／舊事項）。小插曲：執行對話暫存目錄舊 `bisect.py` 遮蔽標準庫致 Python 啟動失敗，已改名（非入庫檔） | `aea379d`（報告188） | 我驗：commit 僅 HANDOVER／索引／報告188，`.py`／論文／data 零變更 |

**階段結論（規劃對話）**：報告185 C1–C4 全數完成並經驗證；全量 pytest 1580 passed／0 failed；KG#4 前後總數相同（唯讀、無 LLM）。**最重要的發現**：KG#4 的 Fact 有 89.1% 為 `RELATED_TO`，且 7 題答案邊全是 `RELATED_TO`＋原始 `verb`、既有紀錄 `resolve_query_relation_type` 全為 None——**用這 7 題當 RQ4a 區分題預期效應≈0**。這是對 RQ4a 值不值得做的第一個實證訊號（尚缺 LLM 仲裁分支一環）。本階段零實驗、零重抽、零論文變更、零題庫變更。下一步取決於使用者對報告188 §4 的裁示。
