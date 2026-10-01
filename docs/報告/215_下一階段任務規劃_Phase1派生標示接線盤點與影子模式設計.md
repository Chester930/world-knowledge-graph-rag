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
| M2 | ⚠️ 部分完成（誠實停在缺口；規劃對話獨立驗證） | 已保存 trace 缺 subject／object／verb／rel_type，故 **fields／relation_type／實體型別標示無法離線重放**；只重放出 `in_prompt` 與 `article_no`。執行者報：42 題去重、Fact 4,815／triple 1,044；進 prompt Fact 1,758、triple 677；article_no 僅 K2／K3 有值（K2 有條號進 prompt 35.5% vs 無 39.6%；K3 18.8% vs 21.9%）。**「進 prompt 中殘缺比例」無法算**，不宣稱任何方向。已否決以空白切 text 推測空欄位（Fact 實體名稱本身含空白） | `b56f046`（報告217、`data/analysis/semantic_marks_replay_20261001.json`、`scripts/analysis/semantic_marks_replay.py`＋測試） | **我驗**：範圍＝僅新增報告217／JSON／腳本／測試，未動 production、規劃文件。**我自行掃描所有 `records.json` 的 `lineage.stage1_retrieval.retrieval_trace`**：fact／triple 的鍵集合皆只有 `article_no／in_prompt／kind／rank／score／source_doc_id／source_svo_chunk_index／text`——**缺欄位之說屬實**。**全量 pytest 我重跑＝1661 passed／0 failed**。**小差異**：我寬鬆掃描找到含 trace 的 records.json 為 49 個，執行者報 27 個（它去重並可能排除非檔名規則／重複檔；去重後 42 題與 4,815／1,044 我**未逐筆重算**，數字以報告217 為準、僅供量級參考）。**結論**：M2 的核心問題（進 prompt 中殘缺事實比例）**離線無法回答**；要回答需 ①唯讀 join KG#4 回補欄位（選項A）或 ②下次評測啟用 M1 旗標保存（選項B，需跑檢索＝要啟動服務）。**待使用者裁示，我建議 A**（見下） |
| M2b | ✅ 通過（使用者授權選項A；規劃對話連DB唯讀獨立驗證） | KG#4 唯讀 join 補算：Fact 對回 22,639／22,784＝99.4%（歧義 0、未對到 145，全在 `t2_k1_topk40` 舊 KG 狀態批）；triple 10,819／10,987＝98.5%（歧義 22、未對到 146；已保存 triple 的 chunk_index 皆 None，故以 (doc,text) 對回）。**進 prompt 的 Fact 中「尚未處理」比例：凍結基準 s0 24.1%（266／1,102）、s2_k1 26.7%、彙總 26.5%；「未知」＝0（現行過濾已排除空受詞且空 verb 者）**；被檢索端 19.9%／22.7%／23.2%；Phase 0 全圖 30.5%。triple 進 prompt 殘缺約 9.5–11.2%。關係「已解決」Fact 約 9.4–9.6%、triple 約 15%。條號對回後 99.7–99.9% 已解決。實體型別：「概念」佔位約佔進 prompt 事實型別標示的 6 成，結果取決於 A／B 決定。全量 pytest 1671 passed | `0267bf2`（報告218、`0e8eb06` 為報告217 §8 Fact 版 join；腳本 `semantic_marks_replay_join.py`＋測試、兩份 JSON） | **我驗**：①範圍＝僅新增／修改分析腳本、測試、JSON、報告217／218，未動 production、規劃文件。②腳本查詢僅 `MATCH／OPTIONAL MATCH／UNWIND／RETURN`，且只經 `ReadOnlyRunner`＋`assert_read_only`（`default_access_mode="READ"`）。③**我自己連 KG#4（READ）核對總數＝57,451／137,873／16,826／12,296**，JSON 的前後總數相同。④**密碼外洩比對 0 命中**（新腳本、兩份 JSON、報告217／218）。⑤標題數字我用 JSON 的 s0 三個檔彙整重算：進 prompt Fact 1,102、尚未處理 266＝24.1%，吻合。⑥**獨立抽查 join**：自 s0_r1 取 40 筆進 prompt Fact，我自己對 KG#4 以 (doc,text) 查詢並套 `mark_fact_fields`：40／40 對回、0 未對到，7 筆（17.5%）尚未處理——與該檔整體 24.2%（136／563）在樣本誤差內相容（n=40 太小，只能證明 join 方向正確，不足以驗證比例）。⑦全量 pytest 我重跑＝**1671 passed／0 failed**。**程序提醒**：執行者在我正式派 M2b（我的授權查詢）**之前**已於 21:02 先 commit 報告217 §8 的 Fact 版 join（`0e8eb06`），聲稱已依使用者授權；我無法驗證該授權的來源（可能是使用者直接對該 session 說）。已確認該 join 同為唯讀、前後總數相同、無外洩，**實質無害**，但**日後唯讀 DB 查詢請先經規劃對話確認併發**。 |
| M3 | ✅ 通過（Claude 執行對話完成；規劃對話獨立驗證） | 報告219：M1／M2／M2b 經過、關鍵數字、五個接線選項（①維持影子 ②trace／評測層常態啟用 ③prompt 標示 ④降權排除 ⑤落地儲存；各列檔／函式、可逆性、風險、驗證）、限制與待裁示清單。**未替使用者選擇、不宣稱品質改善** | `8b5f584` | **我驗**：範圍＝僅 `HANDOVER.md`（頂部新增條目＋最後更新行）、`00_報告索引.md`（新增 216–219 四列）、報告219；未動程式、規劃文件、論文、題庫。**數字**：我用 `semantic_marks_replay_join2_20261001.json` 重算 s0／s2_k1／彙總的 Fact 與 triple（被檢索／進 prompt）的尚未處理、未知、關係已解決，共 12 組**全數吻合報告219 §2**（如進 prompt Fact 尚未處理 24.1%／26.7%／26.5%、n＝1,102／1,503／9,578；triple 11.2%／9.5%／9.7%）。**全量 pytest 我重跑＝1671 passed／0 failed**。**選項分析**：未越權，§6 待裁示 6 項只列不決。**需補充一點**：§5-8 說 0e8eb06 的提前 join 是「依使用者『選項 A 授權』的指示」——我無法驗證該授權時間點早於 21:02（我自己的授權紀錄在其之後），以報告為執行者自述看待。**階段結論**：Phase 1 影子模式完成；**主要發現＝進 prompt 的 Fact 有約 1／4（24–27%）為「尚未處理」殘缺事實，關係型別約 9 成為來源不明 `RELATED_TO`，條號幾乎全已解決**；是否進 prompt／降權／落地由使用者決定。 |
