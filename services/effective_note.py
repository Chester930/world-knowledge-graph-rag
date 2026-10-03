"""報告267／268 的施行備註純函式（PROVISIONAL、零接線、不連線）。

本模組只做純運算；不讀寫檔案、不使用目前時間，``as_of`` 一律由呼叫端傳入。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Sequence

_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_NUM = "零〇一二三四五六七八九十百"
DATE_RE = re.compile(rf"(?:中華民國)?([{_NUM}]+)年([{_NUM}]+)月([{_NUM}]+)日")
UNDETERMINED = "施行日期以命令定之"
ART_NUM = r"\d+(?:-\d+)?"
ART_ITEM = rf"{ART_NUM}(?:[～~]{ART_NUM})?"
ART_RE = re.compile(rf"第({ART_ITEM}(?:、{ART_ITEM})*)條")
APPX = r"附表[一二三四五六七八九十]+"
APPX_LOC_RE = re.compile(rf"^(?:條文)?(?:之)?({APPX}(?:編號[{_NUM}、]+)?(?:及{APPX})?(?:、{APPX})*)")
PARA_LOC_RE = re.compile(r"^(?:條文)?(第[\d、～~]+項)")
ARTICLE_NO_RE = re.compile(rf"{ART_NUM}")

STATUS_IN_FORCE = "in_force"
STATUS_NO_INFORMATION = "no_information"
STATUS_PENDING_WHOLE = "pending_whole"
STATUS_PENDING_PARTIAL = "pending_partial"
STATUS_UNDETERMINED = "undetermined"


@dataclass(frozen=True)
class ArticleEffectiveStatus:
    """單一條文相對於呼叫端 ``as_of`` 的施行狀態。"""

    status: str
    effective_from: str | None
    locators: tuple[str, ...]
    ops: tuple[str, ...]


def _validate_as_of(as_of: str) -> None:
    if not isinstance(as_of, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of):
        raise ValueError("as_of 必須是 YYYY-MM-DD 字串")
    try:
        date.fromisoformat(as_of)
    except ValueError as exc:
        raise ValueError("as_of 必須是有效的 YYYY-MM-DD 日期") from exc


def cn_to_int(text: str) -> int:
    """中文數字（至百位，如「一百十六」）轉為整數。"""
    total = section = num = 0
    for ch in text:
        if ch in _DIGITS:
            num = _DIGITS[ch]
        elif ch == "十":
            section += (num or 1) * 10
            num = 0
        elif ch == "百":
            section += (num or 1) * 100
            num = 0
        else:
            raise ValueError(f"無法解析的中文數字：{text!r}")
    return total + section + num


def roc_to_iso(text: str) -> str:
    """把備註中的民國年月日轉為 ISO 日期。"""
    match = DATE_RE.search(text)
    if not match:
        raise ValueError(f"找不到民國日期：{text!r}")
    year, month, day = (cn_to_int(group) for group in match.groups())
    return date(year + 1911, month, day).isoformat()


def normalize(note: str | None) -> str:
    """移除備註中的空白，保留其餘文字。"""
    return re.sub(r"\s+", "", note or "")


def art_key(article_no: str) -> tuple[int, int]:
    """回傳條號的排序鍵。"""
    first, _, second = article_no.partition("-")
    return int(first), int(second or 0)


def fmt_article(article_no: str) -> str:
    """將條號格式化為既有分析輸出的形式。"""
    return f"第 {article_no} 條"


def expand_articles(spec: str, known: Sequence[str]) -> list[str]:
    """依該文件已知條號展開條號範圍，端點即使不在清單也保留。"""
    known_set = set(known)
    out: list[str] = []
    for item in spec.split("、"):
        parts = re.split(r"[～~]", item)
        if len(parts) == 1:
            out.append(parts[0])
            continue
        lo, hi = art_key(parts[0]), art_key(parts[1])
        inside = sorted((key for key in known_set if lo <= art_key(key) <= hi), key=art_key)
        for endpoint in parts:
            if endpoint not in known_set and known:
                inside.append(endpoint)
        out.extend(sorted(set(inside), key=art_key) if known else parts)
    return out


def parse_provisions(text: str, known: Sequence[str]) -> list[dict[str, Any]]:
    """從文字抽出條文、項／附表定位與操作別。"""
    out: list[dict[str, Any]] = []
    for match in ART_RE.finditer(text):
        tail = text[match.end():]
        locator, scope = None, "article"
        appendix = APPX_LOC_RE.match(tail)
        paragraph = PARA_LOC_RE.match(tail)
        if appendix:
            locator, scope = appendix.group(1), "appendix"
        elif paragraph:
            locator, scope = paragraph.group(1), "paragraph"
        head = text[max(0, match.start() - 6):match.start()]
        op = "增訂" if "增訂" in head else "刪除" if "刪除" in head else "修正"
        for article_no in expand_articles(match.group(1), known):
            out.append({"article_no": article_no, "locator": locator, "scope": scope, "op": op})
    return out


def parse_effective_note(note: str | None, known_articles: Sequence[str] = ()) -> dict[str, Any]:
    """解析施行備註；非法日期以 ``unparsed`` 和 ``errors`` 回傳，不向外拋例外。"""
    text = normalize(note)
    if not text:
        return {"kind": "empty", "items": [], "all_dates": [], "max_date": None}
    if UNDETERMINED in text:
        return {"kind": "undetermined", "items": [], "all_dates": [], "max_date": None}
    try:
        all_dates = sorted({roc_to_iso(match.group(0)) for match in DATE_RE.finditer(text)})
        rule_match = re.search(r"依第[\d\-]+條規定[:：]", text)
        preamble, rule = (text[:rule_match.start()], text[rule_match.end():]) if rule_match else (text, text)
        base = {"all_dates": all_dates, "max_date": all_dates[-1] if all_dates else None}
        staged = re.search(rf"除(.+?)外[，,]自({DATE_RE.pattern})施行", rule)
        items: list[dict[str, Any]] = []
        full_text = re.search(r"全文\d+條", preamble) is not None
        if staged:
            default_date = roc_to_iso(staged.group(2))
            exceptions = staged.group(1)
            for segment in re.finditer(rf"([^自]+?)自({DATE_RE.pattern})施行", exceptions):
                segment_date = roc_to_iso(segment.group(2))
                provisions = parse_provisions(re.sub(r"^[，,及]+", "", segment.group(1)), known_articles)
                items.extend({**provision, "effective_date": segment_date, "origin": "exception"} for provision in provisions)
            pre_items = parse_provisions(preamble, known_articles)
            listed = pre_items if not full_text else [
                {"article_no": article_no, "locator": None, "scope": "article", "op": "修正"}
                for article_no in known_articles
            ]
            items.extend({**provision, "effective_date": default_date, "origin": "default"} for provision in listed)
            return {"kind": "staged", "default_date": default_date, "items": items, **base}
        single = re.search(rf"自({DATE_RE.pattern})施行|定自({DATE_RE.pattern})施行", rule)
        if single:
            effective_date = roc_to_iso(single.group(0))
            provisions = parse_provisions(preamble, known_articles)
            items = [{**provision, "effective_date": effective_date, "origin": "single"} for provision in provisions]
            return {"kind": "single", "default_date": effective_date, "items": items, **base}
        return {"kind": "unparsed", "items": [], **base}
    except ValueError as exc:
        return {"kind": "unparsed", "items": [], "all_dates": [], "max_date": None, "errors": [str(exc)]}


def pending_items(parsed: Mapping[str, Any], as_of: str) -> list[dict[str, Any]]:
    """回傳施行日嚴格晚於 ``as_of`` 且非刪除的項目。"""
    _validate_as_of(as_of)
    return [item for item in parsed.get("items", []) if item["effective_date"] > as_of and item["op"] != "刪除"]


def consistency(parsed: Mapping[str, Any], effective_date: str | None) -> dict[str, Any]:
    """核對文件層 YYYYMMDD 施行日與解析出的最晚日期。"""
    doc_iso = f"{effective_date[:4]}-{effective_date[4:6]}-{effective_date[6:]}" if effective_date and len(effective_date) == 8 else None
    return {"document_effective_date": doc_iso, "parsed_max_date": parsed.get("max_date"),
            "consistent": (doc_iso == parsed.get("max_date")) if doc_iso or parsed.get("max_date") else True}


def _article_key(article_no: str) -> str:
    normalized = re.sub(r"[第條\s]", "", article_no)
    if not ARTICLE_NO_RE.fullmatch(normalized):
        raise ValueError(f"無法解析的條號：{article_no!r}")
    return normalized


def _unique(values: Sequence[str | None]) -> tuple[str, ...]:
    return tuple(value for index, value in enumerate(values) if value and value not in values[:index])


def article_effective_status(parsed: Mapping[str, Any], article_no: str, as_of: str) -> ArticleEffectiveStatus:
    """推導單一條文的五種施行狀態；不改變 ``parsed``。"""
    _validate_as_of(as_of)
    if parsed.get("kind") == "undetermined":
        return ArticleEffectiveStatus(STATUS_UNDETERMINED, None, (), ())
    if parsed.get("kind") in {"empty", "unparsed"}:
        return ArticleEffectiveStatus(STATUS_NO_INFORMATION, None, (), ())
    target = _article_key(article_no)
    pending = [item for item in pending_items(parsed, as_of) if item.get("article_no") == target]
    if not pending:
        return ArticleEffectiveStatus(STATUS_IN_FORCE, None, (), ())
    whole = all(item.get("op") == "增訂" and item.get("scope") == "article" for item in pending)
    status = STATUS_PENDING_WHOLE if whole else STATUS_PENDING_PARTIAL
    return ArticleEffectiveStatus(
        status,
        min(item["effective_date"] for item in pending),
        _unique([item.get("locator") for item in pending]),
        _unique([item.get("op") for item in pending]),
    )


def document_effective_status(parsed: Mapping[str, Any], as_of: str) -> str:
    """推導文件層狀態：``has_pending`` 表示至少一條尚未施行。"""
    _validate_as_of(as_of)
    if parsed.get("kind") == "undetermined":
        return STATUS_UNDETERMINED
    if parsed.get("kind") in {"empty", "unparsed"}:
        return STATUS_NO_INFORMATION
    return "has_pending" if pending_items(parsed, as_of) else STATUS_IN_FORCE


__all__ = [
    "ArticleEffectiveStatus", "STATUS_IN_FORCE", "STATUS_NO_INFORMATION", "STATUS_PENDING_WHOLE",
    "STATUS_PENDING_PARTIAL", "STATUS_UNDETERMINED", "article_effective_status", "art_key", "cn_to_int",
    "consistency", "document_effective_status", "expand_articles", "fmt_article", "normalize",
    "parse_effective_note", "parse_provisions", "pending_items", "roc_to_iso",
]
