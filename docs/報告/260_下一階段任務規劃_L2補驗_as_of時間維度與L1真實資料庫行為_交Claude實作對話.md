# 報告260：下一階段任務規劃——L2 補驗：`state_as_of` 時間維度、L1 真實資料庫行為、BFS 邊混合、條文層連動（在拋棄式 Neo4j；交 Claude 實作對話寫程式，規劃對話執行 docker）

> **日期**：2026-10-02
> **性質**：階段任務規劃。分工：**規劃對話決定、起臨時容器並執行驗證腳本、獨立驗證；Claude 實作對話寫純函式、腳本與測試**（實作對話的使用者規則禁止操作 docker／連 Neo4j）。**本文件只由規劃對話修改（§11 執行紀錄）。**
> **依據**：[報告257](257_關係狀態機落地設計審查_依最新證據更新報告234.md) §5 L2；使用者「依照建議繼續」＝同意做 L2，**包含允許規劃對話起一個拋棄式臨時 Neo4j 容器**（報告257 D5 的建議）。
> **基準**：HEAD ≥ `9733150`；全量 pytest **2007 passed**；`kg2-neo4j` 新基準 StartedAt＝`2026-10-02T11:09:32.79429649Z`。
> **本任務的性質**：**只在一次性容器、只用合成資料**。**不碰 KG#4／`kg2-neo4j`（不連 17990）、不改 production（`services/` 既有函式、`routers/`、`core/` 零變動）。** 唯一允許的 `services/` 變更是在純運算原型 `services/relation_lifecycle.py` **新增** `state_as_of`（零接線，見 N1）。

---

## 1. 為什麼 L2 要縮小範圍（規劃對話的查證，〔事實〕）

報告257 把 L2 寫成「用虛構資料驗證 W1／W3／R2／R3／`state_as_of`」。查證後發現 **P3／P4（報告240–243）已在拋棄式 Neo4j 驗證過其中大部分**（`scripts/analysis/disposable_fact_state_validation.py` 的 C1–C5、`disposable_write_path_validation.py` 的 V1–V4）：

| 項目 | 已驗證？ | 出處 |
| --- | --- | --- |
| 先過濾後去重 vs 現行去重（新舊同鍵時現行留下較近的舊版） | ✅ | P3 C1／C4 |
| 撤銷：現行 `revoke_chunk_facts` 實體刪除 vs 提案「追加撤銷事件→已駁回」 | ✅ | P3 C2 |
| BFS 邊聚合與 Fact 狀態推導（含 ~1,000 Fact 負載） | ✅ | P3 C3 |
| 事件重播＝快取狀態、漂移稽核 | ✅ | P3 C5 |
| 新建 Fact 帶生命週期屬性不破壞既有函式；簡繁合併／改邊型別後扁平屬性不同步 | ✅ | P4 V1–V4 |
| **`state_as_of`（時間維度，報告257 G1）** | ❌ | 新 |
| **L1 在真實資料庫的行為**（Fact 有狀態值時 `properties(node)[…]` 回傳、`UnknownPropertyKey` 通知是否在屬性鍵存在後消失、trace 實際顯示狀態） | ❌ | 新（L1 只用假 driver＋KG#4 上「無任何 Fact 帶狀態」的情況驗證） |
| **BFS 邊的來源混合（報告257 G2）**：同一三元組兩個版本來源→一條邊、`natural_text` 被後寫覆蓋 | ❌ | 新（P3 C3 只驗狀態推導） |
| **條文層「新版取代」連動 Fact（報告257 G3）** | ❌ | 新 |

**本任務只補後四列（稱 L2′）。**

## 2. 〔更正〕報告257 G1 的一個不精確處（規劃對話自查）

報告257 G1 寫「尚未施行條文的 Fact：『驗證通過』事件的 `effective_date` 設為施行日 → 在 `as_of＝今日` 時重播停在『候選』之前的狀態，不在可檢索集合內」。**這句有誤**：只要「抽取完成」事件已被納入（日期早於 `as_of`），重播結果就是**候選**，而 `DEFAULT_RETRIEVABLE_STATES` 含候選（`relation_lifecycle.py:47`），**仍會被檢索到**。
**修正後的設計（本任務要驗證的）**：
- 該條文 Fact 的**所有事件**（含「抽取完成」）都以**施行日**為 `effective_date`——「這條規定成為一條規定」的時點是施行日；
- `state_as_of(events, as_of)` 回傳**狀態＋判定類別**，區分三種不同的「沒有狀態」：
  1. `no_events`：Fact 沒有任何事件（舊資料）＝「尚未處理」，**依既有規則可檢索**；
  2. `not_yet_effective`：有事件，但**全部**晚於 `as_of`＝「尚未生效」，**不可檢索**；
  3. `replayed`：至少一個事件生效，以生效事件重播得到的狀態，再依可檢索集合判定。
