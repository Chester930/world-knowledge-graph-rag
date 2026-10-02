"""Q4-B：L3′ 試點——`as_of` 檢索原型（報告264 §3）。

提供可 `import` 的 `asof_search(...)` 與 CLI：

- ``mode="naive"``：直接呼叫 production `services.svo_service.vector_search_facts`（現行行為，作對照），並以 DB 讀取補上每個 Fact 所屬
  `LawArticle` 的 `law_id`／`article_no`／`valid_from`（評測用，不改變檢索結果）。
- ``mode="asof"``：向量索引取 `top_k × FACT_SEARCH_CANDIDATE_MULTIPLIER` 候選（連同 `lifecycle_state`、`lifecycle_events_json` 與所屬 LawArticle
  屬性）→ 重用報告260 S4 原型 `filter_as_of_then_dedupe`（**先過濾後去重**）→ 截斷 `top_k`。

**識別鍵斷言**：`filter_as_of_then_dedupe` 以 `<source_doc_id>#<source_svo_chunk_index>` 當 Fact 識別；試點同一區塊（＝同一條文）會有多個 Fact，
它們的事件由條文決定而相同，所以鍵相同無妨——但原型**斷言**同一識別鍵下事件一致，不一致就拋 `InconsistentEventsError`（不靜默覆蓋）。

CLI：不帶 ``--execute`` 時只印出將執行的請求（離線，`connects:false`）；``--execute`` 才連線（重用 Q2 閘門；由規劃對話執行）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import UUID

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.kg import pilot_import as pi  # noqa: E402  (只含常數／純函式；不匯入 core／neo4j)
from services import relation_lifecycle as rl  # noqa: E402

MODES = ("asof", "naive")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RESULT_FIELDS = ("fact_text", "subject", "verb", "object", "rel_type", "score", "source_doc_id", "source_svo_chunk_index",
                 "law_id", "article_no", "valid_from", "lifecycle_state", "as_of_status")

ASOF_CANDIDATES_CYPHER = """
CALL db.index.vector.queryNodes('__INDEX__', $candidate_k, $vector)
YIELD node, score
OPTIONAL MATCH (node)-[:SUPPORTED_BY]->(a:LawArticle {kg_id: $kg_id})
RETURN node.fact_text AS fact_text, node.verb AS verb, node.confidence AS confidence,
       node.subject AS subject, node.object AS object, node.rel_type AS rel_type,
       node.source_doc_id AS source_doc_id, node.source_svo_chunk_index AS source_svo_chunk_index, score,
       properties(node)['lifecycle_state'] AS lifecycle_state,
       properties(node)['lifecycle_events_json'] AS lifecycle_events_json,
       a.law_id AS law_id, a.article_no AS article_no, a.valid_from AS valid_from
"""
ATTRIBUTE_CYPHER = """
UNWIND $keys AS key
MATCH (f:Fact {kg_id: $kg_id, source_doc_id: key.source_doc_id, source_svo_chunk_index: key.chunk})
OPTIONAL MATCH (f)-[:SUPPORTED_BY]->(a:LawArticle {kg_id: $kg_id})
RETURN DISTINCT key.source_doc_id AS source_doc_id, key.chunk AS chunk,
       a.law_id AS law_id, a.article_no AS article_no, a.valid_from AS valid_from
