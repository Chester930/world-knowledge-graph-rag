import io

import pytest
from PIL import Image, ImageDraw

from parser.core import DocumentParser
from parser.image_pipeline import ImagePipeline, ImagePipelineConfig, ImageProcessResult


def _make_diagram_image(size=(300, 200)) -> Image.Image:
    """產生一張帶有方框與連線的合成圖片，模擬流程圖／架構圖的圖形特徵。"""
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, 120, 80], outline="black", width=3)
    draw.rectangle([180, 20, 280, 80], outline="black", width=3)
    draw.line([120, 50, 180, 50], fill="black", width=3)
    return img


def _make_plain_photo(size=(300, 200)) -> Image.Image:
    """產生一張無明顯結構特徵的純色圖片，模擬普通照片/裝飾圖。"""
    return Image.new("RGB", size, (120, 140, 160))


# --- 空間去重 (IoU 覆蓋率) ---------------------------------------------------

def test_spatial_dedup_skips_when_covered_by_native_text():
    pipeline = ImagePipeline()
    image_bbox = (0, 0, 100, 100)
    text_bboxes = [(0, 0, 100, 80)]  # 覆蓋 80% 面積，超過預設 70% 門檻
    assert pipeline.is_covered_by_native_text(image_bbox, text_bboxes) is True


def test_spatial_dedup_keeps_when_not_covered():
    pipeline = ImagePipeline()
    image_bbox = (0, 0, 100, 100)
    text_bboxes = [(0, 0, 100, 30)]  # 僅覆蓋 30% 面積
    assert pipeline.is_covered_by_native_text(image_bbox, text_bboxes) is False


# --- 雙序列圖號編號 ------------------------------------------------------------

def test_figure_numbering_prefers_caption_over_auto():
    pipeline = ImagePipeline()
    fid, id_type, source = pipeline.assign_figure_id("圖1 系統架構圖", "", "")
    assert fid == "圖1"
    assert id_type == "original"
    assert source == "caption"


def test_figure_numbering_falls_back_to_auto_sequence():
    pipeline = ImagePipeline()
    fid1, id_type1, _ = pipeline.assign_figure_id("", "", "")
    fid2, id_type2, _ = pipeline.assign_figure_id("", "", "")
    assert id_type1 == id_type2 == "auto"
    assert fid1 == "自補圖-1"
    assert fid2 == "自補圖-2"
    assert fid1 != fid2


def test_figure_numbering_original_and_auto_sequences_never_collide():
    pipeline = ImagePipeline()
    original_fid, _, _ = pipeline.assign_figure_id("圖1 標題", "", "")
    auto_fid, id_type, _ = pipeline.assign_figure_id("", "", "")
    assert original_fid == "圖1"
    assert auto_fid == "自補圖-1"
    assert id_type == "auto"


def test_reset_numbering_clears_state_between_documents():
    pipeline = ImagePipeline()
    pipeline.assign_figure_id("", "", "")
    pipeline.reset_numbering()
    fid, _, _ = pipeline.assign_figure_id("", "", "")
    assert fid == "自補圖-1"


# --- 強制旁路規則 ---------------------------------------------------------------

def test_forced_bypass_detects_explicit_reference_in_text():
    pipeline = ImagePipeline()
    assert pipeline.check_forced_bypass("pdf_native", "如下圖所示，系統分為三層") is True


def test_forced_bypass_respects_doc_type_force_list():
    config = ImagePipelineConfig(force_visual_parse_doc_types=["pptx"])
    pipeline = ImagePipeline(config)
    assert pipeline.check_forced_bypass("pptx", "") is True
    assert pipeline.check_forced_bypass("docx", "") is False


def test_forced_bypass_false_when_nothing_matches():
    pipeline = ImagePipeline()
    assert pipeline.check_forced_bypass("docx", "普通段落文字，沒有提到任何圖片") is False


# --- 三維度評分 ------------------------------------------------------------------

def test_score_is_within_0_100_bounds():
    pipeline = ImagePipeline()
    score = pipeline.compute_score(_make_diagram_image(), "pdf_native", "", 0.0)
    assert 0.0 <= score <= 100.0


def test_pptx_base_score_higher_than_docx_given_same_image():
    pipeline = ImagePipeline()
    img = _make_plain_photo()
    pptx_score = pipeline.compute_score(img, "pptx", "識別到的文字", 90.0)
    docx_score = pipeline.compute_score(img, "docx", "識別到的文字", 90.0)
    assert pptx_score > docx_score


