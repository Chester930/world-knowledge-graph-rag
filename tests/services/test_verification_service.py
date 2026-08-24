import json

import pytest

from services.verification_service import ClaimGrounding, verify_fact_grounding


class FakeLLM:
    def __init__(self, payload: str | None = None, error: Exception | None = None):
        self.payload = payload
        self.error = error
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        return await self.generate_json(prompt)

    async def stream(self, prompt: str):
        yield await self.generate_json(prompt)

    async def generate_json(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return self.payload


@pytest.mark.asyncio
async def test_returns_empty_when_llm_provider_missing():
    """比照 `extract_svo_triples()` 對可選 provider 的既有慣例：`None` 時
    安全跳過，回傳空清單（＝未核對，非「核對後判定全部接地」）。"""
    result = await verify_fact_grounding("本法保障勞工權益。", ["本法保障勞工權益。"], None)
    assert result == []


@pytest.mark.asyncio
async def test_returns_empty_when_answer_text_blank():
    llm = FakeLLM()
    result = await verify_fact_grounding("   ", ["某個事實。"], llm)
    assert result == []
    assert llm.prompts == []


@pytest.mark.asyncio
async def test_marks_all_unsupported_without_llm_call_when_no_facts_retrieved():
    """§ 3.6 設計提案的關鍵區分：沒有任何 Fact 可供比對時，不可靜默省略，
    也不呼叫 LLM（沒有東西好比對）——明確標記每句未接地並註明原因。"""
    llm = FakeLLM()
    result = await verify_fact_grounding("本法保障勞工權益。加班費應加倍給付。", [], llm)

    assert len(result) == 2
    assert all(not c.supported for c in result)
    assert all("未檢索到任何 Fact" in c.reason for c in result)
    assert llm.prompts == []  # 沒有呼叫 LLM


@pytest.mark.asyncio
async def test_parses_valid_grounding_response():
    llm = FakeLLM(payload=json.dumps({
        "claims": [
            {"statement": "每日辦公時數為八小時。", "supported": True, "reason": "與事實一致"},
            {"statement": "每三個月不得超過二百四十小時。", "supported": False, "reason": "事實清單中無此數字"},
        ]
    }))

    result = await verify_fact_grounding(
        "每日辦公時數為八小時。每三個月不得超過二百四十小時。",
        ["公務員每日辦公時數為八小時。", "延長辦公時數每日不得超過十二小時，每月總計不得超過六十小時。"],
        llm,
    )

    assert result == [
        ClaimGrounding(statement="每日辦公時數為八小時。", supported=True, reason="與事實一致"),
        ClaimGrounding(statement="每三個月不得超過二百四十小時。", supported=False, reason="事實清單中無此數字"),
    ]
    assert len(llm.prompts) == 1
    assert "每日辦公時數為八小時" in llm.prompts[0]  # 待核對句子確實進了 prompt
    assert "公務員每日辦公時數為八小時" in llm.prompts[0]  # 事實清單確實進了 prompt


@pytest.mark.asyncio
async def test_accepts_bare_json_list_response():
    """比照 `_parse_triples_payload()` 的既有彈性：`{"claims": [...]}` 與
    裸陣列皆可接受，不強制單一格式。"""
    llm = FakeLLM(payload=json.dumps([
        {"statement": "本法保障勞工權益。", "supported": True, "reason": "一致"},
    ]))

    result = await verify_fact_grounding("本法保障勞工權益。", ["本法保障勞工權益。"], llm)

    assert len(result) == 1
    assert result[0].supported is True


@pytest.mark.asyncio
async def test_gracefully_degrades_on_malformed_json():
    """LLM 輸出格式錯誤時不可拋出例外中斷呼叫端的 SSE 串流——每句標記為
    未接地並在 reason 註明核對本身失敗，不可假裝已核對過。"""
    llm = FakeLLM(payload="這不是 JSON")

    result = await verify_fact_grounding(
        "本法保障勞工權益。", ["本法保障勞工權益。"], llm,
    )

    assert len(result) == 1
    assert result[0].supported is False
    assert "格式錯誤" in result[0].reason


@pytest.mark.asyncio
async def test_strips_markdown_code_fence_from_response():
    llm = FakeLLM(payload="""```json
{"claims":[{"statement":"本法保障勞工權益。","supported":true,"reason":"一致"}]}
```""")

    result = await verify_fact_grounding("本法保障勞工權益。", ["本法保障勞工權益。"], llm)

    assert len(result) == 1
    assert result[0].supported is True
