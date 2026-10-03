"""KG#4「尚未施行」條文標示分析（報告267，D4）——對 KG#4 **唯讀**；解析 `Document.effective_note` 的施行日資訊。

文件層的 `effective_date` 只是備註裡**最晚的**施行日；真正尚未施行的是備註列出的特定條文／項／附表。
本腳本把備註（民國日期、條號清單、分階段「除…外」結構）解析成逐條的施行日，與 KG#4 的 `LawArticle`／Fact 對照，
並以「解析出的最晚日期 ＝ `Document.effective_date`」做自動交叉驗證。純解析函式離線可測；主程式只經 `ReadOnlyRunner`（純 MATCH）。
用法：python scripts/analysis/kg4_pending_effect_analysis.py --as-of 2026-10-03 --out data/analysis/kg4_pending_effect_20261003.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Sequence

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


def cn_to_int(text: str) -> int:
    """中文數字（至百位，如「一百十六」「一百零四」「三十」）→ 整數。"""
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
    m = DATE_RE.search(text)
    if not m:
        raise ValueError(f"找不到民國日期：{text!r}")
    y, mo, d = (cn_to_int(g) for g in m.groups())
    return date(y + 1911, mo, d).isoformat()


def normalize(note: str | None) -> str:
    return re.sub(r"\s+", "", note or "")


def art_key(article_no: str) -> tuple[int, int]:
    a, _, b = article_no.partition("-")
    return int(a), int(b or 0)


def fmt_article(article_no: str) -> str:
    return f"第 {article_no} 條"


def expand_articles(spec: str, known: Sequence[str]) -> list[str]:
    """`21-3、57、185-1～185-4` → 條號清單；範圍以該文件實際存在的條號展開（`known`），端點必須存在。"""
    known_set = set(known)
    out: list[str] = []
    for item in spec.split("、"):
        parts = re.split(r"[～~]", item)
        if len(parts) == 1:
            out.append(parts[0])
            continue
        lo, hi = art_key(parts[0]), art_key(parts[1])
        inside = sorted((k for k in known_set if lo <= art_key(k) <= hi), key=art_key)
        for endpoint in parts:
            if endpoint not in known_set and known:
                inside.append(endpoint)  # 端點不在 KG（例如已刪除）仍保留，供對照
        out.extend(sorted(set(inside), key=art_key) if known else parts)
    return out


def parse_provisions(text: str, known: Sequence[str]) -> list[dict[str, Any]]:
    """從一段文字抽出被提及的條文（含項／附表定位）。回傳 [{article_no, locator, op}]。"""
    out: list[dict[str, Any]] = []
    for m in ART_RE.finditer(text):
        tail = text[m.end():]
        locator, kind = None, "article"
        am = APPX_LOC_RE.match(tail)
        pm = PARA_LOC_RE.match(tail)
        if am:
            locator, kind = am.group(1), "appendix"
        elif pm:
            locator, kind = pm.group(1), "paragraph"
        head = text[max(0, m.start() - 6):m.start()]
        op = "增訂" if "增訂" in head else "刪除" if "刪除" in head else "修正"
        for no in expand_articles(m.group(1), known):
            out.append({"article_no": no, "locator": locator, "scope": kind, "op": op})
    return out


def parse_effective_note(note: str | None, known_articles: Sequence[str] = ()) -> dict[str, Any]:
    """解析備註。回傳 kind（`undetermined`／`staged`／`single`／`unparsed`／`empty`）、逐條施行日 `items`、`all_dates`、`max_date`。"""
    t = normalize(note)
    if not t:
        return {"kind": "empty", "items": [], "all_dates": [], "max_date": None}
    if UNDETERMINED in t:
        return {"kind": "undetermined", "items": [], "all_dates": [], "max_date": None}
    all_dates = sorted({roc_to_iso(m.group(0)) for m in DATE_RE.finditer(t)})
    m_rule = re.search(r"依第[\d\-]+條規定[:：]", t)
    preamble, rule = (t[:m_rule.start()], t[m_rule.end():]) if m_rule else (t, t)
    base = {"all_dates": all_dates, "max_date": all_dates[-1] if all_dates else None}
    m_staged = re.search(rf"除(.+?)外[，,]自({DATE_RE.pattern})施行", rule)
    items: list[dict[str, Any]] = []
    full_text = re.search(r"全文\d+條", preamble) is not None
    if m_staged:
        default_date = roc_to_iso(m_staged.group(2))
        exc = m_staged.group(1)
        exc_articles: set[str] = set()
        for seg in re.finditer(rf"([^自]+?)自({DATE_RE.pattern})施行", exc):
            seg_date = roc_to_iso(seg.group(2))
            for p in parse_provisions(re.sub(r"^[，,及]+", "", seg.group(1)), known_articles):
                items.append({**p, "effective_date": seg_date, "origin": "exception"})
                exc_articles.add(p["article_no"])
        pre_items = parse_provisions(preamble, known_articles)
        listed = [p for p in pre_items] if not full_text else [{"article_no": a, "locator": None, "scope": "article", "op": "修正"} for a in known_articles]
        for p in listed:
            items.append({**p, "effective_date": default_date, "origin": "default"})
        return {"kind": "staged", "default_date": default_date, "items": items, **base}
    m_date = re.search(rf"自({DATE_RE.pattern})施行|定自({DATE_RE.pattern})施行", rule)
    if m_date:
        eff = roc_to_iso(m_date.group(0))
        listed = parse_provisions(preamble, known_articles)
        for p in listed:
            items.append({**p, "effective_date": eff, "origin": "single"})
        return {"kind": "single", "default_date": eff, "items": items, **base}
    return {"kind": "unparsed", "items": [], **base}


def pending_items(parsed: dict[str, Any], as_of: str) -> list[dict[str, Any]]:
    """施行日晚於 `as_of`（ISO 字串比較）且非刪除者。"""
    return [i for i in parsed.get("items", []) if i["effective_date"] > as_of and i["op"] != "刪除"]


def consistency(parsed: dict[str, Any], effective_date: str | None) -> dict[str, Any]:
    """交叉驗證：文件層 `effective_date`（YYYYMMDD）應等於解析出的最晚施行日。"""
    doc_iso = f"{effective_date[:4]}-{effective_date[4:6]}-{effective_date[6:]}" if effective_date and len(effective_date) == 8 else None
    return {"document_effective_date": doc_iso, "parsed_max_date": parsed.get("max_date"),
            "consistent": (doc_iso == parsed.get("max_date")) if doc_iso or parsed.get("max_date") else True}


DOCS_CYPHER = """
MATCH (x:Document {kg_id: $k})
OPTIONAL MATCH (a:LawArticle {kg_id: $k})-[:PART_OF]->(x)
OPTIONAL MATCH (f:Fact {kg_id: $k})-[:SUPPORTED_BY]->(a)
RETURN x.source AS source, x.update_date AS update_date, x.effective_date AS effective_date, x.effective_note AS note,
       a.article_no AS article_no, count(DISTINCT f) AS facts
