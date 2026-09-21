"""Scratch driver (not committed) for the K+Hybrid/K+Cap/K+Hybrid+Cap ablation.

Monkeypatches routers.agent.vector_search_facts / routers.agent.chat in-process
so the real `chat()` production code path runs unmodified, just with hybrid/
source_doc_cap injected for this process only. Delegates the rest to the
existing scripts/eval/run_rq1_comparison.py harness (same CLI args as the
K-arm baseline run in rq1_stage1_health_check_pilot_v3/manifest.json).

Usage:
  ABLATION_HYBRID=1 ABLATION_CAP=8 OUT_DIR=rq1_ablation_hybrid_cap \
    python _run_ablation_arm.py
"""
import os
import sys

import routers.agent as agent

ABLATION_HYBRID = os.environ.get("ABLATION_HYBRID") == "1"
_cap_raw = os.environ.get("ABLATION_CAP", "").strip()
ABLATION_CAP = int(_cap_raw) if _cap_raw else None
OUT_DIR = os.environ.get("OUT_DIR", "rq1_ablation_arm")

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
    f"[ablation] hybrid={ABLATION_HYBRID} source_doc_cap={ABLATION_CAP} out={OUT_DIR}",
    file=sys.stderr,
)

sys.argv = [
    "run_rq1_comparison.py",
    "--kg-id", "236903cf-055a-40a8-8923-b9d06601f3b7",
    "--doc-ids",
    "N0060007_高溫作業勞工作息時間標準,N0060012_精密作業勞工視機能保護設施標準,"
    "N0060015_特定化學物質危害預防標準,N0060022_勞工健康保護規則,"
    "N0060022_附表一_特別危害健康作業",
    "--questions", "_ablation_3q.json",
    "--arms", "K",
    "--runs", "1",
    "--query-timeout-s", "300",
    "--allow-shared-judge",
    "--out", OUT_DIR,
]

from scripts.eval.run_rq1_comparison import main  # noqa: E402

main()
