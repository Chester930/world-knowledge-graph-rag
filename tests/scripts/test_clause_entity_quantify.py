"""報告223 O1：`clause_entity_quantify.py` 純運算部分的單元測試（假資料，無需連線）。"""

import importlib.util
import json
import os
from pathlib import Path

from services import semantic_marks as sm

_ROOT = Path(__file__).resolve().parents[2]
_ENV_BEFORE = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
_SPEC = importlib.util.spec_from_file_location("clause_entity_quantify", _ROOT / "scripts" / "analysis" / "clause_entity_quantify.py")
cq = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cq)

CORE = {"ORGANIZATION": "Organization"}
EXT: dict = {}


def test_import_does_not_touch_os_environ():
    assert {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"} == _ENV_BEFORE


def test_name_features_each_feature_and_none():
    assert cq.name_features("勞工在同一雇主繼續工作滿五年以上者") == {"條文用語": True, "標點括號": False, "數字加單位": True}
    f = cq.name_features("基金之收支、運用情形")
    assert f["標點括號"] is True and f["條文用語"] is True
    assert cq.name_features("勞動部") == {"條文用語": False, "標點括號": False, "數字加單位": False}


def test_strong_candidate_requires_length_and_feature():
    assert cq.is_strong_candidate("勞工在同一雇主繼續工作滿五年以上十年未滿者")
    assert not cq.is_strong_candidate("勞工之")  # 太短
    assert not cq.is_strong_candidate("中華民國勞動部勞工保險局")  # 夠長但無特徵（長名稱不等於子句）
    assert cq.is_strong_candidate("中華民國勞動部勞工保險局", threshold=8) is False
    assert cq.is_strong_candidate("勞動基準法施行細則第三十五條") is True  # 已知誤判：合法長名稱含「條」數字單位


def test_legal_name_like_heuristic():
    assert cq.is_legal_name_like("勞動基準法施行細則第三十五條")
    assert cq.is_legal_name_like("職業安全衛生管理辦法")
    assert not cq.is_legal_name_like("勞工在同一雇主繼續工作滿五年以上者")


def test_quantiles_and_histogram_edge_cases():
    assert cq.quantiles([]) == {k: None for k in ("min", "p25", "median", "p75", "p90", "p99", "max")}
    q = cq.quantiles([1, 2, 3, 4, 5])
    assert (q["min"], q["median"], q["max"]) == (1, 3, 5)
    h = cq.histogram([0, 1, 3, 4, 7, 8, 11, 12, 19, 20, 39, 40, 100])
    assert h == {"1-3": 2, "4-7": 2, "8-11": 2, "12-19": 2, "20-39": 2, "40+": 2, "0": 1}


def _ents():
    return [
        {"name": "勞動部", "type": "組織"},
        {"name": "勞工在同一雇主繼續工作滿五年以上者", "type": "概念"},      # 17
        {"name": "中華民國勞動部勞工保險局", "type": "Organization"},         # 12，無特徵
        {"name": "A" * 25, "type": "概念"},
    ]


def test_threshold_summary_counts_and_shares():
    s = cq.threshold_summary(_ents(), thresholds=(8, 12, 20))
    assert s["entities"] == 4 and s["concept_entities"] == 2
    t12 = s["by_threshold"]["12"]
    assert t12["count"] == 3 and t12["concept"] == 2 and t12["non_concept"] == 1
    assert t12["share_of_all"] == 0.75 and t12["share_of_concept_entities"] == 1.0
    assert t12["strong_candidates"] == 1  # 只有第 2 筆有特徵
    assert s["by_threshold"]["20"]["count"] == 1
    assert cq.threshold_summary([], thresholds=(12,))["by_threshold"]["12"]["share_of_all"] is None


def test_type_marks_three_schemes():
    m = cq.type_marks([{"name": "x", "type": "概念"}, {"name": "y", "type": "Organization"}, {"name": "z", "type": ""}], CORE, EXT)
    assert m["A"] == {sm.UNKNOWN: 2, sm.RESOLVED: 1}
    assert m["B"] == {sm.RESOLVED: 2, sm.UNKNOWN: 1}
    assert m["strict"] == {sm.INDETERMINATE: 1, sm.RESOLVED: 1, sm.UNKNOWN: 1}


def _edge(s, o, docs):
    return {"subject": s, "object": o, "citations_json": json.dumps([{"source_doc_id": d} for d in docs])}


def test_degrees_and_docs_with_self_loop_and_bad_json():
    rows = [_edge("甲", "乙", ["d1"]), _edge("甲", "甲", ["d2", "d2"]), {"subject": "丙", "object": "乙", "citations_json": "{bad"}]
    deg, docs = cq.degrees_and_docs(rows)
    assert deg == {"甲": 3, "乙": 2, "丙": 1}  # 自環計 2
    assert docs["甲"] == {"d1", "d2"} and "丙" not in docs
    s = cq.degree_doc_summary(["甲", "乙", "丙", "丁"], deg, docs)
    assert s["degree_hist"] == {"0": 1, "1": 1, "2": 1, "3-5": 1, "6+": 0}
    assert s["degree_eq_1_share"] == 0.25
    assert s["doc_count_hist"] == {"0": 2, "1": 1, "2+": 1}
    assert cq.degree_doc_summary([], {}, {})["degree_eq_1_share"] is None


def test_affected_facts_subject_object_either():
    facts = [{"subject": "A", "object": "B"}, {"subject": "A", "object": "A"}, {"subject": "C", "object": "A"}, {"subject": "C", "object": "D"}]
    r = cq.affected_facts({"A"}, facts)
    assert (r["as_subject"], r["as_object"], r["either"], r["facts_total"]) == (2, 2, 3, 4)
    assert r["either_share"] == 0.75
    assert cq.affected_facts({"A"}, [])["either_share"] is None


def test_near_duplicates_only_punctuation_and_space_differences():
    r = cq.near_duplicates(["基金之收支,運用情形", "基金之收支、運用情形", "基金之 收支運用情形", "完全不同的名稱"])
    assert r["duplicate_groups"] == 1 and r["entities_in_duplicate_groups"] == 3 and r["groups"] == 2
    assert cq.near_duplicates([])["duplicate_groups"] == 0


def _t(kind, text, ip, doc="d1", idx=1):
    return {"kind": kind, "text": text, "in_prompt": ip, "source_doc_id": doc, "source_svo_chunk_index": idx, "rank": 0, "score": None, "article_no": None}


def test_cross_retrieval_counts_endpoints_in_sets_and_skips_unmatched_and_ambiguous():
    from scripts.analysis import semantic_marks_replay_join as rj

    facts = [
        {"doc": "d1", "idx": 1, "text": "f1", "subject": "長名稱甲", "object": "乙", "verb": "v", "rel_type": "R", "article_no": "第1條"},
        {"doc": "d1", "idx": 2, "text": "f2", "subject": "丙", "object": "丁", "verb": "v", "rel_type": "R", "article_no": "第1條"},
        {"doc": "d1", "idx": 3, "text": "f3", "subject": "長名稱甲", "object": "乙", "verb": "v", "rel_type": "R", "article_no": "第1條"},
        {"doc": "d1", "idx": 3, "text": "f3", "subject": "戊", "object": "己", "verb": "v", "rel_type": "R", "article_no": "第1條"},  # 同鍵端點不同＝歧義
    ]
    fi = rj.build_fact_index(facts, CORE, EXT, extra_fields=("subject", "object"))
    entries = [("Q", _t("fact", "f1", True, idx=1)), ("Q", _t("fact", "f2", False, idx=2)),
               ("Q", _t("fact", "f3", True, idx=3)), ("Q", _t("fact", "nope", True, idx=9)), ("Q", {"kind": "x"})]
    out = cq.cross_retrieval(entries, fi, {}, {"set": {"長名稱甲"}})
    f = out["fact"]
    assert (f["entries"], f["matched"], f["matched_in_prompt"]) == (4, 2, 1)
    assert f["retrieved"] == {"set": 1} and f["in_prompt"] == {"set": 1}


class _FakeRunner:
    def __init__(self):
        self.calls = []

    def run(self, label, cypher, **params):
        self.calls.append((cypher, params))
        return []


def test_fetch_entities_is_read_only_and_parametrized():
    r = _FakeRunner()
    cq.fetch_entities(r, "kg1")
    cypher, params = r.calls[0]
    assert params == {"k": "kg1"}
    assert not set(cypher.upper().split()) & {"SET", "MERGE", "DELETE", "CREATE", "REMOVE"}
