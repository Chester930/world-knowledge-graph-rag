"""報告231 S2：玩具圖譜示範腳本——以斷言鎖定示範結果（全為虛構資料）。"""

import ast
import importlib.util
import json
from pathlib import Path

from services import relation_lifecycle as rl

_ROOT = Path(__file__).resolve().parents[2]
_PATH = _ROOT / "scripts" / "analysis" / "relation_lifecycle_demo.py"
_SPEC = importlib.util.spec_from_file_location("relation_lifecycle_demo", _PATH)
demo_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(demo_mod)

DEMO = demo_mod.build_demo()
INST = {r["instance_id"]: r for s in DEMO["scenarios"] for r in s["instances"]}
SCEN = {s["no"]: s for s in DEMO["scenarios"]}


def test_counts_cover_all_ten_scenarios():
    assert DEMO["counts"] == {"scenarios": 10, "instances": 16, "illegal_events": 4}
    assert sorted(SCEN) == list(range(1, 11))


def test_final_states_per_instance_are_locked():
    expected = {
        "S1-a": rl.VALID, "S2-v1": rl.SUPERSEDED, "S2-v2": rl.VALID, "S3-a": rl.VALID, "S4-a": rl.VALID,
        "S5-a": rl.SUPERSEDED, "S6-a": rl.REJECTED, "S7-a": rl.SUPERSEDED, "S7-b": rl.REJECTED, "S7-c": None,
        "S8-a": rl.VALID, "S8-b": rl.VALID, "S9-dated": rl.VALID, "S9-undated": rl.VALID, "S9-mixed": rl.VALID,
        "S10-a": rl.TERMINATED,
    }
    assert {k: v["final_state"] for k, v in INST.items()} == expected


def test_amendment_new_version_walks_candidate_then_valid_and_exclusivity_passes():
    v2 = INST["S2-v2"]
    assert [s["to"] for s in v2["steps"]] == [rl.CANDIDATE, rl.VALID]
    assert INST["S2-v1"]["key"] == v2["key"]  # 同鍵、不同實例
    assert SCEN[2]["exclusivity_violations"] == []


def test_terminate_then_reactivate_is_one_instance_with_two_valid_periods():
    steps = INST["S3-a"]["steps"]
    assert [s["to"] for s in steps] == [rl.CANDIDATE, rl.VALID, rl.TERMINATED, rl.VALID] and all(s["ok"] for s in steps)


def test_dispute_two_rulings():
    assert [s["to"] for s in INST["S4-a"]["steps"]][-2:] == [rl.DISPUTED, rl.VALID]
    assert [s["to"] for s in INST["S5-a"]["steps"]][-2:] == [rl.DISPUTED, rl.SUPERSEDED]


def test_illegal_transitions_are_rejected_with_reasons_and_first_illegal_recorded():
    a = INST["S7-a"]
    assert [s["ok"] for s in a["steps"]] == [True, True, True, False, False]
    assert a["first_illegal"]["step"] == 4 and a["first_illegal"]["event"] == rl.REACTIVATE and "終點狀態" in a["first_illegal"]["reason"]
    assert INST["S7-b"]["first_illegal"]["step"] == 3 and "已駁回" in INST["S7-b"]["first_illegal"]["reason"]
    c = INST["S7-c"]
    assert c["final_state"] is None and "尚未建立" in c["first_illegal"]["reason"]
    assert INST["S1-a"]["first_illegal"] is None and INST["S1-a"]["ok"]


def test_exclusivity_violation_detected_only_in_scenario_8():
    assert [v["instance_ids"] for v in SCEN[8]["exclusivity_violations"]] == [["S8-a", "S8-b"]]
    assert all(not s["exclusivity_violations"] for n, s in SCEN.items() if n != 8)
    assert [v["key"] for v in DEMO["exclusivity_whole_toy_graph"]] == [["申公司", "應給", "酉獎金"]]


def test_dated_undated_and_mixed_have_identical_transitions():
    assert DEMO["dated_vs_undated_identical_transitions"] is True
    assert INST["S9-undated"]["steps"][0]["date"] is None and INST["S9-dated"]["steps"][0]["date"] == "2020-01-01"
    assert INST["S9-mixed"]["steps"][1]["date"] is None and INST["S9-mixed"]["steps"][2]["date"] == "2021-03-01"


def test_extension_example_runs_and_bad_extensions_are_rejected():
    assert DEMO["extension"]["valid"] is True
    steps = INST["S10-a"]["steps"]
    assert INST["S10-a"]["lifecycle"] == "虛構-暫停適用" and all(s["ok"] for s in steps)
    assert [s["to"] for s in steps] == [rl.CANDIDATE, rl.VALID, "暫停", rl.VALID, "暫停", rl.TERMINATED]
    bad = DEMO["bad_extensions"]
    assert set(bad) == {"終點狀態加轉出", "改道核心轉換", "刪除核心轉換"} and all(not v["ok"] for v in bad.values())
    assert any("終點狀態「已被取代」不得有任何轉出" in e for e in bad["終點狀態加轉出"]["errors"])
    assert any("不得改寫或重述核心轉換" in e for e in bad["改道核心轉換"]["errors"])
    assert any("不得刪除核心轉換" in e for e in bad["刪除核心轉換"]["errors"])


def test_replay_is_deterministic_and_build_demo_is_repeatable():
    assert DEMO["all_deterministic"] is True
    assert demo_mod.build_demo() == DEMO


def test_markdown_and_json_carry_fictional_disclaimer_and_match_committed_outputs(tmp_path):
    md = demo_mod.render_markdown(DEMO)
    assert md.count("虛構玩具資料") >= 2 and "不代表任何真實法規" in md and "KG#4" in md
    assert "不代表任何真實法規" in DEMO["disclaimer"]
    out_j, out_m = tmp_path / "d.json", tmp_path / "d.md"
    assert demo_mod.main(["--out-json", str(out_j), "--out-md", str(out_m)]) == 0
    assert json.loads(out_j.read_text(encoding="utf-8")) == json.loads(json.dumps(DEMO, ensure_ascii=False))
    assert out_m.read_text(encoding="utf-8") == md
    # 已提交的示範輸出與目前結果一致（防止資料／規則改了卻沒重產）
    assert json.loads(demo_mod.OUT_JSON.read_text(encoding="utf-8")) == json.loads(json.dumps(DEMO, ensure_ascii=False))
    assert demo_mod.OUT_MD.read_text(encoding="utf-8").replace("\r\n", "\n") == md


def test_script_reads_no_files_and_touches_no_database():
    tree = ast.parse(_PATH.read_text(encoding="utf-8"))
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not attrs & {"read_text", "read_bytes", "GraphDatabase", "environ", "getenv"} and "open" not in names
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not mods & {"neo4j", "core", "routers", "repositories", "requests", "httpx"}
