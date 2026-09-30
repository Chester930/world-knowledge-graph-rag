"""N4 搬移驗收（報告160 U1）：逐字、重新匯出身分、反向依賴、資料檔定位。"""

import ast
import importlib
import json
from pathlib import Path

import pytest

from tests.services.n4_symbols import BASELINE, N4_NAMES, REPO, top_level_defs

EXTRACTION = REPO / "services" / "extraction"
# 搬移時唯一允許與搬移前不同的符號（路徑定位修正，見報告160 U1 設計 #3）
ALLOWED_DIFF = {"_EXTENDED_ENTITY_TYPES_PATH"}
# 目前已搬移的符號數；每一刀更新，最後一刀必須是 62
EXPECTED_MOVED = 54


def _locations() -> dict[str, tuple[str, str]]:
    loc = {}
    for f in sorted(EXTRACTION.glob("*.py")):
        if f.name == "__init__.py":
            continue
        defs = top_level_defs(f)
        for name, (text, _) in defs.items():
            if name in N4_NAMES:
                loc[name] = (f.stem, text)
    return loc


LOC = _locations()
BASE = json.loads(BASELINE.read_text(encoding="utf-8"))


def test_moved_symbol_count():
    assert len(LOC) == EXPECTED_MOVED


@pytest.mark.parametrize("name", sorted(LOC))
def test_symbol_source_verbatim(name):
    if name in ALLOWED_DIFF:
        assert LOC[name][1] == '_EXTENDED_ENTITY_TYPES_PATH = _locate_data_dir() / "schema_org_entity_types.json"'
    else:
        assert LOC[name][1] == BASE[name]


@pytest.mark.parametrize("name", sorted(LOC))
def test_reexport_identity(name):
    from services import svo_service

    mod = importlib.import_module(f"services.extraction.{LOC[name][0]}")
    assert getattr(svo_service, name) is getattr(mod, name)


def test_svo_service_no_longer_defines_moved_symbols():
    local = top_level_defs(REPO / "services" / "svo_service.py")
    assert not (set(LOC) & set(local))


def test_extraction_does_not_import_svo_service():
    for f in EXTRACTION.glob("*.py"):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Import):
                mods = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                mods = [(n.module or "")] + [f"{n.module}.{a.name}" for a in n.names]
            else:
                continue
            assert not any(m == "services.svo_service" or m.startswith("services.svo_service.") for m in mods), f.name



def test_extended_entity_type_lookup_is_loaded_and_non_empty():
    from services.extraction import prompt

    assert prompt._EXTENDED_ENTITY_TYPES_PATH.is_file()
    assert prompt._EXTENDED_ENTITY_TYPES_PATH == REPO / "data" / "schema_org_entity_types.json"
    lookup = prompt._load_extended_entity_type_lookup()
    assert len(lookup) >= 900  # schema.org 939 類
    assert prompt.resolve_entity_type("Local Business") != ""
