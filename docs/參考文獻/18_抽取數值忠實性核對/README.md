# 18_抽取數值忠實性核對

對應 `docs/報告/20_抽取數值忠實性核對機制設計報告.md`、`docs/報告/25_擴大版新舊KG問答品質比對報告.md` §4 發現3；`docs/論文/03_系統設計與方法論.md` § 3.1.3／§ 3.1.4。

## 起點

報告19 §10 的真實重跑驗證發現：同一份輸入文字，不同次真實LLM呼叫（`qwen2.5:7b`，`temperature=0.0`）得到不同結果——把「三至七日」錯抽成同文件另一條文的「一至三日」。查證後確認是 LLM 推論本身的批次大小依賴（非本專案 bug），據此設計數值忠實性核對機制（純字串比對，不需LLM）。

**2026-09-03 擴充（報告25 §4 發現3）**：字詞層級核對攔不下「數字/謂語逐字正確、但綁到錯的列舉子句」——N0070020 §3「每增加一種型式加收四千元」被抽成「八千元」、N0030018 §2「未滿三十日：於五日前提出」被抽成主詞「三十日以上」。因為錯誤數字都確實逐字出現在同一 chunk 的另一個子句。據此把核對從字詞層級擴充到子句層級綁定（`_quantity_mis_bound_to_clause()`，三重條件、含誤殺防線）。

## 內容清單

| 檔案 | 文獻 | 來源 | 狀態 |
|---|---|---|---|
| `see-et-al-2017-pointer-generator.pdf` | See, Liu & Manning (2017), *Get To The Point: Summarization with Pointer-Generator Networks* | ACL Anthology [P17-1099](https://aclanthology.org/P17-1099/) | ✅ 🟢 已下載並精讀相關段落（2026-08-31）——pointer機制讓模型可直接從原文複製關鍵詞彙，佐證「複製自原文的內容比生成內容更可信」這個設計哲學；⚠️ 應用場景為摘要生成訓練架構，非本報告的事後核對機制，具體演算法不可直接套用 |
| `supervised-rationale-verification-2024.pdf` | Li, Miao, Zhou, Xu, Ren & Qian (2024), *Enhancing Relation Extraction via Supervised Rationale Verification and Feedback* | arXiv [2412.07289](https://arxiv.org/abs/2412.07289)（AAAI 2025） | ✅ 🟡 已下載全文精讀（2026-09-03）——驗「rationale」（LLM 為何這樣抽）而非只驗三元組；doc-level Algorithm 2「逐三元組 verify → retain/discard」是本專案「逐三元組事後篩選」的精神先例。⚠️ 主體是訓練式（BERT-like rationale supervisor + 對比學習 + causal intervention 收集偏誤/無偏誤 rationale），需標註資料與訓練，本專案 OpenIE 式無固定關係詞彙、無訓練資料，不直接套用 |
| `atomic-propositions-2026-propositioner.pdf` | Pommeret et al. (2026), *Propositioner: Atomic Proposition Decomposition for ...* | arXiv [2604.02866](https://arxiv.org/abs/2604.02866) | ✅ 🟡 已下載全文精讀（2026-09-03）——列舉/複雜句先拆成 atomic propositions 再抽，可降低句法雜訊。⚠️ Tables 2/3 明確顯示：對**弱**抽取器有幫助、對**強** LLM 反而變差（"when using LLM extraction, performance decreases"）；且是輸入端預防、非事後核對。本專案因此改採事後子句層級核對，不在輸入端拆解。引用 FActScore（Min et al. 2023）作為 atomic-fact + 逐原子驗證的先例 |
| `jiang-et-al-2024-genres.pdf` | Jiang et al. (2024), *GenRES: Rethinking Evaluation for Generative Relation Extraction in the Era of LLMs* | arXiv [2402.10744](https://arxiv.org/abs/2402.10744)（NAACL 2024） | ✅ 🟡 已下載（2026-09-03）——生成式 RE 的多維評估框架（含 factualness 維度）。與本報告相關性偏邊際：是評估方法論、非抽取階段的修正機制，未直接影響 `_quantity_mis_bound_to_clause()` 設計 |

**未下載（無免費全文）**：Huang et al. (2026)，*Trustworthy LLM-Based Relational Triple Extraction via Entailment-Aware Collaboration*——只有 Springer／ResearchGate（付費牆），無 arXiv/ACL 版本，僅能書目層級引用。這是**方法論最貼近的先例**：對每條抽取三元組驗「(subject, verb, object) 是否被來源描述蘊涵」，不一致就丟棄該三元組及文件內同型別者。`_quantity_mis_bound_to_clause()` 是這個「per-triple 蘊涵核對 → 丟棄」精神的輕量、非LLM、聚焦數量片語的具體化。

**未下載（部落格文章，非論文，不適用🟢/🟡分級）**：Horace He (2025-09-10)，*Defeating Nondeterminism in LLM Inference*，Thinking Machines Lab（Connectionism部落格）——https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/ 。核心主張：temperature=0不保證LLM推論決定性輸出，根因是批次大小依賴（batch-size dependence）而非取樣隨機性；徹底解決（batch-invariant kernels）需付出62-113%吞吐量開銷。作者為知名ML系統工程師（PyTorch核心貢獻者），文中附可重現GitHub實作與量化數據，非空泛主張，但屬部落格文章非同行評審出版品。

## 待辦

- [ ] 若後續需要更嚴謹的正式引用，可查證 Thinking Machines Lab 部落格內容是否有對應的後續正式論文發表