def test_low_ocr_confidence_increases_score():
    pipeline = ImagePipeline()
    img = _make_plain_photo()
    low_conf_score = pipeline.compute_score(img, "pdf_native", "亂碼文字", 10.0)
    high_conf_score = pipeline.compute_score(img, "pdf_native", "清楚的文字", 95.0)
    assert low_conf_score > high_conf_score


# --- 圖片前置過濾（裝飾性小圖） -------------------------------------------------

def test_tiny_decorative_image_is_filtered_out():
    pipeline = ImagePipeline()
    tiny_icon = Image.new("RGB", (10, 10), "white")
    result = pipeline.process_image(tiny_icon, doc_type="pptx")
    assert result is None


def test_normal_sized_image_produces_result():
    pipeline = ImagePipeline()
    result = pipeline.process_image(_make_diagram_image(), doc_type="pptx")
    assert result is not None
    assert result.figure_id  # 應被賦予圖號（原生或自補）


# --- 圖理解模型預設關閉、優雅降級 -------------------------------------------------

def test_image_understanding_disabled_by_default_keeps_ocr_only():
    config = ImagePipelineConfig()
    assert config.enable_image_understanding is False
    pipeline = ImagePipeline(config)
    result = pipeline.process_image(_make_diagram_image(), doc_type="pptx", force_image_understanding=False)
    assert result is not None
    assert result.used_image_understanding is False
    assert result.understanding_text is None


def test_vision_call_gracefully_degrades_when_ollama_unreachable():
    """即使強制觸發圖理解，Ollama 服務未啟動時也不應拋出例外，應自動降級保留 OCR。"""
    config = ImagePipelineConfig(
        enable_image_understanding=True,
        ollama_base_url="http://localhost:1",  # 刻意指向不存在的服務
        ollama_timeout_seconds=2,
    )
    pipeline = ImagePipeline(config)
    result = pipeline.process_image(
        _make_diagram_image(), doc_type="pptx", force_image_understanding=True
    )
    assert result is not None
    assert result.understanding_text is None
    assert result.used_image_understanding is False


# --- 輸出格式化 ------------------------------------------------------------------

def test_to_text_block_includes_figure_id_and_content():
    result = ImageProcessResult(
        figure_id="圖1", id_type="original", match_source="caption",
        caption="系統架構圖", ocr_text="輸入 輸出", ocr_confidence=90.0, score=20.0,
    )
    block = result.to_text_block()
    assert "[圖片:圖1]" in block
    assert "系統架構圖" in block
    assert "輸入 輸出" in block


def test_to_text_block_prefers_understanding_over_ocr():
    result = ImageProcessResult(
        figure_id="自補圖-1", id_type="auto", match_source="none",
        ocr_text="模糊文字", score=80.0,
        used_image_understanding=True, understanding_text="流程圖：A 指向 B",
    )
    block = result.to_text_block()
    assert "流程圖：A 指向 B" in block
    assert "模糊文字" not in block


# --- 端對端：PPTX 內嵌圖片會被抽取並回填進最終輸出文字 ---------------------------

def test_pptx_end_to_end_extracts_embedded_image_content(tmp_path):
    pptx = pytest.importorskip("pptx")
    from pptx import Presentation

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # 空白版面

    img_buf = io.BytesIO()
    _make_diagram_image().save(img_buf, format="PNG")
    img_buf.seek(0)
    slide.shapes.add_picture(img_buf, left=0, top=0)

    pptx_path = tmp_path / "sample.pptx"
    prs.save(pptx_path)

    parser = DocumentParser()
    text = parser.parse_file(str(pptx_path))

    assert "[圖片:" in text


def test_docx_end_to_end_extracts_embedded_image_content(tmp_path):
    docx_module = pytest.importorskip("docx")
    from docx import Document

    doc = Document()
    doc.add_paragraph("這是段落文字，下方附有架構圖。")
    img_buf = io.BytesIO()
    _make_diagram_image().save(img_buf, format="PNG")
    img_buf.seek(0)
    doc.add_picture(img_buf)

    docx_path = tmp_path / "sample.docx"
    doc.save(docx_path)

    parser = DocumentParser()
    text = parser.parse_file(str(docx_path))

    assert "[圖片:" in text
    assert "這是段落文字" in text


