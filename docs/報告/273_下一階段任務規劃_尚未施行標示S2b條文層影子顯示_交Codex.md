# 報告273：下一階段任務規劃——「尚未施行」標示 S2b：條文層影子顯示（預設關閉、零行為變更；不改檢索）（交 Codex）

> **日期**：2026-10-04
> **性質**：階段任務規劃。分工：**規劃對話（Claude）決定與獨立驗證、Codex 執行、規劃對話只記錄**。**本文件只由規劃對話修改（§12 執行紀錄）。**
> **依據**：[報告272 §4](272_尚未施行標示S2啟用觀察指南與S2b設計草案.md)（S2b 設計草案）、[報告270 §12](270_下一階段任務規劃_尚未施行標示S2文件層影子顯示_交Codex.md)（S2 已驗證）、[報告267](267_尚未施行條文標示_唯讀分析與設計.md)；使用者「同意，請繼續」＝同意進行 S2b。
> **基準**：HEAD ≥ `2f96ad1`；全量 pytest **2241 passed**。
> **本任務的性質**：**會修改 production 程式，但只在 `TRACE_SEMANTIC_MARKS` 旗標開啟、`include_retrieval_trace=true`、且本次證據含「有待施行條文的文件（`has_pending`）」時才多做事；其餘情況（旗標關閉＝預設）所有輸出必須與修改前逐位元相同，且不得多執行任何資料庫查詢。不改檢索、排序、截斷、prompt、生成、評分；不寫入任何資料；Codex 全程離線。**

---

## 1. 目標（〔判讀〕）

S2 只標到「文件層」：設施規則 1,829 個 Fact 中只有 105 個（5.7%）真的屬於待施行條文，整份文件卻都會被標 `has_pending`。S2b 讓**檢索 trace 的每筆證據（Fact／三元組）**多帶**條文層狀態**——這是 S3（prompt 附註、整條增訂排除）的前置條件。**本任務仍只做影子顯示。**

## 2. 任務總覽

| 步驟 | 內容 | 產出 |
| --- | --- | --- |
| **T0** | 前置：`git fetch`／`git status`；HEAD ≥ `2f96ad1`；基準 pytest（應 2241 passed）；`ls docs/報告`（Codex 報告自 **274** 起）；讀 §3 所列檔案與其既有測試 | 基準數字 |
| **T1** | `repositories/law_document_repo.py`：**僅新增**兩個唯讀方法（§4-1） | 修改一檔 |
| **T2** | `services/context/trace_marks.py`：新增純函式 `article_effective_marks(...)`（§4-2） | 修改一檔 |
| **T3** | `services/context/telemetry.py`：`build_retrieval_trace` 新增選用參數（§4-3）；順手補 `Mapping` 匯入（§4-6） | 修改一檔 |
| **T4** | `routers/agent.py`：新增 `_fetch_article_effective_inputs`、在 `chat()` 條件式呼叫（§4-4） | 修改一檔 |
| **T5** | 測試（§5）、結構守衛（§6） | 新增測試 |
| **T6** | 報告 274＋索引一行＋`HANDOVER.md` 頂部條目 | 文件 |
| **T7** | 全量 pytest、`scripts/analysis/check_node_cards.py`、commit | 回報 |

## 3. 必讀位置（〔事實〕，規劃對話已讀碼；請自行重新核對）

