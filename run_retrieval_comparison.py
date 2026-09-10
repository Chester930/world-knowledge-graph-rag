"""報告39：七路檢索比較標準化測試 harness（SDD-4 交付物）。

對同一題組，把 7 條檢索 arm（D／B0／B1／F／G／K／K−2b，見報告39 §1）各跑
`--runs` 次，收集可比的原始輸出與統計，供使用者依 §4／§4.1 人工評分後產出
比較報告（報告 40）。**本腳本只跑 harness，不下任何結論。**

核心不變量（§5.4.1）：B0/B1/F/G/K/K−2b 只差餵進去的 context，生成端共用
`routers/agent.py::_generate_from_context_lines()`（SDD-3）。

    D    ChatRequest(use_svo=False)                     — 不檢索
    B0   baseline_rag_service.search_baseline(hybrid=0) → _generate_from_context_lines(context_lines=)
    B1   baseline_rag_service.search_baseline(hybrid=1[,reranker]) → 同上
    F    ChatRequest(use_svo=1, retrieval_mode="fact_only", scope_doc_ids=)
    G    ChatRequest(use_svo=1, retrieval_mode="bfs_only",  scope_doc_ids=)
    K    ChatRequest(use_svo=1, retrieval_mode="both",      scope_doc_ids=)
    K-2b 同 K ＋ disable_grounding_regen=True

用法：

    python run_retrieval_comparison.py \\
        --kg-id 236903cf-055a-40a8-8923-b9d06601f3b7 \\
        --doc-ids N0030006_勞工請假規則,N0030018_...,... \\
        --questions docs/附錄A題庫.json \\
        --arms D,B0,B1,F,G,K,K-2b --runs 3 --chunk-size 500 \\
        --complexity all --out report39_comparison/<自訂>

前置：`python check_comparison_readiness.py ...` 全 PASS（尤其 §2.4 抽取新鮮度、
baseline `.npy` 已建）。環境見報告39 §7（Neo4j 容器、WSL2 Ollama、
OLLAMA_EMBEDDING_NUM_GPU=0）。

⚠️ `qwen2.5:7b` 非決定性 → 要下「A > B」結論的比較該 arm 至少 --runs 3
（報告39 §4.1）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

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
from repositories.kg_repo import KGRepository
from routers import agent
from services import baseline_rag_service, document_record_service

try:
    from build_baseline_chunk_index import _read_original
except ImportError:  # pragma: no cover
    _read_original = None  # type: ignore[assignment]

ALL_ARMS = ["D", "B0", "B1", "F", "G", "K", "K-2b"]
_DEFAULT_QUESTIONS = "docs/附錄A題庫.json"
_BASELINE_TOP_K = 5


# ── LLM 呼叫計數（llm_calls 統計）────────────────────────────────────

class _CountingLLM:
    """包住真實 LLM provider，數 `stream()`／`generate_json()` 呼叫次數。
    judge 也走同一個包裝 → `llm_calls` 含核對呼叫（前導夠用；報告 40 若要
    分開再拆）。"""

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


# ── 題組載入 ────────────────────────────────────────────────────────

def _load_questions(spec: str, complexity: str) -> list[dict]:
    path = Path(spec)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        qs = data["questions"] if isinstance(data, dict) else data
        selected_ids = None
    else:
        selected_ids = {s.strip() for s in spec.split(",") if s.strip()}
        default = json.loads(Path(_DEFAULT_QUESTIONS).read_text(encoding="utf-8"))
        qs = default["questions"]
    out = []
    for q in qs:
        if selected_ids is not None and q["id"] not in selected_ids:
            continue
        if complexity != "all" and q.get("complexity_bucket") != complexity:
            continue
        out.append(q)
    return out


# ── 文件範圍解析 ────────────────────────────────────────────────────

def _resolve_scope(kg_id: UUID, doc_ids: list[str]) -> tuple[list[UUID], set[str]]:
    """回傳 (scope_doc_ids UUID 清單, 這些文件的 source 字串集合)。"""
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


# ── baseline 索引（B0/B1）───────────────────────────────────────────

def _load_scoped_baseline_index(kg_id: UUID, chunk_size: int, sources: set[str]):
    import numpy as np

    vectors, meta = baseline_rag_service.load_baseline_index(kg_id, chunk_size)
    keep = [i for i, m in enumerate(meta) if m.get("source") in sources]
    if not keep:
        raise SystemExit(
            f"baseline 索引（cs{chunk_size}）沒有涵蓋 --doc-ids 任何文件；"
            f"先跑 python build_baseline_chunk_index.py {kg_id} --chunk-size {chunk_size}"
        )
    return np.asarray([vectors[i] for i in keep], dtype=np.float32), [meta[i] for i in keep]


# ── SSE 解析（走 chat() 的 arm）─────────────────────────────────────

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
        "answer": "".join(answer), "error": error, "regenerated": regenerated,
        "triples": (sources or {}).get("triples", []),
        "facts": (sources or {}).get("facts", []),
        "resolved_rel_type": (sources or {}).get("resolved_rel_type"),
        "grounding": grounding or [],
    }


def _grounding_stats(grounding: list[dict], regenerated) -> dict:
    claims = [c for c in grounding if c.get("is_claim")]
    return {
        "n_sentences": len(grounding),
        "n_claims": len(claims),
        "n_unsupported": sum(1 for c in grounding if not c.get("supported")),
        "n_claim_unsupported": sum(1 for c in claims if not c.get("supported")),
        "regenerated": regenerated,
    }


# ── 單一 (題 × arm × run) ──────────────────────────────────────────

async def _run_one(
    q: dict, arm: str, kg_id: UUID, scope_uuids: list[UUID],
    cfg, counting: _CountingLLM, baseline_index, reranker, baseline_top_k: int,
) -> dict:
    counting.reset()
    t0 = time.perf_counter()

    if arm == "D":
        r = await _drain_chat(ChatRequest(question=q["question"], kg_id=kg_id, use_svo=False))
        passages = []
    elif arm in ("B0", "B1"):
        vectors, meta = baseline_index
        emb = get_embedding_provider()
        q_vec = await emb.encode(q["question"])
        hits = baseline_rag_service.search_baseline(
            q["question"], q_vec, vectors, meta,
            top_k=baseline_top_k, hybrid=(arm == "B1"),
            reranker=reranker if arm == "B1" else None,
        )
        ctx = baseline_rag_service.build_context_lines(hits)
        gen = None
        async for item in agent._generate_from_context_lines(
            q["question"], history=None, cfg=cfg,
            llm_provider=counting, judge_llm_provider=counting,
            kg_id=kg_id, use_svo=True, context_lines=ctx,
        ):
            if isinstance(item, agent._GenerationResult):
                gen = item
        grounding = [
            {"statement": c.statement, "is_claim": c.is_claim,
             "supported": c.supported, "reason": c.reason}
            for c in (gen.grounding if gen else [])
        ]
        r = {"answer": gen.final_answer if gen else "", "error": None,
             "regenerated": gen.regenerated if gen else None,
             "triples": [], "facts": [], "resolved_rel_type": None, "grounding": grounding}
        passages = hits
    else:  # F / G / K / K-2b
        mode = {"F": "fact_only", "G": "bfs_only", "K": "both", "K-2b": "both"}[arm]
        r = await _drain_chat(ChatRequest(
            question=q["question"], kg_id=kg_id, use_svo=True,
            retrieval_mode=mode, disable_grounding_regen=(arm == "K-2b"),
            scope_doc_ids=scope_uuids,
        ))
        passages = {"triples": r["triples"], "facts": r["facts"]}

    latency = round(time.perf_counter() - t0, 2)
    return {
        "question_id": q["id"], "arm": arm,
        "answer": r["answer"], "error": r["error"],
        "latency_s": latency, "llm_calls": counting.calls,
        "bfs_triple_count": len(r["triples"]),
        "semantic_fact_count": len(r["facts"]),
        "retrieved_passages": passages,
        "grounding_stats": _grounding_stats(r["grounding"], r["regenerated"]),
        "human_score": None,  # 0/1/2 grounded，使用者人工填
    }


# ── 彙總 ────────────────────────────────────────────────────────────

def _mean_var(xs: list[float]) -> tuple[float, float]:
    xs = [x for x in xs if x is not None]
    if not xs:
        return (0.0, 0.0)
    return (round(statistics.mean(xs), 2),
            round(statistics.pvariance(xs), 3) if len(xs) > 1 else 0.0)


def _write_summary(out_dir: Path, manifest: dict, records: list[dict], arms: list[str], qids: list[str]) -> None:
    by = {}
    for rec in records:
        by.setdefault((rec["question_id"], rec["arm"]), []).append(rec)

    lines = ["# 報告39 七路檢索比較 — 彙總（前導）", "",
             "> 本表由 `run_retrieval_comparison.py` 產生，**人工評分欄留空**。",
             "> 依報告39 §4／§4.1 填 0/1/2 grounded 後產出報告 40。", ""]
    lines += ["## 追溯資訊", "", "```json", json.dumps(manifest, ensure_ascii=False, indent=2), "```", ""]
    lines += ["## 題 × arm 矩陣（latency 秒 mean±var／llm_calls mean／檢索量 mean）", ""]
    header = "| 題號 | " + " | ".join(arms) + " |"
    lines += [header, "|" + "---|" * (len(arms) + 1)]
    for qid in qids:
        cells = [qid]
        for arm in arms:
            recs = by.get((qid, arm), [])
            if not recs:
                cells.append("—"); continue
            lm, lv = _mean_var([r["latency_s"] for r in recs])
            cm, _ = _mean_var([float(r["llm_calls"]) for r in recs])
            retr = _mean_var([float(r["bfs_triple_count"] + r["semantic_fact_count"]
                                    + (len(r["retrieved_passages"]) if isinstance(r["retrieved_passages"], list) else 0))
                              for r in recs])[0]
            errs = sum(1 for r in recs if r["error"])
            cells.append(f"{lm}±{lv}／{cm}／{retr}" + (f" ⚠{errs}err" if errs else ""))
        lines.append("| " + " | ".join(cells) + " |")

    lines += ["", "## 人工評分表（0=無依據／1=部分接地／2=完整接地，逐 run 填）", "",
              "| 題號 | arm | run | 人工分 | 備註 |", "|---|---|---|---|---|"]
    for qid in qids:
        for arm in arms:
            for i, _rec in enumerate(by.get((qid, arm), []), start=1):
                lines.append(f"| {qid} | {arm} | {i} |  |  |")

    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _git_hash() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              cwd=Path(__file__).parent, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


async def _main() -> int:
    ap = argparse.ArgumentParser(description="報告39 七路檢索比較 harness")
    ap.add_argument("--kg-id", required=True, type=UUID)
    ap.add_argument("--doc-ids", required=True, help="workspace/<kg_id>/ 底下的資料夾名，逗號分隔")
    ap.add_argument("--questions", default=_DEFAULT_QUESTIONS,
                    help="題庫 JSON 路徑，或逗號分隔的題號清單（預設 docs/附錄A題庫.json）")
    ap.add_argument("--arms", default=",".join(ALL_ARMS))
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--chunk-size", type=int, default=500)
    ap.add_argument("--complexity", choices=["single", "multi", "all"], default="all")
    ap.add_argument("--baseline-top-k", type=int, default=_BASELINE_TOP_K)
    ap.add_argument("--reranker", default=None,
                    help="B1 選配 cross-encoder 模型名（sentence_transformers.CrossEncoder）；預設關")
    ap.add_argument("--out", default=None, help="輸出目錄（預設 report39_comparison/<timestamp>）")
    ap.add_argument("--dry-run", action="store_true", help="只解析題組／文件／arm 並印計畫，不連線、不呼叫模型")
    args = ap.parse_args()

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    bad = [a for a in arms if a not in ALL_ARMS]
    if bad:
        raise SystemExit(f"未知 arm：{bad}；可用：{ALL_ARMS}")
    doc_ids = [d.strip() for d in args.doc_ids.split(",") if d.strip()]
    questions = _load_questions(args.questions, args.complexity)
    if not questions:
        raise SystemExit("題組為空（檢查 --questions／--complexity）")
    scope_uuids, sources = _resolve_scope(args.kg_id, doc_ids)

    out_dir = Path(args.out) if args.out else Path("report39_comparison") / datetime.now().strftime("%Y%m%d_%H%M%S")

    plan = (f"KG {args.kg_id}｜arms {arms}｜{len(questions)} 題 × {args.runs} run "
            f"= {len(questions) * len(arms) * args.runs} 次呼叫\n"
            f"文件範圍 {len(doc_ids)} 份｜chunk_size {args.chunk_size}｜complexity {args.complexity}\n"
            f"題號：{[q['id'] for q in questions]}\n輸出：{out_dir}")
    print(plan)
    if args.dry_run:
        return 0

    init_providers()
    await connect()
    manifest = {
        "report": "39",
        "git_hash": _git_hash(),
        "kg_id": str(args.kg_id),
        "arms": arms, "runs": args.runs, "chunk_size": args.chunk_size,
        "complexity": args.complexity, "doc_ids": doc_ids,
        "scope_doc_ids": [str(u) for u in scope_uuids],
        "questions_file": args.questions,
        "question_ids": [q["id"] for q in questions],
        "baseline_top_k": args.baseline_top_k, "reranker": args.reranker,
        "embedding": {"provider": settings.embedding_provider,
                      "model": getattr(settings, "ollama_embedding_model", None) or getattr(settings, "local_embedding_model", None)},
        "llm_model": getattr(settings, "ollama_llm_model", None),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "generation_alignment": (
            "B0/B1/D 與 F/G/K/K-2b 共用 _generate_from_context_lines()（SDD-3）；"
            "baseline arm 走單次強約束重生，不套 2b 定向修訂／分解式重生／G3 列舉 guard"
            "（前導夠用版，見報告39 §3.2、§6）。llm_calls 含核對呼叫。"
        ),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # cfg：與 K 走同一份 per-KG 設定（生成端 system_context 一致）
    domain_pack = None
    try:
        kg_meta = await KGRepository(get_driver()).get(args.kg_id)
        domain_pack = kg_meta.domain_pack if kg_meta else None
    except Exception:  # noqa: BLE001
        pass
    cfg = ConfigLoader([FileConfigSource(settings.kg_config_dir)]).load(args.kg_id, domain_pack=domain_pack)

    baseline_index = None
    if {"B0", "B1"} & set(arms):
        baseline_index = _load_scoped_baseline_index(args.kg_id, args.chunk_size, sources)

    reranker = None
    if args.reranker and "B1" in arms:
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
            for q in questions:
                for arm in arms:
                    print(f"  [run {run_i}/{args.runs}] {q['id']} · {arm} …", flush=True)
                    try:
                        rec = await _run_one(q, arm, args.kg_id, scope_uuids, cfg,
                                             counting, baseline_index, reranker, args.baseline_top_k)
                    except Exception as exc:  # noqa: BLE001 - 單格失敗不中斷整批
                        rec = {"question_id": q["id"], "arm": arm, "answer": "", "error": f"{type(exc).__name__}: {exc}",
                               "latency_s": None, "llm_calls": None, "bfs_triple_count": 0,
                               "semantic_fact_count": 0, "retrieved_passages": [],
                               "grounding_stats": {}, "human_score": None}
                    rec["run"] = run_i
                    run_records.append(rec)
                    all_records.append(rec)
            (out_dir / f"run{run_i}.json").write_text(
                json.dumps(run_records, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        agent.get_llm_provider, agent.get_judge_llm_provider = _orig_llm, _orig_judge
        await disconnect()

    _write_summary(out_dir, manifest, all_records, arms, [q["id"] for q in questions])
    print(f"\n完成：{len(all_records)} 筆 → {out_dir}/（run*.json + summary.md + manifest.json）")
    print("下一步：人工填 summary.md 的 0/1/2 grounded 評分，依報告39 §4 產出報告 40。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
