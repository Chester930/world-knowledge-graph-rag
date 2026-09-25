# 72 報告62殘留待辦：新題庫基準重建／K1b／T3條文擴充／chunk-RAG對照組任務書（交付Codex）

**建立日期**：2026-09-23
**文件性質**：任務書，交付 Codex 執行，完成後由 Claude Code 複驗。
**觸發脈絡**：[報告62](62_下一階段任務書_檢索排名與條文擴充驗證.md)規劃的T2（top_k=40）／§14量測工具稽核已完成並裁示（§14.11），但T3（條文層級擴充）、K1b（top_k=40且維持BFS名額）、T6（chunk-RAG對照組，決策點D1）自09-21起全程被報告65-69插隊，**仍未執行**。同時報告62 §14.10已修正題庫（`57-DIST1/2`補天數span），題庫雜湊由`404cde9f…`變為`23f8c06f…`，T2當初「12→14」的判定是在**舊雜湊**下做的，尚未有任何在**新雜湊**下的正式K arm基準數字可供後續候選比對。

---

## 0. 一頁摘要

**目標**：依序完成4件事——(1)在新題庫雜湊下重建K arm凍結基準（新的比較基期）、(2)K1b（隔離BFS縮減效應）、(3)T3條文層級擴充（opt-in、驗證是否修復被拆碎的gold span）、(4)T6 chunk-RAG對照組（回答論文核心問題：KG相對於chunk-RAG的增益）。**這是報告62既有設計的執行，不是重新設計**——技術方案在報告62 §3/§7/§11已經寫好，本任務書只負責排執行順序與把「新題庫基準重建」這個新增的前置步驟補上。

**已知缺口（誠實揭露，執行前必讀）**：報告62 §14.9第4項「`57-AGGR18`的新舊法歸屬檢查（讓`role_mismatch`對排版變化穩健）」**仍待辦，不在本任務書範圍內**。這代表S1（K1b）／S2（T3）的評測結果，若牽涉角色互換型錯誤（`claim_scope_auditor`目前只有AGGR15-18有規則），**原子正確率可能高估**——回報結果時必須附帶這個已知限制的提醒，不能只看Atomic Accuracy數字就下結論。

---

## 1. 現況（已查證，供直接引用，避免重新查證已有結論）

1. **題庫雜湊變更**：`57-DIST1/2`已於報告62 §14.10補入天數span（第2條「給予一至三日之特別休假」、第3條「給予二至五日之特別休假」，已核對法規原文），兩份鏡像（`data/eval/test_cases.json`、`docs/附錄A題庫.json`）sha256同步為`23f8c06f…`，跟09-20凍結雜湊`404cde9f…`不同。**這是預期變更，不是環境壞掉**。
2. **T2（K1=top_k 40）已完成並判定，但是在舊雜湊下**：達標12→14（淨增2，p=0.75），穩定通過的`57-DIST1/2`退步（後經§13.1診斷為評分器對逐字引用vs改寫的敏感度，非真退步）、Type-E退步。**判定：需更多證據，不建議設為預設**（報告62 §12.2）。
3. **§14量測工具稽核已收尾（§14.11）**：v2評分器（規則R）裁決「暫不採用，維持現行`AtomicScorer`為預設」；人工複核4題已全部裁決（`57-DIST1/2`因題庫修正自動解決、`26-Q5`維持支持但標記生成品質問題、`57-AGGR19`推翻原判改判不支持）。**現行評分器程式碼未變動，可直接沿用**。
4. **K1b設計**（報告62 §11.3）：top_k=40且維持BFS名額，需用per-KG設定檔覆寫`factlist.min_bfs_slots`（不改程式預設）。目的是回答「T2的退步是否來自BFS名額被top_k=40間接壓縮」（報告62 §10揭露：prompt截斷門檻非單調，池>35時放寬到35行，使top_k=40同時會縮減BFS名額）。
5. **T3設計**（報告62 §3 T3節）：opt-in的`article_expand`（預設關），檢索到某條文的任一Fact時，把同一條文的兄弟Fact一併帶入（`SUPPORTED_BY → LawArticle`邊），設每條文兄弟Fact上限＋去重。**反向風險：SNR是主要觀察指標**（LegalBench-RAG強調最小精準片段）。決策點：T2、T3、K1b三臂同時評估組合（K1=top_k40、K2=條文擴充、K3=兩者），避免互相掩蓋效果。
6. **T4採用規則已預先寫定**（報告62 §11.1，評測前定案，不可事後改切法）：主指標淨增≥3題且逐題配對增加多於減少；基準穩定通過題不得變成穩定未達標；SNR不得低於基準一半；Type-E不得退步；統計需附信賴區間或逐題配對差異。**這組規則直接沿用，不需要重新裁示**，但因為現在是新題庫基準，「基準」指的是本任務書S0產出的新基準，不是舊的12/42。
7. **T6設計**（報告62 §3 T6節，決策點D1）：harness已有B0／B1／D等現成臂（`run_rq1_comparison.py`約221-260行），需在同一批42題、同凍結條件補跑對照臂，回答「KG相對於chunk-RAG在哪有增益」這個論文定位問題。
8. **已知風險與陷阱**（報告62 §5，執行前務必重讀）：Ollama記憶體壓力（曾中止4次評測）、延遲數字不可靠、harness逾時紀錄`_build_timeout_record`會偽造空lineage（務必`--query-timeout-s 900`）、`_process_one()`吞例外（重抽務必讀回佇列狀態，本任務書不涉及重抽，僅提醒同一套「不要信自我回報」原則也適用於評測harness的執行紀錄）、評分器盲點（不檢查歸屬，見本文件§0已知缺口）、共用generator/judge僅屬pilot、worktree協作衝突（開工前`ListAgents`＋`git log`）。

---

## 2. 任務清單

### S0（M，先決）：新題庫雜湊下重建K arm凍結基準

- 用`frozen_baseline_stage.py`，在**現行程式碼**（本分支HEAD，已含報告65-69的所有已核准修法：規則10、`prefer_fact_on_collision`旗標、簡體字防護閘門、metric-judge解耦等）與**新題庫**（雜湊`23f8c06f…`）下，重跑42題K arm，重複次數規則比照09-20凍結基準（`scripts/eval/adaptive_repeat.py`品質門檻式規則，最多3次，抽查約25%單次通過題）。
- **這不是回頭修正09-20的「12/42」歷史數字**——那次數字語意不變，仍是舊題庫下的結果。S0產出的是一份**新的、獨立的基準**，作為S1/S2/S3後續比較的基期。
- 產出：達標題數、Context Recall、SNR、逐題結果，存放路徑比照`data/eval/baseline_runs/`既有慣例（例如`data/eval/baseline_runs/20260923_rebased/`），並在本報告新增一節記錄結果與跟09-20舊基準的差異摘要（預期差異只來自`57-DIST1/2`的題目文字本身變嚴格，不應有其他系統性差異——若觀察到其他題目也系統性變動，需要調查原因再繼續，不要略過）。

