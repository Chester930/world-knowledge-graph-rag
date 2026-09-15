# RQ1 統一評測報告：Pareto 最優邊界與全生命週期成本矩陣

> 生成時間：2026-09-15T04:34:35.677737+00:00
> 基準圖譜：`236903cf-055a-40a8-8923-b9d06601f3b7` | 評測題數：10 題 | 每題重複：3 次

## 1. 核心四大代表方法 Pareto 表現矩陣

| 方法代號 | 代表架構 | 原子事實正確率 (Acc) | 必要事實召回率 (Rec) | 服務期 p50 延遲 (s) | 建庫膨脹比 | 千次查詢預估 (USD) |
|---|---|---|---|---|---|---|
| **M1** | B0 | 68.9% | 68.9% | 83.64s | 1.53x | $0.1787 |
| **M2** | B1 | 70.6% | 70.6% | 59.65s | 2.33x | $0.1713 |
| **M3** | F | 30.0% | 30.0% | 125.35s | 11.35x | $0.0467 |
| **M4** | K | 32.2% | 32.2% | 169.64s | 25.77x | $0.0510 |

## 2. 場景梯度細分（Type-A ~ Type-E）表現

| 題號 | 場景分類 | M1 | M2 | M3 | M4 |
|---|---| --- | --- | --- | --- |
| **17-Q1** | `Type-A` | 100% (3/3✓) | 100% (3/3✓) | 0% (0/3✓) | 0% (0/3✓) |
| **17-Q2** | `Type-A` | 100% (3/3✓) | 100% (3/3✓) | 0% (0/3✓) | 0% (0/3✓) |
| **18-Q1** | `Type-B` | 89% (2/3✓) | 56% (1/3✓) | 67% (0/3✓) | 56% (0/3✓) |
| **18-Q2** | `Type-B` | 83% (2/3✓) | 83% (2/3✓) | 33% (0/3✓) | 50% (0/3✓) |
| **18-Q3** | `Type-A` | 17% (0/3✓) | 33% (0/3✓) | 0% (0/3✓) | 50% (0/3✓) |
| **18-Q4** | `Type-B` | 100% (3/3✓) | 67% (2/3✓) | 67% (2/3✓) | 33% (1/3✓) |
| **18-Q5** | `Type-B` | 0% (0/3✓) | 0% (0/3✓) | 0% (0/3✓) | 0% (0/3✓) |
| **26-Q5** | `Type-C` | 33% (1/3✓) | 67% (2/3✓) | 33% (0/3✓) | 33% (0/3✓) |
| **canary-P1** | `Type-E` | 100% (3/3✓) | 100% (3/3✓) | 33% (1/3✓) | 33% (1/3✓) |
| **canary-P4** | `Type-E` | 67% (2/3✓) | 100% (3/3✓) | 67% (2/3✓) | 67% (2/3✓) |

## 3. 典型缺陷全鏈路血統歸因

