# RQ1 統一評測報告：Pareto 最優邊界與全生命週期成本矩陣

> 生成時間：2026-09-21T14:35:58.558613+00:00
> 基準圖譜：`236903cf-055a-40a8-8923-b9d06601f3b7` | 評測題數：8 題 | 每題重複：1 次

## 1. 核心四大代表方法 Pareto 表現矩陣

| 方法代號 | 代表架構 | 原子事實正確率 (Acc) | 必要事實召回率 (Rec) | 服務期 p50 延遲 (s) | 建庫膨脹比 | 千次查詢預估 (USD) |
|---|---|---|---|---|---|---|
| **K** | K | 43.7% | 43.7% | 182.64s | 25.77x | $0.4211 |

## 2. Context Quality 矩陣（維度I，純檢索品質，不受生成端干擾——報告57 §2）

| 方法代號 | Context Recall | SNR（信噪比） | Chain Completeness（僅跨文件題） |
|---|---|---|---|
| **K** | 60.4% | 2.2% | 40.0% (n=5) |

## 3. 場景梯度細分（Type-A ~ Type-E）表現

| 題號 | 場景分類 | K |
|---|---| --- |
| **57-CANARY1** | `Type-E` | 100% (1/1✓) |
| **57-CANARY2** | `Type-E` | 0% (0/1✓) |
| **57-AGGR1** | `Type-C` | 50% (0/1✓) |
| **57-AGGR2** | `Type-D` | 33% (0/1✓) |
| **57-CANARY3** | `Type-E` | 0% (0/1✓) |
| **57-AGGR3** | `Type-D` | 33% (0/1✓) |
| **57-AGGR4** | `Type-C` | 33% (0/1✓) |
| **57-CANARY4** | `Type-A` | 100% (1/1✓) |

## 4. 典型缺陷全鏈路血統歸因

| 題號 | 方法 | 錯誤診斷 | 歸因原因 |
|---|---|---|---|
| 57-CANARY2 | K | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['休假期間遇有緊急事故，得隨時令其銷假，並保留其假期或酌發不休假獎金']. |
| 57-AGGR1 | K | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['勞工健康保護規則附表一（特別危害健康作業）之項次一為高溫作業勞工作息時間標準所稱之高溫作業。']) |
| 57-AGGR2 | K | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['勞工健康保護規則附表一（特別危害健康作業）之項次一為高溫作業勞工作息時間標準所稱之高溫作業。', '附表一之項次九為製造、處置或使用特定化學物質或其重量比（苯為體積比）超過百分之一之混合物之作業', '雇主使勞工從事特別危害健康作業，應每年或於變更其作業時，依第十六條附表十所定項目，實施特殊健康檢查。']) |
| 57-CANARY3 | K | 瑕疵 | Stage 1 Retrieval Failure: 2/2 gold facts missed (['本標準依職業安全衛生法第六條及第十九條規定訂定之。', '特別危害健康作業：指符合附表一之物理性及化學性危害之作業。']) |
| 57-AGGR3 | K | 瑕疵 | Stage 1 Retrieval Failure: 2/3 gold facts missed (['普通傷病假一年內未超過三十日部分，工資折半發給，其領有勞工保險普通傷病給付未達工資半數者，由雇主補足之。', '前項女工受僱工作在六個月以上者，停止工作期間工資照給；未滿六個月者減半發給。']) |
| 57-AGGR4 | K | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['普通傷病假一年內未超過三十日部分，工資折半發給，其領有勞工保險普通傷病給付未達工資半數者，由雇主補足之。', '勞工在醫療中不能工作時，雇主應按其原領工資數額予以補償。']. |