### S1（M）：K1b——top_k=40且維持BFS名額

- 依報告62 §11.3設計，用per-KG設定檔覆寫`factlist.min_bfs_slots`維持原有BFS名額，同時套用`--k-top-k 40`。
- 對S0的新基準做配對比較，套用報告62 §11.1的採用規則（見本文件§1.6）。
- **驗收重點**：若K1b（維持BFS名額）比K1（原始top_k=40）表現更好、且原本T2退步的題目在K1b恢復通過，就代表退步主因是BFS名額被間接壓縮，這本身是一個值得記錄的診斷結論，即使K1b整體仍未達採用門檻。

### S2（M，**在S1有結果後才做，可與S1同批次設計但需先看過S1初步訊號**）：T3條文層級擴充

- 依報告62 §3 T3節與本文件§1.5設計opt-in `article_expand`，實作進`_arrange_fact_lines()`附近（確切插入點需在實作時依現有程式碼結構決定並在commit訊息說明）。
- 依報告62的決策建議，**同時評估K1（top_k40）、K2（純條文擴充）、K3（兩者組合）三臂**，避免效果互相掩蓋，全部對S0新基準配對比較。
- **附加驗收**：另做一個小型人工抽查（至少5個原本屬於報告57 §4.21類別B「抽到但被拆碎」的gold span），確認條文擴充後這些片段確實被補齊，而不只是分數上升（可能是不相關原因造成的分數波動）。
- **SNR是否顯著下降是否決條件**：若SNR跌破S0基準的一半，即使Atomic Accuracy上升也不建議採用（報告62 §11.1既有規則）。

### S3（M，決策點D1）：chunk-RAG對照組

- 用既有B0／B1／D等arm，在同一批42題（新題庫雜湊）、同凍結條件下（同generator/judge/timeout/KG狀態）補跑對照組。
- 產出K arm（S0基準，或若S1/S2有採用建議則包含最終建議配置）與chunk-RAG對照組的並列比較表，回答「KG相對於做得夠好的chunk-RAG在哪有增益、增益幅度多大」。
- **這是論文定位的關鍵證據**，回報時需明確、誠實地陳述結果（即使結果是「KG目前沒有顯著優於chunk-RAG」也要如實記錄，不要選擇性呈現）。

---

## 3. 明確不做的事

- **不擴大題庫**——42題已是既定基準規模，改動題庫（除非是報告62 §14.10已核准的修正）會再次改變雜湊，需要另外走核准流程。
- **不修改`AtomicScorer`預設邏輯**——報告62 §14.11已裁決維持現行評分器，本任務書沿用。
- **不重抽KG或大範圍修改抽取程式碼**——本任務書是評測，不是抽取修復（報告65/66/67系列已處理過抽取粒度與自然語言化問題）。
- **不更換生成模型**——維持`qwen2.5:7b`，這是報告62 §4已明確排除的選項。
- **不把`article_expand`或K1b的per-KG設定改成全域預設**——全部opt-in，不改變`chat()`現行行為。
- **不在本任務書內處理`57-AGGR18`歸屬檢查的`role_mismatch`規則泛化**——已知缺口，另案處理，本任務書只需要在回報時提醒這個限制。
- **不自動合併master**——即使S0-S3的異動全部是opt-in、風險低，仍需個別走使用者核准流程，比照HANDOVER.md既有規定「合併master前須逐項確認」。

---

## 4. 驗收標準

1. S0產出的新基準有完整的執行紀錄（程式碼commit、題庫雜湊、KG狀態、重複次數規則），可供S1-S3直接引用比對，不需要每個子任務各自重跑基準。
2. S1/S2/S3的比較都對S0的同一份新基準做配對比較，採用/不採用的判定都依報告62 §11.1既定規則，不臨場改切法。
3. 每個子任務的結果都誠實回報（包含不如預期的結果），不因為想要「有進展可以交差」而選擇性呈現。
4. 回報中明確提醒本文件§0揭露的「歸屬檢查缺口」對結果解讀的影響。
5. `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py`在有程式碼異動（S1的per-KG設定機制、S2的`article_expand`）後全綠。

---

## 5. 給 Codex 的指令（可直接貼上）

> 請依序執行 `docs/報告/72_報告62殘留待辦新基準與K1b_T3_chunkRAG任務書.md` 的S0-S3。背景：報告62規劃的T3（條文層級擴充）、K1b（top_k=40且維持BFS名額）、T6（chunk-RAG對照組）自09-21起被報告65-69插隊、全程未執行；同時報告62 §14.10已修正題庫（`57-DIST1/2`補天數span），題庫雜湊由`404cde9f…`變成`23f8c06f…`，T2當初「12→14」的判定是在**舊雜湊**下做的。**S0（先決）**：用`frozen_baseline_stage.py`在現行程式碼（本分支HEAD）與新題庫雜湊下重跑42題K arm，重複次數比照09-20凍結基準的`adaptive_repeat.py`品質門檻規則，產出獨立的新基準（不是修正09-20的舊數字，兩者語意不同），存放並記錄在`data/eval/baseline_runs/20260923_rebased/`與本報告新增章節。**S1**：依報告62 §11.3設計K1b（`--k-top-k 40`＋per-KG設定覆寫`factlist.min_bfs_slots`維持BFS名額），對S0新基準配對比較，套用報告62 §11.1既定採用規則（淨增≥3題、不退步、SNR不低於基準一半、Type-E不退步、附信賴區間），**規則不可臨場更改**。**S2**：依報告62 §3 T3節設計opt-in `article_expand`（檢索到條文任一Fact時帶入同條文兄弟Fact，設上限＋去重），同時評估K1／K2（純條文擴充）／K3（組合）三臂對S0新基準比較，另做至少5個報告57 §4.21類別B gold span的人工抽查確認片段確實被補齊。**S3**：用既有B0／B1／D arm在同一批42題新題庫、同凍結條件下補跑chunk-RAG對照組，產出與K arm（S0或最終建議配置）的並列比較表，這是回答論文核心問題「KG相對chunk-RAG的增益」的關鍵證據，**結果無論好壞都要如實記錄**。**已知缺口**：`57-AGGR18`的角色互換歸屬檢查（`role_mismatch`規則泛化）仍待辦不在本任務書範圍，回報S1/S2/S3結果時必須提醒這個限制可能讓Atomic Accuracy高估。全程遵守報告62 §5列出的已知風險（Ollama記憶體壓力、`--query-timeout-s 900`、評分器盲點、共用generator/judge僅屬pilot）；開工前用ListAgents確認沒有其他Claude session同時在用同一組Neo4j/Ollama；不擴大題庫、不改評分器預設、不重抽KG、不換生成模型、不把新機制設為全域預設、不自動合併master。完成後跑`python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py`確認全綠，回報每個子任務的結果與是否建議採用。

---

