"""匯入相依快照（報告106）：掃描專案內 .py 的 import，輸出內部模組相依圖、
fan-in／fan-out 與循環相依（強連通分量）。

用法：python scripts/analysis/import_graph_snapshot.py <repo根目錄> <輸出.json>

限制：只解析靜態 import 陳述式（含函式內的延遲 import）；動態載入
（importlib、字串 __import__）不會被偵測。排除 tests／data／docs／ui 等目錄。
"""
import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2])
SKIP = {".git", ".claude", "node_modules", "__pycache__", ".venv", "venv",
        "data", "docs", "tests", "ui"}


def module_name(path: Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


files: dict[str, Path] = {}
for p in ROOT.rglob("*.py"):
    rel = p.relative_to(ROOT)
    if any(part in SKIP for part in rel.parts):
        continue
    name = module_name(p)
    if name:
        files[name] = p
mods = set(files)


def resolve(dotted: str):
    parts = dotted.split(".")
    for i in range(len(parts), 0, -1):
        cand = ".".join(parts[:i])
        if cand in mods:
            return cand
    return None


graph: dict[str, list[str]] = {}
errors: list[str] = []
for m, p in sorted(files.items()):
    try:
        tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        errors.append(m)
        graph[m] = []
        continue
    is_pkg = p.name == "__init__.py"
    deps: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                r = resolve(alias.name)
                if r and r != m:
                    deps.add(r)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                pkg = m.split(".") if is_pkg else m.split(".")[:-1]
                base = pkg[: len(pkg) - (node.level - 1)]
                target = ".".join(base + ([node.module] if node.module else []))
            else:
                target = node.module or ""
            if not target:
                continue
            r = resolve(target)
            if r and r != m:
                deps.add(r)
            for alias in node.names:
                r2 = resolve(f"{target}.{alias.name}")
                if r2 and r2 != m:
                    deps.add(r2)
    graph[m] = sorted(deps)

fan_in = {m: 0 for m in graph}
for deps in graph.values():
    for d in deps:
        fan_in[d] += 1
fan_out = {m: len(deps) for m, deps in graph.items()}

# Tarjan 強連通分量（大小 > 1 即為循環相依）
sys.setrecursionlimit(10000)
index_counter = [0]
stack: list[str] = []
on_stack: set[str] = set()
indices: dict[str, int] = {}
low: dict[str, int] = {}
sccs: list[list[str]] = []


def strong(v: str) -> None:
    indices[v] = low[v] = index_counter[0]
    index_counter[0] += 1
    stack.append(v)
    on_stack.add(v)
    for w in graph.get(v, []):
        if w not in indices:
            strong(w)
            low[v] = min(low[v], low[w])
        elif w in on_stack:
            low[v] = min(low[v], indices[w])
    if low[v] == indices[v]:
        comp = []
        while True:
            w = stack.pop()
            on_stack.discard(w)
            comp.append(w)
            if w == v:
                break
        if len(comp) > 1:
            sccs.append(sorted(comp))


for v in sorted(graph):
    if v not in indices:
        strong(v)

try:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
except Exception:
    head = ""

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps({
    "git_head": head,
    "module_count": len(graph),
    "edge_count": sum(len(d) for d in graph.values()),
    "syntax_errors": errors,
    "cycles": sorted(sccs),
    "fan_in": dict(sorted(fan_in.items(), key=lambda kv: (-kv[1], kv[0]))),
    "fan_out": dict(sorted(fan_out.items(), key=lambda kv: (-kv[1], kv[0]))),
    "graph": graph,
}, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"modules={len(graph)} edges={sum(len(d) for d in graph.values())} "
      f"cycles={len(sccs)} syntax_errors={len(errors)}")
