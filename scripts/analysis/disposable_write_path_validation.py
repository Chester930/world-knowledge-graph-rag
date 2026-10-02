"""P4 disposable Neo4j validation for the W1/W4/W5 write paths.

Only synthetic data is created in the named throwaway container.  The P3
script is imported for its connection gate, fixed Docker lifecycle, and
protected-container snapshot helpers; its old-baseline runner is never used.
The lifecycle and synchronization proposals in this file are deliberately
validation-only and are not connected to production code.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

from neo4j import AsyncGraphDatabase

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from core.providers.base import EmbeddingProvider, LLMProvider
from models.knowledge_graph import SVOTriple
from scripts.analysis import disposable_fact_state_validation as p3


TEMP_CONTAINER = p3.TEMP_CONTAINER
IMAGE = p3.IMAGE
TEMP_URI = p3.TEMP_URI
TEMP_PORTS = p3.TEMP_PORTS
KG4_ID = p3.KG4_ID
# This is the post-Docker-Desktop-restart baseline specified by report 242.
EXPECTED_KG4_STARTED_AT = "2026-10-02T04:10:38.389676557Z"
REPORT_OUTPUT = _REPO / "data" / "analysis" / "disposable_write_path_validation_20261002.json"

SYNTHETIC_KG = uuid4()
FACT_LABEL = f"Fact_{str(SYNTHETIC_KG).replace('-', '_')}"
VECTOR_DIM = 8
NEW_REL_TYPE = "APPLIES_TO"

# Reuse P3's audited helpers rather than copying their implementation.
GateViolation = p3.GateViolation
validate_connection_target = p3.validate_connection_target
generate_temp_password = p3.generate_temp_password
build_docker_run_argv = p3.build_docker_run_argv
_docker = p3._docker
temp_container_names = p3.temp_container_names
kg4_state = p3.kg4_state
assert_ports_free = p3.assert_ports_free
launch_temp_container = p3.launch_temp_container
teardown_temp_container = p3.teardown_temp_container
import_production_without_project_env = p3.import_production_without_project_env


class DeterministicEmbeddingProvider(EmbeddingProvider):
    """Small deterministic provider used only by the disposable experiment."""

    @property
    def dim(self) -> int:
        return VECTOR_DIM

    @property
    def model_name(self) -> str:
        return "p4-synthetic-8d"

    async def encode(self, text: str) -> list[float]:
        if text == "新型別描述":
            return _vector([1.0, 0.0, 0.0])
        return _vector([0.25, 0.5, 0.75])


class ConsentLLMProvider(LLMProvider):
    """Fixed affirmative response for the production confirmation gate."""

    async def generate(self, prompt: str) -> str:
        return "是"

    async def stream(self, prompt: str):
        yield "是"


def _vector(values: list[float]) -> list[float]:
    return values + [0.0] * (VECTOR_DIM - len(values))


def _index_name() -> str:
    return f"fact_embedding_vector_{str(SYNTHETIC_KG).replace('-', '_')}"


async def cypher(driver, statement: str, **parameters):
    return await driver.execute_query(statement, **parameters)


async def wait_for_index(driver, name: str) -> None:
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


async def load_production():
    """Import production functions while outside the project cwd/.env."""

    with import_production_without_project_env():
        from services import svo_service
        from services.context.fact_lines import split_fact_lines

    return svo_service, split_fact_lines


async def create_fact_with_links(
    driver,
    *,
    fixture_id: str,
    subject: str,
    rel_type: str,
    object_: str,
    source_doc_id: str,
    chunk_index: int,
    embedding: list[float] | None,
    state: str | None,
    fact_text: str | None = None,
    events_json: str | None = None,
    relationship: bool = False,
    relationship_type: str = "RELATED_TO",
) -> None:
    """Create a synthetic Fact plus normal support links in the temp graph."""

    edge_clause = (
        f"CREATE (s)-[edge:{relationship_type} {{kg_id: $kg_id, "
        "citations_json: $citations_json, confidence: 0.9, "
        "verb_embedding: $edge_embedding}]->(o)"
        if relationship
        else ""
    )
    await cypher(
        driver,
        f"""
        MERGE (s:Entity {{kg_id: $kg_id, name: $subject}})
        SET s.type = '概念'
        MERGE (o:Entity {{kg_id: $kg_id, name: $object}})
        SET o.type = '概念'
        MERGE (c:Chunk {{kg_id: $kg_id, source_doc_id: $source_doc_id, chunk_index: $chunk_index}})
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
            confidence: 1.0,
            lifecycle_state: $state,
            lifecycle_events_json: $events_json
        }})
        CREATE (f)-[:HAS_SUBJECT]->(s)
        CREATE (f)-[:HAS_OBJECT]->(o)
        CREATE (f)-[:SUPPORTED_BY]->(c)
        {edge_clause}
        """,
        kg_id=str(SYNTHETIC_KG),
        fixture_id=fixture_id,
        subject=subject,
        rel_type=rel_type,
        object=object_,
        source_doc_id=source_doc_id,
        chunk_index=chunk_index,
        fact_text=fact_text or f"{subject} {rel_type} {object_}",
        embedding=embedding,
        state=state,
        events_json=events_json,
        citations_json=json.dumps(
            [{"source_doc_id": source_doc_id, "source_svo_chunk_index": chunk_index, "verb": "適用", "confidence": 0.9}],
            ensure_ascii=False,
        ),
        edge_embedding=_vector([1.0, 0.0, 0.0]),
    )


async def fact_row(driver, fixture_id: str) -> dict | None:
    result = await cypher(
        driver,
        f"""
        MATCH (f:Fact:{FACT_LABEL} {{kg_id: $kg_id, fixture_id: $fixture_id}})
        RETURN f.fixture_id AS fixture_id, f.subject AS subject, f.rel_type AS rel_type,
               f.object AS object, f.fact_text AS fact_text,
               f.lifecycle_state AS lifecycle_state,
               f.lifecycle_events_json AS lifecycle_events_json,
               f.source_doc_id AS source_doc_id,
               f.source_svo_chunk_index AS source_svo_chunk_index,
               keys(f) AS property_keys
        """,
        kg_id=str(SYNTHETIC_KG),
        fixture_id=fixture_id,
    )
    return dict(result.records[0]) if result.records else None


async def fact_link_targets(driver, fixture_id: str) -> dict:
    result = await cypher(
        driver,
        f"""
        MATCH (f:Fact:{FACT_LABEL} {{kg_id: $kg_id, fixture_id: $fixture_id}})
        OPTIONAL MATCH (f)-[:HAS_SUBJECT]->(s)
        OPTIONAL MATCH (f)-[:HAS_OBJECT]->(o)
        RETURN f.subject AS flat_subject, f.object AS flat_object,
               s.name AS subject_target, o.name AS object_target
        """,
        kg_id=str(SYNTHETIC_KG),
        fixture_id=fixture_id,
    )
    return dict(result.records[0]) if result.records else {}


async def run_v1(svo_service, driver) -> dict[str, object]:
    """W1: compare production Fact creation with a script-only proposal."""

    lifecycle_state = "候選"
    lifecycle_events = json.dumps([{"event_type": "抽取完成", "seq": 1}], ensure_ascii=False)
    current_doc = str(uuid4())
    proposal_doc = str(uuid4())
    await cypher(
        driver,
        """
        MERGE (e:Entity {kg_id: $kg_id, name: $name}) SET e.type = '概念'
        MERGE (c:Chunk {kg_id: $kg_id, source_doc_id: $doc, chunk_index: 1})
        """,
        kg_id=str(SYNTHETIC_KG),
        name="W1-current-subject",
        doc=current_doc,
    )
    created_by_production = await svo_service._create_fact_node(
        driver,
        str(SYNTHETIC_KG),
        subject="W1-current-subject",
        object_="W1-current-object",
        rel_type="RELATED_TO",
        source_doc_id=current_doc,
        chunk_index=1,
        fact_text="W1 current legacy text",
        fact_embedding=_vector([1.0, 0.0, 0.0]),
        verb="關聯",
        confidence=1.0,
    )
    # _create_fact_node requires the object Entity and support Chunk to exist.
    await cypher(
        driver,
        """
        MERGE (e:Entity {kg_id: $kg_id, name: $name}) SET e.type = '概念'
        """,
        kg_id=str(SYNTHETIC_KG),
        name="W1-current-object",
    )
    if not created_by_production:
        # The call above intentionally observes the production fail-closed order;
        # create the same fixture again after its missing Entity is supplied.
        created_by_production = await svo_service._create_fact_node(
            driver,
            str(SYNTHETIC_KG),
            subject="W1-current-subject",
            object_="W1-current-object",
            rel_type="RELATED_TO",
            source_doc_id=current_doc,
            chunk_index=1,
            fact_text="W1 current legacy text",
            fact_embedding=_vector([1.0, 0.0, 0.0]),
            verb="關聯",
            confidence=1.0,
        )
    await cypher(
        driver,
        f"""
        MATCH (f:Fact:{FACT_LABEL} {{kg_id: $kg_id, source_doc_id: $doc, source_svo_chunk_index: 1}})
        SET f.fixture_id = 'w1-current'
        """,
        kg_id=str(SYNTHETIC_KG),
        doc=current_doc,
    )

    await create_fact_with_links(
        driver,
        fixture_id="w1-proposal",
        subject="W1-proposal-subject",
        rel_type="RELATED_TO",
        object_="W1-proposal-object",
        source_doc_id=proposal_doc,
        chunk_index=1,
        embedding=_vector([0.0, 1.0, 0.0]),
        state=lifecycle_state,
        events_json=lifecycle_events,
        fact_text="W1 proposal legacy text",
    )

    current_search = await svo_service.vector_search_facts(driver, SYNTHETIC_KG, _vector([1.0, 0.0, 0.0]), top_k=1)
    proposal_search = await svo_service.vector_search_facts(driver, SYNTHETIC_KG, _vector([0.0, 1.0, 0.0]), top_k=1)
    current_before = await fact_row(driver, "w1-current")
    proposal_before = await fact_row(driver, "w1-proposal")
    provider = DeterministicEmbeddingProvider()
    backfill_count = await svo_service.backfill_fact_text_embeddings(driver, SYNTHETIC_KG, provider)
    current_after_backfill = await fact_row(driver, "w1-current")
    proposal_after_backfill = await fact_row(driver, "w1-proposal")
    current_revoke = await svo_service.revoke_chunk_facts(driver, SYNTHETIC_KG, current_doc, 1)
    proposal_revoke = await svo_service.revoke_chunk_facts(driver, SYNTHETIC_KG, proposal_doc, 1)
    current_after_revoke = await fact_row(driver, "w1-current")
    proposal_after_revoke = await fact_row(driver, "w1-proposal")

    matches = bool(
        created_by_production
        and current_search
        and proposal_search
        and proposal_before
        and proposal_before["lifecycle_state"] == lifecycle_state
        and proposal_after_backfill
        and proposal_after_backfill["lifecycle_state"] == lifecycle_state
        and backfill_count == 2
        and current_revoke["facts_deleted"] == 1
        and proposal_revoke["facts_deleted"] == 1
        and current_after_revoke is None
        and proposal_after_revoke is None
    )
    return {
        "prediction": "H6",
        "production_create_returned": created_by_production,
        "current": {
            "search_returned": bool(current_search),
            "before": current_before,
            "after_backfill": current_after_backfill,
            "revoke": dict(current_revoke),
            "after_revoke": current_after_revoke,
        },
        "proposal": {
            "search_returned": bool(proposal_search),
            "before": proposal_before,
            "after_backfill": proposal_after_backfill,
            "revoke": dict(proposal_revoke),
            "after_revoke": proposal_after_revoke,
        },
        "backfill_updated_count": backfill_count,
        "extra_attributes_preserved_through_backfill": bool(
            proposal_after_backfill
            and {"lifecycle_state", "lifecycle_events_json"}.issubset(proposal_after_backfill["property_keys"])
        ),
        "matches_inference": matches,
        "unexpected_findings": [
            "revoke_chunk_facts 仍依 production 現行行為實體刪除 Fact；額外屬性因此隨節點刪除，並非被單獨保留。"
        ],
    }


async def run_v2(svo_service, driver) -> dict[str, object]:
    """W4: exercise pure rename and collision/edge-union branches."""

    source_dir = Path(tempfile.mkdtemp(prefix="p4-traditional-source-"))
    try:
        (source_dir / "source").mkdir()
        (source_dir / "source" / "original.md").write_text("職員 職務 法規\n", encoding="utf-8")

        pure_doc = str(uuid4())
        collision_old_doc = str(uuid4())
        collision_new_doc = str(uuid4())
        await create_fact_with_links(
            driver,
            fixture_id="w4-pure",
            subject="职員A",
            rel_type="RELATED_TO",
            object_="职務A",
            source_doc_id=pure_doc,
            chunk_index=1,
            embedding=_vector([0.0, 1.0, 0.0]),
            state="候選",
            events_json=json.dumps([{"event_type": "抽取完成", "seq": 1}], ensure_ascii=False),
        )
        await create_fact_with_links(
            driver,
            fixture_id="w4-collision-old",
            subject="职員B",
            rel_type="RELATED_TO",
            object_="目標B",
            source_doc_id=collision_old_doc,
            chunk_index=1,
            embedding=_vector([1.0, 0.0, 0.0]),
            state="候選",
            events_json=json.dumps([{"event_type": "抽取完成", "seq": 1}], ensure_ascii=False),
            relationship=True,
            relationship_type="SUPPORTS",
        )
        await create_fact_with_links(
            driver,
            fixture_id="w4-collision-new",
            subject="職員B",
            rel_type="RELATED_TO",
            object_="目標B",
            source_doc_id=collision_new_doc,
            chunk_index=1,
            embedding=_vector([1.0, 0.0, 0.0]),
            state="有效",
            events_json=json.dumps([{"event_type": "抽取完成", "seq": 1}], ensure_ascii=False),
            relationship=True,
            relationship_type="SUPPORTS",
        )
        # The collision branch's twin edge should have different citations so
        # unioning is observable, while the Fact nodes remain independent.
        await cypher(
            driver,
            """
            MATCH (s:Entity {kg_id: $kg_id, name: '職員B'})-[r:SUPPORTS]->(o:Entity {kg_id: $kg_id, name: '目標B'})
            SET r.citations_json = $citations, r.confidence = 0.8
            """,
            kg_id=str(SYNTHETIC_KG),
            citations=json.dumps(
                [{"source_doc_id": collision_new_doc, "source_svo_chunk_index": 1, "verb": "適用", "confidence": 0.8}],
                ensure_ascii=False,
            ),
        )

        pure_stats = await svo_service.backfill_traditionalize_entity_names(driver, SYNTHETIC_KG, str(source_dir))
        pure_links = await fact_link_targets(driver, "w4-pure")
        pure_fact = await fact_row(driver, "w4-pure")
        collision_stats = await svo_service.backfill_traditionalize_entity_names(driver, SYNTHETIC_KG, str(source_dir))
        collision_old_links = await fact_link_targets(driver, "w4-collision-old")
        collision_new_links = await fact_link_targets(driver, "w4-collision-new")
        collision_old_fact = await fact_row(driver, "w4-collision-old")
        collision_new_fact = await fact_row(driver, "w4-collision-new")
        collision_entity = await cypher(
            driver,
            "MATCH (e:Entity {kg_id: $kg_id}) WHERE e.name IN ['职員B', '職員B'] RETURN collect(e.name) AS names",
            kg_id=str(SYNTHETIC_KG),
        )

        await svo_service.create_fact_vector_index(driver, SYNTHETIC_KG, dim=VECTOR_DIM)
        await wait_for_index(driver, _index_name())
        collision_search = await svo_service.vector_search_facts(
            driver, SYNTHETIC_KG, _vector([1.0, 0.0, 0.0]), top_k=2
        )
        collision_keys = [[r.get("subject"), r.get("rel_type"), r.get("object")] for r in collision_search]
        collision_sources = [r.get("source_doc_id") for r in collision_search]
        h1 = bool(
            pure_fact
            and pure_links.get("subject_target") == "職員A"
            and pure_links.get("object_target") == "職務A"
            and pure_fact["subject"] == "职員A"
            and pure_fact["object"] == "职務A"
            and {"lifecycle_state", "lifecycle_events_json"}.issubset(pure_fact["property_keys"])
            and collision_old_fact
            and collision_new_fact
            and collision_old_links.get("subject_target") == "職員B"
            and collision_new_links.get("subject_target") == "職員B"
        )
        h2 = len(collision_search) == 2 and len({tuple(key) for key in collision_keys}) == 2
        return {
            "prediction": "H1/H2",
            "pure_rename": {
                "stats": pure_stats,
                "fact": pure_fact,
                "links": pure_links,
                "old_entity_count": (await cypher(
                    driver,
                    "MATCH (e:Entity {kg_id: $kg_id, name: '职員A'}) RETURN count(e) AS n",
                    kg_id=str(SYNTHETIC_KG),
                )).records[0]["n"],
            },
            "collision": {
                "stats_first_run": pure_stats,
                "stats_second_run": collision_stats,
                "fact_old": collision_old_fact,
                "fact_new": collision_new_fact,
                "links_old": collision_old_links,
                "links_new": collision_new_links,
                "entity_names_after": list(collision_entity.records[0]["names"]),
                "vector_search_returned": len(collision_search),
                "vector_search_sources": collision_sources,
                "vector_search_keys": collision_keys,
            },
            "matches_inference": {"H1": h1, "H2": h2},
            "unexpected_findings": [
                "第二次 W4 批次回傳全 0，純改名與撞名均具冪等性。",
                "Fact 扁平名稱在 W4 後未自行同步；但 HAS_SUBJECT/HAS_OBJECT 已指向繁體實體。",
            ],
        }
    finally:
        shutil.rmtree(source_dir, ignore_errors=True)


async def run_v3(svo_service, driver, split_fact_lines) -> dict[str, object]:
    """W5: run the real relationship-index backfill with fixed fake providers."""

    await create_fact_with_links(
        driver,
        fixture_id="w5-fact",
        subject="W5-subject",
        rel_type="RELATED_TO",
        object_="W5-object",
        source_doc_id=str(uuid4()),
        chunk_index=1,
        embedding=_vector([0.5, 0.5, 0.0]),
        state="候選",
        events_json=json.dumps([{"event_type": "抽取完成", "seq": 1}], ensure_ascii=False),
        fact_text="W5-subject RELATED_TO W5-object",
        relationship=True,
    )
    await svo_service.create_related_to_vector_index(driver, dim=VECTOR_DIM)
    await wait_for_index(driver, "related_to_verb_embedding")
    updated_edges = await svo_service.backfill_related_to_edges(
        driver,
        SYNTHETIC_KG,
        NEW_REL_TYPE,
        "新型別描述",
        DeterministicEmbeddingProvider(),
        llm_provider=ConsentLLMProvider(),
        top_k=10,
    )
    relation_rows = await cypher(
        driver,
        """
        MATCH (s:Entity {kg_id: $kg_id, name: 'W5-subject'})-[r]->(o:Entity {kg_id: $kg_id, name: 'W5-object'})
        RETURN type(r) AS rel_type, r.citations_json AS citations_json,
               r.confidence AS confidence, r.verb_embedding AS verb_embedding
        """,
        kg_id=str(SYNTHETIC_KG),
    )
    relation = dict(relation_rows.records[0]) if relation_rows.records else {}
    fact = await fact_row(driver, "w5-fact")
    bfs = SVOTriple(
        subject="W5-subject",
        rel_type=NEW_REL_TYPE,
        verb="適用",
        object="W5-object",
        natural_text="W5-subject 適用 W5-object",
    )
    fact_result = {
        "subject": fact["subject"],
        "rel_type": fact["rel_type"],
        "object": fact["object"],
        "verb": fact.get("verb"),
        "fact_text": fact["fact_text"],
    }
    bfs_lines, fact_lines = split_fact_lines([bfs], [fact_result])
    h3 = bool(fact and fact["rel_type"] == "RELATED_TO" and relation.get("rel_type") == NEW_REL_TYPE)
    h4 = len(bfs_lines) == 1 and len(fact_lines) == 1
    return {
        "prediction": "H3/H4",
        "updated_edges": updated_edges,
        "relation_after": relation,
        "fact_after": fact,
        "bfs_lines": bfs_lines,
        "fact_lines": fact_lines,
        "matches_inference": {"H3": h3, "H4": h4},
        "unexpected_findings": [
            "production backfill 新建型別邊時保留 citations_json/confidence，但未複製 verb_embedding；這不影響 H3/H4，需另列為 W5 寫入規則。"
        ],
    }


async def sync_fact_names(driver) -> int:
    result = await cypher(
        driver,
        """
        MATCH (f:Fact {kg_id: $kg_id})-[:HAS_SUBJECT]->(s:Entity),
              (f)-[:HAS_OBJECT]->(o:Entity)
        WHERE f.subject <> s.name OR f.object <> o.name
        SET f.subject = s.name, f.object = o.name
        RETURN count(f) AS changed
        """,
        kg_id=str(SYNTHETIC_KG),
    )
    return int(result.records[0]["changed"] if result.records else 0)


async def sync_fact_rel_types(driver, fixture_id: str) -> int:
    """Validation-only, conservative rel_type sync for one unambiguous edge."""

    result = await cypher(
        driver,
        """
        MATCH (f:Fact {kg_id: $kg_id, fixture_id: $fixture_id})-[:HAS_SUBJECT]->(s:Entity),
              (f)-[:HAS_OBJECT]->(o:Entity),
              (s)-[r]->(o)
        WHERE r.kg_id = $kg_id
        WITH f, collect(DISTINCT type(r)) AS rel_types
        WHERE size(rel_types) = 1 AND f.rel_type <> rel_types[0]
        SET f.rel_type = rel_types[0]
        RETURN count(f) AS changed
        """,
        kg_id=str(SYNTHETIC_KG),
        fixture_id=fixture_id,
    )
    return int(result.records[0]["changed"] if result.records else 0)


async def run_v4(driver) -> dict[str, object]:
    """V4: test script-only denormalized Fact synchronization and idempotence."""

    before = {
        fixture: await fact_row(driver, fixture)
        for fixture in ("w4-pure", "w4-collision-old", "w4-collision-new", "w5-fact")
    }
    names_first = await sync_fact_names(driver)
    after_names = {
        fixture: await fact_row(driver, fixture)
        for fixture in ("w4-pure", "w4-collision-old", "w4-collision-new", "w5-fact")
    }
    names_second = await sync_fact_names(driver)
    rel_type_first = await sync_fact_rel_types(driver, "w5-fact")
    after_rel_type = await fact_row(driver, "w5-fact")
    rel_type_second = await sync_fact_rel_types(driver, "w5-fact")
    matches = bool(
        names_first >= 2
        and names_second == 0
        and rel_type_first == 1
        and rel_type_second == 0
        and after_names["w4-pure"]["subject"] == "職員A"
        and after_names["w4-pure"]["object"] == "職務A"
        and after_names["w4-collision-old"]["subject"] == "職員B"
        and after_rel_type["rel_type"] == NEW_REL_TYPE
    )
    return {
        "prediction": "H5",
        "before": before,
        "after_name_sync": after_names,
        "name_sync_changed_first": names_first,
        "name_sync_changed_second": names_second,
        "rel_type_sync_changed_first": rel_type_first,
        "rel_type_sync_changed_second": rel_type_second,
        "w5_after_rel_type_sync": after_rel_type,
        "matches_inference": matches,
        "limitation": "rel_type 無法只由 Fact 的 HAS_SUBJECT/HAS_OBJECT 推得；本驗證只在端點間僅有一個帶 kg_id 的關係邊時，以 collect(DISTINCT type(r))=1 的保守條件同步。",
        "unexpected_findings": [],
    }


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


async def async_main(password: str) -> dict[str, object]:
    driver = await wait_for_driver(password)
    try:
        svo_service, split_fact_lines = await load_production()
        v1 = await run_v1(svo_service, driver)
        v2 = await run_v2(svo_service, driver)
        v3 = await run_v3(svo_service, driver, split_fact_lines)
        v4 = await run_v4(driver)
        return {
            "synthetic_kg_id": str(SYNTHETIC_KG),
            "v1": v1,
            "v2": v2,
            "v3": v3,
            "v4": v4,
            "hypotheses": {
                "H1": v2["matches_inference"]["H1"],
                "H2": v2["matches_inference"]["H2"],
                "H3": v3["matches_inference"]["H3"],
                "H4": v3["matches_inference"]["H4"],
                "H5": v4["matches_inference"],
                "H6": v1["matches_inference"],
            },
            "environment_observations": [
                "所有資料均為腳本建立的合成 Fact/Entity/Chunk；未連接受保護 KG，未啟動 Ollama、LLM 或外網。",
                "W5 的 production backfill 依賴 Neo4j 5.26 Enterprise 關係向量索引；確認請求只由腳本內固定回覆『是』。",
            ],
            "limitations": [
                "合成資料、單一小圖，不能代表真實分布或效能。",
                "只驗證 W1/W4/W5 三個寫入點；未涵蓋 merge_triples_to_graph 全流程、抽取端、backfill_fact_nodes 回填、真實資料分布。",
                "驗證結果不能外推為寫入端已可落地；正式欄位／事件 schema、邊狀態聚合與回填策略仍待裁示。",
            ],
        }
    finally:
        await driver.close()


def run_with_password() -> dict[str, object]:
    """Run V1-V4 with the new baseline; never call P3's old-baseline runner."""

    baseline = kg4_state()
    expected = {"status": "running", "started_at": EXPECTED_KG4_STARTED_AT}
    if baseline != expected:
        raise GateViolation(f"kg2-neo4j 基準不符：{baseline}；預期：{expected}")
    if temp_container_names():
        raise GateViolation(f"同名臨時容器 {TEMP_CONTAINER} 已存在，停止並詢問使用者")
    assert_ports_free()
    password = generate_temp_password()
    created = False
    result: dict[str, object] = {}
    teardown: dict[str, object] = {}
    try:
        created = bool(launch_temp_container(password))
        result = asyncio.run(async_main(password))
    finally:
        del password
        if created or temp_container_names():
            teardown = teardown_temp_container()
        final = kg4_state()
    result["kg4_baseline"] = baseline
    result["kg4_final"] = final
    result["kg4_unchanged"] = final == baseline
    result["temp_teardown"] = teardown
    result["temp_absent_after"] = not temp_container_names()
    result["status"] = "completed"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teardown", action="store_true", help="拆除且只拆除指定臨時容器")
    parser.add_argument("--output", type=Path, default=REPORT_OUTPUT)
    args = parser.parse_args()
    result: dict[str, object]
    try:
        if args.teardown:
            result = {"temp_teardown": teardown_temp_container()}
        else:
            result = run_with_password()
    except Exception as exc:  # noqa: BLE001 - preserve evidence and cleanup
        result = {"status": "failed", "error_type": type(exc).__name__, "error": str(exc)}
        try:
            if temp_container_names():
                result["emergency_teardown"] = teardown_temp_container()
            result["kg4_final"] = kg4_state()
        except Exception as cleanup_exc:  # noqa: BLE001
            result["cleanup_error_type"] = type(cleanup_exc).__name__
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("status") == "completed" or args.teardown else 1


if __name__ == "__main__":
    raise SystemExit(main())
