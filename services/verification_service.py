"""事實接地性核對（Fact-Grounded Verification）v1：偵測用、不自動重試。

對應 `docs/報告/16_事實接地性核對機制設計報告.md`、
`docs/論文/03_系統設計與方法論.md` § 3.6「設計提案」。生成回答完畢後，逐句
核對回答內容是否被本輪實際檢索到的 `Fact.fact_text` 支持——真實測試發現
既有的圖遍歷信心訊號（種子命中數／BFS 路徑長度）拓不到「證據已檢索到、
生成階段仍捏造內容」這種失效模式，需要獨立訊號。

Traceability: 03 §3.6（設計提案） -> 04（v1：`routers/agent.py::chat()` 串流
結束後呼叫，僅回傳核對結果，不觸發自動重新生成——v1 刻意縮小範圍，見報告
第 6 節「先切最小可行版」）。
Literature: RAGAS（Es et al., 2023/2024）Faithfulness 指標演算法（claim
decomposition + 逐句 NLI 式核對）的線上執行期延伸；AIS（Rashkin et al.）
可歸因性理論框架；Chain-of-Verification（Dhuliawala et al., 2023）佐證
prompt-only、不訓練驗證路線獨立於 Self-RAG 的訓練式反思標記。
Project: 本模組是本論文自行設計的 v1（句子層級拆解＋單次 LLM 判斷），非
RAGAS 官方兩階段流程（獨立的 claim decomposition LLM 呼叫 + 獨立的核對 LLM
呼叫）的直接程式碼移植——用既有 `parser.core.split_into_sentences()`
（規則式、免費）取代 RAGAS 的 LLM 式 claim decomposition，換取少一次 LLM
呼叫的成本，代價是句子層級的拆解粒度比 RAGAS 的原子陳述句粗（見
`verify_fact_grounding()` docstring 誠實侷限）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Sequence

from core.providers.base import LLMProvider
from parser.core import split_into_sentences


@dataclass(frozen=True)
class ClaimGrounding:
    statement: str
    supported: bool
    reason: str
    # 這句話是否為「需要被事實支持的具體主張」（含數字／期限／條件／結論）。
    # 引言句、章節標題、把問題原樣回貼、純過渡語等**不是主張**——它們天生
    # 不會被事實清單支持，但也不代表回答有問題（報告25 § 4 發現6→⑥ 診斷：
    # `chat()` 對這類非主張句誤觸發限制性重生成、把正確草稿改壞）。判準對齊
    # RAGAS Faithfulness（Es et al., 2023）與 Context-faithful Prompting
    # （Zhou et al., 2023, EMNLP Findings）「對抽取出的事實主張做核對」的作法，
    # 補上本函式 docstring 自述的「句 vs 原子主張」粒度侷限。
    # 缺省 True：分類不出來時當作主張處理（保守，讓重生成仍會對真問題觸發）。
    is_claim: bool = True


def _strip_json_fence(raw: str) -> str:
    cleaned = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL | re.IGNORECASE)
    return fence.group(1).strip() if fence else cleaned


def _grounding_prompt(
    sentences: Sequence[str],
    fact_texts: Sequence[str],
    *,
    question: str = "",
) -> str:
    facts_block = "\n".join(f"{i}. {text}" for i, text in enumerate(fact_texts, start=1))
    sentences_block = "\n".join(f"{i}. {text}" for i, text in enumerate(sentences, start=1))
    # A′（報告32 §9 G2）：核對「查表例外僅限逐字對照、且題目數值本身要逐字出現
    # 在事實清單或問題裡」需要看到問題本身。question 為空（裸單元測試）時省略此段，
    # prompt 與舊版逐字相同。
    question_block = f"使用者問題：{question}\n\n" if question.strip() else ""
    return f"""你是事實查核員。請核對「回答」裡的每一句陳述。

{question_block}已知事實：
{facts_block}

回答（已依句子拆分，逐句列出）：
{sentences_block}

對每一句先判斷 is_claim，再判斷 supported：

is_claim（這句是不是「需要被事實支持的具體主張」）：
- true：這句話對問題的答案做出了具體斷言——含數字、期限、金額、比例、條件、資格、是否允許、結論等。
- false：這句話不是需要被支持的主張——例如引言句（「根據提供的事實…」）、章節標題、把使用者的問題原樣回貼、純過渡語、對讀者的提醒。這類句子照原樣輸出、is_claim 給 false，不需要（也不會）被事實清單支持。

supported（僅在 is_claim 為 true 時才有意義；is_claim 為 false 時 supported 一律填 true）：
- true：這句主張的具體內容能在已知事實清單裡找到對應依據。
- true（明示查表推論例外）：若已知事實清單裡有一組「數值區間 → 對應值」的分段對照（例如「1 以上未滿 10 → 變量係數為 2」「10 以上未滿 100 → 變量係數為 1.5」這種分段對照表），而這句主張只是把問題給定的一個具體數值，對應到它所落在的那個區間、取該區間在清單裡明列的對應值，這種「把清單裡明列的分段對照表套用到題目給定的數值」算 supported=true。此例外僅限數值區間／門檻／分級的查表對應，且用到的每一列對照都必須逐字出現在事實清單裡（題目數值則須逐字出現在上方「使用者問題」或事實清單裡）。此例外只在「這句主張所用的數值，嚴格落在它所引用那一列明列的上下界之內」時成立——若這句主張取的是「最接近的一列」、或所用數值落在該列明列下界以下／上界以上、或落在相鄰兩列之間的間隙，都不算查表命中，一律依下面的 false 處理。
- false（含查表未命中）：這句主張的具體內容在已知事實清單裡找不到依據——除了上面「明示查表推論例外」那一種情形以外，即使主題相關、即使是合理推論，只要具體數字或結論沒有在清單裡出現過，就算 false，不可因為「聽起來合理」就判定 true。下列情形即使事實清單裡有分段對照表也一律算 false：(a) 這句主張所用的數值沒有落在任何一列明列的區間內；(b) 事實清單只出現了部分級距／部分區間（例如三級只給了兩級、對照表中間缺一段），而這句主張卻對沒被列出的那一段給了確定答案。這兩種情形的正確回答是承認查不到，挑一列硬套算未接地。

