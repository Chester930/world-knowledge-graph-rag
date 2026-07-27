from uuid import uuid4

import pytest
from fastapi import HTTPException

from core import config
from models.knowledge_graph import ExpandProposalResolveRequest
from routers import expand
from services import expand_governance_service


@pytest.mark.asyncio
async def test_list_proposals_returns_awaiting_review(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    expand_governance_service.create_proposal(
        config.task_queue_db_path(), str(uuid4()), ["導致惡化"], "AGGRAVATES", "描述",
    )

    result = await expand.list_proposals(kg_id=None)

    assert len(result) == 1
    assert result[0]["suggested_type_name"] == "AGGRAVATES"


@pytest.mark.asyncio
async def test_list_proposals_filters_by_kg_id(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    kg_id_a = uuid4()
    kg_id_b = uuid4()
    db_path = config.task_queue_db_path()
    expand_governance_service.create_proposal(db_path, str(kg_id_a), ["A"], "TYPE_A", "描述")
    expand_governance_service.create_proposal(db_path, str(kg_id_b), ["B"], "TYPE_B", "描述")

    result = await expand.list_proposals(kg_id=kg_id_a)

    assert len(result) == 1
    assert result[0]["suggested_type_name"] == "TYPE_A"


@pytest.mark.asyncio
async def test_resolve_proposal_rejected_updates_status_without_commit(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    db_path = config.task_queue_db_path()
    proposal_id = expand_governance_service.create_proposal(
        db_path, "kg-1", ["導致惡化"], "AGGRAVATES", "描述",
    )
    commit_calls = []
    monkeypatch.setattr(
        "routers.expand.expand_worker.commit_and_backfill",
        lambda *a, **k: commit_calls.append((a, k)),
    )

    await expand.resolve_proposal(proposal_id, ExpandProposalResolveRequest(decision="rejected"))

    assert commit_calls == []
    proposal = expand_governance_service.get_proposal(db_path, proposal_id)
    assert proposal["status"] == "rejected"


@pytest.mark.asyncio
async def test_resolve_proposal_approved_triggers_commit_and_backfill(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    db_path = config.task_queue_db_path()
    kg_id = uuid4()
    proposal_id = expand_governance_service.create_proposal(
        db_path, str(kg_id), ["導致惡化"], "AGGRAVATES", "A 使 B 惡化",
    )

    commit_calls = []

    async def _fake_commit(driver, kg_id_arg, embedding_provider, llm_provider, **kwargs):
        commit_calls.append((kg_id_arg, kwargs))
        return 1

    monkeypatch.setattr("routers.expand.expand_worker.commit_and_backfill", _fake_commit)
    monkeypatch.setattr("routers.expand.get_driver", lambda: "fake-driver")
    monkeypatch.setattr("routers.expand.get_embedding_provider", lambda: "fake-embedding")
    monkeypatch.setattr("routers.expand.get_llm_provider", lambda: "fake-llm")

    await expand.resolve_proposal(proposal_id, ExpandProposalResolveRequest(decision="approved"))

    assert len(commit_calls) == 1
    assert commit_calls[0][0] == kg_id
    assert commit_calls[0][1]["type_name"] == "AGGRAVATES"
    assert commit_calls[0][1]["member_verbs"] == ["導致惡化"]
    assert commit_calls[0][1]["reused_from_registry"] is False

    proposal = expand_governance_service.get_proposal(db_path, proposal_id)
    assert proposal["status"] == "approved"


@pytest.mark.asyncio
async def test_resolve_proposal_missing_raises_404(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))

    with pytest.raises(HTTPException) as exc_info:
        await expand.resolve_proposal(999, ExpandProposalResolveRequest(decision="approved"))
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_resolve_proposal_already_resolved_raises_409(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    db_path = config.task_queue_db_path()
    proposal_id = expand_governance_service.create_proposal(db_path, "kg-1", ["A"], "TYPE_A", "描述")
    expand_governance_service.resolve_proposal(db_path, proposal_id, "rejected")

    with pytest.raises(HTTPException) as exc_info:
        await expand.resolve_proposal(proposal_id, ExpandProposalResolveRequest(decision="approved"))
    assert exc_info.value.status_code == 409
