# 18_抽取數值忠實性核對

對應 `docs/報告/20_抽取數值忠實性核對機制設計報告.md`；`docs/論文/03_系統設計與方法論.md` § 3.1.3。

## 起點

報告19 §10 的真實重跑驗證發現：同一份輸入文字，不同次真實LLM呼叫（`qwen2.5:7b`，`temperature=0.0`）得到不同結果——把「三至七日」錯抽成同文件另一條文的「一至三日」。查證後確認是 LLM 推論本身的批次大小依賴（非本專案 bug），據此設計數值忠實性核對機制（純字串比對，不需LLM）。

## 內容清單

| 檔案 | 文獻 | 來源 | 狀態 |
|---|---|---|---|
| `see-et-al-2017-pointer-generator.pdf` | See, Liu & Manning (2017), *Get To The Point: Summarization with Pointer-Generator Networks* | ACL Anthology [P17-1099](https://aclanthology.org/P17-1099/) | ✅ 🟢 已下載並精讀相關段落（2026-08-31）——pointer機制讓模型可直接從原文複製關鍵詞彙，佐證「複製自原文的內容比生成內容更可信」這個設計哲學；⚠️ 應用場景為摘要生成訓練架構，非本報告的事後核對機制，具體演算法不可直接套用 |

**未下載（部落格文章，非論文，不適用🟢/🟡分級）**：Horace He (2025-09-10)，*Defeating Nondeterminism in LLM Inference*，Thinking Machines Lab（Connectionism部落格）——https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/ 。核心主張：temperature=0不保證LLM推論決定性輸出，根因是批次大小依賴（batch-size dependence）而非取樣隨機性；徹底解決（batch-invariant kernels）需付出62-113%吞吐量開銷。作者為知名ML系統工程師（PyTorch核心貢獻者），文中附可重現GitHub實作與量化數據，非空泛主張，但屬部落格文章非同行評審出版品。

## 待辦

- [ ] 若後續需要更嚴謹的正式引用，可查證 Thinking Machines Lab 部落格內容是否有對應的後續正式論文發表
