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
| `muhamed-et-al-2025-refusalbench.pdf` | Muhamed, Ribeiro, Dreyer, Smith & Diab (2025), *RefusalBench: Generative Evaluation of Selective Refusal in Grounded Language Models* | [arXiv:2510.10390](https://arxiv.org/abs/2510.10390)（2025-10-12） | ✅ 🟢 §1–§4.3 精讀（2026-09-08，實為 44 頁）——見下「G2 文獻 §5」。六類不確定性、MissingInfo/Ambiguity 最難、Qwen 家族 refusal <17% 全尺寸（**僅限單文件基準 RefusalBench-NQ**；2026-09-21 重查，多文件 GaRAGe 在可取得的內文中未見 Qwen 數字）、FRR/MRR 指標 |

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

- [x] ~~RefusalBench 全文精讀，確認其「selective refusal」定義與本專案 over-abstention 的對應程度、有無可借用的評估指標。~~ → **2026-09-08 精讀完成**：定義＝「refuse when they should, answer when they can」，六類不確定性；本專案發現2＝overcaution（答案在場仍拒答），G2 例外的風險＝反向的 overconfidence（答案不在場卻硬答）。借用 FRR/MRR/Detection-F1 → 報告32 §9 C。見下「G2 文獻 §5」。
- [x] ~~"Not All Needles Are Found"、Copy-Paste 兩篇……若 2a 不足、要動 `_build_constrained_prompt()` 措辭或改採「定向修訂」（2b），需補全文精讀。~~ → **2b 已於 2026-09-07 落地（報告32 §9 G1，commit `bd3bbb7`）**，用的是本專案已有的 CoVe factored/joint 框架（見 `docs/參考文獻/16`、Dhuliawala et al. 2023），未動這兩篇；2b = 只把「未接地的主張句」給修正步驟、明確禁止沿用其中未查核的數值，接地句零 LLM 重生成。三臂（factored / joint / 2b）正式 A/B 為第五章消融待辦。

---

## G2（Q8 多跳區間推理 + 接地核對罰有效推論，報告32 §9）文獻 —— 2026-09-08 精讀完成

報告32 T1 Q8 的失效有兩層：(1) 生成端不會做「值 5 落在事實清單的『1 以上未滿 10』級距 → 取該級係數 2」這個查表＋比較的組合推論（compositionality gap，既有 `docs/參考文獻/23` 的 Press et al. Self-Ask 已涵蓋）；(2) 就算推對了，`verify_fact_grounding()`（RAGAS 式逐句核對）把「係數 2」判為未接地——因為它是推論結果、不是事實清單裡逐字出現的字串。第 (2) 層是 RAGAS 式 faithfulness 的已知侷限。

| 檔案 | 文獻 | 來源 | 狀態 |
|---|---|---|---|
| `xu-et-al-2025-veritas-faithful-reasoning-rag.pdf` | Xu et al. (2025), *Beyond Correctness: Rewarding Faithful Reasoning in RAG*（VERITAS），TMLR 05/2026 | arXiv [2510.13272](https://arxiv.org/abs/2510.13272)（v3 2026-06） | ✅ 🟢 §2–§3.4 精讀（2026-09-08，30 頁） |
| `muhamed-et-al-2025-refusalbench.pdf` | Muhamed, Ribeiro, Dreyer, Smith & Diab (2025), *RefusalBench: Generative Evaluation of Selective Refusal in Grounded Language Models* | arXiv [2510.10390](https://arxiv.org/abs/2510.10390) | ✅ 🟢 §1–§4.3 + Fig 4/6/8 精讀（2026-09-08，44 頁——README 舊記「18 頁」為誤） |

### 4. VERITAS（Xu et al. 2025）——問題定位，非方法來源；「有效推論」有邊界

- 三個 faithfulness 維度定義在 **§3.2**（README 舊述「§3.3」為誤；§3.3 是把 §3.2 操作化的評估指標）。與 G2 相關的是 **Information-Think faithfulness**：「the reasoning ... is a valid **synthesis, summary, or logical deduction** based on the **newly retrieved** information」，目的是「preventing the model from **ignoring evidence**」，judge「determines whether the reasoning is **grounded in, consistent with, and responsive to** the retrieved content, flagging **ignored, contradicted, or unsupported** claims」。
- **關鍵邊界**：VERITAS 許可的是「對*已檢索到的*證據做綜合／演繹」，**不是**跨缺口外推。查表時數值不在任何檢索到的列裡 → 對 VERITAS 也是 "unsupported claim"，一樣會 flag。memory §9 的「非逐字」對 *synthesis* 成立，但不能當成 gap-filling 的擋箭牌。
- VERITAS 是 **RL turn-level reward 訓練框架**，不提出任何 prompt 措辭。拿它背書 `_grounding_prompt()` 的 prompt 例外是**問題定位層級的佐證**，非方法採用。

### 5. RefusalBench（Muhamed et al. 2025）——G2 的直接風險來源 + §6.2 指標

- **六類資訊不確定性**：Ambiguity / Contradiction / **MissingInfo** / FalsePremise / **GranularityMismatch** / EpistemicMismatch。報26 Q7（問法規沒寫的健檢頻率）= **MissingInfo**；「值落在對照表沒有的級距」= **GranularityMismatch**。
- **MissingInfo 與 Ambiguity 是所有模型最難的兩類**（Fig 4）。模型**把 REFUSE_INFO_MISSING 當 catch-all**，而 **GranularityMismatch 被系統性誤分類**（Fig 8 混淆矩陣：GranMism→MisInfo 0.819）——正是 G2 例外會踩的邊界。
- **⚠️ Qwen 家族 selective-refusal 準確率全尺寸 <17%，不隨規模改善**（Fig 9；**僅限單文件基準 RefusalBench-NQ**）。**適用範圍要講準**：這是「模型在脈絡有缺陷時是否會適當拒答」的生成行為，不是「判斷一段答案／查表是否正確」的分類任務。本專案 `qwen2.5:7b` **同時當生成端與 grounding judge**，負責執行「每一列必須逐字」的那個 judge——它在這類判斷上可能有類似弱點，但**這是推論，不是該論文直接量測的結果**；直接證據是下方 G2 的金絲雀驗證（2026-09-21 校正，見報告61 §3.1）。
- 降 FRR 幾乎必然抬 MRR（"dangerous over-confidence or over-caution"，無模型兩維皆 >80%）。G2 壓 False-Refusal → 預期 Missed-Refusal 上升。
- **可借指標**（Appendix D）：**False Refusal Rate (FRR)**、**Missed Refusal Rate (MRR)**、Refusal Detection F1 → 已用於報告32 §9 C 的 `run_refusal_canary.py`。

### 6. 據此對 G2 的收緊（報告32 §9 A/B/A′，commit `a04f9ea`）

- **A 覆蓋前提**：查表例外只在「數值嚴格落在所引用那一列明列的上下界之內」時成立——取最近一列／落在間隙／越界一律回 false。
- **B 誠實拒答讓路**：數值不在任何明列區間內、或只檢索到部分級距卻對缺漏段給確定答案 → false（含查表未命中），正解是承認查不到。
- **A′**：`_grounding_prompt()` 傳入使用者問題，讓「題目數值須逐字出現」可真正核到。
- **C（§6.2）**：拒答金絲雀組 6 探針 ×3，FRR/MRR 閘門；MRR 一旦 > `ed32291` baseline → 觸發 **E**（把區間查表改成確定性 Python 檢查，移出 qwen judge）。

**尚未下載、G2 設計時再評估**：RAG-Zeval（arXiv:2505.22430，rule-guided reasoning 的 RAG 回答評估，回應 RAGAS 過度嚴格）；DROP（Dua et al. 2019，NAACL，discrete/numeric reasoning over text 的奠基基準——若 G2 要正式定位「數值級距查表」這個能力）。RAGAS 對「可推得但非逐字」claim 的過度懲罰是社群廣泛記錄的現象（如 Nike「1967 年成立」可由「1967 年 incorporated」推得卻可能被判 unfaithful），非單一 canonical 論文，G2 設計時以 RAGAS 官方文件 + VERITAS 佐證即可。

**候選參考專案（僅查證存在性，star 數／是否採用留待 G2 設計時）**：
- [`github.com/confident-ai/deepeval`](https://github.com/confident-ai/deepeval) —— DeepEval，開源 LLM 評估框架，其 faithfulness 指標（claim 抽取＋LLM-as-judge）與 RAGAS 走不同「字面 vs 語用」尺度的實作對照——`verify_fact_grounding()` 要放寬「明示推論」時的既有實作參考。
- VERITAS（arXiv:2510.13272）——官方 repo URL 待查（RL 訓練框架，本專案 prompt-only 路線不直接複用，僅問題定位）。
- RAGAS（[`explodinggradients/ragas`](https://github.com/explodinggradients/ragas)，已在 `docs/參考文獻/05`）——`verify_fact_grounding()` 的方法來源，其官方文件對「可推得但非逐字」的處理即為對照基準。

**G2 狀態**：初版落地 `04a90e8`（窗口診斷 Q8 1/3→3/3），2026-09-08 精讀 RefusalBench/VERITAS 後以 A/B/A′ 收緊（`a04f9ea`，全套 pytest 701 passed）。**C 已於 DRAIN-DONE 後執行完成（2026-09-13）**，結果：

| Probe | GT | baseline (`ed32291`) | after (`a04f9ea`) |
|---|---|:---:|:---:|
| P1 | REFUSE | 3/3 | 3/3 |
| P2 | REFUSE | 3/3 | 2/3（退步） |
| P3 | REFUSE | 0/3 | 0/3（無改善——G2 要修的核心情境仍未修好） |
| P4 | REFUSE | 3/3 | 3/3 |
| P5 | ANSWER | 0/3 | 1/3 |
| P6 | ANSWER | 3/3 | 2/3（退步） |

**MRR：0.25（3/12）→ 0.333（4/12），上升**；**FRR：0.5（3/6）→ 0.5 持平，但 P5 護欄（須 3/3 ANSWER）未過（1/3）**。閘門 1／3 皆 FAIL，閘門 4 的觸發條件（MRR 上升）成立。

**⇒ 依預先訂定的規則，觸發 E**：A/B/A′ 收緊沒有解決 P3（缺級距查表例外）的核心情境，反而在 P2／P6 造成新退步——判斷失效不在「規則覆蓋前提不夠嚴」，而在**這類查表判斷本質上不該交給 `qwen2.5:7b` 這個 judge**（**直接證據是這次金絲雀驗證：MRR 0.25→0.333、P3 缺級距 0/3→0/3**；RefusalBench 在單文件基準 RefusalBench-NQ 上報告 Qwen 各尺寸的拒答準確率皆 <17%，方向一致，但量的是脈絡有缺陷時是否適當拒答，只是間接參考）。下一步是 E：`_grounding_prompt` 保持嚴格，查表判斷移出 LLM，改由 `chat()` 內一個確定性 Python 區間檢查（解析 `[區間] → [值]` fact line + 問題數值，嚴格包含才抑制重生成觸發）。

原始輸出：`refusal_canary_output_baseline_ed32291.txt` / `refusal_canary_output_after_a04f9ea.txt`（repo 根目錄）。

- [x] ~~`is_claim` 分類本身由核對模型判定，可能誤判~~ → C 已量到：`ungrounded` 欄位顯示各 run 未接地主張數 0–6 不等，誤判率隨題目波動，非本次 C 的主要瓶頸。
- [x] ~~若 C 顯示 MRR 上升 → 上 E~~ → **MRR 確實上升，E 已觸發，設計為下一步待辦**（尚未實作，見上）。

---

## 續：`AtomicScorer`（評測用，非 G2 生產路徑）canary_refusal 假陽性修復（報告57 §4.3，2026-09-16）

**觸發**：健康檢查頻率聚合題（`57-CANARY3`）真實跑測發現，`services/atomic_scorer.py::evaluate()` 的 Type-E 拒答檢核只要答案全文**任一處**出現拒答關鍵字（`未記載`／`無法確認`等）就判定整題拒答成功，不要求拒答對應到題目核心主張——模型確信斷言了陷阱結論（精密作業需要特殊健康檢查），卻在文字別處夾帶一句跟核心問題無關的「無法確認」，被誤判 100% 通過。

**跟本節上方 G2/RefusalBench 的關係**：這是**同一類設計取捨在另一個 call site 的重演**——修復時一度考慮「改用 `verify_fact_grounding()` 既有的 `ClaimGrounding` 逐主張語意判斷」，但 G2 的直接經驗是「查表判斷交給 LLM judge，收緊 prompt 後效果仍不佳（金絲雀驗證），才改走方案 E（確定性 Python 檢查、移出 LLM judge）」，RefusalBench 對 Qwen 拒答行為的報告只是間接參考。**要注意：陷阱結論判斷與查表判斷是不同任務，本專案尚未直接驗證 LLM judge 在這個任務上的表現**（2026-09-21 校正，見報告61 §3.1）。故本次修復**選擇確定性優先、不換成語意判斷**，改為新增 `trap_claim_spans`（`models/eval_schema.py::TestCase`）：Type-E 題目選填一組「陷阱結論」固定字串，答案命中任一則即強制判定拒答失敗，純字串比對、零額外 LLM 呼叫，與 G2 方案 E 同一設計原則的延伸應用（把「該不該判定為拒答」的確定性檢查範圍從「查表數值」推廣到「canary 陷阱結論」）。

**結果**：5 題既有 canary 題目回填——只有 `57-CANARY3`（類別混淆型陷阱）有固定可檢查的陷阱結論；`canary-P1`/`canary-P4`/`57-CANARY1`/`57-CANARY2`（開放式捏造具體數字型陷阱）刻意留空，因為陷阱關鍵詞在正確拒答時也會自然出現（用來否定它），加字串比對反而製造假陰性。真實 harness 重跑確認：`57-CANARY3` 漏洞已堵住（模型答案不變，但正確判定失敗）；其餘 4 題零回歸（`canary-P4`/`57-CANARY2` 維持通過，`canary-P1`/`57-CANARY1` 讀答案確認是模型直接編造具體數字、走的是修復前後相同的判定路徑，證實跟本次修復無關——這兩題暴露的是模型本身選擇性拒答能力不足，再次呼應 RefusalBench 的核心發現）。

**`is_refusal_text()`（`services/interval_lookup_service.py`，正式 `chat()` 生產路徑）維持不動**——同一套 naive 關鍵字掃描邏輯理論上也有同樣假陽性風險，但這是已經走過 A/B/A′/C/E 正式驗證流程（`run_refusal_canary.py` 的 FRR/MRR 門檻）的獨立子系統，若要修應另外排程、走同一套探針驗證流程，不跟這次的 eval 評分修復混在一起。
