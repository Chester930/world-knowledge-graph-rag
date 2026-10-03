# 報告270：下一階段任務規劃——「尚未施行」標示 S2：文件層影子顯示（預設關閉、零行為變更）（交 Codex）；附：勞動契約法官方核對

> **日期**：2026-10-03
> **性質**：階段任務規劃。分工：**規劃對話（Claude）決定與獨立驗證、Codex 執行、規劃對話只記錄**。**本文件只由規劃對話修改（§12 執行紀錄）。**
> **依據**：[報告267](267_尚未施行條文標示_唯讀分析與設計.md) §5.2 S2；[報告268 §11](268_下一階段任務規劃_尚未施行標示S1純函式模組與題庫涉及度查證_交Codex.md)（S1 已驗證）；使用者「依照建議繼續」＝進行 S2 並由我核對勞動契約法現況。
> **基準**：HEAD ≥ `75613fd`；全量 pytest **2226 passed**。
> **本任務的性質**：**會修改 production 程式，但只在 `TRACE_SEMANTIC_MARKS` 旗標開啟時多輸出欄位；旗標關閉（預設）時所有輸出必須與修改前逐位元相同。不改檢索、排序、截斷、prompt、生成、評分；不寫入任何資料；不連線。**

---

## 1. 官方核對：勞動契約法現況（規劃對話已完成，〔事實〕）

**問題**：KG#4 的 `N0030010 勞動契約法`（43 條、135 個 Fact）備註只有「施行日期以命令定之。」——它是否真的尚未生效？

**核對**（2026-10-03，全國法規資料庫 `law.moj.gov.tw`，以 WebFetch 取得兩個頁面，內容一致）：
- 第 43 條條文：「本法施行日期以命令定之。」
- 頁面狀態標示：「※本法規部分或全部條文尚未生效，最後生效日期：未定」；附註：「本法尚未命令施行。」
- 頁面為民國 25 年 12 月 25 日公布之法規（僅在其中一個頁面可見公布日）。

**結論**：勞動契約法**經官方資料庫確認「尚未命令施行」**，KG#4 目前把它的 135 個 Fact 當成現行有效的法規提供檢索。（限制：WebFetch 以小模型摘要頁面，已用兩個頁面交叉確認並要求逐字引用；若需入論文引用，須人工開啟頁面確認。）**這支持報告267 的 `undetermined` 狀態設計。**〔附帶發現，〔推論〕〕MOJ 頁面另有統一的「部分或全部條文尚未生效，最後生效日期：…」標示，可能是比備註更直接的官方狀態來源，未來可評估由 collector 一併蒐集（不在本任務）。

## 2. 任務總覽

| 步驟 | 內容 | 產出 |
| --- | --- | --- |
| **R0** | 前置：`git fetch`／`git status`；HEAD ≥ `75613fd`；基準 `python -m pytest -q -p no:cacheprovider`（應 2226 passed）；`ls docs/報告`（Codex 報告自 **271** 起）；讀 §3 所列檔案與其既有測試 | 基準數字 |
| **R1** | `services/effective_note.py`：**僅新增**文件層摘要函式（§4-1） | 修改一檔 |
| **R2** | `services/context/telemetry.py`：`serialize_document`／`serialize_sources` 新增選用參數；`build_retrieval_trace` 新增選用參數（§4-2、§4-3） | 修改一檔 |
| **R3** | `services/context/trace_marks.py`：新增旗標組裝輔助函式（§4-4） | 修改一檔 |
| **R4** | `routers/agent.py`：`chat()` 在旗標開啟時傳入新參數（§4-5） | 修改一檔 |
| **R5** | 測試（§5）、結構守衛（§6） | 新增測試 |
| **R6** | 報告 271＋索引一行＋`HANDOVER.md` 頂部條目 | 文件 |
| **R7** | 全量 pytest、`scripts/analysis/check_node_cards.py`、commit | 回報 |

## 3. 必讀位置（〔事實〕，規劃對話已讀碼；請自行重新核對）

- `services/context/telemetry.py:13–21` `serialize_document(doc)`（回傳 `title`／`update_date`／`effective_date`／`effective_note`）；`:46–156` `build_retrieval_trace(...)`（fact／triple 的 `semantic_marks`；已有 `document_article_applicable` 選用參數）；`serialize_sources(... document_map ...)`（對 facts／triples 附 `document`）。模組開頭註明「無 I/O、只依賴 models 與 fact_lines」——新增對 `services.effective_note` 的匯入請**函式內延遲匯入**（比照 L1 對 `services.semantic_marks` 的做法），並更新模組開頭說明。
- `services/context/trace_marks.py:41–54` `semantic_marks_trace_kwargs(enabled, concept_scheme)`（旗標關閉＝`{}`）。
- `routers/agent.py:1436–1454`：`document_map = await _fetch_document_map(...)`，再 `_serialize_sources(..., retrieval_trace=_build_retrieval_trace(..., **semantic_marks_trace_kwargs(settings.trace_semantic_marks, ...)))`。
- `services/effective_note.py`（S1，229 行）：`parse_effective_note`、`pending_items`、`document_effective_status`、`STATUS_*` 常數。
- `services/semantic_marks.py`：`UNKNOWN`／`INDETERMINATE` 等標示常數。

