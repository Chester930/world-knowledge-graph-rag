# 22_生成端過度保守與選擇性拒答

對應 `docs/報告/25_擴大版新舊KG問答品質比對報告.md` § 4 發現2／§6 ⑥；`docs/論文/03_系統設計與方法論.md` § 3.6（`verify_fact_grounding()` 的 `is_claim` 三分類、限制性重生成觸發條件）；交叉引用 `docs/參考文獻/05_評估方法論/`（RAGAS Faithfulness）、`docs/參考文獻/02_RAG與GraphRAG/`（Chain-of-Verification、Abstention 綜述）。

## 起點（2026-09-02，報告25 發現2）

報告25 §4 發現2 的原始觀察：題4[A]（N0060007 高溫作業）「原有工資不得減少」這條事實逐字在事實清單裡、草稿也逐字引用，最終答案卻是「資料未明確記載，無法確認」。原判定為「生成端過度保守」。

**修正定性（3 輪生成鏈診斷 `diagnose_finding2_q4.py`）**：發現1+5+6 修好檢索後重跑，**草稿三輪都兩部分全對、正確引用事實**。失效不在草稿生成，而在「接地核對 → 限制性重生成」迴圈：

1. `verify_fact_grounding()` 對回答**逐句**判 supported。`qwen2.5:7b` 常把使用者的問題原樣當 markdown 標題回貼（`**…原本的工資可以跟著減少嗎？**`）、加引言句（`根據提供的事實…`）——這些句子天生不會被事實清單支持，被判 `supported=False`（技術上對），但它們**不是需要被支持的事實主張**。
2. `routers/agent.py::chat()` 觸發條件是 `any(not c.supported for c in grounding)`——任一句未接地即觸發限制性重生成，不分「未接地的事實主張」（真問題）與「未接地的非主張句」（無害）。
3. `_build_constrained_prompt()`（依 CoVe factored 設計、刻意不給草稿）在嚴格約束下，對「五十度以上」黏在實體名裡的彆扭事實，有時就答成「資料未明確記載」——**把正確草稿改壞**。

## 內容清單

