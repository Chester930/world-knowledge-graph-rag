"""報告264 Q4-A：`scripts/kg/pilot_apply_versions.py` 的離線測試（純函式、假 driver、閘門重用、`--plan` 不連線）。"""

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
from scripts.kg import pilot_apply_versions as av
from scripts.kg import pilot_import as pi
from services import relation_lifecycle as rl

REPO = Path(pi._REPO)
SRC = Path(av.__file__).read_text(encoding="utf-8")
FAKE_REPO = [Path("/nonexistent-repo-root")]


def _row(article, content, valid_from, *, pcode="N0030006", law_name="勞工請假規則", content_hash=None):
    return {
        "pcode": pcode, "law_name": law_name, "article_no": article, "content": content, "version_date": valid_from,
        "valid_from": valid_from, "valid_to": None, "is_current": True, "valid_from_basis": "official_revision_or_current_date",
        "version_id": f"v-{pcode}-{article}-{valid_from}", "content_hash": content_hash or hashlib.sha1(content.encode("utf-8")).hexdigest(),
        "retrieved_at": "2026-08-19T17:00:00+08:00", "source_url": "https://example.test",
    }


def _manifest():
    files = {"moj_history_20260819T000000Z-history.json": [
        _row("1", "甲版本實質內容", "2020-01-01"), _row("1", "乙版本完全不同的內容", "2024-01-01"),
        _row("2", "同一字串內容", "2020-01-01", content_hash="same"), _row("2", "同一字串內容", "2024-01-01", content_hash="same"),
        _row("3", "排版 內容", "2020-01-01"), _row("3", "排版內容", "2024-01-01"),
    ]}
    return builder.build_corpus(files)["manifest"]


@pytest.fixture()
def manifest():
    return _manifest()


def _nodes(manifest, *, extra=()):
    nodes = [{"eid": f"A{i}", "source_doc_id": v["source_doc_id"], "article_no": v["law_article_no"]} for i, v in enumerate(manifest["versions"])]
    return nodes + list(extra)


# ---- 版本屬性、譜系、配對 --------------------------------------------------------

def test_version_properties_and_key(manifest):
    old = next(v for v in manifest["versions"] if v["article_no"] == "1" and v["valid_from"] == "2020-01-01")
    new = next(v for v in manifest["versions"] if v["article_no"] == "1" and v["valid_from"] == "2024-01-01")
    props = av.version_properties(old)
    assert props["law_id"] == "N0030006" and props["valid_to"] == "2024-01-01" and props["valid_to_original"] is None
    assert props["diff_to_next"] == "substantive" and props["diff_from_previous"] is None and props["is_conflict"] is False
    assert json.loads(props["pilot_roles_json"]) == ["substantive_old"]
    assert av.version_properties(new)["valid_to"] is None and av.version_properties(new)["diff_from_previous"] == "substantive"
    assert av.version_key(old) == (old["source_doc_id"], "第 1 條") and set(props) == {
        "law_id", "version_id", "valid_from", "valid_to", "valid_to_original", "diff_to_next", "diff_from_previous", "is_conflict", "pilot_roles_json"}


def test_pairs_cover_all_adjacent_kinds_with_effective_date(manifest):
    pairs, skipped = av.build_version_pairs(manifest)
    assert skipped == [] and len(pairs) == 3
    assert sorted(p["diff_class"] for p in pairs) == ["format_only", "same_hash", "substantive"]
    assert all(p["effective_date"] == "2024-01-01" and p["old"] != p["new"] for p in pairs)


def test_pair_skipped_when_next_version_not_in_manifest(manifest):
    trimmed = {**manifest, "versions": [v for v in manifest["versions"] if not (v["article_no"] == "1" and v["valid_from"] == "2024-01-01")]}
    pairs, skipped = av.build_version_pairs(trimmed)
    assert len(pairs) == 2 and skipped == [{"old": [trimmed["versions"][0]["source_doc_id"], "第 1 條"], "next_valid_from": "2024-01-01"}]