## 6. S1結果：K1b逐題配對判定（2026-09-24）

### 6.1 資料與判定口徑

本節依報告62 §11.1 的**既定規則**，將 S1 K1b 與本任務書 S0 新基準逐題配對；未改題庫、未改評分器預設、未重抽 KG、未更換 generator/judge。S0 使用 `data/eval/baseline_runs/20260923_rebased/summary_final.json`，S1 使用 `data/eval/candidate_runs/s1_k1b_topk40_bfs16_adaptive_summary_r2.json`。兩份 summary 都是同一批 42 題；S0 有 75 筆有效 records，S1 有 71 筆有效 records。逐題「通過」定義為 `stable_pass` 或 `single_pass`，完全沿用 summary 的 status。

SNR 依 `records.json` 的 `lineage.stage1_retrieval.snr` 計算：先對每題的有效重跑取平均，再對 42 題取平均；各 stage 的 `summary.md` 四捨五入值與此結果一致。

### 6.2 逐題配對結果

| 配對類別 | 題目 | 題數 |
| --- | --- | ---: |
| S0 未通過 → S1 新增通過 | `18-Q1`、`18-Q5`、`18-Q6`、`57-COREF3`、`57-AGGR18` | 5 |
| S0 通過 → S1 退步 | `18-Q4`、`canary-P1` | 2 |
| 兩邊都通過 | — | 11 |
| 兩邊都未通過 | — | 24 |

因此 S0 **13/42** → S1 **16/42**，淨增 **+3 題**；逐題方向為新增 5 題、退步 2 題，新增明顯多於退步。配對差異 `d = S1通過 − S0通過` 的平均為 **+7.14 個百分點**，以 42 題的題目層級差異計算近似 95% CI 為 **−5.16～+19.45 個百分點**；discordant pairs 的 exact McNemar 雙尾 `p = 0.4531`，方向尚不具統計明確性。這些逐題差異與 CI 一併保留，不把淨增 +3 題解讀成已證明的穩定改善。

### 6.3 依 §11.1 逐項驗收

| 條件 | 實際結果 | 判定 |
| --- | --- | --- |
| 主指標：淨增 ≥3，且新增多於退步 | 13 → 16，淨增 +3；新增 5、退步 2 | ✅ |
| 不退步：S0 的 `stable_pass`／`single_pass` 不得變成 S1 `stable_fail` | `18-Q4`、`canary-P1` 發生 | ❌ |
| SNR ≥ S0 一半 | S0 **3.7367%** → S1 **3.0405%**；比值 **0.8137**，門檻 **1.8684%** | ✅ |
| Type-E 不退步 | 5 題中 S0 通過 3 題 → S1 通過 2 題；`canary-P1` 退步 | ❌ |
| 統計／逐題差異 | 已附 5/2 配對清單、McNemar `p` 與 95% CI | ✅ |

### 6.4 不退步題逐題原因

- **`18-Q4`：`stable_pass` → `stable_fail`。** S0 兩次均保留全部 gold span 且通過；S1 兩次的 Context Recall 仍為 1.0，gold Fact 仍在 prompt，但 Stage 3 生成均遺漏／平滑掉「自當年度營利事業所得額減除」這一完整 span，records 的 failure attribution 為 generation failure。這是觀察到的生成階段退步；較長 prompt／內容稀釋可能是候選差異的背景因素，但本資料不足以證明因果。
- **`canary-P1`：`single_pass` → `stable_fail`，同時是 Type-E 退步。** S0 的單次結果正確拒答；S1 兩次均改答「最高一百五十萬元」，而非拒答，屬 unsupported answer。這不是把 S0 的單次通過升格成穩定證據，而是明確記錄為 Type-E 行為退步。

### 6.5 判定與限制

**判定：需更多證據，不建議設為預設；不建議採用 K1b。** K1b 通過了「淨增至少 3 題」、配對方向（5 > 2）及 SNR 一半門檻，但違反必要的不退步條件，且 Type-E 由 3/5 降至 2/5；McNemar `p=0.4531`、配對差 CI 橫跨 0，也不支持把 +3 題視為明確改善。因此本階段不把 K1b 接成全域預設，不進行自動合併 master；S2 是否開始，待使用者核對本節後另行決定。

`57-AGGR18` 雖列在 S1 新增通過，但報告62 §14.9 所揭露的角色互換歸屬檢查（`role_mismatch` 規則泛化）仍未完成；目前 `claim_scope_auditor` 的覆蓋有限，故 Atomic Accuracy／達標 status 可能高估。此限制不在 S1 範圍內，不能用本次分數掩蓋。另依報告62 §5，Ollama 記憶體壓力、`--query-timeout-s 900`、共用 generator/judge 僅屬 pilot 等風險仍有效，SNR 與逐題判定不應被解讀為消除這些風險。

---

## 7. S2結果：T3 `article_expand` 三臂逐題配對判定（2026-09-24）

### 7.1 實作範圍與評測資料

S2 依報告62 §3 T3 原始設計實作為 **opt-in**：檢索到某條文的任一 Fact 後，沿 `Fact -[:SUPPORTED_BY]-> LawArticle` 找同一條文的兄弟 Fact；每條文最多新增 8 個兄弟 Fact，並以結構化 `(subject, rel_type, object)`（無法結構化時退回 `fact_text`）去重。`article_expand` 預設為關閉；可由 request 明確開啟或關閉，沒有改變現行全域預設。

確切插入點在 `routers/agent.py`：`chat()` 完成 `_filter_triples_by_source_doc_ids()`／`_filter_facts_by_source_doc_ids()` 後、呼叫 `_generate_from_context_lines()` 前執行 `_expand_facts_by_article()`；後者才會進入 `_arrange_fact_lines()`。因此擴充發生在檢索結果組裝、`_arrange_fact_lines()` 排列前，仍受既有 prompt／BFS／RRF／LITM 限制，不繞過既有上限。新增 Fact 的 `article_no` 也寫入 retrieval trace，供人工核對「有補入檢索池」與「實際進 prompt」的差異。

三臂均使用 S0 同一批 42 題、新題庫雜湊 `23f8c06f…`、同一 KG、`qwen2.5:7b`／`bge-m3`、`--query-timeout-s 900` 與共用 generator/judge pilot 條件；S0 基準為 `data/eval/baseline_runs/20260923_rebased/summary_final.json`。最終摘要如下：

| 臂 | 設定 | 結果摘要 |
| --- | --- | --- |
| S0 | 新基準 | **13/42**；SNR **3.7367%** |
| K1 | `top_k=40`、`article_expand=false`（控制組） | **16/42**；SNR **3.0405%**（S0 的 0.8134 倍） |
| K2 | 預設 `top_k`、`article_expand=true` | **13/42**；SNR **2.6121%**（S0 的 0.6989 倍） |
| K3 | `top_k=40`、`article_expand=true` | **14/42**；SNR **1.6167%**（S0 的 0.4327 倍） |

