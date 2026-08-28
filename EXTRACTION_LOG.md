# 勞基法語料抽取任務 - 完成紀錄

**完成時間**: 2026-08-07 ~08:1x (Asia/Taipei)
**DB 位置**: `./workspace/task_queue.db`（主目錄根目錄，非 worktree）
**服務**: 已關閉（抽取完成，無事可做；kg2-neo4j 容器仍保留運作中）

---

## 最終狀態：全部完成 ✅

| 項目 | 數量 |
| --- | --- |
| Chunk 總數 | 1874 |
| 已完成 | **1874（100%）** |
| 待處理 / 處理中 / 失敗 | 0 / 0 / 0 |
| 排班與工時法規（deb24e7c）文件 | 56/56 完成 |
| 請假與薪資法規（2ae9d28b）文件 | 69/69 完成 |
| Neo4j 實體數 | 3170 |
| Neo4j 關係數 | 5624 |
| Neo4j Chunk 節點數 | 1924 |

驗證方式：`task_queue.db` 狀態統計 **加上** 逐文件 `_record.json` 的 `extraction_status` 交叉確認（兩者都顯示 100% 完成，避免佇列空但實際未完成的假性完成誤判）。

---

## 這段期間解決過的問題（供未來參考）

1. **worktree 資料遺失**：原本的 `task_queue.db` 進度存在 `.claude/worktrees/labor-law-corpus-test/`，該 worktree 隨背景工作階段結束被清除，本地進度索引遺失（但 Neo4j 圖譜資料本身沒事，存在獨立的 Docker named volume）。修復：workspace 改搬到主目錄根目錄的 `./workspace/`（不在 `.claude/worktrees/` 底下，不會被清除）。
2. **與 Antigravity IDE 的並行衝突**：使用者電腦上另一個 IDE（Antigravity）也在獨立處理同一個抽取任務，兩邊互不知情、搶佔同一個 8010 埠與同一份 `.env`。已請使用者關閉該側工作階段，整合雙方進度後統一由這邊接手。
3. **`rebuild_from_records()` 的 chunk index bug**：原邏輯假設每份文件的 SVO chunk index 一定從 1 連續編號，但部份文件並非如此，導致誤判為「找不到 SVO chunk」的假性失敗。已修正為直接讀取 `svo_index.json` 的實際 index 清單，並提交到 master（commit `5909c4c`）。
4. **11 份大文件從未真正切過 SVO chunk**：`task_queue.db` 一度顯示「全部完成」，但逐文件核對後發現 11 份大文件的 `svo_total_chunks` 為 0，代表根本沒排入過工作。用獨立腳本 `fix_stuck_docs.py`（留在 repo 根目錄）直接呼叫 `trigger_extraction()` 補上，之後才是真正完成。
5. **Windows 保留連接埠範圍問題**：Neo4j 的 bolt 埠（原 7990）與主伺服器埠（原 8010）都曾先後落入 Windows/Hyper-V 動態保留的連接埠範圍，導致無法綁定。透過 `netsh interface ipv4 show excludedportrange protocol=tcp` 診斷後改用未被佔用的埠（Neo4j 一度改用 17990，主伺服器一度改用 8500），問題排除後又都各自換回原本的埠。

---

## 環境配置（結束時）

| 設定 | 值 |
| --- | --- |
| `WORKSPACE_DIR` | `./workspace` |
| KG `deb24e7c` folder_path | `workspace/deb24e7c-c012-4398-9261-c813cb60b197` |
| KG `2ae9d28b` folder_path | `workspace/2ae9d28b-3c5e-424f-9ea4-c3cbe59a2934` |
| `task_queue.db` | `./workspace/task_queue.db`（主目錄根目錄） |
| Neo4j bolt port | `17990`（`bolt://localhost:17990`） |
| Neo4j HTTP port | `7476` |

若之後需要重跑或補做其他語料，直接沿用上述設定即可，不需要再走 worktree。