| 檔案 | 文獻 | 來源 | 狀態 |
|---|---|---|---|
| `zhou-et-al-2023-context-faithful-prompting.pdf` | Zhou, Zhang, Poon & Chen (2023), *Context-faithful Prompting for Large Language Models*，Findings of EMNLP 2023（USC + Microsoft Research） | [arXiv:2303.11315v2](https://arxiv.org/abs/2303.11315)；[ACL Anthology 2023.findings-emnlp.968](https://aclanthology.org/2023.findings-emnlp.968/)；[GitHub wzhouad/context-faithful-llm](https://github.com/wzhouad/context-faithful-llm) | ✅ 🟢 已下載全文精讀（6 頁正文 + 附錄） |
| `muhamed-et-al-2025-refusalbench.pdf` | Muhamed, Ribeiro, Dreyer, Smith & Diab (2025), *RefusalBench: Generative Evaluation of Selective Refusal in Grounded Language Models* | [arXiv:2510.10390](https://arxiv.org/abs/2510.10390)（2025-10-12） | ✅ 已下載；🟡 待精讀（18 頁，摘要層級已查證：frontier model 在多文件任務 refusal accuracy < 50%、同時存在 overconfidence 與 overcaution） |

**參考文獻查證（不下載全文，僅記書目）**：
- **"Not All Needles Are Found: How Fact Distribution and Don't Make It Up Prompts Shape Literal Extraction, Logical Inference, and Hallucination Risks in Long-Context LLMs"**（[arXiv:2601.02023](https://arxiv.org/abs/2601.02023)，2026-01）——🟡 搜尋結果層級：「Don't Make It Up」型 prompt 在「literal extraction vs hallucination」之間的權衡，與本專案 `_grounding_prompt()`／`_build_constrained_prompt()` 的嚴格措辭直接相關。
- **Copy-Paste to Mitigate Large Language Model Hallucinations**（[arXiv:2510.00508](https://arxiv.org/abs/2510.00508)，2025）——🟡：response copying 程度與 context-unfaithful hallucination 反相關；與 `docs/參考文獻/18` 的 pointer-generator（See et al., 2017）同一「複製優於改寫」脈絡。

## 各文獻在本設計中的角色

### 1. Context-faithful Prompting（Zhou et al., 2023）——問題框架與方向佐證，但特定技法對小模型有反效果警示

全文精讀確認：把「context faithfulness」拆成 **knowledge conflict**（context 與參數知識衝突時該信 context）與 **prediction with abstention**（context 沒有答案時該拒答）兩個面向。本專案發現2 屬第二面向的**反向失效**——context **有**答案，系統卻拒答。

論文提出兩個 prompt-only（不 finetune）技法：**opinion-based prompts**（把 context 重寫成「Bob said, '…'」、問「in Bob's opinion」）與 **counterfactual demonstrations**（few-shot 用假事實）。實證：OPIN+INSTR 把 memorization ratio 35.2%→3.0%（NQ）、NoAns 準確率 +57.2%（RealTime QA）。

**⚠️ 關鍵警示（§4.4，直接關係本專案）**：opinion-based prompts 在**較小的 LLM** 上「achieves similar or even higher Brier score than base prompts, indicating it does **not** improve the selective prediction ability」——原因是「smaller LLMs have inferior reading comprehension ability... Opinion-based prompts change uncertain predictions of answerable questions to *I don't know*, which could lead to worse results」。本專案用 `qwen2.5:7b`（小模型），**因此不採用 opinion-based prompting**——它可能加重我們正要減輕的過度拒答。較安全的是論文的 instructed prompt（「based on the given text」這類 attributive phrase）。

**誠實侷限**：論文假設 context 可靠、且聚焦「生成更新後的答案」，不處理多跳推理；實驗為英文。

### 2. RefusalBench（Muhamed et al., 2025）——選擇性拒答校準的評估基準

🟡 摘要層級：grounded LLM 的「selective refusal」評估——「refuse when they should, answer when they can」。frontier model（Gemini 1.5 Pro、GPT-4o、Claude 3.5）在多文件任務 refusal accuracy < 50%，同時存在 dangerous overconfidence 與 overcaution。本專案發現2 是 overcaution 的一種：答案在場、系統仍拒答。作為「這是有命名、有基準的現行研究問題」的佐證，非本次修正的具體方法來源。

### 3. RAGAS Faithfulness（Es et al., 2023，見 `docs/參考文獻/05`）——`is_claim` 分類的直接依據

RAGAS 的 Faithfulness 指標：**先從回答抽取事實主張（claims），再逐一對 context 核對**，分數 = 被支持的 claim 數 / 總 claim 數。關鍵是「claim」是**事實主張**，不是原始句子——引言、標題、過渡語不是 claim、不進分母。本專案 `verify_fact_grounding()` 目前用規則式 `split_into_sentences()` 逐句判定（docstring 自述此為「句 vs 原子主張」粒度侷限），發現2 的 2a 修正正是補上這一層：每句多判 `is_claim`，`chat()` 只在「是 claim 且未接地」時觸發限制性重生成。

## 本次落地（2a，報告25 §6 ⑥）

- `ClaimGrounding` 加 `is_claim: bool = True`（缺省 True＝分類不出來時當主張處理，保守）。
- `_grounding_prompt()` 加指示：每句先判 `is_claim`（含數字／期限／金額／條件／結論的具體斷言 = true；引言／標題／問題回貼／過渡語 = false），`is_claim=false` 時 `supported` 一律填 true。
- `verify_fact_grounding()` 解析 `is_claim`；`is_claim=False` 的句子強制 `supported=True`。
- `chat()` 觸發條件 `any(not c.supported …)` → `any(c.is_claim and not c.supported …)`。
- `event: grounding` SSE 加 `is_claim` 欄位供前端/診斷透明。
- **未採用** opinion-based prompting（Zhou et al. §4.4 小模型反效果警示）。

## 尚未查證／待辦

- [ ] RefusalBench 全文精讀（目前僅摘要），確認其「selective refusal」定義與本專案 over-abstention 的對應程度、有無可借用的評估指標。
- [x] ~~"Not All Needles Are Found"、Copy-Paste 兩篇……若 2a 不足、要動 `_build_constrained_prompt()` 措辭或改採「定向修訂」（2b），需補全文精讀。~~ → **2b 已於 2026-09-07 落地（報告32 §9 G1，commit `bd3bbb7`）**，用的是本專案已有的 CoVe factored/joint 框架（見 `docs/參考文獻/16`、Dhuliawala et al. 2023），未動這兩篇；2b = 只把「未接地的主張句」給修正步驟、明確禁止沿用其中未查核的數值，接地句零 LLM 重生成。三臂（factored / joint / 2b）正式 A/B 為第五章消融待辦。

---

## G2（Q8 多跳區間推理 + 接地核對罰有效推論，報告32 §9）候選文獻 —— 待精讀，G2 設計時定案

報告32 T1 Q8 的失效有兩層：(1) 生成端不會做「值 5 落在事實清單的『1 以上未滿 10』級距 → 取該級係數 2」這個查表＋比較的組合推論（compositionality gap，既有 `docs/參考文獻/23` 的 Press et al. Self-Ask 已涵蓋）；(2) 就算推對了，`verify_fact_grounding()`（RAGAS 式逐句核對）把「係數 2」判為未接地——因為它是推論結果、不是事實清單裡逐字出現的字串。第 (2) 層是 RAGAS 式 faithfulness 的已知侷限。候選（僅摘要／社群文件層級查證，**未精讀**）：

| 檔案 | 文獻 | 來源 | 狀態 |
|---|---|---|---|
| `xu-et-al-2025-veritas-faithful-reasoning-rag.pdf` | Xu, Wu, Zhou, Feng, Zhou, Woo, Ramnath, Tian, Qi, Qiu, Cheong & Ding (2025), *Beyond Correctness: Rewarding Faithful Reasoning in Retrieval-Augmented Generation*（VERITAS） | arXiv [2510.13272](https://arxiv.org/abs/2510.13272)（v3 2026-06） | 🟡 已下載（14 頁），僅摘要層級——明確區分「逐字接地」與「邏輯上由檢索內容推得、但非字對字複述」的推理鏈；三個 faithfulness 維度（Think-Search／Information-Think／Think-Answer）。⚠️ 是 RL 訓練框架（turn-level reward），比本專案 prompt-only 路線重，僅作「有效推論不該被逐字核對罰掉」的問題定位與路線佐證，非方法採用 |

**尚未下載、G2 設計時再評估**：RAG-Zeval（arXiv:2505.22430，rule-guided reasoning 的 RAG 回答評估，回應 RAGAS 過度嚴格）；DROP（Dua et al. 2019，NAACL，discrete/numeric reasoning over text 的奠基基準——若 G2 要正式定位「數值級距查表」這個能力）。RAGAS 對「可推得但非逐字」claim 的過度懲罰是社群廣泛記錄的現象（如 Nike「1967 年成立」可由「1967 年 incorporated」推得卻可能被判 unfaithful），非單一 canonical 論文，G2 設計時以 RAGAS 官方文件 + VERITAS 佐證即可。

**候選參考專案（僅查證存在性，star 數／是否採用留待 G2 設計時）**：
- [`github.com/confident-ai/deepeval`](https://github.com/confident-ai/deepeval) —— DeepEval，開源 LLM 評估框架，其 faithfulness 指標（claim 抽取＋LLM-as-judge）與 RAGAS 走不同「字面 vs 語用」尺度的實作對照——`verify_fact_grounding()` 要放寬「明示推論」時的既有實作參考。
- VERITAS（arXiv:2510.13272）——官方 repo URL 待查（RL 訓練框架，本專案 prompt-only 路線不直接複用，僅問題定位）。
- RAGAS（[`explodinggradients/ragas`](https://github.com/explodinggradients/ragas)，已在 `docs/參考文獻/05`）——`verify_fact_grounding()` 的方法來源，其官方文件對「可推得但非逐字」的處理即為對照基準。

**⚠️ G2 的碼與設計尚未動**——依使用者指示，等 KG #4 抽完、§6.2 窗口確認 Q8 在 F2/F3b/發現29 之後是否還失敗，再設計（prompt 區間比對提示 / 報告28 分解擴充 / grounding 對「明示推論」放寬）。
- [ ] `is_claim` 分類本身由核對模型（`qwen2.5:7b`）判定，可能誤判（把真主張判成非主張 → 漏觸發該重生成的情況）——真實觸發率與誤判率待實測。
