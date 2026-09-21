"""Three-question upper-bound pilot for the one-slot Fact boundary swap."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

REPO_ROOT = ROOT.parents[2]
swap_enabled = "--control" not in sys.argv
experiment_name = "fact_rerank_control_matched_v2"
out_dir = REPO_ROOT / ".claude" / "tmp" / "rq1_scope_audit_20260919" / experiment_name
if out_dir.exists() and any(out_dir.iterdir()):
    raise SystemExit(f"Refusing to overwrite non-empty output directory: {out_dir}")
out_dir.mkdir(parents=True, exist_ok=True)

target_patterns = {
    "57-AGGR15": ["職業安全衛生法", "第二十三條第五項"],
    "57-AGGR16": ["第二類事業", "具中度風險者"],
    "57-AGGR17": ["第三類事業", "具低度風險者"],
}
dataset_path = ROOT / "data" / "eval" / "test_cases.json"
dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
selected = [item for item in dataset["questions"] if item["id"] in target_patterns]
if {item["id"] for item in selected} != set(target_patterns):
    raise SystemExit("The source dataset is missing one or more expected AGGR cases")
subset = {key: value for key, value in dataset.items() if key != "questions"}
subset["questions"] = selected
questions_path = out_dir / "questions.json"
questions_path.write_text(
    json.dumps(subset, ensure_ascii=False, indent=2), encoding="utf-8"
)
(out_dir / "experiment_config.json").write_text(
    json.dumps(
        {
            "variant": (
                "fact_boundary_swap_three_question_upper_bound"
                if swap_enabled
                else "fact_rerank_no_swap_three_question_control"
            ),
            "question_ids": list(target_patterns),
            "target_patterns": target_patterns,
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
            "diagnostic_granularity": (
                "Each diagnostic row is one prompt-arrangement call; a harness run may "
                "assemble multiple prompts for subquestions or grounding regeneration"
            ),
            "swap_enabled": swap_enabled,
            "operation": (
                "After Fact-first duplicate handling and embedding reranking, "
                "promote a question-specific required Fact only when it is "
                "exactly one place beyond the computed Fact budget"
                if swap_enabled
                else "Fact-first duplicate handling and embedding reranking; no boundary swap"
            ),
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
_question_id_by_text = {item["question"]: item["id"] for item in selected}
_current_question: str | None = None
_arrangements_by_question: dict[str, int] = {}
diagnostics: list[dict] = []


def _normalize(text: str) -> str:
    return "".join((text or "").split()).casefold()


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


def _matches_target(question_id: str, line: str) -> bool:
    normalized = _normalize(line)
    return all(_normalize(pattern) in normalized for pattern in target_patterns[question_id])


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
    question_id = _question_id_by_text.get(_current_question or "")
    arrangement_call = None
    if question_id is not None:
        arrangement_call = _arrangements_by_question.get(question_id, 0) + 1
        _arrangements_by_question[question_id] = arrangement_call
    positions = (
        [i for i, line in enumerate(reranked) if _matches_target(question_id, line)]
        if question_id is not None
        else []
    )
    initial_positions = (
        [i for i, line in enumerate(fact_lines) if _matches_target(question_id, line)]
        if question_id is not None
        else []
    )
    target_rank_after_rerank = positions[0] + 1 if positions else None
    displaced_line = None
    swap_applied = bool(
        swap_enabled and positions and positions[0] == budget and budget > 0
    )
    if swap_applied:
        displaced_line = reranked[budget - 1]
        reranked[budget - 1], reranked[positions[0]] = (
            reranked[positions[0]],
            reranked[budget - 1],
        )
    final_rank = next(
        (i + 1 for i, line in enumerate(reranked)
         if question_id is not None and _matches_target(question_id, line)),
        None,
    )
    diagnostics.append(
        {
            "question_id": question_id,
            "arrangement_call": arrangement_call,
            "question": question,
            "fact_candidate_count": len(fact_lines),
            "target_patterns": target_patterns.get(question_id, []),
            "target_rank_before_rerank": initial_positions[0] + 1 if initial_positions else None,
            "target_rank_after_rerank": target_rank_after_rerank,
            "fact_budget": budget,
            "swap_applied": swap_applied,
            "target_rank_after_swap": final_rank,
            "target_retained_by_fact_budget": bool(final_rank and final_rank <= budget),
            "displaced_fact_line": displaced_line,
        }
    )
    return await _real_arrange(question, bfs_lines, reranked, **kwargs)


async def _top_k25(payload):
    global _current_question
    _current_question = payload.question
    payload = payload.model_copy(update={"top_k": 25})
    return await _real_chat(payload)


agent._split_fact_lines = _fact_first_split
agent._arrange_fact_lines = _rerank_and_swap
agent.chat = _top_k25

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

label = "fact-boundary-swap-eval" if swap_enabled else "fact-rerank-control-eval"
print(f"[{label}] questions={list(target_patterns)} out={out_dir}")
main()
diagnostics_name = "swap_diagnostics.json" if swap_enabled else "rerank_diagnostics.json"
(out_dir / diagnostics_name).write_text(
    json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8"
)
