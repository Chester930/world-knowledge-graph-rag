# 報告147：M2 P2 累計 K 臂快照驗收 SDD 任務書（真實 Neo4j＋Ollama，只讀，不改任何程式）

> **日期**：2026-09-30
> **執行者**：Codex｜**設計與審核**：Claude Code
> **上位文件**：[報告135](135_M2_P0補完_K臂凍結評測快照SDD任務書.md)／[136](136_K臂凍結快照結果.md)（凍結基準與 §6 驗收判準）、[報告140](140_P2第一刀結果.md)（第一刀的單次快照，本任務沿用其流程）、P2 第一至第四刀（報告139／141／143／145）
> **成果檔**：`docs/報告/148_P2累計K臂快照結果.md`（Codex 建立）；比對輸出 `data/eval/p2_after_cut4_20260930/`（**提交進版控**，僅兩個小 JSON）
> **性質**：**只讀、跑真實服務、不改任何程式碼**。使用者已於 2026-09-30 選定「累計 K 臂快照」並將確認 Neo4j（`localhost:17990`）與 Ollama（`localhost:11434`）維持開啟。**本任務不得啟動、重啟或停止任何服務，不得對 Neo4j 寫入。**

---

## 0. 目的

P2 第二、三、四刀依使用者決定的頻率 (b) **沒有各自跑 K 臂快照**（只有第一刀跑過一次，見報告140）；它們靠 AST 逐字比對＋差分行為測試證明「純搬移」。本任務用**一次真實服務的快照**，累計驗證「第一至第四刀合在一起後，端到端行為與凍結基準相同」，並實際跑過 `chat()` 匯入新套件 `services/context/`、`services/retrieval/` 的整條路徑。

**被驗證的狀態**：目前 HEAD（`4f6ae52` 或其後僅含文件變更的 commit）。此狀態下 `routers/agent.py` 由 1,904 行降至 1,461 行，16 個函式與 3 個常數已搬到 `services/context/fact_lines.py`、`services/context/telemetry.py`、`services/retrieval/scope.py`，`agent.py` 以原私有名稱重新匯出。

**比對對象**：報告136 的凍結基準 `data/eval/p2_snapshot_20260929/run1` 與 `run2`（凍結時的程式碼狀態＝P2 第一刀之前）。

## 1. 步驟

