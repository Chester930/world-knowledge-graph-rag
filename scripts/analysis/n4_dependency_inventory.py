"""N4（SVO 抽取）依賴與副作用只讀盤點（報告155 T4；報告97 §6.4）。純靜態 AST，不連線、不 import 被分析程式。

輸出 JSON：對 ``services/svo_service.py`` 中屬 N4 的每個頂層函式／常數，列出
(1) 檔內直接相依與遞移閉包、(2) 使用到的 import 名稱、(3) 設定讀取、(4) 副作用、
(5) 外部呼叫者（含 scripts／tests）與測試補丁目標。
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

TARGET = "services/svo_service.py"
MODULE = "services.svo_service"

# 報告97 §6.4 的 N4 範圍（人工列舉；行號以 AST 動態取得）。含相鄰但屬 N9.7 的 resolve_query_relation_type，供比對。
N4_NAMES = [
    "_strip_json_fence", "_parse_triples_payload", "_ENTITY_TYPE_GUIDE", "_EXTENDED_ENTITY_TYPES_PATH",
    "_normalize_type_key", "_CORE_TYPE_LOOKUP", "_load_extended_entity_type_lookup", "resolve_entity_type",
    "_effective_rel_types", "_effective_rel_type_descriptions", "_svo_prompt",
    "_TYPE_DESCRIPTION_EMBEDDING_CACHE", "_type_description_embeddings", "classify_relation_by_embedding",
    "_reconcile_rel_type", "extract_svo_triples", "UNCOVERED_SENTENCE_THRESHOLD", "_find_uncovered_sentences",
    "_QUANTITY_PATTERN", "_CJK_NUMBER_PATTERN", "_MEASURE_NUMBER_PATTERN", "_RANGE_NUMBER_GAP_PATTERN",
    "_regex_token_alternation", "_compile_measure_pattern", "_build_measure_pattern",
    "_compile_range_comparator_pattern", "_build_range_comparator_pattern", "_compile_enum_guard_pattern",
    "_build_enum_guard_pattern", "_compile_scope_modifier_pattern", "_build_scope_modifier_pattern",
    "_DEFAULT_GUARD_CONFIG", "_MEASURE_PATTERN", "_RANGE_COMPARATOR_PATTERN", "_ENUM_GUARD_PATTERN",
    "_SCOPE_MODIFIER_PATTERN", "_has_scope_modifier", "_contains_ungrounded_quantity", "_LEAVE_TYPE_FAMILY",
    "_ENTITY_FAMILIES", "_rival_family_term", "_contains_ungrounded_family_term", "_CLAUSE_SPLIT_PATTERN",
    "_BINDING_NORMALIZE_PATTERN", "_MIN_BINDING_SUBJECT_LEN", "_split_into_clauses", "_normalize_for_binding",
    "_BINDING_UNITS", "_quantity_unit", "_rival_quantity", "_quantity_mis_bound_to_clause",
    "_RISK_LEVEL_BY_BUSINESS_CATEGORY", "_risk_category_misbound_to_clause", "_filter_ungrounded_quantity_triples",
    "extract_svo_triples_with_completeness_check",
    "_opencc_s2tw", "_to_traditional", "_to_traditional_selective", "_kg_source_charset",
    "_KNOWN_SIMPLIFIED_COMPOUNDS", "_fix_known_simplified_compounds", "traditionalize_triples",
]
ADJACENT = ["resolve_query_relation_type"]  # 屬 N9.7，但夾在 N4 區段內

SIDE_EFFECT_MODULES = {
    "expand_governance_service": "寫 SQLite（EXPAND 候選池）",
    "sim_calibration_service": "寫 SQLite（SIM 仲裁事件）",
    "task_queue_service": "SQLite 任務佇列",
    "document_record_service": "讀寫文件 _record.json",
}
PROVIDER_ATTRS = {
    "generate": "LLM 呼叫", "generate_json": "LLM 呼叫", "generate_stream": "LLM 呼叫",
    "encode": "embedding 呼叫", "encode_batch": "embedding 呼叫",
}


def _top_level(tree: ast.Module):
    defs: dict[str, ast.AST] = {}
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defs[n.name] = n
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    defs[t.id] = n
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            defs[n.target.id] = n
    return defs


def _imports(tree: ast.Module) -> dict[str, str]:
    m: dict[str, str] = {}
    for n in tree.body:
        if isinstance(n, ast.Import):
            for a in n.names:
                m[a.asname or a.name.split(".")[0]] = a.name
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                m[a.asname or a.name] = f"{'.' * n.level}{n.module or ''}.{a.name}"
    return m


def _names_used(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _chain(n: ast.AST) -> str | None:
    parts = []
    while isinstance(n, ast.Attribute):
        parts.append(n.attr)
        n = n.value
    if isinstance(n, ast.Name):
        parts.append(n.id)
        return ".".join(reversed(parts))
    return None


def analyze_symbol(name: str, node: ast.AST, defs: dict, imports: dict) -> dict:
    used = _names_used(node)
    intra = sorted(u for u in used if u in defs and u != name)
    imp = sorted(u for u in used if u in imports)
    cfg_reads: set[str] = set()
    side: dict[str, set[str]] = {}
    for n in ast.walk(node):
        if isinstance(n, ast.Attribute):
            ch = _chain(n)
            if ch and (ch.startswith(("cfg.", "_cfg.", "guard.", "settings."))):
                cfg_reads.add(ch)
        if isinstance(n, ast.Call):
            f = n.func
            ch = _chain(f) if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
            if not ch:
                continue
            root = ch.split(".")[0]
            last = ch.split(".")[-1]
            if root in SIDE_EFFECT_MODULES:
                side.setdefault(SIDE_EFFECT_MODULES[root], set()).add(f"{ch}（:{n.lineno}）")
            if last in PROVIDER_ATTRS and "." in ch:
                side.setdefault(PROVIDER_ATTRS[last], set()).add(f"{ch}（:{n.lineno}）")
            if root == "logger" or ch.startswith("logging."):
                side.setdefault("logging", set()).add(f"{ch}（:{n.lineno}）")
            if ch in {"open", "Path"} or last in {"read_text", "write_text", "open", "read_bytes", "write_bytes"}:
                side.setdefault("檔案系統讀寫", set()).add(f"{ch}（:{n.lineno}）")
            if last in {"sleep"}:
                side.setdefault("等待", set()).add(f"{ch}（:{n.lineno}）")
            if root == "lru_cache" or last == "cache_clear":
                side.setdefault("快取", set()).add(f"{ch}（:{n.lineno}）")
            if root in {"OpenCC", "opencc"} or "opencc" in ch.lower():
                side.setdefault("第三方套件（OpenCC）", set()).add(f"{ch}（:{n.lineno}）")
        if isinstance(n, ast.Global):
            side.setdefault("global 寫入", set()).add(",".join(n.names))
        if isinstance(n, (ast.Assign, ast.AugAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            for t in targets:
                if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and t.value.id in defs:
                    side.setdefault("模組層級可變物件寫入", set()).add(f"{t.value.id}[…]（:{n.lineno}）")
    decorators = []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        decorators = [ast.unparse(d) for d in node.decorator_list]
    return {
        "name": name,
        "kind": "async def" if isinstance(node, ast.AsyncFunctionDef) else "def" if isinstance(node, ast.FunctionDef) else "const",
        "lines": [node.lineno, node.end_lineno],
        "intra_deps": intra,
        "imports_used": imp,
        "cfg_reads": sorted(cfg_reads),
        "side_effects": {k: sorted(v) for k, v in side.items()},
        "decorators": decorators,
    }


def closure(names: list[str], info: dict[str, dict]) -> set[str]:
    seen: set[str] = set()
    stack = list(names)
    while stack:
        n = stack.pop()
        if n in seen or n not in info:
            continue
        seen.add(n)
        stack.extend(info[n]["intra_deps"])
    return seen


def external_users(root: Path, names: set[str]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {n: [] for n in names}
    for py in sorted(root.rglob("*.py")):
        rel = py.relative_to(root).as_posix()
        if {".git", ".claude", "node_modules", "__pycache__"} & set(py.relative_to(root).parts):
            continue
        if rel == TARGET:
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        aliases: set[str] = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                if n.module == MODULE:
                    for a in n.names:
                        if a.name in names:
                            out[a.name].append({"file": rel, "line": n.lineno, "kind": "from import"})
                if n.module == "services":
                    for a in n.names:
                        if a.name == "svo_service":
                            aliases.add(a.asname or a.name)
            elif isinstance(n, ast.Import):
                for a in n.names:
                    if a.name == MODULE:
                        aliases.add(a.asname or MODULE)
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and n.attr in names:
                ch = _chain(n.value) if isinstance(n.value, (ast.Attribute, ast.Name)) else None
                if ch and (ch in aliases or ch.endswith("svo_service") or ch in {"svc"}):
                    out[n.attr].append({"file": rel, "line": n.lineno, "kind": f"{ch}.{n.attr}"})
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith(MODULE + "."):
                last = n.value.split(".")[-1]
                if last in names:
                    out[last].append({"file": rel, "line": n.lineno, "kind": f"patch 字串 {n.value}"})
    return out


def reverse_deps(defs: dict, n4: set[str]) -> dict[str, list[str]]:
    """svo_service.py 內「非 N4」的頂層符號使用了哪些 N4 名稱。"""
    rev: dict[str, list[str]] = {}
    for name, node in defs.items():
        if name in n4:
            continue
        for u in _names_used(node) & n4:
            rev.setdefault(u, []).append(name)
    return {k: sorted(v) for k, v in sorted(rev.items())}


def patch_targets(root: Path, names: set[str]) -> dict[str, list[dict]]:
    """tests/ 內 patch／monkeypatch.setattr／patch.object 指向這些名稱的目標。"""
    out: dict[str, list[dict]] = {}
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
            a = n.args
            if a and isinstance(a[0], ast.Constant) and isinstance(a[0].value, str):
                last = a[0].value.split(".")[-1]
                if last in names:
                    out.setdefault(last, []).append({"file": rel, "target": a[0].value})
            elif len(a) >= 2 and isinstance(a[1], ast.Constant) and isinstance(a[1].value, str) and a[1].value in names:
                out.setdefault(a[1].value, []).append({"file": rel, "target": f"<{ast.unparse(a[0])}>.{a[1].value}"})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    tree = ast.parse((a.root / TARGET).read_text(encoding="utf-8"))
    defs = _top_level(tree)
    imports = _imports(tree)
    info = {n: analyze_symbol(n, defs[n], defs, imports) for n in N4_NAMES + ADJACENT if n in defs}
    missing = [n for n in N4_NAMES + ADJACENT if n not in defs]
    all_defs_info = {n: analyze_symbol(n, node, defs, imports) for n, node in defs.items()}
    clo = closure(N4_NAMES, all_defs_info)
    dragged = sorted(clo - set(N4_NAMES))
    users = external_users(a.root, set(defs))
    data = {
        "missing_names": missing,
        "n4": info,
        "closure_extra_outside_n4": {n: all_defs_info[n] for n in dragged},
        "imports": imports,
        "external_users": {n: users.get(n, []) for n in set(N4_NAMES + ADJACENT + dragged)},
        "reverse_deps": reverse_deps(defs, set(N4_NAMES)),
        "patch_targets": patch_targets(a.root, set(N4_NAMES + ADJACENT)),
    }
    text = json.dumps(data, ensure_ascii=False, indent=1)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
