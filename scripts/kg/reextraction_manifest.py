"""Read-only manifest of re-extracted chunks recorded in task_queue.db.

`_process_one()` swallows extraction errors and only marks the chunk `failed`,
so a re-extraction runner that counts "no exception" as success is unreliable.
This tool reports what the queue actually says: which chunks were rewritten
after the bulk drain, and which chunks are not `completed`.

Usage:
    python scripts/kg/reextraction_manifest.py --kg-id <uuid> --since 2026-09-12 \
        [--db D:/Users/666/Desktop/kg-runtime/task_queue.db]
"""
from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict


def _connect_readonly(db_path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _compact(indices: list[int], limit: int = 12) -> str:
    indices = sorted(indices)
    if len(indices) <= limit:
        return ", ".join(str(i) for i in indices)
    head = ", ".join(str(i) for i in indices[:6])
    tail = ", ".join(str(i) for i in indices[-3:])
    return f"{head}, ..., {tail}"


def build_manifest(db_path: str, kg_id: str, since: str) -> str:
    conn = _connect_readonly(db_path)
    try:
        rewritten = conn.execute(
            "SELECT source, chunk_index, status, updated_at FROM task_queue "
            "WHERE kg_id=? AND updated_at>=? ORDER BY updated_at",
            (kg_id, since),
        ).fetchall()
        unfinished = conn.execute(
            "SELECT source, chunk_index, status, updated_at FROM task_queue "
            "WHERE kg_id=? AND status!='completed' ORDER BY status, source, chunk_index",
            (kg_id,),
        ).fetchall()
        totals = dict(
            conn.execute(
                "SELECT status, COUNT(*) FROM task_queue WHERE kg_id=? GROUP BY status",
                (kg_id,),
            ).fetchall()
        )
    finally:
        conn.close()

    groups: dict[tuple[str, str], list[tuple[int, str, str]]] = defaultdict(list)
    for source, chunk_index, status, updated_at in rewritten:
        groups[(source, updated_at[:10])].append((chunk_index, updated_at[11:16], status))

    lines = [
        f"KG `{kg_id}` 佇列狀態：" + "、".join(f"{k} {v}" for k, v in sorted(totals.items())),
        "",
        f"## {since} 之後被改寫的 chunk（updated_at 為 UTC，僅記錄最後一次寫入）",
        "",
        "| 日期(UTC) | 時間 | 文件 | chunk 數 | chunk 索引 | 狀態 |",
        "|---|---|---|---|---|---|",
    ]
    ordered = sorted(groups.items(), key=lambda kv: (kv[0][1], kv[1][0][1]))
    for (source, day), items in ordered:
        indices = [i for i, _, _ in items]
        statuses = "/".join(sorted({s for _, _, s in items}))
        span = f"{min(t for _, t, _ in items)}–{max(t for _, t, _ in items)}"
        lines.append(f"| {day} | {span} | {source} | {len(indices)} | {_compact(indices)} | {statuses} |")

    lines += ["", "## 非 completed 的 chunk", "", "| 文件 | chunk | 狀態 | updated_at(UTC) |", "|---|---|---|---|"]
    if unfinished:
        for source, chunk_index, status, updated_at in unfinished:
            lines.append(f"| {source} | {chunk_index} | {status} | {updated_at} |")
    else:
        lines.append("| （無） | | | |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kg-id", required=True)
    parser.add_argument("--since", default="2026-09-12")
    parser.add_argument("--db", default=r"D:\Users\666\Desktop\kg-runtime\task_queue.db")
    args = parser.parse_args()
    print(build_manifest(args.db, args.kg_id, args.since), end="")


if __name__ == "__main__":
    main()