def test_match_is_exact_by_source_doc_id_and_law_article_no(manifest):
    # 他法同號條文（另一份 source_doc_id 的「第 1 條」）不得被誤配
    other_law = {"eid": "OTHER", "source_doc_id": str(uuid4()), "article_no": "第 1 條"}
    matched = av.match_law_articles(_nodes(manifest, extra=[other_law]), manifest["versions"])
    assert len(matched) == len(manifest["versions"]) and "OTHER" not in matched.values()


def test_match_failures_stop(manifest):
    nodes = _nodes(manifest)
    with pytest.raises(av.MatchError, match="缺少 1"):
        av.match_law_articles(nodes[1:], manifest["versions"])
    dup = {**nodes[0], "eid": "DUP"}
    with pytest.raises(av.MatchError, match="重複 1"):
        av.match_law_articles(nodes + [dup], manifest["versions"])
    wrong_no = [{**nodes[0], "article_no": "第 99 條"}, *nodes[1:]]
    with pytest.raises(av.MatchError):
        av.match_law_articles(wrong_no, manifest["versions"])


# ---- 事件計畫 -------------------------------------------------------------------

def _versions_by_eid(manifest):
    matched = av.match_law_articles(_nodes(manifest), manifest["versions"])
    return {matched[av.version_key(v)]: v for v in manifest["versions"]}, matched


def _facts(manifest, per_article=2, **fields):
    by_eid, _ = _versions_by_eid(manifest)
    return [{"eid": f"F{a}-{n}", "article_eid": a, "events_json": None, "state": None, **fields} for a in by_eid for n in range(per_article)]


def test_initial_events_use_valid_from_and_evidence(manifest):
    version = next(v for v in manifest["versions"] if v["valid_to_derived"] is None)
    events = av.initial_events(version)
    assert [e.event_type for e in events] == [rl.EXTRACTED, rl.VERIFIED]
    assert {e.effective_date for e in events} == {version["valid_from"]}
    assert {e.evidence_ref for e in events} == {f"LawArticle:{version['pcode']}:{version['law_article_no']}:{version['valid_from']}"}
    assert {e.reason for e in events} == {av.REASON_CREATED} and {e.trigger_kind for e in events} == {"事件"}


def test_plan_events_old_get_three_latest_two_and_second_run_is_noop(manifest):
    by_eid, _ = _versions_by_eid(manifest)
    facts = _facts(manifest)
    updates, stats = av.plan_fact_events(facts, by_eid)
    d = av._helpers()
    assert stats["facts"] == len(facts) == stats["updated"] and stats["unchanged"] == 0
    assert stats["initial_written"] == len(facts) and stats["superseded_appended"] == len(facts) // 2
    for update in updates:
        events = d.parse_events(update["events_json"])
        version = by_eid[next(f["article_eid"] for f in facts if f["eid"] == update["eid"])]
        if version["valid_to_derived"] is None:
            assert len(events) == 2 and update["state"] == "有效"
        else:
            assert len(events) == 3 and update["state"] == "已被取代"
            assert events[-1].event_type == rl.REPLACED and events[-1].effective_date == version["valid_to_derived"]
            assert events[-1].evidence_ref.endswith(f":{version['valid_to_derived']}")
        assert all(e.effective_date >= version["valid_from"] for e in events[:2]) and events[0].effective_date == version["valid_from"]
    applied = {u["eid"]: u for u in updates}
    second = [{**f, "events_json": applied[f["eid"]]["events_json"], "state": applied[f["eid"]]["state"]} for f in facts]
    updates2, stats2 = av.plan_fact_events(second, by_eid)
    assert updates2 == [] and stats2["superseded_appended"] == 0 and stats2["initial_written"] == 0
    assert stats2["unchanged"] == len(facts) and stats2["skipped_existing"] == len(facts) // 2


