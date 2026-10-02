"""KG#4 法規時間資訊覆蓋盤點（報告257）——對 KG#4 唯讀。

回答：文件層有多少時間欄位、條號與文件識別格式為何、有多少文件含「尚未施行」的修正（effective_date 晚於 as_of）。
只經 `ReadOnlyRunner`（純 MATCH）；不寫入、不呼叫 embedding provider。
用法：python scripts/analysis/kg4_law_time_coverage.py --as-of 20261002 --out data/analysis/kg4_law_time_coverage_20261002.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

DOCS_CYPHER = """
MATCH (x:Document {kg_id: $k})
OPTIONAL MATCH (a:LawArticle {kg_id: $k})-[:PART_OF]->(x)
OPTIONAL MATCH (f:Fact {kg_id: $k})-[:SUPPORTED_BY]->(a)
RETURN x.source AS source, x.record_type AS record_type, x.update_date AS update_date,
       x.effective_date AS effective_date, x.effective_note AS effective_note,
       count(DISTINCT a) AS articles, count(DISTINCT f) AS facts
"""
ARTICLES_CYPHER = "MATCH (a:LawArticle {kg_id: $k}) RETURN a.article_no AS article_no"
LAWARTICLE_KEYS_CYPHER = "MATCH (a:LawArticle {kg_id: $k}) RETURN keys(a) AS ks LIMIT 1"


def article_no_shape(article_no: str | None) -> str:
    """條號格式（把數字換成 #）：'第 25 條' → '第 # 條'。"""
    return re.sub(r"\d+", "#", article_no or "")


def is_pcode_source(source: str | None) -> bool:
    return bool(re.match(r"^[A-Z]\d{7}_", source or ""))


def summarize(docs: list[dict], article_nos: list[str | None], as_of: str) -> dict:
    with_eff = [d for d in docs if d["effective_date"]]
    future = sorted((d for d in with_eff if d["effective_date"] > as_of), key=lambda d: d["effective_date"])
    return {
        "as_of": as_of,
        "documents": len(docs),
        "record_types": dict(Counter(d["record_type"] for d in docs)),
        "with_update_date": sum(1 for d in docs if d["update_date"]),
        "with_effective_date": len(with_eff),
        "with_effective_note": sum(1 for d in docs if d["effective_note"]),
        "effective_date_8digit": sum(1 for d in with_eff if re.fullmatch(r"\d{8}", d["effective_date"])),
        "pcode_prefixed_sources": sum(1 for d in docs if is_pcode_source(d["source"])),
        "article_no_shapes": dict(Counter(article_no_shape(a) for a in article_nos).most_common(8)),
        "facts_in_docs_with_effective_date": sum(d["facts"] for d in with_eff),
        "future_effective_documents": [
            {"source": d["source"], "update_date": d["update_date"], "effective_date": d["effective_date"],
             "articles": d["articles"], "facts": d["facts"], "effective_note": " ".join((d["effective_note"] or "").split())[:200]}
            for d in future],
        "facts_in_future_effective_documents_upper_bound": sum(d["facts"] for d in future),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--as-of", default="20261002", help="YYYYMMDD；effective_date 晚於此者視為尚未施行")
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
        docs = r.run("文件層時間欄位", DOCS_CYPHER, k=kg)
        arts = [x["article_no"] for x in r.run("條號", ARTICLES_CYPHER, k=kg)]
        keys = r.run("LawArticle 欄位", LAWARTICLE_KEYS_CYPHER, k=kg)
        after = inv.totals(r, kg, "after")
    finally:
        driver.close()
    res = summarize(docs, arts, a.as_of)
    res.update({"law_article_keys": sorted(keys[0]["ks"]) if keys else [], "law_articles": len(arts),
                "totals_before": before, "totals_after": after, "totals_stable": before == after,
                "embedding_provider_called": False})
    a.out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print({k: res[k] for k in ("documents", "with_effective_date", "facts_in_docs_with_effective_date",
                               "facts_in_future_effective_documents_upper_bound", "law_article_keys", "totals_stable")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
