# 報告268：下一階段任務規劃——「尚未施行」標示 S1：`services/effective_note.py`（零接線）＋凍結題庫涉及度查證（交 Codex）

> **日期**：2026-10-03
> **性質**：階段任務規劃。分工：**規劃對話（Claude）決定與獨立驗證、Codex 執行、規劃對話只記錄**。**本文件只由規劃對話修改（§11 執行紀錄）。**
> **依據**：[報告267](267_尚未施行條文標示_唯讀分析與設計.md)（唯讀分析與設計；§5.2 的 **S1**）；使用者指示「轉交給 Codex 執行」（採納報告267 §7 對 S1 的建議）。
> **基準**：HEAD ≥ `a79dd4b`；全量 pytest **2200 passed**；`kg2-neo4j` 基準 StartedAt＝`2026-10-02T11:09:32.79429649Z`（**本任務完全不連線，不需要此基準**）。
> **本任務的性質**：**純離線程式與查證**。把報告267 已驗證的解析邏輯整理成**零接線的 production 純函式模組**，並對凍結題庫做一次離線涉及度查證。**不得連 KG#4（17990）、`kg2-neo4j`、任何 Neo4j／Ollama、不得操作 docker、不得讀取 `.env`、不得改任何既有 production 檔。**

---

## 1. 背景（規劃對話已查證，〔事實〕；Codex 請自行重新核對讀碼部分）

- KG#4 的 `Document.effective_note` 以民國日期與條號清單記載「哪些條文何時施行」；`Document.effective_date` 只是其中**最晚**的施行日。報告267 的腳本 `scripts/analysis/kg4_pending_effect_analysis.py` 已把 16 份真實備註解析成逐條施行日，**16／16 通過「解析最晚日期＝`effective_date`」的交叉驗證**，結果：**21 條條文／202 個 Fact 尚未施行**（as_of＝2026-10-03），另有 1 部「施行日期以命令定之」的法規（勞動契約法）。
- 報告267 §5 建議：**不寫入 KG#4**，改為讀取時由純函式從 `effective_note` 推導狀態；落地分 S1（純函式，零接線）→ S2（影子顯示）→ S3（行為變更）。**本任務只做 S1 與一項免費查證；S2／S3 不在範圍。**
- 分析腳本是「分析用」，本任務要把核心解析邏輯**搬成可被 production 日後匯入的獨立模組**（同 G3 `services/fact_flat_resync.py` 的慣例：新增模組、零接線、附測試）。

## 2. 任務總覽

| 步驟 | 內容 | 產出 |
| --- | --- | --- |
| **P0** | 前置：`git fetch`／`git status`／確認 HEAD ≥ `a79dd4b`；基準 `python -m pytest -q -p no:cacheprovider`（應 2200 passed）；`ls docs/報告`（Codex 報告自 **269** 起）；讀 §1 所列檔案與既有測試 | 基準數字 |
| **P1** | 新模組 `services/effective_note.py`（§3） | 新檔 |
| **P2** | 單元測試 `tests/services/test_effective_note.py`＋fixture（§4） | 新檔 |
| **P3** | 凍結題庫涉及度查證腳本與輸出（§5） | 新檔＋JSON |
| **P4** | 報告 269＋索引一行＋`HANDOVER.md` 頂部條目（§8） | 文件 |
| **P5** | 全量 pytest、`scripts/analysis/check_node_cards.py`、commit（§9） | 回報 |

## 3. P1 規格：`services/effective_note.py`

**來源**：把 `scripts/analysis/kg4_pending_effect_analysis.py` 的純解析函式（`cn_to_int`、`roc_to_iso`、`normalize`、`art_key`、`fmt_article`、`expand_articles`、`parse_provisions`、`parse_effective_note`、`pending_items`、`consistency`）**搬成獨立模組**；**不得修改該腳本**（它保持獨立，供對照）。

1. **純運算**：只用標準庫（`re`、`datetime.date`、`dataclasses`、`typing`）；**不讀寫檔、不連線、不使用目前時間**（`as_of` 一律由呼叫端傳入，**禁止** `date.today()`／`datetime.now()`）；不改 `os.environ`；模組 ≤ 300 行（含 docstring）。
2. **行為相容**：對報告267 的 16 份真實備註，`parse_effective_note`／`pending_items`／`consistency` 的輸出必須與分析腳本**逐項相同**（見 §4-3 的等價測試）。語意不得「改良」；發現缺陷（例如對某備註解析錯誤）**停止並回報**，不要自行改語意。
3. **只做兩項允許的強化**（皆須有測試）：
   - **錯誤不外洩**：備註內出現無法換算的日期（例如月份 13、中文數字非法）時，`parse_effective_note` **不得拋例外**，回傳 `kind="unparsed"`、`items=[]`、並多一個 `errors: list[str]`；`roc_to_iso`／`cn_to_int` 本身仍可拋 `ValueError`（供呼叫端單獨使用）。
   - **`as_of` 驗證**：所有接受 `as_of` 的新函式，`as_of` 必須是 `YYYY-MM-DD` 字串，否則 `ValueError`。
