"""N9 G1／G2 搬移差分測試的案例產生與執行（報告168 W1）。**不是測試檔**。

``run_all(ns)`` 對 ``ns``（``services.svo_service``）執行 8 個純符號各 ≥1000 組（常數逐值），回傳可 JSON 序列化的結果。
搬移前以舊實作產生 golden（``python -m tests.services.n9_differential_harness --write-golden``），
搬移後 ``test_n9_differential.py`` 用新程式重跑逐案比對（輸出、順序、字串逐字、例外型別與訊息）。
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from uuid import UUID, uuid4

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tests.services.n4_differential_harness import call_sync, jsonable  # noqa: E402

GOLDEN = Path(__file__).parent / "fixtures" / "n9_differential_golden.json"
SEED = 20260930
N = 1100

IDS = [f"f{i}" for i in range(12)]
DOCS = [str(UUID(int=i + 1)) for i in range(5)]
ENT = ["勞工", "雇主", "婚假", "特別休假", "", None]
REL = ["HAS_PROPERTY", "REQUIRES", "PART_OF", "", None]


def _det_uuid(rng: random.Random) -> UUID:
    return UUID(int=rng.randint(1, 5))


def run_all(ns) -> list[dict]:
    rng = random.Random(SEED)
    out: list[dict] = []

    def add(kind, args, res):
        out.append({"kind": kind, "args": jsonable(args), "res": res})

    add("const:_BFS_EXPAND_WHEN_BELOW", [], {"ok": jsonable(ns._BFS_EXPAND_WHEN_BELOW)})
    add("const:_BFS_PRIZE_TOP_K", [], {"ok": jsonable(ns._BFS_PRIZE_TOP_K)})

    for _ in range(N):
        rankings = [rng.sample(IDS, rng.randint(0, 8)) for _ in range(rng.randint(0, 4))]
        if rng.random() < 0.2 and rankings:
            rankings[0] = rankings[0] + rankings[0][:2]  # 重複 id
        k = rng.choice([60, 1, 10, 0, 100])
        add("_rrf_fuse_fact_ids", [rankings, k], call_sync(ns._rrf_fuse_fact_ids, rankings, k=k))

    for _ in range(N):
        recs = []
        for _ in range(rng.randint(0, 8)):
            r = {"fact_id": rng.choice(IDS)}
            c = rng.random()
            if c < 0.2:
                pass  # 缺 source_doc_id 鍵
            elif c < 0.3:
                r["source_doc_id"] = None
            else:
                r["source_doc_id"] = rng.choice(DOCS + [UUID(d) for d in DOCS[:2]])
            recs.append(r)
        allowed = rng.choice([None, [], set(), [UUID(d) for d in rng.sample(DOCS, 2)], {UUID(DOCS[0])}, [UUID(DOCS[4])]])
        add("_filter_fact_candidates_by_source_scope", [recs, sorted(map(str, allowed)) if allowed else allowed],
            call_sync(ns._filter_fact_candidates_by_source_scope, recs, allowed))

    for _ in range(N):
        recs = []
        for i in range(rng.randint(0, 10)):
            r = {"fact_id": f"r{i}"}
            c = rng.random()
            if c < 0.25:
                r["source_doc_id"] = None
            elif c < 0.3:
                pass
            else:
                r["source_doc_id"] = rng.choice(DOCS[:3])
            recs.append(r)
        top_k = rng.choice([0, 1, 2, 3, 5, 20])
        cap = rng.choice([None, None, 1, 2, 3])
        add("_apply_source_doc_cap", [recs, top_k, cap], call_sync(ns._apply_source_doc_cap, recs, top_k, cap))

    for _ in range(N):
        recs = []
        for i in range(rng.randint(0, 10)):
            r = {"fact_id": f"r{i}", "subject": rng.choice(ENT), "rel_type": rng.choice(REL), "object": rng.choice(ENT)}
            c = rng.random()
            if c < 0.75:
                r["score"] = rng.choice([0.1, 0.5, 0.5, 0.9, 1, 0])
            recs.append(r)
        if rng.random() < 0.05:
            recs.append({"fact_id": "bad", "subject": "勞工", "rel_type": "REQUIRES", "object": "婚假", "score": None})
        add("_dedupe_facts_by_key", [recs], call_sync(ns._dedupe_facts_by_key, recs))

    for _ in range(N):
        rel_types = rng.choice(["A|B", "IS_A|PART_OF|RELATED_TO", "X", "", "`A`|`B`"])
        lo = rng.randint(0, 3)
        hi = rng.randint(lo, 4)
        scoped = rng.random() < 0.5
        psl = rng.random() < 0.5
        add("_bfs_pass_cypher", [rel_types, lo, hi, scoped, psl],
            call_sync(ns._bfs_pass_cypher, rel_types, lo, hi, scoped=scoped, per_seed_limit=psl))

    def citation(rng):
        c = {}
        for key in ("verb", "source", "source_svo_chunk_file"):
            if rng.random() < 0.7:
                c[key] = rng.choice(["給予", "來源A", "svo-chunk-001.md", None])
        if rng.random() < 0.8:
            c["source_doc_id"] = rng.choice([str(uuid4()) if False else DOCS[0], DOCS[1], None, ""])
        if rng.random() < 0.7:
            c["source_svo_chunk_index"] = rng.choice([1, 2, 7, None])
        for key in ("source_sentence_start", "source_sentence_end"):
            if rng.random() < 0.6:
                c[key] = rng.choice([1, 5, None])
        if rng.random() < 0.3:
            c["article_no"] = "第 3 條"
        return c

    for i in range(N):
        records = []
        for _ in range(rng.randint(0, 4)):
            rec = {"subject": rng.choice(["勞工", "雇主", "甲"]), "subject_type": rng.choice(["概念", "PERSON"]),
                   "rel_type": rng.choice(["HAS_PROPERTY", "REQUIRES"]), "confidence": rng.choice([1, 2, 3]),
                   "natural_text": rng.choice([None, "自然句。", ""]), "object": rng.choice(["婚假", "工資"]),
                   "object_type": rng.choice(["概念", "MONEY"])}
            m = rng.random()
            if m < 0.15:
                rec["citations_json"] = None
            elif m < 0.25:
                rec["citations_json"] = ""
            elif m < 0.28:
                rec["citations_json"] = "not json"
            else:
                rec["citations_json"] = json.dumps([citation(rng) for _ in range(rng.randint(0, 3))], ensure_ascii=False)
            if rng.random() < 0.03:
                rec.pop("rel_type")
            if rng.random() < 0.03:
                rec["citations_json"] = json.dumps([{"source_doc_id": "not-a-uuid"}])
            records.append(rec)
        add("_bfs_records_to_triples", [records], call_sync(ns._bfs_records_to_triples, records))
    return out


def main() -> int:
    if "--write-golden" in sys.argv:
        from services import svo_service

        cases = run_all(svo_service)
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(cases, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(len(cases), "cases written")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
