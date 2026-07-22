import pytest

from services import pronoun_resolution_service as svc


class FakeLLM:
    def __init__(self, responses=None, default: str = ""):
        self.responses = list(responses) if responses is not None else None
        self.default = default
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.responses is not None:
            return self.responses.pop(0)
        return self.default

    async def stream(self, prompt: str):
        yield self.default

    async def generate_json(self, prompt: str) -> str:
        return self.default


class FakePosTagger:
    """依詞表回傳 POS 命中的詞——不模擬真實 spaCy，只驗證雙軌比對邏輯。"""

    def __init__(self, tagged_words: set[str]):
        self._tagged_words = tagged_words

    def pronoun_tokens(self, sentence: str) -> list[str]:
        return [w for w in self._tagged_words if w in sentence]


# ── detect_pronoun（雙軌比對三路分流，10 報告 § 3.1）─────────────────────────

def test_regex_hit_alone_detects_pronoun_without_pos_tagger():
    result = svc.detect_pronoun("他隨後研發了獵鷹火箭。")
    assert result.has_pronoun is True
    assert result.unmapped_tokens == []


def test_no_regex_no_pos_tagger_bypasses():
    result = svc.detect_pronoun("馬斯克創立了 SpaceX。")
    assert result.has_pronoun is False


def test_both_regex_and_pos_hit_detects_pronoun_no_unmapped():
    tagger = FakePosTagger({"他"})
    result = svc.detect_pronoun("他隨後研發了獵鷹火箭。", pos_tagger=tagger)
    assert result.has_pronoun is True
    assert result.unmapped_tokens == []


def test_pos_hit_but_regex_miss_flags_unmapped_token():
    """對應 10 報告核心價值：正則詞庫未收錄的詞，POS 仍能補上召回率。"""
    tagger = FakePosTagger({"彼"})
    result = svc.detect_pronoun("彼曾言及此事。", pos_tagger=tagger)
    assert result.has_pronoun is True
    assert result.unmapped_tokens == ["彼"]


def test_both_miss_bypasses_with_pos_tagger_present():
    tagger = FakePosTagger(set())
    result = svc.detect_pronoun("馬斯克創立了 SpaceX。", pos_tagger=tagger)
    assert result.has_pronoun is False
    assert result.unmapped_tokens == []


def test_regex_known_false_positive_still_triggers_without_pos_correction():
    """05 任務書已知限制：「其他」會被單字元「其」誤觸發——雙軌機制本身不
    負責修正這個特定案例（那是正則詞庫設計問題，不是偵測分流邏輯的責任），
    這裡誠實記錄現況，避免誤以為雙軌機制自動解決了所有已知限制。"""
    result = svc.detect_pronoun("其他公司也跟進了。")
    assert result.has_pronoun is True


# ── 背景 LLM 詞庫審核 ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_audit_unmapped_pronoun_returns_true_when_llm_confirms():
    llm = FakeLLM(default="是，這是代名詞")
    approved = await svc.audit_unmapped_pronoun("彼", "彼曾言及此事。", llm)
    assert approved is True
    assert "彼" in llm.prompts[0]


@pytest.mark.asyncio
async def test_audit_unmapped_pronoun_returns_false_when_llm_rejects():
    llm = FakeLLM(default="否")
    approved = await svc.audit_unmapped_pronoun("蘋果", "他買了蘋果。", llm)
    assert approved is False


def test_append_to_lexicon_writes_new_word(tmp_path):
    path = tmp_path / "custom_pronoun_lexicon.txt"
    svc.append_to_lexicon(path, "彼")

    assert svc.load_custom_lexicon(path) == {"彼"}


def test_append_to_lexicon_does_not_duplicate(tmp_path):
    path = tmp_path / "custom_pronoun_lexicon.txt"
    svc.append_to_lexicon(path, "彼")
    svc.append_to_lexicon(path, "彼")

    assert path.read_text(encoding="utf-8").count("彼") == 1


def test_load_custom_lexicon_returns_empty_set_when_missing(tmp_path):
    assert svc.load_custom_lexicon(tmp_path / "missing.txt") == set()