def test_plan_events_illegal_append_is_skipped_and_counted(manifest):
    by_eid, _ = _versions_by_eid(manifest)
    old_eid = next(e for e, v in by_eid.items() if v["valid_to_derived"] is not None)
    d = av._helpers()
    candidate_only = d.dump_events([rl.LifecycleEvent(rl.EXTRACTED, by_eid[old_eid]["valid_from"])])  # 候選不可直接被取代
    facts = [{"eid": "F1", "article_eid": old_eid, "events_json": candidate_only, "state": "候選"}]
    updates, stats = av.plan_fact_events(facts, by_eid)
    assert updates == [] and stats["skipped_illegal"] == 1 and stats["superseded_appended"] == 0 and stats["unchanged"] == 1


def test_plan_events_repairs_stale_cache_without_new_events(manifest):
    by_eid, _ = _versions_by_eid(manifest)
    latest_eid = next(e for e, v in by_eid.items() if v["valid_to_derived"] is None)
    d = av._helpers()
    events_json = d.dump_events(av.initial_events(by_eid[latest_eid]))
    updates, stats = av.plan_fact_events([{"eid": "F1", "article_eid": latest_eid, "events_json": events_json, "state": "候選"}], by_eid)
    assert [u["state"] for u in updates] == ["有效"] and stats["updated"] == 1 and stats["initial_written"] == 0


# ---- 事後稽核 -------------------------------------------------------------------

def _applied_facts(manifest):
    by_eid, _ = _versions_by_eid(manifest)
    facts = _facts(manifest)
    updates, _ = av.plan_fact_events(facts, by_eid)
    applied = {u["eid"]: u for u in updates}
    return by_eid, [{**f, "events_json": applied[f["eid"]]["events_json"], "state": applied[f["eid"]]["state"]} for f in facts]


