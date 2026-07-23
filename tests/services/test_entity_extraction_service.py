from services.entity_extraction_service import extract_mentions


class FakeNerTagger:
    """離線可測的 `NerTagger` Fake 實作，取代真實 spaCy（本專案環境尚未安裝
    驗證，見模組 docstring）。"""

    def __init__(self, per_sentence: dict[str, list[tuple[str, str]]]):
        self._per_sentence = per_sentence

    def entities(self, sentence: str) -> list[tuple[str, str]]:
        return self._per_sentence.get(sentence, [])


def test_extract_mentions_without_tagger_falls_back_to_regex_only():
    sentences = ["I-35 是美國州際公路。", "沒有代號的普通句子。"]

    mentions = extract_mentions(sentences, ner_tagger=None)

    assert len(mentions) == 2
    assert [m.text for m in mentions[0]] == ["I-35"]
    assert mentions[0][0].sentence_idx == 0
    assert mentions[0][0].entity_type == "概念"
    assert mentions[1] == []


def test_extract_mentions_uses_ner_tagger_results():
    sentences = ["理查·史東創立了太空公司。"]
    tagger = FakeNerTagger({sentences[0]: [("理查·史東", "人物"), ("太空公司", "組織")]})

    mentions = extract_mentions(sentences, ner_tagger=tagger)

    assert len(mentions[0]) == 2
    assert mentions[0][0].text == "理查·史東"
    assert mentions[0][0].entity_type == "人物"
    assert mentions[0][1].text == "太空公司"
    assert mentions[0][1].entity_type == "組織"


def test_extract_mentions_merges_ner_and_regex_without_duplicates():
    sentence = "I-35 由理查·史東提出，正式名稱為 Interstate Highway 35。"
    tagger = FakeNerTagger({sentence: [("理查·史東", "人物"), ("I-35", "概念")]})

    mentions = extract_mentions([sentence], ner_tagger=tagger)[0]

    texts = [m.text for m in mentions]
    assert texts.count("I-35") == 1  # NER 與正則皆命中，去重後只留一筆
    assert "理查·史東" in texts


def test_extract_mentions_skips_blank_ner_results():
    sentence = "有一句話。"
    tagger = FakeNerTagger({sentence: [("  ", "概念"), ("", "概念")]})

    mentions = extract_mentions([sentence], ner_tagger=tagger)[0]

    assert mentions == []


def test_extract_mentions_empty_sentence_list_returns_empty():
    assert extract_mentions([], ner_tagger=None) == []
