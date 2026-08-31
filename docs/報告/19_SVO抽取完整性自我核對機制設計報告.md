# 19：SVO 抽取完整性自我核對機制設計報告

> 狀態：🟡 設計中，尚未實作。2026-08-31，使用者對報告18發現的「規則7擴充修正」提出架構性質疑後撰寫——依使用者要求先設計、寫入文件供確認，本次不動程式碼。同日依使用者要求把候選文獻全文精讀（非僅摘要），並查證對應開源專案，據以**修正 §3 的原始設計**（v1→v2，見 §3 開頭說明）。

## 1. 問題陳述：現行做法是案例驅動的 few-shot 修補，不是通用架構

`services/svo_service.py::_svo_prompt()` 目前用規則1-9加上逐步累積的反例／正例，教 LLM 辨認「一句話裡有多筆事實」「列舉結構」等模式。這是**few-shot 提示詞工程**——每次真實測試踩到一種新的漏抓句型，就得手動補一組新範例（規則7原本只示範「數量上限、次數限制、期限、給付狀態」四類，報告18發現「以小時為請假單位」這種方式/單位彈性不在範例涵蓋範圍內，才臨時擴充）。

**根本限制**：few-shot 範例只能讓 LLM 泛化到「跟範例夠像」的情況，遇到範例沒示範過的句型/附加規定類別還是會漏。這代表：
- 範例清單只會隨著真實測試不斷發現新案例而持續變長，永遠追不完所有可能的句型變化
- 每次修正都要等到「真實測試恰好命中」才會發現，本質是被動、事後補救，不是可預期涵蓋所有情況的設計
- 這正是使用者指出的核心問題：**這違背了「通用架構」的初衷**，變成不斷針對已觀察到的內容做客製化

## 2. 現有可借用的架構先例：事實接地性核對機制（報告16）

本專案已有一套解決**精確度**方向失效的成熟架構，可直接借用其設計精神，鏡像到**召回率／完整性**方向：

`routers/agent.py::chat()` 與 `services/verification_service.py::verify_fact_grounding()` 實作的「事實接地性核對」（報告16，2026-08-24 v1、2026-08-28 升級為方案B「限制性重新生成」）：
1. 先讓 LLM 生成完整草稿
2. 用獨立的核對步驟，逐句檢查草稿內容是否被檢索到的事實支持
3. 有未接地陳述時，用限制性 prompt（只看事實清單，看不到原始草稿，避免文字錨定）重新生成一次
4. 只把核對過的最終版本交給使用者

這個架構的核心價值：**不需要事先窮舉「LLM可能會捏造哪些類型的內容」**，只要讓模型拿自己的輸出跟依據做比對，任何類型的捏造都能被抓到——這正是使用者想要的「通用」而非「客製化清單」。

**文獻定位**（已是本專案既有引用）：Dhuliawala et al.（2023，🟢 *Findings of ACL 2024*）《Chain-of-Verification Reduces Hallucination in Large Language Models》（arXiv:2309.11495）——四步流程（草稿→生成驗證問題→回答→精修），核心主張是「不需訓練、純 prompting 即可讓 LLM 自我驗證並精修」，本專案報告16的方案B是其簡化版（單次核對，非多輪驗證問題）。

## 3. 提議設計：語意涵蓋比對 + 針對性補抽（v2，全文精讀後修正）

**v1（本報告初版，已捨棄）的問題**：初版設計是「把原文和已抽出的三元組整包丟給LLM，問一句『有沒有遺漏』」——這個設計沒有文獻依據，是憑直覺類比報告16畫出來的。全文精讀 ProMem／VeriFact 後發現，兩篇論文的實際做法**都不是**這種「整包丟給LLM自己抓」，而是先用一個**便宜、非LLM或輕量的機制局部定位可能遺漏的片段**，再**只針對那些片段**才觸發LLM補抽——這是更精細、更省成本的架構，v2 改採此設計。

