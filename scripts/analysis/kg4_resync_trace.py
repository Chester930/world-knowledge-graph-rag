"""方案 B 變動的**溯源與實證**（報告255）——對 KG#4 唯讀。

對每個會被同步的 (Fact, 欄位)，用該 Fact 自己的來源 chunk 當證據：
  ① 舊名／新名是否逐字出現在 chunk 原文檔（`kg-runtime/<kg>/<source>/<chunk_file>`，去空白比對）；
  ② 該實體在這個 chunk 的 `HAS_ENTITY.surface_form` 記錄裡有沒有舊名／新名；
並掃描全 KG 實體：別名（`HAS_ENTITY.surface_form` 全 KG 集合）與現名之間的衝突類型與波及 Fact 數。
只經 `ReadOnlyRunner`（純 MATCH）；不寫入、不呼叫 embedding provider。
用法：python scripts/analysis/kg4_resync_trace.py --out data/analysis/kg4_resync_trace_20261002.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

FACT_CHUNK_CYPHER = """
MATCH (f:Fact {kg_id: $k})
MATCH (c:Chunk {kg_id: $k, source_doc_id: f.source_doc_id, chunk_index: f.source_svo_chunk_index})
OPTIONAL MATCH (f)-[:HAS_SUBJECT]->(s:Entity)
WITH f, c, collect(s)[0] AS s
OPTIONAL MATCH (f)-[:HAS_OBJECT]->(o:Entity)
WITH f, c, s, collect(o)[0] AS o
OPTIONAL MATCH (c)-[rs:HAS_ENTITY]->(s)
WITH f, c, s, o, collect(DISTINCT rs.surface_form) AS s_forms
OPTIONAL MATCH (c)-[ro:HAS_ENTITY]->(o)
RETURN elementId(f) AS eid, f.subject AS flat_subject, f.object AS flat_object, f.rel_type AS flat_rel_type,
       f.verb AS verb, f.fact_text AS fact_text,
       s IS NOT NULL AS subject_exists, o IS NOT NULL AS object_exists,
       s.name AS subject_name, o.name AS object_name,
       elementId(s) AS s_eid, elementId(o) AS o_eid,
       c.source AS source, c.chunk_file AS chunk_file,
       s_forms, collect(DISTINCT ro.surface_form) AS o_forms,
       0 AS edge_count, [] AS edge_types
