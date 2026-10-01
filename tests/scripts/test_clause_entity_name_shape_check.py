"""報告225 Q3：`clause_entity_name_shape_check.py` 單元測試（假資料）＋真實保存資料一致性。"""

import importlib.util
import json
from pathlib import Path

from services import semantic_marks as sm

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("clause_entity_name_shape_check", _ROOT / "scripts" / "analysis" / "clause_entity_name_shape_check.py")
chk = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(chk)

STRONG_NAME = "勞工在同一雇主繼續工作滿五年以上者"  # 17 字，有特徵
LONG_PLAIN = "中華民國勞動部勞工保險局"             # 12 字，無特徵
LONG20 = "甲" * 20


def _ents():
    return [{"name": STRONG_NAME, "type": "概念"}, {"name": LONG_PLAIN, "type": "Organization"}, {"name": LONG20, "type": "概念"}]


def test_recompute_counts_by_threshold():
    r = chk.recompute(_ents(), 12)
    assert (r["suspected"], r["strong"], r["length_only"], r["concept"], r["non_concept"]) == (3, 1, 2, 2, 1)
    assert r["features"]["條文用語"] == 1
    r20 = chk.recompute(_ents(), 20)
    assert r20["suspected"] == 1 and r20["length_only"] == 1 and r20["strong"] == 0


def _quant(ents):
    out = {"summary": {"by_threshold": {}}, "groups": {}}
    for th in (12, 20):
        r = chk.recompute([e for e in ents if len(e["name"]) >= th], th)
        out["summary"]["by_threshold"][str(th)] = {
            "count": r["suspected"], "strong_candidates": r["strong"], "concept": r["concept"],
            "non_concept": r["non_concept"], "features": r["features"]}
    out["groups"]["strong(len>=12+特徵)"] = {"count": chk.recompute(ents, 12)["strong"]}
    return out


def _sample(n=50):
    return [{"name": "甲" * 12, "length": 12} for _ in range(n)]


def test_compare_all_consistent_and_detects_mismatch():
    ents = _ents()
    rows = chk.compare(_quant(ents), ents, _sample())
    assert all(r["status"] == "一致" for r in rows)
    bad = _quant(ents)
    bad["summary"]["by_threshold"]["12"]["strong_candidates"] += 1  # 故意不一致
    rows2 = chk.compare(bad, ents, _sample())
    assert any(r["status"] == "不一致" and "強候選" in r["item"] for r in rows2)
    assert any(r["status"] == "不一致" for r in chk.compare(_quant(ents), ents, _sample(49)))  # 樣本數不對


def test_sample_shape_counts():
    assert chk.sample_shape_counts([{"name": STRONG_NAME}, {"name": LONG_PLAIN}, {"name": "短"}]) == {
        sm.NAME_SHAPE_CLAUSE_STRONG: 1, sm.NAME_SHAPE_CLAUSE_LENGTH_ONLY: 1, sm.NAME_SHAPE_NOT_CLAUSE: 1}


def test_real_saved_data_is_consistent_with_report223():
    """真實已保存資料（無需連線）：Q1 函式重算與報告223 O1 數字逐項一致。"""
    quant = json.loads(chk.QUANT.read_text(encoding="utf-8"))
    ents = json.loads(chk.NAMES.read_text(encoding="utf-8"))["entities"]
    sample = json.loads(chk.SAMPLE.read_text(encoding="utf-8"))["records"]
    rows = chk.compare(quant, ents, sample)
    assert rows and all(r["status"] == "一致" for r in rows), [r for r in rows if r["status"] != "一致"]
