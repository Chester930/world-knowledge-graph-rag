# 跨 Agent 接續進度

> **適用對象**：Claude Code、Codex、Gemini CLI，以及其他接續本專案的 agent。此文件是目前進度的唯一權威交接來源；舊的 `HANDOVER_CODEX.md`／`HANDOVER_CLAUDE_CODE.md` 僅保留歷史脈絡。
> **最後更新**：2026-09-29（報告108／109 已審核並 push；A8 = BREAKS，待裁示修正方案）

## 2026-09-30（報告139）：M2 P2 第一刀——抽出 `services/context/fact_lines.py` 任務書，交 Codex 執行

使用者同意第一刀採 A、新模組放 `services/context/`（報告97 §6.3）。**Claude 讀碼後修訂範圍**：原口頭 A 有 4 個函式，但 `_merge_fact_lines`（`agent.py:817-823`）呼叫 `_split_fact_lines`（`:822`，不在本次範圍），若只搬前者新模組就得反向 import `routers.agent`——所以**第一刀縮為 3 個函式＋專屬常數**：`_strip_type_markers`（＋`_CONTROLLED_TYPE_TOKEN_PATTERN`／`_CONTROLLED_TYPE_LIST_PATTERN`／`_TYPE_MARKER_RE` 三個常數，全 repo 只有它用到）、`_is_contentful_line`、`_litm_reorder`；**`_merge_fact_lines`＋`_split_fact_lines` 一起留第二刀**（屆時依賴已搬走、成為依賴封閉的一組）。報告138 Q7 把 `_merge_fact_lines` 評為「低」漏看此依賴（Claude 責任）。[報告139](docs/報告/139_M2_P2第一刀_context_fact_lines抽出SDD任務書.md)：新模組以**去底線的公開名稱**（`strip_type_markers`／`is_contentful_line`／`litm_reorder`）定義、函式本體逐字不變、零反向依賴（僅 `re` 與 `core.constants`）；`agent.py` 以 `import … as _原名` 保留舊私有名稱重新匯出（**同一函式物件**，`is` 比較）。單一 commit、單段執行。驗證＝**機械證據＋K 臂快照**：AST 逐字比對（含 docstring／型別標註）、`agent.py` diff 只能是刪除加一個 import 區塊、對報告136 快照真實資料＋500 筆合成字串的**差分行為測試**（舊實作 vs 新模組）、新測試期望值「先用修改前實作取得」、身分（`is`）測試與 AST 反向依賴測試、相依快照（新增 `services.context*` 兩模組與 `routers.agent → services.context.fact_lines` 等邊）、**K 臂快照重跑**（報告136 §2 逐字指令，輸出到暫存目錄，對基準 run1 與 run2 各比對一次；6 題 L1 ✅、5 個穩定題 L2 ✅、`17-Q1` 看 L3、無 error；比對輸出小檔進版控）。Claude 三項故意破壞（`litm_reorder` 條件反轉、加反向 import、`agent.py` 改為複製函式使 `is` 失敗）。成果報告 140。**狀態：等待 Codex 執行（含約 15 分鐘真實服務評測）→Claude 依§3驗收→通過才 push。** 之後：第二刀＝`_split_fact_lines`＋`_merge_fact_lines`；建議另補 `_rrf_order` 直接測試。

## 2026-09-30（報告137）：M2 P2 前置——`routers/agent.py` 拆分盤點任務書，已完成並 push

使用者同意進 P2、**先只讀盤點再由使用者確認第一刀**。[報告137](docs/報告/137_M2_P2前置_agent_py拆分盤點SDD任務書.md)：純靜態分析，不需 Neo4j／Ollama。Claude 已量測：`agent.py` 1,904 行、37 個頂層定義（36 私有＋公開 `chat`）；最大的是 `chat`（L1637，268 行）、`_generate_from_context_lines`（L1439，195 行）、`_expand_facts_by_article`（139 行）、`_build_prompt`（90 行）；至少 28 個檔案引用 `routers.agent`，harness 以 `from routers import agent` 後用 `agent._xxx` **屬性方式**取用私有函式（簡單搜尋抓不到，本任務要求 `git grep`＋`ast` 雙重掃描）；`services/svo_service.py:2350` 只是 docstring 註解，非真依賴。**最大技術陷阱＝re-export 陷阱**：測試若 `monkeypatch.setattr(agent, "_foo", fake)`，而 `_foo` 連同其呼叫端被搬走、`agent.py` 只留 re-export，patch 只換掉 re-export 的名稱、搬走後的呼叫端仍用原實作——測試**仍通過但已靜默失去效力**（比失敗更危險），Q4 要求逐條判斷 (a) 仍有效／(b) 靜默失效／(c) 直接失敗。共 10 題：Q1 函式盤點表（職責／大節點／純度）、Q2 檔內呼叫圖（含 `chat()` 巢狀函式與閉包捕獲）、Q3 外部引用完整清單（四種形式）、Q4 測試補丁點與 re-export 陷阱、Q5 模組層級狀態與匯入副作用、Q6 `chat`／`_generate_from_context_lines` 流程地圖、Q7 候選第一刀評估（`_rrf_order`／`_litm_reorder`／`_split_fact_lines`／`_merge_fact_lines`／`_arrange_fact_lines`／`_build_prompt`／`_serialize_sources`／…）、Q8 既有測試覆蓋、Q9 無循環分層草案、Q10 K 臂快照盲區（不覆蓋 alias fallback 路徑、`17-Q1` L2 不穩定、僅 6 題）。**不下最終決定。** 成果報告 138。**狀態：✅ 已驗收通過（`c49e359`＋回填 `064f4b9`，報告138）並 push。** Claude 獨立驗證（自寫 `ast` 掃描）：**158 條測試補丁點完全相同**（全在 `tests/routers/test_agent.py`，皆為 `monkeypatch.setattr(agent, "名稱", …)`，無 `patch`／`patch.object`／字串形式）；**屬性存取 290 個節點完全重現**（我的已追蹤檔案 280＋Codex 另納入的未追蹤 `.claude/tmp/rq1_scope_control_runner.py` 的 10＝290；逐檔對帳 17/19 相同，差異只有該未追蹤檔與報告表格把同一行多個屬性合併成一個行號；注意：`import routers.agent as agent` 的別名形式必須處理，根目錄 `_run_*.py` 與 `tests/core/test_kg_config.py` 都用此形式）；函式行號抽查 5 處全對；**獨立完整回歸 1309 passed**。**關鍵事實**：`agent.py` 1,904 行、36 個頂層函式＋1 個 class；`chat()` 內含 217 行的 `_stream()`；生成尾段 `_generate_from_context_lines` 195 行；外部引用 production 只有 `main.py:121 agent.router`，其餘為 harness／腳本／測試（`services/` 沒有 runtime 依賴）；harness 私有 fan-in＝`agent.chat`、`_generate_from_context_lines`、`_GenerationResult`；根目錄 `_run_*.py` 多個 scratch 腳本用 `agent._split_fact_lines`／`_arrange_fact_lines`／`_strip_type_markers`／`_score_lines_by_embedding`。**Claude 的補充判斷（re-export 陷阱的實際影響面）**：被補丁的 13 個名稱＝`get_driver`／`get_embedding_provider`／`get_llm_provider`／`_find_seed_entities`／`vector_search_facts`／`_relevant_doc_ids_from_seeds`／`bfs_query`／`resolve_query_relation_type`／`_fetch_document_map`／`vector_search_entities`／`LawDocumentRepository`／`KGRepository`／`_build_prompt`（僅 1 個測試），全是 **`chat()`／`_stream` 所依賴的東西**；純函式候選（`_rrf_order`／`_litm_reorder`／`_merge_fact_lines`／`_split_fact_lines`／`_arrange_fact_lines`／`_serialize_sources`／`_build_retrieval_trace`／`_build_retrieval_telemetry`／`_expand_facts_by_article`／`_generate_from_context_lines` 等）**沒有任何一個是補丁目標**。所以報告說的「158 條補丁全部靜默失效」只在**連同 `chat`／`_stream` 一起搬走**的最終階段才成立；拆純函式時 158 條補丁完全不受影響（它們的呼叫端仍留在 `agent.py`，經模組全域名稱查找）。**推論的拆分順序**：先拆純函式群（0 個補丁受影響）→…→**最後才搬 `_stream`／`chat`，且搬之前必須先把這 158 條測試遷移為對新模組名稱補丁**。**未覆蓋（K 臂快照盲區，需另補單元測試）**：種子字面→語意 fallback、all-hub、single candidate、`fact_only`／`bfs_only`／`use_svo=False`、explicit scope、article expand、missing Document、錯誤分支。**直接單元測試缺口**：`_rrf_order` 無直接測試（僅經 `_arrange_fact_lines` 間接）。**候選第一刀（報告138 Q7）**：低風險＝`_litm_reorder`（有直接測試）、`_merge_fact_lines`（14 個直接測試）、`_serialize_sources`／`_build_retrieval_trace`／`_build_retrieval_telemetry`（純、有直接測試）；低至中＝`_rrf_order`（無直接測試，須先補 tie／missing rank 測試）；中＝`_split_fact_lines`（7 個腳本檔為私有 API 使用者）；高＝`_find_seed_entities`／`_drop_hub_seeds`（快照盲區＋大量補丁）。Q9 分層草案：`routers/agent.py`（router＋相容 facade）→`workflows/chat.py`→`services/{retrieval,context,generation}`，三個 service 互不依賴，`_build_retrieval_trace` 需用 context 的 `_strip_type_markers`（以直接 import 或注入 renderer，避免 telemetry→context→generation 反向環）。**待使用者確認第一刀。**

## 2026-09-29（報告135）：M2 P0 補完——K 臂凍結評測快照任務書，已完成並 push

使用者選定方案 **(a)**（先做快照再進 P2）。Claude 以連接埠探測**唯讀確認**環境現況：Neo4j `localhost:17990`＝OPEN、Ollama `localhost:11434`＝OPEN（7687／7474 closed，KG#4 走 17990 符合記載）；`ListAgents` 4 個 peer session 皆 offline，無資源衝突。[報告135](docs/報告/135_M2_P0補完_K臂凍結評測快照SDD任務書.md)：固定 **6 題**（多列 1 題以覆蓋 alias fallback 與拒答兩條路徑；皆 `verified`）＝`17-Q1`（雙問句分解）、`26-Q1`（枚舉）、`26-Q5`（跨文件多跳，已知對排序敏感）、`57-DIST1`（鄰近干擾）、`57-ALIAS1`（種子語意 fallback）、`canary-P1`（拒答），K 臂＝`M4`、`--runs 1`；**同一份程式碼連跑兩次**量出雜訊底線。**三層驗收**：**L1 檢索軌跡**（`retrieval_trace`＋`prompt_context_lines`，應確定性，P2 後須逐字相同；兩次基準若就不同須停下回報）、**L2 答案文字**（`qwen2.5:7b` 即使 `seed=0` 仍可能批次相依而非確定性，見報告20；兩次基準不同的題標為「L2 不可比」）、**L3 原子評分通過／未通過**（不得退步）。新增 `scripts/analysis/compare_p2_snapshots.py`＋測試；快照資料 `data/eval/p2_snapshot_20260929/` 提交進版控作為 P2 黃金基準。**安全規則**：不得啟動／重啟／停止 Neo4j、Ollama、WSL；跑測中不得中斷（曾弄壞 WSL runner）；Neo4j 只讀，run 前後 Fact／Entity 計數須完全相同；報告不得含密碼／金鑰。成果報告 136。**v2 修訂（Codex 第一輪試跑後，Codex 依阻塞條件正確停下，無 commit）**：(1) harness 的資格檢查（`services/evaluation_eligibility.py`）排除 `wording_status=gist` 的題目，**題庫所有 `alias_mapping` 題（ALIAS1／2／3、DIST3）皆為 gist**，`57-ALIAS1` 被排除——改以 `57-COREF1` 取代，「種子實體字面→語意 fallback」路徑列為本快照已知限制（Claude 選題疏漏：只看 `verification_status`）；(2) 實測 K 臂單題耗時 70–180 秒（5 題中 `17-Q1`、`canary-P1` 在預設 180 秒逾時、`57-DIST1` 153 秒）——兩輪改用 `--query-timeout-s 600`（Claude 明確授權，兩輪相同）；(3) 檢索軌跡在 `records.json` 的 `lineage.stage1_retrieval`（`retrieved_fact_ids`／`retrieved_chunk_ids`／`retrieval_trace`）與 `lineage.stage2_context.prompt_context_lines`，非頂層，L1 比對欄位路徑已補進任務書。v1 試跑產物作廢（移暫存目錄）。KG#4 計數前後一致（Fact 16826、Entity 12296）。**狀態：✅ v2 已驗收通過（`30b38d6`＋回填 `3dc6cab`，報告136）並 push。** 6 題全數完成（0 excluded、0 逾時、0 錯誤）；run1 00:00:58–00:18:41、run2 00:19:01–00:32:21。**雜訊底線**：**L1 檢索軌跡 6 題全部逐字相同**（檢索是確定性的，P2 最關鍵的保護層成立）；**L2 僅 `17-Q1` 不穩定**（answer／raw_draft／final_output 不同，`grounding_passed`／`regenerated` 相同）；**L3 全部一致**。Claude 獨立驗證：子集檔 6 題逐題與原題庫**完全相等**、原題庫未被修改、SHA-256 吻合；報告無密碼金鑰（僅 SHA／模型 digest）；KG#4 計數 run 前後相同（Fact 16826／Entity 12296／Document 64／LawArticle 3303）；`routers/`、`services/`、`models/`、`core/`、題庫原檔皆未動；**獨立重跑比對腳本＝已提交的 `baseline_noise_floor.json` 完全相同**；用自己構造的資料破壞測試：改一個 L1 欄位（`26-Q1` 兩行 prompt 對調）→ L1 ❌、退出碼 1；只改答案 → L1 ✅／L2 ❌、退出碼 0；error record → 退出碼 1（不默默通過）；**獨立完整回歸 1309 passed**（＝1304＋新增 5）。**回歸基準更新為 1309。** **P2 驗收判準（報告136 §6）**：全部 6 題 L1 逐字相同；`26-Q1`／`26-Q5`／`57-DIST1`／`57-COREF1`／`canary-P1` 的 L2 可嚴格逐字比對；`17-Q1` 的 L2 已不穩定，改採 L3（`is_perfect`／`supported_spans`／`missing_spans` 不得退步）。⚠️ **注意**：比對腳本「只改答案」的退出碼是 0（規格：僅 L1 不同才退出 1），故 P2 驗收**不能只看退出碼**，須逐題看三層表格並套用上述規則（P2 任務書應要求或提供 `--strict-l2` 之類的套用規則）。**harness 指令必須逐字重用**：`--arms M4 --runs 1 --query-timeout-s 600 --allow-shared-judge` 加報告136 §2 的 5 個 `--doc-ids` 範圍（完整指令見報告136 §2）；K 臂單題實測 53–329 秒。**已知限制**：不覆蓋「種子字面→語意 fallback」路徑（題庫所有 `alias_mapping` 題皆 `gist`，被資格檢查排除）；共用 judge 的 pilot 設定；Neo4j 有既有的「不存在 relationship type」warning notification（不影響結果）。**P0 回歸網至此完整**（pytest 1309＋相依快照＋K 臂凍結快照）。**下一步：P2（拆 `routers/agent.py`）**。

## 2026-09-29（報告133）：X1-A（failed 狀態黏性修復）任務書，已完成並 push

使用者同意 X1 採**選項一**（`failed` 黏性至全量完成才轉 `completed`，不新增欄位）。[報告133](docs/報告/133_X1-A失敗狀態黏性修復SDD任務書.md)含**兩個獨立 commit**：Commit 1＝X3-A 收尾簡化（移除 `_RowcountTrackingConnection` 包裝類別，行為零變動，SQL 軌跡逐字相同驗收）；Commit 2＝X1-A 修復（**有意的行為變更**，P1 之後第一個）。**Production 修改只有 `state/document_sm.py` 的一格**：`FAILED + CHUNK_COMPLETED_PARTIAL`：`PROCESSING`→`FAILED`（其餘 24 格不變；`FAILED + FULL → COMPLETED`、RESET／REASSIGN→PENDING 保持），因 P1 已把賦值集中到 `_transition_extraction()`；另微調 `record_chunk_completed` 的 docstring（193-203 行原本聲稱「不再覆寫 failed」，修復後才與行為一致）。驗收方式因是行為變更而不同：**5×5 前後行為矩陣恰有一格不同**、**記錄快照差異須完全符合預期（唯一預期差異＝X1 序列那一步）**、**6 個離線重排路徑測試**（`enqueue` 重排／`rebuild_from_records`／trusted restart 不自動重試 failed（鎖定現況）／`build_graph` 不略過 failed／RESET 與 REASSIGN 仍能清除 failed）證明可恢復路徑通暢；既有測試僅允許改動 X1 那一個（並改名）。Claude 三項故意破壞（格改回、偷加賦值、FULL 也黏性）。成果報告 134。**狀態：✅ 已驗收通過（Commit 1 `cce9947`＋Commit 2 `b400614`，報告134）並 push。** **Commit 1**（X3-A 收尾）：移除 `_RowcountTrackingConnection` 包裝類別，改為 `cursor = conn.execute(...)`／`cursor.rowcount`，SQL 軌跡（14 操作／90 條）用自己的腳本在最終 HEAD 上與基準逐字相同。**Commit 2**（X1-A，有意的行為變更）：production 修改只有 `state/document_sm.py` 一格（`FAILED + CHUNK_COMPLETED_PARTIAL`：`PROCESSING`→`FAILED`，其餘 24 格不變）＋註解＋`record_chunk_completed` 的 docstring；`DOCUMENT_TRANSITIONS` 相較修改前恰一格不同。**記錄快照差異**（Claude 自己的腳本，7 情境全欄位比對）恰有 **1 個**差異：情境 1 第 3 個操作（X1 序列）`extraction_status` `processing`→`failed`，其餘逐字相同（註：原快照腳本內建 X1 現況斷言 `== "processing"`，修復後必須拿掉才能產出快照）。被改動的既有測試僅兩處：X1 測試改名為 `test_failed_stays_failed_on_partial_completion`，以及 `test_record_chunk_completed_does_not_falsely_complete_when_a_lower_index_is_missing`（起點確實有 `mark_extraction_failed`，`processing`→`failed`）。新增 `tests/state/test_x1a_retry_paths.py` 6 個重排路徑測試，證明可恢復路徑通暢：`enqueue` 重排／`rebuild_from_records` 補缺口後皆最終 `completed`；trusted restart 不自動重試 failed（既有行為，已鎖定）；`build_graph` 不略過 `failed` 文件；RESET／REASSIGN 仍清除 `failed`。**獨立完整回歸 1304 passed**（＝1298＋新增 6）。**三項故意破壞全部被抓到**：(a) 格改回 `PROCESSING` → 4 個測試失敗；(b) `record_chunk_completed` 偷加賦值 → 守門測試精確指出第 265 行；(c) `FAILED + FULL` 也黏性 → 2 個重排路徑測試失敗（`assert 'failed' == 'completed'`）。還原後 198 個相關測試通過。**回歸基準更新為 1304。** **已知後果（預期）**：修復後文件可能停在 `failed` 而無人重排——這是設計預期的訊號，需由 `enqueue`／`build_graph`／untrusted rebuild／重新歸屬處理；trusted restart 仍不自動重試 failed chunk（既有行為未動）。KG#4 全為 `completed`，不受影響。
**X1／X3-A 全部收尾。仍未做（另案）**：X3-B／X3-C（呼叫端檢查回傳值／可證明不應缺失處 raise，須先為 `extraction_worker.py:146-148` 的 `mark_extraction_failed` 做 safe wrapper 保留原例外）；`update_status()` 任意→任意未收窄。**下一階段：B（P2 拆 `routers/agent.py`，1,904 行）**，驗收要求「凍結評測逐字相同」，**需先決定「固定 5 題 K 臂評測快照」**（Neo4j＋Ollama、WSL 記憶體風險，我不會自己啟動）。

## 2026-09-29（報告131）：X3-A（缺失目標警告日誌）任務書，已完成並 push

使用者選定「依建議 (1)」：先 X3-A、再 X1-A，兩者**各自單獨 commit／任務書**。[報告131](docs/報告/131_X3-A缺失目標警告日誌SDD任務書.md)：只新增 WARNING 日誌，**回傳值、例外、控制流、SQL 文字零變動**。範圍 6 個函式：`document_record_service` 的 `set_svo_chunk_total`／`reset_extraction_progress`／`record_chunk_completed`／`mark_extraction_failed`／`update_normalization_progress`（`read_record` 回 None 時），與 `task_queue_service.update_status`（`rowcount==0` 時）；**明確不加**：`set_document_vector`（快取欄位，無記錄檔屬常態，加了只是雜訊）。驗證：新增 `tests/services/test_missing_target_warnings.py`（先 RED）＋**沿用前兩批的機械證據**（SQL 軌跡逐字相同、記錄快照逐字相同）＋回歸 1289＋新增測試數＋相依快照邊數不變；Claude 兩項故意破壞（刪一則警告→新測試失敗；改缺失回傳值→既有 no-op 測試失敗）。成果報告 132。單段執行（風險低）。**狀態：✅ 已驗收通過（`ed7c2c5`，報告132）並 push。** Claude 獨立驗證：兩個 service 檔的 diff 全為新增行（`document_record_service.py` 5 則警告位於各自 `return None` 之前；`task_queue_service.py` 的 `update_status` 在 `rowcount==0` 時警告）；**SQL 軌跡**（14 操作／90 條）與**記錄快照**（7 情境）用自己的腳本副本重跑皆與基準逐字相同；缺失列與存在列的 SQL 形態一致（`BEGIN`／`UPDATE`／`COMMIT`），rowcount 讀取沒有多產生 SQL；警告訊息中狀態顯示字面值（`status=completed`）；**獨立完整回歸 1298 passed**（＝1289＋新增 9）；相依快照 cycles=0、420 邊不變。故意破壞：(a) 刪 `mark_extraction_failed` 的警告 → 新測試精確失敗（`assert 0 == 1`）；(b) `update_status` 缺失時改 `return 0` → **新增**的 `test_update_status_missing_row_logs_warning_and_returns_none` 失敗（`assert 0 is None`）——**更正**：任務書 A6(b) 預期的「既有 no-op 測試會失敗」不準確，既有 `test_set_status_on_missing_row_is_silent_noop` 沒有斷言回傳值，這個保護是新測試補上的；兩者還原後 178 個相關測試通過。**回歸基準更新為 1298（帶 `--ignore=tests/core/test_embedding_migration.py`）。** 小缺口：Codex 為讀 `rowcount` 新增了 12 行 `_RowcountTrackingConnection` 包裝類別（為了讓 diff 保持純新增），任務書其實寫的是簡單的 `cursor = conn.execute(...)`（兩處要求互相矛盾，Claude 疏漏）；行為完全正確，**待簡化**——併入 X1-A 任務書，作為獨立的第一個小 commit（`refactor(task_queue): 簡化 rowcount 讀取`），以 SQL 軌跡逐字相同＋既有測試驗證。**下一份：任務書 133＝X1-A**（`failed` 黏性至全量完成，需同步更新 `tests/state/` 鎖定測試並驗證失敗 chunk 可被重排）。

## 2026-09-29（報告129）：X1／X3 既有缺陷影響評估任務書，已完成並 push

使用者同意「先 A（修 X1／X3）後 B（P2 拆 `agent.py`）」，並沿用先評估再決定修法。[報告129](docs/報告/129_X1_X3既有缺陷影響評估SDD任務書.md)：**只讀評估**，不修復。回答 Q1–Q8（X1 讀取端行為差異與真實觸發路徑、X1 三種語意選項 A黏性failed／B新增failed集合欄位／C只改docstring、X3 呼叫端逐一分析含 `extraction_worker.py:146-148` 的 except 內 raise 是否遮蔽原例外、X3 四種修法 A只加warning／B回傳契約／C部分raise／D全raise、依賴 X1／X3 的既有測試、SM-2 是否有同型缺陷、與 A8 B3 的關聯）；**對 KG#4 真實資料做唯讀掃描**（65 份 `_record.json` 的狀態與完成集合一致性、`task_queue.db` 以 `mode=ro` 開啟比對佇列與記錄）判斷 X1／X3 是否已造成真實不一致；離線重現＋選項A的純文字推演。成果報告編號 130。之後由使用者選修法，再寫實作任務書（修 X1／X3 須同步更新 `tests/state/` 鎖定測試，各自單獨 commit）。**狀態：✅ 已驗收通過（`0820b92`，報告130）並 push。** Claude 獨立驗證：真實資料唯讀掃描數字與報告完全相同（KG#4：65 份 `_record.json` 全 `completed`、狀態／完成集合不一致 0、`task_queue.db` 3307 列全 `completed`、大小與 `mtime_ns` 與 Codex 記錄相同）；`kg-runtime` 最新修改時間 2026-09-22，未被本任務動過。**結論**：KG#4 目前**沒有** X1／X3 留下的不一致，但這只證明「目前快照乾淨」，不能證明歷史上沒發生過。X1 讀取端：`build_graph`／`_reconcile_doc` 對 `failed` 與 `processing` 都視為非 completed 而重排，只有 `completed` 被略過，API 會直接看到不同字串；真實觸發路徑「某 chunk failed、另一 chunk 成功」**可發生**。X3 關鍵風險：`extraction_worker.py:146-148` 的 `mark_extraction_failed` 在 `except` 內，直接改 raise 會使新例外成為主要例外，且 `run_extraction_worker()` 迴圈沒有外層保護，可能中止整個 worker——**不可未包裝直接 raise**。Codex 的修法傾向（Claude 同意）：**X3-A（只加 warning，控制流零變動）→ X1-A（`failed` 黏性至全量完成，不改資料格式）→ 針對可證明不應缺失的點才 X3-C（需先做 safe wrapper 保留原例外）**；X1-B（新增失敗集合欄位）與 X3-D（全面 raise）屬大型變更，不與第一個修復 commit 混合。**回歸基準說明**：帶 `--ignore=tests/core/test_embedding_migration.py` ＝ **1289**；不帶則 ＝ **1293**（被排除的 4 個 embedding migration 測試也全數通過）。之後任務書寫明採用哪個指令，驗收以我獨立的 **1289（帶 ignore）** 為準。**待使用者決定修法後，寫實作任務書（X3-A、X1-A 各自單獨 commit，並同步更新 `tests/state/` 鎖定測試）。** **修完 X1／X3 後才進 P2；P2 之前須先決定「固定 5 題 K 臂評測快照」（需 Neo4j＋Ollama、WSL 記憶體風險）。**

## 2026-09-29（報告126）：M2 P1 第三批（SM-1 單一轉移入口）任務書，已完成並 push

