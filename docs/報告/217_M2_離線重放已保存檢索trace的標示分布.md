# 報告217：M2——離線重放已保存檢索 trace 的派生標示分布

> **日期**：2026-10-01　**依據**：報告215 §3 M2　**性質**：離線分析（無 production 改動、未連 Neo4j／Ollama）
> **腳本**：`scripts/analysis/semantic_marks_replay.py`（測試 `tests/scripts/test_semantic_marks_replay.py`）　**原始輸出**：`data/analysis/semantic_marks_replay_20261001.json`
> 只描述分布，不宣稱品質改善。

## 1. 結論（先講最重要的）

1. **「進 prompt 的殘缺事實比例」無法由已保存結果離線算出**：已保存的 trace 每筆只有 `kind／rank／text／score／source_doc_id／source_svo_chunk_index／article_no／in_prompt`，**沒有 subject／object／verb／rel_type／實體型別**。因此 M1 的 `fields`、`relation_type`、實體型別三類標示**不可重放**。用 whitespace 切 `text` 推測空欄位不可靠（實測 Fact `text` 的主詞／受詞本身常含空白，空白切分得 1／2／3／4 段皆有，例：「依第三十條第三項規定變更正常工作時間者 勞工每七日中至少應有一日之例假…」只有 2 段但並非缺欄），故未採用。
2. 可重放的只有 **`in_prompt`**（被檢索 vs 進 prompt 的量體）與 **`article_no`（有／無）**，後者僅在 K2／K3（條文擴充）runs 有值。
3. 要回答 215 的核心問題（5,136 筆「尚未處理」殘缺事實在檢索結果中的占比、進 prompt 幾筆），需要一次**唯讀 join**：以 `(source_doc_id, source_svo_chunk_index, fact_text)` 對回 KG#4 的 Fact 節點取 subject／object／verb／rel_type。這會連 Neo4j（唯讀、須前後總數檢查），**依 M2 規則我未做，等規劃對話決定**。

## 2. 資料來源

掃描 `data/eval/**/records*.json`，其中 **27 個檔含 `lineage.stage1_retrieval.retrieval_trace`**（含 1 個 `records.backup_before_resume.json`，與正檔內容相同，僅列表不入去重）。去重（同題同 kind／text／doc／chunk）後覆蓋 **42 題、Fact 4,815 筆、triple 1,044 筆**（跨不同檢索設定併集，僅表達規模，**不宜據以比較設定**）。`report39_comparison/` 內 JSON 無逐筆 trace，不可用。

## 3. 各來源檔（Fact／triple 為被檢索筆數，A/B＝進 prompt／被檢索）

| 來源 | 題數 | Fact | Fact 進prompt | triple | triple 進prompt | Fact 有 article_no→進 prompt |
| --- | --- | --- | --- | --- | --- | --- |
| baseline 20260923 s0_r1 | 39 | 760 | 563/760 | 881 | 316/881 | 0→0 |
| baseline 20260923 s0_r1_resume1 | 3 | 60 | 50/60 | 94 | 29/94 | 0→0 |
| baseline 20260923 s0_r2 | 33 | 640 | 489/640 | 848 | 295/848 | 0→0 |
| s1_k1b_topk40_bfs16 a／b | 42／29 | 1633／1138 | 875／593 | 975／762 | 638／466 | 0→0 |
| s2_k1_topk40 a／b／c | 40／29／3 | 1560／1131／120 | 831／609／63 | 936／654／161 | 606／444／56 | 0→0 |
| s2_k2_article_expand a／b／c | 42／31／2 | 2373／1736／122 | 864／613／38 | 975／773／80 | 638／494／40 | 1860→661／1352→468／101→32 |
| s2_k3_article_expand_topk40 a／b／c | 41／32／1 | 4558／3612／123 | 887／694／20 | 930／789／45 | 608／483／30 | 3601→677／2855→541／95→16 |
| t0_trace_check／t2_probe | 1／1 | 20／40 | 19／31 | 29／29 | 16／4 | 0→0 |
| t2_k1_topk40 a／a2／a3／b／b2a／b2b／b2c／c | 27／14／1／12／8／7／7／2 | 1054／539／40／454／320／280／259／80 | 807／419／29／339／253／214／202／62 | 509／463／38／200／167／283／219／101 | 184／76／12／93／43／50／37／16 | 0→0 |
| p2_snapshot_20260929 run1／run2 | 6／6 | 66／66 | 49／49 | 23／23 | 23／23 | 0→0 |

