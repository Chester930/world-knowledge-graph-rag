"""報告37 Bug1/Bug2：OllamaLLMProvider 的 num_predict 可設定（預設 4096，
不再是硬寫的 1024），且 generate/generate_json 用 600s timeout。"""
from __future__ import annotations

import httpx
import pytest

from core.providers.llm.ollama import OllamaLLMProvider


class _Resp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"response": "{}"}


@pytest.fixture
def sent(monkeypatch):
    """攔截非同步 AsyncClient.post，記下 json body 與建構時的 timeout。"""
    calls: list[dict] = []
    timeouts: list = []

    real_init = httpx.AsyncClient.__init__

    def fake_init(self, *a, **kw):
        timeouts.append(kw.get("timeout"))
        real_init(self, *a, **kw)

    async def fake_post(self, url, json=None):  # noqa: A002
        calls.append(json)
        return _Resp()

    monkeypatch.setattr(httpx.AsyncClient, "__init__", fake_init)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    return calls, timeouts


@pytest.mark.asyncio
async def test_default_num_predict_is_4096(sent):
    calls, _ = sent
    p = OllamaLLMProvider("http://x", "qwen2.5:7b")
    await p.generate("hi")
    await p.generate_json("hi")
    assert all(c["options"]["num_predict"] == 4096 for c in calls)


@pytest.mark.asyncio
async def test_num_predict_override(sent):
    calls, _ = sent
    p = OllamaLLMProvider("http://x", "qwen2.5:7b", num_predict=1024)
    await p.generate_json("hi")
    assert calls[0]["options"]["num_predict"] == 1024


@pytest.mark.asyncio
async def test_generate_json_still_json_format(sent):
    calls, _ = sent
    p = OllamaLLMProvider("http://x", "qwen2.5:7b")
    await p.generate_json("hi")
    assert calls[0]["format"] == "json"


@pytest.mark.asyncio
async def test_timeout_is_600(sent):
    _, timeouts = sent
    p = OllamaLLMProvider("http://x", "qwen2.5:7b")
    await p.generate("hi")
    await p.generate_json("hi")
    assert 600.0 in timeouts
    assert 300.0 not in timeouts
