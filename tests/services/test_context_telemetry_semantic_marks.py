"""報告216 M1：`build_retrieval_trace` 的影子模式 `semantic_marks`（預設關閉、純派生）。"""

import json
from uuid import uuid4

import pytest

from models.knowledge_graph import SVOTriple
from services import semantic_marks as sm
from services.context.telemetry import build_retrieval_trace

CORE = {"ORGANIZATION": "Organization"}
EXT = {}


def _inputs():
    doc = uuid4()
    triples = [
        SVOTriple(subject="甲", subject_type="Organization", rel_type="CAUSES", verb="導致",
                  object="乙", object_type="概念", source_doc_id=doc, source_article_no="第5條"),
        SVOTriple(subject="丙", subject_type="", rel_type="RELATED_TO", verb="", object="",
                  object_type="Foo", source_doc_id=doc),
    ]
    facts = [
        {"fact_text": "甲 規定 乙", "subject": "甲", "object": "乙", "verb": "規定",
         "rel_type": "REGULATES", "score": 0.9, "source_doc_id": str(doc), "article_no": "第3條"},
        {"fact_text": "丙", "subject": "丙", "object": "", "verb": "", "rel_type": "RELATED_TO"},
    ]
    return triples, facts, doc


def test_default_output_equals_explicit_false_and_has_no_marks():
    triples, facts, _ = _inputs()
    default = build_retrieval_trace(triples, facts, None)
    off = build_retrieval_trace(triples, facts, None, include_semantic_marks=False)
    assert default == off
    assert json.dumps(default, ensure_ascii=False) == json.dumps(off, ensure_ascii=False)
    for e in default["facts"] + default["triples"]:
        assert "semantic_marks" not in e
    assert list(default["facts"][0]) == [
        "kind", "rank", "text", "score", "source_doc_id", "source_svo_chunk_index",
        "article_no", "in_prompt",
    ]


def test_flag_on_only_adds_semantic_marks_key():
    triples, facts, _ = _inputs()
    base = build_retrieval_trace(triples, facts, [["- 甲 規定 乙"]])
    on = build_retrieval_trace(triples, facts, [["- 甲 規定 乙"]], include_semantic_marks=True)
    assert on["prompt_lines"] == base["prompt_lines"]
    for key in ("facts", "triples"):
        stripped = [{k: v for k, v in e.items() if k != "semantic_marks"} for e in on[key]]
        assert stripped == base[key]
        assert all("semantic_marks" in e for e in on[key])


def test_marks_values_and_edge_cases():
    triples, facts, doc = _inputs()
    on = build_retrieval_trace(triples, facts, None, include_semantic_marks=True,
                               type_lookups=(CORE, EXT),
                               document_article_applicable={str(doc): True})
    f0, f1 = (e["semantic_marks"] for e in on["facts"])
    # 報告225 Q2：既有三鍵不變，名稱形態兩鍵附加於最後（短名稱＝非長名稱；空受詞＝無法判定）
    assert f0 == {"fields": sm.RESOLVED, "relation_type": sm.RESOLVED, "article_no": sm.RESOLVED,
                  "subject_name_shape": sm.NAME_SHAPE_NOT_LONG, "object_name_shape": sm.NAME_SHAPE_NOT_LONG,
                  "lifecycle_state": sm.PENDING}  # 報告258 L1：附加於最後；輸入無該鍵＝尚未處理
    assert list(f0) == ["fields", "relation_type", "article_no", "subject_name_shape", "object_name_shape",
                        "lifecycle_state"]
    # 空受詞＋空 verb＝未知；RELATED_TO＝無法判定；無條號且無文件資訊＝無法判定（不猜）
    assert f1 == {"fields": sm.UNKNOWN, "relation_type": sm.INDETERMINATE,
                  "article_no": sm.INDETERMINATE,
                  "subject_name_shape": sm.NAME_SHAPE_NOT_LONG, "object_name_shape": sm.NAME_SHAPE_INDETERMINATE,
                  "lifecycle_state": sm.PENDING}
    t0, t1 = (e["semantic_marks"] for e in on["triples"])
    assert t0["subject_type"] == sm.RESOLVED and t0["object_type"] == sm.UNKNOWN  # 概念，方案A
    assert t0["article_no"] == sm.RESOLVED
    assert t1["subject_type"] == sm.UNKNOWN and t1["object_type"] == sm.PENDING
    assert t1["fields"] == sm.UNKNOWN
    assert t1["article_no"] == sm.UNKNOWN  # 文件適用條號、此筆缺


def test_document_without_any_article_is_not_applicable():
    triples, _, doc = _inputs()
    on = build_retrieval_trace([triples[1]], [], None, include_semantic_marks=True,
                               document_article_applicable={str(doc): False})
    assert on["triples"][0]["semantic_marks"]["article_no"] == sm.NOT_APPLICABLE


@pytest.mark.parametrize("scheme,expected", [("A", sm.UNKNOWN), ("B", sm.RESOLVED), ("strict", sm.INDETERMINATE)])
def test_concept_scheme_parameter(scheme, expected):
    triples, _, _ = _inputs()
    on = build_retrieval_trace(triples[:1], [], None, include_semantic_marks=True,
                               concept_scheme=scheme, type_lookups=(CORE, EXT))
    assert on["triples"][0]["semantic_marks"]["object_type"] == expected


def test_no_type_lookups_omits_entity_type_marks():
    triples, _, _ = _inputs()
    on = build_retrieval_trace(triples, [], None, include_semantic_marks=True)
    assert "subject_type" not in on["triples"][0]["semantic_marks"]


def test_invalid_scheme_raises_only_when_enabled():
    triples, facts, _ = _inputs()
    build_retrieval_trace(triples, facts, None, concept_scheme="bogus")  # 關閉時不檢查
    with pytest.raises(ValueError):
        build_retrieval_trace(triples, facts, None, include_semantic_marks=True, concept_scheme="bogus")


def test_empty_inputs():
    assert build_retrieval_trace([], [], None, include_semantic_marks=True) == \
        build_retrieval_trace([], [], None)
