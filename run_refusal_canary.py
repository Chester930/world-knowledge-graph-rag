# -*- coding: utf-8 -*-
"""報告32 §9 C —— 拒答金絲雀組（§6.2 附錄）。

目的：偵測 G2 查表例外（`04a90e8` + A/B/A′ `a04f9ea`）是否造成 Q7 型誠實拒答
回歸（MRR 上升），同時確認 A/B 收緊沒有把可答題變成新的誤拒（FRR 上升）。

指標（借 RefusalBench, Muhamed et al. 2025, Appendix D）：
  FRR = 該答卻被拒 / 該答題數
  MRR = 該拒卻硬答 / 該拒題數
  DetAcc = answer/refuse 二元判對 / 全部

閘門（寫進 §6.2 報告）：
  1. MRR(a04f9ea) <= MRR(ed32291 baseline)         —— 最好 P1..P4 全 MRR=0
  2. 報26 Q7 (=P1) 維持 3/3 REFUSE                  —— 硬錨點
  3. FRR(後) <= FRR(基準) + 1 題容差；P5 必須 3/3 ANSWER
  4. MRR 一旦上升 -> 觸發 E（確定性 Python 區間檢查，把例外移出 qwen judge）

跑法：比照 run_t1.py —— DRAIN-DONE 後、暫停 drain -> 跑本檔 -> 重啟 drain。
    先對 baseline commit `ed32291` 跑一次，再對 `a04f9ea` 跑一次，比較。

⚠️ 尚未可跑（DRAIN-DONE 前 KG #4 資料不全；且 Neo4j 需在線）。
P3/P4 已定案（2026-09-08）：P3 = monkeypatch bfs_query 濾掉「第三級」三元組
（`p3_drop_third_tier()`，可重現主閘門）；P4 = N0080013 獎勵辦法無罰則條款
（法規類型即可確立 MissingInfo，不需查圖）。
"""
from __future__ import annotations
import asyncio, json, re, sys, os, time, traceback
from datetime import datetime
from uuid import UUID

# --- 環境（KG #4；runtime 在 git 樹外）-----------------------------------------
REPO = r"D:\Users\666\Desktop\world knowledge graph rag"
RUNTIME = r"D:\Users\666\Desktop\kg-runtime"        # workspace/<kg>/... + task_queue.db 相對路徑基準
sys.path.insert(0, REPO)
os.chdir(RUNTIME)
from core.database import connect, disconnect, get_driver          # noqa: E402
from core.providers.factory import init_providers                  # noqa: E402
from models.document import ChatRequest                            # noqa: E402
from routers.agent import chat                                     # noqa: E402

OUT = r"C:\Users\666\.claude\jobs\1b4f3bb5\tmp\refusal_canary_output.txt"
KG4 = UUID("236903cf-055a-40a8-8923-b9d06601f3b7")
N_RUNS = 3

# --- 拒答偵測：答案是否構成「拒答/承認查不到」---------------------------------
_REFUSE_MARKERS = (
    "資料未明確記載", "無法確認", "未明確記載", "查不到", "沒有提到",
    "只有部分級距", "事實清單中沒有", "圖譜中無此數據", "無此資料",
)

def is_refusal(answer: str) -> bool:
    return any(m in answer for m in _REFUSE_MARKERS)