- 時光回溯：舊版 Fact 事件＝[抽取完成@d0, 驗證通過@d0, 新版取代@d1]；`as_of<d1` → 有效（可檢索）；`as_of≥d1` → 已被取代（不可檢索）。

## 3. 任務總覽

| 步驟 | 內容 | 執行者 |
| --- | --- | --- |
| **N0** | 前置：`git pull`、基準 pytest（應 2007 passed）、`ls docs/報告`（實作者報告自 **261** 起）、讀 P3／P4／G1 的腳本與測試（見 §6 範本） | 實作對話 |
| **N1** | `services/relation_lifecycle.py` 新增 `state_as_of`（§4） | 實作對話 |
| **N2** | N1 的單元測試（§4） | 實作對話 |
| **N3** | 驗證腳本 `scripts/analysis/disposable_lifecycle_l2_validation.py`＋其單元測試（§5–§6；Docker 不在一般單元測試中執行） | 實作對話 |
| **N4** | 實作者 commit＋push，SendMessage 通知規劃對話 | 實作對話 |
| **N5** | 規劃對話讀碼驗收閘門 → **起拋棄式容器實跑** → 失敗則把輸出貼回給實作對話修（可能多輪）→ 拆除並證明已拆除 | 規劃對話 |
| **N6** | 報告 261（實作者：程式／測試）與規劃對話的執行紀錄（§11）、索引、`HANDOVER.md` | 兩者 |

## 4. N1／N2 規格：`state_as_of`

```
AsOfResult(state: str | None, status: "no_events"|"not_yet_effective"|"replayed"|"illegal", included: int, excluded: int, replay: ReplayResult | None)
def state_as_of(events: Sequence[LifecycleEvent], as_of: str, lifecycle: Lifecycle = CORE_LIFECYCLE) -> AsOfResult
def is_retrievable_as_of(result: AsOfResult, retrievable: frozenset[str | None] = DEFAULT_RETRIEVABLE_STATES) -> bool
```

1. `as_of` 必須是 `YYYY-MM-DD`（與 `LifecycleEvent` 同形狀檢查），否則 `ValueError`。
2. `events` 為空 → `status="no_events"`、`state=None`、`included=excluded=0`。
3. 事件納入規則：`effective_date is None` **或** `effective_date <= as_of`（ISO 字串比較）＝納入；**保持原順序**（不以日期重排——事件清單的順序是記錄順序）。
4. 納入數為 0（有事件但全被排除）→ `status="not_yet_effective"`、`state=None`。
5. 否則對**納入的事件**呼叫既有 `replay`（**不要改 `replay`**）。〔事實，讀碼 `relation_lifecycle.py:241–268`〕`replay` 遇到非法事件**不停止**：被拒事件記錄在 `steps`、**不改變狀態**、重播繼續，`final_state` 已是「忽略被拒事件」的投影，`first_illegal` 為第一個被拒事件。因此：`state=replay.final_state`；`replay.ok`（`first_illegal is None`）→ `status="replayed"`，否則 `status="illegal"`（**狀態仍取 `final_state`**，只是標示事件紀錄有被拒事件、供稽核）；兩種都把完整 `replay` 帶回。
6. `is_retrievable_as_of`：`no_events` → `None in retrievable`；`not_yet_effective` → `False`；`replayed` 與 `illegal` → `state in retrievable`（`illegal` 採**不隱藏**〔fail-open，與現有 zero-out 行為一致〕，由呼叫端依 `status` 另行報告異常；可直接呼叫既有 `is_retrievable`）。
7. **不得修改**既有函式與常數；`relation_lifecycle.py` 仍零接線（本任務不得讓任何 production 模組匯入它）。
8. 單元測試（表格驅動）：空事件；全部無日期；全部晚於 as_of；部分生效；邊界日期（`==as_of` 納入）；§2 的「尚未施行」案例（所有事件日期＝施行日）在施行日前後；舊版時光回溯案例（`as_of` 在取代日前後）；含非法轉換的事件序列（`status="illegal"`、狀態＝`final_state`、被拒事件不改狀態、`is_retrievable_as_of` 依狀態判定）；`as_of` 格式錯誤；事件順序不被日期重排（給一組日期亂序事件，驗證輸出只取決於納入集合與原順序）；`is_retrievable_as_of` 四種 `status`；自訂 `retrievable`（例如只含「有效」）。

## 5. N3 規格：驗證腳本（S1–S5）