# ── resolve_coreference_pipeline（前四後二雙向上下文，05 任務書 § 3）───────

@pytest.mark.asyncio
async def test_pipeline_bypasses_sentence_without_pronoun():
    llm = FakeLLM(default="不應該被呼叫")
    sentences = ["馬斯克創立了 SpaceX。"]

    result = await svc.resolve_coreference_pipeline(sentences, llm)

    assert result == sentences
    assert llm.prompts == []


@pytest.mark.asyncio
async def test_pipeline_resolves_pronoun_using_past_context():
    llm = FakeLLM(responses=["馬斯克隨後研發了獵鷹火箭。"])
    sentences = ["馬斯克創立了 SpaceX。", "他隨後研發了獵鷹火箭。"]

    result = await svc.resolve_coreference_pipeline(sentences, llm)

    assert result == ["馬斯克創立了 SpaceX。", "馬斯克隨後研發了獵鷹火箭。"]
    assert "馬斯克創立了 SpaceX。" in llm.prompts[0]  # 前文正確傳入


@pytest.mark.asyncio
async def test_pipeline_entity_relay_uses_standardized_history_not_raw():
    """對應 05 任務書 § 3.2「實體接力」——第三句消解時，前文應是已標準化過
    的 S2'，而非原始未消解的 S2。"""
    llm = FakeLLM(responses=[
        "馬斯克隨後研發了獵鷹火箭。",
        "獵鷹火箭是一枚可回收火箭。",
    ])
    sentences = ["馬斯克創立了 SpaceX。", "他隨後研發了獵鷹火箭。", "它是一枚可回收火箭。"]

    result = await svc.resolve_coreference_pipeline(sentences, llm)

    assert result[2] == "獵鷹火箭是一枚可回收火箭。"
    assert "馬斯克隨後研發了獵鷹火箭。" in llm.prompts[1]  # 前文含已標準化的 S2'，非原始「他...」


@pytest.mark.asyncio
async def test_pipeline_without_llm_provider_passes_through_unchanged():
    sentences = ["他隨後研發了獵鷹火箭。"]
    result = await svc.resolve_coreference_pipeline(sentences)
    assert result == sentences


@pytest.mark.asyncio
async def test_pipeline_triggers_lexicon_audit_for_unmapped_pos_token(tmp_path):
    tagger = FakePosTagger({"彼"})
    audit_llm = FakeLLM(default="是")
    resolve_llm = FakeLLM(responses=["馬斯克曾言及此事。"])
    lexicon_path = tmp_path / "custom_pronoun_lexicon.txt"

    sentences = ["彼曾言及此事。"]
    result = await svc.resolve_coreference_pipeline(
        sentences, resolve_llm,
        pos_tagger=tagger,
        lexicon_auditor_provider=audit_llm,
        custom_lexicon_path=lexicon_path,
    )

    assert result == ["馬斯克曾言及此事。"]
    assert svc.load_custom_lexicon(lexicon_path) == {"彼"}


@pytest.mark.asyncio
async def test_pipeline_rejected_audit_does_not_pollute_lexicon(tmp_path):
    tagger = FakePosTagger({"蘋果"})
    audit_llm = FakeLLM(default="否")
    resolve_llm = FakeLLM(responses=["他買了蘋果。"])
    lexicon_path = tmp_path / "custom_pronoun_lexicon.txt"

    await svc.resolve_coreference_pipeline(
        ["他買了蘋果。"], resolve_llm,
        pos_tagger=tagger,
        lexicon_auditor_provider=audit_llm,
        custom_lexicon_path=lexicon_path,
    )

    assert svc.load_custom_lexicon(lexicon_path) == set()


@pytest.mark.asyncio
async def test_pipeline_future_context_capped_at_two_sentences():
    llm = FakeLLM(responses=["馬斯克。"])
    sentences = ["他。", "後一。", "後二。", "後三。"]

    await svc.resolve_coreference_pipeline(sentences, llm)

    prompt = llm.prompts[0]
    assert "後一。" in prompt
    assert "後二。" in prompt
    assert "後三。" not in prompt
