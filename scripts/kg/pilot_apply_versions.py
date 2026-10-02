"""Q4-A：L3′ 試點——把條文版本屬性、版本譜系與 Fact 事件連動寫進試點 Neo4j（報告264 §2）。

- ``--plan``：**完全離線**，只讀 `pilot_manifest.json`，列出將執行的步驟與數量（`connects:false`）；不匯入 `neo4j`／`core`。
- ``--execute``：連線寫入（**實作者不得執行**，由規劃對話執行）。連線前先過 Q2 的閘門（**重用**
  `scripts/kg/pilot_import.py` 的 `validate_environment`／`validate_target_uri`／`validate_kg_id`，不放寬）。

配對規則：`LawArticle` 一律以 (`source_doc_id`, `law_article_no`) 精確配對（報告260 S4 已證明「條號＋版本」會誤抓他法同號條文）；
配對不到、或同一識別配到多個節點＝停止（`MatchError`），不略過。所有事件日期都用該版本的 `valid_from`（報告260 §2）。
事件計畫沿用報告260 S4 原型（`plan_supersede_events`，可重用不修改）；冪等：第二次執行追加 0 筆。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import UUID

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.kg import pilot_import as pi  # noqa: E402  (只含常數／純函式；不匯入 core／neo4j)
from services import relation_lifecycle as rl  # noqa: E402

REASON_CREATED = "試點：以條文版本生效日建立"
STATE_SUPERSEDED, STATE_VALID = rl.SUPERSEDED, rl.VALID
EVENT_TRIGGER = "事件"

LAW_ARTICLE_NODES_CYPHER = """
MATCH (a:LawArticle {kg_id: $kg_id})
RETURN elementId(a) AS eid, a.source_doc_id AS source_doc_id, a.article_no AS article_no
ORDER BY elementId(a)
"""
WRITE_VERSION_PROPS_CYPHER = """
UNWIND $rows AS row
MATCH (a:LawArticle {kg_id: $kg_id}) WHERE elementId(a) = row.eid
SET a.law_id = row.law_id, a.version_id = row.version_id, a.valid_from = row.valid_from, a.valid_to = row.valid_to,
    a.valid_to_original = row.valid_to_original, a.diff_to_next = row.diff_to_next,
    a.diff_from_previous = row.diff_from_previous, a.is_conflict = row.is_conflict, a.pilot_roles_json = row.pilot_roles_json
RETURN count(a) AS updated
"""
WRITE_SUPERSEDED_BY_CYPHER = """
UNWIND $pairs AS pair
MATCH (old:LawArticle {kg_id: $kg_id}) WHERE elementId(old) = pair.old
MATCH (new:LawArticle {kg_id: $kg_id}) WHERE elementId(new) = pair.new
MERGE (old)-[r:SUPERSEDED_BY]->(new)
SET r.diff_class = pair.diff_class, r.effective_date = pair.effective_date
RETURN count(r) AS merged
"""
SUPPORTED_FACTS_CYPHER = """
MATCH (f:Fact {kg_id: $kg_id})-[:SUPPORTED_BY]->(a:LawArticle {kg_id: $kg_id})
RETURN elementId(f) AS eid, elementId(a) AS article_eid, properties(f)['lifecycle_events_json'] AS events_json,
       properties(f)['lifecycle_state'] AS state
