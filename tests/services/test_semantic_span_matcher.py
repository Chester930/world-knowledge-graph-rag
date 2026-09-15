"""單元測試：語意 NLI 式 gold exact_span 比對備援（報告52 後續修正）。

驗證：
1. 逐字命中時不呼叫 judge LLM（零額外成本）。
2. 逐字缺漏、judge LLM 判定語意存在時，補救為命中。
3. judge LLM 判定語意仍不存在時，維持缺漏（如 26-Q5 的「當日」平滑化，
   內容確實不同，不該被語意 fallback 誤救）。
4. `judge_llm_provider=None` 時退化為純逐字比對，行為不變。
5. judge LLM 回傳格式錯誤時保守視為未核對成功，不假裝已核對過。
"""
import json
import pytest

from services.semantic_span_matcher import match_spans_with_fallback


class _FakeJudge:
    """回傳固定 JSON 的假 judge LLM，用於測試 wiring 而非真實語意判斷。"""

    def __init__(self, response: str):
        self._response = response
        self.calls = 0

    async def generate_json(self, prompt: str) -> str:
        self.calls += 1
        return self._response


@pytest.mark.asyncio
async def test_exact_match_skips_llm_call():
    judge = _FakeJudge('{"results":[]}')
    hit, missed = await match_spans_with_fallback(
        "受災勞工保險費由中央政府支應六個月。", ["由中央政府支應"], judge,
    )
    assert hit == ["由中央政府支應"]
    assert missed == []
    assert judge.calls == 0


@pytest.mark.asyncio
async def test_semantic_fallback_rescues_paraphrase():
    """17-Q1 情境：Fact-RAG 用詞被自然語言化改寫，但語意內容正確。"""
    judge = _FakeJudge(json.dumps({"results": [{"index": 1, "present": True}]}))
    pool = "勞工結婚可以請八日婚假，婚假期間工資照給，不受影響。"
    hit, missed = await match_spans_with_fallback(
        pool, ["勞工結婚者給予婚假八日，工資照給"], judge,
    )
    assert hit == ["勞工結婚者給予婚假八日，工資照給"]
    assert missed == []
    assert judge.calls == 1


@pytest.mark.asyncio
async def test_semantic_fallback_does_not_rescue_real_error():
    """26-Q5 情境：「當日」平滑化內容確實不同，judge 應判 false，維持缺漏。"""
    judge = _FakeJudge(json.dumps({"results": [{"index": 1, "present": False}]}))
    pool = "其期間自災害發生當日起計算六個月。"
    hit, missed = await match_spans_with_fallback(
        pool, ["自災害發生之當月一日起計算六個月"], judge,
    )
    assert hit == []
    assert missed == ["自災害發生之當月一日起計算六個月"]


@pytest.mark.asyncio
async def test_none_judge_falls_back_to_literal_only():
    hit, missed = await match_spans_with_fallback(
        "無關內容", ["自災害發生之當月一日起計算六個月"], None,
    )
    assert hit == []
    assert missed == ["自災害發生之當月一日起計算六個月"]


@pytest.mark.asyncio
async def test_malformed_judge_response_stays_conservative():
    judge = _FakeJudge("not valid json at all")
    hit, missed = await match_spans_with_fallback(
        "某段與 gold span 無逐字重疊的文字", ["自災害發生之當月一日起計算六個月"], judge,
    )
    assert hit == []
    assert missed == ["自災害發生之當月一日起計算六個月"]


@pytest.mark.asyncio
async def test_empty_pool_text_skips_llm_call():
    judge = _FakeJudge('{"results":[{"index":1,"present":true}]}')
    hit, missed = await match_spans_with_fallback("", ["任何事實"], judge)
    assert hit == []
    assert missed == ["任何事實"]
    assert judge.calls == 0
