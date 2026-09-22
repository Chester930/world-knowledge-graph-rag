# 39_LLM評判者一致性與固定化評測量尺

對應 HANDOVER.md 2026-09-22「embedding快取重跑獨立judge pilot」段落——七題中有4題（`57-CANARY5`／`57-AGGR7`／`57-AGGR8`／`57-AGGR19`）的Stage 1 Context Recall會隨受測的judge換人而變動，即使embedding快取已確認讓檢索本身逐位元決定性。根因是`services/semantic_span_matcher.py::match_spans_with_fallback()`在逐字比對失敗時會呼叫`judge_llm_provider`做語意蘊含核對，而harness目前對Stage 1/2（檢索量測）與Stage 3/4（生成評分）全部共用**同一個、隨受測arm變動的judge實例**。本資料夾記錄查證結果，用來判斷這個confound該怎麼定性、怎麼修。

本資料夾不另存 PDF，僅 README 記角色＋WebSearch 即時查證（2026-09-22），比照 `38_檢索embedding非決定性與可重現性/` 的輕量作法。

## 查證結果

### 1. 奠基文獻：LLM-as-Judge本身已知的失效模式，以及「固定外部judge評分所有受測模型」的標準做法

> **Zheng, Chiang, Sheng, Zhuang, Wu, Zhuang, Lin, Li, Li, Xing, Zhang, Gonzalez & Stoica (2023)**，*Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena*，arXiv:2306.05685（NeurIPS 2023）

LLM-as-Judge範式的奠基之作，明確定義三種judge失效模式：**position bias**（回答呈現順序影響評分）、**verbosity bias**（偏好冗長回答不論品質）、**self-enhancement bias**（judge偏袒自己生成的內容）。**關鍵對應**：這篇論文自己的評測方法論，就是用**同一顆固定外部judge（GPT-4）為所有受測模型評分**，正是為了避免judge本身的變異污染「哪個模型比較好」這個待測結論——這跟本專案harness目前的做法（judge隨受測arm一起變動）背道而馳。

### 2. Self-preference bias：judge偏袒「自己認得出來的」輸出，跟本專案Stage 1情境的差異

> **Panickssery, Bowman & Feng (2024)**，*LLM Evaluators Recognize and Favor Their Own Generations*，arXiv:2404.13076（NeurIPS 2024）

發現LLM judge能一定程度辨認出「這是不是自己生成的」，且**self-recognition能力與self-preference bias強度呈線性相關**——judge認得出自己的輸出時，會給比較高的分數，即使人類標註者認為品質相當。

**誠實對應本專案情境的限制**：本專案Stage 1核對的對象是KG檢索出的事實文字（來自抽取管線，非任何judge生成），Stage 1的judge並不是在評自己的輸出，所以這篇的self-recognition機制**不直接適用**於Stage 1的confound。但Stage 3（Atomic Accuracy核對最終答案）情境較接近——若受測arm的judge同時決定了`chat()`內部的重生成行為（影響最終答案內容）又拿來評分最終答案，兩者間可能存在judge與生成流程的隱性耦合，雖然機制上不完全是「self-recognition」（答案生成者本身固定是qwen2.5:7b，變的只有judge），仍建議比照Zheng et al. 2023的原則處理：評分工具與受測變因分離。

### 3. 關鍵細節：事實導向RAG任務裡self-preference bias不顯著，本專案觀察到的更接近「評判者間信度」問題

> **Chen, Jin, Kuo, Huang & Chen (2024)**，*LLMs are Biased Evaluators But Not Biased for Retrieval-Augmented Generation*，arXiv:2410.20833

用三個QA資料集（NQ／MARCO／TriviaQA）與五個模型（GPT-3.5、GPT-4o-mini、Gemini、LLaMA3、Mistral）測試，發現：一般開放式評測任務中self-preference bias確實存在，但**在事實導向的RAG任務（reranking／grounding核對）中，self-preference bias並不顯著**，因為「事實準確性凌駕於風格偏好之上，即使在沒有先驗知識的情況下」。

**對本專案的定性意義**：這篇支持一個重要的精確化——本專案Stage 1觀察到的「Stage 1 Recall隨judge換人而變」，**更準確的定性不是self-preference bias（self-enhancement），而是基礎的評判者間信度（inter-rater reliability）問題**：不同judge模型對「這段話的語意是否蘊含gold span」這個entailment判斷本身能力/寬嚴不同，跟自我偏袒無關（Stage 1核對的文字不是任何judge自己生成的）。這個區分會影響論文行文用詞，不宜把這個現象直接歸類為self-preference bias。

## 對本專案的具體建議

1. **統一設計原則**：把「受測arm自己的judge」（`JUDGE_LLM_PROVIDER`，只用在`chat()`內部真正被測試的重生成決策）與「拿來當評分工具的judge」（用在Stage 1/2語意span核對**與**Stage 3/4 Atomic Accuracy，應固定、跨所有arm一致）分開——這正是Zheng et al. 2023自己evaluation方法論採用的原則（固定外部judge評分所有受測模型），不是本專案自創的做法。
2. **用詞精確化**：論文或報告描述這個現象時，應定性為「評判者間信度／量測工具隨受測變因變動導致的confound」，不宜直接套用self-preference bias/self-enhancement bias這個詞——因為Chen et al. 2024顯示這個機制在事實導向RAG任務裡本來就不是主要成因，而且Stage 1核對的內容不是judge自己生成的，跟self-preference bias的定義（judge偏袒自己的輸出）不吻合。
3. **範圍**：這個修法只影響評測harness層（`scripts/eval/`），不需要改`routers/agent.py`或任何production程式碼——`chat()`內部`JUDGE_LLM_PROVIDER`驅動的重生成行為維持現狀不變，只是harness量測Stage 1/2/3/4分數時，額外接一個固定、獨立於受測arm的metric-judge。