### S1　前置檢查（唯讀；任一項不符即停下回報，**不得啟動／重啟／停止任何服務，不得自行修復**）
1. `git status -s` 必須為空；記錄 `git rev-parse HEAD`。
2. **確認被驗證的程式碼狀態**：對下列路徑，`HEAD` 相對於 commit `4f6ae52` **不得有任何變更**（另一個 Claude 對話會在同一工作目錄提交設計文件，這些**文件**變更是允許的，但**程式碼**變更不允許）：`routers/`、`services/`、`state/`、`core/`、`models/`、`repositories/`、`scripts/`、`main.py`。用 `git diff --stat 4f6ae52 HEAD -- routers services state core models repositories scripts main.py` 驗證輸出為空；有輸出則停下回報。**此檢查在 S3 跑完後必須再做一次**，兩次都為空。
3. 連接埠探測：`localhost:17990`（Neo4j Bolt）與 `localhost:11434`（Ollama）皆須開啟。
4. Ollama 唯讀查詢：`/api/tags` 含 `qwen2.5:7b` 與 `bge-m3`，且 digest 與報告136 §1 相同（`qwen2.5:7b`＝`845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e`、`bge-m3:latest`＝`7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab`）——**模型 digest 必須相同（硬性）**；記錄 Ollama 版本（`ollama --version` 與 `/api/version`）。**（v2 修訂）Ollama 版本允許與報告136 的 `0.34.4` 不同**：Codex 第一次試跑發現目前為 `0.35.0`（環境自動升級，模型 digest 不變）。這**不是停止條件**，但是**混淆因子**——見 S4 的「Ollama 版本漂移的處理規則」。報告148 §1 必須並列記錄「基準版本 0.34.4」與「本次版本」。
5. 確認沒有其他 harness、抽取 worker、匯入或重抽腳本在執行。**（v2 修訂）若作業系統權限使你無法檢視所有 Python 行程，這不是停止條件**：在報告148 §1 明確記錄「行程檢查受權限限制，僅能檢視到 N 個 Python 行程，其中無 `run_rq1_comparison`／抽取 worker／匯入腳本」，並**以使用者確認環境空閒為準**（使用者已於 2026-09-30 確認 Neo4j／Ollama 維持開啟並保留給本任務）。本工作目錄可能同時有另一個 Claude 對話存在，但它只做文件變更；若能看到它在跑評測或動用 Neo4j／Ollama，才停下回報。
6. KG#4（`236903cf-055a-40a8-8923-b9d06601f3b7`）唯讀計數：`Fact`＝16826、`Entity`＝12296、`Document`＝64、`LawArticle`＝3303（與報告136 §1 相同）；**跑完後再查一次必須完全相同**。
7. 確認題目檔 `data/eval/p2_snapshot_questions_20260929.json` 與凍結基準**位元組相同**：**（v2 修訂，更正 v1 的錯誤）** 檔案的**位元組 SHA-256 必須為 `5b899bde651ba25f712c217e5722662d57231ade75de668ac14f472c1a1ed2f1`**——這是 harness 自己記錄在基準 run1／run2 的 `manifest.json` 的 `dataset_sha256`（harness 以 `_sha256_file` 對檔案位元組計算），也是 Codex 第一次試跑實際算出的值。**v1 誤寫的 `2a572105…` 是題目檔 `meta.subset_sha256` 內記錄的「正規化 JSON 雜湊」（報告136 §3 所引用），不是檔案位元組雜湊，不可拿來比對檔案**（Claude 已驗證：檔案自 commit `30b38d6` 起未被改動、題庫原檔 `test_cases.json` 亦未變）。同時確認 6 題與 `data/eval/test_cases.json` 逐題相等；並在報告148 §1 註明兩種雜湊的差異。

> ⚠️ WSL 記憶體風險：全程一次只能有一個 harness 行程；**不得在跑測中途中斷**，也不得重啟 Ollama／WSL。Ollama 無回應時等待並記錄，超過 20 分鐘無進展才停下回報。**報告與提交檔不得含任何密碼、金鑰或完整 `.env` 內容。**

### S2　閱讀基準的呼叫方式（只讀）
閱讀報告136 §2，**逐字**取用其中的 harness 指令，僅把 `--out` 換成新的輸出目錄。預期形如（**以報告136 §2 為準**，若有出入請說明）：

```text
python -m scripts.eval.run_rq1_comparison --questions data/eval/p2_snapshot_questions_20260929.json --doc-ids D0080015_警察人員特別休假辦法,N0030006_勞工請假規則,N0030018_育嬰留職停薪實施辦法,N0050030_災區受災勞工保險與勞工職業災害保險及就業保險被保險人保險費支應及傷病給付辦法,N0060029_高架作業勞工保護措施標準 --arms M4 --runs 1 --query-timeout-s 600 --allow-shared-judge --out <新輸出目錄>
```

### S3　執行一輪累計快照
- 輸出到**系統暫存目錄**（例如 `C:\Users\666\AppData\Local\Temp\report147_after_cut4_20260930\run1`，**不進版控**）。
- 預估 13–20 分鐘；請用背景執行並輪詢輸出檔，**不得中途中斷**。
- 記錄起訖時間、每題耗時、是否有逾時或錯誤。manifest 的 `eligible_question_ids` 必須恰為 `17-Q1`、`26-Q1`、`26-Q5`、`57-DIST1`、`57-COREF1`、`canary-P1`，`excluded_questions` 為空；否則停下回報。

