"""語意 NLI 式 gold exact_span 比對備援（Semantic Span Matcher，報告52 後續修正）。

`atomic_scorer.py`／`lineage_tracker.py` 原本只做逐字子字串比對——對逐字錨定
法規原文的 chunk-RAG 基準（M1/M2）公平，但對報告24自然語言化管線改寫過用詞
的 Fact-RAG/KG 答案（M3/M4）系統性低估（報告52：17-Q1 案例，回答內容完全
正確卻因未逐字複製法規句式被判失敗；18-Q5 顯示連 M1 都會踩到同一機制，
證明這不是 KG 獨有問題，只是 KG 的上游輸入已經改寫過一次，中招機率更高）。

本模組只在逐字比對失敗時，才補呼叫一次 judge LLM 做「這段話的具體內容是否
已在文字中以任何用詞方式被表達」的蘊含式核對，複用 `verification_service.py`
既有的 judge-prompt 設計模式（is_claim/supported 二階判斷的姊妹版）。逐字
命中的項目不受影響、不多花 LLM 呼叫——只用來救回「語意正確但用詞不同」的
偽陰性，不會把原本命中的項目判掉。
"""
from __future__ import annotations

import json
import re
from typing import Sequence

from core.providers.base import LLMProvider


def clean_text(text: str) -> str:
    """去除空格、換行、標點以進行標準化字串包含比對（與舊版逐字比對規則一致）"""
    if not text:
        return ""
    return re.sub(r"[\s\n\r\t，。、；：：「」『』\"\'\(\)（）]", "", text)


def _strip_json_fence(raw: str) -> str:
    cleaned = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL | re.IGNORECASE)
    return fence.group(1).strip() if fence else cleaned


def _prompt(pool_text: str, spans: Sequence[str], *, question: str = "") -> str:
    spans_block = "\n".join(f"{i}. {s}" for i, s in enumerate(spans, start=1))
    question_block = f"使用者問題：{question}\n\n" if question.strip() else ""
    return f"""你是嚴格的法規事實比對員。請判斷下面每一條「待核事實」的具體內容
（數字、期限、條件、結論），是否已經在「文字」中以任何用詞方式被表達出來
（可以是換句話說、自然語言化改寫，只要具體內容一致就算 true；若只是主題
相關、或具體數字/結論不同，一律 false，不可因為聽起來合理就判 true）。

{question_block}文字：
{pool_text}

待核事實：
{spans_block}

只輸出 JSON，不要輸出解釋。
輸出格式：{{"results":[{{"index":1,"present":true}}]}}
"""


async def match_spans_with_fallback(
    pool_text: str,
    spans: Sequence[str],
    judge_llm_provider: LLMProvider | None,
    *,
    question: str = "",
) -> tuple[list[str], list[str]]:
    """回傳 `(hit_spans, missed_spans)`。

    先對每個 span 做逐字子字串比對；仍缺漏、且提供 `judge_llm_provider` 時，
    才對缺漏項目**一次性批次**補呼叫語意蘊含核對。`judge_llm_provider=None`
    或 `pool_text` 為空時，直接回傳逐字比對結果（與舊版行為逐位元相同）。

    LLM 回傳格式錯誤時保守視為未核對成功——維持缺漏判定，不假裝已核對過。
    """
    hit: list[str] = []
    remaining: list[str] = []
    clean_pool = clean_text(pool_text)
    for span in spans:
        if clean_text(span) in clean_pool:
            hit.append(span)
        else:
            remaining.append(span)

    if not remaining or judge_llm_provider is None or not pool_text.strip():
        return hit, remaining

    raw = await judge_llm_provider.generate_json(
        _prompt(pool_text, remaining, question=question)
    )
    try:
        payload = json.loads(_strip_json_fence(raw))
        results = payload.get("results", []) if isinstance(payload, dict) else payload
        if not isinstance(results, list):
            raise ValueError("語意核對結果必須是 JSON list 或含 results 的 object")
    except (json.JSONDecodeError, ValueError):
        return hit, remaining

    present_indices: set[int] = set()
    for item in results:
        if isinstance(item, dict) and item.get("present") is True:
            idx = item.get("index")
            if isinstance(idx, int):
                present_indices.add(idx)

    still_missed: list[str] = []
    for i, span in enumerate(remaining, start=1):
        if i in present_indices:
            hit.append(span)
        else:
            still_missed.append(span)
    return hit, still_missed
