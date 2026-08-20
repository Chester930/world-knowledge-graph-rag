import pytest

from services import ingestion_service
from services.entity_registry_service import Mention
from services.pronoun_resolution_service import DEFAULT_PRONOUN_LEXICON
from services.svo_preprocessing_service import (
    prepare_svo_ready_chunks,
    read_sentence_embeddings,
    read_standardized_sentences,
    write_sentence_embeddings,
)


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


@pytest.mark.asyncio
async def test_pipeline_without_mentions_skips_registry_and_chunks_result(tmp_path):
    staging = tmp_path / "staging"
    output = tmp_path / "output"
    # 刻意避開英文專有名詞緊接句號的組合（parser.core.split_into_sentences
    # 既有的縮寫防誤判 lookbehind 會連帶擋下如「SpaceX。」這類邊界，屬既有、
    # 與本次工作無關的規則限制，不在此修正，測試改用不觸發此限制的文字）。
    text = "馬斯克創立了太空公司。他隨後研發了獵鷹火箭。"
    ingestion_service.chunk_and_stage(text, "report.txt", staging)

    llm = FakeLLM(responses=["馬斯克隨後研發了獵鷹火箭。"])

    paths, chunks = await prepare_svo_ready_chunks(
        "report.txt", staging, output, pronoun_llm_provider=llm,
    )

    assert len(paths) == 1
    assert len(chunks) == 1
    assert chunks[0].original_sentences == ["馬斯克創立了太空公司。", "他隨後研發了獵鷹火箭。"]
    assert chunks[0].normalized_sentences == ["馬斯克創立了太空公司。", "馬斯克隨後研發了獵鷹火箭。"]
    assert paths[0].exists()


@pytest.mark.asyncio
async def test_pipeline_with_mentions_applies_registry_before_pronoun_resolution(tmp_path):
    staging = tmp_path / "staging"
    output = tmp_path / "output"
    text = "理查·史東創立了太空公司。史東隨後研發了獵鷹火箭。它是一枚可回收火箭。"
    ingestion_service.chunk_and_stage(text, "report.txt", staging)

    mentions = [
        [Mention(sentence_idx=0, text="理查·史東", entity_type="PERSON")],
        [Mention(sentence_idx=1, text="史東", entity_type="PERSON")],
        [],
    ]
    pronoun_llm = FakeLLM(responses=["獵鷹火箭是一枚可回收火箭。"])
    # 代名詞消解只會被觸發在第 3 句（含「它」），前兩句別名登記後不含代名詞

    paths, chunks = await prepare_svo_ready_chunks(
        "report.txt", staging, output,
        mentions=mentions,
        pronoun_llm_provider=pronoun_llm,
    )

    assert len(chunks) == 1
    normalized = chunks[0].normalized_sentences
    assert normalized[0] == "理查·史東創立了太空公司。"
    # 「史東」透過登記表子字串規則併入「理查·史東」，就地替換為文件內暫定標準名
    assert normalized[1] == "理查·史東隨後研發了獵鷹火箭。"
    assert normalized[2] == "獵鷹火箭是一枚可回收火箭。"
    # 第三句含代名詞「它」，交由（唯一一次）LLM 呼叫消解
    assert len(pronoun_llm.prompts) == 1


