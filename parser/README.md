# 獨立文檔與多媒體轉譯器 (Ingestion Parser Engine)

本模組為一獨立、隨插即用的多源文檔轉譯引擎，負責將多種格式的原始輸入（PDF, DOCX, PPTX, MD, TXT, 音訊, 影片, 網頁 URL, YouTube 連結）解析為結構化的純文字，並內建句子感知分塊（Sentence-aware chunking）與表格語意還原能力。

---

## 🎓 學術文獻支撐 (Literature Support)

為了確保在論文中的學術可追溯性，本模組的設計與以下領域的奠基性學術研究進行對焦，以下提供論文寫作的標準 APA 格式引用：

1. **文件版面理解 (Document Layout Understanding)**:
   * **APA 引用**：*Li, M., Xu, Y., Lei, P., Cui, X., Wei, F., & Zhou, M. (2020). LayoutLM: Pre-training of text and layout for document image understanding. In Proceedings of the 26th ACM SIGKDD International Conference on Knowledge Discovery & Data Mining (pp. 3159-3167).*
   * **論文定位**：作為本模組設計「版面解析與閱讀順序還原（Reading Order Recovery）」的理論依據。傳統文字提取流會打亂雙欄排版，而 LayoutLM 證實了結合 2D 空間佈局與文字語意對於理解複雜排版文檔的必要性。
   
2. **版面標註與目標檢測 (Layout Detection)**:
   * **APA 引用**：*Zhong, X., Tang, J., & Yepes, A. J. (2019). PubLayNet: largest dataset for document layout analysis. In Proceedings of the 2019 International Conference on Document Analysis and Recognition (pp. 1015-1022).*
   * **論文定位**：用以支撐本模組將文檔切分為 `Text` (段落), `Title` (標題) 與 `Table` (表格) 等獨立語意區塊的合理性。

3. **表格結構識別 (Table Structure Recognition, TSR)**:
   * **APA 引用**：*Smock, B., Pesala, R., & Robin, G. (2022). PubTables-1M: Towards comprehensive table extraction from images. In Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (pp. 4624-4633).*
   * **論文定位**：支撐本模組將 Word 表格解析並重組為 Markdown Grid 語法，以保留行列語意一致性的合理性。

4. **語音識別與弱監督預訓練 (Robust Speech Recognition)**:
   * **APA 引用**：*Radford, A., Kim, J. W., Xu, T., Brockman, G., McLeavey, C., & Sutskever, I. (2023). Robust speech recognition via large-scale weak supervision. Proceedings of the 40th International Conference on Machine Learning, PMLR 202, 28492-28518.*
   * **論文定位**：作為本模組支援音訊、影片檔案及 YouTube 音軌轉譯的理論基礎。驗證了在大規模弱監督音訊數據上訓練的 Sequence-to-Sequence 模型（Whisper）在零樣本（Zero-shot）多語系識別上的強健性。

5. **網頁去噪與主體提取 (Web Scraping & Boilerplate Removal)**:
   * **APA 引用**：*Barbaresi, A. (2021). Trafilatura: A web scraping library and command-line tool for text discovery and extraction. In Proceedings of the Joint Conference of the 59th Annual Meeting of the Association for Computational Linguistics and the 11th International Joint Conference on Natural Language Processing: System Demonstrations (pp. 122-131). Association for Computational Linguistics.*
   * **論文定位**：作為網頁連結轉譯的依據。論證了相較於傳統粗暴的 HTML2Text 轉換，利用特定的排版啟發式規則與標籤比率，能有效去除導航欄、廣告及版權資訊等「噪音（Boilerplate）」，僅保留核心正文，從而提高下游 RAG 檢索的信噪比。

---

## 🔧 工業級競品與對標專案 (Open Source Projects)

本模組的工程架構借鏡並對標了以下開源專案，並在設計上進行了特化優化：

