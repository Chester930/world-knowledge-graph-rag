import json

import pytest

from services import svo_chunking as svc


def test_build_svo_chunks_tracks_original_sentence_range():
    originals = ["馬斯克創立了 SpaceX。", "他隨後研發了獵鷹火箭。", "它是一枚可回收火箭。"]
    normalized = ["馬斯克創立了 SpaceX。", "馬斯克隨後研發了獵鷹火箭。", "獵鷹火箭是一枚可回收火箭。"]

    chunks = svc.build_svo_chunks(originals, normalized, max_chars=28)

    assert len(chunks) == 2
    assert chunks[0].source_sentence_start == 1
    assert chunks[0].source_sentence_end == 2
    assert chunks[0].original_sentences == originals[:2]
    assert chunks[0].normalized_sentences == normalized[:2]
    assert "馬斯克隨後" in chunks[0].text
    assert chunks[1].source_sentence_start == 3
    assert chunks[1].source_sentence_end == 3


def test_build_svo_chunks_rejects_sentence_count_mismatch():
    with pytest.raises(ValueError, match="數量必須一致"):
        svc.build_svo_chunks(["原句一。", "原句二。"], ["標準化後合併成一句。"])


def test_single_sentence_over_limit_stays_intact():
    sentence = "很長的句子" * 20
    chunks = svc.build_svo_chunks([sentence], [sentence], max_chars=10)

    assert len(chunks) == 1
    assert chunks[0].text == sentence


def test_write_svo_chunks_writes_files_and_index(tmp_path):
    chunks = svc.build_svo_chunks(
        ["原句一。", "原句二。"],
        ["標準句一。", "標準句二。"],
        max_chars=100,
    )

    paths = svc.write_svo_chunks(chunks, "report.txt", tmp_path)

    assert [p.name for p in paths] == ["svo-chunk-001-of-001.md"]
    content = paths[0].read_text(encoding="utf-8")
    assert "svo_chunk_index: 1" in content
    assert "source_sentence_start: 1" in content
    assert "source_sentence_end: 2" in content
    assert "標準句一。" in content

    index = json.loads((tmp_path / "report" / "svo_index.json").read_text(encoding="utf-8"))
    assert index["source"] == "report.txt"
    assert index["chunks"][0]["original_sentences"] == ["原句一。", "原句二。"]
    assert index["chunks"][0]["normalized_sentences"] == ["標準句一。", "標準句二。"]


def test_rerun_cleans_stale_svo_chunks_without_touching_rag_chunks(tmp_path):
    first = svc.build_svo_chunks(["一。", "二。"], ["一。", "二。"], max_chars=2)
    svc.write_svo_chunks(first, "doc.txt", tmp_path)
    doc_folder = tmp_path / "doc"
    (doc_folder / "chunk-001-of-001.md").write_text("rag chunk", encoding="utf-8")

    second = svc.build_svo_chunks(["新。"], ["新。"], max_chars=100)
    svc.write_svo_chunks(second, "doc.txt", tmp_path)

    assert sorted(p.name for p in doc_folder.glob("svo-chunk-*.md")) == ["svo-chunk-001-of-001.md"]
    assert (doc_folder / "chunk-001-of-001.md").read_text(encoding="utf-8") == "rag chunk"


def test_prepare_svo_chunks_from_text_uses_shared_sentence_splitter(tmp_path):
    original = "第一句。第二句？"
    normalized = "第一句。標準化第二句？"

    paths, chunks = svc.prepare_svo_chunks(original, normalized, "note.md", tmp_path)

    assert len(paths) == 1
    assert chunks[0].source_sentence_start == 1
    assert chunks[0].source_sentence_end == 2
    assert svc.read_svo_index(tmp_path / "note")["total_svo_chunks"] == 1
