"""實體合併衝突對檢索 prompt 的**曝險量測**（報告256）——對 KG#4 唯讀、其餘為離線。

資料：凍結評測 K1（top_k=40）的 79 筆 records（含 retrieval_trace，`in_prompt` 標記進 prompt 的證據）。
對每筆進 prompt 的證據，找出它連到的實體（Fact→HAS_SUBJECT／HAS_OBJECT；BFS 三元組→以邊的
`natural_text` 反查兩端實體），判斷是否碰到「現名與別名有關鍵字詞／法規指涉衝突」的實體（報告255 §3.5）。
**曝險不是因果**：只量「有多少進 prompt 的證據碰到可疑實體」，並與題目通過／失敗對照。
用法：python scripts/analysis/kg4_conflict_exposure.py --out data/analysis/kg4_conflict_exposure_20261002.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

STAGES = ["t2_k1_topk40_stage_a", "t2_k1_topk40_stage_a2", "t2_k1_topk40_stage_a3", "t2_k1_topk40_stage_b",
          "t2_k1_topk40_stage_b2a", "t2_k1_topk40_stage_b2b", "t2_k1_topk40_stage_b2c", "t2_k1_topk40_stage_c"]
SEVERE = {"critical_token_change", "law_ref_change"}
FACTS_BY_DOC = """
MATCH (f:Fact {kg_id: $k}) WHERE f.source_doc_id IN $docs
OPTIONAL MATCH (f)-[:HAS_SUBJECT]->(s:Entity)
WITH f, collect(s)[0] AS s
OPTIONAL MATCH (f)-[:HAS_OBJECT]->(o:Entity)
WITH f, s, collect(o)[0] AS o
RETURN f.source_doc_id AS doc, f.source_svo_chunk_index AS idx, f.fact_text AS text,
       elementId(s) AS s_eid, elementId(o) AS o_eid,
       f.subject AS flat_s, f.object AS flat_o, s.name AS s_name, o.name AS o_name