"""


class InconsistentEventsError(RuntimeError):
    """同一 Fact 識別鍵（`<source_doc_id>#<chunk>`）下出現不同的事件序列。"""


def validate_as_of(as_of: str) -> str:
    if not isinstance(as_of, str) or not _ISO_DATE_RE.match(as_of):
        raise ValueError(f"as_of 必須是 YYYY-MM-DD 字串，收到 {as_of!r}")
    return as_of


def _helpers():
    """延遲匯入報告260 S4 原型（會載入 neo4j；離線的 `--plan` 路徑不得呼叫）。"""
    from scripts.analysis import disposable_lifecycle_l2_validation as d

    return d


def _svo():
    from services import svo_service

    return svo_service


def _candidate_multiplier() -> int:
    from core.constants import FACT_SEARCH_CANDIDATE_MULTIPLIER

    return FACT_SEARCH_CANDIDATE_MULTIPLIER


def build_events_by_fact_id(records: Sequence[Mapping[str, Any]]) -> dict[str, list[rl.LifecycleEvent]]:
    """依 `record_fact_id` 分組解析事件；同一識別鍵下事件序列必須一致，否則 `InconsistentEventsError`。"""
    d = _helpers()
    events_by_id: dict[str, list[rl.LifecycleEvent]] = {}
    for record in records:
        fact_id = d.record_fact_id(dict(record))
        events = d.parse_events(record.get("lifecycle_events_json"))
        if fact_id in events_by_id and events_by_id[fact_id] != events:
            raise InconsistentEventsError(f"同一 Fact 識別鍵 {fact_id} 下事件序列不一致（試點應由條文決定而相同）")
        events_by_id[fact_id] = events
    return events_by_id


def _public(record: Mapping[str, Any], as_of_status: str | None) -> dict[str, Any]:
    out = {name: record.get(name) for name in RESULT_FIELDS if name != "as_of_status"}
    out["as_of_status"] = as_of_status
    return out


def asof_filter(
    records: Sequence[Mapping[str, Any]], as_of: str, top_k: int, retrievable: frozenset[str | None] = rl.DEFAULT_RETRIEVABLE_STATES
) -> list[dict[str, Any]]:
    """純運算：候選 → 斷言事件一致 → 先過濾後去重（重用 S4 原型）→ 截斷 `top_k` → 標 `as_of_status`。"""
    validate_as_of(as_of)
    d = _helpers()
    candidates = [dict(r) for r in records]
    events_by_id = build_events_by_fact_id(candidates)
    kept = d.filter_as_of_then_dedupe(candidates, events_by_id, as_of, retrievable)[:top_k]
    return [_public(r, rl.state_as_of(events_by_id[d.record_fact_id(r)], as_of).status) for r in kept]


async def fetch_asof_candidates(driver: Any, kg_id: UUID, query_vector: Sequence[float], candidate_k: int) -> list[dict[str, Any]]:
    svo = _svo()
    await svo.create_fact_vector_index(driver, kg_id, dim=len(query_vector))  # 與 production 的惰性建索引一致（IF NOT EXISTS）
    statement = ASOF_CANDIDATES_CYPHER.replace("__INDEX__", svo._fact_vector_index_name(str(kg_id)))
    result = await driver.execute_query(statement, kg_id=str(kg_id), candidate_k=candidate_k, vector=list(query_vector))
    return [dict(r) for r in result.records]


async def attribute_records(driver: Any, kg_id: UUID, records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """替 production 檢索結果補上所屬 LawArticle（`law_id`／`article_no`／`valid_from`）；查無者為 `None`。只讀。"""
    keys = sorted({(str(r["source_doc_id"]), int(r["source_svo_chunk_index"])) for r in records
                   if r.get("source_doc_id") is not None and r.get("source_svo_chunk_index") is not None})
    found: dict[tuple[str, int], dict[str, Any]] = {}
    if keys:
        result = await driver.execute_query(ATTRIBUTE_CYPHER, kg_id=str(kg_id),
                                            keys=[{"source_doc_id": d_, "chunk": c} for d_, c in keys])
        for row in result.records:
            found[(str(row["source_doc_id"]), int(row["chunk"]))] = dict(row)
    out = []
    for record in records:
        info = found.get((str(record.get("source_doc_id")), record.get("source_svo_chunk_index")), {})
        merged = {**record, **{k: info.get(k) for k in ("law_id", "article_no", "valid_from")}}
        out.append(_public(merged, None))
    return out


async def asof_search(
    driver: Any, kg_id: UUID, query_vector: Sequence[float], as_of: str, top_k: int, *,
    mode: str = "asof", retrievable: frozenset[str | None] = rl.DEFAULT_RETRIEVABLE_STATES,
) -> list[dict[str, Any]]:
    """`mode="naive"`＝現行 `vector_search_facts`（補上 LawArticle 屬性）；`mode="asof"`＝先過濾後去重的時間感知檢索。"""
    if mode not in MODES:
        raise ValueError(f"mode 必須是 {MODES} 之一，收到 {mode!r}")
    validate_as_of(as_of)
    if top_k < 1:
        raise ValueError("top_k 必須 ≥ 1")
    if mode == "naive":
        records = await _svo().vector_search_facts(driver, kg_id, list(query_vector), top_k)
        return await attribute_records(driver, kg_id, records)
    candidates = await fetch_asof_candidates(driver, kg_id, query_vector, top_k * _candidate_multiplier())
    return asof_filter(candidates, as_of, top_k, retrievable)


def build_request_plan(args: argparse.Namespace, corpus_dir: Path) -> dict[str, Any]:
    validate_as_of(args.as_of)
    return {
        "mode": "plan", "connects": False, "request": {"query": args.query, "as_of": args.as_of, "search_mode": args.mode, "top_k": args.top_k,
                                                      "candidate_k": args.top_k * _candidate_multiplier() if args.mode == "asof" else None},
        "corpus_dir": str(corpus_dir), "required_env": list(pi.REQUIRED_ENV),
        "note": "加上 --execute 才會連線（重用 pilot_import 閘門：埠 28687；embedding＝ollama bge-m3，由規劃對話執行）",
    }


async def execute(args: argparse.Namespace, corpus_dir: Path) -> int:
    manifest = pi.load_manifest(corpus_dir)
    facts = pi.validate_environment(os.environ, corpus_dir, manifest, kg_id=args.kg_id, allow_port=args.allow_port)
    validate_as_of(args.as_of)
    # 閘門通過後才匯入 core（Settings 在匯入時建立；環境變數優先於 .env）
    from core.config import settings
    from core.database import connect, disconnect, get_driver
    from core.providers.factory import init_providers

    if settings.neo4j_uri != os.environ["NEO4J_URI"]:
        raise pi.GateViolation("有效設定與行程環境變數不一致（.env 覆蓋？），停止")
    pi.validate_target_uri(settings.neo4j_uri, allow_port=args.allow_port)
    await connect()
    try:
        embedding = init_providers()
        vector = await embedding.encode(args.query)
        results = await asof_search(get_driver(), UUID(facts["kg_id"]), vector, args.as_of, args.top_k, mode=args.mode)
    finally:
        await disconnect()
    print(json.dumps({"mode": args.mode, "as_of": args.as_of, "top_k": args.top_k, "count": len(results), "results": results},
                     ensure_ascii=False, indent=2, default=str))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--query", required=True)
    parser.add_argument("--as-of", required=True, dest="as_of", help="YYYY-MM-DD")
    parser.add_argument("--mode", choices=MODES, default="asof")
    parser.add_argument("--top-k", type=int, default=20, dest="top_k")
    parser.add_argument("--execute", action="store_true", help="才會連線（由規劃對話執行）")
    parser.add_argument("--corpus-dir", type=Path, default=None)
    parser.add_argument("--kg-id", default=None)
    parser.add_argument("--allow-port", type=int, default=None)
    args = parser.parse_args(argv)
    corpus_dir = args.corpus_dir or pi.default_corpus_dir()
    if not args.execute:
        print(json.dumps(build_request_plan(args, corpus_dir), ensure_ascii=False, indent=2))
        return 0
    try:
        return asyncio.run(execute(args, corpus_dir))
    except pi.GateViolation as exc:
        print(f"停止：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
