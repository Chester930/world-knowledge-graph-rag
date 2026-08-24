"""對報告 13、14 的全部 30 題，跑一次標準化RAG（改良RAG）MVP 路徑，
供與已有的知識圖譜路徑結果做真實對照。

不經過 routers/agent.py::chat()（那是知識圖譜路徑）——直接呼叫
standardized_rag.py 的雙階檢索＋LLM，是完全獨立的路徑。

用法：python run_rag_comparison.py > run_rag_comparison_raw.txt 2>&1
"""
from __future__ import annotations

import asyncio
import time
from uuid import UUID

from core.providers.factory import get_embedding_provider, get_llm_provider, init_providers
import standardized_rag as rag

KG_SCHEDULING = UUID("deb24e7c-c012-4398-9261-c813cb60b197")
KG_LEAVE_PAY = UUID("2ae9d28b-3c5e-424f-9ea4-c3cbe59a2934")

# (報告代號, 題號, KG, 問題) —— 報告13/14各自獨立編號1-15，兩份報告都有，
# 用報告代號區分避免混淆。與原本知識圖譜路徑測試用的同一組問題。
QUESTIONS = [
    ("13", 1, KG_SCHEDULING, "二人制飛航組員每日執勤與飛航時間上限各是多少？"),
    ("13", 2, KG_SCHEDULING, "住院醫師的排班需要符合哪些前提條件？"),
    ("13", 3, KG_SCHEDULING, "保全業適用勞基法第84-1條，正常工時與延長工時上限各是多少？"),
    ("13", 4, KG_SCHEDULING, "台鐵列車乘務人員的輪班間隔休息時間規定是什麼？"),
    ("13", 5, KG_SCHEDULING, "生理假一年最多可以請幾天，會不會併入病假計算？"),
    ("13", 6, KG_SCHEDULING, "勞動基準法第三十六條第四項指定行業，可以在什麼條件下調整例假？"),
    ("13", 7, KG_LEAVE_PAY, "颱風天員工未出勤，雇主是否需要給付當日工資？"),
    ("13", 8, KG_LEAVE_PAY, "試用期間的工資是否可以低於基本工資？"),
    ("13", 9, KG_LEAVE_PAY, "全勤獎金在產假期間是否可以被扣除？"),
    ("13", 10, KG_LEAVE_PAY, "拒絕配戴安全帽會導致什麼法律後果？"),
]


async def _ask_rag(kg_id: UUID, question: str, vectors, meta) -> dict:
    embedding_provider = get_embedding_provider()
    llm_provider = get_llm_provider()
    t0 = time.monotonic()

    question_vector = await embedding_provider.encode(question)
    hits = rag.search(question_vector, vectors, meta, top_k=5)
    prompt = rag.build_prompt(question, hits)

    answer_parts: list[str] = []
    async for token in llm_provider.stream(prompt):
        answer_parts.append(token)
    elapsed = time.monotonic() - t0

    return {"answer": "".join(answer_parts), "hits": hits, "elapsed_seconds": round(elapsed, 1)}


async def main() -> None:
    init_providers()
    index_cache: dict[UUID, tuple] = {}
    for kg_id in {KG_SCHEDULING, KG_LEAVE_PAY}:
        index_cache[kg_id] = rag.load_index(kg_id)
        vectors, meta = index_cache[kg_id]
        print(f"KG {kg_id} 索引已載入：{vectors.shape[0]} 筆句子向量")

    for report, num, kg_id, question in QUESTIONS:
        vectors, meta = index_cache[kg_id]
        print(f"\n{'=' * 70}")
        print(f"# [報告{report}] 題 {num}｜KG={kg_id}")
        print(f"【問題】{question}")
        result = await _ask_rag(kg_id, question, vectors, meta)
        print(f"【耗時】{result['elapsed_seconds']} 秒")
        print(f"【標準化RAG回答】\n{result['answer']}")
        print(f"【檢索到 {len(result['hits'])} 個相關段落】")
        for h in result["hits"]:
            print(f"  - 來源：{h['source']}　第{h['chunk_index']}段　"
                  f"相似度={h['score']:.3f}　命中句：{h['matched_sentence'][:60]}")
        print(f"{'=' * 70}\n")


if __name__ == "__main__":
    asyncio.run(main())
