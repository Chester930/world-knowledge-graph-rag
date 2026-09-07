# 交接：c15949bf 誤刪 → reextract-v2 全新重跑

**產生時間**：2026-09-07 ~17:15（末更新 ~19:35）
**交接自**：session efb89cec（背景 job）

---

## 0. TL;DR（狀態）

**▶ drain 抽取執行中（2026-09-07 ~19:31 起）**：
- `drain_236903cf.py`（本 worktree，commit `ba1fdf3`）nohup pid **27180**，log `C:\Users\666\.claude\jobs\efb89cec\tmp\drain_236903cf.log`
- Monitor `b69ge5goh`（每 30 分 + 4 份驗證窗口清零偵測）
- 起點 completed=0 / pending=3303；ETA 數天、跨多 session
- 匯入階段（已完成）：KG `236903cf` = 64 Doc / 3303 Chunk / 3303 LawArticle；已備份 `D:\Users\666\Desktop\kg-backups\kg-runtime-import-done-20260907-182539.zip`
- 分支 `reextract-v2` = `3194185 → fb813eb`(E3) `→ d48ac9a`(交接+resume) `→ e4f3fb9`(交接更新) `→ ba1fdf3`(drain 腳本)。抽取端守衛 F2/F3b/§4.1/E3 全在。

**接手要做的**：看 §7「drain 執行中」。drain 掛了就從 worktree 目錄 nohup 重跑 `drain_236903cf.py`（環境先查）。

---

## 1. 背景：發生過什麼

- 原本在跑 KG `c15949bf` 的全量 SVO 重抽（3303 chunk，已完成 ~896/27%），drain 佇列 + chunk 原文放在 worktree `.claude/worktrees/agent-citation-enrichment/workspace/`（gitignored）。
- 2026-09-07 ~16:05 **另一個 session（`[788803]`）的分支清理跑了 `git worktree remove`**，`.gitignore` 掩蓋了執行期狀態 → `rm -rf` 把 `task_queue.db`（896/6/2401）+ 整個 c15949bf workspace 資料夾一起刪掉。**無備份、回收筒無記錄、三方 session 皆無副本。**
- Neo4j 的 c15949bf 圖資料（4248 Entity / 4965 Fact）當時還在，但：只抽了 27%、混了 ~80 個「sweep 沒掃到、帶前一輪舊資料」的 stale chunk、Fact/Chunk 無時間戳無法分辨哪些是真重抽的。
- **使用者決定**：全新重跑（不試著救 c15949bf）。

## 2. 已做的決策與動作（session efb89cec）

