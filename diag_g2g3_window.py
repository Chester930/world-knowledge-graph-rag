# -*- coding: utf-8 -*-
"""報告32 §9 step 7：G2/G3「4 份文件窗口」診斷。

觸發前置 = `check_4docs_kg4.py` 回報 4 份全 pending=0（sweep 過 chunk_index 16）。

做兩件事，結果同時寫檔 + 印出：

  Part A｜直查 Neo4j（KG 236903cf）——這 4 份文件抽出來的圖長什麼樣：
    - 每份的全部 Fact（chunk_index / subject / rel_type / verb / object / fact_text）
    - 針對 4 題的關鍵語素做 targeted 撈取（分段清單、係數表、分級門檻…）
    - 關鍵 Entity 的 name + aliases + 出入邊 —— 抓 E1 型「子規則主詞被誤併成 alias、事實消失」

  Part B｜跑真正的 routers.agent.chat() ×3（use_svo=True，KG=236903cf）：
    Q3 未滿15歲三段工時（G3 分段清單接地）
    Q6 母性健康保護期間 / 血中鉛第三級 / 紀錄保存（G3 分段清單接地）
    Q8 5ppm 落在「1以上未滿10」→ 變量係數 2（G2 多跳區間推理）
    R26-Q5 災後六個月 / 當月一日起算（窗口對照，跨文件不混淆）
    逐題捕捉：answer、命中詞、BFS三元組數、語意Fact數、regenerated、
             未接地主張（event: grounding 的 statement + reason）、sources 清單

用法：
    cd "D:/Users/666/Desktop/world knowledge graph rag/.claude/worktrees/kg-reextract"
    python diag_g2g3_window.py                 # A + B ×3
    python diag_g2g3_window.py --neo4j-only    # 只 Part A
    python diag_g2g3_window.py --runs 1        # Part B 只跑 1 輪
    python diag_g2g3_window.py --out <path>    # 另指定輸出檔

跑完把 output 檔交回 "project status review" 用來設計 G2/G3 修正。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import traceback
from datetime import datetime
from uuid import UUID

WT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, WT)
os.chdir(WT)  # workspace/<kg>/... 與 .env 的相對解析

from core.database import connect, disconnect, get_driver  # noqa: E402
from core.providers.factory import init_providers  # noqa: E402
from models.document import ChatRequest  # noqa: E402
from routers.agent import chat  # noqa: E402
from services.document_record_service import document_uuid  # noqa: E402

KG_STR = "236903cf-055a-40a8-8923-b9d06601f3b7"
KG = UUID(KG_STR)

# 完整 source 字串（= task_queue.source = document_uuid 的輸入）
DOCS = {
    "N0060004": "N0060004_勞工作業場所容許暴露標準",
    "N0030025": "N0030025_勞動基準法第四十五條無礙身心健康認定基準及審查辦法",
    "N0060065": "N0060065_女性勞工母性健康保護實施辦法",
    "N0050030": "N0050030_災區受災勞工保險與勞工職業災害保險及就業保險被保險人保險費支應及傷病給付辦法",
}

# Part A targeted 撈取：每份文件關心的語素（Fact 的 subject/object/fact_text 命中即列）
DOC_PROBES = {
    "N0030025": ["二小時", "三小時", "四小時", "2小時", "3小時", "4小時", "三十分",
                 "30分", "未滿六歲", "六歲", "十二歲", "十五歲", "未滿六個月", "每次"],
    "N0060065": ["第一級", "第二級", "第三級", "血中鉛", "μg/dl", "µg/dl", "ug/dl",
                 "10", "十", "母性健康保護期間", "妊娠", "分娩", "得知", "保存", "三年", "3年"],
    "N0060004": ["變量係數", "係數", "短時間時量平均", "日時量平均", "1以上未滿10",
                 "未滿10", "未滿一", "尖峰", "2", "二", "ppm", "容許濃度"],
    "N0050030": ["六個月", "當月一日", "災害發生", "起算", "保險費", "中央政府", "支應"],
}

# 關鍵 Entity 名稱片段（撈 name + aliases + 邊 —— 找誤併）
ENTITY_PROBES = {
    "N0030025": ["未滿六歲", "六歲以上", "十二歲以上", "未滿十五歲", "未滿六個月", "童工", "工作時間"],
    "N0060065": ["第一級管理", "第二級管理", "第三級管理", "血中鉛", "鉛濃度", "母性健康保護期間"],
    "N0060004": ["變量係數", "短時間時量平均容許濃度", "八小時日時量平均容許濃度", "容許濃度"],
    "N0050030": ["保險費", "受災勞工", "災害發生當月一日", "中央政府"],
}

# Part B 題組：(標籤, 問題, watch 命中詞, 目標維度)
QUESTIONS = [
    ("Q3 / N0030025 / G3",
     "依勞動基準法第四十五條無礙身心健康認定基準，未滿十五歲的工作者每日工作時間上限，"
     "如何依年齡分三段規定？其中未滿六個月的工作者，每次工作時間有沒有另外的限制？",
     ["二小時", "三小時", "四小時", "三十分鐘", "2小時", "3小時", "4小時", "30分"]),
    ("Q6 / N0060065 / G3",
     "女性勞工的母性健康保護期間，是從什麼時候起算、到什麼時候為止？對於鉛作業，"
     "勞工血中鉛濃度達到多少以上屬於第三級管理？雇主依本辦法採行措施的相關文件及紀錄，至少要保存幾年？",
     ["分娩後一年", "得知", "妊娠", "第三級", "三年", "3年", "十", "10"]),
    ("Q8 / N0060004 / G2",
     "依勞工作業場所容許暴露標準，某有害物的八小時日時量平均容許濃度為 5 ppm，"
     "計算其短時間時量平均容許濃度時，應乘以的變量係數是多少？",
     ["係數為 2", "係數是 2", "變量係數為二", "變量係數為 2", "係數 2", "乘以 2", "為二", "是 2"]),
    ("R26-Q5 / N0050030 / 窗口對照",
     "災區受災勞工，符合規定者在災後多久的期間內，個人應負擔的保險費由中央政府支應？"
     "這個期間從哪一天開始起算？",
     ["六個月", "當月一日", "災害發生", "六個月期間"]),
]

OUT_DEFAULT = os.path.join(WT, "diag_g2g3_window_output.txt")
_out_path = OUT_DEFAULT


def w(msg: str = "") -> None:
    with open(_out_path, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print(msg, flush=True)


# ────────────────────────────── Part A ──────────────────────────────

async def _facts_for_doc(driver, doc_id: str) -> list[dict]:
    q = """
    MATCH (f:Fact {kg_id: $kg, source_doc_id: $doc})
    OPTIONAL MATCH (f)-[:HAS_SUBJECT]->(s:Entity)
    OPTIONAL MATCH (f)-[:HAS_OBJECT]->(o:Entity)
    RETURN f.source_svo_chunk_index AS ci, s.name AS subject, f.rel_type AS rel,
           f.verb AS verb, o.name AS object, f.fact_text AS fact_text
    ORDER BY ci, subject
    """
    async with driver.session() as ses:
        res = await ses.run(q, kg=KG_STR, doc=doc_id)
        return [r.data() async for r in res]


async def _entities_probe(driver, probes: list[str]) -> list[dict]:
    q = """
    MATCH (e:Entity {kg_id: $kg})
    WHERE any(p IN $probes WHERE e.name CONTAINS p)
    OPTIONAL MATCH (e)-[r]->(t:Entity {kg_id: $kg})
    WITH e, collect(DISTINCT {dir:'out', rel:type(r), verb:r.verb, other:t.name}) AS outs
    OPTIONAL MATCH (x:Entity {kg_id: $kg})-[r2]->(e)
    WITH e, outs, collect(DISTINCT {dir:'in', rel:type(r2), verb:r2.verb, other:x.name}) AS ins
    RETURN e.name AS name, e.aliases AS aliases, outs, ins
    ORDER BY name
    """
    async with driver.session() as ses:
        res = await ses.run(q, kg=KG_STR, probes=probes)
        return [r.data() async for r in res]


def _hit(row: dict, probes: list[str]) -> bool:
    blob = " ".join(str(row.get(k) or "") for k in ("subject", "verb", "object", "fact_text"))
    return any(p in blob for p in probes)


async def part_a(driver) -> None:
    w("\n" + "#" * 92)
    w("# PART A — 直查 Neo4j（KG 236903cf）4 份窗口文件的抽取結果")
    w("#" * 92)
    for pref, source in DOCS.items():
        doc_id = str(document_uuid(source))
        facts = await _facts_for_doc(driver, doc_id)
        w(f"\n{'='*92}\n【{pref}】{source}\n  source_doc_id={doc_id}  Fact 總數={len(facts)}\n{'='*92}")

        if not facts:
            w("  ⚠️ 這份還沒有任何 Fact（抽取可能尚未跑到 / 失敗）——先確認 check_4docs_kg4.py 已觸發。")
            continue

        probes = DOC_PROBES.get(pref, [])
        targeted = [f for f in facts if _hit(f, probes)]
        w(f"\n-- targeted 命中（{len(targeted)} / {len(facts)}）：語素 {probes}")
        for f in targeted:
            w(f"   c{f['ci']:>3}  「{f['subject']}」 -[{f['rel']}]/{f['verb']}-> 「{f['object']}」")
            if f.get("fact_text"):
                w(f"          fact_text: {f['fact_text']}")

        w(f"\n-- 全部 Fact（chunk_index 排序，共 {len(facts)}）：")
        for f in facts:
            w(f"   c{f['ci']:>3}  「{f['subject']}」 -[{f['rel']}]/{f['verb']}-> 「{f['object']}」")

        ents = await _entities_probe(driver, ENTITY_PROBES.get(pref, []))
        w(f"\n-- 關鍵 Entity（name + aliases + 邊）：探針 {ENTITY_PROBES.get(pref, [])}")
        for e in ents:
            al = e.get("aliases") or []
            w(f"   ◆ {e['name']}   aliases={al}")
            for edge in (e.get("outs") or []):
                if edge.get("rel"):
                    w(f"       → [{edge['rel']}]/{edge.get('verb')} {edge['other']}")
            for edge in (e.get("ins") or []):
                if edge.get("rel"):
                    w(f"       ← {edge['other']} [{edge['rel']}]/{edge.get('verb')}")


# ────────────────────────────── Part B ──────────────────────────────

async def _call(question: str) -> dict:
    t0 = time.monotonic()
    resp = await chat(ChatRequest(question=question, use_svo=True, kg_id=KG))
    answer, regenerated = "", None
    sources, grounding = None, None
    ev = None
    async for chunk in resp.body_iterator:
        text = chunk if isinstance(chunk, str) else chunk.decode("utf-8")
        for line in text.split("\n"):
            if line == "":
                ev = None
                continue
            if line.startswith("event:"):
                ev = line[7:].strip()
                continue
            if line.startswith("data:"):
                raw = line[5:].strip()
                if not raw:
                    continue
                d = json.loads(raw)
                if ev == "sources":
                    sources = d
                elif ev == "grounding":
                    grounding = d
                elif ev == "status" and isinstance(d, dict) and d.get("phase") == "done":
                    regenerated = d.get("regenerated")
                elif ev is None and isinstance(d, dict) and "token" in d:
                    answer = d["token"]
    ung = [g for g in (grounding or []) if g.get("is_claim", True) and not g.get("supported", True)]
    return {
        "answer": answer,
        "elapsed": round(time.monotonic() - t0, 1),
        "n_triples": len(sources["triples"]) if sources else 0,
        "n_facts": len(sources["facts"]) if sources else 0,
        "regenerated": regenerated,
        "ungrounded": ung,
        "sources": sources,
    }


async def part_b(runs: int) -> None:
    w("\n" + "#" * 92)
    w(f"# PART B — routers.agent.chat() ×{runs}（use_svo=True, KG=236903cf）")
    w("#" * 92)
    for run in range(1, runs + 1):
        w(f"\n\n{'#'*40}  RUN {run}/{runs}  {'#'*40}")
        for tag, q, watch in QUESTIONS:
            w(f"\n{'='*92}\n# [{tag}]  RUN {run}/{runs}\n{'='*92}\nQ: {q}")
            try:
                r = await _call(q)
                hits = [x for x in watch if x in r["answer"]]
                w(f"\n--- {r['elapsed']}s  BFS三元組={r['n_triples']} 語意Fact={r['n_facts']} "
                  f"regenerated={r['regenerated']}  未接地主張={len(r['ungrounded'])}  命中={hits}")
                for g in r["ungrounded"]:
                    w(f"    ✗ 未接地: {g.get('statement')}")
                    if g.get("reason"):
                        w(f"        理由: {g.get('reason')}")
                w("答案:")
                w(r["answer"])
                src = r.get("sources") or {}
                fl = src.get("facts") or []
                tl = src.get("triples") or []
                if fl:
                    w(f"\n  [送進 prompt 的語意 Fact {len(fl)}]")
                    for f in fl[:25]:
                        w(f"    · {f.get('fact_text') or (str(f.get('subject'))+' '+str(f.get('rel_type'))+' '+str(f.get('object')))}  (score={f.get('score')})")
                if tl:
                    w(f"\n  [BFS 三元組 {len(tl)}]")
                    for t in tl[:25]:
                        w(f"    · 「{t.get('subject')}」 -[{t.get('rel_type')}]/{t.get('verb')}-> 「{t.get('object')}」")
            except Exception as e:
                w(f"\n--- !! 例外：{e!r}\n{traceback.format_exc()}")


# ────────────────────────────── main ──────────────────────────────

async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--neo4j-only", action="store_true")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--out", default=OUT_DEFAULT)
    args = ap.parse_args()

    global _out_path
    _out_path = args.out

    w(f"\n\n########## DIAG G2/G3 WINDOW  {datetime.now().isoformat(timespec='seconds')} ##########")
    w(f"KG={KG_STR}  worktree={WT}  out={_out_path}")

    await connect()
    init_providers()
    driver = get_driver()

    await part_a(driver)
    if not args.neo4j_only:
        await part_b(args.runs)

    w(f"\n\nDIAG-DONE {datetime.now().isoformat(timespec='seconds')}")
    await disconnect()


if __name__ == "__main__":
    asyncio.run(main())
