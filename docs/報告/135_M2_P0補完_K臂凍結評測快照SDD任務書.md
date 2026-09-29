# 報告135：M2 P0 補完——K 臂凍結評測快照 SDD 任務書（真實 Neo4j＋Ollama，只讀，跑兩次量雜訊底線）

> **日期**：2026-09-29
> **執行者**：Codex｜**設計與審核**：Claude Code
> **上位文件**：[報告97](97_專案目標與BT_SM工作流設計.md) §6.5（P0 回歸網的最後一項、P2 驗收依據）、[報告108](108_M2_P0回歸基準結果.md) §4（當時刻意未做本項）、[報告62](62_下一階段任務書_檢索排名與條文擴充驗證.md)（T0 檢索軌跡保存，`include_retrieval_trace`）
> **成果檔**：`docs/報告/136_K臂凍結快照結果.md`（Codex 建立）；快照資料 `data/eval/p2_snapshot_20260929/`（**提交進版控**，作為 P2 的黃金基準）；比對腳本 `scripts/analysis/compare_p2_snapshots.py`（新增）
> **性質**：**只讀、跑真實服務**。使用者已於 2026-09-29 選定方案 (a) 並確認環境（Neo4j `localhost:17990`、Ollama `localhost:11434` 已啟動；Claude 已用連接埠探測確認兩者開啟，其他 session 皆離線）。**本任務不得啟動或重啟任何服務，不得對 Neo4j 寫入。**

---

## 0. 目的與設計

P2（拆 `routers/agent.py`，1,904 行）的驗收條件是「重構前後 K 臂行為不變」。純 pytest 無法涵蓋檢索與生成的端到端行為，所以在動手前先凍結一份**真實服務下的快照**，並且**先量出這份快照本身的雜訊底線**（同一份程式碼跑兩次能否逐字相同）。

### 為什麼不能只比「答案逐字相同」
`qwen2.5:7b` 的生成即使設 `seed=0` 仍可能受批次大小影響而非確定性（報告20，Horace He 2025）。所以驗收分**三層**，各自有不同的嚴格度：

| 層 | 內容 | 是否確定性 | P2 驗收要求 |
|---|---|---|---|
| **L1 檢索軌跡** | `retrieval_trace`（`facts`、`triples`）與 `prompt_context_lines`：種子實體、Fact 命中、範圍、BFS 結果、排序後送進 prompt 的行 | **應為確定性**（向量檢索與 Cypher，不含 LLM 採樣） | **逐字相同**（若本任務兩次基準跑就不同，先找出原因並記錄，不得忽略） |
| **L2 答案文字** | `answer` 字串 | 可能不確定 | 若兩次基準逐字相同 → P2 後也須逐字相同；若某題兩次基準就不同 → 該題標為「L2 不可比」，改看 L3 |
| **L3 原子評分結果** | 每題的 `AtomicScorer` 結果（沿用 harness 既有計分，`exact_span` + 語意 fallback）通過／未通過與命中原子事實 | 半確定 | 每題通過／未通過**不得退步**（若某題兩次基準就不一致，記為「不穩定」，不納入嚴格比較） |

### 題目（固定 6 題，已由 Claude 依 `mechanism_tags` 挑選，涵蓋 `chat()` 的不同分支）

| 題號 | 題目（前段） | 機制標籤 | 用來覆蓋 |
|---|---|---|---|
| `17-Q1` | 勞工結婚可以請幾天婚假？工資怎麼算？ | `single_fact` | 以「？」分解子問題的路徑（雙問句） |
| `26-Q1` | 依高架作業勞工保護措施標準，…每連續作業二小時應給予休息… | `segmented_enumeration` | 枚舉／分層家族與 enumeration guard |
| `26-Q5` | 災區受災勞工，符合規定者在災後多久的期間內… | `cross_doc_multihop` | 跨文件多跳、範圍推導與 BFS（已知對檢索排序敏感的題） |
| `57-DIST1` | 警察當選「直轄市」模範警察，可以獲得幾天特別休假？… | `distractor_adjacent` | 鄰近干擾、grounding／條款綁定 |
| `57-COREF1` | 受僱者申請育嬰留職停薪未滿30日，原則上要提前幾天提出？如果是因為子女生病、… | `coreference_resolution`、`multi_fact_assembly` | 多子句、指代消解與多事實組裝（**v2 修訂：取代原 `57-ALIAS1`**，見 §6） |
| `canary-P1` | 請問公司若違反勞動法令，依規定最高可處新臺幣多少億元的罰鍰？ | `canary_refusal` | 拒答路徑（KG 內無此資訊） |