**環境**：沿用 G1 腳本（`scripts/analysis/disposable_resync_solution_b_validation.py`）的做法——`import` P3／P4 的連線閘門與容器函式，**自訂新基準** `EXPECTED_KG4_STARTED_AT = "2026-10-02T11:09:32.79429649Z"`，**不呼叫任何舊基準執行器**；精確容器名稱 `kg2-throwaway-neo4j`、埠 27474／27687、3 GB、`neo4j:5.26-enterprise`；閘門對 `17990`、`kg2-neo4j`、非 `kg2-throwaway-` 前綴磁碟區一律拒絕；合成資料、8 維假向量；結尾**無論成敗都拆除並證明已拆除**；輸出 JSON 到 `data/analysis/disposable_lifecycle_l2_validation_20261002.json`。**資料全為合成；盡量走 production 函式建立資料。**

| 編號 | 驗證什麼 | 作法 | 預期對照（寫成表，結果與預期不符要如實記錄，不要調整） |
| --- | --- | --- | --- |
| **S1** | **L1 真實行為** | 合成 KG、建立 3 組 Fact：無 `lifecycle_state` 屬性鍵的資料庫階段先用 production `vector_search_facts`（`properties(node)['lifecycle_state']` 版本）與等價的 `node.lifecycle_state` 查詢各跑一次，**讀 `result.summary.notifications`**；再建立有狀態值的 Fact（`候選`／`有效`／`已被取代`）後重跑 | ①屬性鍵不存在時：`node.lifecycle_state` 版本有 `UnknownPropertyKeyWarning`、`properties(node)[…]` 版本無通知；②屬性鍵存在後：**兩種寫法都無通知**，`properties(node)[…]` 回傳實際狀態值、無狀態者為 `None`；③以這些真實回傳結果呼叫 `build_retrieval_trace(include_semantic_marks=True)`：fact 的 `semantic_marks.lifecycle_state` 依序為「候選／有效／已被取代／尚未處理」 |
| **S2** | **`state_as_of` 整合進檢索（先過濾後去重）** | 建立：A 尚未施行（事件全為 2027-01-01）、B 舊版（事件@2023-05-01…新版取代@2025-12-09）、C 新版（事件@2025-12-09）、D 舊資料（無事件、無屬性）、E 一般有效；A／B／C 同鍵（subject, rel_type, object）。原型函式 `filter_as_of_then_dedupe(records, events_by_fact_id, as_of, retrievable)`（寫在腳本內，**以 production `_dedupe_facts_by_key` 去重**）；`lifecycle_events_json` 以 Cypher 追加並讀回解析 | `as_of=2026-10-02`：A 排除（尚未生效）、B 排除（已被取代）、C、D、E 保留，同鍵只剩 C；`as_of=2024-01-01`：B 保留、C 排除（尚未生效）、A 排除；`as_of=2027-01-01`：A、C 保留且因同鍵只留分數高者；**對照**：現行 `vector_search_facts`（先去重）在 `top_k` 內可能留下 B 或 A 而漏掉 C（用分數設計讓 B 的分數最高來證明） |
| **S3** | **BFS 邊來源混合（G2）** | 用 production `merge_triples_to_graph` 對**同一三元組**、兩個不同 `source_doc_id`（舊版／新版）、不同 `natural_text` 各寫一次（依該函式實際簽名與前置條件建立實體與 chunk，必要時參考 P3／P4 腳本如何呼叫） | 只有**一條邊**；`citations_json` 含兩筆來源；`natural_text` 為**最後寫入者**；`bfs_query` 回傳的三元組帶最後一筆來源；兩個版本的 Fact 狀態可分別為已被取代／有效——**記錄邊不能分辨**（這是要量化的風險，不是要修的） |
| **S4** | **條文層連動（G3）** | 建 `LawArticle` 舊版（`version_id=v1`）與新版（`v2`），各自 `SUPPORTED_BY` 兩個 Fact；原型連動 Cypher（腳本內）：對舊版條文支持的 Fact **追加**「新版取代」事件（`effective_date`＝新版 `valid_from`，`evidence_ref`＝新版條文識別）並更新快取狀態；**冪等**（以 `evidence_ref` 判斷已追加者不重複追加）；另放一個**不同法規**的同號條文 Fact 作對照 | 舊版 2 個 Fact 各多 1 個事件、快取＝已被取代；新版與對照 Fact 事件數不變；**第二次執行追加 0 筆**；每個 Fact 的事件重播＝快取狀態（無漂移）；`state_as_of` 在取代日前後各驗一次 |
| **S5** | **規模與耗時** | 17,000 個 Fact（含向量索引 `ONLINE`），其中 1,800 帶 `lifecycle_state`＋事件 JSON；跑 production `vector_search_facts` 的 `top_k=20`（候選 80）與 `top_k=40`（候選 160）各 40 次（先暖機），中位／P95 | 記錄屬性鍵**存在**時 `properties(node)[…]` 與 `node.lifecycle_state` 的耗時差（驗證報告258 §10 的「L4 後可改回較便宜寫法」是否成立）；以及 S2 的過濾函式處理 160 候選的耗時 |

