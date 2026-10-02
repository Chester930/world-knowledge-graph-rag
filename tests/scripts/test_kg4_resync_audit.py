"""報告254 審核腳本：分類函式與結構守衛（不連線）。"""
import json
import re
from pathlib import Path

from scripts.analysis.kg4_resync_audit import classify

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "analysis" / "kg4_resync_audit.py"


def test_classify_law_ref_change():
    assert classify("本法未規定者", "本辦法未規定者") == "law_ref_change"


def test_classify_critical_negation_and_number():
    assert classify("視為職業傷害", "不得視為職業傷害") == "critical_token_change"
    assert classify("一百一十", "一百一十五") == "critical_token_change"


def test_classify_expand_shrink_rewrite():
    assert classify("勞雇關係", "加強勞雇關係") == "expand"
    assert classify("加強勞雇關係", "勞雇關係") == "shrink"
    assert classify("差別待遇", "差別之待遇") == "rewrite"


def test_law_ref_has_priority_over_critical():
    assert classify("本法未規定者", "本辦法不得規定者") == "law_ref_change"


def test_script_is_read_only_and_has_no_embedding():
    src = SCRIPT.read_text(encoding="utf-8")
    code_lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith(("#", '"""'))]
    body = "\n".join(code_lines)
    assert not re.search(r"\b(SET|CREATE|MERGE|DELETE|REMOVE)\b", body)
    assert "embedding_provider" not in body.replace("embedding_provider_called", "")
    assert "core.providers" not in body


def test_labels_file_counts_are_consistent():
    labels = json.loads((ROOT / "data" / "analysis" / "kg4_resync_audit_labels_20261002.json").read_text(encoding="utf-8"))
    for cat, d in labels.items():
        if cat.startswith("_"):
            continue
        idx = d["W"] + d["D"] + d["N"] + d["G"]
        assert sorted(idx) == list(range(d["n"])), cat
