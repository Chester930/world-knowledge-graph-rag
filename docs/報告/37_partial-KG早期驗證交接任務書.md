# 37．partial-KG 早期驗證交接任務書

**日期**：2026-09-09
**性質**：執行任務書（交接給另一個在本 repo 開的終端機 session 執行）。本文件不含程式碼變更設計，是「照著做」的步驟書。
**前提**：新 KG `236903cf` 全量重抽在 **41%（completed=1354 / failed=10 / pending=1939）** 被刻意暫停、已備份（`kg-runtime-drain-pause-c1354-20260909-093259.zip`）。14 份驗證題文件**全部抽完**，因此報告30 §1 的 **T1 階段測試現在就能跑，不必等 DRAIN-DONE**。
**關聯**：報告 30（驗收計畫，T0/T1/T2 三時點）、報告 32（上一輪 T1 結果 + E1 診斷 + §9 誤刪事件）、報告 27 §6.1/§6.2、報告 25 §7、報告 26 §1–§2。

---

## 0. 環境事實（cold session 先讀這段）

| 項目 | 值 |
|---|---|
| repo | `D:\Users\666\Desktop\world knowledge graph rag` |
| 新 KG id | `236903cf-055a-40a8-8923-b9d06601f3b7` |
| 重抽 worktree / 分支 | `kg-reextract` / `reextract-v2`（從 `3194185`，需 ff 到 `fb813eb`；master head 見 `git log`） |
| drain runtime（git 樹外） | `D:\Users\666\Desktop\kg-runtime` |
| task_queue DB | `D:\Users\666\Desktop\kg-runtime\task_queue.db`（欄位：`kg_id, source, chunk_index, status, updated_at`） |
| Neo4j database | `kg2-neo4j` |
| Python | `py -3.11`（報告27：3.13 的 OpenSSL 會拒舊政府憑證；本 repo 查詢端不一定受影響，但沿用 3.11 較穩） |
| drain 執行 session | `efb89cec`（名稱「knowledge graph agent implementation」），**目前 `blocked`，等使用者回覆才會重啟 drain**。本任務書做完才回它「繼續」。 |

**這份任務書的範圍**：步驟 1 → 5，**全程 drain 保持暫停**。做完把結果交回，再由使用者回 `efb89cec` 重啟 drain。

**紀律（不可違反）**：
- 報告30 §4.4：停 drain → 跑題 → **當場確認 drain 重啟成功** → 才做別的。memory 記過忘記重啟、主 drain 卡 90 分鐘。
- 報告32 §9.5：重跑完成前**不要**跑 `rebuild_from_records()` 或 `main.py` 全域 worker。
- memory `feedback_worktree_self_deletion`：絕不對自己所在的 worktree 跑 `git worktree remove` / force remove。
- 本 session **不推 master**；程式碼變更（若有）留在 worktree 分支，交回使用者。

---

## 1. 前置檢查（1 分鐘）

```bash
# 1a. 確認沒有 drain worker 在跑（應為空）
#     PowerShell:
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*drain_236903cf*' } | Select-Object ProcessId, CommandLine

# 1b. 確認佇列數字（應 completed=1354 / failed=10 / pending=1939；數字會因步驟 2 微調）
py -3.11 - <<'PY'
import sqlite3
c = sqlite3.connect(r'D:\Users\666\Desktop\kg-runtime\task_queue.db')
print(dict(c.execute("SELECT status,COUNT(*) FROM task_queue GROUP BY status").fetchall()))
PY

# 1c. 確認 Neo4j kg2-neo4j 起得來（用 repo 既有的連線方式；查不到就先啟動 Neo4j Desktop / service）
```

若 Neo4j 沒起來，先啟動再往下。

---

## 2. 步驟 1：T0 Cypher smoke（純讀，幾分鐘）

**目的**：在跑 T1 之前，先直接看抽取端修正（F2 `_RANGE_COMPARATOR_PATTERN` 夾單位、F3b 序數守衛、`_MEASURE_PATTERN` 補 `級`/`個月`）有沒有在圖裡產生正確結果。若這步就沒修好，不用往下跑 T1，直接回報。

**做法**：對 `kg2-neo4j` 跑下列查詢。**Entity 的 label / property 名稱以 `services/svo_service.py`、`services/retrieval_service.py` 實際為準**（下方用常見形態 `:Entity {name, aliases}`、邊型 `rel_type`）。

### 2.1 標的清單（報告30 §4.3 / §9.2、報告32 §5）

