"""報告235 P2：條文版本→狀態機事件的純運算原型測試。"""

import ast
import copy
import json
from pathlib import Path

from services import relation_lifecycle as rl
from services.law_version_events import (
    DIFF_FORMAT_ONLY,
    DIFF_SUBSTANTIVE,
    build_version_chains,
    build_version_event_prototype,
    classify_content_difference,
)

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "tests" / "fixtures" / "law_version_real_sample.json"
_SRC = _ROOT / "services" / "law_version_events.py"


def _fixture_records():
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))["records"]


def _row(article, version, *, content="正文", start="2020-01-01", end=None, current=True):
    return {
        "pcode": "T0000001", "article_no": str(article), "content": content,
        "content_hash": version, "valid_from": start, "valid_to": end,
        "is_current": current, "version_id": version,
    }


def _chain(result, pcode, article):
    return next(c for c in result["chains"] if c["pcode"] == pcode and c["article_no"] == str(article))


def test_real_fixture_has_required_cases_and_final_states():
    result = build_version_event_prototype(_fixture_records())
    assert result["counts"] == {
        "chains": 6, "versions": 12, "events": 30,
        "chains_with_anomalies": 6, "exclusivity_violation_count": 0,
    }
    for chain in result["chains"]:
        assert [version["final_state"] for version in chain["versions"]] == [rl.SUPERSEDED, rl.VALID]
        assert all(version["ok"] for version in chain["versions"])
        assert all("官方來源" in event["reason"] for version in chain["versions"] for event in version["events"] if event["reason"])


def test_real_cases_include_required_amendments_and_shared_difference_rules():
    result = build_version_event_prototype(_fixture_records())
    for article in (7, 9, 12):
        version = _chain(result, "N0030006", article)["versions"][0]
        replacement = version["events"][-1]
        assert replacement["event_type"] == rl.REPLACED
        assert replacement["effective_date"] == "2025-12-09"
        assert "文字不同" in replacement["reason"]
    assert "僅排版" in _chain(result, "N0030001", 8)["versions"][0]["events"][-1]["reason"]
    assert "文字不同" in _chain(result, "N0030001", 2)["versions"][0]["events"][-1]["reason"]
    assert classify_content_difference(
        {"content": "甲　乙 ::: 最新訊息 導覽", "content_hash": "a"},
        {"content": "甲乙", "content_hash": "b"},
    ) == DIFF_FORMAT_ONLY
    assert any("文字不同" in event["reason"] for chain in result["chains"] for version in chain["versions"] for event in version["events"] if event["event_type"] == rl.REPLACED)


def test_single_two_three_versions_and_date_gap_are_deterministic():
    records = [
        _row("1", "a", start="2020-01-01", end="2020-01-01", current=False),
        _row("1", "b", content="改版", start="2020-01-02", end="2020-01-02", current=False),
        _row("1", "c", content="再改版", start="2020-01-04", current=True),
        _row("2", "single", start="2020-01-01", current=True),
    ]
    before = copy.deepcopy(records)
    first = build_version_event_prototype(records)
    second = build_version_event_prototype(records)
    assert first == second and records == before
    chain = _chain(first, "T0000001", 1)
    assert [v["final_state"] for v in chain["versions"]] == [rl.SUPERSEDED, rl.SUPERSEDED, rl.VALID]
    assert any(a["kind"] == "date_not_contiguous" and a["delta_days"] == 2 for a in chain["anomalies"])
    assert _chain(first, "T0000001", 2)["versions"][0]["final_state"] == rl.VALID


def test_current_and_valid_to_anomalies_are_reported_not_repaired():
    records = [
        _row("1", "a", start="2020-01-01", end="2020-01-01", current=True),
        _row("1", "b", start="2020-01-02", current=True),
    ]
    result = build_version_event_prototype(records)
    chain = _chain(result, "T0000001", 1)
    kinds = [item["kind"] for item in chain["anomalies"]]
    assert "current_count" in kinds and "is_current_valid_to_mismatch" in kinds
    assert [v["final_state"] for v in chain["versions"]] == [rl.SUPERSEDED, rl.VALID]
    assert result["exclusivity_violations"] == []


def test_chain_sorting_is_by_pcode_article_and_valid_from():
    rows = [_row("2", "b", start="2020-01-02"), _row("1", "a"), _row("2", "a", start="2020-01-01")]
    chains = build_version_chains(rows)
    assert [(c[0]["pcode"], c[0]["article_no"]) for c in chains] == [("T0000001", "1"), ("T0000001", "2")]
    assert [r["version_id"] for r in chains[1]] == ["a", "b"]


def test_module_is_pure_and_has_no_io_or_environment_access():
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "open" not in names and not attrs & {"read_text", "write_text", "environ", "getenv", "now", "today"}
