# -*- coding: utf-8 -*-
"""G2 方案 E：「數值區間 → 對應值」查表判斷的確定性覆核（報告32 §9 G2、
`docs/論文/03_系統設計與方法論.md` § 3.6 §G2、報告42 §6/§7）。

**動機**：G2 原本靠 prompt 指令＋`qwen2.5:7b` 判斷「問題數值是否落在事實清單
某段區間內」，`run_refusal_canary.py`（報告32 §9 C，2026-09-13）端到端驗證
證實 A/B/A′ 收緊（`a04f9ea`）沒有解決核心情境（P3 缺級距 0/3→0/3）、且 MRR
不降反升——判斷失效根因是「這類查表本質上不該交給弱 LLM judge」（RefusalBench，
Muhamed et al., 2025：Qwen 家族 selective-refusal 準確率全尺寸 <17%）。

**本模組做什麼**：純規則式（不呼叫 LLM）判斷「問題給的數值 vs 事實清單裡的
區間對照表」：① 嚴格落在某一列 → 該列的值是唯一正確答案；② 落在缺口／
超出所有列的範圍 → 正確答案是誠實拒答。回傳的判定用於 `routers/agent.py`
`chat()` 覆核接地核對的重生成觸發，不取代 `verify_fact_grounding()` 處理
其他題型。

**誠實侷限**：① 正則解析仰賴 `docs/報告/24_事實清單自然語言化機制設計報告.md`
既有的自然語言化句式慣例，非通用 NLP 解析器——樣式改變需同步更新（比照
`_MEASURE_PATTERN`／`_RANGE_COMPARATOR_PATTERN` 的既有取捨）。② 只處理
「單一數值 vs 一維分段區間表」，不處理多維度查表。③ `cn2an` 為第三方套件，
僅借用中文數字→阿拉伯數字轉換，不依賴其日期/分數/百分比等其他模式。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Literal

import cn2an

__all__ = [
    "IntervalFact",
    "LookupOverride",
    "parse_interval_facts",
    "extract_question_value",
    "evaluate_lookup_override",
    "is_refusal_text",
]

# 缺口案例（問題數值未落在任何一列明列區間內）強制重生成時的額外提示——
# 2026-09-13 真實測試發現：force_unsupported 觸發重生成後，若只沿用既有
# `_build_constrained_prompt()` 的一般查表指令（「可以取區間對應值作答」），
# 模型在「必須從清單推導出答案」的壓力下，**沒有誠實拒答，反而編造了一條
# 事實清單裡不存在的新區間**去湊出一個答案（比原本「挑錯值硬套」更嚴重的
# 新幻覺型態）。故缺口案例需要明確、不留模糊空間的額外指令，見報告42 §7。
GAP_REFUSAL_NOTE = (
    "特別注意：這一題的數值不在事實清單任何一列明列的區間上下界之內"
    "（不是「挑最接近的」、也不是「不同單位換算後可能對得上」的問題——"
    "就是沒有任何一列涵蓋它）。正確答案是誠實回答「資料未明確記載，"
    "無法確認」並說明是哪個數值查不到對應的區間，不要嘗試套用最接近的"
    "區間、不要推算、也絕對不要為了給出答案而編造事實清單裡沒有出現過的"
    "新區間或新數值。"
)

# 拒答措辭偵測（與 `run_refusal_canary.py`／報告32 §9 C 用的同一組標記一致，
# 避免生產碼與驗證 harness 對「什麼算拒答」認知分歧）。
_REFUSE_MARKERS = (
    "資料未明確記載", "無法確認", "未明確記載", "查不到", "沒有提到",
    "只有部分級距", "事實清單中沒有", "圖譜中無此數據", "無此資料",
)


def is_refusal_text(answer: str) -> bool:
    return any(m in answer for m in _REFUSE_MARKERS)


@dataclass(frozen=True)
class IntervalFact:
    """事實清單裡一則「區間 → 值」查表行的解析結果。"""

    lower: float
    upper: float | None  # None = 開放句式（只有下界，如「X 以上者 屬於 Z」）
    value: str
    raw_line: str


def _to_number(text: str) -> str:
    """中文數字→阿拉伯數字正規化（cn2an 只轉數字序列，不動其他文字）。"""
    try:
        return cn2an.transform(text, "cn2an")
    except Exception:
        # cn2an 對非數字/格式異常內容可能丟例外——正規化失敗時保留原文，
        # 讓後續正則對純阿拉伯數字內容仍可運作（寧可少轉換，不要整段掛掉）。
        return text


_NUM = r"[0-9]+(?:\.[0-9]+)?"

# 下界句式（有上界）："1 以上，未滿 10 的容許濃度 變量係數為 2"
#   數字1 以上 [、,，]? 未滿 數字2 [中間任意非句號內容，非貪婪] (為|＝|=) 值
_BOUNDED_PATTERN = re.compile(
    rf"(?P<lower>{_NUM})[^0-9，,。；;]{{0,10}}?以上[，,]?\s*未滿\s*(?P<upper>{_NUM})"
    rf"[^。\n]{{0,30}}?(?:為|＝|=)\s*(?P<value>{_NUM}|第{_NUM}級[^\s，,。]{{0,6}})"
)

# 開放句式（只有下界）："血中鉛濃度在10 μg/dl 以上者 屬於 第3級管理"
_OPEN_PATTERN = re.compile(
    rf"(?P<lower>{_NUM})[^0-9，,。；;]{{0,15}}?以上者?\s*屬於\s*"
    rf"(?P<value>第{_NUM}級[^\s，,。]{{0,10}}|{_NUM})"
)


def parse_interval_facts(fact_texts: list[str]) -> list[IntervalFact]:
    """從事實清單文字裡解析出所有「區間 → 值」查表行。非查表行忽略。"""
    results: list[IntervalFact] = []
    for raw in fact_texts:
        line = _to_number(raw)
        for m in _BOUNDED_PATTERN.finditer(line):
            lower = float(m.group("lower"))
            upper = float(m.group("upper"))
            if upper <= lower:
                continue  # 解析異常（如抓錯數字對），跳過而非硬湊
            results.append(IntervalFact(lower, upper, m.group("value"), raw))
        for m in _OPEN_PATTERN.finditer(line):
            lower = float(m.group("lower"))
            results.append(IntervalFact(lower, None, m.group("value"), raw))
    return results


# 問題裡「數字 + 選配單位」，優先抓緊鄰在「為／是」前後、或緊鄰量測單位的數字
# ——避免抓到問題句裡跟查表無關的數字（如「8 小時」的 8，那是時間單位不是
# 待查的濃度值）。
_QUESTION_VALUE_PATTERN = re.compile(
    rf"(?P<value>{_NUM})\s*(?P<unit>ppm|μg/dl|mg/m³|mg|公尺|公斤|公分|℃|%|％)?"
)

# 「小時」「次」「年」「月」「日」「星期」——這些後綴的數字通常是時間/頻率
# 描述，不是查表用的目標值，抓取時優先跳過。
_TIME_SUFFIX = re.compile(r"^\s*(?:小時|次|年|月|日|星期|個月|分鐘)")


def extract_question_value(question: str) -> float | None:
    """從問題文字抽取「待查表」的目標數值。優先選有量測單位的數字，
    其次選第一個非時間單位的數字；找不到則回傳 None（非這類題型）。"""
    normalized = _to_number(question)
    candidates: list[tuple[float, bool]] = []  # (value, has_measure_unit)
    for m in _QUESTION_VALUE_PATTERN.finditer(normalized):
        tail = normalized[m.end():]
        if _TIME_SUFFIX.match(tail):
            continue
        has_unit = bool(m.group("unit"))
        try:
            candidates.append((float(m.group("value")), has_unit))
        except ValueError:
            continue
    if not candidates:
        return None
    with_unit = [v for v, has_unit in candidates if has_unit]
    return with_unit[0] if with_unit else candidates[0][0]


@dataclass(frozen=True)
class LookupOverride:
    decision: Literal["force_supported", "force_unsupported", "no_override"]
    # 缺口案例（沒有任何區間命中，正確答案就是拒答）觸發 force_unsupported
    # 時，帶上 `GAP_REFUSAL_NOTE`——重生成 prompt 要塞這段，明確禁止编造
    # 新區間；「命中區間但挑錯值」的 force_unsupported 不帶（既有查表指令
    # 已足夠，見 2026-09-13 第一輪測試 P5 0/3→3/3 的正面結果）。
    extra_prompt_note: str | None = None


def evaluate_lookup_override(
    question: str,
    fact_texts: list[str],
    draft_answer: str,
    is_refusal: Callable[[str], bool],
) -> LookupOverride:
    """回傳對 `chat()` 重生成觸發的覆核建議：

    - ``"force_supported"``：確定性判斷認為草稿已經答對（或正確地誠實拒答），
      即使 judge 判未接地，也不該觸發重生成。
    - ``"force_unsupported"``：確定性判斷認為草稿答錯（挑錯值／缺口硬套／
      該答卻拒答），即使 judge 判已接地，也該觸發重生成去修正。缺口案例
      （`extra_prompt_note` 非 None）必須把這段提示塞進重生成 prompt，
      否則模型可能在「必須從清單推導」的壓力下編造新區間（見上方常數
      docstring、報告42 §7 的真實案例）。
    - ``"no_override"``：解析不出查表結構、或問題抓不到目標數值——不是
      這類題型，維持 judge 原判。
    """
    intervals = parse_interval_facts(fact_texts)
    if not intervals:
        return LookupOverride("no_override")
    q_value = extract_question_value(question)
    if q_value is None:
        return LookupOverride("no_override")

    matched: IntervalFact | None = None
    for f in intervals:
        if f.upper is not None:
            if f.lower <= q_value < f.upper:
                matched = f
                break
        else:
            if q_value >= f.lower:
                matched = f
                break

    refused = is_refusal(draft_answer)
    normalized_answer = _to_number(draft_answer)

    if matched is not None:
        # 有明確命中的區間——正確答案應該是這一列的值。既有查表指令已足夠
        # 引導修正，不需要額外提示。
        got_it_right = matched.value in normalized_answer
        if got_it_right and not refused:
            return LookupOverride("force_supported")
        return LookupOverride("force_unsupported")

    # 沒有任何區間命中（落在缺口或超出所有已知級距）——正確答案應該是
    # 誠實拒答；草稿若給出任何一個查表值當確定答案，視為挑錯值硬套。
    if refused:
        return LookupOverride("force_supported")
    any_value_stated = any(f.value in normalized_answer for f in intervals)
    if any_value_stated:
        return LookupOverride("force_unsupported", GAP_REFUSAL_NOTE)
    return LookupOverride("no_override")
