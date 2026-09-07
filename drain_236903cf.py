"""reextract-v2 KG 236903cf 的 kg-scoped SVO 抽取 drain。

- 只吃 `kg_id=236903cf` 的 pending（不碰其他 KG）。
- 每個 chunk 先 `revoke_chunk_facts()` 清可能的殘留（中斷重試才有作用，
  乾淨 chunk 是 no-op），再 `_process_one()` 抽取。
- 中止後直接重跑即從剩餘 pending 續（`task_queue.db` 是狀態來源）。
- **從本 worktree 目錄跑**，`.env` 的 `WORKSPACE_DIR=D:/Users/666/Desktop/kg-runtime`
  才會生效（task_queue.db + chunk 原文都在那，git 樹外）。
- **不要**同時跑 `main.py` 全域 worker 或 `rebuild_from_records()`。

用法：
    cd "D:/Users/666/Desktop/world knowledge graph rag/.claude/worktrees/kg-reextract"
    nohup python -u drain_236903cf.py >> "<job>/tmp/drain_236903cf.log" 2>&1 &
"""
from __future__ import annotations

import asyncio
import time
from uuid import UUID

from core.database import connect, disconnect, get_driver
from core.providers.factory import init_providers
from core.config import task_queue_db_path
from services.extraction_worker import _process_one
from services.task_queue_service import next_pending
from services.svo_service import revoke_chunk_facts
from services import document_record_service

KG_STR = "236903cf-055a-40a8-8923-b9d06601f3b7"
KG = UUID(KG_STR)
EMPTY_EXITS = 4
EMPTY_SLEEP = 5.0


async def main() -> None:
    await connect()
    init_providers()
    driver = get_driver()
    db_path = task_queue_db_path()
    print(f"drain 開始：kg={KG_STR}  db={db_path}", flush=True)
    processed = 0
    empties = 0
    t0 = time.monotonic()
    while True:
        pending = next_pending(db_path, kg_id=KG_STR)
        if pending is None:
            empties += 1
            if empties >= EMPTY_EXITS:
                break
            await asyncio.sleep(EMPTY_SLEEP)
            continue
        empties = 0
        kg_id, source, chunk_index = pending
        try:
            doc_id = str(document_record_service.document_uuid(source))
            await revoke_chunk_facts(driver, KG, doc_id, chunk_index)
            await _process_one(driver, kg_id, source, chunk_index)
        except Exception as e:
            print(f"  !! {source} c{chunk_index} 例外：{e!r}", flush=True)
        processed += 1
        if processed % 20 == 0:
            rate = processed / (time.monotonic() - t0)
            print(f"已處理 {processed} 筆（{rate*3600:.0f}/hr）", flush=True)
    dt = time.monotonic() - t0
    print(f"DRAIN-DONE：本次處理 {processed} 筆，耗時 {dt/3600:.1f} 小時", flush=True)
    await disconnect()


if __name__ == "__main__":
    asyncio.run(main())