| # | 文件 | 查什麼 | 期望（修好的樣子） | 對應 |
|---|---|---|---|---|
| S1 | N0060029 三段休息 | `高度在二十公尺以上者` 出邊 | `→ 三十五分鐘`（不是「二十五分鐘」） | 報告26 §2.1 頭號失敗 |
| S2 | N0060029 | `高度在二公尺以上未滿五公尺者` 是否為**獨立節點** | 有獨立節點、不是 `五公尺以上未滿二十公尺者` 的 alias；其出邊指向「二十分鐘」那段 | 報告32 §5.2 A 層、報告30 §9.3（F2） |
| S3 | N0060065 母性健康 | `血中鉛濃度在十 μg/dl 以上者` 是否為獨立節點 | 有獨立節點、不是「五 μg/dl 以上未達十」（第一級）的 alias；其事實鏈到「第三級管理」 | 報告32 §5.2 A 層 Q6 根因（F2） |
| S4 | N0060065 | `第一級管理` 的 aliases | **不含** `第二級管理` / `第三級管理` | 報告32 §5.2（F3b：`第[數字]級` 序數守衛） |
| S5 | N0070020 檢查費 | `每一型式` 與「多種型式…者」的金額邊 | `每一型式 → 八千元`、`同時申請多種型式…者 → 四千元` 兩條分開 | 報告25 §7、報告30 §9.2（未回歸） |
| S6 | N0070020 | `每一型式` / `每增加一種型式` 是否被誤併 | 兩者不互為 alias（或後者根本沒被抽成獨立短詞——報告30 §9.2 本輪如此） | 報告29 §4.1（潛在風險） |
| S7 | N0030018 育嬰留停 | `三十日以上` / `未滿三十日` 的出邊 | `三十日以上 → 於十日前提出`、`未滿三十日 → 於五日前提出` | 報告25 §7（發現3）、報告30 §9.2（未回歸） |

### 2.2 查詢模板

```cypher
// 出邊：某實體指向什麼
MATCH (e:Entity)-[r]->(t)
WHERE e.name CONTAINS $frag
RETURN e.name, coalesce(r.rel_type, type(r)) AS rel, t.name
ORDER BY e.name;

// 別名：某實體掛了哪些 alias（分段誤併會在這裡現形）
MATCH (e:Entity)
WHERE e.name CONTAINS $frag OR any(a IN e.aliases WHERE a CONTAINS $frag)
RETURN e.name, e.aliases;

// 反向：某個值是被誰指到的
MATCH (s)-[r]->(v:Entity)
WHERE v.name CONTAINS $frag
RETURN s.name, coalesce(r.rel_type, type(r)) AS rel, v.name;
```

`$frag` 依序帶：`高度在二十公尺以上`、`二公尺以上未滿五公尺`、`血中鉛濃度在十`、`第一級管理`、`每一型式`、`每增加一種型式`、`三十日以上`、`未滿三十日`。

### 2.3 判定

- 全部符合「期望」→ 抽取端修正生效，往步驟 2。
- S1/S2/S3/S4 任一仍是舊壞樣子 → **停**，記下實際 Cypher 結果，回報使用者（可能 F2/F3b 沒 ff 進跑 drain 的碼，或修正沒涵蓋該形態）。S5–S7 若壞是次要（報告30 標為「未回歸」），記錄但不擋 T1。

---

## 3. 步驟 2：補 `N0060016` chunk 2（~5 分）

`N0060016_重體力勞動作業勞工保護措施標準` = 報告26 **Q2（四十／四點五公斤）** 的文件，目前有 **1 個 failed chunk（chunk_index=2）**。跑 T1 前補掉，免得 Q2 事實缺漏。

```bash
# 3a. reset 那一筆
py -3.11 - <<'PY'
import sqlite3
c = sqlite3.connect(r'D:\Users\666\Desktop\kg-runtime\task_queue.db')
c.execute("UPDATE task_queue SET status='pending', updated_at=NULL "
          "WHERE kg_id='236903cf-055a-40a8-8923-b9d06601f3b7' "
          "AND source LIKE 'N0060016%' AND chunk_index=2")
c.commit()
print("reset:", c.total_changes, "row")
PY

# 3b. 跑「單筆 / 小量」drain 把它抽掉
#     用 kg-reextract worktree 裡跑 drain 的同一支腳本，限定只處理 pending 的 1 筆。
#     具體腳本名 / 參數：看 efb89cec 的 tmp（C:\Users\666\.claude\jobs\efb89cec\tmp\）裡的
#     monitor_drain_236903cf.sh 或 drain_236903cf 相關檔，或 repo 內 drain 進入點。
#     跑完 ctrl-c / 讓它自己因 pending 附近沒東西而停。

# 3c. 確認變 completed
py -3.11 - <<'PY'
import sqlite3
c = sqlite3.connect(r'D:\Users\666\Desktop\kg-runtime\task_queue.db')
print(list(c.execute("SELECT source, chunk_index, status FROM task_queue "
    "WHERE source LIKE 'N0060016%' ORDER BY chunk_index")))
PY
```

