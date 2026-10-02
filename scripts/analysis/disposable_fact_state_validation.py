"""P3 disposable Neo4j validation for Fact lifecycle-state risks.

This script is intentionally zero-wiring: it creates synthetic data only in the
named throwaway container, calls existing read/retrieval functions for the
"current" observations, and keeps every lifecycle proposal in this file.
It never reads the repository ``.env``.  The temporary password exists only in
the parent process memory and the child environment used by ``docker run``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from neo4j import AsyncGraphDatabase

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from services import relation_lifecycle as rl
from services.retrieval.fact_candidates import _dedupe_facts_by_key


TEMP_CONTAINER = "kg2-throwaway-neo4j"
IMAGE = "neo4j:5.26-enterprise"
TEMP_URI = "bolt://127.0.0.1:27687"
TEMP_PASSWORD_ENV = "NEO4J_AUTH"
TEMP_PORTS = (27474, 27687)
KG4_ID = UUID("236903cf-055a-40a8-8923-b9d06601f3b7")
EXPECTED_KG4_STARTED_AT = "2026-10-01T12:36:49.303373783Z"
REPORT_OUTPUT = _REPO / "data" / "analysis" / "disposable_fact_state_validation_20261002.json"

SYNTHETIC_KG = uuid4()
FACT_LABEL = f"Fact_{str(SYNTHETIC_KG).replace('-', '_')}"
VECTOR_DIM = 8
RETRIEVABLE_STATES = [rl.CANDIDATE, rl.VALID, rl.DISPUTED]


class GateViolation(RuntimeError):
    """A connection or container request failed the P3 safety gate."""


def validate_connection_target(uri: str, kg_id: UUID | str | None = None) -> None:
    """Reject every target except the disposable Neo4j Bolt endpoint."""

    if "kg2-neo4j" in uri.lower():
        raise GateViolation("拒絕與 kg2-neo4j 相關的 URI")
    parsed = urlsplit(uri)
    try:
        port = parsed.port
    except ValueError as exc:
        raise GateViolation("URI 埠號格式無效") from exc
    if port == 17990:
        raise GateViolation("拒絕 KG#4 埠號")
    if parsed.scheme != "bolt" or parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise GateViolation("只允許 localhost/127.0.0.1 的 bolt URI")
    if port != 27687:
        raise GateViolation("只允許臨時容器 Bolt 埠 27687")
    if kg_id is not None and UUID(str(kg_id)) == KG4_ID:
        raise GateViolation("拒絕 KG#4 kg_id")


def generate_temp_password() -> str:
    """Generate a password without exposing it to argv, files, or output."""

    return secrets.token_urlsafe(32)


def build_docker_run_argv() -> list[str]:
    """Return the fixed, auditable run arguments (secret is passed by env)."""

    return [
        "run",
        "-d",
        "--name",
        TEMP_CONTAINER,
        "--hostname",
        TEMP_CONTAINER,
        "-p",
        "27474:7474",
        "-p",
        "27687:7687",
        "--memory",
        "3g",
        "--env",
        TEMP_PASSWORD_ENV,
        "--env",
        "NEO4J_ACCEPT_LICENSE_AGREEMENT=yes",
        "--env",
        "NEO4J_server_memory_heap_max__size=1G",
        "--env",
        "NEO4J_server_memory_pagecache_size=512M",
        IMAGE,
    ]


def _docker(args: list[str], *, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run one whitelisted Docker command without echoing command output."""

    completed = subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(f"docker {args[0]} failed with exit code {completed.returncode}")
    return completed


def temp_container_names() -> list[str]:
    result = _docker([
        "ps",
        "-a",
        "--filter",
        f"name=^/{TEMP_CONTAINER}$",
        "--format",
        "{{.Names}}",
    ])
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def kg4_state() -> dict[str, str]:
    """Read only State.Status and State.StartedAt from the protected container."""

    result = _docker([
        "inspect",
        "--format",
        "{{.State.Status}}|{{.State.StartedAt}}",
        "kg2-neo4j",
    ])
    status, started_at = result.stdout.strip().split("|", maxsplit=1)
    return {"status": status, "started_at": started_at}


