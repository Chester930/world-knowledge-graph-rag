"""第二批補充題庫（題 15-24）：同樣經 Claude 親自讀取 `workspace/` 下
`original.md` 原文核對過內容與答案後才挑選的問題。挑選時額外發現多起
文件標題與內容不符的案例（見 docs/報告/14_...md），本批問題全部來自
已核對確認內容與標題相符的文件。

用法：python run_demo_report_batch2.py > demo_report_batch2_raw.txt 2>&1
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
        15, KG_SCHEDULING,
        "勞工結婚可以請幾天婚假？工資怎麼計算？",
        "婚假八日，工資照給。",
        "勞工請假規則_全文_中華民國政府發布/original.md 第2條",
    ),
    (
        16, KG_SCHEDULING,
        "勞工未住院的普通傷病假，一年內最多可以請幾天？",
        "未住院者，一年內合計不得超過三十日。",
        "勞工請假規則_全文_中華民國政府發布/original.md 第4條",
    ),
    (
        17, KG_SCHEDULING,
        "雇主資遣勞工，資遣費如何計算？",
        "在同一雇主之事業單位繼續工作，每滿一年發給相當於一個月平均工資之資遣費；剩餘月數或工作未滿一年者比例計給，未滿一個月者以一個月計；應於終止勞動契約三十日內發給。",
        "勞動基準法_全文_中華民國政府發布/original.md 第17條",
    ),
    (
        18, KG_SCHEDULING,
        "特別休假若年度終結未休完，雇主可以拒絕折算成工資嗎？",
        "不可以拒絕。勞工之特別休假因年度終結或契約終止而未休之日數，雇主應發給工資；經勞雇雙方協商遞延至次一年度者，次一年度終結或契約終止仍未休之日數，雇主仍應發給工資。",
        "勞動基準法_全文_中華民國政府發布/original.md 第38條",
    ),
    (
        19, KG_SCHEDULING,
        "勞動基準法第84-1條核定公告的責任制工作者類別包含哪些？",
        "監督管理人員與專業人員（系統研發工程師、專案經理）、監視性與間歇性工作（大樓管理員、保全人員）、航空業機組員、住院醫師等。",
        "勞動基準法第八十四條之一核定公告工作者類別_中華民國政府發布/original.md",
    ),
    (
        20, KG_SCHEDULING,
        "春節假期調移補班日，雇主需要給付加班費嗎？",
        "不需要。調移後之補班日為正常工作日，免給付加班費。",
        "內政部_台內勞字第351220號函/original.md",
    ),
    (
        21, KG_SCHEDULING,
        "工作規則沒有公開揭示，對勞工有沒有法律效力？",
        "沒有。僱用三十人以上應擬訂工作規則並報備，核備後應公開揭示，未揭示者對勞工不生效力。",
        "內政部_台內勞字第351229號函/original.md",
    ),
    (
        22, KG_LEAVE_PAY,
        "就業服務法規定，雇主招募員工不得以哪些理由歧視求職者？",
        "不得以種族、階級、語言、思想、宗教、黨派、籍貫、出生地、性別、性傾向、年齡、婚姻、容貌、五官、身心障礙、星座、血型或以往工會會員身分為由予以歧視。",
        "就業服務法_全文_中華民國政府發布/original.md 第5條",
    ),
    (
        23, KG_LEAVE_PAY,
        "請領失業給付需要符合哪些條件？",
        "被保險人於非自願離職辦理退保當日前三年內，保險年資合計滿一年以上，具有工作能力及繼續工作意願，向公立就業服務機構辦理求職登記，自求職登記之日起十四日內仍無法推介就業或安排職業訓練。",
        "就業保險法_全文_中華民國政府發布/original.md 第11條",
    ),
    (
        24, KG_LEAVE_PAY,
        "伙食代金（伙食津貼）需要納入平均工資的計算嗎？",
        "需要。伙食津貼屬經常性給與，為工資一部分，計算平均工資時應併入。",
        "勞動部_勞動條2字第1070131100號函/original.md",
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