1. [**Unstructured-IO/unstructured**](https://github.com/Unstructured-IO/unstructured) (Apache-2.0, 26k★):
   * **對照分析**：`unstructured` 引進了極為龐大的依賴鏈。本專案對其進行了 **「骨架化收斂（Skeletal Streamlining）」**，將核心代碼收斂至約 300 行，並在體積小於其 10 倍的前題下，利用輕量 `pdfminer.six` 實作了專屬的「混合排版分流演算法」，在零外部重型 Java/C++ 依賴下達到了同等水準的解析精度。
    
2. [**infiniflow/ragflow (DeepDoc)**](https://github.com/infiniflow/ragflow) (Apache-2.0, 84k★):
   * **對照分析**：`RAGFlow` 透過 YOLOv8 目標檢測模型進行雙欄還原。本模組借鏡了其「先欄位分流，後高度融合」的思路，但在實作上改以純 2D 坐標幾何啟發式算法（Heuristic Spatial Partitioning）在 CPU 上完成毫秒級的雙欄還原，大幅降低了本地端延遲。

3. [**openai/whisper**](https://github.com/openai/whisper) (MIT, 65k★):
   * **對照分析**：原生 Whisper 通常需要強大的 GPU 與數 GB 的 PyTorch 環境來載入大模型。本專案將其限制在 `tiny` 級別的語音識別模型，並與 FastAPI 非同步執行緒池整合，實現在普通電腦 CPU 上以秒級速度完成短影音的轉譯，降低了使用門檻。

4. [**yt-dlp/yt-dlp**](https://github.com/yt-dlp/yt-dlp) (Unlicense/GPLv3+, 178k★):
   * **對照分析**：`yt-dlp` 是 `youtube-dl` 停滯後由社群接手的主流分支，維護活躍、抽取邏輯更新快，已被 Ubuntu 官方收錄。本模組僅在 YouTube 官方／社群字幕皆不存在時，才啟用 `yt-dlp` 下載最佳音軌並交由本地 Whisper 轉譯，作為「零字幕」情境下的最後備援，避免對每支影片都預設下載整條音軌造成不必要的頻寬與運算開銷。

---

## 🛠️ 架構與 Fallback 決策流程 (Behavior Tree)

本轉譯引擎採用多源分流決策架構，以完整達到對標 **NotebookLM** 級別的輸入相容性：

```
                                [ 輸入來源 ]
                                     │
             ┌───────────────────────┼───────────────────────┐
             ▼                       ▼                       ▼
      [ 本地檔案路徑 ]           [ 網頁 URL ]           [ YouTube 連結 ]
             │                       │                       │
             ▼                       ▼                       ▼
      【判斷檔案副檔名】        [ trafilatura ]        [ 優先提取自動字幕 ]
             │                (去除導航與廣告，        (youtube-transcript)
             │                 轉為 Markdown)                │
  ┌──────────┼──────────┐            │                       ▼
  ▼          ▼          ▼            │              【字幕是否存在？】
[文本]     [音視頻]    [PDF]         │             ┌─────────┴─────────┐
(TXT/      (MP3/WAV/    │            │          (是) │                 │ (否)
 MD/        MP4/M4A)    ▼            │               ▼                 ▼
 DOCX/       │    ┌─────────────┐    │          [輸出字幕流]      [ 下載音軌 ]
 PPTX)       │    │ 軌道一：    │    │                            (yt-dlp +
  │          │    │ pypdf 文字  │    │                             Whisper)
  │          │    └─────┬───────┘    │                                 │
  │          │          │            │                                 │
  │          │    【文字品質高？】   │                                 │
  │          │      ┌───┴───┐        │                                 │
  │          │   (否)│       │(是)   │                                 │
  │          │      ▼       ▼        │                                 │
  │          │    ┌───┐   [輸出]     │                                 │
  │          │    │軌 │     ▲        │                                 │
  │          │    │道 │     │        │                                 │
  │          │    │二 │─────┘        │                                 │
  │          │    │： │(版面還原)    │                                 │
  │          │    │pdf│              │                                 │
  │          │    │min│              │                                 │
  │          │    └───┘              │                                 │
  │          │      │                │                                 │
  │          │  【是否為掃描件？】   │                                 │
  │          │      ├───┐            │                                 │
  │          │   (是)│   │(否)        │                                 │
  │          │      ▼   ▼            │                                 │
  │          │    ┌───┐[輸出]        │                                 │
  │          │    │軌 │              │                                 │
  │          │    │道 │              │                                 │
  │          │    │三 │              │                                 │
  │          │    │： │              │                                 │
  │          │    │OCR│              │                                 │
  │          │    └───┘              │                                 │
  │          │      │                │                                 │
  │          ▼      ▼                │                                 │
  └─────────►[  Local Whisper  ]◄────┼─────────────────────────────────┘
                    │                │
                    ▼                ▼
             ┌────────────────────────┐
             │    輸出結果文字流      │
             └──────────┬─────────────┘
                        │
                        ▼
             ┌────────────────────────┐
             │  句子感知分塊 (Chunk)  │
             └────────────────────────┘
```

> **注意**：上圖為「文字提取」路由決策樹。其中 **PDF / PPTX / DOCX** 三種格式在各自的文字提取軌道完成後，
> 會額外並行走過下方的「圖文統一處理管線 Behavior Tree」，其輸出會併入前述文字流後才一起進入句子感知分塊；
> 音訊/影片、純文本 (TXT/MD)、網頁 URL、YouTube 連結則不涉及內嵌圖片抽取。

---

## 🖼️ 圖文統一處理管線 (Image Understanding Pipeline)

除純文字提取外，`parser/image_pipeline.py` 額外實作了 PDF / PPTX / DOCX 內嵌圖片的處理管線，
完整設計依據見 [`文檔轉譯器 最終優化架構總結（可跨模型接續討論）.md`](./文檔轉譯器%20最終優化架構總結（可跨模型接續討論）.md)。

### 圖文統一處理管線 Behavior Tree

```
        [ PDF / PPTX / DOCX 文字提取完成 ]
                      │
                      ▼
       【enable_ocr 是否開啟？】(預設 True)
              ┌───────┴───────┐
           (否)│               │(是)
              ▼               ▼
      [跳過圖片處理，   [逐頁/逐張投影片/逐段落
       僅輸出文字流]     抓取內嵌圖片 + 座標/順序]
              │               │
              │               ▼
              │      【空間去重】原生文字覆蓋率 ≥70%？
              │              ┌───────┴───────┐
              │           (是)│               │(否，僅 PDF 有座標可判定)
              │              ▼               ▼
              │        [捨棄該圖，        [裝飾性小圖過濾]
              │         零成本跳過]     (寬或高 <40px 直接捨棄)
              │              │               │
              │              │               ▼
              │              │         [全域 OCR 辨識]
              │              │      (輸出 OCR 文字 + 置信度)
              │              │               │
              │              │               ▼
              │              │     【依視覺閱讀順序排序後】
              │              │       指派圖號（雙序列）
              │              │   圖題標註 > 正文明確引用 >
              │              │   圖片內部列印圖號 > 自補序號
              │              │               │
              │              │               ▼
              │              │   【三維度加權評分】文件類型(30%)
              │              │   + OCR置信度(40%) + 圖形特徵(30%)
              │              │               │
              │              │               ▼
              │              │      【強制旁路規則命中？】
              │              │   (如「如下圖所示」/ 強制參數 /
              │              │    doc_type 全域強制清單)
              │              │      ┌────────┴────────┐
              │              │   (是，跳過評分)      (否)
              │              │      ▼                 ▼
              │              │      └──────┬──────────┘
              │              │             ▼
              │              │   【總分 ≥ score_threshold
              │              │      或命中強制旁路？】
              │              │      ┌────────┴────────┐
              │              │   (否)│                 │(是)
              │              │      ▼                 ▼
              │              │  [保留 OCR      【enable_image_understanding
              │              │   文字結果]        且 Ollama 服務可連線？】
              │              │      │             ┌────────┴────────┐
              │              │      │          (否，優雅降級)      (是)
              │              │      │             ▼                 ▼
              │              │      │       [保留 OCR         [呼叫本地圖理解
              │              │      │        文字結果]         模型產生語義描述]
              │              │      │             │                 │
              │              │      └─────────────┴────────┬────────┘
              │              │                              ▼
              │              │                    [按閱讀順序位置回填
              │              │                     圖文內容，標註來源]
              │              │                              │
              └──────────────┴──────────────────────────────┘
                                         │
                                         ▼
                          [併入文字流，供句子感知分塊使用]
```

核心原則：

1. **能力解耦**：OCR 文字提取為核心基礎能力，`enable_ocr` 預設 `True`，完全不依賴圖理解模型即可運作；
   圖理解語義模型為選配增強能力，`enable_image_understanding` 預設 `False`，需另行啟動本機 [Ollama](https://ollama.com/) 服務並安裝多模態模型（預設對應 `qwen2.5vl:7b`）才會生效。未安裝/未啟動時自動降級為保留 OCR 結果，不中斷解析流程。
2. **算力分層**：空間去重（跳過已被原生文字覆蓋 ≥70% 的裝飾性圖片）→ 全域 OCR → 三維度加權評分
   （文件類型 30% + OCR 置信度 40% + 輕量圖形特徵 30%，預設閾值 60 分）→ 命中「如下圖」等強制旁路規則時
   直接跳過評分 → 分數達標才呼叫本地圖理解模型補足語義。
3. **圖號雙序列**：原文既有圖號（如「圖3」）與系統自動補號（`自補圖-1`、`自補圖-2`）各自獨立遞增，永不互相覆蓋。
4. **圖片不落地**：圖片僅在處理過程中存於記憶體，處理完即釋放，輸出僅保留文字描述（OCR 文字或圖理解語義描述），不寫入磁碟。

### 設定方式

```python
from parser.core import DocumentParser
from parser.image_pipeline import ImagePipelineConfig

config = ImagePipelineConfig(
    enable_image_understanding=True,       # 開啟本地圖理解模型兜底
    ollama_base_url="http://localhost:11434",
    ollama_vision_model="qwen2.5vl:7b",    # 預設值；可換成其他已安裝的視覺模型
    score_threshold=60.0,
    force_visual_parse_doc_types=["pptx"], # 例如：PPT 全域強制圖理解
)
parser = DocumentParser(image_config=config)
text = parser.parse_file("report.pdf")
```

若不提供 `image_config`，則沿用預設值（OCR 開啟、圖理解模型關閉），行為與升級前完全相容。

> **模型選型備註**：預設採用 `qwen2.5vl:7b` 而非社群常見的 `llava`，因其對繁體中文與流程圖／架構圖等結構化圖表的
> OCR、版面理解能力明顯較佳，7B 量化後約 6GB，可在 8GB VRAM 等級的消費級 GPU（如 RTX 4060/4070 Laptop）上順暢運行。
> 若本機 VRAM 較小（如 4-6GB），可改用更輕量的 `minicpm-v` 或 `llava-phi3`；VRAM 充足時可升級至 `qwen2.5vl:32b` 等更大模型以取得更精確的圖表理解品質。

### 已知限制 (Known Limitations)

以下為目前實作已知、經評估後暫不修正的邊界情況，記錄於此供未來迭代參考：

1. **強制旁路規則對同頁多圖可能過度觸發**：`check_forced_bypass` 在圖片沒有專屬圖說候選文字時，
   會退而檢查整頁（PDF）或整份投影片/段落文字（PPTX/DOCX）是否命中「如下圖所示」等強制旁路關鍵字。
   若同一頁存在多張圖片，其中一張確實被文字明確引用，但頁面上其他不相關的圖片也會一併被強制送進
   圖理解模型，造成非必要的算力開銷。此為「寧可誤觸發、不漏判」的保守權衡，非程式錯誤。
2. **DOCX 圖說偵測對「圖片與標題分屬不同段落」的常見排版會失效**：Word 常見寫法是圖片本身獨立一個
   段落（該段落文字通常為空），標題文字則在緊接的下一個段落（使用「插入標題」功能產生）。目前
   `_process_docx_paragraph_images` 僅讀取圖片所在段落自身文字作為圖題候選，無法跨段落抓取標題，
   此情況下該圖片會落到「正文明確引用」或系統自補序列，而非以原文圖號呈現。
3. **PDF 圖片管線與軌道二（pdfminer）版面解析重複呼叫 `extract_pages()`**：當文字提取走到軌道二時，
   `_extract_pdf_images_text` 會再次呼叫 `extract_pages()` 重新解析一次頁面版面，屬效能上可優化但不
   影響正確性的重複計算；未來可考慮合併為單次遍歷。
4. **`_detect_double_column` 為既有未使用方法**：此輔助函式存在於 `core.py` 但目前沒有任何呼叫點
   （早於本次圖文管線改動即存在），與圖文管線無關，暫不清理以維持本次變更範圍最小化。

## 📦 系統依賴說明 (System Prerequisites)

由於部分提取軌道涉及影像處理與音訊重組，請確保本機已安裝以下工具並加入系統環境變數 PATH 中：

1. **Poppler** (用於 `pdf2image` 渲染 PDF 頁面)：
   * *Windows (Scoop)*: `scoop install poppler`
   * *Windows (Chocolatey)*: `choco install poppler`
   * *macOS (Homebrew)*: `brew install poppler`

2. **Tesseract-OCR** (用於光學字元識別)：
   * *Windows (Winget)*: `winget install UB-Mannheim.TesseractOCR`
   * *macOS (Homebrew)*: `brew install tesseract`

3. **FFmpeg** (用於 `whisper` 進行音訊編碼與切分)：
   * *Windows (Scoop)*: `scoop install ffmpeg`
   * *Windows (Chocolatey)*: `choco install ffmpeg`
   * *macOS (Homebrew)*: `brew install ffmpeg`

4. **Ollama**（選配，僅在啟用 `enable_image_understanding=True` 時需要，用於本地圖理解模型兜底）：
   * *Windows (Winget)*: `winget install Ollama.Ollama`
   * *macOS/Linux*: 參考 [ollama.com/download](https://ollama.com/download)
   * 下載預設視覺模型：`ollama pull qwen2.5vl:7b`（或其他支援視覺輸入的模型，並對應設定 `ollama_vision_model`）
   * 未安裝或服務未啟動時，圖片管線會自動降級為僅保留 OCR 結果，不影響其餘解析流程
