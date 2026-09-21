# -*- coding: utf-8 -*-
"""報告57 任務C 第2組聚合題材（請假期間工資對照）Stage 0 重抽（第二批）。

第一批（N0030006單一文件13 chunk）已完成，發現決定性幻覺+列舉漏抽兩個抽取
品質bug（記錄為已知限制，見報告57 §4.4／memory），使用者裁示不深入修根因、
任務C繼續往下走。

本批目標：
  - N0030014_性別平等工作法：全文49個SVO chunk（核心比較文件，生理假/產假/
    產檢假/陪產假/家庭照顧假/育嬰留停等工資規則）
  - N0030001_勞動基準法：只重抽 chunk 57（§50 產假工資）、chunk 66（§59
    職災醫療期間原領工資補償）——不重抽全部98 chunk，這兩條已用
    `grep -l "第 50 條"`／`"第 59 條"` 對 svo-chunk frontmatter 精準定位
  - N0060041_職業災害勞工保護法：只重抽 chunk 29（§29，普通傷病假→公傷病假
    轉銜橋接條文）——不重抽全部41 chunk

安全模式（同第一批）：不走 `knowledge_graph_service.build_graph(force_rebuild=True)`
（對ArticleAware文件會拋`ArticleStructureLossError`），改用
`task_queue_service.enqueue()`把終態(completed)重置為pending，逐一
`revoke_chunk_facts()` + `_process_one()`，沿用既有chunking。

前置：**主 drain（drain_236903cf.py）必須確認未在跑**。

用法：
    cd "D:/Users/666/Desktop/world knowledge graph rag/.claude/worktrees/kg-reextract"
    OLLAMA_EMBEDDING_NUM_GPU=0 nohup python -u reextract_leave_wage_pilot.py \
        >> "<job>/tmp/reextract_leave_wage_batch2.log" 2>&1 &
完成訊號：ALL-DONE
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
    ("N0030014_性別平等工作法", list(range(1, 50))),  # 全文 49 chunk
    ("N0030001_勞動基準法", [57, 66]),  # §50 產假工資、§59 職災工資補償
    ("N0060041_職業災害勞工保護法", [29]),  # §29 橋接條文
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
    print("\nALL-DONE", flush=True)
    await disconnect()


if __name__ == "__main__":
    asyncio.run(main())
