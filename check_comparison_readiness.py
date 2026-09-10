"""報告39 §2：七路檢索比較的前導可行性檢查（SDD-1 交付物）。

對每個要跑的 arm，逐一確認它需要的向量／索引／原文／抽取新鮮度都到位，
輸出 PASS/FAIL 清單並對每個 FAIL 附補救指令。**不改任何資料、純唯讀**。

用法：

    python check_comparison_readiness.py \\
        --kg-id 236903cf-055a-40a8-8923-b9d06601f3b7 \\
        --doc-ids N0030006_勞工請假規則,N0030018_育嬰留職停薪實施辦法,... \\
        --arms D,B0,B1,F,G,K,K-2b \\
        [--chunk-size 500] [--index-dir .] [--baseline-time 2026-09-08T00:00:00+00:00]

`--doc-ids` 為 `workspace/<kg_id>/` 底下的資料夾名（逗號分隔）。

檢查項目（報告39 §2.1／§2.2／§2.4）：

| 檢查 | 哪些 arm 需要 | 失敗代表 |
|---|---|---|
| Fact 節點數 ＋ `fact_embedding` 非空比例 | F / K / K-2b | 抽取時 `embedding_provider=None`，Fact 層根本沒建 |
| `Entity.name_embedding` 非空比例 | G / K / K-2b | 語意種子 fallback 幾乎無種子（純字面命中率常為 0） |
| 關係型別向量索引存在 | F / G / K / K-2b（§3.2§c） | 走 QNOMATCH → 退回不篩選（優雅降級，記 WARN 不擋） |
| `original.md` 存在 | B0 / B1 | 無法對原文重新 chunk 建乾淨基準索引 |
| baseline `.npy` 已建且涵蓋這些文件 | B0 / B1 | 需先跑 `build_baseline_chunk_index.py` |
| `task_queue` pending 數 == 0 | F / G / K / K-2b | 抽取還沒跑完，KG 事實不完整 |
| 每份文件所有 chunk 的 `updated_at` 晚於基準時間（§2.4） | F / G / K / K-2b | 早期 chunk 可能是 `num_predict=1024` 長列舉截斷版 |

退出碼：全部 PASS（WARN 不計）→ 0；任一 FAIL → 1。
"""
from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from core.config import settings, task_queue_db_path
from core.database import connect, disconnect, get_driver
from services import document_record_service

ALL_ARMS = ["D", "B0", "B1", "F", "G", "K", "K-2b"]

# 每個 arm 需要哪些檢查通過（報告39 §2.1 表）
_ARM_NEEDS: dict[str, set[str]] = {
    "D": set(),
    "B0": {"original_md", "baseline_npy"},
    "B1": {"original_md", "baseline_npy"},
    "F": {"fact_embedding", "reltype_index", "pending_zero", "extraction_fresh"},
    "G": {"entity_name_embedding", "reltype_index", "pending_zero", "extraction_fresh"},
    "K": {"fact_embedding", "entity_name_embedding", "reltype_index", "pending_zero", "extraction_fresh"},
    "K-2b": {"fact_embedding", "entity_name_embedding", "reltype_index", "pending_zero", "extraction_fresh"},
}

# §2.4 抽取端 commit 基準：取這些檔案最後一次 commit 的 committer date 當「現行
# 管線」時間；任一文件有 chunk 的 task_queue.updated_at 早於它 → 疑似舊版抽的。
_EXTRACTION_SIDE_PATHS = [
    "services/svo_service.py",
    "services/extraction_worker.py",
    "services/entity_extraction_service.py",
    "services/svo_preprocessing_service.py",
    "core/constants.py",
]

_EMB_RATIO_FAIL_BELOW = 0.95  # 非空比例低於此 → FAIL


class _Check:
    __slots__ = ("name", "status", "detail", "fix")

    def __init__(self, name: str, status: str, detail: str, fix: str = ""):
        self.name = name
        self.status = status  # PASS | FAIL | WARN
        self.detail = detail
        self.fix = fix


def _kg_fact_label(kg_id: UUID) -> str:
    return f"Fact_{str(kg_id).replace('-', '_')}"


