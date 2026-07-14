import os
import re
import tempfile
from pathlib import Path
from typing import List, Optional

# 第三方庫導入與容錯處理
try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTTextContainer, LTChar
except ImportError:
    extract_pages = None

try:
    from docx import Document as DocxDocument
except ImportError:
    DocxDocument = None

try:
    from pptx import Presentation
except ImportError:
    Presentation = None

try:
    from pdf2image import convert_from_path
    import pytesseract
    from PIL import Image
    # Windows 預設 tesseract 安裝路徑檢查，以防 PATH 未設定
    TESSERACT_CMD_CANDIDATES = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        r"C:\Users\666\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"
    ]
    for cand in TESSERACT_CMD_CANDIDATES:
        if os.path.exists(cand):
            pytesseract.pytesseract.tesseract_cmd = cand
            break
except ImportError:
    convert_from_path = None
    pytesseract = None

try:
    import trafilatura
except ImportError:
    trafilatura = None

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    YouTubeTranscriptApi = None

try:
    import whisper
except ImportError:
    whisper = None

try:
    import yt_dlp
except ImportError:
    yt_dlp = None


_whisper_model_cache = {}


def _transcribe_with_whisper(path: str, model_size: str = "tiny") -> str:
    """共用的本地 Whisper 語音轉文字函式，供音檔上傳與 YouTube 音軌備援共用。

    模型載入後會快取在行程記憶體中，避免重複解析時重複載入。
    """
    if whisper is None:
        raise ImportError("未安裝 openai-whisper 套件，請執行 pip install openai-whisper")

    if model_size not in _whisper_model_cache:
        _whisper_model_cache[model_size] = whisper.load_model(model_size)
    model = _whisper_model_cache[model_size]

    result = model.transcribe(str(path))
    return result.get("text", "").strip()


class DocumentParserError(Exception):
    """文件解析異常基類"""
    pass


