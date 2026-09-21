# -*- coding: utf-8 -*-
"""報告57 任務C 第3組聚合題材（職災新舊法交替陷阱）Stage 0 最小 pilot 重抽。

框架：N0050031_勞工職業災害保險及保護法（新法，2022年施行）§106/§107明文
「自本法施行之日起，職業災害勞工保護法不再適用」，但§101/§104/§105/§106
又列了「本法施行前」的過渡期grandfather clause（舊案件仍依舊法辦理）。這是
真實的新舊法交替陷阱——若不分時間點，直接引用N0060041（舊法）的補助規則
會答錯。

targeted chunk（不重抽整份文件——N0050031有109個SVO chunk、N0060041有41個，
只碰真正需要的條文）：
  - N0060041 chunk 8   （§8 生活津貼——舊法補助項目，跟新法對照用）
  - N0050031 chunk 101 （§101 舊法補助過渡期）
  - N0050031 chunk 104 （§104 已請領舊法給付者的選擇權）
  - N0050031 chunk 105 （§105 未加入保險者仍依舊法申請補助）
  - N0050031 chunk 106 （§106 未終結案件仍依舊法辦理 + 核心廢止宣告）
  - N0050031 chunk 107 （§107，緊接廢止條文之後，先納入確認銜接無誤）

安全模式（同任務C第2組用過的模式）：不走force_rebuild=True（ArticleAware
文件會拋錯），改用task_queue_service.enqueue()把終態重置為pending，逐一
revoke_chunk_facts()+_process_one()。

用法：
    cd "D:/Users/666/Desktop/world knowledge graph rag/.claude/worktrees/kg-reextract"
    OLLAMA_EMBEDDING_NUM_GPU=0 nohup python -u reextract_old_new_law_pilot.py \
        >> "<job>/tmp/reextract_old_new_law_pilot.log" 2>&1 &
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
    ("N0060041_職業災害勞工保護法", [8]),
    ("N0050031_勞工職業災害保險及保護法", [101, 104, 105, 106, 107]),
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
