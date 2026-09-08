# -*- coding: utf-8 -*-
"""報告32 §9 C — P4 探針選題：列 N0080013 在 KG #4 抽出的全部 fact，
確認「罰鍰金額」這類數字是否真的不在圖裡（P4 = MissingInfo/REFUSE 探針）。"""
from __future__ import annotations
import asyncio, sys, os
REPO = r"D:\Users\666\Desktop\world knowledge graph rag"
sys.path.insert(0, REPO)
os.chdir(r"D:\Users\666\Desktop\kg-runtime")
from core.database import connect, disconnect, get_driver  # noqa: E402

KG = "236903cf-055a-40a8-8923-b9d06601f3b7"


async def main() -> None:
    await connect()
    d = get_driver()
    async with d.session() as s:
        # 1) 找 N0080013 的 Document / source_doc_id
        res = await s.run(
            "MATCH (doc:Document {kg_id:$kg}) WHERE doc.source CONTAINS 'N0080013' "
            "RETURN doc.id AS id, doc.source AS source",
            kg=KG,
        )
        docs = [r.data() async for r in res]
        print("DOCS:", docs)
        if not docs:
            # fallback：直接用 Fact.source_doc_id 掃 source 字串
            res = await s.run(
                "MATCH (f:Fact {kg_id:$kg}) WHERE f.source CONTAINS 'N0080013' "
                "RETURN DISTINCT f.source_doc_id AS did, f.source AS src LIMIT 5", kg=KG)
            print("via Fact:", [r.data() async for r in res])
        doc_ids = [x["id"] for x in docs] or []

        # 2) 列該文件所有 fact
        for did in doc_ids:
            res = await s.run(
                "MATCH (f:Fact {kg_id:$kg, source_doc_id:$doc}) "
                "OPTIONAL MATCH (f)-[:HAS_SUBJECT]->(su:Entity) "
                "OPTIONAL MATCH (f)-[:HAS_OBJECT]->(o:Entity) "
                "RETURN f.source_svo_chunk_index AS ci, su.name AS s, f.verb AS v, "
                "o.name AS o, f.fact_text AS ft ORDER BY ci", kg=KG, doc=did)
            rows = [r.data() async for r in res]
            print(f"\n=== {did}  ({len(rows)} facts) ===")
            for r in rows:
                print(f"  [{r['ci']}] {r['s']} -[{r['v']}]-> {r['o']}   | {r['ft']}")

        # 3) 針對「罰/罰鍰/元/處/新臺幣」關鍵字掃全 KG 內 N0080013 來源
        res = await s.run(
            "MATCH (f:Fact {kg_id:$kg}) WHERE f.source CONTAINS 'N0080013' AND "
            "(f.fact_text CONTAINS '罰' OR f.fact_text CONTAINS '元' OR f.fact_text CONTAINS '處') "
            "RETURN f.fact_text AS ft", kg=KG)
        pen = [r.data()["ft"] async for r in res]
        print(f"\n=== N0080013 內含 罰/元/處 的 fact（{len(pen)}）===")
        for x in pen:
            print("  ", x)
    await disconnect()


asyncio.run(main())
