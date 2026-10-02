"""G2 disposable backup/restore drill for Neo4j Enterprise 5.26.

This is an experiment harness only.  It never connects to KG#4, never reads
the project ``.env``, and never changes production code.  All Docker calls go
through the gates in this file; the only permitted containers are the two
names documented by report 247 and only ``kg2-throwaway-*`` volumes may be
created or mounted.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID

from neo4j import AsyncGraphDatabase

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.analysis import disposable_fact_state_validation as p3


IMAGE = p3.IMAGE
SOURCE_CONTAINER = "kg2-throwaway-neo4j"
RESTORE_CONTAINER = "kg2-throwaway-restore"
ALLOWED_CONTAINERS = frozenset({SOURCE_CONTAINER, RESTORE_CONTAINER})
SOURCE_VOLUME = "kg2-throwaway-data"
RESTORE_VOLUME = "kg2-throwaway-restore-data"
VOLUME_PREFIX = "kg2-throwaway-"
PROTECTED_VOLUME = "kg2_neo4j_data"
TEMP_ROOT = Path(r"D:\Users\666\Desktop\kg-drill-tmp")
TEMP_URI = p3.TEMP_URI
TEMP_PORTS = p3.TEMP_PORTS
KG4_ID = p3.KG4_ID
EXPECTED_KG4_STARTED_AT = "2026-10-02T04:10:38.389676557Z"
REPORT_OUTPUT = _REPO / "data" / "analysis" / "disposable_backup_restore_validation_20261002.json"

DRILL_KG = UUID("5d2e1b1a-1f36-4b7e-9a7f-0d2d5b5a4e31")
FACT_LABEL = f"Fact_{str(DRILL_KG).replace('-', '_')}"
ENTITY_LABEL = "Entity"
DATABASE = "neo4j"
VECTOR_DIM = 1024
NODE_TARGETS = {"Entity": 12_000, "Chunk": 3_000, "Fact": 17_000, "Document": 25_000}
RELATION_TARGET = 138_000

# Reuse audited connection/password/protected-container helpers; do not call
# either old-baseline runner.  The Docker runner below is a stricter wrapper
# because this drill adds volumes, a second exact container name, and cp.
GateViolation = p3.GateViolation
validate_connection_target = p3.validate_connection_target
generate_temp_password = p3.generate_temp_password
kg4_state = p3.kg4_state
import_production_without_project_env = p3.import_production_without_project_env


class DockerCommandError(RuntimeError):
    def __init__(self, args: list[str], result: subprocess.CompletedProcess[str]):
        self.args_list = list(args)
        self.returncode = result.returncode
        self.stdout = result.stdout or ""
        self.stderr = result.stderr or ""
        super().__init__(f"docker {args[0] if args else '<empty>'} failed ({result.returncode})")


def _norm(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False)))


def validate_container_name(name: str) -> None:
    if name not in ALLOWED_CONTAINERS:
        raise GateViolation(f"拒絕非白名單臨時容器：{name}")


def validate_volume_name(name: str) -> None:
    if not name.startswith(VOLUME_PREFIX) or name == PROTECTED_VOLUME:
        raise GateViolation(f"拒絕非 kg2-throwaway- 磁碟區：{name}")


def validate_temp_path(path: str | Path, *, allow_root: bool = True) -> Path:
    candidate = Path(path)
    normalized = _norm(candidate)
    root = _norm(TEMP_ROOT)
    if not (normalized == root or normalized.startswith(root + os.sep)):
        raise GateViolation(f"路徑不在指定暫存目錄：{path}")
    if not allow_root and normalized == root:
        raise GateViolation("此操作不得直接使用暫存目錄根目錄")
    return candidate


def _volume_mount_is_safe(value: str) -> bool:
    parts = value.split(":")
    if len(parts) >= 2 and parts[0].startswith(VOLUME_PREFIX):
        validate_volume_name(parts[0])
        return parts[1].startswith("/")
    # Windows host path; split at the final colon before the container path.
    if value.lower().startswith(_norm(TEMP_ROOT).lower()):
        marker = value.lower().find(":/", len(_norm(TEMP_ROOT).lower()))
        if marker < 0:
            raise GateViolation(f"暫存 bind mount 缺少容器目標：{value}")
        validate_temp_path(value[:marker])
        return value[marker + 1 :].startswith("/")
    raise GateViolation(f"拒絕非允許 mount：{value}")


def validate_docker_run_args(args: list[str]) -> None:
    if not args or args[0] != "run":
        raise GateViolation("此閘門只接受 docker run")
    if any(token == "--pull" or token.startswith("--pull=") for token in args):
        raise GateViolation("禁止 docker pull／--pull")
    if "--name" not in args:
        raise GateViolation("docker run 必須指定白名單名稱")
    name = args[args.index("--name") + 1]
    validate_container_name(name)
    if "--memory" not in args or args[args.index("--memory") + 1] != "3g":
        raise GateViolation("臨時容器記憶體上限必須為 3g")
    if IMAGE not in args:
        raise GateViolation("只能使用本機既有 neo4j:5.26-enterprise")
    ports = [args[i + 1] for i, token in enumerate(args[:-1]) if token == "-p"]
    if any(port not in {"27474:7474", "27687:7687"} for port in ports):
        raise GateViolation(f"拒絕非允許埠映射：{ports}")
    mounts = [args[i + 1] for i, token in enumerate(args[:-1]) if token in {"-v", "--volume"}]
    for mount in mounts:
        _volume_mount_is_safe(mount)
    if any(token == "kg2-neo4j" for token in args):
        raise GateViolation("拒絕參照受保護容器 kg2-neo4j")


def _split_cp_ref(value: str) -> tuple[str | None, str]:
    for container in ALLOWED_CONTAINERS:
        prefix = container + ":"
        if value.startswith(prefix):
            return container, value[len(prefix) :]
    return None, value


def validate_docker_cp_args(args: list[str]) -> None:
    if len(args) != 3 or args[0] != "cp":
        raise GateViolation("docker cp 只允許單一來源與目的")
    source_container, source_path = _split_cp_ref(args[1])
    dest_container, dest_path = _split_cp_ref(args[2])
    if source_container and dest_container:
        raise GateViolation("禁止 container-to-container docker cp")
    if source_container is None:
        validate_temp_path(source_path)
    else:
        if not source_path.startswith("/"):
            raise GateViolation("container cp 來源必須是絕對路徑")
    if dest_container is None:
        validate_temp_path(dest_path)
    else:
        if not dest_path.startswith("/"):
            raise GateViolation("container cp 目的必須是絕對路徑")


def validate_docker_exec_args(args: list[str]) -> None:
    if len(args) < 3 or args[0] != "exec":
        raise GateViolation("docker exec 參數無效")
    validate_container_name(args[1])
    if "kg2-neo4j" in " ".join(args[2:]):
        raise GateViolation("docker exec 不得參照受保護容器")


def _validate_docker_args(args: list[str]) -> None:
    if not args:
        raise GateViolation("空的 Docker 指令")
    command = args[0]
    if command == "run":
        validate_docker_run_args(args)
    elif command == "cp":
        validate_docker_cp_args(args)
    elif command == "exec":
        validate_docker_exec_args(args)
    elif command in {"stop", "rm", "logs"}:
        if len(args) < 2:
            raise GateViolation(f"docker {command} 缺少容器名稱")
        validate_container_name(args[1])
        if any(token == "-f" for token in args):
            raise GateViolation("禁止強制刪除臨時容器")
    elif command == "ps":
        if "-a" not in args or "--filter" not in args:
            raise GateViolation("只允許精確名稱的 docker ps -a")
        filters = [args[i + 1] for i, token in enumerate(args[:-1]) if token == "--filter"]
        if len(filters) != 1 or not any(f == f"name=^/{name}$" for name in ALLOWED_CONTAINERS for f in filters):
            raise GateViolation("docker ps 必須是白名單容器的精確查詢")
    elif command == "volume":
        if len(args) < 3 or args[1] not in {"create", "rm", "ls"}:
            raise GateViolation("只允許受閘門保護的 volume create/rm/ls")
        if args[1] in {"create", "rm"}:
            validate_volume_name(args[2])
        elif args[1] == "ls":
            if "--filter" not in args or "name=kg2-throwaway-" not in args:
                raise GateViolation("volume ls 必須限制於 kg2-throwaway- 前綴")
    elif command == "system" and args[1:] == ["df", "-v"]:
        pass  # Required read-only protected-volume size evidence.
    else:
        raise GateViolation(f"禁止 Docker 指令：{' '.join(args)}")


def _docker(args: list[str], *, password: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    _validate_docker_args(args)
    child_env = None
    if password is not None:
        child_env = os.environ.copy()
        child_env["NEO4J_AUTH"] = f"neo4j/{password}"
    result = subprocess.run(["docker", *args], capture_output=True, text=True, env=child_env, check=False)
    if check and result.returncode != 0:
        raise DockerCommandError(args, result)
    return result


def _container_present(name: str) -> bool:
    validate_container_name(name)
    result = _docker(["ps", "-a", "--filter", f"name=^/{name}$", "--format", "{{.Names}}"])
    return any(line.strip() == name for line in result.stdout.splitlines())


def _any_throwaway_present() -> list[str]:
    return [name for name in ALLOWED_CONTAINERS if _container_present(name)]


def _teardown_container(name: str) -> dict[str, Any]:
    validate_container_name(name)
    before = _container_present(name)
    if not before:
        return {"name": name, "present_before": False, "stop_exit_code": None, "rm_exit_code": None, "present_after": False}
    stopped = _docker(["stop", name], check=False)
    removed = _docker(["rm", name], check=False)
    after = _container_present(name)
    if after:
        raise RuntimeError(f"臨時容器拆除失敗：{name}")
    return {"name": name, "present_before": True, "stop_exit_code": stopped.returncode, "rm_exit_code": removed.returncode, "present_after": after}


def _create_volume(name: str) -> None:
    validate_volume_name(name)
    if _volume_exists(name):
        raise GateViolation(f"同名磁碟區 {name} 已存在，停止並詢問使用者")
    _docker(["volume", "create", name])


def _volume_exists(name: str) -> bool:
    validate_volume_name(name)
    result = _docker(["volume", "ls", "--filter", "name=kg2-throwaway-", "--format", "{{.Name}}"])
    return name in {line.strip() for line in result.stdout.splitlines()}


def _remove_volume(name: str) -> dict[str, Any]:
    validate_volume_name(name)
    if not _volume_exists(name):
        return {"name": name, "present_before": False, "rm_exit_code": None, "present_after": False}
    result = _docker(["volume", "rm", name], check=False)
    present_after = _volume_exists(name)
    if present_after:
        raise RuntimeError(f"臨時磁碟區拆除失敗：{name}")
    return {"name": name, "present_before": True, "rm_exit_code": result.returncode, "present_after": False}


def _server_run_args(container: str, volume: str) -> list[str]:
    validate_container_name(container)
    validate_volume_name(volume)
    return [
        "run", "-d", "--name", container, "--hostname", container,
        "-p", "27474:7474", "-p", "27687:7687", "--memory", "3g",
        "--env", "NEO4J_AUTH", "--env", "NEO4J_ACCEPT_LICENSE_AGREEMENT=yes",
        "--env", "NEO4J_server_backup_listen__address=0.0.0.0:6362",
        "--env", "NEO4J_server_memory_heap_max__size=1G",
        "--env", "NEO4J_server_memory_pagecache_size=512M",
        "-v", f"{volume}:/data", IMAGE,
    ]


def _run_server(container: str, volume: str, password: str) -> str:
    if _any_throwaway_present():
        raise GateViolation("一次只能存在一個臨時容器，起動前已有臨時容器")
    result = _docker(_server_run_args(container, volume), password=password)
    container_id = result.stdout.strip()
    if not container_id:
        raise RuntimeError("docker run 未回傳容器識別字")
    return container_id


def _admin_hold_args(container: str, volume: str) -> list[str]:
    validate_container_name(container)
    validate_volume_name(volume)
    return [
        "run", "-d", "--name", container, "--memory", "3g",
        "--env", "NEO4J_ACCEPT_LICENSE_AGREEMENT=yes", "-v", f"{volume}:/data",
        "--entrypoint", "sh", IMAGE, "-c", "while :; do sleep 3600; done",
    ]


def _run_admin_hold(container: str, volume: str) -> None:
    if _any_throwaway_present():
        raise GateViolation("一次只能存在一個臨時容器，admin hold 起動前已有容器")
    _docker(_admin_hold_args(container, volume))


def _run_admin_oneshot(container: str, volume: str, command: list[str]) -> subprocess.CompletedProcess[str]:
    validate_container_name(container)
    validate_volume_name(volume)
    args = [
        "run", "--name", container, "--memory", "3g",
        "--env", "NEO4J_ACCEPT_LICENSE_AGREEMENT=yes", "-v", f"{volume}:/data",
        "--entrypoint", "sh", IMAGE, "-c", "mkdir -p /tmp/g2-b && exec neo4j-admin " + " ".join(command),
    ]
    if _any_throwaway_present():
        raise GateViolation("一次只能存在一個臨時容器，admin oneshot 起動前已有容器")
    return _docker(args, check=False)


def _run_tar_helper(container: str, volume: str, archive_name: str, *, extract: bool = False) -> subprocess.CompletedProcess[str]:
    validate_container_name(container)
    validate_volume_name(volume)
    validate_temp_path(TEMP_ROOT)
    if _any_throwaway_present():
        raise GateViolation("一次只能存在一個臨時容器，tar helper 起動前已有容器")
    mount_volume = f"{volume}:/data:ro" if not extract else f"{volume}:/data"
    if extract:
        command = ["-xzf", f"/backup/{archive_name}", "-C", "/data"]
    else:
        command = ["-czf", f"/backup/{archive_name}", "-C", "/data", "."]
    args = [
        "run", "--name", container, "--memory", "3g", "--user", "0:0",
        "--env", "NEO4J_ACCEPT_LICENSE_AGREEMENT=yes", "-v", mount_volume,
        "-v", f"{TEMP_ROOT}:/backup", "--entrypoint", "tar", IMAGE, *command,
    ]
    return _docker(args, check=False)


async def _wait_for_driver(password: str) -> Any:
    validate_connection_target(TEMP_URI, DRILL_KG)
    driver = AsyncGraphDatabase.driver(TEMP_URI, auth=("neo4j", password))
    last_error: Exception | None = None
    for _ in range(150):
        try:
            await driver.verify_connectivity()
            return driver
        except Exception as exc:  # noqa: BLE001 - readiness retry
            last_error = exc
            await asyncio.sleep(1)
    await driver.close()
    raise RuntimeError(f"臨時 Neo4j 未就緒：{type(last_error).__name__}")


async def _cypher(driver: Any, statement: str, **parameters: Any):
    return await driver.execute_query(statement, database_=DATABASE, **parameters)


def _vector(seed: int) -> list[float]:
    values = [0.0] * VECTOR_DIM
    values[seed % VECTOR_DIM] = 1.0
    values[(seed * 17 + 11) % VECTOR_DIM] = 0.5
    return values


def _batch(values: Iterable[Any], size: int) -> Iterable[list[Any]]:
    current: list[Any] = []
    for value in values:
        current.append(value)
        if len(current) == size:
            yield current
            current = []
    if current:
        yield current


async def _seed_nodes(driver: Any) -> None:
    entity_rows = [
        {"id": f"entity-{i:05d}", "name": f"合成實體{i:05d}", "embedding": _vector(i)}
        for i in range(NODE_TARGETS["Entity"])
    ]
    for rows in _batch(entity_rows, 300):
        await _cypher(driver, f"""
            UNWIND $rows AS row
            CREATE (e:{ENTITY_LABEL} {{synthetic_id: row.id, kg_id: $kg_id, name: row.name, name_embedding: row.embedding}})
        """, rows=rows, kg_id=str(DRILL_KG))
    chunk_rows = [
        {"id": f"chunk-{i:05d}", "embedding": _vector(i + 3)}
        for i in range(NODE_TARGETS["Chunk"])
    ]
    for rows in _batch(chunk_rows, 300):
        await _cypher(driver, """
            UNWIND $rows AS row
            CREATE (c:Chunk {synthetic_id: row.id, kg_id: $kg_id, chunk_index: row.id, embedding: row.embedding})
        """, rows=rows, kg_id=str(DRILL_KG))
    fact_rows = [
        {
            "id": f"fact-{i:05d}", "subject_id": f"entity-{i % 12000:05d}",
            "object_id": f"entity-{(i * 7 + 13) % 12000:05d}",
            "chunk_id": f"chunk-{i % 3000:05d}", "embedding": _vector(i + 7),
            "source_doc_id": f"doc-{i % 3000:05d}", "fact_text": f"合成實體{i % 12000:05d} RELATED_TO 合成實體{(i * 7 + 13) % 12000:05d}",
        }
        for i in range(NODE_TARGETS["Fact"])
    ]
    for rows in _batch(fact_rows, 250):
        await _cypher(driver, f"""
            UNWIND $rows AS row
            CREATE (f:Fact:{FACT_LABEL} {{synthetic_id: row.id, kg_id: $kg_id,
                fact_id: row.id, source_doc_id: row.source_doc_id, source_svo_chunk_index: 0,
                subject: row.subject_id, object: row.object_id, rel_type: 'RELATED_TO', verb: 'RELATED_TO',
                fact_text: row.fact_text, fact_embedding: row.embedding, confidence: 0.75,
                citations_json: '[{{"synthetic":true}}]'}})
        """, rows=rows, kg_id=str(DRILL_KG))
    document_rows = [{"id": f"document-{i:05d}"} for i in range(NODE_TARGETS["Document"])]
    for rows in _batch(document_rows, 500):
        await _cypher(driver, """
            UNWIND $rows AS row
            CREATE (:Document {synthetic_id: row.id, kg_id: $kg_id, source: 'g2-synthetic'})
        """, rows=rows, kg_id=str(DRILL_KG))


async def _seed_relationships(driver: Any) -> None:
    fact_rows = [
        {"fact": f"fact-{i:05d}", "subject": f"entity-{i % 12000:05d}", "object": f"entity-{(i * 7 + 13) % 12000:05d}", "chunk": f"chunk-{i % 3000:05d}"}
        for i in range(NODE_TARGETS["Fact"])
    ]
    for rows in _batch(fact_rows, 300):
        await _cypher(driver, """
            UNWIND $rows AS row
            MATCH (f:Fact {synthetic_id: row.fact}), (s:Entity {synthetic_id: row.subject}),
                  (o:Entity {synthetic_id: row.object}), (c:Chunk {synthetic_id: row.chunk})
            CREATE (f)-[:HAS_SUBJECT {kg_id: $kg_id}]->(s),
                   (f)-[:HAS_OBJECT {kg_id: $kg_id}]->(o),
                   (f)-[:SUPPORTED_BY {kg_id: $kg_id}]->(c)
        """, rows=rows, kg_id=str(DRILL_KG))
    chunk_rows = [{"chunk": f"chunk-{i:05d}", "entity": f"entity-{(i * 11) % 12000:05d}"} for i in range(3000)]
    for rows in _batch(chunk_rows, 300):
        await _cypher(driver, """
            UNWIND $rows AS row
            MATCH (c:Chunk {synthetic_id: row.chunk}), (e:Entity {synthetic_id: row.entity})
            CREATE (c)-[:HAS_ENTITY {kg_id: $kg_id}]->(e)
        """, rows=rows, kg_id=str(DRILL_KG))
    # 84,000 entity-to-entity edges plus 54,000 fact/chunk edges = 138,000.
    rel_rows = [
        {"subject": f"entity-{i % 12000:05d}", "object": f"entity-{(i * 37 + 19) % 12000:05d}", "id": i}
        for i in range(84_000)
    ]
    for rows in _batch(rel_rows, 700):
        await _cypher(driver, """
            UNWIND $rows AS row
            MATCH (s:Entity {synthetic_id: row.subject}), (o:Entity {synthetic_id: row.object})
            CREATE (s)-[:RELATED_TO {kg_id: $kg_id, citations_json: '[{"synthetic":true}]', confidence: 0.5, synthetic_edge_id: row.id}]->(o)
        """, rows=rows, kg_id=str(DRILL_KG))


async def _create_indexes(driver: Any, svo_service: Any) -> None:
    await svo_service.create_entity_name_vector_index(driver, dim=VECTOR_DIM)
    await svo_service.create_chunk_vector_index(driver, dim=VECTOR_DIM)
    await svo_service.create_fact_vector_index(driver, DRILL_KG, dim=VECTOR_DIM)
    names = ["entity_name_vector", "chunk_embedding_vector", svo_service._fact_vector_index_name(str(DRILL_KG))]
    for name in names:
        for _ in range(180):
            result = await _cypher(driver, "SHOW INDEXES YIELD name, state WHERE name = $name RETURN state", name=name)
            if result.records and result.records[0]["state"] == "ONLINE":
                break
            await asyncio.sleep(1)
        else:
            raise RuntimeError(f"向量索引未 ONLINE：{name}")


async def _create_lookup_indexes(driver: Any) -> None:
    """Make the large synthetic relationship batches index-backed."""

    await _cypher(driver, "CREATE INDEX g2_entity_lookup IF NOT EXISTS FOR (n:Entity) ON (n.synthetic_id)")
    await _cypher(driver, "CREATE INDEX g2_fact_lookup IF NOT EXISTS FOR (n:Fact) ON (n.synthetic_id)")
    await _cypher(driver, "CREATE INDEX g2_chunk_lookup IF NOT EXISTS FOR (n:Chunk) ON (n.synthetic_id)")
    for name in ("g2_entity_lookup", "g2_fact_lookup", "g2_chunk_lookup"):
        for _ in range(120):
            result = await _cypher(driver, "SHOW INDEXES YIELD name, state WHERE name = $name RETURN state", name=name)
            if result.records and result.records[0]["state"] == "ONLINE":
                break
            await asyncio.sleep(0.5)
        else:
            raise RuntimeError(f"查找索引未 ONLINE：{name}")


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, float):
        return round(value, 9)
    return value


def _digest_rows(rows: Iterable[Any]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(json.dumps(_jsonable(row), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
        digest.update(b"\n")
    return digest.hexdigest()


async def _stream_digest(driver: Any, statement: str, **parameters: Any) -> str:
    digest = hashlib.sha256()
    async with driver.session(database=DATABASE) as session:
        result = await session.run(statement, **parameters)
        async for record in result:
            digest.update(json.dumps(_jsonable(dict(record)), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
            digest.update(b"\n")
        await result.consume()
    return digest.hexdigest()


async def _fingerprint(driver: Any, svo_service: Any) -> dict[str, Any]:
    label_rows = await _cypher(driver, """
        MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS count ORDER BY label
    """)
    rel_rows = await _cypher(driver, "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS count ORDER BY type")
    fact_count = (await _cypher(driver, "MATCH (f:Fact) RETURN count(f) AS count")).records[0]["count"]
    entity_count = (await _cypher(driver, "MATCH (e:Entity) RETURN count(e) AS count")).records[0]["count"]
    total_node_count = (await _cypher(driver, "MATCH (n) RETURN count(n) AS count")).records[0]["count"]
    entity_digest = await _stream_digest(driver, """
        MATCH (e:Entity) RETURN e.name AS name, e.synthetic_id AS id ORDER BY id
    """)
    edge_digest = await _stream_digest(driver, """
        MATCH (s:Entity)-[r]->(o:Entity)
        RETURN s.synthetic_id AS subject, type(r) AS type, o.synthetic_id AS object,
               r.kg_id AS kg_id, r.citations_json AS citations_json, r.confidence AS confidence,
               r.synthetic_edge_id AS synthetic_edge_id
        ORDER BY subject, type, object, synthetic_edge_id
    """)
    fact_digest = await _stream_digest(driver, """
        MATCH (f:Fact)
        RETURN f.fact_id AS fact_id, f.kg_id AS kg_id, f.source_doc_id AS source_doc_id,
               f.source_svo_chunk_index AS chunk_index, f.subject AS subject, f.object AS object,
               f.rel_type AS rel_type, f.verb AS verb, f.fact_text AS fact_text,
               f.confidence AS confidence, f.citations_json AS citations_json
        ORDER BY fact_id
    """)
    index_rows = await _cypher(driver, """
        SHOW INDEXES YIELD name, state, type, entityType, labelsOrTypes, properties, options
        RETURN name, state, type, entityType, labelsOrTypes, properties, options ORDER BY name
    """)
    index_summary = [_jsonable(dict(record)) for record in index_rows.records]
    query_vectors = [_vector(i * 13 + 1) for i in range(5)]
    knn: list[list[dict[str, Any]]] = []
    for vector in query_vectors:
        result = await _cypher(driver, f"""
            CALL db.index.vector.queryNodes('{svo_service._fact_vector_index_name(str(DRILL_KG))}', 5, $vector)
            YIELD node, score
            RETURN node.fact_id AS fact_id, node.fact_text AS fact_text, score
        """, vector=vector)
        knn.append([_jsonable(dict(record)) for record in result.records])
    production_results = []
    for vector in query_vectors[:1]:
        production_results = [_jsonable(item) for item in await svo_service.vector_search_facts(driver, DRILL_KG, vector, 5)]
    return {
        "label_counts": [{"label": r["label"], "count": r["count"]} for r in label_rows.records],
        "relationship_counts": [{"type": r["type"], "count": r["count"]} for r in rel_rows.records],
        "fact_count": fact_count, "entity_count": entity_count,
        "node_count": total_node_count,
        "relationship_count": sum(r["count"] for r in rel_rows.records),
        "entity_name_digest": entity_digest, "entity_edge_digest": edge_digest, "fact_properties_digest": fact_digest,
        "indexes": index_summary, "knn_samples": knn, "production_vector_search": production_results,
    }


def _artifact_info(path: Path) -> dict[str, Any]:
    validate_temp_path(path)
    files = sorted(p for p in path.rglob("*") if p.is_file())
    digest = hashlib.sha256()
    total = 0
    for file in files:
        size = file.stat().st_size
        total += size
        digest.update(str(file.relative_to(path)).encode())
        with file.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    return {"path": str(path), "file_count": len(files), "size_bytes": total, "sha256": digest.hexdigest(), "files": [str(p.relative_to(path)) for p in files]}


def _copy_container_dir_to_host(container: str, container_path: str, host_dir: Path) -> None:
    validate_container_name(container)
    validate_temp_path(host_dir)
    host_dir.mkdir(parents=True, exist_ok=True)
    # Docker Desktop on Windows rejects the POSIX ``/.`` directory spelling
    # even when the directory exists; copy the directory itself instead.
    _docker(["cp", f"{container}:{container_path}", str(host_dir)])
    copied_dir = host_dir / Path(container_path).name
    if copied_dir.is_dir():
        for child in copied_dir.iterdir():
            shutil.move(str(child), str(host_dir / child.name))
        copied_dir.rmdir()


def _copy_container_files_to_host(container: str, container_path: str, host_dir: Path) -> list[str]:
    """List and copy archive files one by one; avoids Windows dir-cp ambiguity."""

    validate_container_name(container)
    validate_temp_path(host_dir)
    host_dir.mkdir(parents=True, exist_ok=True)
    listing = _docker(["exec", container, "sh", "-c", f"find {container_path} -type f -print"], check=False)
    files = [line.strip() for line in listing.stdout.splitlines() if line.strip()]
    if not files:
        raise RuntimeError(
            f"容器內沒有備份檔：path={container_path}; "
            f"stdout={listing.stdout.strip()[:3000]} stderr={listing.stderr.strip()[:1000]}"
        )
    for source in files:
        name = Path(source).name
        _docker(["cp", f"{container}:{source}", str(host_dir / name)])
    return files


def _copy_host_files_to_container(container: str, host_dir: Path, target_dir: str = "/tmp/load") -> None:
    validate_container_name(container)
    validate_temp_path(host_dir)
    _docker(["exec", container, "mkdir", "-p", target_dir])
    for file in sorted(p for p in host_dir.rglob("*") if p.is_file()):
        relative = file.relative_to(host_dir).as_posix()
        target_parent = str(Path(target_dir) / Path(relative).parent).replace("\\", "/")
        _docker(["exec", container, "mkdir", "-p", target_parent])
        _docker(["cp", str(file), f"{container}:{str(Path(target_dir) / relative).replace(chr(92), '/')}"])


def _sanitized_error(exc: Exception, password: str) -> str:
    text = str(exc)
    if isinstance(exc, DockerCommandError):
        text = (exc.stderr or exc.stdout or str(exc)).strip()
    text = text.replace(password, "<redacted>").replace(f"neo4j/{password}", "neo4j/<redacted>")
    return text.splitlines()[0][:1000] if text else type(exc).__name__


async def _validate_restore(
    password: str, before: dict[str, Any], svo_service: Any, method: str, restore_volume: str,
) -> dict[str, Any]:
    start = time.perf_counter()
    _run_server(RESTORE_CONTAINER, restore_volume, password)
    driver = await _wait_for_driver(password)
    try:
        after = await _fingerprint(driver, svo_service)
        production = [_jsonable(item) for item in await svo_service.vector_search_facts(driver, DRILL_KG, _vector(1), 5)]
        await _cypher(driver, "CREATE (p:BackupRestoreProbe {probe_id: $id, method: $method})", id=f"{method}-probe", method=method)
        readback = (await _cypher(driver, "MATCH (p:BackupRestoreProbe {probe_id: $id}) RETURN p.method AS method", id=f"{method}-probe")).records
        await _cypher(driver, "MATCH (p:BackupRestoreProbe {probe_id: $id}) DELETE p", id=f"{method}-probe")
        return {
            "restore_seconds": round(time.perf_counter() - start, 6),
            "fingerprint_equal": before == after,
            "before_fingerprint": before,
            "after_fingerprint": after,
            "production_vector_search_equal": production == before["production_vector_search"],
            "production_vector_search_after": production,
            "write_readback": [dict(r) for r in readback],
            "write_readback_ok": bool(readback and readback[0]["method"] == method),
        }
    finally:
        await driver.close()


def _prepare_restore_volume() -> None:
    _create_volume(RESTORE_VOLUME)


def _load_archive_into_restore(password: str, host_dir: Path, *, method: str) -> None:
    _prepare_restore_volume()
    _run_admin_hold(RESTORE_CONTAINER, RESTORE_VOLUME)
    try:
        _copy_host_files_to_container(RESTORE_CONTAINER, host_dir)
        command = ["database", "load", DATABASE, "--from-path=/tmp/load", "--overwrite-destination=true"]
        result = _docker(["exec", RESTORE_CONTAINER, "neo4j-admin", *command], check=False)
        if result.returncode != 0:
            raise DockerCommandError(["exec", RESTORE_CONTAINER, "neo4j-admin", *command], result)
    finally:
        _teardown_container(RESTORE_CONTAINER)


def _corrupted_backup_failure(password: str, source_dir: Path) -> dict[str, Any]:
    """Truncate one dump and require ``neo4j-admin database load`` to fail."""

    validate_temp_path(source_dir)
    source_files = [path for path in source_dir.rglob("*") if path.is_file()]
    if len(source_files) != 1:
        raise RuntimeError(f"損毀情境預期單一 B dump 檔，實際 {len(source_files)} 檔")
    corrupt_dir = TEMP_ROOT / "corrupt"
    corrupt_dir.mkdir(parents=True, exist_ok=False)
    corrupt_file = corrupt_dir / source_files[0].name
    original = source_files[0].read_bytes()
    corrupt_file.write_bytes(original[: max(1, len(original) // 2)])
    _prepare_restore_volume()
    error_text = ""
    returncode: int | None = None
    try:
        _run_admin_hold(RESTORE_CONTAINER, RESTORE_VOLUME)
        _copy_host_files_to_container(RESTORE_CONTAINER, corrupt_dir)
        command = ["exec", RESTORE_CONTAINER, "neo4j-admin", "database", "load", DATABASE, "--from-path=/tmp/load", "--overwrite-destination=true"]
        result = _docker(command, check=False)
        returncode = result.returncode
        error_text = (result.stderr or result.stdout or "").strip().splitlines()[0][:1000]
        if returncode == 0:
            raise RuntimeError("損毀備份 load 未失敗，違反明確失敗要求")
    finally:
        _teardown_container(RESTORE_CONTAINER)
        _remove_volume(RESTORE_VOLUME)
    return {
        "source": str(source_files[0]),
        "corrupt_copy": str(corrupt_file),
        "original_size_bytes": len(original),
        "corrupt_size_bytes": corrupt_file.stat().st_size,
        "load_returncode": returncode,
        "explicit_failure": returncode != 0,
        "error_message_sanitized": error_text,
    }


async def _run_method_a(password: str, source_fingerprint: dict[str, Any], svo_service: Any) -> dict[str, Any]:
    host_dir = TEMP_ROOT / "method-a"
    start = time.perf_counter()
    _docker(["exec", SOURCE_CONTAINER, "mkdir", "-p", "/tmp/g2-a"])
    result = _docker([
        "exec", SOURCE_CONTAINER, "neo4j-admin", "database", "backup",
        "--from=localhost:6362", "--to-path=/tmp/g2-a", "--type=FULL", DATABASE,
    ], check=False)
    backup_seconds = time.perf_counter() - start
    if result.returncode != 0:
        raise DockerCommandError(["exec", SOURCE_CONTAINER, "neo4j-admin", "database", "backup"], result)
    _copy_container_dir_to_host(SOURCE_CONTAINER, "/tmp/g2-a", host_dir)
    artifact = _artifact_info(host_dir)
    # A is online: backup itself does not stop the running database.
    _teardown_container(SOURCE_CONTAINER)
    restore_start = time.perf_counter()
    _load_archive_into_restore(password, host_dir, method="A")
    restored = await _validate_restore(password, source_fingerprint, svo_service, "A", RESTORE_VOLUME)
    restored["restore_seconds"] = round(time.perf_counter() - restore_start, 6)
    teardown = _teardown_container(RESTORE_CONTAINER)
    volume = _remove_volume(RESTORE_VOLUME)
    return {"backup_seconds": round(backup_seconds, 6), "backup": artifact, "downtime_seconds": 0.0, "restore": restored, "restore_container_teardown": teardown, "restore_volume_teardown": volume}


def _dump_source_to_host(host_dir: Path) -> tuple[float, dict[str, Any]]:
    downtime_start = time.perf_counter()
    _teardown_container(SOURCE_CONTAINER)
    result = _run_admin_oneshot(SOURCE_CONTAINER, SOURCE_VOLUME, ["database", "dump", DATABASE, "--to-path=/tmp/g2-b"])
    if result.returncode != 0:
        message = result.stderr or result.stdout
        _teardown_container(SOURCE_CONTAINER)
        raise DockerCommandError(["run", SOURCE_CONTAINER, "neo4j-admin", "database", "dump"], result)
    _copy_container_dir_to_host(SOURCE_CONTAINER, "/tmp/g2-b", host_dir)
    artifact = _artifact_info(host_dir)
    downtime = time.perf_counter() - downtime_start
    _teardown_container(SOURCE_CONTAINER)
    return downtime, artifact


async def _run_method_b(password: str, source_fingerprint: dict[str, Any], svo_service: Any) -> dict[str, Any]:
    host_dir = TEMP_ROOT / "method-b"
    downtime, artifact = _dump_source_to_host(host_dir)
    restore_start = time.perf_counter()
    _load_archive_into_restore(password, host_dir, method="B")
    restored = await _validate_restore(password, source_fingerprint, svo_service, "B", RESTORE_VOLUME)
    restored["restore_seconds"] = round(time.perf_counter() - restore_start, 6)
    teardown = _teardown_container(RESTORE_CONTAINER)
    volume = _remove_volume(RESTORE_VOLUME)
    return {"backup_seconds": round(downtime, 6), "backup": artifact, "downtime_seconds": round(downtime, 6), "restore": restored, "restore_container_teardown": teardown, "restore_volume_teardown": volume}


async def _run_method_c(password: str, source_fingerprint: dict[str, Any], svo_service: Any) -> dict[str, Any]:
    host_dir = TEMP_ROOT / "method-c"
    host_dir.mkdir(parents=True, exist_ok=True)
    archive_name = "data.tar.gz"
    downtime_start = time.perf_counter()
    _teardown_container(SOURCE_CONTAINER)
    tar_result = _run_tar_helper(SOURCE_CONTAINER, SOURCE_VOLUME, archive_name)
    if tar_result.returncode != 0:
        _teardown_container(SOURCE_CONTAINER)
        raise DockerCommandError(["run", SOURCE_CONTAINER, "tar"], tar_result)
    downtime = time.perf_counter() - downtime_start
    _teardown_container(SOURCE_CONTAINER)
    artifact = _artifact_info(TEMP_ROOT)
    # C's helper writes directly into the host drill directory; validate the
    # artifact separately without copying it into the repository.
    archive_path = TEMP_ROOT / archive_name
    archive_info = {
        "path": str(archive_path), "file_count": 1, "size_bytes": archive_path.stat().st_size,
        "sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        "files": [archive_name],
    }
    _prepare_restore_volume()
    restore_start = time.perf_counter()
    restore_tar = _run_tar_helper(RESTORE_CONTAINER, RESTORE_VOLUME, archive_name, extract=True)
    if restore_tar.returncode != 0:
        _teardown_container(RESTORE_CONTAINER)
        raise DockerCommandError(["run", RESTORE_CONTAINER, "tar", "-xzf"], restore_tar)
    _teardown_container(RESTORE_CONTAINER)
    restored = await _validate_restore(password, source_fingerprint, svo_service, "C", RESTORE_VOLUME)
    restored["restore_seconds"] = round(time.perf_counter() - restore_start, 6)
    teardown = _teardown_container(RESTORE_CONTAINER)
    volume = _remove_volume(RESTORE_VOLUME)
    return {"backup_seconds": round(downtime, 6), "backup": archive_info, "downtime_seconds": round(downtime, 6), "restore": restored, "restore_container_teardown": teardown, "restore_volume_teardown": volume, "temp_dir_listing_digest": artifact["sha256"]}


async def _drill(password: str) -> dict[str, Any]:
    with import_production_without_project_env():
        from services import svo_service
    _create_volume(SOURCE_VOLUME)
    _run_server(SOURCE_CONTAINER, SOURCE_VOLUME, password)
    driver = await _wait_for_driver(password)
    try:
        await _seed_nodes(driver)
        await _create_lookup_indexes(driver)
        await _seed_relationships(driver)
        await _create_indexes(driver, svo_service)
        fingerprint = await _fingerprint(driver, svo_service)
    finally:
        await driver.close()
    result: dict[str, Any] = {
        "b1": {"targets": NODE_TARGETS, "expected_relationship_count": RELATION_TARGET, "fingerprint": fingerprint},
        "admin_help": {"backup_requires_configured_service": True, "dump_requires_offline_database": True, "load_accepts_dump_or_full_backup": True},
    }
    result["b2"] = await _run_method_a(password, fingerprint, svo_service)
    _run_server(SOURCE_CONTAINER, SOURCE_VOLUME, password)
    await (await _wait_for_driver(password)).close()
    result["b3"] = await _run_method_b(password, fingerprint, svo_service)
    result["corrupted_backup"] = _corrupted_backup_failure(password, TEMP_ROOT / "method-b")
    _run_server(SOURCE_CONTAINER, SOURCE_VOLUME, password)
    await (await _wait_for_driver(password)).close()
    result["b4"] = await _run_method_c(password, fingerprint, svo_service)
    return result


def _protected_volume_size() -> dict[str, str]:
    result = _docker(["system", "df", "-v"])
    for line in result.stdout.splitlines():
        fields = line.split()
        if fields and fields[0] == PROTECTED_VOLUME and len(fields) >= 3:
            return {"volume": PROTECTED_VOLUME, "links": fields[1], "size": fields[2], "raw_line": line.strip()}
    raise RuntimeError("docker system df -v 找不到受保護磁碟區摘要")


def _cleanup_temp_root(created_by_script: bool) -> dict[str, Any]:
    validate_temp_path(TEMP_ROOT)
    if not TEMP_ROOT.exists():
        return {"exists_before": False, "removed": False, "exists_after": False}
    if not created_by_script:
        raise GateViolation("暫存目錄不是本次建立，拒絕刪除")
    shutil.rmtree(TEMP_ROOT)
    return {"exists_before": True, "removed": True, "exists_after": TEMP_ROOT.exists()}


def _safe_failure(exc: Exception, password: str) -> dict[str, Any]:
    return {"status": "failed", "error_type": type(exc).__name__, "error_message_sanitized": _sanitized_error(exc, password)}


def run_drill(output: Path) -> dict[str, Any]:
    baseline = kg4_state()
    expected = {"status": "running", "started_at": EXPECTED_KG4_STARTED_AT}
    if baseline != expected:
        raise GateViolation(f"kg2-neo4j 基準不符：{baseline}；預期：{expected}")
    if _any_throwaway_present() or _volume_exists(SOURCE_VOLUME) or _volume_exists(RESTORE_VOLUME):
        raise GateViolation("同名臨時容器或磁碟區已存在，停止並詢問使用者")
    if TEMP_ROOT.exists():
        raise GateViolation(f"暫存目錄已存在，停止並詢問使用者：{TEMP_ROOT}")
    TEMP_ROOT.mkdir(parents=True, exist_ok=False)
    password = generate_temp_password()
    result: dict[str, Any] = {"status": "running", "b0": {"kg4_start": baseline, "protected_volume_start": _protected_volume_size()}}
    try:
        result.update(asyncio.run(_drill(password)))
        result["status"] = "completed"
    except Exception as exc:  # noqa: BLE001 - preserve evidence and cleanup
        result.update(_safe_failure(exc, password))
    finally:
        try:
            for name in (SOURCE_CONTAINER, RESTORE_CONTAINER):
                if _container_present(name):
                    result.setdefault("cleanup", []).append(_teardown_container(name))
            for volume in (SOURCE_VOLUME, RESTORE_VOLUME):
                if _volume_exists(volume):
                    result.setdefault("cleanup", []).append(_remove_volume(volume))
        finally:
            try:
                result["temp_dir_teardown"] = _cleanup_temp_root(created_by_script=True)
            except Exception as cleanup_exc:  # noqa: BLE001
                result["temp_dir_cleanup_error"] = type(cleanup_exc).__name__
        result["b6"] = {
            "kg4_end": kg4_state(),
            "kg4_unchanged": kg4_state() == baseline,
            "protected_volume_end": _protected_volume_size(),
            "protected_volume_unchanged": result["b0"]["protected_volume_start"] == result["b6"]["protected_volume_end"] if "b6" in result else False,
            "temp_containers_absent": not _any_throwaway_present(),
            "temp_volumes_absent": not (_volume_exists(SOURCE_VOLUME) or _volume_exists(RESTORE_VOLUME)),
            "temp_dir_absent": not TEMP_ROOT.exists(),
        }
        # Recompute the self-reference safely after the dictionary is built.
        result["b6"]["protected_volume_unchanged"] = result["b0"]["protected_volume_start"] == result["b6"]["protected_volume_end"]
        del password
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(_jsonable(result), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPORT_OUTPUT)
    args = parser.parse_args()
    try:
        result = run_drill(args.output)
    except Exception as exc:  # baseline/name gate failure before temp creation
        result = {"status": "failed", "error_type": type(exc).__name__, "error_message_sanitized": str(exc).splitlines()[0][:1000]}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(_jsonable(result), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result.get("status"), "output": str(args.output), "b6": result.get("b6")}, ensure_ascii=False))
    return 0 if result.get("status") == "completed" and result.get("b6", {}).get("kg4_unchanged") and result.get("b6", {}).get("temp_dir_absent") else 1


if __name__ == "__main__":
    raise SystemExit(main())
