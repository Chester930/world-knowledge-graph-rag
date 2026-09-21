# RQ1 統一評測報告：Pareto 最優邊界與全生命週期成本矩陣

> 生成時間：2026-09-16T11:54:10.456220+00:00
> 基準圖譜：`236903cf-055a-40a8-8923-b9d06601f3b7` | 評測題數：3 題 | 每題重複：1 次

## 1. 核心四大代表方法 Pareto 表現矩陣

| 方法代號 | 代表架構 | 原子事實正確率 (Acc) | 必要事實召回率 (Rec) | 服務期 p50 延遲 (s) | 建庫膨脹比 | 千次查詢預估 (USD) |
|---|---|---|---|---|---|---|
| **K** | K | 0.0% | 0.0% | 0.72s | 25.77x | $0.0000 |

## 2. Context Quality 矩陣（維度I，純檢索品質，不受生成端干擾——報告57 §2）

| 方法代號 | Context Recall | SNR（信噪比） | Chain Completeness（僅跨文件題） |
|---|---|---|---|
| **K** | 0.0% | 0.0% | 0.0% (n=2) |

## 3. 場景梯度細分（Type-A ~ Type-E）表現

| 題號 | 場景分類 | K |
|---|---| --- |
| **57-AGGR3** | `Type-D` | 0% (0/1✓) |
| **57-AGGR4** | `Type-C` | 0% (0/1✓) |
| **57-CANARY4** | `Type-A` | 0% (0/1✓) |

## 4. 典型缺陷全鏈路血統歸因

| 題號 | 方法 | 錯誤診斷 | 歸因原因 |
|---|---|---|---|
| 57-AGGR3 | K | 瑕疵 | Harness Exception: HTTPStatusError: Client error '404 Not Found' for url 'http://localhost:11434/api/embeddings'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404 |
| 57-AGGR4 | K | 瑕疵 | Harness Exception: HTTPStatusError: Client error '404 Not Found' for url 'http://localhost:11434/api/embeddings'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404 |
| 57-CANARY4 | K | 瑕疵 | Harness Exception: HTTPStatusError: Client error '404 Not Found' for url 'http://localhost:11434/api/embeddings'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404 |