**兩篇論文的實際機制**（全文精讀確認，非摘要臆測）：
- **ProMem**（§4詳列）：對來源的每個最小單位（論文情境是對話輪），計算它與已抽取記憶項目的 cosine 相似度，`> τmatch`（論文設為0.6）視為已涵蓋；未涵蓋的單位收集起來，**只對這些**做第二次 LLM 抽取，再合併。消融實驗證實單獨這一步就把完整性從54.03%拉到73.80%。
- **VeriFact**（§4詳列）：用 word-mapping（最長公共子串）演算法**（非LLM、純字串比對）**先找出原文裡存在、但抽取結果完全沒提到的文字片段，再用LLM判斷這些片段是否構成有意義的遺漏事實（僅聚焦時間性/因果關係兩類PDTB一級關係），最後才用LLM補寫遺漏事實。量化效果：不完整事實比例56.7%→22.5%（↓60.3%）、遺漏事實數1.22→0.76（↓37.7%）、人類事實覆蓋率77.5%→87.1%（↑12.4%）。

**流程（v2）**：
1. **第一階段**（現有不變）：`extract_svo_triples(text)` 用現有 `_svo_prompt()` 抽出三元組
2. **涵蓋比對（新增，非LLM）**：對 chunk 內每一句原文（`svo_index.json` 各 chunk 已有的 `original_sentences` 清單，抽取管線既有資料，不需新建索引），計算它與「已抽出三元組」文字（`subject+verb+object` 串接）之間的最高 cosine 相似度；低於門檻（比照 ProMem 的 τmatch=0.6）視為未涵蓋
3. **針對性補抽（僅未涵蓋句子非空時才觸發）**：把未涵蓋的句子重新組成一小段文字，直接重用現有 `extract_svo_triples()`（同一份 `_svo_prompt()`，不需要新寫prompt），只對這幾句話再抽一次
4. 合併第一、二階段結果，依 `(subject, verb, object)` 去重

**為什麼比較通用**：涵蓋比對這一步不需要我們事先列舉「數量上限、期限、方式、單位……」這些具體類別——任何類型的遺漏，只要它在向量空間裡跟現有三元組差異夠大，就會被標記為未涵蓋，不需要等真實測試踩到新案例才補 prompt。

**比 v1 好在哪**：
- **成本是條件式的**：只有真的有句子未涵蓋才觸發補抽LLM呼叫；涵蓋比對本身用既有的 `embedding_provider.encode_batch()`＋`services/classify_service.py::cosine_similarity()`（兩者皆已存在於本專案），成本遠低於一次LLM生成呼叫。多數已經抽得夠完整的chunk，補抽呼叫次數是0，不是v1原本誤判的「不管有沒有遺漏都要跑一次」。
- **補抽範圍更精準**：只把未涵蓋的句子送進LLM，不是整個chunk重新抽一次，補抽呼叫本身的輸入輸出token數也更小。
- **有真實量化證據支持這個具體機制有效**（v1的「整包丟給LLM自己抓」沒有對應的消融實驗數據佐證）。

**對應開源專案佐證**：Google `google/langextract`（即時查證 **38,512★**，`gh api`，2026-08-31，`archived: false`，4天前才有新push，非停滯專案）提供 `extraction_passes=N` 參數處理長文件的「needle-in-a-haystack」召回率問題，官方文件明確標註「Improves recall through multiple passes」——但其機制是對整份文件做N次**獨立完整重抽**再合併（ensemble式），沒有先定位遺漏片段的步驟，是比ProMem/VeriFact更暴力、成本更高的做法（每次都是全量重抽，非條件式）。**本設計刻意不採用LangExtract這種暴力多次抽取的做法**，改採ProMem/VeriFact的「先定位、再局部補抽」，成本效益更好。

