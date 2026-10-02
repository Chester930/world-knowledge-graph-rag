"""services/fact_flat_resync.py 單元測試（報告250 R2/R3）：假 driver，不連任何 Neo4j／docker。"""
from __future__ import annotations

import ast
import asyncio
import copy
import re
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from services import fact_flat_resync as mod
from services.fact_flat_resync import (
    SYNC_ATTRIBUTES,
    _apply_updates,
    _plan_resync_updates,
    resync_fact_flat_properties,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "fact_flat_resync.py"
WRITE_RE = re.compile(r"\b(SET|CREATE|MERGE|DELETE|REMOVE)\b", re.IGNORECASE)


def _row(**overrides):
    row = {
        "eid": "e1",
        "flat_subject": "A", "flat_object": "B", "flat_rel_type": "R",
        "subject_exists": True, "object_exists": True,
        "subject_name": "A", "object_name": "B",
        "edge_count": 0, "edge_types": [],
    }
    row.update(overrides)
    return row


class FakeDriver:
    def __init__(self, rows=None, write_counts=None):
        self.rows = rows or []
        self.write_counts = write_counts  # None → 回報與請求筆數相同
        self.calls: list[tuple[str, dict]] = []

    async def execute_query(self, statement, **params):
        self.calls.append((statement, params))
        if "RETURN elementId(f) AS eid" in statement:
            return SimpleNamespace(records=list(self.rows))
        n = len(params["updates"]) if self.write_counts is None else self.write_counts
        return SimpleNamespace(records=[{"updated": n}])


def run(coro):
    return asyncio.run(coro)


# ---- A. 純計畫函式 -------------------------------------------------------

@pytest.mark.parametrize(
    "row,stats_delta,upd",
    [
        (_row(subject_name="A2"), {"subject_changed": 1}, {"subject": [{"eid": "e1", "value": "A2"}]}),
        (_row(object_name="B2"), {"object_changed": 1}, {"object": [{"eid": "e1", "value": "B2"}]}),
        (_row(subject_name="A2", object_name="B2"), {"subject_changed": 1, "object_changed": 1},
         {"subject": [{"eid": "e1", "value": "A2"}], "object": [{"eid": "e1", "value": "B2"}]}),
        (_row(), {"unchanged": 1}, {}),
        (_row(subject_name=None, object_name=None), {"unchanged": 1}, {}),
        (_row(subject_exists=False, subject_name="A2"), {"facts_without_links": 1}, {}),
        (_row(object_exists=False, object_name="B2"), {"facts_without_links": 1}, {}),
    ],
)
def test_plan_subject_object(row, stats_delta, upd):
    stats, updates = _plan_resync_updates([row], sync_rel_type=False)
    expected = mod._new_stats()
    expected.update(stats_delta)
    assert stats == expected
    assert updates == {"subject": [], "object": [], "rel_type": [], **upd}


def test_plan_rel_type_off_ignores_edges():
    stats, updates = _plan_resync_updates(
        [_row(edge_count=1, edge_types=["X"], flat_rel_type="R")], sync_rel_type=False
    )
    assert updates["rel_type"] == []
    assert stats["rel_type_changed"] == stats["rel_type_skipped_multi_edge"] == stats["rel_type_skipped_no_edge"] == 0


@pytest.mark.parametrize(
    "row,key,rel_updates",
    [
        (_row(edge_count=1, edge_types=["X"]), "rel_type_changed", [{"eid": "e1", "value": "X"}]),
        (_row(edge_count=1, edge_types=["R"]), "unchanged", []),
        (_row(edge_count=2, edge_types=["R", "X"]), "rel_type_skipped_multi_edge", []),
        (_row(edge_count=0, edge_types=[]), "rel_type_skipped_no_edge", []),
        # 現行行為鎖定：邊數 1 但型別為空／多種 → 落入 else，計為 skipped_no_edge
        (_row(edge_count=1, edge_types=[]), "rel_type_skipped_no_edge", []),
        (_row(edge_count=1, edge_types=["X", "Y"]), "rel_type_skipped_no_edge", []),
        # None 視為 0／空
        (_row(edge_count=None, edge_types=None), "rel_type_skipped_no_edge", []),
    ],
)
def test_plan_rel_type_on(row, key, rel_updates):
    stats, updates = _plan_resync_updates([row], sync_rel_type=True)
    assert stats[key] == 1
    assert updates["rel_type"] == rel_updates


def test_plan_no_updates_when_links_missing_even_with_rel_type():
    stats, updates = _plan_resync_updates(
        [_row(subject_exists=False, subject_name="Z", edge_count=1, edge_types=["X"])], sync_rel_type=True
    )
    assert stats["facts_without_links"] == 1
    assert all(v == [] for v in updates.values())


def test_plan_idempotent():
    rows = [
        _row(eid="a", subject_name="A2", object_name="B2", edge_count=1, edge_types=["X"]),
        _row(eid="b", subject_name="C", flat_subject="C0", edge_count=1, edge_types=["R"]),
    ]
    _, updates = _plan_resync_updates(rows, sync_rel_type=True)
    applied = copy.deepcopy(rows)
    by_eid = {r["eid"]: r for r in applied}
    for attr, flat in (("subject", "flat_subject"), ("object", "flat_object"), ("rel_type", "flat_rel_type")):
        for u in updates[attr]:
            by_eid[u["eid"]][flat] = u["value"]
    stats, _ = _plan_resync_updates(applied, sync_rel_type=True)
    assert stats["subject_changed"] == stats["object_changed"] == stats["rel_type_changed"] == 0


# ---- B. 主函式（假 driver） ----------------------------------------------

def test_dry_run_default_sends_no_write_statements():
    kg = uuid4()
    driver = FakeDriver([_row(subject_name="A2", object_name="B2")])
    stats = run(resync_fact_flat_properties(driver, kg))
    assert stats["subject_changed"] == 1 and stats["object_changed"] == 1
    assert driver.calls
    for statement, _ in driver.calls:
        assert not WRITE_RE.search(statement), statement


def test_dry_run_with_rel_type_still_read_only():
    driver = FakeDriver([_row(edge_count=1, edge_types=["X"])])
    stats = run(resync_fact_flat_properties(driver, uuid4(), sync_rel_type=True))
    assert stats["rel_type_changed"] == 1
    assert len(driver.calls) == 1 and not WRITE_RE.search(driver.calls[0][0])


def test_apply_writes_only_changed_attributes_with_whitelist_set():
    kg = uuid4()
    driver = FakeDriver([_row(subject_name="A2")])
    run(resync_fact_flat_properties(driver, kg, dry_run=False))
    writes = [c for c in driver.calls if WRITE_RE.search(c[0])]
    assert len(writes) == 1
    sets = re.findall(r"SET\s+f\.(\w+)", writes[0][0])
    assert sets == ["subject"]


def test_apply_all_three_attributes():
    driver = FakeDriver([_row(subject_name="A2", object_name="B2", edge_count=1, edge_types=["X"])])
    run(resync_fact_flat_properties(driver, uuid4(), dry_run=False, sync_rel_type=True))
    writes = [c for c in driver.calls if WRITE_RE.search(c[0])]
    sets = [re.findall(r"SET\s+f\.(\w+)", w[0])[0] for w in writes]
    assert sorted(sets) == sorted(SYNC_ATTRIBUTES)


def test_apply_no_changes_zero_writes():
    driver = FakeDriver([_row()])
    run(resync_fact_flat_properties(driver, uuid4(), dry_run=False))
    assert not [c for c in driver.calls if WRITE_RE.search(c[0])]


def test_apply_count_mismatch_raises():
    driver = FakeDriver([_row(subject_name="A2")], write_counts=0)
    with pytest.raises(RuntimeError):
        run(resync_fact_flat_properties(driver, uuid4(), dry_run=False))


@pytest.mark.parametrize("bad", ["fact_text", "name) DETACH DELETE (n"])
def test_apply_rejects_non_whitelisted_attribute(bad):
    driver = FakeDriver()
    updates = {"subject": [{"eid": "e1", "value": "x"}], bad: [{"eid": "e1", "value": "x"}]}
    with pytest.raises(ValueError):
        run(_apply_updates(driver, uuid4(), updates))
    assert driver.calls == []


def test_every_statement_scoped_by_string_kg_id():
    kg = uuid4()
    driver = FakeDriver([_row(subject_name="A2", object_name="B2", edge_count=1, edge_types=["X"])])
    run(resync_fact_flat_properties(driver, kg, dry_run=False, sync_rel_type=True))
    for statement, params in driver.calls:
        assert params["kg_id"] == str(kg)
        assert "{kg_id: $kg_id}" in statement


# ---- C. 結構守衛 ---------------------------------------------------------

def _source() -> str:
    return MODULE_PATH.read_text(encoding="utf-8")


def test_no_connection_or_env_imports():
    tree = ast.parse(_source())
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    banned = ("core", "dotenv", "os", "neo4j")
    assert not [m for m in imported if m.split(".")[0] in banned], imported
    assert "environ" not in _source() and "getenv" not in _source()


def test_zero_wiring():
    skip = {"tests", "docs", ".claude", ".git", "__pycache__", "node_modules", ".venv", "venv"}
    hits = []
    for path in REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT)
        if skip & set(rel.parts) or any(p.startswith(".pytest-tmp") for p in rel.parts):
            continue
        if path == MODULE_PATH:
            continue
        if "fact_flat_resync" in path.read_text(encoding="utf-8", errors="ignore"):
            hits.append(str(rel))
    assert hits == []