@pytest.mark.asyncio
async def test_pipeline_uses_ner_tagger_to_populate_registry_when_no_explicit_mentions(tmp_path):
    """`ner_tagger` 是 `mentions` 的替代輸入來源（2026-07-23 新增）：呼叫端
    不必自行先跑 NER 組出 `mentions`，只要傳入 `ner_tagger`，本函式會用
    `entity_extraction_service.extract_mentions()` 對原始句子現場抽取。"""
    staging = tmp_path / "staging"
    output = tmp_path / "output"
    text = "理查·史東創立了太空公司。史東隨後研發了獵鷹火箭。"
    ingestion_service.chunk_and_stage(text, "report.txt", staging)

    class FakeNerTagger:
        def entities(self, sentence: str):
            if sentence == "理查·史東創立了太空公司。":
                return [("理查·史東", "人物")]
            if sentence == "史東隨後研發了獵鷹火箭。":
                return [("史東", "人物")]
            return []

    paths, chunks = await prepare_svo_ready_chunks(
        "report.txt", staging, output, ner_tagger=FakeNerTagger(),
    )

    normalized = chunks[0].normalized_sentences
    assert normalized[0] == "理查·史東創立了太空公司。"
    # 「史東」透過登記表子字串規則併入「理查·史東」，就地替換為文件內暫定標準名，
    # 證實 ner_tagger 產生的 mentions 確實有餵進 §a REGISTRY／ALIASCHECK。
    assert normalized[1] == "理查·史東隨後研發了獵鷹火箭。"


@pytest.mark.asyncio
async def test_pipeline_explicit_mentions_take_priority_over_ner_tagger(tmp_path):
    staging = tmp_path / "staging"
    output = tmp_path / "output"
    text = "馬斯克創立了太空公司。"
    ingestion_service.chunk_and_stage(text, "report.txt", staging)

    class ExplodingNerTagger:
        def entities(self, sentence: str):
            raise AssertionError("mentions 已明確提供時不應呼叫 ner_tagger")

    paths, chunks = await prepare_svo_ready_chunks(
        "report.txt", staging, output,
        mentions=[[]],
        ner_tagger=ExplodingNerTagger(),
    )

    assert len(chunks) == 1


@pytest.mark.asyncio
async def test_pipeline_persists_svo_index_to_disk(tmp_path):
    staging = tmp_path / "staging"
    output = tmp_path / "output"
    ingestion_service.chunk_and_stage("單句無代名詞。", "note.md", staging)

    paths, chunks = await prepare_svo_ready_chunks("note.md", staging, output)

    from services.svo_chunking import read_svo_index
    index = read_svo_index(output / "note")
    assert index is not None
    assert index["total_svo_chunks"] == len(chunks)


# ── SENTEMBED（逐句 embedding，2026-07-22 補齊）──────────────────────────────

class FakeEmbedding:
    dim = 4
    model_name = "fake-embedding"

    async def encode(self, text: str) -> list[float]:
        return [float(len(text))] * self.dim

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(t))] * self.dim for t in texts]


@pytest.mark.asyncio
async def test_pipeline_writes_sentence_embeddings_when_provider_given(tmp_path):
    staging = tmp_path / "staging"
    output = tmp_path / "output"
    ingestion_service.chunk_and_stage("馬斯克創立了太空公司。他隨後研發了獵鷹火箭。", "note.md", staging)

    paths, chunks = await prepare_svo_ready_chunks(
        "note.md", staging, output, embedding_provider=FakeEmbedding(),
    )

    vectors = read_sentence_embeddings("note.md", output)
    assert vectors is not None
    assert len(vectors) == len(chunks[0].normalized_sentences)


@pytest.mark.asyncio
async def test_pipeline_skips_sentence_embeddings_without_provider(tmp_path):
    staging = tmp_path / "staging"
    output = tmp_path / "output"
    ingestion_service.chunk_and_stage("單句無代名詞。", "note.md", staging)

    await prepare_svo_ready_chunks("note.md", staging, output)

    assert read_sentence_embeddings("note.md", output) is None


# ── write/read_standardized_sentences（2026-08-20，§ Phase 1 標準化 RAG）──────

def test_write_sentence_embeddings_stores_sentences_when_provided(tmp_path):
    write_sentence_embeddings(
        [[0.1, 0.2], [0.3, 0.4]], "note.md", tmp_path,
        sentences=["馬斯克創立了太空公司。", "馬斯克隨後研發了獵鷹火箭。"],
    )

    assert read_standardized_sentences("note.md", tmp_path) == [
        "馬斯克創立了太空公司。", "馬斯克隨後研發了獵鷹火箭。",
    ]
    # 既有只需要向量的呼叫端不受影響，仍可正常讀回向量本身
    assert read_sentence_embeddings("note.md", tmp_path) == [[0.1, 0.2], [0.3, 0.4]]