**誠實侷限（比照報告16 §「誠實侷限」的既有慣例，不宣稱百分之百）**：
- 只做一輪涵蓋比對＋一輪補抽，不做多輪迭代收斂（比照方案B「只重新生成一次」的既有設計），避免無限迴圈與成本失控
- 門檻值 0.6 直接沿用 ProMem 論文設定，尚未針對本專案的中文法規文本語料與 embedding 模型（`bge-m3`）重新校正——不同語言/領域的最適門檻可能不同，需要用真實資料驗證，不能盲目沿用英文論文的數值
- 涵蓋比對本身是語意相似度的近似判斷，不是形式化驗證，仍可能有極少數邊界案例誤判（相似度夠高但實際語意不同，或相似度不夠高但其實已涵蓋），是機率性的品質提升手段，非保證

### 3.1 對應程式寫法（設計草案，未實作）

比照 §3 的流程，對應 `services/svo_service.py` 的新增函式草案（沿用既有 `SVOTriple`／`EmbeddingProvider`／`cosine_similarity` 型別與既有 `extract_svo_triples()` 呼叫方式，不需要新的外部依賴）：

```python
from services.classify_service import cosine_similarity

UNCOVERED_SENTENCE_THRESHOLD = 0.6  # 沿用 ProMem (Yang et al. 2026) τmatch 設定，未針對本專案語料重新校正


async def _find_uncovered_sentences(
    original_sentences: list[str],
    triples: list[SVOTriple],
    embedding_provider: EmbeddingProvider,
    *,
    threshold: float = UNCOVERED_SENTENCE_THRESHOLD,
) -> list[str]:
    """比照 ProMem《Beyond Static Summarization》(arXiv:2601.04463) §Memory Completion
    的語意涵蓋比對：對每一句原文，計算它與「已抽出三元組」的最高相似度，低於門檻
    視為未涵蓋——供 extract_svo_triples_with_completeness_check() 判斷是否需要對這些
    句子額外做一次針對性補抽。

    triples 為空（第一階段完全沒抽到任何三元組）時，全部句子視為未涵蓋。
    """
    if not original_sentences:
        return []
    if not triples:
        return list(original_sentences)

    sentence_vectors = await embedding_provider.encode_batch(original_sentences)
    triple_texts = [f"{t.subject}{t.verb}{t.object}" for t in triples]
    triple_vectors = await embedding_provider.encode_batch(triple_texts)

    uncovered: list[str] = []
    for sentence, s_vec in zip(original_sentences, sentence_vectors):
        best_score = max(cosine_similarity(s_vec, t_vec) for t_vec in triple_vectors)
        if best_score < threshold:
            uncovered.append(sentence)
    return uncovered


async def extract_svo_triples_with_completeness_check(
    text: str,
    original_sentences: list[str],
    llm_provider: LLMProvider,
    embedding_provider: EmbeddingProvider,
    **kwargs,
) -> list[SVOTriple]:
    """第一階段：現有 extract_svo_triples()；涵蓋比對：非LLM、用既有 embedding
    比對定位未涵蓋句子；第二階段（僅未涵蓋句子非空時觸發）：對這些句子重用同一份
    extract_svo_triples() 再抽一次，合併去重。

    成本模型對稱於報告16接地核對機制：只有真的偵測到問題（此處是「有句子未涵蓋」）
    才多花一次 LLM 呼叫，多數已抽得夠完整的 chunk 不會觸發第二次呼叫。
    """
    triples = await extract_svo_triples(text, llm_provider, embedding_provider, **kwargs)

    uncovered = await _find_uncovered_sentences(original_sentences, triples, embedding_provider)
    if not uncovered:
        return triples

    supplement_text = "\n".join(uncovered)
    supplement_triples = await extract_svo_triples(
        supplement_text, llm_provider, embedding_provider, **kwargs
    )

    seen = {(t.subject, t.verb, t.object) for t in triples}
    merged = list(triples)
    for t in supplement_triples:
        key = (t.subject, t.verb, t.object)
        if key not in seen:
            seen.add(key)
            merged.append(t)
    return merged
```

**呼叫端整合點**：`trigger_extraction()`（`services/svo_service.py`）目前呼叫 `extract_svo_triples()` 的位置，需要額外傳入該 chunk 的 `original_sentences`（`svo_index.json` 各 chunk 已有此欄位，見 `build_svo_chunks()` 產出的結構，不需新建資料）。是否直接取代 `extract_svo_triples()` 的呼叫、或做成可選的 wrapper（保留舊函式供未升級的呼叫端使用，比照既有 `embedding_provider` 選填參數的優雅降級慣例），待 §7 確認方向後決定。

