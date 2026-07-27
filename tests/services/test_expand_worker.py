from uuid import uuid4

import pytest

from core import config
from services import expand_governance_service, expand_worker as worker


class FakeLLM:
    def __init__(self, response: str):
        self.response = response
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


class SequencedFakeLLM:
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._responses.pop(0)


class FakeEmbedding:
    dim = 4
    model_name = "fake-expand-embedding"

    def __init__(self, vectors: dict[str, list[float]] | None = None, default: list[float] | None = None):
        self._vectors = vectors or {}
        self._default = default or [0.0, 0.0, 0.0, 1.0]

    def encode(self, text: str) -> list[float]:
        return self._vectors.get(text, self._default)

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.encode(t) for t in texts]


class SpyDriver:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def execute_query(self, query: str, **params):
        self.calls.append((query.strip(), params))
        return None


def _seed_pool(db_path, kg_id: str, count: int, prefix: str = "候選動詞") -> list[str]:
    verbs = [f"{prefix}{i}" for i in range(count)]
    for i, verb in enumerate(verbs):
        expand_governance_service.add_candidate(db_path, kg_id, verb, [0.0] * 4)
    return verbs


def _seed_graduated_history(db_path, kg_id: str, window: int, approved: int) -> None:
    """預先累積 `window` 筆已審核提案，`approved` 筆核准／其餘駁回，
    讓 `recent_agreement_rate()` 達到 GATE 畢業門檻。"""
    for i in range(window):
        proposal_id = expand_governance_service.create_proposal(
            db_path, kg_id, [f"歷史動詞{i}"], f"HIST_TYPE_{i}", "歷史提案",
        )
        decision = "approved" if i < approved else "rejected"
        expand_governance_service.resolve_proposal(db_path, proposal_id, decision)


# ── _parse_llmjudge_response ──────────────────────────────────────────────

def test_parse_llmjudge_response_parses_approved_judgement():
    raw = "判斷：是\n名稱：invests in\n說明：A 投入資金支持 B 的營運或成長"
    is_new, type_name, description = worker._parse_llmjudge_response(raw)
    assert is_new is True
    assert type_name == "INVESTS_IN"
    assert description == "A 投入資金支持 B 的營運或成長"


def test_parse_llmjudge_response_parses_rejection():
    is_new, type_name, description = worker._parse_llmjudge_response("判斷：否")
    assert (is_new, type_name, description) == (False, "", "")


def test_parse_llmjudge_response_treats_malformed_approval_as_rejection():
    """判斷「是」但缺少名稱或說明，視為格式不完整，保守判定為否。"""
    is_new, type_name, description = worker._parse_llmjudge_response("判斷：是\n名稱：INVESTS_IN")
    assert (is_new, type_name, description) == (False, "", "")


# ── run_governance_cycle：POOLSIZE／HASCLUSTER 閘門 ─────────────────────────

