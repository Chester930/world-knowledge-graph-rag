"""Read-only trace of AGGR16 Fact candidates and prompt-list truncation."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import UUID

from core.config import settings
from core.database import connect, disconnect, get_driver
from core.kg_config import ConfigLoader, FileConfigSource
from core.providers.embedding.ollama import OllamaEmbeddingProvider
from repositories.kg_repo import KGRepository
from scripts.eval.run_rq1_comparison import _resolve_scope
from services.svo_service import (
    FACT_SEARCH_CANDIDATE_MULTIPLIER,
    _dedupe_facts_by_key,
    _fact_vector_index_name,
    _filter_fact_candidates_by_source_scope,
    classify_relation_by_embedding,
)

import routers.agent as agent


KG_ID = UUID("236903cf-055a-40a8-8923-b9d06601f3b7")
DOC_NAMES = [
    "N0060027_職業安全衛生管理辦法",
    "N0060001_職業安全衛生法",
]
QUESTION_ID = "57-AGGR16"
TARGET_PARTS = ("第二類事業", "中度風險")
TOP_K = 25


def _target(record: dict) -> bool:
    text = record.get("fact_text") or ""
    return all(part in text for part in TARGET_PARTS)


async def main() -> None:
    dataset_path = Path("data/eval/test_cases.json")
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    test_case = next(q for q in dataset["questions"] if q["id"] == QUESTION_ID)
    question = test_case["question"]
    kg_id = KG_ID

    embedding = OllamaEmbeddingProvider(
        base_url=settings.ollama_base_url,
        model=settings.ollama_embedding_model,
        num_gpu=settings.ollama_embedding_num_gpu,
    )

    await connect()
    try:
        driver = get_driver()
        kg_meta = await KGRepository(driver).get(kg_id)
        cfg = ConfigLoader([FileConfigSource(settings.kg_config_dir)]).load(
            kg_id, domain_pack=kg_meta.domain_pack if kg_meta is not None else None,
        )
        explicit_scope_ids, _ = _resolve_scope(kg_id, DOC_NAMES)
        question_vector = await embedding.encode(question)
        seeds = await agent._find_seed_entities(
            driver,
            kg_id,
            question,
            embedding_provider=embedding,
            question_vector=question_vector,
            cfg=cfg,
        )
        seed_doc_ids = await agent._relevant_doc_ids_from_seeds(driver, kg_id, seeds)
        allowed_source_doc_ids = agent._resolve_doc_scope(
            seed_doc_ids, set(), explicit_scope_ids,
        )

        candidate_k = TOP_K * FACT_SEARCH_CANDIDATE_MULTIPLIER
        index_name = _fact_vector_index_name(str(kg_id))
        raw_result = await driver.execute_query(
            f"""
            CALL db.index.vector.queryNodes('{index_name}', $candidate_k, $vector)
            YIELD node, score
            RETURN elementId(node) AS fact_id,
                   node.fact_text AS fact_text,
                   node.subject AS subject,
                   node.object AS object,
                   node.rel_type AS rel_type,
                   node.source_doc_id AS source_doc_id,
                   score
            ORDER BY score DESC
            """,
            candidate_k=candidate_k,
            vector=question_vector,
        )
        raw_candidates = [dict(record) for record in raw_result.records]
        scoped = _filter_fact_candidates_by_source_scope(
            raw_candidates, allowed_source_doc_ids,
        )
        deduped = _dedupe_facts_by_key(scoped)

        baseline_result = await driver.execute_query(
            f"""
            CALL db.index.vector.queryNodes('{index_name}', $candidate_k, $vector)
            YIELD node, score
            RETURN elementId(node) AS fact_id,
                   node.fact_text AS fact_text,
                   node.subject AS subject,
                   node.object AS object,
                   node.rel_type AS rel_type,
                   node.source_doc_id AS source_doc_id,
                   score
            ORDER BY score DESC
            """,
            candidate_k=20 * FACT_SEARCH_CANDIDATE_MULTIPLIER,
            vector=question_vector,
        )
        baseline_raw = [dict(record) for record in baseline_result.records]
        baseline_scoped = _filter_fact_candidates_by_source_scope(
            baseline_raw, allowed_source_doc_ids,
        )
        baseline_deduped = _dedupe_facts_by_key(baseline_scoped)
        top20 = deduped[:20]
        top25 = deduped[:TOP_K]
        returned_facts = [
            {key: value for key, value in record.items() if key != "fact_id"}
            for record in top25
        ]
        _, fact_lines = agent._split_fact_lines([], returned_facts)
        fact_only_assembled = await agent._arrange_fact_lines(
            question,
            [],
            fact_lines,
            embedding_provider=embedding,
            question_vector=question_vector,
            cfg=cfg,
        )

        semantic_doc_ids = agent._relevant_doc_ids_from_facts(
            returned_facts, top_n=cfg.bfs.doc_scope_top_n_facts,
        )
        bfs_scope_doc_ids = agent._resolve_doc_scope(
            seed_doc_ids, semantic_doc_ids, explicit_scope_ids,
        )
        bfs_triples = await agent.bfs_query(
            driver,
            kg_id,
            seeds,
            hops=1,
            scope_doc_ids=bfs_scope_doc_ids or None,
            per_seed_limit=cfg.bfs.per_seed_limit,
            cfg=cfg,
        )
        bfs_lines, _ = agent._split_fact_lines(bfs_triples, [])
        best_rel_type, best_rel_score = await classify_relation_by_embedding(
            question, embedding,
        )
        if best_rel_score >= cfg.reltype.qsim_assign_threshold:
            resolved_rel_type = best_rel_type
            relation_filter_mode = "embedding_confident"
            filtered_bfs_lines = agent._split_fact_lines(
                agent._filter_triples_by_relation_type(bfs_triples, resolved_rel_type), [],
            )[0]
        elif best_rel_score < cfg.reltype.qsim_escalate_low_threshold:
            resolved_rel_type = None
            relation_filter_mode = "no_match"
            filtered_bfs_lines = bfs_lines
        else:
            resolved_rel_type = None
            relation_filter_mode = "would_require_llm_confirmation"
            filtered_bfs_lines = bfs_lines
        filtered_bfs_triples = agent._filter_triples_by_source_doc_ids(
            agent._filter_triples_by_relation_type(bfs_triples, resolved_rel_type),
            bfs_scope_doc_ids,
        )
        filtered_bfs_lines, combined_fact_lines = agent._split_fact_lines(
            filtered_bfs_triples, returned_facts,
        )
        combined_assembled = await agent._arrange_fact_lines(
            question,
            filtered_bfs_lines,
            combined_fact_lines,
            embedding_provider=embedding,
            question_vector=question_vector,
            cfg=cfg,
        )
        ranked_filtered_bfs_all = await agent._score_lines_by_embedding(
            question,
            filtered_bfs_lines,
            embedding_provider=embedding,
            question_vector=question_vector,
        )
        ranked_filtered_bfs = ranked_filtered_bfs_all[:cfg.factlist.bfs_keep_max]
        bfs_target_lines = [line for line in bfs_lines if all(p in line for p in TARGET_PARTS)]
        bfs_target_ranked_lines = [
            line for line in ranked_filtered_bfs if all(p in line for p in TARGET_PARTS)
        ]
        combined_target_line = next(
            ((index + 1, line) for index, line in enumerate(combined_assembled) if all(p in line for p in TARGET_PARTS)),
            None,
        )
        bfs_target_full_rank = next(
            (index + 1 for index, line in enumerate(ranked_filtered_bfs_all) if all(p in line for p in TARGET_PARTS)),
            None,
        )
        combined_total = len(ranked_filtered_bfs) + len(combined_fact_lines)
        if combined_total <= cfg.factlist.truncate_k:
            allocated_target = combined_total
            allocated_bfs = len(ranked_filtered_bfs)
        else:
            allocated_target = (
                cfg.factlist.truncate_k
                if combined_total <= cfg.factlist.reorder_threshold_k
                else cfg.factlist.reorder_threshold_k
            )
            allocated_bfs = min(
                len(ranked_filtered_bfs),
                max(cfg.factlist.min_bfs_slots, allocated_target - len(combined_fact_lines)),
            )
        allocated_facts = min(len(combined_fact_lines), allocated_target - allocated_bfs)
        allocated_bfs_target = (
            bfs_target_full_rank is not None and bfs_target_full_rank <= allocated_bfs
        )
        allocated_fact_target = any(
            all(part in line for part in TARGET_PARTS)
            for line in combined_fact_lines[:allocated_facts]
        )

        raw_target = next(
            ((index + 1, record) for index, record in enumerate(raw_candidates) if _target(record)),
            None,
        )
        scoped_target = next(
            ((index + 1, record) for index, record in enumerate(scoped) if _target(record)),
            None,
        )
        deduped_target = next(
            ((index + 1, record) for index, record in enumerate(deduped) if _target(record)),
            None,
        )
        prompt_target = next(
            ((index + 1, line) for index, line in enumerate(fact_only_assembled) if all(p in line for p in TARGET_PARTS)),
            None,
        )

        result = {
            "question_id": QUESTION_ID,
            "question": question,
            "embedding_model": embedding.model_name,
            "kg_id": str(kg_id),
            "explicit_scope_doc_ids": [str(value) for value in explicit_scope_ids],
            "seed_entities": seeds,
            "seed_scope_doc_ids": sorted(str(value) for value in seed_doc_ids),
            "effective_fact_scope_doc_ids": sorted(str(value) for value in allowed_source_doc_ids),
            "candidate_pool_k": candidate_k,
            "raw_candidate_count": len(raw_candidates),
            "raw_target": ({"rank": raw_target[0], **raw_target[1]} if raw_target else None),
            "scoped_candidate_count": len(scoped),
            "scoped_target": ({"rank": scoped_target[0], **scoped_target[1]} if scoped_target else None),
            "deduped_candidate_count": len(deduped),
            "deduped_target": ({"rank": deduped_target[0], **deduped_target[1]} if deduped_target else None),
            "top20_contains_target": any(_target(record) for record in top20),
            "top25_contains_target": any(_target(record) for record in top25),
            "baseline_top20_candidate_pool_k": len(baseline_raw),
            "baseline_top20_target_rank_after_scope_dedupe": next(
                (index + 1 for index, record in enumerate(baseline_deduped) if _target(record)),
                None,
            ),
            "baseline_top20_fact_candidates_contain_target": any(
                _target(record) for record in baseline_deduped[:20]
            ),
            "retrieved_fact_line_count": len(fact_lines),
            "factlist_truncate_k": cfg.factlist.truncate_k,
            "factlist_reorder_threshold_k": cfg.factlist.reorder_threshold_k,
            "factlist_min_bfs_slots": cfg.factlist.min_bfs_slots,
            "bfs_line_count_after_relation_filter": len(filtered_bfs_lines),
            "fact_line_count_after_bfs_dedupe": len(combined_fact_lines),
            "combined_input_line_count": len(filtered_bfs_lines) + len(combined_fact_lines),
            "assembly_allocated_total_k": allocated_target,
            "assembly_allocated_bfs_slots": allocated_bfs,
            "assembly_allocated_fact_slots": allocated_facts,
            "target_in_allocated_bfs_candidates": allocated_bfs_target,
            "target_in_allocated_fact_candidates": allocated_fact_target,
            "target_rank_in_bfs_relevance_order": bfs_target_full_rank,
            "fact_only_assembled_line_count": len(fact_only_assembled),
            "target_line_in_fact_only_assembly": prompt_target is not None,
            "target_prompt_rank_without_bfs": prompt_target[0] if prompt_target else None,
            "combined_assembled_line_count": len(combined_assembled),
            "target_line_in_combined_assembly_without_llm_generation": combined_target_line is not None,
            "target_combined_prompt_rank_without_llm_generation": combined_target_line[0] if combined_target_line else None,
            "bfs_scope_doc_ids": sorted(str(value) for value in bfs_scope_doc_ids),
            "bfs_triple_count_before_relation_filter": len(bfs_triples),
            "bfs_line_count_before_relation_filter": len(bfs_lines),
            "bfs_target_lines_before_relation_filter": bfs_target_lines,
            "relation_type_best_candidate": best_rel_type,
            "relation_type_embedding_score": round(float(best_rel_score), 7),
            "relation_type_assign_threshold": cfg.reltype.qsim_assign_threshold,
            "relation_type_escalate_low_threshold": cfg.reltype.qsim_escalate_low_threshold,
            "relation_filter_mode_without_llm": relation_filter_mode,
            "resolved_relation_type_without_llm": resolved_rel_type,
            "bfs_target_lines_after_relation_filter": bfs_target_ranked_lines,
            "bfs_kept_line_count": len(ranked_filtered_bfs),
            "bfs_minimum_reserved_slots": min(len(ranked_filtered_bfs), cfg.factlist.min_bfs_slots),
            "read_only_note": "Direct vector-index query and in-memory replay of scope, dedupe, and fact-line assembly; BFS and relation classification use read-only graph/embedding queries; no LLM generation and no graph data writes.",
            "retrieved_ranks_16_to_25": [
                {
                    "rank": rank,
                    "score": round(float(record.get("score") or 0), 7),
                    "fact_text": record.get("fact_text"),
                    "is_target": _target(record),
                }
                for rank, record in enumerate(deduped[15:25], start=16)
            ],
            "chat_pilot_missed_span": test_case["atomic_gold_facts"],
        }

        output_path = (
            Path(__file__).resolve().parents[3]
            / ".claude"
            / "tmp"
            / "rq1_fact_candidate_trace_20260918.json"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print(f"\nTRACE_JSON={output_path}")
    finally:
        await disconnect()


if __name__ == "__main__":
    asyncio.run(main())