ORDER BY elementId(f)
"""
ENTITY_FORMS_CYPHER = """
MATCH (e:Entity {kg_id: $k})
OPTIONAL MATCH (:Chunk {kg_id: $k})-[r:HAS_ENTITY]->(e)
RETURN elementId(e) AS eid, e.name AS name, collect(DISTINCT r.surface_form) AS forms
"""
ENTITY_DEGREE_CYPHER = """
MATCH (f:Fact {kg_id: $k})-[:HAS_SUBJECT|HAS_OBJECT]->(e:Entity)
RETURN elementId(e) AS eid, count(DISTINCT f) AS facts
"""


def norm(text: str | None) -> str:
    """去除所有空白與全形空白，供逐字比對。"""
    return re.sub(r"\s+", "", (text or "").replace("　", ""))


def evidence(flat: str, new: str, text_norm: str | None, forms: list[str]) -> dict[str, str]:
    """對單一 (舊名, 新名) 回傳兩種證據：chunk 原文逐字、chunk 內 surface_form 記錄。
    text_norm 為 None 表示原文檔讀不到（記為 unknown）。"""
    out: dict[str, str] = {}
    if text_norm is None:
        out["text"] = "unknown"
    else:
        f_in, n_in = norm(flat) in text_norm, norm(new) in text_norm
        out["text"] = ("both" if f_in and n_in else "flat_only" if f_in else "new_only" if n_in else "neither")
    fs = {norm(x) for x in forms}
    f_in, n_in = norm(flat) in fs, norm(new) in fs
    out["forms"] = ("both" if f_in and n_in else "flat_only" if f_in else "new_only" if n_in else "neither")
    return out


def entity_alias_conflicts(entities: list[dict[str, Any]], degree: dict[str, int], classify) -> dict[str, Any]:
    """全 KG 實體：現名 vs 每個別名的衝突分類；回傳計數與波及 Fact 數。"""
    ent_by_cat: Counter[str] = Counter()
    facts_by_cat: Counter[str] = Counter()
    suspicious: dict[str, set[str]] = defaultdict(set)
    multi = 0
    for e in entities:
        forms = [x for x in (e["forms"] or []) if x and x != e["name"]]
        if not forms:
            continue
        multi += 1
        cats = {classify(x, e["name"]) for x in forms}
        for c in cats:
            ent_by_cat[c] += 1
            suspicious[c].add(e["eid"])
    for c, eids in suspicious.items():
        facts_by_cat[c] = sum(degree.get(eid, 0) for eid in eids)
    return {"entities_with_other_forms": multi, "entities_by_conflict_category": dict(ent_by_cat),
            "facts_touching_entities_by_category": dict(facts_by_cat)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)
    repo = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo))
    from neo4j import GraphDatabase

    from scripts.analysis import kg4_backfill_reencode_estimate as est
    from scripts.analysis import semantic_layer_invariants as inv
    from scripts.analysis.kg4_resync_audit import classify
    from scripts.analysis.semantic_marks_replay_join import _env_value
    from services.fact_flat_resync import _plan_resync_updates

    if est.docker_started_at() != est.EXPECTED_STARTED_AT:
        raise SystemExit("kg2-neo4j StartedAt 不符新基準，停止")
    kg = inv.KG_ID_DEFAULT
    driver = GraphDatabase.driver(inv.BOLT_URI_DEFAULT, auth=("neo4j", _env_value(repo / ".env", "NEO4J_PASSWORD")))
    try:
        r = inv.ReadOnlyRunner(driver)
        before = inv.totals(r, kg, "before")
        if before != inv.EXPECTED_TOTALS:
            raise SystemExit(f"資料量與預期不符：{before}")
        rows = r.run("Fact×Chunk×surface_form", FACT_CHUNK_CYPHER, k=kg)
        entities = r.run("實體別名集合", ENTITY_FORMS_CYPHER, k=kg)
        degree = {x["eid"]: x["facts"] for x in r.run("實體 Fact 度數", ENTITY_DEGREE_CYPHER, k=kg)}
        after = inv.totals(r, kg, "after")
    finally:
        driver.close()

    _, updates = _plan_resync_updates(rows, sync_rel_type=False)
    by_eid = {row["eid"]: row for row in rows}
    runtime = inv.KG_RUNTIME_DEFAULT / kg
    text_cache: dict[tuple[str, str], str | None] = {}

    def chunk_text(source: str, fname: str) -> str | None:
        key = (source, fname)
        if key not in text_cache:
            p = runtime / source / fname
            text_cache[key] = norm(p.read_text(encoding="utf-8", errors="ignore")) if p.is_file() else None
        return text_cache[key]

    tally: dict[str, Counter[str]] = defaultdict(Counter)
    pair_ev: dict[tuple[str, str, str], dict[str, Counter[str]]] = defaultdict(lambda: {"text": Counter(), "forms": Counter()})
    for side in ("subject", "object"):
        for u in updates[side]:
            row = by_eid[u["eid"]]
            flat = row["flat_subject"] if side == "subject" else row["flat_object"]
            forms = row["s_forms"] if side == "subject" else row["o_forms"]
            ev = evidence(flat or "", u["value"], chunk_text(row["source"], row["chunk_file"]), forms)
            cat = classify(flat or "", u["value"])
            tally[cat][f"text:{ev['text']}"] += 1
            tally[cat][f"forms:{ev['forms']}"] += 1
            tally["ALL"][f"text:{ev['text']}"] += 1
            tally["ALL"][f"forms:{ev['forms']}"] += 1
            for k in ("text", "forms"):
                pair_ev[(side, flat or "", u["value"])][k][ev[k]] += 1
    conflicts = entity_alias_conflicts(entities, degree, classify)
    res = {
        "facts_total": len(rows), "attribute_updates": {k: len(v) for k, v in updates.items()},
        "evidence_by_category": {k: dict(v) for k, v in tally.items()},
        "entity_alias_conflicts": conflicts,
        "chunk_files_read": sum(1 for v in text_cache.values() if v is not None),
        "chunk_files_missing": sum(1 for v in text_cache.values() if v is None),
        "pair_evidence": [{"side": s, "old": o, "new": n, "text": dict(e["text"]), "forms": dict(e["forms"])}
                          for (s, o, n), e in pair_ev.items()],
        "totals_before": before, "totals_after": after, "totals_stable": before == after,
        "embedding_provider_called": False,
    }
    a.out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print({k: res[k] for k in ("facts_total", "attribute_updates", "chunk_files_read", "chunk_files_missing", "totals_stable")})
    print("evidence ALL:", dict(tally["ALL"]))
    print("conflicts:", conflicts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
