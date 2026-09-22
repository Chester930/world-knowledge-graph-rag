"""Run / resume stages of a frozen RQ1 baseline using only files in the frozen dir.

The frozen dir holds ``frozen_manifest.json`` (code commit, bank hash, eligible ids,
scope docs, KG id) plus per-stage outputs.  Two subcommands:

  remaining  -- emit the eligible questions that have no result yet in the given
                records files (used to resume an interrupted stage)
  run        -- run one stage of the harness with the exact frozen settings

Typical resume:
    python scripts/eval/frozen_baseline_stage.py remaining --frozen-dir D \
        --records D/stage_b/records.json --emit D/stage_b_rest.json
    python scripts/eval/frozen_baseline_stage.py run --frozen-dir D \
        --questions D/stage_b_rest.json --out D/stage_b_2

Export WORKSPACE_DIR / NEO4J_URI / NEO4J_PASSWORD in the environment first (the
worktree .env uses a relative WORKSPACE_DIR); ``run`` fills the values used for
the 2026-09-20 baseline only if they are unset.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV = {
    "WORKSPACE_DIR": "D:/Users/666/Desktop/kg-runtime",
    "NEO4J_URI": "bolt://localhost:17990",
    "NEO4J_PASSWORD": "kg2_test_2026",
    # 這台機器同時有 Windows(127.0.0.1) 與 WSL(::1) 兩個 Ollama，用 "localhost" 會打到哪個不固定。
    "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
}


def ollama_version_matches(expected: str | None, actual: str | None) -> bool:
    """凍結資訊未記錄版本時不檢查；記錄了就必須一致。"""
    return expected is None or expected == actual


def fetch_ollama_version(base_url: str) -> str | None:
    import urllib.request

    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/version", timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8")).get("version")
    except Exception:  # noqa: BLE001
        return None


def load_manifest(frozen_dir: Path) -> dict:
    return json.loads((frozen_dir / "frozen_manifest.json").read_text(encoding="utf-8"))


def remaining_question_ids(eligible_ids: list[str], record_paths: list[Path]) -> list[str]:
    done: set[str] = set()
    for path in record_paths:
        for record in json.loads(path.read_text(encoding="utf-8")):
            done.add(record["question_id"])
    return [q for q in eligible_ids if q not in done]


def cmd_remaining(args: argparse.Namespace) -> None:
    manifest = load_manifest(Path(args.frozen_dir))
    ids = remaining_question_ids(manifest["eligible_ids"], [Path(p) for p in args.records])
    bank = json.loads((REPO_ROOT / "data/eval/test_cases.json").read_text(encoding="utf-8"))
    selected = [q for q in bank["questions"] if q["id"] in set(ids)]
    Path(args.emit).write_text(
        json.dumps({"questions": selected}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"eligible {len(manifest['eligible_ids'])}, remaining {len(selected)}: {ids}")


def build_run_command(
    manifest: dict,
    questions: str,
    out: str,
    embedding_cache: str | None = None,
) -> list[str]:
    """組出 frozen stage 的 harness command；快取旗標是 opt-in。"""
    cmd = [
        sys.executable, "-u", str(REPO_ROOT / "scripts" / "eval" / "run_rq1_comparison.py"),
        "--kg-id", manifest["kg_id"],
        "--doc-ids", ",".join(manifest["scope_doc_ids"]),
        "--questions", questions,
        "--arms", "K", "--runs", "1",
        "--query-timeout-s", "900",
        "--allow-shared-judge",
        "--out", out,
    ]
    if embedding_cache:
        cmd += ["--embedding-cache", embedding_cache]
    return cmd


def cmd_run(args: argparse.Namespace) -> int:
    manifest = load_manifest(Path(args.frozen_dir))
    env = dict(os.environ)
    for key, value in DEFAULT_ENV.items():
        env.setdefault(key, value)
    cmd = build_run_command(
        manifest,
        args.questions,
        args.out,
        getattr(args, "embedding_cache", None),
    )
    if getattr(args, "k_top_k", None) is not None:  # 報告62 T1 候選臂；預設不傳＝凍結基準
        cmd += ["--k-top-k", str(args.k_top_k)]
    base_url = env["OLLAMA_BASE_URL"]
    actual_version = fetch_ollama_version(base_url)
    if not ollama_version_matches(manifest.get("ollama_version"), actual_version):
        raise SystemExit(
            f"Ollama 版本與凍結資訊不符：端點 {base_url} 為 {actual_version}，"
            f"凍結為 {manifest.get('ollama_version')}。請確認連到正確的 Ollama 實例。"
        )
    print("frozen commit:", manifest["git_commit"], "| bank sha256:", manifest["bank_sha256"][:16],
          "| ollama:", base_url, actual_version, flush=True)
    return subprocess.run(cmd, cwd=REPO_ROOT, env=env).returncode


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    rem = sub.add_parser("remaining")
    rem.add_argument("--frozen-dir", required=True)
    rem.add_argument("--records", action="append", default=[])
    rem.add_argument("--emit", required=True)
    run = sub.add_parser("run")
    run.add_argument("--frozen-dir", required=True)
    run.add_argument("--questions", required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--k-top-k", type=int, default=None,
                     help="報告62 T1 候選臂的語意 Fact 筆數；預設不傳＝凍結基準（20）。")
    run.add_argument("--embedding-cache", default=None,
                     help="選填：評測專用 embedding JSON 快取路徑；不傳則完全不啟用。")
    args = parser.parse_args()
    if args.command == "remaining":
        cmd_remaining(args)
    else:
        sys.exit(cmd_run(args))


if __name__ == "__main__":
    main()
