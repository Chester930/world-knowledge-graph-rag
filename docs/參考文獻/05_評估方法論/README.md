# 05_評估方法論

對應 `../../論文/02_文獻探討.md` § 2.5（評估方法論的橫向文獻回顧，2026-07-23 第二章重組前為 § 2.1.5）。

## 內容清單

| 檔案 | 文獻 | 來源 | 角色與摘要 |
|---|---|---|---|
| `yang-et-al-2018-hotpotqa.pdf` | Yang et al. (2018), *HotpotQA: A Dataset for Diverse, Explainable Multi-hop Question Answering*，EMNLP 2018 | [arXiv:1809.09600](https://arxiv.org/abs/1809.09600) | 多跳問答標準基準資料集，提供需跨多個文件進行推理之問答對，第五章實驗測試資料集選型依據。2026-08-20 完成全文下載。 |
| `es-et-al-2023-ragas.pdf` | Es et al. (2023/2024), *RAGAS: Automated Evaluation of Retrieval Augmented Generation*，EACL 2024 | [arXiv:2309.15217](https://arxiv.org/abs/2309.15217) | RAG 自動化無參考答案評估框架（忠實度 Faithfulness、答案相關性 Answer Relevance 等），第五章實驗評估指標框架基礎。2026-08-20 完成全文下載。 |
| `ru-et-al-2024-ragchecker.pdf` | Ru et al. (2024), *RAGChecker: A Fine-grained Framework for Diagnosing Retrieval-Augmented Generation* | [arXiv:2408.08067](https://arxiv.org/abs/2408.08067) | 分別對檢索模組與生成模組提出診斷指標，摘要明確指出「RAG 因模組化特性而難以評估」並以與人工判斷的相關性驗證指標——支持報告57「檢索品質與生成品質解耦評測」的動機。2026-09-21 下載；🟡 僅核對 arXiv 摘要頁（標題、作者、日期、核心主張），**未全文精讀**。 |
| `miller-2024-error-bars-for-evals.pdf` | Miller (2024), *Adding Error Bars to Evals: A Statistical Approach to Language Model Evaluations* | [arXiv:2411.00640](https://arxiv.org/abs/2411.00640) | 把評測題目視為題庫母體的樣本，提供計算標準誤、比較兩模型差異與**規劃評測實驗**的公式與建議。可作為報告57 §4.20「品質門檻式重複」與樣本量限制討論的統計基礎（該重複規則本身是自訂工程規則，沒有這篇文獻直接背書）。2026-09-21 下載；🟡 僅核對摘要頁，**未全文精讀**，尚未實際套用其公式。 |