- `routers/agent.py:374–404` `_fetch_document_map`（以 `LawDocumentRepository(driver).get_document` 逐份查 `Document`）；`:1436–1460` `chat()` 內 S2 的 `effective_marks_kwargs(...)` 與 `_serialize_sources(...)`／`_build_retrieval_trace(...)` 呼叫。
- `repositories/law_document_repo.py:90–136`（`get_document`、`list_law_articles`——後者取回整條內容，S2b 只需要條號，故新增輕量方法，**不要改它**）。
- `services/context/telemetry.py` `build_retrieval_trace`（已有 `document_effective_status` 參數；每筆 fact／triple entry 含 `source_doc_id`（字串或 `None`）與 `source_svo_chunk_index`）。
- `services/context/trace_marks.py` `effective_marks_kwargs`（S2）。
- `services/effective_note.py`（S1／S2）：`parse_effective_note(note, known_articles)`、`article_effective_status(parsed, article_no, as_of) -> ArticleEffectiveStatus(status, effective_from, locators, ops)`、`document_effective_status`、`summarize_document_effective`、`STATUS_*` 常數。
- 資料形狀（〔事實〕）：KG#4 的 `Fact` 節點有 `source_doc_id`（字串）與 `source_svo_chunk_index`（整數），經 `SUPPORTED_BY` 連到 `LawArticle`（有 `article_no`，如 `第 57 條`、`第 185-1 條`、`第 11-2 條`）；同一區塊的 Fact 都連到同一條文；`LawArticle` 以 `PART_OF` 連到 `Document`（`Document.source_doc_id`）。

## 4. 規格

### 4-1　T1：兩個新增的唯讀 repository 方法（只讀、限定 `kg_id`、**不得含** `SET`／`CREATE`／`MERGE`／`DELETE`／`REMOVE`／`CALL`）

```python
async def article_nos_for_evidence(self, kg_id: UUID, keys: Sequence[tuple[str, int]]) -> dict[tuple[str, int], str]
async def list_article_nos(self, kg_id: UUID, source_doc_id: UUID) -> list[str]
```
- `article_nos_for_evidence`：`keys` 為 `(source_doc_id 字串, source_svo_chunk_index)` 清單；以 `UNWIND $keys AS key MATCH (f:Fact {kg_id: $kg_id, source_doc_id: key.source_doc_id, source_svo_chunk_index: key.chunk})-[:SUPPORTED_BY]->(a:LawArticle {kg_id: $kg_id}) RETURN DISTINCT key.source_doc_id, key.chunk, a.article_no`（寫法可調整，語意不變）；`keys` 為空時**不查詢**直接回 `{}`；同一鍵對應多個不同條號時（理論上不應發生）取字面排序最小者並**記錄 warning**；找不到的鍵不在回傳中。
- `list_article_nos`：只回傳該文件所有 `LawArticle.article_no`（字串，字面排序），**不取 `article_content`**。
- **不得修改**既有方法。

### 4-2　T2：`services/context/trace_marks.py` 純函式

```python
def article_effective_marks(
    *, as_of: str,
    document_notes: Mapping[str, str | None],         # source_doc_id → Document.effective_note
    document_status: Mapping[str, str],               # source_doc_id → 文件層狀態（effective_marks_kwargs 的 document_effective_status）
    evidence_keys: Sequence[tuple[str | None, int | None]],
    article_nos: Mapping[tuple[str, int], str],       # T1 取得的 (doc, chunk) → 條號
    known_articles: Mapping[str, Sequence[str]],      # has_pending 文件 → 已知條號清單（T1）
) -> dict[tuple[str, int], dict[str, Any]]
```
- 回傳每個證據鍵（`doc` 非 `None` 且 `chunk` 非 `None`）的 `{"status": ..., "effective_from": str | None, "locators": list[str]}`：
  - 文件層狀態為 `in_force`／`no_information`／`undetermined`：直接沿用為條文層 `status`（`effective_from=None`、`locators=[]`），**不查詢、不解析**；
  - 文件層狀態為 `has_pending`：以 `known_articles[doc]`（把 `第 N 條` 轉成不含「第」「條」「空白」的 `N`，供範圍展開）解析 `document_notes[doc]`，再對該證據的條號（`article_nos` 查得；查無 → `status=semantic_marks.INDETERMINATE`、其餘空）呼叫 `article_effective_status(parsed, article_no, as_of)`；
  - 文件不在 `document_status`（`Document` 節點不存在）：`status=semantic_marks.INDETERMINATE`。
