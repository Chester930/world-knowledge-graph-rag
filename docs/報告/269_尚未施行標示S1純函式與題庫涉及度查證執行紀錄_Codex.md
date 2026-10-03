# 報告269：尚未施行標示 S1 純函式與題庫涉及度查證執行紀錄（Codex）

> 日期：2026-10-03
> 本紀錄是 Codex 的離線執行結果；不取代規劃對話的獨立驗證。除本報告明列的測試結果外，不使用「已驗證」措辭。

## 1. 範圍與硬規則

依報告268 P0–P5 執行。全程未連 KG#4（17990）、`kg2-neo4j`、任何 Neo4j／Ollama，未操作 Docker，未讀取 `.env` 或密碼。未修改既有 production 檔、既有腳本與測試、題庫、既有資料檔、規劃文件、論文或歷史報告原文。

`git pull` 先執行，結果為 `Already up to date.`。工作樹分支為 `worktree-sdd-retrieval-comparison`，起始 HEAD 為 `681cda2`；報告目錄在寫入前已確認尚無 269。

## 2. P0 前置與基準

- 基準命令：`python -m pytest -q -p no:cacheprovider`
- 基準結果：`2200 passed, 8 warnings, 1 subtests passed in 47.28s`
- 讀取報告267、報告268、既有分析腳本與既有解析器測試；沒有修改分析腳本。
- 兩個凍結 42 題候選檔的 ID 數量與順序相同，均為 42 題；因此依報告268採用 `data/eval/baseline_runs/20260920_frozen/frozen_manifest.json`，並在輸出中記錄另一候選檔已比較。

## 3. P1：`services/effective_note.py`

新增 229 行的零接線純函式模組（符合 ≤300 行限制）。只使用標準庫；不讀寫檔案、不連線、不使用目前時間，`as_of` 由呼叫端傳入並驗證為有效 `YYYY-MM-DD`。

公開解析函式為：

`cn_to_int(text: str) -> int`、`roc_to_iso(text: str) -> str`、`normalize(note: str | None) -> str`、`art_key(article_no: str) -> tuple[int, int]`、`fmt_article(article_no: str) -> str`、`expand_articles(spec: str, known: Sequence[str]) -> list[str]`、`parse_provisions(text: str, known: Sequence[str]) -> list[dict[str, Any]]`、`parse_effective_note(note: str | None, known_articles: Sequence[str] = ()) -> dict[str, Any]`、`pending_items(parsed: Mapping[str, Any], as_of: str) -> list[dict[str, Any]]`、`consistency(parsed: Mapping[str, Any], effective_date: str | None) -> dict[str, Any]`、`article_effective_status(parsed: Mapping[str, Any], article_no: str, as_of: str) -> ArticleEffectiveStatus`、`document_effective_status(parsed: Mapping[str, Any], as_of: str) -> str`。

新增 `ArticleEffectiveStatus` 與五個狀態常數；非法日期備註回傳 `kind="unparsed"`、`errors`，沒有把例外外洩；其餘解析語意逐項照搬既有分析腳本。

## 4. P2：fixture 與測試

新增 `tests/fixtures/kg4_effective_notes_20261003.json`，包含分析 JSON 的 16 份真實備註原文、已知條號與期望值。fixture 期望涵蓋 5 份文件、21 條待施行條文；另含勞動契約法 `undetermined`。

新增 `tests/services/test_effective_note.py`，共 20 個測試案例（含參數化案例）：

- 16 份備註逐一與 `scripts.analysis.kg4_pending_effect_analysis` 比較 `parse_effective_note`、`pending_items`、`consistency`；結果 16／16 相等。
- 中文數字、民國日期、範圍端點、分階段「除…外」、刪除排除、施行日邊界與未來 `as_of` 推演。
- 五種條文狀態、四種條號寫法、最早日期、定位去重保序、非法日期與 `as_of` 錯誤。
- 標準庫／時鐘／檔案／連線字串與 production 零接線結構守衛。

## 5. P3：凍結題庫涉及度

新增 `scripts/analysis/frozen_bank_pending_overlap.py` 與輸出 `data/analysis/frozen_bank_pending_overlap_20261003.json`。腳本只比對 65 題的 `atomic_gold_facts` 之 `source_law`＋`source_article`；不代表檢索結果實際取到該條。

新增 `tests/scripts/test_frozen_bank_pending_overlap.py`，共 6 個測試案例，含條號正規化、完整 source 對應、合成命中／未命中、42 題篩選與真實檔案冒煙測試。

### 5.1 輸出摘要

| 題目集合 | 命中待施行條文 | 命中題號 | 命中勞動契約法 | 同屬 5 份文件但不在待施行條文 |
|---|---:|---|---:|---:|
| 凍結 42 題 | 1 | `57-CANARY3` | 0 | 2（`57-AGGR1`、`57-AGGR2`） |
| 全部 65 題 | 1 | `57-CANARY3` | 0 | 2（`57-AGGR1`、`57-AGGR2`） |

`57-CANARY3` 命中 `N0060022_勞工健康保護規則` 第 2 條附表，施行日 `2028-01-01`。本次資料中沒有 gold fact 落在 `N0030010_勞動契約法`。

凍結 42 題權威檔：`data/eval/baseline_runs/20260920_frozen/frozen_manifest.json`；比較檔：`data/analysis/source_ambiguity/questions_frozen42.json`。兩者 ID 與順序一致。

## 6. P4：報告與交接文件

本報告、`docs/報告/00_報告索引.md` 的 269 一行、以及 `HANDOVER.md` 頂部條目均已新增。沒有修改報告268或其他規劃／歷史文件。

## 7. P5：執行檢查

- 新增測試：`26 passed`（20＋6）。
- `python scripts/analysis/check_node_cards.py`：掃描 3 張節點卡，`0` 警告。
- 全量命令：`python -m pytest -q -p no:cacheprovider`。
- 全量結果：`2226 passed, 8 warnings, 1 subtests passed in 46.59s`；相對基準增加 26 個測試，無回歸。
- commit／push 結果於提交後由本報告與 HANDOVER 補入。

## 8. 限制與偏離

- 解析器仍只在 16 份備註上做等價測試；48／64 份沒有備註不等於已施行。
- 項／附表施行資訊仍只能標在條文層；題庫涉及度只看 gold fact 的法規與條號，不是檢索命中率。
- 沒有執行 S2／S3，沒有把新模組接入任何 production 路徑，也沒有將分析腳本改為匯入新模組。
- 截至本節記錄，沒有遇到報告268 §7 停止條件；偏離報告268之處：無。
