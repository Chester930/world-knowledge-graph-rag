# RQ1 統一評測報告：Pareto 最優邊界與全生命週期成本矩陣

> 生成時間：2026-09-28T09:15:35.136505+00:00
> 基準圖譜：`236903cf-055a-40a8-8923-b9d06601f3b7` | 評測題數：9 題 | 每題重複：1 次

## 1. 核心四大代表方法 Pareto 表現矩陣

| 方法代號 | 代表架構 | 原子事實正確率 (Acc) | 必要事實召回率 (Rec) | 服務期 p50 延遲 (s) | 建庫膨脹比 | 千次查詢預估 (USD) |
|---|---|---|---|---|---|---|
| **M1** | B0 | 38.0% | 38.0% | 195.05s | 1.53x | $0.1632 |
| **M2** | B1 | 46.3% | 46.3% | 123.12s | 2.33x | $0.1733 |
| **B2** | B2 | 42.6% | 42.6% | 211.18s | 2.33x | $0.1880 |

## 2. Context Quality 矩陣（維度I，純檢索品質，不受生成端干擾——報告57 §2）

| 方法代號 | Context Recall | SNR（信噪比） | Chain Completeness（僅跨文件題） |
|---|---|---|---|
| **M1** | 68.5% | 3.9% | 63.9% (n=6) |
| **M2** | 68.5% | 3.8% | 63.9% (n=6) |
| **B2** | 64.8% | 2.8% | 58.3% (n=6) |

## 3. 場景梯度細分（Type-A ~ Type-E）表現

| 題號 | 場景分類 | M1 | M2 | B2 |
|---|---| --- | --- | --- |
| **57-AGGR3** | `Type-D` | 67% (0/1✓) | 67% (0/1✓) | 67% (0/1✓) |
| **57-AGGR4** | `Type-C` | 33% (0/1✓) | 33% (0/1✓) | 0% (0/1✓) |
| **57-CANARY4** | `Type-A` | 100% (1/1✓) | 100% (1/1✓) | 100% (1/1✓) |
| **57-CANARY5** | `Type-C` | 50% (0/1✓) | 50% (0/1✓) | 50% (0/1✓) |
| **57-AGGR5** | `Type-C` | 33% (0/1✓) | 67% (0/1✓) | 67% (0/1✓) |
| **57-AGGR6** | `Type-C` | 0% (0/1✓) | 0% (0/1✓) | 0% (0/1✓) |
| **57-AGGR7** | `Type-C` | 0% (0/1✓) | 67% (0/1✓) | 67% (0/1✓) |
| **57-AGGR8** | `Type-D` | 25% (0/1✓) | 0% (0/1✓) | 0% (0/1✓) |
| **57-AGGR9** | `Type-C` | 33% (0/1✓) | 33% (0/1✓) | 33% (0/1✓) |

## 4. 典型缺陷全鏈路血統歸因