- **純運算**：不 I/O、不使用目前時間、不匯入 `neo4j`／`requests`／`httpx`；`services.effective_note` 沿用**函式內延遲匯入**。同一文件的 `parse_effective_note` 只解析一次（可快取於函式內）。

### 4-3　T3：`build_retrieval_trace`

新增選用參數 `article_effective_status: Mapping[tuple[str, int], Mapping[str, Any]] | None = None`。僅當 `include_semantic_marks=True` **且**參數非 `None` 時，fact 與 triple 的 `semantic_marks` **末尾**（在既有 `document_effective_status` 之後）附加：
- `"article_effective_status"`：對照表中該證據 `(source_doc_id, source_svo_chunk_index)` 的 `status`；對照表沒有該鍵（或 `source_doc_id`／`chunk` 為 `None`）＝`semantic_marks.INDETERMINATE`；
- 僅當 `status` 為 `pending_whole` 或 `pending_partial` 時，另附 `"article_effective_from"`（ISO 字串）與 `"article_pending_locators"`（`list[str]`，可為空）。
其他情況輸出與修改前**逐位元相同**。

### 4-4　T4：`routers/agent.py`

- 新增 `async def _fetch_article_effective_inputs(driver, kg_id, evidence_keys, pending_doc_ids) -> tuple[dict, dict]`（比照 `_fetch_document_map` 的位置與風格）：用 `LawDocumentRepository` 的 T1 方法，回傳 `(article_nos, known_articles)`；`evidence_keys` 或 `pending_doc_ids` 為空時**不呼叫資料庫**。
- 在 `chat()`：**僅當** `settings.trace_semantic_marks` 為真 **且** `payload.include_retrieval_trace` 為真 **且** `trace_kw["document_effective_status"]` 中**至少一個本次證據的文件狀態為 `has_pending`** 時：收集證據鍵（fact_results 的 `(str(source_doc_id), int(source_svo_chunk_index))`；triples 同理，`source_doc_id` 轉字串；缺值者略過）、`pending_doc_ids`（證據中屬 `has_pending` 的文件）→ 呼叫 `_fetch_article_effective_inputs` → `article_effective_marks(...)` → 結果以 `article_effective_status=` 傳給 `_build_retrieval_trace`。**其餘情況不得多做任何事、不得多執行任何查詢。**
- **失敗隔離**：上述新增的查詢與計算**包在 `try/except Exception` 內**——任何例外只 `logger.warning(...)`（不含密碼等敏感資料）並視同「沒有條文層標示」（不傳該參數），**絕不能影響回答、`sources` 事件的其他內容或串流**。
- 不新增設定項；不改 `vector_search_facts`、檢索、排序、截斷、prompt、生成；`date.today()` 仍只在 `routers/agent.py`（S2 已有的 `as_of`，直接沿用，不得重複取日期）。

### 4-5　條文層狀態的預期（〔事實〕，作為測試期望的來源，`as_of＝2026-10-03`）

| 文件／條文 | 預期 `article_effective_status` |
| --- | --- |
| 營造安全衛生設施標準 第 11-2 條（增訂、整條） | `pending_whole`，`effective_from=2027-07-01`，`locators=[]` |
| 營造安全衛生設施標準 第 12 條等其他條 | `in_force` |
| 職業安全衛生設施規則 第 57、116、21-3、185-1～185-4 條 | `pending_partial`，`effective_from=2027-01-01`（範圍須以已知條號展開） |
| 職業安全衛生教育訓練規則 第 3 條 | `pending_partial`，`locators` 含 `附表一`，`effective_from=2027-01-01` |
| 勞工健康保護規則 第 6 條 | `pending_partial`，`locators` 含 `第2～4項`，`effective_from=2027-07-01`；第 5 條 `pending_partial`（`2027-07-01`）；第 17 條 `2028-01-01` |
| 勞動契約法 任一條 | `undetermined` |
| 勞動基準法（無備註）任一條 | `no_information` |
| 勞工請假規則（已施行）任一條 | `in_force` |

