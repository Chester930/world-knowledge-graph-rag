"""L3′ 時間感知檢索評測執行器（報告266）——依 `data/eval/pilot_time_questions.json` 的**預先寫死判準**（criteria_sha256 鎖定）。

比較 `asof`（先過濾後去重）與 `naive`（現行 `vector_search_facts`）兩種檢索，`top_k=20`，以 Fact 所屬 `LawArticle`
（`law_id`＋`article_no`＋`valid_from`）判定 hit／leak，**不看生成**。純計算部分（判定與彙總）離線可測；`--execute` 才連試點 Neo4j
（重用 `scripts/kg/pilot_import` 的閘門：埠 28687）與 Ollama `bge-m3`，由規劃對話執行。判準與題目不得因結果調整。

用法：python scripts/analysis/pilot_time_eval.py --execute [--out data/analysis/pilot_time_eval_20261003.json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import UUID

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

QUESTIONS_PATH = _REPO / "data" / "eval" / "pilot_time_questions.json"
DEFAULT_OUT = _REPO / "data" / "analysis" / "pilot_time_eval_20261003.json"
TOP_K = 20
MODES = ("asof", "naive")


def evaluate_question(question: Mapping[str, Any], results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """單題判定。target＝與題目同法規同條號的回傳 Fact；hit＝其中有期望版本（對照組：acceptable_valid_froms 任一）；
    leak＝（僅實質修改題）其中有「另一版」——該版在 as_of 當時不應有效（兩版中期望版本才是當時有效者）。"""
    target = [r for r in results if r.get("law_id") == question["law_id"] and r.get("article_no") == question["article_no"]]
    versions = sorted({r.get("valid_from") for r in target if r.get("valid_from")})
    acceptable = set(question.get("acceptable_valid_froms") or [question["expected_valid_from"]])
    hit = any(r.get("valid_from") in acceptable for r in target)
    leak = None
    if question["pair_kind"] == "substantive":
        leak = any(r.get("valid_from") == question["other_valid_from"] for r in target)
    return {"id": question["id"], "pair_kind": question["pair_kind"], "is_conflict": bool(question["is_conflict"]),
            "expected_role": question.get("expected_role"), "n_results": len(results), "n_target": len(target),
            "versions_returned": versions, "hit": hit, "leak": leak}


def _rate(flags: Sequence[bool]) -> float | None:
    return round(sum(1 for f in flags if f) / len(flags), 4) if flags else None


def summarize(per_question: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    """彙總（判準見題庫 meta.criteria）：主要指標＝substantive 且非 conflict；控制組＝format_only／same_hash；衝突題另列。"""
    def pick(mode: str, pred) -> list[Mapping[str, Any]]:
        return [r for r in per_question[mode] if pred(r)]

    primary = lambda r: r["pair_kind"] == "substantive" and not r["is_conflict"]  # noqa: E731
    conflict = lambda r: r["is_conflict"]  # noqa: E731
    control = lambda r: r["pair_kind"] in ("format_only", "same_hash")  # noqa: E731
    out: dict[str, Any] = {"n": {m: len(per_question[m]) for m in MODES}}
    for name, pred in (("primary", primary), ("control", control), ("conflict", conflict)):
        block: dict[str, Any] = {}
        for mode in MODES:
            rows = pick(mode, pred)
            block[mode] = {"n": len(rows), "hit_rate": _rate([r["hit"] for r in rows]),
                           "leak_rate": _rate([r["leak"] for r in rows if r["leak"] is not None]) if name != "control" else None}
        out[name] = block
    p = out["primary"]
    out["verdict"] = {
        "asof_leak_rate_le_0.05": (p["asof"]["leak_rate"] is not None and p["asof"]["leak_rate"] <= 0.05),
        "asof_hit_rate_ge_naive": (p["asof"]["hit_rate"] is not None and p["naive"]["hit_rate"] is not None
                                   and p["asof"]["hit_rate"] >= p["naive"]["hit_rate"]),
        "control_hit_equal": out["control"]["asof"]["hit_rate"] == out["control"]["naive"]["hit_rate"],
        "secondary_naive_leak_rate": p["naive"]["leak_rate"],
        "secondary_hit_rate_diff_asof_minus_naive": (None if p["asof"]["hit_rate"] is None or p["naive"]["hit_rate"] is None
                                                     else round(p["asof"]["hit_rate"] - p["naive"]["hit_rate"], 4)),
    }
    out["verdict"]["primary_pass"] = bool(out["verdict"]["asof_leak_rate_le_0.05"] and out["verdict"]["asof_hit_rate_ge_naive"])
    return out


def load_questions(path: Path = QUESTIONS_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


async def execute(out_path: Path) -> int:
    from scripts.kg import pilot_import as pi

    corpus_dir = pi.default_corpus_dir()
    manifest = pi.load_manifest(corpus_dir)
    facts = pi.validate_environment(os.environ, corpus_dir, manifest)
    from core.config import settings
    from core.database import connect, disconnect, get_driver
    from core.providers.factory import init_providers
    from scripts.kg.pilot_asof_search import asof_search

    if settings.neo4j_uri != os.environ["NEO4J_URI"]:
        raise pi.GateViolation("有效設定與行程環境變數不一致，停止")
    pi.validate_target_uri(settings.neo4j_uri)
    doc = load_questions()
    kg_id = UUID(facts["kg_id"])
    await connect()
    per_question: dict[str, list[dict[str, Any]]] = {m: [] for m in MODES}
    details: list[dict[str, Any]] = []
    try:
        embedding = init_providers()
        driver = get_driver()
        for q in doc["questions"]:
            vector = await embedding.encode(q["question"])
            row_detail: dict[str, Any] = {"id": q["id"]}
            for mode in MODES:
                results = await asof_search(driver, kg_id, vector, q["as_of"], TOP_K, mode=mode)
                judged = evaluate_question(q, results)
                per_question[mode].append(judged)
                row_detail[mode] = {k: judged[k] for k in ("hit", "leak", "n_results", "n_target", "versions_returned")}
            details.append(row_detail)
    finally:
        await disconnect()
    summary = summarize(per_question)
    result = {"criteria_sha256": doc["meta"]["criteria_sha256"], "top_k": TOP_K, "question_count": len(doc["questions"]),
              "summary": summary, "per_question": details, "embedding_provider_called": True}
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--execute", action="store_true", help="連線評測（由規劃對話執行）")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    if not args.execute:
        doc = load_questions()
        print(json.dumps({"mode": "plan", "connects": False, "questions": len(doc["questions"]),
                          "criteria_sha256": doc["meta"]["criteria_sha256"], "top_k": TOP_K, "modes": list(MODES)}, ensure_ascii=False))
        return 0
    return asyncio.run(execute(args.out))


if __name__ == "__main__":
    raise SystemExit(main())
