"""報告225 Q1／Q2：`mark_entity_name_shape()` 單元測試＋與報告223 O1 腳本定義的不漂移守門＋trace 整合。"""

import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest

from models.knowledge_graph import SVOTriple
from services import semantic_marks as sm
from services.context.telemetry import build_retrieval_trace

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("clause_entity_quantify", _ROOT / "scripts" / "analysis" / "clause_entity_quantify.py")
cq = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cq)

STRONG, LEN_ONLY, NOT, IND = (sm.NAME_SHAPE_LONG_STRONG, sm.NAME_SHAPE_LONG_LENGTH_ONLY,
                              sm.NAME_SHAPE_NOT_LONG, sm.NAME_SHAPE_INDETERMINATE)


def test_values_do_not_collide_with_existing_mark_values():
    assert set(sm.NAME_SHAPES).isdisjoint(set(sm.MARKS))
    assert len(set(sm.NAME_SHAPES)) == 4


def test_indeterminate_for_blank_none_and_non_string():
    for v in (None, "", "   ", "　　", "\t\n", 123, ["x"]):
        assert sm.mark_entity_name_shape(v) == IND


def test_boundary_11_vs_12_chars_default_threshold():
    n11, n12 = "甲" * 11, "甲" * 12
    assert sm.mark_entity_name_shape(n11) == NOT
    assert sm.mark_entity_name_shape(n12) == LEN_ONLY  # 夠長但無特徵


def test_length_plus_feature_is_strong_each_feature():
    assert sm.mark_entity_name_shape("勞工在同一雇主繼續工作滿五年以上者") == STRONG        # 條文用語
    assert sm.mark_entity_name_shape("甲乙丙丁戊己庚辛壬癸子丑，寅") == STRONG              # 標點
    assert sm.mark_entity_name_shape("甲乙丙丁戊己庚辛壬三日癸子") == STRONG                # 數字加單位
    assert sm.mark_entity_name_shape("中華民國勞動部勞工保險局") == LEN_ONLY


def test_feature_but_shorter_than_threshold_is_not_clause():
    assert sm.mark_entity_name_shape("勞工之") == NOT
    assert sm.mark_entity_name_shape("依法，者") == NOT


def test_legal_full_name_is_a_known_false_positive():
    # 已知誤判：合法長名稱被判為「長度＋特徵」（docstring 已警示，不得宣稱語意判定）
    assert sm.mark_entity_name_shape("勞動基準法施行細則第三十五條") == STRONG


def test_threshold_parameter_8_12_20():
    name = "勞工應於十日內通知"  # 9 字，含「應」「日」
    assert sm.mark_entity_name_shape(name, 8) == STRONG
    assert sm.mark_entity_name_shape(name, 12) == NOT
    long_no_feature = "甲" * 20
    assert sm.mark_entity_name_shape(long_no_feature, 20) == LEN_ONLY
    assert sm.mark_entity_name_shape("甲" * 19, 20) == NOT


def test_length_is_raw_length_not_stripped_same_as_o1():
    padded = " " + "甲" * 11  # 原字串 12 字（含空白）：與 O1 的 len(name) 一致
    assert sm.mark_entity_name_shape(padded) == LEN_ONLY
    assert cq.is_strong_candidate(padded) is False


def test_is_long_name_shape():
    assert sm.is_long_name_shape(STRONG) and sm.is_long_name_shape(LEN_ONLY)
    assert not sm.is_long_name_shape(NOT) and not sm.is_long_name_shape(IND)


def test_definition_constants_identical_to_report223_script():
    """不漂移守門：關鍵字、三個特徵的正則、主門檻與 O1 腳本逐項相同。"""
    assert sm.NAME_SHAPE_KEYWORDS == cq.KEYWORDS
    assert sm._NAME_SHAPE_PUNCT_RE.pattern == cq._PUNCT_RE.pattern
    assert sm._NAME_SHAPE_NUM_UNIT_RE.pattern == cq._NUM_UNIT_RE.pattern
    assert sm.NAME_SHAPE_DEFAULT_THRESHOLD == cq.MAIN_THRESHOLD
    assert list(sm.name_shape_features("x")) == list(cq.FEATURES)


