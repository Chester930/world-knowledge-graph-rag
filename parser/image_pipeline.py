"""圖文統一轉譯管線 (Image Understanding Pipeline)。

實作依據：《文檔轉譯器 最終優化架構總結（可跨模型接續討論）.md》所定稿之架構。

核心底線（不可變）：
1. OCR 文字提取是【核心基礎能力】，預設開啟、不依賴任何圖理解模型。
2. 圖理解語義模型是【可選增強能力】，預設關閉，未安裝/未開啟時自動降級為
   保留 OCR 結果，絕不中斷主解析流程。
3. 算力分層：輕量前置判斷（空間去重 → OCR → 三維度評分）優先，重型的本地
   多模態模型僅在評分達標或命中強制旁路規則時才觸發。

實作順序與規格文件的小幅差異（有意為之，不影響最終輸出語意）：
規格書步驟順序為「圖片編號 → 全域 OCR」，但圖號匹配的第三優先序
（圖片內部列印圖號）需要用到 OCR 文字結果。因此本模組在實作上先執行 OCR，
再進行編號判定，兩個步驟的「輸出結果」與規格書描述完全一致。
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageFilter
except ImportError:
    Image = None
    ImageFilter = None

try:
    import numpy as np
except ImportError:
    np = None

try:
    import pytesseract
except ImportError:
    pytesseract = None

try:
    import requests
except ImportError:
    requests = None


# ---------------------------------------------------------------------------
# 設定與資料結構
# ---------------------------------------------------------------------------

@dataclass
class ImagePipelineConfig:
    """可插拔開關體系。所有欄位皆可由呼叫端覆寫，維持模組隨插即用特性。"""

    # 核心能力開關（預設開啟，獨立於圖理解模型）
    enable_ocr: bool = True

    # 選配增強能力（預設關閉，需本機另行安裝並啟動 Ollama 服務）
    enable_image_understanding: bool = False
    ollama_base_url: str = "http://localhost:11434"
    # qwen2.5vl 對繁體中文與流程圖/架構圖等結構化圖表的理解與 OCR 能力優於 llava，
    # 且 7b 量化後約 6GB，可在 8GB VRAM 等級的消費級 GPU 上順暢運行。
    ollama_vision_model: str = "qwen2.5vl:7b"
    ollama_timeout_seconds: int = 60

    # 三維度評分權重（總和應為 1.0）與升級閾值
    weight_doc_type: float = 0.3
    weight_ocr_confidence: float = 0.4
    weight_graphic_feature: float = 0.3
    score_threshold: float = 60.0

    # 文件類型基礎分（0-100，PPTX 視覺導向機率高故基礎分較高）
    doc_type_base_score: dict = field(default_factory=lambda: {
        "pptx": 90.0,
        "pdf_scanned": 55.0,
        "pdf_native": 25.0,
        "docx": 25.0,
    })

    # 強制旁路：命中即跳過評分，直接觸發圖理解模型
    force_visual_parse_doc_types: List[str] = field(default_factory=list)  # 例如 ["pptx"]

    # 空間去重：原生文字覆蓋率達此比例即跳過該圖片的所有後續處理
    spatial_dedup_coverage_threshold: float = 0.7

    # 裝飾性小圖過濾（寬或高小於此像素值視為 icon/項目符號，直接略過）
    min_image_dimension_px: int = 40

    # 圖號前綴
    auto_figure_id_prefix: str = "自補圖"


_CAPTION_PATTERNS = [
    re.compile(r'(?:圖|附圖|Figure|Fig\.?)\s*[\.:：]?\s*(\d+(?:[-.]\d+)?)', re.IGNORECASE),
]

_INLINE_REFERENCE_PATTERN = re.compile(
    r'(?:如|見|參[見閱]|詳)?(?:上|下)?(?:圖|附圖|Figure|Fig\.?)\s*(\d+(?:[-.]\d+)?)\s*'
    r'(?:所示|所述|說明|shows|illustrates)?',
    re.IGNORECASE,
)

_FORCED_BYPASS_PATTERN = re.compile(
    r'(如下圖|如上圖|下圖所示|上圖所示|圖\s*\d+\s*(?:所示|說明)|'
    r'Figure\s*\d+\s*(?:shows|illustrates|below|above))',
    re.IGNORECASE,
)


@dataclass
class ImageProcessResult:
    """單張圖片的最終處理結果，供 core.py 組裝回文本。"""

    figure_id: str
    id_type: str  # "original" | "auto"
    match_source: str  # "caption" | "inline_reference" | "printed_number" | "none"
    caption: str = ""
    ocr_text: str = ""
    ocr_confidence: float = 0.0
    score: float = 0.0
    score_threshold: float = 60.0  # 產生本結果時實際生效的升級閾值，供 to_text_block() 判斷品質註記
    used_image_understanding: bool = False
    understanding_text: Optional[str] = None
    skipped_reason: Optional[str] = None  # 非 None 時代表此圖不應輸出任何內容

    def to_text_block(self) -> str:
        """格式化為可回填進正文的文字區塊。"""
        if self.skipped_reason is not None:
            return ""

        lines = [f"[圖片:{self.figure_id}]"]
        if self.caption:
            lines.append(f"標題: {self.caption}")

        if self.understanding_text:
            lines.append(f"圖像語義描述（來源: 本地圖理解模型）: {self.understanding_text}")
        elif self.ocr_text:
            quality_note = "，資訊可能不足" if self.score >= self.score_threshold else ""
            lines.append(f"圖片 OCR 文字（來源: OCR{quality_note}）: {self.ocr_text}")
        else:
            lines.append("（圖片無可辨識文字內容）")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主管線
# ---------------------------------------------------------------------------

class ImagePipeline:
    """統一處理各來源（PDF/PPTX/DOCX）內嵌圖片的評分、編號、OCR 與圖理解流程。"""

    def __init__(self, config: Optional[ImagePipelineConfig] = None):
        self.config = config or ImagePipelineConfig()
        self._auto_counter = 0
        self._used_figure_ids: set = set()
        self._vision_unavailable_logged = False

    def reset_numbering(self) -> None:
        """每份新文件開始解析前呼叫，避免跨文件的圖號序列互相汙染。"""
        self._auto_counter = 0
        self._used_figure_ids = set()
        self._vision_unavailable_logged = False

    # -- 空間去重 -----------------------------------------------------------

    def is_covered_by_native_text(
        self,
        image_bbox: Tuple[float, float, float, float],
        text_bboxes: List[Tuple[float, float, float, float]],
    ) -> bool:
        """判斷圖片區域是否已被原生文字大面積覆蓋（如文字背後的裝飾底圖）。

        以「文字覆蓋圖片面積」的聯集比例估算，達到門檻即視為零成本可跳過。
        """
        ix0, iy0, ix1, iy1 = image_bbox
        image_area = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
        if image_area <= 0:
            return True

        covered_area = 0.0
        for bx0, by0, bx1, by1 in text_bboxes:
            ox0, oy0 = max(ix0, bx0), max(iy0, by0)
            ox1, oy1 = min(ix1, bx1), min(iy1, by1)
            if ox1 > ox0 and oy1 > oy0:
                covered_area += (ox1 - ox0) * (oy1 - oy0)

        coverage_ratio = min(1.0, covered_area / image_area)
        return coverage_ratio >= self.config.spatial_dedup_coverage_threshold

    # -- OCR ------------------------------------------------------------

    def _run_ocr(self, pil_image) -> Tuple[str, float]:
        """回傳 (OCR文字, 平均置信度 0-100)。未安裝 pytesseract 時安全降級為空結果。"""
        if not self.config.enable_ocr or pytesseract is None:
            return "", 0.0

        try:
            data = pytesseract.image_to_data(
                pil_image, lang="chi_tra+eng", output_type=pytesseract.Output.DICT
            )
        except Exception:
            try:
                text = pytesseract.image_to_string(pil_image, lang="eng")
                return text.strip(), 50.0 if text.strip() else 0.0
            except Exception:
                return "", 0.0

        words = []
        confidences = []
        for text, conf in zip(data.get("text", []), data.get("conf", [])):
            text = text.strip()
            if not text:
                continue
            words.append(text)
            try:
                conf_val = float(conf)
            except (TypeError, ValueError):
                continue
            if conf_val >= 0:
                confidences.append(conf_val)

        ocr_text = " ".join(words).strip()
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        return ocr_text, avg_confidence

    # -- 三維度評分 -----------------------------------------------------

    def _graphic_feature_score(self, pil_image) -> float:
        """輕量圖形特徵評分：以邊緣密度與規則直線比例估計「流程圖/架構圖」機率。

        不引入 opencv 等重型依賴，改以 PIL 邊緣濾波 + numpy 統計，維持模組輕量化定位。
        """
        if Image is None or ImageFilter is None:
            return 0.0

        try:
            gray = pil_image.convert("L")
            edges = gray.filter(ImageFilter.FIND_EDGES)
        except Exception:
            return 0.0

        if np is None:
            # 無 numpy 時退化為粗略估計：僅用平均像素亮度近似邊緣密度
            try:
                stat_mean = sum(edges.getdata()) / (edges.width * edges.height)
                return min(100.0, (stat_mean / 255.0) * 100.0)
            except Exception:
                return 0.0

        try:
            arr = np.asarray(edges, dtype=np.float32)
            edge_density = float((arr > 40).mean())  # 邊緣像素佔比

            # 規則直線比例：偵測「整列/整欄邊緣像素密集」代表方框、表格線、箭頭等結構線條
            row_line_ratio = float(((arr > 40).mean(axis=1) > 0.3).mean())
            col_line_ratio = float(((arr > 40).mean(axis=0) > 0.3).mean())
            structural_line_score = (row_line_ratio + col_line_ratio) / 2.0

            score = (edge_density * 0.6 + structural_line_score * 0.4) * 100.0
            return max(0.0, min(100.0, score))
        except Exception:
            return 0.0

    def _ocr_confidence_score(self, ocr_text: str, ocr_confidence: float) -> float:
        """OCR 置信度評分：置信度越低（越可能識別失敗）分數越高，代表越需要圖理解模型補足。"""
        base_score = max(0.0, 100.0 - ocr_confidence)
        # 有印出字元但置信度很低：判定為「疑似識別失敗」而非「無字」，強化加分
        if ocr_text.strip() and ocr_confidence < 30.0:
            base_score = max(base_score, 85.0)
        return min(100.0, base_score)

    def compute_score(
        self, pil_image, doc_type: str, ocr_text: str, ocr_confidence: float
    ) -> float:
        doc_type_score = self.config.doc_type_base_score.get(doc_type, 25.0)
        ocr_score = self._ocr_confidence_score(ocr_text, ocr_confidence)
        graphic_score = self._graphic_feature_score(pil_image)

        total = (
            doc_type_score * self.config.weight_doc_type
            + ocr_score * self.config.weight_ocr_confidence
            + graphic_score * self.config.weight_graphic_feature
        )
        return round(total, 2)

    # -- 強制旁路 ---------------------------------------------------------

    def check_forced_bypass(self, doc_type: str, nearby_text: str, force: bool = False) -> bool:
        if force:
            return True
        if doc_type in self.config.force_visual_parse_doc_types:
            return True
        if nearby_text and _FORCED_BYPASS_PATTERN.search(nearby_text):
            return True
        return False

    # -- 圖號雙序列編號 ----------------------------------------------------

    def assign_figure_id(
        self, nearby_caption_text: str, full_doc_text: str, ocr_text: str
    ) -> Tuple[str, str, str]:
        """回傳 (figure_id, id_type, match_source)。

        匹配優先序：圖題標註 > 正文明確圖號引用 > 圖片內部列印圖號 > 無匹配（進入自補序列）。
        """
        # 1. 圖題標註（圖片附近文字，如「圖1 系統架構圖」）
        if nearby_caption_text:
            match = _CAPTION_PATTERNS[0].search(nearby_caption_text)
            if match:
                fid = f"圖{match.group(1)}"
                if fid not in self._used_figure_ids:
                    self._used_figure_ids.add(fid)
                    return fid, "original", "caption"

        # 2. 正文明確圖號引用（如「如圖2所示」）
        if full_doc_text:
            for match in _INLINE_REFERENCE_PATTERN.finditer(full_doc_text):
                fid = f"圖{match.group(1)}"
                if fid not in self._used_figure_ids:
                    self._used_figure_ids.add(fid)
                    return fid, "original", "inline_reference"

        # 3. 圖片內部列印圖號（OCR 文字中出現的圖號字樣）
        if ocr_text:
            match = _CAPTION_PATTERNS[0].search(ocr_text)
            if match:
                fid = f"圖{match.group(1)}"
                if fid not in self._used_figure_ids:
                    self._used_figure_ids.add(fid)
                    return fid, "original", "printed_number"

        # 4. 無匹配：進入系統自補獨立序列，與原生序列永不混序
        self._auto_counter += 1
        fid = f"{self.config.auto_figure_id_prefix}-{self._auto_counter}"
        self._used_figure_ids.add(fid)
        return fid, "auto", "none"

    # -- 本地圖理解模型（Ollama，選配） -------------------------------------

    def _call_ollama_vision(self, pil_image) -> Optional[str]:
        if not self.config.enable_image_understanding:
            return None
        if requests is None or Image is None:
            if not self._vision_unavailable_logged:
                logger.warning(
                    "[ImagePipeline] 未安裝 requests，圖理解模型無法呼叫，自動降級保留 OCR 結果"
                )
                self._vision_unavailable_logged = True
            return None

        try:
            import base64

            buf = io.BytesIO()
            pil_image.convert("RGB").save(buf, format="PNG")
            b64_image = base64.b64encode(buf.getvalue()).decode("utf-8")

            resp = requests.post(
                f"{self.config.ollama_base_url}/api/generate",
                json={
                    "model": self.config.ollama_vision_model,
                    "prompt": (
                        "請描述這張圖片的內容，特別注意其中的流程、結構、層級與元素間的關係，"
                        "以繁體中文簡潔輸出，供後續知識圖譜關係抽取使用。"
                    ),
                    "images": [b64_image],
                    "stream": False,
                },
                timeout=self.config.ollama_timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()
            description = (data.get("response") or "").strip()
            return description or None
        except Exception as e:
            if not self._vision_unavailable_logged:
                logger.warning(
                    "[ImagePipeline] 呼叫本地圖理解模型失敗（%s），自動降級保留 OCR 結果", str(e)
                )
                self._vision_unavailable_logged = True
            return None

    # -- 對外主入口 ---------------------------------------------------------

    def process_image(
        self,
        pil_image,
        *,
        doc_type: str,
        nearby_caption_text: str = "",
        full_doc_text: str = "",
        force_image_understanding: bool = False,
    ) -> Optional[ImageProcessResult]:
        """處理單張圖片，回傳結果；若判定為裝飾性圖片則回傳 None（不佔用圖號序列）。"""
        if pil_image is None:
            return None

        width, height = pil_image.size
        if width < self.config.min_image_dimension_px or height < self.config.min_image_dimension_px:
            return None  # 裝飾性小圖 / icon / 項目符號，前置過濾

        ocr_text, ocr_confidence = self._run_ocr(pil_image)

        figure_id, id_type, match_source = self.assign_figure_id(
            nearby_caption_text, full_doc_text, ocr_text
        )

        score = self.compute_score(pil_image, doc_type, ocr_text, ocr_confidence)
        forced = self.check_forced_bypass(doc_type, nearby_caption_text or full_doc_text, force_image_understanding)

        understanding_text = None
        used_understanding = False
        if forced or score >= self.config.score_threshold:
            understanding_text = self._call_ollama_vision(pil_image)
            used_understanding = understanding_text is not None

        caption_match = _CAPTION_PATTERNS[0].search(nearby_caption_text) if nearby_caption_text else None
        caption = nearby_caption_text.strip() if caption_match else ""

        return ImageProcessResult(
            figure_id=figure_id,
            id_type=id_type,
            match_source=match_source,
            caption=caption,
            ocr_text=ocr_text,
            ocr_confidence=ocr_confidence,
            score=score,
            score_threshold=self.config.score_threshold,
            used_image_understanding=used_understanding,
            understanding_text=understanding_text,
        )
