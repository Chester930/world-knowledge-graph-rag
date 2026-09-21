"""AGGR16 upper-bound pilot swapping the rank-15 Fact into its 14-line budget."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

allowed_out_dir = (ROOT.parents[2] / ".claude" / "tmp").resolve()
out_dir = allowed_out_dir / "rq1_fact_ranking_20260918" / "fact_boundary_swap"
if out_dir.exists() and any(out_dir.iterdir()):
    raise SystemExit(f"Refusing to overwrite non-empty output directory: {out_dir}")
out_dir.mkdir(parents=True, exist_ok=True)

question_id = "57-AGGR16"
question_text = "《職業安全衛生管理辦法》規定的第一類事業與第二類事業，風險等級與應設置管理單位的人數門檻各是什麼？"
dataset_path = ROOT / "data" / "eval" / "test_cases.json"
dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
selected = [item for item in dataset["questions"] if item["id"] == question_id]
if len(selected) != 1 or selected[0]["question"] != question_text:
    raise SystemExit("The source dataset does not contain the expected AGGR16 case")
subset = {key: value for key, value in dataset.items() if key != "questions"}
subset["questions"] = selected
questions_path = out_dir / "questions.json"
questions_path.write_text(
    json.dumps(subset, ensure_ascii=False, indent=2), encoding="utf-8"
)
(out_dir / "experiment_config.json").write_text(
    json.dumps(
        {
            "variant": "fact_boundary_swap_upper_bound",
            "question_id": question_id,
            "kg_id": "236903cf-055a-40a8-8923-b9d06601f3b7",
            "doc_ids": [
                "N0060027_職業安全衛生管理辦法",
                "N0060001_職業安全衛生法",
            ],
            "runs": 3,
            "query_timeout_s": 900,
            "allow_shared_judge": True,
            "fact_top_k": 25,
            "context_line_cap": 18,
            "operation": "After Fact-first duplicate handling and embedding reranking, swap rank-15 target Fact into the final rank-14 Fact slot",
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
_real_split = agent._split_fact_lines
_real_arrange = agent._arrange_fact_lines
_current_question: str | None = None
diagnostics: list[dict] = []


def _fact_key(fact: dict) -> tuple[str, str, str] | None:
    key = (fact.get("subject"), fact.get("rel_type"), fact.get("object"))
    return key if all(key) else None


def _fact_first_split(triples, fact_results):
    _, fact_lines = _real_split([], fact_results)
    fact_keys = {key for fact in fact_results if (key := _fact_key(fact))}
    bfs_lines, _ = _real_split(triples, [])
    duplicate_lines = set()
    for triple in triples:
        key = (triple.subject, triple.rel_type, triple.object)
        if all(key) and key in fact_keys:
            raw = triple.natural_text or f"{triple.subject} {triple.verb} {triple.object}".rstrip()
            duplicate_lines.add(f"- {agent._strip_type_markers(raw)}")
    return [line for line in bfs_lines if line not in duplicate_lines], fact_lines


def _is_target(line: str) -> bool:
    return "第二類事業" in line and "具中度風險者" in line


def _fact_budget(fact_count: int, bfs_count: int, cfg) -> int:
    bfs_count = min(bfs_count, cfg.factlist.bfs_keep_max)
    total = fact_count + bfs_count
    if total <= cfg.factlist.truncate_k:
        return fact_count
    target = (
        cfg.factlist.truncate_k
        if total <= cfg.factlist.reorder_threshold_k
        else cfg.factlist.reorder_threshold_k
    )
    kept_bfs = min(
        bfs_count,
        max(cfg.factlist.min_bfs_slots, target - fact_count),
    )
    return min(fact_count, target - kept_bfs)


async def _rerank_and_swap(question, bfs_lines, fact_lines, **kwargs):
    reranked = await agent._score_lines_by_embedding(
        question,
        fact_lines,
        embedding_provider=kwargs.get("embedding_provider"),
        question_vector=kwargs.get("question_vector"),
    )
    cfg = kwargs.get("cfg") or KGConfig()
    budget = _fact_budget(len(reranked), len(bfs_lines), cfg)
    positions = [i for i, line in enumerate(reranked) if _is_target(line)]
    before_rank = next((i + 1 for i, line in enumerate(fact_lines) if _is_target(line)), None)
    after_rank = positions[0] + 1 if positions else None
    dropped_line = None
    if (
        _current_question == question_text
        and positions
        and positions[0] == budget
        and budget > 0
    ):
        dropped_line = reranked[budget - 1]
        reranked[budget - 1], reranked[positions[0]] = (
            reranked[positions[0]],
            reranked[budget - 1],
        )
    final_rank = next((i + 1 for i, line in enumerate(reranked) if _is_target(line)), None)
    diagnostics.append(
        {
            "question": question,
            "fact_candidate_count": len(fact_lines),
            "target_rank_before_rerank": before_rank,
            "target_rank_after_rerank": after_rank,
            "fact_budget": budget,
            "target_rank_after_swap": final_rank,
            "target_retained_by_fact_budget": bool(final_rank and final_rank <= budget),
            "displaced_fact_line": dropped_line,
        }
    )
    return await _real_arrange(question, bfs_lines, reranked, **kwargs)


async def _top_k25_aggr16(payload):
    global _current_question
    _current_question = payload.question
    payload = payload.model_copy(update={"top_k": 25})
    return await _real_chat(payload)


agent._split_fact_lines = _fact_first_split
agent._arrange_fact_lines = _rerank_and_swap
agent.chat = _top_k25_aggr16

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

print(f"[fact-boundary-swap-eval] question={question_id} out={out_dir}")
main()
(out_dir / "swap_diagnostics.json").write_text(
    json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8"
)
