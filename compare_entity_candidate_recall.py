"""報告40（L6 R2）驗證 harness：新舊實體候選集檢索 recall 對照。

比較「現行 `_fetch_entity_candidates()` 全 KG 掃描」vs「canopy 式候選檢索
（本腳本自帶實作，見 `_fetch_candidates_canopy()`——production 尚未接線，
故不 import 未落地的程式碼）」對同一批真實 mention，餵進**現行未修改**的
`resolve_entity_name()`（僅比對 tiers ③精確／④編輯距離／⑤cosine，**不帶
`llm_provider`**——tier ⑥ LLM 灰色地帶仲裁本身非決定性，混進批次比較會
混淆「候選集差異」與「LLM 抽樣雜訊」兩件事；灰色地帶案例改用
`--show-grey-zone` 額外列出，供人工檢視兩邊灰色地帶候選是否一致）後，
兩邊的 `resolve_entity_name()` 結果是否一致。

**⚠️ 執行時機**：`--setup-only`（建向量/fulltext 索引 + 補齊 `name_embedding`）
可在 drain 進行中隨時跑（純附加、冪等，不影響正在寫入的資料）。**完整比較
需等 KG 進入穩定終態**（`task_queue` 該 KG 全數 `completed`／`failed`，非
`pending`／`processing`）——否則新舊兩邊看到的候選集本身就會因為背景仍在
寫入而不可比。預設會檢查並拒絕；`--force` 略過檢查（僅供小樣本乾跑腳本
本身邏輯，不代表結果可採信）。全程唯讀，不寫入 Neo4j 除了 `--setup-only`
的索引/embedding 補齊（`CREATE ... IF NOT EXISTS` 與 `backfill_entity_
name_embeddings()`，皆為既有生產路徑本來就會做的事，非本腳本新引入的
寫入）。

對應 `docs/報告/40_實體對齊候選集檢索效能改造設計報告.md` §7「驗證計畫」。

用法：

    # 1) drain 期間可先跑：建索引 + 補齊向量（安全、冪等）
    python compare_entity_candidate_recall.py <kg_id> --setup-only

    # 2) DRAIN-DONE 後：完整 recall 對照
    python compare_entity_candidate_recall.py <kg_id> --sample-size 300 --canopy-k 50 \\
        --out compare_entity_candidate_recall_result.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import UUID

from core.config import settings, task_queue_db_path
from core.database import connect, disconnect, get_driver
from core.providers.factory import get_embedding_provider, init_providers
from services.svo_service import (
    _fetch_entity_candidates,
    backfill_entity_name_embeddings,
    resolve_entity_name,
)
from services.classify_service import cosine_similarity

ENTITY_NAME_VECTOR_INDEX = "entity_name_vector"
ENTITY_NAME_FULLTEXT_INDEX = "entity_name_fulltext"


async def create_entity_name_vector_index(driver, dim: int) -> None:
    """報告40 §6.1：全域索引（非 per-KG label）＋查詢後 `kg_id` 過濾——
    `Entity` 已是單一 label、`_fetch_entity_candidates` 本來就帶 `kg_id`
    過濾，不像 `Fact` 被迫 per-KG label。"""
    await driver.execute_query(
        f"""
        CREATE VECTOR INDEX {ENTITY_NAME_VECTOR_INDEX} IF NOT EXISTS
        FOR (e:Entity) ON e.name_embedding
        OPTIONS {{ indexConfig: {{ `vector.dimensions`: $dim, `vector.similarity_function`: 'cosine' }} }}
        """,
        dim=dim,
    )


async def create_entity_name_fulltext_index(driver) -> bool:
    """CJK bigram fulltext；部署版本不支援時回傳 `False`（呼叫端退回
    `CONTAINS` 過渡方案，見報告40 §3.3）。"""
    try:
        await driver.execute_query(
            f"""
            CREATE FULLTEXT INDEX {ENTITY_NAME_FULLTEXT_INDEX} IF NOT EXISTS
            FOR (e:Entity) ON EACH [e.name]
            OPTIONS {{ indexConfig: {{ `fulltext.analyzer`: 'cjk' }} }}
            """,
        )
        return True
    except Exception:  # noqa: BLE001 -- 純唯讀探測，任何失敗都優雅退回 CONTAINS
        return False


async def _fetch_candidates_canopy(
    driver, kg_id: UUID, name: str, *, canopy_k: int, fulltext_available: bool,
) -> list[dict]:
    """報告40 §3 的三 canopy 聯集（本腳本自帶實作，供對照——**非**
    production 程式碼，尚未接線進 `svo_service.py`）。"""
    kg_id_str = str(kg_id)
    by_name: dict[str, dict] = {}

    # 3.1 exact canopy
    exact = await driver.execute_query(
        "MATCH (e:Entity {kg_id: $kg_id, name: $name}) "
        "RETURN e.name AS name, e.name_embedding AS name_embedding",
        kg_id=kg_id_str, name=name,
    )
    for r in exact.records:
        by_name[r["name"]] = {"name": r["name"], "name_embedding": r.get("name_embedding")}

    # 3.2 cosine canopy（向量索引）
    cosine_result = await driver.execute_query(
        f"""
        CALL db.index.vector.queryNodes('{ENTITY_NAME_VECTOR_INDEX}', $k, $vec)
        YIELD node AS e, score
        WHERE e.kg_id = $kg_id
        RETURN e.name AS name, e.name_embedding AS name_embedding
        """,
        k=canopy_k, vec=await get_embedding_provider().encode(name), kg_id=kg_id_str,
    )
    for r in cosine_result.records:
        by_name.setdefault(r["name"], {"name": r["name"], "name_embedding": r.get("name_embedding")})

    # 3.3 字串 canopy
    if fulltext_available:
        ft = await driver.execute_query(
            f"CALL db.index.fulltext.queryNodes('{ENTITY_NAME_FULLTEXT_INDEX}', $q) "
            "YIELD node AS e WHERE e.kg_id = $kg_id "
            "RETURN e.name AS name, e.name_embedding AS name_embedding",
            q=name, kg_id=kg_id_str,
        )
        for r in ft.records:
            by_name.setdefault(r["name"], {"name": r["name"], "name_embedding": r.get("name_embedding")})
    else:
        contains = await driver.execute_query(
            "MATCH (e:Entity {kg_id: $kg_id}) WHERE e.name CONTAINS $name OR $name CONTAINS e.name "
            "RETURN e.name AS name, e.name_embedding AS name_embedding",
            kg_id=kg_id_str, name=name,
        )
        for r in contains.records:
            by_name.setdefault(r["name"], {"name": r["name"], "name_embedding": r.get("name_embedding")})

    return list(by_name.values())


@dataclass
class MentionResult:
    mention: str
    old_candidate_count: int
    new_candidate_count: int
    old_resolved: str
    new_resolved: str
    agree: bool
    grey_zone: bool  # 任一邊 cosine 落在 [ESCALATE_LOW, COSINE) 卻無 llm_provider 可仲裁


async def _sample_mentions(driver, kg_id: UUID, n: int, seed: int) -> list[str]:
    """從既有 `HAS_ENTITY` 邊的 `surface_form` 抽樣——比 `Entity.name`
    本身更貼近真實 mention（含尚未被 PROMOTE 成標準名的別名字面）。"""
    result = await driver.execute_query(
        "MATCH (:Chunk {kg_id: $kg_id})-[r:HAS_ENTITY]->(:Entity {kg_id: $kg_id}) "
        "RETURN DISTINCT r.surface_form AS mention",
        kg_id=str(kg_id),
    )
    pool = [r["mention"] for r in result.records if r["mention"]]
    random.Random(seed).shuffle(pool)
    return pool[:n]


def _kg_is_idle(kg_id: UUID) -> tuple[bool, int]:
    db_path = task_queue_db_path()
    if not db_path.exists():
        return True, 0
    conn = sqlite3.connect(str(db_path))
    try:
        n = conn.execute(
            "SELECT count(*) FROM task_queue WHERE kg_id = ? AND status IN ('pending', 'processing')",
            (str(kg_id),),
        ).fetchone()[0]
    finally:
        conn.close()
    return n == 0, n


async def _main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kg_id", type=UUID)
    ap.add_argument("--setup-only", action="store_true", help="只建索引＋補齊 name_embedding，不跑比較")
    ap.add_argument("--sample-size", type=int, default=300)
    ap.add_argument("--canopy-k", type=int, default=50)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--force", action="store_true", help="略過 KG 穩定終態檢查（僅供乾跑腳本邏輯）")
    ap.add_argument("--out", type=Path, default=Path("compare_entity_candidate_recall_result.json"))
    args = ap.parse_args()

    init_providers()
    await connect()
    driver = get_driver()
    embedding_provider = get_embedding_provider()

    try:
        print(f"[setup] 建 {ENTITY_NAME_VECTOR_INDEX} 向量索引（dim={embedding_provider.dim}）…")
        await create_entity_name_vector_index(driver, embedding_provider.dim)
        fulltext_ok = await create_entity_name_fulltext_index(driver)
        print(f"[setup] fulltext 索引{'已建立' if fulltext_ok else '不支援，比較時退回 CONTAINS'}")
        backfilled = await backfill_entity_name_embeddings(driver, args.kg_id, embedding_provider, limit=100000)
        print(f"[setup] 補齊 name_embedding：{backfilled} 個節點")

        if args.setup_only:
            print("[setup] --setup-only：完成，不跑比較。")
            return 0

        idle, pending = _kg_is_idle(args.kg_id)
        if not idle and not args.force:
            print(
                f"[FAIL] KG {args.kg_id} 仍有 {pending} 個 pending/processing chunk——"
                "新舊候選集在背景寫入中不可比。等 DRAIN-DONE 再跑，或 --force 僅乾跑腳本邏輯。"
            )
            return 1
        if not idle:
            print(f"[WARN] --force：略過穩定終態檢查（仍有 {pending} 個未完成 chunk），結果僅供乾跑參考。")

        mentions = await _sample_mentions(driver, args.kg_id, args.sample_size, args.seed)
        print(f"[compare] 抽樣 {len(mentions)} 個真實 mention（來自 HAS_ENTITY.surface_form）")

        results: list[MentionResult] = []
        for i, mention in enumerate(mentions, start=1):
            old_candidates = await _fetch_entity_candidates(driver, args.kg_id, None, mention)
            new_candidates = await _fetch_candidates_canopy(
                driver, args.kg_id, mention, canopy_k=args.canopy_k, fulltext_available=fulltext_ok,
            )

            old_resolved = await resolve_entity_name(
                mention, old_candidates, embedding_provider=embedding_provider, llm_provider=None,
            )
            new_resolved = await resolve_entity_name(
                mention, new_candidates, embedding_provider=embedding_provider, llm_provider=None,
            )

            # 灰色地帶粗旗標：任一邊有候選 cosine 落在 [ESCALATE_LOW, COSINE) 之間
            # （resolve_entity_name 無 llm_provider 時對這類候選直接放行不合併，
            # 兩邊在這裡本來就可能因為「有沒有 llm_provider」而與正式管線不同，
            # 故只做旗標、不計入 agree/disagree 的正式統計，見腳本 docstring）。
            from core.constants import ENTITY_DEDUP_COSINE_THRESHOLD, ENTITY_DEDUP_ESCALATE_LOW_THRESHOLD
            grey = False
            for cands in (old_candidates, new_candidates):
                for c in cands:
                    if c["name"] == mention or c.get("name_embedding") is None:
                        continue
                    score = cosine_similarity(await embedding_provider.encode(mention), c["name_embedding"])
                    if ENTITY_DEDUP_ESCALATE_LOW_THRESHOLD <= score < ENTITY_DEDUP_COSINE_THRESHOLD:
                        grey = True
                        break
                if grey:
                    break

            results.append(MentionResult(
                mention=mention,
                old_candidate_count=len(old_candidates),
                new_candidate_count=len(new_candidates),
                old_resolved=old_resolved,
                new_resolved=new_resolved,
                agree=(old_resolved == new_resolved),
                grey_zone=grey,
            ))
            if i % 50 == 0:
                print(f"[compare] {i}/{len(mentions)}…")

        disagreements = [r for r in results if not r.agree]
        grey_zone_hits = [r for r in results if r.grey_zone]
        avg_old = sum(r.old_candidate_count for r in results) / len(results) if results else 0
        avg_new = sum(r.new_candidate_count for r in results) / len(results) if results else 0

        print()
        print(f"===== 報告40 §7 recall 對照結果（KG {args.kg_id}）=====")
        print(f"樣本數：{len(results)}")
        print(f"一致：{len(results) - len(disagreements)}（{(1 - len(disagreements)/len(results))*100:.1f}%）" if results else "無樣本")
        print(f"不一致：{len(disagreements)} —— 需逐案分類（見報告40 §7 步驟2：漏掉真merge / 避開錯merge / tie-break）")
        print(f"灰色地帶命中（旗標，不計入一致率）：{len(grey_zone_hits)}")
        print(f"平均候選數：舊 {avg_old:.1f} → 新 {avg_new:.1f}（縮小 {(1 - avg_new/avg_old)*100:.1f}%）" if avg_old else "")
        if disagreements:
            print("\n前 10 筆不一致（供人工分類）：")
            for r in disagreements[:10]:
                print(f"  「{r.mention}」：舊→「{r.old_resolved}」({r.old_candidate_count} 候選) "
                      f"vs 新→「{r.new_resolved}」({r.new_candidate_count} 候選)")

        args.out.write_text(
            json.dumps({
                "kg_id": str(args.kg_id),
                "sample_size": len(results),
                "canopy_k": args.canopy_k,
                "fulltext_used": fulltext_ok,
                "agreement_rate": (1 - len(disagreements) / len(results)) if results else None,
                "disagreements": [asdict(r) for r in disagreements],
                "grey_zone_count": len(grey_zone_hits),
                "avg_old_candidates": avg_old,
                "avg_new_candidates": avg_new,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n完整結果已寫入 {args.out}")

        return 1 if disagreements and not args.force else 0
    finally:
        await disconnect()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