SNR 的計算方式與 §6 相同：從各臂所有 stage 的 `records.json` 讀取 `lineage.stage1_retrieval.snr`，先對每題有效重跑取平均，再對 42 題取平均；錯誤 records 不列入數值平均。三臂最終摘要的 `next_run_ids` 均為空。過程中 K1 有 5 題、K2 有 2 題、K3 有 1 題曾出現 Ollama `/api/embeddings` HTTP 500 的 transient `harness_exception`，均由 adaptive stage C 補跑完成；這些事件仍列為評測風險，不能當作模型品質證據。

### 7.2 逐題配對差異與信賴區間

下列「通過」完全沿用 summary 的 `stable_pass` 或 `single_pass`，未依結果臨時改切法。CI 是 42 題題目層級配對差異的近似 95% CI；另列 discordant pairs 的 exact McNemar 雙尾檢定。

| 臂 | S0 未通過 → 新增通過 | S0 通過 → 退步 | 淨變化 | 配對差 CI（百分點） | McNemar `p` |
| --- | --- | --- | ---: | ---: | ---: |
| K1 | `18-Q1`、`18-Q5`、`18-Q6`、`57-AGGR18`、`57-COREF3`（5） | `18-Q4`、`canary-P1`（2） | **+3**（16/42） | **−5.16～+19.45** | **0.4531** |
| K2 | `18-Q6`、`57-AGGR17`、`57-COREF1`、`57-DIST1`、`canary-P4`（5） | `18-Q3`、`18-Q4`、`26-Q5`、`57-AGGR12`、`57-CANARY2`（5） | **0**（13/42） | **−14.94～+14.94** | **1.0000** |
| K3 | `18-Q6`、`57-AGGR17`、`57-AGGR19`、`57-COREF1`、`57-DIST1`、`canary-P4`（6） | `18-Q3`、`18-Q4`、`26-Q5`、`57-AGGR12`、`57-CANARY2`（5） | **+1**（14/42） | **−13.27～+18.03** | **1.0000** |

### 7.3 依報告62 §11.1 逐項判定

| 條件 | K1 | K2 | K3 |
| --- | --- | --- | --- |
| 淨增至少 3 題且新增明顯多於退步 | ✅ +3；5 > 2 | ❌ 0；5 = 5 | ❌ +1；6 > 5 但未達 +3 |
| S0 穩定通過題不得變成 `stable_fail` | ❌ `18-Q4`、`canary-P1` | ❌ `18-Q3`、`18-Q4`、`26-Q5`、`57-AGGR12`、`57-CANARY2` | ❌ 同 K2 |
| SNR 不低於 S0 一半（門檻 **1.8683%**） | ✅ 3.0405% | ✅ 2.6121% | ❌ 1.6167% |
| Type-E 不退步 | ❌ 3/5 → 2/5，`canary-P1` 退步 | ❌ 雖總數仍 3/5，`57-CANARY2` 逐題由通過退步 | ❌ 同樣 `57-CANARY2` 逐題退步 |

**K1 判定：需更多證據，不建議設為預設。** 它達到 +3 且新增多於退步，SNR 也過半，但穩定通過不退步與 Type-E 必要條件失敗；所以這次僅作為 `top_k=40` 對照，不採用。

**K2 判定：需更多證據，不建議設為預設。** 達標題數沒有淨增，新增與退步相抵，並有 5 個 S0 通過題變成 `stable_fail`；即使 SNR 尚未跌破一半，也不能採用。

**K3 判定：需更多證據，不建議設為預設。** 條文擴充與 `top_k=40` 組合只淨增 1 題，且 SNR 跌至 S0 一半以下（1.6167% < 1.8683%），直接觸發 SNR 否決條件；同時仍有穩定退步與 Type-E 逐題退步。

### 7.4 穩定退步逐題原因

- **K1：`18-Q4`。** S0 為穩定通過；K1 的 gold span 仍被檢索並進 prompt，但兩次生成均遺漏「自當年度營利事業所得額減除」，屬 Stage 3 generation smoothing／intrinsic generation failure，不能把它解釋成檢索修復。**`canary-P1`** 為 Type-E，S0 的 single pass 是正確拒答；K1 兩次均回答金額而未拒答，屬 refusal／Stage 1 行為退步。
- **K2/K3：`18-Q3`、`18-Q4`、`26-Q5`、`57-AGGR12`。** 逐題診斷顯示相關 gold facts 已檢索並進 prompt，但生成分別遺漏「雇主應予同意」、「自當年度營利事業所得額減除」、「自災害發生之當月一日起計算六個月」或退休提撥事實；屬生成階段遺漏／平滑，部分被 guard 記為 atomic 0.5，不能以 article expansion 的 retrieval presence 宣稱已修復。
- **K2 的 `57-CANARY2`。** gold fact 在有效 records 中仍可見且進 prompt，但預期拒答沒有生成，屬 refusal／generation failure。**K3 的 `57-CANARY2`** 在診斷 record 中甚至未召回該 gold fact，且同樣沒有預期拒答，故為 retrieval 加 refusal 雙重退步。

### 7.5 類別 B「抽到但被拆碎」人工抽查

依報告57 §4.21 與 `data/eval/baseline_runs/20260920_frozen/analysis/retrieval_failure_diagnosis.json` 選取 5 個案例，逐一查看 K2 的 retrieval trace；`article_no` 用來區分同條文兄弟是否真的進入候選池，`in_prompt` 用來確認是否實際補到生成上下文。K2 42 題 trace 共記錄 1,860 個帶 `article_no` 的 expanded Facts；K1 trace 沒有帶 `article_no` 的 expanded Facts，表示 opt-in 機制確實有運作，但不代表每個 gold span 都能穿過後續排序與 prompt cap。

| 題目／條文 | gold span 的人工核對 | K2 結果與判定 |
| --- | --- | --- |
| `18-Q5`／D0080015 §4 | `有左列情事之一者，給予三至七日之特別休假` | 候選／trace 出現同條文 `第4條` 的 `左列情事之一者 給予 三至七日之特別休假`，且 `in_prompt=true`；核心條件與日數補入，但「有」仍缺漏，判為**部分修復，非逐字完整**。 |
| `57-AGGR1`／N0060022 附表一項次一 | `勞工健康保護規則附表一（特別危害健康作業）之項次一為高溫作業勞工作息時間標準所稱之高溫作業。` | 未看到目標附表／項次一的同條文兄弟或完整 gold span；只有不相干的高溫工作時數片段，判為**未補齊**。 |
| `57-AGGR7`／N0090058 §6 | `雇主依本法第二十四條第二項規定辦理訓練，並申請訓練費用補助者，最低開班人數應達五人，且訓練時數不得低於八十小時。` | 未出現 `第6條` 兄弟或「五人／八十小時」目標片段；雖有 `第24條` 的不相干訓練補助 Fact，判為**未補齊**。 |
| `57-AGGR8`／N0090055 §24 | `雇主依前項規定辦理職業訓練，中央主管機關得予訓練費用補助。` | trace 沒有完整目標 gold span 或目標條文兄弟進 prompt，判為**未補齊**。 |
| `57-AGGR10`／N0090025 §8 | `第六條補助金，每人每次得發給新臺幣五百元。但情形特殊者，得核實發給，每次不得超過新臺幣一千二百五十元。` | 未看到 `第8條` 兄弟或 500／1,250 元目標片段進 prompt，只有其他條文內容，判為**未補齊**。 |