（以上 6 題皆為 `verification_status == "verified"` **且通過 harness 的資格檢查**（`services/evaluation_eligibility.py::assess_test_case`；Claude 已用該函式逐題確認 `eligible=True`）。使用者原先說「5 題」，本任務書列 6 題以覆蓋拒答與多子句指代兩條不同路徑；如需縮減，先與 Claude 確認，**不要自行刪題**。）
>
> **v2 修訂註記（2026-09-29，Codex 第一輪試跑後）**：原 v1 選了 `57-ALIAS1`，但題庫中**所有** `alias_mapping` 題（ALIAS1／2／3、DIST3）的 `wording_status` 都是 `gist`，被 harness 資格檢查排除，因此無法用 alias 題覆蓋「種子實體字面→語意 fallback」路徑；此路徑**本快照不覆蓋**（記為已知限制）。v1 第一輪試跑的產物（5 題、含 2 題 180 秒逾時）**作廢**，見 §6。

---

## 1. 步驟

### S1　環境確認（唯讀，任一項不符即停下回報，**不要自行啟動或修復服務**）
1. `git status -s` 為空；記錄 `git rev-parse HEAD`。
2. 連接埠探測：`localhost:17990`（Neo4j Bolt）與 `localhost:11434`（Ollama）皆須開啟。
3. Ollama 唯讀查詢：`http://localhost:11434/api/tags`，確認含 `qwen2.5:7b` 與 `bge-m3`；記錄各自的 digest、`ollama --version`／`/api/version`。
4. 確認**沒有其他 harness、抽取 worker、匯入或重抽腳本正在執行**（例如檢視 `Get-Process python`、`tasklist` 中是否有其他長時間運行的 Python）；若有，停下回報。
5. 判斷 harness 如何取得 Neo4j 連線與 provider 設定：**唯讀**檢視 worktree 的 `.env`（或 `core/config.py` 預設與 `kg-reextract/.env`），確認 `NEO4J_URI` 指向 `bolt://localhost:17990`、`EMBEDDING_PROVIDER=ollama`。**報告中不得出現任何密碼、金鑰或完整的 `.env` 內容**，只寫「已確認 URI／provider 設定正確」。
6. **KG 基準計數（唯讀）**：以 harness 既有的 driver（或一支暫存目錄腳本）對 KG#4（`236903cf-055a-40a8-8923-b9d06601f3b7`）只執行唯讀 Cypher，記錄 `Fact`、`Entity`（以及 `Document`、`LawArticle` 若存在）節點數。預期與 HANDOVER 記載接近（Fact 16,826、Entity 12,296）；**跑完全部快照後再查一次，兩次計數必須完全相同**（證明沒有寫入）。

> ⚠️ WSL 記憶體風險：**本任務全程一次只能有一個 harness 行程**，且**不得在跑測中途中斷或重啟 Ollama／WSL**（HANDOVER 已記錄中斷會弄壞 WSL runner）。若 Ollama 在跑測中無回應，等待並記錄，不要重啟；超過 20 分鐘無進展才停下回報。

### S2　建立固定題目檔（不改題庫原檔）
用暫存腳本從 `data/eval/test_cases.json` 取出上表 6 題，**逐題以原物件（欄位與內容一字不改）**寫成新檔 `data/eval/p2_snapshot_questions_20260929.json`，結構沿用原檔（`meta` 與 `questions` 兩個鍵；`meta` 內註明「P2 凍結快照子集，取自 test_cases.json，題庫雜湊另計」並附子集檔本身的 SHA-256 與原題庫檔的 SHA-256）。**不得修改 `data/eval/test_cases.json`**。

