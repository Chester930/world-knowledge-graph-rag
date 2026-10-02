"""報告255 溯源腳本：純函式與結構守衛（不連線）。"""
import re
from pathlib import Path

from scripts.analysis.kg4_resync_audit import classify
from scripts.analysis.kg4_resync_trace import entity_alias_conflicts, evidence, norm

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "analysis" / "kg4_resync_trace.py"


def test_norm_strips_all_whitespace():
    assert norm(" 本 辦　法\n") == "本辦法"
    assert norm(None) == ""


def test_evidence_text_four_outcomes():
    text = norm("婚生子女之認領")
    assert evidence("婚生子女", "非婚生子女", text, [])["text"] == "flat_only"
    assert evidence("認領", "婚生子女", text, [])["text"] == "both"
    assert evidence("甲", "婚生子女", text, [])["text"] == "new_only"
    assert evidence("甲", "乙", text, [])["text"] == "neither"


def test_evidence_text_unknown_when_file_missing():
    assert evidence("甲", "乙", None, [])["text"] == "unknown"


def test_evidence_forms_use_normalized_membership():
    assert evidence("甲", "乙", None, ["甲 "])["forms"] == "flat_only"
    assert evidence("甲", "乙", None, ["乙"])["forms"] == "new_only"
    assert evidence("甲", "乙", None, ["甲", "乙"])["forms"] == "both"
    assert evidence("甲", "乙", None, [])["forms"] == "neither"


def test_entity_alias_conflicts_counts_and_facts():
    entities = [
        {"eid": "e1", "name": "非婚生子女", "forms": ["婚生子女", "非婚生子女"]},
        {"eid": "e2", "name": "勞雇關係", "forms": ["勞雇關係"]},          # 無其他別名：不計
        {"eid": "e3", "name": "加強勞雇關係", "forms": ["勞雇關係"]},
    ]
    res = entity_alias_conflicts(entities, {"e1": 5, "e2": 9, "e3": 2}, classify)
    assert res["entities_with_other_forms"] == 2
    assert res["entities_by_conflict_category"] == {"critical_token_change": 1, "expand": 1}
    assert res["facts_touching_entities_by_category"] == {"critical_token_change": 5, "expand": 2}


def test_script_is_read_only_and_has_no_embedding_calls():
    body = "\n".join(ln for ln in SCRIPT.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#"))
    cypher_blocks = re.findall(r'"""\s*(MATCH.*?)"""', body, flags=re.S)
    assert cypher_blocks
    for block in cypher_blocks:
        assert not re.search(r"\b(SET|CREATE|MERGE|DELETE|REMOVE|CALL)\b", block)
    assert "core.providers" not in body
    assert "embedding_provider" not in body.replace("embedding_provider_called", "")