因此人工抽查結論是「擴充機制確實把部分同條文 Fact 帶入候選池，但對類別 B 的拆碎 gold span 並非穩定補齊」；K2 的 13/42 也沒有超過 S0，不能用分數波動取代內容證據。另抽查 `57-AGGR19` 可見同條文 `第85條` Fact 進入 retrieval pool 但 gold 的「準用勞動基準法規定預告雇主」未進 prompt，進一步顯示候選池擴充不等於上下文有效擴充。

### 7.6 風險、已知限制與結論

S2 三臂均保留報告62 §5 的風險：Ollama 記憶體壓力、`--query-timeout-s 900` 的必要性、延遲數字不宜過度解讀，以及共用 generator/judge 僅屬 pilot。`57-AGGR18` 的角色互換歸屬檢查（`role_mismatch` 規則泛化）仍不在本範圍內，可能使 Atomic Accuracy／達標 status 高估；本次 K1 的 `57-AGGR18` 新增通過尤其不能脫離此限制解讀。

**S2 總結：K1、K2、K3 均「需更多證據，不建議設為預設」；沒有任何一臂採用。** 本節如實記錄了 SNR、逐題退步、Type-E 與人工內容抽查結果；不自動修改全域預設、不合併 master，S3 chunk-RAG 對照組不在本次執行範圍內，待使用者另行決定。

---

## 8. 總結

S0 新題庫基準為 **13/42**。S1 的 K1b，以及 S2 的 K1（`top_k=40`）、K2（純 `article_expand`）與 K3（兩者組合）四個候選臂，依報告62 §11.1 逐題配對規則，全部判定為**需更多證據，不建議採用**；沒有任何候選臂設為預設。

`article_expand` 對報告57 §4.21 類別 B「抽到但被拆碎」gold span 的 5 個人工抽查結果為：**1/5 部分修復、4/5 未補齊**。這表示同條文兄弟 Fact 確實可進入檢索候選池，但不等於完整內容能通過排序與 prompt 限制進入上下文。

結果解讀仍受兩項限制約束：`57-AGGR18` 的角色互換歸屬檢查（`role_mismatch` 規則泛化）尚未完成，可能使 Atomic Accuracy／達標 status 高估；共用 generator/judge 僅屬 pilot，非正式評測證據。

S3 chunk-RAG 對照組已完成，結果與逐題配對明細見下方 §9；本次仍未把任何對照臂設為全域預設，也未自動合併 master。

---

## 9. S3結果：chunk-RAG對照組與S0 K arm並列比較（2026-09-25）

### 9.1 凍結條件、執行範圍與資料完整性

本節只執行 S3，沒有重跑 S0、S1 或 S2。比較基準是 S0 新題庫 K arm 本身，不是任何 S1/S2候選配置：

- 題庫仍為同一批 42 題，manifest／題庫雜湊為 `23f8c06fa7f4459e2bc64531ef80c62f6e00a25b779a0abb7eb4e81933b3aa84`（短雜湊 `23f8c06f`）。
- KG 為 `236903cf-055a-40a8-8923-b9d06601f3b7`，沿用既有 frozen manifest 的 23 個 scope documents；沒有重抽 KG，也沒有改動 Neo4j 資料。
- generator/judge 維持 `qwen2.5:7b`，embedding 維持 `bge-m3`；`--query-timeout-s 900`、chunk size `500`、baseline top-k `5`、共用 generator/judge pilot 與 S0 相同。
- `B0` 在 harness 中以 `M1` alias 執行（naive chunk-RAG），`B1` 以 `M2` alias 執行（hybrid chunk-RAG）；`D` 是既有無檢索 direct-LM control，不把它冒充成 chunk-RAG。
- 每題先執行一筆，再依既有 `adaptive_repeat.py` 規則補跑不穩定題及固定四題 audit；成功評測 records 均無 harness error。輸出位於 `data/eval/candidate_runs/s3_chunk_rag_{d,b0,b1}_*`，最終 adaptive 摘要分別為 `s3_chunk_rag_d_adaptive_summary_r2.json`、`s3_chunk_rag_b0_adaptive_summary_r3.json`、`s3_chunk_rag_b1_adaptive_summary_r2.json`。

下表的「確定通過」完全沿用 §6/§7 的口徑，只計 `single_pass` 或 `stable_pass`；`unstable` 不擅自當成通過。Context Recall、Atomic Accuracy、SNR 則依各臂所有有效 records，先按題目平均重跑結果，再按 42 題平均；錯誤 records 不列入數值平均。

### 9.2 K arm與chunk-RAG對照組並列表

| 臂 | 方法／設定 | 確定通過 | Atomic Accuracy | Context Recall | SNR | 有效 records | 備註 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| S0 K | KG新基準 | **13/42** | 52.98% | 66.86% | **3.7367%** | 75 | `stable_pass=4`、`single_pass=9` |
| D | 無檢索 direct-LM control | **2/42** | 13.59% | 0.00% | 0.0000% | 82 | 不是 chunk-RAG；用來確認無檢索下限 |
| B0 | naive chunk-RAG（M1） | **20/42** | 72.22% | 84.33% | 3.0952% | 69 | `single_pass=16`、`stable_pass=4`、`stable_fail=21`、`unstable=1` |
| B1 | hybrid chunk-RAG（M2） | **21/42** | 73.71% | 85.71% | 3.1605% | 67 | `single_pass=17`、`stable_pass=4`、`stable_fail=21` |

B0 的唯一 `unstable` 是 `57-AGGR19`，三次結果為 `[False, True, True]`；若以多數決觀察會是 21/42，但本表和逐題主判定仍保守列為 20/42。B1 是本次較強的 chunk-RAG 對照：比 S0 多 **8** 個確定通過題，Context Recall 高 **18.85 個百分點**，SNR 為 S0 的 **0.8458 倍**（仍高於 §11.1 的一半門檻）。B0 則比 S0 多 **7** 題，SNR 為 S0 的 **0.8283 倍**。因此，SNR 沒有跌破一半不能解釋成 KG 已取得整體優勢；在本題庫上，chunk-RAG 的達標與召回表現反而較高。

### 9.3 逐題配對差異與信賴區間

下表的方向是「對照臂通過 − S0 K 通過」；「對照新增」代表 S0 未通過而 chunk/direct control 通過，「KG優勢」代表 S0 通過而對照臂未通過。CI 是 42 題題目層級差異的近似 95% CI，另列 discordant pairs 的 exact McNemar 雙尾檢定。