### S4　比對（依報告136 §6 判準；**必須逐題看表格，不能只看退出碼**）
用 `scripts/analysis/compare_p2_snapshots.py` 將新 run 與基準 run1、基準 run2 **各比對一次**，輸出到：
- `data/eval/p2_after_cut4_20260930/compare_vs_baseline_run1.json`
- `data/eval/p2_after_cut4_20260930/compare_vs_baseline_run2.json`

**驗收判準**：
- **6 題 L1 全部 ✅**（對 run1 與 run2 都是）。
- `26-Q1`、`26-Q5`、`57-DIST1`、`57-COREF1`、`canary-P1` 的 **L2 必須 ✅**。
- `17-Q1`：L2 允許 ❌（基準內已不穩定），但 **L3 必須 ✅**。
- 所有題 **L3 ✅**；無任何 `error`／逾時。

**任何違反判準：停下回報，貼出完整差異，不得自行判定為雜訊、不得修改任何程式碼或重跑以「湊」出通過。** 特別是：
- 若 **L1** 在任一題不同：這代表 P2 某一刀改變了檢索行為（純搬移不該發生）。報告中詳述差異位置（哪一題、`retrieved_fact_ids`／`retrieved_chunk_ids`／`retrieval_trace`／`prompt_context_lines` 的哪個欄位、第一個差異內容），**不要嘗試診斷或修復**，由 Claude 用各刀的 commit 二分定位（第一刀 `729f763`、第二刀 `0e14a1c`、第三刀 `bac1f82`、第四刀 `f92a44c`）。
- 若**穩定題的 L2** 不同而 L1 相同：先如實回報，並可（在使用者已授權的前提下不需再問）用**完全相同的指令與參數**再跑第二輪一次，以確認是否為執行期雜訊；兩輪結果都要如實回報。

#### Ollama 版本漂移的處理規則（v2 新增）
基準凍結時 Ollama 為 `0.34.4`，本次為 `0.35.0`（模型 digest 相同）。Ollama 升級**理論上**可能改變 `bge-m3` 的向量數值（影響向量檢索排序，即 L1）或 `qwen2.5:7b` 的生成（影響 L2）。因此：
- **若判準全部成立**：結論同時證明「P2 四刀不改變行為」與「這次 Ollama 升級對這 6 題沒有可觀察影響」，照常提交。
- **若 L1 或穩定題 L2 有差異**：此時**無法**區分是 P2 重構造成、還是 Ollama 升級造成。**停下回報完整差異，不要診斷、不要修改程式**；由 Claude 決定是否做**對照組**（在**搬移前的程式碼狀態**——commit `3ddc001`，用 `git worktree` 於暫存位置檢出，**不得在本工作目錄切換分支**——以目前的 Ollama 與同一指令再跑一輪，看差異是否同樣出現）。**本任務不要自行做對照組。**
- 不論結果，報告148 §1 與 §5 必須明確列出「Ollama 版本由 0.34.4 變為 0.35.0」這個混淆因子。

### S5　收尾檢查
1. 重跑 S1-2（程式碼未變）與 S1-6（KG 計數前後相同）；任一不符停下回報。
2. 確認暫存的新 run 目錄仍保留（Claude 需要它來獨立比對）；記錄完整路徑。

### S6　成果報告與提交
建立 `docs/報告/148_P2累計K臂快照結果.md`，固定結構：

```markdown
# 報告148：P2 累計 K 臂快照結果
> 日期 ｜ 被驗證的 HEAD ｜ 執行者：Codex（依報告147）

## 1. 環境與版本
（HEAD、Ollama 版本、模型 digest、KG#4 計數 run 前後、題目檔 SHA-256；不含任何密碼）
## 2. 被驗證的程式碼狀態
（S1-2 兩次的 `git diff --stat 4f6ae52 HEAD …` 結果；`agent.py` 行數、新增模組清單）
## 3. 執行紀錄
（指令、起訖時間、每題耗時、逾時／錯誤）
## 4. 比對結果
### 4.1 對基準 run1
| 題號 | L1 | L2 | L3 | 備註 |
### 4.2 對基準 run2
| 題號 | L1 | L2 | L3 | 備註 |
## 5. 判準檢查與結論
（逐項對照 §S4 判準；若有違反，完整差異）
## 6. 已知限制
（不覆蓋種子字面→語意 fallback 路徑；僅 6 題；共用 judge pilot 設定；`17-Q1` L2 基準不穩定）
```