腳本結構沿用 G1：`W0` 式閘門與測試 → 建環境 → 逐場景 → 拆除；每個場景回傳 `{current, proposal, expected, matches_expected, unexpected_findings}`，結尾彙總表。

## 6. 範本與限制

- **範本**：`scripts/analysis/disposable_resync_solution_b_validation.py`（G1，已驗證）、`disposable_backup_restore_validation.py`（G2）、`disposable_fact_state_validation.py`／`disposable_write_path_validation.py`（P3／P4）。**不得修改**這些既有腳本與其測試。
- **單元測試**（不需 Docker）：閘門（拒絕 17990／`kg2-neo4j`／非白名單容器名／非 `kg2-throwaway-` 磁碟區）、新基準常數值、`filter_as_of_then_dedupe` 的純函式部分（可用假資料測）、連動 Cypher 的**結構檢查**（只對 `Fact` 追加、含 `kg_id` 範圍、不含 `DETACH DELETE`／`DELETE`）、輸出 JSON 結構、腳本不含任何 `17990`／`bolt://` 以外的連線字串（臨時埠除外）與密碼樣式字串。
- **你不能自己跑腳本、不能碰 docker**；Cypher 與 production 函式的簽名要自己讀碼確認；第一次實跑由我執行，若有 bug 我把完整輸出貼回你，你修。

## 7. 驗收（規劃對話）

- `git diff` 範圍：新增／修改 `services/relation_lifecycle.py`（**僅新增** `AsOfResult`、`state_as_of`、`is_retrievable_as_of`）、新增腳本與測試與輸出 JSON、報告 261、索引、`HANDOVER.md`；**其他 production 檔、既有 `disposable_*` 腳本與測試、規劃文件、論文、題庫、歷史報告原文零變動**；
- 我 `git grep` 確認 `relation_lifecycle` 仍只被 `law_version_events.py`、`scripts/analysis/*` 與測試匯入；
- 我讀碼逐項核對閘門（磁碟區前綴、受保護名稱、禁止 pull、17990 完全不出現）；
- **我實跑**並逐場景對照 §5 預期；**失敗或與預期不符一律如實記錄，不調整預期**；
- 拆除證據：`docker ps -a` 無 `kg2-throwaway-*` 容器、無殘留磁碟區；`kg2-neo4j` StartedAt 前後皆為新基準；`kg2_neo4j_data` 大小不變；
- 全量 pytest ≥ 2007＋新增數、節點卡 0 警告、`.env` 敏感值外洩掃描 0 命中。

## 8. 停止條件（實作對話遇到即停止並回報）

1. 需要連 KG#4／碰 docker／讀 `.env`，或需要改 `relation_lifecycle.py` 既有函式或其他 production 檔；
2. production 函式（`merge_triples_to_graph`、`_create_fact_node` 等）的簽名或前置條件讀碼後仍不確定如何在合成環境呼叫；
3. 發現 `ReplayResult`／`replay` 的既有語意與 §4-5 的描述不符（說明差異，**不要自行改 `replay`**）。

## 9. 編號、約定、回報

實作者報告自 **261** 起（先 `ls docs/報告`）。繁體中文；conventional commit（例 `feat(lifecycle): ...`、`test(...)`、`docs(報告261): ...`）；commit 後 push 本分支（不動 master）。**不得自稱已驗證**。完成時**直接 SendMessage 回報規劃對話 `project refactor review sdd`**，格式：`N0–N4｜結論｜commit SHA｜新增函式簽名｜新增測試數與全量 pytest 結果｜腳本一行指令｜S1–S5 預期對照是否寫成表｜改動檔清單（逐檔一行）｜偏離報告260之處（無則寫無）`。

## 10. 不在本任務範圍

寫入 `lifecycle_state`／事件到 KG#4、正式 W1／W3／R2／R3 實作、BFS 標示、試點 KG（L3′）、「尚未施行」`effective_note` 解析（D4）——皆需另行同意。

## 11. 執行紀錄（僅規劃對話更新）

⏳ 任務書已寫成，將以 SendMessage 派給實作對話。KG#4 仍無任何寫入核准；本任務不涉及 KG#4。
