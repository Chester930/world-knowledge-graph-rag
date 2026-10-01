# 報告215：下一階段任務規劃——Phase 1「派生標示接進檢索／回答」的接線盤點與影子模式設計

> **日期**：2026-10-01
> **性質**：階段任務規劃（**本文只含規劃對話自己做的唯讀程式碼盤點與建議，尚未派工**）。分工同前：規劃對話決定、執行者執行、規劃對話只記錄。**本文件只由規劃對話修改。**
> **依據**：使用者「繼續下一步」——採用規劃對話建議的第 2 步（報告212 §7、記憶接續點 §六-2）。
> **前提不變**：不改儲存資料、不重抽、不改抽取提示詞、不動 KG#4、不啟動 Ollama／LLM、不改論文與題庫。

---

## 1. 盤點結果：派生標示要接，會碰到哪些位置（程式碼讀過，非推測）

| # | 位置 | 現況（已讀） | 對 Phase 1 的意義 |
| --- | --- | --- | --- |
| P1 | `services/context/fact_lines.py:13-36` `strip_type_markers()` | 生產路徑**刻意把事實文字裡的型別標記清掉**，含「（概念）」與受控型別詞（報告25 §4 發現5：標記洩漏到最終答案） | **關鍵風險**：把「未知／尚未處理」直接寫進 prompt 事實行，等於重新引入先前被清除的標記，可能再度洩漏到答案。**prompt 側不得先動** |
| P2 | `fact_lines.py:39-54` `is_contentful_line()` ＋ `:114-131` `_add_fact()` | 空受詞事實靠「渲染後文字」判斷是否殘缺；空主詞直接丟；`verb` 空時另有品質守門 | 與「尚未處理（5,136）／未知（145）」的派生規則**直接重疊**：現行過濾已隱含一套殘缺判定，Phase 1 若再加一套，兩者必須對齊，否則會出現不一致 |
| P3 | `services/context/telemetry.py:46-` `build_retrieval_trace()` | **選用（`include_retrieval_trace`）、純記錄**、不改檢索／排序／截斷；每筆 fact 已有 `rank`、`article_no`、`in_prompt` | **最安全的接線點**：可在此為每筆 fact／triple 附加派生標示欄位，不影響回答 |
| P4 | `services/retrieval/bfs.py:26-72` | BFS 回傳 `rel_type`；`RELATED_TO` 無其他來源資訊 | 關係標示可由 `rel_type` 純派生（`RELATED_TO`＝來源不明），**不需改 Cypher** |
| P5 | `routers/agent.py:572 _arrange_fact_lines()` 與 `:1063` 接地核對 | 排序／截斷／接地核對皆吃「渲染後文字行」 | 若日後要「降權殘缺事實」，改動點在此，屬**行為變更**，需評測，不在本階段 |
| P6 | `source_article_no` | trace 已輸出 `article_no`；`svo_service.py:1114-1121` 有 `if article_no:` 的真假值判斷（哨兵字串會令事實消失） | 只可「查詢時派生」；`semantic_marks` 已有對應函式，不新增欄位 |

**結論**：派生標示有一個天然的**零行為風險落點（P3：檢索 trace）**，而 prompt 側（P1、P2、P5）有已知的前車之鑑與重疊規則，**不應先動**。

## 2. 建議：Phase 1 先做「影子模式」（只進 trace，不進 prompt、不影響排序）

**做法**：在 `build_retrieval_trace()` 的輸出中，為每筆 fact／triple 附加一個**選用的、預設關閉的**欄位 `semantic_marks`（內容＝`services/semantic_marks.py` 對該筆事實的派生結果，`concept_scheme` 以參數表示），旗標預設 `False` 時輸出與現在**逐位元組相同**。

**為什麼這樣排**：
1. 成功標準（理由乙）是「標示覆蓋率／不變量符合度」，影子模式正好能量到「**實際被檢索到、實際進 prompt 的事實**」的標示分布——這比全圖的分布更貼近使用者關心的問題（Phase 0 是全圖母體，不代表檢索會撈到什麼）。
2. 可回答一個還沒有數據的問題：**檢索結果裡 5,136 筆「尚未處理」殘缺事實實際佔多少比例、有多少進了 prompt**。若比例極低，Phase 1 接進 prompt 就不值得；若高，才有設計降權／呈現規則的依據。
3. 完全可逆：旗標關閉即回到原行為；不碰 P1／P2／P5。

**不做（需使用者另行決定）**：把標示寫進 prompt、依標示降權或排除、新增儲存欄位、改抽取。

## 3. 任務規格