"""


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--as-of", default="2026-10-03")
    a = ap.parse_args(argv)
    repo = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo))
    from neo4j import GraphDatabase

    from scripts.analysis import kg4_backfill_reencode_estimate as est
    from scripts.analysis import semantic_layer_invariants as inv
    from scripts.analysis.semantic_marks_replay_join import _env_value

    if est.docker_started_at() != est.EXPECTED_STARTED_AT:
        raise SystemExit("kg2-neo4j StartedAt 不符新基準，停止")
    kg = inv.KG_ID_DEFAULT
    driver = GraphDatabase.driver(inv.BOLT_URI_DEFAULT, auth=("neo4j", _env_value(repo / ".env", "NEO4J_PASSWORD")))
    try:
        r = inv.ReadOnlyRunner(driver)
        before = inv.totals(r, kg, "before")
        if before != inv.EXPECTED_TOTALS:
            raise SystemExit(f"資料量與預期不符：{before}")
        rows = r.run("文件／條文／Fact 數", DOCS_CYPHER, k=kg)
        after = inv.totals(r, kg, "after")
    finally:
        driver.close()
    docs: dict[str, dict[str, Any]] = {}
    for row in rows:
        d = docs.setdefault(row["source"], {"source": row["source"], "update_date": row["update_date"],
                                            "effective_date": row["effective_date"], "note": row["note"], "articles": {}})
        if row["article_no"]:
            d["articles"][row["article_no"].replace("第", "").replace("條", "").replace(" ", "")] = row["facts"]
    report: list[dict[str, Any]] = []
    totals = {"pending_articles": 0, "pending_facts": 0, "undetermined_docs": 0, "undetermined_facts": 0}
    for d in docs.values():
        if not d["effective_date"] and not d["note"]:
            continue
        known = sorted(d["articles"], key=art_key)
        parsed = parse_effective_note(d["note"], known)
        pend = pending_items(parsed, a.as_of)
        by_article: dict[str, dict[str, Any]] = {}
        for p in pend:
            e = by_article.setdefault(p["article_no"], {"article_no": fmt_article(p["article_no"]), "in_kg4": p["article_no"] in d["articles"],
                                                         "facts": d["articles"].get(p["article_no"], 0), "scopes": set(), "ops": set(), "dates": set()})
            e["scopes"].add(p["scope"]); e["ops"].add(p["op"]); e["dates"].add(p["effective_date"])
        arts = [{**e, "scopes": sorted(e["scopes"]), "ops": sorted(e["ops"]), "dates": sorted(e["dates"])} for e in sorted(by_article.values(), key=lambda e: art_key(e["article_no"].split()[1]))]
        entry = {"source": d["source"], "effective_date": d["effective_date"], "kind": parsed["kind"], "default_date": parsed.get("default_date"),
                 "consistency": consistency(parsed, d["effective_date"]), "note": " ".join((d["note"] or "").split()),
                 "all_articles": len(d["articles"]), "all_facts": sum(d["articles"].values()),
                 "pending_articles": arts, "pending_article_count": len(arts), "pending_fact_count": sum(e["facts"] for e in arts)}
        if parsed["kind"] == "undetermined":
            totals["undetermined_docs"] += 1
            totals["undetermined_facts"] += entry["all_facts"]
        totals["pending_articles"] += entry["pending_article_count"]
        totals["pending_facts"] += entry["pending_fact_count"]
        report.append(entry)
    res = {"as_of": a.as_of, "documents_with_effect_info": len(report), "totals": totals,
           "all_consistent": all(e["consistency"]["consistent"] for e in report), "documents": report,
           "totals_before": before, "totals_after": after, "totals_stable": before == after, "embedding_provider_called": False}
    a.out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"as_of": a.as_of, "docs": len(report), "all_consistent": res["all_consistent"], "totals": totals, "stable": res["totals_stable"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