| 項目 | 內容 |
|---|---|
| **c15949bf 刪除** | 使用者「現在就刪」→ DETACH DELETE 15883 節點 + 1 KnowledgeGraph + 30509 邊。刪前確認 0 邊跨到別的 kg_id，刪後 76bc98ff 逐 label 數字完全不變（已驗證）。 |
| **76bc98ff 保留** | 凍結的「修正前」對照基準，完整 100%（Doc 64/Chunk 3304/Entity 6547/Fact 8421）。報告 18–26 的比對錨點，**絕對不要動**。其 workspace 資料夾也隨 worktree 消失，但當基準只需 Neo4j 圖（跑 `chat()`），無影響。 |
| **kg54f8cdfa** | 獨立 Neo4j database，1810 Entity 的違規案例圖（公司/人名），跟論文重跑無關，**未動**。 |
| **Q4 task_queue 清理** | 主 checkout `workspace/task_queue.db` 的 2190 筆孤兒列（5 個已刪 KG）全清。備份 `workspace/task_queue.db.bak-20260907-165657`。 |
| **新 worktree + 分支** | `.claude/worktrees/kg-reextract`，分支 `reextract-v2`，從 master `3194185` 開。 |
| **runtime 移出 git 樹**（結構性修復） | 該 worktree 的 `.env` 設 `WORKSPACE_DIR=D:/Users/666/Desktop/kg-runtime`（`CHUNK_STORE_DIR` 同）。已驗證 `task_queue_db_path()`、KG folder 都落在 `kg-runtime\`。**之後誰再 `git worktree remove` 這個 worktree，只刪程式碼（git 內可復原），佇列/chunk 原文不受影響。** |
| **死 worktree** | git 層已無註冊（`git worktree prune` 無事可做）。實體空目錄 `.claude/worktrees/agent-citation-enrichment/` 被行程佔用刪不掉，空殼無害，可之後再刪。 |

## 3. 目前執行中的任務：匯入 + 切 chunk

- **指令**（已在跑，不要重複執行）：
  ```
  cd "D:/Users/666/Desktop/world knowledge graph rag/.claude/worktrees/kg-reextract"
  nohup python -u create_clean_leave_scheduling_kg.py --kg-name "勞動部法規遵循示範集（64筆，2026-09-07 reextract-v2 乾淨重跑版）" >> "C:/Users/666/.claude/jobs/efb89cec/tmp/reextract_v2_import.log" 2>&1 &
  ```
- **process**：nohup pid **523**（session efb89cec 啟動；跨 session 存活）
- **log**：`C:\Users\666\.claude\jobs\efb89cec\tmp\reextract_v2_import.log`
- **新 KG id**：`236903cf-055a-40a8-8923-b9d06601f3b7`（Neo4j database `neo4j`，用 `kg_id` 屬性分隔）
- **進度監看**：Monitor task `b9fedcbwo`（每份文件一行；session efb89cec 結束後停）
- `trigger_extraction()` 只做 CHUNKREADY（前處理＋指代消解 LLM＋逐句 embedding＋ArticleAwareChunking 切塊）→ 向量化 → ENQUEUE 入列。**不做 SVO 三元組抽取**（那是 drain worker 的事）。
- **ETA** ~1–3 小時。大檔慢：N0060009（451 條）、N0060030（270 條）、N0060014（203 條）。
- **預期完成訊號**（log 尾）：`完成：新匯入 64 筆，略過 0 筆，逾時略過 0 筆。` + `KG id=236903cf...`
- **快照查詢**：
  ```
  python - <<'EOF'
  import sqlite3
  c = sqlite3.connect(r"D:\Users\666\Desktop\kg-runtime\task_queue.db")
  print(dict(c.execute("SELECT status,COUNT(*) FROM task_queue GROUP BY status").fetchall()))
  EOF
  ```
## 3b. 中途停 + 接續（⚠️ 不能直接重跑 create 腳本）

`create_clean_leave_scheduling_kg.py` **每次執行都鑄新 KG id**，重跑會建第二個 KG、64 份從頭。**要接續就用 `resume_import_236903cf.py`**（本 worktree，已寫好測過）：

- **停**：`Stop-Process -Id 523 -Force`（或 kill 當前匯入 pid）。停 Monitor（TaskStop 或隨 session 結束）。不用清理——resume 腳本會處理半套殘留。
- **接續**（環境先確認 kg2-neo4j healthy + Ollama 200）：
  ```
  cd "D:/Users/666/Desktop/world knowledge graph rag/.claude/worktrees/kg-reextract"
  python resume_import_236903cf.py --status     # 先看 done / 待補
  nohup python -u resume_import_236903cf.py >> "C:/Users/666/.claude/jobs/<job>/tmp/resume_import.log" 2>&1 &
  ```
- **判斷完成的依據**：`task_queue.db` 有沒有該 `source` 的列（`enqueue()` 是單一原子交易，一份文件要嘛全入列要嘛沒有）。待補的文件（含 kill 時正在處理的半套那份）會先清資料夾 + `DETACH DELETE` 該文件的 Chunk 節點 + 刪 tq 列，再完整重做。
- resume 腳本可重複跑，只補還沒入列的。逾時/失敗的再跑一次即可。
- **若有文件逾時/失敗**（log 印 `⚠️ 逾時`/`⚠️ LLM 呼叫失敗`）：再跑一次 `resume_import_236903cf.py` 即只針對那幾份重試。

## 4. 匯入完成後：停點 checklist

1. log 尾出現 `完成：新匯入 N 筆` + pid 523 結束。
2. 驗證：`kg-runtime/task_queue.db` 全 `pending`、筆數 ~3303（對照舊 c15949bf 是 3303、76bc98ff 是 3304，±數筆正常）。
3. 驗證：Neo4j `236903cf` 有 64 Document / ~3303 Chunk / ~3303 LawArticle。
4. **備份** `D:\Users\666\Desktop\kg-runtime\` 整個資料夾到 repo 外（`D:\Users\666\Desktop\kg-backups\kg-runtime-20260907.zip` 之類）。
5. 停。**不要開 drain。** 不要跑 `main.py`（全域 worker 會撿任何 KG 的 pending）。不要跑 `rebuild_from_records()`。
6. 更新 memory `project_c15949bf_full_reextraction.md`。

## 5. 環境

- **Neo4j**：Docker 容器 `kg2-neo4j`，`bolt://localhost:17990`（healthy）。恢復：`Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"` → 等 `docker ps` healthy。
- **Ollama**：`http://localhost:11434`（`qwen2.5:7b` + `bge-m3`），`curl http://localhost:11434/api/version` 應回 200。
- **EMBEDDING_PROVIDER=ollama**（本機 `local` 是壞的，別改）。
- 連線密碼在 `.env`（worktree 的 `.env` 已從主 checkout 複製 + 改 WORKSPACE_DIR）。

