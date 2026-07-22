"""代名詞消解——前四後二雙向上下文標準化，含 POS＋正則雙軌代名詞偵測與
背景 LLM 詞庫自動進化。

對應 `docs/報告/05_指代消解與前處理任務書.md`（雙向上下文視窗機制、LLM
prompt 設計）與 `docs/報告/10_代名詞雙軌檢測與正則詞庫自動進化機制設計
報告.md`（POS＋正則雙軌偵測、Unmapped 詞背景審核，2026-07-21 使用者決策
採用，取代 05 任務書單一正則設計已知的「其/該」誤觸發限制）。

3.4 §a Behavior Tree 對應：`PRONCHECK`（雙軌偵測）→ `PRONLLM`（雙向上下文
LLM 消解）／`BYPASS`（直接通過）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from core.providers.base import LLMProvider

# 正則詞庫（可由 audit_unmapped_pronoun 通過審核後動態擴充）。
# 05 任務書已知限制之一（複數代名詞缺漏）已在此補上：他們/她們/它們。
DEFAULT_PRONOUN_LEXICON: frozenset[str] = frozenset({
    "他", "她", "它", "其", "該", "這家", "這名", "那名", "前者", "後者", "上述",
    "他們", "她們", "它們",
})

PAST_CONTEXT_SIZE = 4
FUTURE_CONTEXT_SIZE = 2


class PosTagger(Protocol):
    """詞性標註介面——10 報告依賴 spaCy `PRON`/`DET` 標籤（Universal
    Dependencies 標準），以介面注入取代直接依賴 spaCy，讓雙軌判讀邏輯可
    離線測試，不需要真的安裝 spaCy 才能驗證判讀邏輯本身。"""

    def pronoun_tokens(self, sentence: str) -> list[str]:
        """回傳句子中所有 POS 標註為 `PRON` 或 `DET` 的詞（表面字串）。"""
        ...


class SpacyPosTagger:
    """spaCy 官方 POS 標註實作（預設 `zh_core_web_sm`，Universal
    Dependencies `PRON`/`DET` 標籤）。延遲匯入 spaCy——只有真的建立此類別
    時才需要 spaCy 已安裝，模組其餘部分（含所有離線可測的雙軌判讀邏輯）
    不因 spaCy 未安裝而無法匯入或測試。

    ⚠️ 本專案目前尚未安裝 spaCy／`zh_core_web_sm`（見 `requirements.txt`
    新增項目與安裝指引），此類別本身未在自動化測試中實際驗證，僅測試過
    其依賴注入的 `PosTagger` 介面（以 Fake 實作覆蓋）。
    """

    def __init__(self, model_name: str = "zh_core_web_sm"):
        import spacy  # noqa: PLC0415 -- 刻意延遲匯入，見類別 docstring
        self._nlp = spacy.load(model_name)

    def pronoun_tokens(self, sentence: str) -> list[str]:
        doc = self._nlp(sentence)
        return [token.text for token in doc if token.pos_ in ("PRON", "DET")]


@dataclass
class PronounDetectionResult:
    has_pronoun: bool
    unmapped_tokens: list[str] = field(default_factory=list)


def detect_pronoun(
    sentence: str,
    lexicon: frozenset[str] = DEFAULT_PRONOUN_LEXICON,
    pos_tagger: PosTagger | None = None,
) -> PronounDetectionResult:
    """雙軌比對三路分流（10 報告 § 3.1）：

    - 正則命中 → 確定含代名詞（`unmapped_tokens` 為空，免驚動 POS 標註器）
    - 正則未命中、POS 命中 → 視為含代名詞（避免正則詞庫不完整造成漏抓），
      POS 抓到但正則未收錄的詞記入 `unmapped_tokens`，供背景詞庫審核
    - 兩者皆未命中 → 不含代名詞（Bypass，0 成本）

    `pos_tagger` 為 `None`（未注入標註器，例如 spaCy 尚未安裝／不需要這層
    保障的場合）時只依賴正則判斷，退化為 05 任務書原始的單一正則設計，
    仍可正常運作，只是失去雙軌互補的召回率保障。
    """
    regex_hit = any(word in sentence for word in lexicon)
    if pos_tagger is None:
        return PronounDetectionResult(has_pronoun=regex_hit)

    pos_tokens = pos_tagger.pronoun_tokens(sentence)
    unmapped = [t for t in pos_tokens if t not in lexicon]
    return PronounDetectionResult(has_pronoun=regex_hit or bool(pos_tokens), unmapped_tokens=unmapped)


# ── 背景 LLM 詞庫自動進化（10 報告 § 3.2 Async LLM Lexicon Auditor）─────────

def load_custom_lexicon(path: Path) -> set[str]:
    """讀取自動進化後的正則詞庫（`custom_pronoun_lexicon.txt`），檔案不存在
    時回傳空集合。呼叫端應與 `DEFAULT_PRONOUN_LEXICON` 聯集後再傳入
    `detect_pronoun()`，本函式不負責合併。"""
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def append_to_lexicon(path: Path, word: str) -> None:
    """把審核通過的詞追加寫入詞庫檔案，已存在則不重複寫入。"""
    existing = load_custom_lexicon(path)
    if word in existing:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(word + "\n")


async def audit_unmapped_pronoun(word: str, sentence: str, llm_provider: LLMProvider) -> bool:
    """背景 LLM 詞庫審核器：判斷 POS 命中但正則未收錄的詞，在此句子的用法
    下是否為有效指代詞，決定是否該動態追加至正則詞庫。回傳 `True` 代表
    審核通過；本函式只判斷，寫入詞庫檔案由呼叫端（`resolve_coreference_
    pipeline`）視回傳值決定是否呼叫 `append_to_lexicon()`。"""
    prompt = (
        f"句子：「{sentence}」\n"
        f"詞語：「{word}」\n"
        "這個詞在此句子中是否作為代名詞或指代詞使用（例如：他、它、該、這家"
        "之類，用來指代前後文提到的具體對象）？只回答「是」或「否」，"
        "不要有其他文字。"
    )
    answer = (await llm_provider.generate(prompt)).strip()
    return answer.startswith("是")


# ── 前四後二雙向上下文標準化（05 任務書 § 3-4）───────────────────────────────

def _build_prompt(past_context: list[str], target: str, future_context: list[str]) -> str:
    past_text = "\n".join(f"- {s}" for s in past_context) or "(無)"
    future_text = "\n".join(f"- {s}" for s in future_context) or "(無)"
    return f"""你是一個文字標準化助手。