4. **新增狀態推導 API**（本任務唯一的新語意，規格如下；**請照字面實作，不要自行擴充**）：

```python
STATUS_IN_FORCE = "in_force"            # 備註可解析、有施行資訊，且該條沒有待施行項目
STATUS_NO_INFORMATION = "no_information" # 備註為空或無法解析（≠ 已施行）
STATUS_PENDING_WHOLE = "pending_whole"   # 該條所有待施行項目都是「增訂」且無項／附表定位（整條尚未施行）
STATUS_PENDING_PARTIAL = "pending_partial" # 該條有待施行項目，但不屬 pending_whole（修正條文，或僅部分項／附表待施行）
STATUS_UNDETERMINED = "undetermined"     # 備註為「施行日期以命令定之」（整部法規施行日未定）

@dataclass(frozen=True)
class ArticleEffectiveStatus:
    status: str
    effective_from: str | None   # 該條待施行項目的最早施行日（ISO）；無待施行項目為 None
    locators: tuple[str, ...]    # 待施行項目的項／附表定位（去重、保持首見順序）；整條為空
    ops: tuple[str, ...]         # 待施行項目的操作別（增訂／修正，去重、保持首見順序）

def article_effective_status(parsed: Mapping[str, Any], article_no: str, as_of: str) -> ArticleEffectiveStatus
def document_effective_status(parsed: Mapping[str, Any], as_of: str) -> str   # 回傳上列五個常數之一或 "has_pending"（文件內至少一條待施行）
```

   判定規則（依序）：①`parsed["kind"]=="undetermined"` → 所有條文 `undetermined`（`effective_from=None`）；②`kind` 為 `empty`／`unparsed` → `no_information`；③對 `article_no`（接受 `"57"`、`"185-1"`、`"第 57 條"`、`"第 185-1 條"` 四種寫法，內部正規化為不含「第」「條」「空白」）取 `pending_items(parsed, as_of)` 中屬該條者：無 → `in_force`；全部為（`op=="增訂"` 且 `scope=="article"`）→ `pending_whole`；其餘 → `pending_partial`；④`effective_from`＝這些項目 `effective_date` 的最小值。`document_effective_status`：`undetermined`／`no_information` 同上；否則文件內有任何待施行項目 → `"has_pending"`，沒有 → `in_force`。
5. **Docstring 與命名**：繁體中文 docstring，模組開頭註明「報告267／268；PROVISIONAL；零接線；不連線；`as_of` 由呼叫端傳入」。
6. **零接線**：除 `tests/` 與（若你想）`scripts/analysis/`（**不得改既有腳本**）外，不得被 `main.py`、`routers/`、`core/`、`services/` 其他模組、`repositories/`、`models/` 匯入。

## 4. P2 規格：測試

