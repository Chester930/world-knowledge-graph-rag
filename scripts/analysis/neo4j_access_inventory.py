"""Neo4j 存取位置只讀盤點（報告155 T3）。純靜態 AST 分析，不連線、不 import 被分析的程式。

三個獨立來源，供交叉檢查：
  A. 執行點：``.execute_query`` / ``.execute_read`` / ``.execute_write`` / ``.run``（接收者名稱含 session/tx）/
     ``.session(`` / ``.begin_transaction(``，以及「以變數傳入查詢字串的包裝函式」的呼叫點。
  B. Cypher 字串：函式內（含可解析的模組層級常數）含 Cypher 子句的字串常數。
  C. 簽名：參數或註解含 ``AsyncDriver`` / ``driver`` 的函式。

輸出 JSON 至 stdout（或 --out）。
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

SKIP = {".git", ".claude", "node_modules", "__pycache__", ".venv", "venv", "tests", "data", "docs"}
EXEC_ATTRS = {"execute_query", "execute_read", "execute_write", "session", "begin_transaction"}
CYPHER_RE = re.compile(r"\b(MATCH|MERGE|CREATE|UNWIND|CALL|DETACH DELETE|OPTIONAL MATCH)\b[^\n]{0,80}[\(\{]|\bRETURN\b|CREATE (VECTOR |FULLTEXT )?(INDEX|CONSTRAINT)|db\.index\.")
WRITE_RE = re.compile(r"\b(MERGE|CREATE|SET|DELETE|DETACH DELETE|REMOVE)\b")
LABEL_RE = re.compile(r"\(\s*\w*((?::\s*[A-Za-z_]\w*)+)")
LABEL2_RE = re.compile(r"\bFOR \(\w+:([A-Za-z0-9_]+)\)|\bON \(\w+:([A-Za-z0-9_]+)\)")
REL_RE = re.compile(r"\[\s*\w*\s*:\s*([A-Z][A-Z0-9_|]*)")
FEATURES = {
    "elementId": re.compile(r"elementId\("),
    "SHOW_admin": re.compile(r"SHOW (VECTOR )?(INDEXES|DATABASES)"),
    "DDL_database": re.compile(r"(CREATE|DROP) DATABASE"),
    "DROP_INDEX": re.compile(r"DROP INDEX"),
    "EXISTS_subquery": re.compile(r"EXISTS\s*\{"),
    "vector_similarity_fn": re.compile(r"vector\.similarity\.cosine"),
    "dynamic_label_or_reltype": re.compile(r":\s*\{_?\w*(label|rel)|\[\w*:\s*\{"),
    "SKIP_LIMIT_paging": re.compile(r"SKIP \$"),
    "vector_index_proc": re.compile(r"db\.index\.vector\.queryNodes"),
    "fulltext_proc": re.compile(r"db\.index\.fulltext"),
    "create_vector_index": re.compile(r"CREATE VECTOR INDEX"),
    "create_fulltext_index": re.compile(r"CREATE FULLTEXT INDEX"),
    "create_index_or_constraint": re.compile(r"CREATE (INDEX|CONSTRAINT)|IF NOT EXISTS"),
    "CALL_subquery": re.compile(r"CALL\s*\{|CALL\s*\(\w"),
    "CALL_proc": re.compile(r"\bCALL\s+[a-z]\w*\."),
    "UNWIND": re.compile(r"\bUNWIND\b"),
    "MERGE": re.compile(r"\bMERGE\b"),
    "OPTIONAL_MATCH": re.compile(r"OPTIONAL MATCH"),
    "var_length_path": re.compile(r"\[[^\]]*\*\d*\.?\.?\d*[^\]]*\]"),
    "shortestPath": re.compile(r"shortestPath|allShortestPaths"),
    "apoc": re.compile(r"\bapoc\."),
    "collect_agg": re.compile(r"\bcollect\("),
    "DETACH_DELETE": re.compile(r"DETACH DELETE"),
    "ON_CREATE_ON_MATCH": re.compile(r"ON CREATE|ON MATCH"),
}


def _strings_of(node: ast.AST, consts: dict[str, str]) -> list[str]:
    out: list[str] = []
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.append(n.value)
        elif isinstance(n, ast.Name) and n.id in consts:
            out.append(consts[n.id])
    return out


def _module_consts(tree: ast.Module) -> dict[str, str]:
    consts: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            strs = [n.value for n in ast.walk(node.value) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
            if strs:
                consts[node.targets[0].id] = "\n".join(strs)
    return consts


def _receiver_name(func: ast.Attribute) -> str:
    v = func.value
    if isinstance(v, ast.Name):
        return v.id
    if isinstance(v, ast.Attribute):
        return v.attr
    return ""


def _is_exec_call(call: ast.Call) -> str | None:
    f = call.func
    if not isinstance(f, ast.Attribute):
        return None
    if f.attr in EXEC_ATTRS:
        if f.attr in {"session", "begin_transaction"}:
            return f.attr
        return f.attr
    if f.attr == "run":
        r = _receiver_name(f).lower()
        if "session" in r or r in {"tx", "txn", "transaction", "s"}:
            return "run"
    return None


class Func:
    def __init__(self, path: str, qual: str, node: ast.AST):
        self.path, self.qual, self.node = path, qual, node
        self.exec_sites: list[tuple[int, str]] = []
        self.cypher: list[str] = []
        self.wrapper_calls: list[tuple[int, str]] = []
        self.has_driver_sig = False


def _iter_funcs(tree: ast.Module, path: str):
    def visit(body, prefix):
        for n in body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield f"{prefix}{n.name}", n
                yield from visit(n.body, f"{prefix}{n.name}.")
            elif isinstance(n, ast.ClassDef):
                yield from visit(n.body, f"{prefix}{n.name}.")

    yield from visit(tree.body, "")


def _own_nodes(fn: ast.AST):
    """函式自身節點（不深入巢狀 def，避免重複歸屬）。"""
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        yield n
        stack.extend(ast.iter_child_nodes(n))


def analyze(root: Path) -> dict:
    funcs: list[Func] = []
    for py in sorted(root.rglob("*.py")):
        rel = py.relative_to(root).as_posix()
        if SKIP & set(py.relative_to(root).parts[:-1]):
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        consts = _module_consts(tree)
        for qual, node in _iter_funcs(tree, rel):
            f = Func(rel, qual, node)
            args = node.args.args + node.args.kwonlyargs
            for a in args:
                ann = ast.unparse(a.annotation) if a.annotation else ""
                if "Driver" in ann or a.arg in {"driver", "session", "tx"}:
                    f.has_driver_sig = True
            doc_id = None
            if node.body and isinstance(node.body[0], ast.Expr) and isinstance(getattr(node.body[0], "value", None), ast.Constant):
                doc_id = id(node.body[0].value)
            for n in _own_nodes(node):
                if id(n) == doc_id:
                    continue
                if isinstance(n, ast.Call):
                    kind = _is_exec_call(n)
                    if kind:
                        f.exec_sites.append((n.lineno, kind))
                        for a in n.args[:1]:
                            f.cypher += [s for s in _strings_of(a, consts)]
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and CYPHER_RE.search(n.value):
                    f.cypher.append(n.value)
                if isinstance(n, ast.Name) and n.id in consts and CYPHER_RE.search(consts[n.id]):
                    f.cypher.append(consts[n.id])
            funcs.append(f)

    # 包裝函式：函式內的 execute_query／run 以「非字串常數」的名稱／參數傳入查詢
    wrappers: dict[str, Func] = {}
    for f in funcs:
        for n in _own_nodes(f.node):
            if isinstance(n, ast.Call) and _is_exec_call(n) in {"execute_query", "run", "execute_read", "execute_write"}:
                if n.args and isinstance(n.args[0], ast.Name) and n.args[0].id in {a.arg for a in f.node.args.args + f.node.args.kwonlyargs}:
                    wrappers[f.qual.split(".")[-1]] = f
    for f in funcs:
        for n in _own_nodes(f.node):
            if isinstance(n, ast.Call):
                name = n.func.id if isinstance(n.func, ast.Name) else (n.func.attr if isinstance(n.func, ast.Attribute) else "")
                if name in wrappers and f is not wrappers[name]:
                    f.wrapper_calls.append((n.lineno, name))
                    # 呼叫點的 Cypher 字串
                    consts: dict[str, str] = {}
                    for a in n.args[1:2] + n.args[:1]:
                        f.cypher += _strings_of(a, consts)

    records = []
    for f in funcs:
        text = "\n".join(dict.fromkeys(f.cypher))
        has_cypher = bool(CYPHER_RE.search(text))
        if not (f.exec_sites or f.wrapper_calls or has_cypher):
            continue
        labels = sorted({x.strip() for grp in LABEL_RE.findall(text) for x in grp.split(":") if x.strip()} | {x for t in LABEL2_RE.findall(text) for x in t if x})
        if re.search(r":\s*\{_\w*label", text):
            labels.append("<per-KG 動態標籤>")
        rels = sorted({r for grp in REL_RE.findall(text) for r in grp.split("|")} - {"MATCH", "RETURN", "WHERE", "WITH", "ON"})
        feats = sorted(k for k, rx in FEATURES.items() if rx.search(text))
        is_write = bool(WRITE_RE.search(text))
        if "CREATE TABLE" in text or f.path.endswith("neo4j_access_inventory.py"):
            continue
        records.append({
            "path": f.path,
            "function": f.qual,
            "line": f.node.lineno,
            "exec_sites": [{"line": ln, "kind": k} for ln, k in sorted(set(f.exec_sites))],
            "wrapper_calls": [{"line": ln, "wrapper": w} for ln, w in sorted(set(f.wrapper_calls))],
            "has_cypher_string": has_cypher,
            "has_driver_sig": f.has_driver_sig,
            "read_write": "write" if is_write else "read",
            "labels": labels,
            "rels": rels,
            "features": feats,
            "cypher_preview": re.sub(r"\s+", " ", text)[:400],
            "source_A": bool(f.exec_sites or f.wrapper_calls),
            "source_B": has_cypher,
            "source_C": f.has_driver_sig,
        })
    seen = {(r["path"], r["function"]) for r in records}
    passthrough = [
        {"path": f.path, "function": f.qual, "line": f.node.lineno}
        for f in funcs if f.has_driver_sig and (f.path, f.qual) not in seen
        and not f.path.endswith("neo4j_access_inventory.py")
    ]
    return {"wrappers": sorted(wrappers), "records": records, "driver_sig_only": passthrough}


def test_patch_targets(root: Path) -> dict[str, list[dict]]:
    """tests/ 內 patch／monkeypatch.setattr／patch.object 的目標：名稱 → [{file, target}]。

    - ``patch("a.b.name")``：target 為完整字串。
    - ``monkeypatch.setattr(obj, "name", ...)`` / ``patch.object(obj, "name")``：target 為 ``<obj 原始碼>.name``。
    - ``monkeypatch.setattr("a.b.name", ...)``：完整字串。
    """
    targets: dict[str, list[dict]] = {}

    def add(name: str, rel: str, target: str) -> None:
        targets.setdefault(name, []).append({"file": rel, "target": target})

    for py in sorted((root / "tests").rglob("*.py")):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        rel = py.relative_to(root).as_posix()
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            fname = n.func.attr if isinstance(n.func, ast.Attribute) else (n.func.id if isinstance(n.func, ast.Name) else "")
            if fname not in {"patch", "setattr", "object"}:
                continue
            args = n.args
            if args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
                add(args[0].value.split(".")[-1], rel, args[0].value)
            elif len(args) >= 2 and isinstance(args[1], ast.Constant) and isinstance(args[1].value, str):
                add(args[1].value, rel, f"<{ast.unparse(args[0])}>.{args[1].value}")
    return targets


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    data = analyze(a.root)
    data["test_patch_targets"] = test_patch_targets(a.root)
    text = json.dumps(data, ensure_ascii=False, indent=1)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