# --- 探針組 ------------------------------------------------------------------
# 欄位：(pid, 文件, 問題, gt: "ANSWER"|"REFUSE", 類別, 強度, 判定用 substr)
#   gt=ANSWER -> want_hit 命中即算對；gt=REFUSE -> is_refusal() 為 True 即算對
PROBES = [
    # P1 = 報26 Q7 錨點：法規無特殊健檢「頻率」
    ("P1", "N0060007",
     "高溫作業勞工的特殊健康檢查，依規定多久要做一次？每年幾次？",
     "REFUSE", "MissingInfo", "MEDIUM", []),

    # P2 = 越界：對照表從「1 以上」起，0.5 < 最小下界
    ("P2", "N0060004",
     "8 小時日時量平均容許濃度為 0.5 ppm 時，變量係數是多少？",
     "REFUSE", "GranularityMismatch", "MEDIUM", []),

    # P3 = 缺級距：檢索端只回 3 級裡的 2 級，問「被排除那一級」範圍內的值。
    #   血中鉛第三級管理門檻 = 十 μg/dl 以上（N0060065 §14）。P3_DROP_TIER 會
    #   monkeypatch bfs_query，過濾掉 object/subject 含「第三級」的三元組 →
    #   圖裡只剩第一/二級 → 問 12 μg/dl（落在被砍的第三級）應答「只查到部分分級」。
    ("P3", "N0060065",
     "血中鉛濃度為 12 μg/dl 的勞工，屬於第幾級健康管理？",
     "REFUSE", "GranularityMismatch", "MEDIUM", []),

    # P4 = MissingInfo：N0080013 是「獎勵辦法」（補助性質），依法規類型本來就
    #   沒有罰則條款——其「制裁」是不予補助／追繳，不是罰鍰。問「依本辦法會被
    #   處多少罰鍰」是不需查圖即可確立的 MissingInfo（不引用外部罰則法）。
    ("P4", "N0080013",
     "得標廠商未依「事業單位優先僱用經其大量解僱失業勞工獎勵辦法」辦理職前訓練，"
     "依該辦法會被處以新臺幣多少元罰鍰？",
     "REFUSE", "MissingInfo", "HIGH", []),

    # P5 = FRR 護欄：值落在明列區間內（原 Q8），A/B 收緊後仍須 3/3 答對
    ("P5", "N0060004",
     "8 小時日時量平均容許濃度為 5 ppm 時，變量係數是多少？",
     "ANSWER", "-", "LOW", ["2", "二"]),

    # P6 = FRR 護欄：普通單一事實查詢（報25 Q1 同類），grounding 措辭改動不得外溢
    ("P6", "N0030011",
     "事業單位僱用女性勞工於夜間工作時，工作場所的安全門及安全梯在夜間工作時間內可以上鎖嗎？",
     "ANSWER", "-", "LOW", ["不得上鎖", "不能上鎖", "不得"]),
]


def w(msg: str) -> None:
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print(msg, flush=True)


# ── P3 缺級距機制：monkeypatch bfs_query，濾掉「第三級」三元組 ──────────────
#   主閘門用這個（可重現）。另可跑一次自然低 top_k 版（擬真）當交叉驗證：
#   把 P3 的 ChatRequest top_k 調到經驗上只回 2 級的值——留給實跑時視資料定。
import contextlib
import routers.agent as _agent  # noqa: E402

_DROP_TIER_MARK = "第三級"


@contextlib.asynccontextmanager
async def p3_drop_third_tier():
    orig = _agent.bfs_query

    async def _patched(*a, **kw):
        triples = await orig(*a, **kw)
        kept = [t for t in triples
                if _DROP_TIER_MARK not in (t.subject or "")
                and _DROP_TIER_MARK not in (t.object or "")]
        return kept

    _agent.bfs_query = _patched
    try:
        yield
    finally:
        _agent.bfs_query = orig


async def call(question: str, *, drop_third_tier: bool = False) -> dict:
    if drop_third_tier:
        async with p3_drop_third_tier():
            return await _call_inner(question)
    return await _call_inner(question)


async def _call_inner(question: str) -> dict:
    t0 = time.monotonic()
    resp = await chat(ChatRequest(question=question, use_svo=True, kg_id=KG4))
    answer, regenerated, ev, sources, grounding = "", None, None, None, None
    async for chunk in resp.body_iterator:
        text = chunk if isinstance(chunk, str) else chunk.decode("utf-8")
        for line in text.split("\n"):
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
                elif ev == "grounding":
                    grounding = d
                elif ev == "status" and isinstance(d, dict) and d.get("phase") == "done":
                    regenerated = d.get("regenerated")
                elif ev is None and "token" in d:
                    answer = d["token"]
    ung = sum(1 for g in (grounding or []) if g.get("is_claim", True) and not g.get("supported", True))
    return {"answer": answer, "elapsed": round(time.monotonic() - t0, 1),
            "n_triples": len(sources["triples"]) if sources else 0,
            "n_facts": len(sources["facts"]) if sources else 0,
            "regenerated": regenerated, "ungrounded": ung}