只輸出 JSON，不要輸出解釋。

輸出格式：
{{"claims":[{{"statement":"", "is_claim": true, "supported": true, "reason":""}}]}}
"""


async def verify_fact_grounding(
    answer_text: str,
    fact_texts: Sequence[str],
    llm_provider: LLMProvider | None,
    *,
    question: str = "",
) -> list[ClaimGrounding]:
    """核對 `answer_text` 逐句是否被 `fact_texts` 支持。

    `llm_provider` 為 `None`（例如尚未 `init_providers()` 的測試環境）時安全
    跳過，回傳空清單——比照 `extract_svo_triples()` 對可選 provider 的既有
    慣例，呼叫端據此判斷本次是否真的做過核對（空清單＝未核對，非「核對後
    判定全部接地」）。

    `fact_texts` 為空（本輪完全沒檢索到任何 Fact）時，不呼叫 LLM——沒有東西
    可供比對，直接把每句都標記為未接地，讓呼叫端能明確區分「有檢索但生成
    脫離證據」與「根本沒檢索到東西」兩種情境，不可靜默省略。

    LLM 回傳格式錯誤時，同樣不可假裝已核對過——每句標記為 `supported=False`
    並在 `reason` 註明核對本身失敗，不拋出例外中斷呼叫端的 SSE 串流回應。

    ✅ **`is_claim` 三分類（2026-09-02，報告25 § 4 發現6→⑥ 診斷）**：每句
    先判斷是不是「需要被事實支持的具體主張」（含數字／期限／條件／結論），
    再判斷 supported——引言句、章節標題、把問題原樣回貼等**非主張句**天生
    不會被事實清單支持，但也不代表回答有問題。呼叫端（`routers/agent.py::
    chat()`）據 `is_claim and not supported` 決定是否觸發限制性重生成，不再
    對非主張句誤觸發（3 輪真實診斷確認：`qwen2.5:7b` 常把問題當 markdown
    標題回貼，舊版逐句判定全數觸發重生成、把正確草稿改壞成「資料未明確
    記載」）。對齊 RAGAS Faithfulness（Es et al., 2023）／Context-faithful
    Prompting（Zhou et al., 2023）「對抽取出的事實主張做核對」的作法。

    ⚠️ **誠實侷限**：句子拆解仍用既有規則式 `split_into_sentences()`，不是
    RAGAS 的 LLM 式原子陳述句拆解——一個句子若包含多個獨立陳述，本函式只能
    整句判斷；`is_claim` 分類本身也由核對模型判定、可能誤判（把真主張判成
    非主張會漏掉該重生成的情況）。是否改用 LLM 拆解留待第五章消融實驗評估。

    `question`（keyword-only，2026-09-08 報告32 §9 A′）：供 `_grounding_prompt()`
    核對 G2「明示查表推論例外」的「題目數值須逐字出現」要求。未傳入時該半句
    退化為僅核對事實清單側，其餘行為與舊版逐字相同。
    """
    if llm_provider is None or not answer_text.strip():
        return []

    sentences = [s.strip() for s in split_into_sentences(answer_text) if s.strip()]
    if not sentences:
        return []

    if not fact_texts:
        return [
            ClaimGrounding(statement=s, supported=False, reason="本輪未檢索到任何 Fact 可供核對")
            for s in sentences
        ]

    raw = await llm_provider.generate_json(
        _grounding_prompt(sentences, fact_texts, question=question)
    )
    try:
        payload = json.loads(_strip_json_fence(raw))
        claims = payload.get("claims", []) if isinstance(payload, dict) else payload
        if not isinstance(claims, list):
            raise ValueError("接地性核對結果必須是 JSON list 或含 claims 的 object")
    except (json.JSONDecodeError, ValueError):
        return [
            ClaimGrounding(statement=s, supported=False, reason="核對機制本身輸出格式錯誤，無法判定")
            for s in sentences
        ]

    results: list[ClaimGrounding] = []
    for item in claims:
        if not isinstance(item, dict):
            continue
        # `is_claim` 缺省 True——舊版核對模型（或格式不符）沒給這個欄位時，
        # 當作主張處理，維持「有未接地就重生成」的既有保守行為。
        is_claim = bool(item.get("is_claim", True))
        # 非主張句（is_claim=False）永遠視為 supported——它天生不需要被事實
        # 支持，呼叫端據 `is_claim and not supported` 決定是否重生成。
        supported = True if not is_claim else bool(item.get("supported", False))
        results.append(ClaimGrounding(
            statement=str(item.get("statement", "")).strip(),
            supported=supported,
            reason=str(item.get("reason", "")).strip(),
            is_claim=is_claim,
        ))
    return results
