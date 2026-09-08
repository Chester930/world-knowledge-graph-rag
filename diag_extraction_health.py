# -*- coding: utf-8 -*-
"""報告32 §9 — Test A：抽取端品質體檢（0 等待，唯讀）。

不需要等窗口/全量。拿 KG 236903cf 目前已抽的 chunk（drain 邊跑邊查），
對照凍結基準 76bc98ff，檢查抽取端有沒有系統性問題：

  1. 規模與覆蓋   Document/Chunk/Fact/Entity 計數；已完成 chunk 的 Fact 產出率；0-fact chunk
  2. rel_type 分佈  是否幾乎全 RELATED_TO 兜底
  3. blob entity   Entity.name 是整句子句 / 帶「為限」「以上」「個月」且過長（E3 目標）
  4. 數字黏名詞    name 尾端「數值+單位」黏在一起（F2/F3 目標，如「婚假八日」）
  5. alias 分級誤併 同一 Entity 的 aliases 去掉數字/序數後同形（E1 目標）
  6. 每份文件覆蓋  64 份各自 completed chunk vs 有 Fact 的 chunk

用法：
    cd "D:/Users/666/Desktop/world knowledge graph rag/.claude/worktrees/kg-reextract"
    python diag_extraction_health.py
    python diag_extraction_health.py --out <path>
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime

WT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, WT)
os.chdir(WT)

from core.database import connect, disconnect, get_driver  # noqa: E402

KG4 = "236903cf-055a-40a8-8923-b9d06601f3b7"   # reextract-v2 新 KG
BASE = "76bc98ff-2cbd-447e-a087-7f2df6898655"  # 凍結基準
TQ_DB = r"D:\Users\666\Desktop\kg-runtime\task_queue.db"

OUT_DEFAULT = os.path.join(WT, "diag_extraction_health_output.txt")
_out = OUT_DEFAULT

# blob entity 判準：帶條文語氣詞且過長，或含句讀
_BLOB_HINT = re.compile(r"(為限|以上|以下|不得|個月|個年|個星期|應實施|所定|規定|之期間|包括)")
_PUNCT = re.compile(r"[。；：、，（）「」]")
# 數字黏名詞：name 尾端是「數值+單位」
_NUM = "[0-90-9一二三四五六七八九十兩參零百千]+"
_UNIT = "(日|月|年|小時|分鐘|分|秒|公尺|公分|公里|公斤|公升|毫克|微克|克|元|歲|人|次|款|條|項|目|級|倍|週|天|度|%|％|ppm)"
_NUM_GLUED = re.compile(rf".{{2,10}}{_NUM}{_UNIT}$")
_STRIP_NUM = re.compile(r"[0-90-9一二三四五六七八九十兩參零百千第之]+")


def w(msg: str = "") -> None:
    with open(_out, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print(msg, flush=True)


async def _scalar(driver, q, **kw):
    async with driver.session() as s:
        r = await s.run(q, **kw)
        rec = await r.single()
        return rec[0] if rec else None


async def _rows(driver, q, **kw):
    async with driver.session() as s:
        r = await s.run(q, **kw)
        return [rec.data() async for rec in r]


async def counts(driver, kg: str) -> dict:
    d = {}
    for lbl in ("Document", "Chunk", "LawArticle", "Fact", "Entity"):
        d[lbl] = await _scalar(driver, f"MATCH (x:{lbl} {{kg_id:$k}}) RETURN count(x)", k=kg)
    d["chunks_with_fact"] = await _scalar(
        driver,
        "MATCH (f:Fact {kg_id:$k}) RETURN count(DISTINCT [f.source_doc_id, f.source_svo_chunk_index])",
        k=kg,
    )
    return d


async def rel_dist(driver, kg: str) -> Counter:
    rows = await _rows(driver, "MATCH (f:Fact {kg_id:$k}) RETURN f.rel_type AS rt, count(*) AS n", k=kg)
    return Counter({r["rt"]: r["n"] for r in rows})


async def entity_names(driver, kg: str) -> list[str]:
    rows = await _rows(driver, "MATCH (e:Entity {kg_id:$k}) RETURN e.name AS n", k=kg)
    return [r["n"] for r in rows if r["n"]]


async def multi_alias(driver, kg: str) -> list[dict]:
    return await _rows(
        driver,
        "MATCH (e:Entity {kg_id:$k}) WHERE size(e.aliases) > 1 RETURN e.name AS name, e.aliases AS aliases",
        k=kg,
    )


def analyse_names(names: list[str]) -> dict:
    lens = sorted(len(n) for n in names)
    n = len(lens)
    p = lambda q: lens[min(n - 1, int(q * n))] if n else 0
    blob = [x for x in names if len(x) > 40 or (_PUNCT.search(x) and len(x) > 12) or (_BLOB_HINT.search(x) and len(x) >= 14)]
    glued = [x for x in names if _NUM_GLUED.match(x) and not x.isdigit()]
    return {
        "n": n, "p50": p(.5), "p90": p(.9), "p99": p(.99), "max": lens[-1] if lens else 0,
        "blob": blob, "glued": glued,
    }


def alias_merge(rows: list[dict]) -> list[dict]:
    hits = []
    for r in rows:
        al = [a for a in (r.get("aliases") or []) if a]
        norm = {}
        for a in al:
            key = _STRIP_NUM.sub("", a)
            norm.setdefault(key, []).append(a)
        collide = {k: v for k, v in norm.items() if len(set(v)) > 1 and k}
        if collide:
            hits.append({"name": r["name"], "collide": collide})
    return hits


def tq_status() -> dict:
    c = sqlite3.connect(TQ_DB)
    return dict(c.execute("SELECT status,COUNT(*) FROM task_queue WHERE kg_id=? GROUP BY status", (KG4,)).fetchall())


async def per_doc_coverage(driver) -> list[dict]:
    c = sqlite3.connect(TQ_DB)
    done = c.execute(
        "SELECT source, COUNT(*) FROM task_queue WHERE kg_id=? AND status='completed' GROUP BY source", (KG4,)
    ).fetchall()
    from services.document_record_service import document_uuid
    out = []
    for source, ndone in done:
        did = str(document_uuid(source))
        nf = await _scalar(
            driver,
            "MATCH (f:Fact {kg_id:$k, source_doc_id:$d}) RETURN count(DISTINCT f.source_svo_chunk_index)",
            k=KG4, d=did,
        )
        nfact = await _scalar(driver, "MATCH (f:Fact {kg_id:$k, source_doc_id:$d}) RETURN count(f)", k=KG4, d=did)
        out.append({"source": source, "done": ndone, "chunks_with_fact": nf or 0, "facts": nfact or 0})
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT_DEFAULT)
    args = ap.parse_args()
    global _out
    _out = args.out

    w(f"\n\n########## 抽取端品質體檢 (Test A)  {datetime.now().isoformat(timespec='seconds')} ##########")
    tq = tq_status()
    w(f"task_queue（KG4）：{tq}")

    await connect()
    driver = get_driver()

    w("\n" + "=" * 90)
    w("1) 規模與覆蓋 —— KG4 (236903cf) vs 凍結基準 (76bc98ff, 100% 完成)")
    w("=" * 90)
    c4 = await counts(driver, KG4)
    cb = await counts(driver, BASE)
    done_ch = tq.get("completed", 0)
    w(f"{'':22s}{'KG4 (進行中)':>18s}{'BASE (100%)':>16s}")
    for k in ("Document", "Chunk", "LawArticle", "Fact", "Entity", "chunks_with_fact"):
        w(f"  {k:20s}{c4[k]:>18d}{cb[k]:>16d}")
    w(f"\n  已完成 chunk（task_queue）：{done_ch}")
    if done_ch:
        w(f"  Fact / 已完成 chunk        ：{c4['Fact']/done_ch:.2f}   （BASE: {cb['Fact']/max(cb['Chunk'],1):.2f} /chunk）")
        w(f"  有 Fact 的 chunk / 已完成   ：{c4['chunks_with_fact']}/{done_ch} = {c4['chunks_with_fact']/done_ch:.1%}")
        w(f"  → 0-fact chunk（已抽卻無任何 Fact）：約 {done_ch - c4['chunks_with_fact']} 個")

    w("\n" + "=" * 90)
    w("2) rel_type 分佈")
    w("=" * 90)
    r4, rb = await rel_dist(driver, KG4), await rel_dist(driver, BASE)
    t4, tb = sum(r4.values()) or 1, sum(rb.values()) or 1
    w(f"{'rel_type':28s}{'KG4':>12s}{'KG4%':>8s}{'BASE%':>8s}")
    for rt, n in r4.most_common(12):
        w(f"  {str(rt):26s}{n:>12d}{n/t4:>7.1%}{rb.get(rt,0)/tb:>8.1%}")

    w("\n" + "=" * 90)
    w("3) blob entity ＋ 4) 數字黏名詞  （name 長度分佈）")
    w("=" * 90)
    n4 = analyse_names(await entity_names(driver, KG4))
    nb = analyse_names(await entity_names(driver, BASE))
    w(f"  name 長度   KG4: n={n4['n']} p50={n4['p50']} p90={n4['p90']} p99={n4['p99']} max={n4['max']}")
    w(f"             BASE: n={nb['n']} p50={nb['p50']} p90={nb['p90']} p99={nb['p99']} max={nb['max']}")
    w(f"\n  blob entity：KG4 {len(n4['blob'])} 個  /  BASE {len(nb['blob'])} 個")
    for x in sorted(n4["blob"], key=len, reverse=True)[:25]:
        w(f"     [{len(x):3d}] {x}")
    w(f"\n  數字黏名詞：KG4 {len(n4['glued'])} 個  /  BASE {len(nb['glued'])} 個")
    for x in sorted(set(n4["glued"]))[:30]:
        w(f"     · {x}")

    w("\n" + "=" * 90)
    w("5) alias 分級誤併（aliases 去數字/序數後同形）")
    w("=" * 90)
    m4 = alias_merge(await multi_alias(driver, KG4))
    mb = alias_merge(await multi_alias(driver, BASE))
    w(f"  KG4 命中 {len(m4)} 個 Entity  /  BASE {len(mb)} 個")
    for h in m4[:30]:
        w(f"     ◆ {h['name']}")
        for k, v in h["collide"].items():
            w(f"         {sorted(set(v))}")

    w("\n" + "=" * 90)
    w("6) 每份文件覆蓋（已完成 chunk / 有 Fact 的 chunk / Fact 數）——只列已開抽的")
    w("=" * 90)
    cov = await per_doc_coverage(driver)
    cov.sort(key=lambda d: d["source"])
    zero = [d for d in cov if d["done"] and d["chunks_with_fact"] < d["done"]]
    for d in cov:
        flag = "  ⚠️ 有 0-fact chunk" if d["chunks_with_fact"] < d["done"] else ""
        w(f"  {d['source'][:44]:44s} done={d['done']:>3} fact_chunks={d['chunks_with_fact']:>3} facts={d['facts']:>4}{flag}")
    w(f"\n  有 0-fact chunk 的文件：{len(zero)} / {len(cov)}")

    w(f"\n\nTEST-A-DONE {datetime.now().isoformat(timespec='seconds')}")
    await disconnect()


if __name__ == "__main__":
    asyncio.run(main())
