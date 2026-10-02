"""方案 B 套用後 1,789 筆 Fact 文字變動的**唯讀審核**（報告254）。

只經 `ReadOnlyRunner`（純 MATCH）取資料；不寫入、不呼叫 embedding provider。
對每個會被同步的 (舊扁平名 → 新實體名) 做機械分類，並以配對歸併（同一配對影響多少 Fact）。
用法：python scripts/analysis/kg4_resync_audit.py --out data/analysis/kg4_resync_audit_20261002.json
密碼於程式內讀 `.env`（只由有 KG#4 唯讀授權的規劃對話使用），不印出。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

LAW_REF = ("本法", "本辦法", "本條例", "本規則", "本細則", "本準則", "本標準", "本規定", "本要點", "本規程", "本通則")
CRITICAL = re.compile(r"[0-9０-９〇一二三四五六七八九十百千萬零]+|不|未|無|非|禁止|得|應|須|勿")


def _law_refs(text: str) -> frozenset[str]:
    return frozenset(w for w in LAW_REF if w in text)


def classify(old: str, new: str) -> str:
    """優先序：法規指涉變動 > 關鍵字詞（數字／否定／義務情態）變動 > 改寫 > 截短 > 補全。"""
    if _law_refs(old) != _law_refs(new):
        return "law_ref_change"
    if Counter(CRITICAL.findall(old)) != Counter(CRITICAL.findall(new)):
        return "critical_token_change"
    if old in new:
        return "expand"
    if new in old:
        return "shrink"
    return "rewrite"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)
    repo = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo))
    from neo4j import GraphDatabase

    from scripts.analysis import kg4_backfill_reencode_estimate as est
    from scripts.analysis import semantic_layer_invariants as inv
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
        rows = r.run("Fact 與實體名稱", est.ROWS_CYPHER, k=kg)
        after = inv.totals(r, kg, "after")
    finally:
        driver.close()
    _, updates = _plan_resync_updates(rows, sync_rel_type=False)
    by_eid = {row["eid"]: row for row in rows}
    pairs: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(lambda: {"facts": 0, "sample_texts": []})
    for side in ("subject", "object"):
        for u in updates[side]:
            row = by_eid[u["eid"]]
            old = row["flat_subject"] if side == "subject" else row["flat_object"]
            key = (side, old or "", u["value"])
            p = pairs[key]
            p["facts"] += 1
            if len(p["sample_texts"]) < 2:
                p["sample_texts"].append(row["fact_text"])
    out_pairs = []
    for (side, old, new), p in sorted(pairs.items(), key=lambda kv: -kv[1]["facts"]):
        out_pairs.append({"side": side, "old": old, "new": new, "category": classify(old, new),
                          "facts": p["facts"], "sample_fact_texts": p["sample_texts"]})
    cat_pairs = Counter(p["category"] for p in out_pairs)
    cat_facts: Counter[str] = Counter()
    for p in out_pairs:
        cat_facts[p["category"]] += p["facts"]
    res = {
        "facts_total": len(rows), "changed_facts": len(set(u["eid"] for s in updates.values() for u in s)),
        "attribute_updates": {k: len(v) for k, v in updates.items()},
        "unique_pairs": len(out_pairs), "pairs_by_category": dict(cat_pairs),
        "attribute_updates_by_category": dict(cat_facts),
        "totals_before": before, "totals_after": after, "totals_stable": before == after,
        "embedding_provider_called": False, "pairs": out_pairs,
    }
    a.out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print({k: res[k] for k in ("facts_total", "changed_facts", "attribute_updates", "unique_pairs",
                               "pairs_by_category", "attribute_updates_by_category", "totals_stable")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