### S3　閱讀 harness，確定精確的呼叫方式（只讀）
閱讀 `scripts/eval/run_rq1_comparison.py`（重點：`main()` 的參數解析約 891-926 行、K 臂＝`M4` 的執行路徑、`_run_single_query()`、`include_retrieval_trace=True` 在約 218 行、結果 JSON 的結構），並在報告136 §「harness 呼叫方式」寫明：
- 實際使用的完整指令列（預期形如 `python -m scripts.eval.run_rq1_comparison --questions data/eval/p2_snapshot_questions_20260929.json --arms M4 --runs 1 --out data/eval/p2_snapshot_20260929/run1`，**以實際 harness 為準，不要照抄**）；
- 生成器的 `seed`／`temperature`／`num_gpu` 等實際設定來源（`core/config.py`、`.env`、provider 程式碼），以及 harness 是否已把它們寫入輸出的 manifest；
- 輸出檔（每題答案、`retrieval_trace`、`prompt_context_lines`、AtomicScorer 結果、耗時）分別在 JSON 的哪些欄位。
若 harness 不能只跑指定的 6 題或 K 臂，**停下回報**，不要修改 harness（若確需修改，另案）。

### S4　執行基準快照 run1、run2（同一份程式碼、連續兩次）
- 依 S3 確認的指令，連續執行兩次，輸出到 `data/eval/p2_snapshot_20260929/run1/` 與 `.../run2/`。
- **v2：兩輪都必須加 `--query-timeout-s 600`**（Claude 明確授權；理由：v1 試跑實測 K 臂單題耗時 70–180 秒，5 題中 2 題在預設 180 秒逾時、另 1 題 153 秒，逾時的題目沒有答案與檢索軌跡，無法作為黃金基準）。兩輪必須使用**完全相同**的逾時值，並記錄在報告136 §1／§2。**若 600 秒仍有題逾時，停下回報，不要再自行加大。**
- **v2：清理 v1 試跑產物**：把 v1 試跑產出的 `data/eval/p2_snapshot_20260929/run1/`（5 題、含逾時）與舊的 `data/eval/p2_snapshot_questions_20260929.json` **移到系統暫存目錄**（不要刪除證據、也不要留在 repo 內），再用 v2 題目重新產生子集檔並重跑；最終 repo 內只保留 v2 的 run1／run2。
- **資格檢查**：跑完後確認 manifest 的 `eligible_question_ids` 恰為 6 題（與 §0 表相同）、`excluded_questions` 為空；否則停下回報。
- 這是**長時間任務**（每題預估 1–3 分鐘，兩輪合計約 20–40 分鐘）：請用背景執行並輪詢輸出檔，**不得中途中斷**。
- 每輪結束後記錄：起訖時間、每題耗時、是否有逾時（`--query-timeout-s` 預設 180；若有題逾時，記錄並如實回報，**不要**改逾時設定後假裝成功）、是否有任何錯誤。
- 兩輪之間**不得**修改任何程式碼、設定或環境。

### S5　建立比對腳本並跑一次自我檢查
新增 `scripts/analysis/compare_p2_snapshots.py`（**新增檔案**；純標準庫；不得連任何服務），介面：

```text
python scripts/analysis/compare_p2_snapshots.py <run_dir_A> <run_dir_B> [--out <報告.json>]
```

