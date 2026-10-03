# 報告 276：S3 前置量測——凍結評測 prompt 中「尚未施行」證據的實際暴露

> 規劃對話（project refactor review sdd）。2026-10-04。僅唯讀：KG#4 走 `ReadOnlyRunner`，檢索記錄取自離線 `data/eval/candidate_runs/t2_k1_topk40_stage_*`。未改任何程式、未寫 KG#4。

## 1. 目的

S3（把「尚未施行」標示寫進 prompt）會改變回答行為。決策前先量：凍結評測 K1（top_k=40，8 個 stage、42 題）真正進入 prompt 的證據裡，有多少屬於尚未施行條文？若暴露極低，S3 的收益無法用現有題庫量到。

## 2. 方法

- 取 42 題無錯誤記錄中 `in_prompt` 且具 `source_doc_id` + `source_svo_chunk_index` 的證據，共 **2,325 項**。
- 以 S1/S2/S2b 既有函式（`effective_marks_kwargs`、`article_effective_marks`）、`as_of=2026-10-04` 對每項判定條文層狀態；條文對應由 KG#4 唯讀查 `Fact -[:SUPPORTED_BY]-> LawArticle`。
- 腳本：job tmp 的 `s3_exposure.py`（不入庫，邏輯如上）。

## 3. 結果

| 條文層狀態 | 項數 | 占比 |
|---|---|---|
| no_information（文件無施行備註） | 1,538 | 66.2% |
| in_force | 667 | 28.7% |
| pending_partial | 116 | 5.0% |
| 無法由現有資料判定（chunk 對不到條文） | 4 | 0.2% |
| pending_whole | 0 | 0% |

- `pending_partial` 的 116 項**全部來自勞工健康保護規則**，分布在 **14／42 題**（含 57-CANARY3、57-AGGR1/2/7/14/16/17、57-COREF1/2/3、57-DIST1、18-Q4 等）。
- `pending_whole`：0 題。勞動契約法（undetermined）：0 項進 prompt。
- 腳本內 `undetermined` 計數鍵與實際標籤（中文「無法由現有資料判定」）不一致，故逐題 `undetermined` 列為 0 是鍵名問題；該 4 項是 chunk 對不到條文，不是勞動契約法，結論不變。

## 4. 解讀

1. 暴露集中：只有一部法規、且全是「部分條款尚未施行」，不是整條未生效。
2. `pending_partial` 只代表該條文有尚未施行的**款／附表**；116 項中有多少真的引用到未施行部分，現有資料不能判斷（需看 `locators` 與回答引用內容）。
3. 凍結題庫無法衡量 S3：沒有題目專門問「某條何時施行／是否已生效」，14 題碰到只是檢索順帶帶入。

## 5. 對 S3 的建議

- **不做排除**：pending_whole 在真實 prompt 為 0，沒有可排除的對象，排除只會增加漏答風險。
- **若做就只做「標註」且限 pending_partial**，附 `locators` 與 `effective_from`，措辭中性（例：「本條之○○自○年○月○日施行」），不宣稱整條無效。
- **勞動契約法**：prompt 暴露為 0，S3 階段不處理；若日後要處理，另開題（需先有進 prompt 的題目）。
- **先備評測題**：S3 要有新題（健康保護規則含未施行款的題、問施行日的題），且先約定採用規則，才能判斷 S3 是否有益。
- 優先序建議：S3 排在「使用者開 `TRACE_SEMANTIC_MARKS=1` 觀察」之後，並以觀察結果決定是否值得。

## 6. 待使用者裁示

1. 是否開啟旗標觀察 S2/S2b（部署由使用者決定，我不動）。
2. 是否要新增 S3 評測題（需另開任務書）。
3. 施行日資料缺口（48／64 份文件無 `effective_note`）是否補。
