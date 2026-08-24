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


# 以下擷取自 labor-compliance-collector 資料集實際樣本（D0070148 建築物室內
# 裝修管理辦法），涵蓋多句條文、單句條文、已刪除條文三種真實案例。
SAMPLE_ARTICLES = [
    {
        "ArticleType": "A",
        "ArticleNo": "第 1 條",
        "ArticleContent": "本辦法依建築法（以下簡稱本法）第七十七條之二第四項規定訂定之。",
    },
    {
        "ArticleType": "A",
        "ArticleNo": "第 3 條",
        "ArticleContent": (
            "本辦法所稱室內裝修，指除壁紙、壁布、窗簾、家具、活動隔屏、地氈等之黏貼及擺設外之下列行為：\r\n"
            "一、固著於建築物構造體之天花板裝修。\r\n二、內部牆面裝修。"
        ),
    },
    {
        "ArticleType": "A",
        "ArticleNo": "第 21 條",
        "ArticleContent": "（刪除）",
    },
]


def test_build_article_aware_chunks_one_chunk_per_article():
    chunks = svc.build_article_aware_chunks(SAMPLE_ARTICLES)

    # 第 21 條「（刪除）」佔位條文應被濾除，剩下第 1、3 條共 2 塊
    assert len(chunks) == 2
    assert [c.article_no for c in chunks] == ["第 1 條", "第 3 條"]
    assert [c.total_chunks for c in chunks] == [2, 2]
    assert [c.index for c in chunks] == [1, 2]


def test_build_article_aware_chunks_uses_article_local_sentence_range():
    chunks = svc.build_article_aware_chunks(SAMPLE_ARTICLES)

    single_sentence_article = chunks[0]
    assert single_sentence_article.source_sentence_start == 1
    assert single_sentence_article.source_sentence_end == 1

    multi_sentence_article = chunks[1]
    assert multi_sentence_article.source_sentence_start == 1
    assert multi_sentence_article.source_sentence_end == 3
    assert len(multi_sentence_article.original_sentences) == 3


def test_build_article_aware_chunks_skips_deleted_and_empty_articles():
    articles = [
        {"ArticleNo": "第 1 條", "ArticleContent": "有效條文內容。"},
        {"ArticleNo": "第 2 條", "ArticleContent": "（刪除）"},
        {"ArticleNo": "第 3 條", "ArticleContent": "  "},
        {"ArticleNo": "第 4 條", "ArticleContent": "另一條有效內容。"},
    ]

    chunks = svc.build_article_aware_chunks(articles)

    assert [c.article_no for c in chunks] == ["第 1 條", "第 4 條"]
    assert [c.total_chunks for c in chunks] == [2, 2]


def test_build_article_aware_chunks_empty_input_returns_empty_list():
    assert svc.build_article_aware_chunks([]) == []
    assert svc.build_article_aware_chunks([{"ArticleNo": "第 1 條", "ArticleContent": "（刪除）"}]) == []


def test_build_article_aware_chunks_skips_chapter_headers_with_empty_article_no():
    """實測發現（N0030001 勞動基準法）：`payload.articles` 混入
    `ArticleType: "C"` 的章節標題項目，`ArticleNo` 恆為空字串、
    `ArticleContent` 是章節標題文字（如「第一章　總則」），不是可供 SVO
    抽取的條文——須依 `ArticleNo` 是否為空白濾除，否則章節標題會被誤當成
    一條「條文」送進抽取管線。"""
    articles = [
        {"ArticleType": "C", "ArticleNo": "", "ArticleContent": "第 一 章 總則"},
        {"ArticleType": "A", "ArticleNo": "第 1 條", "ArticleContent": "為規定勞動條件最低標準訂定之。"},
        {"ArticleType": "C", "ArticleNo": "", "ArticleContent": "第 二 章 勞動契約"},
        {"ArticleType": "A", "ArticleNo": "第 9 條", "ArticleContent": "勞動契約分為定期契約及不定期契約。"},
    ]

    chunks = svc.build_article_aware_chunks(articles)

    assert [c.article_no for c in chunks] == ["第 1 條", "第 9 條"]
    assert [c.total_chunks for c in chunks] == [2, 2]


def test_fixed_sentence_group_chunking_matches_build_svo_chunks():
    originals = ["一句。", "二句。", "三句。"]
    normalized = ["一句。", "二句。", "三句。"]

    strategy = svc.FixedSentenceGroupChunking(originals, normalized, max_sentences=2, overlap_sentences=0)
    via_strategy = strategy.build_chunks()
    via_function = svc.build_svo_chunks(originals, normalized, max_sentences=2, overlap_sentences=0)

    assert via_strategy == via_function
    assert all(c.article_no is None for c in via_strategy)


def test_article_aware_chunking_strategy_matches_function():
    strategy = svc.ArticleAwareChunking(SAMPLE_ARTICLES)

    assert strategy.build_chunks() == svc.build_article_aware_chunks(SAMPLE_ARTICLES)


def test_write_svo_chunks_includes_article_no_in_frontmatter_when_present(tmp_path):
    chunks = svc.build_article_aware_chunks(SAMPLE_ARTICLES)

    paths = svc.write_svo_chunks(chunks, "D0070148_建築物室內裝修管理辦法", tmp_path)

    content = paths[0].read_text(encoding="utf-8")
    assert 'article_no: "第 1 條"' in content

    index = json.loads((tmp_path / "D0070148_建築物室內裝修管理辦法" / "svo_index.json").read_text(encoding="utf-8"))
    assert index["chunks"][0]["article_no"] == "第 1 條"
    assert index["chunks"][1]["article_no"] == "第 3 條"
