"""報告260 N3：L2′ 驗證腳本的純測試（閘門、純函式、Cypher 結構、假 driver）；不需 Docker／Neo4j。"""

from __future__ import annotations

import ast
import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from scripts.analysis import disposable_lifecycle_l2_validation as h
from services import relation_lifecycle as rl

SCRIPT = Path(h.__file__)
SRC = SCRIPT.read_text(encoding="utf-8")


def ev(kind, date=None, ref=None):
    return rl.LifecycleEvent(kind, date, None, ref)


# ---- 閘門與常數 -------------------------------------------------------------

def test_new_baseline_constant():
    assert h.EXPECTED_KG4_STARTED_AT == "2026-10-02T11:09:32.79429649Z"
    assert h._baseline_ok({"status": "running", "started_at": h.EXPECTED_KG4_STARTED_AT})
    assert not h._baseline_ok({"status": "running", "started_at": "2026-10-02T04:10:38.389676557Z"})
    assert not h._baseline_ok({"status": "exited", "started_at": h.EXPECTED_KG4_STARTED_AT})


def test_gate_accepts_only_throwaway_endpoint():
    h.validate_connection_target("bolt://127.0.0.1:27687", uuid4())
    h.validate_connection_target("bolt://localhost:27687", uuid4())


@pytest.mark.parametrize("uri", [
    "bolt://localhost:17990", "bolt://127.0.0.1:7687", "http://localhost:27687", "bolt://kg2-neo4j:27687",
    "bolt://example.com:27687",
])
def test_gate_rejects_protected_or_wrong_targets(uri):
    with pytest.raises(RuntimeError):
        h.validate_connection_target(uri, uuid4())


def test_gate_rejects_kg4_id():
    with pytest.raises(RuntimeError):
        h.validate_connection_target("bolt://127.0.0.1:27687", h.KG4_ID)


def test_docker_args_fixed_no_volume_mount_or_pull():
    argv = h.build_docker_run_argv()
    assert argv[0] == "run" and h.TEMP_CONTAINER in argv and h.IMAGE in argv
    assert h.TEMP_CONTAINER == "kg2-throwaway-neo4j"
    assert "27474:7474" in argv and "27687:7687" in argv and "3g" in argv
    assert not {"--pull", "--mount", "-v", "--volume", "--network", "--privileged"} & set(argv)
    assert all("kg2_neo4j_data" not in a and "17990" not in a for a in argv)
    assert "neo4j/" not in " ".join(argv)


def test_password_random_and_redaction_safe_for_empty():
    a, b = h.generate_temp_password(), h.generate_temp_password()
    assert a != b and a not in " ".join(h.build_docker_run_argv())
    assert h.redact("連線失敗", "") == "連線失敗"
    assert "secret" not in h.redact("auth neo4j/secret failed secret", "secret")


# ---- 通知與計時 -------------------------------------------------------------

def test_notification_codes_both_shapes():
    dict_shape = SimpleNamespace(notifications=[{"code": "Neo.ClientNotification.Statement.UnknownPropertyKeyWarning"}])
    obj_shape = SimpleNamespace(notifications=None, summary_notifications=[SimpleNamespace(code="X.Y"), SimpleNamespace(code=None)])
    empty = SimpleNamespace(notifications=[], summary_notifications=[])
    assert h.has_unknown_property_key(h.notification_codes(dict_shape))
    assert h.notification_codes(obj_shape) == ["X.Y"] and not h.has_unknown_property_key(["X.Y"])
    assert h.notification_codes(empty) == [] and h.notification_codes(SimpleNamespace()) == []


FIXTURE_WARNING = {
    "code": "Neo.ClientNotification.Statement.UnknownPropertyKeyWarning", "title": "The provided property key is not in the database",
    "description": "One of the property names in your query is not available in the database, make sure you didn't "
                   "misspell it or that the label is available when you run this statement in your application "
                   "(the missing property name is: fixture_id)",
}
LIFECYCLE_WARNING = {**FIXTURE_WARNING, "description": FIXTURE_WARNING["description"].replace("fixture_id", "lifecycle_state")}


