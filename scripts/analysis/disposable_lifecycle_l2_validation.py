"""L2′ disposable Neo4j validation（報告260 §5，S1–S5）：L1 真實資料庫行為、`state_as_of` 先過濾後去重、
BFS 邊來源混合、條文層「新版取代」連動、17,000 Fact 規模與耗時。

僅為實驗 harness：沿用 G1 腳本的做法 import 已審核的 P3 閘門與容器函式，**自訂新基準**
`EXPECTED_KG4_STARTED_AT`，**不呼叫任何舊基準執行器**，不修改 production。資料全為合成；唯一允許的容器是
精確名稱 ``kg2-throwaway-neo4j``（P3 的 `TEMP_CONTAINER`），埠 27474／27687、3 GB，不掛任何磁碟區（無 `-v`／`--mount`，
因此不可能碰到正式資料的磁碟區）。結尾無論成敗都拆除並證明已拆除。

執行（由有 docker 授權者）：``python scripts/analysis/disposable_lifecycle_l2_validation.py``
僅拆除：``... --teardown``。輸出：``data/analysis/disposable_lifecycle_l2_validation_20261002.json``。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, AsyncIterator, Iterable, Sequence
from uuid import UUID, uuid4

from neo4j import AsyncGraphDatabase

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from core.providers.base import EmbeddingProvider, LLMProvider
from models.knowledge_graph import SVOTriple
from scripts.analysis import disposable_fact_state_validation as p3
from services import relation_lifecycle as rl
from services.retrieval.fact_candidates import _dedupe_facts_by_key

TEMP_CONTAINER = p3.TEMP_CONTAINER
IMAGE = p3.IMAGE
TEMP_URI = p3.TEMP_URI
TEMP_PORTS = p3.TEMP_PORTS
KG4_ID = p3.KG4_ID
EXPECTED_KG4_STARTED_AT = "2026-10-02T11:09:32.79429649Z"
REPORT_OUTPUT = _REPO / "data" / "analysis" / "disposable_lifecycle_l2_validation_20261002.json"

# 實體名稱向量以「依出現順序的 one-hot」避免 DEDUP4 把不同合成實體合併；最後一維保留給 Fact 文字，故維度取 16（>8）。
VECTOR_DIM = 16
FACT_AXIS = VECTOR_DIM - 1
SCALE_DIM = 1024  # 僅 S5 使用：fact_embedding 與真實 KG（bge-m3）同為 1024 維，才量得到 properties(node) 物化向量的成本
SCALE_BATCH = 500  # S5 建立 Fact 的每批筆數（1024 維向量，控制 3 GB 容器的堆積記憶體）
S1_KG, S2_KG, S3_KG, S4_KG, S5_KG = (uuid4() for _ in range(5))
AS_OF_DATES = ("2026-10-02", "2024-01-01", "2027-01-01")
SCALE_COUNT, SCALE_STATEFUL, TIMING_RUNS, TIMING_WARMUP = 17_000, 1_800, 40, 3

GateViolation = p3.GateViolation
validate_connection_target = p3.validate_connection_target
generate_temp_password = p3.generate_temp_password
build_docker_run_argv = p3.build_docker_run_argv
temp_container_names = p3.temp_container_names
kg4_state = p3.kg4_state
launch_temp_container = p3.launch_temp_container
teardown_temp_container = p3.teardown_temp_container
import_production_without_project_env = p3.import_production_without_project_env


# ── 合成 provider ────────────────────────────────────────────────────────────
def _onehot(axis: int) -> list[float]:
    return [1.0 if i == axis else 0.0 for i in range(VECTOR_DIM)]


class SyntheticEmbeddingProvider(EmbeddingProvider):
    """決定性假向量：不含空白的文字（實體名稱）依出現順序取 one-hot 軸（互相正交）；含空白者（Fact 文字）一律取 Fact 軸。"""

    def __init__(self) -> None:
        self.names: dict[str, int] = {}

    @property
    def dim(self) -> int:
        return VECTOR_DIM

    @property
    def model_name(self) -> str:
        return "l2-synthetic-onehot"

    async def encode(self, text: str) -> list[float]:
        if " " in text:
            return _onehot(FACT_AXIS)
        if text not in self.names:
            if len(self.names) >= FACT_AXIS:
                raise RuntimeError("合成實體名稱數超過可用 one-hot 軸")
            self.names[text] = len(self.names)
        return _onehot(self.names[text])


class ScriptedLLMProvider(LLMProvider):
    """依序回傳預先給定的自然語句（供 `_naturalize_triple`）；不呼叫任何模型。"""

    def __init__(self, texts: Sequence[str]) -> None:
        self._texts = list(texts)

    async def generate(self, prompt: str) -> str:
        return self._texts.pop(0)

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        yield await self.generate(prompt)


def theta_vector(theta: float, dim: int = VECTOR_DIM) -> list[float]:
    """單位向量 (cos θ, sin θ, 0…)；與 `[1,0,…]` 的夾角即 θ，θ 越小分數越高。"""
    return [math.cos(theta), math.sin(theta)] + [0.0] * (dim - 2)


# ── 連線與通知 ───────────────────────────────────────────────────────────────
async def cypher(driver: Any, statement: str, **parameters: Any):
    return await driver.execute_query(statement, **parameters)


def notification_codes(summary: Any) -> list[str]:
    """取 `result.summary` 上的通知代碼；相容 driver 的 dict 與物件兩種形式。"""
    raw = None
    for attr in ("notifications", "summary_notifications"):
        try:
            raw = getattr(summary, attr, None)
        except Exception:  # noqa: BLE001 - 舊／新 driver 屬性差異
            raw = None
        if raw is not None:
            break
    codes: list[str] = []
    for item in raw or []:
        code = item.get("code") if isinstance(item, dict) else getattr(item, "code", None)
        if code:
            codes.append(str(code))
    return codes


def has_unknown_property_key(codes: Iterable[str]) -> bool:
    return any("UnknownPropertyKey" in c for c in codes)


def notification_details(summary: Any) -> list[dict[str, str]]:
    """每個通知的 `code`／`title`／`description`（描述內含被指為未知的屬性鍵名稱）；相容 dict 與物件兩種形式。"""
    raw = None
    for attr in ("notifications", "summary_notifications"):
        try:
            raw = getattr(summary, attr, None)
        except Exception:  # noqa: BLE001 - 舊／新 driver 屬性差異
            raw = None
        if raw is not None:
            break
    details: list[dict[str, str]] = []
    for item in raw or []:
        get = (lambda k, i=item: i.get(k)) if isinstance(item, dict) else (lambda k, i=item: getattr(i, k, None))
        if get("code"):
            details.append({"code": str(get("code")), "title": str(get("title") or ""),
                            "description": str(get("description") or "")})
    return details


def lifecycle_unknown_key_warnings(details: Iterable[dict[str, str]], key: str = "lifecycle_state") -> list[dict[str, str]]:
    """只挑「UnknownPropertyKey 且描述指名 `key`」的通知；其他屬性鍵（例如 `fixture_id`）的同類警告不算。"""
    return [d for d in details if "UnknownPropertyKey" in d["code"] and key in (d["description"] + d["title"])]


class RecordingDriver:
    """包住 driver，記錄每個語句的通知代碼；供 production 函式（只需 `execute_query`）使用。"""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.log: list[dict[str, Any]] = []

    async def execute_query(self, statement: str, **parameters: Any):
        result = await self.inner.execute_query(statement, **parameters)
        self.log.append({"statement": " ".join(statement.split())[:240], "codes": notification_codes(result.summary),
                         "details": notification_details(result.summary)})
        return result


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


async def wait_for_index(driver: Any, name: str) -> None:
    for _ in range(120):
        result = await cypher(driver, "SHOW INDEXES YIELD name, state WHERE name = $name RETURN state", name=name)
        if result.records and result.records[0]["state"] == "ONLINE":
            return
        await asyncio.sleep(0.5)
    raise RuntimeError(f"索引未在等待時間內 ONLINE：{name}")


async def load_production():
    with import_production_without_project_env():
        from services import svo_service
        from services.context.telemetry import build_retrieval_trace

    return SimpleNamespace(svo=svo_service, build_trace=build_retrieval_trace)


def redact(message: str, password: str) -> str:
    """遮蔽臨時密碼；密碼為空字串時不處理（`str.replace("", …)` 會在每個字元間插入）。"""
    if not password:
        return message
    return message.replace(f"neo4j/{password}", "neo4j/<redacted>").replace(password, "<redacted>")


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in (sorted(value, key=str) if isinstance(value, (set, frozenset)) else value)]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


# ── 事件序列化與 as_of 過濾（純函式）────────────────────────────────────────────
def event_to_dict(event: rl.LifecycleEvent) -> dict[str, Any]:
    return {"event_type": event.event_type, "effective_date": event.effective_date, "reason": event.reason,
            "evidence_ref": event.evidence_ref, "trigger_kind": event.trigger_kind}


def parse_events(raw: str | None) -> list[rl.LifecycleEvent]:
    """`lifecycle_events_json`（JSON 字串）→ 事件清單；`None`／空字串＝沒有事件。"""
    if not raw:
        return []
    return [rl.LifecycleEvent(**item) for item in json.loads(raw)]


def dump_events(events: Sequence[rl.LifecycleEvent]) -> str:
    return json.dumps([event_to_dict(e) for e in events], ensure_ascii=False)


def record_fact_id(record: dict[str, Any]) -> str:
    """合成環境的穩定 Fact 識別：`<source_doc_id>#<source_svo_chunk_index>`（production 檢索輸出本身不帶 fact_id）。"""
    return f"{record.get('source_doc_id')}#{record.get('source_svo_chunk_index')}"


def filter_as_of_then_dedupe(
    records: list[dict[str, Any]],
    events_by_fact_id: dict[str, list[rl.LifecycleEvent]],
    as_of: str,
    retrievable: frozenset[str | None] = rl.DEFAULT_RETRIEVABLE_STATES,
) -> list[dict[str, Any]]:
    """提案（報告260 S2）：先依 `state_as_of` 過濾，再以 production `_dedupe_facts_by_key` 去重。查無事件＝`no_events`。"""
    kept = [
        record for record in records
        if rl.is_retrievable_as_of(rl.state_as_of(events_by_fact_id.get(record_fact_id(record), []), as_of), retrievable)
    ]
    return _dedupe_facts_by_key(kept)


def summarize_timings(values_ms: Sequence[float]) -> dict[str, float | int]:
    ordered = sorted(values_ms)
    if not ordered:
        return {"n": 0}
    p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
    return {"n": len(ordered), "median_ms": round(statistics.median(ordered), 3), "p95_ms": round(p95, 3),
            "min_ms": round(ordered[0], 3), "max_ms": round(ordered[-1], 3)}


def plan_supersede_events(
    rows: list[dict[str, Any]], *, evidence_ref: str, valid_from: str | None
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """純計畫：對每個 Fact 追加「新版取代」事件。已含同 `evidence_ref` 者跳過（冪等）；追加後重播非法者跳過。"""
    stats = {"matched": len(rows), "appended": 0, "skipped_existing": 0, "skipped_illegal": 0, "skipped_no_date": 0}
    updates: list[dict[str, Any]] = []
    for row in rows:
        events = parse_events(row.get("events_json"))
        if any(e.evidence_ref == evidence_ref for e in events):
            stats["skipped_existing"] += 1
            continue
        if valid_from is None:
            stats["skipped_no_date"] += 1
            continue
        new_event = rl.LifecycleEvent(rl.REPLACED, valid_from, "新版條文取代", evidence_ref, "事件")
        candidate = [*events, new_event]
        replayed = rl.replay(candidate)
        if not replayed.ok:
            stats["skipped_illegal"] += 1
            continue
        stats["appended"] += 1
        updates.append({"eid": row["eid"], "events_json": dump_events(candidate), "state": replayed.final_state})
    return updates, stats


def scenario_result(current: Any, proposal: Any, expected: Any, unexpected: list[str]) -> dict[str, Any]:
    return {"current": current, "proposal": proposal, "expected": expected,
            "matches_expected": not unexpected, "unexpected_findings": unexpected}


def summarize_results(results: dict[str, Any]) -> dict[str, Any]:
    flags = {name: (res.get("matches_expected") if isinstance(res, dict) else None) for name, res in results.items()}
    return {"scenarios": flags, "all_match": bool(flags) and all(v is True for v in flags.values())}


# ── Cypher（原型；結構由單元測試檢查）──────────────────────────────────────────
RAW_CANDIDATES_CYPHER = """
CALL db.index.vector.queryNodes('{index}', $candidate_k, $vector)
YIELD node, score
RETURN {fixture}node.fact_text AS fact_text, node.verb AS verb,
       node.confidence AS confidence, node.subject AS subject, node.object AS object,
       node.rel_type AS rel_type, node.source_doc_id AS source_doc_id,
       node.source_svo_chunk_index AS source_svo_chunk_index, score{extra}
