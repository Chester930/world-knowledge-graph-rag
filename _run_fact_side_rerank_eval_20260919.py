"""Scratch RQ1 pilot for Fact-first deduplication and embedding reranking.

The evaluator raises AGGR16 to top_k=25. For each case, duplicate Fact entries
take precedence over same-key BFS renderings, then Fact lines are re-ranked with
the existing query-embedding scorer before the unchanged 18-line allocator.
All changes are process-local; no production code, KG config, or graph data is
written.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

allowed_out_dir = (ROOT.parents[2] / ".claude" / "tmp").resolve()
out_dir = allowed_out_dir / "rq1_fact_ranking_20260918" / "fact_side_embedding_rerank"
if out_dir.exists() and any(out_dir.iterdir()):
    raise SystemExit(f"Refusing to overwrite non-empty output directory: {out_dir}")
out_dir.mkdir(parents=True, exist_ok=True)

dataset_path = ROOT / "data" / "eval" / "test_cases.json"
selected_ids = {"57-AGGR15", "57-AGGR16", "57-AGGR17"}
dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
selected = [item for item in dataset["questions"] if item["id"] in selected_ids]
if {item["id"] for item in selected} != selected_ids:
    raise SystemExit("The source dataset does not contain exactly the requested cases")

subset = {key: value for key, value in dataset.items() if key != "questions"}
subset["questions"] = selected
questions_path = out_dir / "questions.json"
questions_path.write_text(
    json.dumps(subset, ensure_ascii=False, indent=2), encoding="utf-8"
)
(out_dir / "experiment_config.json").write_text(
    json.dumps(
        {
            "variant": "fact_side_embedding_rerank",
            "question_ids": sorted(selected_ids),
            "kg_id": "236903cf-055a-40a8-8923-b9d06601f3b7",
            "doc_ids": [
                "N0060027_職業安全衛生管理辦法",
                "N0060001_職業安全衛生法",
            ],
            "runs": 3,
            "query_timeout_s": 900,
            "allow_shared_judge": True,
            "fact_top_k": {"57-AGGR15": 20, "57-AGGR16": 25, "57-AGGR17": 20},
            "fact_duplicate_policy": "Fact representation wins when a candidate shares a triple key with BFS",
            "fact_reranker": "existing _score_lines_by_embedding with the request question vector",
            "context_line_cap": 18,
            "production_code_modified": False,
            "neo4j_fact_data_writes_expected": False,
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)

import routers.agent as agent  # noqa: E402
from core.kg_config import KGConfig  # noqa: E402

_real_chat = agent.chat
_real_split_fact_lines = agent._split_fact_lines
_real_arrange_fact_lines = agent._arrange_fact_lines
_current_question: str | None = None
rerank_diagnostics: list[dict] = []


def _fact_key(fact: dict) -> tuple[str, str, str] | None:
    key = (fact.get("subject"), fact.get("rel_type"), fact.get("object"))
    return key if all(key) else None


def _fact_first_split(triples, fact_results):
    """Keep one representation per triple key, preferring retrieved Fact lines."""
    _, fact_lines = _real_split_fact_lines([], fact_results)
    fact_keys = {key for fact in fact_results if (key := _fact_key(fact))}
    bfs_lines, _ = _real_split_fact_lines(triples, [])
    duplicate_bfs_lines = set()
    for triple in triples:
        key = (triple.subject, triple.rel_type, triple.object)
        if all(key) and key in fact_keys:
            raw = triple.natural_text or f"{triple.subject} {triple.verb} {triple.object}".rstrip()
            duplicate_bfs_lines.add(f"- {agent._strip_type_markers(raw)}")
    return [line for line in bfs_lines if line not in duplicate_bfs_lines], fact_lines


def _is_target_fact(line: str) -> bool:
    return "第二類事業" in line and "具中度風險者" in line


async def _rerank_facts_before_assembly(question, bfs_lines, fact_lines, **kwargs):
    embedding_provider = kwargs.get("embedding_provider")
    question_vector = kwargs.get("question_vector")
    reranked_facts = await agent._score_lines_by_embedding(
        question,
        fact_lines,
        embedding_provider=embedding_provider,
        question_vector=question_vector,
    )
    before_ranks = [i + 1 for i, line in enumerate(fact_lines) if _is_target_fact(line)]
    after_ranks = [i + 1 for i, line in enumerate(reranked_facts) if _is_target_fact(line)]
    cfg = kwargs.get("cfg") or KGConfig()
    bfs_count = min(len(bfs_lines), cfg.factlist.bfs_keep_max)
    total_count = len(reranked_facts) + bfs_count
    if total_count <= cfg.factlist.truncate_k:
        fact_budget = len(reranked_facts)
    else:
        target = (
            cfg.factlist.truncate_k
            if total_count <= cfg.factlist.reorder_threshold_k
            else cfg.factlist.reorder_threshold_k
        )
        bfs_budget = min(
            bfs_count,
            max(cfg.factlist.min_bfs_slots, target - len(reranked_facts)),
        )
        fact_budget = min(len(reranked_facts), target - bfs_budget)
    if _current_question and "第二類事業" in _current_question:
        rerank_diagnostics.append(
            {
                "question": question,
                "fact_candidate_count": len(fact_lines),
                "target_rank_before_rerank": min(before_ranks) if before_ranks else None,
                "target_rank_after_rerank": min(after_ranks) if after_ranks else None,
                "fact_budget_for_context": fact_budget,
                "target_retained_by_fact_budget": bool(
                    after_ranks and after_ranks[0] <= fact_budget
                ),
            }
        )
    return await _real_arrange_fact_lines(
        question, bfs_lines, reranked_facts, **kwargs
    )


async def _top_k25_for_aggr16(payload):
    global _current_question
    _current_question = payload.question
    if payload.question == "《職業安全衛生管理辦法》規定的第一類事業與第二類事業，風險等級與應設置管理單位的人數門檻各是什麼？":
        payload = payload.model_copy(update={"top_k": 25})
    return await _real_chat(payload)


agent._split_fact_lines = _fact_first_split
agent._arrange_fact_lines = _rerank_facts_before_assembly
agent.chat = _top_k25_for_aggr16

sys.argv = [
    "run_rq1_comparison.py",
    "--kg-id",
    "236903cf-055a-40a8-8923-b9d06601f3b7",
    "--doc-ids",
    "N0060027_職業安全衛生管理辦法,N0060001_職業安全衛生法",
    "--questions",
    str(questions_path),
    "--arms",
    "K",
    "--runs",
    "3",
    "--query-timeout-s",
    "900",
    "--allow-shared-judge",
    "--out",
    str(out_dir),
]

from scripts.eval.run_rq1_comparison import main  # noqa: E402

print(f"[fact-rerank-eval] questions={len(selected)} out={out_dir}")
main()
(out_dir / "rerank_diagnostics.json").write_text(
    json.dumps(rerank_diagnostics, ensure_ascii=False, indent=2), encoding="utf-8"
)
