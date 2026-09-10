import pytest
import os
from pathlib import Path
from parser.core import DocumentParser, URLParser, sentence_aware_chunking, split_into_sentences
from services.ingestion_service import parse_document


def test_sentence_aware_chunking():
    text = "這是一個句子。這是有問號的句子？這是有驚嘆號的句子！這是不完整的句子"
    chunks = sentence_aware_chunking(text, chunk_size=30, chunk_overlap=5)

    assert len(chunks) > 0
    # 確保分割出的 chunk 保留了標點
    assert "這是一個句子。" in chunks[0] or "這是一個句子。" in text


def test_split_into_sentences_basic():
    text = "這是第一句。這是第二句！這是第三句？"
    sentences = split_into_sentences(text)

    assert sentences == ["這是第一句。", "這是第二句！", "這是第三句？"]


def test_split_into_sentences_preserves_exact_reconstruction():
    # 拆分後重新 join 必須完全還原原文，供 sentence_aware_chunking() 的
    # "".join() 重組邏輯依賴。
    text = "第一句。  第二句，還沒結束的子句；第三句！\n第四句。"
    sentences = split_into_sentences(text)

    assert "".join(sentences) == text


def test_split_into_sentences_avoids_abbreviation_false_positives():
    text = "本設計參考 e.g. 案例、i.e. 定義與 vs. 對照組，數值為 3.14 不應被誤判斷句。"
    sentences = split_into_sentences(text)

    # 全文不含中文句尾標點，僅有縮寫/小數點，理應完全不觸發斷句
    assert len(sentences) == 1
    assert sentences[0] == text


def test_split_into_sentences_semicolon_is_sentence_boundary():
    text = "前半句；後半句。"
    sentences = split_into_sentences(text)

    assert sentences == ["前半句；", "後半句。"]


# ── B2：結構區塊（Markdown 表格／標記行）的內部換行不被當句界 ─────────────────

def test_split_into_sentences_keeps_markdown_table_as_one_unit():
    text = "說明段落。\n| 欄A | 欄B |\n| --- | --- |\n| 甲 | 乙 |\n| 丙 | 丁 |\n結語。"
    sentences = split_into_sentences(text)

    assert "".join(sentences) == text  # 精確重組不變
    table = "| 欄A | 欄B |\n| --- | --- |\n| 甲 | 乙 |\n| 丙 | 丁 |"
    # 整張四列表格落在同一個片段內，未被拆成「每列一句」
    assert any(table in s for s in sentences)


def test_split_into_sentences_law_enumeration_still_splits_on_newline():
    # 法條列舉（非表格）維持既有逐行斷句行為，B2 不影響
    text = "請假規則如下：\n一、婚假八日。\n二、喪假六日。"
    sentences = split_into_sentences(text)

    assert "".join(sentences) == text
    assert "一、婚假八日。" in sentences
    assert "二、喪假六日。" in sentences


def test_sentence_aware_chunking_roundtrips_text_with_table():
    text = "前言。\n| a | b |\n| c | d |\n" + "補充說明句。" * 40
    chunks = sentence_aware_chunking(text, chunk_size=120, chunk_overlap=20)
    assert chunks
    # 表格列不會各自成為一個殘缺 chunk
    assert not any(c.strip() in ("| a | b |", "| c | d |") for c in chunks)


# ── B1：混合型 PDF 的逐頁品質判定 ───────────────────────────────────────────

_GOOD_PAGE = "這是一段足夠長的正常中文內容用來通過低品質判定門檻。" * 4  # 遠超過 80 字、可讀比例高