## 6. 開 drain 前的前置：ff reextract-v2 到 `fb813eb`

平行 session **「project status review」**（透過 SendMessage 聯絡）負責報告32 §9 的抽取端修正。**2026-09-07 ~17:3x 全部完成**：

- **在 master `3194185`**：F2（`_RANGE_COMPARATOR_PATTERN` v2）+ F3b（`_ENUM_GUARD_PATTERN`）+ §4.1（`_SCOPE_MODIFIER_PATTERN`）。`reextract-v2` 從 3194185 開，已帶到。
- **F3a**：設計上不做。
- **E3**：現行碼「blob entity」已不重現。唯一碼改動 = `fb813eb`：`_MEASURE_PATTERN` 補 `個月/個年/個星期`（`三個月為限`/`六個月為限` 舊樣式沒被守衛擋到）。prompt 規則 10 **不落地**（qwen2.5:7b 太敏感、會弄壞相鄰正常形態），待更強模型或全新 KG 驗證後再議。
- **F4**：naturalization 守衛正確、不需改碼。全新 KG 每條邊過現行 `_naturalize_triple` 即修好舊時序問題。
- **master `3194185 → fb813eb`** 之間：`fb813eb`（E3 `個月` + 測試，681 pytest passed）、`1cc4676`（報告32 純文件）。

### ⚠️ 動作：**匯入完成 + 備份之後**，開 drain 之前
```
cd "D:/Users/666/Desktop/world knowledge graph rag/.claude/worktrees/kg-reextract"
git fetch && git merge --ff-only fb813eb     # 或 1cc4676，兩者皆可
```
**不要在匯入（pid 523）還在跑的時候 ff**——會擾動執行中的行程。等 pid 523 結束再做。

### 一般原則（不只 E3/F4）
開 drain 前，對**任何 `services/svo_service.py` / `_svo_prompt`（抽取端）的變更**都要先確認狀態、ff 進 `reextract-v2`——否則前後 chunk 用不同版本的抽取邏輯。例：之後若用更強模型重試 prompt 規則 10，那是抽取端，比照 E3 先 ff。
**查詢端變更（`routers/agent.py`、BFS query、生成 prompt，如 G1 限制性重生成過度修正、G 系列）不卡 drain**——它們不影響重跑出來的圖。
目前平行 session 的 `svo_service.py` 已凍結（除非全新 KG 驗證後要推 prompt 規則 10 / G 系列抽取端項目）。

## 7. 開 drain 時（將來）

