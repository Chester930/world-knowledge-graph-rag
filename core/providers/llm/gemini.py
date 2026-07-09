from __future__ import annotations
import logging
from typing import AsyncIterator

from core.providers.base import LLMProvider

logger = logging.getLogger(__name__)


class GeminiLLMProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(model)

    async def generate(self, prompt: str) -> str:
        response = await self._model.generate_content_async(prompt)
        return response.text

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        response = await self._model.generate_content_async(prompt, stream=True)
        async for chunk in response:
            if chunk.text:
                yield chunk.text
