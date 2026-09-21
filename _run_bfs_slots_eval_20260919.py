"""Scratch RQ1 runner testing one extra reserved BFS context line.

The only intervention is a process-local wrapper around
``routers.agent._arrange_fact_lines`` that sets ``factlist.min_bfs_slots`` to 5.
No production module, KG configuration, or Neo4j graph data is written.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

allowed_out_dir = (ROOT.parents[2] / ".claude" / "tmp").resolve()
out_dir = allowed_out_dir / "rq1_fact_ranking_20260918" / "bfs_slots_5"
if out_dir == allowed_out_dir:
    raise SystemExit(f"Refusing to write directly into {allowed_out_dir}")
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
            "variant": "bfs_slots_5",
            "question_ids": sorted(selected_ids),
            "kg_id": "236903cf-055a-40a8-8923-b9d06601f3b7",
            "doc_ids": [
                "N0060027_職業安全衛生管理辦法",
                "N0060001_職業安全衛生法",
            ],
            "runs": 3,
            "query_timeout_s": 900,
            "allow_shared_judge": True,
            "intervention": "process-local factlist.min_bfs_slots=5; default is 4",
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

_real_arrange_fact_lines = agent._arrange_fact_lines


async def _arrange_with_one_extra_bfs_slot(question, bfs_lines, fact_lines, **kwargs):
    cfg = kwargs.get("cfg") or KGConfig()
    adjusted_factlist = cfg.factlist.model_copy(update={"min_bfs_slots": 5})
    kwargs["cfg"] = cfg.model_copy(update={"factlist": adjusted_factlist})
    return await _real_arrange_fact_lines(question, bfs_lines, fact_lines, **kwargs)


agent._arrange_fact_lines = _arrange_with_one_extra_bfs_slot

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

print(f"[bfs-slot-eval] min_bfs_slots=5 questions={len(selected)} out={out_dir}")
main()