ORDER BY elementId(f)
"""
WRITE_FACT_EVENTS_CYPHER = """
UNWIND $updates AS update
MATCH (f:Fact {kg_id: $kg_id}) WHERE elementId(f) = update.eid
SET f.lifecycle_events_json = update.events_json, f.lifecycle_state = update.state
RETURN count(f) AS updated
"""


class MatchError(RuntimeError):
    """manifest 版本無法唯一配對到 LawArticle 節點。"""


# ── 純函式：版本、譜系、配對 ─────────────────────────────────────────────────
def evidence_ref(law_id: str, law_article_no: str, valid_from: str) -> str:
    return f"LawArticle:{law_id}:{law_article_no}:{valid_from}"


def version_key(version: Mapping[str, Any]) -> tuple[str, str]:
    """LawArticle 識別＝(source_doc_id, law_article_no)（不是「條號＋版本」）。"""
    return str(version["source_doc_id"]), str(version["law_article_no"])


def version_properties(version: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "law_id": version["pcode"], "version_id": version["version_id"], "valid_from": version["valid_from"],
        "valid_to": version["valid_to_derived"], "valid_to_original": version["valid_to_original"],
        "diff_to_next": version["diff_to_next"], "diff_from_previous": version["diff_from_previous"],
        "is_conflict": bool(version["is_conflict"]), "pilot_roles_json": json.dumps(version["roles"], ensure_ascii=False),
    }


def build_version_pairs(manifest: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """相鄰版本對（下一版＝`valid_to_derived`）；下一版不在 manifest 的記錄在 `skipped`（無法建立關係，不是錯誤）。"""
    by_chain = {(v["pcode"], v["article_no"], v["valid_from"]): v for v in manifest["versions"]}
    pairs: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for old in manifest["versions"]:
        if old["valid_to_derived"] is None:
            continue
        new = by_chain.get((old["pcode"], old["article_no"], old["valid_to_derived"]))
        if new is None:
            skipped.append({"old": list(version_key(old)), "next_valid_from": old["valid_to_derived"]})
            continue
        pairs.append({"old": version_key(old), "new": version_key(new), "diff_class": old["diff_to_next"],
                      "effective_date": new["valid_from"]})
    return pairs, skipped


def match_law_articles(nodes: Sequence[Mapping[str, Any]], versions: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], str]:
    """(source_doc_id, law_article_no) → 節點 elementId；缺少或重複一律 `MatchError`（不略過）。"""
    by_key: dict[tuple[str, str], list[str]] = {}
    for node in nodes:
        by_key.setdefault((str(node["source_doc_id"]), str(node["article_no"])), []).append(node["eid"])
    missing = [version_key(v) for v in versions if version_key(v) not in by_key]
    duplicated = [version_key(v) for v in versions if len(by_key.get(version_key(v), [])) > 1]
    if missing or duplicated:
        raise MatchError(f"LawArticle 配對失敗：缺少 {len(missing)} 個 {missing[:3]}；重複 {len(duplicated)} 個 {duplicated[:3]}")
    return {version_key(v): by_key[version_key(v)][0] for v in versions}


# ── 純函式：事件計畫與稽核 ───────────────────────────────────────────────────
def _helpers():
    """延遲匯入報告260 S4 原型的函式（該模組會載入 neo4j；`--plan` 不得呼叫）。"""
    from scripts.analysis import disposable_lifecycle_l2_validation as d

    return d


def initial_events(version: Mapping[str, Any]) -> list[rl.LifecycleEvent]:
    ref = evidence_ref(version["pcode"], version["law_article_no"], version["valid_from"])
    return [rl.LifecycleEvent(kind, version["valid_from"], REASON_CREATED, ref, EVENT_TRIGGER) for kind in (rl.EXTRACTED, rl.VERIFIED)]


def plan_fact_events(facts: Sequence[Mapping[str, Any]], versions_by_article_eid: Mapping[str, Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """每個支持 Fact 的最終事件序列與快取狀態；只回傳**有變動**者（冪等：第二次回傳空）。"""
    d = _helpers()
    stats = Counter(facts=len(facts), initial_written=0, superseded_appended=0, skipped_existing=0, skipped_illegal=0, updated=0, unchanged=0)
    updates: list[dict[str, Any]] = []
    for fact in facts:
        version = versions_by_article_eid[fact["article_eid"]]
        before = d.parse_events(fact.get("events_json"))
        events = list(before)
        if not events:
            events = initial_events(version)
            stats["initial_written"] += 1
        next_from = version["valid_to_derived"]
        if next_from is not None:
            ref = evidence_ref(version["pcode"], version["law_article_no"], next_from)
            planned, sub = d.plan_supersede_events([{"eid": fact["eid"], "events_json": d.dump_events(events)}],
                                                   evidence_ref=ref, valid_from=next_from)
            stats["superseded_appended"] += sub["appended"]
            stats["skipped_existing"] += sub["skipped_existing"]
            stats["skipped_illegal"] += sub["skipped_illegal"]
            if planned:
                events = d.parse_events(planned[0]["events_json"])
        state = rl.replay(events).final_state
        if events == before and state == fact.get("state"):
            stats["unchanged"] += 1
            continue
        stats["updated"] += 1
        updates.append({"eid": fact["eid"], "events_json": d.dump_events(events), "state": state})
    return updates, dict(stats)


def audit_facts(facts: Sequence[Mapping[str, Any]], versions_by_article_eid: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """事後稽核：事件重播＝快取（無漂移）、無事件 Fact 數＝0、舊版全「已被取代」、最新版全「有效」。"""
    d = _helpers()
    drift, no_events, violations = [], [], []
    states: Counter[str] = Counter()
    for fact in facts:
        events = d.parse_events(fact.get("events_json"))
        state = fact.get("state")
        states[str(state)] += 1
        if not events:
            no_events.append(fact["eid"])
        elif rl.replay(events).final_state != state:
            drift.append(fact["eid"])
        version = versions_by_article_eid[fact["article_eid"]]
        expected = STATE_SUPERSEDED if version["valid_to_derived"] is not None else STATE_VALID
        if state != expected:
            violations.append({"eid": fact["eid"], "law_article_no": version["law_article_no"], "valid_from": version["valid_from"],
                               "state": state, "expected": expected})
    return {"ok": not (drift or no_events or violations), "facts": len(facts), "drift": drift, "facts_without_events": len(no_events),
            "state_counts": dict(states), "expectation_violations": violations}


# ── --plan（離線）───────────────────────────────────────────────────────────
def build_plan(corpus_dir: Path) -> dict[str, Any]:
    manifest = pi.load_manifest(corpus_dir)
    versions = manifest["versions"]
    pairs, skipped = build_version_pairs(manifest)
    old = sum(v["valid_to_derived"] is not None for v in versions)
    latest = len(versions) - old
    return {
        "mode": "plan", "connects": False, "pilot_kg_id": manifest["pilot_kg_id"], "corpus_dir": str(corpus_dir),
        "required_env": list(pi.REQUIRED_ENV), "target_port_default": pi.DEFAULT_PILOT_PORT,
        "counts": {
            "version_property_rows": len(versions), "superseded_by_relations": len(pairs),
            "superseded_by_by_diff_class": dict(sorted(Counter(p["diff_class"] for p in pairs).items())),
            "pairs_skipped_next_not_in_manifest": len(skipped), "old_versions": old, "latest_versions": latest,
            "conflict_versions": sum(bool(v["is_conflict"]) for v in versions),
        },
        "events": {
            "per_fact": {"latest_version": "2 筆（抽取完成、驗證通過）→ 快取＝有效", "old_version": "3 筆（＋新版取代）→ 快取＝已被取代"},
            "lower_bound_if_each_article_has_one_fact": 2 * latest + 3 * old,
            "upper_bound": "3 × 實際 Fact 數（Fact 數需連線才知道；每條文可有多個 Fact）",
            "second_run_expected_appended": 0,
        },
        "steps": [
            {"n": 1, "action": "驗證環境與目標（重用 pilot_import 閘門：埠 28687、拒絕 17990／27687／7687、kg2-neo4j；kg_id＝pilot_kg_id）"},
            {"n": 2, "action": "讀 LawArticle 節點，以 (source_doc_id, law_article_no) 配對 manifest 版本；缺少或重複即停止", "count": len(versions)},
            {"n": 3, "action": "寫入版本屬性 law_id／version_id／valid_from／valid_to／valid_to_original／diff_to_next／diff_from_previous／is_conflict／pilot_roles_json",
             "count": len(versions)},
            {"n": 4, "action": "MERGE (:LawArticle old)-[:SUPERSEDED_BY {diff_class, effective_date}]->(:LawArticle new)", "count": len(pairs)},
            {"n": 5, "action": "對每個 SUPPORTED_BY 的 Fact 寫事件（缺則補 [抽取完成, 驗證通過]@valid_from；舊版追加 新版取代@下一版 valid_from）並更新 lifecycle_state"},
            {"n": 6, "action": "事後稽核：重播＝快取、無事件 Fact＝0、舊版全已被取代／最新版全有效"},
        ],
    }


# ── --execute（實作者不得執行）────────────────────────────────────────────────
async def _write_rows(driver: Any, cypher: str, key: str, rows: Sequence[Any], count_field: str, kg_id: UUID) -> int:
    if not rows:
        return 0
    result = await driver.execute_query(cypher, kg_id=str(kg_id), **{key: list(rows)})
    count = int(result.records[0][count_field])
    if count != len(rows):
        raise RuntimeError(f"寫入筆數不符：{key} expected={len(rows)} actual={count}")
    return count


async def apply_versions(driver: Any, kg_id: UUID, manifest: Mapping[str, Any]) -> dict[str, Any]:
    """對 driver 執行 Q4-A 全部步驟並回傳統計與稽核（假 driver 可測；不含任何連線／環境處理）。"""
    versions = manifest["versions"]
    nodes = [dict(r) for r in (await driver.execute_query(LAW_ARTICLE_NODES_CYPHER, kg_id=str(kg_id))).records]
    matched = match_law_articles(nodes, versions)
    rows = [{"eid": matched[version_key(v)], **version_properties(v)} for v in versions]
    written = await _write_rows(driver, WRITE_VERSION_PROPS_CYPHER, "rows", rows, "updated", kg_id)
    pairs, skipped = build_version_pairs(manifest)
    pair_rows = [{"old": matched[p["old"]], "new": matched[p["new"]], "diff_class": p["diff_class"], "effective_date": p["effective_date"]} for p in pairs]
    merged = await _write_rows(driver, WRITE_SUPERSEDED_BY_CYPHER, "pairs", pair_rows, "merged", kg_id)
    versions_by_eid = {matched[version_key(v)]: v for v in versions}

    async def read_facts() -> list[dict[str, Any]]:
        return [dict(r) for r in (await driver.execute_query(SUPPORTED_FACTS_CYPHER, kg_id=str(kg_id))).records]

    updates, event_stats = plan_fact_events(await read_facts(), versions_by_eid)
    await _write_rows(driver, WRITE_FACT_EVENTS_CYPHER, "updates", updates, "updated", kg_id)
    audit = audit_facts(await read_facts(), versions_by_eid)
    return {"version_properties_written": written, "superseded_by_merged": merged, "pairs_skipped": len(skipped),
            "event_stats": event_stats, "audit": audit}


async def execute(corpus_dir: Path, kg_id: str | None, allow_port: int | None) -> int:
    manifest = pi.load_manifest(corpus_dir)
    facts = pi.validate_environment(os.environ, corpus_dir, manifest, kg_id=kg_id, allow_port=allow_port)
    # 閘門通過後才匯入 core（Settings 在匯入時建立；此時行程環境變數已確認，環境變數優先於 .env）
    from core.config import settings
    from core.database import connect, disconnect, get_driver

    if settings.neo4j_uri != os.environ["NEO4J_URI"]:
        raise pi.GateViolation("有效設定與行程環境變數不一致（.env 覆蓋？），停止")
    pi.validate_target_uri(settings.neo4j_uri, allow_port=allow_port)
    await connect()
    try:
        result = await apply_versions(get_driver(), UUID(facts["kg_id"]), manifest)
    finally:
        await disconnect()
    print(json.dumps({"mode": "execute", "target": facts["target"], "kg_id": facts["kg_id"], **result}, ensure_ascii=False, indent=2))
    return 0 if result["audit"]["ok"] else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true", help="離線：只列步驟與數量，不連線")
    mode.add_argument("--execute", action="store_true", help="連線寫入（由規劃對話執行）")
    parser.add_argument("--corpus-dir", type=Path, default=None)
    parser.add_argument("--kg-id", default=None)
    parser.add_argument("--allow-port", type=int, default=None)
    args = parser.parse_args(argv)
    corpus_dir = args.corpus_dir or pi.default_corpus_dir()
    if args.plan:
        print(json.dumps(build_plan(corpus_dir), ensure_ascii=False, indent=2))
        return 0
    try:
        return asyncio.run(execute(corpus_dir, args.kg_id, args.allow_port))
    except (pi.GateViolation, MatchError) as exc:
        print(f"停止：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
