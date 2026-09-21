# -*- coding: utf-8 -*-
"""報告57 任務C 第5組聚合題材（中高齡/高齡就業促進母法子法授權鏈）Stage 0 targeted重抽。

框架：N0090055_中高齡者及高齡者就業促進法（母法）§27「前三條所定補助...之辦法，
由中央主管機關定之」授權訂定N0090058_失業中高齡者及高齡者就業促進辦法（子法），
子法§1明文引用母法§27。母法§24另規定雇主可自行/委託辦理職業訓練並可獲訓練費用
補助；子法把「雇主自行辦理訓練」（§6：最低開班人數5人、時數不低於80小時）與
「失業者個人參訓」（§4：全額補助，不設班級人數門檻）兩種申請補助路徑分開規範
——兩條路徑條件不同，是測試系統會不會混淆兩種補助路徑的天然聚合題材。

已直接讀`original.md`與對應svo-chunk-*.md逐字核對，內容與所引用條號一致，
無需再查Neo4j（本組chunk自2026-09-07起即未重抽，早於guard修復commit，
重新重抽同時確保套用最新的_LEAVE_TYPE_FAMILY/_MEASURE_PATTERN等guard）。

targeted chunk（不重抽整份文件——母法45個SVO chunk、子法49個，只碰真正需要
的條文）：
  - N0090055 chunk 24/25/26/27（§24 雇主辦訓練授權、§25 創業協助、§26 就業
    協助津貼、§27 細節辦法授權條款——四條合看才完整，§27明文「前三條」）
  - N0090058 chunk 1/4/5/6（§1 法源依據引用母法§27、§4 個人參訓全額補助、
    §5 高齡者職業訓練專班規定、§6 雇主辦訓練最低5人/80小時門檻）

安全模式（同任務C第2/3/4組）：不走force_rebuild=True，改用
task_queue_service.enqueue()把終態重置為pending，逐一revoke_chunk_facts()
+_process_one()。

前置：主drain（drain_236903cf.py）必須確認未在跑。

用法：
    cd "D:/Users/666/Desktop/world knowledge graph rag/.claude/worktrees/kg-reextract"
    OLLAMA_EMBEDDING_NUM_GPU=0 nohup python -u reextract_age_employment_pilot.py \
        >> "<job>/tmp/reextract_age_employment_pilot.log" 2>&1 &
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
    ("N0090055_中高齡者及高齡者就業促進法", [24, 25, 26, 27]),
    ("N0090058_失業中高齡者及高齡者就業促進辦法", [1, 4, 5, 6]),
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