| 題號 | 方法 | 錯誤診斷 | 歸因原因 |
|---|---|---|---|
| 17-Q1 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['勞工結婚者給予婚假八日，工資照給']) |
| 17-Q1 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['勞工結婚者給予婚假八日，工資照給']) |
| 17-Q2 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['一年內合計不得超過十四日。事假期間不給工資']) |
| 17-Q2 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['一年內合計不得超過十四日。事假期間不給工資']) |
| 18-Q1 | M1 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['未住院者，一年內合計不得超過三十日', '住院者，二年內合計不得超過一年', '未超過三十日部分，工資折半發給']) |
| 18-Q1 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['未住院者，一年內合計不得超過三十日', '住院者，二年內合計不得超過一年', '未超過三十日部分，工資折半發給']) |
| 18-Q1 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['未住院者，一年內合計不得超過三十日', '住院者，二年內合計不得超過一年', '未超過三十日部分，工資折半發給']) |
| 18-Q1 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['未住院者，一年內合計不得超過三十日', '住院者，二年內合計不得超過一年', '未超過三十日部分，工資折半發給']) |
| 18-Q2 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 2/2 gold facts missed (['每次以不少於六個月為原則', '三十日以上未達六個月：以二次為限']) |
| 18-Q2 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 2/2 gold facts missed (['每次以不少於六個月為原則', '三十日以上未達六個月：以二次為限']) |
| 18-Q3 | M1 | 瑕疵 | Stage 1 Retrieval Failure: 2/2 gold facts missed (['自行排定請假返國期日', '雇主應予同意']) |
| 18-Q3 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 2/2 gold facts missed (['自行排定請假返國期日', '雇主應予同意']) |
| 18-Q3 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['雇主應予同意']) |
| 18-Q3 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['雇主應予同意']) |
| 18-Q4 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['得就其給付薪資金額之百分之一百五十，自當年度營利事業所得額減除']) |
| 18-Q4 | M4 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['得就其給付薪資金額之百分之一百五十，自當年度營利事業所得額減除']. |
| 18-Q5 | M1 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['有左列情形之一者，給予一至三日之特別休假', '有左列情事之一者，給予二至五日之特別休假', '有左列情事之一者，給予三至七日之特別休假']) |
| 18-Q5 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['有左列情形之一者，給予一至三日之特別休假', '有左列情事之一者，給予二至五日之特別休假', '有左列情事之一者，給予三至七日之特別休假']) |
| 18-Q5 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['有左列情形之一者，給予一至三日之特別休假', '有左列情事之一者，給予二至五日之特別休假', '有左列情事之一者，給予三至七日之特別休假']) |
| 18-Q5 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['有左列情形之一者，給予一至三日之特別休假', '有左列情事之一者，給予二至五日之特別休假', '有左列情事之一者，給予三至七日之特別休假']) |
| 26-Q5 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['自災害發生之當月一日起計算六個月']) |
| 26-Q5 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['自災害發生之當月一日起計算六個月']) |
| canary-P1 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['未記載相關規定']) |
| canary-P1 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['未記載相關規定']) |
| canary-P4 | M1 | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['未記載相關規定']) |
| canary-P4 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['未記載相關規定']) |
| 17-Q1 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['勞工結婚者給予婚假八日，工資照給']) |
| 17-Q1 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['勞工結婚者給予婚假八日，工資照給']) |
| 17-Q2 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['一年內合計不得超過十四日。事假期間不給工資']) |
| 17-Q2 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['一年內合計不得超過十四日。事假期間不給工資']) |
| 18-Q1 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['未住院者，一年內合計不得超過三十日', '住院者，二年內合計不得超過一年', '未超過三十日部分，工資折半發給']) |
| 18-Q1 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['未住院者，一年內合計不得超過三十日', '住院者，二年內合計不得超過一年', '未超過三十日部分，工資折半發給']) |
| 18-Q1 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['未住院者，一年內合計不得超過三十日', '住院者，二年內合計不得超過一年', '未超過三十日部分，工資折半發給']) |
| 18-Q2 | M1 | 瑕疵 | Stage 1 Retrieval Failure: 2/2 gold facts missed (['每次以不少於六個月為原則', '三十日以上未達六個月：以二次為限']) |
| 18-Q2 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 2/2 gold facts missed (['每次以不少於六個月為原則', '三十日以上未達六個月：以二次為限']) |
| 18-Q2 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 2/2 gold facts missed (['每次以不少於六個月為原則', '三十日以上未達六個月：以二次為限']) |
| 18-Q3 | M1 | 瑕疵 | Stage 1 Retrieval Failure: 2/2 gold facts missed (['自行排定請假返國期日', '雇主應予同意']) |
| 18-Q3 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 2/2 gold facts missed (['自行排定請假返國期日', '雇主應予同意']) |
| 18-Q3 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['雇主應予同意']) |
| 18-Q3 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['雇主應予同意']) |
| 18-Q4 | M3 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['得就其給付薪資金額之百分之一百五十，自當年度營利事業所得額減除']. |
| 18-Q5 | M1 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['有左列情形之一者，給予一至三日之特別休假', '有左列情事之一者，給予二至五日之特別休假', '有左列情事之一者，給予三至七日之特別休假']) |
| 18-Q5 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['有左列情形之一者，給予一至三日之特別休假', '有左列情事之一者，給予二至五日之特別休假', '有左列情事之一者，給予三至七日之特別休假']) |
| 18-Q5 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['有左列情形之一者，給予一至三日之特別休假', '有左列情事之一者，給予二至五日之特別休假', '有左列情事之一者，給予三至七日之特別休假']) |
| 18-Q5 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['有左列情形之一者，給予一至三日之特別休假', '有左列情事之一者，給予二至五日之特別休假', '有左列情事之一者，給予三至七日之特別休假']) |
| 26-Q5 | M1 | 瑕疵 | Stage 1 Retrieval Failure: 2/2 gold facts missed (['自災害發生之當月一日起計算六個月', '災後六個月期間內被保險人應負擔之保險費，由中央政府支應']) |
| 26-Q5 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['自災害發生之當月一日起計算六個月']) |
| 26-Q5 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['自災害發生之當月一日起計算六個月']) |
| canary-P1 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['未記載相關規定']) |
| canary-P1 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['未記載相關規定']) |
| canary-P4 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['未記載相關規定']) |
| 17-Q1 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['勞工結婚者給予婚假八日，工資照給']) |
| 17-Q1 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['勞工結婚者給予婚假八日，工資照給']) |
| 17-Q2 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['一年內合計不得超過十四日。事假期間不給工資']) |
| 17-Q2 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['一年內合計不得超過十四日。事假期間不給工資']) |
| 18-Q1 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['未住院者，一年內合計不得超過三十日', '住院者，二年內合計不得超過一年', '未超過三十日部分，工資折半發給']) |
| 18-Q1 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['未住院者，一年內合計不得超過三十日', '住院者，二年內合計不得超過一年', '未超過三十日部分，工資折半發給']) |
| 18-Q2 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 2/2 gold facts missed (['每次以不少於六個月為原則', '三十日以上未達六個月：以二次為限']) |
| 18-Q2 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 2/2 gold facts missed (['每次以不少於六個月為原則', '三十日以上未達六個月：以二次為限']) |
| 18-Q2 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 2/2 gold facts missed (['每次以不少於六個月為原則', '三十日以上未達六個月：以二次為限']) |
| 18-Q3 | M1 | 瑕疵 | Stage 1 Retrieval Failure: 2/2 gold facts missed (['自行排定請假返國期日', '雇主應予同意']) |
| 18-Q3 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 2/2 gold facts missed (['自行排定請假返國期日', '雇主應予同意']) |
| 18-Q3 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['雇主應予同意']) |
| 18-Q3 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['雇主應予同意']) |
| 18-Q4 | M4 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['得就其給付薪資金額之百分之一百五十，自當年度營利事業所得額減除']. |
| 18-Q5 | M1 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['有左列情形之一者，給予一至三日之特別休假', '有左列情事之一者，給予二至五日之特別休假', '有左列情事之一者，給予三至七日之特別休假']) |
| 18-Q5 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['有左列情形之一者，給予一至三日之特別休假', '有左列情事之一者，給予二至五日之特別休假', '有左列情事之一者，給予三至七日之特別休假']) |
| 18-Q5 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['有左列情形之一者，給予一至三日之特別休假', '有左列情事之一者，給予二至五日之特別休假', '有左列情事之一者，給予三至七日之特別休假']) |
| 18-Q5 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['有左列情形之一者，給予一至三日之特別休假', '有左列情事之一者，給予二至五日之特別休假', '有左列情事之一者，給予三至七日之特別休假']) |
| 26-Q5 | M1 | 瑕疵 | Stage 1 Retrieval Failure: 2/2 gold facts missed (['自災害發生之當月一日起計算六個月', '災後六個月期間內被保險人應負擔之保險費，由中央政府支應']) |
| 26-Q5 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 2/2 gold facts missed (['自災害發生之當月一日起計算六個月', '災後六個月期間內被保險人應負擔之保險費，由中央政府支應']) |
| 26-Q5 | M3 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['自災害發生之當月一日起計算六個月']) |
| 26-Q5 | M4 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['自災害發生之當月一日起計算六個月']) |