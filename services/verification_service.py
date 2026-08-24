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


def _strip_json_fence(raw: str) -> str:
    cleaned = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL | re.IGNORECASE)
    return fence.group(1).strip() if fence else cleaned


def _grounding_prompt(sentences: Sequence[str], fact_texts: Sequence[str]) -> str:
    facts_block = "\n".join(f"{i}. {text}" for i, text in enumerate(fact_texts, start=1))
    sentences_block = "\n".join(f"{i}. {text}" for i, text in enumerate(sentences, start=1))
    return f"""你是事實查核員。請核對「回答」裡的每一句陳述，是否被「已知事實」清單支持。

已知事實：
{facts_block}

回答（已依句子拆分，逐句列出）：
{sentences_block}

對每一句判斷 supported：
- true：這句話陳述的具體內容（包含數字、期限、結論等細節）能在已知事實清單裡找到對應依據。
- false：這句話陳述的具體內容在已知事實清單裡找不到依據——即使主題相關、即使是合理推論，只要具體數字或結論沒有在清單裡出現過，就算 false，不可因為「聽起來合理」就判定 true。

只輸出 JSON，不要輸出解釋。

輸出格式：
{{"claims":[{{"statement":"", "supported": true, "reason":""}}]}}
"""


async def verify_fact_grounding(
    answer_text: str,
    fact_texts: Sequence[str],
    llm_provider: LLMProvider | None,
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

    ⚠️ **誠實侷限**：句子拆解用既有規則式 `split_into_sentences()`，不是
    RAGAS 原始演算法的 LLM 式原子陳述句拆解——一個句子若包含多個獨立陳述，
    本函式只能整句判斷 supported/false，無法只標記其中錯誤的那個子陳述；
    是否改用 LLM 拆解留待第五章消融實驗評估是否值得多一次 LLM 呼叫的代價。
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

    raw = await llm_provider.generate_json(_grounding_prompt(sentences, fact_texts))
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
        results.append(ClaimGrounding(
            statement=str(item.get("statement", "")).strip(),
            supported=bool(item.get("supported", False)),
            reason=str(item.get("reason", "")).strip(),
        ))
    return results
