"""Re-extract specific SVO chunks and verify the REAL outcome from task_queue.db.

`_process_one()` swallows extraction errors and only marks the chunk `failed`,
so "no exception" is not success.  This runner resets each chunk to pending,
revokes its old Facts, runs `_process_one()`, then reads the queue status back.
A chunk that ends up `failed` is retried up to `--retries` times; exit code is 1
if any chunk is not `completed` at the end.  Logging is on so the traceback that
`_process_one()` logs on failure is visible.

**Content-loss guard (2026-09-22, 報告65 §6/§7 真實案例)**: a chunk can end up
`completed` while silently losing information — `57-CANARY5`（N0050031 c101）
collapsed from 3 facts carrying partial conditions to 1 fact with none of them,
worse than before re-extraction, yet the queue status was `completed` throughout.
This runner now snapshots each chunk's `fact_text` list *before* revoking, and
compares total character count against the post-extraction snapshot. A drop
below `--content-loss-threshold` (default 0.7 = new total < 70% of old total)
is flagged in the printed summary and written to `<db_path's dir>/
content_loss_flags.json` for manual review — it does **not** block or retry
automatically (this is a deterministic, mechanical heuristic, not a judgement
of correctness; a legitimate consolidation of redundant facts can also trigger
it, so a human must look before deciding to revert or re-run).

Run with the process CWD anywhere, but export WORKSPACE_DIR / NEO4J_* first
(the worktree .env uses a relative WORKSPACE_DIR):

    python scripts/kg/reextract_chunks.py --kg-id <uuid> \
        --chunk "N0060041_職業災害勞工保護法:8,23,24" --chunk "N0030006_勞工請假規則:3,8"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)


def parse_chunk_specs(specs: list[str]) -> list[tuple[str, int]]:
    targets: list[tuple[str, int]] = []
    for spec in specs:
        source, _, indices = spec.rpartition(":")
        if not source or not indices:
            raise ValueError(f"--chunk 格式應為 'source:1,2,3'，收到：{spec!r}")
        targets.extend((source, int(i)) for i in indices.split(",") if i.strip())
    return targets


def read_status(db_path: Path, kg_id: str, source: str, chunk_index: int) -> str | None:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT status FROM task_queue WHERE kg_id=? AND source=? AND chunk_index=?",
            (kg_id, source, chunk_index),
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


async def _snapshot_fact_texts(driver, kg_id, doc_id: str, chunk_index: int) -> list[str]:
    """唯讀快照：這個 chunk 目前所有 `Fact.fact_text`，供內容流失防護閘門
    比對前後總字數（見模組 docstring「Content-loss guard」）。MATCH 條件
    比照 `revoke_chunk_facts()` 既有查詢，不做任何寫入。"""
    result = await driver.execute_query(
        """
        MATCH (f:Fact {kg_id: $kg_id, source_doc_id: $source_doc_id, source_svo_chunk_index: $chunk_index})
        RETURN f.fact_text AS fact_text
        """,
        kg_id=str(kg_id),
        source_doc_id=doc_id,
        chunk_index=chunk_index,
    )
    return [r["fact_text"] for r in result.records if r["fact_text"]]


def _content_loss_ratio(before_texts: list[str], after_texts: list[str]) -> float | None:
    """`after` 總字數 / `before` 總字數。`before` 為空（例如這個 chunk 先前
    從未抽出任何 Fact）時回傳 `None`（不適用，不能除以零，也不該被判定為
    流失）。"""
    before_total = sum(len(t) for t in before_texts)
    if before_total == 0:
        return None
    after_total = sum(len(t) for t in after_texts)
    return after_total / before_total


async def run(
    kg_id: str, targets: list[tuple[str, int]], retries: int, content_loss_threshold: float,
) -> int:
    from core.config import settings, task_queue_db_path
    from core.database import connect, disconnect, get_driver
    from core.providers.factory import init_providers
    from services import document_record_service
    from services.extraction_worker import _process_one
    from services.svo_service import revoke_chunk_facts
    from services.task_queue_service import enqueue

    db_path = task_queue_db_path()
    print(
        f"task_queue.db={db_path} llm={settings.llm_provider} "
        f"embedding={settings.embedding_provider}",
        flush=True,
    )
    await connect()
    init_providers()
    driver = get_driver()
    kg = UUID(kg_id)

    results: list[tuple[str, int, str | None, int, float]] = []
    content_loss_flags: list[dict] = []
    try:
        for source, chunk_index in targets:
            doc_id = str(document_record_service.document_uuid(source))
            before_texts = await _snapshot_fact_texts(driver, kg, doc_id, chunk_index)
            status: str | None = None
            attempts = 0
            started = time.monotonic()
            while attempts <= retries:
                attempts += 1
                enqueue(db_path, kg_id, source, [chunk_index])
                await revoke_chunk_facts(driver, kg, doc_id, chunk_index)
                await _process_one(driver, kg_id, source, chunk_index)
                status = read_status(db_path, kg_id, source, chunk_index)
                print(
                    f"  {source} c{chunk_index} attempt {attempts}: {status}",
                    flush=True,
                )
                if status == "completed":
                    break
            results.append((source, chunk_index, status, attempts, time.monotonic() - started))

            if status == "completed":
                after_texts = await _snapshot_fact_texts(driver, kg, doc_id, chunk_index)
                ratio = _content_loss_ratio(before_texts, after_texts)
                if ratio is not None and ratio < content_loss_threshold:
                    print(
                        f"  ⚠️  {source} c{chunk_index} 內容流失警告：重抽後總字數為重抽前的"
                        f" {ratio:.0%}（門檻 {content_loss_threshold:.0%}）——這是機械式字數比對，"
                        f"不代表判斷一定錯，但需要人工核對 fact_text 是否真的漏掉限定條件",
                        flush=True,
                    )
                    content_loss_flags.append({
                        "source": source,
                        "chunk_index": chunk_index,
                        "ratio": ratio,
                        "before_texts": before_texts,
                        "after_texts": after_texts,
                    })
    finally:
        await disconnect()

    print("\n=== 結果（讀自 task_queue.db）===", flush=True)
    failed = 0
    for source, chunk_index, status, attempts, seconds in results:
        if status != "completed":
            failed += 1
        print(f"{source} c{chunk_index}: {status} (嘗試 {attempts} 次, {seconds / 60:.1f} 分)", flush=True)
    print(f"\n完成 {len(results) - failed} / {len(results)}；未完成 {failed}", flush=True)

    if content_loss_flags:
        flags_path = db_path.parent / "content_loss_flags.json"
        existing: list[dict] = []
        if flags_path.is_file():
            existing = json.loads(flags_path.read_text(encoding="utf-8"))
        existing.extend(content_loss_flags)
        flags_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            f"\n⚠️  {len(content_loss_flags)} 個 chunk 觸發內容流失警告，已寫入 {flags_path}"
            "（需人工複核，本工具不自動回復或阻擋）",
            flush=True,
        )

    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kg-id", required=True)
    parser.add_argument("--chunk", action="append", required=True, help="source:1,2,3（可重複）")
    parser.add_argument("--retries", type=int, default=1, help="failed 時額外重試次數")
    parser.add_argument(
        "--content-loss-threshold", type=float, default=0.7,
        help="重抽後總字數低於重抽前這個比例就標記警告（預設0.7＝70%%），見模組docstring",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    targets = parse_chunk_specs(args.chunk)
    sys.exit(asyncio.run(run(args.kg_id, targets, args.retries, args.content_loss_threshold)))


if __name__ == "__main__":
    main()
