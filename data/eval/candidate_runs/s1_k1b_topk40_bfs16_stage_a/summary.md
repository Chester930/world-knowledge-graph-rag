# RQ1 統一評測報告：Pareto 最優邊界與全生命週期成本矩陣

> 生成時間：2026-09-23T16:39:16.468514+00:00
> 基準圖譜：`236903cf-055a-40a8-8923-b9d06601f3b7` | 評測題數：42 題 | 每題重複：1 次

## 1. 核心四大代表方法 Pareto 表現矩陣

| 方法代號 | 代表架構 | 原子事實正確率 (Acc) | 必要事實召回率 (Rec) | 服務期 p50 延遲 (s) | 建庫膨脹比 | 千次查詢預估 (USD) |
|---|---|---|---|---|---|---|
| **K** | K | 56.5% | 56.5% | 73.56s | 25.77x | $0.1822 |

## 2. Context Quality 矩陣（維度I，純檢索品質，不受生成端干擾——報告57 §2）

| 方法代號 | Context Recall | SNR（信噪比） | Chain Completeness（僅跨文件題） |
|---|---|---|---|
| **K** | 74.4% | 3.0% | 57.1% (n=14) |

## 3. 場景梯度細分（Type-A ~ Type-E）表現

| 題號 | 場景分類 | K |
|---|---| --- |
| **17-Q1** | `Type-A` | 100% (1/1✓) |
| **17-Q2** | `Type-A` | 100% (1/1✓) |
| **17-Q6** | `Type-B` | 0% (0/1✓) |
| **18-Q1** | `Type-B` | 100% (1/1✓) |
| **18-Q2** | `Type-B` | 100% (1/1✓) |
| **18-Q3** | `Type-A` | 100% (1/1✓) |
| **18-Q4** | `Type-B` | 0% (0/1✓) |
| **18-Q5** | `Type-B` | 100% (1/1✓) |
| **18-Q6** | `Type-A` | 100% (1/1✓) |
| **26-Q1** | `Type-B` | 100% (1/1✓) |
| **26-Q5** | `Type-C` | 100% (1/1✓) |
| **canary-P1** | `Type-E` | 0% (0/1✓) |
| **canary-P4** | `Type-E` | 0% (0/1✓) |
| **57-COREF1** | `Type-B` | 67% (0/1✓) |
| **57-COREF2** | `Type-A` | 100% (1/1✓) |
| **57-COREF3** | `Type-B` | 100% (1/1✓) |
| **57-DIST1** | `Type-B` | 75% (0/1✓) |
| **57-DIST2** | `Type-B` | 50% (0/1✓) |
| **57-CANARY1** | `Type-E` | 100% (1/1✓) |
| **57-CANARY2** | `Type-E` | 100% (1/1✓) |
| **57-AGGR1** | `Type-C` | 0% (0/1✓) |
| **57-AGGR2** | `Type-D` | 33% (0/1✓) |
| **57-CANARY3** | `Type-E` | 0% (0/1✓) |
| **57-AGGR3** | `Type-D` | 67% (0/1✓) |
| **57-AGGR4** | `Type-C` | 0% (0/1✓) |
| **57-CANARY4** | `Type-A` | 100% (1/1✓) |
| **57-CANARY5** | `Type-C` | 50% (0/1✓) |
| **57-AGGR5** | `Type-C` | 0% (0/1✓) |
| **57-AGGR6** | `Type-C` | 75% (0/1✓) |
| **57-AGGR7** | `Type-C` | 33% (0/1✓) |
| **57-AGGR8** | `Type-D` | 25% (0/1✓) |
| **57-AGGR9** | `Type-C` | 0% (0/1✓) |
| **57-AGGR10** | `Type-D` | 0% (0/1✓) |
| **57-AGGR11** | `Type-C` | 0% (0/1✓) |
| **57-AGGR12** | `Type-D` | 100% (1/1✓) |
| **57-AGGR13** | `Type-C` | 33% (0/1✓) |
| **57-AGGR14** | `Type-D` | 67% (0/1✓) |
| **57-AGGR15** | `Type-C` | 0% (0/1✓) |
| **57-AGGR16** | `Type-D` | 50% (0/1✓) |
| **57-AGGR17** | `Type-D` | 100% (1/1✓) |
| **57-AGGR18** | `Type-C` | 100% (1/1✓) |
| **57-AGGR19** | `Type-C` | 50% (0/1✓) |

## 4. 典型缺陷全鏈路血統歸因

