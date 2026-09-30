"""N9 G1／G2 搬移驗收（報告168 W1）：逐字、重新匯出身分、反向依賴、外部使用者名稱仍可取得。"""

import ast
import importlib
import json

import pytest

from tests.services.n4_symbols import top_level_defs
from tests.services.n9_symbols import BASELINE, N9_NAMES, REPO

RETRIEVAL = REPO / "services" / "retrieval"
EXPECTED_MOVED = 8  # 每一刀更新；最後一刀必須是 8


def _locations() -> dict[str, tuple[str, str]]:
    loc = {}
    for f in sorted(RETRIEVAL.glob("*.py")):
        if f.name == "__init__.py":
            continue
        for name, (text, _) in top_level_defs(f).items():
            if name in N9_NAMES:
                loc[name] = (f.stem, text)
    return loc


LOC = _locations()
BASE = json.loads(BASELINE.read_text(encoding="utf-8"))


def test_moved_symbol_count():
    assert len(LOC) == EXPECTED_MOVED


@pytest.mark.parametrize("name", sorted(LOC))
def test_symbol_source_verbatim(name):
    assert LOC[name][1] == BASE[name]


@pytest.mark.parametrize("name", sorted(LOC))
def test_reexport_identity(name):
    from services import svo_service

    mod = importlib.import_module(f"services.retrieval.{LOC[name][0]}")
    assert getattr(svo_service, name) is getattr(mod, name)


def test_svo_service_no_longer_defines_moved_symbols():
    local = top_level_defs(REPO / "services" / "svo_service.py")
    assert not (set(LOC) & set(local))


def test_retrieval_does_not_import_svo_service():
    for f in RETRIEVAL.glob("*.py"):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Import):
                mods = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                mods = [(n.module or "")] + [f"{n.module}.{a.name}" for a in n.names]
            else:
                continue
            assert not any(m == "services.svo_service" or m.startswith("services.svo_service.") for m in mods), f.name


def test_all_n9_names_still_available_from_svo_service():
    """外部使用者（core/kg_config golden 錨點、run_rq1_comparison、根目錄腳本、測試）以舊名稱取得。"""
    from services import svo_service

    for name in N9_NAMES:
        assert hasattr(svo_service, name), name


def test_golden_anchor_constants_equal_kgconfig_defaults():
    from core.kg_config import KGConfig
    from services import svo_service

    cfg = KGConfig()
    assert cfg.bfs.expand_when_below == svo_service._BFS_EXPAND_WHEN_BELOW
    assert cfg.bfs.prize_top_k == svo_service._BFS_PRIZE_TOP_K


def test_root_script_imports_from_svo_service_still_resolve():
    """根目錄 `_trace_aggr16_candidate_path_20260918.py` 以 from-import 取用私有輔助；只做 AST 檢查名稱仍可取得，不執行該腳本。"""
    from services import svo_service

    tree = ast.parse((REPO / "_trace_aggr16_candidate_path_20260918.py").read_text(encoding="utf-8"))
    names = [a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "services.svo_service" for a in n.names]
    assert names, "預期該腳本有 from services.svo_service import …"
    for name in names:
        assert hasattr(svo_service, name), name