## 4. 規格

### 4-1　R1：`services/effective_note.py` 新增文件層摘要（**僅新增，不得改動既有函式與常數**）

```python
@dataclass(frozen=True)
class DocumentEffectiveSummary:
    status: str                      # in_force | has_pending | no_information | undetermined（同 document_effective_status）
    pending_dates: tuple[str, ...]   # 待施行項目的施行日（ISO，去重、升冪）；無則為空
    # 不含條號清單：範圍展開需要文件的已知條號，文件層不具備，故不輸出（見報告270 §7）

def summarize_document_effective(note: str | None, as_of: str) -> DocumentEffectiveSummary
```

- 內部：`parsed = parse_effective_note(note, known_articles=())`；`status = document_effective_status(parsed, as_of)`；`pending_dates` 取 `pending_items(parsed, as_of)` 的 `effective_date`（日期不受範圍展開影響，故傳空 `known_articles` 即可）。`note` 為 `None`／空字串／無法解析 → `status="no_information"`、`pending_dates=()`。`as_of` 驗證沿用既有（`YYYY-MM-DD`，否則 `ValueError`）。**不得拋出其他例外**（解析失敗已由 `parse_effective_note` 吸收）。
- 純運算限制不變（不使用目前時間、不 I/O）。

### 4-2　R2：`serialize_document`

```python
def serialize_document(doc: LawDocument | None, *, effective_as_of: str | None = None) -> dict | None
```
- `effective_as_of is None`（預設）：輸出與修改前**逐位元相同**（四個鍵、順序不變）。
- 提供 `effective_as_of`：**附加於既有鍵之後**兩個鍵：`"effective_status"`（上列四種之一）、`"effective_pending_dates"`（`list[str]`）。`doc is None` 仍回傳 `None`。

`serialize_sources(..., effective_as_of: str | None = None)`：新增選用參數並傳給所有 `serialize_document` 呼叫；預設 `None` 時整體輸出與修改前相同。

### 4-3　R2：`build_retrieval_trace`

新增選用參數 `document_effective_status: Mapping[str, str] | None = None`（`source_doc_id` 字串 → 四種文件層狀態之一）。僅當 `include_semantic_marks=True` **且**該參數不是 `None` 時，fact 與 triple 的 `semantic_marks` **末尾**附加 `"document_effective_status"`：值＝該證據 `source_doc_id` 在對照表中的狀態；查無（或 `source_doc_id` 為 `None`）＝`semantic_marks.INDETERMINATE`。其他情況（旗標關閉、參數為 `None`）輸出與修改前**逐位元相同**；既有鍵與順序不變。

### 4-4　R3：`services/context/trace_marks.py`

新增 `effective_marks_kwargs(enabled: bool, as_of: str, document_map: Mapping[str, Any] | None) -> tuple[dict, dict]`：
- 回傳 `(sources_kwargs, trace_kwargs)`；`enabled=False` → `({}, {})`（**不匯入 `services.effective_note`**、不做任何運算）。
- `enabled=True`：`sources_kwargs={"effective_as_of": as_of}`；`trace_kwargs={"document_effective_status": {doc_id: summarize_document_effective(doc.effective_note, as_of).status for doc_id, doc in (document_map or {}).items()}}`（`document_map` 的值是 `LawDocument` 或 `None`，`None` 者略過）。

### 4-5　R4：`routers/agent.py`（**最小改動**）

在 `chat()` 計算 `document_map` 之後、呼叫 `_serialize_sources` 之前：`as_of` **只在此處**以 `date.today().isoformat()` 取得（`routers/` 是允許讀時鐘的層；純函式模組與 `telemetry` 仍禁止）；`sources_kw, trace_kw = effective_marks_kwargs(settings.trace_semantic_marks, as_of, document_map)`；把 `sources_kw` 以 `**` 傳給 `_serialize_sources`、`trace_kw` 與既有 `semantic_marks_trace_kwargs(...)` 一併 `**` 傳給 `_build_retrieval_trace`。**旗標關閉時兩者皆為 `{}`，行為與修改前完全相同**；**不得新增設定項**（沿用 `TRACE_SEMANTIC_MARKS`）、不得改檢索／排序／截斷／prompt／生成。

