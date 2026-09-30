"""論文與程式現況差異盤點（報告171 X1；比照報告152）。純靜態，只讀 ``docs/論文/*.md`` 與程式碼符號表。

分類（逐行）：
  A  行內帶 ``svo_service`` 路徑（``svo_service.py``／``services/svo_service``／``svo_service::``…）且同一行出現被搬移符號名稱
  A? 行內出現被搬移符號名稱，且前後 ±N 行內有 ``svo_service`` 路徑（路徑與名稱不同行；需人工判定）
  B  只出現符號名稱、附近無 svo_service 路徑
  D  ``03_變更紀錄.md`` 內的行（既有歷史條目，不改）
輸出 JSON（每行命中）與統計。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tests.services.n4_symbols import N4_NAMES  # noqa: E402
from tests.services.n9_symbols import N9_NAMES  # noqa: E402

PATH_RE = re.compile(r"svo_service")
NEAR = 3


def locations() -> dict[str, str]:
    import ast

    loc: dict[str, str] = {}
    for pkg, names in (("extraction", N4_NAMES), ("retrieval", N9_NAMES)):
        for f in sorted((REPO / "services" / pkg).glob("*.py")):
            if f.name == "__init__.py":
                continue
            tree = ast.parse(f.read_text(encoding="utf-8"))
            for n in tree.body:
                nms = []
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    nms = [n.name]
                elif isinstance(n, ast.Assign):
                    nms = [t.id for t in n.targets if isinstance(t, ast.Name)]
                elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                    nms = [n.target.id]
                for nm in nms:
                    if nm in names:
                        loc[nm] = f"services/{pkg}/{f.name}"
    return loc


def scan(thesis_dir: Path) -> dict:
    loc = locations()
    names = sorted(loc, key=len, reverse=True)
    name_re = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(re.escape(n) for n in names) + r")(?![A-Za-z0-9_])")
    rows = []
    for md in sorted(thesis_dir.glob("*.md")):
        lines = md.read_text(encoding="utf-8").split("\n")
        for i, line in enumerate(lines, 1):
            hits = sorted({m.group(1) for m in name_re.finditer(line)})
            if not hits:
                continue
            if md.name == "03_變更紀錄.md":
                cat = "D"
            elif PATH_RE.search(line):
                cat = "A"
            elif any(PATH_RE.search(lines[j]) for j in range(max(0, i - 1 - NEAR), min(len(lines), i + NEAR))):
                cat = "A?"
            else:
                cat = "B"
            rows.append({"file": md.name, "line": i, "cat": cat, "symbols": hits,
                         "new_locations": sorted({loc[h] for h in hits}), "text": line.strip()[:220]})
    return {"symbols": loc, "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--thesis", type=Path, default=REPO / "docs" / "論文")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    data = scan(a.thesis)
    text = json.dumps(data, ensure_ascii=False, indent=1)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
