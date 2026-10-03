# 報告275：S2b 條文層影子顯示執行紀錄（Codex）

> 日期：2026-10-04
>
> 性質：報告273 S2b 的 T1–T7 執行紀錄。結果供規劃對話獨立驗收；本報告不取代報告274，亦不宣稱已驗證。

## 1. 範圍與前置

- 工作樹：`sdd-retrieval-comparison`。
- 分支：`worktree-sdd-retrieval-comparison`。
- 已先執行 `git pull`：`Already up to date`。
- 已重新閱讀報告273，包含 §13 裁示：`source_svo_chunk_index=None` 不構成停止條件；缺值或查無對照一律標 `INDETERMINATE`，不猜測、不改檢索、不查詢。
- 報告274 保留為前次停止紀錄，本次另建報告275。
- 基準全量 pytest：`2241 passed, 8 warnings, 1 subtests passed`。

全程離線：未連 KG#4（17990）、`kg2-neo4j`、任何 Neo4j／Ollama，未操作 Docker，未讀取或印出 `.env`／密碼。

## 2. T1–T4 實作

### T1：唯讀 repository 方法

在 `repositories/law_document_repo.py` 僅新增兩個方法，既有方法未改動：

```text
article_nos_for_evidence(self, kg_id: UUID, keys: Sequence[tuple[str, int]]) -> dict[tuple[str, int], str]
list_article_nos(self, kg_id: UUID, source_doc_id: UUID) -> list[str]
```

兩個查詢均限定 `kg_id`、只使用 `MATCH`／`UNWIND`／`RETURN`／`ORDER BY`，不取 `article_content`，不含寫入 Cypher 關鍵字。空 `keys` 直接回 `{}` 且不查詢；同一證據鍵對應多條號時記錄 warning 並取字面排序最小值。

### T2：條文層純函式

新增：

```text
article_effective_marks(
    *, as_of, document_notes, document_status, evidence_keys,
    article_nos, known_articles
) -> dict[tuple[str, int], dict[str, Any]]
```

此函式不做 I/O、不取目前時間、不匯入資料庫／HTTP 模組；`services.effective_note` 仍為函式內延遲匯入。同一待施行文件只解析一次。文件層非 `has_pending` 時直接沿用狀態；文件不存在、查無條號、或其他對照缺值時回傳 `INDETERMINATE`。

### T3：retrieval trace

`build_retrieval_trace` 新增選用參數：

```text
article_effective_status: Mapping[tuple[str, int], Mapping[str, object]] | None = None
```

只有 `include_semantic_marks=True` 且參數非 `None` 時，才在既有 `document_effective_status` 後附加 `article_effective_status`；`pending_whole`／`pending_partial` 才附加 `article_effective_from` 與 `article_pending_locators`。缺值或查無鍵在 trace 層為 `INDETERMINATE`。

### T4：router 條件式接線

新增：

```text
_fetch_article_effective_inputs(
    driver, kg_id, evidence_keys, pending_doc_ids
) -> tuple[dict, dict]
```

只有旗標開啟、`include_retrieval_trace=true`、且本次證據含 `has_pending` 文件時，才收集鍵並呼叫新增 repository 方法。空鍵／空待施行文件集合不建構 repository。新增查詢與計算包在 `try/except Exception`；失敗只記 generic warning，不傳條文層參數，因此不影響回答、`sources` 其餘內容或 SSE 串流。`date.today()` 維持只在 `routers/agent.py` 的既有 `as_of` 位置。

## 3. T5 測試與結構守衛

新增 16 個測試，未修改任何既有測試：

- `tests/repositories/test_law_document_repo_article_effective.py`：空鍵零查詢、多條號 warning／最小值、`kg_id`、只讀查詢、條號清單不取內容。
- `tests/services/test_context_article_effective_marks.py`：報告273 §4-5 的整條增訂、範圍展開、附表／項定位、各文件層狀態、單文件只解析一次、缺值與查無鍵、trace 鍵順序，以及時鐘／外部依賴／唯讀查詢結構守衛。
- `tests/routers/test_agent_article_effective_marks.py`：成功 SSE、旗標關閉零新增 repository 呼叫、不需查詢路徑、repository 例外失敗隔離、空輸入不建構 repository。

缺值證據測試結果：

1. triple 的 `source_svo_chunk_index=None`：trace 標 `INDETERMINATE`，不產生查詢鍵。
2. Fact 的 `source_doc_id=None`：trace 標 `INDETERMINATE`，不產生查詢鍵。
3. `has_pending` 文件但 `article_nos` 查無 `(source_doc_id, chunk)`：標 `INDETERMINATE`，其餘欄位為空，且不因缺鍵補查或猜測。

## 4. T6 文件紀錄

已新增本報告275、更新 `docs/報告/00_報告索引.md` 一行，並在 `HANDOVER.md` 頂部加入本次交接條目。報告274 未覆寫。

## 5. T7 測試結果與限制

- 聚焦測試（含本次新增與受影響既有測試）：前一輪為 `190 passed`；新增缺例後本次新增測試為 `16 passed`。
- 全量 pytest：`2257 passed, 8 warnings, 1 subtests passed`。
- `python scripts/analysis/check_node_cards.py`：`掃描 3 張節點卡，0 則警告`。
- §4-5 表格案例：離線 fixture／純函式測試涵蓋營造第11-2／第12條、設施規則列示的 21-3／57／116／185-1～185-4、教育訓練第3條、健康保護第5／6／17條、勞動契約法 `undetermined`、無備註 `no_information`、請假規則 `in_force`；預期狀態、日期與 locator 測試均通過。
- 未執行 KG#4 唯讀端到端 Fact 計數核對，因本次硬規則要求全程離線；該項留待規劃對話獨立驗收。
- 本次無報告273 §8 停止條件；§13 缺值裁示依規格落實。

待規劃對話進行差分輸出與 KG#4 唯讀核對；本次紀錄僅報告本地實作與測試執行結果。
