"""`core/providers/factory.py` 的 judge provider 解耦（論文 §3.8 / §5.6.1）。

覆蓋 `get_judge_llm_provider(fallback)` 的語意與 `_make_llm_provider()` 的
model 覆蓋，不呼叫 `init_providers()`（會載入 sentence-transformers 模型）。
"""
from __future__ import annotations

import pytest

from core.providers import factory
from core.providers.llm.ollama import OllamaLLMProvider


@pytest.fixture(autouse=True)
def _restore_factory_globals():
    """每個測試後還原 factory 的模組級 provider 快取，避免互相污染。"""
    saved = (factory._llm, factory._judge_llm, factory._embedding)
    yield
    factory._llm, factory._judge_llm, factory._embedding = saved


def test_get_judge_llm_provider_returns_fallback_when_no_dedicated_judge():
    fallback = object()
    factory._judge_llm = None
    assert factory.get_judge_llm_provider(fallback) is fallback


def test_get_judge_llm_provider_returns_dedicated_instance_when_set():
    fallback, judge = object(), object()
    factory._judge_llm = judge
    result = factory.get_judge_llm_provider(fallback)
    assert result is judge
    assert result is not fallback


def test_make_llm_provider_uses_model_override():
    prov = factory._make_llm_provider("ollama", "llama3.1:70b")
    assert isinstance(prov, OllamaLLMProvider)
    assert prov.model == "llama3.1:70b"


def test_make_llm_provider_defaults_to_settings_model_when_no_override(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "ollama_llm_model", "qwen2.5:7b")
    prov = factory._make_llm_provider("ollama", None)
    assert prov.model == "qwen2.5:7b"


def test_make_llm_provider_rejects_unknown_provider():
    with pytest.raises(ValueError):
        factory._make_llm_provider("not-a-provider")


def test_init_providers_wires_independent_judge_when_configured(monkeypatch):
    """judge_llm_provider 有設 → init_providers 另建一個 _judge_llm，
    且與生成端 _llm 是不同實例；embedding 走假建構避免載入模型。"""
    from core.config import settings

    monkeypatch.setattr(settings, "embedding_provider", "local")
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    monkeypatch.setattr(settings, "judge_llm_provider", "ollama")
    monkeypatch.setattr(settings, "judge_llm_model", "llama3.1:70b")
    monkeypatch.setattr(
        "core.providers.embedding.local.LocalEmbeddingProvider",
        lambda *a, **k: object(),
    )

    factory.init_providers()

    assert factory._judge_llm is not None
    assert factory._judge_llm is not factory._llm
    assert factory._judge_llm.model == "llama3.1:70b"
    assert factory.get_judge_llm_provider(factory._llm) is factory._judge_llm


def test_init_providers_judge_none_falls_back(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "embedding_provider", "local")
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    monkeypatch.setattr(settings, "judge_llm_provider", None)
    monkeypatch.setattr(
        "core.providers.embedding.local.LocalEmbeddingProvider",
        lambda *a, **k: object(),
    )

    factory.init_providers()

    assert factory._judge_llm is None
    assert factory.get_judge_llm_provider(factory._llm) is factory._llm