def assert_ports_free() -> None:
    for port in TEMP_PORTS:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.25)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                raise GateViolation(f"臨時容器埠 {port} 已被占用")


def launch_temp_container(password: str) -> str:
    """Launch only the fixed disposable container; no pull, volume, or mount."""

    if temp_container_names():
        raise GateViolation(f"同名臨時容器 {TEMP_CONTAINER} 已存在，停止並詢問使用者")
    assert_ports_free()
    child_env = os.environ.copy()
    child_env[TEMP_PASSWORD_ENV] = f"neo4j/{password}"
    try:
        result = _docker(build_docker_run_argv(), env=child_env)
    finally:
        child_env.pop(TEMP_PASSWORD_ENV, None)
    container_id = result.stdout.strip()
    if not container_id:
        raise RuntimeError("docker run 未回傳容器識別字")
    return container_id


def teardown_temp_container() -> dict[str, object]:
    """Stop then remove only the exact disposable-container name."""

    present_before = temp_container_names()
    if not present_before:
        return {"present_before": [], "stop_exit_code": None, "rm_exit_code": None, "present_after": []}
    stopped = _docker(["stop", TEMP_CONTAINER], check=False)
    removed = _docker(["rm", TEMP_CONTAINER], check=False)
    present_after = temp_container_names()
    if present_after:
        raise RuntimeError(f"臨時容器拆除失敗：{present_after}")
    return {
        "present_before": present_before,
        "stop_exit_code": stopped.returncode,
        "rm_exit_code": removed.returncode,
        "present_after": present_after,
    }


@contextmanager
def import_production_without_project_env():
    """Import current functions while cwd has no project ``.env`` to read."""

    previous = Path.cwd()
    os.chdir(Path(tempfile.gettempdir()))
    try:
        yield
    finally:
        os.chdir(previous)


def load_current_functions() -> tuple[ModuleType, object, object, object]:
    """Load production retrieval functions without constructing project settings."""

    with import_production_without_project_env():
        from services import svo_service

    return (
        svo_service,
        svo_service.vector_search_facts,
        svo_service.revoke_chunk_facts,
        svo_service.bfs_query,
    )


async def wait_for_driver(password: str):
    validate_connection_target(TEMP_URI, SYNTHETIC_KG)
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


def _vector(values: list[float]) -> list[float]:
    return values + [0.0] * (VECTOR_DIM - len(values))


def _index_name() -> str:
    return f"fact_embedding_vector_{str(SYNTHETIC_KG).replace('-', '_')}"


async def cypher(driver, statement: str, **parameters):
    return await driver.execute_query(statement, **parameters)


async def create_fact(
    driver,
    *,
    fixture_id: str,
    subject: str,
    rel_type: str,
    object_: str,
    source_doc_id: UUID,
    chunk_index: int,
    embedding: list[float] | None,
    state: str | None,
    events_json: str | None = None,
    fact_text: str | None = None,
) -> None:
    await cypher(
        driver,
        f"""
        CREATE (f:Fact:{FACT_LABEL} {{
            kg_id: $kg_id,
            fixture_id: $fixture_id,
            subject: $subject,
            rel_type: $rel_type,
            object: $object,
            source_doc_id: $source_doc_id,
            source_svo_chunk_index: $chunk_index,
            fact_text: $fact_text,
            fact_embedding: $embedding,
            verb: $rel_type,
            confidence: 1.0
        }})
        FOREACH (_ IN CASE WHEN $state IS NULL THEN [] ELSE [1] END |
            SET f.lifecycle_state = $state)
        FOREACH (_ IN CASE WHEN $events_json IS NULL THEN [] ELSE [1] END |
            SET f.lifecycle_events_json = $events_json)
        """,
        kg_id=str(SYNTHETIC_KG),
        fixture_id=fixture_id,
        subject=subject,
        rel_type=rel_type,
        object=object_,
        source_doc_id=str(source_doc_id),
        chunk_index=chunk_index,
        fact_text=fact_text or f"{subject} {rel_type} {object_}",
        embedding=embedding,
        state=state,
        events_json=events_json,
    )


