"""報告37 ②：OllamaEmbeddingProvider 的 num_gpu 選項只在非 None 時帶進
Ollama 請求 payload，None 時行為與先前完全一致。"""
from __future__ import annotations

import httpx
import pytest

from core.providers.embedding.ollama import OllamaEmbeddingProvider


class _FakeResp:
    def __init__(self, dim: int = 4):
        self._dim = dim

    def raise_for_status(self):
        pass

    def json(self):
        return {"embedding": [0.0] * self._dim}


@pytest.fixture
def captured(monkeypatch):
    """攔截同步 httpx.post（_probe_dim 用）與非同步 AsyncClient.post（encode 用），
    把送出的 json body 收集起來。"""
    bodies: list[dict] = []

    def fake_post(url, json=None, timeout=None):  # noqa: A002
        bodies.append(json)
        return _FakeResp()

    async def fake_async_post(self, url, json=None):  # noqa: A002
        bodies.append(json)
        return _FakeResp()

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_async_post)
    return bodies


def test_num_gpu_none_omits_options(captured):
    OllamaEmbeddingProvider("http://x", "bge-m3", num_gpu=None)
    assert captured  # _probe_dim fired
    assert all("options" not in b for b in captured)


def test_num_gpu_zero_forces_cpu_option(captured):
    OllamaEmbeddingProvider("http://x", "bge-m3", num_gpu=0)
    assert captured
    assert all(b.get("options") == {"num_gpu": 0} for b in captured)


def test_default_is_none(captured):
    # 位置參數不帶 num_gpu → 預設 None → 不改變既有行為
    p = OllamaEmbeddingProvider("http://x", "bge-m3")
    assert p._num_gpu is None
    assert all("options" not in b for b in captured)


@pytest.mark.asyncio
async def test_encode_threads_option(captured):
    p = OllamaEmbeddingProvider("http://x", "bge-m3", num_gpu=0)
    captured.clear()
    await p.encode("測試")
    assert captured == [{"model": "bge-m3", "prompt": "測試", "options": {"num_gpu": 0}}]
