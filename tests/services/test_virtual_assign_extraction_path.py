import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from services import classify_service, document_record_service, ingestion_service
from services import svo_service
from services.extraction_worker import _find_chunk


def _raise_provider_error():
    raise RuntimeError("provider intentionally disabled for path test")


def _patch_trigger_dependencies(monkeypatch, tmp_path, kg_id, kg_folder):
    class FakeKGRepository:
        def __init__(self, driver):
            self.driver = driver

        async def get(self, requested_id):
            assert requested_id == kg_id
            return SimpleNamespace(
                folder_path=kg_folder,
                pronoun_lexicon_exclude=[],
                domain_pack=None,
            )

    monkeypatch.setattr(svo_service, "KGRepository", FakeKGRepository)
    monkeypatch.setattr(svo_service, "get_embedding_provider", _raise_provider_error)
    monkeypatch.setattr(svo_service, "get_llm_provider", _raise_provider_error)
    monkeypatch.setattr(svo_service.task_queue_service, "enqueue", lambda *args: None)
    monkeypatch.setattr(svo_service, "task_queue_db_path", lambda: tmp_path / "task_queue.db")
    monkeypatch.setattr(
        svo_service.document_record_service,
        "set_svo_chunk_total",
        lambda *args: None,
    )


def _stage_and_assign(tmp_path):
    staging = tmp_path / "staging"
    kg_folder = tmp_path / "kg"
    staging.mkdir()
    kg_folder.mkdir()
    doc_folder, _record = ingestion_service.chunk_and_stage(
        "第一句說明用途。第二句說明內容。第三句補充範圍。",
        "a8_demo.txt",
        staging,
    )
    kg_id = uuid4()
    assigned_path = classify_service.assign_document_to_kg(
        doc_folder,
        classify_service.KGInfo(kg_id=kg_id, kg_name="A8", folder_path=kg_folder),
        "manual",
    )
    return staging, kg_folder, kg_id, doc_folder, assigned_path


@pytest.mark.asyncio
async def test_virtual_assign_svo_index_written_under_kg_folder(tmp_path, monkeypatch):
    _staging, kg_folder, kg_id, doc_folder, assigned_path = _stage_and_assign(tmp_path)
    _patch_trigger_dependencies(monkeypatch, tmp_path, kg_id, kg_folder)

    await svo_service.trigger_extraction(
        object(), assigned_path, kg_id, kg_folder=kg_folder,
    )

    assert (kg_folder / doc_folder.name / "svo_index.json").exists()
    assert _find_chunk(kg_folder, "a8_demo.txt", 1) is not None


@pytest.mark.asyncio
async def test_virtual_assign_staging_not_polluted_with_svo_output(tmp_path, monkeypatch):
    staging, kg_folder, kg_id, doc_folder, assigned_path = _stage_and_assign(tmp_path)
    _patch_trigger_dependencies(monkeypatch, tmp_path, kg_id, kg_folder)

    await svo_service.trigger_extraction(
        object(), assigned_path, kg_id, kg_folder=kg_folder,
    )

    assert not (staging / doc_folder.name / "svo_index.json").exists()


def test_virtual_assign_record_updated_in_original_folder(tmp_path, monkeypatch):
    _staging, kg_folder, _kg_id, doc_folder, _assigned_path = _stage_and_assign(tmp_path)
    from services.classify_service import resolve_document_folder

    resolved = resolve_document_folder(kg_folder, doc_folder.name)
    document_record_service.record_chunk_completed(resolved, 1)

    updated = document_record_service.read_record(doc_folder)
    assert updated is not None
    assert 1 in updated.completed_chunk_indices
    assert not (kg_folder / doc_folder.name / "_record.json").exists()


@pytest.mark.asyncio
async def test_physical_move_behavior_unchanged(tmp_path, monkeypatch):
    staging = tmp_path / "staging"
    kg_folder = tmp_path / "kg"
    staging.mkdir()
    kg_folder.mkdir()
    doc_folder, _record = ingestion_service.chunk_and_stage(
        "實體搬移模式文件。",
        "physical.txt",
        staging,
    )
    kg_id = uuid4()
    dest = classify_service.assign_document_to_kg(
        doc_folder,
        classify_service.KGInfo(kg_id=kg_id, kg_name="A8", folder_path=kg_folder),
        "manual",
        move_physical=True,
    )
    _patch_trigger_dependencies(monkeypatch, tmp_path, kg_id, kg_folder)

    await svo_service.trigger_extraction(object(), dest, kg_id)

    assert (kg_folder / dest.name / "svo_index.json").exists()
    assert (kg_folder / dest.name / "_record.json").exists()


def test_resolve_document_folder_cases(tmp_path):
    from services.classify_service import resolve_document_folder

    kg_folder = tmp_path / "kg"
    kg_folder.mkdir()

    physical = kg_folder / "physical-doc"
    physical.mkdir()
    assert resolve_document_folder(kg_folder, "physical-doc") == physical

    source = tmp_path / "staging-doc"
    source.mkdir()
    (kg_folder / "_members.json").write_text(
        json.dumps({
            "kg_id": str(uuid4()),
            "assigned_documents": [{
                "doc_id": "virtual-doc",
                "source_path": str(source),
            }],
        }),
        encoding="utf-8",
    )
    assert resolve_document_folder(kg_folder, "virtual-doc") == source

    assert resolve_document_folder(kg_folder, "missing-doc") == kg_folder / "missing-doc"
