# -*- coding: utf-8 -*-
"""報告57 任務C 第8組聚合題材候選（私立就業服務機構許可雙來源授權鏈）
Stage 0 targeted重抽（僅重抽，尚未出題）。

框架：N0090002_私立就業服務機構許可及管理辦法（子法）§1「依就業服務法
（以下簡稱本法）第三十四條第三項及第四十條第二項規定訂定之」——又一個
雙來源授權（母法N0090001兩條不同條文共同授權同一子法，跟第6/7組候選同
一模式）。§34(3)是廣泛的設立許可管理辦法授權，§40(2)是窄化的單一款項
（第十七款外國人行蹤不明人數比率）查核辦法授權——兩者授權範圍寬窄不同，
跟第6/7組「兩條範圍相近」的雙來源結構略有差異，值得作為題材多樣性補充。

已直接讀`original.md`與對應svo-chunk-*.md逐字核對，內容與所引用條號一致。

targeted chunk（不重抽整份文件——子法48個SVO chunk、母法84個，只碰真正
需要的條文）：
  - N0090002 chunk 1（§1法源依據）
  - N0090001 chunk 34/40（§34設立許可授權、§40行蹤不明查核授權）

安全模式（同任務C第2-7組）：不走force_rebuild=True，改用
task_queue_service.enqueue()把終態重置為pending，逐一revoke_chunk_facts()
+_process_one()。

前置：主drain（drain_236903cf.py）必須確認未在跑。

用法：
    cd "D:/Users/666/Desktop/world knowledge graph rag/.claude/worktrees/kg-reextract"
    OLLAMA_EMBEDDING_NUM_GPU=0 nohup python -u reextract_private_agency_pilot.py \
        >> "<job>/tmp/reextract_private_agency_pilot.log" 2>&1 &
完成訊號：PILOT-DONE
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
    ("N0090002_私立就業服務機構許可及管理辦法", [1]),
    ("N0090001_就業服務法", [34, 40]),
]


async def run_one(driver, source: str, chunk_indices: list[int]) -> tuple[int, int]:
    doc_id = str(document_record_service.document_uuid(source))
    t0 = time.monotonic()
    done = fail = 0
    for i, chunk_index in enumerate(chunk_indices, 1):
        try:
            await revoke_chunk_facts(driver, KG, doc_id, chunk_index)
            await _process_one(driver, KG_STR, source, chunk_index)
            done += 1
        except Exception as e:  # noqa: BLE001
            fail += 1
            print(f"  !! {source} c{chunk_index} 例外：{e!r}", flush=True)
        elapsed = time.monotonic() - t0
        rate = (i / elapsed * 60) if elapsed > 0 else 0.0
        print(f"  [{source}][{i}/{len(chunk_indices)}] done={done} fail={fail}  {rate:.1f}/min", flush=True)
    dt = time.monotonic() - t0
    print(f"{source}：{done} 成功 / {fail} 失敗，耗時 {dt/60:.1f} 分\n", flush=True)
    return done, fail


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
        print(f"\n=== 開始：{source}（{len(chunk_indices)} chunk）===", flush=True)
        done, fail = await run_one(driver, source, chunk_indices)
        total_done += done
        total_fail += fail

    dt = time.monotonic() - t0
    print(f"\n全部完成：{total_done} 成功 / {total_fail} 失敗，總耗時 {dt/60:.1f} 分", flush=True)
    print("\nPILOT-DONE", flush=True)
    await disconnect()


if __name__ == "__main__":
    asyncio.run(main())