（完整逐檔數字見原始 JSON。）

## 4. 可重放的 `article_no` 標示（僅 K2／K3）

K1 系列（含凍結基準 s0）的 trace 中 Fact 的 `article_no` 全為空——這是**該檢索路徑的 trace 未帶出條號**，不等於資料沒有條號（Phase 0：Fact 16,826 筆中 16,773 筆〔99.7%〕有 `LawArticle` 目標、53 筆無；64／65 份文件有條號）。因此 trace 內「無條號」依 M1 語意標為「無法由現有資料判定」，**不可**解讀為「未知」或「不適用」。

K2／K3（條文擴充）有條號的 Fact 進 prompt 比例：K2 stage_a 661/1,860（35.5%）、無條號者 203/513（39.6%）；K3 stage_a 677/3,601（18.8%）、無條號者 210/957（21.9%）。兩組差距小，且擴充設定下「有條號」多為擴充帶入的鄰近條文，不代表原始檢索偏向或避開任何類型。

## 5. 與 Phase 0 全圖分布並列（報告208／209／214 L3）

| 標示 | Phase 0 全圖（Fact 16,826） | 檢索結果／進 prompt |
| --- | --- | --- |
| fields：已解決（完整） | 11,545（68.6%） | **無法重放**（缺 subject／object／verb） |
| fields：尚未處理 | 5,136（30.5%） | 無法重放 |
| fields：未知（空受詞且空 verb） | 145（0.9%） | 無法重放 |
| relation_type：已解決／來源不明（RELATED_TO） | 1,832／14,994 | 無法重放（缺 rel_type） |
| article_no：有／無 | 16,773／53 | 僅 K2／K3 可部分重放，見 §4 |

因此**本次不能說「檢索偏向或避開殘缺事實」**——沒有資料支持任一方向。

## 6. 缺口與下一步（待規劃對話決定）

- 缺口：trace 無 subject／object／verb／rel_type／實體型別；K1 路徑 trace 無 `article_no`；triple 的 `text` 為自然語句，更無法拆欄。
- 選項 A：授權一次唯讀 join（KG#4，`assert_read_only`／`ReadOnlyRunner`、前後總數 57,451／137,873／16,826／12,296、先 `ListAgents`），以 `(source_doc_id, source_svo_chunk_index, fact_text)` 對回 Fact 取欄位後重放 M1 派生。
- 選項 B：日後讓 `build_retrieval_trace` 的呼叫端在下次評測時保存 `semantic_marks`（即 M1 旗標），屬新評測，需另行決定。

## 7. 驗證（§1–§6 的離線部分）

腳本 5 項單元測試通過；離線部分唯讀 `data/eval`，輸出寫 `data/analysis/semantic_marks_replay_20261001.json`；未連線、未改 production。

## 8. 補充：唯讀 join 結果（使用者於 2026-10-01 授權選項 A）

**做法**：`python scripts/analysis/semantic_marks_replay.py --join-neo4j --env-file <.env> --out data/analysis/semantic_marks_replay_join_20261001.json`。沿用 `ReadOnlyRunner`（READ session＋`assert_read_only` 白名單），只執行 1 條 Fact 全表查詢（`MATCH (f:Fact {kg_id}) OPTIONAL MATCH (f)-[:SUPPORTED_BY]->(a:LawArticle) RETURN …`）加前後各 4 條總數查詢；前後總數均為 57,451／137,873／16,826／12,296，**完全一致**（`totals_identical=true`）。`ListAgents` 確認當時無其他會連 Neo4j 的 session（唯一 peer 為規劃對話）；未啟動 Ollama、未印出密碼、KG#4 未寫入。以 `(source_doc_id, source_svo_chunk_index, fact_text)` 對回 Fact，再用 `services/semantic_marks.py` 對等函式派生（文件層條號適用性取自 Fact 全表：該文件任一 Fact 有 `LawArticle.article_no` 即「適用」）。同鍵多筆且標示不一致者列為「歧義」不計入（KG#4 有 225 組重複鍵；實測各檔歧義＝0）。**只涵蓋 Fact；triple 的標示未做**（edge 無 Fact 對應鍵，且實體型別需另 join Entity，列為剩餘缺口）。