"""
EDGES_BY_TEXT = """
MATCH (s:Entity {kg_id: $k})-[r]->(o:Entity {kg_id: $k}) WHERE r.natural_text IN $texts
RETURN r.natural_text AS text, elementId(s) AS s_eid, elementId(o) AS o_eid
"""


def clean(s: str | None) -> str:
    return "".join((s or "").split())


def severe_entities(entities: list[dict[str, Any]], classify) -> dict[str, set[str]]:
    """eid → 該實體現名與其他提及形式的衝突類別集合（只保留 SEVERE 內者）。"""
    out: dict[str, set[str]] = {}
    for e in entities:
        forms = [x for x in (e["forms"] or []) if x and x != e["name"]]
        cats = {classify(x, e["name"]) for x in forms} & SEVERE
        if cats:
            out[e["eid"]] = cats
    return out


def question_group(status: str) -> str:
    return {"stable_pass": "pass", "single_pass": "pass", "stable_fail": "fail", "unstable": "unstable"}.get(status, "other")


def is_exposed(eids: list[str | None], severe: dict[str, set[str]]) -> bool:
    return any(e is not None and e in severe for e in eids)


def diverged(hit: dict[str, Any]) -> bool:
    """Fact 的扁平屬性與其連到的實體現名不一致（＝方案 B 會更動的那一類）。"""
    return ((hit.get("s_name") is not None and hit.get("flat_s") != hit["s_name"])
            or (hit.get("o_name") is not None and hit.get("flat_o") != hit["o_name"]))


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
    from scripts.analysis.kg4_resync_trace import ENTITY_FORMS_CYPHER
    from scripts.analysis.semantic_marks_replay_join import _env_value

    runs = repo / "data" / "eval" / "candidate_runs"
    records = [dict(x, _stage=s) for s in STAGES for x in json.loads((runs / s / "records.json").read_text(encoding="utf-8"))
               if not x.get("error")]
    status = json.loads((runs / "t2_k1_topk40_stage_c" / "summary_final.json").read_text(encoding="utf-8"))["questions"]
    bank = {q["id"]: q for q in json.loads((repo / "data" / "eval" / "test_cases.json").read_text(encoding="utf-8"))["questions"]}
    docs = sorted({e["source_doc_id"] for r in records for e in r["lineage"]["stage1_retrieval"]["retrieval_trace"] if e["source_doc_id"]})
    texts = sorted({e["text"] for r in records for e in r["lineage"]["stage1_retrieval"]["retrieval_trace"] if e["kind"] == "triple"})

    if est.docker_started_at() != est.EXPECTED_STARTED_AT:
        raise SystemExit("kg2-neo4j StartedAt 不符新基準，停止")
    kg = inv.KG_ID_DEFAULT
    driver = GraphDatabase.driver(inv.BOLT_URI_DEFAULT, auth=("neo4j", _env_value(repo / ".env", "NEO4J_PASSWORD")))
    try:
        r = inv.ReadOnlyRunner(driver)
        before = inv.totals(r, kg, "before")
        if before != inv.EXPECTED_TOTALS:
            raise SystemExit(f"資料量與預期不符：{before}")
        entities = r.run("實體別名集合", ENTITY_FORMS_CYPHER, k=kg)
        fact_rows = r.run("評測涉及文件的 Fact", FACTS_BY_DOC, k=kg, docs=docs)
        edge_rows = r.run("三元組 natural_text 反查邊", EDGES_BY_TEXT, k=kg, texts=texts)
        after = inv.totals(r, kg, "after")
    finally:
        driver.close()

    severe = severe_entities(entities, classify)
    fact_map: dict[tuple, list[dict]] = defaultdict(list)
    for x in fact_rows:
        fact_map[(x["doc"], x["idx"], x["text"])].append(x)
    edge_map: dict[str, list[dict]] = defaultdict(list)
    for x in edge_rows:
        edge_map[x["text"]].append(x)

    per_q: dict[str, dict[str, Any]] = {}
    totals_c: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []
    for rec in records:
        qid = rec["question_id"]
        grp = question_group(status.get(qid, {}).get("status", ""))
        gold = [clean(f["exact_span"]) for f in bank[qid]["atomic_gold_facts"]]
        d = per_q.setdefault(qid, {"group": grp, "items": 0, "matched": 0, "exposed": 0, "gold_items": 0, "gold_exposed": 0,
                                   "diverged": 0, "gold_diverged": 0, "runs": 0})
        d["runs"] += 1
        for e in rec["lineage"]["stage1_retrieval"]["retrieval_trace"]:
            if not e["in_prompt"]:
                continue
            if e["kind"] == "fact":
                hits = fact_map.get((e["source_doc_id"], e["source_svo_chunk_index"], e["text"]), [])
            else:
                hits = edge_map.get(e["text"], [])
            kind = e["kind"]
            d["items"] += 1
            totals_c[f"{kind}:items"] += 1
            is_gold = any(g in clean(e["text"]) for g in gold)
            d["gold_items"] += is_gold
            if hits:
                d["matched"] += 1
                totals_c[f"{kind}:matched"] += 1
                if kind == "fact" and any(diverged(h) for h in hits):
                    d["diverged"] += 1
                    totals_c["fact:diverged"] += 1
                    d["gold_diverged"] += is_gold
                exp = any(is_exposed([h["s_eid"], h["o_eid"]], severe) for h in hits)
                if exp:
                    d["exposed"] += 1
                    totals_c[f"{kind}:exposed"] += 1
                    d["gold_exposed"] += is_gold
                    if grp == "fail" and len(examples) < 30:
                        examples.append({"question": qid, "kind": kind, "rank": e["rank"], "text": e["text"][:120], "gold_bearing": is_gold})
    groups: dict[str, Counter[str]] = defaultdict(Counter)
    for qid, d in per_q.items():
        g = groups[d["group"]]
        g["questions"] += 1
        g["questions_with_exposure"] += d["exposed"] > 0
        g["items"] += d["items"]
        g["matched"] += d["matched"]
        g["exposed"] += d["exposed"]
        g["gold_items"] += d["gold_items"]
        g["gold_exposed"] += d["gold_exposed"]
        g["diverged"] += d["diverged"]
        g["gold_diverged"] += d["gold_diverged"]
    res = {
        "records": len(records), "questions": len(per_q), "severe_entities": len(severe),
        "totals": dict(totals_c), "by_group": {k: dict(v) for k, v in groups.items()},
        "per_question": per_q, "failing_question_examples": examples,
        "totals_before": before, "totals_after": after, "totals_stable": before == after,
        "embedding_provider_called": False,
    }
    a.out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print({k: res[k] for k in ("records", "questions", "severe_entities", "totals", "by_group", "totals_stable")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
