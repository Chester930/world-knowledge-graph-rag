# RQ1 統一評測報告：Pareto 最優邊界與全生命週期成本矩陣

> 生成時間：2026-09-28T01:32:09.758669+00:00
> 基準圖譜：`236903cf-055a-40a8-8923-b9d06601f3b7` | 評測題數：6 題 | 每題重複：1 次

## 1. 核心四大代表方法 Pareto 表現矩陣

| 方法代號 | 代表架構 | 原子事實正確率 (Acc) | 必要事實召回率 (Rec) | 服務期 p50 延遲 (s) | 建庫膨脹比 | 千次查詢預估 (USD) |
|---|---|---|---|---|---|---|
| **M1** | B0 | 77.8% | 77.8% | 57.16s | 1.53x | $0.1764 |
| **M2** | B1 | 94.4% | 94.4% | 65.01s | 2.33x | $0.1813 |
| **B2** | B2 | 94.4% | 94.4% | 82.40s | 2.33x | $0.2546 |

## 2. Context Quality 矩陣（維度I，純檢索品質，不受生成端干擾——報告57 §2）

| 方法代號 | Context Recall | SNR（信噪比） | Chain Completeness（僅跨文件題） |
|---|---|---|---|
| **M1** | 83.3% | 1.9% | N/A（無跨文件題樣本） |
| **M2** | 83.3% | 1.9% | N/A（無跨文件題樣本） |
| **B2** | 83.3% | 1.4% | N/A（無跨文件題樣本） |

## 3. 場景梯度細分（Type-A ~ Type-E）表現

| 題號 | 場景分類 | M1 | M2 | B2 |
|---|---| --- | --- | --- |
| **26-Q1** | `Type-B` | 100% (1/1✓) | 100% (1/1✓) | 100% (1/1✓) |
| **26-Q5** | `Type-C` | 100% (1/1✓) | 100% (1/1✓) | 100% (1/1✓) |
| **canary-P1** | `Type-E` | 0% (0/1✓) | 100% (1/1✓) | 100% (1/1✓) |
| **canary-P4** | `Type-E` | 100% (1/1✓) | 100% (1/1✓) | 100% (1/1✓) |
| **57-COREF1** | `Type-B` | 67% (0/1✓) | 67% (0/1✓) | 67% (0/1✓) |
| **57-COREF2** | `Type-A` | 100% (1/1✓) | 100% (1/1✓) | 100% (1/1✓) |

## 4. 典型缺陷全鏈路血統歸因

| 題號 | 方法 | 錯誤診斷 | 歸因原因 |
|---|---|---|---|
| canary-P1 | M1 | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['未記載相關規定']) |
| 57-COREF1 | M1 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['因子女生病、停托、停課，受僱者須親自照顧時，得於一日前提出']. |
| 57-COREF1 | M2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['因子女生病、停托、停課，受僱者須親自照顧時，得於一日前提出']. |
| 57-COREF1 | B2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['因子女生病、停托、停課，受僱者須親自照顧時，得於一日前提出']. |