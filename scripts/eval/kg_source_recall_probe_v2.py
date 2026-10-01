"""KG 來源回取「召回優先」再探測（報告160 U3）：納入 BFS 三元組（以邊上 ``citations_json`` 解析來源 chunk）。

**唯讀 Neo4j、不呼叫任何 LLM**（``resolve_query_relation_type`` 以 ``llm_provider=None`` 執行；灰色地帶回 None＝不篩選，
與 ``chat()`` 帶 LLM 時可能不同，已在結果中記錄）。只做檢索、不做生成。**不得以 gold 選段**。

檢索步驟鏡像 ``routers/agent.py::chat`` 的 ``if payload.use_svo:`` 區塊（種子實體→範圍→Fact 向量檢索→文件範圍→BFS→
關係型別後篩→範圍兜底），參數同凍結基準的 K 臂（``top_k`` 預設 20、``svo_hops`` 1、``retrieval_mode=both``、
``scope_doc_ids``＝凍結 manifest 的 23 份文件）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from uuid import UUID

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

ENV_FILE = REPO / ".claude" / "worktrees" / "kg-reextract" / ".env"
MAIN_ENV = Path("D:/Users/666/Desktop/world knowledge graph rag/.claude/worktrees/kg-reextract/.env")


def load_env() -> None:
    for p in (ENV_FILE, MAIN_ENV):
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
            return


class _LazyV1:
    """延遲載入 `kg_source_recall_probe`（v1）。

    匯入本模組不得有行程級副作用（舊版在模組層級呼叫 `load_env()`，匯入即把
    kg-reextract 的 `.env` 寫進 `os.environ`，汙染同一行程內的其他測試）。v1 會匯入
    `services.*`／`core.config`，依賴環境變數，所以環境載入必須先於 v1 的匯入——
    改為首次存取 `v1.<屬性>` 時才「載入環境 → 匯入 v1」，命令列執行的先後順序不變。
    """

    _mod = None

    def __getattr__(self, name: str):
        if _LazyV1._mod is None:
            load_env()
            from scripts.eval import kg_source_recall_probe as mod  # noqa: PLC0415

            _LazyV1._mod = mod
        return getattr(_LazyV1._mod, name)


v1 = _LazyV1()

OUT = REPO / "data" / "eval" / "candidate_runs" / "kg_source_recall_probe_v2"
KG_ID = "236903cf-055a-40a8-8923-b9d06601f3b7"


async def retrieve_all(questions: dict[str, str], scope_ids: list[str], cache: Path) -> dict:
    from core.database import connect, disconnect, get_driver
    from core.kg_config import ConfigLoader, FileConfigSource
    from core.config import settings
    from core.providers.factory import get_embedding_provider, init_providers
    from repositories.kg_repo import KGRepository
    from routers import agent
    from services import svo_service

    await connect()
    init_providers()
    driver = get_driver()
    emb = get_embedding_provider()
    kg_id = UUID(KG_ID)
    kg_meta = await KGRepository(driver).get(kg_id)
    cfg = ConfigLoader([FileConfigSource(settings.kg_config_dir)]).load(
        kg_id, domain_pack=getattr(kg_meta, "domain_pack", None))
    from services.document_record_service import document_uuid

    scope = [document_uuid(s) for s in scope_ids]  # manifest 的 scope_doc_ids 是文件資料夾名稱，與 run_rq1_comparison._resolve_scope 同法轉 UUID5
    results = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    try:
        for qid, question in questions.items():
            if qid in results:
                continue
            qvec = await emb.encode(question)
            seeds = await agent._find_seed_entities(driver, kg_id, question, embedding_provider=emb,
                                                    question_vector=qvec, cfg=cfg)
            seed_doc_ids = await agent._relevant_doc_ids_from_seeds(driver, kg_id, seeds)
            fscope = agent._resolve_doc_scope(seed_doc_ids, set(), scope)
            kw = {"allowed_source_doc_ids": fscope} if fscope else {}
            facts = await svo_service.vector_search_facts(driver, kg_id, qvec, top_k=20, **kw)
            sem_docs = agent._relevant_doc_ids_from_facts(facts, top_n=cfg.bfs.doc_scope_top_n_facts)
            rel_docs = agent._resolve_doc_scope(seed_doc_ids, sem_docs, scope)
            triples = await svo_service.bfs_query(
                driver, kg_id, seeds, hops=1, scope_doc_ids=(rel_docs or None),
                per_seed_limit=cfg.bfs.per_seed_limit, cfg=cfg)
            rel_type = await svo_service.resolve_query_relation_type(question, emb, llm_provider=None, cfg=cfg)
            triples = agent._filter_triples_by_relation_type(triples, rel_type)
            triples = agent._filter_triples_by_source_doc_ids(triples, rel_docs)
            facts = agent._filter_facts_by_source_doc_ids(facts, rel_docs)
            if cfg.factlist.article_expand:
                facts = await agent._expand_facts_by_article(driver, kg_id, facts,
                                                             sibling_limit=cfg.factlist.article_expand_sibling_limit)
            # 邊上 citations_json（唯讀）
            rows = [{"s": t.subject, "o": t.object, "rt": t.rel_type} for t in triples]
            cites: dict[str, list] = {}
            if rows:
                res = await driver.execute_query(
                    "UNWIND $rows AS row "
                    "MATCH (s:Entity {kg_id: $k, name: row.s})-[r]->(o:Entity {kg_id: $k, name: row.o}) "
                    "WHERE type(r) = row.rt AND r.kg_id = $k "
                    "RETURN row.s AS s, row.rt AS rt, row.o AS o, r.citations_json AS c",
                    rows=rows, k=str(kg_id))
                for rec in res.records:
                    cites[f"{rec['s']}\t{rec['rt']}\t{rec['o']}"] = json.loads(rec["c"] or "[]")
            results[qid] = {
                "seeds": seeds, "rel_type": rel_type,
                "facts": [{"text": f.get("fact_text"), "score": f.get("score"), "source_doc_id": str(f.get("source_doc_id")),
                           "source_svo_chunk_index": f.get("source_svo_chunk_index"), "article_no": f.get("article_no")}
                          for f in facts],
                "triples": [{"text": t.natural_text or "", "subject": t.subject, "rel_type": t.rel_type, "object": t.object,
                             "source_doc_id": str(t.source_doc_id) if t.source_doc_id else None,
                             "source_svo_chunk_index": t.source_svo_chunk_index,
                             "citations": cites.get(f"{t.subject}\t{t.rel_type}\t{t.object}", [])}
                            for t in triples],
            }
            cache.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
            print(qid, "facts", len(facts), "triples", len(triples), "seeds", len(seeds), flush=True)
    finally:
        await disconnect()
    return results


def triple_candidates(tr: dict, mode: str) -> list[dict]:
    """把一條 BFS 三元組的 citations 轉成可解析候選。mode: last（最後一筆）／all（全部，去重）。"""
    cits = tr["citations"]
    if not cits:
        return []
    picked = cits[-1:] if mode == "last" else cits
    out, seen = [], set()
    for c in picked:
        key = (c.get("source_doc_id"), c.get("source_svo_chunk_index"), c.get("article_no"))
        if key in seen:
            continue
        seen.add(key)
        out.append({"kind": "triple", "rank": None, "source_doc_id": c.get("source_doc_id"),
                    "source_svo_chunk_index": c.get("source_svo_chunk_index"), "article_no": c.get("article_no"),
                    "in_prompt": None})
    return out


def analyse(rerun: dict, kg_folder: Path) -> dict:
    bank = v1.load_bank()
    krecs = v1.load_records(v1.K_DIRS)
    brecs = v1.load_records([v1.B1_DIR])
    b1_index = v1.load_b1_index()
    resolver = v1.SourceResolver(kg_folder)
    rows = []
    for qid in sorted(rerun):
        q = bank[qid]
        gold, atomic = q["gold"], q["atomic"]
        rr = rerun[qid]
        frozen = krecs[qid]["lineage"]["stage1_retrieval"]["retrieval_trace"]
        fset = {e["text"] for e in frozen if e["kind"] == "fact"}
        tset = {e["text"] for e in frozen if e["kind"] == "triple"}
        nf = {f["text"] for f in rr["facts"]}
        nt = {t["text"] for t in rr["triples"]}
        jac = lambda a, b: round(len(a & b) / len(a | b), 4) if (a | b) else None  # noqa: E731
        fact_cands = [{"kind": "fact", "rank": i, **{k: f[k] for k in ("source_doc_id", "source_svo_chunk_index", "article_no")},
                       "in_prompt": None} for i, f in enumerate(rr["facts"])]
        faces = {}
        for tri_mode in ("last", "all"):
            tri_cands = [c for t in rr["triples"] for c in triple_candidates(t, tri_mode)]
            para_f, _ = v1.dedup_sources(fact_cands, resolver)
            para_t, un_t = v1.dedup_sources(tri_cands, resolver)
            para_ft, un_ft = v1.dedup_sources(fact_cands + tri_cands, resolver)
            faces[f"tri_{tri_mode}_unresolved"] = dict(Counter(u["reason"] for u in un_t))
            for m in v1.M_VALUES:
                faces[f"R1p_{tri_mode}_m{m}"] = v1.measure([p["text"] for p in para_ft[:m]], gold, atomic)
            faces[f"paras_{tri_mode}"] = {"facts": len(para_f), "triples": len(para_t), "both": len(para_ft)}
            faces[f"R1p_{tri_mode}_unbounded"] = v1.measure([p["text"] for p in para_ft], gold, atomic)
            faces["R1_facts_unbounded"] = v1.measure([p["text"] for p in para_f], gold, atomic)
            if qid in brecs:
                budget = brecs[qid]["lineage"]["stage1_retrieval"]["retrieved_char_count"]
                faces[f"R1p_{tri_mode}_budget"] = v1.measure(
                    [p["text"] for p in v1.take_by_budget(para_ft, budget)], gold, atomic)
                faces["R1_rerun_budget"] = v1.measure([p["text"] for p in v1.take_by_budget(para_f, budget)], gold, atomic)
                faces["R1_tri_only_budget_" + tri_mode] = v1.measure(
                    [p["text"] for p in v1.take_by_budget(para_t, budget)], gold, atomic)
        for m in v1.M_VALUES:
            faces[f"R1_rerun_m{m}"] = v1.measure([p["text"] for p in para_f[:m]], gold, atomic)
        rows.append({"question_id": qid, "scenario_type": q["scenario_type"], "faces": faces,
                     "overlap": {"fact_jaccard": jac(fset, nf), "triple_jaccard": jac(tset, nt),
                                 "n_facts_frozen": len(fset), "n_facts_rerun": len(nf),
                                 "n_triples_frozen": len(tset), "n_triples_rerun": len(nt)},
                     "seeds": rr["seeds"], "rel_type": rr["rel_type"]})
    return {"rows": rows}


def main() -> int:
    load_env()  # 命令列入口：先載入環境（setdefault，與 v1 延遲載入時的呼叫冪等）
    ap = argparse.ArgumentParser()
    ap.add_argument("--kg-folder", type=Path, default=v1.DEFAULT_KG)
    ap.add_argument("--analyse-only", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    cache = OUT / "retrieval_rerun.json"
    man = json.loads((v1.BASE / "frozen_manifest.json").read_text(encoding="utf-8"))
    bank = json.loads(v1.BANK.read_text(encoding="utf-8"))["questions"]
    questions = {q["id"]: q["question"] for q in bank if q["id"] in man["eligible_ids"]}
    if not a.analyse_only:
        asyncio.run(retrieve_all(questions, man["scope_doc_ids"], cache))
    rerun = json.loads(cache.read_text(encoding="utf-8"))
    res = analyse(rerun, a.kg_folder)
    (OUT / "per_question.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", len(res["rows"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