@pytest.mark.parametrize("full_text, page_texts, expected", [
    (_GOOD_PAGE * 3, [_GOOD_PAGE, _GOOD_PAGE, _GOOD_PAGE], False),   # 全部正常
    (_GOOD_PAGE, [_GOOD_PAGE, "", "", ""], True),                     # 1/4 好、3/4 掃描 → 升級
    (_GOOD_PAGE, [_GOOD_PAGE, ""], False),                           # < 3 頁，不做比例判定
    (_GOOD_PAGE, [_GOOD_PAGE] * 7 + ["", "", ""], False),            # 3/10 = 30% < 34%
    (_GOOD_PAGE, [_GOOD_PAGE] * 6 + [""] * 4, True),                 # 4/10 = 40%
    ("短", ["短"], True),                                            # 整份低品質
])
def test_pdf_needs_fallback_thresholds(full_text, page_texts, expected):
    assert DocumentParser()._pdf_needs_fallback(full_text, page_texts) is expected


def test_parser_txt(tmp_path):
    # 建立臨時的 txt 檔案進行解析測試
    test_file = tmp_path / "test.txt"
    test_content = "測試獨立轉譯器 TXT 功能。\n這是第二行。"
    test_file.write_text(test_content, encoding="utf-8")
    
    parser = DocumentParser()
    result = parser.parse_file(str(test_file))
    
    assert test_content in result


@pytest.mark.asyncio
async def test_ingestion_service_async(tmp_path):
    test_file = tmp_path / "test.md"
    test_content = "# 測試 MD\n非同步 ingestion_service 測試。"
    test_file.write_text(test_content, encoding="utf-8")

    result = await parse_document(str(test_file))
    assert "非同步" in result


@pytest.mark.parametrize("url,expected_id", [
    ("https://www.youtube.com/watch?v=jNQXAC9IVRw", "jNQXAC9IVRw"),
    ("https://youtu.be/jNQXAC9IVRw", "jNQXAC9IVRw"),
    ("https://www.youtube.com/embed/jNQXAC9IVRw", "jNQXAC9IVRw"),
    ("https://www.youtube.com/shorts/jNQXAC9IVRw", "jNQXAC9IVRw"),
    ("https://www.youtube.com/watch?v=jNQXAC9IVRw&t=10s", "jNQXAC9IVRw"),
])
def test_extract_youtube_id(url, expected_id):
    parser = URLParser()
    assert parser._extract_youtube_id(url) == expected_id


@pytest.mark.parametrize("url,is_youtube", [
    ("https://www.youtube.com/watch?v=abc", True),
    ("https://youtu.be/abc", True),
    ("https://news.ycombinator.com/", False),
    ("https://example.com/youtube-clone", False),
])
def test_is_youtube_url(url, is_youtube):
    parser = URLParser()
    assert parser._is_youtube_url(url) == is_youtube


def test_youtube_falls_back_to_audio_when_no_subtitles(monkeypatch):
    """字幕抓取失敗（或該影片無字幕）時，應自動改用 yt-dlp + Whisper 音軌備援，而非直接報錯。"""
    parser = URLParser()

    def fake_fetch_subtitles(video_id):
        raise ValueError("找不到該影片的任何字幕")

    def fake_transcribe_audio(url, video_id):
        return "這是備援音軌轉譯出的文字"

    monkeypatch.setattr(parser, "_fetch_youtube_subtitles", fake_fetch_subtitles)
    monkeypatch.setattr(parser, "_transcribe_youtube_audio", fake_transcribe_audio)

    result = parser.parse_url("https://www.youtube.com/watch?v=jNQXAC9IVRw")

    assert "這是備援音軌轉譯出的文字" in result
    assert "音軌 Whisper 逐字稿" in result


def test_youtube_uses_subtitles_when_available(monkeypatch):
    """有字幕可用時應直接回傳字幕文字，不應觸發音軌備援。"""
    parser = URLParser()

    def fake_fetch_subtitles(video_id):
        return "這是官方字幕文字"

    def fake_transcribe_audio(url, video_id):
        raise AssertionError("不應呼叫音軌備援，因為字幕抓取應已成功")

    monkeypatch.setattr(parser, "_fetch_youtube_subtitles", fake_fetch_subtitles)
    monkeypatch.setattr(parser, "_transcribe_youtube_audio", fake_transcribe_audio)

    result = parser.parse_url("https://www.youtube.com/watch?v=jNQXAC9IVRw")

    assert "這是官方字幕文字" in result
    assert "字幕逐字稿" in result