def _extraction_side_baseline_time() -> datetime | None:
    """`git log -1 --format=%cI` 取 `_EXTRACTION_SIDE_PATHS` 最後一次 commit 的
    committer date（最新那個）。取不到（非 git、路徑不存在）→ None。"""
    latest: datetime | None = None
    for path in _EXTRACTION_SIDE_PATHS:
        try:
            out = subprocess.run(
                ["git", "log", "-1", "--format=%cI", "--", path],
                capture_output=True, text=True, cwd=Path(__file__).parent, check=True,
            ).stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
        if not out:
            continue
        try:
            dt = datetime.fromisoformat(out)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if latest is None or dt > latest:
            latest = dt
    return latest


def _parse_task_queue_updated_at(raw: str) -> datetime | None:
    """`task_queue.updated_at` 是 SQLite `datetime('now')` 的輸出（UTC，格式
    `YYYY-MM-DD HH:MM:SS`）。也容忍 ISO 8601（含 T／時區）。"""
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(raw)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _resolve_docs(kg_id: UUID, doc_ids: list[str]) -> tuple[dict[str, dict], list[_Check]]:
    """把 `--doc-ids` 每一項對到 `workspace/<kg_id>/<folder>`，讀 `_record.json`
    取真實 `source` 與 `document_uuid`。回傳 `{folder: {...}}` 與未解析的 FAIL。"""
    kg_folder = Path(settings.workspace_dir) / str(kg_id)
    resolved: dict[str, dict] = {}
    checks: list[_Check] = []
    for entry in doc_ids:
        folder = kg_folder / entry
        if not folder.is_dir():
            checks.append(_Check(
                f"文件解析：{entry}", "FAIL",
                f"找不到資料夾 {folder}",
                f"確認 WORKSPACE_DIR 指向正確位置（KG#4 runtime 在 D:/Users/666/Desktop/kg-runtime），"
                f"且 {entry} 拼字與 workspace/<kg_id>/ 底下一致",
            ))
            continue
        record = document_record_service.read_record(folder)
        source = record.source if record is not None else entry
        resolved[entry] = {
            "folder": folder,
            "source": source,
            "doc_uuid": document_record_service.document_uuid(source),
            "record": record,
            "has_original_md": (folder / "original.md").exists(),
        }
    return resolved, checks


def _check_original_md(resolved: dict[str, dict]) -> _Check:
    missing = [e for e, m in resolved.items() if not m["has_original_md"]]
    if not resolved:
        return _Check("original.md 存在", "FAIL", "沒有任何文件解析成功")
    if missing:
        return _Check(
            "original.md 存在", "FAIL",
            f"{len(missing)} 份缺 original.md：{', '.join(missing)}",
            "這些文件缺原文，B0/B1 無法自建乾淨 chunk 索引；確認 workspace 完整、"
            "或改用其他有原文的文件",
        )
    return _Check("original.md 存在", "PASS", f"{len(resolved)} 份皆有 original.md")


def _check_baseline_npy(kg_id: UUID, resolved: dict[str, dict], chunk_size: int, index_dir: Path) -> _Check:
    import json as _json

    stem = index_dir / f"baseline_rag_index_{kg_id}_cs{chunk_size}"
    npy, meta = stem.with_suffix(".npy"), stem.with_suffix(".json")
    fix = f"python build_baseline_chunk_index.py {kg_id} --chunk-size {chunk_size}"
    if not npy.exists() or not meta.exists():
        return _Check("baseline .npy 已建", "FAIL", f"找不到 {npy.name} / {meta.name}", fix)
    try:
        records = _json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _Check("baseline .npy 已建", "FAIL", f"{meta.name} 讀取失敗：{exc}", fix)
    indexed_sources = {r.get("source") for r in records}
    # meta 的 source 可能是 frontmatter source 或資料夾名 → 兩種都比對
    want = {m["source"] for m in resolved.values()} | set(resolved.keys())
    covered = {e for e, m in resolved.items() if m["source"] in indexed_sources or e in indexed_sources}
    uncovered = [e for e in resolved if e not in covered]
    if uncovered:
        return _Check(
            "baseline .npy 已建", "FAIL",
            f"索引未涵蓋 {len(uncovered)} 份：{', '.join(uncovered)}（索引內 {len(records)} chunk）",
            fix + "（確認 build 腳本跑的 workspace 與這次一致）",
        )
    return _Check("baseline .npy 已建", "PASS",
                  f"{npy.name}：{len(records)} chunk，涵蓋全部 {len(resolved)} 份")


