# RQ1 統一評測報告：Pareto 最優邊界與全生命週期成本矩陣

> 生成時間：2026-09-25T05:14:19.140532+00:00
> 基準圖譜：`236903cf-055a-40a8-8923-b9d06601f3b7` | 評測題數：25 題 | 每題重複：1 次

## 1. 核心四大代表方法 Pareto 表現矩陣

| 方法代號 | 代表架構 | 原子事實正確率 (Acc) | 必要事實召回率 (Rec) | 服務期 p50 延遲 (s) | 建庫膨脹比 | 千次查詢預估 (USD) |
|---|---|---|---|---|---|---|
| **M2** | B1 | 57.0% | 57.0% | 24.85s | 2.33x | $0.1899 |

## 2. Context Quality 矩陣（維度I，純檢索品質，不受生成端干擾——報告57 §2）

| 方法代號 | Context Recall | SNR（信噪比） | Chain Completeness（僅跨文件題） |
|---|---|---|---|
| **M2** | 80.0% | 3.4% | 69.4% (n=12) |

## 3. 場景梯度細分（Type-A ~ Type-E）表現

| 題號 | 場景分類 | M2 |
|---|---| --- |
| **18-Q2** | `Type-B` | 100% (1/1✓) |
| **18-Q4** | `Type-B` | 100% (1/1✓) |
| **18-Q5** | `Type-B` | 0% (0/1✓) |
| **57-COREF1** | `Type-B` | 67% (0/1✓) |
| **57-DIST1** | `Type-B` | 75% (0/1✓) |
| **57-CANARY2** | `Type-E` | 100% (1/1✓) |
| **57-AGGR1** | `Type-C` | 50% (0/1✓) |
| **57-AGGR2** | `Type-D` | 0% (0/1✓) |
| **57-CANARY3** | `Type-E` | 0% (0/1✓) |
| **57-AGGR3** | `Type-D` | 33% (0/1✓) |
| **57-AGGR4** | `Type-C` | 33% (0/1✓) |
| **57-CANARY4** | `Type-A` | 100% (1/1✓) |
| **57-CANARY5** | `Type-C` | 50% (0/1✓) |
| **57-AGGR5** | `Type-C` | 67% (0/1✓) |
| **57-AGGR7** | `Type-C` | 67% (0/1✓) |
| **57-AGGR8** | `Type-D` | 25% (0/1✓) |
| **57-AGGR9** | `Type-C` | 33% (0/1✓) |
| **57-AGGR10** | `Type-D` | 67% (0/1✓) |
| **57-AGGR11** | `Type-C` | 33% (0/1✓) |
| **57-AGGR12** | `Type-D` | 100% (0/1✓) |
| **57-AGGR13** | `Type-C` | 0% (0/1✓) |
| **57-AGGR15** | `Type-C` | 50% (0/1✓) |
| **57-AGGR16** | `Type-D` | 100% (1/1✓) |
| **57-AGGR17** | `Type-D` | 100% (1/1✓) |
| **57-AGGR18** | `Type-C` | 75% (0/1✓) |

## 4. 典型缺陷全鏈路血統歸因

| 題號 | 方法 | 錯誤診斷 | 歸因原因 |
|---|---|---|---|
| 18-Q5 | M2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['有左列情形之一者，給予一至三日之特別休假', '有左列情事之一者，給予二至五日之特別休假', '有左列情事之一者，給予三至七日之特別休假']. |
| 57-COREF1 | M2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['因子女生病、停托、停課，受僱者須親自照顧時，得於一日前提出']. |
| 57-DIST1 | M2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['給予一至三日之特別休假']. |
| 57-AGGR1 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['勞工健康保護規則附表一（特別危害健康作業）之項次一為高溫作業勞工作息時間標準所稱之高溫作業。']) |
| 57-AGGR2 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 2/3 gold facts missed (['勞工健康保護規則附表一（特別危害健康作業）之項次一為高溫作業勞工作息時間標準所稱之高溫作業。', '附表一之項次九為製造、處置或使用特定化學物質或其重量比（苯為體積比）超過百分之一之混合物之作業']) |
| 57-CANARY3 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['特別危害健康作業：指符合附表一之物理性及化學性危害之作業。']) |
| 57-AGGR3 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 1/3 gold facts missed (['前項女工受僱工作在六個月以上者，停止工作期間工資照給；未滿六個月者減半發給。']) |
| 57-AGGR4 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 2/3 gold facts missed (['普通傷病假一年內未超過三十日部分，工資折半發給，其領有勞工保險普通傷病給付未達工資半數者，由雇主補足之。', '勞工在醫療中不能工作時，雇主應按其原領工資數額予以補償。']) |
| 57-CANARY5 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['本法施行前依法應為所屬勞工辦理參加勞工保險而未辦理之雇主，其勞工發生職業災害事故致死亡或失能，經依本法施行前職業災害勞工保護法第六條規定發給補助者，處以補助金額相同額度之罰鍰。']) |
| 57-AGGR5 | M2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['前二條及前項補助或津貼之條件、基準、申請與核發程序及其他應遵行事項之辦法，由中央主管機關定之。', '本辦法所定輔助設施補助，以每一職業災害勞工同一職業災害事故，補助總金額新臺幣二十萬元為限。']. |
| 57-AGGR7 | M2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['本辦法依中高齡者及高齡者就業促進法（以下簡稱本法）第二十七條規定訂定之。']. |
| 57-AGGR8 | M2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['主管機關為協助中高齡者及高齡者創業或與青年共同創業，得提供創業諮詢輔導、創業研習課程及創業貸款利息補貼等措施。', '主管機關對於失業之中高齡者及高齡者，應協助其就業，提供相關就業協助措施，並得發給相關津貼、補助或獎助。', '前三條所定補助、利息補貼、津貼或獎助之申請資格條件、項目、方式、期間、廢止、經費來源及其他相關事項之辦法，由中央主管機關定之。']. |
| 57-AGGR9 | M2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['前項利息補貼、津貼與補助金之申請資格條件、項目、方式、期間、經費來源及其他應遵行事項之辦法，由中央主管機關定之。', '第一項津貼或補助金之申請資格、金額、期間、經費來源及其他相關事項之辦法，由主管機關定之。']. |
| 57-AGGR10 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 1/3 gold facts missed (['第十八條津貼每月按最低工資百分之六十發給，最長以六個月為限。申請人為身心障礙者，最長發給一年。']) |
| 57-AGGR11 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 1/3 gold facts missed (['年金保險之契約應由雇主擔任要保人，勞工為被保險人及受益人。事業單位以向一保險人投保為限。保險人之資格，由中央主管機關會同該保險業務之主管機關定之。']) |
| 57-AGGR13 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 2/3 gold facts missed (['本辦法依就業服務法（以下簡稱本法）第三十四條第三項及第四十條第二項規定訂定之。', '前項第十七款之人數、比率及查核方式等事項，由中央主管機關定之。']) |
| 57-AGGR15 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['前四項之事業單位規模、性質、安全衛生組織、人員、職責、管理、自動檢查、職業安全衛生管理系統建置及其他相關事項之辦法，由中央主管機關定之。']) |
| 57-AGGR18 | M2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['職業災害勞工經醫療終止後，經公立醫療機構認定身心障礙不堪勝任工作。']. |