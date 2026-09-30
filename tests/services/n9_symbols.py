"""N9 G1／G2 的 8 個符號與搬移前原始碼基準（報告168 W1）。``--write-baseline`` 在搬移前擷取。"""

from __future__ import annotations

import json
import sys

from tests.services.n4_symbols import REPO, top_level_defs

N9_NAMES = [
    "_rrf_fuse_fact_ids", "_filter_fact_candidates_by_source_scope", "_apply_source_doc_cap", "_dedupe_facts_by_key",
    "_bfs_pass_cypher", "_bfs_records_to_triples", "_BFS_EXPAND_WHEN_BELOW", "_BFS_PRIZE_TOP_K",
]
BASELINE = REPO / "tests" / "services" / "fixtures" / "n9_symbol_source_baseline.json"

if __name__ == "__main__":
    if "--write-baseline" in sys.argv:
        defs = top_level_defs(REPO / "services" / "svo_service.py")
        BASELINE.write_text(json.dumps({n: defs[n][0] for n in N9_NAMES}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(len(N9_NAMES), "symbols")