def test_write_sentence_embeddings_omits_sentences_field_when_not_provided(tmp_path):
    """向後相容：不帶 `sentences` 時行為與 2026-08-20 修正前完全一致。"""
    write_sentence_embeddings([[0.1, 0.2]], "note.md", tmp_path)

    assert read_standardized_sentences("note.md", tmp_path) is None
    assert read_sentence_embeddings("note.md", tmp_path) == [[0.1, 0.2]]


def test_read_standardized_sentences_returns_none_when_file_missing(tmp_path):
    assert read_standardized_sentences("does-not-exist.md", tmp_path) is None


@pytest.mark.asyncio
async def test_pipeline_writes_standardized_sentence_text_alongside_embeddings(tmp_path):
    """2026-08-20：`prepare_svo_ready_chunks()` 呼叫 `write_sentence_embeddings()`
    時應一併帶入 `sentences=normalized_sentences`，供 § Phase 1 的 Neo4j
    `Sentence` 節點寫入時讀回文字本身，不需重新呼叫指代消解。"""
    staging = tmp_path / "staging"
    output = tmp_path / "output"
    text = "馬斯克創立了太空公司。他隨後研發了獵鷹火箭。"
    ingestion_service.chunk_and_stage(text, "note.md", staging)

    llm = FakeLLM(responses=["馬斯克隨後研發了獵鷹火箭。"])
    await prepare_svo_ready_chunks(
        "note.md", staging, output, pronoun_llm_provider=llm, embedding_provider=FakeEmbedding(),
    )

    sentences = read_standardized_sentences("note.md", output)
    assert sentences == ["馬斯克創立了太空公司。", "馬斯克隨後研發了獵鷹火箭。"]


# ── pronoun_lexicon（2026-08-20，§ KG 專屬代名詞排除詞庫）───────────────────

@pytest.mark.asyncio
async def test_pipeline_uses_custom_pronoun_lexicon_to_skip_resolution(tmp_path):
    """`pronoun_lexicon` 明確傳入時（呼叫端已扣除該 KG 排除的字），詞庫外的字
    即使原本在 `DEFAULT_PRONOUN_LEXICON` 內，也不應觸發 LLM 消解。"""
    staging = tmp_path / "staging"
    output = tmp_path / "output"
    ingestion_service.chunk_and_stage("本法保障其權益。", "note.md", staging)

    llm = FakeLLM(default="不應被呼叫")
    custom_lexicon = DEFAULT_PRONOUN_LEXICON - {"其"}

    paths, chunks = await prepare_svo_ready_chunks(
        "note.md", staging, output,
        pronoun_llm_provider=llm, pronoun_lexicon=custom_lexicon,
    )

    assert chunks[0].normalized_sentences == ["本法保障其權益。"]
    assert llm.prompts == []


@pytest.mark.asyncio
async def test_pipeline_defaults_to_full_lexicon_when_pronoun_lexicon_not_given(tmp_path):
    """`pronoun_lexicon` 未傳入（`None`）時沿用完整的 `DEFAULT_PRONOUN_LEXICON`，
    行為與此參數新增前完全一致——確認新增可選參數未改變既有預設行為。"""
    staging = tmp_path / "staging"
    output = tmp_path / "output"
    ingestion_service.chunk_and_stage("本法保障其權益。", "note.md", staging)

    llm = FakeLLM(responses=["本法保障勞工權益。"])

    paths, chunks = await prepare_svo_ready_chunks(
        "note.md", staging, output, pronoun_llm_provider=llm,
    )

    assert chunks[0].normalized_sentences == ["本法保障勞工權益。"]
    assert len(llm.prompts) == 1
