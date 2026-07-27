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


@pytest.mark.asyncio
async def test_lifespan_starts_and_gracefully_cancels_extraction_worker(monkeypatch):
    """§ 3.1.2『WORKER 執行模型定案』驗收標準：`main.py` 的 lifespan 應該把
    抽取 Worker 當作常駐背景任務啟動，並在應用關閉時優雅取消，而不是讓它
    隨行程被硬殺。其餘啟動步驟（`connect()`／`init_providers()`／各索引
    建立）與本測試無關，全部替換成 no-op，只驗證 Worker 任務的生命週期。
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
    monkeypatch.setattr(main_module, "_restart_task_queue", _noop_async)
    monkeypatch.setattr(main_module, "get_driver", lambda: "fake-driver")

    worker_calls = {"driver": None, "cancelled": False}

    async def _fake_worker(driver, poll_interval_idle=2.0):
        worker_calls["driver"] = driver
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            worker_calls["cancelled"] = True
            raise

    monkeypatch.setattr(main_module, "run_extraction_worker", _fake_worker)

    async with lifespan(app):
        await asyncio.sleep(0)  # 讓 create_task() 排進的協程真的開始執行
        assert worker_calls["driver"] == "fake-driver"
        task = app.state.extraction_worker_task
        assert not task.done()

    assert worker_calls["cancelled"] is True
    assert task.cancelled()
