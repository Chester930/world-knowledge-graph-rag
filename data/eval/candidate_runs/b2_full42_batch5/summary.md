# RQ1 統一評測報告：Pareto 最優邊界與全生命週期成本矩陣

> 生成時間：2026-09-28T10:40:19.544837+00:00
> 基準圖譜：`236903cf-055a-40a8-8923-b9d06601f3b7` | 評測題數：9 題 | 每題重複：1 次

## 1. 核心四大代表方法 Pareto 表現矩陣

| 方法代號 | 代表架構 | 原子事實正確率 (Acc) | 必要事實召回率 (Rec) | 服務期 p50 延遲 (s) | 建庫膨脹比 | 千次查詢預估 (USD) |
|---|---|---|---|---|---|---|
| **M1** | B0 | 63.0% | 63.0% | 96.13s | 1.53x | $0.1886 |
| **M2** | B1 | 70.4% | 70.4% | 96.28s | 2.33x | $0.1875 |
| **B2** | B2 | 70.4% | 70.4% | 108.91s | 2.33x | $0.1926 |

## 2. Context Quality 矩陣（維度I，純檢索品質，不受生成端干擾——報告57 §2）

| 方法代號 | Context Recall | SNR（信噪比） | Chain Completeness（僅跨文件題） |
|---|---|---|---|
| **M1** | 79.6% | 3.8% | 75.0% (n=4) |
| **M2** | 79.6% | 3.7% | 75.0% (n=4) |
| **B2** | 79.6% | 3.6% | 75.0% (n=4) |

## 3. 場景梯度細分（Type-A ~ Type-E）表現

| 題號 | 場景分類 | M1 | M2 | B2 |
|---|---| --- | --- | --- |
| **57-AGGR10** | `Type-D` | 67% (0/1✓) | 67% (0/1✓) | 67% (0/1✓) |
| **57-AGGR11** | `Type-C` | 33% (0/1✓) | 33% (0/1✓) | 33% (0/1✓) |
| **57-AGGR12** | `Type-D` | 100% (0/1✓) | 100% (0/1✓) | 100% (0/1✓) |
| **57-AGGR13** | `Type-C` | 33% (0/1✓) | 33% (0/1✓) | 33% (0/1✓) |
| **57-AGGR14** | `Type-D` | 100% (1/1✓) | 100% (1/1✓) | 100% (1/1✓) |
| **57-AGGR15** | `Type-C` | 50% (0/1✓) | 50% (0/1✓) | 50% (0/1✓) |
| **57-AGGR16** | `Type-D` | 100% (1/1✓) | 75% (0/1✓) | 75% (0/1✓) |
| **57-AGGR17** | `Type-D` | 33% (0/1✓) | 100% (1/1✓) | 100% (1/1✓) |
| **57-AGGR18** | `Type-C` | 50% (0/1✓) | 75% (0/1✓) | 75% (0/1✓) |

## 4. 典型缺陷全鏈路血統歸因

| 題號 | 方法 | 錯誤診斷 | 歸因原因 |
|---|---|---|---|
| 57-AGGR10 | M1 | 瑕疵 | Stage 1 Retrieval Failure: 1/3 gold facts missed (['第十八條津貼每月按最低工資百分之六十發給，最長以六個月為限。申請人為身心障礙者，最長發給一年。']) |
| 57-AGGR10 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 1/3 gold facts missed (['第十八條津貼每月按最低工資百分之六十發給，最長以六個月為限。申請人為身心障礙者，最長發給一年。']) |
| 57-AGGR10 | B2 | 瑕疵 | Stage 1 Retrieval Failure: 1/3 gold facts missed (['第十八條津貼每月按最低工資百分之六十發給，最長以六個月為限。申請人為身心障礙者，最長發給一年。']) |
| 57-AGGR11 | M1 | 瑕疵 | Stage 1 Retrieval Failure: 2/3 gold facts missed (['事業單位採行前項規定之年金保險者，應報請中央主管機關核准。', '年金保險之契約應由雇主擔任要保人，勞工為被保險人及受益人。事業單位以向一保險人投保為限。保險人之資格，由中央主管機關會同該保險業務之主管機關定之。']) |
| 57-AGGR11 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 1/3 gold facts missed (['年金保險之契約應由雇主擔任要保人，勞工為被保險人及受益人。事業單位以向一保險人投保為限。保險人之資格，由中央主管機關會同該保險業務之主管機關定之。']) |
| 57-AGGR11 | B2 | 瑕疵 | Stage 1 Retrieval Failure: 1/3 gold facts missed (['年金保險之契約應由雇主擔任要保人，勞工為被保險人及受益人。事業單位以向一保險人投保為限。保險人之資格，由中央主管機關會同該保險業務之主管機關定之。']) |
| 57-AGGR13 | M1 | 瑕疵 | Stage 1 Retrieval Failure: 1/3 gold facts missed (['前項第十七款之人數、比率及查核方式等事項，由中央主管機關定之。']) |
| 57-AGGR13 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 2/3 gold facts missed (['本辦法依就業服務法（以下簡稱本法）第三十四條第三項及第四十條第二項規定訂定之。', '前項第十七款之人數、比率及查核方式等事項，由中央主管機關定之。']) |
| 57-AGGR13 | B2 | 瑕疵 | Stage 1 Retrieval Failure: 2/3 gold facts missed (['本辦法依就業服務法（以下簡稱本法）第三十四條第三項及第四十條第二項規定訂定之。', '前項第十七款之人數、比率及查核方式等事項，由中央主管機關定之。']) |
| 57-AGGR15 | M1 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['前四項之事業單位規模、性質、安全衛生組織、人員、職責、管理、自動檢查、職業安全衛生管理系統建置及其他相關事項之辦法，由中央主管機關定之。']) |
| 57-AGGR15 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['前四項之事業單位規模、性質、安全衛生組織、人員、職責、管理、自動檢查、職業安全衛生管理系統建置及其他相關事項之辦法，由中央主管機關定之。']) |
| 57-AGGR15 | B2 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['前四項之事業單位規模、性質、安全衛生組織、人員、職責、管理、自動檢查、職業安全衛生管理系統建置及其他相關事項之辦法，由中央主管機關定之。']) |
| 57-AGGR16 | M2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['第一類事業之事業單位勞工人數在一百人以上者，應設直接隸屬雇主之專責一級管理單位。']. |
| 57-AGGR16 | B2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['第一類事業之事業單位勞工人數在一百人以上者，應設直接隸屬雇主之專責一級管理單位。']. |
| 57-AGGR17 | M1 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['二、第二類事業：具中度風險者。', '三、第三類事業：具低度風險者。']. |
| 57-AGGR18 | M1 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['職業災害勞工經醫療終止後，經公立醫療機構認定身心障礙不堪勝任工作。', '經公立醫療機構認定身心障礙不堪勝任工作。']. |
| 57-AGGR18 | M2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['職業災害勞工經醫療終止後，經公立醫療機構認定身心障礙不堪勝任工作。']. |
| 57-AGGR18 | B2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['職業災害勞工經醫療終止後，經公立醫療機構認定身心障礙不堪勝任工作。']. |