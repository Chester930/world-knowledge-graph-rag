# RQ1 統一評測報告：Pareto 最優邊界與全生命週期成本矩陣

> 生成時間：2026-09-29T16:32:20.478844+00:00
> 基準圖譜：`236903cf-055a-40a8-8923-b9d06601f3b7` | 評測題數：6 題 | 每題重複：1 次

## 1. 核心四大代表方法 Pareto 表現矩陣

| 方法代號 | 代表架構 | 原子事實正確率 (Acc) | 必要事實召回率 (Rec) | 服務期 p50 延遲 (s) | 建庫膨脹比 | 千次查詢預估 (USD) |
|---|---|---|---|---|---|---|
| **M4** | K | 81.9% | 81.9% | 146.63s | 25.77x | $0.0587 |

## 2. Context Quality 矩陣（維度I，純檢索品質，不受生成端干擾——報告57 §2）

| 方法代號 | Context Recall | SNR（信噪比） | Chain Completeness（僅跨文件題） |
|---|---|---|---|
| **M4** | 77.8% | 9.7% | N/A（無跨文件題樣本） |

## 3. 場景梯度細分（Type-A ~ Type-E）表現

| 題號 | 場景分類 | M4 |
|---|---| --- |
| **17-Q1** | `Type-A` | 100% (1/1✓) |
| **26-Q1** | `Type-B` | 100% (1/1✓) |
| **26-Q5** | `Type-C` | 50% (0/1✓) |
| **57-DIST1** | `Type-B` | 75% (0/1✓) |
| **57-COREF1** | `Type-B` | 67% (0/1✓) |
| **canary-P1** | `Type-E` | 100% (1/1✓) |

## 4. 典型缺陷全鏈路血統歸因

| 題號 | 方法 | 錯誤診斷 | 歸因原因 |
|---|---|---|---|
| 26-Q5 | M4 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['災後六個月期間內被保險人應負擔之保險費，由中央政府支應']. |
| 57-DIST1 | M4 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['當選直轄市、縣（市）級模範警察或好人好事代表者']. |
| 57-COREF1 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 1/3 gold facts missed (['受僱者因突發情形不及於一日前提出者，得委託他人代辦申請手續']) |