def test_notification_details_both_shapes():
    dict_shape = SimpleNamespace(notifications=[dict(FIXTURE_WARNING), {"title": "no code"}])
    obj_shape = SimpleNamespace(notifications=None, summary_notifications=[
        SimpleNamespace(code="A.B", title="t", description="d"), SimpleNamespace(code=None, title="x", description="y")])
    assert h.notification_details(dict_shape) == [FIXTURE_WARNING]
    assert h.notification_details(obj_shape) == [{"code": "A.B", "title": "t", "description": "d"}]
    assert h.notification_details(SimpleNamespace()) == []


def test_fixture_id_warning_alone_is_not_a_lifecycle_state_warning():
    assert h.lifecycle_unknown_key_warnings([FIXTURE_WARNING]) == []
    assert h.lifecycle_unknown_key_warnings([FIXTURE_WARNING, LIFECYCLE_WARNING]) == [LIFECYCLE_WARNING]
    assert h.lifecycle_unknown_key_warnings([]) == []
    # 非 UnknownPropertyKey 的通知即使描述提到 lifecycle_state 也不算
    other = {"code": "Neo.ClientNotification.Statement.CartesianProduct", "title": "", "description": "lifecycle_state"}
    assert h.lifecycle_unknown_key_warnings([other]) == []
    assert h.lifecycle_unknown_key_warnings([{**LIFECYCLE_WARNING, "description": "", "title": "lifecycle_state"}])


