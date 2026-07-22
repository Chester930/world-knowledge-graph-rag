import json
from pathlib import Path

from parser.chunk_writer import (
    read_original_text,
    read_sentences_index,
    write_chunks_as_markdown,
    write_original_text,
    write_sentences_index,
    _safe_filename_stem,
    document_folder_path,
)


def test_writes_one_file_per_chunk_into_dedicated_document_folder(tmp_path):
    chunks = ["第一段內容。", "第二段內容。", "第三段內容。"]
    paths = write_chunks_as_markdown(chunks, "report.pdf", tmp_path)

    assert len(paths) == 3
    doc_folder = tmp_path / "report"
    assert all(p.parent == doc_folder for p in paths)

    names = sorted(p.name for p in paths)
    assert names == [
        "chunk-001-of-003.md",
        "chunk-002-of-003.md",
        "chunk-003-of-003.md",
    ]
    for p in paths:
        assert p.exists()


def test_frontmatter_and_body_content_are_correct(tmp_path):
    chunks = ["這是第一個切塊的內容。"]
    paths = write_chunks_as_markdown(chunks, "D:/docs/系統架構.docx", tmp_path)

    content = paths[0].read_text(encoding="utf-8")
    assert '---' in content
    assert 'chunk_index: 1' in content
    assert 'total_chunks: 1' in content
    assert '系統架構.docx' in content  # source 應完整保留在 frontmatter 中
    assert "這是第一個切塊的內容。" in content
    # frontmatter 應在內容之前
    assert content.index("---") < content.index("這是第一個切塊的內容。")


def test_output_dir_and_document_folder_are_created_if_missing(tmp_path):
    target = tmp_path / "nested" / "chunks"
    assert not target.exists()

    write_chunks_as_markdown(["內容"], "a.txt", target)

    doc_folder = target / "a"
    assert doc_folder.exists()
    assert len(list(doc_folder.glob("*.md"))) == 1


def test_empty_chunks_returns_empty_list_and_does_not_create_document_folder(tmp_path):
    paths = write_chunks_as_markdown([], "empty.txt", tmp_path)
    assert paths == []
    assert not (tmp_path / "empty").exists()


def test_rerun_with_fewer_chunks_cleans_up_stale_files(tmp_path):
    """迴歸測試：同一來源重新處理後分塊數變少時，舊有多出來的分塊檔案應被清除，
    避免殘留過期、跟目前內容對不上的檔案。"""
    write_chunks_as_markdown(["a", "b", "c", "d", "e"], "doc.txt", tmp_path)
    doc_folder = tmp_path / "doc"
    assert len(list(doc_folder.glob("chunk-*.md"))) == 5

    write_chunks_as_markdown(["x", "y"], "doc.txt", tmp_path)
    remaining = sorted(p.name for p in doc_folder.glob("chunk-*.md"))

    assert remaining == ["chunk-001-of-002.md", "chunk-002-of-002.md"]


def test_rerun_cleanup_does_not_touch_other_files_in_document_folder(tmp_path):
    """資料夾內若有其他檔案（例如 document_record_service 寫入的記錄檔），
    重跑分塊清理時不應被誤刪——清理只鎖定 chunk-*-of-*.md 這個 glob。"""
    write_chunks_as_markdown(["a", "b", "c"], "doc.txt", tmp_path)
    doc_folder = tmp_path / "doc"
    record_file = doc_folder / "_record.json"
    record_file.write_text("{}", encoding="utf-8")

    write_chunks_as_markdown(["x"], "doc.txt", tmp_path)

    assert record_file.exists()
    assert record_file.read_text(encoding="utf-8") == "{}"


def test_rerun_does_not_affect_other_sources_folders(tmp_path):
    write_chunks_as_markdown(["a", "b"], "doc_one.txt", tmp_path)
    write_chunks_as_markdown(["c"], "doc_two.txt", tmp_path)

    write_chunks_as_markdown(["z"], "doc_one.txt", tmp_path)

    assert sorted(p.name for p in (tmp_path / "doc_one").glob("*.md")) == ["chunk-001-of-001.md"]
    assert sorted(p.name for p in (tmp_path / "doc_two").glob("*.md")) == ["chunk-001-of-001.md"]


def test_document_folder_path_matches_actual_written_location(tmp_path):
    paths = write_chunks_as_markdown(["內容"], "report.pdf", tmp_path)
    assert paths[0].parent == document_folder_path("report.pdf", tmp_path)


def test_safe_filename_stem_sanitizes_path_source():
    assert _safe_filename_stem("D:/Users/666/Desktop/report.pdf") == "report"
    assert _safe_filename_stem(r"C:\docs\系統架構 v2.docx") == "系統架構_v2"