任務：參考【前文】或【後文】的實體資訊，將【目標句子】中模糊的代名詞（如：他、她、它、該、這、其）替換為明確的實體名稱。

規則：
1. 優先從【前文】尋找指代對象。若【前文】找不到，請從【後文】尋找首次出現的具體名稱（如：後文若有「SpaceX」，目標句的「這家公司」應替換為「SpaceX」）。
2. 只修改【目標句子】中的指代詞，不要修改其他文字，亦不要合併或拆分句子。
3. 不要輸出任何解釋或多餘的引言。只輸出修改後的句子本身。

【前文（歷史資訊）】
{past_text}

【目標句子】
{target}

【後文（後續資訊）】
{future_text}

【修改後句子】"""


async def resolve_coreference_pipeline(
    sentences: list[str],
    llm_provider: LLMProvider | None = None,
    *,
    lexicon: frozenset[str] = DEFAULT_PRONOUN_LEXICON,
    pos_tagger: PosTagger | None = None,
    lexicon_auditor_provider: LLMProvider | None = None,
    custom_lexicon_path: Path | None = None,
) -> list[str]:
    """指代消解標準化前處理管線（05 任務書 § 4.1，2026-07-21 改用 10 報告的
    雙軌偵測取代單一正則）。

    對每句話：雙軌偵測是否含代名詞；有則打包「前 4 句已標準化 + 當前句 +
    後 2 句原始」呼叫 LLM 消解（實體接力：前文用的是已標準化過的句子，讓
    後續句子的消解品質隨佇列累積而提升）；無則直接通過。偵測到 POS 命中但
    正則未收錄的 unmapped 詞時，背景觸發詞庫審核（需同時提供
    `lexicon_auditor_provider` 與 `custom_lexicon_path`），審核通過就寫入
    詞庫檔案，供下次直接命中正則、不需再依賴 POS 標註器（詞庫隨系統運作
    逐步完善，見 10 報告 § 3.2）。

    `llm_provider` 為 `None` 時（未提供實際消解用的 LLM），含代名詞的句子
    直接原樣通過，不強行消解——讓離線管線與單元測試可以安全呼叫，行為與
    `services/svo_service.py::extract_svo_triples()` 對可選 provider 的
    處理方式一致。
    """
    total = len(sentences)
    final_sentences: list[str] = []

    for i, sentence in enumerate(sentences):
        detection = detect_pronoun(sentence, lexicon, pos_tagger)

        if detection.has_pronoun and llm_provider is not None:
            past_context = final_sentences[max(0, i - PAST_CONTEXT_SIZE):i]
            future_context = sentences[i + 1: min(total, i + 1 + FUTURE_CONTEXT_SIZE)]
            normalized = (await llm_provider.generate(
                _build_prompt(past_context, sentence, future_context)
            )).strip()
            final_sentences.append(normalized)
        else:
            final_sentences.append(sentence)

        if detection.unmapped_tokens and lexicon_auditor_provider is not None and custom_lexicon_path is not None:
            for word in detection.unmapped_tokens:
                if await audit_unmapped_pronoun(word, sentence, lexicon_auditor_provider):
                    append_to_lexicon(custom_lexicon_path, word)

    return final_sentences
