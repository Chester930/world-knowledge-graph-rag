# -*- coding: utf-8 -*-
"""報告57 任務C 第9組聚合題材候選（職安衛管理辦法風險分級+單一授權鏈）
Stage 0 targeted重抽（僅重抽，尚未出題）。

框架：N0060027_職業安全衛生管理辦法（子法）§1「依職業安全衛生法（以下
簡稱本法）第二十三條第五項規定訂定之」——單一來源授權（跟第1/2/3/4組
候選同一模式，作為與第6/7/8組雙來源結構的對照）。子法§2把事業依危害
風險分三類（第一類顯著風險/第二類中度風險/第三類低度風險），§2-1訂有
對應的職業安全衛生管理單位設置人數門檻（第一類事業100人以上、第二類
事業300人以上）——是天然的風險分級+對應組織門檻聚合題材，跟第1組候選
（健康檢查頻率）的分級邏輯類似但換了完全不同的規範主題。

已直接讀`original.md`與對應svo-chunk-*.md逐字核對，內容與所引用條號一致。

targeted chunk（不重抽整份文件——子法107個SVO chunk、母法61個，只碰真正
需要的條文）：
  - N0060027 chunk 1/3/4（§1法源依據、§2風險三分類、§2-1對應人數門檻）
  - N0060001 chunk 27（§23第5項授權條款）

安全模式（同任務C第2-8組）：不走force_rebuild=True，改用
task_queue_service.enqueue()把終態重置為pending，逐一revoke_chunk_facts()
+_process_one()。

前置：主drain（drain_236903cf.py）必須確認未在跑。

用法：
    cd "D:/Users/666/Desktop/world knowledge graph rag/.claude/worktrees/kg-reextract"
    OLLAMA_EMBEDDING_NUM_GPU=0 nohup python -u reextract_osh_management_pilot.py \
        >> "<job>/tmp/reextract_osh_management_pilot.log" 2>&1 &
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
    ("N0060027_職業安全衛生管理辦法", [1, 3, 4]),
    ("N0060001_職業安全衛生法", [27]),
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
