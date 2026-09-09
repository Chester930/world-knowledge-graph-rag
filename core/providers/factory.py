from __future__ import annotations
import logging

from core.providers.base import EmbeddingProvider, LLMProvider

logger = logging.getLogger(__name__)

_llm: LLMProvider | None = None
_judge_llm: LLMProvider | None = None
_embedding: EmbeddingProvider | None = None


def _make_llm_provider(provider_name: str, model_override: str | None = None) -> LLMProvider:
    """依 provider 名稱（＋可選 model 覆蓋）建立一個 LLMProvider。

    `model_override` 為 `None` 時使用該 provider 在 settings 的預設 model 欄位；
    API key／base_url 一律沿用 settings 既有的 per-provider 欄位。生成端與
    核對者（judge）provider 共用此建構邏輯。
    """
    from core.config import settings

    match provider_name:
        case "ollama":
            from core.providers.llm.ollama import OllamaLLMProvider
            return OllamaLLMProvider(
                base_url=settings.ollama_base_url,
                model=model_override or settings.ollama_llm_model,
                num_predict=settings.ollama_llm_num_predict,
            )
        case "openai":
            from core.providers.llm.openai import OpenAILLMProvider
            return OpenAILLMProvider(
                api_key=settings.openai_api_key,
                model=model_override or settings.openai_llm_model,
            )
        case "anthropic":
            from core.providers.llm.anthropic import AnthropicLLMProvider
            return AnthropicLLMProvider(
                api_key=settings.anthropic_api_key,
                model=model_override or settings.anthropic_model,
            )
        case "gemini":
            from core.providers.llm.gemini import GeminiLLMProvider
            return GeminiLLMProvider(
                api_key=settings.google_api_key,
                model=model_override or settings.gemini_model,
            )
        case "grok":
            from core.providers.llm.grok import GrokLLMProvider
            return GrokLLMProvider(
                api_key=settings.grok_api_key,
                model=model_override or settings.grok_model,
            )
        case _:
            raise ValueError(f"不支援的 llm_provider：{provider_name}")


def init_providers() -> EmbeddingProvider:
    """
    根據 settings 初始化 LLM 與 Embedding provider。
    在 app lifespan 啟動時呼叫一次；回傳 EmbeddingProvider 供建立 vector index 使用。
    """
    global _llm, _judge_llm, _embedding
    from core.config import settings

    # ── Embedding ──────────────────────────────────────────────────────────────
    match settings.embedding_provider:
        case "local":
            from core.providers.embedding.local import LocalEmbeddingProvider
            _embedding = LocalEmbeddingProvider(settings.local_embedding_model)
        case "openai":
            from core.providers.embedding.openai import OpenAIEmbeddingProvider
            _embedding = OpenAIEmbeddingProvider(
                api_key=settings.openai_api_key,
                model=settings.openai_embedding_model,
            )
        case "ollama":
            from core.providers.embedding.ollama import OllamaEmbeddingProvider
            _embedding = OllamaEmbeddingProvider(
                base_url=settings.ollama_base_url,
                model=settings.ollama_embedding_model,
                num_gpu=settings.ollama_embedding_num_gpu,
            )
        case _:
            raise ValueError(f"不支援的 embedding_provider：{settings.embedding_provider}")

    # ── LLM（生成端）──────────────────────────────────────────────────────────
    _llm = _make_llm_provider(settings.llm_provider)

    # ── LLM（核對者 / grounding judge，論文 §3.8 / §5.6.1）────────────────────
    # judge_llm_provider 留空 ＝ 沿用生成端 provider（get_judge_llm_provider()
    # 會 fallback），行為與重構前完全一致。有設才另建一個獨立實例。
    if settings.judge_llm_provider:
        _judge_llm = _make_llm_provider(
            settings.judge_llm_provider, settings.judge_llm_model
        )
        logger.info(
            f"Judge LLM Provider：{settings.judge_llm_provider}"
            f"（model={settings.judge_llm_model or '預設'}）"
        )
    else:
        _judge_llm = None

    logger.info(f"LLM Provider：{settings.llm_provider}")
    logger.info(f"Embedding Provider：{settings.embedding_provider}")
    return _embedding


def get_llm_provider() -> LLMProvider:
    if _llm is None:
        raise RuntimeError("Provider 尚未初始化，請先呼叫 init_providers()")
    return _llm


def get_judge_llm_provider(fallback: LLMProvider) -> LLMProvider:
    """事實接地核對（verify_fact_grounding）使用的 LLM provider。

    `settings.judge_llm_provider` 未設定時回傳傳入的 `fallback`（通常＝生成端
    provider，行為零變化）；設定後回傳獨立實例，供論文 §5.6.1「獨立核對者
    對照組」實驗——避免生成者＝核對者的判斷循環性（§3.8）。呼叫端已持有
    生成 provider，故以參數傳入 fallback，本函式不自行 raise。
    """
    return _judge_llm if _judge_llm is not None else fallback


def get_embedding_provider() -> EmbeddingProvider:
    if _embedding is None:
        raise RuntimeError("Provider 尚未初始化，請先呼叫 init_providers()")
    return _embedding