1. **fixture**：`tests/fixtures/kg4_effective_notes_20261003.json`（新增）——16 份真實備註（`source`、`effective_date`、`note`、以及需要範圍展開者的已知條號清單 `known_articles`；備註全文取自 `data/analysis/kg4_pending_effect_20261003.json` 各文件的 `note` 欄位，**原文照抄**，不得改寫）。設施規則的 `known_articles` 至少含 `["21-3","57","116","185","185-1","185-2","185-3","185-4"]`；健康保護規則為 `"1"`–`"29"`。
2. **逐文件期望**（寫進 fixture 的 `expected`，數字取自報告267 §3）：各文件 `kind`、`max_date`、以及 `as_of=2026-10-03` 的待施行條文集合（條號、`scope`、`effective_date`）；共 **5 份文件、21 條條文**，合計與報告267 §3 表格一致；勞動契約法 `kind="undetermined"`；其餘 10 份待施行為空。
3. **等價測試**：對 fixture 中每份備註，同時呼叫新模組與 `scripts.analysis.kg4_pending_effect_analysis` 的同名函式，斷言 `parse_effective_note`、`pending_items`、`consistency` 輸出**完全相等**。
4. **其餘測試**（表格驅動）：中文數字與民國日期（`一百十六`→116、`一百零四`、`一百十`、`三十`、`十二`；`一百十七年一月一日`→`2028-01-01`）；範圍展開（`185-1～185-4`、`43～46`、`11～12-7` 以已知條號清單展開、端點不在清單仍保留）；分階段「除…外」；`as_of` 邊界（`as_of==effective_date` 時**不算待施行**，因 `effective_date > as_of` 才待施行；`as_of` 為施行日前一天算待施行）；`as_of` 推演（2027-01-01 後設施規則全數 `in_force`、營造第 11-2 條到 2027-07-01 前仍 `pending_whole`、2027-07-01 起 `in_force`）；刪除不計入待施行；非法日期（月份 13）→ `unparsed`＋`errors`、不拋例外；`as_of` 格式錯誤 → `ValueError`；§3-4 的五種狀態各至少 2 個案例（含 `article_no` 四種寫法等價、`pending_whole` 與 `pending_partial` 的分界〔增訂整條 vs 修正條文 vs 增訂但有項／附表定位〕、`effective_from` 取最小日期、`locators` 去重保序、`undetermined` 套用到所有條文、`no_information`≠`in_force`）。
5. **結構守衛測試**：①模組原始碼不含 `date.today`／`datetime.now`／`time.time`／`open(`／`os.environ`／`neo4j`／`requests`／`httpx`；②用 `ast` 確認只匯入標準庫；③全 repo（排除 `tests/`、`docs/`、`.claude/`、`.git`、`scripts/`）無任何檔案引用 `effective_note` 模組（零接線）。
6. 既有測試**不得修改**。

## 5. P3 規格：凍結題庫涉及度查證（離線）

**問題**：報告267 的 21 條待施行條文與勞動契約法，是否影響凍結評測的題目？（作為 S3 行為變更前的免費前置查證。）

1. 腳本 `scripts/analysis/frozen_bank_pending_overlap.py`（新增，**純離線**）：輸入①`data/eval/test_cases.json`（65 題；每題 `atomic_gold_facts[]` 有 `source_law`（如 `N0030006_勞工請假規則`）與 `source_article`（如 `第2條`）；另有題目層 `pcode`／`source_article`）；②`data/analysis/kg4_pending_effect_20261003.json`（`documents[].source`、`pending_articles[].article_no`、`kind`）；③凍結評測的 42 題清單（`data/eval/baseline_runs/20260920_frozen/frozen_manifest.json` 或 `data/analysis/source_ambiguity/questions_frozen42.json`；**先讀這兩個檔確認哪個才是凍結 42 題的權威清單並在報告中說明**）。
2. 條號正規化：`第2條`／`第 2 條`／`第21-3條` 一律轉成不含「第」「條」「空白」的形式再比對。`source_law` 以資料夾名稱（`<pcode>_<名稱>`）對應 `documents[].source`。
3. 輸出 `data/analysis/frozen_bank_pending_overlap_20261003.json`，至少含：
   - 對**凍結 42 題**與**全部 65 題**各自：①有任何 gold fact 落在「待施行條文」的題目清單（題號、命中的條文、`scope`、施行日）；②有任何 gold fact 落在「勞動契約法」的題目清單；③gold fact 屬於「5 份待施行文件」但**不在**待施行條文內的題目數（僅供對照，表示同文件但現行有效）；④總數；
   - 每個命中的 gold fact：`exact_span`（原文，法規文字）、`source_law`、`source_article`；
   - 方法說明（正規化規則、清單來源、as_of）。
4. 單元測試（`tests/scripts/test_frozen_bank_pending_overlap.py`）：條號正規化、`source_law`↔`source` 對應、命中與未命中的合成案例、凍結清單篩選、輸出結構；**不依賴真實 repo 檔案內容的測試用合成資料**，另加一個對真實檔案實跑的冒煙測試（只驗證不拋例外與輸出結構，不鎖定數字）。
5. **不得**修改題庫與任何既有資料檔。

## 6. 範圍、限制與驗收（規劃對話自行驗證）