- 用 **kg-scoped drain**（`next_pending(db_path, kg_id="236903cf-...")`），不要用 `main.py` 全域 worker。舊 drain 腳本樣板見 memory `project_c15949bf_full_reextraction.md`「啟動指令」節（把 KG_STR 換成 `236903cf-055a-40a8-8923-b9d06601f3b7`，`sys.path` 換成 kg-reextract worktree 路徑）。
- 從 kg-reextract worktree 目錄跑（`.env` 的 WORKSPACE_DIR 才會生效）。
- 掛 30 分進度 Monitor。
- 每 25% 備份一次 kg-runtime。
- ETA 數天（3303 chunk × qwen2.5:7b 本機 ~40s–5min）。
- **⚠️ 通知平行 session「project status review」**：drain 跑起來後，橫掃過 chunk_index 16 時這 4 份會清完（約 drain 開始後 1–2 天）——`N0060004` / `N0030025` / `N0060065` / `N0050030` 的 `pending`+`processing` 全歸零時，SendMessage 通知他（他要跑 `diag_g2g3_window.py` 診斷 G2/G3）。查詢：
  ```sql
  SELECT source, status, COUNT(*) FROM task_queue
  WHERE source LIKE 'N0060004%' OR source LIKE 'N0030025%'
     OR source LIKE 'N0060065%' OR source LIKE 'N0050030%'
  GROUP BY source, status;
  ```

## 8. 開放事項

- **Q1（使用者手動）**：`! cd "D:/Users/666/Desktop/world knowledge graph rag" && git push origin master`——master 領先 origin **數十個 commit、只在本機**（量持續在長），harness 禁止 agent push master。使用者要在 prompt 敲。
- **master 持續在動**：平行 session 持續 commit（截至 ~18:00 head `be88c4a`；`fb813eb`=E3 抽取端、`bd3bbb7`=G1 純查詢端、其餘文件）。**抽取端只到 `fb813eb`**——ff `reextract-v2` 到 `fb813eb` 即可，`bd3bbb7`(G1) 是 `routers/agent.py` 查詢端、ff 不 ff 對重跑都一樣。`reextract-v2` 只 ff 確定的東西回 master。
- E3 / F4（見 §6，已完成）。
- **已知數據風險——匯入抽取後要驗的一條**：現行抽取對 **N0030018 §2**「每次以不少於六個月為原則」會**偶發抽成「六個半月」**（數值幻覺——`半` 非數字，`_MEASURE_PATTERN` / `_contains_ungrounded_quantity` 都攔不到）。全新 KG #4 的 N0030018 §2 抽完後，直查 `育嬰留職停薪期間 -[原則上每次以不少於]-> ?` 這條邊，確認是「六個月」不是「六個半月」。若中了 → 是 qwen2.5:7b 抽取幻覺、非機制缺陷，記錄即可（或那一 chunk 重抽）。
- 論文正文同步（報告32 §9 / memory）：§3.7 / §3.2 §b / §4.7.1 / 00_研究追溯對映表 的 BFS 行為描述。

## 9. 關鍵路徑速查

| 東西 | 路徑 |
|---|---|
| 主 checkout | `D:\Users\666\Desktop\world knowledge graph rag`（master） |
| 重跑 worktree | `D:\Users\666\Desktop\world knowledge graph rag\.claude\worktrees\kg-reextract`（分支 `reextract-v2`） |
| runtime 狀態（佇列+chunk） | `D:\Users\666\Desktop\kg-runtime\`（**git 樹外**） |
| 佇列 DB | `D:\Users\666\Desktop\kg-runtime\task_queue.db` |
| 匯入 log | `C:\Users\666\.claude\jobs\efb89cec\tmp\reextract_v2_import.log` |
| 來源資料集 | `D:\Users\666\Desktop\labor-compliance-collector\projects\20260821_請假與排班法規庫_精簡標準化版\20260821_leave_and_scheduling_normalized.jsonl`（470 MB） |
| create 腳本 | `<worktree>\create_clean_leave_scheduling_kg.py`（`TARGET_SOURCES` 硬編 64 份） |
| memory | `C:\Users\666\.claude\projects\D--Users-666-Desktop-world-knowledge-graph-rag\memory\project_c15949bf_full_reextraction.md` |
| 新 KG id | `236903cf-055a-40a8-8923-b9d06601f3b7` |
| 凍結基準 KG id | `76bc98ff-2cbd-447e-a087-7f2df6898655`（**勿動**） |
| 主 checkout 舊佇列備份 | `D:\Users\666\Desktop\world knowledge graph rag\workspace\task_queue.db.bak-20260907-165657` |