def test_audit_ok_and_detects_drift_missing_events_and_wrong_state(manifest):
    by_eid, facts = _applied_facts(manifest)
    ok = av.audit_facts(facts, by_eid)
    assert ok["ok"] and ok["drift"] == [] and ok["facts_without_events"] == 0 and ok["expectation_violations"] == []
    assert ok["state_counts"] == {"已被取代": len(facts) // 2, "有效": len(facts) // 2}
    drifted = [{**facts[0], "state": "爭議"}, *facts[1:]]
    result = av.audit_facts(drifted, by_eid)
    assert not result["ok"] and result["drift"] == [facts[0]["eid"]] and result["expectation_violations"]
    assert av.audit_facts([{**facts[0], "events_json": None, "state": None}], by_eid)["facts_without_events"] == 1
    latest = next(f for f in facts if by_eid[f["article_eid"]]["valid_to_derived"] is None)
    d = av._helpers()
    wrong = {**latest, "events_json": d.dump_events([rl.LifecycleEvent(rl.EXTRACTED, "2020-01-01")]), "state": "候選"}
    assert av.audit_facts([wrong], by_eid)["expectation_violations"][0]["expected"] == "有效"


# ---- 假 driver 端對端與冪等 ----------------------------------------------------------

class FakeNeo:
    def __init__(self, manifest, per_article=2, wrong_count=None):
        self.nodes = _nodes(manifest)
        self.props, self.rels, self.wrong_count = {}, {}, wrong_count
        by_eid, _ = _versions_by_eid(manifest)
        self.facts = {f"F{a}-{n}": {"article_eid": a, "events_json": None, "state": None} for a in by_eid for n in range(per_article)}
        self.statements: list[str] = []

    async def execute_query(self, statement, **params):
        self.statements.append(statement)
        assert params["kg_id"]
        if statement == av.LAW_ARTICLE_NODES_CYPHER:
            return SimpleNamespace(records=self.nodes)
        if statement == av.WRITE_VERSION_PROPS_CYPHER:
            for row in params["rows"]:
                self.props[row["eid"]] = row
            return SimpleNamespace(records=[{"updated": self.wrong_count if self.wrong_count is not None else len(params["rows"])}])
        if statement == av.WRITE_SUPERSEDED_BY_CYPHER:
            for pair in params["pairs"]:
                self.rels[(pair["old"], pair["new"])] = pair
            return SimpleNamespace(records=[{"merged": len(params["pairs"])}])
        if statement == av.SUPPORTED_FACTS_CYPHER:
            return SimpleNamespace(records=[{"eid": e, **f} for e, f in self.facts.items()])
        if statement == av.WRITE_FACT_EVENTS_CYPHER:
            for update in params["updates"]:
                self.facts[update["eid"]].update(events_json=update["events_json"], state=update["state"])
            return SimpleNamespace(records=[{"updated": len(params["updates"])}])
        raise AssertionError(f"未預期的語句：{statement[:60]}")


def test_apply_versions_end_to_end_is_idempotent(manifest):
    neo = FakeNeo(manifest)
    first = asyncio.run(av.apply_versions(neo, uuid4(), manifest))
    assert first["version_properties_written"] == 6 and first["superseded_by_merged"] == 3 and first["pairs_skipped"] == 0
    assert first["event_stats"]["updated"] == len(neo.facts) and first["audit"]["ok"]
    assert len(neo.rels) == 3 and all(r["diff_class"] in {"substantive", "same_hash", "format_only"} for r in neo.rels.values())
    snapshot = json.dumps(neo.facts, sort_keys=True)
    second = asyncio.run(av.apply_versions(neo, uuid4(), manifest))
    assert second["event_stats"]["updated"] == 0 and second["event_stats"]["superseded_appended"] == 0
    assert second["event_stats"]["initial_written"] == 0 and second["audit"]["ok"] and len(neo.rels) == 3
    assert json.dumps(neo.facts, sort_keys=True) == snapshot
    assert not any(re.search(r"\b(DELETE|DETACH|REMOVE)\b", s) for s in neo.statements)


def test_apply_versions_stops_on_unmatched_article_and_on_count_mismatch(manifest):
    neo = FakeNeo(manifest)
    neo.nodes = neo.nodes[1:]
    with pytest.raises(av.MatchError):
        asyncio.run(av.apply_versions(neo, uuid4(), manifest))
    assert av.WRITE_VERSION_PROPS_CYPHER not in neo.statements  # 配對失敗時不寫入任何東西
    with pytest.raises(RuntimeError, match="寫入筆數不符"):
        asyncio.run(av.apply_versions(FakeNeo(manifest, wrong_count=0), uuid4(), manifest))


# ---- --plan 與閘門重用 ---------------------------------------------------------------

@pytest.fixture()
def corpus(tmp_path):
    files = {"moj_history_20260819T000000Z-history.json": [_row("1", "甲版本實質內容", "2020-01-01"), _row("1", "乙版本完全不同的內容", "2024-01-01")]}
    built = builder.build_corpus(files)
    out = tmp_path / "kg-runtime-pilot" / str(builder.PILOT_KG_ID_DEFAULT)
    builder.write_corpus(built, out, FAKE_REPO)
    return out


def test_plan_counts_and_no_connection(corpus):
    plan = av.build_plan(corpus)
    assert plan["connects"] is False and plan["counts"]["version_property_rows"] == 2 and plan["counts"]["superseded_by_relations"] == 1
    assert plan["counts"]["old_versions"] == 1 and plan["counts"]["latest_versions"] == 1
    assert plan["events"]["lower_bound_if_each_article_has_one_fact"] == 2 * 1 + 3 * 1 and plan["events"]["second_run_expected_appended"] == 0
    assert [s["n"] for s in plan["steps"]] == [1, 2, 3, 4, 5, 6] and av.build_plan(corpus) == plan
    code = ("import sys\n" f"sys.path.insert(0, {str(REPO)!r})\n" "from scripts.kg import pilot_apply_versions as av\n"
            f"rc = av.main(['--plan', '--corpus-dir', {str(corpus)!r}])\n"
            "print('RC', rc, [m for m in ('neo4j', 'core.config', 'services.svo_service', 'scripts.analysis.disposable_lifecycle_l2_validation') if m in sys.modules])\n")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8", cwd=str(corpus.parent))
    assert result.returncode == 0, result.stderr[-400:]
    assert result.stdout.strip().splitlines()[-1] == "RC 0 []"


def _env(corpus, **override):
    env = {"NEO4J_URI": "bolt://localhost:28687", "NEO4J_USER": "neo4j", "NEO4J_PASSWORD": "S3cr3t-PW-xyz",
           "WORKSPACE_DIR": str(corpus.parent), "EMBEDDING_PROVIDER": "ollama"}
    env.update(override)
    return env


@pytest.mark.parametrize("override", [{"NEO4J_URI": "bolt://localhost:17990"}, {"NEO4J_URI": "bolt://kg2-neo4j:28687"},
                                      {"NEO4J_URI": "bolt://localhost:27687"}, {"NEO4J_URI": "bolt://localhost:7687"}])
def test_execute_refuses_protected_targets_without_echoing_password(corpus, monkeypatch, capsys, override):
    for key, value in _env(corpus, **override).items():
        monkeypatch.setenv(key, value)
    assert av.main(["--execute", "--corpus-dir", str(corpus)]) == 2
    captured = capsys.readouterr()
    assert "S3cr3t-PW-xyz" not in captured.out + captured.err and "停止" in captured.err


def test_execute_refuses_wrong_kg_id(corpus, monkeypatch, capsys):
    for key, value in _env(corpus).items():
        monkeypatch.setenv(key, value)
    assert av.main(["--execute", "--corpus-dir", str(corpus), "--kg-id", str(uuid4())]) == 2
    assert av.main(["--execute", "--corpus-dir", str(corpus), "--kg-id", str(pi.KG4_ID)]) == 2


def test_gates_are_reused_from_pilot_import_not_reimplemented():
    tree = ast.parse(SRC)
    assert "def validate_environment" not in SRC and "def validate_target_uri" not in SRC and "def validate_kg_id" not in SRC
    calls = [ast.get_source_segment(SRC, n) for n in ast.walk(tree) if isinstance(n, ast.Call)]
    assert any(c.startswith("pi.validate_environment(") for c in calls) and any(c.startswith("pi.validate_target_uri(") for c in calls)
    execute = ast.get_source_segment(SRC, next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "execute"))
    assert execute.index("pi.validate_environment(") < execute.index("from core.config import")


