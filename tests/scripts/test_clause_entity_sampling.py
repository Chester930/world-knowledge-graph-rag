"""報告223 O2：`clause_entity_sampling.py` 單元測試（假母體，不連 DB、不讀 kg-runtime）。"""

import csv
import importlib.util
import json
import os
from pathlib import Path

import pytest

_ENV_BEFORE = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("clause_entity_sampling", _ROOT / "scripts" / "analysis" / "clause_entity_sampling.py")
cs = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cs)


def _pool(n=60):
    ents = [{"name": f"勞工在同一雇主繼續工作滿五年以上者{i:03d}", "type": "概念"} for i in range(n)]
    ents.append({"name": "短名", "type": "組織"})  # 不在母體
    edges = []
    for i, e in enumerate(ents[:n]):
        cites = json.dumps([{"source_doc_id": f"d{i % 3}", "source_svo_chunk_index": i, "verb": "應", "source_sentence_start": 1,
                             "source_sentence_end": 1}])
        edges.append({"subject": e["name"], "object": "短名", "rel_type": "R", "citations": cites})
    return {"entities": ents, "edges": edges}


def test_import_does_not_touch_os_environ():
    assert {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"} == _ENV_BEFORE


def test_population_filters_by_length():
    pop = cs.population(_pool()["entities"])
    assert len(pop) == 60 and all(len(e["name"]) >= cs.MIN_LEN for e in pop)
    assert cs.population([{"name": ""}, {"name": None}, {"name": "x" * 12}]) == [{"name": "x" * 12}]


def test_build_material_is_deterministic_numbered_and_has_degree_docs_facts():
    doc_by_id = {"d0": "文件0", "d1": "文件1", "d2": "文件2"}
    m1, pop = cs.build_material(_pool(), doc_by_id, seed=7, size=50)
    m2, _ = cs.build_material(_pool(), doc_by_id, seed=7, size=50)
    assert pop == 60 and len(m1) == 50 and m1 == m2  # 固定種子可重現
    assert [r["sample_number"] for r in m1] == list(range(1, 51))
    assert m1 == sorted(m1, key=lambda r: (r["name"], r["type"]))
    r = m1[0]
    assert r["degree"] == 1 and r["doc_count"] == 1 and len(r["facts"]) == 1
    assert r["facts"][0]["entity_role"] == "主詞" and r["facts"][0]["document"].startswith("文件")
    m3, _ = cs.build_material(_pool(), doc_by_id, seed=8, size=50)
    assert [r["name"] for r in m3] != [r["name"] for r in m1]  # 不同種子結果不同


def test_build_material_rejects_population_smaller_than_size():
    with pytest.raises(ValueError):
        cs.build_material({"entities": [{"name": "x" * 12, "type": "概念"}], "edges": []}, {}, size=50)


def _mat(n):
    return [{"sample_number": i, "sample_key": f"k{i}|概念", "name": f"n{i}", "type": "概念", "length": 12, "degree": 1,
             "doc_count": 1, "fact_count_included": 0, "facts": []} for i in range(1, n + 1)]


def test_apply_annotations_defaults_question_first_and_invalid_label():
    ann = {"2": {"label": "s", "question": False, "reason": "r2"}, "3": {"label": "L", "question": True, "reason": "r3"}}
    out = cs.apply_annotations(_mat(3), ann)
    assert [r["sample_number"] for r in out] == [1, 3, 2]  # 缺標註（1）與疑問（3）置前
    assert out[0]["label"] == "U" and out[0]["question"] is True and "尚未完成" in out[0]["reason"]
    assert out[2]["label"] == "S"  # 大小寫不拘
    with pytest.raises(ValueError):
        cs.apply_annotations(_mat(1), {"1": {"label": "P"}})


def test_summarize_counts_shares_and_wilson():
    recs = [{"label": "S", "question": False}] * 3 + [{"label": "L", "question": True}] + [{"label": "U", "question": True}]
    s = cs.summarize(recs)
    assert s["total"] == 5 and s["labels"]["S"]["count"] == 3 and s["labels"]["S"]["share"] == 0.6
    lo, hi = s["labels"]["S"]["wilson_95"]
    assert 0 < lo < 0.6 < hi < 1
    assert s["question_flags"]["count"] == 2 and "未經使用者確認" in s["status"]
    e = cs.summarize([])
    assert e["total"] == 0 and e["labels"]["S"]["share"] is None and e["labels"]["S"]["wilson_95"] is None


def test_write_outputs_marks_draft_and_orders_question_first(tmp_path):
    ann = {"1": {"label": "S", "question": False, "reason": "甲"}, "2": {"label": "L", "question": True, "reason": "乙"}}
    recs = cs.apply_annotations(_mat(2), ann)
    cs.write_outputs(recs, csv_path=tmp_path / "a.csv", review_path=tmp_path / "a.md", stats_path=tmp_path / "a.json",
                     seed=1, pop_size=99)
    rows = list(csv.DictReader((tmp_path / "a.csv").open(encoding="utf-8-sig")))
    assert [r["編號"] for r in rows] == ["2", "1"] and all("未經使用者確認" in r["標註狀態"] for r in rows)
    md = (tmp_path / "a.md").read_text(encoding="utf-8")
    assert "未經使用者確認" in md and md.index("| 2 |") < md.index("| 1 |")
    stats = json.loads((tmp_path / "a.json").read_text(encoding="utf-8"))
    assert stats["seed"] == 1 and stats["population_size"] == 99 and stats["total"] == 2