（備註原文與已知條號清單可用 `tests/fixtures/kg4_effective_notes_20261003.json`；條號 `known_articles` 在測試中自行造，如設施規則 `["21-3","57","116","185","185-1","185-2","185-3","185-4"]`。）

### 4-6　順手小項

`services/context/telemetry.py` 補上 `Mapping` 的匯入（例如 `from typing import Mapping`），讓 `build_retrieval_trace` 的新舊註解都不是未定義名稱；**不得**因此改變任何行為。

## 5. 測試要求

1. **旗標關閉的黃金測試**：旗標關閉時 `chat()` 路徑**完全不呼叫**新的 repository 方法與 `_fetch_article_effective_inputs`（以假物件斷言呼叫次數為 0）；`build_retrieval_trace` 不帶新參數時輸出與修改前相同；`article_effective_marks` 不被呼叫。
2. **旗標開啟但不需要查詢**：`include_retrieval_trace=false`；或證據的文件狀態皆非 `has_pending` → 查詢次數為 0；trace 的 `semantic_marks` 仍可帶 S2 的 `document_effective_status`（不帶 `article_effective_status` 參數時不附加）。
3. **`article_effective_marks`**（表格驅動，用 §4-5 的案例與真實備註 fixture）：各狀態、`pending_whole`／`pending_partial` 分界、`locators`／`effective_from`、範圍展開、`known_articles` 的 `第 N 條`→`N` 轉換、`article_nos` 查無→`INDETERMINATE`、文件不在 `document_status`→`INDETERMINATE`、`in_force`／`no_information`／`undetermined` 直接沿用且**不呼叫解析**（可用猴子補丁計次）。
4. **`build_retrieval_trace` 新參數**：附加位置在 `document_effective_status` 之後、僅在 `include_semantic_marks=True` 且參數非 `None` 時、`pending_*` 才附加 `article_effective_from`／`article_pending_locators`、查無鍵＝`INDETERMINATE`、`source_doc_id=None` 的處理、既有鍵與順序不變。
5. **repository**（假 driver）：`keys` 為空不查詢；語句只讀且含 `kg_id`；多條號的 warning 與取最小；`list_article_nos` 不取內容；**不修改**既有方法。
6. **router 層**（沿用 `tests/routers/test_agent_effective_marks.py` 的手法）：旗標開啟＋`include_retrieval_trace=true`＋證據含 `has_pending` 文件 → SSE 的 `retrieval_trace` 帶 `article_effective_status`（用假 repo 回傳固定條號）；**失敗隔離**：假 repo 拋例外時，`sources` 事件仍完整輸出、`retrieval_trace` 不含 `article_effective_status`、`status: done` 事件照常出現、答案內容不變。
7. **既有測試不得修改**（只新增測試函式）；若既有測試失敗，表示旗標關閉路徑被改動，請修實作。

## 6. 結構守衛（寫成測試）

- `services/context/trace_marks.py`、`services/context/telemetry.py`、`services/effective_note.py` 原始碼不得含 `date.today`／`datetime.now`／`time.time`；`date.today` 仍**只**出現在 `routers/agent.py`；
- 上述 services 檔不得匯入 `neo4j`／`requests`／`httpx`／`os.environ`；`services.effective_note` 只能在函式內匯入；
- 不得修改 `vector_search_facts`、`services/svo_service.py`、`services/retrieval/`、`services/context/fact_lines.py`、`core/`；不得新增設定項；
- 新增的 repository 方法與任何新程式的 Cypher 不得含寫入關鍵字（`SET`／`CREATE`／`MERGE`／`DELETE`／`REMOVE`／`DETACH`／`CALL`）；
- 旗標關閉路徑新增的呼叫＝0（見 §5-1）。

## 7. 驗收（規劃對話自行驗證）

