# 報告274：尚未施行標示 S2b 條文層影子顯示停止紀錄（Codex）

> 本文件是報告273 的 Codex 執行紀錄，供規劃對話獨立驗收；本次因停止條件觸發，未進入 production 實作，不取代規劃對話的驗證。

## 1. T0 前置結果

- 工作目錄：`.claude/worktrees/sdd-retrieval-comparison`。
- 分支：`worktree-sdd-retrieval-comparison`。
- `git pull`：`Already up to date`。
- HEAD：`133e8c8 docs(報告273): 尚未施行標示S2b條文層影子顯示任務書`，符合報告273 要求的 HEAD ≥ `2f96ad1`。
- 已先列出 `docs/報告`；報告274在本次新增前不存在。
- 未改動前基準：`python -m pytest -q -p no:cacheprovider` → `2241 passed, 8 warnings, 1 subtests passed`。

## 2. 觸發的停止條件

依報告273 §8.4，讀碼發現 `chat()` 的證據不一定帶
`source_svo_chunk_index`，會影響 S2b 所需的 `(source_doc_id, chunk)` 對應鍵，因此在讀碼階段停止，不自行修改檢索或補造欄位。

## 3. 讀碼現況與影響

讀取的現有程式顯示：

1. `models/knowledge_graph.py` 的 `SVOTriple.source_svo_chunk_index` 型別為
   `int | None`，預設值為 `None`；同段註解也說明一般 SVOGROUP chunk 恆為 `None`，只有法規 ArticleAwareChunking chunk 才可能有值。
2. `services/retrieval/bfs.py` 從 citation 以 `latest.get("source_svo_chunk_index")` 建立 triple，因此沒有 citation 欄位時會保留 `None`。
3. `routers/agent.py` 的 `chat()` 使用既有 `vector_search_facts()` 的 `fact_results` 與 BFS `triples`；本次沒有改動任何檢索路徑。
4. `services/context/telemetry.py` 現有 trace 已將 fact／triple 的缺值序列化為
   `source_svo_chunk_index=None`；`routers/agent.py` 既有 `_expand_facts_by_article()` 也會對缺少文件或 chunk 的 fact 跳過 `(source_doc_id, chunk)` 鍵。
5. 因此，S2b §4-4 要求的證據鍵只能對有 chunk index 的項目建立；若在缺值項目上猜測、改用其他欄位或改檢索補欄位，都會改變既有語意或違反報告273 §8.4。

影響範圍：即使只在 `has_pending` 文件上啟用，條文層標示也無法對所有 `chat()` 證據保證完成；缺值證據只能被略過或標成不確定，不能依現有資料可靠取得 `LawArticle` 對應。這是本次停止原因，不是測試失敗。

## 4. 尚未執行的步驟

停止後未執行：

- T1：未新增 `LawDocumentRepository.article_nos_for_evidence`／`list_article_nos`。
- T2：未新增 `article_effective_marks`。
- T3：未修改 `build_retrieval_trace`。
- T4：未修改 `routers/agent.py`，未新增查詢或失敗隔離接線。
- T5：未新增測試，未修改既有測試。
- T7：未執行收尾全量 pytest，也未執行 `python scripts/analysis/check_node_cards.py`；T0 基準結果如上。

本次僅新增本停止報告、報告索引一行與 `HANDOVER.md` 頂部條目；沒有 production 變更、沒有檢索變更、沒有資料庫查詢。

## 5. 離線與差異聲明

- 未連 KG#4（17990）、`kg2-neo4j`、任何 Neo4j 或 Ollama。
- 未操作 Docker，未讀取或輸出 `.env`、密碼或其他敏感值。
- 未修改既有測試、既有腳本、題庫、資料檔、規劃文件、論文或歷史報告原文。
- 與報告273 的差異：觸發 §8.4 後停止，T1–T7 production 實作未做；僅留下本停止紀錄與交接文件。

## 6. 待規劃對話處理

請規劃對話先裁示如何處理缺少 `source_svo_chunk_index` 的既有證據，再決定是否另寫任務書；本 Codex 執行不自行放寬守衛、不改檢索、不調整期望。