def test_pdf_end_to_end_extracts_embedded_image_content(tmp_path):
    """驗證 PDF 內嵌 JPEG 圖片能被 pdfminer LTImage 解碼並經圖片管線回填進輸出文字。"""
    reportlab = pytest.importorskip("reportlab")
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader

    img_buf = io.BytesIO()
    _make_diagram_image().save(img_buf, format="JPEG")
    img_buf.seek(0)

    pdf_path = tmp_path / "sample.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=(400, 500))
    # 使用英文內容：reportlab 內建 Helvetica 字型不含 CJK 字形，避免測試混入字型渲染問題。
    # 需要足夠長度的原生文字，避免觸發低品質判定而改走 OCR 備援軌道（該軌道需要 Poppler）。
    c.drawString(50, 460, "Body paragraph describing the system, diagram is shown below.")
    c.drawString(50, 440, "This filler text ensures native text extraction passes the")
    c.drawString(50, 420, "length and readable-character-ratio quality thresholds.")
    c.drawImage(ImageReader(img_buf), 50, 100, width=300, height=200)
    c.save()

    parser = DocumentParser()
    text = parser.parse_file(str(pdf_path))

    assert "Body paragraph" in text
    assert "[圖片:" in text


def test_pdf_image_numbering_follows_visual_order_not_draw_order(tmp_path):
    """迴歸測試：自補圖號的指派順序應依頁面視覺由上到下排序，
    不應受 pdfminer 內部圖形元素發現順序（近似 PDF content stream 繪製順序）影響。"""
    reportlab = pytest.importorskip("reportlab")
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader

    # 以不同尺寸區分兩張圖片，供測試辨識呼叫順序對應到哪一張
    top_img_buf = io.BytesIO()
    Image.new("RGB", (300, 80), (200, 200, 200)).save(top_img_buf, format="JPEG")
    top_img_buf.seek(0)

    bottom_img_buf = io.BytesIO()
    Image.new("RGB", (300, 150), (100, 100, 100)).save(bottom_img_buf, format="JPEG")
    bottom_img_buf.seek(0)

    pdf_path = tmp_path / "order_test.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=(400, 500))
    c.drawString(50, 470, "Body text ensures native extraction passes quality thresholds for this test document reliably.")
    c.drawString(50, 450, "Additional filler sentence to keep the readable character ratio comfortably above the cutoff.")
    # 刻意先畫「視覺上位於下方」的圖片，模擬 pdfminer 內部發現順序與視覺閱讀順序不同的情境
    c.drawImage(ImageReader(bottom_img_buf), 50, 80, width=300, height=150)   # y: 80~230（下方）
    c.drawImage(ImageReader(top_img_buf), 50, 260, width=300, height=80)     # y: 260~340（上方）
    c.save()

    parser = DocumentParser()
    call_order_sizes = []
    original_process_image = parser.image_pipeline.process_image

    def recording_process_image(pil_image, **kwargs):
        call_order_sizes.append(pil_image.size)
        return original_process_image(pil_image, **kwargs)

    parser.image_pipeline.process_image = recording_process_image

    text = parser.parse_file(str(pdf_path))

    assert len(call_order_sizes) == 2
    # 視覺上方的圖（300x80）應先被指派圖號，即使它在 content stream 中是後畫的
    assert call_order_sizes[0] == (300, 80)
    assert call_order_sizes[1] == (300, 150)

    assert "自補圖-1" in text and "自補圖-2" in text
    assert text.index("自補圖-1") < text.index("自補圖-2")


# --- 純文字文件預檢：跳過整套圖片管線 -----------------------------------------

def _make_text_only_pdf(tmp_path, filename="text_only.pdf"):
    reportlab = pytest.importorskip("reportlab")
    from reportlab.pdfgen import canvas

    pdf_path = tmp_path / filename
    c = canvas.Canvas(str(pdf_path), pagesize=(400, 500))
    c.drawString(50, 460, "This document contains only native text and no embedded images at all.")
    c.drawString(50, 440, "It exists purely to validate that the cheap pre-check skips the image pipeline.")
    c.drawString(50, 420, "A third filler line keeps the readable-character-ratio comfortably above threshold.")
    c.save()
    return pdf_path


def test_pdf_has_embedded_images_false_for_text_only_pdf(tmp_path):
    pdf_path = _make_text_only_pdf(tmp_path)
    parser = DocumentParser()
    assert parser._pdf_has_embedded_images(pdf_path) is False


def test_pdf_has_embedded_images_true_when_image_present(tmp_path):
    reportlab = pytest.importorskip("reportlab")
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader

    img_buf = io.BytesIO()
    _make_diagram_image().save(img_buf, format="JPEG")
    img_buf.seek(0)

    pdf_path = tmp_path / "has_image.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=(400, 500))
    c.drawString(50, 460, "Body text plus an embedded diagram below it for this test document.")
    c.drawImage(ImageReader(img_buf), 50, 100, width=300, height=200)
    c.save()

    parser = DocumentParser()
    assert parser._pdf_has_embedded_images(pdf_path) is True