| 臂 | 對照新增（S0未通過 → 對照通過） | KG優勢（S0通過 → 對照未通過） | 淨差 | 配對差 CI（百分點） | McNemar `p` |
| --- | --- | --- | ---: | ---: | ---: |
| D | `57-AGGR17`（1） | `17-Q1`、`17-Q2`、`18-Q2`、`18-Q3`、`18-Q4`、`26-Q1`、`26-Q5`、`canary-P1`、`57-CANARY1`、`57-CANARY2`、`57-CANARY4`、`57-AGGR12`（12） | **−11**（2/42） | **−41.22～−11.17** | **0.0034** |
| B0 | `17-Q6`、`18-Q1`、`18-Q5`、`18-Q6`、`canary-P4`、`57-COREF1`、`57-COREF3`、`57-AGGR14`、`57-AGGR18`（9） | `57-CANARY1`、`57-AGGR12`（2） | **−7**（20/42） | **+1.86～+31.48** | **0.0654** |
| B1 | `17-Q6`、`18-Q1`、`18-Q6`、`canary-P4`、`57-COREF3`、`57-DIST2`、`57-AGGR6`、`57-AGGR14`、`57-AGGR19`（9） | `57-AGGR12`（1） | **−8**（21/42） | **+5.30～+32.80** | **0.0215** |

以較強的 B1 為例，S0 K 的可辨識優勢只在 `57-AGGR12`；相反地，B1 從 S0 未通過中新增 9 題，包含新題庫修正相關的 `57-DIST2`。B0 也只有兩題是 S0 通過而 B0 未通過，且沒有 S0 `stable_pass` → 對照 `stable_fail` 的退步；B1 同樣沒有這種 stable regression。Type-E 則是 S0 **3/5**、B0 **3/5**、B1 **4/5**、D **0/5**；B1 的 Type-E 並未因 chunk-RAG 而退步。

### 9.4 「KG相對於做得夠好的chunk-RAG」的回答

本次資料對論文定位問題的答案是：**目前沒有顯示 KG 相對於做得夠好的 chunk-RAG 有整體增益。** B1 這個較強的 chunk-RAG 對照組為 21/42，而 S0 K 為 13/42；逐題是 chunk-RAG 新增 9 題、KG 保有 1 題，淨差為 KG **−8 題**，McNemar `p=0.0215`，配對差 CI 亦未跨 0。B0 的方向相同（chunk 新增 9 題、KG 優勢 2 題，淨差 KG **−7 題**），只是 `p=0.0654` 尚未達同樣的統計明確性。

KG 相對無檢索 D control 仍有明顯增益（13/42 對 2/42），所以結果不是「檢索沒有價值」；較精確的結論是，**在這批題目、這個既有 KG 與目前 generator/judge 條件下，KG 沒有勝過已做得足夠好的 chunk-RAG，反而低於 B0/B1**。這個結果不選擇性隱去，亦不把 B0/B1 設成系統預設；S3 是對照證據，不是架構切換裁示。

### 9.5 風險、已知限制與交付狀態

- `57-AGGR18` 的角色互換歸屬檢查（`role_mismatch` 規則泛化）仍未完成；它可能讓 Atomic Accuracy／達標 status 高估，且這項限制同樣影響 S3，不只是 S1/S2。B0 的新增清單包含 `57-AGGR18`，因此不能把該題當成無條件的 KG 或 chunk-RAG 增益證據。
- generator/judge 共用 `qwen2.5:7b` 仍是 pilot，不是獨立正式 judge；延遲也不作為本節結論。B0 的 `57-AGGR19` 仍不穩定，已保留為 `unstable` 而非擅自升格。
- 本次未擴大題庫、未修改 `AtomicScorer` 預設、未重抽 KG、未更換生成模型、未修改全域預設、未處理 `services/expand_worker.py`，也沒有執行 Neo4j 資料寫入。
- S3 評測資料與 summaries 已保留在 `data/eval/candidate_runs/s3_chunk_rag_*`；完成後依任務書要求執行完整 pytest，結果記於交付回報。S3 不自動合併 master，push 亦不在本次範圍內。

---

## 10. S3 落差題逐題根因診斷（2026-09-25）

### 10.1 分析口徑與資料來源

本節依報告78 T1–T5 做**純離線分析**，沒有重跑評測 harness、沒有呼叫 Neo4j／Ollama、沒有修改程式碼。S0 K 的 records 逐題從 `data/eval/baseline_runs/20260923_rebased/stage_s0_r1/records.json`、`stage_s0_r1_resume1/records.json`、`stage_s0_r2/records.json` 重新讀取；B1 成功對照來自 `data/eval/candidate_runs/s3_chunk_rag_b1_stage_a/records.json`。B1 record 的 `stage2_context.prompt_context_lines` 本身為空，但其 `stage1_retrieval.retrieved_chunk_ids` 已保留；因此本節以既有 `baseline_rag_index_236903cf-055a-40a8-8923-b9d06601f3b7_cs500.json` 按 chunk id 離線還原 B1 原始段落，沒有重新檢索。

任務書 §0 的 `failure_attribution` 只是 harness 啟發式分類，不直接視為根因真相；以下以 `atomic_score.missing_spans`、`stage1_retrieval.retrieval_trace`、`stage2_context.prompt_context_lines`、`stage2_context.dropped_exact_spans` 與 `stage3_generation` 的實際內容交叉核對。特別是「gold span 未命中」不必然等於答案語意錯誤：若答案已用合理改寫表達同一法效果，會另標為評分器／表面形式問題。

### 10.2 T1逐題診斷總表

