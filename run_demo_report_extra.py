"""補充題庫（題 11-14）：針對既有 10 題以外、且已由 Claude 親自讀取
`workspace/` 下 `original.md` 原文核對過內容與答案的 4 個新問題，執行一次
真實、非模擬的端到端查詢。挑選標準：來源文件標題與實際內容一致（已人工
核對，排除掉抽樣中發現的 3 份標題與內容不符的文件——見
docs/報告/13_..._2026-08-18.md 補充章節）。

用法：python run_demo_report_extra.py > demo_report_extra_raw.txt 2>&1
"""
from __future__ import annotations

import asyncio
import json
import time
from uuid import UUID

from core.database import connect, disconnect, get_driver
from core.providers.factory import init_providers
from models.document import ChatRequest
from routers.agent import chat

KG_SCHEDULING = UUID("deb24e7c-c012-4398-9261-c813cb60b197")  # 排班與工時法規
KG_LEAVE_PAY = UUID("2ae9d28b-3c5e-424f-9ea4-c3cbe59a2934")   # 請假與薪資法規

# (題號, KG, 問題, 已核對的原文正確答案, 原文來源)
QUESTIONS = [
    (
        11, KG_SCHEDULING,
        "汽車運輸業駕駛人的每日工作時間及駕駛時間上限是多少？",
        "每日正常+延長工時總計不得超過十二小時；每日駕駛時間不得超過十小時；連續駕車四小時，至少應有三十分鐘之休息。",
        "汽車運輸業管理規則_部分摘錄_駕駛工時與排班限制_中華民國政府發布/original.md 第19-1條",
    ),
    (
        12, KG_SCHEDULING,
        "船員在任意二十四小時內的休息時間規定是什麼？",
        "任意二十四小時內，船員之休息時間不得少於十小時；任意七日內，總休息時間不得少於七十七小時。",
        "船員法_部分摘錄_工作與休息時間規定_中華民國政府發布/original.md 第37條",
    ),
    (
        13, KG_LEAVE_PAY,
        "職業安全衛生法規定，雇主僱用勞工時應施行什麼檢查？",
        "雇主於僱用勞工時應施行體格檢查；對在職勞工應施行一般健康檢查，從事特別危害健康作業者另施行特殊健康檢查。",
        "職業安全衛生法_全文_中華民國政府發布/original.md 第20條",
    ),
    (
        14, KG_LEAVE_PAY,
        "雇主為勞工提繳退休金的法定最低比例是多少？",
        "雇主應為勞工負擔提繳之退休金，不得低於勞工每月工資百分之六。",
        "勞工退休金條例_全文_中華民國政府發布/original.md 第14條",
    ),
]


async def _run_one(kg_id: UUID, question: str) -> dict:
    payload = ChatRequest(question=question, kg_id=kg_id)
    t0 = time.monotonic()
    response = await chat(payload)

    answer_parts: list[str] = []
    sources: dict | None = None
    error: str | None = None
    async for chunk in response.body_iterator:
        if chunk.startswith("event: error"):
            error = json.loads(chunk.split("\n", 1)[1][len("data: "):])["message"]
        elif chunk.startswith("event: sources"):
            sources = json.loads(chunk.split("\n", 1)[1][len("data: "):])
        elif chunk.startswith("data: "):
            answer_parts.append(json.loads(chunk[len("data: "):])["token"])
    elapsed = time.monotonic() - t0

    return {
        "answer": "".join(answer_parts),
        "sources": sources,
        "error": error,
        "elapsed_seconds": round(elapsed, 1),
    }


async def main() -> None:
    await connect()
    init_providers()
    try:
        for idx, kg_id, question, ground_truth, source_ref in QUESTIONS:
            print(f"\n{'=' * 70}")
            print(f"# 題 {idx}｜KG={kg_id}")
            print(f"【問題】{question}")
            print(f"【已核對的原文正確答案】{ground_truth}")
            print(f"【原文來源】{source_ref}")
            result = await _run_one(kg_id, question)
            print(f"【耗時】{result['elapsed_seconds']} 秒")
            if result["error"]:
                print(f"【錯誤】{result['error']}")
                continue
            print(f"【系統實際回答】\n{result['answer']}")
            sources = result["sources"] or {}
            triples = sources.get("triples", [])
            facts = sources.get("facts", [])
            print(f"【解析出的關係型別】{sources.get('resolved_rel_type') or '（未解析出／QNOMATCH）'}")
            print(f"【BFS 三元組筆數】{len(triples)}")
            print(f"【語意 Fact 筆數】{len(facts)}")
            for t in triples[:15]:
                print(
                    f"  - {t['subject']}（{t['subject_type']}）-[{t['rel_type']}]{t['verb']}→"
                    f"{t['object']}（{t['object_type']}）  來源：{t.get('source_svo_chunk_file') or '（無）'}"
                )
            if len(triples) > 15:
                print(f"  ...（另有 {len(triples) - 15} 筆，未列出）")
            for f in facts:
                print(f"  - [Fact] {f['fact_text']}  (score={f.get('score')})")
            print(f"{'=' * 70}\n")
    finally:
        await disconnect()


if __name__ == "__main__":
    asyncio.run(main())
