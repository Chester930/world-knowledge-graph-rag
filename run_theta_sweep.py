# -*- coding: utf-8 -*-
"""報告27 §6.2 待辦2 + 報告32 §9 —— θ 敏感度 sweep（DRAIN-DONE 後跑）。

網格（報告27 §6.2）：
  θ_deg  = routers.agent._SEED_MAX_DEGREE       ∈ {100, 200, 400}
  θ_hop  = services.svo_service._BFS_EXPAND_WHEN_BELOW ∈ {5, 8, 12}
  per_seed = routers.agent._BFS_PER_SEED_LIMIT   ∈ {30, 60, 100}
  L2 k   = services.svo_service._BFS_PRIZE_TOP_K  ∈ {5, 10, 20}   （報告32 §9 L2，僅在 L2 接線後才有意義）

量測（每 config × 每題 ×N_RUNS）：延遲、BFS 三元組數、命中 watch 字串（正確性 proxy）。
目標對照（報告27 §6.2）：Q7 延遲 < 90s、Q6 BFS 三元組 < 30，且 Q1..Q8 正確性無回歸。

⚠️ 尚未可跑（DRAIN-DONE + Neo4j 在線）。預設只掃「一次動一軸、其餘留現行值」的
   3+3+3 = 9 個 config（full 笛卡爾 81 個太貴）；--full 開全網格。
   L2 k 軸預設跳過（L2 未接線）；--with-l2 且 chat() 已接 L2 時才掃。

現行值基準：θ_deg=100, θ_hop=8, per_seed=30, k=10（報告27 §7.1 / 報告32 §9 §7.2）。
"""
from __future__ import annotations
import argparse, asyncio, itertools, json, sys, os, time, traceback
from datetime import datetime
from uuid import UUID

REPO = r"D:\Users\666\Desktop\world knowledge graph rag"
sys.path.insert(0, REPO)
os.chdir(r"D:\Users\666\Desktop\kg-runtime")
from core.database import connect, disconnect, get_driver   # noqa: E402
from core.providers.factory import init_providers           # noqa: E402
from models.document import ChatRequest                     # noqa: E402
from routers.agent import chat                              # noqa: E402
import routers.agent as _agent                              # noqa: E402
import services.svo_service as _svo                          # noqa: E402

OUT = r"C:\Users\666\.claude\jobs\1b4f3bb5\tmp\theta_sweep_output.txt"
KG4 = UUID("236903cf-055a-40a8-8923-b9d06601f3b7")
N_RUNS = 2

BASE = {"theta_deg": 100, "theta_hop": 8, "per_seed": 30, "k": 10}
AXES = {
    "theta_deg": [100, 200, 400],
    "theta_hop": [5, 8, 12],
    "per_seed": [30, 60, 100],
    "k": [5, 10, 20],
}

# 報告27 §6.2 的 8 題子集（延遲/三元組數最吃緊的幾題 + 一個正確性錨點）。
# watch = 命中即視為「正確性未回歸」的 proxy 字串。
QS = [
    ("Q6", "母性健康保護期間 + 血中鉛第三級 + 紀錄保存年限？", ["分娩後一年", "第三級", "三年", "3年"]),
    ("Q7", "高溫作業勞工的特殊健康檢查依規定多久做一次？", ["未明確", "無法確認", "未規定"]),  # 誠實拒答
    ("Q5", "災區受災勞工保險費支應幾個月？起算日？", ["六個月", "6個月"]),
    ("Q1", "高架作業高度 2–5 公尺、5–20 公尺、20 公尺以上，各應給多少休息？", ["二十分鐘", "二十五分鐘", "三十五分鐘"]),
]


def w(m: str = "") -> None:
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(m + "\n")
    print(m, flush=True)


async def one_call(q: str) -> dict:
    t0 = time.monotonic()
    resp = await chat(ChatRequest(question=q, use_svo=True, kg_id=KG4))
    ans, sources = "", None
    ev = None
    async for chunk in resp.body_iterator:
        txt = chunk if isinstance(chunk, str) else chunk.decode("utf-8")
        for line in txt.split("\n"):
            if line == "":
                ev = None; continue
            if line.startswith("event:"):
                ev = line[7:].strip(); continue
            if line.startswith("data:"):
                raw = line[5:].strip()
                if not raw:
                    continue
                d = json.loads(raw)
                if ev == "sources":
                    sources = d
                elif ev is None and "token" in d:
                    ans = d["token"]
    return {"answer": ans, "elapsed": round(time.monotonic() - t0, 1),
            "n_triples": len(sources["triples"]) if sources else 0}


def apply_cfg(cfg: dict) -> None:
    _agent._SEED_MAX_DEGREE = cfg["theta_deg"]
    _agent._BFS_PER_SEED_LIMIT = cfg["per_seed"]
    _svo._BFS_EXPAND_WHEN_BELOW = cfg["theta_hop"]
    _svo._BFS_PRIZE_TOP_K = cfg["k"]


def configs(full: bool, with_l2: bool):
    axes = dict(AXES)
    if not with_l2:
        axes.pop("k")
    if full:
        keys = list(axes)
        for combo in itertools.product(*(axes[k] for k in keys)):
            cfg = dict(BASE); cfg.update(dict(zip(keys, combo)))
            yield cfg
    else:
        yield dict(BASE)  # 基準
        for ax, vals in axes.items():
            for v in vals:
                if v == BASE[ax]:
                    continue
                cfg = dict(BASE); cfg[ax] = v
                yield cfg


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--with-l2", action="store_true")
    args = ap.parse_args()

    w(f"\n\n########## THETA-SWEEP START {datetime.now().isoformat(timespec='seconds')} "
      f"full={args.full} with_l2={args.with_l2} ##########")
    await connect(); init_providers(); get_driver()

    for cfg in configs(args.full, args.with_l2):
        apply_cfg(cfg)
        tag = f"deg={cfg['theta_deg']} hop={cfg['theta_hop']} per={cfg['per_seed']} k={cfg['k']}"
        w(f"\n{'='*90}\n# CONFIG {tag}\n{'='*90}")
        for qid, q, watch in QS:
            lats, tris, hits = [], [], []
            for _ in range(N_RUNS):
                try:
                    r = await one_call(q)
                    lats.append(r["elapsed"]); tris.append(r["n_triples"])
                    hits.append(any(x in r["answer"] for x in watch))
                except Exception as e:
                    w(f"  {qid} !! {e!r}\n{traceback.format_exc()}")
                    lats.append(-1); tris.append(-1); hits.append(False)
            w(f"  {qid}: 延遲 {lats} 三元組 {tris} 命中 {sum(hits)}/{N_RUNS}")
    w(f"\nTHETA-SWEEP-DONE {datetime.now().isoformat(timespec='seconds')}")
    await disconnect()


asyncio.run(main())
