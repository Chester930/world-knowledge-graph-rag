# RQ1 統一評測報告：Pareto 最優邊界與全生命週期成本矩陣

> 生成時間：2026-09-15T18:07:49.082272+00:00
> 基準圖譜：`236903cf-055a-40a8-8923-b9d06601f3b7` | 評測題數：3 題 | 每題重複：1 次

## 1. 核心四大代表方法 Pareto 表現矩陣

| 方法代號 | 代表架構 | 原子事實正確率 (Acc) | 必要事實召回率 (Rec) | 服務期 p50 延遲 (s) | 建庫膨脹比 | 千次查詢預估 (USD) |
|---|---|---|---|---|---|---|
| **K** | K | 0.0% | 0.0% | 117.27s | 25.77x | $0.0000 |

## 2. Context Quality 矩陣（維度I，純檢索品質，不受生成端干擾——報告57 §2）

| 方法代號 | Context Recall | SNR（信噪比） | Chain Completeness（僅跨文件題） |
|---|---|---|---|
| **K** | 0.0% | 0.0% | 0.0% (n=3) |

## 3. 場景梯度細分（Type-A ~ Type-E）表現

| 題號 | 場景分類 | K |
|---|---| --- |
| **57-AGGR1** | `Type-C` | 0% (0/1✓) |
| **57-AGGR2** | `Type-D` | 0% (0/1✓) |
| **57-CANARY3** | `Type-E` | 0% (0/1✓) |

## 4. 典型缺陷全鏈路血統歸因

| 題號 | 方法 | 錯誤診斷 | 歸因原因 |
|---|---|---|---|
| 57-AGGR1 | K | 瑕疵 | Harness Exception: ValidationError: 6 validation errors for RetrievalStageLineage
retrieved_fact_ids.0
  Input should be a valid string [type=string_type, input_value=None, input_type=NoneType]
    For further information visit https://errors.pydantic.dev/2.12/v/string_type
retrieved_fact_ids.1
  Input should be a valid string [type=string_type, input_value=None, input_type=NoneType]
    For further information visit https://errors.pydantic.dev/2.12/v/string_type
retrieved_fact_ids.2
  Input should be a valid string [type=string_type, input_value=None, input_type=NoneType]
    For further information visit https://errors.pydantic.dev/2.12/v/string_type
retrieved_fact_ids.3
  Input should be a valid string [type=string_type, input_value=None, input_type=NoneType]
    For further information visit https://errors.pydantic.dev/2.12/v/string_type
retrieved_fact_ids.4
  Input should be a valid string [type=string_type, input_value=None, input_type=NoneType]
    For further information visit https://errors.pydantic.dev/2.12/v/string_type
retrieved_fact_ids.5
  Input should be a valid string [type=string_type, input_value=None, input_type=NoneType]
    For further information visit https://errors.pydantic.dev/2.12/v/string_type |
| 57-AGGR2 | K | 瑕疵 | Harness Exception: TypeError: sequence item 1: expected str instance, NoneType found |
| 57-CANARY3 | K | 瑕疵 | Harness Timeout after 180.0s |