def test_agrees_with_o1_functions_on_a_name_corpus():
    names = ["", "勞動部", "甲" * 11, "甲" * 12, "勞工之", "勞工在同一雇主繼續工作滿五年以上者", "基金之收支、運用情形",
             "勞動基準法施行細則第三十五條", "中華民國勞動部勞工保險局", "過氧化鉀,過氧化鈉,過氧化鋇", "A" * 25, "第 三 條 之 一 規 定 事 項",
             "不得在休假日或在娛樂場、旅館、酒店或其他販賣貨物之處所行之", "高壓氣體特定設備操作人員"]
    for th in (8, 12, 20):
        for n in names:
            shape = sm.mark_entity_name_shape(n, th)
            if not n.strip():
                assert shape == IND
                continue
            assert sm.is_long_name_shape(shape) == (len(n) >= th)
            assert (shape == STRONG) == cq.is_strong_candidate(n, th)
            assert sm.name_shape_features(n) == cq.name_features(n)


# ── Q2：trace 整合 ──────────────────────────────────────────────────────────
def _inputs():
    doc = uuid4()
    long_name = "勞工在同一雇主繼續工作滿五年以上者"
    triples = [SVOTriple(subject=long_name, subject_type="概念", rel_type="CAUSES", verb="導致", object="乙",
                         object_type="概念", source_doc_id=doc)]
    facts = [{"fact_text": "x", "subject": "中華民國勞動部勞工保險局", "object": None, "verb": "規定", "rel_type": "R"}]
    return triples, facts


def test_trace_adds_name_shape_only_when_flag_on_and_flag_off_is_identical():
    triples, facts = _inputs()
    off_default = build_retrieval_trace(triples, facts, None)
    off_explicit = build_retrieval_trace(triples, facts, None, include_semantic_marks=False)
    assert off_default == off_explicit
    assert json.dumps(off_default, ensure_ascii=False) == json.dumps(off_explicit, ensure_ascii=False)
    assert all("semantic_marks" not in e for e in off_default["facts"] + off_default["triples"])

    on = build_retrieval_trace(triples, facts, None, include_semantic_marks=True)
    t = on["triples"][0]["semantic_marks"]
    f = on["facts"][0]["semantic_marks"]
    assert t["subject_name_shape"] == STRONG and t["object_name_shape"] == NOT
    assert f["subject_name_shape"] == LEN_ONLY and f["object_name_shape"] == IND  # object=None
    # 既有鍵與順序不變，新鍵附加最後
    assert list(t)[:3] == ["fields", "relation_type", "article_no"]
    assert list(t)[-2:] == ["subject_name_shape", "object_name_shape"]
    # 除 semantic_marks 外，旗標開啟與關閉的 trace 相同
    for key in ("facts", "triples"):
        stripped = [{k: v for k, v in e.items() if k != "semantic_marks"} for e in on[key]]
        assert stripped == off_default[key]


def test_trace_name_shape_does_not_need_type_lookups_and_coexists_with_them():
    triples, facts = _inputs()
    without = build_retrieval_trace(triples, facts, None, include_semantic_marks=True)["triples"][0]["semantic_marks"]
    assert "subject_type" not in without and "subject_name_shape" in without
    with_types = build_retrieval_trace(triples, facts, None, include_semantic_marks=True,
                                       type_lookups=({}, {}))["triples"][0]["semantic_marks"]
    assert list(with_types)[3:5] == ["subject_type", "object_type"]
    assert list(with_types)[-2:] == ["subject_name_shape", "object_name_shape"]


@pytest.mark.parametrize("bad", [None, ""])
def test_trace_blank_endpoints_are_indeterminate(bad):
    on = build_retrieval_trace([], [{"fact_text": "x", "subject": bad, "object": bad, "verb": "v"}], None,
                               include_semantic_marks=True)
    m = on["facts"][0]["semantic_marks"]
    assert m["subject_name_shape"] == IND and m["object_name_shape"] == IND