def _check_task_queue(
    kg_id: UUID, resolved: dict[str, dict], baseline_time: datetime | None
) -> list[_Check]:
    import sqlite3

    checks: list[_Check] = []
    db_path = task_queue_db_path()
    if not db_path.exists():
        checks.append(_Check(
            "task_queue.db 存在", "FAIL", f"找不到 {db_path}",
            "確認 WORKSPACE_DIR 指向 KG#4 runtime；或抽取尚未初始化佇列",
        ))
        return checks

    conn = sqlite3.connect(str(db_path))
    try:
        # ── pending == 0（整個 KG）──
        total_pending = conn.execute(
            "SELECT count(*) FROM task_queue WHERE kg_id = ? AND status = 'pending'",
            (str(kg_id),),
        ).fetchone()[0]
        if total_pending:
            checks.append(_Check(
                "KG pending == 0", "WARN",
                f"整個 KG 還有 {total_pending} 個 pending chunk（前導只需比較用文件 pending=0）",
            ))
        else:
            checks.append(_Check("KG pending == 0", "PASS", "整個 KG 無 pending"))

        # ── 每份比較文件：pending 與新鮮度 ──
        stale_docs: list[str] = []
        pending_docs: list[str] = []
        missing_rows: list[str] = []
        for entry, meta in resolved.items():
            rows = conn.execute(
                "SELECT chunk_index, status, updated_at FROM task_queue WHERE kg_id = ? AND source = ?",
                (str(kg_id), meta["source"]),
            ).fetchall()
            if not rows:
                # source 可能存資料夾名而非 record.source
                rows = conn.execute(
                    "SELECT chunk_index, status, updated_at FROM task_queue WHERE kg_id = ? AND source = ?",
                    (str(kg_id), entry),
                ).fetchall()
            if not rows:
                missing_rows.append(entry)
                continue
            if any(s == "pending" for _, s, _ in rows):
                pending_docs.append(entry)
            if baseline_time is not None:
                oldest = min(
                    (_parse_task_queue_updated_at(u) for _, _, u in rows if _parse_task_queue_updated_at(u)),
                    default=None,
                )
                if oldest is None or oldest < baseline_time:
                    stale_docs.append(f"{entry}（最舊 {oldest.isoformat() if oldest else '無法解析'}）")

        if missing_rows:
            checks.append(_Check(
                "比較文件在佇列中", "FAIL",
                f"{len(missing_rows)} 份在 task_queue 查無任何 chunk：{', '.join(missing_rows)}",
                "在 reextract-v2 HEAD 對這些文件跑 force_rebuild=True 重抽",
            ))
        if pending_docs:
            checks.append(_Check(
                "比較文件 pending == 0", "FAIL",
                f"{len(pending_docs)} 份仍有 pending chunk：{', '.join(pending_docs)}",
                "等這些文件抽完（pending=0）再跑比較，或改用已完成的文件子集",
            ))
        else:
            checks.append(_Check("比較文件 pending == 0", "PASS",
                                 f"{len(resolved) - len(missing_rows)} 份皆無 pending"))

        if baseline_time is None:
            checks.append(_Check(
                "抽取新鮮度（§2.4）", "WARN",
                "無法取得基準時間（非 git 環境且未給 --baseline-time）→ 跳過新鮮度檢查",
                "給 --baseline-time <本次 force_rebuild 的時間戳，ISO 8601>",
            ))
        elif stale_docs:
            checks.append(_Check(
                "抽取新鮮度（§2.4）", "FAIL",
                f"{len(stale_docs)} 份有 chunk 早於基準 {baseline_time.isoformat()}："
                + "；".join(stale_docs),
                "在 reextract-v2 HEAD 對這些文件跑 force_rebuild=True 重抽"
                "（帶 embedding provider、OLLAMA_EMBEDDING_NUM_GPU=0），讓 Fact 節點與 "
                "fact_embedding 一併以現行管線重建",
            ))
        else:
            checks.append(_Check("抽取新鮮度（§2.4）", "PASS",
                                 f"全部 chunk updated_at ≥ {baseline_time.isoformat()}"))
    finally:
        conn.close()
    return checks