| ID | 任務 | 性質 |
| --- | --- | --- |
| **M1** | 在 `telemetry.build_retrieval_trace()` 增加**預設關閉**的 `semantic_marks` 附加欄位（參數化 `concept_scheme`），含單元測試與「旗標關閉時輸出完全不變」的回歸測試 | 新增程式（production 檔唯一改動點，僅此函式） |
| **M2** | 離線重放：用**既有已保存的**檢索結果（先找 repo 內報告62 T0／報告65／t2 評測保存的 trace／結果檔；**找不到就停止回報，不要為此啟動 Ollama 重跑**），套 M1 的派生，輸出「被檢索事實／進 prompt 事實」的標示分布 | 離線分析腳本＋報告 |
| **M3** | 階段彙整：M2 數字、與 Phase 0 全圖分布對照、是否值得接 prompt 的**證據**（不替使用者決定） | 報告 |

**M1 硬性驗收**：
- 旗標預設 `False`；以測試證明預設輸出與修改前完全相同（`==` 比對 dict）；
- 修改前後 `ast.dump` 比對，**只允許 `build_retrieval_trace` 內新增參數與一個條件分支**，其餘函式與檔案不變（我會自己跑 `ast.dump`）；
- 不改 `strip_type_markers`、`split_fact_lines`、`_arrange_fact_lines`、`bfs.py`、任何 Cypher；
- `routers/agent.py` 若必須傳入新參數，需列出**確切行號與理由**，預設不傳（沿用關閉）；若要新增請求欄位（如 `include_semantic_marks`），**先停止回報，由我與使用者決定**（會動公開 API）；
- 全量 pytest ≥1646 passed／0 failed；`check_node_cards.py` 不新增警告。

**M2 防護**：不連 Neo4j 即可完成最佳；若必須連，沿用唯讀防護（`assert_read_only`／`ReadOnlyRunner`、前後總數 57,451／137,873／16,826／12,296、密碼不外洩）；不啟動 Ollama／WSL、不呼叫 LLM／embedding。

## 4. 停止條件

1. M1 需改動 `build_retrieval_trace` 以外的 production 函式，或需新增公開請求欄位——回報。
2. M2 找不到可離線重放的已保存檢索結果——回報（不要重跑評測）。
3. 派生結果與 Phase 0 對同一事實的判定不一致——回報，不調整規則湊數字。
4. 工作區出現非自己的未提交檔：逐檔指定路徑 commit，不用 `git add -A`。

## 5. 需使用者決定（我不代決定；**可同時進行，不擋 M1／M2**）

1. 是否同意 Phase 1 採「影子模式優先」（本文建議）；
2. 報告214 L1 的 12 筆、報告209 K3 的 20 筆疑問（仍待）；
3. 影子模式結果出來後，才討論是否進 prompt、降權或落地儲存。

## 6. 編號與約定

本文為 **215**；執行者新報告自 **216** 起（先 `ls docs/報告` 確認）。派工一次只能一個執行者；Claude 執行對話用 `SendMessage`（`notify_when_idle:true`），Codex 由使用者貼指令。

## 7. 執行紀錄（僅規劃對話更新）

| ID | 狀態 | 結論 | commit | 備註 |
| --- | --- | --- | --- | --- |
| M1 | ✅ 通過（Claude 執行對話完成；規劃對話獨立驗證） | `build_retrieval_trace()` 新增 4 個選用參數（`include_semantic_marks=False`、`concept_scheme="A"`、`type_lookups=None`、`document_article_applicable=None`）；旗標開啟時每筆 fact／triple 多 `semantic_marks` 鍵；全量 pytest 1656 passed（基準 1646＋10 新測試） | `7faa62e`（報告216） | **我驗**：範圍＝`git diff --name-status` 僅 `telemetry.py`（+46 行、0 刪）、新測試檔、報告216；未動規劃文件／其他 production／資料。**`ast.dump` 前後比對**：模組層節點 only_old／only_new 皆空，唯一變動的是 `build_retrieval_trace`，原三參數順序不變、僅尾端追加 4 個帶預設值參數，`semantic_marks` 於旗標分支內才 import。**無接線**：`git grep` 除 `telemetry.py` 本身外，非測試的 production 檔無任何引用；`routers/agent.py` 仍以舊三參數呼叫（旗標恆為預設關閉，行為零變更）。**全量 pytest 我重跑＝1656 passed／0 failed**（63 秒）。**我看到的設計細節**：①fact 路徑不傳實體型別，所以 fact 只有 `fields`／`relation_type`／`article_no` 三項標示，實體型別標示只在 triple 且提供 `type_lookups` 時出現——M2 離線重放時要注意 fact 缺實體型別維度；②無條號且查無文件適用資訊時標「無法由現有資料判定」（不猜，符合任務書）；③無效 `concept_scheme` 會 `ValueError`（僅旗標開啟時） |
| M2 | ⏳ | — | — | — |
| M3 | ⏳ | — | — | — |
