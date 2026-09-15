# RQ1 統一評測報告：Pareto 最優邊界與全生命週期成本矩陣

> 生成時間：2026-09-14T09:52:36.634288+00:00
> 基準圖譜：`236903cf-055a-40a8-8923-b9d06601f3b7` | 評測題數：4 題 | 每題重複：1 次

## 1. 核心四大代表方法 Pareto 表現矩陣

| 方法代號 | 代表架構 | 原子事實正確率 (Acc) | 必要事實召回率 (Rec) | 服務期 p50 延遲 (s) | 建庫膨脹比 | 千次查詢預估 (USD) |
|---|---|---|---|---|---|---|
| **M1** | B0 | 25.0% | 25.0% | 98.03s | 1.53x | $0.1290 |
| **M4** | K | 25.0% | 25.0% | 180.00s | 25.77x | $0.0162 |

## 2. 場景梯度細分（Type-A ~ Type-E）表現

| 題號 | 場景分類 | M1 | M4 |
|---|---| --- | --- |
| **17-Q1** | `Type-A` | 100% (1/1✓) | 0% (0/1✓) |
| **18-Q4** | `Type-B` | 0% (0/1✓) | 0% (0/1✓) |
| **26-Q5** | `Type-C` | 0% (0/1✓) | 0% (0/1✓) |
| **canary-P1** | `Type-E` | 0% (0/1✓) | 100% (1/1✓) |

## 3. 典型缺陷全鏈路血統歸因

| 題號 | 方法 | 錯誤診斷 | 歸因原因 |
|---|---|---|---|
| 17-Q1 | M4 | 瑕疵 | Harness Timeout after 180.0s |
| 18-Q4 | M1 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['得就其給付薪資金額之百分之一百五十，自當年度營利事業所得額減除']. |
| 18-Q4 | M4 | 瑕疵 | Harness Timeout after 180.0s |
| 26-Q5 | M1 | 瑕疵 | Harness Timeout after 180.0s |
| 26-Q5 | M4 | 瑕疵 | Harness Timeout after 180.0s |
| canary-P1 | M1 | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['未記載相關規定']) |