async def _check_neo4j(kg_id: UUID, resolved: dict[str, dict]) -> list[_Check]:
    checks: list[_Check] = []
    try:
        await connect()
    except Exception as exc:  # noqa: BLE001 - 連不上就整批標 FAIL、不 crash
        return [_Check(
            "Neo4j 連線", "FAIL", f"{type(exc).__name__}: {exc}",
            f"確認 Neo4j 容器 kg2-neo4j 已啟動、NEO4J_URI（{settings.neo4j_uri}）正確",
        )]
    driver = get_driver()
    try:
        fact_label = _kg_fact_label(kg_id)
        # ── Fact 節點 ＋ fact_embedding 非空比例 ──
        rec = (await driver.execute_query(
            f"MATCH (f:`{fact_label}`) RETURN count(f) AS total, "
            f"count(f.fact_embedding) AS emb"
        )).records[0]
        total, emb = rec["total"], rec["emb"]
        if total == 0:
            checks.append(_Check(
                "Fact 節點存在", "FAIL",
                f"label {fact_label} 沒有任何節點",
                "抽取時 embedding_provider=None → merge_triples_to_graph() 完全不建 Fact；"
                "在 reextract-v2 HEAD 帶 embedding provider 重抽",
            ))
        else:
            ratio = emb / total
            status = "PASS" if ratio >= _EMB_RATIO_FAIL_BELOW else "FAIL"
            checks.append(_Check(
                "fact_embedding 非空比例", status,
                f"{emb}/{total} = {ratio:.1%}",
                "" if status == "PASS" else
                "跑 backfill_fact_text_embeddings() 或重抽補齊 fact_embedding",
            ))

        # ── Entity.name_embedding 非空比例 ──
        rec = (await driver.execute_query(
            "MATCH (e:Entity {kg_id: $kg}) RETURN count(e) AS total, "
            "count(e.name_embedding) AS emb", kg=str(kg_id),
        )).records[0]
        total, emb = rec["total"], rec["emb"]
        if total == 0:
            checks.append(_Check("Entity.name_embedding", "FAIL",
                                 f"KG {kg_id} 沒有任何 Entity 節點"))
        else:
            ratio = emb / total
            status = "PASS" if ratio >= _EMB_RATIO_FAIL_BELOW else "FAIL"
            checks.append(_Check(
                "Entity.name_embedding 非空比例", status,
                f"{emb}/{total} = {ratio:.1%}",
                "" if status == "PASS" else
                "跑 backfill_entity_name_embeddings()；缺了 G arm 語意種子 fallback 幾乎無種子",
            ))

        # ── 每份比較文件在 KG 內有 Fact ──
        no_fact = []
        for entry, meta in resolved.items():
            n = (await driver.execute_query(
                f"MATCH (f:`{fact_label}`) WHERE f.source_doc_id = $sd RETURN count(f) AS n",
                sd=str(meta["doc_uuid"]),
            )).records[0]["n"]
            if n == 0:
                no_fact.append(entry)
        if no_fact:
            checks.append(_Check(
                "比較文件在 KG 內有 Fact", "FAIL",
                f"{len(no_fact)} 份查無 Fact（source_doc_id 比對）：{', '.join(no_fact)}",
                "確認這些文件已抽完並寫入；或 source_doc_id 對不上（舊資料未指派）→ 重抽",
            ))
        else:
            checks.append(_Check("比較文件在 KG 內有 Fact", "PASS",
                                 f"{len(resolved)} 份皆有 Fact 節點"))

        # ── 關係型別向量索引（§3.2§c）──
        idx = (await driver.execute_query(
            "SHOW INDEXES YIELD name, type WHERE type = 'VECTOR' RETURN collect(name) AS names"
        )).records[0]["names"]
        reltype_idx = [n for n in idx if "related_to" in n.lower() or "rel_type" in n.lower()
                       or "relation" in n.lower()]
        if reltype_idx:
            checks.append(_Check("關係型別向量索引", "PASS", f"找到：{', '.join(reltype_idx)}"))
        else:
            checks.append(_Check(
                "關係型別向量索引", "WARN",
                "查無 RELATED_TO / 關係型別向量索引 → §3.2§c 走 QNOMATCH 退回不篩選"
                "（優雅降級，不擋比較，但報告要記這條 caveat）",
                "app 啟動會呼叫 create_related_to_vector_index()；手動：啟一次 main.py 或"
                "直接對該 KG 跑一次語意查詢即可惰性建立",
            ))
    finally:
        await disconnect()
    return checks