無佔位符。**提交**：`data/eval/p2_after_cut4_20260930/compare_vs_baseline_run1.json`、`…_run2.json`、報告148。commit 訊息 `test(P2): 累計K臂快照驗收（第一至第四刀）——比對凍結基準（報告147）`。**不 push。** 任務書 §3 回填區可直接填寫（請填新 run 的暫存目錄完整路徑與起訖時間）。

---

## 2. 允許新增／修改的檔案（其餘一律不動）

| 檔案 | 性質 |
|---|---|
| `data/eval/p2_after_cut4_20260930/compare_vs_baseline_run1.json`、`…_run2.json` | 新增 |
| `docs/報告/148_P2累計K臂快照結果.md` | 新增 |
| 本任務書 §3 回填區 | 只可填寫該區 |

## 3. 回填區（Codex 填寫）

- commit SHA：本次唯一提交（最終回報列出）
- 新 run 的暫存目錄路徑與起訖時間：`C:\Users\666\AppData\Local\Temp\report147_after_cut4_20260930_02\run1`；`2026-09-30 11:43:28.794299 +08:00`–`2026-09-30 12:02:08.286368 +08:00`
- 判準檢查結果（一行）：兩個基準的 6 題 L1 全部通過；五個穩定題 L2 全部通過；`17-Q1` L3 通過且其 L2 為基準內既知不穩定；全部 L3 通過、無 error/timeout。
- 意外狀況：Ollama 基準 `0.34.4` 漂移至 `0.35.0`（模型 digest 相同，依 v2 列為混淆因子）；Windows 行程檢查僅能檢視 11 個 Python（含 pythonw）行程，未見 harness/抽取/匯入腳本，依使用者確認環境空閒繼續；另一對話於快照期間只提交設計文件，S1 HEAD `c08b6d9`、S5 HEAD `2f2cb4f`，程式碼 diff 仍為空。Neo4j 只有既有不存在 relationship type warning，未造成 error/timeout。

## 4. 驗收（Claude 審核）

| # | 檢查 |
|---|---|
| A1 | diff 只有 §2 的檔案；**程式碼（`routers/`、`services/`、`state/`、`core/`、`models/`、`repositories/`、`scripts/`、`main.py`）相對 `4f6ae52` 零變更**（Claude 用 `git diff` 驗證） |
| A2 | Claude 讀 Codex 回報的暫存目錄，用 `compare_p2_snapshots.py` **獨立重跑**對 run1 與 run2 的比對，逐題核對結果與報告148、與提交的比對檔實質一致（A／B 順序互換不算差異） |
| A3 | 驗收判準全部成立：6 題 L1 ✅、5 個穩定題 L2 ✅、`17-Q1` L3 ✅、無 error |
| A4 | 報告148 §1 有版本、digest、KG 計數（run 前後相同）、題目檔 SHA；**無任何密碼或金鑰**；提交的 JSON 無密碼類字樣 |
| A5 | 兩次「程式碼未變」檢查（S3 前後）都有記錄且為空 |
| A6 | 若有任何判準違反：報告148 有完整差異且**未**自行修改程式或以重跑掩蓋；Claude 依此決定是否用各刀 commit 二分 |

## 5. 禁止事項

- **不得修改任何程式碼、既有測試、harness、題庫、設定**。
- **不得啟動、重啟或停止 Neo4j、Ollama、WSL**；跑測中不得中斷；Neo4j 只讀，不得寫入。
- 不得為了讓結果通過而調整 seed／逾時／模型參數／指令參數（沿用報告136 §2 的逐字指令）。
- 報告與提交檔不得含密碼、API 金鑰或完整 `.env` 內容。
- 不得 push。
