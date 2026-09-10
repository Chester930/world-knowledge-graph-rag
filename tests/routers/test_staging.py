from pathlib import Path
from uuid import uuid4

import pytest

from core import config
from routers import staging
from services import classify_service, document_record_service


def _make_staged_doc(staging_dir: Path, name: str, *, with_record: bool = True, chunks: int = 2) -> Path:
    folder = staging_dir / name
    folder.mkdir(parents=True)
    for i in range(1, chunks + 1):
        (folder / f"chunk-{i:03d}-of-{chunks:03d}.md").write_text(
            f'---\nsource: "{name}"\nchunk_index: {i}\ntotal_chunks: {chunks}\n---\n\n第{i}段\n',
            encoding="utf-8",
        )
    if with_record:
        document_record_service.init_record(folder, source=name, total_chunks=chunks)
    return folder


@pytest.mark.asyncio
async def test_list_pool_returns_items_with_record_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    staging_dir = config.staging_folder()
    _make_staged_doc(staging_dir, "報告A")
    ghost = _make_staged_doc(staging_dir, "無記錄檔", with_record=False)
    (ghost / "_record.json").unlink(missing_ok=True)

    items = await staging.list_pool()

    by_name = {it.folder_name: it for it in items}
    assert set(by_name) == {"報告A", "無記錄檔"}
    assert by_name["報告A"].record is not None
    assert by_name["報告A"].chunk_files == 2
    assert by_name["報告A"].has_document_vector is False
    assert by_name["無記錄檔"].record is None


@pytest.mark.asyncio
async def test_list_pool_empty_when_no_staging_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path / "nonexistent"))
    assert await staging.list_pool() == []


@pytest.mark.asyncio
async def test_classify_one_404_when_folder_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    config.staging_folder().mkdir(parents=True)

    with pytest.raises(Exception) as exc:
        await staging.classify_one("不存在")
    assert getattr(exc.value, "status_code", None) == 404


@pytest.mark.asyncio
async def test_classify_one_scores_single_doc_against_known_kgs(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    staging_dir = config.staging_folder()
    _make_staged_doc(staging_dir, "報告A", chunks=1)

    class _Fake:
        async def encode_batch(self, texts):
            return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(classify_service, "get_embedding_provider", lambda: _Fake())
    monkeypatch.setattr(classify_service, "embedding_signature", lambda: "test:fake")

    kg = classify_service.KGInfo(kg_id=uuid4(), kg_name="KG-A", folder_path=tmp_path / "kg_a")
    (tmp_path / "kg_a" / "member").mkdir(parents=True)
    (tmp_path / "kg_a" / "member" / "chunk-001-of-001.md").write_text(
        '---\nsource: "m"\nchunk_index: 1\ntotal_chunks: 1\n---\n\nx\n', encoding="utf-8",
    )
    document_record_service.init_record(tmp_path / "kg_a" / "member", source="m", total_chunks=1)
    monkeypatch.setattr(staging, "_known_kgs", lambda: _async_list([kg]))

    result = await staging.classify_one("報告A")

    assert result.filename == "報告A"
    assert result.matched_kg_name == "KG-A"
    assert result.score == pytest.approx(1.0)


async def _async_list(value):
    return value