def test_s1_probe_queries_do_not_reference_fixture_id():
    source = ast.get_source_segment(SRC, next(n for n in ast.walk(ast.parse(SRC))
                                              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_s1_probe"))
    assert "with_fixture=False" in source and "node.fixture_id" not in source
    assert "node.fixture_id" not in h.candidates_cypher("idx", h.EXTRA_DOT, with_fixture=False)
    assert "node.fixture_id AS fixture_id" in h.candidates_cypher("idx", h.EXTRA_DOT)  # S2／S5 的 Fact 有 fixture_id
    assert h.candidates_cypher("idx", h.EXTRA_MAP, with_fixture=False).count("RETURN node.fact_text AS fact_text") == 1


def test_s1_judgement_uses_lifecycle_specific_warnings_not_raw_codes():
    source = ast.get_source_segment(SRC, next(n for n in ast.walk(ast.parse(SRC))
                                              if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_s1"))
    assert "lifecycle_state_warnings" in source and "has_unknown_property_key" not in source


def test_recording_driver_details():
    class Inner:
        async def execute_query(self, statement, **params):
            return SimpleNamespace(records=[], summary=SimpleNamespace(notifications=[dict(LIFECYCLE_WARNING)]))

    rec = h.RecordingDriver(Inner())
    asyncio.run(rec.execute_query("MATCH (n) RETURN n"))
    assert rec.log[0]["details"] == [LIFECYCLE_WARNING] and rec.log[0]["codes"] == [LIFECYCLE_WARNING["code"]]


def test_s5_uses_1024_dim_while_other_scenarios_stay_16():
    assert h.SCALE_DIM == 1024 and h.VECTOR_DIM == 16
    assert len(h.theta_vector(0.5, h.SCALE_DIM)) == 1024 and len(h.theta_vector(0.5)) == 16

    calls: list[dict] = []

    class Driver:
        async def execute_query(self, statement, **params):
            calls.append({"statement": statement, **params})
            return SimpleNamespace(records=[])

    ctx = SimpleNamespace(svo=SimpleNamespace(_kg_fact_label=lambda kg: "Fact_x"))
    asyncio.run(h.create_scale_facts(ctx, Driver(), uuid4()))
    assert len(calls) == -(-h.SCALE_COUNT // h.SCALE_BATCH)
    assert all(len(c["pad"]) == h.SCALE_DIM - 2 for c in calls)  # [cos, sin] + pad ＝ 1024 維
    assert calls[0]["start"] == 0 and calls[-1]["end"] == h.SCALE_COUNT - 1
    assert all("DELETE" not in c["statement"] for c in calls)

    index_calls: list[tuple] = []

    class Svo:
        async def create_fact_vector_index(self, driver, kg_id, dim):
            index_calls.append(("create", dim))

        def _fact_vector_index_name(self, kg):
            return "idx"

    class IdxDriver:
        async def execute_query(self, statement, **params):
            return SimpleNamespace(records=[{"state": "ONLINE"}])

    asyncio.run(h.ensure_fact_index(SimpleNamespace(svo=Svo()), IdxDriver(), uuid4(), dim=h.SCALE_DIM))
    asyncio.run(h.ensure_fact_index(SimpleNamespace(svo=Svo()), IdxDriver(), uuid4()))
    assert index_calls == [("create", 1024), ("create", 16)]
    s5 = ast.get_source_segment(SRC, next(n for n in ast.walk(ast.parse(SRC))
                                          if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_s5"))
    assert "dim=SCALE_DIM" in s5 and "theta_vector(0.5, SCALE_DIM)" in s5


def test_summarize_timings():
    out = h.summarize_timings([5.0, 1.0, 3.0, 2.0, 4.0])
    assert (out["n"], out["median_ms"], out["min_ms"], out["max_ms"]) == (5, 3.0, 1.0, 5.0)
    assert out["p95_ms"] == 5.0 and h.summarize_timings([]) == {"n": 0}


def test_summarize_results_and_scenario_result():
    ok = h.scenario_result({}, {}, {}, [])
    bad = h.scenario_result({}, {}, {}, ["x"])
    assert ok["matches_expected"] is True and bad["matches_expected"] is False
    assert h.summarize_results({"S1": ok, "S2": ok})["all_match"] is True
    assert h.summarize_results({"S1": ok, "S2": bad})["all_match"] is False
    assert h.summarize_results({"S1": ok, "S2": {"status": "error", "matches_expected": False}})["all_match"] is False
    assert h.summarize_results({})["all_match"] is False


def test_events_json_round_trip():
    events = [ev(rl.EXTRACTED, "2025-01-01"), rl.LifecycleEvent(rl.REPLACED, "2025-12-09", "原因", "ref", "事件")]
    assert h.parse_events(h.dump_events(events)) == events
    assert h.parse_events(None) == [] and h.parse_events("") == [] and h.parse_events("[]") == []


# ---- filter_as_of_then_dedupe ------------------------------------------------

def _records():
    def rec(fixture, score, key, doc, chunk):
        return {"fixture_id": fixture, "score": score, "subject": key[0], "rel_type": key[1], "object": key[2],
                "source_doc_id": doc, "source_svo_chunk_index": chunk}

    key = ("主", "R", "受")
    return [rec("B", 0.99, key, "dB", 1), rec("A", 0.95, key, "dA", 1), rec("C", 0.90, key, "dC", 1),
            rec("D", 0.80, ("d", "R", "d"), "dD", 1), rec("E", 0.70, ("e", "R", "e"), "dE", 1)]


def _events():
    e = ev
    return {
        "dA#1": [e(rl.EXTRACTED, "2027-01-01"), e(rl.VERIFIED, "2027-01-01")],
        "dB#1": [e(rl.EXTRACTED, "2023-05-01"), e(rl.VERIFIED, "2023-05-01"), e(rl.REPLACED, "2025-12-09")],
        "dC#1": [e(rl.EXTRACTED, "2025-12-09"), e(rl.VERIFIED, "2025-12-09")],
        "dE#1": [e(rl.EXTRACTED, "2020-01-01"), e(rl.VERIFIED, "2020-01-01")],
    }  # D 無事件


@pytest.mark.parametrize("as_of", h.AS_OF_DATES)
def test_filter_matches_report_expectations(as_of):
    kept = h.filter_as_of_then_dedupe(_records(), _events(), as_of)
    assert [r["fixture_id"] for r in kept] == h.S2_EXPECTED[as_of]


def test_current_behaviour_dedupes_first_and_loses_new_version():
    from services.retrieval.fact_candidates import _dedupe_facts_by_key

    assert [r["fixture_id"] for r in _dedupe_facts_by_key(_records())] == ["B", "D", "E"]


def test_filter_missing_key_fields_kept_and_unknown_events_treated_as_none():
    records = [{"fixture_id": "X", "score": 1, "subject": None, "rel_type": None, "object": None,
                "source_doc_id": "dX", "source_svo_chunk_index": 1}]
    assert h.filter_as_of_then_dedupe(records, {}, "2026-10-02") == records
    assert h.filter_as_of_then_dedupe(records, {}, "2026-10-02", frozenset({rl.VALID})) == []


def test_s2_fixture_design_scores_and_keys():
    thetas = {k: v[1] for k, v in h.S2_FACTS.items()}
    assert thetas["B"] < thetas["A"] < thetas["C"] < thetas["D"] < thetas["E"]
    assert h.S2_FACTS["A"][0] == h.S2_FACTS["B"][0] == h.S2_FACTS["C"][0]
    assert h.S2_FACTS["D"][0] != h.S2_FACTS["E"][0] and h.S2_FACTS["D"][2] == []


# ---- plan_supersede_events 與假 driver ----------------------------------------

REF = "LawArticle:LAW-A:第5條:v2"


def test_plan_supersede_appends_skips_existing_illegal_and_is_idempotent():
    valid = h.dump_events([ev(rl.EXTRACTED, "2023-05-01"), ev(rl.VERIFIED, "2023-05-01")])
    candidate = h.dump_events([ev(rl.EXTRACTED, "2023-05-01")])  # 候選不可直接被取代
    done = h.dump_events([ev(rl.EXTRACTED, "2023-05-01"), ev(rl.VERIFIED, "2023-05-01"), ev(rl.REPLACED, "2025-12-09", REF)])
    rows = [{"eid": "1", "events_json": valid}, {"eid": "2", "events_json": candidate},
            {"eid": "3", "events_json": done}, {"eid": "4", "events_json": None}]
    updates, stats = h.plan_supersede_events(rows, evidence_ref=REF, valid_from="2025-12-09")
    assert stats == {"matched": 4, "appended": 1, "skipped_existing": 1, "skipped_illegal": 2, "skipped_no_date": 0}
    assert [u["eid"] for u in updates] == ["1"] and updates[0]["state"] == "已被取代"
    assert len(h.parse_events(updates[0]["events_json"])) == 3
    rows[0]["events_json"] = updates[0]["events_json"]
    again, stats2 = h.plan_supersede_events(rows, evidence_ref=REF, valid_from="2025-12-09")
    assert again == [] and stats2["appended"] == 0 and stats2["skipped_existing"] == 2
    _, stats3 = h.plan_supersede_events(rows[:1] and [{"eid": "5", "events_json": valid}], evidence_ref=REF, valid_from=None)
    assert stats3["skipped_no_date"] == 1 and stats3["appended"] == 0


class FakeEventsDriver:
    """依語句分流：讀取連動候選／寫入事件；以記憶體字典模擬 Fact 屬性。"""

    def __init__(self, facts):
        self.facts = facts  # eid → {"events_json", "state"}
        self.statements: list[tuple[str, dict]] = []

    async def execute_query(self, statement, **params):
        self.statements.append((statement, params))
        if "LawArticle" in statement:
            rows = [{"eid": e, "events_json": f["events_json"], "valid_from": "2025-12-09"} for e, f in self.facts.items()]
            return SimpleNamespace(records=rows)
        if "SET f.lifecycle_events_json" in statement:
            self.facts[params["eid"]] = {"events_json": params["events_json"], "state": params["state"]}
            return SimpleNamespace(records=[{"updated": 1}])
        return SimpleNamespace(records=[{"events_json": self.facts[params["eid"]]["events_json"],
                                         "state": self.facts[params["eid"]]["state"]}])


def test_link_new_version_supersedes_is_idempotent_with_fake_driver():
    base = h.dump_events([ev(rl.EXTRACTED, "2023-05-01"), ev(rl.VERIFIED, "2023-05-01")])
    driver = FakeEventsDriver({"f1": {"events_json": base, "state": "有效"}, "f2": {"events_json": base, "state": "有效"}})
    kwargs = dict(law_id="LAW-A", article_no="第5條", old_version_id="v1", new_version_id="v2")
    first = asyncio.run(h.link_new_version_supersedes(driver, uuid4(), **kwargs))
    second = asyncio.run(h.link_new_version_supersedes(driver, uuid4(), **kwargs))
    assert first["appended"] == 2 and second["appended"] == 0 and second["skipped_existing"] == 2
    for fact in driver.facts.values():
        assert fact["state"] == rl.replay(h.parse_events(fact["events_json"])).final_state == "已被取代"
        assert h.parse_events(fact["events_json"])[-1].evidence_ref == REF


def test_recording_driver_records_statement_and_codes():
    class Inner:
        async def execute_query(self, statement, **params):
            return SimpleNamespace(records=[], summary=SimpleNamespace(notifications=[{"code": "A.B"}]))

    rec = h.RecordingDriver(Inner())
    asyncio.run(rec.execute_query("MATCH (n)\n RETURN n"))
    assert [(e["statement"], e["codes"]) for e in rec.log] == [("MATCH (n) RETURN n", ["A.B"])]


# ---- Cypher 結構 -------------------------------------------------------------

def test_write_and_link_cypher_structure():
    for statement in (h.FACT_EVENTS_READ_CYPHER, h.FACT_EVENTS_WRITE_CYPHER, h.SUPERSEDE_READ_CYPHER):
        assert "$kg_id" in statement and "Fact" in statement
        assert not re.search(r"\b(DELETE|DETACH|REMOVE|DROP|MERGE)\b", statement, re.I)
    assert "{kg_id: $kg_id}" in h.FACT_EVENTS_WRITE_CYPHER
    assert re.findall(r"SET\s+(.+)", h.FACT_EVENTS_WRITE_CYPHER) == ["f.lifecycle_events_json = $events_json, f.lifecycle_state = $state"]
    assert "law_id: $law_id" in h.SUPERSEDE_READ_CYPHER  # 不同法規同號條文不得被連動
    assert "SUPPORTED_BY" in h.SUPERSEDE_READ_CYPHER


def test_candidate_cypher_variants():
    index = "fact_embedding_vector_x"
    dot, mapped = h.candidates_cypher(index, h.EXTRA_DOT), h.candidates_cypher(index, h.EXTRA_MAP)
    assert "node.lifecycle_state AS lifecycle_state" in dot and "properties(node)" not in dot
    assert "properties(node)['lifecycle_state'] AS lifecycle_state" in mapped and "node.lifecycle_state" not in mapped
    assert "lifecycle" not in h.candidates_cypher(index, h.EXTRA_NONE)
    assert "properties(node)['lifecycle_events_json']" in h.candidates_cypher(index, h.EXTRA_MAP_EVENTS)
    assert index in dot and "{extra}" not in dot


# ---- 腳本文字守衛 ---------------------------------------------------------------

def test_script_has_no_forbidden_connection_strings_or_secrets():
    for needle in ("17990", "bolt://", "neo4j://", "kg2_neo4j_data", ".env"):
        assert needle not in SRC, needle
    # 密碼樣式＝43 字元以上且同時含大寫、小寫與數字（`secrets.token_urlsafe(32)`）；snake_case 識別字／檔名不含大寫
    for token in re.findall(r"[A-Za-z0-9_\-]{43,}", SRC):
        assert not (re.search(r"[A-Z]", token) and re.search(r"[a-z]", token) and re.search(r"\d", token)), token
    assert not re.search(r"(?i)password\s*=\s*[\"'][^\"']+[\"']", SRC)


def test_script_never_defines_or_calls_old_baseline_runners_or_other_docker():
    names = {n.name for n in ast.walk(ast.parse(SRC)) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert not {"_run_with_password", "run_with_password"} & names
    assert "p3._run_with_password" not in SRC and "p4.run_with_password" not in SRC
    assert "disposable_write_path_validation" not in SRC
    assert not re.search(r"subprocess|docker\s+(run|rm|stop|exec|cp|pull)", SRC)


def test_scenarios_exist_s1_first_and_output_path():
    for name in ("run_s1", "run_s2", "run_s3", "run_s4", "run_s5"):
        assert callable(getattr(h, name))
    order = re.search(r'\(\("S1", run_s1\), \("S2", run_s2\), \("S3", run_s3\), \("S4", run_s4\), \("S5", run_s5\)\)', SRC)
    assert order, "S1 必須最先執行（資料庫尚無 lifecycle_state 屬性鍵時才能觀察 UnknownPropertyKey）"
    assert h.REPORT_OUTPUT.name == "disposable_lifecycle_l2_validation_20261002.json"
    json.dumps(h._jsonable({"a": {1, 2}, "b": (1, "x")}))


def test_synthetic_providers_are_deterministic_and_orthogonal():
    provider = h.SyntheticEmbeddingProvider()
    a = asyncio.run(provider.encode("甲"))
    b = asyncio.run(provider.encode("乙"))
    fact = asyncio.run(provider.encode("甲 規範 乙"))
    assert a == asyncio.run(provider.encode("甲")) and sum(x * y for x, y in zip(a, b)) == 0
    assert fact == h._onehot(h.FACT_AXIS) and len(a) == h.VECTOR_DIM == provider.dim
    llm = h.ScriptedLLMProvider(["一", "二"])
    assert asyncio.run(llm.generate("p")) == "一" and asyncio.run(llm.generate("p")) == "二"
    vec = h.theta_vector(0.0)
    assert vec[0] == 1.0 and len(vec) == h.VECTOR_DIM
