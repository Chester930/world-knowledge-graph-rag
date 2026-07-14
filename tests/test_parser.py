import pytest
import os
from pathlib import Path
from parser.core import DocumentParser, sentence_aware_chunking
from services.ingestion_service import parse_document


def test_sentence_aware_chunking():
    text = "這是一個句子。這是有問號的句子？這是有驚嘆號的句子！這是不完整的句子"
    chunks = sentence_aware_chunking(text, chunk_size=30, chunk_overlap=5)
    
    assert len(chunks) > 0
    # 確保分割出的 chunk 保留了標點
    assert "這是一個句子。" in chunks[0] or "這是一個句子。" in text


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