| 題號 | 方法 | 錯誤診斷 | 歸因原因 |
|---|---|---|---|
| 17-Q6 | K | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['搶救重大災害，冒險犯難，達三日以上，獲記大功以上之獎勵者']) |
| 18-Q4 | K | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['得就其給付薪資金額之百分之一百五十，自當年度營利事業所得額減除']. |
| canary-P1 | K | 瑕疵 | Stage 1 Retrieval Failure: 1/1 gold facts missed (['未記載相關規定']) |
| 57-COREF1 | K | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['受僱者因突發情形不及於一日前提出者，得委託他人代辦申請手續']. |
| 57-DIST1 | K | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['給予二至五日之特別休假']. |
| 57-DIST2 | K | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['當選直轄市、縣（市）級模範警察或好人好事代表者', '給予一至三日之特別休假']. |
| 57-AGGR1 | K | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['勞工健康保護規則附表一（特別危害健康作業）之項次一為高溫作業勞工作息時間標準所稱之高溫作業。']) |
| 57-AGGR2 | K | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['勞工健康保護規則附表一（特別危害健康作業）之項次一為高溫作業勞工作息時間標準所稱之高溫作業。', '附表一之項次九為製造、處置或使用特定化學物質或其重量比（苯為體積比）超過百分之一之混合物之作業', '雇主使勞工從事特別危害健康作業，應每年或於變更其作業時，依第十六條附表十所定項目，實施特殊健康檢查。']) |
| 57-CANARY3 | K | 瑕疵 | Stage 1 Retrieval Failure: 2/2 gold facts missed (['本標準依職業安全衛生法第六條及第十九條規定訂定之。', '特別危害健康作業：指符合附表一之物理性及化學性危害之作業。']) |
| 57-AGGR3 | K | 瑕疵 | Stage 1 Retrieval Failure: 2/3 gold facts missed (['普通傷病假一年內未超過三十日部分，工資折半發給，其領有勞工保險普通傷病給付未達工資半數者，由雇主補足之。', '前項女工受僱工作在六個月以上者，停止工作期間工資照給；未滿六個月者減半發給。']) |
| 57-AGGR4 | K | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['職業災害未認定前，勞工得依勞工請假規則第四條規定，先請普通傷病假，普通傷病假期滿，雇主應予留職停薪，如認定結果為職業災害，再以公傷病假處理。', '普通傷病假一年內未超過三十日部分，工資折半發給，其領有勞工保險普通傷病給付未達工資半數者，由雇主補足之。', '勞工在醫療中不能工作時，雇主應按其原領工資數額予以補償。']. |
| 57-CANARY5 | K | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['本法施行前依法應為所屬勞工辦理參加勞工保險而未辦理之雇主，其勞工發生職業災害事故致死亡或失能，經依本法施行前職業災害勞工保護法第六條規定發給補助者，處以補助金額相同額度之罰鍰。']) |
| 57-AGGR5 | K | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['本辦法依勞工職業災害保險及保護法（以下簡稱本法）第六十九條第二項規定訂定之。', '前二條及前項補助或津貼之條件、基準、申請與核發程序及其他應遵行事項之辦法，由中央主管機關定之。', '本辦法所定輔助設施補助，以每一職業災害勞工同一職業災害事故，補助總金額新臺幣二十萬元為限。']) |
| 57-AGGR6 | K | 瑕疵 | Stage 1 Retrieval Failure: 1/4 gold facts missed (['雇主依第二十三條第二款，或勞工依第二十四條第一款規定終止勞動契約者，雇主應依勞動基準法之規定，發給勞工退休金。']) |
| 57-AGGR7 | K | 瑕疵 | Stage 1 Retrieval Failure: 1/3 gold facts missed (['雇主依本法第二十四條第二項規定辦理訓練，並申請訓練費用補助者，最低開班人數應達五人，且訓練時數不得低於八十小時。']) |
| 57-AGGR8 | K | 瑕疵 | Stage 1 Retrieval Failure: 1/4 gold facts missed (['雇主依前項規定辦理職業訓練，中央主管機關得予訓練費用補助。']) |
| 57-AGGR9 | K | 瑕疵 | Stage 1 Retrieval Failure: 1/3 gold facts missed (['本辦法依就業服務法（以下簡稱本法）第二十三條第二項及第二十四條第四項規定訂定之。']) |
| 57-AGGR10 | K | 瑕疵 | Stage 1 Retrieval Failure: 3/3 gold facts missed (['第六條補助金，每人每次得發給新臺幣五百元。但情形特殊者，得核實發給，每次不得超過新臺幣一千二百五十元。', '第十條津貼發給基準，按中央主管機關公告之每小時最低工資核給，且一個月合計不超過月最低工資，最長六個月。', '第十八條津貼每月按最低工資百分之六十發給，最長以六個月為限。申請人為身心障礙者，最長發給一年。']) |
| 57-AGGR11 | K | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['本辦法依勞工退休金條例（以下簡稱本條例）第三十五條第三項及第三十七條規定訂定之。', '事業單位採行前項規定之年金保險者，應報請中央主管機關核准。', '年金保險之契約應由雇主擔任要保人，勞工為被保險人及受益人。事業單位以向一保險人投保為限。保險人之資格，由中央主管機關會同該保險業務之主管機關定之。']. |
| 57-AGGR13 | K | 瑕疵 | Stage 1 Retrieval Failure: 2/3 gold facts missed (['本辦法依就業服務法（以下簡稱本法）第三十四條第三項及第四十條第二項規定訂定之。', '前項第十七款之人數、比率及查核方式等事項，由中央主管機關定之。']) |
| 57-AGGR14 | K | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['從業人員人數逾十人者，應置就業服務專業人員至少三人，並自第十一人起，每逾十人應另增置就業服務專業人員一人。']. |
| 57-AGGR15 | K | 瑕疵 | Stage 1 Retrieval Failure: 2/2 gold facts missed (['本辦法依職業安全衛生法（以下簡稱本法）第二十三條第五項規定訂定之。', '前四項之事業單位規模、性質、安全衛生組織、人員、職責、管理、自動檢查、職業安全衛生管理系統建置及其他相關事項之辦法，由中央主管機關定之。']) |
| 57-AGGR16 | K | 瑕疵 | Stage 1 Retrieval Failure: 1/4 gold facts missed (['第二類事業：具中度風險者。']) |
| 57-AGGR19 | K | 瑕疵 | Stage 1 Retrieval Failure: 2/4 gold facts missed (['職業災害勞工依第二十四條第一款規定終止勞動契約時，準用勞動基準法規定預告雇主。', '職業災害勞工依前項第一款規定終止勞動契約時，準用勞動基準法規定預告雇主。']) |