- **範圍**（`git diff --name-only 2f96ad1..HEAD` 僅允許）：`repositories/law_document_repo.py`、`services/context/trace_marks.py`、`services/context/telemetry.py`、`routers/agent.py`、新增的測試檔、報告 274、索引一行、`HANDOVER.md` 頂部條目。其他既有 production 檔、`core/`、既有腳本與測試、題庫與資料檔、規劃文件、論文、歷史報告原文零變動；`law_document_repo.py` 與 `trace_marks.py` 的既有函式／方法零改動。
- **我的驗收**：
  1. **差分測試**（修改前 `git show 2f96ad1:…` 對修改後）：旗標關閉與「不帶新參數」輸出 0 不一致；
  2. **KG#4 唯讀端到端核對（最重要）**：我用 `ReadOnlyRunner` 以 Codex 的**同一組 Cypher**（只讀）取得 KG#4 五份待施行文件的全部 Fact 對應條號與已知條號清單，餵進 `article_effective_marks`，核對**條文層狀態的 Fact 計數**——預期待施行（`pending_*`）共 **202 個 Fact、21 條條文**（健康保護規則 74／9、設施規則 105／7、教育訓練規則 19／3、容許暴露標準 2／1、營造標準 2／1），其餘全部 `in_force`；`pending_whole` 僅營造第 11-2 條（2 個 Fact）；勞動契約法 135 個 Fact 全為 `undetermined`；
  3. 讀碼：旗標關閉時零呼叫、失敗隔離、`date.today` 僅一處、Cypher 只讀；
  4. 全量 pytest ≥ 2241＋新增數、節點卡 0 警告、`.env` 敏感值外洩掃描 0 命中。

## 8. 停止條件（遇到即停止並回報）

1. 需要連 KG#4／`kg2-neo4j`／Neo4j／Ollama／docker／讀 `.env`；
2. 需要改檢索、排序、截斷、prompt、生成或 `core/config.py` 才能完成；
3. 旗標關閉時既有測試因你的改動失敗，且不是「測試鎖定了完整鍵集合」以外的原因；
4. 讀碼發現 `chat()` 的證據不一定帶 `source_svo_chunk_index`（影響對應鍵）——如實回報影響範圍，**不要自行改檢索讓它帶**；〔**已由規劃對話裁示澄清，見 §13**：型別允許 `None` 不構成停止條件〕
5. `chat()` 現有測試手法無法在不修改既有測試的前提下覆蓋失敗隔離（說明原因與最小可行測試方式，**不要放寬守衛**）；
6. 全量 pytest 出現非本任務造成的失敗。

## 9. 編號、約定與回報

**Codex 無法傳訊**：結果寫進**報告 274**（先 `ls docs/報告`）與 `HANDOVER.md` 頂部條目，由使用者貼回規劃對話；**不得自稱已驗證**。繁體中文；conventional commit（例 `feat(article-effective-marks): ...`）；**只 `git add` 自己的檔案**；commit 後 push 本分支（不動 master、不 force-push、不 merge）。

**最終回報格式（Codex 在對話最後輸出，供使用者貼回）**：`T0–T7｜結論｜commit SHA｜新增／修改的函式簽名｜旗標關閉零呼叫測試結果｜§4-5 條文層預期是否全數通過｜失敗隔離測試採用的手法｜新增測試數與全量 pytest 結果｜改動檔清單（逐檔一行）｜改過的既有測試（無則寫無）｜是否連過任何資料庫／Ollama／docker／.env（應為否）｜偏離報告273之處（無則寫無）`。

## 10. 不在本任務範圍

S3（prompt 附註與排除）、`vector_search_facts` 回傳條號、BFS 版本分離、對 KG#4 的任何寫入、`effective_note` 以外的施行日來源。

## 11. 交接指令（使用者貼給 Codex）

