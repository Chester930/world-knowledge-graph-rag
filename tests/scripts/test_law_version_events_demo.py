"""報告235 P2：真實 fixture 示範輸出測試。"""

import ast
import importlib.util
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PATH = _ROOT / "scripts" / "analysis" / "law_version_events_demo.py"
_SPEC = importlib.util.spec_from_file_location("law_version_events_demo", _PATH)
demo_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(demo_mod)


DEMO = demo_mod.build_demo()


def test_demo_counts_and_required_real_cases():
    assert DEMO["prototype"]["counts"] == {
        "chains": 6, "versions": 12, "events": 30,
        "chains_with_anomalies": 6, "exclusivity_violation_count": 0,
    }
    required = {("N0030006", "7"), ("N0030006", "9"), ("N0030006", "12"),
                ("N0030001", "2"), ("N0030001", "3"), ("N0030001", "8")}
    actual = {(c["pcode"], c["article_no"]) for c in DEMO["prototype"]["chains"]}
    assert required <= actual


def test_demo_output_is_deterministic_and_reproducible(tmp_path):
    assert demo_mod.build_demo() == DEMO
    out_json, out_report = tmp_path / "demo.json", tmp_path / "demo.md"
    assert demo_mod.main(["--out-json", str(out_json), "--out-report", str(out_report)]) == 0
    assert json.loads(out_json.read_text(encoding="utf-8")) == DEMO
    assert out_report.read_text(encoding="utf-8") == demo_mod.render_report(DEMO)


def test_demo_script_reads_fixture_only_and_does_not_use_database_or_network():
    tree = ast.parse(_PATH.read_text(encoding="utf-8"))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    modules = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    modules |= {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "open" not in names and not attrs & {"GraphDatabase", "environ", "getenv"}
    assert not modules & {"neo4j", "requests", "httpx", "ollama"}