"""
EXTRA_NONE = ""
EXTRA_DOT = ",\n       node.lifecycle_state AS lifecycle_state"
EXTRA_MAP = ",\n       properties(node)['lifecycle_state'] AS lifecycle_state"
EXTRA_MAP_EVENTS = (",\n       properties(node)['lifecycle_state'] AS lifecycle_state,"
                    "\n       properties(node)['lifecycle_events_json'] AS lifecycle_events_json")

FACT_EVENTS_READ_CYPHER = """
MATCH (f:Fact {kg_id: $kg_id}) WHERE elementId(f) = $eid
RETURN properties(f)['lifecycle_events_json'] AS events_json, properties(f)['lifecycle_state'] AS state
"""
FACT_EVENTS_WRITE_CYPHER = """
MATCH (f:Fact {kg_id: $kg_id}) WHERE elementId(f) = $eid
SET f.lifecycle_events_json = $events_json, f.lifecycle_state = $state
RETURN count(f) AS updated
"""
SUPERSEDE_READ_CYPHER = """
MATCH (old:LawArticle {kg_id: $kg_id, law_id: $law_id, article_no: $article_no, version_id: $old_version_id})
MATCH (new:LawArticle {kg_id: $kg_id, law_id: $law_id, article_no: $article_no, version_id: $new_version_id})
MATCH (f:Fact {kg_id: $kg_id})-[:SUPPORTED_BY]->(old)
RETURN elementId(f) AS eid, properties(f)['lifecycle_events_json'] AS events_json, new.valid_from AS valid_from
ORDER BY elementId(f)
"""


def candidates_cypher(index_name: str, extra: str, *, with_fixture: bool = True) -> str:
    """`with_fixture=False` 用於 production merge 建出的 Fact（沒有 `fixture_id` 屬性）：若仍帶 `node.fixture_id`，
    每個查詢都會多一個與 `lifecycle_state` 無關的 UnknownPropertyKey 警告而污染 S1 判定。"""
    fixture = "node.fixture_id AS fixture_id, " if with_fixture else ""
    return RAW_CANDIDATES_CYPHER.format(index=index_name, extra=extra, fixture=fixture)


# ── 資料建立輔助 ─────────────────────────────────────────────────────────────
async def create_direct_fact(ctx: Any, driver: Any, kg_id: UUID, *, fixture_id: str, subject: str, rel_type: str,
                             object_: str, theta: float, source_doc_id: UUID, chunk_index: int) -> str:
    label = ctx.svo._kg_fact_label(str(kg_id))
    result = await cypher(
        driver,
        f"""
        CREATE (f:Fact:{label} {{
            kg_id: $kg_id, fixture_id: $fixture_id, subject: $subject, rel_type: $rel_type, object: $object,
            verb: '規範', confidence: 1.0, fact_text: $fact_text, fact_embedding: $embedding,
            source_doc_id: $source_doc_id, source_svo_chunk_index: $chunk_index
        }})
        RETURN elementId(f) AS eid
        """,
        kg_id=str(kg_id), fixture_id=fixture_id, subject=subject, rel_type=rel_type, object=object_,
        fact_text=f"{subject} 規範 {object_}", embedding=theta_vector(theta),
        source_doc_id=str(source_doc_id), chunk_index=chunk_index,
    )
    return result.records[0]["eid"]


async def set_fact_events(driver: Any, kg_id: UUID, eid: str, events: Sequence[rl.LifecycleEvent]) -> None:
    await cypher(driver, FACT_EVENTS_WRITE_CYPHER, kg_id=str(kg_id), eid=eid,
                 events_json=dump_events(events), state=rl.replay(events).final_state)


async def append_fact_event(driver: Any, kg_id: UUID, eid: str, event: rl.LifecycleEvent) -> None:
    read = await cypher(driver, FACT_EVENTS_READ_CYPHER, kg_id=str(kg_id), eid=eid)
    existing = parse_events(read.records[0]["events_json"]) if read.records else []
    await set_fact_events(driver, kg_id, eid, [*existing, event])


async def read_fact_events(driver: Any, kg_id: UUID, eid: str) -> tuple[list[rl.LifecycleEvent], str | None]:
    read = await cypher(driver, FACT_EVENTS_READ_CYPHER, kg_id=str(kg_id), eid=eid)
    row = read.records[0]
    return parse_events(row["events_json"]), row["state"]


async def link_new_version_supersedes(driver: Any, kg_id: UUID, *, law_id: str, article_no: str,
                                      old_version_id: str, new_version_id: str) -> dict[str, int]:
    """原型連動：對舊版條文支持的 Fact 追加「新版取代」事件並更新快取狀態；冪等（以 `evidence_ref` 判斷）。"""
    read = await cypher(driver, SUPERSEDE_READ_CYPHER, kg_id=str(kg_id), law_id=law_id, article_no=article_no,
                        old_version_id=old_version_id, new_version_id=new_version_id)
    rows = [dict(r) for r in read.records]
    evidence_ref = f"LawArticle:{law_id}:{article_no}:{new_version_id}"
    updates, stats = plan_supersede_events(rows, evidence_ref=evidence_ref,
                                           valid_from=rows[0]["valid_from"] if rows else None)
    for update in updates:
        result = await cypher(driver, FACT_EVENTS_WRITE_CYPHER, kg_id=str(kg_id), eid=update["eid"],
                              events_json=update["events_json"], state=update["state"])
        if int(result.records[0]["updated"]) != 1:
            raise RuntimeError("連動寫入筆數不符")
    return stats


def _triple(subject: str, verb: str, object_: str, doc: UUID, chunk: int, article_no: str | None = None) -> SVOTriple:
    return SVOTriple(subject=subject, rel_type="RELATED_TO", verb=verb, object=object_, source_doc_id=doc,
                     source_svo_chunk_index=chunk, source_article_no=article_no)


async def merge_synthetic(ctx: Any, driver: Any, kg_id: UUID, triples: list[SVOTriple], *,
                          llm: LLMProvider | None = None,
                          provider: SyntheticEmbeddingProvider | None = None) -> SyntheticEmbeddingProvider:
    """走 production `merge_triples_to_graph` 建資料；同一場景要重複呼叫時請傳入同一個 provider（one-hot 編號才一致）。"""
    provider = provider or SyntheticEmbeddingProvider()
    await ctx.svo.merge_triples_to_graph(driver, kg_id, triples, embedding_provider=provider, llm_provider=llm)
    return provider


async def ensure_fact_index(ctx: Any, driver: Any, kg_id: UUID, dim: int = VECTOR_DIM) -> None:
    await ctx.svo.create_fact_vector_index(driver, kg_id, dim=dim)
    await wait_for_index(driver, ctx.svo._fact_vector_index_name(str(kg_id)))


# ── S1：L1 真實行為 ──────────────────────────────────────────────────────────
S1_TRIPLES = (("勞動契約", "規範", "工資"), ("職業災害", "給予", "補償"), ("特別休假", "計算", "年資"), ("加班", "限制", "工時"))
S1_STATES = {"勞動契約": "候選", "職業災害": "有效", "特別休假": "已被取代"}  # 第四筆刻意不設
S1_EXPECTED_MARKS = {"勞動契約": "候選", "職業災害": "有效", "特別休假": "已被取代", "加班": "尚未處理"}


async def _s1_probe(ctx: Any, driver: Any, tag: str) -> dict[str, Any]:
    index = ctx.svo._fact_vector_index_name(str(S1_KG))
    query = _onehot(FACT_AXIS)
    rec = RecordingDriver(driver)
    results = await ctx.svo.vector_search_facts(rec, S1_KG, query, top_k=10)
    knn = [e for e in rec.log if "queryNodes" in e["statement"]]
    knn_details = [d for e in knn for d in e["details"]]
    out: dict[str, Any] = {
        "production_properties_map": {
            "notification_codes": [d["code"] for d in knn_details],
            "notification_details": knn_details,
            "lifecycle_state_warnings": len(lifecycle_unknown_key_warnings(knn_details)),
            "values": {r["subject"]: r.get("lifecycle_state", "<缺鍵>") for r in results},
        }
    }
    for name, extra in (("dot_property_same_text", EXTRA_DOT), ("map_same_text", EXTRA_MAP),
                        ("dot_property_fresh_plan", EXTRA_DOT), ("map_fresh_plan", EXTRA_MAP)):
        # 探針不帶 fixture_id：S1 的 Fact 由 production merge 建立，沒有該屬性，帶了會多一個無關警告
        text = candidates_cypher(index, extra, with_fixture=False) + (
            "" if name.endswith("same_text") else f"\n// plan-{tag}-{name}")
        res = await cypher(driver, text, candidate_k=40, vector=query)
        details = notification_details(res.summary)
        out[name] = {"notification_codes": [d["code"] for d in details], "notification_details": details,
                     "lifecycle_state_warnings": len(lifecycle_unknown_key_warnings(details)),
                     "values": {r["subject"]: r["lifecycle_state"] for r in res.records}}
    out["_results"] = results
    return out


async def run_s1(ctx: Any, driver: Any) -> dict[str, Any]:
    await merge_synthetic(ctx, driver, S1_KG, [_triple(s, v, o, uuid4(), 1) for s, v, o in S1_TRIPLES])
    await ensure_fact_index(ctx, driver, S1_KG)
    keys_before = await cypher(driver, "CALL db.propertyKeys() YIELD propertyKey RETURN collect(propertyKey) AS keys")
    key_existed_before = "lifecycle_state" in keys_before.records[0]["keys"]
    before = await _s1_probe(ctx, driver, "before")
    before.pop("_results")
    for subject, state in S1_STATES.items():
        await cypher(driver, "MATCH (f:Fact {kg_id: $kg_id, subject: $subject}) SET f.lifecycle_state = $state",
                     kg_id=str(S1_KG), subject=subject, state=state)
    keys_after = await cypher(driver, "CALL db.propertyKeys() YIELD propertyKey RETURN collect(propertyKey) AS keys")
    after = await _s1_probe(ctx, driver, "after")
    results = after.pop("_results")
    trace = ctx.build_trace([], results, None, include_semantic_marks=True)
    marks = {r["subject"]: f["semantic_marks"]["lifecycle_state"] for r, f in zip(results, trace["facts"])}
    unexpected: list[str] = []
    if key_existed_before:
        unexpected.append("屬性鍵 lifecycle_state 在寫入前就已存在於資料庫（S1 前置條件不成立）")
    # 只以「描述指名 lifecycle_state 的 UnknownPropertyKey 通知」判定；其他屬性鍵的警告（例如 fixture_id）不算
    if not before["dot_property_same_text"]["lifecycle_state_warnings"]:
        unexpected.append("屬性鍵不存在時，node.lifecycle_state 版本沒有指名 lifecycle_state 的 UnknownPropertyKey 通知")
    for name in ("production_properties_map", "map_same_text", "map_fresh_plan"):
        if before[name]["lifecycle_state_warnings"]:
            unexpected.append(f"屬性鍵不存在時，{name}（properties(node)[…]）出現指名 lifecycle_state 的通知")
    for name in ("production_properties_map", "dot_property_same_text", "map_same_text", "dot_property_fresh_plan",
                 "map_fresh_plan"):
        if after[name]["lifecycle_state_warnings"]:
            unexpected.append(f"屬性鍵存在後，{name} 仍有指名 lifecycle_state 的通知：{after[name]['notification_details']}")
    for name in ("production_properties_map", "map_same_text", "map_fresh_plan"):
        if after[name]["values"] != {**S1_STATES, "加班": None}:
            unexpected.append(f"屬性鍵存在後，{name} 回傳值不符：{after[name]['values']}")
    if marks != S1_EXPECTED_MARKS:
        unexpected.append(f"trace semantic_marks.lifecycle_state 不符：{marks}")
    expected = {
        "before_key_exists": {"dot_property": "有指名 lifecycle_state 的 UnknownPropertyKey 警告",
                              "properties_map": "無指名 lifecycle_state 的警告"},
        "after_key_exists": {"both_styles": "無指名 lifecycle_state 的警告",
                             "properties_map_values": {**S1_STATES, "加班": None}},
        "trace_marks": S1_EXPECTED_MARKS,
    }
    return scenario_result(
        {"before_key_exists": before, "property_key_existed_before": key_existed_before,
         "property_key_exists_after": "lifecycle_state" in keys_after.records[0]["keys"]},
        {"after_key_exists": after, "trace_marks": marks}, expected, unexpected)


# ── S2：state_as_of 先過濾後去重 ─────────────────────────────────────────────
S2_KEY = ("條文主體", "RELATED_TO", "資格")


def _e(kind: str, date: str) -> rl.LifecycleEvent:
    return rl.LifecycleEvent(kind, date)


S2_FACTS = {  # fixture → (key, θ, 事件序列)；θ 越小分數越高：B(最高) > A > C > D > E
    "A": (S2_KEY, 0.10, [_e(rl.EXTRACTED, "2027-01-01"), _e(rl.VERIFIED, "2027-01-01")]),
    "B": (S2_KEY, 0.00, [_e(rl.EXTRACTED, "2023-05-01"), _e(rl.VERIFIED, "2023-05-01"), _e(rl.REPLACED, "2025-12-09")]),
    "C": (S2_KEY, 0.20, [_e(rl.EXTRACTED, "2025-12-09"), _e(rl.VERIFIED, "2025-12-09")]),
    "D": (("舊資料主體", "RELATED_TO", "舊資料受詞"), 0.50, []),
    "E": (("一般主體", "RELATED_TO", "一般受詞"), 0.70, [_e(rl.EXTRACTED, "2020-01-01"), _e(rl.VERIFIED, "2020-01-01")]),
}
S2_EXPECTED = {"2026-10-02": ["C", "D", "E"], "2024-01-01": ["B", "D", "E"], "2027-01-01": ["A", "D", "E"]}
S2_EXPECTED_CURRENT = ["B", "D", "E"]


async def run_s2(ctx: Any, driver: Any) -> dict[str, Any]:
    fixture_by_pair: dict[tuple[str, int], str] = {}
    for i, (fixture, (key, theta, events)) in enumerate(S2_FACTS.items(), start=1):
        doc = uuid4()
        eid = await create_direct_fact(ctx, driver, S2_KG, fixture_id=fixture, subject=key[0], rel_type=key[1],
                                       object_=key[2], theta=theta, source_doc_id=doc, chunk_index=i)
        fixture_by_pair[(str(doc), i)] = fixture
        if events:
            await cypher(driver, "MATCH (f:Fact {kg_id: $kg_id}) WHERE elementId(f) = $eid "
                                 "SET f.lifecycle_events_json = '[]'", kg_id=str(S2_KG), eid=eid)
            for event in events:  # 以 Cypher 逐一追加並讀回
                await append_fact_event(driver, S2_KG, eid, event)
    await ensure_fact_index(ctx, driver, S2_KG)
    index = ctx.svo._fact_vector_index_name(str(S2_KG))
    query = _onehot(0)
    current = await ctx.svo.vector_search_facts(driver, S2_KG, query, top_k=5)
    current_fixtures = [fixture_by_pair[(r["source_doc_id"], r["source_svo_chunk_index"])] for r in current]
    raw = await cypher(driver, candidates_cypher(index, EXTRA_MAP_EVENTS), candidate_k=25, vector=query)
    candidates = [dict(r) for r in raw.records]
    events_by_id = {record_fact_id(c): parse_events(c["lifecycle_events_json"]) for c in candidates}
    proposal: dict[str, Any] = {}
    unexpected: list[str] = []
    for as_of in AS_OF_DATES:
        kept = filter_as_of_then_dedupe(candidates, events_by_id, as_of)
        fixtures = [c["fixture_id"] for c in kept]
        decisions = {c["fixture_id"]: rl.state_as_of(events_by_id[record_fact_id(c)], as_of).status for c in candidates}
        proposal[as_of] = {"kept": fixtures, "decisions": decisions}
        if fixtures != S2_EXPECTED[as_of]:
            unexpected.append(f"as_of={as_of} 保留 {fixtures}，預期 {S2_EXPECTED[as_of]}")
    if current_fixtures != S2_EXPECTED_CURRENT:
        unexpected.append(f"現行 vector_search_facts 輸出 {current_fixtures}，預期 {S2_EXPECTED_CURRENT}（同鍵留最高分 B、漏 C）")
    scores = {c["fixture_id"]: c["score"] for c in candidates}
    if not (scores["B"] > scores["A"] > scores["C"]):
        unexpected.append(f"分數設計未成立（B>A>C）：{scores}")
    return scenario_result(
        {"vector_search_facts_top_k_5": current_fixtures, "scores": scores,
         "misses_C": "C" not in current_fixtures, "keeps_superseded_B": "B" in current_fixtures},
        proposal, {"proposal_kept": S2_EXPECTED, "current": S2_EXPECTED_CURRENT}, unexpected)


# ── S3：BFS 邊來源混合 ───────────────────────────────────────────────────────
S3_TEXTS = ("依舊版規定，甲公司應給付乙津貼。", "依新版規定，甲公司應給付乙津貼。")


async def run_s3(ctx: Any, driver: Any) -> dict[str, Any]:
    doc_old, doc_new = uuid4(), uuid4()
    llm = ScriptedLLMProvider(S3_TEXTS)
    provider = await merge_synthetic(ctx, driver, S3_KG, [_triple("甲公司", "應給付", "乙津貼", doc_old, 1)], llm=llm)
    await merge_synthetic(ctx, driver, S3_KG, [_triple("甲公司", "應給付", "乙津貼", doc_new, 1)], llm=llm,
                          provider=provider)
    edges = await cypher(
        driver,
        """
        MATCH (s:Entity {kg_id: $kg_id, name: '甲公司'})-[r]->(o:Entity {kg_id: $kg_id, name: '乙津貼'})
        WHERE r.citations_json IS NOT NULL
        RETURN type(r) AS rel, r.citations_json AS citations_json, r.natural_text AS natural_text
        """, kg_id=str(S3_KG))
    edge_rows = [dict(r) for r in edges.records]
    citations = json.loads(edge_rows[0]["citations_json"]) if edge_rows else []
    facts = await cypher(driver, "MATCH (f:Fact {kg_id: $kg_id}) RETURN elementId(f) AS eid, f.source_doc_id AS doc",
                         kg_id=str(S3_KG))
    eid_by_doc = {r["doc"]: r["eid"] for r in facts.records}
    for doc in (doc_old, doc_new):
        await set_fact_events(driver, S3_KG, eid_by_doc[str(doc)],
                              [_e(rl.EXTRACTED, "2023-05-01"), _e(rl.VERIFIED, "2023-05-01")])
    await append_fact_event(driver, S3_KG, eid_by_doc[str(doc_old)], _e(rl.REPLACED, "2025-12-09"))
    states = {name: (await read_fact_events(driver, S3_KG, eid_by_doc[str(doc)]))[1]
              for name, doc in (("old", doc_old), ("new", doc_new))}
    triples = await ctx.svo.bfs_query(driver, S3_KG, ["甲公司"], hops=1)
    bfs = [{"source_doc_id": str(t.source_doc_id), "natural_text": t.natural_text} for t in triples]
    version_fields = unexpected_free(sorted(SVOTriple.model_fields))
    unexpected: list[str] = []
    if len(edge_rows) != 1:
        unexpected.append(f"邊數 {len(edge_rows)}，預期 1")
    if {c.get("source_doc_id") for c in citations} != {str(doc_old), str(doc_new)}:
        unexpected.append(f"citations 來源 {[c.get('source_doc_id') for c in citations]}，預期含新舊兩份")
    if edge_rows and edge_rows[0]["natural_text"] != S3_TEXTS[1]:
        unexpected.append(f"natural_text 非最後寫入者：{edge_rows[0]['natural_text']!r}")
    if len(bfs) != 1 or bfs[0]["source_doc_id"] != str(doc_new) or bfs[0]["natural_text"] != S3_TEXTS[1]:
        unexpected.append(f"bfs_query 回傳不符預期（單筆、帶最後來源與最後 natural_text）：{bfs}")
    if states != {"old": "已被取代", "new": "有效"}:
        unexpected.append(f"兩個版本的 Fact 狀態不符：{states}")
    if version_fields:
        unexpected.append(f"SVOTriple 已有生命週期／版本欄位 {version_fields}（與『邊不能分辨版本』的預期不符）")
    current = {"edge_rows": len(edge_rows), "citation_sources": [c.get("source_doc_id") for c in citations],
               "natural_text": edge_rows[0]["natural_text"] if edge_rows else None, "bfs_triples": bfs,
               "fact_states": states, "old_doc": str(doc_old), "new_doc": str(doc_new)}
    proposal = {"edge_can_distinguish_versions": bool(version_fields), "svo_triple_version_fields": version_fields,
                "note": "邊只有最後一筆來源與 natural_text；舊版 Fact 已被取代，邊卻仍呈現（新版措辭）——這是要量化的風險，不是要修的"}
    return scenario_result(current, proposal, {
        "edge_rows": 1, "citations": 2, "natural_text": "最後寫入者（新版）", "bfs_source": "新版",
        "fact_states": {"old": "已被取代", "new": "有效"}, "edge_distinguishes_versions": False}, unexpected)


def unexpected_free(fields: Sequence[str]) -> list[str]:
    """`SVOTriple` 欄位中與生命週期／版本相關者（預期為空＝邊不帶版本資訊）。"""
    return [name for name in fields if "lifecycle" in name or "version" in name]


# ── S4：條文層連動 ───────────────────────────────────────────────────────────
S4_LAW, S4_ARTICLE = "LAW-A", "第5條"
S4_ARTICLES = (  # (law_id, version_id, valid_from, [(subject, verb, object)])
    ("LAW-A", "v1", "2023-05-01", [("僱主", "給付", "員工"), ("工會", "協商", "資方")]),
    ("LAW-A", "v2", "2025-12-09", [("學校", "聘任", "教師"), ("醫院", "僱用", "護理師")]),
    ("LAW-B", "v1", "2024-01-01", [("銀行", "通知", "客戶")]),
)


async def run_s4(ctx: Any, driver: Any) -> dict[str, Any]:
    all_triples: list[SVOTriple] = []
    chunk = 0
    for law_id, version_id, valid_from, triples in S4_ARTICLES:
        doc = uuid4()
        await cypher(
            driver,
            """
            MERGE (a:LawArticle {kg_id: $kg_id, source_doc_id: $doc, article_no: $article_no})
            SET a.law_id = $law_id, a.version_id = $version_id, a.valid_from = $valid_from, a.article_content = '合成條文'
            """,
            kg_id=str(S4_KG), doc=str(doc), article_no=S4_ARTICLE, law_id=law_id, version_id=version_id,
            valid_from=valid_from)
        for subject, verb, object_ in triples:
            chunk += 1
            all_triples.append(_triple(subject, verb, object_, doc, chunk, S4_ARTICLE))
    # LawArticle 須先於 Fact 存在（`_create_fact_node` 的 article_no 路徑 fail-closed）；全部三元組用同一 provider 一次寫入
    await merge_synthetic(ctx, driver, S4_KG, all_triples)
    facts = await cypher(
        driver,
        """
        MATCH (f:Fact {kg_id: $kg_id})-[:SUPPORTED_BY]->(a:LawArticle {kg_id: $kg_id})
        RETURN elementId(f) AS eid, f.subject AS subject, a.law_id AS law_id, a.version_id AS version_id,
               a.valid_from AS valid_from
        """, kg_id=str(S4_KG))
    fact_rows = [dict(r) for r in facts.records]
    for row in fact_rows:
        await set_fact_events(driver, S4_KG, row["eid"],
                              [rl.LifecycleEvent(rl.EXTRACTED, row["valid_from"]), rl.LifecycleEvent(rl.VERIFIED, row["valid_from"])])
    naive = await cypher(
        driver,
        "MATCH (f:Fact {kg_id: $kg_id})-[:SUPPORTED_BY]->(a:LawArticle {kg_id: $kg_id, article_no: $article_no, version_id: 'v1'}) "
        "RETURN count(f) AS n", kg_id=str(S4_KG), article_no=S4_ARTICLE)
    first = await link_new_version_supersedes(driver, S4_KG, law_id=S4_LAW, article_no=S4_ARTICLE,
                                              old_version_id="v1", new_version_id="v2")
    second = await link_new_version_supersedes(driver, S4_KG, law_id=S4_LAW, article_no=S4_ARTICLE,
                                               old_version_id="v1", new_version_id="v2")
    per_fact: dict[str, Any] = {}
    unexpected: list[str] = []
    for row in fact_rows:
        events, cached = await read_fact_events(driver, S4_KG, row["eid"])
        replayed = rl.replay(events).final_state
        key = f"{row['law_id']}:{row['version_id']}:{row['subject']}"
        asof = {d: rl.state_as_of(events, d).state for d in ("2025-12-08", "2025-12-09")}
        per_fact[key] = {"events": len(events), "cached": cached, "replayed": replayed, "state_as_of": asof}
        old_of_a = (row["law_id"], row["version_id"]) == (S4_LAW, "v1")
        if replayed != cached:
            unexpected.append(f"{key} 事件重播 {replayed} ≠ 快取 {cached}（漂移）")
        want_events, want_state = (3, "已被取代") if old_of_a else (2, "有效")
        if (len(events), cached) != (want_events, want_state):
            unexpected.append(f"{key} 事件數／快取為 {(len(events), cached)}，預期 {(want_events, want_state)}")
        if old_of_a and asof != {"2025-12-08": "有效", "2025-12-09": "已被取代"}:
            unexpected.append(f"{key} state_as_of 取代日前後不符：{asof}")
    if first.get("appended") != 2:
        unexpected.append(f"第一次連動追加 {first.get('appended')} 筆，預期 2")
    if second.get("appended") != 0:
        unexpected.append(f"第二次連動追加 {second.get('appended')} 筆，預期 0（冪等）")
    return scenario_result(
        {"first_run": first, "second_run": second, "per_fact": per_fact,
         "naive_match_without_law_id_count": int(naive.records[0]["n"])},
        {"linkage": "link_new_version_supersedes（以 law_id＋article_no＋version_id 精確比對）"},
        {"first_appended": 2, "second_appended": 0, "old_facts": "3 事件／已被取代", "others": "2 事件／有效",
         "no_drift": True}, unexpected)


# ── S5：規模與耗時 ───────────────────────────────────────────────────────────
async def create_scale_facts(ctx: Any, driver: Any, kg_id: UUID) -> None:
    label = ctx.svo._kg_fact_label(str(kg_id))
    events_json = dump_events([_e(rl.EXTRACTED, "2020-01-01"), _e(rl.VERIFIED, "2020-01-01")])
    doc = str(uuid4())
    for start in range(0, SCALE_COUNT, SCALE_BATCH):
        await cypher(
            driver,
            f"""
            UNWIND range($start, $end) AS i
            CREATE (f:Fact:{label} {{
                kg_id: $kg_id, fixture_id: 'l2-scale-' + toString(i),
                subject: '規模主體' + toString(i), rel_type: 'RELATED_TO', object: '規模物件', verb: '規範',
                confidence: 1.0, fact_text: '規模主體' + toString(i) + ' 規範 規模物件',
                fact_embedding: [cos(i * 0.001), sin(i * 0.001)] + $pad,
                source_doc_id: $doc, source_svo_chunk_index: i + 1
            }})
            FOREACH (_ IN CASE WHEN i < $stateful THEN [1] ELSE [] END |
                SET f.lifecycle_state = '有效', f.lifecycle_events_json = $events_json)
            """,
            kg_id=str(kg_id), start=start, end=min(start + SCALE_BATCH - 1, SCALE_COUNT - 1),
            pad=[0.0] * (SCALE_DIM - 2),  # S5 單獨用 1024 維，直接 Cypher 建立（不經實體 merge，不受 one-hot／DEDUP4 限制）
            doc=doc, stateful=SCALE_STATEFUL, events_json=events_json)


async def _time_query(driver: Any, statement: str, **params: Any) -> tuple[list[float], int]:
    samples: list[float] = []
    rows = 0
    for i in range(TIMING_WARMUP + TIMING_RUNS):
        start = time.perf_counter()
        result = await cypher(driver, statement, **params)
        elapsed = (time.perf_counter() - start) * 1000
        rows = len(result.records)
        if i >= TIMING_WARMUP:
            samples.append(elapsed)
    return samples, rows


async def run_s5(ctx: Any, driver: Any) -> dict[str, Any]:
    await create_scale_facts(ctx, driver, S5_KG)
    counts = await cypher(
        driver,
        "MATCH (f:Fact {kg_id: $kg_id}) RETURN count(f) AS total, "
        "count(CASE WHEN properties(f)['lifecycle_state'] IS NOT NULL THEN 1 END) AS stateful", kg_id=str(S5_KG))
    total, stateful = counts.records[0]["total"], counts.records[0]["stateful"]
    dim_probe = await cypher(driver, "MATCH (f:Fact {kg_id: $kg_id}) RETURN size(f.fact_embedding) AS d LIMIT 1",
                             kg_id=str(S5_KG))
    embedding_dim = int(dim_probe.records[0]["d"])
    await ensure_fact_index(ctx, driver, S5_KG, dim=SCALE_DIM)  # 索引維度＝向量長度＝1024
    index = ctx.svo._fact_vector_index_name(str(S5_KG))
    query = theta_vector(0.5, SCALE_DIM)
    variants = {"no_column": EXTRA_NONE, "properties_map": EXTRA_MAP, "dot_property": EXTRA_DOT,
                "map_with_events_json": EXTRA_MAP_EVENTS}
    timings: dict[str, Any] = {}
    row_counts: dict[str, int] = {}
    notifications: dict[str, list[dict[str, str]]] = {}
    for candidate_k in (80, 160):
        for name, extra in variants.items():
            samples, rows = await _time_query(driver, candidates_cypher(index, extra), candidate_k=candidate_k, vector=query)
            timings[f"{name}@k{candidate_k}"] = summarize_timings(samples)
            row_counts[f"{name}@k{candidate_k}"] = rows
            probe = await cypher(driver, candidates_cypher(index, extra), candidate_k=candidate_k, vector=query)
            notifications[f"{name}@k{candidate_k}"] = notification_details(probe.summary)
    for top_k in (20, 40):
        samples = []
        for i in range(TIMING_WARMUP + TIMING_RUNS):
            start = time.perf_counter()
            results = await ctx.svo.vector_search_facts(driver, S5_KG, query, top_k=top_k)
            if i >= TIMING_WARMUP:
                samples.append((time.perf_counter() - start) * 1000)
        timings[f"production_vector_search_facts@top_k{top_k}"] = summarize_timings(samples)
        row_counts[f"production_vector_search_facts@top_k{top_k}"] = len(results)
    raw = await cypher(driver, candidates_cypher(index, EXTRA_MAP_EVENTS), candidate_k=160, vector=query)
    candidates = [dict(r) for r in raw.records]
    events_by_id = {record_fact_id(c): parse_events(c["lifecycle_events_json"]) for c in candidates}
    filter_samples = []
    for _ in range(TIMING_RUNS):
        start = time.perf_counter()
        kept = filter_as_of_then_dedupe(candidates, events_by_id, "2026-10-02")
        filter_samples.append((time.perf_counter() - start) * 1000)
    timings["filter_as_of_then_dedupe@160_candidates"] = summarize_timings(filter_samples)

    def median(name: str) -> float:
        return float(timings[name]["median_ms"])

    comparison = {f"k{k}": {"dot_property_minus_properties_map_median_ms": round(median(f"dot_property@k{k}") - median(f"properties_map@k{k}"), 3),
                            "properties_map_minus_no_column_median_ms": round(median(f"properties_map@k{k}") - median(f"no_column@k{k}"), 3),
                            "dot_property_cheaper": median(f"dot_property@k{k}") < median(f"properties_map@k{k}")}
                  for k in (80, 160)}
    unexpected: list[str] = []
    if (total, stateful) != (SCALE_COUNT, SCALE_STATEFUL):
        unexpected.append(f"Fact 總數／帶狀態數為 {(total, stateful)}，預期 {(SCALE_COUNT, SCALE_STATEFUL)}")
    for name, rows in row_counts.items():
        want = int(name.rsplit("k", 1)[1])  # `…@k80`／`…@top_k20` 皆以尾端數字為預期筆數
        if rows != want:
            unexpected.append(f"{name} 回傳 {rows} 筆，預期 {want}")
    if embedding_dim != SCALE_DIM:
        unexpected.append(f"fact_embedding 維度為 {embedding_dim}，預期 {SCALE_DIM}")
    flagged = {k: lifecycle_unknown_key_warnings(v) for k, v in notifications.items() if lifecycle_unknown_key_warnings(v)}
    if flagged:
        unexpected.append(f"屬性鍵存在時仍有指名 lifecycle_state 的 UnknownPropertyKey 通知：{flagged}")
    return scenario_result(
        {"embedding_dim": embedding_dim, "timings_ms": timings, "row_counts": row_counts,
         "kept_after_filter_160": len(kept)},
        {"dot_vs_map_when_key_exists": comparison, "notification_details": notifications},
        {"fact_count": SCALE_COUNT, "stateful_count": SCALE_STATEFUL, "candidate_rows": "80／160",
         "embedding_dim": SCALE_DIM, "no_lifecycle_state_unknown_key_warning_when_key_exists": True,
         "claim_to_test": "報告258 §10『L4 後可改回較便宜寫法』是否成立（dot_property_cheaper）"}, unexpected)


# ── 執行 ─────────────────────────────────────────────────────────────────────
async def _guard(name: str, coro: Any, password: str) -> dict[str, Any]:
    try:
        return await coro
    except Exception as exc:  # noqa: BLE001 - 單一場景失敗不得中止其他場景
        message = redact(str(exc), password)
        return {"status": "error", "scenario": name, "error_type": type(exc).__name__,
                "error_message_sanitized": message.splitlines()[0][:500] if message else "", "matches_expected": False}


async def run_validation(driver: Any, password: str) -> dict[str, Any]:
    ctx = await load_production()
    await ctx.svo.create_entity_name_vector_index(driver, dim=VECTOR_DIM)
    await wait_for_index(driver, "entity_name_vector")
    results: dict[str, Any] = {}
    for name, runner in (("S1", run_s1), ("S2", run_s2), ("S3", run_s3), ("S4", run_s4), ("S5", run_s5)):
        results[name] = await _guard(name, runner(ctx, driver), password)  # S1 必須最先：此時資料庫尚無 lifecycle_state 屬性鍵
    return {**results, "summary": summarize_results(results), "status": "completed"}


async def run_session(password: str) -> tuple[dict[str, Any], str | None]:
    driver = await wait_for_driver(password, S1_KG)
    try:
        result = await run_validation(driver, password)
    except Exception as exc:  # noqa: BLE001 - preserve teardown/reporting
        message = redact(str(exc), password)
        result = {"status": "failed", "error_type": type(exc).__name__,
                  "error_message_sanitized": message.splitlines()[0][:500] if message else ""}
    close_error: str | None = None
    try:
        await driver.close()
    except Exception as exc:  # noqa: BLE001 - close must not block Docker teardown
        close_error = type(exc).__name__
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
    password = ""
    try:
        password = generate_temp_password()
        launch_temp_container(password)
        launched = True
        result, _ = asyncio.run(run_session(password))
    except Exception as exc:  # noqa: BLE001 - preserve cleanup and report failure type
        message = redact(str(exc), password)
        result = {"status": "failed", "error_type": type(exc).__name__,
                  "error_message_sanitized": message.splitlines()[0][:500] if message else ""}
    finally:
        teardown = teardown_temp_container() if launched else {"present_before": [], "present_after": []}
        kg4_end = kg4_state()
        result["w0"] = {
            "baseline_expected": EXPECTED_KG4_STARTED_AT, "kg4_start": kg4_start, "kg4_end": kg4_end,
            "kg4_unchanged": kg4_start == kg4_end,
            "container_args": {"name": TEMP_CONTAINER, "image": IMAGE, "ports": list(TEMP_PORTS), "memory": "3g",
                               "volume": False, "bind_mount": False, "pull": False},
        }
        result["w5"] = {"teardown": teardown, "temp_absent_after": not teardown.get("present_after"),
                        "kg4_unchanged": kg4_start == kg4_end}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(_jsonable(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": result.get("status"), "output": str(args.output),
                      "all_match": result.get("summary", {}).get("all_match"),
                      "temp_absent_after": result.get("w5", {}).get("temp_absent_after"),
                      "kg4_unchanged": result.get("w5", {}).get("kg4_unchanged")}, ensure_ascii=False))
    ok = result.get("status") == "completed" and result["w5"]["temp_absent_after"] and result["w5"]["kg4_unchanged"]
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
