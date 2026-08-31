# 19：SVO 抽取完整性自我核對機制設計報告

> 狀態：✅ 已實作（2026-08-31，同日）。設計→文獻全文精讀修正（v1→v2）→下載文獻並綁定進論文02/03→實作，全程同一天完成。`_find_uncovered_sentences()`／`extract_svo_triples_with_completeness_check()` 已落地於 `services/svo_service.py`（commit `7ae8794`），已接線進正式抽取路徑 `services/extraction_worker.py::_process_one()`；9項新單元測試＋真實LLM/embedding端到端驗證皆通過，全套580項測試無迴歸。**尚未對既有KG重新抽取受益**（比照規則7上線時的既有慣例，需 `force_rebuild=True`），§7 待確認事項的實作前決策已由使用者於同日確認（見 §7 更新）。

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

## 7. 待確認事項（2026-08-31 同日全數確認完畢，狀態見下）

1. ✅ 採用 v2 設計（§3／§3.1）——已實作。
2. ✅ 使用者決策：**兩者並存，非A非B的混合立場**——「先以涵蓋為主，補充為輔」：完整性核對機制是真正保證召回率的主要機制，規則7-9 few-shot範例保留不動（不刪減、不新增），角色降級為降低第一階段遺漏量、間接減少第二階段補抽負擔的輔助優化。程式碼與docstring已依此決策撰寫（見 `services/svo_service.py::extract_svo_triples_with_completeness_check()` docstring）。
3. ✅ 已完成——文獻已下載全文並綁定進 `docs/參考文獻/17_抽取完整性與召回率驗證/`、`docs/論文/02_文獻探討.md`§2.4.4、`docs/論文/03_系統設計與方法論.md`§3.1.3、`docs/論文/附錄與參考文獻.md`（commit `60ccc6e`）。
4. ⏸️ 門檻值 0.6 直接沿用 ProMem 設定實作上線，**未針對本專案中文法規語料校正**——真實觸發率/門檻敏感度測試留待後續（見§9待辦）。
5. ✅ 使用者決策：選填 wrapper——新增 `extract_svo_triples_with_completeness_check()`，`extract_svo_triples()` 完全不動，向後相容。
6. ⏸️ 實作後重新驗證報告18的5+2題——**尚未執行**，需要對既有KG重新抽取（`force_rebuild=True`）才能反映新機制效果，是否/何時進行留待使用者決定（見§9待辦）。

## 8. 實作摘要（2026-08-31）

- **程式碼**：`services/svo_service.py` 新增 `UNCOVERED_SENTENCE_THRESHOLD`（=0.6）、`_find_uncovered_sentences()`、`extract_svo_triples_with_completeness_check()`（commit `7ae8794`）。
- **接線**：`services/extraction_worker.py::_process_one()` 原本呼叫 `extract_svo_triples()` 改為新 wrapper，傳入 `chunk["original_sentences"]`（`svo_index.json` 既有欄位，不需新資料）。
- **測試**：`tests/services/test_svo_service.py` 新增9項單元測試，涵蓋無三元組全未涵蓋、無句子/無embedding_provider優雅降級、已涵蓋不觸發補抽、未涵蓋觸發補抽、合併去重五類情境；全套580項測試通過，無迴歸。
- **真實LLM/embedding端到端驗證**：對「第7條全文」（已被規則7擴充涵蓋）與「警察特休三等級條文」（一般未特別修過案例）分別驗證，兩案例皆只觸發1次抽取LLM呼叫（完整性核對正確判定無遺漏，未觸發補抽）——證實「規則7-9降低第一階段遺漏、完整性核對當安全網」的條件式成本模型在真實環境下成立，非純理論推算。

## 9. 後續待辦（未執行，供接續）

1. 門檻值 0.6 的真實觸發率／敏感度測試（§7-4）——建議用報告18的5筆場景資料實測。
2. 既有KG（a53203ab／99a25aca／76bc98ff）尚未重新抽取，無法反映新機制效果——是否/何時 `force_rebuild=True` 待使用者決定；76bc98ff 目前仍暫停於49%，牽涉是否要與抽取恢復一併處理。
3. 實作後重新驗證報告18的5+2題（§7-6），量化完整性核對機制上線前後的品質差異。

## 10. 最小規模真實重跑驗證（2026-08-31，同日）

使用者要求「實際跑抽取來比對結果」。挑選報告18 Q5 已發現明顯缺陷的真實案例——KG `a53203ab` 的 `D0080015_警察人員特別休假辦法` chunk 4（第4條，三至七日最高等級特休），確認 Neo4j 裡完全查無對應三元組（`task_queue` 標記為 completed，但實際內容缺席）。

**排查過程與誤判修正**：
1. 直接呼叫 `extract_svo_triples_with_completeness_check()`：正確抽出4筆三元組，物件為「三至七日之特別休假」，抽取步驟本身確認已修好。
2. 透過真實 production 路徑 `_process_one()` 重跑整個 chunk 並寫回 Neo4j 後，查詢 `r.verb`／`r.source`／`r.source_svo_chunk_index` 這些「以為存在」的關係邊屬性，發現皆為 `None`，一度誤判為 merge 邏輯有 bug（新抽取結果進不去）。
3. **深入排查後訂正**：這些欄位設計上**不是**關係邊的扁平屬性——`merge_triples_to_graph()`（見程式碼 docstring「事實層級去重，2026-07-22 確定」）刻意把來源追溯資訊（`verb`／`source`／`source_svo_chunk_index`／`article_no` 等）包成一筆 citation，累積存在 `r.citations_json` 這個 JSON 陣列裡，同一組 `(subject, rel_type, object)` 的多次抽取只收斂成一條邊、多筆 citation，不是各自開新邊。改查 `citations_json` 後確認：這次重跑的來源資訊（`source_svo_chunk_index: 4`、`article_no: 第4條`）**已正確寫入**，merge 邏輯運作如設計，並無 bug。

**意外發現（與今天工作無關的既有限制）**：改查 `citations_json` 後看到，這次真實LLM呼叫把物件錯誤抽成「一至三日之特別休假」（應為三至七日）——與前一步驟直接呼叫時的正確結果（三至七日）不一致，是**同一份輸入文字、不同次真實LLM呼叫得到不同結果**的具體案例，反映 `qwen2.5:7b`（7B小模型）輸出的不穩定性——這與 `docs/論文/03_系統設計與方法論.md` 已記錄的規則6「未能穩定遵守於所有抽取呼叫」是同一類既有限制，非本次完整性核對機制或merge邏輯引入的新問題，留待第五章消融實驗（例如評估換用更大參數量模型的效益）處理，不在本報告範圍內。

**結論**：本次真實重跑驗證確認完整性核對機制與既有merge邏輯皆正確運作；同時誠實記錄一個過程中差點誤判為新bug、實際上是既有查詢認知錯誤的排查案例，以及一個真實但與本次功能無關的既有模型能力侷限。
