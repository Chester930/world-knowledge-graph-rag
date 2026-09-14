"""RQ1 統一評測 Harness（SDD-2.1 交付物）。

支援：
- 四大核心代表方法（M1: Naive Chunk B0、M2: Hybrid Text B1、M3: Fact Vector F、M4: Full KG K）及消融組（D, G, K-2b）。
- 自動調用 AtomicScorer 執行原子法規真值比對（exact_span 逐字核驗）。
- 全鏈路 LineageTracker 記錄（因果隔離檢索、組裝與生成三階段）。
- 三階段 CostAnalyzer 生命週期成本報告與 Pareto 矩陣產出。

⚠️ **2026-09-14 補：`main()` 串接已完成**（原入庫時的誠實註記——`main()` 只寫
`manifest.json`、`_run_single_query()`/`_render_pareto_summary()` 從未被呼叫——已依報告
47 §5 任務A 修復）。串接方式仿照報告39 `run_retrieval_comparison.py` 的既有模式：
`--dry-run` 只印計畫不連線；預設對 `test_cases × arms × runs` 迴圈呼叫
`_run_single_query()`，逐 run 寫出 `run{n}.json`，全部跑完呼叫 `_render_pareto_summary()`。
另加上報告47 §5 任務A 前置條件的 eligibility filter：預設只納入
`verification_status == "verified"` 的題目（含 Canary），`--include-unverified` 可停用但
不得用於正式結論。**本次入庫尚未實際執行過完整跑測**（需要活的 Neo4j／LLM 服務，且與
其他共用該環境的行程有衝突風險）——執行前務必依報告47 §5.1 Track A／B 分流規則凍結
KG／commit／題庫版本。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import settings
from core.database import connect, disconnect, get_driver
from core.kg_config import ConfigLoader, FileConfigSource
from core.providers.factory import (
    get_embedding_provider,
    get_judge_llm_provider,
    get_llm_provider,
    init_providers,
)
from models.document import ChatRequest
from models.eval_schema import AtomicGoldFact, EvaluationDataset, TestCase
from repositories.kg_repo import KGRepository
from routers import agent
from services import baseline_rag_service, document_record_service
from services.atomic_scorer import AtomicScorer
from services.cost_analyzer import CostAnalyzer
from services.lineage_tracker import LineageTracker

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEST_CASES_PATH = REPO_ROOT / "data" / "eval" / "test_cases.json"
LEGACY_TEST_CASES_PATH = REPO_ROOT / "docs" / "附錄A題庫.json"

# 方法名稱別名映射
ARM_ALIAS_MAP = {
    "M1": "B0",
    "M2": "B1",
    "M3": "F",
    "M4": "K",
}
INVERSE_ARM_ALIAS_MAP = {
    "B0": "M1",
    "B1": "M2",
    "F": "M3",
    "K": "M4",
}


class _CountingLLM:
    """計數包裝器"""
    def __init__(self, inner):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "stream_calls", 0)
        object.__setattr__(self, "json_calls", 0)

    def reset(self):
        object.__setattr__(self, "stream_calls", 0)
        object.__setattr__(self, "json_calls", 0)

    @property
    def calls(self) -> int:
        return self.stream_calls + self.json_calls

    async def stream(self, prompt: str):
        object.__setattr__(self, "stream_calls", self.stream_calls + 1)
        async for tok in self._inner.stream(prompt):
            yield tok

    async def generate_json(self, prompt: str) -> str:
        object.__setattr__(self, "json_calls", self.json_calls + 1)
        return await self._inner.generate_json(prompt)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_inner"), name)


def _load_questions(
    spec: str, complexity: str, *, include_unverified: bool = False
) -> tuple[list[TestCase], int]:
    """載入題庫，並套用報告 47 §5 優先任務 A 的 eligibility filter。

    預設只納入 `verification_status == "verified"` 的題目（含 Canary，
    Canary 的拒答評分走 `AtomicScorer.evaluate(refusal_expected=True)`，
    不會被當成一般法律 exact-span 題計分）。回傳 `(合格題目, 被過濾題數)`，
    被過濾題數用於寫入 manifest 以利追溯。
    """
    path = Path(spec)
    if not path.exists():
        if DEFAULT_TEST_CASES_PATH.exists():
            path = DEFAULT_TEST_CASES_PATH
        else:
            path = LEGACY_TEST_CASES_PATH

    data = json.loads(path.read_text(encoding="utf-8"))
    raw_qs = data["questions"] if isinstance(data, dict) and "questions" in data else data

    selected_ids = None
    if spec and not Path(spec).exists():
        selected_ids = {s.strip() for s in spec.split(",") if s.strip()}

    out: list[TestCase] = []
    excluded_unverified = 0
    for q in raw_qs:
        if isinstance(q, dict):
            qid = q.get("id")
            if selected_ids is not None and qid not in selected_ids:
                continue
            if complexity != "all" and q.get("complexity_bucket") != complexity:
                continue
            if not include_unverified and q.get("verification_status") != "verified":
                excluded_unverified += 1
                continue
            # 轉換為 TestCase 物件
            gold_facts = [
                AtomicGoldFact(**f) if isinstance(f, dict) else f
                for f in q.get("atomic_gold_facts", [])
            ]
            q_copy = dict(q)
            q_copy["atomic_gold_facts"] = gold_facts
            out.append(TestCase(**q_copy))
    return out, excluded_unverified


def _resolve_scope(kg_id: UUID, doc_ids: list[str]) -> tuple[list[UUID], set[str]]:
    """解析指定文件範圍"""
    kg_folder = Path(settings.workspace_dir) / str(kg_id)
    uuids, sources = [], set()
    for entry in doc_ids:
        folder = kg_folder / entry
        rec = document_record_service.read_record(folder) if folder.is_dir() else None
        source = rec.source if rec is not None else entry
        uuids.append(document_record_service.document_uuid(source))
        sources.add(source)
        sources.add(entry)
    return uuids, sources


def _load_scoped_baseline_index(kg_id: UUID, chunk_size: int, sources: set[str]):
    import numpy as np

    vectors, meta = baseline_rag_service.load_baseline_index(kg_id, chunk_size)
    keep = [i for i, m in enumerate(meta) if m.get("source") in sources]
    if not keep:
        raise SystemExit(f"baseline 索引（cs{chunk_size}）未涵蓋目標文件。")
    return np.asarray([vectors[i] for i in keep], dtype=np.float32), [meta[i] for i in keep]


async def _drain_chat(payload: ChatRequest) -> dict:
    resp = await agent.chat(payload)
    answer, sources, grounding, regenerated, error = [], None, None, None, None
    async for chunk in resp.body_iterator:
        if chunk.startswith("event: error"):
            error = json.loads(chunk.split("\n", 1)[1][len("data: "):]).get("message")
        elif chunk.startswith("event: sources"):
            sources = json.loads(chunk.split("\n", 1)[1][len("data: "):])
        elif chunk.startswith("event: grounding"):
            grounding = json.loads(chunk.split("\n", 1)[1][len("data: "):])
        elif chunk.startswith("event: status"):
            st = json.loads(chunk.split("\n", 1)[1][len("data: "):])
            if st.get("phase") == "done":
                regenerated = st.get("regenerated")
        elif chunk.startswith("data: "):
            answer.append(json.loads(chunk[len("data: "):]).get("token", ""))
    return {
        "answer": "".join(answer),
        "error": error,
        "regenerated": regenerated,
        "triples": (sources or {}).get("triples", []),
        "facts": (sources or {}).get("facts", []),
        "grounding": grounding or [],
    }


async def _run_single_query(
    tc: TestCase,
    arm: str,
    kg_id: UUID,
    scope_uuids: list[UUID],
    cfg,
    counting: _CountingLLM,
    baseline_index,
    reranker,
    baseline_top_k: int,
) -> dict:
    counting.reset()
    t0 = time.perf_counter()

    raw_arm = ARM_ALIAS_MAP.get(arm, arm)
    tracker = LineageTracker(tc.id, arm, tc.question)
    gold_spans = [f.exact_span for f in tc.atomic_gold_facts]

    context_lines = []
    retrieved_texts = []
    chunk_ids = []
    fact_ids = []

    if raw_arm == "D":
        r = await _drain_chat(ChatRequest(question=tc.question, kg_id=kg_id, use_svo=False))
    elif raw_arm in ("B0", "B1"):
        vectors, meta = baseline_index
        emb = get_embedding_provider()
        q_vec = await emb.encode(tc.question)
        hits = baseline_rag_service.search_baseline(
            tc.question, q_vec, vectors, meta,
            top_k=baseline_top_k, hybrid=(raw_arm == "B1"),
            reranker=reranker if raw_arm == "B1" else None,
        )
        context_lines = baseline_rag_service.build_context_lines(hits)
        retrieved_texts = [h.get("text", "") for h in hits]
        chunk_ids = [f"{h.get('source')}_{h.get('chunk_index')}" for h in hits]

        gen = None
        async for item in agent._generate_from_context_lines(
            tc.question, history=None, cfg=cfg,
            llm_provider=counting, judge_llm_provider=counting,
            kg_id=kg_id, use_svo=True, context_lines=context_lines,
        ):
            if isinstance(item, agent._GenerationResult):
                gen = item
        r = {
            "answer": gen.final_answer if gen else "",
            "error": None,
            "regenerated": gen.regenerated if gen else None,
            "triples": [],
            "facts": [],
            "grounding": [
                {"statement": c.statement, "is_claim": c.is_claim, "supported": c.supported}
                for c in (gen.grounding if gen else [])
            ],
        }
    else:  # F / G / K / K-2b
        mode = {"F": "fact_only", "G": "bfs_only", "K": "both", "K-2b": "both"}.get(raw_arm, "both")
        r = await _drain_chat(ChatRequest(
            question=tc.question, kg_id=kg_id, use_svo=True,
            retrieval_mode=mode, disable_grounding_regen=(raw_arm == "K-2b"),
            scope_doc_ids=scope_uuids,
        ))
        retrieved_texts = [t.get("natural_text", "") for t in r["triples"]] + [f.get("fact_text", "") for f in r["facts"]]
        chunk_ids = [t.get("source_doc_id", "") for t in r["triples"]]
        fact_ids = [f.get("fact_id", "") for f in r["facts"]]
        context_lines = retrieved_texts

    latency_s = round(time.perf_counter() - t0, 2)
    answer = r["answer"]

    # 階段一血統
    tracker.record_retrieval(retrieved_texts, gold_spans, latency_ms=latency_s * 1000, chunk_ids=chunk_ids, fact_ids=fact_ids)
    # 階段二血統
    full_context_str = "\n".join(context_lines)
    tracker.record_context_assembly(full_context_str, gold_spans, total_tokens=len(full_context_str) // 4)
    # 階段三血統
    tracker.record_generation(
        raw_draft=answer,
        final_output=answer,
        grounding_passed=all(c.get("supported", False) for c in r["grounding"] if c.get("is_claim")),
        latency_ms=latency_s * 1000,
        regenerated=bool(r["regenerated"]),
    )

    # 執行確定性原子事實評分
    refusal_exp = (tc.scenario_type == "Type-E")
    atomic_eval = AtomicScorer.evaluate(answer, tc.atomic_gold_facts, refusal_expected=refusal_exp)

    full_lineage = tracker.build_full_lineage(gold_spans)

    return {
        "question_id": tc.id,
        "arm": arm,
        "raw_arm": raw_arm,
        "scenario_type": tc.scenario_type.value,
        "answer": answer,
        "error": r["error"],
        "latency_s": latency_s,
        "llm_calls": counting.calls,
        "estimated_tokens": len(full_context_str) // 4 + len(answer) // 4,
        "atomic_score": atomic_eval.model_dump(),
        "lineage": full_lineage.model_dump(),
        "failure_attribution": full_lineage.failure_attribution,
    }


def _render_pareto_summary(
    out_dir: Path,
    manifest: dict,
    records: list[dict],
    arms: list[str],
    test_cases: list[TestCase],
) -> None:
    """生成包含三階段生命週期成本與原子事實準確率的 Pareto 評估報告"""
    q_map = {tc.id: tc for tc in test_cases}
    by_arm_qid = {}
    for r in records:
        by_arm_qid.setdefault((r["arm"], r["question_id"]), []).append(r)

    summary_lines = [
        "# RQ1 統一評測報告：Pareto 最優邊界與全生命週期成本矩陣",
        "",
        f"> 生成時間：{datetime.now(timezone.utc).isoformat()}",
        f"> 基準圖譜：`{manifest.get('kg_id')}` | 評測題數：{len(test_cases)} 題 | 每題重複：{manifest.get('runs', 3)} 次",
        "",
        "## 1. 核心四大代表方法 Pareto 表現矩陣",
        "",
        "| 方法代號 | 代表架構 | 原子事實正確率 (Acc) | 必要事實召回率 (Rec) | 服務期 p50 延遲 (s) | 建庫膨脹比 | 千次查詢預估 (USD) |",
        "|---|---|---|---|---|---|---|",
    ]

    for arm in arms:
        arm_recs = [r for r in records if r["arm"] == arm]
        if not arm_recs:
            continue
        acc = statistics.mean([r["atomic_score"]["atomic_accuracy"] for r in arm_recs])
        rec = statistics.mean([r["atomic_score"]["atomic_recall"] for r in arm_recs])
        latencies_ms = [r["latency_s"] * 1000 for r in arm_recs]
        tokens = [r.get("estimated_tokens", 500) for r in arm_recs]

        serving_cost = CostAnalyzer.compute_serving_cost(arm, latencies_ms, tokens)
        profile = CostAnalyzer.get_baseline_profile(arm)

        summary_lines.append(
            f"| **{arm}** | {arm_recs[0]['raw_arm']} | {acc*100:.1f}% | {rec*100:.1f}% | "
            f"{serving_cost.latency_p50_ms/1000:.2f}s | {profile.build_cost.storage_multiplier}x | "
            f"${serving_cost.estimated_cost_per_1k_queries_usd:.4f} |"
        )

    summary_lines.extend([
        "",
        "## 2. 場景梯度細分（Type-A ~ Type-E）表現",
        "",
        "| 題號 | 場景分類 | " + " | ".join(arms) + " |",
        "|---|---| " + " | ".join(["---"] * len(arms)) + " |",
    ])

    for tc in test_cases:
        row = [f"**{tc.id}**", f"`{tc.scenario_type.value}`"]
        for arm in arms:
            recs = by_arm_qid.get((arm, tc.id), [])
            if not recs:
                row.append("—")
                continue
            acc = statistics.mean([r["atomic_score"]["atomic_accuracy"] for r in recs])
            perfect = sum(1 for r in recs if r["atomic_score"]["is_perfect"])
            row.append(f"{acc*100:.0f}% ({perfect}/{len(recs)}✓)")
        summary_lines.append("| " + " | ".join(row) + " |")

    summary_lines.extend([
        "",
        "## 3. 典型缺陷全鏈路血統歸因",
        "",
        "| 題號 | 方法 | 錯誤診斷 | 歸因原因 |",
        "|---|---|---|---|",
    ])

    for r in records:
        if not r["atomic_score"]["is_perfect"] and "Success" not in r["failure_attribution"]:
            summary_lines.append(
                f"| {r['question_id']} | {r['arm']} | 瑕疵 | {r['failure_attribution']} |"
            )

    out_file = out_dir / "summary.md"
    out_file.write_text("\n".join(summary_lines), encoding="utf-8")
    print(f"✅ Summary report generated at {out_file}")


def _git_hash() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            cwd=REPO_ROOT, check=True,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


async def _main() -> int:
    parser = argparse.ArgumentParser(description="RQ1 統一標準化評測 Harness")
    parser.add_argument("--kg-id", default="236903cf-055a-40a8-8923-b9d06601f3b7")
    parser.add_argument("--doc-ids", default="D0080015_警察人員特別休假辦法,F0040034_員工接受召集請假期間薪資費用加成減除辦法,N0030006_勞工請假規則,N0030018_育嬰留職停薪實施辦法,N0050030_災區受災勞工保險與勞工職業災害保險及就業保險被保險人保險費支應及傷病給付辦法,N0090051_受聘僱從事就業服務法第四十六條第一項第八款至第十款規定工作之外國人請假返國辦法")
    parser.add_argument("--questions", default=str(DEFAULT_TEST_CASES_PATH))
    parser.add_argument("--arms", default="M1,M2,M3,M4")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--chunk-size", type=int, default=500)
    parser.add_argument("--complexity", default="all")
    parser.add_argument("--baseline-top-k", type=int, default=5)
    parser.add_argument(
        "--reranker", default=None,
        help="B1(M2) 選配 cross-encoder 模型名（sentence_transformers.CrossEncoder）；預設關",
    )
    parser.add_argument(
        "--include-unverified", action="store_true",
        help="⚠️ 停用報告47 §5 任務A的 eligibility filter，納入 unverified 題目——"
        "僅供除錯用途，不得用於正式評測結論。",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只解析題組／文件／arm 並印計畫，不連線資料庫、不呼叫任何 LLM。",
    )
    parser.add_argument("--out", default="rq1_eval_results")

    args = parser.parse_args()
    kg_uuid = UUID(args.kg_id)
    doc_id_list = [d.strip() for d in args.doc_ids.split(",") if d.strip()]
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]

    test_cases, excluded_unverified = _load_questions(
        args.questions, args.complexity, include_unverified=args.include_unverified
    )
    if not test_cases:
        raise SystemExit("題組為空（檢查 --questions／--complexity／eligibility filter）")
    if args.include_unverified:
        print(
            f"⚠️ --include-unverified 已停用 eligibility filter：納入全部 {len(test_cases)} 題"
            "（含 unverified）。此結果不得作為正式評測結論。"
        )
    else:
        print(
            f"Loaded {len(test_cases)} eligible (verified) test cases; "
            f"excluded {excluded_unverified} unverified per 報告47 §5 任務A前置條件。"
        )

    scope_uuids, sources = _resolve_scope(kg_uuid, doc_id_list)

    out_dir = Path(args.out)

    plan = (
        f"KG {kg_uuid}｜arms {arms}｜{len(test_cases)} 題 × {args.runs} run "
        f"= {len(test_cases) * len(arms) * args.runs} 次呼叫\n"
        f"文件範圍 {len(doc_id_list)} 份｜chunk_size {args.chunk_size}｜complexity {args.complexity}\n"
        f"題號：{[tc.id for tc in test_cases]}\n輸出：{out_dir}"
    )
    print(plan)
    if args.dry_run:
        return 0

    init_providers()
    await connect()

    manifest = {
        "report": "47",
        "git_hash": _git_hash(),
        "kg_id": str(kg_uuid),
        "arms": arms,
        "runs": args.runs,
        "chunk_size": args.chunk_size,
        "complexity": args.complexity,
        "doc_ids": doc_id_list,
        "scope_doc_ids": [str(u) for u in scope_uuids],
        "questions_file": str(args.questions),
        "question_ids": [tc.id for tc in test_cases],
        "questions_count": len(test_cases),
        "excluded_unverified_count": excluded_unverified,
        "include_unverified": args.include_unverified,
        "baseline_top_k": args.baseline_top_k,
        "reranker": args.reranker,
        "embedding": {
            "provider": settings.embedding_provider,
            "model": getattr(settings, "ollama_embedding_model", None)
            or getattr(settings, "local_embedding_model", None),
        },
        "llm_model": getattr(settings, "ollama_llm_model", None),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        domain_pack = None
        try:
            kg_meta = await KGRepository(get_driver()).get(kg_uuid)
            domain_pack = kg_meta.domain_pack if kg_meta else None
        except Exception:  # noqa: BLE001
            pass
        cfg = ConfigLoader([FileConfigSource(settings.kg_config_dir)]).load(kg_uuid, domain_pack=domain_pack)

        baseline_index = None
        if {"M1", "M2", "B0", "B1"} & set(arms):
            baseline_index = _load_scoped_baseline_index(kg_uuid, args.chunk_size, sources)

        reranker = None
        if args.reranker and ({"M2", "B1"} & set(arms)):
            from sentence_transformers import CrossEncoder

            reranker = CrossEncoder(args.reranker)

        counting = _CountingLLM(get_llm_provider())
        _orig_llm, _orig_judge = agent.get_llm_provider, agent.get_judge_llm_provider
        agent.get_llm_provider = lambda: counting
        agent.get_judge_llm_provider = lambda _fb: counting

        all_records: list[dict] = []
        try:
            for run_i in range(1, args.runs + 1):
                run_records = []
                for tc in test_cases:
                    for arm in arms:
                        print(f"  [run {run_i}/{args.runs}] {tc.id} · {arm} …", flush=True)
                        try:
                            rec = await _run_single_query(
                                tc, arm, kg_uuid, scope_uuids, cfg,
                                counting, baseline_index, reranker, args.baseline_top_k,
                            )
                        except Exception as exc:  # noqa: BLE001 - 單格失敗不中斷整批
                            rec = {
                                "question_id": tc.id, "arm": arm, "raw_arm": ARM_ALIAS_MAP.get(arm, arm),
                                "scenario_type": tc.scenario_type.value,
                                "answer": "", "error": f"{type(exc).__name__}: {exc}",
                                "latency_s": None, "llm_calls": None, "estimated_tokens": 0,
                                "atomic_score": {"atomic_accuracy": 0.0, "atomic_recall": 0.0, "is_perfect": False},
                                "lineage": None,
                                "failure_attribution": f"Harness error: {type(exc).__name__}",
                            }
                        rec["run"] = run_i
                        run_records.append(rec)
                        all_records.append(rec)
                (out_dir / f"run{run_i}.json").write_text(
                    json.dumps(run_records, ensure_ascii=False, indent=2), encoding="utf-8"
                )
        finally:
            agent.get_llm_provider, agent.get_judge_llm_provider = _orig_llm, _orig_judge
    finally:
        await disconnect()

    _render_pareto_summary(out_dir, manifest, all_records, arms, test_cases)
    print(f"\n完成：{len(all_records)} 筆 → {out_dir}/（run*.json + summary.md + manifest.json）")
    return 0


def main() -> int:
    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())
