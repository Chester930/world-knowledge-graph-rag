"""報告257 法規時間覆蓋盤點：純函式與結構守衛（不連線）。"""
import re
from pathlib import Path

from scripts.analysis.kg4_law_time_coverage import article_no_shape, is_pcode_source, summarize

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "analysis" / "kg4_law_time_coverage.py"


def test_article_no_shape():
    assert article_no_shape("第 25 條") == "第 # 條"
    assert article_no_shape("第 9-1 條") == "第 #-# 條"
    assert article_no_shape(None) == ""


def test_is_pcode_source():
    assert is_pcode_source("N0030006_勞工請假規則")
    assert not is_pcode_source("勞工請假規則")
    assert not is_pcode_source(None)


def _doc(source, eff=None, facts=0, articles=0, note=None):
    return {"source": source, "record_type": "law", "update_date": "20250101", "effective_date": eff,
            "effective_note": note, "articles": articles, "facts": facts}


def test_summarize_future_effective_split():
    docs = [_doc("N0000001_甲", "20270101", facts=10, articles=2, note="自 一百十六年\n一月一日施行"),
            _doc("N0000002_乙", "20260101", facts=5),
            _doc("N0000003_丙", None, facts=7)]
    res = summarize(docs, ["第 1 條", "第 2-1 條"], "20261002")
    assert res["documents"] == 3 and res["with_effective_date"] == 2
    assert [d["source"] for d in res["future_effective_documents"]] == ["N0000001_甲"]
    assert res["facts_in_future_effective_documents_upper_bound"] == 10
    assert res["facts_in_docs_with_effective_date"] == 15
    assert res["future_effective_documents"][0]["effective_note"] == "自 一百十六年 一月一日施行"
    assert res["article_no_shapes"] == {"第 # 條": 1, "第 #-# 條": 1}


def test_script_is_read_only_and_has_no_embedding_calls():
    body = "\n".join(ln for ln in SCRIPT.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#"))
    for block in re.findall(r'"""\s*(MATCH.*?)"""', body, flags=re.S):
        assert not re.search(r"\b(SET|CREATE|MERGE|DELETE|REMOVE|CALL)\b", block)
    assert "core.providers" not in body
    assert "embedding_provider" not in body.replace("embedding_provider_called", "")
