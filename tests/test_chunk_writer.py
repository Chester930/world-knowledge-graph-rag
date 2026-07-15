from pathlib import Path

from parser.chunk_writer import write_chunks_as_markdown, _safe_filename_stem


def test_writes_one_file_per_chunk_with_expected_naming(tmp_path):
    chunks = ["第一段內容。", "第二段內容。", "第三段內容。"]
    paths = write_chunks_as_markdown(chunks, "report.pdf", tmp_path)

    assert len(paths) == 3
    names = sorted(p.name for p in paths)
    assert names == [
        "report__chunk-001-of-003.md",
        "report__chunk-002-of-003.md",
        "report__chunk-003-of-003.md",
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


def test_output_dir_is_created_if_missing(tmp_path):
    target = tmp_path / "nested" / "chunks"
    assert not target.exists()

    write_chunks_as_markdown(["內容"], "a.txt", target)

    assert target.exists()
    assert len(list(target.glob("*.md"))) == 1


def test_empty_chunks_returns_empty_list_and_does_not_crash(tmp_path):
    paths = write_chunks_as_markdown([], "empty.txt", tmp_path)
    assert paths == []


def test_rerun_with_fewer_chunks_cleans_up_stale_files(tmp_path):
    """迴歸測試：同一來源重新處理後分塊數變少時，舊有多出來的分塊檔案應被清除，
    避免殘留過期、跟目前內容對不上的檔案。"""
    write_chunks_as_markdown(["a", "b", "c", "d", "e"], "doc.txt", tmp_path)
    assert len(list(tmp_path.glob("doc__chunk-*.md"))) == 5

    write_chunks_as_markdown(["x", "y"], "doc.txt", tmp_path)
    remaining = sorted(p.name for p in tmp_path.glob("doc__chunk-*.md"))

    assert remaining == ["doc__chunk-001-of-002.md", "doc__chunk-002-of-002.md"]


def test_rerun_does_not_affect_other_sources_in_same_directory(tmp_path):
    write_chunks_as_markdown(["a", "b"], "doc_one.txt", tmp_path)
    write_chunks_as_markdown(["c"], "doc_two.txt", tmp_path)

    write_chunks_as_markdown(["z"], "doc_one.txt", tmp_path)

    remaining = sorted(p.name for p in tmp_path.glob("*.md"))
    assert remaining == ["doc_one__chunk-001-of-001.md", "doc_two__chunk-001-of-001.md"]


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
    assert paths[0].name == "big__chunk-0001-of-1234.md"
    assert paths[-1].name == "big__chunk-1234-of-1234.md"
