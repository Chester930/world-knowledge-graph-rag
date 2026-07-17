import pytest

from core.embedding_guard import EmbeddingProviderMismatchError, check_and_register


class FakeQueryResult:
    def __init__(self, records):
        self.records = records


class FakeDriver:
    """簡化的 AsyncDriver 替身：用一個 dict 模擬 `_EmbeddingMeta` 節點是否存在，
    不需要真的連 Neo4j 就能測試一致性比對邏輯。"""

    def __init__(self, existing: dict | None = None):
        self._existing = existing  # None = 尚無記錄（首次啟動）
        self.create_calls: list[dict] = []

    async def execute_query(self, query: str, **params):
        if query.strip().startswith("MATCH"):
            return FakeQueryResult([] if self._existing is None else [self._existing])
        # CREATE（僅在首次啟動時發生）
        self.create_calls.append(params)
        self._existing = {"provider": params["provider"], "model": params["model"], "dim": params["dim"]}
        return FakeQueryResult([])


class TestFirstRun:
    @pytest.mark.asyncio
    async def test_no_existing_record_creates_one(self):
        driver = FakeDriver(existing=None)
        await check_and_register(driver, "local", "paraphrase-multilingual-MiniLM-L12-v2", 384)
        assert driver.create_calls == [
            {"provider": "local", "model": "paraphrase-multilingual-MiniLM-L12-v2", "dim": 384}
        ]


class TestConsistentRecord:
    @pytest.mark.asyncio
    async def test_matching_record_passes_without_rewriting(self):
        driver = FakeDriver(existing={"provider": "local", "model": "m", "dim": 384})
        await check_and_register(driver, "local", "m", 384)
        assert driver.create_calls == []


class TestMismatchedRecord:
    @pytest.mark.asyncio
    async def test_different_provider_raises_with_both_values_in_message(self):
        driver = FakeDriver(existing={"provider": "local", "model": "m", "dim": 384})
        with pytest.raises(EmbeddingProviderMismatchError) as exc_info:
            await check_and_register(driver, "openai", "text-embedding-3-small", 1536)
        message = str(exc_info.value)
        assert "local" in message and "m" in message
        assert "openai" in message and "text-embedding-3-small" in message

    @pytest.mark.asyncio
    async def test_same_provider_different_model_raises(self):
        driver = FakeDriver(existing={"provider": "local", "model": "model-v1", "dim": 384})
        with pytest.raises(EmbeddingProviderMismatchError):
            await check_and_register(driver, "local", "model-v2", 384)

    @pytest.mark.asyncio
    async def test_same_provider_and_model_different_dim_raises(self):
        driver = FakeDriver(existing={"provider": "local", "model": "m", "dim": 384})
        with pytest.raises(EmbeddingProviderMismatchError):
            await check_and_register(driver, "local", "m", 768)

    @pytest.mark.asyncio
    async def test_mismatch_does_not_overwrite_existing_record(self):
        driver = FakeDriver(existing={"provider": "local", "model": "m", "dim": 384})
        with pytest.raises(EmbeddingProviderMismatchError):
            await check_and_register(driver, "openai", "text-embedding-3-small", 1536)
        assert driver.create_calls == []
