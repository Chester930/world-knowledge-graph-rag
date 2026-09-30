"""N9（KG 內檢索）依賴與副作用只讀盤點（報告164 V2；比照 ``n4_dependency_inventory.py``）。純靜態 AST。

N9 成員依 ``services/retrieval/NODE.md`` 登記，跨 ``routers/agent.py``、``services/svo_service.py``、
``services/retrieval/scope.py``；另分析 ``chat()`` 內嵌的 N9.1（載入 KGConfig）／N9.2（問題向量化）。
輸出 JSON。
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from n4_dependency_inventory import _chain, _imports, _names_used, _top_level, analyze_symbol  # noqa: E402

MEMBERS = {
    "routers/agent.py": [
        "_SEED_ENTITY_LIMIT", "_SEED_MAX_DEGREE", "_BFS_PER_SEED_LIMIT", "_DOC_SCOPE_TOP_N_FACTS",
        "_find_seed_entities", "_drop_hub_seeds", "_relevant_doc_ids_from_seeds", "_expand_facts_by_article",
    ],
    "services/svo_service.py": [
        "vector_search_facts", "vector_search_entities", "bfs_query", "resolve_query_relation_type",
        "_rrf_fuse_fact_ids", "_filter_fact_candidates_by_source_scope", "_apply_source_doc_cap", "_dedupe_facts_by_key",
        "_bfs_pass_cypher", "_bfs_records_to_triples", "_BFS_EXPAND_WHEN_BELOW", "_BFS_PRIZE_TOP_K",
        "_fact_vector_index_name", "_fact_fulltext_index_name", "_kg_fact_label",
    ],
    "services/retrieval/scope.py": [
        "relevant_doc_ids_from_facts", "intersect_doc_scopes", "resolve_doc_scope", "scope_by_source_doc_ids",
        "filter_triples_by_source_doc_ids", "filter_facts_by_source_doc_ids", "filter_triples_by_relation_type",
    ],
}
# chat() 內嵌區段（行號以目前 routers/agent.py 為準；由腳本驗證邊界字串）
N91 = (1265, 1274)   # 載入 KGConfig
N92 = (1296, 1298)   # 問題向量化（含 use_svo 分支開頭）
N9_BLOCK = (1296, 1396)  # `if payload.use_svo:` 全區塊（N9.2–條文擴充）

NEO4J_ATTRS = {"execute_query", "execute_read", "execute_write", "session", "run"}


def neo4j_sites(node: ast.AST) -> int:
    n = 0
    for x in ast.walk(node):
        if isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) and x.func.attr in {"execute_query", "execute_read", "execute_write"}:
            n += 1
    return n


def collect(root: Path) -> dict:
    per_file = {}
    for rel, names in MEMBERS.items():
        src = (root / rel).read_text(encoding="utf-8")
        tree = ast.parse(src)
        defs = _top_level(tree)
        imports = _imports(tree)
        info = {}
        for nm in names:
            if nm not in defs:
                info[nm] = {"missing": True}
                continue
            d = analyze_symbol(nm, defs[nm], defs, imports)
            d["neo4j_execute_sites"] = neo4j_sites(defs[nm])
            info[nm] = d
        # 反向：同檔非成員符號使用了哪些成員
        member_set = set(names)
        rev = {}
        for nm, node in defs.items():
            if nm in member_set:
                continue
            for u in _names_used(node) & member_set:
                rev.setdefault(u, []).append(nm)
        # 遞移閉包（檔內）
        allinfo = {nm: analyze_symbol(nm, node, defs, imports) for nm, node in defs.items()}
        stack, seen = [n for n in names if n in defs], set()
        while stack:
            x = stack.pop()
            if x in seen or x not in allinfo:
                continue
            seen.add(x)
            stack.extend(allinfo[x]["intra_deps"])
        per_file[rel] = {"members": info, "reverse_deps_in_file": {k: sorted(v) for k, v in rev.items()},
                         "closure_extra_outside_members": sorted(seen - member_set - {"logger"}),
                         "closure_extra_info": {k: {"kind": allinfo[k]["kind"], "lines": allinfo[k]["lines"]} for k in sorted(seen - member_set - {"logger"})},
                         "imports": imports}
    return per_file


def chat_inline(root: Path) -> dict:
    src = (root / "routers/agent.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    chat = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "chat")
    stream = next((n for n in ast.walk(chat) if isinstance(n, ast.AsyncFunctionDef) and n.name == "_stream"), None)
    lines = src.split("\n")
    out = {"chat": [chat.lineno, chat.end_lineno], "_stream": [stream.lineno, stream.end_lineno] if stream else None}
    checks = {
        "N9.1 起點（載入 KGRepository／ConfigLoader）": (N91[0], "domain_pack: str | None = None"),
        "N9.1 終點（cfg = ConfigLoader…load）": (N91[1], ")"),
        "N9.2（問題向量化）": (N92[0], "if payload.use_svo:"),
        "N9 區塊終點（條文擴充呼叫）": (N9_BLOCK[1], ")"),
    }
    out["boundary_checks"] = {k: lines[ln - 1].strip()[:80] for k, (ln, _) in checks.items()}

    def loads_stores(lo, hi):
        loads, stores = {}, {}
        for x in ast.walk(stream or chat):
            if isinstance(x, ast.Name) and lo <= x.lineno <= hi:
                (loads if isinstance(x.ctx, ast.Load) else stores).setdefault(x.id, []).append(x.lineno)
        return loads, stores

    for label, (lo, hi) in {"N9.1": N91, "N9.2_to_end": N9_BLOCK}.items():
        loads, stores = loads_stores(lo, hi)
        after_loads = {}
        for x in ast.walk(stream or chat):
            if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load) and x.lineno > hi and x.id in stores:
                after_loads.setdefault(x.id, []).append(x.lineno)
        # 區塊內讀取但區塊外（之前）才定義的名稱
        before_defs = set()
        for x in ast.walk(stream or chat):
            if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store) and x.lineno < lo:
                before_defs.add(x.id)
        params = {a.arg for a in chat.args.args}
        outer_inputs = sorted(n for n in loads if n in before_defs or n in params)
        out[label] = {
            "range": [lo, hi],
            "assigned_in_block": sorted(stores),
            "read_after_block": {k: v[:6] for k, v in sorted(after_loads.items())},
            "inputs_from_before_block": outer_inputs,
            "module_or_import_names_read": sorted(n for n in loads if n not in stores and n not in before_defs and n not in params),
        }
    return out


def external_users(root: Path, per_file: dict) -> dict:
    """成員名稱的外部引用：from-import、模組屬性、patch 字串／setattr，及測試補丁目標。"""
    mod_of = {"routers/agent.py": "routers.agent", "services/svo_service.py": "services.svo_service",
              "services/retrieval/scope.py": "services.retrieval.scope"}
    alias_hint = {"routers.agent": {"agent", "routers_agent"}, "services.svo_service": {"svo_service", "svc"},
                  "services.retrieval.scope": {"scope"}}
    names_by_mod = {mod_of[f]: set(v["members"]) for f, v in per_file.items()}
    # 也接受重新匯出的私有別名（agent.py 以底線名匯出 scope.py 的函式）
    agent_aliases = {"_" + n: n for n in per_file["services/retrieval/scope.py"]["members"]}
    out: dict[str, list] = {}
    skip = {".git", ".claude", "node_modules", "__pycache__"}
    for py in sorted(root.rglob("*.py")):
        rel = py.relative_to(root).as_posix()
        if skip & set(py.relative_to(root).parts):
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module in names_by_mod:
                for a in n.names:
                    if a.name in names_by_mod[n.module]:
                        out.setdefault(f"{n.module}.{a.name}", []).append({"file": rel, "line": n.lineno, "kind": "from-import"})
            if isinstance(n, ast.Attribute):
                base = _chain(n.value) if isinstance(n.value, (ast.Name, ast.Attribute)) else None
                if base:
                    last = base.split(".")[-1]
                    for mod, hints in alias_hint.items():
                        if (last in hints or base == mod) and n.attr in names_by_mod[mod]:
                            out.setdefault(f"{mod}.{n.attr}", []).append({"file": rel, "line": n.lineno, "kind": f"{base}.{n.attr}"})
                    if last in alias_hint["routers.agent"] and n.attr in agent_aliases:
                        out.setdefault(f"services.retrieval.scope.{agent_aliases[n.attr]}", []).append(
                            {"file": rel, "line": n.lineno, "kind": f"{base}.{n.attr}（agent 重新匯出）"})
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                for mod, names in names_by_mod.items():
                    if n.value.startswith(mod + "."):
                        last = n.value.split(".")[-1]
                        if last in names:
                            out.setdefault(f"{mod}.{last}", []).append({"file": rel, "line": n.lineno, "kind": f"patch 字串 {n.value}"})
    return out


def patch_targets(root: Path, per_file: dict) -> dict:
    names = {nm for f in per_file.values() for nm in f["members"]} | {"_" + n for n in per_file["services/retrieval/scope.py"]["members"]}
    out: dict[str, list] = {}
    for py in sorted((root / "tests").rglob("*.py")):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        rel = py.relative_to(root).as_posix()
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            fn = n.func.attr if isinstance(n.func, ast.Attribute) else (n.func.id if isinstance(n.func, ast.Name) else "")
            if fn not in {"patch", "setattr", "object"}:
                continue
            a = n.args
            if a and isinstance(a[0], ast.Constant) and isinstance(a[0].value, str) and a[0].value.split(".")[-1] in names:
                out.setdefault(a[0].value.split(".")[-1], []).append({"file": rel, "target": a[0].value})
            elif len(a) >= 2 and isinstance(a[1], ast.Constant) and isinstance(a[1].value, str) and a[1].value in names:
                out.setdefault(a[1].value, []).append({"file": rel, "target": f"<{ast.unparse(a[0])}>.{a[1].value}"})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    per_file = collect(a.root)
    data = {"files": per_file, "chat_inline": chat_inline(a.root), "external_users": external_users(a.root, per_file),
            "patch_targets": patch_targets(a.root, per_file)}
    text = json.dumps(data, ensure_ascii=False, indent=1)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
