# RQ1 統一評測報告：Pareto 最優邊界與全生命週期成本矩陣

> 生成時間：2026-09-20T17:28:41.745117+00:00
> 基準圖譜：`236903cf-055a-40a8-8923-b9d06601f3b7` | 評測題數：10 題 | 每題重複：3 次

## 1. 核心四大代表方法 Pareto 表現矩陣

| 方法代號 | 代表架構 | 原子事實正確率 (Acc) | 必要事實召回率 (Rec) | 服務期 p50 延遲 (s) | 建庫膨脹比 | 千次查詢預估 (USD) |
|---|---|---|---|---|---|---|
| **M2** | B1 | 70.0% | 70.0% | 133.79s | 2.33x | $0.1484 |

## 2. 場景梯度細分（Type-A ~ Type-E）表現

| 題號 | 場景分類 | M2 |
|---|---| --- |
| **17-Q1** | `Type-A` | 0% (0/3✓) |
| **17-Q2** | `Type-A` | 100% (3/3✓) |
| **18-Q1** | `Type-B` | 100% (3/3✓) |
| **18-Q2** | `Type-B` | 100% (3/3✓) |
| **18-Q3** | `Type-A` | 0% (0/3✓) |
| **18-Q4** | `Type-B` | 100% (3/3✓) |
| **18-Q5** | `Type-B` | 0% (0/3✓) |
| **26-Q5** | `Type-C` | 100% (3/3✓) |
| **canary-P1** | `Type-E` | 100% (3/3✓) |
| **canary-P4** | `Type-E` | 100% (3/3✓) |

## 3. 典型缺陷全鏈路血統歸因

| 題號 | 方法 | 錯誤診斷 | 歸因原因 |
|---|---|---|---|
| 17-Q1 | M2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['勞工結婚者給予婚假八日，工資照給']. |
| 17-Q1 | M2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['勞工結婚者給予婚假八日，工資照給']. |
| 17-Q1 | M2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['勞工結婚者給予婚假八日，工資照給']. |
| 18-Q3 | M2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['自行排定請假返國期日', '雇主應予同意']. |
| 18-Q3 | M2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['自行排定請假返國期日', '雇主應予同意']. |
| 18-Q3 | M2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['自行排定請假返國期日', '雇主應予同意']. |
| 18-Q5 | M2 | 瑕疵 | Harness Timeout after 180.0s |
| 18-Q5 | M2 | 瑕疵 | Harness Timeout after 180.0s |
| 18-Q5 | M2 | 瑕疵 | Harness Timeout after 180.0s |