行為：讀取兩個 run 目錄的 `records.json`，對**每一題**輸出三層的比對結果。**v2：欄位路徑已由 Claude 對照 v1 試跑產物確認**（每筆 record 的頂層鍵為 `question_id`、`arm`、`answer`、`error`、`latency_s`、`atomic_score`、`lineage`…；檢索軌跡**不在頂層**，而在 `lineage` 底下）：
- **L1**：`lineage.stage1_retrieval` 的 `retrieved_fact_ids`、`retrieved_chunk_ids`、`retrieval_trace`（依原順序，list of dict），以及 `lineage.stage2_context.prompt_context_lines` 是否逐字相同；**不要納入**會隨執行而變的欄位（`retrieval_latency_ms`、各種耗時，以及其他明顯的計時／延遲欄位）。不同時列出第一個差異位置與雙方內容摘要；
- **L2**：頂層 `answer`，並附帶比對 `lineage.stage3_generation` 的 `raw_draft`、`final_output`、`grounding_passed`、`regenerated`（用來判斷差異是出在生成本身還是後處理）；不納入 `generation_latency_ms`；
- **L3**：`atomic_score` 的 `is_perfect`、`supported_spans`、`missing_spans`（通過／未通過與命中原子集合）；
- 任一 record 的 `error` 非空（例如逾時）時，該題標為「無資料」並使總判定失敗，不得默默略過；
並在最後輸出總表（每題三層 ✅／❌）與「哪些題 L2 不可比、哪些題 L3 不穩定」的清單。退出碼：任一題 L1 不同時為 1，否則 0。

**同時新增測試** `tests/scripts/test_compare_p2_snapshots.py`（**寫法請比照既有的 `tests/scripts/test_compare_scope_audit_runs.py`**：`tests/scripts/` 沒有 `__init__.py`，既有測試以 `sys.path.insert(0, <repo 根>)` 後 `import scripts.…` 的方式載入；先確認 `scripts/analysis/` 能以同樣方式匯入，不能的話比照該既有測試處理，**不要**為此新增 `__init__.py` 或修改既有檔案。以合成的小型結果 JSON 驗證：完全相同→全 ✅；只改 `answer`→L2 ❌ 但 L1 ✅；改 `retrieval_trace` 順序→L1 ❌ 且退出碼 1；缺少某題→明確報錯）。

### S6　比對 run1 vs run2，記錄雜訊底線
執行 `python scripts/analysis/compare_p2_snapshots.py data/eval/p2_snapshot_20260929/run1 data/eval/p2_snapshot_20260929/run2 --out data/eval/p2_snapshot_20260929/baseline_noise_floor.json`，並在報告136 用表格逐題列出 L1／L2／L3 結果。
- **若某題 L1 兩次就不同**：這違反「檢索應確定性」的假設，**停下並在報告中詳述差異**（差異位置、可能原因，例如向量相似度平手時的排序不穩、ANN 索引非確定性），**不要**把它當成正常雜訊；提出處理建議（例如該題排除、或標記為「L1 不穩定」），交 Claude 判斷。
- L2／L3 不同的題，標為「L2 不可比」／「L3 不穩定」，這是預期可能發生的雜訊，如實記錄即可。

### S7　複查 KG 未被改動
重跑 S1-6 的唯讀計數，與 run 前逐項比對必須完全相同；不同就停下回報。

### S8　成果報告與提交
建立 `docs/報告/136_K臂凍結快照結果.md`，固定結構：

```markdown
# 報告136：K 臂凍結快照結果
> 日期 ｜ 基準 commit ｜ 執行者：Codex（依報告135）

## 1. 環境與版本
（HEAD、Ollama 版本、qwen2.5:7b／bge-m3 digest、KG#4 計數 run 前後、生成器 seed 等設定；**不含任何密碼**）
## 2. harness 呼叫方式
## 3. 固定題目
## 4. 兩次基準的執行紀錄
（每題耗時、逾時、錯誤）
## 5. 雜訊底線（run1 vs run2）
| 題號 | L1 | L2 | L3 | 備註 |
## 6. P2 驗收判準（依本次雜訊底線導出）
（明確寫出：哪些題 L2 可用嚴格逐字比對、哪些改用 L3；L1 是否所有題皆確定性）
## 7. 已知限制
## 附錄 A：比對腳本用法
```

提交：`data/eval/p2_snapshot_questions_20260929.json`、`data/eval/p2_snapshot_20260929/`（run1、run2、baseline_noise_floor.json）、`scripts/analysis/compare_p2_snapshots.py`、`tests/scripts/test_compare_p2_snapshots.py`、報告136。commit 訊息 `test(P2前置): K臂凍結評測快照與比對腳本，量測雜訊底線（報告135）`。**不 push。** 完整回歸（`python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py`，基準 **1304**＋本次新增測試數）須在提交前通過。

