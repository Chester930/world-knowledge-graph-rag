"""檢索失敗診斷：判斷「gold span 沒被撈到」是抽取端缺口、還是排名太後（報告57 §4.20）。

對每題「所有有效執行都沒命中」的必要 gold span，唯讀查 KG：
  1. 該 span 所屬條文（`LawArticle`）底下有哪些 `Fact`、與 span 的 embedding 餘弦相似度；
  2. 重現 `vector_search_facts()`（範圍＝凍結的 23 份文件）後，這些 `Fact` 的全域排名。

輸出供人工閱讀；相似度與排名只是輔助，最終分類（沒抽到／抽到但語意破碎／抽到但排太後／
其他）由人讀 Fact 文字判斷。**唯讀，不寫 KG**；需 Neo4j 與 Ollama(bge-m3) 可連線。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path
from uuid import UUID, uuid5

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from neo4j import AsyncGraphDatabase  # noqa: E402

from core.constants import DOCUMENT_ID_NAMESPACE  # noqa: E402
from core.providers.embedding.ollama import OllamaEmbeddingProvider  # noqa: E402
from routers.agent import _find_seed_entities, _relevant_doc_ids_from_seeds, _resolve_doc_scope  # noqa: E402
from services.svo_service import vector_search_facts  # noqa: E402

SEARCH_TOP_K = 300


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def normalize_article(source_article: str) -> str | None:
    """'第6條第2項' -> '第6條'；附表等無法對應條文者回傳 None。"""
    m = re.match(r"\s*(第\s*\d+(?:-\d+)?\s*條)", source_article or "")
    return re.sub(r"\s+", "", m.group(1)) if m else None


def persistently_missed(records: list[dict]) -> list[str]:
    """回傳在**所有**有效執行中都未命中的 exact_span。"""
    valid = [r for r in records if not r.get("error")]
    if not valid:
        return []
    missed_sets = [set(r["lineage"]["stage1_retrieval"]["missed_exact_spans"]) for r in valid]
    return sorted(set.intersection(*missed_sets)) if missed_sets else []


async def main_async(args: argparse.Namespace) -> None:
    bank = {q["id"]: q for q in json.loads(Path(args.bank).read_text(encoding="utf-8"))["questions"]}
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    kg_id = manifest["kg_id"]
    runs: dict[str, list[dict]] = defaultdict(list)
    for path in args.records:
        for r in json.loads(Path(path).read_text(encoding="utf-8")):
            runs[r["question_id"]].append(r)

    driver = AsyncGraphDatabase.driver(args.neo4j_uri, auth=("neo4j", args.neo4j_password))
    embed = OllamaEmbeddingProvider(args.ollama_url, "bge-m3")

    # 文件 ID＝uuid5(DOCUMENT_ID_NAMESPACE, source)。附表等文件沒有獨立的 Document 節點，
    # 不能用標題比對，直接算 ID。
    def doc_uuid(source: str) -> str:
        return str(uuid5(DOCUMENT_ID_NAMESPACE, source))

    scope_ids = {UUID(doc_uuid(name)) for name in manifest["scope_doc_ids"]}

    report = []
    for qid in args.question_ids:
        case = bank[qid]
        missed = persistently_missed(runs[qid])
        gold = {g["exact_span"]: g for g in case["atomic_gold_facts"]}
        qvec = await embed.encode(case["question"])
        # 重現 chat() 的實際 Fact 檢索範圍：種子實體推出的文件 ∩ 明確指定的範圍（錨定優先）。
        seeds = await _find_seed_entities(
            driver, UUID(kg_id), case["question"], embedding_provider=embed, question_vector=qvec
        )
        seed_docs = await _relevant_doc_ids_from_seeds(driver, UUID(kg_id), seeds)
        prod_scope = _resolve_doc_scope(seed_docs, set(), scope_ids)
        ranked = await vector_search_facts(
            driver, UUID(kg_id), qvec, top_k=SEARCH_TOP_K, allowed_source_doc_ids=prod_scope or scope_ids
        )
        rank_of = {}
        for i, f in enumerate(ranked, start=1):
            rank_of.setdefault(f["fact_text"], i)
        q_entry = {
            "question_id": qid, "n_runs": len(runs[qid]), "seeds": seeds[:8],
            "prod_scope_size": len(prod_scope or []), "spans": [],
        }
        for span in missed:
            g = gold.get(span, {})
            source_law, source_article = g.get("source_law", ""), g.get("source_article", "")
            doc_id = doc_uuid(source_law) if source_law else None
            art = normalize_article(source_article)
            span_vec = await embed.encode(span)
            if doc_id and art:
                q = """MATCH (f:Fact {kg_id:$k, source_doc_id:$d})-[:SUPPORTED_BY]->(a:LawArticle)
                       WHERE replace(a.article_no,' ','') = $art
                       RETURN f.fact_text AS t, f.fact_embedding AS e"""
                rows = (await driver.execute_query(q, k=kg_id, d=doc_id, art=art)).records
                scope_kind = f"條文 {art}"
            elif doc_id:
                q = """MATCH (f:Fact {kg_id:$k, source_doc_id:$d})
                       RETURN f.fact_text AS t, f.fact_embedding AS e"""
                rows = (await driver.execute_query(q, k=kg_id, d=doc_id)).records
                scope_kind = "整份文件（無法對應條文）"
            else:
                rows, scope_kind = [], "找不到文件"
            cands = sorted(
                (
                    {"cos": round(cosine(span_vec, r["e"]), 3) if r["e"] else None,
                     "rank": rank_of.get(r["t"]), "text": r["t"]}
                    for r in rows
                ),
                key=lambda c: -(c["cos"] or 0),
            )
            q_entry["spans"].append({
                "gold_doc_in_prod_scope": (UUID(doc_id) in prod_scope) if (doc_id and prod_scope) else None,
                "span": span, "essential": g.get("is_essential"), "source_law": source_law,
                "source_article": source_article, "candidate_scope": scope_kind,
                "n_candidate_facts": len(rows), "top_candidates": cands[:5],
            })
        report.append(q_entry)
    await driver.close()
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(report)} questions to {args.out}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bank", required=True)
    p.add_argument("--manifest", required=True, help="frozen_manifest.json")
    p.add_argument("--records", action="append", default=[])
    p.add_argument("--question-ids", nargs="+", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--neo4j-uri", default="bolt://localhost:17990")
    p.add_argument("--neo4j-password", default="kg2_test_2026")
    p.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    main()
