import asyncio

import pytest

import main as main_module
from main import app, lifespan


class FakeEmbedding:
    model_name = "fake-embedding"
    dim = 4


class FakeConceptRepo:
    def __init__(self, driver):
        self.driver = driver

    async def create_vector_index(self, dim):
        return None


def _make_background_task_spy(calls: dict, key: str):
    async def _fake_worker(driver, *args, **kwargs):
        calls[key]["driver"] = driver
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            calls[key]["cancelled"] = True
            raise

    return _fake_worker


@pytest.mark.asyncio
async def test_lifespan_starts_and_gracefully_cancels_background_workers(monkeypatch):
    """§ 3.1.2／3.1.3 §a『WORKER 執行模型定案』驗收標準：`main.py` 的
    lifespan 應該把抽取 Worker（P0-3）與治理 Worker（P2-3）都當作常駐背景
    任務啟動，並在應用關閉時各自優雅取消，而不是讓它們隨行程被硬殺。其餘
    啟動步驟（`connect()`／`init_providers()`／各索引建立）與本測試無關，
    全部替換成 no-op，只驗證兩個 Worker 任務各自的生命週期。
    """
    async def _noop_async(*args, **kwargs):
        return None

    monkeypatch.setattr(main_module, "connect", _noop_async)
    monkeypatch.setattr(main_module, "disconnect", _noop_async)
    monkeypatch.setattr(main_module, "init_providers", lambda: FakeEmbedding())
    monkeypatch.setattr(main_module, "check_embedding_consistency", _noop_async)
    monkeypatch.setattr(main_module, "ConceptRepository", FakeConceptRepo)
    monkeypatch.setattr(main_module.svo_service, "create_entity_index", _noop_async)
    monkeypatch.setattr(main_module.svo_service, "create_chunk_vector_index", _noop_async)
    monkeypatch.setattr(main_module.svo_service, "create_related_to_vector_index", _noop_async)
    monkeypatch.setattr(main_module.svo_service, "create_fact_vector_index", _noop_async)
    monkeypatch.setattr(main_module, "_restart_task_queue", _noop_async)
    monkeypatch.setattr(main_module, "get_driver", lambda: "fake-driver")

    calls = {
        "extraction": {"driver": None, "cancelled": False},
        "governance": {"driver": None, "cancelled": False},
    }
    monkeypatch.setattr(
        main_module, "run_extraction_worker", _make_background_task_spy(calls, "extraction"),
    )
    monkeypatch.setattr(
        main_module, "run_governance_worker", _make_background_task_spy(calls, "governance"),
    )

    async with lifespan(app):
        await asyncio.sleep(0)  # 讓 create_task() 排進的協程真的開始執行
        assert calls["extraction"]["driver"] == "fake-driver"
        assert calls["governance"]["driver"] == "fake-driver"
        extraction_task = app.state.extraction_worker_task
        governance_task = app.state.governance_worker_task
        assert not extraction_task.done()
        assert not governance_task.done()

    assert calls["extraction"]["cancelled"] is True
    assert calls["governance"]["cancelled"] is True
    assert extraction_task.cancelled()
    assert governance_task.cancelled()