def test_pdf_text_only_skips_image_pipeline_entirely(tmp_path, monkeypatch):
    """迴歸測試：純文字 PDF 不應觸發 _extract_pdf_images_text（避免重複 extract_pages()）。"""
    pdf_path = _make_text_only_pdf(tmp_path)
    parser = DocumentParser()

    called = []
    original = parser._extract_pdf_images_text

    def spy(path):
        called.append(path)
        return original(path)

    monkeypatch.setattr(parser, "_extract_pdf_images_text", spy)

    text = parser.parse_file(str(pdf_path))

    assert called == []
    assert "[圖片:" not in text
    assert "This document contains only native text" in text


def test_pdf_with_image_still_invokes_image_pipeline(tmp_path, monkeypatch):
    """對照組：含圖片的 PDF 仍應正常觸發圖片管線，確認預檢沒有誤傷正常情境。"""
    reportlab = pytest.importorskip("reportlab")
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader

    img_buf = io.BytesIO()
    _make_diagram_image().save(img_buf, format="JPEG")
    img_buf.seek(0)

    pdf_path = tmp_path / "with_image.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=(400, 500))
    c.drawString(50, 460, "Body text plus an embedded diagram shown further below on this page.")
    c.drawString(50, 440, "This filler line ensures native text extraction passes the quality gate.")
    c.drawString(50, 420, "A third line keeps the readable-character-ratio comfortably above cutoff.")
    c.drawImage(ImageReader(img_buf), 50, 100, width=300, height=200)
    c.save()

    parser = DocumentParser()

    called = []
    original = parser._extract_pdf_images_text

    def spy(path):
        called.append(path)
        return original(path)

    monkeypatch.setattr(parser, "_extract_pdf_images_text", spy)

    text = parser.parse_file(str(pdf_path))

    assert len(called) == 1
    assert "[圖片:" in text


def test_docx_has_embedded_images_false_for_text_only_docx(tmp_path):
    docx_module = pytest.importorskip("docx")
    from docx import Document

    doc = Document()
    doc.add_paragraph("這是一份完全沒有圖片的純文字文件。")
    doc.add_paragraph("第二段落，用來確認純文字偵測邏輯正確運作。")
    docx_path = tmp_path / "text_only.docx"
    doc.save(docx_path)

    parser = DocumentParser()
    reopened = Document(docx_path)
    assert parser._docx_has_embedded_images(reopened) is False


def test_docx_text_only_skips_paragraph_image_scan(tmp_path, monkeypatch):
    """迴歸測試：純文字 DOCX 不應對任何段落呼叫 _process_docx_paragraph_images。"""
    docx_module = pytest.importorskip("docx")
    from docx import Document

    doc = Document()
    for i in range(5):
        doc.add_paragraph(f"第 {i + 1} 段純文字內容，沒有任何內嵌圖片。")
    docx_path = tmp_path / "text_only_multi.docx"
    doc.save(docx_path)

    parser = DocumentParser()
    called = []
    original = parser._process_docx_paragraph_images

    def spy(doc_obj, paragraph, full_doc_text):
        called.append(paragraph)
        return original(doc_obj, paragraph, full_doc_text)

    monkeypatch.setattr(parser, "_process_docx_paragraph_images", spy)

    text = parser.parse_file(str(docx_path))

    assert called == []
    assert "[圖片:" not in text
    assert "第 1 段純文字內容" in text


def test_docx_with_image_still_invokes_paragraph_image_scan(tmp_path, monkeypatch):
    """對照組：含圖片的 DOCX 仍應正常掃描段落圖片，確認預檢沒有誤傷正常情境。"""
    docx_module = pytest.importorskip("docx")
    from docx import Document

    doc = Document()
    doc.add_paragraph("這段文字後面有一張圖片。")
    img_buf = io.BytesIO()
    _make_diagram_image().save(img_buf, format="PNG")
    img_buf.seek(0)
    doc.add_picture(img_buf)
    docx_path = tmp_path / "with_image.docx"
    doc.save(docx_path)

    parser = DocumentParser()
    called = []
    original = parser._process_docx_paragraph_images

    def spy(doc_obj, paragraph, full_doc_text):
        called.append(paragraph)
        return original(doc_obj, paragraph, full_doc_text)

    monkeypatch.setattr(parser, "_process_docx_paragraph_images", spy)

    text = parser.parse_file(str(docx_path))

    assert len(called) >= 1
    assert "[圖片:" in text