```text
你是 Codex，接手「世界知識圖譜 RAG」專案的任務（工作目錄：D:\Users\666\Desktop\world knowledge graph rag\.claude\worktrees\sdd-retrieval-comparison，分支 worktree-sdd-retrieval-comparison）。
請先 git pull，然後完整閱讀 docs/報告/273_下一階段任務規劃_尚未施行標示S2b條文層影子顯示_交Codex.md，並依 T0–T7 逐步執行。
硬規則（違反即停止回報）：
1. 全程離線：不得連 KG#4（埠 17990）、kg2-neo4j、任何 Neo4j 或 Ollama；不得操作 docker；不得讀取或印出 .env 與任何密碼。
2. 這是會改 production 的任務，但旗標（TRACE_SEMANTIC_MARKS）關閉時所有輸出必須與修改前逐位元相同，且不得多執行任何資料庫查詢；只允許修改 repositories/law_document_repo.py（僅新增方法）、services/context/trace_marks.py、services/context/telemetry.py、routers/agent.py 與新增測試；不得改 core/config.py、不得新增設定項、不得改檢索／排序／截斷／prompt／生成。
3. 不得修改既有測試（只能新增測試函式）；若既有測試因你的改動失敗，表示旗標關閉路徑被改動，請修實作。
4. date.today() 只允許出現在 routers/agent.py（沿用 S2 已有的 as_of）；其餘模組一律由呼叫端傳入。
5. 新增的資料庫查詢必須只讀、且包在 try/except 內做失敗隔離（失敗只記 warning，絕不影響回答與其他 SSE 事件）。
6. 遇到報告273 §8 的停止條件就立即停止，把現況與差異寫進報告 274 並回報。
7. 先跑基準 pytest（應為 2241 passed）再開工；結束時全量 pytest 不得有回歸；也要執行 python scripts/analysis/check_node_cards.py（0 警告）。
8. 只 git add 你自己新增或修改的檔案；commit 後 push 本分支；不得動 master、不得 force-push、不得 merge。
9. 你無法傳訊：結果寫進 docs/報告/274（先 ls docs/報告 確認編號）與 HANDOVER.md 頂部條目；不得自稱「已驗證」（驗證由規劃對話做）。
完成後，請在對話最後依報告273 §9 的「最終回報格式」輸出一段文字，供使用者貼回規劃對話。
```

## 12. 執行紀錄（僅規劃對話更新）

⚠️ **2026-10-04 Codex 第一次執行在 T0 後依 §8.4 停止**（[報告274](274_S2b條文層影子顯示停止紀錄_Codex.md)：`SVOTriple.source_svo_chunk_index` 型別為 `int | None`，一般 SVOGROUP chunk 恆為 `None`）。**停止是正確且保守的**（符合「不要自行放寬守衛」）；規劃對話裁示如 §13，任務書**其餘內容不變**，請 Codex 繼續 T1–T7。KG#4 仍無任何寫入核准。

## 13. 規劃對話裁示與澄清（2026-10-04；回應報告274）

1. **型別允許 `None` 不構成停止條件**。§4-2／§4-3 本來就規定：證據的 `source_doc_id` 或 `source_svo_chunk_index` 為 `None`、或對應表查無該鍵 → `article_effective_status＝semantic_marks.INDETERMINATE`；**不得猜測、不得改用其他欄位、不得改檢索補欄位**。§8.4 的原意只針對「缺值普遍到使 S2b 失去意義」的情況。
2. **真實資料的影響範圍（規劃對話對 KG#4 唯讀量測，〔事實〕）**：KG#4 全部 **16,826 個 Fact 的 `source_svo_chunk_index` 與 `source_doc_id` 皆非空（空值 0）**；全部 **16,826 筆邊引用（`citations_json`，三元組的來源）都帶 `source_svo_chunk_index`（空值 0）**；其中屬於 5 份待施行文件與勞動契約法的 **3,606 筆邊引用與 3,606 個 Fact 同樣空值 0**。〔推論，依 `SVOTriple` 欄位註解與資料形狀，未對其他 KG 實測〕`source_svo_chunk_index` 缺值只會出現在**非法規**（一般 SVOGROUP chunk）的 KG／文件，那些文件通常沒有 `Document` 節點或備註（文件層狀態為 `no_information` 或不在對照中），不會進入 `has_pending` 路徑；即使進入，也只會標 `INDETERMINATE`，不會誤標。
3. **需補的測試**（新增，不改規格）：①三元組證據 `source_svo_chunk_index=None`、②Fact 證據 `source_doc_id=None`、③`has_pending` 文件但對照表查無該鍵——三者 `article_effective_status` 皆為 `INDETERMINATE`，且不觸發任何資料庫查詢（缺鍵者不列入查詢鍵）。
4. **報告編號**：報告 274 已被停止紀錄使用；本次**實際執行紀錄請寫報告 275**（不要覆蓋 274）。最終回報格式沿用 §9，並多一項「缺值證據的測試結果」。
5. 其餘（T0–T7、§4 規格、§5 測試、§6 守衛、§7 驗收、§8 其餘停止條件）**不變**。