使用者同意第三批，且 **X1 決定「不修，另案」**（整理與改行為不放同一個 commit）。[報告126](docs/報告/126_M2_P1第三批_SM1單一轉移入口SDD任務書.md)：`document_record_service` 內 6 處 `extraction_status`／`normalization_status` 賦值集中到兩個私有轉移入口（`_transition_extraction`／`_transition_normalization`，由 `state/document_sm` 轉移表決定結果）；**行為零變動**（X1 `failed→processing`、X3 缺記錄靜默回 None、`update_normalization_progress` 任意→任意全保留）。特別要求：`update_normalization_progress` 傳入非法 status 現況是直接寫入，改用 Enum 建構會提早拋 `ValueError`＝行為變更，第一段須提出保持現況的做法。驗證：`_record.json` **逐欄快照比對**（`assigned_at` 正規化）＋新增**結構性守門測試**（賦值只能出現在兩個轉移函式內）＋Claude 兩項故意破壞（映射改錯、偷加賦值）。兩段：第一段報告127（只讀）→**停下等 Claude 核准**→第二段報告128。**之後另案**：X1／X3 修復（單獨 commit、需評估對重啟重排佇列的影響）。**狀態：第一段已審核通過並 push（`3e8c1c5`，報告127：6 個寫入點全在表內、快照基準 7 情境／33 操作、Claude 獨立重跑 `scenarios` 完全相同＝確定性成立）。已核准第二段，附加更正：報告127 §3.2 建議的相容分支 `if target not in valid_targets` 對 `REPARSE_CHUNK_COUNT_CHANGED`（`target=None`）也成立，會把 `normalization_status` 寫成 `None`——第二段必須改為 `if event is NormalizationEvent.SET_STATUS and target not in valid_targets`。第二段已驗收通過（`c6f7e35`＋回填 `0b7de55`，報告128）並 push。** `document_record_service` 內 6 處狀態賦值集中為兩個私有轉移入口 `_transition_extraction`／`_transition_normalization`（由 `state/document_sm` 轉移表決定結果）；相容分支更正已套用（`event is SET_STATUS and target not in valid_targets`）；公開函式簽章、回傳、例外、欄位更新順序全部不變，X1／X3 保留。Claude 獨立驗證：**記錄快照逐字相同**（自跑腳本，7 情境，`scenarios` 與 `time_normalization` 兩欄）；**兩項故意破壞**：(a) `record_chunk_completed` 的 FULL／PARTIAL 事件對調 → 15 個測試失敗；(b) 在 `set_svo_chunk_total` 偷加一行 `record.extraction_status = "processing"` → 結構性守門測試失敗並精確指出 `set_svo_chunk_total` 第 205 行；兩者還原後 183 個相關測試通過；**獨立完整回歸 1289 passed**（＝1286＋新增 3）；相依快照 151 模組／420 邊／0 循環，新增邊 `document_record_service → state.document_sm`，`state` 零對外依賴。回歸基準更新為 **1289**。
**P1（SM 化）三批全部完成**：第一批 `state/` Enum＋現況轉移表＋對等測試（103 個）、第二批 SM-2 詞彙統一（SQL 零變動、SQL 軌跡逐字相同）、第三批 SM-1 單一轉移入口。**已知未修（另案）**：X1（`failed→processing` 覆寫失敗）、X3（缺記錄／缺列靜默 no-op，呼叫端不檢查回傳）；`update_status()` 任意→任意仍未收窄；import 順序（`from state...` 排在 `from services...` 前）待統一整理。**下一階段 P2（拆 `routers/agent.py`）之前，須先決定「固定 5 題 K 臂評測快照」**（需 Neo4j＋Ollama、有 WSL 記憶體風險，P2 驗收要求「凍結評測逐字相同」）。**

## 2026-09-29（報告123）：M2 P1 第二批（SM-2 佇列詞彙統一）任務書，已完成並 push

使用者同意進第二批並要求「先出替換對照表、Claude 審過才准實作」。[報告123](docs/報告/123_M2_P1第二批_SM2佇列詞彙統一SDD任務書.md)：**設計發現**——SM-2 的狀態語意寫在**原子 SQL** 裡（`claim_next_pending` 的 `UPDATE…RETURNING` 是多 Worker 併發安全的關鍵），**不可**改成 Python 端讀後寫的 `transition()`；Python 端狀態寫入只有 `extraction_worker.py` 的 4 個 `update_status()` 呼叫。故第二批僅做「詞彙統一」：4 個呼叫改用 `state.task_sm.TaskStatus`（`StrEnum`，值不變）、`update_status` 型別標註放寬；**SQL 文字零變動**，並以「SQL 執行軌跡逐字比對」驗證；同時是 `state/` 的第一個 production import（驗接線無循環）。**SM-1 的單一 `transition()` 入口（JSON 記錄、無併發原子性問題）才是 P1 實質內容，留第三批。** 兩段：第一段出報告124（替換對照表＋SQL 軌跡基準腳本，只讀）→**停下等 Claude 核准**→第二段實作（報告125）。**狀態：第一段已審核通過並 push（`b5497a5`，報告124：15 個寫入點盤點、5 項替換、7 項明確不替換；基準 1286 passed；SQL baseline 14 操作／90 條軌跡）。Claude 獨立重跑軌跡腳本，`operations` 與 `trace` 兩欄與 Codex 基準完全相同＝確定性成立（注意 JSON 含 `repo`／`script` 路徑欄位，不可直接比整檔雜湊，只比這兩欄）。已核准第二段，附加條件：after 比對腳本必須改傳 `TaskStatus.X` 成員（baseline 傳字串，若 after 也傳字串則必然相同、失去意義），且 after 須輸出到不同檔名不得覆寫 baseline。第二段已驗收通過（`58548d4`，報告125）並 push。** 4 個 worker `update_status` 呼叫改傳 `StateTaskStatus.X`、`update_status` 型別標註放寬為 `TaskStatus | StateTaskStatus`，SQL 文字零變動，是 `state/` 的第一個 production import（`extraction_worker`、`task_queue_service`）。Claude 獨立驗證：**SQL 軌跡逐字相同**（自寫 after 腳本，所有狀態參數改傳 `TaskStatus.X`，14 操作／90 條軌跡與基準相同，SQLite 綁定值仍為原字面值）；**故意破壞驗證**（worker 的 `COMPLETED` 改成 `FAILED` → `test_process_one_success_merges_triples_and_marks_completed` 失敗，還原後 141 passed）；**獨立完整回歸 1286 passed**；相依快照 151 模組／419 邊／0 循環，production 只有兩處 import `state`，`state` 仍零對外依賴。小備註：新增的 `from state...` import 排在 `from services...` 之前（isort 順序，不影響功能，之後統一整理）。
**下一步（P1 第三批）**：SM-1（`document_record_service`，JSON 記錄、無併發原子性問題）——這才是「單一 `transition()` 入口」的實質內容：把 `reset_extraction_progress`／`record_chunk_completed`／`mark_extraction_failed`／`append_assignment` 的狀態寫入集中，行為不變，以 `tests/state/test_document_sm.py` 對等測試為回歸網；X1／X3 是否另案修復屆時再決定。**

## 2026-09-29（報告121）：M2 P1 第一批（選項C）任務書，已完成並 push

使用者選定 P1 切分**選項 C**：先只新增、不替換任何寫入。[報告121](docs/報告/121_M2_P1第一批_狀態機Enum轉移表與特性測試SDD任務書.md)：新增 `state/`（`StrEnum`＋事件＋**照現況寫**的轉移表＋純查表函式，零依賴、不接線）＋`tests/state/` 對等測試（對每個「來源狀態×事件」呼叫**真實既有函式**，與表逐格比對；X1／X3 明確鎖定為既有行為）。**不得修改任何既有 production 檔案與測試**。回歸須 1183＋新增測試數 passed。成果報告編號 122。之後兩批：第二批替換 SM-2（task_queue）寫入、第三批替換 SM-1（document_record）寫入，屆時再決定 X1／X3 是否另案修復。**狀態：✅ 已驗收通過（`c9592d3`，報告122）並 push。** 新增 `state/{__init__,document_sm,task_sm}.py`＋`tests/state/`（103 個測試）。Claude 驗證：轉移表逐格對照報告120（文件 25 格、佇列 24 格）；對等測試確實呼叫真實既有函式；production 無人 import `state`、`state/` 只 import 標準庫 `enum`；**故意破壞驗證**（把 `FAILED+PARTIAL` 與 `COMPLETED+ENQUEUE` 兩格改錯）→ 3 個測試失敗，還原後 103 passed；**獨立完整回歸 1286 passed（83s）＝1183＋103**，回歸基準更新為 **1286**。Codex 環境有 3 個既有 UMAP 測試（`test_cluster_service.py::TestReduceDimensionality`）超過 10 分鐘無輸出，在 Codex 環境屬環境限制，Claude 環境正常完成——**今後驗收以 Claude 獨立完整回歸為準**。相依快照 cycles=0、`state` fan-in=0。
**下一步（P1 第二批）**：替換 SM-2（`task_queue_service`）寫入為呼叫 `state/task_sm` 的轉移表／單一入口，行為不變，靠 `tests/state` 對等測試當回歸網；X1／X3 屆時再決定是否另案修。

## 2026-09-29（報告119）：M2 第一步 P1（SM 化）前置——狀態機現況轉移盤點任務書，已完成並 push

使用者同意（依建議）：M2 先做 P1（報告97 §6.5），因範圍小（狀態寫入約 18 處、5 個檔案）、不需凍結評測快照、且能根治 A8 那類靜默 no-op。分兩步：**119 只讀盤點（本任務）→ 121 實作**（Enum＋轉移表＋單一 `transition()`，先寫特性測試、行為不變、回歸須 ≥1183 passed）。[報告119](docs/報告/119_M2_P1前置_狀態機現況轉移盤點SDD任務書.md)：盤點 SM-1（`extraction_status`）、SM-1b（`normalization_status`）、SM-2（`task_queue.status`）的所有寫入／讀取點與**現況實際轉移矩陣**，並用離線特性重現產出 P1 特性測試的黃金依據；三個待驗證疑點 X1（`record_chunk_completed` 是否靜默覆寫 `failed`）、X2（`pending_upload` 在 SM-1 是否可達）、X3（靜默 no-op 寫入點）。成果報告編號 120。**「固定 5 題 K 臂評測快照」維持 (a)：P1 完成後、P2 拆 `agent.py` 之前再決定**（需 Neo4j＋Ollama、有 WSL 記憶體風險，不擋 P1）。**狀態：✅ 已驗收通過（`f9d4e6f` 報告120＋`703c32a` 回填任務書）並 push。** Claude 獨立驗證：SM-1 production 寫入 grep 與報告 Q1 完全吻合（`document_record_service.py:97,157,185,211,223,250`）；重跑 Codex 離線腳本，X1／X3／非法轉移皆重現。
- **X1 成立**：`mark_extraction_failed()` 後對另一 chunk 呼叫 `record_chunk_completed()`，`failed → processing`（`document_record_service.py:211-213` 無條件覆寫，與其 docstring「不再覆寫失敗」不一致）。**未修，另案**。
- **X2 不成立**：`pending_upload` 只由 SM-2 佇列使用，SM-1 production 從不寫入。
- **X3 成立**：5 個記錄寫入函式＋`update_status()` 對不存在目標靜默回 None，呼叫端均未檢查回傳。**未修，另案**。
- `update_status()` 對既存列是任意→任意（`completed→processing`、`failed→completed`、`pending→completed` 皆被接受）；`update_normalization_progress` 無 production 呼叫者。
- **P1 轉移表必須容許的「不合理」轉移**（行為不變）見報告120 §5.2 共 6 項；P1 切分選項 A（先 SM-2）／B（先 SM-1）／C（先只加 Enum＋特性測試、再分批替換）見 §5.3，**待使用者裁示**。
- 附註（Claude 疏漏）：報告119 §3 禁止修改其他檔案、交接指令卻要求填回填區，兩者矛盾；Codex 依交接指令填了回填區（僅該區 3 行），接受。今後任務書統一把「回填區」列為允許修改。

## 2026-09-29（報告117）：build_graph 清空前虛擬成員防護任務書，已完成並 push

使用者同意「先做 a（風險1防護性最小修補）再 c（M2 重構第一步）」。[報告117](docs/報告/117_build_graph虛擬成員清空前防護SDD任務書.md)：`build_graph(force_rebuild=True, doc_ids=None)` 在清空 Neo4j **之前**偵測 manifest 成員缺 `_record.json`，有就拋 `VirtualMembersNotRebuildableError`（router→409）、不清空；非 force 時僅 WARNING。先寫失敗測試→修→回歸須 1183 passed。**只擋住，不支援虛擬成員**（留 M2）。成果報告編號 118。**狀態：✅ 已驗收通過（`8803184`，報告118）並 push。** Claude 離線腳本三情境驗證：虛擬 KG＋force＝拋 `VirtualMembersNotRebuildableError`、0 次 `DETACH DELETE`、0 次抽取；虛擬 KG 非 force＝無錯、不清空；實體 KG＋force＝行為不變（1 次清空、1 次抽取）。回歸基準更新為 **1183 passed**（取代 1180）。**風險1 已堵住（僅防護，非支援）**；`doc_ids` 局部重建仍靜默略過虛擬成員（僅 WARNING）、`ArticleStructureLossError` 在 router 仍回 500、風險2–4／匯入腳本／評測工具的虛擬成員支援留 M2。**下一步＝(c) M2 重構第一步**（以報告108 相依快照挑拆分目標）。

## 2026-09-29（報告115）：虛擬成員盲點追查任務書，已完成並 push

A8 完成後的殘留項合併成一份只讀追查：[報告115](docs/報告/115_虛擬成員盲點追查SDD任務書.md)。盤點所有「以 KG 資料夾內容推論成員」的位置（`build_graph()`、`task_queue_service` 重建、`classify_service`、`_kg_source_charset`、匯入腳本），重點確認 **`build_graph(force_rebuild=True)` 先清空 Neo4j 卻不重抽虛擬成員的資料損失路徑**，並確認 KG#4 屬實體還是虛擬。成果報告編號 116。純只讀、不修復。**狀態：✅ 已審核通過（`fb5d8a7`，報告116）並 push。** 結論（各項均為程式路徑＋離線 mock 重現，**未對真實資料驗證**）：
- **風險1／資料損失**：`build_graph(force_rebuild=True, doc_ids=None)` 先 `DETACH DELETE` 清空該 KG，但虛擬成員（manifest-only）不在 `iterdir()` 的 target 內、輸出子目錄又無 `_record.json` 而被略過 → 重抽 0 件，router（`routers/knowledge_graph.py:47-52`）無任何確認或防護。**在修好之前，對任何含虛擬成員的 KG 不要呼叫 `force_rebuild=True`。**
- 風險2：`task_queue_service.rebuild_from_records()` 掃不到虛擬成員，佇列遺失後無法還原其未完成任務。
- 風險3：三個 `import_*`／`create_clean_*` 腳本在虛擬模式重跑，未傳 `move_physical=True` 也未傳 `kg_folder`，會踩 A8 同型問題。
- 風險4：`_kg_source_charset()` 只讀 `kg_folder/*/original.md`，虛擬 KG 回空集合＝全轉簡繁（削弱報告25 發現4 的選擇性保護）；`routers/agent.py:1631` 傳的是 `workspace/<kg_id>`。
- 中：eval／readiness／baseline／sweep 工具的 scope resolver 在虛擬 KG 上同樣看不到成員。
- **OK**：`classify_service` 的 manifest／prototype／count 已正確納入虛擬成員。
- **Q8 ✅ 已確認（2026-09-29，Claude 唯讀 `ls` 驗證）：KG#4 是純實體目錄，不受上列盲點影響。** 實際位置＝`D:/Users/666/Desktop/kg-runtime/236903cf-055a-40a8-8923-b9d06601f3b7`（由 `.claude/worktrees/kg-reextract/.env` 的 `WORKSPACE_DIR` 指定；主 checkout 的 `workspace/` 與本 worktree 都沒有 KG#4）。65 個文件子目錄，**每一個都同時有 `_record.json`、`original.md`、`svo_index.json`**（65/65/65），根目錄**沒有 `_members.json`**。因此對 KG#4：`build_graph()`（含 `force_rebuild`）、`rebuild_from_records()`、`_kg_source_charset()` 都看得到全部成員，風險1–4 **目前對現有生產資料不成立**。盲點只在「今後透過網頁上傳／分類（虛擬歸屬預設）建立的新 KG」上暴露。另：以 Glob 遞迴搜尋 `**/_members.json`，`D:/Users/666/Desktop/kg-runtime` 與主 checkout `workspace/`（含另 4 個 KG 資料夾 `0bd40837…`、`238753a1…`、`2ae9d28b…`、`deb24e7c…`）**皆找不到任何 `_members.json`**＝**目前本機沒有任何含虛擬成員的 KG**，盲點屬「潛在」而非「已發生」。修正緊迫度因此降為：在有人透過網頁上傳／分類建立新 KG 之前修好即可；在那之前不會有資料損失。
- 修正方向 5 項見報告116 §5，**待使用者裁示，尚未實作**。

## 2026-09-29（報告110＋111）：A8 修正與 05 §5.7.1 更新任務書，交 Codex 執行

使用者同意 A8 採報告109 §5 方向 1（＋方向4），順序：先 A8 再文件。
- [報告110](docs/報告/110_A8虛擬歸屬抽取路徑修正SDD任務書.md)：程式修正（僅 `classify_service`／`svo_service`／`extraction_worker`／`routers/staging`＋新測試）。契約：輸入在文件實際資料夾、SVO 輸出寫 `kg.folder_path/<doc>`、記錄檔回寫原文件資料夾（新增 `resolve_document_folder`）。**另發現隱性 bug B3**：worker 的 `record_chunk_completed`/`mark_extraction_failed` 在虛擬模式下對不存在的記錄靜默回 None。先寫失敗測試→修→完整回歸須 1178 passed。`build_graph()` 看不到虛擬成員（109 Q6）**不在本任務範圍**，另案。成果報告編號 112。
- [報告111](docs/報告/111_論文05_5.7.1時程表現況更新SDD任務書.md)：純文件，只改 05 §5.7.1 表四處過時敘述（P0d／P0c／P3／P5），須先核實再改。與 110 無檔案重疊。
**狀態（審核結果）**：Codex 已完成兩份（`34d29d1` 報告110／112、`38568ca` 報告111）。111 審核通過。110 程式與規格逐處一致、範圍正確，但 **Claude 獨立重現發現 B3 在真實流程仍未修好**：`resolve_document_folder()` 先判斷 `kg_folder/<doc>` 是否為目錄，而 SVO 輸出寫出後該目錄就存在 → 記錄回寫仍落空（缺陷出自 110 §S3(a) 規格，Codex 已在 112 §4 誠實記錄）。已開 [報告113](docs/報告/113_A8補修_resolver判斷順序SDD任務書.md)（改以 `_record.json` 存在判定；先測後修；成果報告 114；回歸須 1180 passed）。**✅ 補修已驗收通過（`ac17900`，報告113／114）並與 110／111 一併 push**：resolver 改以 `_record.json` 存在判定；Claude 重現腳本確認輸出目錄建立後解析到原文件資料夾；獨立回歸 **1180 passed**（新基準，取代報告108 的 1173）。**A8 完成。** 仍未處理（另案）：`build_graph()` 看不到虛擬成員（報告109 Q6）、`_kg_source_charset(str(kg_folder))` 在虛擬模式下可能讀不到來源、`scripts/import_*` 在虛擬模式下重跑需另案驗證 dest 路徑。

## 2026-09-29（報告106＋107）：M2 前置兩份只讀任務書，已完成並 push

論文對齊系列（報告98–105）查核通過後，依使用者同意的順序進入 M2 前置：
- [報告106](docs/報告/106_M2前置_P0回歸基準SDD任務書.md)：完整 pytest 跑兩次建立測試基準＋新增 `scripts/analysis/import_graph_snapshot.py` 產生模組相依快照（fan-in/out、循環）；成果寫入 `docs/報告/108_M2_P0回歸基準結果.md` 與 `data/analysis/import_graph_20260929.json`。**不含**固定5題K臂評測快照（需Neo4j+Ollama、有WSL記憶體風險，待使用者裁示）。
- [報告107](docs/報告/107_A8虛擬歸屬後抽取路徑追查SDD任務書.md)：只讀追查「虛擬歸屬後 `trigger_extraction()` 以 `doc_folder.parent` 當KG資料夾，但worker到 `kg.folder_path` 找 `svo_index.json`」是否真的對不上（假設待驗證），暫存目錄重現、不碰Neo4j；成果寫入 `docs/報告/109_A8虛擬歸屬路徑追查結果.md`。KG#4由匯入腳本建立、不走此路徑。
兩份皆**不得修改既有檔案、測試失敗只記錄不修復**。
**狀態（已審核通過、已 push）**：
- 報告108（`bccce0d`）：pytest 基準 **1173 passed**（Codex 兩次 82.54s／67.08s，Claude 獨立重跑 65.46s 一致）；相依快照 148 模組／415 邊／**0 循環**；`services.svo_service` fan-in 16；harness→`routers.agent` 耦合已確認。M2 每階段完成後須重跑比對。
- 報告109（`a2fb2c5`）：**A8 判定 `BREAKS`**——虛擬歸屬下 `assign_document_to_kg()` 回傳原資料夾（`classify_service.py:615`），`trigger_extraction()` 以 `doc_folder.parent` 當 kg_folder 寫 `svo_index.json`（`svo_service.py:3641`），worker 卻讀 `Path(kg.folder_path)`（`extraction_worker.py:87`），暫存目錄實測 `_find_chunk()` 回傳 None。`/staging/classify`、`/{filename}/assign`、`/cluster/confirm` 三個網頁入口皆受影響；KG#4（匯入腳本路徑）不受影響。**修正方案僅列選項，待使用者裁示後才另開任務書，尚未實作。**

## 2026-09-29（報告105 已完成並push——論文對齊系列告一段落）

## 2026-09-29（報告105）：04新增「4.12 評測Harness實作」章節，已完成並push

依使用者「繼續」，Claude Code判斷04章缺「評測harness實作」是目前最大的文件缺口——第六、七章所有RQ1結果都建立在此harness上，但04完全沒有章節說明其運作。已把整節內容（臂定義表、逐題執行流程、評分管線、自適應重跑判定、已知量測限制五個子小節）整理自已核實過的[報告95](95_專案節點流程總覽與設計說明.md)§15與[報告97](97_專案目標與BT_SM工作流設計.md)§4.7（皆為早前直接核對程式碼所得），寫成最終版本放進[報告105](docs/報告/105_論文對齊_04新增評測harness實作章節SDD任務書.md)，附加在04檔案最末尾（風險最低的插入方式）。Codex逐字貼上（commit `59c484a`，53行新增/0刪除）。**Claude Code審核A1-A5全數通過**（本次Bash/PowerShell權限檢查暫時無回應，改用Read工具直接讀檔逐字核對4.12.1-4.12.5五個子小節與變更紀錄條目，確認04原有340行內容一字未動），**已push**。

**至此論文對齊系列（報告98-105）全部完成並push**：批次1-4結構重構（B2現況/BT-SM表示法與總覽圖/檢索流程圖/生成流程圖）、guard_profile實作訂正、關係詞彙擴充+檢索trace登記、規則10消歧+簡體詞組修正登記、04評測harness實作章節。**仍待辦（未排入任何任務書）**：04新增「資料維護與修補程序」章節（報告96 §5）、報告96 A8（虛擬歸屬後抽取路徑是否真的斷掉，需實測而非文件修正）、A9（API驗證/Grok provider，份量極小）。
## 2026-09-29（報告103＋104）：兩份SDD任務書已建立，交給Codex執行

依使用者指示「做2（報告96 A2/A3/A6，較短）」完成後，「安排Codex可處理的長任務、可自動檢查接續」，Claude Code一次產出兩份任務書：

**[報告103](docs/報告/103_論文對齊_關係詞彙擴充與檢索trace登記SDD任務書.md)（短，兩處純插入）**：03§3.3補per-KG可擴充關係詞彙（RelTypeExtension，報告77）登記；04§4.7.1補檢索trace（include_retrieval_trace，報告62 T0）登記。A2（共用生成堆疊）已由報告101一併登記，不再需要。

**[報告104](docs/報告/104_論文對齊_規則10與簡體詞組修正登記_長任務SDD任務書.md)（長，三步驟、Codex自主依序完成、每步自我檢查）**：03§3.1.3補規則10（複合法規句條件複述，報告65，commit `35f95ab`）登記，**含關鍵消歧**——03§3.1.4附近已有一段提到「規則10」，但那是報告32時期**另一次、更早、失敗擱置**的嘗試，本次登記的是**後來獨立成功上線**的版本，任務書已在插入文字開頭明確寫出消歧說明並提醒Codex不要誤刪既有段落；04§4.4.3補簡體詞組修正（`_fix_known_simplified_compounds()`）登記；03變更紀錄補一筆。每步驟附具體自我檢查條件（diff形狀、grep計數），設計成Codex完成三步後才回報一次，不需逐步等待確認。

**報告103已完成並push**（commit `9cda598`，Claude Code審核A1-A5全數通過）。Codex正確識別報告104的起始HEAD條件已被報告103變動，**主動停下未執行**，等候另行授權新HEAD後才接續——這正是report104設計「自我檢查」機制的預期行為。

**報告104已完成並push**（commit `03244ca`，Claude Code審核A1-A7全數通過）。Codex自我檢查誠實抓到2處落差，經Claude Code核對後確認**皆屬任務書本身描述不精確、非Codex工作有誤**：①任務書驗收條件「規則10」grep應恰好2處，但新段落本身就3次提及該詞（加既有1處＝4次字串出現，因首段寫成單一長行，grep行數算出3行）；②任務書描述的「插入點前一段文字」有誤（Claude Code當初讀取時漏看中間一小段「現況訂正2026-08-23」既有內容），但Codex正確抓住「插在3.1.3§a標題前」這個真正意圖，放對了位置。兩處皆非內容錯誤，逐字比對§2規格完全相符。**批次1-4結構重構＋報告102/103/104登記全部完成並push**。
## 2026-09-29（報告102）：論文對齊——03 §3.9.4 guard_profile 實作訂正 SDD 任務書已建立，交給 Codex 執行

依使用者「依照建議繼續」，結構性重構四批（報告98-101）完成後，進入報告96盤點出的機制登記項目。**過程發現一個重要澄清**：報告96 A1（圖片OCR管線「完全無記載」）經查證是**假陽性**——`parser/README.md` 已完整記載該管線（含BT圖、文獻引用、使用範例），符合論文既有慣例（PARSE/VEC節點皆指向程式碼旁README、不重複展開至論文正文，見03 §3.1開頭明文原則），**不需要、也不應該**補進03/04正文，此finding已作廢（未另開task book，因為沒有東西要做）。

改選A7（守衛設定 `03§3.9.4`）作為下一個登記目標：Claude Code查證發現該節現有設計描述（具名`guard_profile`選擇器如`"cjk-legal-enumeration"`）與實際落地（報告76 `GuardConfig`）形狀不同——實作是五個獨立token清單欄位，無具名選擇器，且兩個既有domain pack皆未覆寫、行為與改造前相同。已把訂正段落寫成最終版本放進[報告102](docs/報告/102_論文對齊_守衛設定檔guard_profile實際落地登記SDD任務書.md)，Codex逐字貼上即可。**本批純插入**（保留原設計段落、附加✅訂正），驗收要求diff只能有新增行。**狀態：等待Codex執行→Claude依§5驗收A1-A5審核→通過才push**。

Codex逐字貼上（commit `2fee646`）。**Claude Code審核A1-A5全數通過**（03系統設計檔僅2行新增、0刪除，原設計段落與§3.9.5後續內容皆未動），**已push**。