class DocumentParser:
    """統一文件解析進入點"""

    def parse_file(self, file_path: str) -> str:
        """根據檔案副檔名進行路由解析，返回純文字內容。"""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"找不到檔案: {file_path}")

        suffix = path.suffix.lower()
        if suffix in [".txt", ".md"]:
            return self._parse_text(path)
        elif suffix == ".pdf":
            return self._parse_pdf(path)
        elif suffix in [".docx", ".doc"]:
            return self._parse_docx(path)
        elif suffix in [".pptx", ".ppt"]:
            return self._parse_pptx(path)
        elif suffix in [".mp3", ".wav", ".m4a", ".ogg", ".flac", ".mp4", ".mkv", ".webm"]:
            return self._parse_audio(path)
        else:
            raise DocumentParserError(f"不支援的檔案格式: {suffix}")

    def _parse_text(self, path: Path) -> str:
        """解析 TXT 或 Markdown"""
        try:
            # 優先嘗試 UTF-8，失敗則嘗試 Big5 (繁體中文常見編碼) 或 cp950
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                return path.read_text(encoding="big5")
            except UnicodeDecodeError:
                return path.read_text(encoding="cp950", errors="ignore")

    def _parse_docx(self, path: Path) -> str:
        """解析 Word 文件，保留表格 Markdown 格式"""
        if DocxDocument is None:
            raise ImportError("未安裝 python-docx 套件，請執行 pip install python-docx")

        doc = DocxDocument(path)
        content_parts = []

        # 遍歷 docx 的所有子元素，以保留表格與段落的原始順序
        for element in doc.element.body:
            # 如果是段落
            if element.tag.endswith('p'):
                # 尋找對應的 python-docx Paragraph 對象
                for p in doc.paragraphs:
                    if p._element is element:
                        if p.text.strip():
                            content_parts.append(p.text)
                        break
            # 如果是表格
            elif element.tag.endswith('tbl'):
                for t in doc.tables:
                    if t._element is element:
                        # 轉為 Markdown table
                        table_md = self._convert_table_to_markdown(t)
                        if table_md:
                            content_parts.append("\n" + table_md + "\n")
                        break

        return "\n\n".join(content_parts)

    def _convert_table_to_markdown(self, table) -> str:
        """將 python-docx 的 Table 物件轉換為 Markdown 表格語法，保留儲存格內換行"""
        if not table.rows:
            return ""

        md_rows = []
        # 處理標頭列
        header_cells = table.rows[0].cells
        md_rows.append("| " + " | ".join(cell.text.replace("\n", "<br>").strip() for cell in header_cells) + " |")
        md_rows.append("| " + " | ".join("---" for _ in header_cells) + " |")

        # 處理資料列
        for row in table.rows[1:]:
            cells = row.cells
            row_texts = []
            prev_cell = None
            for cell in cells:
                if cell == prev_cell:
                    # 跨欄合併，留空
                    row_texts.append("")
                else:
                    # 將內建換行替換為 <br> 以維持 Markdown 表格單行結構
                    row_texts.append(cell.text.replace("\n", "<br>").strip())
                prev_cell = cell
            md_rows.append("| " + " | ".join(row_texts) + " |")

        return "\n".join(md_rows)

    def _parse_pptx(self, path: Path) -> str:
        """解析 PPTX 投影片"""
        if Presentation is None:
            raise ImportError("未安裝 python-pptx 套件，請執行 pip install python-pptx")

        prs = Presentation(path)
        content_parts = []

        for slide_idx, slide in enumerate(prs.slides):
            slide_text = []
            slide_text.append(f"--- [Slide {slide_idx + 1}] ---")
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    slide_text.append(shape.text.strip())
            content_parts.append("\n".join(slide_text))

        return "\n\n".join(content_parts)

    def _parse_audio(self, path: Path) -> str:
        """使用本地 Whisper 模型進行語音轉文字"""
        try:
            # 使用 tiny 模型，以防使用者下載過久。預設對中文已堪用
            return _transcribe_with_whisper(str(path), model_size="tiny")
        except ImportError:
            raise
        except Exception as e:
            raise DocumentParserError(f"音訊轉譯失敗: {str(e)}")

    def _parse_pdf(self, path: Path) -> str:
        """三層備援 PDF 轉譯主入口"""
        # --- 軌道一：pypdf 快速文本流提取 ---
        text = self._pdf_track_pypdf(path)
        
        # 評估是否需要 Fallback：字元數過少或疑似亂碼
        if self._is_low_quality_text(text):
            # --- 軌道二：pdfminer 佈局感知與雙欄排序提取 ---
            text = self._pdf_track_pdfminer(path)
            
            # 如果依然判定為低品質（例如圖片掃描件），進入軌道三
            if self._is_low_quality_text(text):
                # --- 軌道三：OCR 視覺區域識別解析 ---
                text = self._pdf_track_ocr(path)
                
        return text

    def _pdf_track_pypdf(self, path: Path) -> str:
        """第一軌：使用 pypdf 提取文字"""
        if PdfReader is None:
            return ""
        try:
            reader = PdfReader(path)
            pages_text = []
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    pages_text.append(t)
            return "\n\n".join(pages_text)
        except Exception:
            return ""

    def _pdf_track_pdfminer(self, path: Path) -> str:
        """第二軌：使用 pdfminer 還原閱讀順序與雙欄解析 (混合佈局優化版)"""
        if extract_pages is None:
            return ""
        try:
            pages_text = []
            for page_layout in extract_pages(path):
                page_width = page_layout.width
                mid_x = page_width / 2

                # 提取該頁所有文字容器
                text_containers = []
                for element in page_layout:
                    if isinstance(element, LTTextContainer):
                        text_containers.append(element)

                if not text_containers:
                    continue

                # 1. 混合分流：將「跨欄大標題/全寬物件」與「窄欄正文」區分開來
                span_elements = []  # 跨中線的大型元素 (如 Title)
                column_elements = []  # 需要雙欄分流排序的元素

                for elem in text_containers:
                    width = elem.x1 - elem.x0
                    # 如果寬度大於頁面寬度的 70%，或者明顯橫跨中線且寬度寬
                    if width > (page_width * 0.65) and (elem.x0 < mid_x < elem.x1):
                        span_elements.append(elem)
                    else:
                        column_elements.append(elem)

                # 2. 對需要雙欄分流的元素進行左右分類
                left_col = []
                right_col = []
                for elem in column_elements:
                    elem_mid_x = (elem.x0 + elem.x1) / 2
                    if elem_mid_x < mid_x:
                        left_col.append(elem)
                    else:
                        right_col.append(elem)

                # 3. 各自按 Y1 軸降序（自上而下）排序
                span_elements.sort(key=lambda e: e.y1, reverse=True)
                left_col.sort(key=lambda e: e.y1, reverse=True)
                right_col.sort(key=lambda e: e.y1, reverse=True)

                # 4. 拓撲結構重組：按 Y 軸高度，將單欄元素插回雙欄元素之間
                page_content = []
                left_idx = 0
                right_idx = 0

                # 依高度從上到下依次處理單欄跨欄元素
                for span_elem in span_elements:
                    # 先將高度高於此跨欄元素的所有左右欄元素寫入
                    while left_idx < len(left_col) and left_col[left_idx].y1 > span_elem.y1:
                        page_content.append(left_col[left_idx].get_text().strip())
                        left_idx += 1
                    while right_idx < len(right_col) and right_col[right_idx].y1 > span_elem.y1:
                        page_content.append(right_col[right_idx].get_text().strip())
                        right_idx += 1
                    
                    # 寫入跨欄元素本身 (如論文標題或大圖表)
                    page_content.append(span_elem.get_text().strip())

                # 將剩餘的低於最後一個跨欄元素的所有左右欄元素寫入
                while left_idx < len(left_col):
                    page_content.append(left_col[left_idx].get_text().strip())
                    left_idx += 1
                while right_idx < len(right_col):
                    page_content.append(right_col[right_idx].get_text().strip())
                    right_idx += 1

                pages_text.append("\n".join(page_content))

            return "\n\n".join(pages_text)
        except Exception:
            return ""

    def _pdf_track_ocr(self, path: Path) -> str:
        """第三軌：PDF 轉影像後使用 pytesseract 進行 OCR"""
        if convert_from_path is None or pytesseract is None:
            raise ImportError(
                "未安裝 pdf2image 或 pytesseract 套件，或系統缺乏 Poppler/Tesseract。"
                "請執行 pip install pdf2image pytesseract 並安裝對應系統工具。"
            )

        try:
            # 將 PDF 所有頁面轉換為 PIL Image 物件
            images = convert_from_path(path)
            ocr_texts = []
            
            for idx, img in enumerate(images):
                # 提取繁體中文 (chi_tra) 和英文 (eng)
                try:
                    text = pytesseract.image_to_string(img, lang="chi_tra+eng")
                except Exception:
                    # 若本機未安裝繁體中文語言包，回退到英文與通用簡體中文
                    text = pytesseract.image_to_string(img, lang="eng")
                
                if text.strip():
                    ocr_texts.append(f"--- [Page {idx + 1} OCR] ---\n" + text.strip())
            
            return "\n\n".join(ocr_texts)
        except Exception as e:
            raise DocumentParserError(f"PDF OCR 解析失敗: {str(e)}")

    def _detect_double_column(self, containers: List[LTTextContainer], mid_x: float) -> bool:
        """啟發式偵測頁面是否為雙欄排版"""
        if len(containers) < 4:
            return False

        left_side_count = 0
        right_side_count = 0
        span_mid_count = 0

        for elem in containers:
            # 寬度太窄的可能是頁碼或小標，不列入判定
            if elem.x1 - elem.x0 < 30:
                continue
            
            # 判斷是否跨越中線
            if elem.x0 < mid_x and elem.x1 > mid_x:
                # 如果中線穿過文字塊，且文字塊寬度大於中線的 20%，視為跨越
                overlap = min(elem.x1, mid_x) - max(elem.x0, mid_x)
                if (elem.x1 - elem.x0) > (mid_x * 0.4):
                    span_mid_count += 1
            elif elem.x1 <= mid_x:
                left_side_count += 1
            elif elem.x0 >= mid_x:
                right_side_count += 1

        # 如果跨越中線的區塊極少，而兩側各有顯著數量的區塊，判定為雙欄
        if span_mid_count <= 2 and left_side_count >= 2 and right_side_count >= 2:
            return True
        return False

    def _is_low_quality_text(self, text: str) -> bool:
        """判定文字是否低品質（如空白、純符號、亂碼或字元數極低）"""
        clean_text = text.strip()
        if not clean_text:
            return True
        
        # 1. 字元數過少（整份文件少於 80 字，通常是掃描件）
        if len(clean_text) < 80:
            return True
            
        # 2. 亂碼與特殊符號比例過高檢測
        # 計算正常可讀中英文字元比例
        alphanumeric_chinese = len(re.findall(r'[\u4e00-\u9fa5a-zA-Z0-9]', clean_text))
        ratio = alphanumeric_chinese / len(clean_text)
        
        # 如果可讀字元比例低於 60%（表示有大量特殊控制碼或亂碼），判定為低品質
        if ratio < 0.6:
            return True
            
        return False