## 15. 驗證紀錄（規劃對話，2026-10-04）——✅ **S2b 已獨立驗證通過**

Codex 續行 commit `687de23`（執行紀錄見[報告275](275_S2b條文層影子顯示執行紀錄_Codex.md)；報告274 保留為第一次停止紀錄）。Codex 全程離線；**KG#4 端到端核對由規劃對話唯讀完成**；KG#4 仍無任何寫入核准。

1. **範圍**：`git diff --name-status b6c5060..HEAD` 僅 §7 允許的檔案——4 個 production 檔（`repositories/law_document_repo.py`、`services/context/trace_marks.py`、`services/context/telemetry.py`、`routers/agent.py`）、3 個**新增**測試檔、報告 275、索引、HANDOVER；**沒有修改任何既有測試**；`core/`、`services/svo_service.py`、`services/retrieval/`、`services/context/fact_lines.py`、`services/effective_note.py` 零變動（受保護路徑變動數 0）；repository 與 `trace_marks` 的既有函式／方法零改動（只新增）。
2. **讀碼**：兩個新 repository 方法的 Cypher 皆只讀、限定 `kg_id`、無寫入關鍵字；`keys` 空則不查詢；多條號取字面最小並 warning。`chat()` 的新增全部在 `if settings.trace_semantic_marks and payload.include_retrieval_trace:` 之內，且**僅當至少一筆證據屬 `has_pending` 文件才查詢**；整段包在 `try/except Exception`（只 `logger.warning`、不含敏感資料）；`article_effective_marks` 與規格 §4-2 逐項相符（`in_force`／`no_information`／`undetermined` 沿用文件層狀態不解析；`has_pending` 才解析並呼叫 `article_effective_status`；缺鍵／查無／文件不在對照＝`INDETERMINATE`）；`build_retrieval_trace` 新參數僅在 `include_semantic_marks=True` 且非 `None` 時於 `document_effective_status` 之後附加，`pending_*` 才附 `article_effective_from`／`article_pending_locators`。
3. **KG#4 唯讀端到端核對（最重要；以 Codex 的同一組 Cypher 逐字取得 5 份待施行文件＋勞動契約法全部 Fact 的條號與已知條號清單，餵進 `article_effective_marks`，as_of＝2026-10-03）**：684 個證據鍵全部對得到條號（0 個鍵對應多條號）；**待施行 Fact 共 202 個、21 條條文，與報告267 的 21 條集合逐條相同**；各文件：健康保護規則 74／9、設施規則 105／7、教育訓練規則 19／3、容許暴露標準 2／1、營造標準 2／1；`pending_whole` **僅營造第 11-2 條（2 個 Fact）**，其餘 200 個為 `pending_partial`；勞動契約法 135 個 Fact 全為 `undetermined`；其餘 3,269 個全為 `in_force`；抽樣：健康保護規則第 6 條＝`pending_partial`／2027-07-01／`第2～4項`、教育訓練規則第 3 條＝`pending_partial`／2027-01-01／`附表一`、設施規則第 185-2 條（範圍展開）＝`pending_partial`／2027-01-01、第 17 條＝2028-01-01、營造第 11-2 條＝`pending_whole`／2027-07-01。
4. **差分測試（我自寫；舊版 `git show b6c5060:services/context/telemetry.py` vs 新版）**：新參數省略時 `build_retrieval_trace` 在 4 種組合（`include_semantic_marks` 開／關 × `document_effective_status` 有／無）**0 不一致**；帶新參數時新鍵附加於既有鍵之後、既有鍵值不變、缺鍵＝`INDETERMINATE`、`pending_*` 的 `article_effective_from`／`article_pending_locators` 值正確；`include_semantic_marks=False` 時忽略新參數。（我的第一版檢查誤把既有的 `article_no` 標示鍵當成新鍵濾掉，是我的測試缺陷，已更正。）
5. **守衛**：`date.today` 在 `services/`／`routers/`／`core/`／`repositories/`／`models/` 內仍只出現在 `routers/agent.py:1460`；全量 pytest **2257 passed**（2241＋16）、節點卡 0 警告、`.env` 敏感值對 52 個檔 0 命中；`kg2-neo4j` StartedAt 仍為新基準。