def test_no_connection_strings_or_secrets():
    src = _source()
    for needle in ("17990", "bolt://", "neo4j://", "password", "PASSWORD"):
        assert needle not in src
    assert not re.search(r"[A-Za-z0-9_\-]{43}", src)


def test_cypher_only_sets_whitelisted_and_protected_fields_not_in_cypher():
    tree = ast.parse(_source())
    cypher_strings = []
    fragments = {id(v) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) for v in n.values}
    for node in ast.walk(tree):
        if id(node) in fragments:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "MATCH" in node.value:
            cypher_strings.append(node.value)
        if isinstance(node, ast.JoinedStr):
            text = "".join(
                v.value if isinstance(v, ast.Constant) else "{" + ast.unparse(v.value) + "}"
                for v in node.values
            )
            if "MATCH" in text:
                cypher_strings.append(text)
    assert cypher_strings
    for text in cypher_strings:
        for field in ("fact_text", "fact_embedding", "natural_text", "verb_embedding"):
            assert field not in text
        for target in re.findall(r"SET\s+(\S+)", text):
            assert target in ("f.{attribute}",), target
    # 每個含 MATCH (f:Fact 的語句都帶 kg_id 範圍
    assert all("{{kg_id: $kg_id}}" in t or "{kg_id: $kg_id}" in t for t in cypher_strings if "(f:Fact" in t)