async def create_entity(driver, name: str) -> None:
    await cypher(
        driver,
        "MERGE (e:Entity {kg_id: $kg_id, name: $name}) SET e.type = '概念'",
        kg_id=str(SYNTHETIC_KG),
        name=name,
    )


async def show_index_online(driver) -> None:
    for _ in range(60):
        result = await cypher(
            driver,
            "SHOW INDEXES YIELD name, state WHERE name = $name RETURN state",
            name=_index_name(),
        )
        if result.records and result.records[0]["state"] == "ONLINE":
            return
        await asyncio.sleep(0.5)
    raise RuntimeError("Fact 向量索引未在等待時間內 ONLINE")


async def raw_fact_candidates(driver, query_vector: list[float], candidate_k: int = 8) -> list[dict]:
    result = await cypher(
        driver,
        f"""
        CALL db.index.vector.queryNodes('{_index_name()}', $candidate_k, $vector)
        YIELD node, score
        RETURN node.fixture_id AS fixture_id,
               node.subject AS subject, node.rel_type AS rel_type,
               node.object AS object, node.lifecycle_state AS lifecycle_state,
               node.source_doc_id AS source_doc_id,
               node.source_svo_chunk_index AS source_svo_chunk_index, score
        """,
        candidate_k=candidate_k,
        vector=query_vector,
    )
    return [dict(record) for record in result.records]


def proposal_filter_then_dedupe(records: list[dict]) -> list[dict]:
    """Report 234 proposal: state filter precedes the existing key dedupe."""

    filtered = [
        record
        for record in records
        if record.get("lifecycle_state") in {None, *RETRIEVABLE_STATES}
    ]
    return _dedupe_facts_by_key(filtered)


def compact_records(records: list[dict]) -> list[dict]:
    return [
        {
            "fixture_id": record.get("fixture_id"),
            "key": [record.get("subject"), record.get("rel_type"), record.get("object")],
            "lifecycle_state": record.get("lifecycle_state"),
            "score": round(float(record["score"]), 8) if record.get("score") is not None else None,
        }
        for record in records
    ]