---

## 2. 允許新增／修改的檔案

| 檔案 | 性質 |
|---|---|
| `data/eval/p2_snapshot_questions_20260929.json` | 新增 |
| `data/eval/p2_snapshot_20260929/**` | 新增（快照資料） |
| `scripts/analysis/compare_p2_snapshots.py` | 新增 |
| `tests/scripts/test_compare_p2_snapshots.py` | 新增 |
| `docs/報告/136_K臂凍結快照結果.md` | 新增 |
| 本任務書 §4 回填區 | 只可填寫該區 |

## 3. 驗收（Claude 審核）

| # | 檢查 |
|---|---|
| A1 | diff 只有 §2 的檔案；`data/eval/test_cases.json`、`scripts/eval/*`、`routers/`、`services/` 完全未動 |
| A2 | 題目子集檔的 6 題與原題庫逐題**欄位內容一字不差**（Claude 用腳本逐題比對） |
| A3 | 報告136 §1 有版本與 KG 計數（run 前後相同）；**無任何密碼或金鑰** |
| A4 | run1／run2 皆完整涵蓋 6 題；有無逾時／錯誤如實記錄 |
| A5 | 比對腳本與測試存在且通過；Claude 用自己構造的資料另測一次（改一個 L1 欄位須被抓到、退出碼為 1） |
| A6 | 雜訊底線表可由 Claude 用腳本獨立重現（Claude 重跑 `compare_p2_snapshots.py run1 run2` 結果一致）；§6 的驗收判準與資料相符、可直接作為 P2 的比對規則 |
| A7 | 完整回歸 = 1304＋新增測試數 passed、0 failed（Claude 獨立重跑） |

## 6. v2 修訂說明（2026-09-29，Codex 第一輪試跑後）

Codex 依 v1 執行至阻塞點並如實停下（無 commit、無報告 136、KG#4 計數前後一致），揭露了三件 v1 未預見的事：

| # | 發現 | 處理 |
|---|---|---|
| 1 | harness 載入 6 題但只有 5 題 eligible：`57-ALIAS1` 的 `wording_status=gist` 被排除。**所有 `alias_mapping` 題皆為 `gist`，無可用替代** | 以 `57-COREF1` 取代；alias fallback 路徑列為本快照的已知限制（Claude 責任：v1 選題只看 `verification_status`，漏看 harness 的資格檢查） |
| 2 | 5 題中 2 題（`17-Q1`、`canary-P1`）在預設 180 秒逾時，`57-DIST1` 耗時 153 秒；其餘 70–80 秒 | 兩輪加 `--query-timeout-s 600`（§S4） |
| 3 | 檢索軌跡在 `records.json` 的 `lineage` 底下而非頂層（v1 §S5 未寫明路徑） | §S5 補上確切欄位路徑（本檔 v2 已更新） |

v1 第一輪的產物作廢（移至暫存目錄，不進版控）。**Codex 的阻塞停止是正確的處理**（任務書禁止修改 harness 與題目物件）。

## 4. 回填區（Codex 填寫）

- commit SHA：
- S1–S8 自我檢查結果：
- 兩次基準的起訖時間與總耗時：
- 新增測試數：
- 意外狀況：

## 5. 禁止事項

- **不得啟動、重啟或停止 Neo4j、Ollama、WSL**；跑測中不得中斷。
- **不得對 Neo4j 寫入**（只讀 Cypher）；不得執行抽取 worker、匯入或重抽腳本。
- 不得修改任何 production 程式、harness、既有測試、既有題庫檔、既有設定；不得為了讓基準穩定而調整 seed／模型參數（**逾時例外**：僅限 §S4 授權的 `--query-timeout-s 600`，兩輪相同，不得再更動）。
- 若 L1 兩次基準就不同，**如實記錄並停下回報**，不得自行「修正」或忽略。
- 報告與資料檔中**不得包含密碼、API 金鑰或完整 `.env` 內容**。
- 不得 push。
