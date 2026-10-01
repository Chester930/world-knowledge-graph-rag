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


# ── 唯讀 join（報告217 §8）──────────────────────────────────────────────────
class _FakeRunner:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def run(self, label, cypher, **params):
        self.calls.append((label, cypher, params))
        return self.rows


def _row(doc, idx, text, s="甲", o="乙", v="規定", rel="REGULATES", art="第1條"):
    return {"doc": doc, "idx": idx, "text": text, "subject": s, "object": o, "verb": v,
            "rel_type": rel, "article_no": art}


def test_fetch_fact_table_uses_runner_with_kg_param_and_is_read_only_cypher():
    r = _FakeRunner([_row("d", 1, "t")])
    assert replay.fetch_fact_table(r, "kg1") == r.rows
    assert r.calls[0][2] == {"k": "kg1"}
    words = set(r.calls[0][1].upper().split())
    assert not words & {"SET", "MERGE", "DELETE", "CREATE", "REMOVE"}


def test_build_index_marks_and_document_level_article_applicability():
    rows = [
        _row("d1", 1, "完整"),
        _row("d1", 2, "空受詞", o="", rel="RELATED_TO", art=None),  # d1 有條號 → 此筆無條號＝未知
        _row("d2", 1, "空受詞空verb", o=" ", v="", art=None),      # d2 全無條號 → 不適用
    ]
    idx = replay.build_fact_index(rows)
    assert idx[("d1", 1, "完整")][0] == {
        "fields": sm.RESOLVED, "relation_type": sm.RESOLVED, "article_no": sm.RESOLVED}
    m2 = idx[("d1", 2, "空受詞")][0]
    assert (m2["fields"], m2["relation_type"], m2["article_no"]) == (sm.PENDING, sm.INDETERMINATE, sm.UNKNOWN)
    m3 = idx[("d2", 1, "空受詞空verb")][0]
    assert (m3["fields"], m3["article_no"]) == (sm.UNKNOWN, sm.NOT_APPLICABLE)


def test_join_summarize_matched_unmatched_ambiguous_and_in_prompt():
    rows = [
        _row("d1", 1, "完整"),
        _row("d1", 2, "空受詞", o=""),
        _row("d1", 3, "重複", o=""), _row("d1", 3, "重複", o="乙"),    # 同鍵但標示不一致 → 歧義
        _row("d1", 4, "重複同", o=""), _row("d1", 4, "重複同", o=""),  # 同鍵且標示一致 → 可用
    ]
    idx = replay.build_fact_index(rows)
    entries = [
        ("Q", _e("fact", "完整", True, doc="d1", idx=1)),
        ("Q", _e("fact", "空受詞", False, doc="d1", idx=2)),
        ("Q", _e("fact", "不存在", True, doc="d1", idx=9)),
        ("Q", _e("fact", "重複", True, doc="d1", idx=3)),
        ("Q", _e("fact", "重複同", True, doc="d1", idx=4)),
        ("Q", _e("triple", "忽略", True)),
    ]
    s = replay.join_summarize(entries, idx)
    assert (s["fact_entries"], s["matched"], s["unmatched"], s["ambiguous"]) == (5, 3, 1, 1)
    assert s["retrieved"]["fields"] == {sm.RESOLVED: 1, sm.PENDING: 2}
    assert s["in_prompt"]["fields"] == {sm.RESOLVED: 1, sm.PENDING: 1}
    assert s["in_prompt_matched"] == 2


def test_join_summarize_empty():
    s = replay.join_summarize([], {})
    assert s["fact_entries"] == 0 and s["retrieved"]["fields"] == {}