async def run_scenarios(driver) -> dict[str, object]:
    _, vector_search_facts, revoke_chunk_facts, bfs_query = load_current_functions()
    docs = {name: uuid4() for name in ("c1_old", "c1_new", "c4_missing", "c4_superseded", "c2", "c3", "c5")}

    await create_entity(driver, "C2-A")
    await create_entity(driver, "C2-B")
    await create_entity(driver, "C3-A")
    await create_entity(driver, "C3-B")
    await create_entity(driver, "C5-A")
    await create_entity(driver, "C5-B")

    await create_fact(
        driver, fixture_id="c1-old", subject="同一主詞", rel_type="RELATED_TO", object_="同一受詞",
        source_doc_id=docs["c1_old"], chunk_index=1, embedding=_vector([1, 0, 0]), state=rl.SUPERSEDED,
    )
    await create_fact(
        driver, fixture_id="c1-new", subject="同一主詞", rel_type="RELATED_TO", object_="同一受詞",
        source_doc_id=docs["c1_new"], chunk_index=2, embedding=_vector([0.99, 0.1, 0]), state=rl.VALID,
    )
    await create_fact(
        driver, fixture_id="c4-missing", subject="舊資料主詞", rel_type="RELATED_TO", object_="舊資料受詞",
        source_doc_id=docs["c4_missing"], chunk_index=1, embedding=_vector([0, 0.98, 0.2]), state=None,
    )
    await create_fact(
        driver, fixture_id="c4-superseded", subject="舊資料主詞", rel_type="RELATED_TO", object_="舊資料受詞",
        source_doc_id=docs["c4_superseded"], chunk_index=2, embedding=_vector([0, 1, 0]), state=rl.SUPERSEDED,
    )
    await create_fact(
        driver, fixture_id="c2-current", subject="C2-A", rel_type="RELATED_TO", object_="C2-B",
        source_doc_id=docs["c2"], chunk_index=2, embedding=_vector([0, 0, 1]), state=rl.VALID,
    )
    await cypher(
        driver,
        """
        MERGE (a:Entity {kg_id: $kg_id, name: 'C2-A'})
        MERGE (b:Entity {kg_id: $kg_id, name: 'C2-B'})
        MERGE (a)-[r:RELATED_TO {kg_id: $kg_id}]->(b)
        SET r.citations_json = $citations_json, r.confidence = 1.0
        """,
        kg_id=str(SYNTHETIC_KG),
        citations_json=json.dumps([{
            "source_doc_id": str(docs["c2"]), "source_svo_chunk_index": 2, "verb": "關聯",
        }], ensure_ascii=False),
    )

    await create_fact(
        driver, fixture_id="c3-anchor", subject="C3-A", rel_type="RELATED_TO", object_="C3-B",
        source_doc_id=docs["c3"], chunk_index=3, embedding=None, state=rl.SUPERSEDED,
    )
    await cypher(
        driver,
        """
        MERGE (a:Entity {kg_id: $kg_id, name: 'C3-A'})
        MERGE (b:Entity {kg_id: $kg_id, name: 'C3-B'})
        MERGE (a)-[r:RELATED_TO {kg_id: $kg_id}]->(b)
        SET r.citations_json = $citations_json, r.confidence = 1.0
        """,
        kg_id=str(SYNTHETIC_KG),
        citations_json=json.dumps([{
            "source_doc_id": str(docs["c3"]), "source_svo_chunk_index": 3, "verb": "關聯",
        }], ensure_ascii=False),
    )

    await create_fact(
        driver, fixture_id="c5-state", subject="C5-A", rel_type="RELATED_TO", object_="C5-B",
        source_doc_id=docs["c5"], chunk_index=5, embedding=None, state=rl.CANDIDATE,
        events_json=json.dumps([{"event_type": rl.EXTRACTED}], ensure_ascii=False),
    )

    await cypher(
        driver,
        """
        CREATE (:Chunk {kg_id: $kg_id, source_doc_id: $source_doc_id, chunk_index: 2})
        """,
        kg_id=str(SYNTHETIC_KG), source_doc_id=str(docs["c2"]),
    )

    # C1: current vector search dedupes before any proposed lifecycle filter.
    await cypher(
        driver,
        f"""
        CREATE VECTOR INDEX {_index_name()} IF NOT EXISTS
        FOR (f:{FACT_LABEL}) ON f.fact_embedding
        OPTIONS {{ indexConfig: {{ `vector.dimensions`: $dim, `vector.similarity_function`: 'cosine' }} }}
        """,
        dim=VECTOR_DIM,
    )
    await show_index_online(driver)
    c1_query = _vector([1, 0, 0])
    c1_actual = await vector_search_facts(driver, SYNTHETIC_KG, c1_query, top_k=1)
    c1_raw = await raw_fact_candidates(driver, c1_query)
    c1_proposed = proposal_filter_then_dedupe(c1_raw)[:1]
    c1_actual_fixture = next((r for r in c1_raw if r["source_doc_id"] == c1_actual[0]["source_doc_id"]), None) if c1_actual else None

    # C2: observe current physical deletion, then perform the proposal on a new node.
    before_c2 = await cypher(
        driver, "MATCH (f:Fact {kg_id: $kg_id, fixture_id: 'c2-current'}) RETURN count(f) AS n", kg_id=str(SYNTHETIC_KG)
    )
    c2_actual_stats = await revoke_chunk_facts(driver, SYNTHETIC_KG, str(docs["c2"]), 2)
    after_c2 = await cypher(
        driver, "MATCH (f:Fact {kg_id: $kg_id, fixture_id: 'c2-current'}) RETURN count(f) AS n", kg_id=str(SYNTHETIC_KG)
    )
    await create_fact(
        driver, fixture_id="c2-proposal", subject="C2-A", rel_type="RELATED_TO", object_="C2-B",
        source_doc_id=docs["c2"], chunk_index=2, embedding=_vector([0, 0, 1]), state=rl.VALID,
        events_json=json.dumps([{"event_type": rl.EXTRACTED}, {"event_type": rl.VERIFIED}], ensure_ascii=False),
    )
    c2_proposal_event = {"event_type": rl.REVOKED, "reason": "synthetic P3 revoke"}
    await cypher(
        driver,
        """
        MATCH (f:Fact {kg_id: $kg_id, fixture_id: 'c2-proposal'})
        WITH f, coalesce(f.lifecycle_events_json, '[]') AS prior
        SET f.lifecycle_events_json =
            CASE WHEN prior = '[]' THEN '[' + $event_json + ']'
                 ELSE substring(prior, 0, size(prior) - 1) + ',' + $event_json + ']'
            END,
            f.lifecycle_state = $rejected
        """,
        kg_id=str(SYNTHETIC_KG), event_json=json.dumps(c2_proposal_event, ensure_ascii=False, separators=(",", ":")),
        rejected=rl.REJECTED,
    )
    c2_proposed_read = await cypher(
        driver,
        """
        MATCH (f:Fact {kg_id: $kg_id, fixture_id: 'c2-proposal'})
        RETURN f.lifecycle_state AS lifecycle_state, f.lifecycle_events_json AS lifecycle_events_json
        """,
        kg_id=str(SYNTHETIC_KG),
    )
    c2_retrievable = await cypher(
        driver,
        """
        MATCH (f:Fact {kg_id: $kg_id, fixture_id: 'c2-proposal'})
        RETURN count(f) AS n,
               count(CASE WHEN f.lifecycle_state IS NULL OR f.lifecycle_state IN $states THEN 1 END) AS retrievable
        """,
        kg_id=str(SYNTHETIC_KG), states=RETRIEVABLE_STATES,
    )

    # C3: BFS reads the relationship edge, while the proposal aggregates Fact state.
    c3_started = time.perf_counter()
    c3_bfs = await bfs_query(driver, SYNTHETIC_KG, ["C3-A"], hops=1)
    c3_bfs_seconds = time.perf_counter() - c3_started
    c3_aggregate = await cypher(
        driver,
        """
        MATCH (s:Entity {kg_id: $kg_id, name: 'C3-A'})-[r:RELATED_TO {kg_id: $kg_id}]->(o:Entity {kg_id: $kg_id, name: 'C3-B'})
        OPTIONAL MATCH (f:Fact {kg_id: $kg_id, subject: s.name, rel_type: type(r), object: o.name})
        WITH collect(f) AS facts
        RETURN size([f IN facts WHERE f IS NOT NULL]) AS fact_count,
               size([f IN facts WHERE f IS NOT NULL AND (f.lifecycle_state IS NULL OR f.lifecycle_state IN $states)]) AS retrievable_count
        """,
        kg_id=str(SYNTHETIC_KG), states=RETRIEVABLE_STATES,
    )
    await cypher(
        driver,
        f"""
        UNWIND range(1, $count) AS i
        CREATE (f:Fact:{FACT_LABEL} {{
            kg_id: $kg_id, fixture_id: 'c3-load-' + toString(i),
            subject: 'C3-A', rel_type: 'RELATED_TO', object: 'C3-B',
            source_doc_id: $source_doc_id, source_svo_chunk_index: i,
            fact_text: 'C3 synthetic load', verb: 'RELATED_TO', confidence: 1.0,
            lifecycle_state: $state
        }})
        """,
        count=1000, kg_id=str(SYNTHETIC_KG), source_doc_id=str(docs["c3"]), state=rl.SUPERSEDED,
    )
    c3_load_started = time.perf_counter()
    c3_load_aggregate = await cypher(
        driver,
        """
        MATCH (s:Entity {kg_id: $kg_id, name: 'C3-A'})-[r:RELATED_TO {kg_id: $kg_id}]->(o:Entity {kg_id: $kg_id, name: 'C3-B'})
        OPTIONAL MATCH (f:Fact {kg_id: $kg_id, subject: s.name, rel_type: type(r), object: o.name})
        WITH collect(f) AS facts
        RETURN size([f IN facts WHERE f IS NOT NULL]) AS fact_count,
               size([f IN facts WHERE f IS NOT NULL AND (f.lifecycle_state IS NULL OR f.lifecycle_state IN $states)]) AS retrievable_count
        """,
        kg_id=str(SYNTHETIC_KG), states=RETRIEVABLE_STATES,
    )
    c3_load_seconds = time.perf_counter() - c3_load_started

    # C4: current dedupe can retain the closer superseded record; proposed filter keeps missing state.
    c4_query = _vector([0, 1, 0])
    c4_actual = await vector_search_facts(driver, SYNTHETIC_KG, c4_query, top_k=1)
    c4_raw = await raw_fact_candidates(driver, c4_query)
    c4_proposed = proposal_filter_then_dedupe(c4_raw)[:1]
    c4_actual_fixture = next((r for r in c4_raw if r["source_doc_id"] == c4_actual[0]["source_doc_id"]), None) if c4_actual else None

    # C5: append in Cypher, replay in the existing pure state-machine prototype, then audit drift.
    c5_event = {
        "event_type": rl.VERIFIED,
        "effective_date": "2026-10-02",
        "reason": "synthetic verification",
        "evidence_ref": "P3-C5",
        "trigger_kind": "人工",
    }
    await cypher(
        driver,
        """
        MATCH (f:Fact {kg_id: $kg_id, fixture_id: 'c5-state'})
        WITH f, coalesce(f.lifecycle_events_json, '[]') AS prior
        SET f.lifecycle_events_json =
            CASE WHEN prior = '[]' THEN '[' + $event_json + ']'
                 ELSE substring(prior, 0, size(prior) - 1) + ',' + $event_json + ']'
            END,
            f.lifecycle_state = $state
        """,
        kg_id=str(SYNTHETIC_KG), event_json=json.dumps(c5_event, ensure_ascii=False, separators=(",", ":")), state=rl.VALID,
    )
    c5_row = await cypher(
        driver,
        "MATCH (f:Fact {kg_id: $kg_id, fixture_id: 'c5-state'}) RETURN f.lifecycle_state AS state, f.lifecycle_events_json AS events_json",
        kg_id=str(SYNTHETIC_KG),
    )
    c5_value = dict(c5_row.records[0])
    c5_events = [rl.LifecycleEvent(**event) for event in json.loads(c5_value["events_json"])]
    c5_replay = rl.replay(c5_events)
    await cypher(
        driver,
        "MATCH (f:Fact {kg_id: $kg_id, fixture_id: 'c5-state'}) SET f.lifecycle_state = $state",
        kg_id=str(SYNTHETIC_KG), state=rl.REJECTED,
    )
    c5_drift_row = await cypher(
        driver,
        "MATCH (f:Fact {kg_id: $kg_id, fixture_id: 'c5-state'}) RETURN f.lifecycle_state AS state",
        kg_id=str(SYNTHETIC_KG),
    )
    c5_drift_state = c5_drift_row.records[0]["state"]

    c1_expected = c1_actual_fixture is not None and c1_actual_fixture["fixture_id"] == "c1-old" and c1_proposed and c1_proposed[0]["fixture_id"] == "c1-new"
    c2_expected = before_c2.records[0]["n"] == 1 and after_c2.records[0]["n"] == 0 and c2_proposed_read.records[0]["lifecycle_state"] == rl.REJECTED and c2_retrievable.records[0]["retrievable"] == 0
    c3_expected = bool(c3_bfs) and c3_aggregate.records[0]["retrievable_count"] == 0 and c3_load_aggregate.records[0]["fact_count"] >= 1000
    c4_expected = c4_proposed and c4_proposed[0]["fixture_id"] == "c4-missing"
    c5_expected = c5_value["state"] == c5_replay.final_state == rl.VALID and c5_replay.ok and c5_drift_state != c5_replay.final_state

    return {
        "synthetic_kg_id": str(SYNTHETIC_KG),
        "c1": {
            "current": {"returned": compact_records([c1_actual_fixture] if c1_actual_fixture else [])},
            "proposal": {"raw": compact_records(c1_raw), "returned": compact_records(c1_proposed[:1])},
            "matches_inference": bool(c1_expected),
            "unexpected_findings": [],
        },
        "c2": {
            "current": {"before_fact_count": before_c2.records[0]["n"], "revoke_stats": dict(c2_actual_stats), "after_fact_count": after_c2.records[0]["n"]},
            "proposal": {"state": c2_proposed_read.records[0]["lifecycle_state"], "events_json": c2_proposed_read.records[0]["lifecycle_events_json"], "retrievable_count": c2_retrievable.records[0]["retrievable"]},
            "matches_inference": bool(c2_expected),
            "unexpected_findings": [],
        },
        "c3": {
            "current": {"bfs_return_count": len(c3_bfs), "bfs_seconds": round(c3_bfs_seconds, 6)},
            "proposal": {"one_fact": dict(c3_aggregate.records[0]), "about_1000_facts": dict(c3_load_aggregate.records[0]), "about_1000_query_seconds": round(c3_load_seconds, 6)},
            "matches_inference": bool(c3_expected),
            "unexpected_findings": [],
        },
        "c4": {
            "current": {"returned": compact_records([c4_actual_fixture] if c4_actual_fixture else [])},
            "proposal": {"raw": compact_records(c4_raw), "returned": compact_records(c4_proposed[:1])},
            "matches_inference": bool(c4_expected),
            "unexpected_findings": [],
        },
        "c5": {
            "current": {"cached_state_after_append": c5_value["state"], "event_count": len(c5_events), "replay_final_state": c5_replay.final_state, "replay_ok": c5_replay.ok},
            "proposal": {"drift_state": c5_drift_state, "audit_detected_drift": c5_drift_state != c5_replay.final_state},
            "matches_inference": bool(c5_expected),
            "unexpected_findings": [],
        },
    }


