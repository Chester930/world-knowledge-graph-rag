"""N4 的數值／類別／子句守衛（報告160 U1 自 ``services.svo_service`` 搬入，行為不變；含被實體去重共用的樣式建構）。"""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Sequence

from core.kg_config import GuardConfig
from models.knowledge_graph import SVOTriple
from services.extraction.traditional import (
    _to_traditional,
)

# 沿用舊 logger 名稱，確保搬移前後的 log 記錄（name／訊息）完全相同。
logger = logging.getLogger("services.svo_service")

# 中文數字（含全形／半形阿拉伯數字混用）＋常見單位的量詞片語粗略偵測，
# 不要求完全精確（寧可多檢查幾個非量詞片語，也不要漏掉真正的量詞片語）。
_QUANTITY_PATTERN = re.compile(
    r"[〇零一二三四五六七八九十百千萬0-9]+"
    r"(?:至[〇零一二三四五六七八九十百千萬0-9]+)?"
    # 「等級」（2026-09-16，任務C第3組候選真實案例）：N0060041 §8「第一等級
    # 至第七等級」被抽成「第一等級至第十等級」——「十等級」逐字取自同文件
    # 完全不同的第34條，屬跨條文數字挪用，跟「三至七日」錯抽「一至三日」
    # （報告19§10）同一種根因，但原本的單位清單沒收「等級」，這個片語從未
    # 被 `_QUANTITY_PATTERN` 掃描到，數值忠實性核對因此對這筆三元組完全失效。
    r"(?:日|月|年|次|小時|分鐘|百分之|％|%|元|倍|等級)"
)

# 比 `_QUANTITY_PATTERN` 更寬的「分段量詞」偵測——多收「歲／人／名／週／度／
# 種／類／條／款／項／點」等法規列舉分段常用的單位。原設計**只給
# `resolve_entity_name()` 的模糊合併守衛用**（報告25 §4 發現C／診斷 Q3），
# 2026-09-05（報告26 §4 #6）新增第二個用途：`_naturalization_dropped_
# quantity()` 借用同一組樣式核對自然語言化輸出是否遺漏量詞/日期片語，
# 兩個用途共用同一份「量詞/日期片語」定義，不必另建一份重複清單：
# `年齡未滿六歲者`／`年齡六歲以上未滿十二歲者`／`年齡十二歲以上未滿十五歲者`
# 這種「字面高度相似、分段值不同」的主詞，被 `_edit_ratio` 0.80／cosine 0.88
# 誤併成一個節點，三段工時上限（二／三／四小時）全接到同一個節點、
# `natural_text` 還被寫錯段。`_QUANTITY_PATTERN` 刻意不動（發現3 的
# `_quantity_mis_bound_to_clause`／報告20 的 `_contains_ungrounded_quantity`
# 對「數量忠實性」的語意較窄，混進「歲／人／條」會擴大它們的誤判面）。
_CJK_NUMBER_PATTERN = r"[〇零一二三四五六七八九十百千萬0-9]+"
_MEASURE_NUMBER_PATTERN = _CJK_NUMBER_PATTERN + r"(?:至" + _CJK_NUMBER_PATTERN + r")?"
_RANGE_NUMBER_GAP_PATTERN = r"[^，,。；;、（）()]{0,12}?"


def _regex_token_alternation(tokens: tuple[str, ...]) -> str:
    """把 domain token 清單轉成安全的正則 alternation。

    空清單使用永不匹配的分支，避免 domain pack 清空詞彙後意外把守衛變成
    「匹配所有字串」的空 alternation。
    """
    return "|".join(re.escape(token) for token in tokens) or r"(?!)"


