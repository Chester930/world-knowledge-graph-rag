"""報告256 曝險量測腳本：純函式與結構守衛（不連線）。"""
import re
from pathlib import Path

from scripts.analysis.kg4_conflict_exposure import clean, diverged, is_exposed, question_group, severe_entities
from scripts.analysis.kg4_resync_audit import classify

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "analysis" / "kg4_conflict_exposure.py"


def test_clean_removes_whitespace():
    assert clean(" 甲 乙\n") == "甲乙"
    assert clean(None) == ""


def test_question_group_mapping():
    assert question_group("stable_pass") == "pass"
    assert question_group("single_pass") == "pass"
    assert question_group("stable_fail") == "fail"
    assert question_group("unstable") == "unstable"
    assert question_group("???") == "other"


def test_severe_entities_keeps_only_critical_and_law_ref():
    entities = [
        {"eid": "e1", "name": "非婚生子女", "forms": ["婚生子女", "非婚生子女"]},       # critical
        {"eid": "e2", "name": "本辦法未規定者", "forms": ["本法未規定者"]},            # law_ref
        {"eid": "e3", "name": "加強勞雇關係", "forms": ["勞雇關係"]},                  # expand → 排除
        {"eid": "e4", "name": "甲", "forms": []},
    ]
    res = severe_entities(entities, classify)
    assert set(res) == {"e1", "e2"}
    assert res["e2"] == {"law_ref_change"}


def test_is_exposed_handles_none():
    severe = {"e1": {"critical_token_change"}}
    assert is_exposed(["e1", None], severe)
    assert not is_exposed([None, "e9"], severe)


def test_diverged_detects_flat_vs_entity_name():
    assert diverged({"flat_s": "甲", "s_name": "乙", "flat_o": "丙", "o_name": "丙"})
    assert diverged({"flat_s": "甲", "s_name": "甲", "flat_o": "丙", "o_name": "丁"})
    assert not diverged({"flat_s": "甲", "s_name": "甲", "flat_o": "丙", "o_name": "丙"})
    assert not diverged({"flat_s": "甲", "s_name": None, "flat_o": "丙", "o_name": None})


def test_script_is_read_only_and_has_no_embedding_calls():
    body = "\n".join(ln for ln in SCRIPT.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#"))
    for block in re.findall(r'"""\s*(MATCH.*?)"""', body, flags=re.S):
        assert not re.search(r"\b(SET|CREATE|MERGE|DELETE|REMOVE|CALL)\b", block)
    assert "core.providers" not in body
    assert "embedding_provider" not in body.replace("embedding_provider_called", "")
