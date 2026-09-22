"""Ollama thinking-mode forwarding for generation requests."""
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
def post_calls(monkeypatch):
    calls: list[dict] = []

    real_init = httpx.AsyncClient.__init__

    def fake_init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)

    async def fake_post(self, url, json=None):  # noqa: A002
        calls.append(json)
        return _Resp()

    monkeypatch.setattr(httpx.AsyncClient, "__init__", fake_init)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("think", [None, False, True])
@pytest.mark.parametrize("method", ["generate", "generate_json"])
async def test_generate_methods_forward_think_only_when_configured(post_calls, method, think):
    provider = OllamaLLMProvider("http://x", "qwen2.5:7b", think=think)

    await getattr(provider, method)("hi")

    payload = post_calls[0]
    if think is None:
        assert "think" not in payload
    else:
        assert payload["think"] is think
        assert "think" not in payload["options"]


@pytest.mark.asyncio
@pytest.mark.parametrize("think", [None, False, True])
async def test_stream_forwards_think_only_when_configured(monkeypatch, think):
    calls: list[dict] = []

    class _StreamResponse:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def aiter_lines(self):
            yield '{"response":"ok","done":true}'

    real_init = httpx.AsyncClient.__init__

    def fake_init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)

    def fake_stream(self, method, url, json=None):  # noqa: A002
        calls.append(json)
        return _StreamResponse()

    monkeypatch.setattr(httpx.AsyncClient, "__init__", fake_init)
    monkeypatch.setattr(httpx.AsyncClient, "stream", fake_stream)

    provider = OllamaLLMProvider("http://x", "qwen2.5:7b", think=think)
    assert "".join([token async for token in provider.stream("hi")]) == "ok"

    payload = calls[0]
    if think is None:
        assert "think" not in payload
    else:
        assert payload["think"] is think
        assert "think" not in payload["options"]
