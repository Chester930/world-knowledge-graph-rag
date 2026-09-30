"""節點卡檢查（報告155 T2；草案 BT_SM節點化結構設計草案 §6.2）。**預設警告模式**。

掃描所有 ``**/NODE.md``，檢查三件事：

1. 卡內以 `` `檔案.py::名稱` `` 引用的函式／類別／模組層級名稱，是否真的存在於該檔（AST）。
2. 表格列標「已搬移」的引用必須位於本節點資料夾內；標「仍在原處」的引用不得位於本節點資料夾內。
3. 節點資料夾內的 ``.py`` 不得 import 其他節點資料夾（含 ``NODE.md`` 的資料夾）的模組。

預設只印警告並 exit 0；``--strict`` 有警告時 exit 1。不接 CI／pre-commit，不 import 被檢查的程式。
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

_SKIP_PARTS = {".git", ".claude", "node_modules", "__pycache__", ".venv", "venv"}
_REF_RE = re.compile(r"`([\w/]+\.py)::(\w+)`|`(\w+)`(?=（`:\d+`）)")
_STATUS_RE = re.compile(r"^\s*(已搬移|仍在原處)")


def find_cards(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("NODE.md")
        if not (_SKIP_PARTS & set(p.relative_to(root).parts))
    )


def _top_level_names(py_path: Path) -> set[str] | None:
    try:
        tree = ast.parse(py_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _refs_in_text(text: str) -> list[tuple[str, str]]:
    """依出現順序回傳 (path, name)；裸名稱（後接 `（`:N`）`）繼承同一行最近的 path。"""
    refs: list[tuple[str, str]] = []
    for line in text.splitlines():
        current: str | None = None
        for m in _REF_RE.finditer(line):
            if m.group(1):
                current = m.group(1)
                refs.append((current, m.group(2)))
            elif current:
                refs.append((current, m.group(3)))
    return refs


def _inside(path: str, folder_rel: str) -> bool:
    return path.startswith(folder_rel.rstrip("/") + "/")


def check_card_refs(card: Path, root: Path) -> list[str]:
    warnings: list[str] = []
    rel_card = card.relative_to(root).as_posix()
    folder_rel = card.parent.relative_to(root).as_posix()
    text = card.read_text(encoding="utf-8")
    cache: dict[str, set[str] | None] = {}

    def names_of(path: str) -> set[str] | None:
        if path not in cache:
            target = root / path
            cache[path] = _top_level_names(target) if target.exists() else None
        return cache[path]

    # (1) 引用存在
    for path, name in _refs_in_text(text):
        names = names_of(path)
        if names is None:
            warnings.append(f"{rel_card}: 引用的檔案不存在或無法解析：{path}")
        elif name not in names:
            warnings.append(f"{rel_card}: {path} 內找不到 {name}")

    # (2) 已搬移／仍在原處
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [c for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        m = _STATUS_RE.match(cells[-1])
        if not m:
            continue
        paths = {p for p, _ in _refs_in_text(" ".join(cells[:-1]))}
        for p in sorted(paths):
            if m.group(1) == "已搬移" and not _inside(p, folder_rel):
                warnings.append(f"{rel_card}: 標「已搬移」但 {p} 不在本節點資料夾 {folder_rel}/ 內")
            if m.group(1) == "仍在原處" and _inside(p, folder_rel):
                warnings.append(f"{rel_card}: 標「仍在原處」但 {p} 已在本節點資料夾 {folder_rel}/ 內")
    return warnings


def check_cross_node_imports(cards: list[Path], root: Path) -> list[str]:
    folders = {c.parent.relative_to(root).as_posix(): c.parent for c in cards}
    dotted = {f: f.replace("/", ".") for f in folders}
    warnings: list[str] = []
    for folder, abs_folder in folders.items():
        for py in sorted(abs_folder.glob("*.py")):
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                continue
            mods: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    mods += [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    mods.append(node.module)
            for mod in mods:
                for other, other_dotted in dotted.items():
                    if other == folder:
                        continue
                    if mod == other_dotted or mod.startswith(other_dotted + "."):
                        warnings.append(
                            f"{py.relative_to(root).as_posix()}: import 了其他節點資料夾 {other}/ 的模組 {mod}"
                        )
    return warnings


def run(root: Path) -> list[str]:
    cards = find_cards(root)
    warnings: list[str] = []
    for card in cards:
        warnings += check_card_refs(card, root)
    warnings += check_cross_node_imports(cards, root)
    return warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--strict", action="store_true", help="有警告時以 exit 1 結束")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    cards = find_cards(root)
    warnings = run(root)
    for w in warnings:
        print(f"[WARN] {w}")
    print(f"[check_node_cards] 掃描 {len(cards)} 張節點卡，{len(warnings)} 則警告")
    return 1 if (args.strict and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
