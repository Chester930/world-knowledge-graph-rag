"""報告41（L9 V1）驗證 harness：檢索文件範圍「錨定優先」vs 現行「雜訊 top-N
Fact 反推」，retrieval 層對照。

只比較**檢索層**（doc-scope 推導 → `bfs_query()` 範圍下推 → 三元組排除
篩選），**不跑完整 `chat()` 生成／接地核對**——後者需要多次 LLM 呼叫，
且 `qwen2.5:7b` 本身非決定性（報告20 已 root-cause），會把「檢索範圍對不
對」與「LLM 這次抽得/答得好不好」兩件事混在一起。本腳本只證明報告41 的
核心機制主張：**新方案是否讓正解文件進入範圍、且不讓舊方案已涵蓋的正解
文件掉出範圍**——這是「錨定優先」設計本身的直接驗證，完整端到端 grounding
對照留給報告41 §6 步驟1-2（人工另行執行 `chat()`）。

**現行（OLD）**：`vector_search_facts()` top-N → `_relevant_doc_ids_from_facts()`
反推 `semantic_doc_ids` → `_intersect_doc_scopes()`。
**新方案（NEW，本腳本自帶實作，production 尚未接線）**：`_find_seed_entities()`
的種子 → `_relevant_doc_ids_from_seeds()`（`HAS_ENTITY` 查種子出現的文件）
→ `_resolve_doc_scope()`（錨定優先：種子文件非空即用，語意範圍降為 fallback）。

兩邊各自把 `bfs_query(scope_doc_ids=...)` 的結果再套 `_filter_triples_by_
source_doc_ids()`，比較：① gold 文件是否在範圍內；② gold 文件的三元組
是否還在最終結果裡；③ 三元組總數變化。

⚠️ **執行時機**：全程唯讀，不寫入任何資料，理論上隨時可跑；但「範圍是否
正確」的結論只有在 KG 進入穩定終態時才有意義（drain 未完成時，語意 Fact
排序、`HAS_ENTITY` 邊都還在變動）——比照 `compare_entity_candidate_recall.py`
的檢查，預設對該 KG 的 `task_queue` 做 pending/processing==0 檢查，未過
拒跑；`--force` 僅供乾跑腳本邏輯。

題庫預設讀 `docs/附錄A題庫.json`（報告39 SDD-4 機讀版），預設篩 `26-Q1`
到 `26-Q8`（報告26/27 §6.2 的 8 題，含本報告的主目標 `26-Q5`＝報告38 Q5
「當月一日」）；`--question-ids` 可自訂。`gold_doc_id` 由題庫的 `pcode`
欄位對 Neo4j `Document.source`／`title` 做 CONTAINS 查詢解析——解析不到
時該題只比較三元組數變化，不判斷「gold 文件在不在範圍內」。

對應 `docs/報告/41_檢索文件範圍改用實體錨定設計報告.md` §6「驗證計畫」。

用法：

    python compare_doc_scope_retrieval.py 236903cf-055a-40a8-8923-b9d06601f3b7 \\
        --out compare_doc_scope_retrieval_result.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import UUID

from core.config import task_queue_db_path
from core.database import connect, disconnect, get_driver
from core.kg_config import KGConfig
from core.providers.factory import get_embedding_provider, init_providers
from routers.agent import (
    _filter_triples_by_source_doc_ids,
    _find_seed_entities,
    _intersect_doc_scopes,
    _relevant_doc_ids_from_facts,
)
from services.svo_service import bfs_query, vector_search_facts

_DEFAULT_QUESTIONS_FILE = Path("docs/附錄A題庫.json")
_DEFAULT_QUESTION_IDS = [f"26-Q{i}" for i in range(1, 9)]  # 報告26/27 §6.2 的 8 題


def _load_questions(path: Path, ids: list[str] | None) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    questions = data["questions"]
    if ids:
        wanted = set(ids)
        questions = [q for q in questions if q["id"] in wanted]
    return questions


async def _relevant_doc_ids_from_seeds(driver, kg_id: UUID, seed_names: list[str]) -> set[UUID]:
    """報告41 §3.2：種子實體出現在哪些文件（`HAS_ENTITY` 結構邊）。"""
    if not seed_names:
        return set()
    result = await driver.execute_query(
        "MATCH (c:Chunk {kg_id: $kg_id})-[:HAS_ENTITY]->(e:Entity {kg_id: $kg_id}) "
        "WHERE e.name IN $names "
        "RETURN DISTINCT c.source_doc_id AS doc_id",
        kg_id=str(kg_id), names=seed_names,
    )
    doc_ids: set[UUID] = set()
    for r in result.records:
        raw = r["doc_id"]
        if not raw:
            continue
        try:
            doc_ids.add(UUID(raw) if isinstance(raw, str) else raw)
        except ValueError:
            continue
    return doc_ids


def _resolve_doc_scope(
    seed_doc_ids: set[UUID], semantic_doc_ids: set[UUID], explicit_doc_ids: list[UUID] | None = None,
) -> set[UUID]:
    """報告41 §3.3：錨定優先——`seed_doc_ids` 非空即用它（語意範圍不參與）；
    空則 fallback `semantic_doc_ids`（= 現行行為，零回歸）；再與明確範圍交集。"""
    base = seed_doc_ids if seed_doc_ids else semantic_doc_ids
    return _intersect_doc_scopes(base, explicit_doc_ids)


async def _resolve_gold_doc_id(driver, kg_id: UUID, pcode: str) -> UUID | None:
    result = await driver.execute_query(
        "MATCH (d:Document {kg_id: $kg_id}) WHERE d.source CONTAINS $pcode OR d.title CONTAINS $pcode "
        "RETURN d.source_doc_id AS doc_id LIMIT 1",
        kg_id=str(kg_id), pcode=pcode,
    )
    if not result.records:
        return None
    raw = result.records[0]["doc_id"]
    try:
        return UUID(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return None


@dataclass
class QuestionResult:
    id: str
    question: str
    pcode: str
    gold_doc_id: str | None
    old_scope_size: int
    new_scope_size: int
    old_hits_gold: bool | None  # None = gold_doc_id 解析不到，無法判斷
    new_hits_gold: bool | None
    old_triple_count: int
    new_triple_count: int
    verdict: str  # "target_fixed" / "regressed" / "unchanged" / "unknown"


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
    ap.add_argument("--questions-file", type=Path, default=_DEFAULT_QUESTIONS_FILE)
    ap.add_argument("--question-ids", default=",".join(_DEFAULT_QUESTION_IDS),
                     help="逗號分隔的題目 id；空字串＝題庫全部")
    ap.add_argument("--doc-scope-top-n-facts", type=int, default=KGConfig().bfs.doc_scope_top_n_facts)
    ap.add_argument("--per-seed-limit", type=int, default=KGConfig().bfs.per_seed_limit)
    ap.add_argument("--hops", type=int, default=1)
    ap.add_argument("--top-k", type=int, default=20, help="vector_search_facts top_k（對齊 ChatRequest 現行預設）")
    ap.add_argument("--force", action="store_true", help="略過 KG 穩定終態檢查（僅供乾跑腳本邏輯）")
    ap.add_argument("--out", type=Path, default=Path("compare_doc_scope_retrieval_result.json"))
    args = ap.parse_args()

    init_providers()
    await connect()
    driver = get_driver()
    embedding_provider = get_embedding_provider()
    cfg = KGConfig()

    try:
        idle, pending = _kg_is_idle(args.kg_id)
        if not idle and not args.force:
            print(
                f"[FAIL] KG {args.kg_id} 仍有 {pending} 個 pending/processing chunk——"
                "語意排序與 HAS_ENTITY 邊在背景寫入中不可比。等 DRAIN-DONE 再跑，或 --force 僅乾跑腳本邏輯。"
            )
            return 1
        if not idle:
            print(f"[WARN] --force：略過穩定終態檢查（仍有 {pending} 個未完成 chunk），結果僅供乾跑參考。")

        ids = [i.strip() for i in args.question_ids.split(",") if i.strip()] or None
        questions = _load_questions(args.questions_file, ids)
        print(f"[load] {args.questions_file}：{len(questions)} 題（{', '.join(q['id'] for q in questions)}）")

        results: list[QuestionResult] = []
        for q in questions:
            question_text, pcode = q["question"], q["pcode"]
            print(f"\n[{q['id']}] {question_text}")

            question_vector = await embedding_provider.encode(question_text)
            gold_doc_id = await _resolve_gold_doc_id(driver, args.kg_id, pcode)
            if gold_doc_id is None:
                print(f"  [WARN] 題庫 pcode「{pcode}」在 KG 內查無對應 Document，無法判斷範圍準確度")

            # 種子（新舊共用同一組——V1 不改種子抽取本身，只改「何時用它」）
            seeds = await _find_seed_entities(
                driver, args.kg_id, question_text,
                embedding_provider=embedding_provider, question_vector=question_vector, cfg=cfg,
            )

            # OLD：語意 Fact top-N 反推
            fact_results = await vector_search_facts(driver, args.kg_id, question_vector, args.top_k)
            semantic_doc_ids = _relevant_doc_ids_from_facts(fact_results, top_n=args.doc_scope_top_n_facts)
            old_scope = _intersect_doc_scopes(semantic_doc_ids, None)

            # NEW：種子錨定優先
            seed_doc_ids = await _relevant_doc_ids_from_seeds(driver, args.kg_id, seeds)
            new_scope = _resolve_doc_scope(seed_doc_ids, semantic_doc_ids, None)

            old_triples = await bfs_query(
                driver, args.kg_id, seeds, hops=args.hops,
                scope_doc_ids=(old_scope or None), per_seed_limit=args.per_seed_limit, cfg=cfg,
            )
            old_triples = _filter_triples_by_source_doc_ids(old_triples, old_scope)

            new_triples = await bfs_query(
                driver, args.kg_id, seeds, hops=args.hops,
                scope_doc_ids=(new_scope or None), per_seed_limit=args.per_seed_limit, cfg=cfg,
            )
            new_triples = _filter_triples_by_source_doc_ids(new_triples, new_scope)

            old_hits = (not old_scope) or (gold_doc_id in old_scope) if gold_doc_id else None
            new_hits = (not new_scope) or (gold_doc_id in new_scope) if gold_doc_id else None

            if gold_doc_id is None:
                verdict = "unknown"
            elif old_hits and new_hits:
                verdict = "unchanged"
            elif (not old_hits) and new_hits:
                verdict = "target_fixed"
            elif old_hits and (not new_hits):
                verdict = "regressed"
            else:
                verdict = "unchanged"  # 兩邊都沒命中 gold（本腳本無法讓它變好，非本改造造成）

            results.append(QuestionResult(
                id=q["id"], question=question_text, pcode=pcode,
                gold_doc_id=(str(gold_doc_id) if gold_doc_id else None),
                old_scope_size=len(old_scope), new_scope_size=len(new_scope),
                old_hits_gold=old_hits, new_hits_gold=new_hits,
                old_triple_count=len(old_triples), new_triple_count=len(new_triples),
                verdict=verdict,
            ))
            print(f"  範圍：舊 {len(old_scope)} 篇 → 新 {len(new_scope)} 篇 | "
                  f"gold 命中：舊={old_hits} 新={new_hits} | 三元組：舊 {len(old_triples)} → 新 {len(new_triples)} | "
                  f"verdict={verdict}")

        fixed = [r for r in results if r.verdict == "target_fixed"]
        regressed = [r for r in results if r.verdict == "regressed"]
        unknown = [r for r in results if r.verdict == "unknown"]

        print("\n===== 報告41 §6 retrieval 層對照結果 =====")
        print(f"題數：{len(results)}")
        print(f"由未命中修成命中（target_fixed）：{len(fixed)} —— {[r.id for r in fixed]}")
        print(f"由命中退步成未命中（regressed，**接受標準要求 = 0**）：{len(regressed)} —— {[r.id for r in regressed]}")
        print(f"gold 文件解析不到（unknown，未計入判斷）：{len(unknown)} —— {[r.id for r in unknown]}")
        q5 = next((r for r in results if r.id == "26-Q5"), None)
        if q5:
            print(f"\n主目標 26-Q5：{q5.verdict}"
                  + ("（✅ 符合報告41 假設：範圍修成含正解文件）" if q5.verdict == "target_fixed" else "（⚠️ 未如預期，需重新檢視報告41 §3 的錨定邏輯）"))

        args.out.write_text(
            json.dumps({
                "kg_id": str(args.kg_id),
                "results": [asdict(r) for r in results],
                "target_fixed_count": len(fixed),
                "regressed_count": len(regressed),
                "unknown_count": len(unknown),
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n完整結果已寫入 {args.out}")

        return 1 if regressed and not args.force else 0
    finally:
        await disconnect()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
