"""報告267 「尚未施行」備註解析器：中文數字、條號展開、分階段「除…外」結構、交叉驗證、不連線守衛（用 KG#4 真實備註當 fixture）。"""
import re
from pathlib import Path

import pytest

from scripts.analysis.kg4_pending_effect_analysis import (
    art_key, cn_to_int, consistency, expand_articles, normalize, parse_effective_note, pending_items, roc_to_iso,
)

ROOT = Path(__file__).resolve().parents[2]
AS_OF = "2026-10-03"

NOTE_HEALTH = ("一百十五年六月二十六日修正之全文 29 條，依第 29 條規定：除第 5 條、第 6 條第 2～4 項、第 13 條第 3 項自一百十六年七月一日施行 ，"
               "及第 2 條附表一、第 16 條附表九、附表十、第 17、18、20、21 條 自一百十七年一月一日施行外，自一百十五年七月一日施行。")
NOTE_CONSTRUCTION = "一百十五年六月三十日增訂之第 11-2 條，自一百十六年七月一日施行。"
NOTE_EXPOSURE = "一百十四年四月十一日修正發布第 2 條條文之附表一編號十五、二百十 一、四百四十五及附表二，自一百十六年一月一日施行。"
NOTE_FACILITY = "一百十五年六月三十日修正之第 21-3、57、116、185-1～185-4 條，自 一百十六年一月一日施行。"
NOTE_TRAINING = ("一百十五年六月二十五日修正之第 1、17、18、20、40、43 條條文及第 3 條條文之附表一、第 4 條條文之附表二、第 5 條條文之附表三、"
                 "第 6 條條文之附表四；增訂第 42-4 條條文，依第 43 條規定：除第 3 條條文之附表一 、第 4 條條文之附表二、第 5 條條文之附表三自一百十六年一月一日 "
                 "施行外，自一百十五年七月一日施行。")
NOTE_INFORCE = "一百十四年十二月九日令修正發布第 7、9、12 條條文；增訂第 9-1 條 條文，依第 12 條規定：自一百十五年一月一日施行。"
KNOWN_FACILITY = ["21-3", "57", "116", "185", "185-1", "185-2", "185-3", "185-4"]


def test_chinese_numerals_and_roc_dates():
    assert cn_to_int("一百十六") == 116 and cn_to_int("一百零四") == 104 and cn_to_int("一百十") == 110
    assert cn_to_int("三十") == 30 and cn_to_int("十二") == 12 and cn_to_int("一百十五") == 115
    assert roc_to_iso("自一百十六年七月一日施行") == "2027-07-01"
    assert roc_to_iso("一百十七年一月一日") == "2028-01-01"
    with pytest.raises(ValueError):
        roc_to_iso("沒有日期")


def test_expand_articles_uses_known_articles_for_ranges():
    assert expand_articles("185-1～185-4", KNOWN_FACILITY) == ["185-1", "185-2", "185-3", "185-4"]
    assert expand_articles("43～46", ["42", "43", "44", "45", "46", "47"]) == ["43", "44", "45", "46"]
    assert expand_articles("21-3、57", KNOWN_FACILITY) == ["21-3", "57"]
    assert sorted(["12", "12-1", "11"], key=art_key) == ["11", "12", "12-1"]


def test_staged_health_protection_rules():
    p = parse_effective_note(NOTE_HEALTH, [str(n) for n in range(1, 30)])
    assert p["kind"] == "staged" and p["default_date"] == "2026-07-01" and p["max_date"] == "2028-01-01"
    pend = {(i["article_no"], i["scope"], i["effective_date"]) for i in pending_items(p, AS_OF)}
    assert pend == {("5", "article", "2027-07-01"), ("6", "paragraph", "2027-07-01"), ("13", "paragraph", "2027-07-01"),
                    ("2", "appendix", "2028-01-01"), ("16", "appendix", "2028-01-01"), ("17", "article", "2028-01-01"),
                    ("18", "article", "2028-01-01"), ("20", "article", "2028-01-01"), ("21", "article", "2028-01-01")}
    full = {i["article_no"] for i in p["items"] if i["origin"] == "default"}
    assert len(full) == 29  # 全文修正：所有條文預設 2026-07-01


def test_single_clause_new_article_and_appendix_and_range():
    c = parse_effective_note(NOTE_CONSTRUCTION, ["11", "11-2"])
    assert [(i["article_no"], i["op"], i["effective_date"]) for i in pending_items(c, AS_OF)] == [("11-2", "增訂", "2027-07-01")]
    e = parse_effective_note(NOTE_EXPOSURE, ["2"])
    assert [(i["article_no"], i["scope"]) for i in pending_items(e, AS_OF)] == [("2", "appendix")]
    f = parse_effective_note(NOTE_FACILITY, KNOWN_FACILITY)
    assert [i["article_no"] for i in pending_items(f, AS_OF)] == ["21-3", "57", "116", "185-1", "185-2", "185-3", "185-4"]


def test_training_rules_only_three_appendices_pending():
    p = parse_effective_note(NOTE_TRAINING, ["1", "3", "4", "5", "6", "17", "18", "20", "40", "42-4", "43"])
    pend = pending_items(p, AS_OF)
    assert {(i["article_no"], i["scope"], i["effective_date"]) for i in pend} == {
        ("3", "appendix", "2027-01-01"), ("4", "appendix", "2027-01-01"), ("5", "appendix", "2027-01-01")}
    assert p["default_date"] == "2026-07-01" and p["max_date"] == "2027-01-01"


def test_in_force_note_has_no_pending_and_deleted_are_excluded():
    p = parse_effective_note(NOTE_INFORCE, ["7", "9", "9-1", "12"])
    assert pending_items(p, AS_OF) == []
    deleted = parse_effective_note("一百十五年六月二十六日刪除第 5 條條文，自一百十六年一月一日施行。", ["5"])
    assert pending_items(deleted, AS_OF) == []


def test_undetermined_and_empty_and_unparsed():
    assert parse_effective_note("施行日期以命令定之。")["kind"] == "undetermined"
    assert parse_effective_note("")["kind"] == "empty" and parse_effective_note(None)["kind"] == "empty"
    assert parse_effective_note("一些無法解析的文字")["kind"] == "unparsed"


def test_consistency_cross_check():
    p = parse_effective_note(NOTE_HEALTH, [str(n) for n in range(1, 30)])
    assert consistency(p, "20280101")["consistent"] is True
    assert consistency(p, "20270701")["consistent"] is False
    assert consistency(parse_effective_note(NOTE_INFORCE, []), "20260101")["consistent"] is True


def test_normalize_removes_whitespace():
    assert normalize(" 第 2、9\r\n條 ") == "第2、9條"


def test_script_is_read_only_and_does_not_import_neo4j_offline():
    src = (ROOT / "scripts" / "analysis" / "kg4_pending_effect_analysis.py").read_text(encoding="utf-8")
    for block in re.findall(r'"""\s*(MATCH.*?)"""', src, flags=re.S):
        assert not re.search(r"\b(SET|CREATE|MERGE|DELETE|REMOVE|CALL)\b", block)
    top = src.split("def main", 1)[0]
    assert "import neo4j" not in top and "from neo4j" not in top
    assert "embedding_provider" not in src.replace("embedding_provider_called", "")