## 5. 測試要求

1. **旗標關閉的黃金測試**：以固定輸入呼叫修改前後都存在的簽名（`serialize_document(doc)`、`serialize_sources(...)` 不帶新參數、`build_retrieval_trace(...)` 不帶新參數，以及 `effective_marks_kwargs(False, ...)`），輸出與修改前完全相同（T0 先以現行程式碼產生並寫死於測試）。
2. **旗標開啟**：`serialize_document(doc, effective_as_of="2026-10-03")` 對 KG#4 的真實備註樣本（直接用 `tests/fixtures/kg4_effective_notes_20261003.json` 的 16 份）：5 份待施行文件→`has_pending`＋正確 `effective_pending_dates`（健康保護規則 `["2027-07-01","2028-01-01"]`、設施規則 `["2027-01-01"]`、教育訓練規則 `["2027-01-01"]`、容許暴露標準 `["2027-01-01"]`、營造標準 `["2027-07-01"]`）；勞動契約法→`undetermined`＋空日期；其餘 10 份→`in_force`；`effective_note=None`→`no_information`；`doc=None`→`None`；既有四鍵與順序不變。
3. **trace**：`build_retrieval_trace(..., include_semantic_marks=True, document_effective_status={...})` 對有／無對照的 `source_doc_id`、`source_doc_id=None` 各至少一例；`document_effective_status=None` 時不附加；`include_semantic_marks=False` 時即使提供參數也不附加；既有 `semantic_marks` 鍵與值不變。
4. **`summarize_document_effective`**：表格驅動（16 份備註、空／`None`／無法解析、`as_of` 邊界與推演〔2027-01-01 後設施規則變 `in_force`〕、`as_of` 格式錯誤→`ValueError`、日期去重升冪）。
5. **router 層**：沿用 `tests/routers/test_agent.py` 既有的 `chat()` 測試手法（先讀它如何假造 driver／provider／SSE），新增兩個測試：旗標關閉時 SSE `sources` 的 `document` 物件**沒有** `effective_status`；旗標開啟時有（`as_of` 以猴子補丁固定時鐘，**不得讓測試依賴真實日期**）。
6. **既有測試不得修改**。若既有測試因新鍵而失敗，表示旗標關閉路徑被改動了——修實作，不要改測試。

## 6. 結構守衛（寫成測試）

- `services/effective_note.py`、`services/context/telemetry.py`、`services/context/trace_marks.py` 的原始碼不得含 `date.today`／`datetime.now`／`time.time`；`date.today` **只允許**出現在 `routers/agent.py`；
- 上述三個 services 檔不得匯入 `neo4j`／`requests`／`httpx`／`os.environ`；`telemetry.py` 對 `services.effective_note` 只能在函式內匯入；
- 全 repo（排除 `tests/`、`docs/`、`.claude/`、`.git`、`scripts/`）對 `services.effective_note` 的匯入只允許出現在 `services/context/telemetry.py`、`services/context/trace_marks.py`（以及 `services/effective_note.py` 自己）；
- 不得新增 `core/config.py` 設定項；不得在 `services/svo_service.py`、`services/retrieval/`、`services/context/prompt*`、`services/context/fact_lines.py` 引用 `effective_note`；
- 不得有任何寫入 Neo4j 的新程式（`SET`／`CREATE`／`MERGE`／`DELETE`）。

## 7. 為什麼只做文件層（〔判讀〕，供 Codex 理解範圍）

Fact 目前不帶條號（`vector_search_facts` 不回傳 `article_no`），條文層標示需要改檢索查詢或多一次 `LawArticle` 查詢；且範圍展開（`185-1～185-4`）需要文件的已知條號。這些屬於 S2b，**本任務不做**。文件層標示（這份法規含尚未施行的條文／整部尚未施行）已足以讓人工審核與日後評測知道「這筆證據來自有待施行條文的法規」。

## 8. 驗收（規劃對話自行驗證）

