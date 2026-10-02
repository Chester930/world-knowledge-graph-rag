"""Q1：L3′ 試點語料建構器（報告262 §4）——collector 歷史檔 → 試點文件資料夾＋ `pilot_manifest.json`。

離線、只讀 collector（絕不修改）、不連任何資料庫／模型服務、不操作容器、不讀環境設定檔。純運算（`build_corpus`）與 I/O
（`write_corpus`）分開；同輸入必得同輸出（含檔案內容、排序、`pilot_kg_id`，且 manifest 不含時間戳）。

身分（D3）：(pcode, 正規化條號, `valid_from`)；衝突（同身分不同 `version_id` 或 `content_hash`）取最新 snapshot 檔為權威並列入
`conflicts`；已知 snapshot 不一致的兩條（勞基法第 86 條、請假規則第 12 條）一律列入 `conflicts` 且**不納入對照組**。
`valid_to` 缺口不修：舊版 `valid_to` 以下一版 `valid_from` 推導，原始值與推導值並存於 manifest。

用法：``python scripts/analysis/pilot_version_corpus_builder.py [--dry-run]``
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.analysis.law_version_inventory import DEFAULT_SOURCE_DIR, load_history_files, sha256_file  # noqa: E402
from services.law_version_events import (  # noqa: E402
    DIFF_FORMAT_ONLY,
    DIFF_SAME_HASH,
    DIFF_SUBSTANTIVE,
    NAVIGATION_MARKER_RE,
    classify_content_difference,
)

DEFAULT_OUT_ROOT = Path(r"D:\Users\666\Desktop\kg-runtime-pilot")
OUT_ROOT_DIRNAME = "kg-runtime-pilot"
PILOT_KG_ID_DEFAULT = uuid5(NAMESPACE_URL, "world-knowledge-graph-rag/pilot/law-version/v1")
CONTROL_LIMIT = 10
KNOWN_SNAPSHOT_INCONSISTENT = (("N0030001", "86"), ("N0030006", "12"))  # 報告262 §2 D3：已知，不裁決
ROLE_SUBSTANTIVE_OLD, ROLE_SUBSTANTIVE_NEW = "substantive_old", "substantive_new"
ROLE_CONTROL_FORMAT_ONLY, ROLE_CONTROL_SAME_HASH = "control_format_only", "control_same_hash"
ROLES = (ROLE_SUBSTANTIVE_OLD, ROLE_SUBSTANTIVE_NEW, ROLE_CONTROL_FORMAT_ONLY, ROLE_CONTROL_SAME_HASH)
CONTROL_ROLE_BY_KIND = {DIFF_FORMAT_ONLY: ROLE_CONTROL_FORMAT_ONLY, DIFF_SAME_HASH: ROLE_CONTROL_SAME_HASH}


class OutputPathError(ValueError):
    """輸出目錄不在 `kg-runtime-pilot` 之下，或位於 repo 內。"""


# ── 正規化與雜訊 ─────────────────────────────────────────────────────────────
def normalize_article_no(value: object) -> str:
    """NFKC＋去空白（沿用 P1／P2）。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value)))


def article_sort_key(article_no: str) -> tuple[object, ...]:
    return tuple(int(part) if part.isdecimal() else part for part in re.split(r"(\d+)", article_no))


def clean_law_name(name: object) -> str:
    """去掉英文頁面殘留的 ` EN` 後綴（collector 的 law_name 兩種寫法並存）。"""
    return re.sub(r"\s+EN$", "", unicodedata.normalize("NFKC", str(name)).strip())


def truncate_navigation_noise(text: str) -> tuple[str, bool]:
    """從 `::: 最新訊息` 起截到文末，但**輸出文字保持原樣**（不做 NFKC 轉換）。

    標記以逐字 NFKC 後的字串搜尋（與 P1／P2 的判定一致），再依逐字對應回原字串位置截斷，避免全形標點被轉成半形。
    這是保守的操作型規則，不宣稱能清除所有導覽雜訊。
    """
    normalized: list[str] = []
    origin: list[int] = []
    for index, char in enumerate(text):
        piece = unicodedata.normalize("NFKC", char)
        normalized.append(piece)
        origin.extend([index] * len(piece))
    match = NAVIGATION_MARKER_RE.search("".join(normalized))
    if match is None:
        return text, False
    return text[: origin[match.start()]], True


def render_original_md(source: str, articles: Sequence[tuple[str, str]]) -> str:
    """與 KG#4 `original.md` 同結構：前置 `---\\nsource: "…"\\n---\\n\\n`，每條 `第 N 條\\n\\n<條文>`，條間空一行，
    結尾單一換行；換行一律 CRLF（KG#4 檔實測為 CRLF；此處以顯式 `\\r\\n` 輸出，不依平台）。"""
    body = "\n\n".join(
        f"第 {article_no} 條\n\n{text.replace(chr(13) + chr(10), chr(10)).replace(chr(13), chr(10))}"
        for article_no, text in articles
    )
    return (f'---\nsource: "{source}"\n---\n\n{body}\n').replace("\n", "\r\n")


