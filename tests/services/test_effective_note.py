"""effective_note 純函式、真實備註等價性與零接線守衛。"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from scripts.analysis import kg4_pending_effect_analysis as legacy
from services import effective_note as subject

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "kg4_effective_notes_20261003.json"
AS_OF = "2026-10-03"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _pending_shape(items: list[dict]) -> list[tuple[str, str, str]]:
    return sorted((item["article_no"], item["scope"], item["effective_date"]) for item in items)


def test_sixteen_real_notes_are_equivalent_to_analysis_script():
    data = _fixture()
    assert len(data["documents"]) == 16
    for document in data["documents"]:
        note = document["note"]
        known = document["known_articles"]
        new_parsed = subject.parse_effective_note(note, known)
        old_parsed = legacy.parse_effective_note(note, known)
        assert new_parsed == old_parsed, document["source"]
        assert subject.pending_items(new_parsed, AS_OF) == legacy.pending_items(old_parsed, AS_OF)
        assert subject.consistency(new_parsed, document["effective_date"]) == legacy.consistency(old_parsed, document["effective_date"])


def test_real_fixture_expected_kind_dates_and_twenty_one_articles():
    data = _fixture()
    pending_total = 0
    for document in data["documents"]:
        parsed = subject.parse_effective_note(document["note"], document["known_articles"])
        expected = document["expected"]
        assert parsed["kind"] == expected["kind"], document["source"]
        assert parsed["max_date"] == expected["max_date"], document["source"]
        actual = _pending_shape(subject.pending_items(parsed, data["as_of"]))
        wanted = _pending_shape(expected["pending_articles"])
        assert actual == wanted, document["source"]
        pending_total += len({article for article, _, _ in actual})
    assert pending_total == 21


@pytest.mark.parametrize(
    ("text", "expected"),
    [("一百十六", 116), ("一百零四", 104), ("一百十", 110), ("三十", 30), ("十二", 12)],
)
def test_chinese_numerals_and_roc_dates(text: str, expected: int):
    assert subject.cn_to_int(text) == expected
    assert subject.roc_to_iso(f"{text}年一月一日") == f"{expected + 1911:04d}-01-01"


def test_ranges_use_known_articles_and_keep_unknown_endpoints():
    known = ["21-3", "57", "116", "185", "185-1", "185-2", "185-3", "185-4"]
    assert subject.expand_articles("185-1～185-4", known) == ["185-1", "185-2", "185-3", "185-4"]
    assert subject.expand_articles("43～46", ["42", "43", "44", "45", "46", "47"]) == ["43", "44", "45", "46"]
    assert subject.expand_articles("11～12-7", ["11", "12", "12-1", "12-7"]) == ["11", "12", "12-1", "12-7"]
    assert subject.expand_articles("185-1～186", ["185-1", "185-2"]) == ["185-1", "185-2", "186"]


def test_staged_and_deleted_provisions():
    health = _fixture()["documents"][1]
    parsed = subject.parse_effective_note(health["note"], health["known_articles"])
    assert parsed["default_date"] == "2026-07-01"
    assert len([item for item in parsed["items"] if item["origin"] == "default"]) == 29
    deleted = subject.parse_effective_note(
        "一百十五年六月二十六日刪除第 5 條條文，自一百十六年一月一日施行。", ["5"]
    )
    assert subject.pending_items(deleted, AS_OF) == []


def test_as_of_boundaries_and_projections():
    documents = _fixture()["documents"]
    facility = documents[2]
    construction = documents[11]
    facility_parsed = subject.parse_effective_note(facility["note"], facility["known_articles"])
    construction_parsed = subject.parse_effective_note(construction["note"], construction["known_articles"])
    assert subject.pending_items(facility_parsed, "2026-12-31")
    assert subject.pending_items(facility_parsed, "2027-01-01") == []
    assert subject.article_effective_status(construction_parsed, "11-2", "2027-06-30").status == subject.STATUS_PENDING_WHOLE
    assert subject.article_effective_status(construction_parsed, "11-2", "2027-07-01").status == subject.STATUS_IN_FORCE
    assert subject.document_effective_status(facility_parsed, "2027-01-01") == subject.STATUS_IN_FORCE
    assert subject.document_effective_status(construction_parsed, "2027-06-30") == "has_pending"


def test_article_number_spellings_are_equivalent():
    document = _fixture()["documents"][2]
    parsed = subject.parse_effective_note(document["note"], document["known_articles"])
    statuses_57 = [subject.article_effective_status(parsed, value, "2026-12-31") for value in ("57", "第57條", "第 57 條")]
    statuses_185 = [subject.article_effective_status(parsed, value, "2026-12-31") for value in ("185-1", "第185-1條", "第 185-1 條")]
    assert all(status == statuses_57[0] for status in statuses_57)
    assert all(status == statuses_185[0] for status in statuses_185)


def test_status_cases_include_no_information_partial_whole_and_undetermined():
    fixture = _fixture()
    documents = fixture["documents"]
    leave = subject.parse_effective_note(documents[5]["note"], documents[5]["known_articles"])
    health = subject.parse_effective_note(documents[1]["note"], documents[1]["known_articles"])
    construction = subject.parse_effective_note(documents[11]["note"], documents[11]["known_articles"])
    undetermined = subject.parse_effective_note(documents[13]["note"], documents[13]["known_articles"])
    empty = subject.parse_effective_note("")
    unparsed = subject.parse_effective_note("一些無法解析的文字")
    assert subject.article_effective_status(leave, "7", AS_OF).status == subject.STATUS_IN_FORCE
    assert subject.article_effective_status(leave, "9", AS_OF).status == subject.STATUS_IN_FORCE
    assert subject.article_effective_status(empty, "1", AS_OF).status == subject.STATUS_NO_INFORMATION
    assert subject.article_effective_status(unparsed, "1", AS_OF).status == subject.STATUS_NO_INFORMATION
    assert subject.article_effective_status(construction, "11-2", AS_OF).status == subject.STATUS_PENDING_WHOLE
    assert subject.article_effective_status(construction, "11-2", "2027-06-30").status == subject.STATUS_PENDING_WHOLE
    assert subject.article_effective_status(health, "5", AS_OF).status == subject.STATUS_PENDING_PARTIAL
    assert subject.article_effective_status(health, "6", AS_OF).status == subject.STATUS_PENDING_PARTIAL
    assert subject.article_effective_status(undetermined, "1", AS_OF).status == subject.STATUS_UNDETERMINED
    assert subject.article_effective_status(undetermined, "43", AS_OF).status == subject.STATUS_UNDETERMINED


def test_status_metadata_uses_earliest_date_and_stable_unique_order():
    parsed = {
        "kind": "single",
        "items": [
            {"article_no": "7", "locator": "第2～3項", "scope": "paragraph", "op": "修正", "effective_date": "2028-01-01"},
            {"article_no": "7", "locator": "第2～3項", "scope": "paragraph", "op": "修正", "effective_date": "2027-01-01"},
            {"article_no": "7", "locator": "附表一", "scope": "appendix", "op": "增訂", "effective_date": "2029-01-01"},
        ],
    }
    status = subject.article_effective_status(parsed, "第 7 條", AS_OF)
    assert status.status == subject.STATUS_PENDING_PARTIAL
    assert status.effective_from == "2027-01-01"
    assert status.locators == ("第2～3項", "附表一")
    assert status.ops == ("修正", "增訂")


def test_invalid_date_is_unparsed_with_errors_without_raising():
    parsed = subject.parse_effective_note("一百十五年十三月一日修正第 1 條，自一百十五年十三月一日施行。", ["1"])
    assert parsed["kind"] == "unparsed"
    assert parsed["items"] == []
    assert parsed["errors"]
    with pytest.raises(ValueError):
        subject.roc_to_iso("一百十五年十三月一日")


@pytest.mark.parametrize("as_of", ["2026-1-01", "2026/10/03", "2026-13-01", None])
def test_as_of_must_be_valid_iso_date(as_of):
    parsed = {"kind": "empty", "items": []}
    with pytest.raises(ValueError):
        subject.pending_items(parsed, as_of)
    with pytest.raises(ValueError):
        subject.article_effective_status(parsed, "1", as_of)
    with pytest.raises(ValueError):
        subject.document_effective_status(parsed, as_of)


def test_module_is_stdlib_only_and_has_no_runtime_or_clock_access():
    path = ROOT / "services" / "effective_note.py"
    source = path.read_text(encoding="utf-8")
    for forbidden in ("date.today", "datetime.now", "time.time", "open(", "os.environ", "neo4j", "requests", "httpx"):
        assert forbidden not in source
    tree = ast.parse(source)
    allowed = {"__future__", "re", "dataclasses", "datetime", "typing"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name.split(".")[0] in allowed for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.module and node.module.split(".")[0] in allowed
    assert len(source.splitlines()) <= 300


def test_effective_note_has_no_production_references():
    excluded = {"tests", "docs", ".claude", ".git", "scripts"}
    for path in ROOT.rglob("*"):
        if (not path.is_file() or any(part in excluded for part in path.parts) or path.name.startswith(".env")
                or path.suffix.lower() in {".md", ".json", ".txt"}):
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if path == ROOT / "services" / "effective_note.py":
            continue
        assert "effective_note" not in source, path
