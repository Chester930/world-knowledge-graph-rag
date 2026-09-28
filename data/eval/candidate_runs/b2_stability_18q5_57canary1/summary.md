# RQ1 統一評測報告：Pareto 最優邊界與全生命週期成本矩陣

> 生成時間：2026-09-28T07:49:25.074933+00:00
> 基準圖譜：`236903cf-055a-40a8-8923-b9d06601f3b7` | 評測題數：2 題 | 每題重複：3 次

## 1. 核心四大代表方法 Pareto 表現矩陣

| 方法代號 | 代表架構 | 原子事實正確率 (Acc) | 必要事實召回率 (Rec) | 服務期 p50 延遲 (s) | 建庫膨脹比 | 千次查詢預估 (USD) |
|---|---|---|---|---|---|---|
| **M1** | B0 | 66.7% | 66.7% | 272.15s | 1.53x | $0.1266 |
| **M2** | B1 | 50.0% | 50.0% | 286.52s | 2.33x | $0.1201 |
| **B2** | B2 | 16.7% | 16.7% | 257.34s | 2.33x | $0.4827 |

## 2. Context Quality 矩陣（維度I，純檢索品質，不受生成端干擾——報告57 §2）

| 方法代號 | Context Recall | SNR（信噪比） | Chain Completeness（僅跨文件題） |
|---|---|---|---|
| **M1** | 66.7% | 0.7% | N/A（無跨文件題樣本） |
| **M2** | 66.7% | 0.8% | N/A（無跨文件題樣本） |
| **B2** | 100.0% | 0.6% | N/A（無跨文件題樣本） |

## 3. 場景梯度細分（Type-A ~ Type-E）表現

| 題號 | 場景分類 | M1 | M2 | B2 |
|---|---| --- | --- | --- |
| **18-Q5** | `Type-B` | 33% (1/3✓) | 0% (0/3✓) | 33% (0/3✓) |
| **57-CANARY1** | `Type-E` | 100% (3/3✓) | 100% (3/3✓) | 0% (0/3✓) |

## 4. 典型缺陷全鏈路血統歸因

| 題號 | 方法 | 錯誤診斷 | 歸因原因 |
|---|---|---|---|
| 18-Q5 | M1 | 瑕疵 | Harness Timeout after 300.0s |
| 18-Q5 | M1 | 瑕疵 | Harness Timeout after 300.0s |
| 18-Q5 | M2 | 瑕疵 | Harness Timeout after 300.0s |
| 18-Q5 | M2 | 瑕疵 | Harness Timeout after 300.0s |
| 18-Q5 | M2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['有左列情形之一者，給予一至三日之特別休假', '有左列情事之一者，給予二至五日之特別休假', '有左列情事之一者，給予三至七日之特別休假']. |
| 18-Q5 | B2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['有左列情事之一者，給予二至五日之特別休假', '有左列情事之一者，給予三至七日之特別休假']. |
| 18-Q5 | B2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['有左列情事之一者，給予二至五日之特別休假', '有左列情事之一者，給予三至七日之特別休假']. |
| 18-Q5 | B2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['有左列情事之一者，給予二至五日之特別休假', '有左列情事之一者，給予三至七日之特別休假']. |