**待辦（未在本批處理，留供後續）**：03§3.1.3的「規則10」有一處歷史記載描述**較早、已失敗/擱置**的規則10嘗試（報告32era，「未落地」），與後來報告65成功落地的規則10是**不同設計、只是編號恰好相同**——若要登記報告65的規則10，需要在新段落中明確澄清「這是第二次、不同的嘗試」避免與既有記載混淆，本次因該區塊密度極高、風險較高而暫緩，列為下一個候選批次。
## 2026-09-29（報告101）：論文對齊批次4 已完成並push（03 §3.6 生成流程現況BT圖）——結構性重構批次全部完成

依使用者「依照建議繼續」，批次4在03 §3.6補上「目前實際運作的生成流程」BT圖（分解/接地核對/G2查表覆核/定向修正或限制性重生成/列舉完整性檢查），與既有RQ3目標設計圖（多輪回補檢索，已正確標註未實作）明確區分。Claude Code把新段落與新Mermaid圖寫成最終版本放進[報告101](docs/報告/101_論文對齊批次4_生成流程現況BT圖SDD任務書.md)，Codex逐字貼上（commit `73e544c`）。**本批是純插入，Codex完美達成「diff只能有新增行、不能有刪除行」的最嚴格驗收要求**（03_系統設計與方法論.md：26 insertions、0 deletions）。**Claude Code審核A1-A7全數通過，已push**。

**批次1-4（報告98/99/100/101）至此全部完成並push**：B2現況與過時狀態修正、BT/SM表示法約定與總覽圖、檢索流程BT圖與04順序修正、生成流程現況BT圖。**論文對齊中涉及結構設計判斷的部分告一段落**；報告97 §5.3規劃的後續批次（批次5起：01/04/05/00等章節回寫報告53-94期間新增機制、04新增評測實作與資料維護程序兩節）多為照固定格式補登記，待使用者指示是否繼續。
## 2026-09-29（報告100）：論文對齊批次3 已完成並push（03 §3.2 §b 檢索流程圖+04 §4.7.2 順序修正）

依使用者「依照建議繼續」，批次3修正檢索流程的錯誤敘述與缺漏圖示：04 §4.7.2 原寫「先BFS再Fact檢索」，已查證（報告95§11直接核對程式碼）實際順序是「種子→Fact檢索（範圍錨定種子文件）→推導文件範圍→BFS範圍下推→關係型別後篩→範圍兜底過濾」；03 §3.2 §b的圖原只畫BFS、完全沒畫Fact檢索與範圍推導。Claude Code把新說明段落、完整替換Mermaid圖、04修正段落寫成最終版本放進[報告100](docs/報告/100_論文對齊批次3_檢索流程BT圖與04檢索順序修正SDD任務書.md)，Codex逐字貼上（commit `f7f4648`）。**Claude Code審核A1-A7全數通過（逐行比對diff，內容與規格完全一致、無偏離），已push**。

內容：03 §3.2 §b圖新增`FACTSEARCH`（Fact向量檢索）、`SCOPE`（推導文件範圍）、`FILTER`（範圍兜底過濾）、`RELLINK`（連到§c關係連結）四個節點；移除與3.6節不一致的`CTX`/`SORT`尾端節點（只以三元組為輸入，未涵蓋事實清單組裝實際需要的Fact結果），完整組裝流程圖留給下一批補進3.6節；04 §4.7.2第一段改寫為正確順序。03變更紀錄補一筆。**這次任務書指令已修正上次基準commit筆誤的問題**（不寫死hash，改讓Codex自行核對HEAD），此次順利無誤。**下一批（批次4：03 §3.6補「目前實際運作的生成流程」BT圖，與規劃中的精煉迴圈圖分開畫）待使用者指示。**

## 2026-09-29（報告99 批次2 完成並push）
## 2026-09-29（報告99）：論文對齊批次2 已完成並push（03 §3.1 BT/SM表示法+總覽圖）

依使用者確認的分批順序，批次2是結構設計（03 §3.1 新增「BT／SM 表示法約定」段落＋改寫系統總覽圖，用虛線標示規劃中節點）。因涉及設計判斷，Claude Code 把段落文字與完整 Mermaid 圖都寫成最終版本放進[報告99](docs/報告/99_論文對齊批次2_BTSM表示法約定與總覽圖SDD任務書.md)，Codex 逐字貼上（commit `a998bff`）。**Claude Code 審核 A1-A6 全數通過（逐字精確比對diff，無偏離規格），已push**。過程中一次基準commit筆誤（任務書寫定`f560e24`、實際push後變成`f506323`，Codex正確攔下並回報，Claude Code即時給修正後指令重貼，未造成誤改）。

內容：新增BT（一次執行流程）／SM（長期實體生命週期）表示法約定，規則「BT改狀態只能發SM事件」；系統總覽圖`ROUTE`（ConceptNode路由）、`REFINE`（自我精煉迴圈）、`CONCEPTIDX`寫入路徑改虛線灰底樣式（`classDef planned`）；主線`Q-->ROUTE-->BFS-->REFINE-->CTX`改為`Q-->BFS-->CTX`實線+規劃中節點虛線繞行，反映現況（呼叫端須直接指定kg_id、檢索結果直接進組裝無精煉迴圈）；03變更紀錄補一筆。**下一批（批次3：03 §3.2 §b＋04 §4.7.1–4.7.2 檢索流程BT圖，修正04錯誤的檢索順序敘述）待使用者指示。**

## 2026-09-28（報告98 批次1+5 完成並push）

## 2026-09-28（報告98）：論文對齊批次1＋5 已完成並push（06/07/00/01/04/05/03）

Codex 執行報告98（commit `ad48dbf`）後，Claude Code 審核發現 2 處需修正（04 §4.10／00 第73列把3b/4步抽取端半的完成時點誤標成2026-09-08批次；06 §6.2.1插入B2段落後「這個負向但非全盤否定的結果」指涉不清變成像指B2），交Codex修正（commit `78835b9`）並複審，僅剩一個commit hash刪節號被誤合併的筆誤，Claude Code自行修正（commit `8a78d4d`）。**三個commit已push到`origin/worktree-sdd-retrieval-comparison`**。

內容：06/07/00 的B2現況改為「已完成全量pilot（n=41：B0 0.649/B1 0.693/B2 0.681），非正式評估，不併入S3表」；01 §1.4.2、04開頭/§4.10/§4.11、05 §5.4（65題、sha256 `77c293ed…`）等過時狀態已同步更新；03變更紀錄補一筆。**下一批（批次2：03 §3.1新增BT/SM表示法約定並改總覽圖）屬結構設計，待使用者指示由Claude撰寫或先寫任務書交Codex。**

## 2026-09-28（報告97，專案目標與 BT＋SM 工作流設計）

## 2026-09-28（報告98）：論文對齊批次1＋5 SDD 任務書已建立，交給 Codex 執行

使用者指示：為節省 Claude 用量，**較簡單的部分寫成 SDD 任務書交 Codex 執行，Claude 只負責撰寫與審核**。已建立[報告98](docs/報告/98_論文對齊批次1與5_B2現況與過時狀態修正SDD任務書.md)（T1–T11，純論文文字修改）：06／07／00 的 B2 現況（全量 pilot，**不得併入 S3 表、不得與 S3 數字比較**，因為是 `--runs 1`＋共用 judge＋平均 atomic_accuracy，條件不同）、01 §1.4.2、04 開頭與 §4.10（3b few-shot、第 4 步抽取端半已完成；**自然化模板仍寫死未完成**）、04 §4.11、05 §5.4、00 第 73 列、03 變更紀錄。**狀態：等待 Codex 執行 → Claude 依 §5 驗收 A1–A8 審核 → 審核通過後才 push**。下一批（批次2：03 §3.1 BT／SM 表示法約定＋總覽圖）屬結構設計，預計由 Claude 撰寫。

## 2026-09-28（使用者確認報告97）：先做 M1 論文收斂、再做 M2 程式整理；論文修正「分批、完成多少改多少」

使用者確認報告97 的目標、里程碑順序與 BT＋SM 設計方向，並要求論文修正不要一次做完、依完成度逐批修改。Claude Code 已提出分批建議（見下一次對話紀錄／報告97 後續），**尚未開始修改論文**，待使用者選定第一批。

## 2026-09-28（報告97）：專案目標與 BT＋SM 工作流設計（純文件，未動程式碼）

使用者要求「先整理專案資料與紀錄（不動程式碼），用 BT＋SM 節點工作流設計；先確認整體目標，再用此方式整理程式，決定如何模組化，並與論文對齊」。產出：
① [報告97](docs/報告/97_專案目標與BT_SM工作流設計.md)：§1 目標與里程碑草案（M0 現況／M1 論文收斂／M2 程式整理／M3 研究延伸／M4 產品化，**建議 M1 先於 M2，待使用者確認**）；§2 表示法（BT＝一次執行流程、SM＝長期實體生命週期，BT 改狀態只能發 SM 事件）；§3 十個 SM（SM-8 KG 無狀態欄位是缺口）；§4 八棵 BT，葉節點沿用論文 03 大寫代號，新代號標「新」；§5 論文對齊（新發現：01 §1.4.2 仍寫 domain pack 不存在；03 缺目前生成流程 BT 圖；評測與維護沒有 BT）；§6 程式整理決策 D1–D6（建議不導入 BT 執行框架、SM 用 Enum＋轉移表、漸進式目錄調整、拆 `agent.py`／`svo_service.py`，分 P0–P6 階段，每階段行為不變）；§7 資料整理。
② [報告索引](docs/報告/00_報告索引.md)：101 份編號報告依 18 主題分組並標節點。
**刻意沒有搬移任何檔案**：根目錄輸出檔多被程式或論文以路徑引用（例如 `baseline_rag_index_*` 由 `baseline_rag_service` 從工作目錄載入，搬走 B0/B1/B2 會失敗），搬移計畫列在報告97 §7.4（R1–R6）。**下次接手：先請使用者確認報告97 §8 第1項（目標與里程碑），其餘決策依序確認。**

## 2026-09-28（報告96）：程式流程與論文 03／04 登記缺漏盤點（純盤點，未改程式／論文）

使用者擔心「流程已建立但未登記到 03／04，日後遺忘成垃圾」。新增 `scripts/analysis/thesis_code_coverage_inventory.py`（名稱比對盤點，可重跑），134 模組／449 頂層定義中 74 個模組 03／04 皆未提及。人工核實後重點見[報告96](docs/報告/96_程式流程與論文03_04登記缺漏盤點.md)：①**在跑但未登記 9 項**——最嚴重是 `parser/image_pipeline.py`（469 行，每次解析都跑的 OCR／圖理解管線，論文與所有報告皆無記載），以及報告53/62/65/66/68/69/72/76/77/93/94 無一在 03／04 正文被引用；②**評測實作（N13）在 04 幾乎無章節**，04 §4.11 仍寫「`run_rq1_comparison` 未串接跑測迴圈」（過時）；③**只寫不讀／無呼叫者 7 項**——標準化 RAG Sentence 節點每次抽取都寫但無正式讀取端、`update_normalization_progress` 無呼叫、`prepare_svo_chunks` 舊入口殘留、`claim_next_pending` 未用、Document CRUD／`/search` stub；④重抽／修補／回填程序未登記；⑤根目錄 34 支 `.py` 約 22 支一次性。**全部待使用者裁示（報告96 §7），未刪除任何東西**。

## 2026-09-28（報告95）：專案節點流程總覽與設計說明（純文件）

使用者要求建立「節點流程說明＋專案介紹」，用於介紹專案與日後重構。已依程式碼（非舊文件）撰寫[報告95](docs/報告/95_專案節點流程總覽與設計說明.md)：10 個大節點（N1 輸入→N10 評測）＋3 個橫切節點，每個大節點附內部節點 Mermaid 流程圖與節點卡（目的／設計原理／程式位置／狀態／重構觀察），**v2（同日，使用者裁示「先不要急著重構、分已完成／規劃中、與論文對齊」）**：改為 Part A 已完成（✅）／Part B 規劃中（🟡零件在但未接線、📐只有設計），每個節點標出論文 03/04/05–07 章節；原重構建議降格為 §17「結構觀察（不重構）」。**v2 修正 v1 錯誤**：N2 不是「搬入 KG 資料夾」，預設是 SDD-51 Manifest 虛擬歸屬＋段落激活投票（可多 KG）。**新發現（程式閱讀、未實測）**：虛擬歸屬下 `trigger_extraction()` 以 `doc_folder.parent` 當 KG 資料夾、worker 卻到 `kg.folder_path` 找 `svo_index.json`，產品上傳路徑可能斷（KG#4 經匯入腳本建立、不受影響）。**§16 論文對齊落差（未改論文，待裁示）**：06/07/00 仍寫 B2 未完成；04 §4.7.2 檢索順序是舊版；04 §4.10/00 第73列說 3b few-shot 未完成但已接線；05 §5.4 仍寫「待決定」30 題。**未改任何程式碼與論文**。已 push 至 `origin/worktree-sdd-retrieval-comparison`（未進 master）。**v3（同日，使用者定義語意）**：「大節點＝規劃流程（可能只是規劃）、內部節點＝已確定的實作細節、尚未規劃成大節點的目標只做註記」。報告95 改為 13 個大節點（依論文 03 章）：✅8（N2/N4/N5/N6/N9/N10/N11/N13）、🟡2（N1/N3）、📐3（N7 事實時序 RQ5、N8 跨KG路由 RQ2、N12 自我精煉迴圈 RQ3）；內部節點只收已接線執行的程式，未接線零件列在各大節點「規劃範圍內未完成」；新增 §17 目標註記 G1–G11（07 §7.4 方案二/四/七/八、增量更新、同文件二次檢索、結構化條件查詢、人工標註、跨領域、產品化、GAP-06）。論文對齊在 §18、結構觀察在 §19。下次接手：待使用者裁示報告95 §20.2（論文對齊順序、疑似斷點是否實測等）。

## 2026-09-28（報告94 §0.3）：B2退步案例診斷收尾——`18-Q2`撤回、`57-CANARY1`根因確認、`57-AGGR4`已解決、`57-AGGR19`卡在Ollama client端逾時常數

**現況（接手前先確認）**：使用者裁示「先1」（診斷`18-Q2`退步原因並解決2個timeout案例），主session（非fork）直接查資料執行：

1. **`18-Q2`撤回**：§0.2原本列的「B2淨負案例`18-Q2`」查證後沒有資料佐證（三臂`atomic_accuracy`皆1.0），已撤回。真正確認存在的B2淨負案例只有`57-CANARY1`一筆。
2. **`57-CANARY1`根因已確認**（用`lineage.stage1_retrieval`實際比對三臂檢索內容，非推測）：這是「誠實拒答型canary」題（正確答案應是「無法確認」），M1/M2單次檢索5個相關chunk、正確拒答；B2的反思迴圈因為一直找不到「延長規定」（根本不存在）而持續判定證據不足、擴大搜尋到12個chunk，混入不相關的`育嬰留職停薪實施辦法`（另一種留職停薪、真的有延長機制）與`勞動基準法`片段，SNR腰斬（0.005→0.0022），生成端把雜訊當信號，產生幻覺式肯定答案。**這是agentic多輪檢索在拒答型題目上的架構性弱點**——反思機制找不到證據時只會觸發「再查」，缺少「查無此規定本身就是答案」的終止條件，呼應報告36文獻回顧提到、但B2規則式簡化版沒涵蓋的Adaptive-RAG路由精神。本次只診斷未修正。
3. **`57-AGGR4`已解決**：用900s timeout重跑，424.9秒完成，`atomic_accuracy=0.3333`跟M1/M2完全一致（三臂都漏掉同樣2/3 gold facts）——證實先前的timeout只是掩蓋了一個B2表現正常的結果。
4. **`57-AGGR19`仍未解決，但確認是更底層的限制**：900s仍失敗，錯誤從harness的`Timeout after 450s`變成`Harness Exception: ReadTimeout`（749.1秒拋出）——追查到`core/providers/llm/ollama.py:44`的`_TIMEOUT = 600.0`是Ollama provider HTTP client的**寫死逾時**，獨立於harness層級的`--query-timeout-s`。這題是全題庫最複雜的多跳比較題，單一次LLM呼叫本身可能就超過600秒。**這不是調高harness timeout能解決的，需要調高這個全域共用常數，但會影響所有production LLM呼叫，是否值得調整需使用者裁示，本次未修改**。