def _print_report(kg_id: UUID, arms: list[str], checks: list[_Check]) -> int:
    by_name = {c.name: c for c in checks}
    print(f"\n{'=' * 72}\n報告39 §2 前導可行性檢查｜KG {kg_id}\n{'=' * 72}")

    width = max((len(c.name) for c in checks), default=20)
    for c in checks:
        mark = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️ "}[c.status]
        print(f"  {mark} {c.name.ljust(width)}  {c.detail}")
        if c.fix and c.status != "PASS":
            print(f"       ↳ 補救：{c.fix}")

    # ── 每個 arm 是否可跑 ──
    print(f"\n{'-' * 72}\narm 可跑性：")
    name_to_check = {
        "original_md": "original.md 存在",
        "baseline_npy": "baseline .npy 已建",
        "fact_embedding": "fact_embedding 非空比例",
        "entity_name_embedding": "Entity.name_embedding 非空比例",
        "reltype_index": "關係型別向量索引",
        "pending_zero": "比較文件 pending == 0",
        "extraction_fresh": "抽取新鮮度（§2.4）",
    }
    any_blocked = False
    for arm in arms:
        blockers = []
        for need in sorted(_ARM_NEEDS.get(arm, set())):
            chk = by_name.get(name_to_check[need])
            if chk is None or chk.status == "FAIL":
                blockers.append(name_to_check[need])
        # Fact 在 KG 內 / Neo4j 連線 / 文件解析 這類全域 FAIL 也算 blocker（F/G/K）
        if arm in ("F", "G", "K", "K-2b"):
            for extra in ("Neo4j 連線", "比較文件在 KG 內有 Fact", "比較文件在佇列中",
                          "task_queue.db 存在"):
                c = by_name.get(extra)
                if c is not None and c.status == "FAIL":
                    blockers.append(extra)
        if blockers:
            any_blocked = True
            print(f"  ❌ {arm.ljust(5)} 卡：{', '.join(dict.fromkeys(blockers))}")
        else:
            print(f"  ✅ {arm.ljust(5)} 可跑")

    has_fail = any(c.status == "FAIL" for c in checks)
    print(f"\n{'=' * 72}")
    if has_fail or any_blocked:
        print("結果：FAIL — 依上方補救指令補齊後重跑本檢查")
        return 1
    print("結果：PASS — 可執行 run_retrieval_comparison.py")
    return 0


async def _main() -> int:
    ap = argparse.ArgumentParser(description="報告39 §2 七路檢索比較前導可行性檢查")
    ap.add_argument("--kg-id", required=True, type=UUID)
    ap.add_argument("--doc-ids", required=True,
                    help="workspace/<kg_id>/ 底下的資料夾名，逗號分隔")
    ap.add_argument("--arms", default=",".join(ALL_ARMS),
                    help=f"逗號分隔，預設全部：{','.join(ALL_ARMS)}")
    ap.add_argument("--chunk-size", type=int, default=500)
    ap.add_argument("--index-dir", default=".", help="baseline_rag_index_*.npy 所在目錄")
    ap.add_argument("--baseline-time",
                    help="§2.4 新鮮度基準（ISO 8601）；省略時取抽取端檔案最後 commit 時間")
    args = ap.parse_args()

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    bad = [a for a in arms if a not in ALL_ARMS]
    if bad:
        print(f"未知 arm：{bad}；可用：{ALL_ARMS}", file=sys.stderr)
        return 2
    doc_ids = [d.strip() for d in args.doc_ids.split(",") if d.strip()]

    if args.baseline_time:
        baseline_time = datetime.fromisoformat(args.baseline_time)
        if baseline_time.tzinfo is None:
            baseline_time = baseline_time.replace(tzinfo=timezone.utc)
    else:
        baseline_time = _extraction_side_baseline_time()

    resolved, checks = _resolve_docs(args.kg_id, doc_ids)

    need = set().union(*(_ARM_NEEDS[a] for a in arms))
    if "original_md" in need:
        checks.append(_check_original_md(resolved))
    if "baseline_npy" in need:
        checks.append(_check_baseline_npy(args.kg_id, resolved, args.chunk_size, Path(args.index_dir)))
    if {"pending_zero", "extraction_fresh"} & need:
        checks.extend(_check_task_queue(args.kg_id, resolved, baseline_time))
    if {"fact_embedding", "entity_name_embedding", "reltype_index"} & need:
        checks.extend(await _check_neo4j(args.kg_id, resolved))

    return _print_report(args.kg_id, arms, checks)


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
