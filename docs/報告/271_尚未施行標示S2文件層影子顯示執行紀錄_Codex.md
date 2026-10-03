# 報告271：尚未施行標示 S2 文件層影子顯示執行紀錄（Codex）

> 本文件是報告270 R0–R7 的 Codex 執行紀錄，供規劃對話獨立驗收；不取代規劃對話的驗證。

## 1. 範圍與硬規則

目前分支為 `worktree-sdd-retrieval-comparison`，工作樹位於
`.claude/worktrees/sdd-retrieval-comparison`。本次僅實作文件層影子顯示：

- `TRACE_SEMANTIC_MARKS` 開啟時，`sources.document` 附加 `effective_status` 與 `effective_pending_dates`。
- 同一旗標開啟時，retrieval trace 的 fact／triple `semantic_marks` 附加 `document_effective_status`。
- 旗標關閉時維持既有輸出；沒有改檢索、排序、截斷、prompt、生成或設定項。
- `services/effective_note.py`、`services/context/telemetry.py`、`services/context/trace_marks.py` 不讀時鐘；`date.today()` 只在 `routers/agent.py`，由 router 傳入 `as_of`。

全程離線，未連 KG#4（17990）、`kg2-neo4j`、任何 Neo4j／Ollama，未操作 Docker，未讀取或輸出 `.env`／密碼。

## 2. R0 前置與基準

- 已在正確分支執行 `git pull`：`Already up to date`。
- 基準命令：`python -m pytest -q -p no:cacheprovider`。
- 基準結果：`2226 passed, 8 warnings, 1 subtests passed`。
- `docs/報告` 已先列出；本次報告編號為 271，提交前不存在同名報告。

## 3. R1–R4 實作

### R1：文件層純函式

新增：

```python
@dataclass(frozen=True)
class DocumentEffectiveSummary:
    status: str
    pending_dates: tuple[str, ...]

def summarize_document_effective(note: str | None, as_of: str) -> DocumentEffectiveSummary
```

實作沿用 `parse_effective_note(note, known_articles=())`、`document_effective_status` 與
`pending_items`；待施行日期去重、排序後回傳 tuple。沒有目前時間、I/O 或接線。

### R2：來源與 trace

新增／修改簽名：

```python
def serialize_document(
    doc: LawDocument | None, *, effective_as_of: str | None = None
) -> dict | None

def serialize_sources(
    triples: list[SVOTriple], fact_results: list[dict], resolved_rel_type: str | None,
    document_map: dict[str, LawDocument] | None = None,
    retrieval_telemetry: dict | None = None,
    retrieval_trace: dict | None = None,
    effective_as_of: str | None = None,
) -> dict

def build_retrieval_trace(
    triples: list[SVOTriple], fact_results: list[dict], prompt_lines: list[str] | None,
    include_semantic_marks: bool = False, concept_scheme: str = "A",
    type_lookups: tuple[dict[str, str], dict[str, str]] | None = None,
    document_article_applicable: dict[str, bool] | None = None,
    document_effective_status: Mapping[str, str] | None = None,
) -> dict
```

預設 `effective_as_of=None`／`document_effective_status=None` 時維持既有結構；開啟時新增鍵都放在既有鍵之後。`telemetry.py` 對 `effective_note` 使用函式內延遲匯入。

### R3：旗標參數組裝

新增：

```python
def effective_marks_kwargs(
    enabled: bool, as_of: str, document_map: Mapping[str, Any] | None
) -> tuple[dict, dict]
```

關閉時直接回傳 `({}, {})`，不匯入摘要模組、不計算；開啟時分別回傳
`effective_as_of` 與文件狀態對照表，`None` 文件略過。

### R4：router

`chat()` 在 `_fetch_document_map(...)` 後只於 router 取得
`date.today().isoformat()`，再將來源參數與 trace 參數傳入既有序列化呼叫。沒有新增設定項。

## 4. R5 測試與離線結果

新增 15 個 pytest case（含參數化展開）：

- `tests/services/test_effective_note_s2.py`：16 份 fixture、空／None／無法解析、日期邊界、日期去重與格式錯誤、來源鍵順序。
- `tests/services/test_context_effective_marks.py`：來源／trace 開關、未知 source、延遲匯入與結構守衛。
- `tests/routers/test_agent_effective_marks.py`：router fake driver／provider／repo、固定日期、SSE drain 與 `sources` JSON 解析；同一測試以旗標關閉／開啟各跑一次。

旗標開啟對 S1 保存的 16 份備註 fixture 的結果：

| 類別 | 文件數 | `effective_pending_dates` |
|---|---:|---|
| `has_pending` | 5 | 健康保護規則：`2027-07-01`, `2028-01-01`；設施規則：`2027-01-01`；教育訓練規則：`2027-01-01`；容許暴露標準：`2027-01-01`；營造標準：`2027-07-01` |
| `undetermined` | 1 | 勞動契約法：空 tuple／序列化後空 list |
| `in_force` | 10 | 空 tuple／序列化後空 list |

另以測試確認 `None`／空字串／無法解析備註得到 `no_information`，不將沒有備註誤判為 `in_force`。

本次沒有連 KG#4，因此沒有讀取報告270 §8 所述的 64 份 `Document`；64 份的獨立驗收仍由規劃對話依其流程進行。

本次新增測試與受影響既有測試合計：`184 passed`。全量測試：
`2241 passed, 8 warnings, 1 subtests passed`；相對基準增加 15 個新增 case，未見既有測試回歸。

節點卡檢查：

```text
[check_node_cards] 掃描 3 張節點卡，0 則警告
```

## 5. R6 文件與 R7 收尾

已新增本報告、報告索引一行與 `HANDOVER.md` 頂部條目。既有測試檔沒有修改，沒有修改既有腳本、題庫、資料檔、規劃文件、論文或歷史報告原文。

提交訊息：`feat(effective-marks): add document-level shadow status`。實際 SHA 以本分支最後的
`git log -1 --format=%H` 與本次對話最終回報為準；不在提交內容中嵌入自引用 SHA。規劃對話需以 commit、差分與其獨立測試結果為準。

## 6. 變更檔案

```text
services/effective_note.py
services/context/telemetry.py
services/context/trace_marks.py
routers/agent.py
tests/services/test_effective_note_s2.py
tests/services/test_context_effective_marks.py
tests/routers/test_agent_effective_marks.py
docs/報告/271_尚未施行標示S2文件層影子顯示執行紀錄_Codex.md
docs/報告/00_報告索引.md
HANDOVER.md
```

沒有改過既有測試。

## 7. 偏離與停止條件

- 報告270 §9 停止條件：本次未遇到。
- 偏離報告270：無；但依硬規則未執行 KG#4 的 64 份唯讀資料取得，僅執行已保存的 16 份離線 fixture 測試。
