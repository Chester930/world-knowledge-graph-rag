import json

import pytest

from services import svo_chunking as svc


def test_build_svo_chunks_tracks_original_sentence_range():
    originals = ["馬斯克創立了 SpaceX。", "他隨後研發了獵鷹火箭。", "它是一枚可回收火箭。"]
    normalized = ["馬斯克創立了 SpaceX。", "馬斯克隨後研發了獵鷹火箭。", "獵鷹火箭是一枚可回收火箭。"]

    chunks = svc.build_svo_chunks(originals, normalized, max_sentences=2, overlap_sentences=0)

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


def test_max_sentences_cap_splits_chunks():
    sentences = [f"第{i}句。" for i in range(1, 8)]  # 7 個短句

    chunks = svc.build_svo_chunks(sentences, sentences, max_sentences=5, overlap_sentences=0)

    assert len(chunks) == 2
    assert chunks[0].source_sentence_start == 1
    assert chunks[0].source_sentence_end == 5
    assert chunks[1].source_sentence_start == 6
    assert chunks[1].source_sentence_end == 7


def test_max_sentences_must_be_positive():
    with pytest.raises(ValueError, match="max_sentences"):
        svc.build_svo_chunks(["句子。"], ["句子。"], max_sentences=0)


def test_overlap_sentences_must_be_smaller_than_max_sentences():
    with pytest.raises(ValueError, match="overlap_sentences"):
        svc.build_svo_chunks(["句子。"], ["句子。"], max_sentences=5, overlap_sentences=5)


def test_default_chunk_size_matches_paper_decision():
    assert svc.DEFAULT_SVO_CHUNK_MAX_SENTENCES == 5
    assert svc.DEFAULT_SVO_CHUNK_OVERLAP_SENTENCES == 2


def test_default_overlap_produces_1_5_4_8_7_11_pattern():
    """對應 2026-07-22 使用者確認的切塊演算法：起始點公差 3（= 5 句 - 重疊
    2 句）、每塊最多 5 句，序列為 1-5、4-8、7-11。"""
    sentences = [f"第{i}句。" for i in range(1, 12)]  # 11 句

    chunks = svc.build_svo_chunks(sentences, sentences)

    ranges = [(c.source_sentence_start, c.source_sentence_end) for c in chunks]
    assert ranges == [(1, 5), (4, 8), (7, 11)]


def test_every_sentence_union_of_its_chunks_covers_front_two_and_back_two():
    """對應使用者提出的設計目標：每一句透過其所屬（最多兩個）chunk 的聯集，
    都能拿到前 2 句與後 2 句（文件開頭/結尾因為沒有更多句子，前後文自然
    受限，不算違反）。"""
    total = 20
    sentences = [f"第{i}句。" for i in range(1, total + 1)]

    chunks = svc.build_svo_chunks(sentences, sentences)

    covering = {i: [] for i in range(1, total + 1)}
    for chunk in chunks:
        for s in range(chunk.source_sentence_start, chunk.source_sentence_end + 1):
            covering[s].append((chunk.source_sentence_start, chunk.source_sentence_end))

    for s in range(1, total + 1):
        union_start = min(r[0] for r in covering[s])
        union_end = max(r[1] for r in covering[s])
        expected_before = min(2, s - 1)
        expected_after = min(2, total - s)
        assert s - union_start >= expected_before, f"句 {s} 前文不足：{covering[s]}"
        assert union_end - s >= expected_after, f"句 {s} 後文不足：{covering[s]}"


def test_write_svo_chunks_writes_files_and_index(tmp_path):
    chunks = svc.build_svo_chunks(
        ["原句一。", "原句二。"],
        ["標準句一。", "標準句二。"],
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
    first = svc.build_svo_chunks(["一。", "二。"], ["一。", "二。"], max_sentences=1, overlap_sentences=0)
    svc.write_svo_chunks(first, "doc.txt", tmp_path)
    doc_folder = tmp_path / "doc"
    (doc_folder / "chunk-001-of-001.md").write_text("rag chunk", encoding="utf-8")

    second = svc.build_svo_chunks(["新。"], ["新。"])
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
