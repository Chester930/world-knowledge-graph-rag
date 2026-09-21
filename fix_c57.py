# -*- coding: utf-8 -*-
"""緊急修補：worker1在重跑N0030001 chunk 57途中被Stop-Process中止，
revoke_chunk_facts()已執行但_process_one()來不及完成，導致chunk 57
（§50產假工資）的Fact被清空、task_queue.db卡在processing。重新處理。
"""
from __future__ import annotations

import asyncio
import os
import sys
from uuid import UUID

WT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, WT)
os.chdir(WT)

from core.database import connect, disconnect, get_driver  # noqa: E402
from core.providers.factory import init_providers  # noqa: E402
from services.extraction_worker import _process_one  # noqa: E402
from services.svo_service import revoke_chunk_facts  # noqa: E402
from services import document_record_service  # noqa: E402

KG_STR = "236903cf-055a-40a8-8923-b9d06601f3b7"
KG = UUID(KG_STR)
SOURCE = "N0030001_勞動基準法"
CHUNK_INDEX = 57


async def main() -> None:
    await connect()
    init_providers()
    driver = get_driver()
    doc_id = str(document_record_service.document_uuid(SOURCE))
    await revoke_chunk_facts(driver, KG, doc_id, CHUNK_INDEX)
    await _process_one(driver, KG_STR, SOURCE, CHUNK_INDEX)
    print("FIX-C57-DONE", flush=True)
    await disconnect()


if __name__ == "__main__":
    asyncio.run(main())
