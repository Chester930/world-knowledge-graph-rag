import json

import pytest

from services.verification_service import (
    ClaimGrounding,
    _grounding_prompt,
    verify_fact_grounding,
)


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
async def test_parses_is_claim_and_missing_defaults_true():
    """報告25 §4 發現6→⑥：核對結果多帶 `is_claim`；舊格式（無此欄位）缺省 True，
    維持既有「有未接地就重生成」的保守行為。"""
    llm = FakeLLM(payload=json.dumps({"claims": [
        {"statement": "根據提供的事實：", "is_claim": False, "supported": True, "reason": "引言句"},
        {"statement": "每日不得超過十二小時。", "is_claim": True, "supported": False, "reason": "無此數字"},
        {"statement": "舊格式沒帶 is_claim。", "supported": True, "reason": "一致"},
    ]}))

    result = await verify_fact_grounding("引言。主張。舊句。", ["某事實。"], llm)

    assert [(c.is_claim, c.supported) for c in result] == [(False, True), (True, False), (True, True)]


@pytest.mark.asyncio
async def test_non_claim_forced_supported_even_if_llm_says_false():
    """is_claim=False 的句子天生不需要被支持——即使核對模型填了 supported:false
    也一律視為 supported，呼叫端據 `is_claim and not supported` 判斷是否重生成。"""
    llm = FakeLLM(payload=json.dumps({"claims": [
        {"statement": "問題被當標題回貼？", "is_claim": False, "supported": False, "reason": "問題非陳述"},
    ]}))

    result = await verify_fact_grounding("問題被當標題回貼？", ["某事實。"], llm)

    assert result[0].is_claim is False
    assert result[0].supported is True


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


def test_grounding_prompt_carries_interval_lookup_carve_out():
    """報告32 §9 G2：`_grounding_prompt()` 要保留「明示查表推論例外」——
    分段對照表 + 題目數值 → 查表取對應值算 supported，其他推論仍一律 false。
    這條例外被誤刪會讓 Q8 型答案再度被判未接地、觸發限制性重生成而拒答。"""
    prompt = _grounding_prompt(["某句陳述。"], ["1 以上未滿 10 → 變量係數為 2"])
    assert "明示查表推論例外" in prompt
    assert "分段對照表套用到題目給定的數值" in prompt
    # 一般禁令仍在（不可因「聽起來合理」就判 true）
    assert "不可因為「聽起來合理」就判定 true" in prompt


def test_grounding_prompt_interval_lookup_has_coverage_precondition():
    """報告32 §9 A/B：查表例外只在數值「嚴格落在明列列的上下界內」時成立，
    取最近一列／落在間隙／越界 → 一律回到 false（含查表未命中）。級距缺一段
    卻硬答也算未接地。"""
    prompt = _grounding_prompt(["某句陳述。"], ["1 以上未滿 10 → 變量係數為 2"])
    assert "嚴格落在它所引用那一列明列的上下界之內" in prompt
    assert "false（含查表未命中）" in prompt
    assert "只出現了部分級距" in prompt
    assert "挑一列硬套算未接地" in prompt


def test_grounding_prompt_includes_question_when_supplied():
    """報告32 §9 A′：傳入 question 時 prompt 帶「使用者問題：」段，供核對
    查表例外的「題目數值須逐字出現」要求。"""
    prompt = _grounding_prompt(
        ["某句。"], ["某事實。"], question="5 ppm 時變量係數是多少？"
    )
    assert "使用者問題：5 ppm 時變量係數是多少？" in prompt


def test_grounding_prompt_omits_question_block_when_absent():
    """A′：question 為空時 prompt 與舊版逐字相同（不含「使用者問題：」段）。"""
    assert "使用者問題：" not in _grounding_prompt(["某句。"], ["某事實。"])


@pytest.mark.asyncio
async def test_strips_markdown_code_fence_from_response():
    llm = FakeLLM(payload="""```json
{"claims":[{"statement":"本法保障勞工權益。","supported":true,"reason":"一致"}]}
```""")

    result = await verify_fact_grounding("本法保障勞工權益。", ["本法保障勞工權益。"], llm)

    assert len(result) == 1
    assert result[0].supported is True