| 題目 | 重新核對的 S0 失敗階段 | 具體證據與根因 | GAP-04／06／07 是否對得上因 |
| --- | --- | --- | --- |
| `17-Q6` | Stage 1 `(a)` 從未抽取／候選未出現 | `missing_spans` 包含「搶救重大災害，冒險犯難，達三日以上，獲記大功以上之獎勵者」；34 筆 `retrieval_trace` 與 18 條 prompt line 都沒有這個條件或語意等價候選。prompt 只有其他「給予一至三日」條件，例如「當選直轄市、縣（市）級模範警察或好人好事代表者」。B1 的 `D0080015_警察人員特別休假辦法_0` 則保留完整第2條共享結果與第三款條件。 | 三者皆否。雖然法律原文有多個條件共享「一至三日」結果，這次失敗是特定條件未進候選，不是缺少 GAP-04 的新資料模型；沒有 Relator 或時態證據。 |
| `18-Q1` | Stage 3 真正遺漏／抹平 | S0 `stage2_context` 有「未住院傷病假與住院傷病假二年內合計不得超過一年」等相關事實，metadata 也列 `retained_exact_spans`；但生成答案對第二問直接寫「資料未明確記載，無法確認」。B1 的 `N0030006_勞工請假規則_0` 將第4條的一、二、三款放在同一完整段落，直接保留「住院者，二年內合計不得超過一年」。 | 三者皆否。這是上下文呈現與生成注意力問題，不是條件抽取、關係載體或歷史有效期問題。 |
| `18-Q6` | Stage 3 表面形式／評分器未命中，非純內容遺漏 | S0 prompt 有「一年內事假不得累計超過十四日」，答案也寫出「一年內事假不得累計超過十四日」；gold 是「一年內合計不得超過十四日」。這是語意等價但表面不同，`atomic_score` 仍列為 missing。B1 的完整第7條段落與答案寫成「一年內合計請事假的天數不得超過14日」，因較接近評分器預期而通過。 | 三者皆否。失敗證據指向 span matcher／答案表面形式，不是 GAP-07 雙時態。 |
| `canary-P4` | Type-E 拒答校準 | `atomic_score.details` 為 `Failed to Refuse on Type-E Canary`，而 `failure_attribution` 顯示三階段 gold span 保留；它是火星旅遊的虛構規定本應拒答卻被判失敗。 | 不適用；不深入診斷，也沒有證據支持三個 GAP。 |
| `57-COREF3` | Stage 3 部分遺漏＋表面形式敏感 | S0 prompt 分開列出「勞工為了親自照顧家庭成員，得依前項規定請事假」與「事假可以選擇以小時為請假單位」；答案確實回答可以用小時計算，但沒有完整重述「除本法或其他法律另有規定」及「得依前項規定」的綁定句。B1 的第7條原文段落把照顧家庭成員、前項事假與小時單位放在同一法條脈絡，答案保留完整句。 | 三者皆否。這是條文脈絡被拆開後的生成／評分問題，雖與「條件綁定」有表面相似，卻不是報告75所定多個並列條件共享結果的 GAP-04 證據。 |
| `57-DIST2` | Stage 3 表面形式／評分器未命中，非純內容遺漏 | S0 prompt 已有「當選直轄市、縣（市）級模範警察或好人好事代表者 給予 一至三日之特別休假」；答案也明確回答直轄市／縣市級為一至三日，並正確比較全國性二至五日，但 gold 的通用 span「給予一至三日之特別休假」仍列 missing。B1 的完整第2、3條段落保留共享結果與各款條件，答案因引用法條原文而通過。 | 三者皆否。這是答案語意已大致正確但 scorer 對完整 span 敏感，不是雙時態或 Relator 問題。 |
| `57-AGGR6` | Stage 1 `(a)`：兩個退休金分支未形成可用候選 | 4 個 gold facts 中，S0 `hit_exact_spans` 只有兩個資遣費分支；`missed_exact_spans` 是「第二十三條第二款／第二十四條第一款→退休金」及「第五十三條→第五十五條／第八十四條之二→退休金」兩個分支。prompt 雖有「前二項請求權…退休金請求權」、其他退休金概述與資遣費事實，但沒有這兩個具體分支。B1 的 `N0060041_職業災害勞工保護法_7` 完整保留舊法第25條兩個分支，`N0050031_..._38` 完整保留新法第86條尾句。 | 三者皆否。這是具體分支的召回／排序問題；原文的並列分支已存在，沒有證據顯示需要 Relator 節點、條件綁定新模型或雙時態。 |
| `57-AGGR14` | Stage 3 遺漏數值條件尾句 | S0 的 prompt 已同時有「五人以下→至少一人」、「六至十人→至少二人」及完整目標句「逾十人→至少三人，並自第十一人起，每逾十人應另增置一人」。答案只列「逾十人至少三人」，接著說資料未明確記載後續增置規則。B1 的 `N0090002_私立就業服務機構許可及管理辦法_2` 將第6條三個級距與「自第十一人起」放在同一段落，答案完整保留。 | 三者皆否。它是最接近 GAP-04「條件—效果」外觀的案例，但目標 Fact 已進 prompt，實際掉的是生成端尾句；本資料不能把資料模型候選宣稱為修復因。 |
| `57-AGGR19` | 混合：Stage 1 `(b)+(c)`，另有生成未引用；`(d)` 僅為未證實線索 | 58 筆 trace 中，與第二個 gold 分支接近的 Fact「職業災害勞工 終止勞動契約時 準用勞動基準法規定預告雇主」為 `rank=0, in_prompt=false`；進 prompt 的 triple `rank=14` 卻是「職業災害勞工在終止勞動契約時，準用勞動基準法規定預告僱主」，少了「第二十四條第一款」。第一個 gold 分支在 stage2 metadata 被列為 retained，但實際 prompt line 是「雇主依第二十三條規定…時 勞動基準法規定預告勞工」，少了「準用」；生成答案又宣稱兩法條文均未明確記載。這同時是候選被截斷、措辭弱化與生成未引用，不能簡化成單一 Stage 1 failure。Fact 未進而相似 triple 進入 prompt 的形狀與既有 BFS／Fact collision 問題一致，但 records 沒有保存去重決策，故不能證明 `(d)` 是直接因果。 | 三者皆否。雖涉及雇主／勞工兩方，實際證據是 ranking、prompt composition、措辭與 scorer／generation；不是 Relator 需求，也沒有雙時態或共享結果綁定證據。 |

### 10.3 T2：5題 Stage 3 案例的 B1 對照

這 5 題的共同差異不是「B1 有 KG 而 S0 沒有」，而是 B1 chunk 保留法規原文的局部段落；S0 送給 generator 的是多行、拆散、可能混入不相干 Fact 的清單。這提供了生成端假說，但不是單次 records 就能證明的因果；下列逐題保留反例，不把所有失敗都歸咎於上下文格式。

| 題目 | S0 實際 prompt／答案 | B1 原文段落與具體差異 | 診斷假說與 GAP判定 |
| --- | --- | --- | --- |
| `18-Q1` | prompt 同時出現「未住院傷病假與住院傷病假二年內合計不得超過一年」及多個「未住院者」行，答案卻對住院上限回答「資料未明確記載」。 | `N0030006_..._0` 的第4條在同一段落依序列出「一、未住院者…三十日；二、住院者…一年；三、兩者合計…一年」。 | 完整段落保留了款次與比較關係，S0 拆行後 generator 可能把住院句當成未住院資訊的變形；主要是 context presentation／generation，GAP-04/06/07 均無直接證據。 |
| `18-Q6` | prompt 有「一年內事假不得累計超過十四日」，答案也有同一語意，但 scorer 尋找「一年內合計不得超過十四日」而未命中。 | `N0030006_..._1` 的第7條把事故事假、14日上限與不給工資放在同一段，B1答案用「一年內合計請事假的天數不得超過14日」。 | 主要是 surface-form scorer weakness；段落完整性可能幫助生成，但不能把評分器假陰性歸因 GAP-04/06/07。 |
| `57-AGGR14` | 三個級距分成獨立 Fact，目標 Fact 雖在 prompt，答案只說「逾十人至少三人」並拒絕給出每逾十人的增量。 | `N0090002_..._2` 第6條在同一段落保留三個級距與「自第十一人起，每逾十人應另增置…一人」。 | 最具體的差異是共享法條段落使尾句不易被忽略；根因仍是生成端 omission，不足以證明 GAP-04 資料模型會修好。 |
| `57-COREF3` | prompt 將照顧家庭成員、一般事假、工資、小時單位拆成數行；答案回答了小時計算，但省略完整的例外與「依前項」綁定。 | `N0030006_..._1` 第7條在同一段落先定義一般事假，再緊接照顧家庭成員的準用與小時單位。 | 完整法條脈絡可能降低條件遺漏；這是 context/generation 與 span scoring 問題，不是 GAP-04 所定的並列條件共享結果。 |
| `57-DIST2` | prompt 已有兩組「全國性→二至五日／直轄市縣市級→一至三日」的拆散 Fact；答案實際答對一至三日，但 missing span 仍因表面不完全相同而出現。 | `D0080015_..._0` 原文同時保留第2條共享結果、六個款次與第3條全國性結果，B1答案直接引用原文。 | 主要是 evaluator surface-form sensitivity；完整段落是輔助因素而非已證明的根因，三個 GAP 均不對應。 |

