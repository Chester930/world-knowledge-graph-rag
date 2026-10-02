"""G1 disposable Neo4j validation for Fact flat-property resynchronization.

This file is an experiment harness only.  It imports the audited P3/P4 gate and
container helpers, but never calls either old-baseline runner and does not alter
production code.  All graph data is synthetic and the only permitted container
is ``kg2-throwaway-neo4j``.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from neo4j import AsyncGraphDatabase

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from core.providers.base import EmbeddingProvider
from models.knowledge_graph import SVOTriple
from scripts.analysis import disposable_fact_state_validation as p3
from scripts.analysis import disposable_write_path_validation as p4  # audited helper module import


TEMP_CONTAINER = p3.TEMP_CONTAINER
IMAGE = p3.IMAGE
TEMP_URI = p3.TEMP_URI
TEMP_PORTS = p3.TEMP_PORTS
KG4_ID = p3.KG4_ID
EXPECTED_KG4_STARTED_AT = "2026-10-02T04:10:38.389676557Z"
REPORT_OUTPUT = _REPO / "data" / "analysis" / "disposable_resync_solution_b_validation_20261002.json"

VECTOR_DIM = 8
SYNC_ATTRIBUTES = ("subject", "object", "rel_type")
W1_KG = uuid4()
BOUNDARY_KG = uuid4()
ISOLATION_KG = uuid4()
SCALE_KG = uuid4()

# Reuse the audited gate/lifecycle implementation; do not copy or call either
# prior script's password runner.
GateViolation = p3.GateViolation
validate_connection_target = p3.validate_connection_target
generate_temp_password = p3.generate_temp_password
build_docker_run_argv = p3.build_docker_run_argv
temp_container_names = p3.temp_container_names
kg4_state = p3.kg4_state
launch_temp_container = p3.launch_temp_container
teardown_temp_container = p3.teardown_temp_container
import_production_without_project_env = p3.import_production_without_project_env


class CountingSyntheticEmbeddingProvider(EmbeddingProvider):
    """Deterministic 8-D provider; no Ollama, model, or network is used."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    @property
    def dim(self) -> int:
        return VECTOR_DIM

    @property
    def model_name(self) -> str:
        return "g1-synthetic-8d"

    async def encode(self, text: str) -> list[float]:
        self.calls.append(text)
        # Keep the subject alias family apart from the object family.  Fact
        # texts contain 對象甲, so both old/new Fact vectors remain identical
        # and the production vector search can return both candidates.
        if text == "對象甲" or "對象甲" in text:
            return [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        return [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def _vector() -> list[float]:
    return [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


async def cypher(driver: Any, statement: str, **parameters: Any):
    return await driver.execute_query(statement, **parameters)


async def wait_for_driver(password: str, kg_id: UUID):
    validate_connection_target(TEMP_URI, kg_id)
    driver = AsyncGraphDatabase.driver(TEMP_URI, auth=("neo4j", password))
    last_error: Exception | None = None
    for _ in range(90):
        try:
            await driver.verify_connectivity()
            return driver
        except Exception as exc:  # noqa: BLE001 - readiness retry only
            last_error = exc
            await asyncio.sleep(1)
    await driver.close()
    raise RuntimeError(f"臨時 Neo4j 未在等待時間內就緒：{type(last_error).__name__}")


async def load_production():
    """Import production functions while cwd is outside the project/.env path."""

    with import_production_without_project_env():
        from services import svo_service
        from services.context.fact_lines import split_fact_lines
        from services.extraction.traditional import _kg_source_charset

    return svo_service, split_fact_lines, _kg_source_charset


async def wait_for_index(driver: Any, name: str) -> None:
    for _ in range(60):
        result = await cypher(
            driver,
            "SHOW INDEXES YIELD name, state WHERE name = $name RETURN state",
            name=name,
        )
        if result.records and result.records[0]["state"] == "ONLINE":
            return
        await asyncio.sleep(0.5)
    raise RuntimeError(f"索引未在等待時間內 ONLINE：{name}")


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _digest(rows: list[Any]) -> str:
    payload = "\n".join(
        json.dumps(_jsonable(row), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for row in sorted(rows, key=lambda row: json.dumps(_jsonable(row), ensure_ascii=False, sort_keys=True))
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _changed_stats(stats: dict[str, int]) -> dict[str, int]:
    return {key: stats[key] for key in ("subject_changed", "object_changed", "rel_type_changed")}


def _stats_zero_changed(stats: dict[str, int]) -> bool:
    return all(stats[key] == 0 for key in ("subject_changed", "object_changed", "rel_type_changed"))


def _new_stats() -> dict[str, int]:
    return {
        "subject_changed": 0,
        "object_changed": 0,
        "rel_type_changed": 0,
        "rel_type_skipped_multi_edge": 0,
        "rel_type_skipped_no_edge": 0,
        "unchanged": 0,
        "facts_without_links": 0,
    }


async def _fact_sync_rows(driver: Any, kg_id: UUID, *, sync_rel_type: bool) -> list[dict[str, Any]]:
    edge_subquery = """
    CALL {
        WITH s, o
        OPTIONAL MATCH (s)-[r]->(o)
        WHERE s IS NOT NULL AND o IS NOT NULL
          AND r.kg_id = $kg_id AND r.citations_json IS NOT NULL
        RETURN count(r) AS edge_count, collect(DISTINCT type(r)) AS edge_types
    }
    """ if sync_rel_type else """
    WITH f, s, o, 0 AS edge_count, [] AS edge_types
    """
    result = await cypher(
        driver,
        f"""
        MATCH (f:Fact {{kg_id: $kg_id}})
        CALL {{
            WITH f
            OPTIONAL MATCH (f)-[:HAS_SUBJECT]->(s:Entity)
            RETURN collect(s)[0] AS s
        }}
        CALL {{
            WITH f
            OPTIONAL MATCH (f)-[:HAS_OBJECT]->(o:Entity)
            RETURN collect(o)[0] AS o
        }}
        {edge_subquery}
        RETURN elementId(f) AS eid,
               f.subject AS flat_subject, f.object AS flat_object, f.rel_type AS flat_rel_type,
               s IS NOT NULL AS subject_exists, o IS NOT NULL AS object_exists,
               s.name AS subject_name, o.name AS object_name,
               edge_count, edge_types
        ORDER BY elementId(f)
        """,
        kg_id=str(kg_id),
    )
    return [dict(record) for record in result.records]


def _plan_resync_updates(
    rows: list[dict[str, Any]], *, sync_rel_type: bool
) -> tuple[dict[str, int], dict[str, list[dict[str, Any]]]]:
    """Pure analysis phase.  It never receives a driver and never writes."""

    stats = _new_stats()
    updates: dict[str, list[dict[str, Any]]] = {name: [] for name in SYNC_ATTRIBUTES}
    for row in rows:
        if not row["subject_exists"] or not row["object_exists"]:
            stats["facts_without_links"] += 1
            continue

        changed = False
        if row["subject_name"] is not None and row["flat_subject"] != row["subject_name"]:
            stats["subject_changed"] += 1
            updates["subject"].append({"eid": row["eid"], "value": row["subject_name"]})
            changed = True
        if row["object_name"] is not None and row["flat_object"] != row["object_name"]:
            stats["object_changed"] += 1
            updates["object"].append({"eid": row["eid"], "value": row["object_name"]})
            changed = True

        if sync_rel_type:
            edge_count = int(row["edge_count"] or 0)
            edge_types = list(row["edge_types"] or [])
            if edge_count == 1 and len(edge_types) == 1:
                if row["flat_rel_type"] != edge_types[0]:
                    stats["rel_type_changed"] += 1
                    updates["rel_type"].append({"eid": row["eid"], "value": edge_types[0]})
                    changed = True
            elif edge_count > 1:
                stats["rel_type_skipped_multi_edge"] += 1
            else:
                stats["rel_type_skipped_no_edge"] += 1

        if not changed:
            stats["unchanged"] += 1
    return stats, updates


async def _apply_updates(driver: Any, kg_id: UUID, updates: dict[str, list[dict[str, Any]]]) -> None:
    for attribute, rows in updates.items():
        if not rows:
            continue
        result = await cypher(
            driver,
            f"""
            UNWIND $updates AS update
            MATCH (f:Fact {{kg_id: $kg_id}})
            WHERE elementId(f) = update.eid
            SET f.{attribute} = update.value
            RETURN count(f) AS updated
            """,
            kg_id=str(kg_id),
            updates=rows,
        )
        updated = int(result.records[0]["updated"] if result.records else 0)
        if updated != len(rows):
            raise RuntimeError(f"方案 B 寫入數量不符：{attribute} expected={len(rows)} actual={updated}")


async def resync_fact_flat_properties(
    driver: Any,
    kg_id: UUID,
    *,
    dry_run: bool = True,
    sync_rel_type: bool = False,
) -> dict[str, int]:
    """Validation-only scheme B prototype; production remains untouched."""

    rows = await _fact_sync_rows(driver, kg_id, sync_rel_type=sync_rel_type)
    stats, updates = _plan_resync_updates(rows, sync_rel_type=sync_rel_type)
    if not dry_run:
        await _apply_updates(driver, kg_id, updates)
    return stats


async def graph_invariants(driver: Any, kg_id: UUID) -> dict[str, Any]:
    node_count = await cypher(driver, "MATCH (n {kg_id: $kg_id}) RETURN count(n) AS count", kg_id=str(kg_id))
    edge_count = await cypher(
        driver,
        "MATCH (a {kg_id: $kg_id})-[r]->(b {kg_id: $kg_id}) RETURN count(r) AS count",
        kg_id=str(kg_id),
    )
    entities = await cypher(
        driver,
        "MATCH (e:Entity {kg_id: $kg_id}) RETURN e.name AS name ORDER BY e.name",
        kg_id=str(kg_id),
    )
    edges = await cypher(
        driver,
        """
        MATCH (a {kg_id: $kg_id})-[r]->(b {kg_id: $kg_id})
        RETURN elementId(a) AS a_id, labels(a) AS a_labels, a.name AS a_name,
               type(r) AS rel_type, properties(r) AS rel_props,
               elementId(b) AS b_id, labels(b) AS b_labels, b.name AS b_name
        """,
        kg_id=str(kg_id),
    )
    facts = await cypher(
        driver,
        "MATCH (f:Fact {kg_id: $kg_id}) RETURN elementId(f) AS eid, properties(f) AS props",
        kg_id=str(kg_id),
    )
    fact_rows = [
        {"eid": record["eid"], "props": _jsonable(record["props"])} for record in facts.records
    ]
    non_target_rows = []
    for row in fact_rows:
        props = dict(row["props"])
        for attribute in SYNC_ATTRIBUTES:
            props.pop(attribute, None)
        non_target_rows.append({"eid": row["eid"], "props": props})
    return {
        "node_count": int(node_count.records[0]["count"]),
        "edge_count": int(edge_count.records[0]["count"]),
        "entity_count": len(entities.records),
        "entity_names_digest": _digest([record["name"] for record in entities.records]),
        "edge_digest": _digest([dict(record) for record in edges.records]),
        "fact_count": len(fact_rows),
        "fact_all_digest": _digest(fact_rows),
        "fact_non_target_digest": _digest(non_target_rows),
    }


async def fact_rows_for_kg(driver: Any, kg_id: UUID) -> list[dict[str, Any]]:
    result = await cypher(
        driver,
        """
        MATCH (f:Fact {kg_id: $kg_id})
        OPTIONAL MATCH (f)-[:HAS_SUBJECT]->(s:Entity)
        OPTIONAL MATCH (f)-[:HAS_OBJECT]->(o:Entity)
        RETURN f.fixture_id AS fixture_id, f.subject AS subject, f.object AS object,
               f.rel_type AS rel_type, f.fact_text AS fact_text, f.verb AS verb,
               s.name AS subject_target, o.name AS object_target
        ORDER BY f.fixture_id
        """,
        kg_id=str(kg_id),
    )
    return [dict(record) for record in result.records]


async def create_direct_fact(
    driver: Any,
    kg_id: UUID,
    *,
    fixture_id: str,
    flat_subject: str | None,
    flat_rel_type: str | None,
    flat_object: str | None,
    subject_target: str | None = None,
    object_target: str | None = None,
    edge_types: tuple[str, ...] = (),
) -> None:
    """Create only synthetic fixtures for W2/W4 boundary cases."""

    if any("`" in rel_type or not rel_type.replace("_", "").isalnum() for rel_type in edge_types):
        raise ValueError("fixture relationship type is not a fixed safe identifier")
    clauses: list[str] = []
    if subject_target is not None:
        clauses.append("MERGE (s:Entity {kg_id: $kg_id, name: $subject_target}) SET s.type = '概念'")
    if object_target is not None:
        clauses.append("MERGE (o:Entity {kg_id: $kg_id, name: $object_target}) SET o.type = '概念'")
    clauses.append(
        """
        CREATE (f:Fact {
            kg_id: $kg_id, fixture_id: $fixture_id,
            subject: $flat_subject, rel_type: $flat_rel_type, object: $flat_object,
            fact_text: $fact_text, fact_embedding: $embedding,
            verb: '合成動詞', confidence: 0.42,
            source_doc_id: $source_doc_id, source_svo_chunk_index: 1,
            lifecycle_state: '候選', lifecycle_events_json: '[]'
        })
        """
    )
    if subject_target is not None:
        clauses.append("CREATE (f)-[:HAS_SUBJECT]->(s)")
    if object_target is not None:
        clauses.append("CREATE (f)-[:HAS_OBJECT]->(o)")
    for rel_type in edge_types:
        clauses.append(
            f"CREATE (s)-[:{rel_type} {{kg_id: $kg_id, citations_json: $citations_json, confidence: 0.8}}]->(o)"
        )
    await cypher(
        driver,
        "\n".join(clauses),
        kg_id=str(kg_id),
        fixture_id=fixture_id,
        flat_subject=flat_subject,
        flat_rel_type=flat_rel_type,
        flat_object=flat_object,
        subject_target=subject_target,
        object_target=object_target,
        fact_text=f"{flat_subject or ''} 合成動詞 {flat_object or ''}".strip(),
        embedding=_vector(),
        source_doc_id=str(uuid4()),
        citations_json=json.dumps([{"synthetic": fixture_id}], ensure_ascii=False),
    )


async def create_scale_facts(driver: Any, kg_id: UUID, *, count: int, stale_count: int) -> None:
    await cypher(
        driver,
        """
        MERGE (s:Entity {kg_id: $kg_id, name: '規模主體'}) SET s.type = '概念'
        MERGE (o:Entity {kg_id: $kg_id, name: '規模物件'}) SET o.type = '概念'
        WITH s, o
        UNWIND range(0, $last_index) AS i
        CREATE (f:Fact {
            kg_id: $kg_id, fixture_id: 'scale-' + toString(i),
            subject: CASE WHEN i < $stale_count THEN '舊規模主體' ELSE '規模主體' END,
            rel_type: 'RELATED_TO', object: '規模物件',
            fact_text: '規模主體 合成動詞 規模物件', fact_embedding: $embedding,
            verb: '合成動詞', confidence: 0.5,
            source_doc_id: $source_doc_id, source_svo_chunk_index: i + 1
        })
        CREATE (f)-[:HAS_SUBJECT]->(s)
        CREATE (f)-[:HAS_OBJECT]->(o)
        """,
        kg_id=str(kg_id),
        last_index=count - 1,
        stale_count=stale_count,
        embedding=_vector(),
        source_doc_id=str(uuid4()),
    )


async def run_w1_to_w3(svo_service: Any, split_fact_lines: Any, kg_source_charset: Any, driver: Any) -> dict[str, Any]:
    provider = CountingSyntheticEmbeddingProvider()
    docs = [uuid4(), uuid4(), uuid4()]
    triples = [
        SVOTriple(
            subject="勞動法規", rel_type="RELATED_TO", verb="適用", object="對象甲",
            source_doc_id=docs[0], source_svo_chunk_index=1,
        ),
        SVOTriple(
            subject="勞動法", rel_type="RELATED_TO", verb="適用", object="對象甲",
            source_doc_id=docs[1], source_svo_chunk_index=1,
        ),
        SVOTriple(
            subject="勞動法", rel_type="RELATED_TO", verb="適用", object="對象甲",
            source_doc_id=docs[2], source_svo_chunk_index=1,
        ),
    ]
    await svo_service.merge_triples_to_graph(
        driver, W1_KG, triples, embedding_provider=provider, llm_provider=None,
    )
    w1_facts = await fact_rows_for_kg(driver, W1_KG)
    stale_subjects = [row for row in w1_facts if row["subject"] != row["subject_target"]]
    stale_texts = [
        row for row in w1_facts
        if row["fact_text"] != svo_service._verbalize_fact(
            row["subject_target"] or "", "", row["verb"] or "", row["object_target"] or "", ""
        )
    ]
    w1 = {
        "production_path": "merge_triples_to_graph -> merge_entity",
        "source_doc_count": len(set(str(doc) for doc in docs)),
        "entity_promotion": {
            "expected": True,
            "actual": any(row["subject_target"] == "勞動法" for row in w1_facts),
            "final_subject_targets": sorted({row["subject_target"] for row in w1_facts}),
        },
        "fact_links_survive": all(
            row["subject_target"] is not None and row["object_target"] is not None for row in w1_facts
        ),
        "stale_subject_count": len(stale_subjects),
        "stale_fact_text_count": len(stale_texts),
        "fact_count": len(w1_facts),
    }

    await svo_service.create_fact_vector_index(driver, W1_KG, dim=VECTOR_DIM)
    await wait_for_index(driver, svo_service._fact_vector_index_name(str(W1_KG)))
    pre_vector = await svo_service.vector_search_facts(driver, W1_KG, _vector(), 20)
    pre_keys = [
        (row.get("subject"), row.get("rel_type"), row.get("object")) for row in pre_vector
    ]
    before_w2 = await graph_invariants(driver, W1_KG)
    dry = await resync_fact_flat_properties(driver, W1_KG, dry_run=True, sync_rel_type=True)
    after_dry = await graph_invariants(driver, W1_KG)
    actual = await resync_fact_flat_properties(driver, W1_KG, dry_run=False, sync_rel_type=True)
    after_actual = await graph_invariants(driver, W1_KG)
    second = await resync_fact_flat_properties(driver, W1_KG, dry_run=False, sync_rel_type=True)
    after_second = await graph_invariants(driver, W1_KG)
    w2 = {
        "dry_run_stats": dry,
        "actual_stats": actual,
        "dry_run_equals_actual": dry == actual,
        "dry_run_no_write": before_w2["fact_all_digest"] == after_dry["fact_all_digest"],
        "idempotent_second_run_changed_zero": _stats_zero_changed(second),
        "second_run_stats": second,
        "only_three_attributes": (
            before_w2["node_count"] == after_actual["node_count"]
            and before_w2["edge_count"] == after_actual["edge_count"]
            and before_w2["entity_names_digest"] == after_actual["entity_names_digest"]
            and before_w2["edge_digest"] == after_actual["edge_digest"]
            and before_w2["fact_non_target_digest"] == after_actual["fact_non_target_digest"]
        ),
        "second_run_no_additional_write": after_actual["fact_all_digest"] == after_second["fact_all_digest"],
    }

    source_dir = Path(tempfile.mkdtemp(prefix="g1-synthetic-source-"))
    try:
        (source_dir / "synthetic-doc").mkdir()
        (source_dir / "synthetic-doc" / "original.md").write_text("勞動法 對象甲 適用\n", encoding="utf-8")
        source_charset = kg_source_charset(str(source_dir))
        provider.calls.clear()
        backfill_first = await svo_service.backfill_fact_text_embeddings(
            driver, W1_KG, provider, source_charset=source_charset,
        )
        first_encode_calls = len(provider.calls)
        provider.calls.clear()
        backfill_second = await svo_service.backfill_fact_text_embeddings(
            driver, W1_KG, provider, source_charset=source_charset,
        )
        second_encode_calls = len(provider.calls)
    finally:
        shutil.rmtree(source_dir, ignore_errors=True)

    post_facts = await fact_rows_for_kg(driver, W1_KG)
    post_vector = await svo_service.vector_search_facts(driver, W1_KG, _vector(), 20)
    post_keys = [
        (row.get("subject"), row.get("rel_type"), row.get("object")) for row in post_vector
    ]
    bfs = [SVOTriple(subject="勞動法", rel_type="RELATED_TO", verb="適用", object="對象甲")]
    pre_bfs_lines, pre_fact_lines = split_fact_lines(bfs, pre_vector)
    post_bfs_lines, post_fact_lines = split_fact_lines(bfs, post_vector)
    after_w3 = await graph_invariants(driver, W1_KG)
    expected_changed_facts = len([row for row in post_facts if row["fact_text"]])
    # The provider is counted only around the production backfill; the first
    # run's returned update count is the authoritative number of changed texts.
    w3 = {
        "backfill_first_updated": backfill_first,
        "backfill_first_encode_calls": first_encode_calls,
        "backfill_encode_equals_text_updates": first_encode_calls == backfill_first,
        "backfill_second_updated": backfill_second,
        "backfill_second_encode_calls": second_encode_calls,
        "vector_keys_before_resync": pre_keys,
        "vector_keys_after_resync": post_keys,
        "vector_dedupe_before_count": len(pre_vector),
        "vector_dedupe_after_count": len(post_vector),
        "vector_dedupe_after_one": len(post_vector) == 1,
        "split_fact_lines_before": {"bfs": len(pre_bfs_lines), "fact": len(pre_fact_lines)},
        "split_fact_lines_after": {"bfs": len(post_bfs_lines), "fact": len(post_fact_lines)},
        "bfs_fact_key_dedup_after": len(post_bfs_lines) == 1 and len(post_fact_lines) == 0,
        "graph_invariants_preserved_through_w3": (
            before_w2["node_count"] == after_w3["node_count"]
            and before_w2["edge_count"] == after_w3["edge_count"]
            and before_w2["entity_names_digest"] == after_w3["entity_names_digest"]
            and before_w2["edge_digest"] == after_w3["edge_digest"]
        ),
        "w3_text_update_count": backfill_first,
    }
    return {"w1": w1, "w2": w2, "w3": w3}


async def run_w4(driver: Any) -> dict[str, Any]:
    await create_direct_fact(
        driver, BOUNDARY_KG, fixture_id="missing-both", flat_subject="舊主詞", flat_rel_type="OLD", flat_object="舊受詞",
    )
    await create_direct_fact(
        driver, BOUNDARY_KG, fixture_id="missing-object-link", flat_subject="舊主詞", flat_rel_type="OLD", flat_object="舊受詞",
        subject_target="缺連結主詞", object_target=None,
    )
    await create_direct_fact(
        driver, BOUNDARY_KG, fixture_id="empty-values", flat_subject="", flat_rel_type="OLD", flat_object=None,
        subject_target="空主詞", object_target="空受詞", edge_types=("UNIQUE_EDGE",),
    )
    await create_direct_fact(
        driver, BOUNDARY_KG, fixture_id="whitespace-name", flat_subject="舊主詞", flat_rel_type="OLD", flat_object="空白受詞",
        subject_target="  含 空白  ", object_target="空白受詞",
    )
    await create_direct_fact(
        driver, BOUNDARY_KG, fixture_id="consistent", flat_subject="一致主詞", flat_rel_type="UNIQUE_EDGE", flat_object="一致受詞",
        subject_target="一致主詞", object_target="一致受詞", edge_types=("UNIQUE_EDGE",),
    )
    await create_direct_fact(
        driver, BOUNDARY_KG, fixture_id="multi-edge", flat_subject="舊多邊主詞", flat_rel_type="OLD", flat_object="舊多邊受詞",
        subject_target="多邊主詞", object_target="多邊受詞", edge_types=("MULTI_EDGE_A", "MULTI_EDGE_B"),
    )
    await create_direct_fact(
        driver, BOUNDARY_KG, fixture_id="no-edge", flat_subject="舊無邊主詞", flat_rel_type="OLD", flat_object="舊無邊受詞",
        subject_target="無邊主詞", object_target="無邊受詞",
    )
    await create_direct_fact(
        driver, ISOLATION_KG, fixture_id="isolated", flat_subject="隔離舊主詞", flat_rel_type="OLD", flat_object="隔離舊受詞",
        subject_target="隔離主詞", object_target="隔離受詞", edge_types=("ISOLATED_EDGE",),
    )

    boundary_before = await graph_invariants(driver, BOUNDARY_KG)
    boundary_dry = await resync_fact_flat_properties(driver, BOUNDARY_KG, dry_run=True, sync_rel_type=True)
    boundary_after_dry = await graph_invariants(driver, BOUNDARY_KG)
    isolated_before = await graph_invariants(driver, ISOLATION_KG)
    isolated_fact_before = await fact_rows_for_kg(driver, ISOLATION_KG)
    boundary_actual = await resync_fact_flat_properties(driver, BOUNDARY_KG, dry_run=False, sync_rel_type=True)
    boundary_after = await graph_invariants(driver, BOUNDARY_KG)
    boundary_second = await resync_fact_flat_properties(driver, BOUNDARY_KG, dry_run=False, sync_rel_type=True)
    isolated_after = await graph_invariants(driver, ISOLATION_KG)
    isolated_fact_after = await fact_rows_for_kg(driver, ISOLATION_KG)

    scale_count = 17_000
    scale_stale = 1_800
    await create_scale_facts(driver, SCALE_KG, count=scale_count, stale_count=scale_stale)
    scale_before = await graph_invariants(driver, SCALE_KG)
    timings: dict[str, float] = {}
    start = time.perf_counter()
    scale_dry = await resync_fact_flat_properties(driver, SCALE_KG, dry_run=True, sync_rel_type=False)
    timings["dry_run_seconds"] = round(time.perf_counter() - start, 4)
    start = time.perf_counter()
    scale_actual = await resync_fact_flat_properties(driver, SCALE_KG, dry_run=False, sync_rel_type=False)
    timings["apply_seconds"] = round(time.perf_counter() - start, 4)
    start = time.perf_counter()
    scale_second = await resync_fact_flat_properties(driver, SCALE_KG, dry_run=False, sync_rel_type=False)
    timings["idempotent_second_seconds"] = round(time.perf_counter() - start, 4)
    scale_after = await graph_invariants(driver, SCALE_KG)

    return {
        "boundary": {
            "dry_run_stats": boundary_dry,
            "actual_stats": boundary_actual,
            "dry_run_equals_actual": boundary_dry == boundary_actual,
            "dry_run_no_write": boundary_before["fact_all_digest"] == boundary_after_dry["fact_all_digest"],
            "idempotent_second_run_changed_zero": _stats_zero_changed(boundary_second),
            "second_run_stats": boundary_second,
            "only_three_attributes": (
                boundary_before["node_count"] == boundary_after["node_count"]
                and boundary_before["edge_count"] == boundary_after["edge_count"]
                and boundary_before["entity_names_digest"] == boundary_after["entity_names_digest"]
                and boundary_before["edge_digest"] == boundary_after["edge_digest"]
                and boundary_before["fact_non_target_digest"] == boundary_after["fact_non_target_digest"]
            ),
            "edge_and_node_counts_preserved": (
                boundary_before["node_count"] == boundary_after["node_count"]
                and boundary_before["edge_count"] == boundary_after["edge_count"]
            ),
            "boundary_fact_rows": await fact_rows_for_kg(driver, BOUNDARY_KG),
        },
        "isolation": {
            "kg_b_before": isolated_before,
            "kg_b_after": isolated_after,
            "kg_b_fact_before": isolated_fact_before,
            "kg_b_fact_after": isolated_fact_after,
            "kg_b_unchanged": isolated_before == isolated_after and isolated_fact_before == isolated_fact_after,
        },
        "scale_17000": {
            "fact_count_expected": scale_count,
            "stale_count_expected": scale_stale,
            "fact_count_actual": scale_before["fact_count"],
            "dry_run_stats": scale_dry,
            "actual_stats": scale_actual,
            "dry_run_equals_actual": scale_dry == scale_actual,
            "idempotent_second_run_changed_zero": _stats_zero_changed(scale_second),
            "second_run_stats": scale_second,
            "timings_seconds": timings,
            "container_memory_limit": "3g",
            "completed": scale_before["fact_count"] == scale_count and scale_actual["subject_changed"] == scale_stale,
            "invariants_preserved": (
                scale_before["node_count"] == scale_after["node_count"]
                and scale_before["edge_count"] == scale_after["edge_count"]
                and scale_before["entity_names_digest"] == scale_after["entity_names_digest"]
                and scale_before["edge_digest"] == scale_after["edge_digest"]
                and scale_before["fact_non_target_digest"] == scale_after["fact_non_target_digest"]
            ),
        },
    }


async def run_validation(driver: Any) -> dict[str, Any]:
    svo_service, split_fact_lines, kg_source_charset = await load_production()
    await svo_service.create_entity_name_vector_index(driver, dim=VECTOR_DIM)
    await wait_for_index(driver, "entity_name_vector")
    w1_w3 = await run_w1_to_w3(svo_service, split_fact_lines, kg_source_charset, driver)
    w4 = await run_w4(driver)
    return {**w1_w3, "w4": w4, "status": "completed"}


async def run_session(password: str) -> tuple[dict[str, Any], str | None]:
    """Keep driver creation, use, and close on one asyncio event loop."""

    driver = await wait_for_driver(password, W1_KG)
    result: dict[str, Any]
    try:
        result = await run_validation(driver)
    except Exception as exc:  # noqa: BLE001 - preserve teardown/reporting
        safe_message = str(exc).replace(password, "<redacted>").replace(f"neo4j/{password}", "neo4j/<redacted>")
        result = {
            "status": "failed",
            "error_type": type(exc).__name__,
            "error_message_sanitized": safe_message.splitlines()[0][:500],
        }
    close_error: str | None = None
    try:
        await driver.close()
    except Exception as exc:  # noqa: BLE001 - close must not block Docker teardown
        close_error = type(exc).__name__
    if close_error is not None:
        result["driver_close_error_type"] = close_error
    return result, close_error


def _baseline_ok(state: dict[str, str]) -> bool:
    return state == {"status": "running", "started_at": EXPECTED_KG4_STARTED_AT}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teardown", action="store_true", help="拆除且只拆除指定臨時容器")
    parser.add_argument("--output", type=Path, default=REPORT_OUTPUT)
    args = parser.parse_args()

    if args.teardown:
        teardown = teardown_temp_container()
        print(json.dumps({"teardown": teardown, "temp_absent_after": not teardown["present_after"]}, ensure_ascii=False))
        return 0

    kg4_start = kg4_state()
    if not _baseline_ok(kg4_start):
        raise SystemExit(
            "停止：kg2-neo4j 基準不符，請詢問使用者；"
            f"實測 status={kg4_start['status']} started_at={kg4_start['started_at']}"
        )
    existing = temp_container_names()
    if existing:
        raise SystemExit(f"停止：{TEMP_CONTAINER} 已存在（{existing}），請先由使用者處理")

    result: dict[str, Any] = {}
    launched = False
    try:
        password = generate_temp_password()
        launch_temp_container(password)
        launched = True
        result, _ = asyncio.run(run_session(password))
    except Exception as exc:  # noqa: BLE001 - preserve cleanup and report failure type
        safe_message = str(exc).replace(password, "<redacted>").replace(f"neo4j/{password}", "neo4j/<redacted>")
        result = {
            "status": "failed",
            "error_type": type(exc).__name__,
            "error_message_sanitized": safe_message.splitlines()[0][:500],
        }
    finally:
        teardown = teardown_temp_container() if launched else {"present_before": [], "present_after": []}
        kg4_end = kg4_state()
        result["w0"] = {
            "baseline_expected": EXPECTED_KG4_STARTED_AT,
            "kg4_start": kg4_start,
            "kg4_end": kg4_end,
            "kg4_unchanged": kg4_start == kg4_end,
            "container_args": {
                "name": TEMP_CONTAINER, "image": IMAGE, "ports": list(TEMP_PORTS),
                "memory": "3g", "volume": False, "bind_mount": False, "pull": False,
            },
        }
        result["w5"] = {
            "teardown": teardown,
            "temp_absent_after": not teardown.get("present_after"),
            "kg4_unchanged": kg4_start == kg4_end,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(_jsonable(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": result.get("status"), "output": str(args.output), "temp_absent_after": result.get("w5", {}).get("temp_absent_after"), "kg4_unchanged": result.get("w5", {}).get("kg4_unchanged")}, ensure_ascii=False))
    return 0 if result.get("status") == "completed" and result["w5"]["temp_absent_after"] and result["w5"]["kg4_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
