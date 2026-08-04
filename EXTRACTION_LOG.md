# 勞基法語料抽取任務 - 接續狀態紀錄

**最後更新**: 2026-08-04 11:36 (Asia/Taipei)
**資料庫位置**: `.claude/worktrees/labor-law-corpus-test/workspace/task_queue.db`

---

## 1. 接續抽取進度（2026-08-04 第二次啟動）

| 狀態 | 數量 |
| :--- | :---: |
| **已完成 (completed)** | **1120+（持續增加中）** |
| **待處理 (pending)** | **625（持續減少）** |
| **失敗 (failed)** | **0** |
| **總 Chunk 數** | **1746** |

---

## 2. 本次診斷修復的三個問題

### 問題一：`task_queue.db` 路徑不一致
- `check_status.py` 查 `.claude/worktrees/.../workspace/task_queue.db`
- 服務用 `.env` 的 `WORKSPACE_DIR=./workspace`（空的 DB）
- **修法**：`.env` 改為 `WORKSPACE_DIR=./.claude/worktrees/labor-law-corpus-test/workspace`

### 問題二：Neo4j `folder_path` 仍指向舊路徑
- KG 的 `folder_path` 存的是 `workspace\<kg_id>`（相對路徑，指向空目錄）
- chunk 資料實際在 `.claude/worktrees/.../workspace/<kg_id>/`
- **修法**：執行 `fix_folder_path.py` 更新 Neo4j 兩個 KG 的 `folder_path`

### 問題三：`backfill_entity_name_embeddings` 佔滿 event loop
- 同步 `encode()` 在迴圈中 block asyncio，導致 extraction_worker 無法被調度
- **修法**：`svo_service.py` 的 backfill 迴圈每筆加 `await asyncio.sleep(0)`

---

## 3. 下次接續抽取說明

```powershell
# 直接啟動，系統自動接續
& "d:\Users\666\Desktop\world knowledge graph rag\.venv\Scripts\python.exe" -m uvicorn main:app --port 8010 --log-level info
```

如有大量 failed，執行 `reset_failed.py` 重置後再重啟。


**記錄時間**: 2026-08-04 10:09 (Asia/Taipei)
**資料庫位置**: `.claude/worktrees/labor-law-corpus-test/workspace/task_queue.db`

---

## 1. 任務終止執行結果
- **Port 8010 服務進程**: 已強制終止 (`Stop-Process`)
- **卡住任務清理**: 已重置 1 筆 `processing` 狀態為 `pending`，確保乾淨中斷
- **背景抽取進程**: 已完全停止

---

## 2. 最終抽取進度統計 (`task_queue`)

| 狀態 | 數量 | 比例 |
| :--- | :---: | :---: |
| **已完成 (completed)** | **1119** | **64.09%** |
| **待處理 (pending)** | **505** | **28.92%** |
| **失敗 (failed)** | **122** | **6.99%** |
| **處理中 (processing)** | **0** | **0.00%** |
| **總 Chunk 數** | **1746** | **100%** |

---

## 3. 關聯擴充與日誌統計
- **`expand_pool` (動詞池)**:
  - `pending`: 560 筆
  - `discarded`: 436 筆
- **`expand_cluster_proposal` (聚類提案)**:
  - `awaiting_review`: 4797 筆
- **`escalate3_log` (三階升級紀錄)**:
  - 共 2350 筆紀錄

---

## 4. 下次接續抽取說明
下次如需重啟接續抽取，請直接執行以下步驟：

1. **啟動 FastAPI 服務**：
   在工作樹目錄下啟動服務：
   ```powershell
   # 進入工作樹目錄
   & "d:\Users\666\Desktop\world knowledge graph rag\.venv\Scripts\python.exe" -m uvicorn main:app --port 8010 --log-level info
   ```
2. **自動接續機制**：
   系統在 `lifespan` 啟動時會自動呼叫 `_restart_task_queue()` 檢查 DB，並繼續消費剩餘 505 筆 `pending` Chunks。
