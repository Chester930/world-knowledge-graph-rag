"""報告264 Q4-B：`scripts/kg/pilot_asof_search.py` 的離線測試（假 driver／假 svo；不連線）。"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from scripts.analysis import pilot_version_corpus_builder as builder
from scripts.kg import pilot_asof_search as aso
from scripts.kg import pilot_import as pi
from services import relation_lifecycle as rl

REPO = Path(pi._REPO)
SRC = Path(aso.__file__).read_text(encoding="utf-8")
FAKE_REPO = [Path("/nonexistent-repo-root")]


def ev(kind, date, ref="r"):
    return rl.LifecycleEvent(kind, date, None, ref, "事件")


def events_json(*events):
    from scripts.analysis import disposable_lifecycle_l2_validation as d

    return d.dump_events(events)


OLD = events_json(ev(rl.EXTRACTED, "2023-05-01"), ev(rl.VERIFIED, "2023-05-01"), ev(rl.REPLACED, "2025-12-09"))
NEW = events_json(ev(rl.EXTRACTED, "2025-12-09"), ev(rl.VERIFIED, "2025-12-09"))
FUTURE = events_json(ev(rl.EXTRACTED, "2027-01-01"), ev(rl.VERIFIED, "2027-01-01"))
GENERAL = events_json(ev(rl.EXTRACTED, "2020-01-01"), ev(rl.VERIFIED, "2020-01-01"))


def cand(fixture, score, key, doc, chunk, events, *, state=None, law_id="N1", article="第 1 條", valid_from="2020-01-01"):
    return {"fact_text": f"{key[0]} 規範 {key[2]}", "verb": "規範", "confidence": 1.0, "subject": key[0], "object": key[2], "rel_type": key[1],
            "source_doc_id": doc, "source_svo_chunk_index": chunk, "score": score, "lifecycle_state": state,
            "lifecycle_events_json": events, "law_id": law_id, "article_no": article, "valid_from": valid_from, "_fixture": fixture}


KEY = ("條文主體", "RELATED_TO", "資格")


def s2_candidates():
    # 與報告260 S2 同構：B 舊版分數最高、A 尚未施行、C 新版；D 無事件；E 一般有效；A／B／C 同鍵
    return [cand("B", 0.99, KEY, "dB", 1, OLD, state="已被取代", valid_from="2023-05-01"),
            cand("A", 0.95, KEY, "dA", 1, FUTURE, state="有效", valid_from="2027-01-01"),
            cand("C", 0.90, KEY, "dC", 1, NEW, state="有效", valid_from="2025-12-09"),
            cand("D", 0.80, ("舊資料主體", "RELATED_TO", "舊資料受詞"), "dD", 1, None),
            cand("E", 0.70, ("一般主體", "RELATED_TO", "一般受詞"), "dE", 1, GENERAL)]


def fixtures(results):
    return [next(c["_fixture"] for c in s2_candidates() if c["source_doc_id"] == r["source_doc_id"]) for r in results]


# ---- 純運算：先過濾後去重、截斷、欄位 -------------------------------------------------

@pytest.mark.parametrize("as_of,expected", [("2026-10-02", ["C", "D", "E"]), ("2024-01-01", ["B", "D", "E"]), ("2027-01-01", ["A", "D", "E"])])
def test_asof_filter_matches_report260_s2(as_of, expected):
    assert fixtures(aso.asof_filter(s2_candidates(), as_of, 20)) == expected


def test_result_fields_status_and_events_json_not_exposed():
    results = aso.asof_filter(s2_candidates(), "2026-10-02", 20)
    assert all(tuple(r) == aso.RESULT_FIELDS for r in results)
    assert [r["as_of_status"] for r in results] == ["replayed", "no_events", "replayed"]
    assert results[0]["law_id"] == "N1" and results[0]["article_no"] == "第 1 條" and results[0]["valid_from"] == "2025-12-09"
    assert all("lifecycle_events_json" not in r for r in results)


def test_top_k_truncation_and_custom_retrievable():
    assert fixtures(aso.asof_filter(s2_candidates(), "2026-10-02", 2)) == ["C", "D"]
    only_valid = frozenset({"有效"})  # 無事件（None）不在集合內 → D 被排除
    assert fixtures(aso.asof_filter(s2_candidates(), "2026-10-02", 20, only_valid)) == ["C", "E"]


def test_illegal_events_are_kept_but_flagged():
    illegal = events_json(ev(rl.EXTRACTED, "2020-01-01"), ev(rl.REPLACED, "2020-02-01"), ev(rl.VERIFIED, "2020-03-01"))
    results = aso.asof_filter([cand("X", 0.9, KEY, "dX", 1, illegal)], "2026-10-02", 5)
    assert len(results) == 1 and results[0]["as_of_status"] == "illegal"


def test_same_article_multiple_facts_with_identical_events_are_fine():
    rows = [cand("1", 0.9, ("甲", "R", "乙"), "dA", 3, NEW), cand("2", 0.8, ("丙", "R", "丁"), "dA", 3, NEW),
            cand("3", 0.7, ("戊", "R", "己"), "dA", 3, events_json(*aso._helpers().parse_events(NEW)))]
    assert len(aso.asof_filter(rows, "2026-10-02", 20)) == 3
    assert aso.build_events_by_fact_id(rows) == {"dA#3": aso._helpers().parse_events(NEW)}


@pytest.mark.parametrize("other", [GENERAL, None, OLD])
def test_same_identity_with_different_events_raises(other):
    rows = [cand("1", 0.9, ("甲", "R", "乙"), "dA", 3, NEW), cand("2", 0.8, ("丙", "R", "丁"), "dA", 3, other)]
    with pytest.raises(aso.InconsistentEventsError, match="dA#3"):
        aso.asof_filter(rows, "2026-10-02", 20)


def test_input_validation():
    for bad in ("2026/10/02", "", None, "2026-1-2"):
        with pytest.raises(ValueError):
            aso.validate_as_of(bad)
    with pytest.raises(ValueError):
        aso.asof_filter(s2_candidates(), "bad", 5)


# ---- 假 driver：asof／naive 路徑 --------------------------------------------------

class FakeDriver:
    def __init__(self, candidates, attribution=None):
        self.candidates, self.attribution = candidates, attribution or {}
        self.calls: list[tuple[str, dict]] = []

    async def execute_query(self, statement, **params):
        self.calls.append((statement, params))
        if "db.index.vector.queryNodes" in statement:
            return SimpleNamespace(records=self.candidates)
        if "UNWIND $keys" in statement:
            rows = [{"source_doc_id": k["source_doc_id"], "chunk": k["chunk"], **self.attribution.get((k["source_doc_id"], k["chunk"]), {})}
                    for k in params["keys"]]
            return SimpleNamespace(records=rows)
        raise AssertionError(statement[:60])


@pytest.fixture()
def fake_svo(monkeypatch):
    calls = {"index": [], "naive": []}

    async def create_fact_vector_index(driver, kg_id, dim):
        calls["index"].append((kg_id, dim))

    async def vector_search_facts(driver, kg_id, query_vector, top_k, **kw):
        calls["naive"].append((kg_id, list(query_vector), top_k, kw))
        return [{"fact_text": "t", "subject": "甲", "verb": "v", "object": "乙", "rel_type": "R", "score": 0.9, "lifecycle_state": None,
                 "source_doc_id": "dX", "source_svo_chunk_index": 2, "confidence": 1}]

    svo = SimpleNamespace(create_fact_vector_index=create_fact_vector_index, vector_search_facts=vector_search_facts,
                          _fact_vector_index_name=lambda kg: f"fact_embedding_vector_{kg.replace('-', '_')}")
    monkeypatch.setattr(aso, "_svo", lambda: svo)
    monkeypatch.setattr(aso, "_candidate_multiplier", lambda: 4)
    return calls


def test_asof_mode_fetches_top_k_times_multiplier_candidates_and_filters(fake_svo):
    kg = uuid4()
    driver = FakeDriver(s2_candidates())
    results = asyncio.run(aso.asof_search(driver, kg, [0.1, 0.2], "2026-10-02", 3, mode="asof"))
    assert fixtures(results) == ["C", "D", "E"] and fake_svo["index"] == [(kg, 2)]
    statement, params = driver.calls[0]
    assert params["candidate_k"] == 12 and params["kg_id"] == str(kg) and params["vector"] == [0.1, 0.2]
    assert f"fact_embedding_vector_{str(kg).replace('-', '_')}" in statement and "__INDEX__" not in statement
    assert not fake_svo["naive"]


def test_naive_mode_calls_production_with_exact_signature_and_attributes(fake_svo):
    kg = uuid4()
    driver = FakeDriver([], attribution={("dX", 2): {"law_id": "N0030006", "article_no": "第 3 條", "valid_from": "2025-12-09"}})
    results = asyncio.run(aso.asof_search(driver, kg, [0.5, 0.5], "2026-10-02", 20, mode="naive"))
    assert fake_svo["naive"] == [(kg, [0.5, 0.5], 20, {})]  # 位置參數 (driver, kg_id, query_vector, top_k)，不帶額外選項
    assert [(r["law_id"], r["article_no"], r["valid_from"], r["as_of_status"]) for r in results] == [("N0030006", "第 3 條", "2025-12-09", None)]
    assert tuple(results[0]) == aso.RESULT_FIELDS and not fake_svo["index"]


def test_naive_attribution_for_unknown_fact_is_none(fake_svo):
    results = asyncio.run(aso.asof_search(FakeDriver([]), uuid4(), [0.1], "2026-10-02", 5, mode="naive"))
    assert results[0]["law_id"] is None and results[0]["article_no"] is None


def test_search_argument_validation(fake_svo):
    with pytest.raises(ValueError, match="mode"):
        asyncio.run(aso.asof_search(FakeDriver([]), uuid4(), [0.1], "2026-10-02", 5, mode="other"))
    with pytest.raises(ValueError):
        asyncio.run(aso.asof_search(FakeDriver([]), uuid4(), [0.1], "bad", 5))
    with pytest.raises(ValueError):
        asyncio.run(aso.asof_search(FakeDriver([]), uuid4(), [0.1], "2026-10-02", 0))


# ---- Cypher 結構 -----------------------------------------------------------------

def test_cypher_is_read_only_scoped_and_avoids_unknown_property_access():
    for statement in (aso.ASOF_CANDIDATES_CYPHER, aso.ATTRIBUTE_CYPHER):
        assert not re.search(r"\b(CREATE|MERGE|SET|DELETE|DETACH|REMOVE|DROP)\b", statement, re.I)
        assert "{kg_id: $kg_id}" in statement
    assert "node.lifecycle_state" not in aso.ASOF_CANDIDATES_CYPHER and "node.lifecycle_events_json" not in aso.ASOF_CANDIDATES_CYPHER
    assert "properties(node)['lifecycle_state']" in aso.ASOF_CANDIDATES_CYPHER and "properties(node)['lifecycle_events_json']" in aso.ASOF_CANDIDATES_CYPHER
    assert "SUPPORTED_BY" in aso.ASOF_CANDIDATES_CYPHER and "__INDEX__" in aso.ASOF_CANDIDATES_CYPHER
    assert aso.ASOF_CANDIDATES_CYPHER.lstrip().startswith("CALL db.index.vector.queryNodes")


# ---- CLI、閘門、離線 -----------------------------------------------------------------

def _row(article, content, valid_from):
    return {"pcode": "N0030006", "law_name": "勞工請假規則", "article_no": article, "content": content, "version_date": valid_from,
            "valid_from": valid_from, "valid_to": None, "is_current": True, "valid_from_basis": "x", "version_id": f"v-{article}-{valid_from}",
            "content_hash": hashlib.sha1(content.encode()).hexdigest(), "retrieved_at": "2026-08-19T17:00:00+08:00", "source_url": "u"}


@pytest.fixture()
def corpus(tmp_path):
    built = builder.build_corpus({"moj_history_20260819T000000Z-history.json": [_row("1", "甲版本實質內容", "2020-01-01"), _row("1", "乙版本完全不同的內容", "2024-01-01")]})
    out = tmp_path / "kg-runtime-pilot" / str(builder.PILOT_KG_ID_DEFAULT)
    builder.write_corpus(built, out, FAKE_REPO)
    return out


def test_cli_without_execute_is_offline_plan_and_loads_nothing_heavy(corpus):
    code = ("import sys\n" f"sys.path.insert(0, {str(REPO)!r})\n" "from scripts.kg import pilot_asof_search as aso\n"
            f"rc = aso.main(['--query', '勞工請假', '--as-of', '2026-10-02', '--mode', 'asof', '--top-k', '20', '--corpus-dir', {str(corpus)!r}])\n"
            "print('RC', rc, [m for m in ('neo4j', 'core.config', 'services.svo_service', 'scripts.analysis.disposable_lifecycle_l2_validation') if m in sys.modules])\n")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8", cwd=str(corpus.parent))
    assert result.returncode == 0, result.stderr[-400:]
    assert result.stdout.strip().splitlines()[-1] == "RC 0 []"
    plan = json.loads(result.stdout[: result.stdout.rindex("RC 0")])
    assert plan["connects"] is False and plan["request"]["as_of"] == "2026-10-02"
    assert plan["request"]["candidate_k"] % 20 == 0 and plan["request"]["candidate_k"] >= 20  # top_k × 候選倍數


def test_cli_rejects_bad_as_of_offline(corpus):
    with pytest.raises(ValueError):
        aso.main(["--query", "q", "--as-of", "2026/10/02", "--corpus-dir", str(corpus)])


def _env(corpus, **override):
    env = {"NEO4J_URI": "bolt://localhost:28687", "NEO4J_USER": "neo4j", "NEO4J_PASSWORD": "S3cr3t-PW-xyz",
           "WORKSPACE_DIR": str(corpus.parent), "EMBEDDING_PROVIDER": "ollama"}
    env.update(override)
    return env


@pytest.mark.parametrize("override", [{"NEO4J_URI": "bolt://localhost:17990"}, {"NEO4J_URI": "bolt://kg2-neo4j:28687"}, {"NEO4J_URI": "bolt://localhost:27687"}])
def test_execute_refuses_protected_targets_without_echoing_password(corpus, monkeypatch, capsys, override):
    for key, value in _env(corpus, **override).items():
        monkeypatch.setenv(key, value)
    assert aso.main(["--query", "q", "--as-of", "2026-10-02", "--execute", "--corpus-dir", str(corpus)]) == 2
    captured = capsys.readouterr()
    assert "S3cr3t-PW-xyz" not in captured.out + captured.err and "停止" in captured.err


def test_execute_refuses_kg4_and_foreign_kg_id(corpus, monkeypatch):
    for key, value in _env(corpus).items():
        monkeypatch.setenv(key, value)
    for bad in (str(uuid4()), str(pi.KG4_ID)):
        assert aso.main(["--query", "q", "--as-of", "2026-10-02", "--execute", "--kg-id", bad, "--corpus-dir", str(corpus)]) == 2


def test_gates_reused_and_core_imported_only_after_gate():
    tree = ast.parse(SRC)
    assert "def validate_environment" not in SRC and "def validate_target_uri" not in SRC
    execute = ast.get_source_segment(SRC, next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "execute"))
    assert execute.index("pi.validate_environment(") < execute.index("from core.config import")
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    modules = [a.name for n in top if isinstance(n, ast.Import) for a in n.names] + [n.module or "" for n in top if isinstance(n, ast.ImportFrom)]
    assert not [m for m in modules if m.split(".")[0] in {"core", "neo4j", "httpx"} or m.startswith(("services.svo", "scripts.analysis"))]


def test_no_secrets_no_forbidden_resources_no_production_modification():
    tree = ast.parse(SRC)
    strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert all(not ("17990" in s and "://" in s) for s in strings)
    for needle in ("subprocess", "docker", "load_dotenv", "putenv", "environ.setdefault", ".write_text(", ".write_bytes("):
        assert needle not in SRC, needle
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print":
            segment = ast.get_source_segment(SRC, node)
            assert "PASSWORD" not in segment and "environ" not in segment