## 4. 文獻佐證（2026-08-31 即時查證，非憑記憶引用）

**以下三篇文獻與一個開源專案，本次（2026-08-31）皆已全文精讀（非僅摘要），比照專案既有慣例（見報告08 §6 對 HippoRAG 的全文精讀訂正經驗）：**

- **Chain-of-Verification**（Dhuliawala et al., 2023，🟢 ACL 2024 Findings，見§2）——本專案既有引用，本設計是其「草稿→核對→修正」架構在抽取完整性方向的鏡像應用，非新架構、是既有經驗證設計精神的複用。
- **ProMem**（Yang, Sun, Wei & Hu，2026，arXiv:2601.04463，🟡 全文已讀，但尚未查證是否已通過同行評審，僅為2026年1月的 arXiv 預印本）《Beyond Static Summarization: Proactive Memory Extraction for LLM Agents》——**Memory Completion 演算法**：對每個來源單位（對話輪）計算與已抽記憶項目的 cosine 相似度，`> τmatch=0.6` 視為已涵蓋，未涵蓋單位收集後只對這些做第二次LLM抽取（見 §3 演算法虛擬碼）。實驗：GPT-4o-mini 為主要抽取模型、GPT-4o 評判、Qwen3-Embedding-8B 做語意比對，HaluMem／LongMemEval 資料集，另有 Llama3-8B 小模型驗證。消融實驗（Table 2）比較 w/o MC／w/o MV／w/o MC&MV 三種變體，證實兩模組「both essential」；Memory Integrity 42.91%（Mem0基線）→73.80%（ProMem），單獨補完步驟貢獻 54.03%→73.80%。**未見公開程式碼倉庫**。
- **VeriFact**（Liu, Zhang, Munir, Gu & Wang，2025，arXiv:2505.09701v2，2025-09-26，🟡 全文已讀，尚未查證是否已被正式會議/期刊接受，仍為 arXiv 預印本）《Enhancing Long-Form Factuality Evaluation with Refined Fact Extraction and Reference Facts》——在 SAFE 的 decompose-decontextualize-verify 流程中插入 **Detect＋Refine** 兩個新階段：不完整事實偵測用三個LLM（GPT-4o／Llama 3.3-70B／Qwen 2.5-32B）ensemble、取union合併提升recall；遺漏事實偵測用**word-mapping（最長公共子串）演算法**（非LLM，純字串比對）定位原文中未被抽取結果涵蓋的片段，再用LLM判斷是否構成有意義的遺漏（僅聚焦時間性/因果關係）。量化效果（Table 2）：不完整事實比例56.7%→22.5%（↓60.3%）、遺漏事實數1.22→0.76（↓37.7%）、人類事實覆蓋率77.5%→87.1%（↑12.4%）；人工精煉後24.9%的事實正確性標籤改變，證實遺漏context確實會導致對模型事實性的誤判。程式碼倉庫僅見 HuggingFace Space（`launch/factrbench`），未見完整GitHub開源。
- **google/langextract**（開源專案，即時查證 **38,512★**，`gh api`，2026-08-31，`archived: false`，4天前有新push）——Google官方維護的LLM結構化抽取函式庫，`extraction_passes=N` 參數官方文件明確標註「Improves recall through multiple passes」，用於解決長文件的「needle-in-a-haystack」召回問題，機制是對整份文件做N次獨立完整重抽再合併（ensemble式），**沒有先定位遺漏片段的步驟**——是本設計刻意不採用的對照組（見§3「比v1好在哪」）。

**全文精讀後對 v1（本報告初版設計）的修正**：v1「整包丟給LLM問有沒有遺漏」在三篇文獻裡都找不到對應機制——ProMem／VeriFact 都是先用**非LLM或輕量機制**定位可能遺漏的片段，才**針對性**觸發LLM補抽；v1這種設計沒有相應的量化實驗數據佐證其有效性，v2（見§3）已改採文獻實證過的架構。

