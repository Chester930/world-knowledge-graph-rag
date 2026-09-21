# -*- coding: utf-8 -*-
"""報告57 任務C 第2組聚合題材——worker 2（獨立文件，零碰撞風險）。

worker 1（reextract_leave_wage_pilot.py，PID還在跑）目前在處理
N0030014_性別平等工作法（49 chunk，循序1→49，非atomic claim），本腳本
只碰完全不同的另外2份文件（N0030001／N0060041），worker 1要等N0030014
全部49個做完才會碰到這2份文件，兩者不會撞到同一個chunk_index，安全並行。

用法：
    cd "D:/Users/666/Desktop/world knowledge graph rag/.claude/worktrees/kg-reextract"
    OLLAMA_EMBEDDING_NUM_GPU=0 nohup python -u reextract_leave_wage_worker2.py \
        >> "<job>/tmp/reextract_leave_wage_worker2.log" 2>&1 &
完成訊號：WORKER2-DONE
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from uuid import UUID

WT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, WT)
os.chdir(WT)

from core.database import connect, disconnect, get_driver  # noqa: E402
from core.providers.factory import init_providers  # noqa: E402
from core.config import task_queue_db_path  # noqa: E402
from services.extraction_worker import _process_one  # noqa: E402
from services.svo_service import revoke_chunk_facts  # noqa: E402
from services.task_queue_service import enqueue  # noqa: E402
from services import document_record_service  # noqa: E402

KG_STR = "236903cf-055a-40a8-8923-b9d06601f3b7"
KG = UUID(KG_STR)

TARGETS: list[tuple[str, list[int]]] = [
    ("N0030001_勞動基準法", [57, 66]),  # §50 產假工資、§59 職災工資補償
    ("N0060041_職業災害勞工保護法", [29]),  # §29 橋接條文
]


async def main() -> None:
    db_path = task_queue_db_path()
    print(f"task_queue.db = {db_path}", flush=True)

    for source, chunk_indices in TARGETS:
        enqueue(db_path, KG_STR, source, chunk_indices)
        print(f"已把 {source} 的 {len(chunk_indices)} 個 SVO chunk 終態重置為 pending", flush=True)

    await connect()
    init_providers()
    driver = get_driver()

    total_done = total_fail = 0
    t0 = time.monotonic()
    for source, chunk_indices in TARGETS:
        doc_id = str(document_record_service.document_uuid(source))
        for i, chunk_index in enumerate(chunk_indices, 1):
            try:
                await revoke_chunk_facts(driver, KG, doc_id, chunk_index)
                await _process_one(driver, KG_STR, source, chunk_index)
                total_done += 1
            except Exception as e:  # noqa: BLE001
                total_fail += 1
                print(f"  !! {source} c{chunk_index} 例外：{e!r}", flush=True)
            print(f"  [{source}][{i}/{len(chunk_indices)}] done={total_done} fail={total_fail}", flush=True)

    dt = time.monotonic() - t0
    print(f"\n完成：{total_done} 成功 / {total_fail} 失敗，耗時 {dt/60:.1f} 分", flush=True)
    print("\nWORKER2-DONE", flush=True)
    await disconnect()


if __name__ == "__main__":
    asyncio.run(main())