# ---- 結構守衛 -------------------------------------------------------------------

def test_cypher_is_scoped_and_never_deletes():
    statements = [av.LAW_ARTICLE_NODES_CYPHER, av.WRITE_VERSION_PROPS_CYPHER, av.WRITE_SUPERSEDED_BY_CYPHER,
                  av.SUPPORTED_FACTS_CYPHER, av.WRITE_FACT_EVENTS_CYPHER]
    for statement in statements:
        assert "$kg_id" in statement and "{kg_id: $kg_id}" in statement
        assert not re.search(r"\b(DELETE|DETACH|REMOVE|DROP)\b", statement, re.I)
    assert re.findall(r"SET\s+(.+?)(?:\n|$)", av.WRITE_FACT_EVENTS_CYPHER) == ["f.lifecycle_events_json = update.events_json, f.lifecycle_state = update.state"]
    assert "MERGE (old)-[r:SUPERSEDED_BY]->(new)" in av.WRITE_SUPERSEDED_BY_CYPHER and "MERGE" not in av.WRITE_VERSION_PROPS_CYPHER
    assert "law_id" not in av.LAW_ARTICLE_NODES_CYPHER  # 配對只用 source_doc_id＋article_no，不用法規或版本屬性


def test_top_level_imports_are_light_and_no_secrets_or_forbidden_resources():
    tree = ast.parse(SRC)
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    modules = [a.name for n in top if isinstance(n, ast.Import) for a in n.names] + [n.module or "" for n in top if isinstance(n, ast.ImportFrom)]
    assert not [m for m in modules if m.split(".")[0] in {"core", "neo4j", "httpx"} or m.startswith(("services.svo", "scripts.analysis"))]
    strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert all(not ("17990" in s and "://" in s) for s in strings)
    for needle in ("subprocess", "docker", "load_dotenv", "putenv", "environ.setdefault"):
        assert needle not in SRC, needle
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print":
            segment = ast.get_source_segment(SRC, node)
            assert "PASSWORD" not in segment and "environ" not in segment
