"""Re-extract specific SVO chunks and verify the REAL outcome from task_queue.db.

`_process_one()` swallows extraction errors and only marks the chunk `failed`,
so "no exception" is not success.  This runner resets each chunk to pending,
revokes its old Facts, runs `_process_one()`, then reads the queue status back.
A chunk that ends up `failed` is retried up to `--retries` times; exit code is 1
if any chunk is not `completed` at the end.  Logging is on so the traceback that
`_process_one()` logs on failure is visible.

Run with the process CWD anywhere, but export WORKSPACE_DIR / NEO4J_* first
(the worktree .env uses a relative WORKSPACE_DIR):

    python scripts/kg/reextract_chunks.py --kg-id <uuid> \
        --chunk "N0060041_職業災害勞工保護法:8,23,24" --chunk "N0030006_勞工請假規則:3,8"
"""
from __future__ import annotations

import argparse
import asyncio
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


async def run(kg_id: str, targets: list[tuple[str, int]], retries: int) -> int:
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
    try:
        for source, chunk_index in targets:
            doc_id = str(document_record_service.document_uuid(source))
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
    finally:
        await disconnect()

    print("\n=== 結果（讀自 task_queue.db）===", flush=True)
    failed = 0
    for source, chunk_index, status, attempts, seconds in results:
        if status != "completed":
            failed += 1
        print(f"{source} c{chunk_index}: {status} (嘗試 {attempts} 次, {seconds / 60:.1f} 分)", flush=True)
    print(f"\n完成 {len(results) - failed} / {len(results)}；未完成 {failed}", flush=True)
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kg-id", required=True)
    parser.add_argument("--chunk", action="append", required=True, help="source:1,2,3（可重複）")
    parser.add_argument("--retries", type=int, default=1, help="failed 時額外重試次數")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    targets = parse_chunk_specs(args.chunk)
    sys.exit(asyncio.run(run(args.kg_id, targets, args.retries)))


if __name__ == "__main__":
    main()
