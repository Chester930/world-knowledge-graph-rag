"""Scratch driver (not committed) for K+Hybrid/K+Cap ablation on group-4
candidate questions (57-AGGR5/57-AGGR6), the confirmed vector_search_facts()
global-ranking-failure cases (N0060041 §25). Same monkeypatch approach as
_run_ablation_arm.py (group 1); kept as a separate file to preserve that one
as-is for reference.

Usage:
  ABLATION_HYBRID=1 ABLATION_CAP=5 OUT_DIR=rq1_g4_ablation_hybrid_cap \
    python _run_ablation_arm_g4.py
"""
import os
import sys

import routers.agent as agent

ABLATION_HYBRID = os.environ.get("ABLATION_HYBRID") == "1"
_cap_raw = os.environ.get("ABLATION_CAP", "").strip()
ABLATION_CAP = int(_cap_raw) if _cap_raw else None
OUT_DIR = os.environ.get("OUT_DIR", "rq1_g4_ablation_arm")

_real_chat = agent.chat
_real_vsf = agent.vector_search_facts
_ctx = {"question": None}


async def _patched_vsf(driver, kg_id, query_vector, top_k):
    return await _real_vsf(
        driver, kg_id, query_vector, top_k=top_k,
        hybrid=ABLATION_HYBRID,
        question=_ctx["question"] if ABLATION_HYBRID else None,
        source_doc_cap=ABLATION_CAP,
    )


async def _patched_chat(payload):
    _ctx["question"] = payload.question
    return await _real_chat(payload)


agent.vector_search_facts = _patched_vsf
agent.chat = _patched_chat

print(
    f"[g4-ablation] hybrid={ABLATION_HYBRID} source_doc_cap={ABLATION_CAP} out={OUT_DIR}",
    file=sys.stderr,
)

sys.argv = [
    "run_rq1_comparison.py",
    "--kg-id", "236903cf-055a-40a8-8923-b9d06601f3b7",
    "--doc-ids",
    "N0060041_職業災害勞工保護法,N0050031_勞工職業災害保險及保護法,"
    "N0060079_直轄市及縣市政府辦理協助職業災害勞工重返職場補助辦法",
    "--questions", "_ablation_group4_2q.json",
    "--arms", "K",
    "--runs", "3",
    "--query-timeout-s", "300",
    "--allow-shared-judge",
    "--out", OUT_DIR,
]

from scripts.eval.run_rq1_comparison import main  # noqa: E402

main()
