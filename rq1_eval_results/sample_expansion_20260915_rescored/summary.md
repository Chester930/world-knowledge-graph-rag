# RQ1 統一評測報告：Pareto 最優邊界與全生命週期成本矩陣

> 生成時間：2026-09-15T06:10:44.530549+00:00
> 基準圖譜：`236903cf-055a-40a8-8923-b9d06601f3b7` | 評測題數：32 題 | 每題重複：3 次

## 1. 核心四大代表方法 Pareto 表現矩陣

| 方法代號 | 代表架構 | 原子事實正確率 (Acc) | 必要事實召回率 (Rec) | 服務期 p50 延遲 (s) | 建庫膨脹比 | 千次查詢預估 (USD) |
|---|---|---|---|---|---|---|
| **M1** | B0 | 91.1% | 91.1% | 83.64s | 1.53x | $0.1787 |
| **M2** | B1 | 96.1% | 96.1% | 59.65s | 2.33x | $0.1713 |
| **M3** | F | 70.0% | 70.0% | 125.35s | 11.35x | $0.0467 |
| **M4** | K | 66.7% | 66.7% | 169.64s | 25.77x | $0.0510 |

## 2. 場景梯度細分（Type-A ~ Type-E）表現

| 題號 | 場景分類 | M1 | M2 | M3 | M4 |
|---|---| --- | --- | --- | --- |
| **17-Q1** | `Type-A` | 100% (3/3✓) | 100% (3/3✓) | 100% (3/3✓) | 100% (3/3✓) |
| **17-Q2** | `Type-A` | 100% (3/3✓) | 100% (3/3✓) | 100% (3/3✓) | 100% (3/3✓) |
| **17-Q3** | `Type-B` | — | — | — | — |
| **17-Q4** | `Type-A` | — | — | — | — |
| **17-Q5** | `Type-A` | — | — | — | — |
| **17-Q6** | `Type-B` | — | — | — | — |
| **17-Q7** | `Type-B` | — | — | — | — |
| **18-Q1** | `Type-B` | 100% (3/3✓) | 100% (3/3✓) | 67% (0/3✓) | 56% (0/3✓) |
| **18-Q2** | `Type-B` | 100% (3/3✓) | 100% (3/3✓) | 100% (3/3✓) | 100% (3/3✓) |
| **18-Q3** | `Type-A` | 83% (2/3✓) | 83% (2/3✓) | 83% (2/3✓) | 83% (2/3✓) |
| **18-Q4** | `Type-B` | 100% (3/3✓) | 100% (3/3✓) | 67% (2/3✓) | 33% (1/3✓) |
| **18-Q5** | `Type-B` | 78% (1/3✓) | 78% (2/3✓) | 33% (0/3✓) | 44% (0/3✓) |
| **18-Q6** | `Type-A` | — | — | — | — |
| **18-Q7** | `Type-B` | — | — | — | — |
| **25-Q1** | `Type-A` | — | — | — | — |
| **25-Q2** | `Type-B` | — | — | — | — |
| **25-Q3** | `Type-B` | — | — | — | — |
| **25-Q4** | `Type-B` | — | — | — | — |
| **25-Q5** | `Type-B` | — | — | — | — |
| **25-Q6** | `Type-B` | — | — | — | — |
| **25-Q7** | `Type-B` | — | — | — | — |
| **25-Q8** | `Type-B` | — | — | — | — |
| **26-Q1** | `Type-B` | — | — | — | — |
| **26-Q2** | `Type-B` | — | — | — | — |
| **26-Q3** | `Type-C` | — | — | — | — |
| **26-Q4** | `Type-B` | — | — | — | — |
| **26-Q5** | `Type-C` | 83% (2/3✓) | 100% (3/3✓) | 50% (0/3✓) | 50% (1/3✓) |
| **26-Q6** | `Type-B` | — | — | — | — |
| **26-Q7** | `Type-B` | — | — | — | — |
| **26-Q8** | `Type-B` | — | — | — | — |
| **canary-P1** | `Type-E` | 100% (3/3✓) | 100% (3/3✓) | 33% (1/3✓) | 33% (1/3✓) |
| **canary-P4** | `Type-E` | 67% (2/3✓) | 100% (3/3✓) | 67% (2/3✓) | 67% (2/3✓) |

