# 23_複合問題分解與自相矛盾修正

對應 `docs/報告/28_複合問題子問題分解機制設計與實作報告.md`（報告26 §4 #2
「多事實組裝糊成一團」的修法：`routers/agent.py::_split_into_subquestions()`／
`_generate_decomposed_answer()`）。

## 內容清單

| 檔案 | 文獻 | 來源 | 狀態 |
|---|---|---|---|
| `zhou-et-al-2023-least-to-most-prompting.pdf` | Zhou, Schärli, Hou, Wei, Scales, Wang, Schuurmans, Cui, Bousquet, Le & Chi (2023, Google Research)，*Least-to-Most Prompting Enables Complex Reasoning in Large Language Models*，ICLR 2023 | [arXiv:2205.10625](https://arxiv.org/abs/2205.10625) | ✅ 已下載全文（61 頁，含附錄）精讀方法章節（§2） |
| `press-et-al-2022-self-ask-compositionality-gap.pdf` | Press, Zhang, Min, Schmidt, Smith & Lewis (2022, UW/MosaicML/Meta AI/AI2)，*Measuring and Narrowing the Compositionality Gap in Language Models*（Self-Ask），Findings of EMNLP 2023 | [arXiv:2210.03350](https://arxiv.org/abs/2210.03350) | ✅ 已下載全文（25 頁）精讀方法章節（§3.1/Figure 2/3） |

## 精讀後的精確機制（2026-09-05，訂正報告28 初版的簡化描述）

報告28 初版把兩篇文獻的機制籠統描述為「LLM 分解＋循序求解」。全文精讀後，
兩篇的機制比這句話更具體，且**跟本專案 `_split_into_subquestions()`／
`_generate_decomposed_answer()` 的差異比初版描述的更大**：

### Least-to-Most（Zhou et al., ICLR 2023）——精確為兩階段、皆為 few-shot prompting、無微調

1. **Decomposition 階段**：一次 LLM 呼叫，prompt 由「示範分解的少樣本範例」+ 原問題組成，輸出子問題清單。
2. **Subproblem solving 階段**：**逐一循序**呼叫 LLM。第 *i* 個子問題的 prompt = 示範範例 + **前面所有已解出的子問題與答案** + 第 *i* 個子問題。原問題本身當作最後一個「子問題」附加在序列尾端，故最後一次呼叫已經看過全部中間答案。
   - 論文 Table 1/2/3 的字母串接範例明確示範：第二個範例的答案是「延伸自第一個範例的答案」（"think, machine" 的解 "ke" 被第二次呼叫直接引用去組成 "think, machine, learning" 的解），是貨真價實的**跨呼叫依賴鏈**，不是各自獨立作答。
   - 效果：SCAN 組合泛化基準用 code-davinci-002 達 ≥99% 準確率（14 個示範），比 chain-of-thought 的 16% 高極多；last-letter-concatenation 任務隨串列變長，優勢隨長度擴大（L=12 時 74.0% vs. CoT 31.8%）。

### Self-Ask（Press et al., 2022）——精確為單次生成內的自問自答鷹架，非多次獨立呼叫

- **核心機制（Figure 2）**：**單一** LLM 生成呼叫。Prompt 尾端接上「Are follow up questions needed here:」，模型在**同一段連續輸出**裡自己產生「Follow up: ⟨子問題⟩」「Intermediate answer: ⟨子答案⟩」，重複數輪，直到輸出「So the final answer is: ⟨答案⟩」收尾。是模型自己決定要問幾個子問題、自己回答，全程一次呼叫完成，不是外部迴圈拆成 N 次獨立呼叫。
- **Self-Ask + Search Engine（SA+SE）變體**（§3.3）才會真正拆成多次呼叫：LM 生成到「Follow up: …」時外部程式介入，把子問題送進搜尋引擎、把搜尋結果塞回 prompt 續接，重複直到 LM 輸出最終答案——但**子答案之間仍是累積、循序可見**的（後一輪的 prompt 包含前面所有子問題/答案），跟 Least-to-Most 的依賴鏈精神一致。
- **Compositionality gap（本篇核心貢獻，非解法本身）**：定義為「模型能各自答對每個子問題，卻答錯組合起來的複合問題」的比例。GPT-3 家族實測發現這個 gap **不隨模型規模縮小**（穩定在 ~40%），顯示模型擴大只增加事實記憶量、不增加組合推理能力——這是本專案觀察到的失效模式（模型正確引用某條事實作答、收尾摘要卻又推翻說未記載）在更廣泛意義上的同類現象：**知道個別事實，不代表能正確地把多個事實組裝進同一個連貫答案**。

## 與本專案 M1 設計的關係（誠實比較）

| 面向 | Least-to-Most／Self-Ask | 本專案 `_split_into_subquestions()`／`_generate_decomposed_answer()` |
|---|---|---|
| 分解方式 | LLM 呼叫（few-shot 示範） | **純規則**：按句末問號切分，零 LLM 呼叫 |
| 子問題間關係 | **循序依賴**——後一子問題的 prompt 包含前面所有子問題與答案（Least-to-Most 顯式串接；Self-Ask 同一生成內累積） | **完全獨立**——每個子問題各自對同一份事實清單生成，彼此在生成當下互相看不到對方的輸出 |
| 呼叫次數 | Least-to-Most：分解1次＋子問題N次序列呼叫；Self-Ask：預設1次（SA+SE 才拆多次，但仍累積） | N 次獨立呼叫（草稿）＋視情況再 N 次（限制性重新生成） |
| 適用情境 | 子問題有真實計算/邏輯依賴（後一步需要前一步的數值結果） | 本專案的子問題彼此**無依賴**——各自對應事實清單裡不同的一條事實（例如「連續僱用滿多久」與「獎勵金發給幾個月」互不影響），依賴鏈機制對本案例沒有必要，故簡化為獨立生成以換取更低成本（零分解呼叫）與更強的抗汙染性（無跨子答案內容可見，不會互相矛盾） |

**誠實聲明**：本設計是兩篇文獻「顯式分解＋逐一作答」精神的**簡化應用**，
刻意捨棄了兩者的核心機制（LLM 分解、循序依賴鏈），因為本專案的子問題結構
（各自獨立對應一條事實）不需要這兩個機制解決的問題（子問題間的計算依賴、
組合推理的 compositionality gap）。若第五章需要用這兩篇文獻做嚴謹方法論
對照，應明確區分「動機借鏡」與「演算法直接複用」——本設計屬前者。
