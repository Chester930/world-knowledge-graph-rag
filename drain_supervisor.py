"""KG 236903cf 抽取 drain 的自動調度器（auto-scaler）。

每 INTERVAL 秒依「剩餘 pending 數」＋「Windows 可用 RAM」決定要跑 1/2/3 個
`drain_236903cf.py` worker，補開 / 優雅縮編。

count → 目標 worker 數：
    pending == 0   → 0（收尾、印 DRAIN-DONE、結束）
    pending > 400  → 3
    pending > 80   → 2
    其餘（1..80）  → 1
RAM 上限保護：
    free < 2000 MB → 上限 1
    free < 3000 MB → 上限 2
    否則           → 上限 3
    target = min(count_target, ram_cap)

縮編用 `STOP_<label>` 檔——`drain_236903cf.py` 在認領下一個 chunk 前看到就乾淨退出，
不留孤兒 processing row（不像 SIGKILL）。擴編直接 spawn 新 worker。

用法（取代手動「開 N worker」）：
    cd "D:/Users/666/Desktop/world knowledge graph rag/.claude/worktrees/kg-reextract"
    nohup python -u drain_supervisor.py >> "C:/Users/666/.claude/jobs/<job>/tmp/drain_supervisor.log" 2>&1 &

進度 / 每 25% 備份仍由 `monitor_drain_236903cf.sh` Monitor 負責（DB 驅動、與本腳本無關）。
"""
from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
from core.config import task_queue_db_path  # noqa: E402
from services.task_queue_service import reset_stuck_processing  # noqa: E402

KG_STR = "236903cf-055a-40a8-8923-b9d06601f3b7"
INTERVAL = 90
LABELS = ["w1", "w2", "w3"]
WORKER_ENV = {"OLLAMA_EMBEDDING_NUM_GPU": "0", "OLLAMA_LLM_NUM_PREDICT": "8192"}
LOG_DIR = Path(r"C:\Users\666\.claude\jobs\efb89cec\tmp")
DRAIN_SCRIPT = str(_HERE / "drain_236903cf.py")

DB = task_queue_db_path()
RUNTIME = DB.parent


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def q_counts() -> tuple[int, int]:
    c = sqlite3.connect(DB)
    try:
        rows = dict(c.execute(
            "SELECT status,COUNT(*) FROM task_queue WHERE kg_id=? GROUP BY status",
            (KG_STR,)).fetchall())
    finally:
        c.close()
    return rows.get("pending", 0), rows.get("processing", 0)


def free_mb() -> int:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024,0)"],
            capture_output=True, text=True, timeout=25)
        return int(out.stdout.strip())
    except Exception:
        return 9999  # 讀不到就不因 RAM 設限


def count_target(pending: int) -> int:
    if pending == 0:
        return 0
    if pending > 400:
        return 3
    if pending > 80:
        return 2
    return 1


def ram_cap(fm: int) -> int:
    if fm < 2000:
        return 1
    if fm < 3000:
        return 2
    return 3


def spawn(label: str) -> subprocess.Popen:
    env = {**os.environ, **WORKER_ENV}
    logf = open(LOG_DIR / f"drain_236903cf_{label}.log", "ab")
    return subprocess.Popen(
        [sys.executable, "-u", DRAIN_SCRIPT, "--label", label],
        stdout=logf, stderr=subprocess.STDOUT, env=env, cwd=str(_HERE))


def request_stop(label: str) -> None:
    (RUNTIME / f"STOP_{label}").touch()


def clear_stop(label: str) -> None:
    (RUNTIME / f"STOP_{label}").unlink(missing_ok=True)


def reap(workers: dict, stopping: set) -> None:
    for lb in list(workers):
        if workers[lb].poll() is not None:
            del workers[lb]
            stopping.discard(lb)
            clear_stop(lb)
            print(f"{ts()} {lb} 已退出", flush=True)


def _kill_stray_drains() -> None:
    """啟動前：殺掉任何非本 supervisor 管理的 drain_236903cf.py 行程，再 blanket
    reset_stuck_processing（只有在確定無 worker 在跑時才安全）。"""
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -like '*drain_236903cf*' } | "
             "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
            capture_output=True, text=True, timeout=30)
    except Exception:
        pass
    time.sleep(3)
    freed = reset_stuck_processing(DB)
    kg_freed = [r for r in freed if r[0] == KG_STR]
    if kg_freed:
        print(f"{ts()} 啟動清理：reset {len(kg_freed)} 個 stuck processing row", flush=True)
    for lb in LABELS:
        clear_stop(lb)


def main() -> None:
    workers: dict[str, subprocess.Popen] = {}
    stopping: set[str] = set()

    def shutdown(*_):
        print(f"{ts()} supervisor 收到中止訊號——請所有 worker 優雅停止", flush=True)
        for lb in list(workers):
            request_stop(lb)
        deadline = time.time() + 480
        while workers and time.time() < deadline:
            reap(workers, stopping)
            time.sleep(5)
        for lb in list(workers):
            workers[lb].kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print(f"{ts()} supervisor 啟動  db={DB}", flush=True)
    _kill_stray_drains()

    empty_rounds = 0
    while True:
        reap(workers, stopping)
        pending, processing = q_counts()
        fm = free_mb()
        tgt = min(count_target(pending), ram_cap(fm))
        alive = [lb for lb in LABELS if lb in workers and lb not in stopping]

        empty_rounds = empty_rounds + 1 if pending == 0 else 0

        if len(alive) < tgt:
            for lb in LABELS:
                if len(alive) >= tgt:
                    break
                if lb not in workers:
                    clear_stop(lb)
                    workers[lb] = spawn(lb)
                    alive.append(lb)
                    print(f"{ts()} + 開 {lb}（target={tgt}）", flush=True)
        elif len(alive) > tgt:
            for lb in reversed(alive):
                if len(alive) <= tgt:
                    break
                request_stop(lb)
                stopping.add(lb)
                alive.remove(lb)
                print(f"{ts()} - 請 {lb} 優雅停止（target={tgt}）", flush=True)

        print(f"{ts()} pending={pending} processing={processing} free={fm}mb "
              f"target={tgt} alive={sorted(alive)} stopping={sorted(stopping)}", flush=True)

        if pending == 0 and not workers and empty_rounds >= 2:
            print(f"{ts()} DRAIN-DONE：pending=0、所有 worker 已退出", flush=True)
            return

        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