## 5. 成本分析（v2修正：條件式成本，比v1誠實揭露的「大致翻倍」更低）

v1原本假設「不管有沒有遺漏都要跑一次LLM」，成本無條件翻倍；v2改採涵蓋比對前置後，成本結構不同：

- **每個chunk一定會增加的成本**：涵蓋比對本身（`encode_batch()` 對句子與三元組文字編碼＋`cosine_similarity()` 比對）——這是 embedding 呼叫＋純數值運算，不是 LLM 生成呼叫，成本遠低於一次 `extract_svo_triples()`（LLM生成）呼叫。多數 chunk 的句子數與三元組數都是個位數到十幾筆，`encode_batch()` 呼叫量小。
- **條件式的LLM補抽成本**：只有涵蓋比對抓到未涵蓋句子的 chunk 才會觸發第二次 LLM 呼叫——實際觸發率取決於第一階段抽取本身的召回率（規則7擴充修正後，第一階段召回率應已提升，觸發率預期隨之下降，但目前無真實資料可估算具體比例）。
- **與報告16接地核對機制的成本模型現在一致**：兩者都是「只有真的偵測到問題才多花一次生成呼叫」的條件式額外成本，不是無條件翻倍。
- **仍需誠實揭露的不確定性**：目前沒有真實資料能估算「有多少比例的chunk會觸發補抽」，所以無法給出精確的整體成本增幅數字（可能遠低於「翻倍」，也可能因法規文本的附加規定密度高而觸發率不低）——建議正式上線前，先對報告18同一批5筆場景資料實測觸發率與耗時增幅，取得真實數字，而非停留在理論推算。

## 6. 與現有規則7-9 few-shot範例的關係（待決）

完整性核對機制上線後，規則7-9的具體反例/正例是否還需要保留、需要保留到什麼程度，有兩種可能立場，本報告不代為決定：

- **立場A（保留現狀）**：few-shot範例仍能提升第一階段的初始召回率，減少第二階段需要補的量，間接降低整體成本（第二階段要生成的遺漏三元組越少，那次呼叫的輸出token數也越少）；完整性核對機制當作「安全網」，兩者疊加使用。
- **立場B（精簡範例）**：既然完整性核對機制本身就足以泛化涵蓋所有類別的遺漏，規則7-9可以只保留最基本的1-2組格式示範（教會LLM「同句多事實要拆分」這個原則本身），不需要再為每個新發現的案例類型持續累積範例——把「涵蓋所有情況」的責任完全交給第二階段，第一階段只需要抓大宗常見情況。

## 7. 待確認事項

本報告依使用者要求「先設計不實作」，2026-08-31 已完成文獻全文精讀與對應開源專案查證（§3、§4），設計由 v1 修正為 v2；以下事項待確認後才進入實作：

1. 是否採用 v2 設計（§3／§3.1 程式碼草案），或有其他方向？
2. 若採用：立場A或立場B（§6，規則7-9 few-shot範例去留）？
3. ProMem／VeriFact 已全文精讀，量化數字已查證（§4）——是否要正式收錄進 `docs/參考文獻/`（比照既有命名慣例新增 `15_...` 或延伸既有資料夾）？兩篇皆為 arXiv 預印本（🟡），是否需要另外確認/等待正式發表venue，或先以現有精讀成果收錄？
4. §3.1 程式碼草案的門檻值 0.6 直接沿用 ProMem 設定，未針對本專案中文法規語料校正——是否要先用報告18的5筆場景資料做真實觸發率/門檻敏感度測試，再決定正式門檻值？
5. §3.1「呼叫端整合點」提到的取代 vs. wrapper 兩種接法，選哪一種？
6. 實作後是否需要重新驗證報告18的5+2題（比對完整性核對機制上線前後的品質差異，作為真實效果驗證，呼應報告18已建立的四條件測試方法論）？
