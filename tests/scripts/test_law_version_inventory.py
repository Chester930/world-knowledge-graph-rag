"""報告235 P1：條文版本盤點的純函式與檔案邊界測試。"""

from pathlib import Path

import pytest

from scripts.analysis import law_version_inventory as inv
from services.law_version_events import (
    DIFF_FORMAT_ONLY,
    DIFF_SAME_HASH,
    DIFF_SUBSTANTIVE,
    classify_content_difference,
    normalize_content,
)


def _row(
    article: str,
    version: str,
    *,
    content: str = "正文",
    content_hash: str | None = None,
    valid_from: str = "2023-01-01",
    valid_to: str | None = None,
    current: bool = True,
) -> dict[str, object]:
    return {
        "pcode": "T0000001", "law_name": "測試法", "article_no": article, "content": content,
        "version_date": valid_from, "valid_from": valid_from, "valid_to": valid_to,
        "is_current": current, "valid_from_basis": "測試", "version_id": version,
        "content_hash": content_hash or version, "retrieved_at": "2026-01-01T00:00:00Z",
        "source_url": "https://example.invalid/law",
    }


def test_normalization_and_three_way_classification():
    same_left = _row("1", "a", content="甲", content_hash="same")
    same_right = _row("1", "b", content="甲\n", content_hash="same")
    format_left = _row("1", "c", content="甲　乙 ::: 最新訊息 導覽", content_hash="c")
    format_right = _row("1", "d", content="甲乙", content_hash="d")
    substantive = _row("1", "e", content="丙", content_hash="e")
    assert classify_content_difference(same_left, same_right) == DIFF_SAME_HASH
    assert classify_content_difference(format_left, format_right) == DIFF_FORMAT_ONLY
    assert classify_content_difference(format_right, substantive) == DIFF_SUBSTANTIVE
    assert normalize_content("Ａ　Ｂ\n") == "AB"


def test_dedup_uses_latest_snapshot_but_reports_conflict():
    old = _row("1", "v1", valid_from="2020-01-01", valid_to="2022-12-31", current=False)
    old_later_snapshot = dict(old, valid_to=None, is_current=True)
    new = _row("1", "v2", valid_from="2023-01-01")
    records, metadata = inv.deduplicate_records({"a.json": [old], "b.json": [old_later_snapshot, new]})
    assert len(records) == 2 and records[0]["version_id"] == "v1"
    assert records[0]["valid_to"] is None and records[0]["is_current"] is True
    assert metadata["key"] == "(pcode, article_no, version_id)"
    assert metadata["duplicate_group_count"] == 1
    assert metadata["conflicting_duplicate_group_count"] == 1
    assert metadata["duplicate_groups"][0]["canonical_file"] == "b.json"


def test_inventory_reports_chain_date_and_current_anomalies():
    rows = [
        _row("1", "v1", valid_from="2020-01-01", valid_to="2020-01-01", current=False),
        _row("1", "v2", valid_from="2020-01-03", current=True),  # gap of two days
        _row("2", "v3", valid_from="2020-01-01", valid_to="2020-01-01", current=True),  # mismatch
        _row("2", "v4", valid_from="2020-01-02", current=True),  # multiple current
    ]
    result = inv.build_inventory({"test.json": rows})
    assert result["version_chains"]["version_count_distribution"] == {"2": 2}
    assert result["date_continuity"]["non_contiguous_pairs"][0]["delta_days"] == 2
    assert result["current_consistency"]["mismatch_count"] == 1
    assert len(result["current_consistency"]["multi_version_with_multiple_current"]) == 1


def test_corpus_mapping_reads_only_original_md_and_matches_normalized_text(tmp_path: Path):
    law_dir = tmp_path / "T0000001_測試法"
    law_dir.mkdir()
    (law_dir / "original.md").write_text("# 測試\n甲　乙\n", encoding="utf-8")
    rows = [_row("1", "v1", content="甲乙")]
    result = inv.build_corpus_mapping(rows, tmp_path, sample_per_pcode=1)
    assert result["sample_size"] == 1 and result["matched_count"] == 1 and result["match_rate"] == 1
    assert result["folder_info"]["T0000001"]["original_md_exists"] is True


def test_load_history_files_rejects_missing_required_field(tmp_path: Path):
    path = tmp_path / "moj_history_20260819T000000Z-history.json"
    path.write_text('[{"pcode": "x"}]', encoding="utf-8")
    with pytest.raises(ValueError, match="缺少欄位"):
        inv.load_history_files(tmp_path)