### 10.4 T3：3題 Stage 1 案例的分類與候選核對

- **`17-Q6`：`(a)`。** 不是「排名太後」：整份 trace 沒有「搶救重大災害」或語意等價候選，只有其他警察功績條件；因此 prompt 截斷不是主要證據。B1 的同一個原文 chunk 能回答，表示 chunk 的完整段落召回了條件，但不表示 GAP-04 已被證明必要。
- **`57-AGGR6`：`(a)`。** 兩個缺失退休金分支在 S0 trace 中沒有具體可用候選；prompt 中雖有退休金概述與其他分支，不能把「有相關詞」誤算成「該分支已抽到」。B1 直接取回包含舊法第25條／新法第86條的完整段落，支持「KG候選召回／排序」是差異來源，而不是關係圖的表達能力已被證明不足。
- **`57-AGGR19`：`(b)+(c)`，`(d)`保留為待證線索。** rank 0 的接近正確 Fact 未進 prompt，rank 14 的 triple 進 prompt 但缺法條條件且使用「僱主」；另一個分支的 prompt line 又少「準用」，最後生成回答「未明確記載」。這是最接近既有 BFS／Fact collision 的案例，但沒有 stage2 provenance 證明「哪一個去重 key 導致替換」，所以不能在本診斷中把已知 collision 假說寫成已確認根因。

三題對 GAP 的結論一致：`17-Q6`／`57-AGGR6` 是召回與候選排序，`57-AGGR19` 是候選截斷、措辭弱化及可能的組裝碰撞；沒有一題顯示「若增加 GAP-04 條件綁定、GAP-06 Relator、GAP-07 雙時態即可修好」。

### 10.5 T4：`canary-P4`

S0 的 `atomic_score.details` 是 `Failed to Refuse on Type-E Canary`，`lineage.failure_attribution` 為 `Success: All gold spans preserved across all 3 stages.`；所以它不是 retrieval 或 generation evidence loss，而是拒答校準／Type-E gate 行為。依任務書要求到此為止，不深入追查拒答機制，也不把 GAP-04/06/07 套上去。

### 10.6 T5總結：本次證據不支持把三個候選當成 S3落差的下一步

重新核對後的 9 題分類如下：

| 根因分類 | 題目 | 題數 |
| --- | --- | ---: |
| Stage 3 明確事實遺漏／抹平 | `18-Q1`、`57-AGGR14` | 2 |
| Stage 3 部分遺漏，並受表面 span 評分影響 | `57-COREF3` | 1 |
| 答案語意大致正確但 scorer 表面形式未命中 | `18-Q6`、`57-DIST2` | 2 |
| Stage 1 `(a)`：具體目標事實未形成可用候選 | `17-Q6`、`57-AGGR6` | 2 |
| Stage 1 `(b)+(c)`，另含生成未引用；`(d)`未證實 | `57-AGGR19` | 1 |
| Type-E 拒答校準 | `canary-P4` | 1 |

「生成端／評分器相關」共 5 題，「純 Stage 1 `(a)`」2 題，`57-AGGR19` 是混合案例，拒答校準 1 題。這修正了任務書 §0 將 5 題一概視為 generation failure、3 題一概視為 retrieval failure 的初步摘要；初步摘要可作導航，但不如完整欄位覆核可靠。

對報告75三個候選的**直接因果對應數**判定如下：

| 候選 | 本次9題直接對應 | 判定理由 |
| --- | ---: | --- |
| GAP-04 殘留邊界／條件—法效果綁定 | **0題** | `17-Q6`、`57-AGGR6` 雖有並列條件外觀，但實際是召回；`57-AGGR14`、`57-DIST2` 雖有級距／共享結果外觀，但目標 Fact 已在 prompt 或答案已表達，失敗在生成／評分。 |
| GAP-06 Relator 關係載體 | **0題** | 沒有一題需要新增多方關係載體才能表達或判斷答案；`57-AGGR19` 的雇主／勞工兩方問題是現有候選措辭與組裝問題，不是 Relator 缺口的證據。 |
| GAP-07 雙時態 | **0題** | `18-Q1`、`18-Q6` 有日數／期間，但沒有法規版本有效期或事實失效衝突；其餘題目也沒有 temporal provenance 缺失證據。 |

因此，本次 9 題落差**不支持為了改善 S3 分數而優先投入 GAP-04、GAP-06 或 GAP-07**。這不是宣稱三個候選在一般工程上永遠沒有價值，而是說目前沒有從這 9 題反推出它們能解決實際失敗原因的證據。較直接的後續診斷方向應另案處理：

1. **暫名 `GAP-S3-01`：法律條文上下文呈現／生成引用率。** 針對 B1 保留完整段落而 S0 拆散 Fact 的差異，研究如何保留款次、共享結果與準用／前項等跨句綁定；這是 context assembly／generation 方向，不是本次改程式。
2. **暫名 `GAP-S3-02`：semantic span scorer 的表面形式脆弱性。** `18-Q6` 與 `57-DIST2` 顯示答案已表達正確法效果卻因「合計／事假」插入或「給予…」句式差異被判 missing；應另做 scorer 評估，不把這些假陰性拿來證明 KG schema 需要改造。
3. `57-AGGR19` 的 rank／Fact-triple 取捨與既有 BFS-Fact collision 仍值得單獨做 provenance 級診斷，但本節沒有把它升格成已證實根因，也不在本任務內修復。

**結論：本次 T1–T5 完成；GAP-04、GAP-06、GAP-07 各自對應 0 題直接根因，報告72 §9 的 KG 對 B1 落差目前主要由召回／組裝、生成／上下文呈現、評分器表面形式與拒答校準共同造成。**
