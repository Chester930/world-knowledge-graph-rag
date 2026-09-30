"""N4 的 62 個符號清單與原始碼片段擷取（報告160 U1；清單來自報告158 §3／`n4_dependency_inventory.py`）。

``python -m tests.services.n4_symbols --write-baseline`` 在**搬移前**擷取 ``services/svo_service.py`` 中各符號的
逐字原始碼（含裝飾器與符號內部註解），存成 baseline；搬移後由 ``test_n4_move.py`` 逐字比對。
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "analysis"))

from n4_dependency_inventory import N4_NAMES  # noqa: E402

BASELINE = Path(__file__).parent / "fixtures" / "n4_symbol_source_baseline.json"


def top_level_defs(path: Path) -> dict[str, tuple[str, ast.AST]]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    lines = src.splitlines()
    out: dict[str, tuple[str, ast.AST]] = {}
    for n in tree.body:
        names: list[str] = []
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [n.name]
        elif isinstance(n, ast.Assign):
            names = [t.id for t in n.targets if isinstance(t, ast.Name)]
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            names = [n.target.id]
        if not names:
            continue
        start = min([n.lineno] + [d.lineno for d in getattr(n, "decorator_list", [])])
        text = "\n".join(lines[start - 1:n.end_lineno])
        for name in names:
            out[name] = (text, n)
    return out


def snapshot(path: Path) -> dict[str, str]:
    defs = top_level_defs(path)
    return {name: defs[name][0] for name in N4_NAMES}


if __name__ == "__main__":
    if "--write-baseline" in sys.argv:
        snap = snapshot(REPO / "services" / "svo_service.py")
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
        print(len(snap), "symbols")