**更新後n=42最終比較**（排除唯一仍timeout的`57-AGGR19`，n=41）：M1（B0）0.649、M2（B1）0.693、**B2 0.681**——與B1差距些微擴大（先前n=40排除2筆是0.690 vs 0.692），但仍同一量級、屬雜訊範圍，不改變整體方向判斷：B2明顯優於B0、與B1相近，budget修正完全驗證，但有`57-CANARY1`這個真實的架構性弱點與`57-AGGR19`這類極端案例的效能風險。**維持report 36「B2為optional」定位**。詳見[報告94 §0.3](docs/報告/94_B2全量42題比較結果.md#03202609-28晚間主session親自診斷18-q2訂正57-canary1根因確認2個timeout案例的最終處置)。

**下次接手建議**：若要繼續投入B2，優先順序是（a）反思prompt加入「多輪查無證據應提高拒答傾向」機制、（b）決定`57-AGGR19`類案例是否值得調整`ollama.py::_TIMEOUT`全域常數、（c）視需要做全部42題的×3正式穩定性評估。或現階段以本輪結果收斂寫入論文限制/未來工作章節。**本次commit未push**。

## 2026-09-28（報告94 §0.2）：B2全量42題比較**已全數完成**，並修正先前「B2嚴重非決定性」的敘事

**現況（接手前先確認）**：使用者核准「擴大B2 pilot規模，補完42題全量比較」，Claude Code分三輪背景執行（09-27晚batch1、09-28上午batch2-3、09-28下午穩定性驗證+batch4-6），**42/42題已全部完成**（含4次timeout重試，2題B2在300s+450s兩次timeout後仍未取得真實結果，如實保留為timeout記錄，未臆測）。過程兩度撞上系統記憶體壓力（Dify/n8n意外復原經使用者手動解決、batch3被系統kill），最終依「依序執行、不重啟WSL、遇到問題檢查檔案而非空等通知」的原則完成。詳見[報告94](docs/報告/94_B2全量42題比較結果.md) §0.2（最終彙整，取代§0/§0.1的階段性小樣本結論）。

**本輪最重要的發現——修正先前的「B2嚴重run-to-run非決定性」結論**：對`18-Q5`／`57-CANARY1`兩題做`--runs 3`乾淨驗證後發現，先前報告93/94建立的「B2答案品質嚴重依賴run-to-run變異」敘事，其主要證據（`18-Q5`在M1/M2身上出現的`0.0`分）**其實是系統負載下的query timeout被誤記成生成失敗**（`failure_attribution="Harness Timeout after 300.0s"`，`answer_len=0`），不是LLM同一份輸入給出天差地遠答案的證據。B2本身在這次乾淨驗證的兩題上都**完全穩定**（3次答案逐字相同）；`57-CANARY1`確認是B2真正、可重現的弱點（3/3失敗，非雜訊）。**harness目前把timeout跟真正生成失敗一樣計入`atomic_accuracy=0.0`，未在統計中排除，這是已知的量測工具限制，記錄在報告94供未來參考，本次未修改harness程式碼。**

**42題全量最終結果**：三臂比較（排除2筆已知timeout）——M1（B0）0.649、M2（B1）0.692、**B2 0.690（幾乎與B1打平，領先B0）**。`retrieval_budget`修正在n=42全量規模下**完全驗證**（所有B2記錄的`rounds_per_subquestion`零個0值，單題／n=9／n=22-23／n=42四次獨立驗證一致）。成本代價：B2平均4.38次LLM呼叫／題（M1/M2約1.45-1.48次，約3倍）、延遲多28%、context多約1.3倍。B2淨勝案例`57-COREF3`（M1/M2皆失敗、B2成功）；淨負案例`18-Q2`（未深入診斷）、`57-CANARY1`（已確認真實弱點）。2題（`57-AGGR4`、`57-AGGR19`）B2在450s仍timeout，是已知的效能風險案例。

**誠實結論**：這是本系列pilot樣本量最大、也最正面的一次結果——排除timeout後B2準確率與B1幾乎打平，且budget修正的有效性已經非常穩固。但仍不足以直接判定「應正式採用為RQ1對照組」，還需要（a）診斷`18-Q2`退步原因、（b）解決2個timeout風險案例、（c）評估harness層級的timeout排除統計、（d）視需要決定是否對全部42題做更大規模的×3正式穩定性評估。**維持report 36「B2為optional」定位，但本輪結果是目前為止對「B2可能值得投入」方向最有力的一次證據。下次接手/使用者裁示**：要不要投入時間解決上述殘留限制、正式評估B2轉正為RQ1對照組，或現階段以「budget修正完全驗證、成本代價確認、準確率在全量下與B1打平但有已知timeout風險」的狀態收斂並寫進論文。**本次commit未push**。

## 2026-09-27（報告93）：B2 Agentic RAG強基準P0d實作+真實pilot（8題，非正式結論）

**現況（接手前先確認）**：使用者核准後，Claude Code（背景fork）完成報告36 §8最後一項待辦（P0d：生成端＋真實reflect LLM prompt＋harness併入）。`services/agentic_baseline_service.py`新增`gather_evidence_agentic_async()`（既有同步版不動）；`scripts/eval/run_rq1_comparison.py`新增`_b2_reflect()`真實LLM反思與`raw_arm=="B2"`分支（沿用B1檢索前端，生成端與B0/B1逐位元共用`_generate_from_context_lines()`——查證發現這條共用生成堆疊其實早就存在，不需要report 36預期的額外重構）；`services/evaluation_preflight.py`／`services/cost_analyzer.py`同步補B2。14個新測試，pytest 1170 passed。commit `c791cbf`／`eabcfc0`，**未push**。

真實pilot（非mock）原訂42題`--arms M1,M2,B2`，執行36分鐘後因系統記憶體壓力被背景保護機制自動終止（非程式錯誤，未重新啟動），**只完整跑完8題**三臂配對：B0 mean atomic_accuracy 0.938、B1 0.812、B2 0.917，但B2平均llm_calls 5.88次/題（B0/B1約1.1次）、延遲高28%、context長度約2倍。B2在1題（18-Q3）救回B0/B1都只答對一半的案例，但在另1題（18-Q5）明顯退步——**發現新confounder**：`retrieval_budget`在多子問題間扁平共用，前面子問題會把後面子問題的檢索額度耗光（`rounds_per_subquestion=[5,3,0]`），report 36原設計沒考慮到。詳見[報告93](docs/報告/93_B2AgenticRAG強基準P0d實作與pilot結果.md)。

**誠實結論（報告93 §4）**：n=8太小，不足以判斷B2值不值得投入更大規模正式RQ1對照，維持report 36「B2為optional」定位不變。使用者已裁示「先修retrieval_budget分配規則」，Claude Code已完成修正（`services/agentic_baseline_service.py`改為「每子問題保底＋剩餘額度動態分配」，commit `cb3be26`，pytest 1173 passed）並**真實重跑18-Q5驗證有效**：`rounds_per_subquestion`從`[5,3,0]`（第三子問題完全沒檢索）變成`[4,2,2]`，`atomic_accuracy`從0.33回升到**1.0（完全正確）**（詳見報告93 §4.1）。**push（`c791cbf`/`eabcfc0`/`0981014`）已於2026-09-27由使用者確認並執行**；`cb3be26`（budget修正）已commit，push待使用者確認。**下次接手建議**：(a) 用修正後的程式碼重新擴大跑測規模（例如補完先前因記憶體壓力中止的42題全量比較）；或(b) 現階段先以「budget缺陷已修正並經單題驗證」的狀態收斂，不擴大規模。兩條路都待使用者裁示，不是自動下一步。

## 2026-09-27（報告92）：報告71殘留22筆natural_text全數處理完畢

**現況（接手前先確認）**：Claude Code派3組agent逐筆用官方「全國法規資料庫」（law.moj.gov.tw）核對報告71殘留的22筆`natural_text`（17需複核+5建議排除），發現09-23的機械品質分級判斷力有限——22筆沒有一筆是「原分級完全正確」的。使用者核准後，已用`scripts/kg/fix_report71_residual_20_facts.py`（preflight/`--apply`/compare-and-set guard模式，比照報告90）對其中20筆backfill驗證後的`natural_text`，全數`written_verified`並經獨立唯讀查詢覆核吻合，pytest 1156 passed。剩餘2筆（`1152927002165017400`、`1152927002165023783`）因結構化欄位本身有問題（段落錯置／公式符號D/d混淆），維持現狀待未來另案處理。詳見[報告92](docs/報告/92_報告71殘留22筆natural_text法規原文複核報告.md)。**至此報告71對KG#4的96筆型別洩漏backfill全數處理完畢**（27+2+20=49筆已backfill，2筆待未來處理，47筆為欄位缺漏安全跳過）。尚未commit（下一步）。

**下次接手建議**：報告71系列已無殘留待辦。若要進一步深化RQ1論證，B2（Agentic RAG強基準）仍是目前唯一還沒做的正式對照組（已有部分證據蒐集端程式碼`services/agentic_baseline_service.py`，缺生成端接線與harness併入，報告36 §8）。

## 2026-09-27（session總結）：第六七章空白段落補齊 + 報告90/91執行複驗 + 全版控同步於`c48268f`

**現況（接手前先確認）**：四處版控完全同步於 commit `c48268f`——本worktree分支（`worktree-sdd-retrieval-comparison`）、`origin/worktree-sdd-retrieval-comparison`、`origin/master`、main checkout本地`master`。

本次session依序完成：

1. **論文第六、七章空白段落補齊**（純文件）：依`00_研究追溯對映表.md`現況，§6.1 TODO量化表、§6.2.2–6.2.6（RQ2-RQ6原本空白的標題）改寫為誠實的機制現況＋缺口說明；§7.2（原TODO：呼應1.3）依三層貢獻框架重申實際完成範圍——**RQ1是本論文唯一完成完整比較實驗閉環的正式研究問題**；補上§7.3缺漏的RQ2限制條目。
2. **報告88人工裁決回灌**（延續前次session的裁決結論）：`18-Q6`算對／`57-DIST2`算錯，KG相對B1落差校正為**−7題**，已寫入第六章§6.2.1/§6.4與第七章GAP-S3-02。
3. **報告90（報告71殘留4筆natural_text的法規原文複核與修正）**：Claude Code用law.moj.gov.tw逐條查證，2筆是誤判（現況已對、不用修）、2筆確認需修正（且問題點跟報告71原判斷不同）；Codex執行T1-T4，Claude Code獨立複驗（腳本compare-and-set guard、獨立唯讀Neo4j查詢核對、pytest 1156）全數通過。詳見[報告90](docs/報告/90_報告71殘留4筆natural_text法規原文複核與修正SDD任務書.md)。報告71殘留的17筆需人工複核、5筆建議排除案例**仍未處理**。
4. **報告91（第七章§7.4「方案二/四/七/八」未來工作補完）**：Claude Code直接讀取v1對標文件（`D:\Users\666\Desktop\智慧知識庫\docs\報告\04_對標NotebookLM_不足分析與完全超越方案.md`）原文，建立任務書，發現方案四（社群自動導讀）在v2查無對應Louvain機制的落差；Codex執行T1-T4，Claude Code獨立複驗（LayoutLM引用全名/作者核對、Grep確認`services/`／`repositories/`確實無社群偵測機制、確認`技術導入評估.md`無方案八專節）全數通過。詳見[報告91](docs/報告/91_第七章未來工作方案二四七八補完SDD任務書.md)。
5. **跨checkout/分支整併收尾**：過程中main checkout本地master一度因Codex在落後版本上作業而產生孤立commit`a020f58`，已用`git stash`保護既有異動＋`git reset --hard`清理；master與本worktree分支最終還分岔1個commit（報告90的T1-T4修正）對多個commit（本session全部工作），已`git merge`（零衝突、純新增）+pytest全綠後push，四處統一於`c48268f`。技術細節（stash SHA、逐步指令）若需要可查git reflog，不再展開於本文件。

**下次接手建議**：
- 第六、七章目前**已無已知的空白/TODO段落**。若要進一步深化RQ1論證，B2（Agentic RAG強基準）是目前唯一還沒做的正式對照組。
- 報告71殘留的17筆需人工複核、5筆建議排除案例，優先度未定，待使用者提出。
- 其餘長期未決事項見下方（續）以前的歷史段落與檔案末尾附錄。

## 2026-09-27：報告75-89批次收尾 + worktree分支合併master並反向fast-forward——四處版控狀態已統一於同一commit

**接手前必讀**：本分支（`worktree-sdd-retrieval-comparison`）、`origin/worktree-sdd-retrieval-comparison`、`origin/master`、主 checkout（`D:\Users\666\Desktop\world knowledge graph rag`）本地 `master` **四處現在完全同步，都指向 commit `32387b9`**（`git rev-list --left-right --count origin/master...HEAD` = `0 0`）。本節整理報告75-89的收尾狀態與這次合併的技術細節。

### 報告75-89 摘要（皆已個別commit並push，詳細內容見各報告檔案）

- **報告75**：本體論設計資料夾（`D:\Users\666\Desktop\本體論設計`）專案整合候選盤點，後續由報告87延伸（§7）。
- **報告76**：guard_profile（CJK正則守衛token）per-KG可插拔化，commit `2da08c0`，pytest 1111 passed。
- **報告77**：法律模態關係型（`RelTypeExtension`）per-KG擴充，commit `b598f34`，pytest 1118 passed。
- **報告78**：S3落差題（B1優於S0-K的9題）逐題根因診斷，commit `ddbc4ac`。
- **報告79**：S3評分器規則R（確定性敏感度分析規則）套用結果，commit `db39d8e`：S0 13→16/42、B1 21→22/42、KG缺口 -8→-6、p值0.021484→0.109375。**規則R只是診斷工具，非正式評分器**。
- **報告80**：S3結果回灌論文RQ1章節（`docs/論文/00,05,06,07`），commit `4812e07`。
- **報告81**：S3落差題獨立模型（granite4.2:3b／qwen3.5:4b）盲審交叉驗證，commit `ebc265e`：模型間一致率僅5/11，弱佐證。
- **報告82**：GAP-S3-01上下文組裝離線消融原型，commit `db68e83`：3/10 is_perfect，證據不充分。
- **報告83**：GAP-S3-01/02試驗結果回灌論文未來工作章節（§7.4），commit `2f6168a`。
- **報告84**：`role_mismatch`（歸屬錯置）風險全題庫（65題）掃描，commit `e1e24fb`：發現`57-AGGR6`／`57-AGGR19`兩個真實未覆蓋案例。
- **報告85**：AGGR6/AGGR19精確pilot規則落地`test_cases.json`，commit `2f8ddab`：`bank_sha256` `23f8c06f…`→`77c293ed…`（預期變更），pytest 1122 passed。
- **報告86**：RQ4a/4b追溯表同步報告76/77，首次執行commit `a1691a2`有資訊遺失瑕疵（誤刪「每一型式 vs 每增加一種型式」具體案例，換成空泛自我指涉句），Claude Code發現後要求修正，commit `664b3ef`已補回。
- **報告87**：本體論設計資料夾尚待詳讀清單掃描，commit `23a9ef8`：未發現新GAP候選（誠實的空結果）。
- **報告88**：`18-Q6`與`57-DIST2`人工法規語意判定資料包，commit `9ddf598`。**⚠️ 使用者尚未裁決，明確表示「晚一點確認」——下次接手第一件事應詢問是否已有結論**。內容含兩題完整未截斷答案文字、既有自動判定表，以及Claude Code發現的`57-DIST2` S0-K答案內部自相矛盾（先說「一至三日」後說「二至五日」）。
- **報告89**：worktree分支合併master前差異摘要（純分析，不執行合併），任務書commit `74872a4`、結果commit`08ccc06`。確認merge-base `b1c620e`、ahead=98/behind=54、交集39檔、8個高風險檔案清單。這次合併就是報告89分析的後續執行。

### 2026-09-27 本次合併執行細節（Claude Code親自執行，非委派Codex）

依報告89的分析與使用者核准，**Claude Code本人**（非Codex）執行`git merge origin/master --no-commit --no-ff`並逐檔手動解決12個衝突：

- `scripts/eval/embedding_cache.py`／`tests/scripts/test_embedding_cache.py`：add/add衝突，內容byte-identical，直接採用。
- `config/domain_packs/generic.json`：保留HEAD（含guard/rel_type_extensions的完整`_note`）。
- `core/kg_config/model.py`：4處衝突全保留HEAD（`GuardConfig`／`RelTypeExtension`類別master完全沒有）；已確認master的`RelTypeConfig`/`reltype`欄位在同檔案未受衝突影響、原樣保留（git自動合併），兩邊功能共存。
- `scripts/eval/run_rq1_comparison.py`、`scripts/eval/frozen_baseline_stage.py`：保留HEAD的`--k-top-k`/`--article-expand`（報告62 T1/T3）CLI參數，與master的`--embedding-cache`/`--metric-judge-*`（報告68/69）並存，兩者互不衝突。
- **`services/svo_service.py`（9處衝突，風險最高）**：多數保留HEAD的superset功能；**其中`_reconcile_rel_type()`一處必須真正合併雙方**——HEAD的`rel_type_extensions`描述（`_effective_rel_type_descriptions()`）與master新增的per-KG`_cfg.reltype.compare_cosine_threshold`（取代寫死的`COMPARE_COSINE_THRESHOLD`常數）缺一不可，已手動合併兩者。
- `routers/agent.py`：1處衝突，HEAD的`article_no: f.get("article_no")`（報告62 T3含article_expand的retrieval trace）取代master的靜態`None`，純附加telemetry欄位、`.get()`安全取值，不影響`chat()`核心邏輯。
- `tests/core/test_kg_config.py`、`tests/scripts/test_rq1_harness_failures.py`、`tests/services/test_svo_service.py`：皆保留HEAD新增的測試（對應上述per-KG功能，master沒有）。
- `HANDOVER.md`：保留HEAD完整敘事版本，master側的短摘要段落內容已被HEAD自己頂部的報告70段落涵蓋，補一句交叉引用避免遺漏。

**⚠️ 發現並修正2處git靜默合併錯誤（非標記衝突，`ast.parse()`測不出來，需完整`compile()`或跑測試才會發現）**：`services/svo_service.py`的`extract_svo_triples()`與`extract_svo_triples_with_completeness_check()`兩個函式各自被git自動合併成**重複宣告`cfg`參數**（HEAD與master各自在不同行位置插入同名參數，未觸發衝突標記但語法非法）。已手動移除重複宣告。同步修正`tests/services/test_svo_service_cfg_wiring.py`中一個因新增`descriptions=`參數而過時的mock函式簽章。

**驗證**：全套`python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py`跑出**1156 passed，零失敗**。

**版控狀態**：merge commit `32387b9`（parents: `d1a22b5`本分支＋`c57f7dd` origin/master）→ push到`origin/worktree-sdd-retrieval-comparison`（fast-forward）→ 使用者確認後push到`origin/master`（`c57f7dd..32387b9`，fast-forward非force）→ 主checkout本地`git pull --ff-only`一度因`core/kg_config/stages.py`／`tests/core/test_kg_config_stages.py`兩個檔案「本地異動」被擋，經`diff --strip-trailing-cr`核對確認**純換行符（CRLF/LF）差異、內容逐字相同、無實質工作內容**，執行`git checkout --`還原後fast-forward成功。**四處版控狀態現在完全一致**。

### 下一步待決定（優先順序供參考）

1. ~~報告88（`18-Q6`／`57-DIST2`）人工裁決~~——**已於2026-09-27完成**，見本文件最上方段落，此項移除。
2. ~~報告69殘餘~~——**2026-09-27使用者已裁示：不進一步處理**。根因（LLM推論非決定性，與報告20同源機制）已查清楚，5/7乾淨樣本已是解耦生效的清楚證據；緩解或擴大樣本正式判定的邊際效益不值得投入。此項移除。
3. **報告67**：96/11,011（0.87%）筆`natural_text`型別洩漏backfill——使用者已明確確認優先度低、暫不處理，勿主動提起執行。
4. 長期、未經深入討論不應啟動的方向：GAP-06（Relator）、GAP-07（bi-temporal）、RQ2-RQ6新研究方向。
5. S3（KG vs chunk-RAG）已完整跑完並回灌論文（報告78-83），GAP-S3-01/02皆已誠實記錄「證據不足，不建議投入」；若要重啟這條線，需要使用者提出新的具體切入點，不是自動下一步。

## 2026-09-23（續）：報告68/69批次整合進master完成 + 3份後續任務書已交付Codex

依HANDOVER「下一步待決定」清單順序，建立4份任務書（[報告70](docs/報告/70_報告68_69批次整合進master任務書.md)～[73](docs/報告/73_報告69殘餘judge非決定性緩解任務書.md)）交付Codex，逐項由使用者在對話中核准後執行：

1. **✅ 報告70已完成並push**：報告68/69 production code（`92d8492`／`1f353d8`）cherry-pick進main checkout master（新SHA`41697bb`／`c8f9184`），另加2筆必要修正——`12d2308`移除3個依賴報告62專屬`_build_kg_chat_request`的測試（該函式不在master，報告62本身尚未合併）、`bc37b61`清理尾端空白行。`routers/agent.py`／`services/`確認未觸碰（`git diff`為空）；`core/providers/factory.py`只新增`override_embedding_provider_for_eval()`／`make_llm_provider_for_eval()`兩個eval-only函式，master原有簽名未變；HANDOVER.md僅新增精簡段落未整份取代。pytest 1107 passed。**已由Claude Code獨立`git fetch`核對`origin/master`確實為`bc37b61`**（範圍`7e67f2b..bc37b61`，非force push）。**待辦**：`12d2308`移除的3個測試屬報告62功能，日後報告62正式合併master時需補回。
2. **✅ 報告71 T0-T2已完成並push，但發現後續需修正的4筆**：T0查明production KG只有2個（KG#4`236903cf-...`與舊KG`76bc98ff-...`，後者0筆`natural_text`不受影響）；T1唯讀dry-run對KG#4重算96筆受影響邊，49筆重算成功、47筆因欄位缺漏安全跳過（不臆測）；人工審閱樣本發現機械「無殘留型別標記」核對不足以保證品質（截斷、缺謂語詞堆疊、疑似LLM幻覺），追加品質分級（數字/單位/CNS-ISO錨點、動詞與主賓詞覆蓋、截斷/缺謂語檢查），49筆分為27筆安全／17筆需人工複核／5筆建議排除。**使用者核准只backfill 27筆安全案例**，T2執行27/27寫入成功且讀回核對一致，其餘69筆確認維持原值未被改動。**已push，`origin/master`最終為`c57f7dd`（Claude Code獨立`git fetch`核對，範圍`bc37b61..c57f7dd`）**。**⚠️ 重要**：Claude Code逐筆核對27筆寫入內容後，發現**機械品質分級仍漏了2類問題**——「關鍵限定詞/受益對象被整段刪除」（例：`...6917546619827179615`刪除「或受益人」、`...1155178801978699636`刪除「高溫作業」主詞）與「插入原文沒有的新子句」（`...1152937997281292486`疑似加料「代其辦理居留業務」），加上1筆語序破碎（`...1152927002165041341`），共**4筆已寫入KG但內容有疑慮**，已記錄在`data/eval/naturalization_backfill_dryrun_20260923/t2_followup_issues.md`（commit `be17cf0`／`c57f7dd`，含目前KG實際值、T1舊值、法規出處），**尚未修正**，需要下一輪人工核對法規原文後另案處理。品質分級規則的這個缺口也已記錄在`quality_grading.md`，供之後（17筆需複核清單、或其他KG的類似backfill）設計檢查規則參考。**仍待辦**：這4筆的實際修正、17筆需人工複核、5筆建議排除，均需要另一輪明確決策。
3. **✅ 報告72 S0-S2已完成，S3待決定**：詳見下方「2026-09-24 報告72 S0-S2完成」。報告73（報告69殘餘judge非決定性緩解）待執行。

## 2026-09-24 報告72 S0-S2完成——4個候選臂全部「需更多證據，不建議採用」

**接手前先讀本段，再讀[報告72任務書](docs/報告/72_報告62殘留待辦新基準與K1b_T3_chunkRAG任務書.md)§6/§7的完整判定。**

**結論**：新題庫（`23f8c06f…`）基準S0為13/42；K1b／K1（top_k=40）、K2（`article_expand`）、K3（兩者組合）**四個候選臂逐題配對後全部判定「需更多證據，不建議設為預設」**，沒有任何一臂被採用。詳細數字：K1b/K1 16/42（違反不退步＋Type-E不退步規則）、K2 13/42（無淨增，5題新增5題退步）、K3 14/42（SNR 1.6167%跌破S0一半門檻1.8683%，直接否決）。**`article_expand`機制的人工抽查**（報告57 §4.21類別B「拆碎gold span」5案例）顯示：機制確實把同條文兄弟Fact帶入檢索候選池（K2 trace有1,860個帶`article_no`的擴充Fact），但**只有1/5部分修復、4/5仍未補齊**——候選池擴充不等於實際排進prompt的內容擴充，這是誠實記錄的負面結果，不是被分數波動掩蓋。

**production程式碼異動**（commit `be57b4d`，**Claude Code已逐行核對diff並獨立重跑pytest確認1089 passed**）：`routers/agent.py`新增`_expand_facts_by_article()`（純唯讀Cypher，只有`MATCH`/`RETURN`，不寫入Neo4j）、`core/kg_config/model.py`新增`FactListConfig.article_expand`（預設`False`）、`models/document.py`新增`ChatRequest.article_expand`（預設`None`，沿用per-KG設定）——**全部opt-in，預設行為未變**，插入點在scope過濾後、`_arrange_fact_lines()`前，仍受既有prompt/BFS/RRF/LITM限制。`config/kg/236903cf-....json`（S1 K1b用）與S2的per-request `article_expand`是兩種不同的啟用方式，兩者都不影響全域預設。

**版控狀態**：HEAD在main worktree（`worktree-sdd-retrieval-comparison`）本地為`be57b4d`（S0/S1/S2全部commit在案，含逐項核對記錄），**尚未push**。main checkout `master`全程未被本任務觸碰。過程中兩次遇到`.git/worktrees/.../index.lock`權限競爭（Codex與Claude Code同時在同一個worktree操作導致），皆由Claude Code協助完成commit解決，未造成資料遺失。

**已知限制**（S3若執行、或之後任何人要引用S1/S2結果時務必提醒）：`57-AGGR18`角色互換歸屬檢查（`claim_scope_auditor`的`role_mismatch`規則泛化）仍待辦，Atomic Accuracy／達標status可能高估；共用generator/judge（`qwen2.5:7b`）僅屬pilot，非正式評測；`18-Q4`／`26-Q5`等多題的退步歸因是Stage 3生成階段遺漏/平滑，不是檢索問題，換檢索策略解不了這類生成端缺陷。

**S3（chunk-RAG對照組，決策點D1）尚未執行**——這是報告62/72設計中回答論文核心問題「KG相對chunk-RAG的增益」的最後一塊，工作量較大（需在同一批42題、同凍結條件下補跑既有B0/B1/D arm），**待使用者決定是否進行**，不是自動下一步。

## 2026-09-24 報告72 S0/S1暫停checkpoint（歷史記錄，已被S2完成取代，保留供追溯）

**接手前先讀本段，再讀[報告72任務書](docs/報告/72_報告62殘留待辦新基準與K1b_T3_chunkRAG任務書.md)與[中繼執行報告74](docs/報告/74_報告72執行接續報告_20260923.md)。**

1. **環境**：branch `worktree-sdd-retrieval-comparison`、worktree`D:\Users\666\Desktop\world knowledge graph rag\.claude\worktrees\sdd-retrieval-comparison`、HEAD`8ad23e3`（此commit已含S0第二輪＋74號報告改名）。題庫雜湊`23f8c06f…`、KG`236903cf-055a-40a8-8923-b9d06601f3b7`（Fact 16,826、Entity 12,296、佇列3,307 completed）、generator/judge皆`qwen2.5:7b`、embedding`bge-m3`、Ollama`0.34.3`（舊凍結manifest記`0.34.2`，model digest相同）。main checkout `master`全程未被本任務觸碰。
2. **S0已完成**（`data/eval/baseline_runs/20260923_rebased/summary_final.json`，**Claude Code已逐項核對，數字真實**）：42題、75筆records、0 errors；`single_pass=9`／`stable_pass=4`／`stable_fail=29`，達標13/42（9+4），抽查4/4、reliability 1.0，`next_run_ids=[]`不需第三輪。`57-DIST1/2`仍`stable_fail`，與報告62 §14.10既有診斷（答案本來就缺天數）一致，非新問題。
3. **S1（K1b：top_k=40＋per-KG`config/kg/236903cf-....json`覆寫`factlist.min_bfs_slots=16`維持BFS名額）已完成**（`data/eval/candidate_runs/s1_k1b_topk40_bfs16_adaptive_summary_r2.json`，**Claude Code已逐項核對，數字真實**）：Stage A 42/42、Stage B（第二輪）29/29，合併後`single_pass=13`／`stable_pass=3`／`stable_fail=26`，達標**16/42**，抽查3/4（reliability 0.75，略低於S0的1.0，屬已知LLM/judge非決定性雜訊範圍，見[報告69](docs/報告/69_評測harness固定metric-judge與受測arm-judge解耦SDD任務書.md)殘餘章節）。Stage A單次批次平均（Atomic Accuracy 56.5%／Context Recall 74.4%／SNR 3.0%）**不是**最終判定用數字，只是單輪原始平均，最終判定要用上面的16/42（穩定通過題數）。
4. **⚠️ 下一步：S1對S0的逐題配對判定尚未執行**——16/42 vs 13/42只是總數，報告62 §11.1的採用規則要求逐題配對（基準中穩定通過的題目是否有變成未達標、SNR是否跌破基準一半、Type-E是否退步、需附信賴區間），**這是接續時第一件事**，做完才能決定K1b是否建議採用，之後才進S2（`article_expand`）。
5. **輸出路徑總覽**：`data/eval/baseline_runs/20260923_rebased/`（S0：`frozen_manifest.json`／`s0_questions.json`／`stage_s0_r1`／`stage_s0_r1_resume1`／`stage_s0_r2`／`s0_adaptive_summary_r2.json`／`summary_final.json`）、`data/eval/candidate_runs/`（S1：`s1_k1b_topk40_bfs16_stage_a/`／`s1_k1b_topk40_bfs16_stage_b/`／`s1_k1b_topk40_bfs16_adaptive_summary_r1.json`／`_r2.json`）、`config/kg/236903cf-055a-40a8-8923-b9d06601f3b7.json`（S1 per-KG覆寫）。
6. **已知限制**（S1/S2/S3結果解讀時務必附帶提醒）：`57-AGGR18`角色互換歸屬檢查（`role_mismatch`規則泛化）仍待辦，Atomic Accuracy可能高估；共用generator/judge僅屬pilot。
7. **接續SOP**：先`git status`／`git log -1`確認HEAD與本段記錄一致，再讀報告72任務書§2 S1驗收段與§11.1採用規則，做逐題配對判定；配對完成、決定K1b是否採用後才開始S2。**全程未對Neo4j寫入、未修改production程式碼、main checkout未被觸碰**；本checkpoint涉及的commit尚未push，push需使用者另行同意。

## 2026-09-23：報告68/69收尾 + master整合完成（大量跨worktree協調，開新對話前必讀）

**報告68（embedding快取）與報告69（固定metric-judge與受測arm-judge解耦）皆已由Codex完成、Claude Code獨立驗證、使用者核准並push**。詳見上方「2026-09-22 報告68」「2026-09-22 embedding快取重跑獨立judge pilot」「2026-09-23 報告69」三段的完整技術細節，此處只記結論：

- 報告68：評測harness查詢embedding快取，解決檢索embedding生成端非決定性（文獻`docs/參考文獻/38/`）。
- 報告69：harness新增`--metric-judge-provider`/`--metric-judge-model`，把「受測arm自己的judge」與「Stage1-4評分工具的固定judge」解耦（文獻`docs/參考文獻/39/`，定性為評判者間信度問題非self-preference bias）。T5驗證：7題中5題Stage1 Recall兩臂完全一致（比修法前3/7進步），殘餘2題（`57-CANARY5`／`57-AGGR19`）獨立查證為已知的LLM推論非決定性（`core/providers/llm/ollama.py`固定seed仍無法完全消除，與報告20同源機制），非本次修法缺陷。
- **待使用者決定、尚未執行**：(a) 殘餘的judge推論非決定性要不要進一步緩解（例如語意fallback核對也跑多次取眾數）；(b) 乾淨樣本5/7是否足以支撐「獨立judge是否有效」的結論，要不要正式重跑判定。

**同日完成一次大規模跨branch/worktree版控整合**（起因：使用者要求整理「待合併與推送項目」，開了另一個Claude Code session在main checkout做盤點）：

1. **盤點結果**：4個worktree/分支——主checkout(`master`)、`.claude/worktrees/kg-reextract`(`reextract-v2`，落後master 227個commit，**維持不動**，不整支merge，只是執行期工具不屬產品主線)、`.claude/worktrees/report-gemini-review`(`worktree-report-gemini-review`，已是master祖先，**無事可做**)、本worktree(`worktree-sdd-retrieval-comparison`，領先master 34/落後48，diffstat 115檔115萬字)。
2. **從本branch挑出9筆commit**（逐commit核對本文件的日期段落狀態標記，而非只看檔案路徑，才正確識別出哪些production變更已核准接線）分4組cherry-pick進一個中繼分支`codex/integrate-sdd-groups`：
   - 第1組（評測診斷）：`aedaf93`／`d918174`／`b15c2ec`
   - 第2組（抽取修復＋設定重構）：`35f95ab`／`860654a`／`8b80eaf`
   - 第3組（去重旗標）：`5ae0154`
   - 第4組（型別標記修復）：`7ed651d`→`6bc644e`
   - 過程中修正2次「整份取代衝突檔案」的錯誤指令——`d918174`/`b15c2ec`混雜了報告文件（該報告的建立commit不在9筆名單內，master上不存在）需要用`git rm`只排除文件、保留code；`8b80eaf`曾誤導成「整份取代`services/svo_service.py`」，會蓋掉master自己獨立演進的cfg門檻接線功能（`074052f`～`a8c7cbb`共10筆，跟這次整合完全無關），被pytest的`test_svo_service_cfg_wiring.py`10個失敗即時攔下，改為精確手動合併（保留master既有的`cfg`參數簽名，只加`_svo_prompt()`重構與一行fewshots轉發）。
3. **意外事件**：第3組完成時（13:50:17建立中繼commit`3ff6d44`後37秒），`origin/master`被直接push成`3ff6d44`，來源查證未果（Codex與另一個平行session皆否認且有操作紀錄佐證），但內容本身已逐筆審查過、判定安全，使用者決定不深究、直接接受現狀往下走。
4. **main checkout本地master同步**：另有一個平行session（使用者稱「Cherry-pick進度追蹤」，非本session）同時在處理一個無關的小任務（`.gitignore`加`.pytest-tmp*/`忽略規則），導致main checkout本地master多出一筆獨立commit、跟意外push的`origin/master`分岔。用「`git reset --hard`到內容已完整涵蓋新commit的目標、事前`git stash`保護使用者既有未commit異動、事後`stash pop`還原」的方式安全處理了兩次分岔（`8d13baf`→`f2ccc63`→`7e67f2b`），main checkout原有的3個既有異動（`docs/報告/53_...md`修改＋2份未追蹤v1.0文件）全程無損。
5. **最終結果**：`origin/master`已fast-forward到`7e67f2b`（=舊master `b629282` + 9筆核准commit + gitignore修正），非force push，已由Claude Code獨立核對ref與內容。`reextract-v2`、`worktree-report-gemini-review`維持不動。

**尚未納入這輪整合**：本worktree（`worktree-sdd-retrieval-comparison`）自己這次工作階段新增的報告68/69內容（embedding快取、metric-judge解耦，commit `92d8492`／`1f353d8`／`b8f0178`／`313b3d5`）**還沒有被cherry-pick進master**——這是下一輪可以考慮的整合批次，屬於「評測基礎設施」類別，風險應該較低（predominantly eval-only，`routers/agent.py`/`services/`皆未觸碰）。

**下一步待決定**（優先順序供參考，非硬性規定）：
- 要不要把報告68/69這批也cherry-pick進master（比照這次的分組審查流程）。
- 報告67遺留的96/11,011（0.87%）筆`natural_text`型別洩漏backfill決策，仍未執行。
- 報告62原始待辦（C/D/E/G/H：新題庫基準重建、K1b、T3條文擴充、chunk-RAG比較），這次工作階段全程被report65-69插隊，仍未動。
- 報告69殘餘的judge推論非決定性緩解，以及要不要正式重跑獨立judge pilot判定成效。

## 先讀這裡

接手前先執行 `git status -sb`、`git branch --show-current`、`git log -1 --oneline`，再讀本文件及下方報告。不要只依賴對話摘要或舊 handover。

### 工作目錄與分支

- 專案主要 checkout：`D:\Users\666\Desktop\world knowledge graph rag`，目前在 `master`，含使用者既有異動；不要在此 checkout 編輯、stage 或 commit 本任務檔案。
- 本任務工作區：`D:\Users\666\Desktop\world knowledge graph rag\.claude\worktrees\sdd-retrieval-comparison`。
- 工作分支：`worktree-sdd-retrieval-comparison`。
- **2026-09-20：使用者已明確授權，本分支已推送並與 `origin/worktree-sdd-retrieval-comparison` 同步**（推送時最新為 `b2c03da`，含先前 Codex 的3個本地 commit 一併推送）。此後的推送仍須取得使用者明確同意。請重新查 `git log` 和 ahead/behind，勿使用此段推算最新 SHA。
- 此前已推送的程式 commit：`a808391`，包含風險修復 `819472a` 與 source-scope Fact 檢索修正。
- 目前已有的根目錄 `CLAUDE.md` 與歷史 handover 有部分過時的架構／進度描述；本文件及報告57 §4.13、報告60 §1.4 優先作為目前狀態依據。

### 最近完成的階段

使用者已核准並完成 AGGR15／16／17 的 source-scope on/off ×3 K-arm A/B，以及固定文件範圍下 Fact-only `top_k=5/10/15/20` 掃描，並對 AGGR16 延伸至 top_k=35。實驗期間只讀取 Neo4j；沒有修改產品程式碼、圖資料或全域預設值。摘要與數據表已記入：

- [報告57 §4.13：scope A/B 與 Fact top_k 精準度掃描](docs/報告/57_檢索品質解耦評測與知識圖譜場景化角色SDD任務書.md#413-source-scope-ab-與-fact-top_k-精準度掃描2026-09-18)
- [報告60 §1.4：接續評估摘要與建議](docs/報告/60_Codex接續確認交接任務書.md#14-2026-09-18-檢索精準度最佳化評估)

### 2026-09-21 最新進度與下一階段（本段優先於下方所有段落）

**下一階段請直接讀 [報告62 下一階段任務書](docs/報告/62_下一階段任務書_檢索排名與條文擴充驗證.md)**，它設計成冷啟動可用（含環境陷阱、任務清單、預先宣告的採用規則、決策點）。摘要：

1. **凍結基準已完成**（報告57 §4.20）：K arm、42 題 12/42 達標（拒答事後重算 14/42）、跨文件題 0/13。**後續分析**（§4.21）：20 題檢索失敗的 35 個 gold span 只有 1 個真的沒抽到，17 個抽到但排名太後、14 個抽到但被拆碎，**重抽 KG 不是主要方向**。文獻與專案證據強度見 [報告61](docs/報告/61_做法與文獻來源查證報告.md)：沒有文獻能證明具體做法有效，論文定位應是「診斷 KG 在什麼條件下有／無增益」。
2. **凍結後產品行為程式碼沒有變更**（`git diff e178c4c HEAD -- services routers core models` 只有註解與一個預設為空的 `extra_refusal_patterns` 參數；題庫 hash 與凍結時一致），所以新候選可直接與凍結基準對照。
3. **同分支上的其他工作**（提交者同為 `Chester930`，無法分辨 session，**未經我審查**）：本地生成模型初篩（結論：暫不替換 `qwen2.5:7b`；條件與凍結基準不同，不可比較）、Embedding×KG×Chunk 協作架構討論稿（其「`HybridEvidence`／`PathTrace`」第一個工程任務與報告62 T0 方向一致）、補入先前 untracked 的實驗輸出，以及 **`master` 已合進本分支（`b1c620e`）**——因此下方第 6 項 (b) 的「先把 master 合進本分支」已完成，只剩依路徑拆分與使用者確認。
4. **推送須取得使用者明確同意**；**合併 `master` 前須逐項詳細確認**（使用者明訂）。
5. **報告62 T0 已完成（本分支未推送）**：opt-in `ChatRequest.include_retrieval_trace` 記錄檢索順位／分數／來源與實際進 prompt 的行，不改行為（1 題實跑與凍結基準逐項相同）。**重要發現**：基準 stage-2／SNR 以「檢索到的全部」計算；prompt 截斷門檻非單調（池 >35 時放寬到 35 行），使 T2（top_k=40）同時會縮減 BFS 名額——詳見報告62 §10。T1（`--k-top-k`）已完成。**T2（K1＝top_k 40）已完成並判定**（報告62 §12）：達標 12→14（淨增 2，p=0.75），穩定通過的 `57-DIST1/2` 退步、Type-E 退步 → **需更多證據，不建議設為預設**；退步題的 gold 皆在 prompt 內（生成階段失敗），新增題也非來自第 21–40 名 Fact。使用者已同意 D3 採用門檻（§11.1，評測前已寫定）。**§13 生成診斷後修正**：`57-DIST1/2` 的退步是評分器對逐字引用 vs 改寫的敏感度（實質答案相同，KG 缺全國性天數）、`57-AGGR18` 的新增是評分器漏抓同一個新舊法寫反的錯——**達標題數 ±2 屬於量測噪音**。**§14 量測工具稽核已完成（2026-09-22，標註者是模型、需使用者抽驗）**：評分器偽陰性下界 ≥11.8%（23/195，主因是改寫／近逐字被判 missing）、偽陽性下界 ≥4.0%（7/174，含新舊法歸屬寫反）；確定性規則 R（高重疊＋數字條號守衛＋否定詞守衛）在樣本內救回 18/23 偽陰性、誤翻 1/18，**T2 的 +2 結論對此穩定**（重判後仍 +2）。**現行評分器未改動**（改了會與凍結基準不可比）；**§14.6–14.9（2026-09-22）**：用 `granite4.2:3b`／`qwen3.5:4b` 盲審交叉比對——只是弱佐證（一致率 52.8%／69.0%）；保守下界改為偽陰性 ≥7.2%（14/195）、偽陽性 ≥3.4%（6/174），另有約 5 題需人工複核（`data/eval/scorer_audit_20260922/contested_for_human_review.json`）。gold span 掃描只發現 `57-DIST1/2` 是真缺陷（法規原文已核對：全國性＝二至五日）。評分器 v2 已離線重判（`data/eval/scorer_v2_20260922/`）：事後情境淨差 +2～+4、p 0.29–0.75，**不翻轉 §12**。待使用者裁示：是否採用 v2 定義當之後候選的比較基準、是否修改 `test_cases.json` 的 DIST1/2、人工複核清單。**跑 Ollama 思考型模型（Granite 4.2、Qwen3/3.5）務必 `think:false`，否則 content 為空且極慢。** 再談 K1b／T3。**§14.10（2026-09-22，使用者已同意）：題庫已修正**——`57-DIST1/2` 各補兩個必要 span（第2條「給予一至三日之特別休假」、第3條「給予二至五日之特別休假」，逐字取自 KG 條文，已核對原文）；兩份鏡像 sha256 同步為 `23f8c06f…`（**與 09-20 凍結雜湊 `404cde9f…` 不同，這是預期變更**）。之後任何用 `frozen_baseline_stage.py` 重跑舊 `20260920_frozen` 流程，`verify_frozen.py` 會如預期回報 bank hash 不一致，**不是環境壞掉**。09-20 的「12/42」歷史數字語意不變（仍是舊題庫下的結果），但**下次要做 T2/T3 或任何新候選評測，一律改用新題庫 `23f8c06f…` 當基準**，不可與舊數字直接相加減。

### 2026-09-22 報告62 §14 量測工具稽核收尾：A（v2評分器）／B（人工複核）已裁示

使用者已就報告62 §14.9 的待裁示事項拍板，詳見報告62 §14.11：**暫不採用規則R／v2評分器為預設**（保留當診斷工具；理由與後續處理原則見§14.11）；**人工複核7筆（4題）已全部裁決**——`57-DIST1/2` 因§14.10題庫修正已自動解決不必另判、`26-Q5`維持支持（但標記答案自相矛盾）、`57-AGGR19`推翻原判改判不支持（丟了「依前項第一款規定」限定條件）。評分器程式碼與凍結基準數字皆未變動。

下一步依先前排定的優先序（A/B → F → C → D/E → G/H）進到 **F：抽取粒度修復設計**——針對 §4.21 類別B「抽到但破碎／丟失限定條件」（35個gold span中佔14個、40%，最新人工複核的`57-AGGR19`也是同型案例）設計修復方案。

### 2026-09-22 F：抽取粒度修復設計已完成文獻查證與任務書撰寫（**尚未實作，待使用者核准**）

依專案既定流程（先查文獻與參考專案、記錄查證結果、未確定內容以報告形式儲存，核准後才進論文與程式碼），已完成：

1. **診斷**：用報告57 §4.21 的 `retrieval_failure_diagnosis.json` 真實 Fact 文字定位根因——`services/svo_service.py::_svo_prompt()` 規則7（要求把附加規定拆成獨立三元組，report18/19/20時期為修「遺漏」問題設計）遇到「共同條件→多個結果」的複合法規句時，條件與結果被拆進互不相干的三元組，任一筆單獨看都不完整。`57-AGGR19` 排名第1名仍判未命中，證明這不是排序問題。
2. **文獻查證**（新資料夾 `docs/參考文獻/37_三元組條件限定詞與超關係表示/`，已同步登錄 `docs/論文/02_文獻探討.md` § 3.1.3 三筆新條目）：Chen et al. Dense X Retrieval 的「去脈絡化」判準、Galkin et al. (2020) StarE 超關係KG／qualifier、Krótkiewicz et al. (2026) 法律規範顯式範圍表示（摘要層級，全文付費牆未取得）。**誠實結論：沒有文獻直接研究這個具體取捨，僅能佐證「限定條件不該被丟」的大方向在相鄰領域被認真對待，不構成有效性證明**。
3. **任務書**：[報告65：抽取粒度修復設計SDD任務書](docs/報告/65_抽取粒度修復設計SDD任務書.md)——三個候選方向（A：修prompt條件複述進verb，成本低，建議優先；B：Fact補句子層級provenance＋檢索時撈同句兄弟Fact，成本中高，需schema+backfill；C：顯式qualifier/超關係表示，成本最高，僅記錄不評估實作），驗證計畫是**定向重抽**（`scripts/kg/reextract_chunks.py`，非全量重抽），不動全域設定。
4. **待使用者核准**：是否採用方向A並執行驗證計畫（報告65 §4/§5）；核准前不得修改 `_svo_prompt()` 或執行任何重抽。

### 2026-09-22 方向A已核准：prompt 修正已落地，定向重抽驗證進行中（背景），後續任務已交付 Codex（**須等驗證完成才可開始**）

1. **使用者已核准方向A**。`services/svo_service.py::_svo_prompt()` 新增**規則10**（commit `35f95ab`）：拆解「共同條件→一個或多個結果」的複合法規句時，條件須複述進每一筆結果三元組的 verb；另涵蓋列舉前言本身漏數量的情形（`18-Q5`/`57-DIST1/2` 同型）。全套 pytest 1043 passed。
2. **⚠️ 架構澄清（使用者要求，已補進報告65 §3.1）**：規則10目前**全域生效，非per-KG範圍**——`_svo_prompt()`（含規則1-10）仍是單一寫死函式，`KGConfig`／domain pack 機制尚未涵蓋抽取端 few-shot（報告33 §6「3b步」已知缺口）。**通用/特定的正確關係應是「共用骨架不動＋具體例句當參數注入」，不是每個 domain 整份複製 prompt**——已落地為[報告66](docs/報告/66_SVO抽取少樣本領域包參數化SDD任務書.md)，交付 Codex，任務書含完整技術方案（`KGConfig.domain.svo_fewshots` 新欄位、`_svo_prompt()` 動態編號組裝、`extraction_worker.py` 比照 `routers/agent.py:1516-1534` 既有 domain_pack 讀取模式）。**Codex 須等下一項的定向重抽驗證完全結束後才能開始**，因為兩者都會動 `services/svo_service.py`，同時進行會互相汙染結果判讀。
3. **✅ 定向重抽驗證已完成（2026-09-22）：好壞參半，判定「未達驗證通過」**，詳見報告65 §6-7。對 KG#4（`236903cf-055a-40a8-8923-b9d06601f3b7`，正式資料）9個chunk定向重抽，9/9 completed：
   - **4/9乾淨修復**（`57-AGGR7`教科書等級、`57-AGGR19`舊法、`D0080015` c3/c4天數回補）——證明規則10對「單一條件→結果」結構有效。
   - **原始診斷主要標的（`57-AGGR19`新法·勞工側，c85，先前排名第1名仍未命中的那筆）依然未修復**，且新增簡體字混入（「准用」「基准法」，既有防護`_to_traditional_selective`未攔到）。
   - **`57-CANARY5`（c101）嚴重退步**：重抽前雖破碎但仍帶部分條件細節，重抽後坍縮成1筆完全無條件的裸陳述，比修改前明顯更差。
   - `57-AGGR8`（c18）出現疑似角色互換的無關雜訊（中央主管機關→雇主）。
   - **判定**：方向A「部分驗證，需加固後才能推廣」，不是「驗證通過」。
5. **✅ 使用者已裁示選2+4，且已執行完成（commit `860654a`／`c190296`）**：
   - **選項4（確定性防護閘門）**：`services/svo_service.py::_fix_known_simplified_compounds()` 逐詞修正已知易錯簡體詞組（准用→準用、基准法→基準法），補救 `_to_traditional_selective()` 逐字白名單的結構性盲點；`scripts/kg/reextract_chunks.py` 新增重抽前後 `fact_text` 總字數比對，低於門檻（預設70%）印警告並寫入 `content_loss_flags.json`，不自動阻擋/回復。全套 pytest 1048 passed。
   - **選項2（修復c101）**：`57-CANARY5`（N0050031 c101）已修復——不是回復（fork的before.json因腳本bug被覆蓋，且重建的S-V-O字串不足以可靠回灌）也不是盲目重試（自動重抽只補回1/3條件），而是核對 `svo_index.json` chunk 101 的權威原文，透過與正常抽取相同的 `merge_triples_to_graph()` 管線寫入一筆完整自足的修正三元組（三個條件+結果全保留），已查詢驗證、無孤兒資料殘留。誠實標註為**人工修正、非LLM抽取結果**，`rel_type` 用 `RELATED_TO` 安全兜底。
   - **✅ 追加完成（同日）：c85 簡體字混入已補修**——發現「準用勞動基準法規定預告雇主」正確版Entity早就存在（`57-AGGR19`舊法c26共用），改名會撞唯一約束；改用 `merge_triples_to_graph()` 既有citation合併邏輯送入修正三元組，再精準刪除（非整chunk revoke）壞Fact/壞邊/壞孤兒Entity各一筆。已查詢驗證c85仍是7筆Fact（數量不變），目標事實已是正確繁體字。
   - **仍未處理**：c85的條件分裂問題本身（報告57/62最初診斷的主要標的，「終止勞動契約時準用勞動基準法規定預告雇主」缺「依前項第一款規定」）仍待規則10加固或方向B/C；c18的角色互換雜訊維持現狀。
   - 詳見報告65 §8。
6. **✅ 報告66（`svo_fewshots`領域包參數化）現在可以交付 Codex**（使用者已確認要排時程，此為回答「什麼時候」的判斷）：`_svo_prompt()` 目前是穩定狀態（規則10已落地，本輪c101/c85的修正都是**資料層級**手動修正、不是再改prompt字串本身），報告66的T1-T6是**結構性重構**（把現有規則1-10包裝成骨架+可注入few-shot參數），有golden test保證shipped defaults逐字不變——這個重構跟「之後可能再幫規則10加多條件並列支援」是兩件互不阻塞的事：先做重構、之後再改few-shot內容，或先改內容、之後再重構，結果一樣，golden test baseline屆時重新對齊即可，不需要為了等內容穩定而卡住重構。**建議現在就可以把報告66 §5的指令貼給Codex**；若使用者傾向先把多條件並列支援也做完再重構，改標一次即可，不影響報告66任務書本身的正確性。

### 2026-09-22 T-B：生成模型與接地核對 judge 解耦設計評估（已完成，僅評估未新增接線）

本節是依使用者要求對 T-B 的設計評估與成本盤點；本輪沒有修改
`routers/agent.py::chat()`、`services/verification_service.py` 或其他正式行為。
盤點後發現：T-B 的基本解耦能力其實已在既有提交 `ce84a77`
（2026-09-08）落地，本次工作不是再做一次接線，而是確認目前接線範圍、預設行為與採用成本。

#### 1. 現況呼叫鏈與目前實際行為

目前的路徑如下：

1. `routers/agent.py::chat()` 先以 `get_llm_provider()` 取得生成端 provider
   （目前預設 `qwen2.5:7b`），再以
   `get_judge_llm_provider(llm_provider)` 取得接地核對 provider；目前位置約為
   `routers/agent.py:1510-1515`。
2. `chat()` 將兩者分開傳入 `_generate_from_context_lines()`：
   `llm_provider` 用於初稿串流、分解式生成、限制性重生成與定向修正；
   `judge_llm_provider` 用於 grounding 核對。helper 的雙 provider 介面約在
   `routers/agent.py:1256-1263`。
3. helper 目前有三個 grounding 核對點，均傳入 `judge_llm_provider`：初稿核對約
   `routers/agent.py:1328-1329`、限制性重生成後複核約
   `routers/agent.py:1422-1423`、列舉完整性重生成後複核約
   `routers/agent.py:1436-1437`。
4. `services/verification_service.py::verify_fact_grounding()` 本身只接受一個
   provider 參數，並在約 `:148-150` 呼叫該 provider 的 `generate_json()`；它不會
   再自行取得或建立模型。因此「生成者＝核對者」與否是呼叫端 provider 選擇問題，
   不是 verification service 內部再拆分的問題。

目前設定與 fallback 語意已存在於 `core/config.py:16-21`、
`core/providers/factory.py:91-124`：

- `JUDGE_LLM_PROVIDER` 未設定（預設 `None`）時，`_judge_llm=None`，
  `get_judge_llm_provider()` 回傳生成端 provider；所以現行預設仍是同一顆模型自我核對，
  完全保留舊行為。
- 設定 `JUDGE_LLM_PROVIDER` 後，啟動時用同一個 `_make_llm_provider()` 建立獨立的
  `_judge_llm` 實例；可用 `JUDGE_LLM_MODEL` 覆蓋 judge model。`chat()` 會實際把
  grounding 核對改送至該獨立實例，生成與重生成仍留在生成端 provider。
- 因此，T-B 已具備「不同 provider／不同模型」以及「同 provider、同模型但不同
  Python provider 實例」兩種部署方式；後者只解除物件／路徑共用，不會消除同一模型
  權重與判斷偏差的相關性。

#### 2. 與離線 harness 的對照

離線 harness 已採相同的角色分離慣例：

- `scripts/eval/run_rq1_comparison.py:648-654` 初始化後分別取得 generator 與 judge，
  並在 `:659-664` 對正式評測禁止 shared judge（除非明確 `--allow-shared-judge`）。
- 每題的生成呼叫在約 `:259-263` 傳 `llm_provider=counting`、
  `judge_llm_provider=judge_counting or counting`；後續 lineage、AtomicScorer 等
  語意核對也沿用同一 judge。這與 `chat()` 的 provider 角色分工一致。
- 差異在於 harness 對「正式比較」強制不同 judge；正式 `chat()` 為了向後相容沒有
  這個強制閘門，未設定時仍允許 shared judge。這是部署策略差異，不是介面能力缺口。

#### 3. 設定方案與建議

不建議再新增 `verification_judge_provider`／`verification_judge_model` 這組重複設定；
現有 `judge_llm_provider`／`judge_llm_model` 名稱已涵蓋接地核對用途，且已被 factory、
router、測試與 harness 使用。三種操作模式如下：

| 模式 | 設定 | 可回答的問題 | 代價／限制 |
|---|---|---|---|
| 現行相容模式 | 不設 `JUDGE_LLM_PROVIDER` | 保持目前生產行為 | 仍有生成者自我審查的循環性 |
| 同模型獨立實例 | `JUDGE_LLM_PROVIDER=ollama`，model 同生成端 | 驗證角色與 provider 路徑是否正確分離 | 不是真正的模型多樣性，不能排除同模型偏差；通常沒有第二組權重 |
| 獨立 judge 模型 | 設定 provider，必要時設 `JUDGE_LLM_MODEL` | 直接測試「生成端與核對端不同模型」是否降低誤判／限制性重生成 | 可能多載入一組模型，增加 VRAM、模型切換與延遲風險 |

T-A 新增的 `OLLAMA_LLM_THINK` 目前是 Ollama 共用設定；若未來要讓生成端與 judge
各自使用不同 thinking 策略，還需另加角色級設定（例如 judge 專用 think），但這不屬
本輪 T-B 評估，也不應在沒有配對實驗前自行新增。

#### 4. 成本與測試影響估算

- **程式改動成本**：T-B 基本能力已完成，追加改動為 0 個正式程式檔。若從尚未有
  解耦能力的版本重做，實際範圍是 `core/config.py`、`core/providers/factory.py`、
  `routers/agent.py`、`tests/core/test_providers_factory.py`、
  `tests/routers/test_agent.py` 五個檔案；現有提交已包含這些變更與回歸測試。
- **呼叫數與延遲**：切換成獨立 judge 不會自動增加 LLM 呼叫數；每次 grounding
  pass 原本就有一次 `generate_json()`，若觸發重生成，原本也會再複核一次，列舉
  guard 另有既有複核路徑。變的是 judge 模型的單次速度與判定結果。若 judge 判定
  差異使重生成率上升，端到端延遲才會額外上升。
- **記憶體／載入**：同一 Ollama 模型的獨立 Python provider 物件本身成本很小；若
  judge 是另一模型，Ollama 可能同時保留兩組權重，也可能因 VRAM 不足反覆卸載／重載，
  造成明顯延遲。這是目前最主要的運行成本，尤其本專案已有 Ollama 記憶體壓力紀錄。
- **測試影響**：現有 `tests/core/test_providers_factory.py` 已覆蓋 fallback、獨立
  judge 實例與 model override；`tests/routers/test_agent.py` 已驗證生成走 generator、
  grounding 走 dedicated judge。若未來改動預設行為，至少要新增 shared／dedicated
  兩模式的 chat 回歸測試，並重跑完整 pytest；本輪沒有改正式程式，所以不需新增測試。
- **觀測成本**：factory 已記錄 judge provider/model；harness 也把 generator/judge
  provider、model、judge calls 寫入 record。正式 chat 若採用獨立 judge，建議後續補記
  judge identity、grounding pass、regeneration 次數與延遲，否則很難判斷改善來自模型
  能力還是只來自不同重生成率。

#### 5. T-B 結論與後續決策建議

T-B **技術上可行且基本接線已完成**；目前真正尚未決定的是是否在正式 `chat()` 環境
設定 dedicated judge，以及要選同模型實例還是不同模型。建議不要把「已能配置」直接當成
「已證明有效」：若要排除 self-judge 放大因素，應固定生成端 `qwen2.5:7b`、題庫、
檢索 context、timeout 與 `think:false`，只做 shared judge vs dedicated judge 的配對
比較，至少記錄 grounding 判定差異、regeneration rate、最終 Atomic Accuracy、拒答／
模糊拒答率、端到端延遲與 judge model load 次數。

因此，本輪不接線、不更換生產模型，也不執行 T-C；使用者可在確認這份評估後，直接以
現有 `JUDGE_LLM_PROVIDER`／`JUDGE_LLM_MODEL` 做受控比較，或另行提出角色級 thinking
設定與更細的 judge 失效分析。

### 2026-09-22 生成模型能力診斷與 Ollama `think` 參數缺陷（T-A 已完成；T-B 見上節）

**背景**：使用者要求確認「是否需要調整生成模型（目前 `qwen2.5:7b`）」。以下判斷依據報告62 §12–14（T2判定＋生成階段診斷＋量測工具稽核）與 `services/verification_service.py` 既有 docstring 記載的歷史 bug，非猜測。

**判斷結論**：

1. **已修復（與是否換模型無關的獨立程式缺陷）**：T-A 前曾確認 `core/providers/llm/ollama.py` 的 `generate()`／`generate_json()`／`stream()` 三個方法都沒有傳 Ollama `/api/generate` 的頂層 `think` 參數，污染了 2026-09-20 的本地生成模型初篩（`rq1_eval_results/local_model_screening_20260921.md`）。現已由提交 `2f2415a` 修復：`think=None` 不送 key，`think:false/true` 送至頂層；因此思考型模型初篩的舊結論仍不可信，但基礎設施缺陷已排除。
2. **尚未確認需要換掉 `qwen2.5:7b`**：現有唯一一次篩選（見上）條件跟凍結基準（K arm、42題、`qwen2.5:7b` generator/judge共用）不可比，又被(1)的bug污染，不能當「換或不換」的證據。同時，報告62 §13 診斷指出的生成端異常（`18-Q4` 限制性重生成變模糊拒答、`canary-P1` 罰鍰區間答錯）主因之一疑似是**接地核對機制用同一顆 7B 模型自我審查**（`services/verification_service.py` docstring 已記錄歷史 bug：qwen2.5:7b 常把問題原樣回貼，被自己的判官誤判成「未接地」觸發重生成）——換模型前應先排除「小模型自我審查放大雜訊」這個設計因素，否則換了模型也未必解決同一種現象。
3. **報告57 的既有教訓**：換生成模型是獨立於 KG 檢索評測的變因，一旦換了必須固定下來、在所有後續候選比較中維持一致，不可中途替換又互比（報告49/51 曾因此污染過結論）。

**交給 Codex 的任務（建議順序）**：

- **T-A（必做，S，純程式缺陷修復，與是否換模型無關；已完成）**：讓 `core/providers/llm/ollama.py` 支援 `think` 參數。
  - `OllamaLLMProvider.__init__` 新增 `think: bool | None = None` 參數；`generate()`／`generate_json()`／`stream()` 的 request payload 只在 `self._think is not None` 時加入**頂層**（不是 `options` 裡）`"think": self._think`——`None` 時完全不送這個 key，向後相容，不改變任何既有行為。
  - `core/config.py` 仿照 `ollama_llm_num_predict`（約第33行）新增 `ollama_llm_think: bool | None = None`（可用環境變數覆寫）。
  - `core/providers/factory.py::_make_llm_provider()`（約第22-29行，`case "ollama":` 分支）把新設定傳入 `OllamaLLMProvider(...)`。
  - 新測試比照既有 `tests/core/test_ollama_llm_num_predict.py` 的模式，新檔 `tests/core/test_ollama_llm_think.py`：驗證 `think=None`（預設）時 payload 不含 `think` key；`think=False`／`True` 時 payload 含對應值；`generate`／`generate_json`／`stream` 三個方法都要覆蓋。
  - 跑 `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py` 確認零回歸。
  - **不要**動 `_NUM_CTX`／`_TIMEOUT`／`_SEED` 等既有常數，也不要改變 `think` 未設定時的預設行為。
- **T-B（S，設計評估已完成；本輪不新增接線）**：現況已由既有 `ce84a77` 提供
  `judge_llm_provider`／`judge_llm_model` 與 `get_judge_llm_provider()`；未設定時仍與
  生成端共用，設定後 `chat()` 的三個 grounding 核對點改用獨立 judge。完整現況、離線
  harness 對照、成本與採用建議見上方「T-B：生成模型與接地核對 judge 解耦設計評估」。
- **T-C（M，需 T-A 完成後才有意義，非本次必做）**：用 T-A 修好的 `think:false` 重跑一次公平的模型篩選比較，比較對象至少含 `qwen2.5:7b`（現況）、`qwen3.5:4b/9b`、`granite4.2:3b/8b`。**必須對齊凍結基準的 K arm 42題（或已修正的新題庫 `23f8c06f…`）條件，不能沿用舊32題／不同judge／不同timeout**，否則結果一樣不可比。建議 T-A、T-B 完成並經使用者確認後才排入排程。

**明確不要做**：在沒有 T-C 這種公平比較之前，**不要**把生產 `chat()` 或評測 harness 的預設生成模型從 `qwen2.5:7b` 換掉。

### 2026-09-22 獨立judge pilot（n=1）：結果被檢索階段非決定性雜訊蓋過，不可信

沿用今天小範圍K-arm的7題（`.claude/tmp/report65_targeted_karm_20260922/questions.json`），設 `JUDGE_LLM_PROVIDER=ollama`／`JUDGE_LLM_MODEL=qwen3.5:4b`／`OLLAMA_LLM_THINK=false` 跑一次對照（`run2_independent_judge`，背景fork執行，唯讀不動KG不改程式碼）。**Judge切換驗證正確**（generator=qwen2.5:7b、judge=qwen3.5:4b、`same_instance=False`）。

**結果好壞參半**：3題改善（`18-Q5`／`57-DIST1`／`57-DIST2`）、3題變差（`57-CANARY5`／`57-AGGR7`／`57-AGGR8`）、1題持平。整體 Atomic Accuracy 50.0%→46.4%（降）、Context Recall 76.2%→57.1%（明顯降）、is_perfect 0/7→2/7（升）。

**關鍵異常，判定「不可信」的理由**：`57-CANARY5` 的 **Stage 1 檢索** recall 從1.0掉到0.5——但 judge 模型理論上完全不會影響檢索階段，同一KG同一問題不該因為換judge就檢索到不同東西。這代表 run1／run2 之間存在**跟judge無關、但幅度大到蓋過待測效果**的雜訊，很可能是檢索/embedding層的非決定性。`57-DIST1`（原本最想驗證的案例）在 run2 仍是 `regenerated=true`、仍缺一個gold span——「限制性重生成→不完整引用」的模式**沒有消失**，數字變好較可能是單次隨機波動。

**判定**：n=1的pilot設計無法把「judge效果」跟「檢索非決定性雜訊」分開，**不建議據此採用或否決獨立judge**。若要繼續驗證，正確做法是用報告62 T0已有的機制（`prompt_context_lines`/固定prompt重放），排除檢索階段變因，只測生成+judge本身。

**文獻查證結果（2026-09-22，新資料夾 `docs/參考文獻/38_檢索embedding非決定性與可重現性/`，已同步登錄 `02_文獻探討.md` §2.6.2 三筆新條目）**：

- **根因有文獻支持，且不是本專案程式錯誤**：Wang, Zhao, Tallent & Guo (2025) *On The Reproducibility Limitations of RAG Systems*（arXiv:2509.18869）系統性研究RAG檢索管線可重現性，明確指出「**核心ANN檢索演算法本身通常可達到完全的run-to-run可重現性**，真正的雜訊來源是每次重新呼叫embedding model時的生成變異」——跟本專案報告20已引用的Horace He/Thinking Machines Lab（LLM生成非決定性根因：batch size依賴）同一機制家族，只是這次發生在embedding端。Yuan et al. (2025)（arXiv:2506.09501）延伸佐證這個根因的普遍性。Lopez Fune (2026)（arXiv:2606.28330，弱佐證，單一作者預印本）補充機制性解釋：高維embedding空間cosine分數集中／對比度塌縮，使排名邊界的候選對微小擾動特別敏感——這正好解釋了觀察到的現象模式（排名邊界的gold fact掉出top-k，不是隨機亂跳）。
- **建議解法（Wang et al. 2025明確提出，低成本可行）**：**Embedding caching**——問題的query embedding只算一次、之後重複執行/多臂比較都重用同一份，避免每次重新呼叫embedding provider引入變異。這是唯一不需要改動Ollama/bge-m3底層、可以直接在應用層（harness層）實作的緩解措施。
- **不建議**：修改Ollama/bge-m3推論精度或批次設定追求完全決定性——本專案透過Ollama黑盒呼叫，沒有掌控這層的能力，文獻顯示即使做到（如LayerCast）也需要修改推論引擎內部，成本遠高於應用層的embedding cache。

**下一步建議**：若要繼續驗證獨立judge或任何「固定檢索、只換其他變因」的pilot，優先在harness層加一個query embedding cache（同一次比較的兩個臂共用同一份embedding），或直接沿用報告62 T0的`prompt_context_lines`重放機制（已經是「固定住檢索結果」的等價做法，只是原本設計動機不同，剛好也能排除這裡發現的embedding變因）。

**✅ 已落地為任務書，交付Codex**：[報告68：評測harness查詢embedding快取SDD任務書](docs/報告/68_評測harness查詢embedding快取SDD任務書.md)——設計原則是**只動評測harness層，完全不改`routers/agent.py::chat()`或任何production程式碼**：在`core/providers/factory.py`新增一個明確標示eval-only的override hook，讓harness把全域embedding provider單例換成快取包裝版，`chat()`透過既有的`get_embedding_provider()`自動受益，不需要改它任何一行。預設（不傳`--embedding-cache`）零行為變化。T4只驗證快取機制本身有效（同一題連續跑兩次結果一致），**不自動重跑獨立judge pilot**，那是之後另外決定的事。**✅ 2026-09-22已由Codex完成並驗證**（commit `92d8492`），T1-T4全數通過，`routers/agent.py`確認未被觸碰，1076 tests全綠。

### 2026-09-22 embedding快取重跑獨立judge pilot：發現Stage 1 Context Recall指標本身內嵌judge模型，非純檢索指標

用報告68落地的`--embedding-cache`，讓共用judge臂（沿用報告68 T4的`run1_cached`，judge=generator=qwen2.5:7b）與新增的獨立judge臂（`JUDGE_LLM_MODEL=qwen3.5:4b`）共用同一份快取檔`.claude/tmp/report68_embedding_cache_20260922/embedding_cache.json`，唯讀背景fork執行，輸出於`.claude/tmp/report69_independent_judge_cached_20260922/run_independent_judge_cached/`。

**embedding快取本身確認有效**：兩次跑的`retrieval_trace`（每個fact的檢索分數與排序）逐位元完全相同，證明「查詢向量→向量搜尋→BFS檢索」這段已是決定性的，報告68的機制做對了。

**但七題中只有3題（`18-Q5`／`57-DIST1`／`57-DIST2`）Stage 1 Context Recall在兩臂間完全一致，另外4題（`57-CANARY5`／`57-AGGR7`／`57-AGGR8`／`57-AGGR19`）不一致**：

| 題目 | 共用judge Recall | 獨立judge Recall | 一致？ | 共用judge Atomic Acc | 獨立judge Atomic Acc |
|---|---|---|---|---|---|
| 18-Q5 | 1.0 | 1.0 | ✅ | 0.667 | 1.0 |
| 57-DIST1 | 1.0 | 1.0 | ✅ | 0.5 | 0.75 |
| 57-DIST2 | 1.0 | 1.0 | ✅ | 0.75 | 1.0 |
| 57-CANARY5 | 1.0 | 0.5 | ❌ | 0.5 | 0.0 |
| 57-AGGR7 | 0.333 | 0.0 | ❌ | 0.333 | 0.0 |
| 57-AGGR8 | 0.75 | 0.0 | ❌ | 0.25 | 0.0 |
| 57-AGGR19 | 0.25 | 0.5 | ❌ | 0.5 | 0.5 |

**根因（已讀碼獨立驗證，非fork片面之詞）**：`services/semantic_span_matcher.py::match_spans_with_fallback()`（第56-107行）對每個gold span先做逐字子字串比對，**若比對不到、且傳入了`judge_llm_provider`，會額外呼叫一次judge LLM做語意蘊含核對**（第83行`judge_llm_provider.generate_json()`）。這個函式被`services/lineage_tracker.py::record_retrieval_async()`（第133行）呼叫來計算Stage 1 Context Recall。也就是說，**Stage 1 Context Recall不是純檢索指標，而是「檢索到的fact集合」+「用哪個judge做語意核對」的複合結果**。只要逐字比對沒有100%命中（本例4/7題如此），這個數字就會隨judge換人而變；18-Q5/DIST1/DIST2三題兩邊一致，是因為逐字比對就已100%命中，根本沒觸發語意fallback。

**這個confound不只影響這次pilot**：任何「固定檢索、只換其他變因」的跨judge比較，只要gold span不是逐字命中（naturalization改寫後很常見，也是報告67處理natural_text品質問題的同一類現象），Stage 1 Recall都會被污染。

**判讀**：
- 只有3/7題是乾淨樣本，可把Atomic Accuracy差異單純歸因於judge——這3題方向一致，獨立judge給分皆較高（0.667→1.0、0.5→0.75、0.75→1.0）。
- 其餘4題的差異混雜「Stage1語意核對用哪個judge」與「Stage3生成評分用哪個judge」兩層效應，不能單獨歸因。
- 不代表獨立judge沒有效果，而是**目前的評測方法論還無法把這個效果乾淨量出來**。

**建議修法方向（尚未實作，待使用者決定）**：`match_spans_with_fallback`計算Stage 1 Recall時，語意fallback應固定用同一顆judge（不隨受測的arm變動），judge差異只保留在Stage 3 Atomic Accuracy這一層——把「評測用哪個judge做語意核對」和「待測的judge本身」分開。這是評測harness的設計問題，不是這次執行出錯，也不影響report68已完成的embedding快取本身的正確性。

### 2026-09-23 報告69：固定metric-judge與受測arm-judge解耦——✅ 已由Codex完成並驗證，confound部分解決，殘餘部分定性為已知LLM生成非決定性

文獻查證（`docs/參考文獻/39_LLM評判者一致性與固定化評測量尺/README.md`）確認上述confound更準確的定性是**評判者間信度問題，非self-preference bias**（Stage 1核對的文字是KG檢索出的事實，不是judge自己生成的內容；Chen et al. 2024指出事實導向RAG任務self-preference bias本來就不顯著）。統一設計原則：把「受測arm自己的judge」（只用於`chat()`內部重生成決策）與「評分工具的固定metric-judge」（Stage 1-4量測，跨所有arm一致）分開，比照Zheng et al. 2023自己的評測方法論（固定外部judge評分所有受測模型）。

**Codex完成T1-T5**（commit `1f353d8`，未push）：`core/providers/factory.py`新增eval-only的`make_llm_provider_for_eval()`；`run_rq1_comparison.py`新增`--metric-judge-provider`/`--metric-judge-model`選填參數，接線到Stage 1-4這4處（`record_retrieval_async`／`record_context_assembly_async`／`AtomicScorer.evaluate_async`／`build_full_lineage_async`），**B0/B1 arm第264行的judge來源明確未動**；`frozen_baseline_stage.py`比照報告68先例新增透傳。**已獨立複驗**：`routers/agent.py`／`services/`確認未被觸碰；diff逐行核對與任務書規格完全一致；`tests/scripts/test_rq1_metric_judge.py`新增4個測試，精準驗證Stage1-4收到metric_counter、B0 arm生成路徑仍收到judge_counting（不受metric_counter影響）、不傳旗標時harness不建立metric_counter；獨立重跑`python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py`確認**1086 passed**，跟Codex回報一致。

**T5驗證結果**：固定`--metric-judge-provider ollama --metric-judge-model qwen2.5:7b`後，7題中5題（`18-Q5`／`57-DIST1`／`57-DIST2`／`57-AGGR7`／`57-AGGR8`）Stage 1 Recall在共用judge臂與獨立judge臂之間完全一致（`57-AGGR7`／`57-AGGR8`從原本不一致變成一致，證明修法確實消除了「換judge model造成的confound」），僅`57-CANARY5`（1.0→0.5）與`57-AGGR19`（0.25→0.5）仍不一致。

**殘餘不一致的根因診斷（已獨立查證，非Codex片面之詞）**：逐位元比對兩次跑的`retrieval_trace`（sha256 hash完全相同），確認retrieval端100%決定性、跟這2題的差異無關。差異出在**同一個固定metric-judge（qwen2.5:7b）對同一段文字、同一個gold span做語意蘊含核對，兩次呼叫給出不同的true/false判斷**——`core/providers/llm/ollama.py`第35-57行的`OllamaLLMProvider`已設定`temperature=0.0`＋固定`seed`，但程式碼註解本身已誠實聲明「固定seed無法完全解決這個問題，根因是batch size依賴的浮點運算非結合律」，與報告20已引用的Horace He/Thinking Machines Lab機制同源，這次剛好體現在judge做語意fallback核對的呼叫上，屬於**已知、文獻記載、目前應用層無法完全消除**的LLM推論非決定性，不是報告69這次修法的缺陷。`57-AGGR19`的分歧點（「雇主依前項規定預告終止勞動契約時，準用勞動基準法規定預告勞工。」是否與另一句幾乎同義的gold span算命中）本身也是新舊法規定實質相同、語意判斷本就落在模糊邊界的案例，跟已知的AGGR19特性吻合。

**下一步待使用者決定**：(a) 是否推送`1f353d8`；(b) 殘餘的judge推論非決定性要不要進一步緩解（例如比照`adaptive_repeat.py`的多次執行取眾數精神，讓語意fallback核對也跑3次取多數決，但這會增加judge呼叫成本，且報告20已有先例說明這類緩解措施的取捨）；(c) 是否要重跑正式的獨立judge pilot（用固定metric-judge+embedding快取），現在乾淨樣本已從3/7提升到5/7，是否足以支撐「獨立judge是否有效」的結論。

（`1f353d8`／`92d8492` 已由上方「2026-09-23（續）：報告68/69批次整合進master完成」段落記錄的報告70任務確認cherry-pick進master，見該段第1點。）

### 2026-09-20 最新進度（本段優先於下方 09-19 段落）

1. **KG#4 抽取狀態已修復**：發現 `_process_one()` 內部吞例外、只標 `failed`，重抽腳本回報的「N/N 成功」不可信；KG 曾有 10 failed＋2 pending chunk（N0060041 §8/23/24/25/33/34、N0050031 §69/84/85/86、N0030006 chunk 3/8）。已用新工具重跑，12/12 首次即 `completed`，Fact 由 44 增為 82 筆，佇列現為 3307/3307 `completed`。詳見 [報告57 附錄C](docs/報告/57_附錄C_KG重抽來源清單與失敗chunk盤點.md)。**先前「終止條件比較子題抽取品質差」「請假規則 §3/§8 漏抽」的結論不成立**，已在報告57 §4.6 與論文 3.1.3§b 更正。
2. **新工具**（皆唯讀或讀回真實狀態）：`scripts/kg/reextraction_manifest.py`（列出被重抽的 chunk 與非 completed 的 chunk）、`scripts/kg/reextract_chunks.py`（重抽後讀回佇列狀態、失敗自動重試、保留日誌）。**今後重抽務必用後者或事後跑前者確認全為 `completed`。** 另從 `reextract-v2` 挑入 `claim_next_pending()`（原子認領）。
3. **兩條抽取分支互補**：抽取守衛（`_LEAVE_TYPE_FAMILY`、「等級」單位、風險三級）只在本分支；drain 工具在 `reextract-v2`。第5–9組 targeted 重抽當時是從 `reextract-v2`（`a72cbaa`）執行，**不含**這些守衛。不要整支互相 merge。
4. **題庫 65 題（verified 46）**：新增 `57-AGGR18`（新舊法認定機構寫反時 Atomic Accuracy 仍 100%）與 `57-AGGR19`（預告規定新舊法實質相同）。**發現原子評分不檢查歸屬**，故只為 AGGR18 依實際觀察到的錯答加了一條 `role_mismatch` 規則（子字串、高精確度低召回，pilot）與回歸測試。詳見報告57 §4.19。
5. **重測 `57-AGGR5`/`57-AGGR6`**（Fact 補齊後，n=1）：仍 0%，檢索失敗型態未消失；但同時經過 `a808391`，不可單獨歸因。報告57 §4.6 已標註。
6. **仍待決定**：(a) 擴大 scope audit 規則到更多題——規則應來自實際觀察到的失敗答案，且會改變題庫雜湊，須先與本文件記載的 matched-v2 對照協調並凍結題庫快照；(b) 合併 `master` 的方式——建議先把 `master` 合進本分支解掉兩份文件衝突（論文第3章、文獻查核表），再**依路徑**拆成「評測基礎／抽取守衛／`chat()` 行為變更（`a808391` 風險最高）／文件與論文」四塊，不要整支合併；(c) 主體/子句 grounding guard 設計討論（問題定義須涵蓋抽取後的實體去重階段）。
7. **協作注意**：本工作目錄由多個 agent 共用，**未 commit 的檔案會被其他 agent 的 `git add` 夾帶進他們的提交**。開工前先看 `git status`／`git log`，改完盡快 commit，並勿改動已被對照實驗使用的題目文字（例如 `57-AGGR16`，它有題庫雜湊比對與 `answer_scope` 規則）。

8. **✅ 凍結基準評測已於 2026-09-21 完成，凍結解除**：42 題最終 12 題達標（28.6%）、Context Recall 68.3%、Type-C 跨文件題 0/13。結果、限制與已確認的兩個評分器盲點（拒答關鍵字漏判、不檢查歸屬）見 [報告57 §4.20](docs/報告/57_檢索品質解耦評測與知識圖譜場景化角色SDD任務書.md)，資料與續跑紀錄在 `data/eval/baseline_runs/20260920_frozen/`（附錄D）。**後續分析（§4.21）**：拒答事後重算 14/42（敏感度分析，凍結正式數字仍為 12/42）；20 題檢索失敗的 35 個 gold span 只有 1 個真的沒抽到，17 個是抽到但排名太後、14 個是抽到但被拆碎或丟限定條件、2 個被種子錨定的範圍排除——結論是**重抽 KG 不是主要方向**。條文層級擴充（同條文兄弟 Fact）是尚未驗證的假說。**日後任何候選修法與此基準對照時，仍須以該凍結條件（程式碼 `e178c4c`、題庫 `404cde9f…`、Windows Ollama 0.34.2）為準，不可與其他來源混比。** 歷史說明：對 42 題合格題（65 題中 verified 46、其中 4 題 wording 標記為未逐字複核而被排除）做 K arm 基準。凍結資訊：程式碼 commit `e178c4c`、題庫雜湊 `404cde9f…`、KG 16826 筆 Fact 且佇列 3307/3307 completed、qwen2.5:7b／bge-m3、範圍為 23 份 gold 文件的聯集。**凍結期間請勿**：修改 `data/eval/test_cases.json`、改動 `services/`／`routers/`／`scripts/eval/` 的行為程式碼、重抽或修改 KG、同時使用 Ollama（會拖慢並污染延遲，也曾因記憶體壓力中止過背景工作）。重複次數採品質門檻式規則（`scripts/eval/adaptive_repeat.py`）：達標＝無錯誤且 `is_perfect` 且 scope audit 通過；只在結果尚不能判定時才補跑，最多3次，並抽查約25%的單次通過題。結果與解除凍結會記在報告57 §4.20。

### 2026-09-19 最新進度（09-19 段落，被上方 09-20 段落部分取代）

1. **同版本 baseline 校正完成**：在目前 worktree HEAD `8afb1e5` 重新跑 dense `top_k=20`，AGGR15/16/17 各 3 次，9/9 完成、零 harness error。中位數為：AGGR15 Recall/Accuracy 100%/50%、SNR 10.54%、254 tokens；AGGR16 75%/50%、8.65%、265 tokens；AGGR17 100%/100%、5.10%、236 tokens。這組數字取代舊 main HEAD `682917d` 的 scope-on baseline 作為後續比較基準。
2. **候選與組裝路徑唯讀追蹤完成**：AGGR16 單方法文件 Fact-only 目標 Fact 排第21；完整 chat 方法＋母法 scope 去重後排第24。18行上限分成14 Fact＋4 BFS，目標 Fact 與等價 BFS 第5名都被排除。Fact budget 與 BFS 名額是目前漏召回的組裝邊界。
3. **BFS 名額 pilot 完成**：程序內將 `min_bfs_slots` 4→5、固定18行、AGGR15/16/17 K-arm ×3。AGGR16 Recall仍75%、SNR 8.65%、265 tokens，Atomic Accuracy中位數由50%升至100%（2/3全答對）；AGGR15/17主要指標中位數不變。沒有修改產品程式、KG設定或 Fact 資料。
4. **Fact embedding rerank 完成**：top-25 Fact 候選先做同鍵 Fact 優先去重，再用既有 query embedding scorer 排序。AGGR16 目標 Fact rank 24→15，但 Fact budget=14；三次 Recall均75%、Atomic Accuracy 50%/75%/75%（中位數75%）、SNR 7.52%、306 tokens。
5. **一格 boundary-swap 診斷完成**：將 rerank 後第15名目標 Fact 換入第14名，擠出第三類3000人門檻 Fact；固定18行下三次 Atomic Accuracy均100%，但 Recall仍75%、SNR 7.52%、306 tokens。這是上界型診斷，不是正式規則。
6. **gold 外主張風險閘門完成**：新增 deterministic 離線檢查，審查 AGGR15/16/17 的題目範圍外主張與條件錯置。原子正確且無風險通過數：current dense 1/9、BFS slots 5 3/9、Fact rerank 2/9、boundary-swap 0/3。boundary-swap 三次都加入500人門檻，並把第二類500人條件寫成「專責」；評分器原本不會扣這類 gold 外錯誤。
7. **正式狀態**：以上全部是 offline pilot／diagnostic。沒有把 rerank、boundary-swap、風險閘門接入 `chat()`，沒有修改全域 `top_k`、scope filter、Hybrid、`source_doc_cap`、BFS 預設名額、題庫或 Neo4j。報告57 §4.14–§4.15、報告60 最新段落已同步記錄。
8. **評測契約欄位化完成**：`TestCase` 新增 `answer_scope`、`required_claims`、`claim_audit_rules`；AGGR15/16/17 已填入規則。新增 `services/claim_scope_auditor.py`，RQ1 runner 每筆輸出新增 `scope_audit`。兩份題庫鏡像（`data/eval/test_cases.json`、`docs/附錄A題庫.json`）已確認相等。這是 offline evaluation infrastructure，不會影響正式 `chat()`。
9. **scope audit 基準與多題 boundary-swap 完成**：K-arm baseline、top-25 rerank no-swap matched control、top-25 boundary-swap 各9筆，全部零 harness error/timeout。只有 AGGR16 的必要 Fact 正好在 rank15／budget14，三次交換均移到rank14；AGGR15目標在rank5／budget16、AGGR17在rank1／budget14，兩題均不交換。AGGR16 Atomic Accuracy在 matched control→swap 為75%→100%，Recall維持75%、SNR與tokens不變，但 scope audit仍0/3通過，三次答案都留下500人適用條件／管理角色錯置風險。AGGR17的scope audit由baseline 1/3升為top-25 control 3/3，並非swap造成。細節見報告57 §4.17與報告60 §1.5；所有組別共用 generator/judge，僅屬 pilot。
10. **無逐題人工審查的自動採用判定（matched-v2）**：新增 `scripts/eval/compare_scope_audit_runs.py`，核對 manifests、資料雜湊、模型設定、arm與run編號，自動彙總 Atomic Accuracy、Context Recall、SNR、scope audit並產生 GO/NO-GO JSON。control與boundary-swap重跑各9/9，題庫雜湊相同（`46b7…a035`）；AGGR16 Atomic Accuracy由control 75%升至100%，Recall仍75%、SNR仍7.52%、scope audit仍0/3，AGGR15/17沒有因swap改善，故候選為NO-GO。dense baseline重跑仍是不同題庫雜湊（`a638…bae2`），完整三組比較不可用。詳報告57 §4.18、報告60 §1.6；63題只有3題有自動範圍規則；比較器6/6、auditor 3/3，合計9/9 targeted pytest通過；完整pytest未重跑。

### 本機分支與未提交異動快照（2026-09-19）

以下為本機 `git status`／本機 remote-tracking refs 的觀察結果；尚未執行 fetch，遠端追蹤 refs 未必反映伺服器最新狀態。

| Worktree | 分支／commit | 相對上游／主要分支 | 工作樹狀態 |
|---|---|---|---|
| 主要 checkout | `master` `682917d` | 與本機 `origin/master` 相同 | 有 1 個修改文件及 2 個未追蹤文件；視為既有使用者異動，不要納入本任務 commit。 |
| 檢索比較 | `worktree-sdd-retrieval-comparison` 最新為 scope audit 自動 gate 本地 commit | 2026-09-20 已推送，與 `origin/worktree-sdd-retrieval-comparison` 同步 | 11個明確選取的 schema、scope auditor、比較器、測試、題庫與報告檔已提交；多個未追蹤 scratch runner／評測輸出仍留在工作樹，沒有 stage。 |
| KG 重抽 | `reextract-v2` `a72cbaa` | 有本機 remote ref `origin/reextract-v2` (`0dc579c`)，但尚未設定 tracking upstream；相對該 ref ahead 6／behind 0。相對 `origin/worktree-sdd-retrieval-comparison` ahead 16／behind 167；相對 `master` ahead 16／behind 119。 | tracked 工作樹乾淨；12個未追蹤檔案（drain／修復／重抽 runner、pilot 與 baseline embedding），不屬於檢索比較任務，勿移動或清除。 |

（2026-09-19 快照，已於 09-20 推送）檢索比較分支當時有3個本地 commit：`5893a65`、`8afb1e5` 與 scope audit 自動 gate commit。該功能提交經兩組 targeted pytest 共9/9通過。臨時 runner 與 `rq1_*` 評測輸出仍未提交，先保留原地，等確認保留價值後再分類。比較分支相對 `master` 為 ahead 52／behind 1；不可直接把整條分支合併進 `master`，應先按主題拆分評審。`reextract-v2` 對應遠端 ref 已存在且本地比該 ref 多6個 commit，但 tracking upstream 尚未設定；它與比較分支的歷史大量分歧，不應整支互相 merge/rebase。任何 push、merge、rebase、reset 或 branch delete 均需在核對目標與差異後再做。

### 關鍵結果與解讀限制

| 題目 | scope off：Recall／Accuracy／SNR／tokens／K 延遲中位數 | scope on：Recall／Accuracy／SNR／tokens／K 延遲中位數 |
|---|---|---|
| AGGR15 | 100%／50%／18.17%／146／45秒 | 100%／50%／10.54%／254／35秒 |
| AGGR16 | 75%／50%／11.51%／197／216秒 | 100%／25%／9.97%／263／600秒 |
| AGGR17 | 66.7%／66.7%／6.21%／127／218秒 | 100%／100%／4.86%／246／524秒 |

- 三題各條件為3次完整 K-arm 問答；共用 `qwen2.5:7b` generator/judge，屬 pilot，`formal_evaluation=false`。延遲、答案正確率有模型與執行環境變異。
- Fact-only 單次掃描中，AGGR15／AGGR17 的 top_k=10 已由 semantic span judge 判定全數召回；相較 top_k=20，檢索文字分別少約42%／51%，SNR較高。這不是正式 end-to-end 結論。
- AGGR16 第二類「具中度風險」Fact 在範圍內第21名：top_k=20 未取回，top_k=25 才納入，top_k=35又開始納入第三類低度風險等其他內容。先擴候選再精煉，比直接把更多Fact送入context值得測試。
- Semantic judge 單次輸出有漏判與非單調情況：AGGR15 top_k=15判50%、top_k=20判100%；AGGR16 judge 漏判 top-20 原始清單中人工可辨識的第一類顯著風險 Fact。檢視原始 Fact 文字；不要把這些單次 judge 數字當正式 Recall。
- 逐字 exact-span 對自然語言化 Fact 全部判0，該表示法不適用作單獨品質分數；Fact-only表格的 Recall/SNR 使用與 RQ1 harness 同款 semantic span matcher。

### 已完成與下一步

1. **已完成**：scope audit 題庫欄位、AGGR15/16/17 K-arm ×3重跑、top-25 rerank matched control，以及多題 boundary-swap 診斷；結果仍未達正式接線門檻。
2. **下一步**：control/swap matched-v2 已完成，不需再重跑。優先固定相同檢索 context，離線測試 AGGR16 生成端條件完整性修正／拒答或再生成策略，control與candidate各×3後使用自動 gate；scope audit通過前不接入正式 `chat()`。若要比較 dense baseline，先凍結同一題庫快照並重跑全部組別，再逐步擴大更多已驗證題目的自動評估契約。
3. **接線門檻**：多題下 Recall、Atomic Accuracy、SNR與 scope audit 必須一起改善或不退步；目前不調全域 top_k、scope filter、Hybrid、source_doc_cap 或 BFS 預設名額。
4. **報告58/59**：報告58來源 Chunk 雙軌組裝仍是設計提案，待 Fact 精煉與風險評分穩定；報告59跨 KG 對齊仍等待跨 KG 使用案例與正反例黃金集。

## 實驗檔案與重現環境

- 原始 scope A/B 輸出：主要 checkout 的 `.claude/tmp/rq1_scope_ab_20260918_n3/`。
- Fact top_k semantic sweep：主要 checkout 的 `.claude/tmp/rq1_fact_topk_sweep_20260918_semantic/retrieval_results.json`。
- AGGR16 rank extension：主要 checkout 的 `.claude/tmp/rq1_fact_topk_aggr16_extension_20260918/retrieval_results.json`。
- 目前 worktree dense matched baseline：主要 checkout 的 `.claude/tmp/rq1_fact_ranking_20260918/current_dense_top_k20/`。
- BFS 名額 pilot：主要 checkout 的 `.claude/tmp/rq1_fact_ranking_20260918/bfs_slots_5/`。
- Fact rerank pilot：主要 checkout 的 `.claude/tmp/rq1_fact_ranking_20260918/fact_side_embedding_rerank/`。
- Boundary-swap pilot：主要 checkout 的 `.claude/tmp/rq1_fact_ranking_20260918/fact_boundary_swap/`。
- Gold 外主張風險明細：主要 checkout 的 `.claude/tmp/rq1_fact_ranking_20260918/claim_risk_audit.json`；執行器為 worktree `_audit_aggr16_claim_risk_20260919.py`。
- 題庫欄位審查器：worktree `services/claim_scope_auditor.py`；單元測試為 `tests/services/test_claim_scope_auditor.py`。
- 新scope audit K-arm輸出：主要 checkout `.claude/tmp/rq1_scope_audit_20260919/k_baseline/`。
- 多題 no-swap matched control：主要 checkout `.claude/tmp/rq1_scope_audit_20260919/fact_rerank_control_3q/`。
- 多題 boundary-swap：主要 checkout `.claude/tmp/rq1_scope_audit_20260919/fact_boundary_swap_3q/`；診斷 JSON 每列代表一次 prompt 組裝呼叫，複合題或 grounding regeneration 可能令一次 harness run 出現多列。
- 評測包裝器：worktree `_run_fact_boundary_swap_3q_eval_20260919.py`；直接執行為 swap，帶 `--control` 為同候選池 no-swap 對照。
- scratch runners 位於工作分支 worktree 的 `.claude/tmp/`：`rq1_scope_control_runner.py`、`rq1_fact_topk_retrieval_sweep.py`、`rq1_aggr16_fact_topk_extension.py`。這些檔案被忽略，尚未納入 Git；輸出 JSON 也在主要 checkout 的忽略目錄，換機/乾淨 clone 後未必存在。
- 重新執行評測時，須以主要 checkout 作為 process CWD 以載入其 `.env` 與 `workspace`，但確保 Python import 的應用程式碼來自本工作分支 worktree。不要在兩個 checkout 間混用版本；先查看 scratch runner 的 `REPO_ROOT` 設定及 help。

## 驗證與工作樹注意事項

- `a808391` 的程式驗證：全套 pytest 976 passed；本輪只新增 scratch audit 與文件紀錄，audit script syntax check、`git diff --check` 通過，未重跑 pytest。
- 本輪新增 schema／auditor 變更後，focused auditor tests 3/3 通過；harness failure tests 以工作區 `--basetemp` 重跑 2/2 通過；baseline/swap runner與評測程式 `py_compile` 通過。完整 pytest 尚未重跑。
- 多個既有 `rq1_*` ablation 目錄和 `_run_ablation_*.py` 在 worktree 為使用者既有未追蹤檔案，不要清理、移動或 stage。stage 檔案時逐一指定。
- 2026-09-20 使用者已授權並完成一次推送；之後新增的 commit 推送前仍須取得使用者明確同意。

## 相關設計文件

- [報告57：檢索品質解耦與場景化角色](docs/報告/57_檢索品質解耦評測與知識圖譜場景化角色SDD任務書.md)
- [報告58：來源 Chunk 提領與雙軌上下文組裝](docs/報告/58_圖遍歷端到端關聯Chunk提領與雙軌上下文組裝SDD任務書.md)
- [報告59：跨 KG 實體對齊與全域語意導航](docs/報告/59_跨KG實體對齊與全域語意導航設計概念記錄.md)
- [報告60：Codex 接續確認任務書](docs/報告/60_Codex接續確認交接任務書.md)
- [報告62：下一階段任務書（檢索排名與條文擴充驗證）](docs/報告/62_下一階段任務書_檢索排名與條文擴充驗證.md)
- [報告65：抽取粒度修復設計SDD任務書（F，方向A已核准並落地，定向重抽驗證背景執行中）](docs/報告/65_抽取粒度修復設計SDD任務書.md)
- [報告66：SVO抽取少樣本領域包參數化SDD任務書（交付Codex，須等報告65驗證完成才開始）](docs/報告/66_SVO抽取少樣本領域包參數化SDD任務書.md)
- [報告67：事實自然語言化（natural_text）品質問題SDD任務書（T1–T4全部完成）](docs/報告/67_事實自然語言化品質問題SDD任務書.md)
- [報告68：評測harness查詢embedding快取SDD任務書（交付Codex，尚未實作）](docs/報告/68_評測harness查詢embedding快取SDD任務書.md)
- [報告75：本體論設計資料夾專案整合候選盤點（純盤點，不含決策）](docs/報告/75_本體論設計資料夾專案整合候選盤點.md)
- [報告76：guard_profile領域可插拔化SDD任務書（✅ 完成+獨立複驗+已push，commit `2da08c0`）](docs/報告/76_guard_profile領域可插拔化SDD任務書.md)
- [報告77：法律模態關係型per-KG擴充SDD任務書（✅ 完成+獨立複驗+已push，commit `b598f34`）](docs/報告/77_法律模態關係型per-KG擴充SDD任務書.md)
- [報告78：S3落差題逐題根因診斷SDD任務書（✅ 完成，commit `ddbc4ac`，未push）](docs/報告/78_S3落差題逐題根因診斷SDD任務書.md)
- [報告79：S3評分器規則R敏感度分析SDD任務書（✅ 完成，commit `db39d8e`，未push）](docs/報告/79_S3評分器規則R敏感度分析SDD任務書.md)
- [報告80：S3結果回灌論文RQ1章節SDD任務書（✅ 完成+獨立複驗+已push，commit `4812e07`）](docs/報告/80_S3結果回灌論文RQ1章節SDD任務書.md)
- [報告81：S3落差題獨立模型盲審交叉驗證SDD任務書（✅ 完成+獨立複驗+已push，commit `ebc265e`）](docs/報告/81_S3落差題獨立模型盲審交叉驗證SDD任務書.md)
- [報告82：GAP-S3-01上下文組裝離線消融原型SDD任務書（✅ 完成+獨立複驗+已push，commit `db68e83`）](docs/報告/82_GAP_S3_01上下文組裝離線消融原型SDD任務書.md)
- [報告83：GAP-S3-01/02試驗結果回灌未來工作章節SDD任務書（✅ 完成+獨立複驗+已push，commit `2f6168a`）](docs/報告/83_GAP_S3_0102試驗結果回灌未來工作SDD任務書.md)
- [報告84：role_mismatch風險題庫全面掃描SDD任務書（✅ 完成+獨立複驗+已push，commit `e1e24fb`；結果見同名`...結果.md`）](docs/報告/84_role_mismatch風險題庫全面掃描SDD任務書.md)
- [報告85：57-AGGR6與57-AGGR19歸屬錯置精確pilot規則SDD任務書（✅ 完成+獨立複驗+已push，commit `2f8ddab`）](docs/報告/85_AGGR6與AGGR19歸屬錯置精確pilot規則SDD任務書.md)
- [報告86：RQ4a/4b追溯表同步報告76/77進度SDD任務書（✅ 完成+獨立複驗+已push，commit `664b3ef`；含1輪修正循環）](docs/報告/86_RQ4a4b追溯表同步報告76_77SDD任務書.md)
- [報告87：本體論設計資料夾尚待詳讀清單掃描SDD任務書（✅ 完成+獨立複驗+已push，commit `23a9ef8`）](docs/報告/87_本體論設計資料夾尚待詳讀清單掃描SDD任務書.md)
- [報告88：18-Q6與57-DIST2人工法規語意判定資料包（Claude Code直接彙整，非交付Codex；待使用者本人判定）](docs/報告/88_18Q6與57DIST2人工法規語意判定資料包.md)
- [報告89：worktree分支合併master前差異摘要SDD任務書 + 結果（✅ 完成+獨立複驗，commit `08ccc06`，未push）](docs/報告/89_worktree分支合併master前差異摘要SDD任務書.md)

### 2026-09-27 報告89完成獨立複驗——合併master不是單純fast-forward，8個高風險檔案待人工核對

**報告89已由Codex完成**（結果檔`docs/報告/89_worktree分支合併master前差異摘要結果.md`；因Codex執行環境`.git`索引無寫入權限未能自行commit，由Claude Code代為commit `08ccc06`，內容未修改）。**Claude Code已獨立複驗**：獨立重算merge-base（`b1c620e...`）、ahead/behind（98/54，與報告一致）、雙方改檔交集（39個，逐檔比對清單完全吻合）；抽查「內容相同21個」組（`atomic_scorer.py`等，確認`git diff`為空）與「內容不同18個」組（`svo_service.py`/`routers/agent.py`/`core/kg_config/model.py`，確認substantial diff）皆precise符合。無任何git分支操作、無merge/rebase/push發生，`master`checkout未被觸碰。

**核心結論：這不是單純fast-forward**——master領先本分支54個commit（含抽取端cfg接線、來源歧義audit、naturalization backfill等本分支不知情的獨立進度），雙方改檔交集39個中**18個最終內容仍不同**，其中8個列為「高」風險（`HANDOVER.md`、`routers/agent.py`、`services/svo_service.py`、`scripts/eval/run_rq1_comparison.py`、`core/kg_config/model.py`、`tests/core/test_kg_config.py`、`tests/routers/test_agent.py`、`tests/services/test_svo_service.py`）——同一批production抽取/生成路徑與評測harness API，master與本分支各自獨立演進，需要逐段人工核對，不能整檔互相覆蓋或依賴自動三方合併。

**待使用者決定**：是否依報告89 §4.2建議的分層順序（先純新增內容→內容相同組確認→設定schema成對檔案→production/harness核心檔案→長期累積文件）逐步處理合併；或採用其他策略。此決定尚未執行，`master`與本worktree分支現況皆未變動。

### 2026-09-26（續14）三個小型待辦處理：刪除gemini報告、report67 backfill維持擱置、report89交付Codex

**小雜務三選一處理**：①`docs/報告/gemini 整理報告.md`（未追蹤檔案）已直接刪除，無需commit。②report67 natural_text backfill（96/11,011筆，0.87%）使用者確認是誤會，維持「優先度低、先不處理」，不建立任務書。③worktree分支合併master：使用者要求「Codex做摘要報告，Claude檢查，同意才合併」——**不是直接交付Codex執行合併**。

查證發現重要事實：**這不是單純fast-forward情境**——本分支領先`origin/master` 97個commit（報告64-88全部），但`origin/master`也領先本分支**54個commit**（master有本分支不知情的獨立進度）。merge-base=`b1c620eac23dadce4b70d079cc83993c25de78ee`。`data/eval/`有158個變更檔案（多為評測產出，不宜逐檔列舉）。**報告89已產出**：純分析任務，絕對禁止Codex執行任何`git merge`/`git rebase`/push到master；要求交叉比對雙方改過的檔案清單找出衝突風險（特別注意`HANDOVER.md`、`00_研究追溯對映表.md`這類長期累積檔案）；明確要求報告只給客觀資訊供人判斷，不可自行下「建議合併」之類逾越授權的結論。**尚未執行，待貼給Codex。**

### 2026-09-26（續13）報告88：整理18-Q6/57-DIST2人工判定資料包，待使用者裁決

使用者選擇優先討論「S3診斷鏈殘留的18-Q6/57-DIST2評分爭議」，要求Claude Code直接彙整（非交付Codex）一份完整資料包供本人判定，要求「完整回答，不可省略」。**報告88已產出**：收錄兩題的完整gold facts、S0-K（兩次重跑逐字相同）/B0/B1全部完整答案原文（無截斷）、既有四項自動化判定（AtomicScorer原始判定、報告79規則R、報告81兩個盲審模型）彙整表。

**整理過程中發現一個先前報告未點出的新細節**：`57-DIST2`的S0-K答案內部有自相矛盾——先正確說「直轄市/縣市級模範警察或好人好事代表可獲得一至三日」，緊接著卻又說「直轄市/縣市級好人好事代表可獲得二至五日」（2-5日應屬全國性，此處歸屬有誤）。這與報告81盲審中`qwen3.5:4b`判「不支持」的理由（「誤將模範警察天數歸於好人好事代表」）呼應，但`granite4.2:3b`未抓到此問題判「支持」——已如實記入報告88 §2.2，不做預判，留給使用者判定「這是實質答錯還是表達累贅」。另發現B1答案的條號（第2條/第3條）與gold標註相反，僅供旁證，不影響AtomicScorer判定（該工具不比對條號）。

**待使用者裁決**：報告88 §3 判定表，兩題各判「算對/算錯/部分對」。裁決後將據此評估是否修改論文§6.2.1/§6.4對這兩題落差的描述。

### 2026-09-26（續12）報告87完成獨立複驗+已push——本體論設計資料夾這條線正式收尾，本輪session可自主完成項目已窮盡

**報告87已由Codex完成**（commit `23a9ef8`）。**Claude Code已獨立複驗**：`git status`確認只動report75一個檔案；逐段核對§7內容，七份優先文件摘要具體有辨識度、非套模板；重複性/取代關係核對確認屬實地做了逐行/逐節比對，非假設；低優先項目依指示選讀，沒有虛構內容湊產出。**結論誠實**：「沒有發現足以新增GAP候選的內容」，唯一值得保留的「重用評估Gate/CQ追溯矩陣」也正確標註為流程治理備忘、非技術GAP。**報告75「尚待詳讀」清單正式清空**，本體論設計資料夾這條線從最初盤點到現在已是完整候選清單。

**本輪session（報告75-87，共13份報告）自主可完成項目已窮盡**：剩餘清單（GAP-06/07重啟討論、per-KG斷點4設計、18-Q6/57-DIST2人工法規語意判定、GAP-S3-01擴大樣本、report67 natural_text backfill決策、`gemini報告.md`去留、worktree合併master、RQ2-RQ6新方向）全部需要使用者自己的判斷/決定，無法再排成Codex可自主執行的任務書。下一步接手者應先跟使用者確認要往哪個方向，不要predict或代為決定。

### 2026-09-26（續11）候選清單盤點 + 報告87交付Codex（尚待詳讀清單掃描）

依使用者要求「把剛剛還有哪些建議做但不是最優先的項目都列出來討論」，系統性整理了4類未執行項目：(A)本體論設計候選（GAP-06/07、per-KG斷點2/4、概念候選、尚待詳讀清單）、(B)S3診斷鏈未竟支線（18-Q6/57-DIST2人工判定、GAP-S3-01擴大樣本、DIST1/2/3）、(C)小型雜務（報告67 backfill決策、gemini報告去留、worktree合併master）、(D)RQ2-RQ6新方向。

評估哪個適合排Codex長任務時，**再次發現查證錯誤並自行更正**：原以為per-KG設定斷點2（切塊配置ChunkingConfig）仍未接線，實際查證`services/svo_service.py::trigger_extraction()`後確認**報告56（2026-09-14）早已完整接線並有測試覆蓋**——先前查`extraction_worker.py`是查錯函式（該函式本來就只消費已切好的chunk，不是切塊設定接線點）。斷點4則需先設計設定結構，不適合直接排任務書。誠實排除所有不適合的候選後，**只剩「尚待詳讀清單」符合零風險、範圍明確、可自主完成**。**報告87已產出**：純閱讀回報任務，明確警告該路徑（`D:\Users\666\Desktop\本體論設計\`）在本git repo之外，若環境無法存取需如實回報限制而非臆測內容；明確要求「預期結果很可能是沒有新東西，這是合理結論，不可為湊產出而誇大」。**尚未執行，待貼給Codex。**

### 2026-09-26（續10）報告86完成獨立複驗，含一輪修正循環——RQ4a/4b追溯表同步收尾

**報告86第一次執行（commit `a1691a2`）獨立複驗時發現真實偏差**：Codex把RQ4b「判定」欄裡`_SCOPE_MODIFIER_PATTERN`剩餘缺口的具體描述（「每一型式」vs「每增加一種型式」）整句刪除，換成自我指涉但已無所指的空話「原有描述維持不變」——資訊遺失，不是任務書原意。**已發修正指令並記入報告86附錄（commit `bb64d75`）**，Codex重新執行（commit `664b3ef`）後**獨立grep確認「每一型式」「每增加一種型式」兩個具體例子確實回到檔案裡**，措辭也正確反映現況（`_SCOPE_MODIFIER_PATTERN`已可配置化，但覆蓋率與全量重抽驗證仍未完成）。RQ4a列與§3「受控關係型別與未知型別仲裁」列自第一次執行起就逐字吻合任務書規格，未受影響。

**至此RQ4a/RQ4b追溯表同步任務完整收尾，累積commit已push**。這也是本輪session第一次在複驗時抓到需要打回修正的偏差，證明獨立複驗這個環節本身有實質價值，不是走過場。

### 2026-09-26（續9）報告86交付Codex——RQ4a/4b追溯表同步（小型、可自主執行的長任務）

使用者要求「先做RQ4a/RQ4b小更新」但希望備妥成一份**冷啟動、可讓Codex自主執行完不需來回確認**的完整任務書。查證`00_研究追溯對映表.md`現況：RQ4a（受控語意關係詞彙標準化）與RQ4b（實體指代/別名/跨文件對齊）兩列的「04/程式現況」欄尚未反映報告76（guard_profile per-KG可配置化）與報告77（rel_type_extensions per-KG可擴充關係詞彙）的已完成進度。**報告86已產出**：任務書直接寫好確切要插入的新舊文字（Codex只需核對現況後插入，不需自行設計措辭），唯一留給Codex判斷的是`_SCOPE_MODIFIER_PATTERN`「待全量重抽完成後才上線」這句是否已因報告76過時。明確要求**不可把判定結論升級成「RQ已完成」**，只誠實補上新機制、消融實驗未完成的結論維持不變。**尚未執行，待貼給Codex。**

### 2026-09-26（續8）報告85完成獨立複驗——role_mismatch追蹤線完整收尾

**報告85已由Codex完成**（commit `2f8ddab`）。**Claude Code已獨立複驗**：`git diff --stat`確認只動`test_cases.json`與`test_claim_scope_auditor.py`；兩條新規則（`aggr6-branch-category-swapped`／`aggr19-version-label-swapped`）的`trigger_patterns`皆為真實記錄逐字擷取；獨立重跑完整pytest得**1122 passed**，`test_claim_scope_auditor.py`單獨9 passed含4個新測試全過；**獨立對`test_cases.json`重新算SHA-256得`77c293ed...`，與commit message宣稱的新雜湊逐字吻合**。

**role_mismatch這條追蹤線至此完整收尾**：先發現機制其實已存在且已接線（推翻「S3準確率被系統性高估」的原假設）→ 全題庫掃描（報告84）找到2個真實未覆蓋案例（`57-AGGR6`／`57-AGGR19`）→ 補上精確pilot規則並驗證（報告85）。累積1個未推送commit，待使用者決定push與否及後續方向。

### 2026-09-26（續7）報告84完成獨立複驗+已push——找到2個真實未覆蓋案例 + 報告85交付Codex

**報告84已由Codex完成**（commit `e1e24fb`，已push）。**Claude Code已獨立複驗**：`git show --stat`確認只新增結果文件；獨立讀取`s3_chunk_rag_b1_stage_a`的`57-AGGR6`完整答案原文，確認Codex描述屬實——答案在「資遣費」標題下正確列出第25/26條，卻又在「退休金」標題下把第25條重新列一次、動詞從「發給勞工資遣費」改寫成「發給勞工退休金」，形成自相矛盾的類別歸屬，但4個gold span逐字版本仍完整出現，`AtomicScorer`判4/4完美通過（`atomic_accuracy=1.0`），完全沒抓到。**這次掃描（19題結構初篩→5題符合role_mismatch結構→2題`57-AGGR6`/`57-AGGR19`查到真實未覆蓋案例）是真實、有具體證據的新發現**，Codex沒有為了湊產出而灌水（`57-DIST1/2/3`誠實保留為「結構有風險但無乾淨對調證據」，未升格）。

使用者同意補這2條精確pilot規則。**報告85已產出**：比照`57-AGGR18`既有的`aggr18-institution-swapped`寫法，要求Codex重新讀取完整答案原文自行設計`trigger_patterns`（不可只憑報告84摘錄）、比照既有`test_claim_scope_auditor.py`的配對測試寫法（真實錯誤答案被抓到+正確答案通過各一組），並明確警告**這會改變`test_cases.json`的`bank_sha256`**——比照報告62 §14.10先例，是預期中的題庫修正，非意外。**尚未執行，待貼給Codex。**

### 2026-09-26（續6）報告83收尾 + 報告84交付Codex（role_mismatch題庫全面掃描）

**報告83已獨立複驗並push**（commit `2f6168a`）：`git show --stat`確認只改07_結論與未來工作.md一個檔案，新增的兩段文字數字（3/10、6/10、2/2、175%、3/11=27.3%、9/11=81.8%、5/11=45.5%）逐字核對與報告81/82原始結論吻合，措辭正確做到「已試驗、證據不足、非永久否定」。至此整個S3系列（72→78→79→80→81→82→83）完整收尾。

依使用者選擇「先做A」（57-AGGR18 role_mismatch規則泛化）後深入查證，**發現原先假設有誤**：`claim_scope_auditor.py::audit_answer_scope()`已接線在`run_rq1_comparison.py`（S3用的主harness），`test_cases.json`的`57-AGGR18`也已有專門的`claim_audit_rules`（`aggr18-institution-swapped`）。掃描S3全部5筆`57-AGGR18`記錄（S0×2/B0×1/B1×2），**沒有一筆真的機構寫反**，`scope_audit.passed`全部正確為true——這代表「role_mismatch讓S3準確率被高估」這個反覆被提及的警語，在這次S3資料裡並未被證實真的發生。使用者確認方向：**先掃全題庫查其他未覆蓋的風險，而非直接建通用機制**。用關鍵字掃描65題題庫找到21題結構性風險候選（新舊法對照/相鄰陷阱類型），僅2題（`57-AGGR15`/`57-AGGR18`）已有覆蓋，其餘19題待逐題判讀。**報告84已產出**，純離線文字分析，不呼叫LLM、不改程式碼，要求先篩出真正符合「歸屬角色寫反」風險類型的題目（非所有19題都符合），再查既有記錄有無實際發作案例，最後給出「值不值得建通用機制」的誠實結論。**尚未執行，待貼給Codex。**

### 2026-09-26（續5）報告83交付Codex——收尾GAP-S3-01/02回灌論文§7.4

依使用者要求「先做A」（補§7.4過時陳述，非啟動RQ2-RQ6新工作）。§7.4現行GAP-S3-01/GAP-S3-02兩點是報告80寫的，當時兩者都還沒試過，措辭是「尚未嘗試的未來方向」；現在報告81/82都已完成小規模試驗，**報告83已產出**，範圍極小（只改07_結論與未來工作.md，§6.4是否補充留給Codex裁量），要求保留既有背景文字、只補充試驗結果與明確結論，措辭紀律「已試驗、證據不足、非永久否定」不可寫成「已排除」。**尚未執行，待貼給Codex。**

### 2026-09-26（續4）報告82完成獨立複驗——GAP-S3-01/02兩條線皆已驗證完畢，暫緩投入

**報告82已由Codex完成**（commit `db68e83`）。**Claude Code已獨立複驗**：`git diff --stat`確認`routers/`／`services/`／`core/`／`docs/論文/`零異動；直接解析原始JSON的`atomic_score.is_perfect`與`target_span_supported`欄位逐筆核對，得到is_perfect 3/10、目標span支持6/10，與回報一致；逐題細節（18-Q6穩定2/2、18-Q1不穩定且run2出現新迴歸——baseline原本答對的「未住院者一年內合計不得超過三十日」反而變缺失）皆在原始資料中屬實。**Codex額外抓到一個精確歸因**：`57-AGGR14`答案把「從業」寫成簡體「从業」導致逐字scorer判定失敗，不是內容沒讀到，是表面形式問題，沒有被籠統算成消融無效。

**結論：GAP-S3-01（上下文組裝）跟GAP-S3-02（評分器正式驗證，見報告81）兩條線皆已用最小成本驗證完畢，結論都是「目前證據不支持投入更大工程」**——GAP-S3-01只有`18-Q6`一題乾淨正向訊號，其餘不穩定/被表面形式卡住/無改善，且伴隨答案冗長化副作用；GAP-S3-02的獨立模型盲審一致率過低（5/11）無法提供有力佐證。兩個報告都留了「除非未來有新的更大樣本證據」的但書，不是永久否定，只是暫緩。**累積2個未推送commit**（`db68e83`及後續HANDOVER更新），待使用者決定push與否及後續方向（回到RQ2-RQ6其他空白章節、或其他優先事項）。

### 2026-09-26（續3）報告81完成獨立複驗+已push + 報告82交付Codex（GAP-S3-01縮小範圍原型）

**報告81已由Codex完成**（commit `ebc265e`，已push）。**Claude Code已獨立複驗**：`git status`確認零多餘異動；獨立重算11筆盲審資料的一致率，與Codex回報數字精確吻合（Granite對原評分器3/11、對規則R5/11；Qwen皆9/11；兩模型彼此5/11）；`57-AGGR6`四個分支Granite全支持/Qwen全不支持的系統性分歧在原始資料裡真實存在。**結論：本次交叉驗證確實「未能提供有力佐證」**，Codex誠實寫出「沒有理由宣稱−6比−8更接近真值」，未回灌論文，§9/§11兩組數字都保留。GAP-S3-02的自動化驗證路徑到此為止——報告72 §12.4建議需要人工法規語意adjudication才能再進一步。

依使用者要求轉向GAP-S3-01（上下文組裝）。完整讀過報告58後發現其設計規模大（ContextBundle/Manifest source resolver/chat()接線），且該報告自己已誠實訂正文獻佐證為「過度宣稱」，具體參數（3~5個chunk等）是未驗證假設值。**沒有照單全收整份設計**，而是縮小成一個離線消融原型：重用報告72 §11.1已示範過的B1 chunk還原方法（`baseline_rag_index_*.json`按`retrieved_chunk_ids`離線還原），對報告78診斷出的5題Stage3生成端遺漏案例（`18-Q1`/`18-Q6`/`57-AGGR14`/`57-COREF3`/`57-DIST2`），只加1個段落（不是報告58原稿的3~5個）、重新生成2次、用既有`AtomicScorer`離線評分，**不建立ContextBundle、不動`chat()`**，先驗證核心假說值不值得投入完整工程。**報告82已產出**，需呼叫本機Ollama（生成，非Neo4j），2026-09-26已用ListAgents確認無資源衝突。**尚未執行，待貼給Codex。**

### 2026-09-26（續2）8個累積commit已push + 報告81交付Codex（GAP-S3-02獨立模型交叉驗證）

**使用者已同意push**，累積的8個commit（`4c7cb69`～`fe05687`，含報告72 S3/78/79/80全部工作）已於2026-09-26推送，`origin/worktree-sdd-retrieval-comparison`現與本地一致（`fe05687`）。

依使用者要求，在GAP-S3-01（上下文組裝，工程量大且奠基文獻已被自己訂正為過度宣稱）與GAP-S3-02（評分器正式驗證）之間，**選擇先做GAP-S3-02**——理由：規則R只是樣本內診斷工具，報告80已誠實聲明不能把−6題當真實落差，先花小成本確認這個結果可不可信，再決定是否投入GAP-S3-01大工程。查證發現報告62 §14.6已建立獨立模型盲審交叉驗證機制（`scripts/eval/scorer_audit_crosscheck.py`，granite4.2:3b/qwen3.5:4b盲審），但當時一致率只有52.8%/69.0%，「幾乎沒有參考價值」——**報告81已產出**，直接import既有PROMPT/ask()/unload()機制套到S3落差題的7個爭議span（排除17-Q6候選未形成、canary-P4拒答校準），要求「不要預期乾淨結論，若結果同樣模糊要如實寫出未能提供有力佐證」。**這次需要呼叫本機Ollama**（跟報告79純離線分析不同），2026-09-26已用ListAgents確認無其他session使用Neo4j/Ollama。**尚未執行，待貼給Codex。**

### 2026-09-26（續）報告80完成獨立複驗——S3→78→79→80整條診斷鏈收斂完成

**報告80已由Codex完成**（commit `4812e07`）。**Claude Code已獨立複驗**：`git show --stat`確認只動`docs/論文/00`／`05`／`06`／`07`四個檔案；額外`git diff --stat`確認01-04章、`docs/參考文獻/`、`services/`、`scripts/`零異動；逐項核對第六章§6.2.1的四個arm數字表與McNemar p值（原評分器−8/0.021484、規則R−6/0.109375，B0對應−7/0.065430與−7/0.092285），與先前獨立驗證過的數字逐字一致。**誠實紀律確實遵守**：原評分器與規則R兩組數字並列呈現、reranker啟用狀態寫成「待確認」未臆測、top-k未校準落差三處一致揭露、GAP-S3-01明確提醒報告58文獻佐證已被自己訂正為過度宣稱、沒有新增任何文獻引用、§7.4既有清單原封不動只在後面新增。小瑕疵（不影響正確性）：§6.2.1新增段落與`### 6.2.2`標題間少一個空行，未修正。

**這條從S3對照組開始的診斷鏈（報告72 S3→報告78根因診斷→報告79評分器敏感度→報告80論文回灌）已完整收斂**：第六章§6.2.1（RQ1）與第七章§7.3不再是TODO/過時條件句，00_研究追溯對映表.md的RQ1判定欄已更新。**累積7個未推送commit**（`4c7cb69`～`4812e07`），待使用者決定push與否及下一步方向（GAP-S3-01/02是否繼續、或轉向其他RQ）。

### 2026-09-26 報告79完成獨立複驗 + 報告80交付Codex（S3結果回灌論文）

**報告79已由Codex完成**（commit `db39d8e`）。**Claude Code已獨立複驗**：`git diff --stat`確認`services/atomic_scorer.py`／`docs/論文/`零異動；McNemar p值（S0vsB0原始0.038574/規則R0.092285、S0vsB1原始0.021484/規則R0.109375）自行用exact binomial公式重算全部精確吻合；直接讀取`s3_rule_r_rejudge.json`原始資料核對S0(13→16)/B0(21→23)/B1(21→22)通過數與翻盤題目清單。**結論：規則R敏感度分析後，KG相對B1的落差由−8/p=0.0215（顯著）縮至−6/p=0.109（不再顯著）**；方向仍是chunk-RAG領先，但原顯著性不穩健。

依使用者要求「整理論文，確認01/02/03/04等章節對應連接」，盤點`docs/論文/`後發現極乾淨的既有對應：**第五章§5.4.1早已預先設計了B0/B1強基準對照實驗**（明文規定「B1是RQ1的硬前提」「B1跑出結果前，RQ1優勢陳述須限定為相較pure-LLM」），**第六章§6.2.1（RQ1結果與討論）完全空白**，**00_研究追溯對映表.md的RQ1判定欄仍寫「完整基準比較尚未完成」**（已過時）——S3就是這個早已設計好、只是一直沒跑完的實驗，核心論點文獻（Han 2025/Xiang 2025/Fan 2026：GraphRAG優勢具任務依賴性）已在第二章§2.3到位，**不需要新文獻查證**。唯一發現的落差：B1實際跑用固定top-k=5，未依§5.4.1原計畫做`{3,5,10}`校準，需誠實揭露。**報告80已產出**，範圍限定00/05/06/07四個論文檔案，要求「原評分器＋規則R兩組數字並列，不選擇性引用」「誠實負向結果，不美化不過度悲觀」。**尚未執行，待貼給Codex。**

### 2026-09-25（續4）報告78完成獨立複驗 + 報告79交付Codex（GAP-S3-02優先於GAP-S3-01）

**報告78已由Codex完成**（commit `ddbc4ac`）。**Claude Code已獨立複驗**：`git diff --stat`確認只動report72一個檔案；獨立抽查`18-Q6`——直接讀S0原始record答案原文，確認模型答案逐字引用「一年內事假不得累計超過十四日」（證明該事實確實在prompt裡），跟gold span「一年內合計不得超過十四日」語意相同措辭不同，印證Codex「評分器表面形式脆弱性」的判定。**Codex的診斷比報告75/78草稿的種子發現更精細**：修正了原本「5生成+3檢索+1拒答」的粗略分類，逐題附證據判定GAP-04/06/07**各自對應0題**，並提出兩個新追蹤項（暫名）：GAP-S3-01（法律條文上下文呈現/生成引用率）、GAP-S3-02（scorer表面形式脆弱性）。

依討論結果，**先做GAP-S3-02（成本低，重用報告62 §14既有的規則R敏感度分析工具與腳本）再看要不要做GAP-S3-01（成本高，報告58的雙軌上下文組裝設計本身"尚未進入程式實作"且文獻佐證已被自己訂正為"過度宣稱"）**。**報告79已產出**：查證確認`scripts/eval/scorer_rule_sensitivity.py`寫死指向舊的`20260920_frozen`基準，不能直接套用S3資料，任務書要求新增一個小腳本import（非複製）既有函式、換成S3的資料路徑，專項驗證`18-Q6`/`57-DIST2`是否在規則R下翻盤，並要求「不論規則R讓落差變大還是變小，都要如實寫出來」。純離線重算，不改production評分邏輯。**尚未執行，待貼給Codex。**

### 2026-09-25（續3）報告72 S3完成獨立複驗 + 報告78交付Codex（診斷優先於Track A）

**報告72 S3已由Codex完成**（commit `4c7cb69`）：S0 K基準13/42、D(無檢索)2/42、B0(naive chunk-RAG)20/42、B1(hybrid chunk-RAG)21/42。**Claude Code已獨立複驗**：`git diff --stat`確認services/models/core/routers/scripts/kg全零異動；直接讀取三個arm的adaptive_summary原始JSON逐一加總status_counts，與報告數字逐字吻合；McNemar p值（B0=0.0654／B1=0.0215／D=0.0034）自行用exact binomial公式重算，與回報精確吻合到小數點後四位；獨立重跑pytest得1118 passed（與報告77後一致，因無程式碼變動）。**結論：B1淨勝KG 8題，p=0.0215達統計顯著，目前沒有證據顯示這個KG相對做得夠好的chunk-RAG有整體增益**（KG相對無檢索control仍有明顯增益，不是「檢索沒用」）。**commit `4c7cb69`尚未push，使用者尚未回覆是否推送**，之後接手者需先確認這點再push，不要假設已推送。

依討論順序（先診斷再決定要不要修），**沒有直接排GAP-04/06/07進任務書**，而是先深入查了B1贏過S0的9題（`17-Q6`／`18-Q1`／`18-Q6`／`canary-P4`／`57-COREF3`／`57-DIST2`／`57-AGGR6`／`57-AGGR14`／`57-AGGR19`）。**初步讀取S0 K arm每筆record既有的`lineage.failure_attribution`欄位發現重要訊號**：5題是Stage3生成端失敗（事實在prompt裡，LLM遺漏/抹平）、3題是Stage1檢索端失敗、1題是Type-E拒答校準失敗——**跟GAP-04/06/07（皆屬抽取端/圖結構候選）明顯無關的至少有6題**。抽查`57-AGGR19`發現疑似是評分器逐字比對脆弱性（gold要求「準用勞動基準法規定預告勞工」，排名第1、已in_prompt的候選文字缺「準用」兩字），不是抽取缺陷。**報告78已產出**，要求Codex逐題重新核實（不可只複製種子發現）、逐一判定GAP-04/06/07是否對得上因，並明確要求「對不上因就誠實記錄，不可牽強附會」。純離線JSON分析，不寫程式碼、不需Neo4j/Ollama。**尚未執行，待貼給Codex。**

### 2026-09-25（續2）報告77完成獨立複驗 + 4個commit已push

**報告77已由Codex完成**（commit `b598f34`）：`RelTypeExtension`+`DomainConfig.rel_type_extensions`四筆內容逐字符合任務書；`core/constants.py`/`docs/論文/`兩條紅線皆未觸碰（`git diff --stat`確認）；`_TYPE_DESCRIPTION_EMBEDDING_CACHE`快取key正確改為`(model_name, 排序後描述項目tuple)`；**額外修正了任務書未明講的細節**——`resolve_query_relation_type()`內原本用`SVO_REL_TYPE_DESCRIPTIONS[best_type]`組LLM仲裁prompt，查詢解析到`OBLIGATES`時會KeyError崩潰，Codex正確改用有效描述字典。**Claude Code已獨立複驗**：獨立重跑pytest得**1118 passed**與回報一致，逐一核對diff內容，`config/domain_packs/generic.json`正確覆寫`rel_type_extensions: []`，T8迴歸測試全數到位且用「預設cfg vs核心-only cfg」雙向對照證明機制真的生效。commit message含完整文獻誠實聲明。

**使用者已同意push，4個累積commit（`34058d5`／`2da08c0`／`d43cc05`／`b598f34`）已於2026-09-25推送**，`origin/worktree-sdd-retrieval-comparison`現與本地一致（`b598f34`）。

**使用者決定：先做完報告62/72的既有殘留待辦（S3），再回頭做本體論設計資料夾的新候選（GAP-04殘留邊界／GAP-06／GAP-07）。** [報告72](docs/報告/72_報告62殘留待辦新基準與K1b_T3_chunkRAG任務書.md) §8已記錄：S0新基準13/42，S1（K1b）＋S2（K1/K2/K3 article_expand）四個候選臂全數「需更多證據，不建議採用」，**S3（chunk-RAG對照組，決策點D1）尚未執行**。2026-09-25已用ListAgents確認無其他session同時使用Neo4j/Ollama，**授權交付Codex執行S3**（依報告72 §2 S3節既定設計，不重跑S0-S2）。

### 2026-09-25（續）報告76完成獨立複驗 + 報告77交付Codex

**報告76已由Codex完成**（commit `2da08c0`，未push）：`GuardConfig`五欄位切法未調整、正則結構固定/token清單可配置切法正確、`resolve_entity_name`/`_naturalize_triple`/`_naturalization_dropped_quantity`/`merge_triples_to_graph`/`backfill_natural_text`全數補上`cfg`參數、§1.2的14個迴歸案例全部轉成golden test。**Claude Code已獨立複驗**：`git show --stat`確認範圍只在9個允許檔案內、`routers/agent.py`未觸碰、獨立重跑`pytest`得**1111 passed**與Codex回報一致、逐一核對`GuardConfig`/正則重構/14條迴歸測試diff內容與任務書規格相符。額外做了任務書沒要求但合理的加分項：`core/kg_config/stages.py`註冊`dedup.guard` stage。**尚未push，待使用者決定。**

依報告75候選序，下一項原訂GAP-04（條件-效果綁定），但查證發現**已被報告65「規則10」部分解決**（2026-09-22落地，report66已參數化）——對「單一條件→結果」有效，對「多個並列條件→共享結果」明確無效（c84/c85已知邊界，非bug），故改選GAP-03（法律模態關係型）。**查證發現比預期複雜**：`SVO_REL_TYPES`被`docs/論文/02_文獻探討.md`明文定義為「恰好等於ConceptNet 5.5官方35個核心關係，逐一可追溯」，有完整的35→33→35查證訂正史，直接加入4個新型別會破壞此學術主張；且該集合同時被抽取端REJECT、BFS圖遍歷Cypher關係型別過濾、SIM/QSIM embedding比對三處共用。使用者確認採用「新建per-KG可覆蓋的域名關係型擴充集」方案（`DomainConfig.rel_type_extensions`，`SVO_REL_TYPES`本身不動）——**報告77已產出**，含文獻誠實聲明紅線（不可宣稱LKIF-Core已查證）、`_type_description_embeddings()`快取key污染風險的具體修法。**尚未執行，待貼給Codex。**

### 2026-09-25 報告75/76：外部本體論設計資料夾盤點 + guard_profile任務書交付Codex

使用者提供 `D:\Users\666\Desktop\本體論設計` 資料夾（獨立於本 repo 的姊妹研究，含本體工程理論、缺口紀錄表、per-KG設定架構報告書等），要求盤點跟本專案的接入可能性。**報告75**（純盤點，不含決策）分五類整理：已對照程式碼驗證的近期候選（GAP-03/04/06/07、per-KG設定斷點）、需先驗證的中長期方向、不建議近期混入（其他產品線如「台灣中小企業數位人資長」規則引擎、異領域案例）、未查證文獻對照、尚待詳讀清單。過程中發現該資料夾的「知識圖譜分層客製化架構報告書」列的「per-KG設定斷點1（few-shot參數化）」**其實已經在報告66完成**，報告75已更正。

使用者選擇優先把「guard_profile（第4步）」排成長任務交付Codex。查證後發現實際範圍比預期複雜：`services/svo_service.py:544-604` 的4組正則（`_MEASURE_PATTERN`／`_RANGE_COMPARATOR_PATTERN`／`_ENUM_GUARD_PATTERN`／`_SCOPE_MODIFIER_PATTERN`）背後是報告20/26/29/32共14個真實迴歸案例，且 `resolve_entity_name()`／`_naturalize_triple()`／`_naturalization_dropped_quantity()` 目前都不接受 `cfg`，需要新增DI鏈路。使用者確認仍按此方向進行，但要求加強迴歸測試——**報告76**已產出，設計「結構固定（CJK通用格式）＋domain token清單（可配置）」切法，T6迴歸測試套件要求§1.2表格14個案例全部轉成golden test。**尚未執行，待貼給Codex。**

### 2026-09-22 報告66 T1–T6：SVO 少樣本領域包參數化已實作

本段完成報告66 的 T1–T6；沒有執行任何 KG 重抽，也沒有修改 Neo4j、
`guard_profile` 或 `_NATURALIZE_PROMPT_TEMPLATE`。

#### 實作內容

1. **T1／設定模型**：`svo_fewshots` 放在 `core/kg_config/model.py::DomainConfig`，型別為
   `tuple[str, ...]`，由 `_DEFAULT_SVO_FEWSHOTS` 集中保存規則 6–10 的 shipped
   內容。選 `DomainConfig` 是因為這些例句是 domain pack 的語意覆蓋，不是抽取門檻；
   也避免 `svo_service.py` 與設定模型各維護一份長字串。
2. **T2／prompt 組裝**：`services/svo_service.py::_svo_prompt()` 接受 keyword-only
   `fewshots`；`None` 使用 shipped defaults，指定 tuple/list 時從規則 6 開始動態編號。
   規則 1–5 保持共用骨架；為維持 35f95ab（含報告65規則10）的逐字相容，保留既有
   規則 6 與規則 7 之間的單換行、其後例句之間的空行差異。
3. **T3／抽取 API**：`extract_svo_triples()` 與
   `extract_svo_triples_with_completeness_check()` 新增 optional keyword-only `cfg`，
   初抽與未涵蓋句補抽都沿用同一份 `cfg.domain.svo_fewshots`；未傳 `cfg` 時仍為
   shipped defaults，既有呼叫端相容。
4. **T4／抽取端佈線**：`services/extraction_worker.py` 比照
   `routers/agent.py::chat()` 使用 `ConfigLoader([FileConfigSource(settings.kg_config_dir)])`
   讀取 KG 的 `domain_pack`，再把 `cfg` 傳給完整性抽取函式。設定檔缺失、格式錯誤或
   loader 失敗時記錄例外並 fallback 到 `KGConfig()`，不讓單一設定阻斷 worker。
5. **T5／domain pack**：`taiwan-labor-law` 不新增覆蓋，故組出的 prompt 使用同一組
   shipped defaults；`generic` 的說明更新為「可覆蓋但目前沿用 shipped defaults」。
6. **T6／驗證**：新增 shipped default 與 `taiwan-labor-law` domain pack 的 prompt
   golden test；兩者針對 `測試` 的 SHA-256 均為
   `40a8417833e67e343f9e3164c090b1032512620d68e36340aec986b0d56a7fb3`。另測試自訂
   fewshots 編號、抽取 cfg 傳遞、worker domain pack 路由與 fallback。

#### 成本與未接線事項

- 每個抽取 chunk 目前會載入一次設定並建構一個 immutable `KGConfig`；這是小量的
  Python／檔案讀取成本，沒有額外 LLM call。若日後量測到大量 chunk 的設定讀取成本，
  可再按 KG 做 cache，但本次先保留正確性與設定變更可見性。
- 這個解耦只參數化 SVO prompt 的 domain fewshots，不會新增 provider、模型載入或
  Ollama 呼叫；因此不會改變生成延遲。T-B 的生成模型／grounding judge provider 解耦
  仍維持先前評估結論，未在本段接線。
- 尚未在本段宣稱任何模型能力改善；後續是否執行 T-C，仍須由使用者決定並以修好的
  `think:false`、凍結題庫與公平條件重跑。

#### 驗證紀錄

- `python -m pytest tests/services/test_svo_service.py tests/core/test_kg_config.py -q -p no:cacheprovider`：292 passed。
- `python -m pytest tests/services/test_extraction_worker.py -q -p no:cacheprovider`：9 passed。
- 完整命令 `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py`：1055 passed，8 warnings，59.02s。

### 2026-09-22 小範圍K-arm驗證（報告65 §9）：抽取修復已生效，被三個下游瓶頸擋住

用新題庫（`23f8c06f…`）對7題（`18-Q5`／`57-AGGR7`／`57-AGGR8`／`57-AGGR19`／`57-CANARY5`／`57-DIST1`／`57-DIST2`）各跑一次K-arm（背景fork執行，pilot性質）。**7題全部`is_perfect=false`，但這不代表今天的抽取端修復沒用**：

1. **修復本身在KG層面已生效**：`57-CANARY5`（本輪人工修正）與`57-DIST1`兩題，修正後的正確內容都**逐字進了prompt**，但生成端沒引用／模糊化掉——卡在已知的生成端問題（報告62 §13同類），不是今天工作造成的新問題。
2. **`57-AGGR7`（規則10教科書案例）印證了已知取捨**：修好的事實在前65名檢索候選裡完全找不到，疑似verb變長稀釋了embedding辨識度（報告65 §3.1已預先標註這個風險，現在有實測證據）。
3. **`57-AGGR19`（c85）發現一個全新、獨立的問題**：修正後的事實排名**第0名（分數最高）卻 `in_prompt:false`**，反而是排名第14、用「僱主」異體字的近似重複版本被排進prompt——疑似組裝端有個去重/多樣性機制誤排除了排名最高的正確事實。**這是抽取粒度問題以外的獨立發現**，成本可能比繼續深化規則10更低（純工程問題，不需要跟LLM非決定性搏鬥），值得優先調查。
4. `57-AGGR8`（c18，已知未修復）符合預期，沒有意外。

**結論**：抽取粒度（方向A）已經不是主要瓶頸，下一步該處理生成端引用率／檢索排名代價／組裝端去重問題，尤其`57-AGGR19`的去重排除機制。詳見報告65 §9。

### 2026-09-22 `57-AGGR19`去重根因定位＋全KG驗證（報告65 §10）：不切換預設值，natural_text品質問題另開報告67

**根因**：`routers/agent.py::_split_fact_lines()` 跨來源去重，BFS 三元組先處理、無條件佔位 `(subject,rel_type,object)` key，語意 Fact 後處理、key 已存在就跳過——不是「排名判斷錯」，是 BFS 先寫的迴圈先贏，**非經評測驗證的既有設計**。今天c85修正後 Fact 的 key 跟既有 BFS 三元組完全一致，觸發此規則，顯示 BFS 的 `natural_text`（僱主異體字版本）。**但這不是`57-AGGR19`這題失敗的根因**——Fact版與BFS版都缺「依前項第一款規定」這個真正的gold span，去重問題是獨立發現。

**全KG規模驗證**（唯讀掃描KG#4）：BFS-Fact碰撞共 **10,531筆**，文字有實質差異 **7,338筆（70%）**——不是個案，是系統性現象。逐案審視發現**兩側都各自有獨立品質問題**：`fact_text`側verb為空時渲染成「主詞　　受詞」雙空格（400筆，5.5%）、定義型關係內容過度精簡；`natural_text`側（新發現，比原認知更嚴重）有**實體型別佔位符字面洩漏**（`ORGANIZATION`／`POSITION`裸字、`（PERSON,PERSON,PERSON,PERSON）`逗號列表，皆不符合既有`_TYPE_MARKER_RE`防禦清除的格式）、疑似**內容錯置**（兩筆不同Fact共用同一句natural_text）。

**決定**：不切換去重優先權預設值——兩邊都有問題，簡單切換是拿一種問題換另一種。已實作`prefer_fact_on_collision`旗標（含verb為空的品質守門），**預設關閉、生產環境零行為變化**，留作之後細緻修復的基礎設施。全套pytest 1057 passed。

**另開任務**：[報告67：事實自然語言化品質問題SDD任務書](docs/報告/67_事實自然語言化品質問題SDD任務書.md)——已查證根因（`_naturalize_triple()` prompt 把型別標記嵌成`（TYPE）`但沒防呆、沒核對輸出是否殘留），並釐清跟報告25 §5已記錄的舊問題（殘缺三元組跳過LLM、樣板拼接殘留型別標記）是**不同的洩漏路徑**——本次發現的是完整三元組、確實呼叫LLM後輸出仍洩漏。**尚未實作，待核准。**

### 2026-09-22 報告67 T2/T3：natural_text 型別標記雙重防護已實作

依 T1 已判定的 LLM／prompt 根因，完成報告67 T2 與 T3；**沒有執行 T4、沒有重抽 KG，也沒有對 Neo4j 寫入**。

1. `services/svo_service.py` 新增 `_naturalization_leaked_type_marker()`：逐一檢查非空 `subject_type`／`object_type` 的逗號分隔 token，支援裸字與重複列表，並用 ASCII 識別字邊界避免把 `PERSONAL` 誤判成 `PERSON`；「概念」保留為合法語意例外。命中後與 `_naturalization_dropped_quantity()` 共用同一個 `_verbalize_fact()` fallback，prompt 明確禁止照抄型別名稱。
2. `routers/agent.py` 改用 `core/constants.py::ENTITY_TYPES` 生成受控型別 token 正則，清除裸字與全形括號逗號列表；不在清單內的合法英文縮寫不受影響，既有 `（概念）` 行為保留。沒有使用任意大寫英文字萬用匹配。
3. 新增 T2/T3 核對、fallback、prompt 與輸入邊界測試。指定完整測試命令：**1065 passed, 8 warnings, 75.63s**。

目前待使用者決定：是否另行排入 T4 範圍估算，或先針對 T2/T3 進一步審查；T4 未在本次 commit 中執行。

### 2026-09-22 報告68 T1–T4：評測 harness embedding cache 已實作並完成小規模複驗

完成報告68 的 T1–T4；範圍只涉及 `core/providers/factory.py`、`scripts/eval/` 與對應測試／文件，
沒有修改 `routers/agent.py` 或 production `chat()` 行為，也沒有對 Neo4j 寫入。

1. `scripts/eval/embedding_cache.py` 新增 `CachingEmbeddingProvider`：以 model name 加
   `SHA-256(text)` 做 JSON 持久化快取，`encode_batch()` 只送唯一的 cache miss 到底層 provider，
   並保留輸入順序。
2. `core/providers/factory.py` 新增明確標示 eval/test-only 的
   `override_embedding_provider_for_eval()`；只有 harness 傳入 `--embedding-cache` 時才包裝既有
   全域 embedding provider。未傳參數維持零行為變化。
3. `run_rq1_comparison.py` 與 `frozen_baseline_stage.py` 已佈線選填 `--embedding-cache`，並新增
   cache、factory 與 CLI 回歸測試。
4. T4 使用既有 7 題連續執行兩次，共用
   `.claude/tmp/report68_embedding_cache_20260922/embedding_cache.json`；兩次均 7/7 完成、無
   harness error／逾時。Stage 1 Context Recall 逐題完全一致：
   `18-Q5=1.0`、`57-DIST1=1.0`、`57-DIST2=1.0`、`57-CANARY5=1.0`、
   `57-AGGR7=0.3333`、`57-AGGR8=0.75`、`57-AGGR19=0.25`。

完整測試與 commit 狀態待本輪收尾更新；本結果只驗證 embedding cache 的 Stage 1 可重現性，沒有重跑
獨立 judge pilot，也不對是否接線或更換模型下結論。

### 2026-09-25 報告72 S3：chunk-RAG對照組已完成

依使用者授權只執行報告72 §2 的 S3，沒有重跑 S0/S1/S2。沿用新題庫雜湊 `23f8c06f`、KG `236903cf-055a-40a8-8923-b9d06601f3b7`、23個scope documents、`qwen2.5:7b`、`bge-m3`、timeout 900 秒與共用 generator/judge pilot；沒有重抽 KG、沒有 Neo4j 寫入。

- S0 K：13/42；D direct-LM：2/42；B0 naive chunk-RAG：20/42（另 `57-AGGR19` 為三次 `[False, True, True]` 的 unstable）；B1 hybrid chunk-RAG：21/42。
- 對 S0 的逐題配對：B0 對照新增9、KG優勢2、淨差 KG -7；B1 對照新增9、KG優勢1、淨差 KG -8。結論是目前沒有 KG 優於做得夠好的 chunk-RAG 的整體證據；完整表格與 CI/McNemar 見報告72 §9。
- `57-AGGR18` 的 `role_mismatch` 泛化仍未完成，可能讓 Atomic Accuracy／達標 status 高估，且影響 S3 解讀；共用 generator/judge 仍只是 pilot。
- 完整 pytest：`1118 passed, 8 warnings`。S3 records／summaries 位於 `data/eval/candidate_runs/s3_chunk_rag_*`；本輪不 push，且保留既有未追蹤檔案不 stage。
