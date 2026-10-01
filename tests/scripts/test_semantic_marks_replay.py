"""報告217 M2：`scripts/analysis/semantic_marks_replay.py` 的單元測試（純離線、tmp_path 假資料）。"""

import importlib.util
import json
from pathlib import Path

from services import semantic_marks as sm

_SPEC = importlib.util.spec_from_file_location(
    "semantic_marks_replay",
    Path(__file__).resolve().parents[2] / "scripts" / "analysis" / "semantic_marks_replay.py",
)
replay = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(replay)


def _e(kind, text, in_prompt, article=None, doc="d1", idx=1):
    return {"kind": kind, "rank": 0, "text": text, "score": None, "source_doc_id": doc,
            "source_svo_chunk_index": idx, "article_no": article, "in_prompt": in_prompt}


def _rec(qid, trace):
    return {"question_id": qid, "lineage": {"stage1_retrieval": {"retrieval_trace": trace}}}


def test_iter_handles_list_dict_and_missing_trace():
    recs = [
        _rec("Q1", [_e("fact", "甲", True)]),
        _rec("Q2", {"facts": [_e("fact", "乙", False)], "triples": [_e("triple", "丙", None)]}),
        {"question_id": "Q3"},
        _rec("Q4", None),
        "not-a-dict",
    ]
    got = list(replay.iter_trace_entries(recs))
    assert [q for q, _ in got] == ["Q1", "Q2", "Q2"]
    assert list(replay.iter_trace_entries({"not": "list"})) == []


def test_article_mark_blank_and_whitespace_are_indeterminate():
    assert replay.article_mark({"article_no": "第5條"}) == sm.RESOLVED
    for v in (None, "", "   "):
        assert replay.article_mark({"article_no": v}) == sm.INDETERMINATE


def test_summarize_counts_in_prompt_three_states_and_article_split():
    entries = [
        ("Q1", _e("fact", "a", True, "第1條")),
        ("Q1", _e("fact", "b", False, None)),
        ("Q1", _e("fact", "c", None, None)),
        ("Q2", _e("triple", "t", True)),
    ]
    s = replay.summarize(entries)
    assert s["questions"] == 2
    f = s["by_kind"]["fact"]
    assert (f["retrieved"], f["in_prompt_true"], f["in_prompt_false"], f["in_prompt_unmeasured"]) == (3, 1, 1, 1)
    assert f["article_retrieved"] == {sm.RESOLVED: 1, sm.INDETERMINATE: 2}
    assert f["article_in_prompt"] == {sm.RESOLVED: 1}
    assert s["by_kind"]["triple"]["in_prompt_true"] == 1


def test_summarize_empty():
    assert replay.summarize([]) == {"questions": 0, "by_kind": {}}


def test_run_dedups_across_files_and_skips_backup(tmp_path):
    ev = tmp_path / "eval"
    (ev / "a").mkdir(parents=True)
    (ev / "b").mkdir()
    same = _e("fact", "甲", False)
    (ev / "a" / "records.json").write_text(json.dumps([_rec("Q1", [same])]), encoding="utf-8")
    (ev / "b" / "records.json").write_text(
        json.dumps([_rec("Q1", [{**same, "in_prompt": True}])]), encoding="utf-8")
    (ev / "b" / "records.backup_x.json").write_text(
        json.dumps([_rec("Q9", [_e("fact", "備份", True)])]), encoding="utf-8")
    (ev / "b" / "records.broken.json").write_text("{not json", encoding="utf-8")
    res = replay.run(ev)
    assert len(res["per_file"]) == 3  # 備份檔仍列在 per_file，壞檔略過
    u = res["unique_union"]
    assert u["questions"] == 1  # 備份檔不併入去重集合
    assert u["by_kind"]["fact"]["retrieved"] == 1
    assert u["by_kind"]["fact"]["in_prompt_true"] == 1  # 任一次進過即計
    assert "fields" in res["not_replayable"]