### 8.1 Fact「欄位完整性」與「關係型別」分布（以對到的 Fact 為分母）

| 來源設定 | Fact 筆數 | 對到（未對到） | 被檢索：已解決（完整）／尚未處理／未知 | 進 prompt：已解決／尚未處理／未知 | 關係型別「已解決」占比（被檢索／進 prompt） |
| --- | --- | --- | --- | --- | --- |
| 凍結基準 s0（r1+resume1+r2） | 1,460 | 1,460（0） | 1,160（79.5%）／290（19.9%）／10（0.7%） | 836（75.9%）／266（24.1%）／0 （共1,102） | 9.9%／9.4% |
| s2_k1_topk40（a+b+c） | 2,811 | 2,811（0） | 2,156（76.7%）／637（22.7%）／18（0.6%） | 1,101（73.3%）／402（26.7%）／0 （共1,503） | 10.5%／9.6% |
| s2_k2 條文擴充（a+b+c） | 4,231 | 4,231（0） | 3,127（73.9%）／1,042（24.6%）／62（1.5%） | 1,110（73.3%）／405（26.7%）／0 （共1,515） | 10.7%／9.0% |
| s2_k3 條文擴充 top40（a+b+c） | 8,293 | 8,293（0） | 6,280（75.7%）／1,931（23.3%）／82（1.0%） | 1,181（73.8%）／420（26.2%）／0 （共1,601） | 10.2%／8.8% |
| t2_k1_topk40（全部 stage） | 3,026 | 2,881（145） | 2,186（75.9%）／678（23.5%）／17（0.6%） | 1,620（72.3%）／621（27.7%）／0 （共2,241） | 10.3%／9.8% |

（逐檔數字見 `data/analysis/semantic_marks_replay_join_20261001.json`。同一事實跨 stage／run 會重複計，僅描述各設定內的分布，不跨設定相加。）

**Phase 0 全圖對照（Fact 16,826）**：完整 68.6%／尚未處理 30.5%／未知 0.9%；關係型別「已解決」10.9%（其餘 RELATED_TO＝來源不明）。

### 8.2 描述性觀察（不作品質結論）

1. **被檢索 Fact 的「尚未處理」占比（19.9%–24.6%）低於全圖 30.5%，「完整」占比（73.9%–79.5%）高於全圖 68.6%**——檢索結果中殘缺事實略少於母體，各設定方向一致。
2. **進 prompt 的 Fact 中「尚未處理」占比（24.1%–27.7%）又高於被檢索集合（19.9%–24.6%）**；進 prompt 的「未知」（空受詞且空 verb）在所有設定皆為 **0 筆**，與現行 `is_contentful_line`／渲染過濾一致（被檢索的「未知」共 10–82 筆）。換言之，現行過濾已排除「未知」，但「尚未處理」（多為空受詞但有 verb）大量進入 prompt，約每 4 筆進 prompt 的 Fact 有 1 筆屬此類——這正是 215 §1 P1／P2 所指與現行過濾重疊之處。
3. **關係型別**：被檢索與進 prompt 的 Fact 中，「已解決」（非 RELATED_TO）約 9–11%，與全圖 10.9% 接近；進 prompt 略低（8.8%–9.8%）。
4. **條號**：對到的 Fact 幾乎都有條號（「已解決」；僅 2 筆「不適用」，屬無條號文件），與 Phase 0（99.7%）一致；§4 的 trace 內「無法判定」確為 trace 欄位缺失造成的重放假象。
5. 未對到（`t2_k1_topk40` 系列 145 筆）：該批 run 為較早的 KG 狀態（Fact 文字後來有變動），其餘設定 0 筆未對到。

### 8.3 剩餘缺口

- triple（BFS 邊）標示與實體型別標示未做（需 edge／Entity join，且 trace 的 triple `text` 為自然語句）。
- 這些是「被檢索／進 prompt 的描述性分布」，**不顯示殘缺事實是否影響答案品質**，亦未與答對／答錯交叉；是否接進 prompt 或降權屬使用者決定（215 §5-3）。

### 8.4 驗證

腳本單元測試 9 項（含 join 函式以假 runner 測，無需連線）；全量 pytest 見回報。