@pytest.mark.asyncio
async def test_run_governance_cycle_noop_when_pool_below_min_size(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    kg_id = uuid4()
    _seed_pool(config.task_queue_db_path(), str(kg_id), 3)
    llm = FakeLLM("判斷：是\n名稱：X\n說明：Y")

    await worker.run_governance_cycle(SpyDriver(), kg_id, FakeEmbedding(), llm)

    assert llm.prompts == []
    assert expand_governance_service.list_awaiting_review(config.task_queue_db_path()) == []


@pytest.mark.asyncio
async def test_run_governance_cycle_noop_when_no_stable_cluster_forms(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    kg_id = uuid4()
    _seed_pool(config.task_queue_db_path(), str(kg_id), 10)
    monkeypatch.setattr("services.expand_worker.cluster_vectors", lambda vectors: [-1] * len(vectors))
    llm = FakeLLM("判斷：是\n名稱：X\n說明：Y")

    await worker.run_governance_cycle(SpyDriver(), kg_id, FakeEmbedding(), llm)

    assert llm.prompts == []


# ── LLMJUDGE：discard 分支 ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_governance_cycle_discards_cluster_when_llmjudge_rejects(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    db_path = config.task_queue_db_path()
    kg_id = uuid4()
    verbs = _seed_pool(db_path, str(kg_id), 10)
    labels = [0, 0, 0] + [-1] * 7
    monkeypatch.setattr("services.expand_worker.cluster_vectors", lambda vectors: labels)
    llm = FakeLLM("判斷：否")

    await worker.run_governance_cycle(SpyDriver(), kg_id, FakeEmbedding(), llm)

    assert len(llm.prompts) == 1
    assert expand_governance_service.pool_size(db_path, str(kg_id)) == 7  # 3 個候選被 discard
    assert expand_governance_service.list_awaiting_review(db_path) == []
    remaining = {c["verb"] for c in expand_governance_service.pending_candidates(db_path, str(kg_id))}
    assert remaining == set(verbs[3:])


# ── REGCHECK：REUSE vs NEWTYPE ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_governance_cycle_reuses_similar_registered_type(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    db_path = config.task_queue_db_path()
    kg_id = uuid4()
    _seed_pool(db_path, str(kg_id), 10)
    monkeypatch.setattr("services.expand_worker.cluster_vectors", lambda vectors: [0] * 10)

    shared_vector = [1.0, 0.0, 0.0, 0.0]
    embedding = FakeEmbedding(vectors={"A 投入資金支持 B": shared_vector})
    expand_governance_service.register_type(
        db_path, "EXISTING_TYPE", "既有登記型別描述", shared_vector, "other-kg",
    )
    llm = FakeLLM("判斷：是\n名稱：INVESTS_IN\n說明：A 投入資金支持 B")

    await worker.run_governance_cycle(SpyDriver(), kg_id, embedding, llm)

    proposals = expand_governance_service.list_awaiting_review(db_path)
    assert len(proposals) == 1
    assert proposals[0]["suggested_type_name"] == "EXISTING_TYPE"
    assert proposals[0]["reused_from_registry"] is True


@pytest.mark.asyncio
async def test_run_governance_cycle_proposes_new_type_when_no_registry_match(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    db_path = config.task_queue_db_path()
    kg_id = uuid4()
    _seed_pool(db_path, str(kg_id), 10)
    monkeypatch.setattr("services.expand_worker.cluster_vectors", lambda vectors: [0] * 10)
    llm = FakeLLM("判斷：是\n名稱：INVESTS_IN\n說明：A 投入資金支持 B")

    await worker.run_governance_cycle(SpyDriver(), kg_id, FakeEmbedding(), llm)

    proposals = expand_governance_service.list_awaiting_review(db_path)
    assert len(proposals) == 1
    assert proposals[0]["suggested_type_name"] == "INVESTS_IN"
    assert proposals[0]["reused_from_registry"] is False


# ── GATE：HUMANCHECK vs AUTOAPPROVE ───────────────────────────────────────

@pytest.mark.asyncio
async def test_run_governance_cycle_awaits_human_review_when_not_graduated(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    db_path = config.task_queue_db_path()
    kg_id = uuid4()
    _seed_pool(db_path, str(kg_id), 10)
    monkeypatch.setattr("services.expand_worker.cluster_vectors", lambda vectors: [0] * 10)
    backfill_calls = []
    monkeypatch.setattr(
        "services.expand_worker.backfill_related_to_edges",
        lambda *a, **k: backfill_calls.append((a, k)),
    )
    llm = FakeLLM("判斷：是\n名稱：INVESTS_IN\n說明：A 投入資金支持 B")

    await worker.run_governance_cycle(SpyDriver(), kg_id, FakeEmbedding(), llm)

    assert backfill_calls == []
    proposals = expand_governance_service.list_awaiting_review(db_path)
    assert len(proposals) == 1
    assert proposals[0]["status"] == "awaiting_review"
    # HUMANCHECK 分支刻意不移出候選池（見 run_governance_cycle docstring 已知缺口）
    assert expand_governance_service.pool_size(db_path, str(kg_id)) == 10


@pytest.mark.asyncio
async def test_run_governance_cycle_auto_approves_and_commits_when_graduated(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    db_path = config.task_queue_db_path()
    kg_id = uuid4()
    _seed_graduated_history(db_path, str(kg_id), window=10, approved=10)
    _seed_pool(db_path, str(kg_id), 10)
    monkeypatch.setattr("services.expand_worker.cluster_vectors", lambda vectors: [0] * 10)

    backfill_calls = []

    async def _fake_backfill(driver, kg_id_arg, new_rel_type, new_type_description, embedding_provider, **kwargs):
        backfill_calls.append((kg_id_arg, new_rel_type, new_type_description))
        return 3

    monkeypatch.setattr("services.expand_worker.backfill_related_to_edges", _fake_backfill)
    llm = FakeLLM("判斷：是\n名稱：INVESTS_IN\n說明：A 投入資金支持 B")

    await worker.run_governance_cycle(SpyDriver(), kg_id, FakeEmbedding(), llm)

    # 自動核准提案不進 awaiting_review
    assert expand_governance_service.list_awaiting_review(db_path) == []
    # COMMIT：候選標記為 committed，移出候選池
    assert expand_governance_service.pool_size(db_path, str(kg_id)) == 0
    # 新型別已寫入跨 KG 登記表
    assert expand_governance_service.find_similar_registered_type(
        db_path, [0.0, 0.0, 0.0, 1.0], threshold=0.99,
    ) == ("INVESTS_IN", pytest.approx(1.0))
    # BACKFILL 已觸發
    assert len(backfill_calls) == 1
    assert backfill_calls[0] == (kg_id, "INVESTS_IN", "A 投入資金支持 B")