**小項（不阻擋）**
- `services/context/telemetry.py` 以 `Mapping = __import__("typing", fromlist=["Mapping"]).Mapping` 取得型別：既有測試 `tests/services/test_context_telemetry.py` 有 AST 守衛限制該模組的匯入集合（不含 `typing`），Codex 為了「不修改既有測試」而以 `__import__` 繞過。功能無害，但這是**繞過守衛字面**的寫法。建議日後經你同意把該守衛的允許集合加入 `typing`（標準庫、無副作用），再把這行改成一般的 `from typing import Mapping`。
- 路由的 `as_of`（S2）無論旗標都會計算一次日期，無副作用。

**限制（沿用）**：沒有端到端跑 `chat()`（router 層由 Codex 以假 driver／repo 測試，包含失敗隔離，我讀碼確認）；`pending_partial` 的項／附表層級只標在條文層（200 個 Fact 中僅有部分真正落在待施行的項／附表）；`no_information` 的 48／64 份文件仍無從判斷；解析器僅 16 份備註驗證；S3 尚未做。

## 14. 續行指令（使用者貼給 Codex；取代 §11 供第二次執行使用）

```text
請接續「報告273 S2b 條文層影子顯示」任務（工作目錄與分支同前）。先 git pull，重新閱讀 docs/報告/273_下一階段任務規劃_尚未施行標示S2b條文層影子顯示_交Codex.md，特別是新增的 §13「規劃對話裁示與澄清」。
你上次依 §8.4 停止是正確且保守的；規劃對話已裁示：SVOTriple.source_svo_chunk_index 型別允許 None 不構成停止條件，缺值證據一律標 INDETERMINATE（不猜測、不改檢索、不查詢）；KG#4 實測 16,826 個 Fact 與 16,826 筆邊引用的 chunk index 空值皆為 0。
請從 T1 開始依 T1–T7 實作（T0 已完成可略過，但請重新 git pull 並確認基準 pytest 仍為 2241 passed）。硬規則不變：全程離線；旗標關閉時輸出逐位元相同且零新增資料庫查詢；只改 repositories/law_document_repo.py（僅新增方法）、services/context/trace_marks.py、services/context/telemetry.py、routers/agent.py 與新增測試；不改既有測試、不改檢索／排序／截斷／prompt／生成、不新增設定項；新增查詢只讀並以 try/except 做失敗隔離；只 git add 自己的檔案、push 本分支、不動 master。
本次執行紀錄請寫成「報告 275」（報告 274 已是停止紀錄，不要覆蓋），並更新 HANDOVER.md 頂部條目。完成後依報告273 §9 的最終回報格式輸出（多加一項：缺值證據的測試結果），供使用者貼回規劃對話。
```