- **範圍**（`git diff --name-only 75613fd..HEAD` 僅允許）：`services/effective_note.py`、`services/context/telemetry.py`、`services/context/trace_marks.py`、`routers/agent.py`、對應測試檔（新增與既有測試檔中的**新增**測試函式）、報告 271、索引一行、`HANDOVER.md` 頂部條目。其他既有 production 檔、`core/config.py`、既有腳本、題庫與資料檔、規劃文件、論文、歷史報告原文零變動。
- **我的驗收**：①差分測試（修改前 `git show 75613fd:...` 對修改後）：旗標關閉輸出 0 不一致、旗標開啟只多出約定的鍵；②**我用 KG#4 全部 64 份 `Document` 的真實 `effective_date`／`effective_note`（唯讀取得）呼叫 `serialize_document(effective_as_of="2026-10-03")`**：預期 `has_pending` 5、`undetermined` 1、`in_force` 10、`no_information` 48；③`git grep` 核對 §6 的匯入與時鐘限制；④讀碼確認 `routers/agent.py` 的改動最小且旗標關閉為 `{}`；⑤全量 pytest ≥ 2226＋新增數、節點卡 0 警告、`.env` 敏感值外洩掃描 0 命中。

## 9. 停止條件（遇到即停止並回報）

1. 需要連 KG#4／`kg2-neo4j`／Neo4j／Ollama／docker／讀 `.env`；
2. 旗標關閉時既有測試因你的改動而失敗，且原因不是「測試鎖定了完整鍵集合」以外的行為變更——停止回報；
3. 需要改 `core/config.py`、檢索／排序／截斷／prompt／生成相關檔案才能完成；
4. `chat()` 現有測試手法無法在不修改既有測試的前提下覆蓋 router 層（說明原因與最小可行測試方式，**不要自行放寬守衛**）；
5. 全量 pytest 出現非本任務造成的失敗。

## 10. 編號、約定與回報

**Codex 無法傳訊**：結果寫進**報告 271**（先 `ls docs/報告`）與 `HANDOVER.md` 頂部條目，由使用者貼回規劃對話；**不得自稱已驗證**。繁體中文；conventional commit（例 `feat(effective-marks): ...`、`test(...)`、`docs(報告271): ...`）；**只 `git add` 自己的檔案**；commit 後 push 本分支（不動 master、不 force-push、不 merge）。

**最終回報格式（Codex 在對話最後輸出，供使用者貼回）**：`R0–R7｜結論｜commit SHA｜新增／修改的函式簽名｜旗標關閉黃金測試結果｜旗標開啟對 16 份真實備註的結果摘要｜router 層測試採用的手法｜新增測試數與全量 pytest 結果｜改動檔清單（逐檔一行）｜改過的既有測試（無則寫無）｜是否連過任何資料庫／Ollama／docker／.env（應為否）｜偏離報告270之處（無則寫無）`。

## 11. 交接指令（使用者貼給 Codex）

```text
你是 Codex，接手「世界知識圖譜 RAG」專案的任務（工作目錄：D:\Users\666\Desktop\world knowledge graph rag\.claude\worktrees\sdd-retrieval-comparison，分支 worktree-sdd-retrieval-comparison）。
請先 git pull，然後完整閱讀 docs/報告/270_下一階段任務規劃_尚未施行標示S2文件層影子顯示_交Codex.md，並依 R0–R7 逐步執行。
硬規則（違反即停止回報）：
1. 全程離線：不得連 KG#4（埠 17990）、kg2-neo4j、任何 Neo4j 或 Ollama；不得操作 docker；不得讀取或印出 .env 與任何密碼。
2. 這是會改 production 的任務，但旗標（TRACE_SEMANTIC_MARKS）關閉時所有輸出必須與修改前逐位元相同；只允許修改 services/effective_note.py（僅新增）、services/context/telemetry.py、services/context/trace_marks.py、routers/agent.py 與新增測試；不得改 core/config.py、不得新增設定項、不得改檢索／排序／截斷／prompt／生成。
3. 不得修改既有測試（只能新增測試函式）；若既有測試因你的改動失敗，表示旗標關閉路徑被改動，請修實作。
4. date.today() 只允許出現在 routers/agent.py；其餘模組一律由呼叫端傳入 as_of。
5. 遇到報告270 §9 的停止條件就立即停止，把現況與差異寫進報告 271 並回報。
6. 先跑基準 pytest（應為 2226 passed）再開工；結束時全量 pytest 不得有回歸；也要執行 python scripts/analysis/check_node_cards.py（0 警告）。
7. 只 git add 你自己新增或修改的檔案；commit 後 push 本分支；不得動 master、不得 force-push、不得 merge。
8. 你無法傳訊：結果寫進 docs/報告/271（先 ls docs/報告 確認編號）與 HANDOVER.md 頂部條目；不得自稱「已驗證」（驗證由規劃對話做）。
完成後，請在對話最後依報告270 §10 的「最終回報格式」輸出一段文字，供使用者貼回規劃對話。
```

## 12. 執行紀錄（僅規劃對話更新）

⏳ 任務書已寫成；待使用者把 §11 的交接指令貼給 Codex。KG#4 仍無任何寫入核准。
