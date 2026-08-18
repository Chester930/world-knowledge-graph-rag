"""§3.1.4 修復效果驗證：對新建立的示範強化 KG（見 setup_314_demo_kg.py）
重跑 6 題先前在舊 KG（source_doc_id 全為 null）上答錯或部分答錯的真實
問題，比對這次是否因為 HAS_ENTITY／Fact 節點真正建立而改善。

每題記錄：新 KG 上的真實回答、BFS 三元組筆數、語意 Fact 筆數
（這次應該 > 0，是本次驗證最關鍵的訊號）、與先前結果的對照。

用法：python verify_314_fix.py <new_kg_id> > verify_314_fix_raw.txt 2>&1
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from uuid import UUID

from core.database import connect, disconnect, get_driver
from core.providers.factory import init_providers
from models.document import ChatRequest
from routers.agent import chat

# (題號, 問題, 舊KG上的錯誤/部分錯誤結果摘要, 已核對的正確答案, 對應文件)
CASES = [
    (
        5, "生理假一年最多可以請幾天，會不會併入病假計算？",
        "❌ 嚴重幻覺：答「一年16天（4天/次×4次）」，正確為一年3天",
        "生理假每月一日，全年不逾三日不併入病假；生理假期間工資折半，不得扣發全勤。",
        "勞動部_勞動條3字第1060130250號函",
    ),
    (
        11, "勞工出差往返的交通時間算工作時間嗎？",
        "🟡 部分正確：方向大致對，但漏掉「正常工時內出差工資照給」「工時外雇主指派駕駛才計入」的細節",
        "若非在雇主監督下，得不計入工作時間；若出差交通時間適逢正常工作時間，工資應照給；若係正常工作時間外由雇主指派駕駛交通工具載運員工或器材，該交通時間應計入工作時間。",
        "內政部_台內勞字第356410號函",
    ),
    (
        14, "雇主可以不經勞工同意就把工資改成用實物或禮券折抵嗎？",
        "🟡 結論正確（不可以），但引用的法條（勞基法第22條）與本題實際依據不符",
        "工資調整應經勞工同意，非經勞工同意雇主不得改以實物或公司禮券折抵。",
        "內政部_台內勞字第342080號",
    ),
    (
        20, "春節假期調移補班日，雇主需要給付加班費嗎？",
        "❌ 事實其實在雜訊裡但答錯：結論說「仍需給付加班費」",
        "調移後之補班日為正常工作日，免給付加班費。",
        "內政部_台內勞字第351220號函",
    ),
    (
        21, "工作規則沒有公開揭示，對勞工有沒有法律效力？",
        "❌ 事實其實在雜訊裡但答錯：結論說「可能仍有約束力」",
        "僱用三十人以上應擬訂工作規則並報備，核備後應公開揭示，未揭示者對勞工不生效力。",
        "內政部_台內勞字第351229號函",
    ),
    (
        24, "伙食代金（伙食津貼）需要納入平均工資的計算嗎？",
        "❌ 正確事實排在檢索結果第一筆卻被忽略：答「無法得出結論」",
        "伙食津貼屬經常性給與，為工資一部分，計算平均工資時應併入。",
        "勞動部_勞動條2字第1070131100號函",
    ),
]


async def _ask(kg_id: UUID, question: str) -> dict:
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
        "answer": "".join(answer_parts), "sources": sources,
        "error": error, "elapsed_seconds": round(elapsed, 1),
    }


async def main(kg_id_str: str) -> None:
    kg_id = UUID(kg_id_str)
    await connect()
    init_providers()
    try:
        for idx, question, old_result, ground_truth, doc in CASES:
            print(f"\n{'=' * 70}")
            print(f"# 題 {idx}（新KG重測）｜文件：{doc}")
            print(f"【問題】{question}")
            print(f"【舊KG結果】{old_result}")
            print(f"【已核對正確答案】{ground_truth}")
            result = await _ask(kg_id, question)
            print(f"【耗時】{result['elapsed_seconds']} 秒")
            if result["error"]:
                print(f"【錯誤】{result['error']}")
                continue
            print(f"【新KG系統回答】\n{result['answer']}")
            sources = result["sources"] or {}
            triples = sources.get("triples", [])
            facts = sources.get("facts", [])
            print(f"【解析出的關係型別】{sources.get('resolved_rel_type') or '（未解析出／QNOMATCH）'}")
            print(f"【BFS 三元組筆數】{len(triples)}")
            print(f"【語意 Fact 筆數】{len(facts)}")
            for t in triples[:10]:
                print(
                    f"  - {t['subject']}（{t['subject_type']}）-[{t['rel_type']}]{t['verb']}→"
                    f"{t['object']}（{t['object_type']}）  來源：{t.get('source_svo_chunk_file') or '（無）'}"
                )
            for f in facts:
                print(f"  - [Fact] {f['fact_text']}  (score={f.get('score')})")
            print(f"{'=' * 70}\n")
    finally:
        await disconnect()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法：python verify_314_fix.py <new_kg_id>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