# ── 身分、去重、衝突 ─────────────────────────────────────────────────────────
def authoritative_records(
    file_rows: Mapping[str, Sequence[Mapping[str, Any]]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """依 (pcode, 正規化條號, valid_from) 去重，取檔名排序最後（最新 snapshot）者為權威；回傳（權威記錄，衝突身分）。"""
    groups: dict[tuple[str, str, str], list[tuple[str, Mapping[str, Any]]]] = defaultdict(list)
    for filename in sorted(file_rows):
        for row in file_rows[filename]:
            groups[(str(row["pcode"]), normalize_article_no(row["article_no"]), str(row["valid_from"]))].append((filename, row))
    records: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for key in sorted(groups, key=lambda k: (k[0], article_sort_key(k[1]), k[2])):
        entries = groups[key]
        filename, row = entries[-1]
        record = dict(row)
        record["article_no_normalized"] = key[1]
        record["_snapshot_file"] = filename
        records.append(record)
        if len({r.get("version_id") for _, r in entries}) > 1 or len({r.get("content_hash") for _, r in entries}) > 1:
            conflicts.append({
                "pcode": key[0], "article_no": key[1], "valid_from": key[2],
                "authority_file": filename, "authority_version_id": row.get("version_id"),
                "occurrences": [{"file": f, "version_id": r.get("version_id"), "content_hash": r.get("content_hash")}
                                for f, r in entries],
                "reason": "same_identity_different_version_id_or_content_hash",
            })
    return records, conflicts


def conflict_articles(conflicts: Sequence[Mapping[str, Any]]) -> set[tuple[str, str]]:
    return {(str(c["pcode"]), str(c["article_no"])) for c in conflicts} | set(KNOWN_SNAPSHOT_INCONSISTENT)


def version_chains(records: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    chains: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in records:
        chains[(str(row["pcode"]), row["article_no_normalized"])].append(row)
    for chain in chains.values():
        chain.sort(key=lambda r: (str(r["valid_from"]), str(r.get("version_date") or ""), str(r.get("version_id") or "")))
    return dict(sorted(chains.items(), key=lambda item: (item[0][0], article_sort_key(item[0][1]))))


def adjacent_pairs(chains: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    pairs = []
    for (pcode, article), chain in chains.items():
        for old, new in zip(chain, chain[1:]):
            pairs.append({
                "pair_id": f"{pcode}:{article}:{old['valid_from']}->{new['valid_from']}",
                "pcode": pcode, "article_no": article, "old": old, "new": new,
                "kind": classify_content_difference(old, new),
            })
    return pairs


def select_pairs(
    pairs: Sequence[Mapping[str, Any]], excluded_from_controls: set[tuple[str, str]], control_limit: int = CONTROL_LIMIT
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """全部「實質修改」對＋決定性對照（依 pcode、條號、舊版 valid_from 排序後各取前 `control_limit` 組；衝突條文不入對照）。"""
    substantive = [p for p in pairs if p["kind"] == DIFF_SUBSTANTIVE]
    controls: list[Mapping[str, Any]] = []
    for kind in (DIFF_FORMAT_ONLY, DIFF_SAME_HASH):
        candidates = [p for p in pairs if p["kind"] == kind and (p["pcode"], p["article_no"]) not in excluded_from_controls]
        candidates.sort(key=lambda p: (p["pcode"], article_sort_key(p["article_no"]), str(p["old"]["valid_from"])))
        controls.extend(candidates[:control_limit])
    return substantive, controls


# ── 組裝（純運算）────────────────────────────────────────────────────────────
def build_corpus(
    file_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    pilot_kg_id: UUID = PILOT_KG_ID_DEFAULT,
    *,
    source_manifest: Sequence[Mapping[str, Any]] | None = None,
    control_limit: int = CONTROL_LIMIT,
) -> dict[str, Any]:
    """回傳 `{"manifest": …, "folders": {source: {"articles": [(article_no, text)], "original_md": str}}}`；不做任何 I/O。"""
    from core.constants import DOCUMENT_ID_NAMESPACE  # 延遲匯入：只取常數（core/__init__ 為空），不讀設定

    records, detected = authoritative_records(file_rows)
    chains = version_chains(records)
    bad_articles = conflict_articles(detected)
    pairs = adjacent_pairs(chains)
    substantive, controls = select_pairs(pairs, bad_articles, control_limit)

    names: dict[str, Counter[str]] = defaultdict(Counter)
    for row in records:
        names[str(row["pcode"])][clean_law_name(row["law_name"])] += 1
    law_name = {pcode: sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] for pcode, c in names.items()}

    roles: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    pair_ids: dict[tuple[str, str, str], list[str]] = defaultdict(list)

    def mark(pair: Mapping[str, Any], old_role: str, new_role: str) -> None:
        for side, role in (("old", old_role), ("new", new_role)):
            ident = (pair["pcode"], pair["article_no"], str(pair[side]["valid_from"]))
            if role not in roles[ident]:
                roles[ident].append(role)
            if pair["pair_id"] not in pair_ids[ident]:
                pair_ids[ident].append(pair["pair_id"])

    for pair in substantive:
        mark(pair, ROLE_SUBSTANTIVE_OLD, ROLE_SUBSTANTIVE_NEW)
    for pair in controls:
        role = CONTROL_ROLE_BY_KIND[pair["kind"]]
        mark(pair, role, role)

    diff_prev: dict[tuple[str, str, str], str] = {}
    diff_next: dict[tuple[str, str, str], str] = {}
    next_valid_from: dict[tuple[str, str, str], str] = {}
    for pair in pairs:
        old_id = (pair["pcode"], pair["article_no"], str(pair["old"]["valid_from"]))
        new_id = (pair["pcode"], pair["article_no"], str(pair["new"]["valid_from"]))
        diff_next[old_id] = pair["kind"]
        diff_prev[new_id] = pair["kind"]
        next_valid_from[old_id] = str(pair["new"]["valid_from"])

    by_identity = {(str(r["pcode"]), r["article_no_normalized"], str(r["valid_from"])): r for r in records}
    folders: dict[str, dict[str, Any]] = {}
    versions: list[dict[str, Any]] = []
    for ident in sorted(roles, key=lambda i: (i[0], i[2], article_sort_key(i[1]))):
        pcode, article, valid_from = ident
        row = by_identity[ident]
        source = f"{pcode}_{law_name[pcode]}@{valid_from}"
        text, truncated = truncate_navigation_noise(str(row.get("content", "")))
        text = text.strip()
        folder = folders.setdefault(source, {"articles": [], "pcode": pcode, "valid_from": valid_from})
        folder["articles"].append((article, text))
        versions.append({
            "pcode": pcode, "law_name": law_name[pcode], "article_no": article, "law_article_no": f"第 {article} 條",
            "valid_from": valid_from,
            "valid_to_original": row.get("valid_to"), "valid_to_derived": next_valid_from.get(ident),
            "version_id": row.get("version_id"), "content_hash": row.get("content_hash"),
            "snapshot_file": row["_snapshot_file"], "roles": sorted(roles[ident], key=ROLES.index),
            "pair_ids": sorted(pair_ids[ident]),
            "diff_from_previous": diff_prev.get(ident), "diff_to_next": diff_next.get(ident),
            "folder": source, "source_doc_id": str(uuid5(DOCUMENT_ID_NAMESPACE, source)),
            "is_conflict": (pcode, article) in bad_articles,
            "noise_truncated": truncated,
            "original_length": len(str(row.get("content", ""))), "truncated_length": len(text),
        })
    for source, folder in folders.items():
        folder["articles"].sort(key=lambda item: article_sort_key(item[0]))
        folder["original_md"] = render_original_md(source, folder["articles"])

    folder_entries = [{
        "source": source, "pcode": folder["pcode"], "law_name": law_name[folder["pcode"]],
        "valid_from": folder["valid_from"], "source_doc_id": str(uuid5(DOCUMENT_ID_NAMESPACE, source)),
        "article_count": len(folder["articles"]),
        "original_md_sha256": hashlib.sha256(folder["original_md"].encode("utf-8")).hexdigest(),
    } for source, folder in sorted(folders.items())]
    role_counts = Counter(role for v in versions for role in v["roles"])
    pair_kind_all = Counter(p["kind"] for p in pairs)
    summary = {
        "authoritative_identities": len(records), "articles": len(chains), "adjacent_pairs": len(pairs),
        "pair_kind_counts_all": {k: pair_kind_all.get(k, 0) for k in (DIFF_SAME_HASH, DIFF_FORMAT_ONLY, DIFF_SUBSTANTIVE)},
        "selected_pairs": {"substantive": len(substantive),
                           "control_format_only": sum(p["kind"] == DIFF_FORMAT_ONLY for p in controls),
                           "control_same_hash": sum(p["kind"] == DIFF_SAME_HASH for p in controls)},
        "selected_versions": len(versions), "role_counts": {role: role_counts.get(role, 0) for role in ROLES},
        "folders": len(folders), "conflict_identities": len(detected), "conflict_articles": len(bad_articles),
        "conflict_versions_selected": sum(v["is_conflict"] for v in versions),
        "noise_truncated_versions": sum(v["noise_truncated"] for v in versions),
        "noise_truncated_total_chars_removed": sum(v["original_length"] - v["truncated_length"] for v in versions if v["noise_truncated"]),
        "valid_to_contiguous_pairs": sum(
            1 for p in pairs if p["old"].get("valid_to") not in (None, "") and str(p["old"]["valid_to"]) == str(p["new"]["valid_from"])
        ),
    }
    manifest = {
        "schema": "pilot_manifest/v1", "pilot_kg_id": str(pilot_kg_id),
        "source_files": list(source_manifest or []),
        "identity_rule": "(pcode, NFKC＋去空白條號, valid_from)；衝突取最新 snapshot 檔；valid_to 以下一版 valid_from 推導（原始值並存）",
        "selection_rule": (f"全部實質修改相鄰對的舊／新版＋format_only／same_hash 各最多 {control_limit} 組"
                           "（依 pcode、條號、舊版 valid_from 排序取前 N；衝突條文不入對照）"),
        "noise_rule": "NFKC 後偵測 `::: 最新訊息`，原字串從該位置截到文末（輸出不轉半形）；只計數，不宣稱清除所有導覽雜訊",
        "summary": summary, "conflicts": detected,
        "known_snapshot_inconsistent_articles": [list(item) for item in KNOWN_SNAPSHOT_INCONSISTENT],
        "folders": folder_entries, "versions": versions,
    }
    return {"manifest": manifest, "folders": folders}


# ── 輸出（I/O）──────────────────────────────────────────────────────────────
def repo_roots() -> list[Path]:
    """本 repo 根目錄；若在 `.claude/worktrees/<name>` 之下，也包含主 checkout 根目錄。"""
    roots = [_REPO.resolve()]
    if _REPO.parent.name == "worktrees" and _REPO.parent.parent.name == ".claude":
        roots.append(_REPO.parents[2].resolve())
    return roots


def validate_output_dir(out_dir: Path, forbidden_roots: Iterable[Path] | None = None) -> Path:
    """輸出目錄必須在名為 `kg-runtime-pilot` 的目錄之下，且不在 repo 內；否則 `OutputPathError`。"""
    resolved = Path(out_dir).resolve()
    if OUT_ROOT_DIRNAME not in resolved.parts[:-1]:
        raise OutputPathError(f"輸出目錄必須在 {OUT_ROOT_DIRNAME} 之下：{resolved}")
    for root in (list(forbidden_roots) if forbidden_roots is not None else repo_roots()):
        try:
            resolved.relative_to(Path(root).resolve())
        except ValueError:
            continue
        raise OutputPathError(f"輸出目錄不得在 repo 內：{resolved}")
    return resolved


def write_corpus(corpus: Mapping[str, Any], out_dir: Path, forbidden_roots: Iterable[Path] | None = None) -> Path:
    target = validate_output_dir(out_dir, forbidden_roots)
    expected = set(corpus["folders"]) | {"pilot_manifest.json"}
    if target.exists():
        stale = sorted(path.name for path in target.iterdir() if path.name not in expected)
        if stale:
            raise OutputPathError(f"輸出目錄已有不屬於本次選材的項目，請手動處理後重跑：{stale}")
    for source, folder in corpus["folders"].items():
        directory = target / source
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "original.md").write_bytes(folder["original_md"].encode("utf-8"))
    manifest_text = json.dumps(corpus["manifest"], ensure_ascii=False, indent=2) + "\n"
    (target / "pilot_manifest.json").write_bytes(manifest_text.encode("utf-8"))
    return target


def source_manifest_for(source_dir: Path, file_rows: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    return [{"file": name, "sha256": sha256_file(source_dir / name), "rows": len(file_rows[name])} for name in sorted(file_rows)]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR, help="collector 歷史檔目錄（只讀）")
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--pilot-kg-id", type=UUID, default=PILOT_KG_ID_DEFAULT)
    parser.add_argument("--dry-run", action="store_true", help="只計算並印出摘要，不寫檔")
    args = parser.parse_args(argv)
    file_rows = load_history_files(args.source_dir)
    corpus = build_corpus(file_rows, args.pilot_kg_id, source_manifest=source_manifest_for(args.source_dir, file_rows))
    out_dir = args.out_root / str(args.pilot_kg_id)
    if not args.dry_run:
        write_corpus(corpus, out_dir)
    print(json.dumps({"out_dir": str(out_dir), "written": not args.dry_run,
                      "summary": corpus["manifest"]["summary"],
                      "conflicts": [{k: c[k] for k in ("pcode", "article_no", "valid_from")} for c in corpus["manifest"]["conflicts"]]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
