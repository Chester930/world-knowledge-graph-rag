# SVO 關聯性可行性驗證

這個資料夾是獨立的展示型子項目，不是主系統的功能測試。

目的不是證明整個 World Knowledge Graph RAG 系統已經完成，而是用一個最小閉環回答：

> 把文本提煉成 SVO 三元組後，這些關係是否能被原文證據支持，並且是否比單純回傳大段文字更容易驗證？

## 驗證邏輯

1. 準備小型文本資料集：`dataset.json`
2. 制定示範用正確三元組與來源句：`gold_triples.json`
3. 放入不同方法產生的三元組：`sample_predictions.json`
4. 用 `evaluator.py` 比對三元組是否正確、來源是否可追溯

這裡先不依賴 LLM 或 Neo4j。原因是這個子項目要先證明「驗證方法」本身成立：

- subject / rel_type / object 是否對得上示範用標準答案
- 每條三元組是否能回到支持它的原文句子
- 錯誤關係、過度推論、沒有來源的關係是否會被扣分

等這個閉環成立後，再把主系統的 SVO 輸出轉成同樣格式，就能直接拿來評估。

## 評估指標

- Precision：系統抽出的三元組中，有多少是真的
- Recall：標準答案中，有多少被系統抽到
- F1：Precision 與 Recall 的綜合
- Traceability：抽對的三元組中，有多少能回到正確來源句

## 執行方式

```bash
python -m experiments.svo_feasibility.evaluator
```

或執行測試：

```bash
python -m pytest experiments/svo_feasibility/test_evaluator.py
```

現場展示可直接照 `LIVE_DEMO.md` 的步驟執行。

## 簡報可用說法

我把 SVO 驗證拉成一個獨立子項目，因為我不是只想說系統「有抽三元組」，而是要證明三件事：

1. 三元組的主詞、關係、受詞是否正確
2. 這條關係是否真的被原文支持
3. 結構化後是否比單純回傳大段文字更容易檢查錯誤

這也是知識圖譜相對於一般 RAG 的關鍵：不是只把可能相關的文本交給 LLM，而是把文本中的關係先提煉出來，再要求每條關係能回到來源證據。

注意：目前 `gold_triples.json` 是示範用標準答案，由研究者根據小型樣本文本先制定，用來驗證 evaluator 與實驗格式。正式實驗才會擴大成人工標註或人工審核資料集。
