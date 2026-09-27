"""B2（Agentic RAG強基準，報告36）`_b2_reflect()`真實LLM反思的單元測試。

只測`_b2_reflect()`本身的JSON解析與安全預設邏輯，用假的llm_provider，
不碰真實LLM／Neo4j／embedding。
"""
import pytest

from scripts.eval.run_rq1_comparison import _b2_reflect
from services.agentic_baseline_service import ReflectVerdict


class _FakeLLM:
    def __init__(self, response: str):
        self._response = response

    async def generate_json(self, prompt: str) -> str:
        return self._response


@pytest.mark.asyncio
async def test_no_evidence_yet_is_insufficient_with_subquestion_as_missing():
    # 第一輪檢索前（evidence_texts為空）不該呼叫LLM，直接視為明確不足。
    result = await _b2_reflect(_FakeLLM("should not be called"), "婚假幾天？", [])
    assert result == ReflectVerdict(sufficient=False, missing="婚假幾天？")


@pytest.mark.asyncio
async def test_valid_json_parsed_correctly():
    llm = _FakeLLM('{"sufficient": true, "missing": ""}')
    result = await _b2_reflect(llm, "婚假幾天？", ["婚假八日。"])
    assert result == ReflectVerdict(sufficient=True, missing="")


@pytest.mark.asyncio
async def test_valid_json_insufficient_with_missing_reason():
    llm = _FakeLLM('{"sufficient": false, "missing": "缺全國性天數"}')
    result = await _b2_reflect(llm, "特別休假幾天？", ["部分條件已知"])
    assert result == ReflectVerdict(sufficient=False, missing="缺全國性天數")


@pytest.mark.asyncio
async def test_json_in_markdown_fence_is_stripped():
    llm = _FakeLLM('```json\n{"sufficient": true, "missing": ""}\n```')
    result = await _b2_reflect(llm, "問題", ["證據"])
    assert result.sufficient is True


@pytest.mark.asyncio
async def test_malformed_json_falls_back_to_sufficient_true():
    llm = _FakeLLM("這不是 JSON")
    result = await _b2_reflect(llm, "問題", ["證據"])
    assert result == ReflectVerdict(sufficient=True, missing="")


@pytest.mark.asyncio
async def test_json_array_instead_of_object_falls_back_to_sufficient_true():
    llm = _FakeLLM('["sufficient", true]')
    result = await _b2_reflect(llm, "問題", ["證據"])
    assert result == ReflectVerdict(sufficient=True, missing="")


@pytest.mark.asyncio
async def test_missing_fields_default_sufficient_true_empty_missing():
    llm = _FakeLLM("{}")
    result = await _b2_reflect(llm, "問題", ["證據"])
    assert result == ReflectVerdict(sufficient=True, missing="")