async def async_main(password: str) -> dict[str, object]:
    driver = await wait_for_driver(password)
    try:
        return await run_scenarios(driver)
    finally:
        await driver.close()


def _run_with_password() -> dict[str, object]:
    """Launch and retain the one in-memory credential for the matching driver."""

    baseline = kg4_state()
    if baseline != {"status": "running", "started_at": EXPECTED_KG4_STARTED_AT}:
        raise GateViolation(f"kg2-neo4j 基準不符：{baseline}")
    if temp_container_names():
        raise GateViolation(f"同名臨時容器 {TEMP_CONTAINER} 已存在，停止並詢問使用者")
    assert_ports_free()
    password = generate_temp_password()
    created = False
    scenario_result: dict[str, object] = {}
    teardown_result: dict[str, object] = {}
    try:
        created = bool(launch_temp_container(password))
        scenario_result = asyncio.run(async_main(password))
    finally:
        del password
        if created:
            teardown_result = teardown_temp_container()
        final_state = kg4_state()
    scenario_result["kg4_baseline"] = baseline
    scenario_result["kg4_final"] = final_state
    scenario_result["kg4_unchanged"] = final_state == baseline
    scenario_result["environment_observations"] = [
        "bfs_query 在僅建立 RELATED_TO 的合成圖上仍枚舉既有 SVO 關係型別清單；Neo4j 對不存在的其他型別發出通知，但 RELATED_TO 結果仍為 1 筆。",
        "production import 產生既有 requests 依賴版本警告；未呼叫 LLM、embedding 或 Ollama。",
    ]
    scenario_result["temp_teardown"] = teardown_result
    scenario_result["temp_absent_after"] = not temp_container_names()
    return scenario_result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teardown", action="store_true", help="stop/remove only the named throwaway container")
    parser.add_argument("--output", type=Path, default=REPORT_OUTPUT)
    args = parser.parse_args()
    if args.teardown:
        teardown = teardown_temp_container()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"temp_teardown": teardown}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 0

    result: dict[str, object]
    try:
        result = _run_with_password()
        result["status"] = "completed"
    except Exception as exc:  # noqa: BLE001 - report gate/validation failure, cleanup is in finally
        result = {"status": "failed", "error_type": type(exc).__name__, "error": str(exc)}
        try:
            if temp_container_names():
                result["emergency_teardown"] = teardown_temp_container()
            result["kg4_final"] = kg4_state()
        except Exception as cleanup_exc:  # noqa: BLE001
            result["cleanup_error_type"] = type(cleanup_exc).__name__
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