def test_safe_filename_stem_handles_url_source():
    stem = _safe_filename_stem("https://www.youtube.com/watch?v=abc123")
    # URL 中的 : / ? 等字元都應被替換掉，不留下對檔案系統不安全的字元
    assert not any(c in stem for c in '\\/:*?"<>|')
    assert stem  # 不應變成空字串


def test_safe_filename_stem_falls_back_when_empty():
    assert _safe_filename_stem("") == "untitled"


def test_digits_padding_scales_with_large_chunk_counts(tmp_path):
    chunks = [f"內容 {i}" for i in range(1234)]
    paths = write_chunks_as_markdown(chunks, "big.txt", tmp_path)

    assert len(paths) == 1234
    assert paths[0].name == "chunk-0001-of-1234.md"
    assert paths[-1].name == "chunk-1234-of-1234.md"


def test_write_original_text_creates_file_in_document_folder(tmp_path):
    original = "這是完整的原始解析文字，尚未經過切塊。"
    path = write_original_text(original, "report.pdf", tmp_path)

    assert path == tmp_path / "report" / "original.md"
    assert path.exists()


def test_write_original_text_preserves_full_body_in_frontmatter(tmp_path):
    original = "第一段。\n\n第二段，含有換行與空白。"
    path = write_original_text(original, "D:/docs/系統架構.docx", tmp_path)

    content = path.read_text(encoding="utf-8")
    assert "系統架構.docx" in content  # source 完整保留在 frontmatter
    assert original in content
    assert content.index("---") < content.index(original)


def test_write_original_text_lands_in_same_folder_as_chunks(tmp_path):
    chunk_paths = write_chunks_as_markdown(["一二三。"], "doc.txt", tmp_path)
    original_path = write_original_text("一二三。", "doc.txt", tmp_path)

    assert original_path.parent == chunk_paths[0].parent


def test_write_original_text_overwrites_on_rerun(tmp_path):
    write_original_text("舊版本內容", "doc.txt", tmp_path)
    path = write_original_text("新版本內容", "doc.txt", tmp_path)

    content = path.read_text(encoding="utf-8")
    assert "新版本內容" in content
    assert "舊版本內容" not in content
    # 不應殘留額外檔案——固定檔名覆寫，不像分塊需要清理數量變動的殘留
    assert len(list(path.parent.glob("original*.md"))) == 1


def test_write_sentences_index_creates_file_in_document_folder(tmp_path):
    sentences = ["第一句。", "第二句！", "第三句？"]
    path = write_sentences_index(sentences, "report.pdf", tmp_path)

    assert path == tmp_path / "report" / "sentences.json"
    assert path.exists()


def test_write_sentences_index_content_matches_input(tmp_path):
    sentences = ["第一句。", "第二句！"]
    path = write_sentences_index(sentences, "doc.txt", tmp_path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["source"] == "doc.txt"
    assert payload["total_sentences"] == 2
    assert payload["sentences"] == sentences


def test_write_sentences_index_lands_in_same_folder_as_chunks_and_original(tmp_path):
    chunk_paths = write_chunks_as_markdown(["一二三。"], "doc.txt", tmp_path)
    original_path = write_original_text("一二三。", "doc.txt", tmp_path)
    sentences_path = write_sentences_index(["一二三。"], "doc.txt", tmp_path)

    assert sentences_path.parent == chunk_paths[0].parent == original_path.parent


def test_write_sentences_index_overwrites_on_rerun(tmp_path):
    write_sentences_index(["舊句子。"], "doc.txt", tmp_path)
    path = write_sentences_index(["新句子一。", "新句子二。"], "doc.txt", tmp_path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["sentences"] == ["新句子一。", "新句子二。"]
    # 不應殘留額外檔案——固定檔名覆寫
    assert len(list(path.parent.glob("sentences*.json"))) == 1


# ── read_original_text／read_sentences_index（§ 3.1.2 GETSENT 讀取端）──────

def test_read_original_text_round_trips_exact_body(tmp_path):
    original = "第一段。\n\n第二段，含有換行與空白。"
    write_original_text(original, "report.pdf", tmp_path)

    assert read_original_text("report.pdf", tmp_path) == original


def test_read_original_text_round_trips_empty_string(tmp_path):
    write_original_text("", "empty.txt", tmp_path)
    assert read_original_text("empty.txt", tmp_path) == ""


def test_read_original_text_returns_none_when_missing(tmp_path):
    assert read_original_text("missing.txt", tmp_path) is None


def test_read_sentences_index_round_trips_list(tmp_path):
    sentences = ["第一句。", "第二句！", "第三句？"]
    write_sentences_index(sentences, "report.pdf", tmp_path)

    assert read_sentences_index("report.pdf", tmp_path) == sentences


def test_read_sentences_index_returns_none_when_missing(tmp_path):
    assert read_sentences_index("missing.txt", tmp_path) is None
