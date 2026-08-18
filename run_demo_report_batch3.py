"""第三批補充問題（5題併入報告13使其達15題，1題併入報告14使其達15題）。
同樣經 Claude 親自讀取 `workspace/` 下 `original.md` 原文核對過內容與
答案後才挑選。

用法：python run_demo_report_batch3.py > demo_report_batch3_raw.txt 2>&1
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

# (報告13題號, KG, 問題, 已核對的原文正確答案, 原文來源)
REPORT13_QUESTIONS = [
    (
        11, KG_SCHEDULING,
        "勞工出差往返的交通時間算工作時間嗎？",
        "若非在雇主監督下，得不計入工作時間；若出差交通時間適逢正常工作時間，工資應照給；若係正常工作時間外由雇主指派駕駛交通工具載運員工或器材，該交通時間應計入工作時間。",
        "內政部_台內勞字第356410號函/original.md",
    ),
    (
        12, KG_SCHEDULING,
        "計算平均工資時，哪些期間不計入計算？",
        "計算事由發生之當日；因職業災害尚在醫療中者；依第五十條第二項減半發給工資者；雇主因天災事變或其他不可抗力不能繼續其事業致勞工未能工作者；依勞工請假規則請普通傷病假者；依性別平等工作法請生理假、產假、家庭照顧假或安胎休養致減少工資者；留職停薪者。",
        "勞動基準法施行細則_全文_中華民國政府發布/original.md 第2條",
    ),
    (
        13, KG_SCHEDULING,
        "哪些行業可以適用勞動基準法第三十條之一的四週變形工時？",
        "住宿及餐飲業、保全業、醫療保健服務業、社會福利服務業、百貨公司業等。",
        "勞動基準法第三十條第二項第三項及第三十條之一指定行業公告_中華民國政府發布/original.md",
    ),
    (
        14, KG_LEAVE_PAY,
        "雇主可以不經勞工同意就把工資改成用實物或禮券折抵嗎？",
        "不可以。工資調整應經勞工同意，非經勞工同意雇主不得改以實物或公司禮券折抵。",
        "內政部_台內勞字第342080號/original.md",
    ),
    (
        15, KG_LEAVE_PAY,
        "勞工保險生育給付的請領條件與給付標準是什麼？",
        "條件：參加保險滿280日後分娩、滿181日後早產、或滿84日後流產。標準：分娩或早產者按平均月投保薪資一次給與分娩費30日（流產減半），並另給生育補助費60日；雙生以上者比例增給。",
        "勞工保險條例_全文_中華民國政府發布/original.md 第31、32條",
    ),
]

# (報告14題號, KG, 問題, 已核對的原文正確答案, 原文來源)
REPORT14_QUESTIONS = [
    (
        25, KG_LEAVE_PAY,
        "私立就業服務機構依設立目的可以分為哪兩種？",
        "營利就業服務機構（依公司法設立之公司或依商業登記法設立之商業組織）與非營利就業服務機構（依法設立之財團、以公益為目的之社團或其他非以營利為目的之組織）。",
        "就業服務法施行細則_全文_中華民國政府發布/original.md 第2條",
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


async def _run_batch(label: str, questions: list) -> None:
    for idx, kg_id, question, ground_truth, source_ref in questions:
        print(f"\n{'=' * 70}")
        print(f"# [{label}] 題 {idx}｜KG={kg_id}")
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


async def main() -> None:
    await connect()
    init_providers()
    try:
        await _run_batch("報告13", REPORT13_QUESTIONS)
        await _run_batch("報告14", REPORT14_QUESTIONS)
    finally:
        await disconnect()


if __name__ == "__main__":
    asyncio.run(main())