- **範圍**（`git diff --name-only a79dd4b..HEAD` 僅允許）：`services/effective_note.py`、`tests/services/test_effective_note.py`、`tests/fixtures/kg4_effective_notes_20261003.json`、`scripts/analysis/frozen_bank_pending_overlap.py`、`tests/scripts/test_frozen_bank_pending_overlap.py`、`data/analysis/frozen_bank_pending_overlap_20261003.json`、報告 269、`docs/報告/00_報告索引.md`（一行）、`HANDOVER.md`（頂部條目）。**既有 production 檔、既有腳本與測試、題庫與既有資料檔、規劃文件（含本報告）、論文、歷史報告原文零變動。**
- **我的驗收**：①`git grep` 確認零接線；②**我自己用不同方法重算**：對 16 份備註獨立呼叫新模組與分析腳本，核對 21 條待施行集合與各文件 `kind`／`max_date`；③自行對 §3-4 的狀態規則做隨機（含邊界）等價測試；④自行重算題庫涉及度（讀 `test_cases.json` 與凍結清單）並逐題對照你的 JSON；⑤全量 pytest ≥ 2200＋新增數、節點卡 0 警告、`.env` 敏感值外洩掃描 0 命中；⑥讀碼檢查 §3-1 的純運算限制。
- **資料限制要寫進報告**：解析器只在 16 份備註驗證；48／64 份文件無備註（`no_information`≠`in_force`）；項／附表層級只能標在條文層；題庫涉及度只比對 gold fact 的 `source_law`＋`source_article`，**不代表檢索結果是否實際取到該條**。

## 7. 停止條件（遇到即停止並回報）

1. 需要連 KG#4／`kg2-neo4j`／Neo4j／Ollama／docker／讀 `.env`，或需要修改任何既有 production 檔或既有腳本才能完成；
2. 新模組與分析腳本在 16 份備註上輸出不相等，且原因不是 §3-3 允許的兩項強化；
3. 解析規則遇到 §4-2 期望值以外的結果（例如 21 條對不起來）——如實回報差異，**不要調整期望去符合**；
4. 凍結 42 題的權威清單無法確定（兩個候選檔不一致）——回報兩者差異；
5. 全量 pytest 出現非本任務造成的失敗。

## 8. 編號、約定與回報

**Codex 無法傳訊**：結果寫進**報告 269**（先 `ls docs/報告`）與 `HANDOVER.md` 頂部條目，由使用者貼回規劃對話；**不得自稱已驗證**。繁體中文；conventional commit（例 `feat(effective-note): ...`、`test(...)`、`docs(報告269): ...`）；**只 `git add` 自己的檔案**；commit 後 push 本分支（**不動 master、不 force-push、不 merge**）。同一時間只能一個執行者。

**最終回報格式（Codex 在對話最後輸出，供使用者貼回）**：`P0–P5｜結論｜commit SHA｜新模組行數與公開函式簽名｜與分析腳本在 16 份備註上的等價測試結果｜21 條待施行集合是否與報告267 一致｜新增測試數與全量 pytest 結果｜題庫涉及度摘要（凍結 42 題／全部 65 題：命中待施行條文的題數與題號、命中勞動契約法的題數、凍結清單採用哪個檔）｜是否連過任何資料庫／Ollama／docker／.env（應為否）｜偏離報告268之處（無則寫無）`。

## 9. 不在本任務範圍

S2（`sources`／trace 影子顯示）、S3（prompt 附註與排除）、對 KG#4 的任何寫入、勞動契約法現況的官方查證、`effective_note` 以外的施行日來源、把分析腳本改為匯入新模組。

## 10. 交接指令（使用者貼給 Codex）

```text
你是 Codex，接手「世界知識圖譜 RAG」專案的任務（工作目錄：D:\Users\666\Desktop\world knowledge graph rag\.claude\worktrees\sdd-retrieval-comparison，分支 worktree-sdd-retrieval-comparison）。
請先 git pull，然後完整閱讀 docs/報告/268_下一階段任務規劃_尚未施行標示S1純函式模組與題庫涉及度查證_交Codex.md，並依 P0–P5 逐步執行。
硬規則（違反即停止回報）：
1. 全程離線：不得連 KG#4（埠 17990）、kg2-neo4j、任何 Neo4j 或 Ollama；不得操作 docker；不得讀取或印出 .env 與任何密碼。
2. 不得修改任何既有 production 檔、既有腳本與其測試、題庫與既有資料檔、規劃文件、論文、歷史報告原文；只新增報告268 §6 列出的檔案。
3. 新模組 services/effective_note.py 必須零接線（只有測試可以匯入）、純運算、不使用目前時間（as_of 一律由呼叫端傳入）。
4. 遇到報告268 §7 的停止條件就立即停止，把現況與差異寫進報告 269 並回報，不要自行改語意或調整期望去符合結果。
5. 先跑基準 pytest（應為 2200 passed）再開工；結束時全量 pytest 不得有回歸；也要執行 python scripts/analysis/check_node_cards.py（0 警告）。
6. 只 git add 你自己新增的檔案；commit 後 push 本分支；不得動 master、不得 force-push、不得 merge。
7. 你無法傳訊：結果寫進 docs/報告/269（先 ls docs/報告 確認編號）與 HANDOVER.md 頂部條目；不得自稱「已驗證」（驗證由規劃對話做）。
完成後，請在對話最後依報告268 §8 的「最終回報格式」輸出一段文字，供使用者貼回規劃對話。
```

