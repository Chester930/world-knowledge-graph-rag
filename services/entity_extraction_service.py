"""具名提及抽取（NER）——3.4 §a `REGISTRY`／`ALIASCHECK` 階段的上游依賴，
spaCy NER 為主、正則兜底補漏的混合式抽取，產出
`entity_registry_service.apply_registry()` 所需的 `mentions`。

對應 docs/論文/03_系統設計與方法論.md § 3.4 §a：`REGISTRY` 節點維護「文件內
已出現具名實體」登記表，但登記表本身要有東西可登記，得先知道每句話裡有哪些
具名提及——這正是本模組要補的上游缺口（見
`docs/報告/06_SVO抽取管線調整任務書.md` 第 4 節「具名提及抽取（NER）」待辦）。

**設計取捨（2026-07-23 使用者決策：混合式，非純 LLM／純 spaCy）**：
- spaCy NER（`doc.ents`）免費、可整份文件一次跑完，複用
  `pronoun_resolution_service.py` 已引入的 `zh_core_web_sm` 模型精神，不新增
  依賴；代價是中文 small model 準確度有限，且對「I-35」這類數字/字母混合
  代號型實體的召回率不可靠（spaCy 的 NER 傾向以命名實體語料訓練，這類技術
  代號不在典型訓練分佈內）。
- 正則兜底只補 spaCy 常見漏抓的代號型 pattern（連續大寫字母＋連字號＋數字），
  刻意不追求全面覆蓋任意實體類型，避免正則本身抓進大量雜訊、把成本問題轉嫁
  給下游 `ALIASCHECK`／`ALIASLLM`。
- 純 LLM-based NER（逐句呼叫 LLM）被否決：會打破現有管線「規則式優先、篩不
  出來才呼叫 LLM」的省成本慣例（`PRONCHECK`／`ALIASCHECK` 皆是此設計）。

**為何刻意偏召回率（recall）而非精確率（precision）**：漏抓的具名提及永遠
不會進入 §a `ALIASCHECK`，之後沒有任何機制可以回頭補救；反之抓錯或抓多的
候選，下游 `ALIASCHECK`／`ALIASLLM` 本身就有比對機制可以緩衝——
`entity_registry_service.resolve_mention()` 對字面不重疊、登記表又找不到
規則命中的提及一律走 `NEWENT` 新增一筆，最壞情況只是多一個候選 Key，不會
誤 merge 到既有實體。

⚠️ **誠實侷限**：與 `pronoun_resolution_service.SpacyPosTagger` 相同，本
專案目前尚未安裝 spaCy／`zh_core_web_sm`（見 `requirements.txt`），
`SpacyNerTagger` 本身未在自動化測試中實際驗證，僅測試過其依賴注入介面
（`NerTagger` Protocol，以 Fake 實作覆蓋）。`_CODE_PATTERN` 正則兜底本身
只認一種明確 pattern，中文人名/地名/組織名等一般具名實體若 spaCy 未安裝
（`ner_tagger=None`）則完全抓不到，此時 §a 別名登記表僅能收斂代號型實體。
"""
from __future__ import annotations

import re
from typing import Protocol

from services.entity_registry_service import Mention

# spaCy NER 標籤 → 本系統既有的粗粒度中文分類。entity_type 目前系統全域無
# 強制分類清單（core/constants.py 未定義任何實體類型常數，其餘欄位皆預設
# 「概念」，見 09 報告與 entity_registry_service 模組 docstring），此處只做
# 低成本的常見類別對應，其餘標籤一律歸「概念」，不追求完整覆蓋 spaCy 全部
# 標籤——分類粒度對 §a 的 PROMOTE／ALIASCHECK 邏輯無影響（皆只用字面比對），
# 純粹是 metadata。
_SPACY_LABEL_MAP: dict[str, str] = {
    "PERSON": "人物",
    "ORG": "組織",
    "GPE": "地點",
    "LOC": "地點",
    "FAC": "地點",
}

# 正則兜底：連續大寫字母（1-5 碼）＋連字號／各式破折號＋數字起頭的代號型
# 實體，spaCy 中文 NER 常見漏抓對象（如「I-35」「ISO-9001」）。刻意保守，
# 只認這一種明確 pattern。
_CODE_PATTERN = re.compile(r"\b[A-Z]{1,5}[\-‐-―]\d[\w\-]*\b")


class NerTagger(Protocol):
    """具名提及抽取介面——比照 `pronoun_resolution_service.PosTagger` 的
    依賴注入模式，讓抽取邏輯可離線測試，不需要真的安裝 spaCy 才能驗證判讀
    邏輯本身。"""

    def entities(self, sentence: str) -> list[tuple[str, str]]:
        """回傳句子中偵測到的 (mention 文字, entity_type) 清單。"""
        ...


class SpacyNerTagger:
    """spaCy 官方 NER 實作（預設 `zh_core_web_sm`）。延遲匯入 spaCy——只有
    真的建立此類別時才需要 spaCy 已安裝，模組其餘部分（含所有離線可測的
    抽取/兜底邏輯）不因 spaCy 未安裝而無法匯入或測試。

    ⚠️ 本專案目前尚未安裝 spaCy／`zh_core_web_sm`，此類別本身未在自動化
    測試中實際驗證，僅測試過其依賴注入的 `NerTagger` 介面（以 Fake 實作
    覆蓋）。
    """

    def __init__(self, model_name: str = "zh_core_web_sm"):
        import spacy  # noqa: PLC0415 -- 刻意延遲匯入，見類別 docstring
        self._nlp = spacy.load(model_name)

    def entities(self, sentence: str) -> list[tuple[str, str]]:
        doc = self._nlp(sentence)
        return [(ent.text, _SPACY_LABEL_MAP.get(ent.label_, "概念")) for ent in doc.ents]


def _regex_entities(sentence: str, already_found: set[str]) -> list[tuple[str, str]]:
    """規則式兜底：抓 spaCy 常見漏抓的代號型實體，跳過已在 `already_found`
    中的字面（避免同一句內重複登記同一提及）。"""
    found: list[tuple[str, str]] = []
    for match in _CODE_PATTERN.finditer(sentence):
        text = match.group(0)
        if text in already_found:
            continue
        already_found.add(text)
        found.append((text, "概念"))
    return found


def extract_mentions(sentences: list[str], ner_tagger: NerTagger | None) -> list[list[Mention]]:
    """對句子清單逐句抽取具名提及，組成
    `entity_registry_service.apply_registry()` 所需的
    `mentions: list[list[Mention]]`（逐句對應，無提及的句子為空列表）。

    `ner_tagger` 為 `None` 時（spaCy 尚未安裝／不需要這層保障的場合）只跑
    正則兜底，退化為「只抓得到代號型實體」的最小版本，仍可正常運作，只是
    失去 spaCy NER 的召回率保障——與
    `pronoun_resolution_service.detect_pronoun()` 對 `pos_tagger=None` 的
    處理方式一致。
    """
    result: list[list[Mention]] = []
    for idx, sentence in enumerate(sentences):
        seen: set[str] = set()
        mentions: list[Mention] = []

        if ner_tagger is not None:
            for text, entity_type in ner_tagger.entities(sentence):
                text = text.strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                mentions.append(Mention(sentence_idx=idx, text=text, entity_type=entity_type))

        for text, entity_type in _regex_entities(sentence, seen):
            mentions.append(Mention(sentence_idx=idx, text=text, entity_type=entity_type))

        result.append(mentions)
    return result
