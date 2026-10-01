"""報告221 N1：`services/context/trace_marks.py`（旗標參數組裝＋靜態型別表載入）。"""

import json

import pytest

from core.constants import ENTITY_TYPES
from services import semantic_marks as sm
from services.context import trace_marks


@pytest.fixture(autouse=True)
def _fresh_cache():
    trace_marks.load_type_lookups.cache_clear()
    yield
    trace_marks.load_type_lookups.cache_clear()


def test_flag_off_returns_empty_kwargs_and_does_not_load(monkeypatch):
    monkeypatch.setattr(trace_marks, "load_type_lookups", lambda: (_ for _ in ()).throw(AssertionError("不得載入")))
    assert trace_marks.semantic_marks_trace_kwargs(False, "A") == {}
    assert trace_marks.semantic_marks_trace_kwargs(False, "bogus") == {}  # 關閉時不檢查 scheme


def test_flag_on_kwargs_shape_and_invalid_scheme():
    kw = trace_marks.semantic_marks_trace_kwargs(True, "B")
    assert set(kw) == {"include_semantic_marks", "concept_scheme", "type_lookups"}
    assert kw["include_semantic_marks"] is True and kw["concept_scheme"] == "B"
    with pytest.raises(ValueError):
        trace_marks.semantic_marks_trace_kwargs(True, "bogus")
    assert "document_article_applicable" not in kw  # 不查 DB


def test_load_type_lookups_normalizes_keys_and_covers_core_and_extended():
    core, ext = trace_marks.load_type_lookups()
    assert len(core) == len({sm.normalize_type_key(k) for k in ENTITY_TYPES})
    for k in core:
        assert k == sm.normalize_type_key(k)
    assert len(ext) > 900  # 擴充表 939 型別（報告208 type_tables）
    assert sm.mark_entity_type("Organization", core, ext) == sm.RESOLVED


def test_load_type_lookups_is_cached():
    assert trace_marks.load_type_lookups() is trace_marks.load_type_lookups()


def test_missing_or_broken_extended_file_degrades_to_empty_ext(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(trace_marks, "_EXT_TYPES_PATH", tmp_path / "nope.json")
    core, ext = trace_marks.load_type_lookups()
    assert core and ext == {}
    assert "降級為空" in caplog.text

    trace_marks.load_type_lookups.cache_clear()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(trace_marks, "_EXT_TYPES_PATH", bad)
    assert trace_marks.load_type_lookups()[1] == {}

    trace_marks.load_type_lookups.cache_clear()
    odd = tmp_path / "odd.json"
    odd.write_text(json.dumps({"types": [{"id": "x"}]}), encoding="utf-8")  # 缺 label
    monkeypatch.setattr(trace_marks, "_EXT_TYPES_PATH", odd)
    assert trace_marks.load_type_lookups()[1] == {}