## 3. 典型缺陷全鏈路血統歸因

| 題號 | 方法 | 錯誤診斷 | 歸因原因 |
|---|---|---|---|
| 18-Q1 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['未住院者，一年內合計不得超過三十日', '住院者，二年內合計不得超過一年', '未超過三十日部分，工資折半發給']) |
| 18-Q1 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['未住院者，一年內合計不得超過三十日', '住院者，二年內合計不得超過一年', '未超過三十日部分，工資折半發給']) |
| 18-Q3 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['雇主應予同意']) |
| 18-Q4 | M4 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['得就其給付薪資金額之百分之一百五十，自當年度營利事業所得額減除']. |
| 18-Q5 | M1 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['有左列情事之一者，給予三至七日之特別休假']. |
| 18-Q5 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['有左列情形之一者，給予一至三日之特別休假', '有左列情事之一者，給予二至五日之特別休假', '有左列情事之一者，給予三至七日之特別休假']) |
| 18-Q5 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['有左列情形之一者，給予一至三日之特別休假', '有左列情事之一者，給予二至五日之特別休假', '有左列情事之一者，給予三至七日之特別休假']) |
| 26-Q5 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['自災害發生之當月一日起計算六個月']) |
| 26-Q5 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['自災害發生之當月一日起計算六個月']) |
| canary-P1 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['未記載相關規定']) |
| canary-P1 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['未記載相關規定']) |
| canary-P4 | M1 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['未記載相關規定']. |
| canary-P4 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['未記載相關規定']) |
| 18-Q1 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['未住院者，一年內合計不得超過三十日', '住院者，二年內合計不得超過一年', '未超過三十日部分，工資折半發給']) |
| 18-Q1 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['未住院者，一年內合計不得超過三十日', '住院者，二年內合計不得超過一年', '未超過三十日部分，工資折半發給']) |
| 18-Q3 | M1 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['雇主應予同意']. |
| 18-Q3 | M2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['雇主應予同意']. |
| 18-Q4 | M3 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['得就其給付薪資金額之百分之一百五十，自當年度營利事業所得額減除']. |
| 18-Q5 | M1 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['有左列情事之一者，給予三至七日之特別休假']. |
| 18-Q5 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['有左列情形之一者，給予一至三日之特別休假', '有左列情事之一者，給予二至五日之特別休假', '有左列情事之一者，給予三至七日之特別休假']) |
| 18-Q5 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['有左列情形之一者，給予一至三日之特別休假', '有左列情事之一者，給予二至五日之特別休假', '有左列情事之一者，給予三至七日之特別休假']) |
| 26-Q5 | M1 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['災後六個月期間內被保險人應負擔之保險費，由中央政府支應']. |
| 26-Q5 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['自災害發生之當月一日起計算六個月']) |
| canary-P1 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['未記載相關規定']) |
| canary-P1 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['未記載相關規定']) |
| canary-P4 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['未記載相關規定']) |
| 18-Q1 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['未住院者，一年內合計不得超過三十日', '住院者，二年內合計不得超過一年', '未超過三十日部分，工資折半發給']) |
| 18-Q1 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['未住院者，一年內合計不得超過三十日', '住院者，二年內合計不得超過一年', '未超過三十日部分，工資折半發給']) |
| 18-Q3 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['雇主應予同意']) |
| 18-Q4 | M4 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['得就其給付薪資金額之百分之一百五十，自當年度營利事業所得額減除']. |
| 18-Q5 | M2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['有左列情形之一者，給予一至三日之特別休假', '有左列情事之一者，給予二至五日之特別休假']. |
| 18-Q5 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['有左列情形之一者，給予一至三日之特別休假', '有左列情事之一者，給予二至五日之特別休假', '有左列情事之一者，給予三至七日之特別休假']) |
| 18-Q5 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['有左列情形之一者，給予一至三日之特別休假', '有左列情事之一者，給予二至五日之特別休假', '有左列情事之一者，給予三至七日之特別休假']) |
| 26-Q5 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['自災害發生之當月一日起計算六個月']) |
| 26-Q5 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['自災害發生之當月一日起計算六個月']) |