| 題號 | 方法 | 錯誤診斷 | 歸因原因 |
|---|---|---|---|
| 57-AGGR3 | M1 | 瑕疵 | Stage 1 Retrieval Failure: 1/3 gold facts missed (['前項女工受僱工作在六個月以上者，停止工作期間工資照給；未滿六個月者減半發給。']) |
| 57-AGGR3 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 1/3 gold facts missed (['前項女工受僱工作在六個月以上者，停止工作期間工資照給；未滿六個月者減半發給。']) |
| 57-AGGR3 | B2 | 瑕疵 | Stage 1 Retrieval Failure: 1/3 gold facts missed (['前項女工受僱工作在六個月以上者，停止工作期間工資照給；未滿六個月者減半發給。']) |
| 57-AGGR4 | M1 | 瑕疵 | Stage 1 Retrieval Failure: 2/3 gold facts missed (['普通傷病假一年內未超過三十日部分，工資折半發給，其領有勞工保險普通傷病給付未達工資半數者，由雇主補足之。', '勞工在醫療中不能工作時，雇主應按其原領工資數額予以補償。']) |
| 57-AGGR4 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 2/3 gold facts missed (['普通傷病假一年內未超過三十日部分，工資折半發給，其領有勞工保險普通傷病給付未達工資半數者，由雇主補足之。', '勞工在醫療中不能工作時，雇主應按其原領工資數額予以補償。']) |
| 57-AGGR4 | B2 | 瑕疵 | Harness Timeout after 300.0s |
| 57-CANARY5 | M1 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['本法施行前依法應為所屬勞工辦理參加勞工保險而未辦理之雇主，其勞工發生職業災害事故致死亡或失能，經依本法施行前職業災害勞工保護法第六條規定發給補助者，處以補助金額相同額度之罰鍰。']) |
| 57-CANARY5 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['本法施行前依法應為所屬勞工辦理參加勞工保險而未辦理之雇主，其勞工發生職業災害事故致死亡或失能，經依本法施行前職業災害勞工保護法第六條規定發給補助者，處以補助金額相同額度之罰鍰。']) |
| 57-CANARY5 | B2 | 瑕疵 | Stage 1 Retrieval Failure: 1/2 gold facts missed (['本法施行前依法應為所屬勞工辦理參加勞工保險而未辦理之雇主，其勞工發生職業災害事故致死亡或失能，經依本法施行前職業災害勞工保護法第六條規定發給補助者，處以補助金額相同額度之罰鍰。']) |
| 57-AGGR5 | M1 | 瑕疵 | Stage 1 Retrieval Failure: 1/3 gold facts missed (['本辦法所定輔助設施補助，以每一職業災害勞工同一職業災害事故，補助總金額新臺幣二十萬元為限。']) |
| 57-AGGR5 | M2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['前二條及前項補助或津貼之條件、基準、申請與核發程序及其他應遵行事項之辦法，由中央主管機關定之。']. |
| 57-AGGR5 | B2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['前二條及前項補助或津貼之條件、基準、申請與核發程序及其他應遵行事項之辦法，由中央主管機關定之。']. |
| 57-AGGR6 | M1 | 瑕疵 | Harness Timeout after 300.0s |
| 57-AGGR6 | M2 | 瑕疵 | Harness Timeout after 300.0s |
| 57-AGGR6 | B2 | 瑕疵 | Harness Timeout after 300.0s |
| 57-AGGR7 | M1 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['雇主依前項規定辦理職業訓練，中央主管機關得予訓練費用補助。', '本辦法依中高齡者及高齡者就業促進法（以下簡稱本法）第二十七條規定訂定之。', '雇主依本法第二十四條第二項規定辦理訓練，並申請訓練費用補助者，最低開班人數應達五人，且訓練時數不得低於八十小時。']. |
| 57-AGGR7 | M2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['雇主依前項規定辦理職業訓練，中央主管機關得予訓練費用補助。']. |
| 57-AGGR7 | B2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['雇主依前項規定辦理職業訓練，中央主管機關得予訓練費用補助。']. |
| 57-AGGR8 | M1 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['主管機關為協助中高齡者及高齡者創業或與青年共同創業，得提供創業諮詢輔導、創業研習課程及創業貸款利息補貼等措施。', '主管機關對於失業之中高齡者及高齡者，應協助其就業，提供相關就業協助措施，並得發給相關津貼、補助或獎助。', '前三條所定補助、利息補貼、津貼或獎助之申請資格條件、項目、方式、期間、廢止、經費來源及其他相關事項之辦法，由中央主管機關定之。']. |
| 57-AGGR8 | M2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['雇主依前項規定辦理職業訓練，中央主管機關得予訓練費用補助。', '主管機關為協助中高齡者及高齡者創業或與青年共同創業，得提供創業諮詢輔導、創業研習課程及創業貸款利息補貼等措施。', '主管機關對於失業之中高齡者及高齡者，應協助其就業，提供相關就業協助措施，並得發給相關津貼、補助或獎助。', '前三條所定補助、利息補貼、津貼或獎助之申請資格條件、項目、方式、期間、廢止、經費來源及其他相關事項之辦法，由中央主管機關定之。']. |
| 57-AGGR8 | B2 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['雇主依前項規定辦理職業訓練，中央主管機關得予訓練費用補助。', '主管機關為協助中高齡者及高齡者創業或與青年共同創業，得提供創業諮詢輔導、創業研習課程及創業貸款利息補貼等措施。', '主管機關對於失業之中高齡者及高齡者，應協助其就業，提供相關就業協助措施，並得發給相關津貼、補助或獎助。', '前三條所定補助、利息補貼、津貼或獎助之申請資格條件、項目、方式、期間、廢止、經費來源及其他相關事項之辦法，由中央主管機關定之。']. |
| 57-AGGR9 | M1 | 瑕疵 | Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): Facts were present in prompt context, but LLM omitted or smoothed ['前項利息補貼、津貼與補助金之申請資格條件、項目、方式、期間、經費來源及其他應遵行事項之辦法，由中央主管機關定之。', '第一項津貼或補助金之申請資格、金額、期間、經費來源及其他相關事項之辦法，由主管機關定之。']. |
| 57-AGGR9 | M2 | 瑕疵 | Stage 1 Retrieval Failure: 1/3 gold facts missed (['第一項津貼或補助金之申請資格、金額、期間、經費來源及其他相關事項之辦法，由主管機關定之。']) |
| 57-AGGR9 | B2 | 瑕疵 | Stage 1 Retrieval Failure: 1/3 gold facts missed (['第一項津貼或補助金之申請資格、金額、期間、經費來源及其他相關事項之辦法，由主管機關定之。']) |