若 3b 這筆連續 3 次仍 failed：依報告30 §5.2，看 Q2 的答案事實（四十公斤 / 四點五公斤）在不在 chunk 2。若在別的 chunk（0/1）→ 不擋 T1，記錄缺口；若就在 chunk 2 → 手動把該 chunk 切小或加「重試到 JSON 合法」迴圈。

---

## 4. 步驟 3：T1（~3 小時，drain 全程停）

### 4.1 指令

```bash
# repo root。報告32 用的是合併腳本 run_t1.py（== run_report26_comparison.py 題組
# + rerun_report25_conditionA.py 題組，各題 ×3）。
py -3.11 run_t1.py            # 若存在
# 若沒有 run_t1.py：分別跑
py -3.11 rerun_report25_conditionA.py   # 報告25 條件A 8 題 ×3（只跑 A）
py -3.11 run_report26_comparison.py     # 報告26 8 題，A + D（×3）；B 直接引用報告26、不重跑
```

輸出：報告32 存成 `t1_output.txt`（955 行）。本輪存成 `t1_output_20260909.txt`（別覆蓋舊的）。

### 4.2 rubric（跑之前先貼在結果檔開頭，報告30 §2.2）

1. 每題逐字答案字串取自報告26 §1 / 報告25 §7 表格。
2. pass = 目標字串**全中** 且 **無「同單位錯值」出現**。
3. 每題 3 次，記「k/3 乾淨」。
4. 回歸判定：只有「報告27 §6.1（或報告32）是 ✅、這輪 ≥1 次失敗」才算回歸、才要回報為擋點。

### 4.3 逐題預期（報告32 §1–§2 基準 + 這輪應改善項）

**報告25 條件A 8 題**（報告32：4/8 乾淨、4/8 退化）

| 題 | 文件 | 報告32 結果 | 這輪預期 |
|---|---|---|---|
| Q1 | N0030011 夜間安全設施 | ✅ 3/3 | 維持 ✅ |
| Q2 | N0030018 育嬰留停 | ◐（十日前守住、「每次≥六個月」2/3 錯、「二次為限」沒乾淨答出） | E3 落地了 `_MEASURE_PATTERN` 補「個月」→ 期望「六個月為限」轉穩；「二次為限」偏生成端，可能仍 ◐ |
| Q3 | N0030025 未滿15歲工時 | ◐（三段年齡 1/3 完整） | 節點本來就獨立（報告32 §5.2），退化是生成/檢索端 → 可能仍 ◐；看 G1 有沒有幫上 |
| Q4 | N0060007 高溫作業 | ✅ 3/3 | 維持 ✅ |
| Q5 | N0060012 精密作業 | ◐輕微（1/3 漏 15 分休息） | 非決定性；維持或轉 ✅ |
| Q6 | N0060065 母性健康 | ◐（「血中鉛 10μg/dl→第三級」3/3 未答出） | **F2 修好後期望轉 ✅**（S3 若在步驟 1 通過，這裡應跟著好） |
| Q7 | N0070020 檢查費 | ✅ 3/3 | 維持 ✅（S5/S6 未回歸的話） |
| Q8 | N0080016 原住民訓練補助 | ✅ 3/3 | 維持 ✅ |

**報告26 8 題（A + D）**

| 題 | 文件 | 報告32 A 結果 | 這輪預期 |
|---|---|---|---|
| Q1 | N0060029 三段休息 | ◐（20m→35 分 ✅；2–5m/5–20m 混淆 3/3） | **F2 修好後期望三段齊全 ✅**（S1+S2 通過的話） |
| Q2 | N0060016 重體力 | ✅ 3/3 | 維持 ✅（前提：步驟 2 補好 chunk 2） |
| Q3 | N0080013 大量解僱 | ↑ 改善（3/3） | 維持 |
| Q4 | N0080013 數值密集 | ✅ 3/3 | 維持 |
| Q5 | N0050030 災區保險費 | ◐（起算日「當月一日」3/3 未答出） | 生成端（G4，未做）→ 可能仍 ◐ |
| Q6 | N0050011 繼續加保 | ✅ 3/3 | 維持 |
| Q7 | N0060007 誠實拒答 | ✅✅ 3/3 | 維持 |
| Q8 | N0060004 變量係數 | ✗（多跳區間推理缺，G2 未做） | 資料已修（清單有「1 以上未滿 10→係數 2」）；生成端多跳仍缺 → 可能仍 ✗，看 G1 定向修訂有沒有讓它別自我推翻 |
| D（純 LLM） | 全 8 題 | 0/24 乾淨 | 對照組，維持 0 即可 |

### 4.4 每題收集欄位（報告30 §2.4）

