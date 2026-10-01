"""報告235 P2：條文版本→狀態機事件的純運算原型測試。"""

import ast
import copy
import hashlib
import json
from pathlib import Path

from services import relation_lifecycle as rl
from services.law_version_events import (
    DIFF_FORMAT_ONLY,
    DIFF_SUBSTANTIVE,
    build_version_chains,
    build_version_event_prototype,
    classify_content_difference,
    strip_navigation_noise,
)

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "tests" / "fixtures" / "law_version_real_sample.json"
_SRC = _ROOT / "services" / "law_version_events.py"


def _fixture_records():
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))["records"]


def _row(article, version, *, content="正文", start="2020-01-01", end=None, current=True, retrieved_at=None):
    return {
        "pcode": "T0000001", "article_no": str(article), "content": content,
        "content_hash": version, "valid_from": start, "valid_to": end,
        "is_current": current, "version_id": version, "retrieved_at": retrieved_at,
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
    assert result["snapshot_collapses"] == []
    assert result["snapshot_field_conflicts"] == []


def test_real_fixture_is_complete_and_self_consistent():
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert payload["source_record_count"] == 209
    assert payload["source_sha256"] == "3a8aceb9c176fb98ea6cc5cacbba0843daa46385ce08d30b538de62448129d40"
    assert len(payload["records"]) == 12
    expected_fields = {
        "pcode", "law_name", "category", "article_no", "content", "version_date", "source_url",
        "valid_from", "valid_to", "is_current", "valid_from_basis", "version_id", "content_hash", "retrieved_at",
    }
    assert all(set(record) == expected_fields for record in payload["records"])
    for record in payload["records"]:
        content_hash = hashlib.sha256(record["content"].encode("utf-8")).hexdigest()
        version_key = f"{record['pcode']}|{record['article_no']}|{record['valid_from']}|{record['content_hash']}"
        version_id = hashlib.sha256(version_key.encode("utf-8")).hexdigest()
        assert record["content_hash"] == content_hash
        assert record["version_id"] == version_id
    assert all(record["law_name"].endswith(" EN") for record in payload["records"] if record["is_current"])
    assert all("::: 最新訊息" in record["content"] for record in payload["records"] if record["article_no"] == "12")


def test_navigation_noise_rule_uses_synthetic_material_only():
    synthetic = "正文 ::: 最新訊息 合成導覽文字"
    assert strip_navigation_noise(synthetic) == "正文 "


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
    assert result["current_flag_anomalies"]["before_collapse_multiple_current"][0]["count"] == 2
    assert result["current_flag_anomalies"]["after_collapse_multiple_current"][0]["count"] == 2


def test_snapshot_duplicates_collapse_by_normalized_content_and_latest_retrieved_at():
    records = [
        _row("1", "old-snapshot", content="甲 ::: 最新訊息 導覽", end="2020-01-01", current=False, retrieved_at="2026-01-01T00:00:00+08:00"),
        _row("1", "new-snapshot", content="甲", current=True, retrieved_at="2026-02-01T00:00:00+08:00"),
    ]
    result = build_version_event_prototype(records)
    chain = _chain(result, "T0000001", 1)
    assert chain["version_count"] == 1
    assert chain["versions"][0]["version_id"] == "new-snapshot"
    assert result["snapshot_collapses"][0]["representative_selection"] == "retrieved_at_max"
    assert result["snapshot_collapses"][0]["collapsed_version_ids"] == ["old-snapshot"]
    assert result["snapshot_field_conflicts"][0]["fields"]["valid_to"]


def test_current_summary_does_not_count_same_version_id_snapshot_rows_twice():
    records = [
        _row("1", "same-version", content="甲", current=True, retrieved_at="2026-01-01T00:00:00+08:00"),
        _row("1", "same-version", content="甲", current=True, retrieved_at="2026-02-01T00:00:00+08:00"),
    ]
    result = build_version_event_prototype(records)
    assert result["current_flag_anomalies"]["before_collapse_multiple_current"] == []
    assert result["current_flag_anomalies"]["after_collapse_multiple_current"] == []


def test_snapshot_without_retrieved_at_uses_input_order_last():
    records = [
        _row("1", "first", current=False),
        _row("1", "last", current=True),
    ]
    result = build_version_event_prototype(records)
    assert result["snapshot_collapses"][0]["representative_version_id"] == "last"
    assert result["snapshot_collapses"][0]["representative_selection"] == "input_order_last"


def test_same_valid_from_different_content_is_retained_and_reported():
    records = [
        _row("1", "a", content="甲", current=True),
        _row("1", "b", content="乙", current=True),
    ]
    result = build_version_event_prototype(records)
    chain = _chain(result, "T0000001", 1)
    assert chain["version_count"] == 2
    assert any(item["kind"] == "same_valid_from_different_content" for item in chain["anomalies"])
    assert result["current_flag_anomalies"]["before_collapse_multiple_current"][0]["count"] == 2
    assert result["current_flag_anomalies"]["after_collapse_multiple_current"][0]["count"] == 2
    assert result["exclusivity_violations"] == []


def test_after_collapse_zero_current_is_reported_separately():
    records = [
        _row("1", "a", start="2020-01-01", current=False),
        _row("1", "b", start="2020-01-02", current=False),
    ]
    result = build_version_event_prototype(records)
    assert result["current_flag_anomalies"]["after_collapse_zero_current"][0]["article_no"] == "1"


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