## 11. 執行紀錄（僅規劃對話更新）

✅ **S1 已於 2026-10-03 由規劃對話獨立驗證通過**（Codex commit `06d710e`＋`03f8bd0`；執行紀錄見[報告269](269_尚未施行標示S1純函式與題庫涉及度查證執行紀錄_Codex.md)）。**本任務全程離線；KG#4 仍無任何寫入核准。**

**規劃對話驗證摘要**
1. **範圍**：`git diff --name-status 681cda2..HEAD` 僅 §6 允許的 9 個檔案（新模組 `services/effective_note.py` 229 行、2 個測試檔、1 個 fixture、題庫涉及度腳本與輸出 JSON、報告 269、索引一行、HANDOVER 頂部條目）；既有 production、既有腳本與測試、題庫與既有資料檔、規劃文件、論文、歷史報告零變動。
2. **純運算與零接線（我自己 grep）**：模組只匯入 `re`／`dataclasses`／`datetime.date`／`typing`；不含 `today()`／`now()`／`time.time`／`open(`／`os.environ`／`neo4j`／`requests`／`httpx`；`services/`／`routers/`／`core/`／`repositories/`／`models/`／`main.py` 內**沒有任何檔案匯入它**（`effective_note` 字樣在 production 出現的是既有的 `Document.effective_note` 欄位名稱，非本模組），只有測試匯入。
3. **獨立等價與規則驗證（我的腳本，不用 Codex 的 fixture）**：用我先前自 KG#4 唯讀取出的 16 份真實備註，新模組與報告267 分析腳本 `parse_effective_note` 輸出 **16／16 完全相等**、`pending_items` 相同；as_of＝2026-10-03 的待施行集合＝**21 條、與報告267 JSON 逐項一致**；以我**依規格字面自寫的參考實作**對狀態規則做 **20,000 組隨機等價**（含 `undetermined`／`empty`／`unparsed`、增訂／修正／刪除、三種 scope、`article_no` 三種寫法、`as_of` 邊界）→ `article_effective_status` 與 `document_effective_status` **0 不一致**；非法日期（月份 13）→ `unparsed`＋`errors`、不拋例外；`as_of` 格式錯誤（`2026/10/03`、`20261003`、空字串、`None`）→ `ValueError`；邊界：`as_of＝2027-06-30` 時營造第 11-2 條為 `pending_whole`、`as_of＝2027-07-01` 起 `in_force`（與規格「`effective_date > as_of` 才待施行」一致）。
4. **題庫涉及度（獨立重算）**：兩個凍結清單候選檔（`frozen_manifest.json` 的 `eligible_ids` 與 `questions_frozen42.json`）**內容完全相同（42 題）**；以正確的條號擷取重算，**與 Codex 的 JSON 逐項相同**：凍結 42 題與全部 65 題都只有 **1 題**的 gold fact 落在待施行條文——`57-CANARY3` 的 `N0060022 勞工健康保護規則 第2條第1款`（該條**只有附表一**待施行，2028-01-01）；落在勞動契約法 **0 題**；同文件但條文不在待施行清單 **2 題**（`57-AGGR1`、`57-AGGR2`）。（我的第一版重算因條號正規化把「第2條第1款」誤處理成「21款」而得到不同答案，已查明是我的腳本缺陷、Codex 正確；兩者修正後一致。）
5. 全量 pytest **2226 passed**（2200＋26）、節點卡 0 警告、`.env` 敏感值對 36 個檔 0 命中；`kg2-neo4j` StartedAt 仍為新基準。

**對 S3 的意義（〔判讀〕）**：凍結題庫幾乎不受「尚未施行」處理影響（42 題中 1 題，且該題的 gold 內容是現行有效的定義款、只有附表一待施行），所以 S3 的行為變更**不會混淆凍結基準的比較**，但也**無法用凍結題庫量到它的效益**；S3 的評測需另備題目。

**限制（沿用）**：解析器僅 16 份備註驗證；48／64 份文件無備註（`no_information`≠`in_force`）；項／附表層級只能標在條文層；題庫涉及度只比對 gold 的 `source_law`＋`source_article`，不代表檢索實際取到該條。
