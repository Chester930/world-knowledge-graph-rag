from __future__ import annotations
from uuid import UUID

from fastapi import APIRouter, HTTPException

from core.config import task_queue_db_path
from core.database import get_driver
from core.providers.factory import get_embedding_provider, get_llm_provider
from models.knowledge_graph import ExpandProposal, ExpandProposalResolveRequest
from services import expand_governance_service, expand_worker

router = APIRouter(prefix="/expand", tags=["expand"])


@router.get("/proposals", response_model=list[ExpandProposal])
async def list_proposals(kg_id: UUID | None = None):
    """`HUMANCHECK` 審核介面資料來源：對應 3.1.3 §a `list_awaiting_review()`。"""
    return expand_governance_service.list_awaiting_review(
        task_queue_db_path(), str(kg_id) if kg_id is not None else None,
    )


@router.post("/proposals/{proposal_id}/resolve", status_code=204)
async def resolve_proposal(proposal_id: int, payload: ExpandProposalResolveRequest):
    """人工核准／駁回一筆待審提案。核准時緊接著觸發 `COMMIT`＋`BACKFILL`
    （`expand_worker.commit_and_backfill()`，與 `run_governance_cycle()` 的
    `AUTOAPPROVE` 分支共用同一段邏輯）；駁回時只更新提案狀態，不動候選池
    （候選動詞先前判定為構成新類別的結論本身沒有錯，只是這次人工不核准
    這個命名／型別，維持 `pending` 讓未來治理週期仍有機會重新分群判斷）。
    """
    db_path = task_queue_db_path()
    proposal = expand_governance_service.get_proposal(db_path, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="提案不存在")
    if proposal["status"] != "awaiting_review":
        raise HTTPException(status_code=409, detail=f"提案已審核過（目前狀態：{proposal['status']}）")

    expand_governance_service.resolve_proposal(db_path, proposal_id, payload.decision)

    if payload.decision == "approved":
        await expand_worker.commit_and_backfill(
            get_driver(), UUID(proposal["kg_id"]), get_embedding_provider(), get_llm_provider(),
            type_name=proposal["suggested_type_name"],
            description=proposal["suggested_description"],
            member_verbs=proposal["member_verbs"],
            reused_from_registry=proposal["reused_from_registry"],
        )
