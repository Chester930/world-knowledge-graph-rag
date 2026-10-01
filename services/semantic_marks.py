"""「未知／不適用／尚未處理」標示的查詢時派生規則（報告212 L2）。**PROVISIONAL，未接線。**

純運算、無 I/O：不匯入 `neo4j`／`core`／`routers`／其他 `services` 模組，不讀檔、不連線、不改 `os.environ`。
型別查表（核心 52／擴充 939）由呼叫端傳入，避免本模組讀取 `data/schema_org_entity_types.json`。

⚠️ **零行為變更**：目前除測試與 `scripts/analysis/semantic_marks_coverage.py` 外，沒有任何程式匯入或呼叫本模組；
不得接進 `chat()`、`merge_*`、`extract_*`、檢索或任何現有路徑（接線屬使用者尚未決定的 Phase 1）。

⚠️ **PROVISIONAL**：下列標示名稱與值域是報告201 §0 的暫定操作型定義，使用者尚未決定欄位名與值域；
它們只是函式回傳值，**不得作為哨兵字串寫回任何資料**（尤其 `source_article_no`：哨兵會令 Fact 靜默消失，報告201 §3.3）。
可逆：「概念」的處理以 `concept_scheme` 參數表示，不寫死。
"""

from __future__ import annotations

import re
from typing import Iterable, Mapping, Sequence

PROVISIONAL = True

RESOLVED = "已解決"
NOT_APPLICABLE = "不適用"
UNKNOWN = "未知"
PENDING = "尚未處理"
INDETERMINATE = "無法由現有資料判定"
MARKS = (RESOLVED, NOT_APPLICABLE, UNKNOWN, PENDING, INDETERMINATE)

CONCEPT_PLACEHOLDER = "概念"
CONCEPT_SCHEMES = ("A", "B", "strict")  # A：視為未知佔位（預設）；B：視為已解決；strict：無法判定

_GENERIC_RELATION = "RELATED_TO"


# ── 共用：空白判斷（明確比較，不依賴真假值）──────────────────────────────────
def is_blank(value: object) -> bool:
    """`None` 或只含空白的字串視為空。非字串（例如數字）不視為空。"""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


# ── ① 實體型別 ───────────────────────────────────────────────────────────────
def normalize_type_key(value: str) -> str:
    """與 `services/extraction/prompt.py::_normalize_type_key` 相同的比對鍵（本模組自行實作，不匯入）。"""
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def classify_entity_type_value(
    raw_type: str | None, core_lookup: Mapping[str, str], ext_lookup: Mapping[str, str]
) -> str:
    """回傳 `empty`／`concept_only`／`standard`／`standard_with_concept`／`outside_raw`。

    `core_lookup`／`ext_lookup` 的鍵須已用 `normalize_type_key` 正規化。多值型別以逗號分隔。
    """
    if is_blank(raw_type):
        return "empty"
    tokens = [t.strip() for t in str(raw_type).split(",")]
    tokens = [t for t in tokens if t != ""]
    if not tokens:
        return "empty"
    has_concept = any(t == CONCEPT_PLACEHOLDER for t in tokens)
    others = [t for t in tokens if t != CONCEPT_PLACEHOLDER]
    if not others:
        return "concept_only"
    for t in others:
        key = normalize_type_key(t)
        if key not in core_lookup and key not in ext_lookup:
            return "outside_raw"
    return "standard_with_concept" if has_concept else "standard"


def mark_entity_type(
    raw_type: str | None,
    core_lookup: Mapping[str, str],
    ext_lookup: Mapping[str, str],
    concept_scheme: str = "A",
) -> str:
    """實體型別 → 標示。

    空值＝未知；標準型別（含與「概念」並列）＝已解決；schema.org 之外原字串＝尚未處理
    （報告201 §1.1 指出無法分辨「尚未對應」與「已判定非 schema.org」，此為操作型對應）；
    「概念」單獨出現依 `concept_scheme`：A→未知、B→已解決、strict→無法由現有資料判定。
    本版沒有「不適用」的型別判定（報告201 §1.2：是否存在待使用者決定）。
    """
    if concept_scheme not in CONCEPT_SCHEMES:
        raise ValueError(f"concept_scheme 必須是 {CONCEPT_SCHEMES} 之一，收到 {concept_scheme!r}")
    cat = classify_entity_type_value(raw_type, core_lookup, ext_lookup)
    if cat == "empty":
        return UNKNOWN
    if cat in ("standard", "standard_with_concept"):
        return RESOLVED
    if cat == "outside_raw":
        return PENDING
    if concept_scheme == "A":
        return UNKNOWN
    if concept_scheme == "B":
        return RESOLVED
    return INDETERMINATE


# ── ② 關係型別 ───────────────────────────────────────────────────────────────
def mark_relation_type(rel_type: str | None) -> str:
    """關係型別 → 標示。

    非 `RELATED_TO`＝已解決；`RELATED_TO`＝來源不明＝無法由現有資料判定（使用者已同意接受，報告212 §1-2）；
    空／缺值同樣無法判定。**不接受也不使用 `verb_embedding`**：它不是兜底專屬標記（報告201 §2.1）。
    """
    if is_blank(rel_type):
        return INDETERMINATE
    if str(rel_type).strip() == _GENERIC_RELATION:
        return INDETERMINATE
    return RESOLVED


# ── ③ source_article_no（文件層判定，不使用哨兵字串）────────────────────────────────
def has_article_no(value: object) -> bool:
    """明確判斷是否為「有內容的條號字串」：僅非空白字串為真。不依賴 `None`／空字串的真假值。"""
    return isinstance(value, str) and value.strip() != ""


def document_has_any_article_no(article_nos: Iterable[object]) -> bool:
    """文件層：該文件任一引用有條號，則該文件「適用條號」。"""
    for value in article_nos:
        if has_article_no(value):
            return True
    return False


def mark_article_no(article_no: object, document_applicable: bool) -> str:
    """單筆引用 → 標示（以文件層是否適用條號判斷）。

    有條號＝已解決；無條號且文件適用＝未知；無條號且整份文件都沒有條號＝不適用。
    """
    if has_article_no(article_no):
        return RESOLVED
    if document_applicable is True:
        return UNKNOWN
    return NOT_APPLICABLE


def mark_citations_by_document(citations_by_doc: Mapping[str, Sequence[object]]) -> dict[str, int]:
    """文件 → 各引用 `article_no` 清單；回傳各標示的引用數。"""
    out = {m: 0 for m in MARKS}
    for article_nos in citations_by_doc.values():
        applicable = document_has_any_article_no(article_nos)
        for value in article_nos:
            out[mark_article_no(value, applicable)] += 1
    return out


# ── ④ 空主詞／空受詞／空 verb ────────────────────────────────────────────────
def mark_fact_fields(subject: str | None, obj: str | None, verb: str | None) -> str:
    """Fact 欄位完整性 → 標示（報告209 嚴格規則）。

    三欄皆非空＝已解決（完整，無需標示）；空受詞且空 verb（不論主詞）＝未知；
    其餘至少一欄為空＝尚未處理（需人工／LLM 才能分「不適用」與「未知」）。
    """
    empty_subject = is_blank(subject)
    empty_object = is_blank(obj)
    empty_verb = is_blank(verb)
    if empty_object and empty_verb:
        return UNKNOWN
    if empty_subject or empty_object or empty_verb:
        return PENDING
    return RESOLVED
