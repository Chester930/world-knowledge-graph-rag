"""方案 B 套用後 `backfill_fact_text_embeddings` 要重算多少向量的**純唯讀估算**（報告252／253）。

只經 `ReadOnlyRunner`（`assert_read_only` ＋ `default_access_mode=READ`）執行純 MATCH／RETURN；
**不呼叫任何 embedding provider／Ollama、不寫入**。唯一允許的 docker 指令：`docker inspect kg2-neo4j`。
匯入本模組不得連線、不得匯入 `core`／`services`（延遲匯入於函式內）。

用法（由有 KG#4 唯讀授權者執行；密碼以參數傳入，絕不印出）：
    python scripts/analysis/kg4_backfill_reencode_estimate.py --password <pw> \
        --out data/analysis/kg4_backfill_reencode_estimate_20261002.json
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

EXPECTED_STARTED_AT = "2026-10-02T11:09:32.79429649Z"
PAGE_SIZE = 200
ROWS_CYPHER = """
MATCH (f:Fact {kg_id: $k})
OPTIONAL MATCH (f)-[:HAS_SUBJECT]->(s:Entity)
WITH f, collect(s)[0] AS s
OPTIONAL MATCH (f)-[:HAS_OBJECT]->(o:Entity)
WITH f, s, collect(o)[0] AS o
RETURN elementId(f) AS eid, f.subject AS flat_subject, f.object AS flat_object,
       f.rel_type AS flat_rel_type, f.verb AS verb, f.fact_text AS fact_text,
       s IS NOT NULL AS subject_exists, o IS NOT NULL AS object_exists,
       s.name AS subject_name, o.name AS object_name,
       0 AS edge_count, [] AS edge_types
ORDER BY elementId(f)
"""


def _production_text_builder() -> Callable[..., str]:
    from services.extraction.traditional import _to_traditional_selective
    from services.svo_service import _verbalize_fact

    def build(subject: Any, verb: Any, obj: Any, source_charset: frozenset[str] | None) -> str:
        # 與 backfill_fact_text_embeddings 一致：None → ""
        return _to_traditional_selective(_verbalize_fact(subject or "", "", verb or "", obj or "", ""), source_charset)

    return build


def _percentile(sorted_values: list[int], p: float) -> int | None:
    if not sorted_values:
        return None
    return sorted_values[min(len(sorted_values) - 1, int(round(p * (len(sorted_values) - 1))))]


def plan_reencode(
    rows: list[dict[str, Any]],
    *,
    source_charset: frozenset[str] | None,
    text_builder: Callable[..., str] | None = None,
    sample_limit: int = 20,
) -> dict[str, Any]:
    """純函式：不連線、不寫入。回傳回填重算數統計與抽樣。"""
    from services.fact_flat_resync import _plan_resync_updates

    build = text_builder or _production_text_builder()
    _, updates = _plan_resync_updates(rows, sync_rel_type=False)
    new_subject = {u["eid"]: u["value"] for u in updates["subject"]}
    new_object = {u["eid"]: u["value"] for u in updates["object"]}
    changed = set(new_subject) | set(new_object)

    without: set[str] = set()
    after: set[str] = set()
    new_texts: dict[str, str] = {}
    old_texts: dict[str, Any] = {}
    for row in rows:
        eid = row["eid"]
        old = row["fact_text"]
        if build(row["flat_subject"], row["verb"], row["flat_object"], source_charset) != old:
            without.add(eid)
        text = build(new_subject.get(eid, row["flat_subject"]), row["verb"],
                     new_object.get(eid, row["flat_object"]), source_charset)
        if text != old:
            after.add(eid)
            new_texts[eid] = text
            old_texts[eid] = old
    only = after - without
    lengths = sorted(len(new_texts[e]) for e in after)
    chars = sum(lengths)
    sample_only = [{"eid": e, "old": old_texts[e], "new": new_texts[e]} for e in sorted(only)[:sample_limit]]
    sample_base = [{"eid": e, "old": old_texts[e], "new": new_texts[e]} for e in sorted(without & after)[:10]]
    return {
        "facts_total": len(rows),
        "would_reencode_without_resync": len(without),
        "would_reencode_after_resync": len(after),
        "resync_changed_facts": len(changed),
        "reencode_caused_by_resync_only": len(only),
        "reencode_overlap": len(without & after),
        "without_not_in_after": len(without - after),
        "text_chars_total_after": {
            "total": chars,
            "mean": round(chars / len(lengths), 3) if lengths else None,
            "p95": _percentile(lengths, 0.95),
            "max": lengths[-1] if lengths else None,
            "median": statistics.median(lengths) if lengths else None,
        },
        "scan_pages": math.ceil(len(rows) / PAGE_SIZE),
        "samples_caused_by_resync_only": sample_only,
        "samples_baseline_already_stale": sample_base,
    }


def docker_started_at() -> str:
    out = subprocess.run(["docker", "inspect", "kg2-neo4j", "--format", "{{.State.StartedAt}}"],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--password", required=True)
    ap.add_argument("--kg-id", default=None)
    ap.add_argument("--kg-runtime", type=Path, default=None)
    ap.add_argument("--uri", default=None)
    a = ap.parse_args(argv)
    repo = Path(__file__).resolve().parents[2]
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    from neo4j import GraphDatabase  # noqa: PLC0415
    from scripts.analysis import semantic_layer_invariants as inv  # noqa: PLC0415
    from services.extraction.traditional import _kg_source_charset  # noqa: PLC0415

    kg, uri = a.kg_id or inv.KG_ID_DEFAULT, a.uri or inv.BOLT_URI_DEFAULT
    if not uri.endswith(":17990"):
        raise SystemExit(f"連線埠硬限 17990，停止：{uri}")
    started_before = docker_started_at()
    if started_before != EXPECTED_STARTED_AT:
        raise SystemExit(f"kg2-neo4j StartedAt 不符新基準，停止：{started_before}")
    kg_folder = (a.kg_runtime or inv.KG_RUNTIME_DEFAULT) / kg
    charset = _kg_source_charset(str(kg_folder))
    driver = GraphDatabase.driver(uri, auth=("neo4j", a.password))
    try:
        r = inv.ReadOnlyRunner(driver)
        before = inv.totals(r, kg, "before")
        if before != inv.EXPECTED_TOTALS:
            raise SystemExit(f"資料量與預期不符，停止：{before}")
        rows = r.run("Fact 重建文字所需欄位", ROWS_CYPHER, k=kg)
        res = plan_reencode(rows, source_charset=charset)
        after_totals = inv.totals(r, kg, "after")
    finally:
        driver.close()
    res.update({
        "source_charset": {"kg_folder": str(kg_folder), "chars": len(charset),
                           "mode": "selective(來源字集白名單)" if charset else "空集合＝全轉（找不到來源檔）"},
        "totals_before": before, "totals_after": after_totals, "totals_stable": before == after_totals,
        "started_at_before": started_before, "started_at_after": docker_started_at(),
        "embedding_provider_called": False, "cypher_log": r.log,
    })
    a.out.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    keys = ("facts_total", "resync_changed_facts", "would_reencode_without_resync",
            "would_reencode_after_resync", "reencode_caused_by_resync_only", "reencode_overlap", "totals_stable")
    print({k: res[k] for k in keys})
    return 0


if __name__ == "__main__":
    sys.exit(main())