最終答案文字、pass/fail vs rubric、延遲、BFS 三元組數、語意 Fact 數、是否觸發限制性重生成（`regenerated`）、grounding 支持比。

> partial KG：**正確性結論可信**（14 題文件 100% 抽完）；**延遲數字只是指標性**，最終以 DRAIN-DONE 後 §6.2 為準。

---

## 5. 步驟 4：G1 讀取判定（併在 T1 內，不另跑）

G1（限制性重生成過度修正 → `_targeted_correction()` 定向修訂，commit `bd3bbb7`）改的是 `chat()` 重生成路徑，每次 T1 呼叫都會走到。從 `t1_output_20260909.txt` 讀：

1. **`regenerated=True` 比例**：報告32 §4 觀察1 = ~75%，且常把對草稿改壞（Q2 part1、Q8 run3）。這輪比例有沒有下降？
2. **定向修訂行為**：`regenerated=True` 的案例，接地句有沒有被原樣保留、只有未接地句被重寫（G1 的預期行為）；還是整份 factored 重生。
3. **改壞率**：草稿本來對、重生成後變錯的次數。G1 的目標是把這個壓下去。

輸出：G1 端到端效果一句話結論（有效 / 無感 / 仍改壞），附 2–3 個 T1 實例行號。

---

## 6. 步驟 5：θ 敏感度網格（選配，只有 T1 的 Q6/Q7 沒收斂才做）

報告30 §2.6。直接呼叫 `bfs_query()`，不經 `chat()`、不搶 Ollama，27 組幾分鐘。

- 網格：`θ_deg (_SEED_MAX_DEGREE) ∈ {100, 200, 400}` × `θ_hop (_BFS_EXPAND_WHEN_BELOW) ∈ {5, 8, 12}` × `per_seed_limit (_BFS_PER_SEED_LIMIT) ∈ {30, 60, 100}`
- 對 Q6 / Q7 量 BFS 三元組數、目標事實有沒有進候選。
- 挑一組能讓 Q6（三元組 ≤ 30）+ Q7（延遲目標 < 90s）過的 config，只重跑 Q6/Q7 過 `chat()` 確認。
- 現行值：`_SEED_MAX_DEGREE=100`、`_BFS_PER_SEED_LIMIT=30`（`7b6d208` 由 200/60 收緊，只驗過 Q6 單題）。

---

## 7. 完成後

1. **回 `efb89cec` session 一句「繼續」**，讓它重啟 2-worker drain。
2. **當場確認**：`Get-CimInstance ... drain_236903cf` 有兩個進程；`task_queue.db` 的 `completed` 開始往上（跑個 2–3 分鐘再查一次）。
3. 把下列交回使用者 / 主線：
   - `t1_output_20260909.txt`
   - **T1 結果表**：報告25 8 題 + 報告26 8 題，逐題 k/3、延遲、BFS 三元組數、`regenerated`、grounding 支持比
   - **T0 smoke 結果**：S1–S7 逐項實際 Cypher 輸出 + 判定
   - **G1 結論**（步驟 4）
   - **有沒有發現新的抽取端 bug**（若 S1–S4 有壞的）——這會決定要不要在 drain 跑完前先改碼＋局部重抽，還是照原計畫等 DRAIN-DONE
   - θ 網格結果（若有做）

## 8. 若中途要中斷

- drain 已經是停的，隨時可停手。
- 唯一要記得的：**別把 `efb89cec` 晾在 `blocked` 太久**——若今天不打算做完 T1，先回它「繼續」讓 drain 先跑，T1 改天在下一個暫停窗口做。
- 已改的檔案（θ 網格腳本之類）留在 worktree 分支，別推 master。

---

## 9. 相關文件

- `docs/報告/30_c15949bf全量重抽最終驗收計畫.md` §1（三時點）、§2.2（rubric）、§2.6（θ 網格）、§4.3（T0 清單）、§4.4（drain 紀律）、§5（failed chunk 處理）、§9（T1 就緒、T0 結果、F2/F3b 缺口）
- `docs/報告/32_T1階段測試結果與列舉分段DEDUP診斷報告.md` §1–§3（上一輪逐題）、§4（三個跨題觀察）、§5（E1 診斷）、§6（生成端 G1–G4）、§7（執行順序）、§9（誤刪事件、選項 C、F2/F3b/§4.1/E3/G1 落地 commit）
- `docs/報告/25_...md` §7（報告25 8 題逐字答案 + 發現3/C）
- `docs/報告/26_...md` §1（8 題題組 + 逐字答案）、§2（逐題）、§4（瓶頸排序）
- `docs/報告/27_...md` §6.1（早期部分驗證先例）、§6.2（最終全量驗證待辦）
- memory：`project_c15949bf_full_reextraction`、`feedback_worktree_self_deletion`
