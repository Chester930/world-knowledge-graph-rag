"""報告32 §9 step 7：G2/G3「4 份文件窗口」觸發檢查。

觸發條件 = KG #4（236903cf）的這 4 份文件 pending + processing 全歸零：
  N0060004 勞工作業場所容許暴露標準        （G2：Q8 混合暴露係數多跳）
  N0030025 勞基法第45條無礙身心健康認定基準  （G3：Q3 未滿15歲三段年齡工時清單）
  N0060065 女性勞工母性健康保護實施辦法      （G3：Q6 血中鉛分級清單）
  N0050030 災區受災勞工保險費支應及傷病給付辦法（L2 / 窗口對照）

用法：
    cd "D:/Users/666/Desktop/world knowledge graph rag/.claude/worktrees/kg-reextract"
    python check_4docs_kg4.py            # 印狀態表 + 是否觸發
    python check_4docs_kg4.py --eta      # 另外用近端速率估窗口 ETA

觸發後 → 跑 diag_g2g3_window.py，並 SendMessage 通知 "project status review"。
"""
from __future__ import annotations

import sqlite3
import sys
import datetime

DB = r"D:\Users\666\Desktop\kg-runtime\task_queue.db"
KG = "236903cf-055a-40a8-8923-b9d06601f3b7"
DOCS = {
    "N0060004": "勞工作業場所容許暴露標準（G2/Q8）",
    "N0030025": "勞基法第45條認定基準（G3/Q3）",
    "N0060065": "女性勞工母性健康保護實施辦法（G3/Q6）",
    "N0050030": "災區受災勞工保險費支應及傷病給付辦法（L2）",
}


def main() -> int:
    c = sqlite3.connect(DB)
    print(f"task_queue.db = {DB}")
    print(f"KG = {KG}\n")
    all_zero = True
    print(f"{'source':10s} {'total':>6s} {'done':>6s} {'pend':>6s} {'proc':>6s} {'fail':>6s}  狀態")
    for pref, label in DOCS.items():
        rows = dict(
            c.execute(
                "SELECT status, COUNT(*) FROM task_queue WHERE kg_id=? AND source LIKE ? GROUP BY status",
                (KG, pref + "%"),
            ).fetchall()
        )
        done = rows.get("completed", 0)
        pend = rows.get("pending", 0)
        proc = rows.get("processing", 0)
        fail = rows.get("failed", 0)
        tot = done + pend + proc + fail
        left = pend + proc
        if left > 0:
            all_zero = False
        flag = "✅ 清空" if left == 0 else f"⏳ 還剩 {left}"
        print(f"{pref:10s} {tot:6d} {done:6d} {pend:6d} {proc:6d} {fail:6d}  {flag}  {label}")

    glob = dict(
        c.execute(
            "SELECT status, COUNT(*) FROM task_queue WHERE kg_id=? GROUP BY status", (KG,)
        ).fetchall()
    )
    print(f"\n全 KG：{glob}")

    if "--eta" in sys.argv:
        comp = [
            r[0]
            for r in c.execute(
                "SELECT updated_at FROM task_queue WHERE kg_id=? AND status='completed' ORDER BY updated_at",
                (KG,),
            ).fetchall()
        ]
        if len(comp) >= 2:
            t0 = datetime.datetime.fromisoformat(comp[0])
            t1 = datetime.datetime.fromisoformat(comp[-1])
            mins = (t1 - t0).total_seconds() / 60
            rate = mins / len(comp)  # min/chunk
            winmax = max(
                c.execute(
                    "SELECT MAX(chunk_index) FROM task_queue WHERE kg_id=? AND source LIKE ?",
                    (KG, p + "%"),
                ).fetchone()[0]
                for p in DOCS
            )
            rem_win = c.execute(
                "SELECT COUNT(*) FROM task_queue WHERE kg_id=? AND chunk_index<=? AND status IN ('pending','processing')",
                (KG, winmax),
            ).fetchone()[0]
            rem_full = c.execute(
                "SELECT COUNT(*) FROM task_queue WHERE kg_id=? AND status IN ('pending','processing')",
                (KG,),
            ).fetchone()[0]
            print(
                f"\n近端速率 {rate:.2f} min/chunk（{60/rate:.0f}/hr，樣本 {len(comp)}）"
            )
            print(
                f"窗口 ETA：sweep 需到 chunk_index {winmax}，剩 {rem_win} → ~{rem_win*rate/60:.1f} h（~{rem_win*rate/60/24:.1f} d）"
            )
            print(
                f"DRAIN-DONE ETA：剩 {rem_full} → ~{rem_full*rate/60:.0f} h（~{rem_full*rate/60/24:.1f} d）"
            )

    print()
    if all_zero:
        print(">>> 觸發：4 份全清空。跑 diag_g2g3_window.py，並通知 project status review。")
        return 0
    print(">>> 尚未觸發。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