def sentence_aware_chunking(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> List[str]:
    """句子感知的文本切片演算法，確保句子邊界不被粗暴截斷"""
    # 句尾結束符號規則，包含中英文標點
    sentence_endings = re.compile(r'([。！？…\n]|\.\s|\?\s|!\s)')
    
    # 依句尾標點進行文本分割，保留標點符號
    parts = []
    current_pos = 0
    for match in sentence_endings.finditer(text):
        end_pos = match.end()
        parts.append(text[current_pos:end_pos])
        current_pos = end_pos
    if current_pos < len(text):
        parts.append(text[current_pos:])

    chunks = []
    current_chunk = []
    current_len = 0

    for part in parts:
        part_len = len(part)
        # 如果單句長度就大於 chunk_size，直接獨立為一個 chunk
        if part_len >= chunk_size:
            if current_chunk:
                chunks.append("".join(current_chunk))
                current_chunk = []
                current_len = 0
            chunks.append(part)
            continue

        if current_len + part_len > chunk_size:
            # 建立當前 chunk
            chunks.append("".join(current_chunk))
            # 保留重疊區段：從 current_chunk 的尾端抓取約 chunk_overlap 長度的句子
            overlap_parts = []
            overlap_len = 0
            for p in reversed(current_chunk):
                if overlap_len + len(p) <= chunk_overlap:
                    overlap_parts.insert(0, p)
                    overlap_len += len(p)
                else:
                    break
            current_chunk = overlap_parts + [part]
            current_len = overlap_len + part_len
        else:
            current_chunk.append(part)
            current_len += part_len

    if current_chunk:
        chunks.append("".join(current_chunk))

    return [c.strip() for c in chunks if c.strip()]


class URLParser:
    """網頁與 YouTube 連結解析器"""

    def parse_url(self, url: str) -> str:
        """解析 URL，支援一般網頁與 YouTube 影片"""
        url = url.strip()
        if not url:
            raise ValueError("URL 不能為空")

        if self._is_youtube_url(url):
            return self._parse_youtube(url)
        else:
            return self._parse_webpage(url)

    def _is_youtube_url(self, url: str) -> bool:
        """判斷是否為 YouTube 網址"""
        pattern = r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/'
        return bool(re.match(pattern, url, re.IGNORECASE))

    def _parse_youtube(self, url: str) -> str:
        """提取 YouTube 字幕；若無字幕則自動備援下載音軌並以 Whisper 轉譯"""
        video_id = self._extract_youtube_id(url)
        if not video_id:
            raise ValueError(f"無法解析 YouTube 影片 ID: {url}")

        subtitle_error = None
        if YouTubeTranscriptApi is not None:
            try:
                full_text = self._fetch_youtube_subtitles(video_id)
                return f"--- [YouTube Video {video_id} 字幕逐字稿] ---\n\n" + full_text
            except Exception as e:
                subtitle_error = e
        else:
            subtitle_error = ImportError("未安裝 youtube-transcript-api 套件")

        # 備援軌：該影片無字幕（或字幕抓取失敗），改為下載音軌並用本地 Whisper 轉譯
        if yt_dlp is None:
            raise DocumentParserError(
                f"YouTube 字幕提取失敗: {str(subtitle_error)}\n"
                "(且未安裝 yt-dlp 套件，無法備援下載音軌，請執行 pip install yt-dlp)"
            )

        try:
            audio_text = self._transcribe_youtube_audio(url, video_id)
            return f"--- [YouTube Video {video_id} 音軌 Whisper 逐字稿（無可用字幕，已自動備援轉譯）] ---\n\n" + audio_text
        except Exception as e:
            raise DocumentParserError(
                f"YouTube 字幕提取失敗: {str(subtitle_error)}\n音軌備援轉譯亦失敗: {str(e)}"
            )

    def _fetch_youtube_subtitles(self, video_id: str) -> str:
        """嘗試抓取 YouTube 官方或社群字幕，找不到則拋出例外交由呼叫端處理備援"""
        languages = ['zh-TW', 'zh-HK', 'zh-CN', 'zh', 'en']
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        transcript = None
        for lang in languages:
            try:
                transcript = transcript_list.find_transcript([lang])
                break
            except Exception:
                continue

        if not transcript:
            try:
                transcript = transcript_list.find_generated_transcript(languages)
            except Exception:
                # 嘗試抓取任意一個可用字幕
                keys = list(transcript_list._manually_created_transcripts.keys()) + list(transcript_list._generated_transcripts.keys())
                if keys:
                    transcript = transcript_list.find_transcript([keys[0]])

        if not transcript:
            raise ValueError("找不到該影片的任何字幕")

        parts = transcript.fetch()
        full_text = [part.text.strip() for part in parts if part.text.strip()]
        if not full_text:
            raise ValueError("字幕內容為空")

        return " ".join(full_text)

    def _transcribe_youtube_audio(self, url: str, video_id: str) -> str:
        """下載 YouTube 影片音軌至暫存檔，並以本地 Whisper 模型轉譯為文字"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            audio_path_template = os.path.join(tmp_dir, f"{video_id}.%(ext)s")
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": audio_path_template,
                "quiet": True,
                "no_warnings": True,
                "noprogress": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            downloaded_files = [
                os.path.join(tmp_dir, f) for f in os.listdir(tmp_dir)
                if f.startswith(video_id)
            ]
            if not downloaded_files:
                raise DocumentParserError("音軌下載失敗，未產生任何音訊檔案")

            return _transcribe_with_whisper(downloaded_files[0], model_size="tiny")

    def _extract_youtube_id(self, url: str) -> Optional[str]:
        """從網址中擷取 YouTube Video ID"""
        patterns = [
            r'v=([^&#]+)',                  # youtube.com/watch?v=xxx
            r'youtu\.be/([^&#\?]+)',        # youtu.be/xxx
            r'embed/([^&#\?]+)',            # youtube.com/embed/xxx
            r'shorts/([^&#\?]+)'            # youtube.com/shorts/xxx
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    def _parse_webpage(self, url: str) -> str:
        """抓取一般網頁並轉為 Markdown"""
        if trafilatura is None:
            raise ImportError("未安裝 trafilatura 套件，請執行 pip install trafilatura")

        try:
            downloaded = trafilatura.fetch_url(url)
            if downloaded is None:
                raise ValueError(f"無法下載網頁內容: {url}")

            result = trafilatura.extract(
                downloaded,
                output_format='markdown',
                include_links=True,
                include_images=False,
                include_tables=True
            )
            
            if not result:
                result = trafilatura.extract(downloaded, output_format='txt')

            if not result:
                raise ValueError("無法提取該網頁的有效內容")

            return f"--- [網頁連結: {url}] ---\n\n" + result

        except Exception as e:
            raise DocumentParserError(f"網頁內容抓取失敗: {str(e)}")

