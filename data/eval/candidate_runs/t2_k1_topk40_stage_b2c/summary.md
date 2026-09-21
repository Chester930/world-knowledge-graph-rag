# RQ1 統一評測報告：Pareto 最優邊界與全生命週期成本矩陣

> 生成時間：2026-09-21T15:16:12.574376+00:00
> 基準圖譜：`236903cf-055a-40a8-8923-b9d06601f3b7` | 評測題數：7 題 | 每題重複：1 次

## 1. 核心四大代表方法 Pareto 表現矩陣

| 方法代號 | 代表架構 | 原子事實正確率 (Acc) | 必要事實召回率 (Rec) | 服務期 p50 延遲 (s) | 建庫膨脹比 | 千次查詢預估 (USD) |
|---|---|---|---|---|---|---|
| **K** | K | 48.8% | 48.8% | 50.55s | 25.77x | $0.1798 |

## 2. Context Quality 矩陣（維度I，純檢索品質，不受生成端干擾——報告57 §2）

| 方法代號 | Context Recall | SNR（信噪比） | Chain Completeness（僅跨文件題） |
|---|---|---|---|
| **K** | 67.9% | 3.6% | 50.0% (n=4) |

## 3. 場景梯度細分（Type-A ~ Type-E）表現

| 題號 | 場景分類 | K |
|---|---| --- |
| **57-AGGR11** | `Type-C` | 0% (0/1✓) |
| **57-AGGR13** | `Type-C` | 0% (0/1✓) |
| **57-AGGR14** | `Type-D` | 67% (0/1✓) |
| **57-AGGR15** | `Type-C` | 0% (0/1✓) |
| **57-AGGR16** | `Type-D` | 75% (0/1✓) |
| **57-AGGR17** | `Type-D` | 100% (1/1✓) |
| **57-AGGR19** | `Type-C` | 100% (1/1✓) |

## 4. 典型缺陷全鏈路血統歸因

| 題號 | 方法 | 錯誤診斷 | 歸因原因 |
|---|---|---|---|
| 57-AGGR11 | K | 瑕疵 | Stage 1 Retrieval Failure: 1/3 gold facts missed (['本辦法依勞工退休金條例（以下簡稱本條例）第三十五條第三項及第三十七條規定訂定之。']) |
| 57-AGGR13 | K | 瑕疵 | Stage 1 Retrieval Failure: 2/3 gold facts missed (['本辦法依就業服務法（以下簡稱本法）第三十四條第三項及第四十條第二項規定訂定之。', '前項第十七款之人數、比率及查核方式等事項，由中央主管機關定之。']) |
| 57-AGGR14 | K | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['從業人員人數逾十人者，應置就業服務專業人員至少三人，並自第十一人起，每逾十人應另增置就業服務專業人員一人。']. |
| 57-AGGR15 | K | 瑕疵 | Stage 1 Retrieval Failure: 2/2 gold facts missed (['本辦法依職業安全衛生法（以下簡稱本法）第二十三條第五項規定訂定之。', '前四項之事業單位規模、性質、安全衛生組織、人員、職責、管理、自動檢查、職業安全衛生管理系統建置及其他相關事項之辦法，由中央主管機關定之。']) |
| 57-AGGR16 | K | 瑕疵 | Stage 1 Retrieval Failure: 1/4 gold facts missed (['第二類事業：具中度風險者。']) |