@lru_cache(maxsize=128)
def _compile_measure_pattern(units: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(
        _MEASURE_NUMBER_PATTERN
        + rf"(?:{_regex_token_alternation(units)})"
    )


def _build_measure_pattern(cfg: GuardConfig) -> re.Pattern[str]:
    """以固定 CJK 數字／範圍結構注入 domain 單位詞。"""
    return _compile_measure_pattern(cfg.measure_units)

# 數字＋（選配單位）＋「以上／以下／以內／未滿／超過」的比較句式偵測
# （報告29 §2.4／§4.3，2026-09-05，報告26 §4 #3 Q8 真實根因診斷）。法規門檻／
# 級距表（變量係數表、罰鍰級距等）常見寫法如「1 以上，未滿 10」「100 以上，
# 未滿 1000」——數字後面接的是比較詞而非 `_MEASURE_PATTERN` 認得的單位，
# 結構上抓不到，導致整段級距表在 `resolve_entity_name()` 被模糊合併壞（真實
# 案例：N0060004 容許暴露標準變量係數表 5 段被併成 2 個節點，其中一個同時
# 掛 3 個互相矛盾的係數值，Q8 需要的「1以上未滿10→2」完全從圖中消失）。
# 跟 `_MEASURE_PATTERN` 同樣只給 `resolve_entity_name()` 的模糊合併守衛用、
# 同樣是早退機制（見該函式 §4.3 設計說明：量詞類實體只准精確比對，不同數值
# range 之間沒有「同類可合併」的中間地帶，跟 `_SCOPE_MODIFIER_PATTERN` 的
# 雙向過濾機制不同）。
#
# v2（報告32 §9.3 F2，2026-09-07）：v1 的 `[數字]\s*(以上|以下|以內)` 要求數字
# 與比較詞相鄰（只允許空白），中間夾一個單位就失效——真實案例 `血中鉛濃度在
# 十 μg/dl 以上者` 被誤併進 `五 μg/dl 以上未達十 μg/dl`（第一級），「≥10→第三級」
# 事實從圖中消失（報告32 Q6）。改為在數字與比較詞之間允許至多 12 個非標點字元
# （非貪婪），涵蓋 `十 μg/dl 以上`、`二十公尺 以上`、`五百平方公尺 以上`；
# 既有「1 以上，未滿 10」等案例無迴歸（`\s*` 是新字元類的子集）。
@lru_cache(maxsize=128)
def _compile_range_comparator_pattern(
    trailing_comparators: tuple[str, ...], leading_comparators: tuple[str, ...]
) -> re.Pattern[str]:
    return re.compile(
        _CJK_NUMBER_PATTERN
        + _RANGE_NUMBER_GAP_PATTERN
        + rf"(?:{_regex_token_alternation(trailing_comparators)})"
        + "|"
        + rf"(?:{_regex_token_alternation(leading_comparators)})"
        + _RANGE_NUMBER_GAP_PATTERN
        + _CJK_NUMBER_PATTERN
    )


def _build_range_comparator_pattern(cfg: GuardConfig) -> re.Pattern[str]:
    """以固定至多 12 個非標點字元結構注入比較詞。"""
    return _compile_range_comparator_pattern(
        cfg.range_trailing_comparators, cfg.range_leading_comparators
    )

# 序數／分數／小數／附表列舉守衛（報告32 §9.3 F3b，2026-09-07）——`_MEASURE_PATTERN`
# （要單位）與 `_RANGE_COMPARATOR_PATTERN`（要比較詞）都抓不到的列舉主詞：
# `第三級管理`（`級` 不在 `_MEASURE_PATTERN`，vs `第一級管理`）、`二分之一`／`五分之一`、
# WBGT 溫度 `30.6℃`／`32.6℃`、變量係數 `1.25`／`1.5`、`附表一`／`附表二`、
# `精密作業之一`／`精密作業之三`。同 `_RANGE_COMPARATOR_PATTERN` 走早退（這類名稱
# 本身即精確列舉標記，不該跟任何東西模糊合併）。F3a「補 `_MEASURE_PATTERN` 單位表」
# 刻意不做：`_MEASURE_PATTERN` 已被 `_naturalization_dropped_quantity()`（報告26 §4 #6）
# 共用，擴大它會連帶讓自然語言化核對更嚴——`級` 走這裡、`公尺／μg/dl` 走 v2 的單位間隔。
# 2026-09-18（任務C第9組真實重抽）：`具顯著／中度／低度風險者` 是封閉列舉值，彼此只差一字；
# 曾把原文正確抽出的「具低度風險者」模糊合併成「具中度風險者」，造成第三類事業的 Fact 錯接。
# 三種風險值加入同一精確比對守衛，防止列舉成員跨值合併。
@lru_cache(maxsize=128)
def _compile_enum_guard_pattern(closed_values: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(
        r"第[〇零一二三四五六七八九十百千0-9]+級"
        r"|[〇零一二三四五六七八九十百千0-9]+分之[〇零一二三四五六七八九十百千0-9]+"
        r"|[0-9]+\.[0-9]+"
        r"|附表[〇零一二三四五六七八九十0-9]+"
        r"|之[〇零一二三四五六七八九十]+$"
        + rf"|(?:{_regex_token_alternation(closed_values)})風險"
    )


def _build_enum_guard_pattern(cfg: GuardConfig) -> re.Pattern[str]:
    """以固定序數／分數／小數／附表結構注入封閉列舉值。"""
    return _compile_enum_guard_pattern(cfg.enum_closed_values)

# 範圍修飾詞守衛（報告29 §4.1／報告32 §9.3，2026-09-07）——「基礎量 vs 遞增量」：
# `每一型式` vs `每增加一種型式`（`_edit_ratio`＝0.727、不含任何量詞，`_MEASURE_PATTERN`／
# `_RANGE_COMPARATOR_PATTERN` 都不命中）。「增加／額外／追加／新增／逾／超出」這個修飾詞把
# 「基礎量」改成「遞增量」，語意相反、表面極相似。與 `_MEASURE_PATTERN`／§4.3 的早退不同：
# 此處做**雙向過濾**——比對迴圈前依「是否含範圍修飾詞」把候選清單與 `name` 分同異兩類、
# 只保留同類候選再比對（含修飾詞的彼此仍可正常合併，不含的彼此也是）。
@lru_cache(maxsize=128)
def _compile_scope_modifier_pattern(words: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(_regex_token_alternation(words))


def _build_scope_modifier_pattern(cfg: GuardConfig) -> re.Pattern[str]:
    return _compile_scope_modifier_pattern(cfg.scope_modifier_words)


# 向後相容的 shipped-default aliases：既有測試與少量內部唯讀呼叫仍可直接
# inspect `.pattern`／`.search()`；正式判定路徑在下方依 cfg 建構對應 pattern。
_DEFAULT_GUARD_CONFIG = GuardConfig()
_MEASURE_PATTERN = _build_measure_pattern(_DEFAULT_GUARD_CONFIG)
_RANGE_COMPARATOR_PATTERN = _build_range_comparator_pattern(_DEFAULT_GUARD_CONFIG)
_ENUM_GUARD_PATTERN = _build_enum_guard_pattern(_DEFAULT_GUARD_CONFIG)
_SCOPE_MODIFIER_PATTERN = _build_scope_modifier_pattern(_DEFAULT_GUARD_CONFIG)


def _has_scope_modifier(name: str, *, pattern: re.Pattern[str] | None = None) -> bool:
    return (pattern or _SCOPE_MODIFIER_PATTERN).search(name) is not None


def _contains_ungrounded_quantity(text: str, source_text: str) -> bool:
    """`docs/報告/20_抽取數值忠實性核對機制設計報告.md` §3：偵測 `text`
    （三元組 subject 或 object）裡是否含有數量／期限用字，且該片段未逐字
    出現在 `source_text`（chunk 原文）裡——真的偵測到才回傳 True。

    根因（報告20 §2）：同一份輸入文字，不同次真實LLM呼叫可能產生不同
    結果（temperature=0 不保證LLM推論決定性輸出，Horace He 2025），真實
    案例是把「三至七日」錯抽成同文件另一條文的「一至三日」。純字串比對
    刻意不用embedding——數量用字需要精確比對，語意相似度比對反而會讓
    結構相似但數值不同的片語被誤判為語意相近而放行。
    """
    for match in _QUANTITY_PATTERN.finditer(text):
        if match.group() not in source_text:
            return True
    return False


# 假別（請假類型）詞彙家族（2026-09-16，任務C第2組候選真實案例）——
# N0030006 §7「事假期間不給工資」／§8「公假…工資照給」被抽成「產假期間
# 不給工資」／「產假期間照給工資」，但整份文件完全沒有「產假」的實質
# 規定，「產假」一詞只出現在完全不同的條文（§9 流產請假參照句）。跟
# `_QUANTITY_PATTERN` 抓的數字挪用同一種根因（同文件跨條文借用），差別
# 只在挪用的是類別名詞而非數字——重跑同一 chunk 3 次結果完全不變，是
# 決定性 bug 不是隨機雜訊，單純重試無法修正，需要字面比對守衛。
# 詞彙互斥（同一子句只會屬於其中一種假別），比照 `_rival_quantity()`
# 的手法，純字串比對，不需 embedding。
_LEAVE_TYPE_FAMILY: tuple[str, ...] = (
    "事假", "病假", "公假", "婚假", "喪假", "產假", "陪產假",
    "育嬰留職停薪", "特別休假", "公傷病假", "普通傷病假",
)

# 目前只驗證過假別這一組家族；未來若發現其他「同文件跨條文借用類別
# 名詞」的真實案例（例如職災等級／給付類別），比照這裡加一份新家族
# tuple 再併進本清單即可，不需改動比對邏輯本身。
_ENTITY_FAMILIES: tuple[tuple[str, ...], ...] = (_LEAVE_TYPE_FAMILY,)


def _rival_family_term(term: str, family: Sequence[str], source_text: str) -> str | None:
    """`family`（互斥類別詞彙表）裡除了 `term` 以外，是否有其他成員逐字
    出現在 `source_text`——有的話回傳第一個，代表三元組本該用這個詞彙。"""
    for other in family:
        if other != term and other in source_text:
            return other
    return None


def _contains_ungrounded_family_term(text: str, source_text: str) -> bool:
    """比照 `_contains_ungrounded_quantity()`：`text`（三元組 subject 或
    object）裡若含有 `_ENTITY_FAMILIES` 任一互斥類別詞彙表裡的詞，但該詞
    未逐字出現在 `source_text`（chunk 原文）、且家族裡「另一個」成員卻
    出現在原文——判定為跨條文借用，回傳 True。

    只在「另一個成員確實存在於原文」時才觸發，避免對『這份文件根本沒提到
    任何家族詞彙』的正常三元組誤殺（比照報告20/25 的降級哲學：寧可漏抓，
    不可誤殺）。
    """
    for family in _ENTITY_FAMILIES:
        for term in family:
            if term in text and term not in source_text:
                if _rival_family_term(term, family, source_text) is not None:
                    return True
    return False


# 條號／列舉項目的起始標記（「一、」「（一）」「1.」等）與句末標點，切子句
# 時一併當分隔點——讓「一、三十日以上：於十日前提出。二、未滿三十日：於
# 五日前提出。」被切成兩個獨立子句，而非黏成一句、使子句層級綁定核對失效。
_CLAUSE_SPLIT_PATTERN = re.compile(
    r"[。；\n]+"
    r"|(?=[一二三四五六七八九十]+、)"
    r"|(?=（[一二三四五六七八九十]+）)"
    r"|(?=\d+[.、)])"
)

_BINDING_NORMALIZE_PATTERN = re.compile(r"[\s、，。：:；「」（）()【】]")

# 子句層級綁定核對只對「夠有辨識度」的 subject 觸發：正規化後長度未達此值
# 的 subject（多為「受僱者」「雇主」「勞工」這類角色詞，且常在具體子句中被
# 省略）不做綁定判斷，避免誤殺——見 docs/報告/25 §4 發現3。
_MIN_BINDING_SUBJECT_LEN = 4


def _split_into_clauses(text: str) -> list[str]:
    """把一段原文切成子句（依句末標點與列舉項目起始標記）。"""
    return [seg.strip() for seg in _CLAUSE_SPLIT_PATTERN.split(text) if seg and seg.strip()]


def _normalize_for_binding(text: str) -> str:
    """比對子句綁定時的輕度正規化：去空白與常見標點、並統一轉繁體，讓
    subject 與子句用字的細微標點差異、以及抽取 LLM 偶發的簡繁混用
    （`qwen2.5:7b` 對繁體輸入有時輸出簡體字，見報告25 §4 發現4）不影響
    substring 判斷——否則簡體 subject 在繁體原文裡永遠找不到歸屬子句，
    子句層級綁定核對會被這個守衛條件靜默略過（報告25 §4 發現3 收尾發現）。"""
    return _BINDING_NORMALIZE_PATTERN.sub("", _to_traditional(text))


_BINDING_UNITS = ("百分之", "小時", "分鐘", "日", "月", "年", "次", "％", "%", "元", "倍")


def _quantity_unit(phrase: str) -> str:
    """取數量片語結尾的單位（「十日前」的 phrase 是 `_QUANTITY_PATTERN` 抓到的
    「十日」，回傳「日」）。取不到回傳空字串。"""
    for unit in _BINDING_UNITS:
        if phrase.endswith(unit):
            return unit
    return ""


def _rival_quantity(phrase: str, clause_texts: Sequence[str]) -> str | None:
    """`clause_texts` 裡是否有「與 `phrase` 同單位、但不同值」的競爭數量片語。
    有的話回傳第一個，代表三元組本該用這個值。"""
    unit = _quantity_unit(phrase)
    if not unit:
        return None
    for text in clause_texts:
        for other in _QUANTITY_PATTERN.findall(text):
            if other != phrase and _quantity_unit(other) == unit:
                return other
    return None


def _quantity_mis_bound_to_clause(
    triple: SVOTriple, source_text: str, original_sentences: Sequence[str] | None,
) -> bool:
    """`docs/報告/25_擴大版新舊KG問答品質比對報告.md` §4 發現3：把報告20 的
    數值忠實性核對從「字詞層級」擴充到「子句層級綁定」。

    報告20 的 `_contains_ungrounded_quantity()` 只檢查數量/期限用字有沒有
    逐字出現在 chunk 原文裡——但真實失效案例（報告25 Q7「每增加一種型式
    加收八千元」實為四千元、Q2「三十日以上於五日前提出」實為十日前）中，
    錯誤數字**確實逐字出現在同一 chunk 的另一個列舉子句**，字詞層級核對
    因此放行。

    子句層級綁定核對：對三元組 verb＋object 裡的每個數量片語 Q，找出原文中
    逐字包含 Q 的子句（Q 的「歸屬子句」）。若同時滿足——
      (1) subject 夠有辨識度（正規化後長度 ≥ `_MIN_BINDING_SUBJECT_LEN`）、
          在原文裡確實有自己的歸屬子句；
      (2) subject 的歸屬子句與 Q 的歸屬子句**完全不相交**；
      (3) subject 的歸屬子句裡帶著一個「同單位、不同值」的競爭數字
          （三元組本該用它）；
    ——才判定 Q 是從別的列舉子句挪過來錯接，回傳 True（應丟棄）。

    條件 (3) 是關鍵的誤殺防線：像「給予三至七日之特別休假：一、<條件>」
    這種「數字在共用句幹、條件在列舉項目」的正常法條，條件子句本身沒有
    競爭數字，不會被誤判。

    保守設計（寧可漏抓、不可誤殺，比照報告19/20 的降級哲學）：任一條件
    不成立就回傳 False。子句切分優先用 `original_sentences`（再各自切子句），
    沒有時退回切 `source_text`。純字串比對，不需額外 LLM／embedding 呼叫。
    """
    subj_norm = _normalize_for_binding(triple.subject)
    if len(subj_norm) < _MIN_BINDING_SUBJECT_LEN:
        return False

    units = list(original_sentences) if original_sentences else [source_text]
    clauses: list[str] = []
    for unit in units:
        clauses.extend(_split_into_clauses(unit))
    if not clauses:
        return False

    clauses_norm = [(_normalize_for_binding(c), c) for c in clauses]
    subject_clauses = [(cn, orig) for cn, orig in clauses_norm if subj_norm in cn]
    if not subject_clauses:
        # subject 在原文裡找不到對應子句（多為 coref 正規化後的標準名）：
        # 無從判斷綁定對錯，不丟。
        return False
    subject_clause_keys = {cn for cn, _ in subject_clauses}
    subject_clause_texts = [orig for _, orig in subject_clauses]

    for phrase in _QUANTITY_PATTERN.findall(f"{triple.verb}{triple.object}"):
        home_keys = {cn for cn, orig in clauses_norm if phrase in orig}
        if not home_keys or not subject_clause_keys.isdisjoint(home_keys):
            continue
        if _rival_quantity(phrase, subject_clause_texts) is not None:
            return True
    return False


_RISK_LEVEL_BY_BUSINESS_CATEGORY = {
    "第一類事業": "顯著風險",
    "第二類事業": "中度風險",
    "第三類事業": "低度風險",
}


def _risk_category_misbound_to_clause(
    triple: SVOTriple, source_text: str, original_sentences: Sequence[str] | None,
) -> bool:
    """攔截事業類別與風險等級從相鄰列舉項目錯接的三元組。

    只在三元組明確提到單一類別和單一風險等級、原文同一類別子句含有
    另一個等級，且抽出的等級實際屬於其他類別子句時才丟棄。這個窄條件
    避免影響同時比較多個類別的三元組，或來源沒有明確對應關係的內容。
    """
    triple_text = _normalize_for_binding(f"{triple.subject} {triple.verb} {triple.object}")
    categories = [
        (category, level)
        for category, level in _RISK_LEVEL_BY_BUSINESS_CATEGORY.items()
        if _normalize_for_binding(category) in triple_text
    ]
    levels = [
        level for level in _RISK_LEVEL_BY_BUSINESS_CATEGORY.values()
        if _normalize_for_binding(level) in triple_text
    ]
    if len(categories) != 1 or len(levels) != 1:
        return False

    category, expected_level = categories[0]
    observed_level = levels[0]
    if observed_level == expected_level:
        return False

    units = list(original_sentences) if original_sentences else [source_text]
    clauses = [
        _normalize_for_binding(clause)
        for unit in units
        for clause in _split_into_clauses(unit)
    ]
    category_norm = _normalize_for_binding(category)
    expected_norm = _normalize_for_binding(expected_level)
    observed_norm = _normalize_for_binding(observed_level)
    category_clauses = [clause for clause in clauses if category_norm in clause]
    if not any(expected_norm in clause for clause in category_clauses):
        return False

    observed_belongs_to_sibling = any(
        observed_norm in clause
        and any(
            _normalize_for_binding(other_category) in clause
            for other_category in _RISK_LEVEL_BY_BUSINESS_CATEGORY
            if other_category != category
        )
        for clause in clauses
    )
    return observed_belongs_to_sibling


def _filter_ungrounded_quantity_triples(
    triples: list[SVOTriple], source_text: str,
    original_sentences: Sequence[str] | None = None,
) -> list[SVOTriple]:
    """丟棄含未忠實數量/期限用字、跨條文借用類別詞彙、或列舉值錯接的三元組。

    四層核對：

    1. **字詞層級**（報告20）：subject／object 的數量用字未逐字出現於原文
       → 丟（跨條文數字挪用，如「三至七日」錯抽成「一至三日」）。
    2. **子句層級綁定**（報告25 §4 發現3）：數量用字逐字出現在原文、但
       出現它的子句與三元組 subject 的歸屬子句不相交 → 丟（數字錯接到
       別的列舉項目，如 Q7「每增加一種型式加收八千元」實為四千元）。
    3. **類別詞彙家族**（2026-09-16，任務C第2組候選）：subject／object 含
       `_ENTITY_FAMILIES` 裡的詞、該詞未逐字出現於原文、但家族裡另一個
       詞卻出現於原文 → 丟（假別跨條文借用，如「事假」被抽成「產假」）。
    4. **列舉子句類別值綁定**（2026-09-18，任務C第9組候選）：三元組將
       正確出現在同一 chunk 的風險等級接到錯誤事業類別，且來源子句明確
       顯示該值屬於相鄰類別 → 丟（「第三類事業」被配成「具中度風險者」）。

    寧可漏抓一筆有疑慮的三元組，也不留下錯誤數字污染圖譜（比照 3.1.3
    REJECT 不阻斷整體、report16/19 既有的降級哲學）。

    2026-08-31（見 docs/報告/21_抽取管線稽核與修正報告.md）：丟棄的三元組
    會記錄一筆 warning——上線首日完全沒有留下任何線索，無法統計這次修正
    實際攔了幾筆、也無法區分「這個chunk本來就沒有數量用字」跟「有數量
    用字但被攔下來了」，稽核時發現這是本機制自己需要補的缺口。
    """
    kept: list[SVOTriple] = []
    for t in triples:
        if _contains_ungrounded_quantity(t.subject, source_text) or _contains_ungrounded_quantity(
            t.object, source_text
        ):
            logger.warning(
                "[數值忠實性核對] 丟棄疑似跨段落挪用數字的三元組：'%s' -[%s]-> '%s'",
                t.subject, t.verb, t.object,
            )
            continue
        if _contains_ungrounded_family_term(t.subject, source_text) or _contains_ungrounded_family_term(
            t.object, source_text
        ):
            logger.warning(
                "[類別詞彙忠實性核對] 丟棄疑似跨條文借用類別詞彙的三元組：'%s' -[%s]-> '%s'",
                t.subject, t.verb, t.object,
            )
            continue
        if _quantity_mis_bound_to_clause(t, source_text, original_sentences):
            logger.warning(
                "[數值忠實性核對] 丟棄數字錯接到別的列舉子句的三元組：'%s' -[%s]-> '%s'",
                t.subject, t.verb, t.object,
            )
            continue
        if _risk_category_misbound_to_clause(t, source_text, original_sentences):
            logger.warning(
                "[列舉類別值忠實性核對] 丟棄類別與值錯接的三元組：'%s' -[%s]-> '%s'",
                t.subject, t.verb, t.object,
            )
            continue
        kept.append(t)
    return kept
