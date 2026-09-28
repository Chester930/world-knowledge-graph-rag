"""盤點：程式模組／頂層函式是否登記在論文 03/04，以及是否被非測試程式碼引用（報告96）。

用法：python scripts/analysis/thesis_code_coverage_inventory.py <repo根目錄> <輸出.json>

判定是「名稱是否出現在文字中」的寬鬆比對：出現即算登記／引用，所以只會低估缺漏、
不會誤報已登記項目為缺漏；反過來，常見名稱（如 `create_kg`）可能被誤算為已引用。
結果需人工複核，不可直接當成刪除清單。
"""
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1])
OUT = Path(sys.argv[2])

thesis03 = (ROOT / "docs/論文/03_系統設計與方法論.md").read_text(encoding="utf-8")
thesis04 = (ROOT / "docs/論文/04_系統實作.md").read_text(encoding="utf-8")
trace00 = (ROOT / "docs/論文/00_研究追溯對映表.md").read_text(encoding="utf-8")
thesis_other = "".join(
    p.read_text(encoding="utf-8") for p in (ROOT / "docs/論文").glob("0[5-7]_*.md")
)
reports = "".join(p.read_text(encoding="utf-8", errors="ignore") for p in (ROOT / "docs/報告").glob("*.md"))

SKIP_DIRS = {".git", ".claude", "node_modules", "tests", "__pycache__", ".venv", "venv", "data", "docs", "ui"}


def iter_py():
    for p in ROOT.rglob("*.py"):
        rel = p.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        yield p, rel


files = list(iter_py())
code_text = {rel.as_posix(): p.read_text(encoding="utf-8", errors="ignore") for p, rel in files}


def mentioned(token: str, text: str) -> bool:
    return re.search(r"(?<![A-Za-z0-9_])" + re.escape(token) + r"(?![A-Za-z0-9_])", text) is not None


def used_elsewhere(name: str, own: str) -> list[str]:
    hits = []
    for rel, txt in code_text.items():
        if rel == own:
            continue
        if mentioned(name, txt):
            hits.append(rel)
    return hits


def used_inside(name: str, own_text: str) -> int:
    return len(re.findall(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"\s*\(", own_text))


modules = []
functions = []
for p, rel in files:
    relp = rel.as_posix()
    stem = p.stem
    if stem == "__init__":
        continue
    txt = code_text[relp]
    mod_ref = [r for r in used_elsewhere(stem, relp)]
    modules.append({
        "module": relp,
        "lines": len([l for l in txt.splitlines() if l.strip()]),
        "in03": mentioned(stem, thesis03) or relp in thesis03,
        "in04": mentioned(stem, thesis04) or relp in thesis04,
        "in00": mentioned(stem, trace00),
        "in05_07": mentioned(stem, thesis_other),
        "in_reports": mentioned(stem, reports),
        "imported_by": len(mod_ref),
    })
    if not (relp.startswith("services/") or relp.startswith("routers/") or relp.startswith("repositories/")
            or relp.startswith("parser/") or relp.startswith("core/")):
        continue
    try:
        tree = ast.parse(txt)
    except SyntaxError:
        continue
    for node in tree.body:
        targets = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            targets = [node]
        for n in targets:
            name = n.name
            is_route = any(
                isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and isinstance(d.func.value, ast.Name)
                and d.func.value.id == "router" for d in getattr(n, "decorator_list", [])
            )
            ext = used_elsewhere(name, relp)
            functions.append({
                "module": relp,
                "name": name,
                "kind": type(n).__name__,
                "route": is_route,
                "in03": mentioned(name, thesis03),
                "in04": mentioned(name, thesis04),
                "in00": mentioned(name, trace00),
                "in_reports": mentioned(name, reports),
                "ext_refs": len(ext),
                "ext_files": ext[:6],
                "internal_calls": used_inside(name, txt) - (1 if isinstance(n, ast.ClassDef) else 0),
            })

OUT.write_text(json.dumps({"modules": modules, "functions": functions}, ensure_ascii=False, indent=1), encoding="utf-8")
print(len(modules), "modules;", len(functions), "top-level defs")