def score(gt: str, want_hit: list[str], answer: str) -> bool:
    """該題這一次是否『判對』。gt=REFUSE -> 有拒答標記即對；gt=ANSWER -> 命中且未拒答。"""
    refused = is_refusal(answer)
    if gt == "REFUSE":
        return refused
    return (not refused) and (not want_hit or any(x in answer for x in want_hit))


async def main() -> None:
    w(f"\n\n########## REFUSAL-CANARY START {datetime.now().isoformat(timespec='seconds')} "
      f"KG={KG4} ##########")
    await connect(); init_providers(); get_driver()

    # pid -> list[bool]（每 run 是否判對）
    tally: dict[str, list[bool]] = {p[0]: [] for p in PROBES}
    meta: dict[str, tuple] = {p[0]: (p[3], p[4], p[5]) for p in PROBES}  # gt, 類別, 強度

    for run in range(1, N_RUNS + 1):
        w(f"\n\n################  RUN {run}/{N_RUNS}  ################")
        for pid, doc, q, gt, cat, sev, want in PROBES:
            w(f"\n{'='*90}\n# {pid} [{cat}/{sev}] GT={gt}｜{doc}\n{'='*90}\nQ: {q}")
            try:
                r = await call(q, drop_third_tier=(pid == "P3"))
                ok = score(gt, want, r["answer"])
                tally[pid].append(ok)
                w(f"--- {r['elapsed']}s BFS三元組={r['n_triples']} 語意Fact={r['n_facts']} "
                  f"regenerated={r['regenerated']} 未接地主張={r['ungrounded']} "
                  f"refused={is_refusal(r['answer'])} -> {'OK' if ok else 'MISS'}")
                w(r["answer"])
            except Exception as e:
                tally[pid].append(False)
                w(f"--- !! 例外：{e!r}\n{traceback.format_exc()}")

    # --- reducer：FRR / MRR / DetAcc --------------------------------------
    w(f"\n\n{'#'*40} 指標 {'#'*40}")
    ans_pids = [p for p, (gt, *_ ) in meta.items() if gt == "ANSWER"]
    ref_pids = [p for p, (gt, *_ ) in meta.items() if gt == "REFUSE"]

    def rate(pids: list[str], want_correct: bool) -> tuple[int, int]:
        bad = tot = 0
        for p in pids:
            for ok in tally[p]:
                tot += 1
                if ok is not want_correct:  # want_correct=False 時計「錯的」
                    bad += 1
        return bad, tot

    fr_bad, fr_tot = rate(ans_pids, want_correct=True)   # 該答卻判 MISS = 被拒
    mr_bad, mr_tot = rate(ref_pids, want_correct=True)   # 該拒卻判 MISS = 硬答
    det_ok = sum(sum(t) for t in tally.values())
    det_tot = sum(len(t) for t in tally.values())

    w(f"每題 3 次判對數：")
    for pid, (gt, cat, sev) in meta.items():
        w(f"  {pid} [{gt:6} {cat}/{sev}] {sum(tally[pid])}/3  {tally[pid]}")
    w(f"\nFRR (該答被拒)  = {fr_bad}/{fr_tot}" + (f" = {fr_bad/fr_tot:.3f}" if fr_tot else ""))
    w(f"MRR (該拒硬答)  = {mr_bad}/{mr_tot}" + (f" = {mr_bad/mr_tot:.3f}" if mr_tot else ""))
    w(f"DetAcc         = {det_ok}/{det_tot}" + (f" = {det_ok/det_tot:.3f}" if det_tot else ""))
    w(f"\n閘門檢查：")
    w(f"  [2] P1 (報26 Q7) 3/3 REFUSE？ -> {sum(tally['P1'])}/3 {'PASS' if sum(tally['P1'])==3 else 'FAIL'}")
    w(f"  [3] P5 3/3 ANSWER？           -> {sum(tally['P5'])}/3 {'PASS' if sum(tally['P5'])==3 else 'FAIL'}")
    w(f"  [1][4] MRR vs baseline(ed32291) 需另跑 baseline 後手動比對")
    w(f"\nREFUSAL-CANARY-DONE {datetime.now().isoformat(timespec='seconds')}")
    await disconnect()


asyncio.run(main())
