"""報告218 M2b：`semantic_marks_replay_join.py` 純運算部分的單元測試（假資料，無需連線）。"""

import importlib.util
import json
from pathlib import Path

from services import semantic_marks as sm

_SPEC = importlib.util.spec_from_file_location(
    "semantic_marks_replay_join",
    Path(__file__).resolve().parents[2] / "scripts" / "analysis" / "semantic_marks_replay_join.py",
)
rj = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rj)

CORE = {"ORGANIZATION": "Organization"}
EXT: dict = {}


class _FakeRunner:
    def __init__(self):
        self.calls = []

    def run(self, label, cypher, **params):
        self.calls.append((label, cypher, params))
        return []


def _frow(doc, idx, text, s="甲", o="乙", v="規定", rel="REGULATES", art="第1條",
          st="Organization", se="甲", ot="概念", oe="乙"):
    return {"doc": doc, "idx": idx, "text": text, "subject": s, "object": o, "verb": v,
            "rel_type": rel, "article_no": art, "subject_type": st, "subject_entity": se,
            "object_type": ot, "object_entity": oe}


def _erow(s, o, nt, doc, idx, verb="導致", art="第1條", rel="CAUSES", st="Organization", ot=""):
    cites = json.dumps([{"source_doc_id": "old", "source_svo_chunk_index": 0, "verb": "舊"},
                        {"source_doc_id": doc, "source_svo_chunk_index": idx, "verb": verb, "article_no": art}])
    return {"subject": s, "subject_type": st, "rel_type": rel, "natural_text": nt, "object": o,
            "object_type": ot, "citations_json": cites}


def _t(kind, text, in_prompt, doc="d1", idx=None):
    return {"kind": kind, "rank": 0, "text": text, "score": None, "source_doc_id": doc,
            "source_svo_chunk_index": idx, "article_no": None, "in_prompt": in_prompt}


def test_fetch_functions_pass_kg_param_with_read_only_cypher():
    r = _FakeRunner()
    rj.fetch_facts(r, "kg1")
    rj.fetch_edges(r, "kg1")
    assert [c[2] for c in r.calls] == [{"k": "kg1"}, {"k": "kg1"}]
    for _, cypher, _ in r.calls:
        assert not set(cypher.upper().split()) & {"SET", "MERGE", "DELETE", "CREATE", "REMOVE"}


def test_entity_type_marks_three_schemes_and_unmatched_entity():
    assert rj.entity_type_marks("概念", True, CORE, EXT) == {
        "A": sm.UNKNOWN, "B": sm.RESOLVED, "strict": sm.INDETERMINATE}
    assert rj.entity_type_marks("Organization", True, CORE, EXT) == {s: sm.RESOLVED for s in rj.SCHEMES}
    assert rj.entity_type_marks(None, False, CORE, EXT) == {s: rj.UNMATCHED_ENTITY for s in rj.SCHEMES}
    assert rj.entity_type_marks("Foo", True, CORE, EXT)["A"] == sm.PENDING


def test_fact_index_marks_include_entity_types():
    idx = rj.build_fact_index([_frow("d1", 1, "完整"), _frow("d1", 2, "無實體", se=None, st=None)], CORE, EXT)
    m = idx[("d1", 1, "完整")][0]
    assert m["fields"] == sm.RESOLVED and m["subject_type_A"] == sm.RESOLVED
    assert m["object_type_A"] == sm.UNKNOWN and m["object_type_B"] == sm.RESOLVED
    assert idx[("d1", 2, "無實體")][0]["subject_type_strict"] == rj.UNMATCHED_ENTITY


def test_edge_index_uses_latest_citation_and_natural_text_fallback():
    rows = [
        _erow("甲", "乙", "甲導致乙。", "d1", 3),
        _erow("丙", "丁", None, "d1", 4, verb="規範"),          # 無 natural_text → "丙 規範 丁"
        {**_erow("戊", "己", "x", "d1", 5), "citations_json": None},  # 無引用 → 略過
        {**_erow("庚", "辛", "y", "d1", 6), "citations_json": "{bad"},  # 壞 JSON → 略過
    ]
    idx = rj.build_edge_index(rows, CORE, EXT)
    assert set(idx) == {("d1", "甲導致乙。"), ("d1", "丙 規範 丁")}
    item = idx[("d1", "甲導致乙。")][0]
    assert item["idx"] == 3 and item["marks"]["relation_type"] == sm.RESOLVED
    assert item["marks"]["article_no"] == sm.RESOLVED  # 取最後一筆引用，非舊引用


def test_join_triple_with_and_without_chunk_index_and_ambiguity():
    edges = rj.build_edge_index([
        _erow("甲", "乙", "同文", "d1", 1, rel="CAUSES"),
        _erow("甲", "乙", "同文", "d1", 2, rel="RELATED_TO"),   # 同 (doc,text) 不同 chunk、標示不同
        _erow("丙", "丁", "唯一", "d1", 7),
    ], CORE, EXT)
    entries = [
        ("Q", _t("triple", "同文", True, idx=None)),   # 舊快照無 chunk → 歧義
        ("Q", _t("triple", "同文", True, idx=2)),      # 有 chunk → 縮小後唯一
        ("Q", _t("triple", "唯一", False)),
        ("Q", _t("triple", "不存在", True)),
    ]
    s = rj.join_summarize(entries, {}, edges)["triple"]
    assert (s["entries"], s["matched"], s["unmatched"], s["ambiguous"]) == (4, 2, 1, 1)
    assert s["in_prompt_matched"] == 1
    assert s["retrieved"]["relation_type"] == {sm.INDETERMINATE: 1, sm.RESOLVED: 1}


def test_join_fact_and_triple_in_one_pass_and_empty():
    facts = rj.build_fact_index([_frow("d1", 1, "完整")], CORE, EXT)
    out = rj.join_summarize([("Q", _t("fact", "完整", True, idx=1)), ("Q", {"kind": "other"})], facts, {})
    assert set(out) == {"fact"} and out["fact"]["in_prompt"]["fields"] == {sm.RESOLVED: 1}
    assert rj.join_summarize([], {}, {}) == {}
