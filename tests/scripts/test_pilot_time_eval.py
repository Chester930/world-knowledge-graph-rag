"""報告266 評測執行器：判定與彙總的純計算、不連線守衛。"""
import json
import subprocess
import sys
from pathlib import Path

from scripts.analysis.pilot_time_eval import evaluate_question, summarize

ROOT = Path(__file__).resolve().parents[2]


def _q(kind="substantive", conflict=False, role="old", acceptable=None):
    return {"id": "Q", "pair_kind": kind, "is_conflict": conflict, "expected_role": role, "law_id": "L", "article_no": "第 1 條",
            "expected_valid_from": "2000-01-01", "other_valid_from": "2020-01-01",
            "acceptable_valid_froms": acceptable or ["2000-01-01"]}


def _r(valid_from, law="L", art="第 1 條"):
    return {"law_id": law, "article_no": art, "valid_from": valid_from}


def test_hit_without_leak():
    j = evaluate_question(_q(), [_r("2000-01-01"), _r("2000-01-01", art="第 2 條")])
    assert j["hit"] is True and j["leak"] is False and j["n_target"] == 1


def test_leak_when_other_version_returned():
    j = evaluate_question(_q(), [_r("2000-01-01"), _r("2020-01-01")])
    assert j["hit"] is True and j["leak"] is True


def test_miss_when_only_other_law_or_article():
    j = evaluate_question(_q(), [_r("2000-01-01", law="OTHER"), _r("2000-01-01", art="第 9 條")])
    assert j["hit"] is False and j["leak"] is False and j["n_target"] == 0


def test_control_uses_acceptable_versions_and_has_no_leak():
    j = evaluate_question(_q(kind="same_hash", acceptable=["2000-01-01", "2020-01-01"]), [_r("2020-01-01")])
    assert j["hit"] is True and j["leak"] is None


def _per(rows_asof, rows_naive):
    return {"asof": rows_asof, "naive": rows_naive}


def _row(kind="substantive", conflict=False, hit=True, leak=False):
    return {"pair_kind": kind, "is_conflict": conflict, "hit": hit, "leak": (None if kind != "substantive" else leak)}


def test_summarize_primary_pass_and_conflict_separate():
    asof = [_row(), _row(), _row(conflict=True, leak=True), _row("same_hash")]
    naive = [_row(leak=True), _row(hit=False), _row(conflict=True, leak=True), _row("same_hash")]
    s = summarize(_per(asof, naive))
    assert s["primary"]["asof"] == {"n": 2, "hit_rate": 1.0, "leak_rate": 0.0}
    assert s["primary"]["naive"]["hit_rate"] == 0.5 and s["primary"]["naive"]["leak_rate"] == 0.5
    assert s["conflict"]["asof"]["n"] == 1 and s["control"]["asof"]["n"] == 1
    assert s["verdict"]["primary_pass"] is True and s["verdict"]["control_hit_equal"] is True
    assert s["verdict"]["secondary_hit_rate_diff_asof_minus_naive"] == 0.5


def test_summarize_fails_when_asof_leaks_or_loses_hits():
    leaky = [_row(leak=True)] * 2
    s = summarize(_per(leaky, [_row()] * 2))
    assert s["verdict"]["primary_pass"] is False and s["verdict"]["asof_leak_rate_le_0.05"] is False
    lossy = [_row(hit=False)] * 2
    s2 = summarize(_per(lossy, [_row()] * 2))
    assert s2["verdict"]["asof_hit_rate_ge_naive"] is False and s2["verdict"]["primary_pass"] is False


def test_plan_mode_does_not_connect_and_does_not_import_neo4j():
    code = ("import sys; sys.argv=['x']; "
            "from scripts.analysis import pilot_time_eval as m; m.main([]); "
            "assert 'neo4j' not in sys.modules and 'core.config' not in sys.modules")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout.strip().splitlines()[-1])["connects"] is False
