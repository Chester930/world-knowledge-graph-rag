# NotebookLM（Google）

## 一、定位與背景

NotebookLM 是 Google Labs 開發的來源基礎（source-grounded）AI 研究助理，定位為「個人/團隊文件閱讀與知識整理工具」。核心賣點是「上傳即用」的低門檻體驗與 Studio 面板（Audio/Video Overview、Mind Map、Reports 等）產出的多樣化二次內容。截至 2026 年中，已從免費個人工具擴展為四級訂閱制產品（Free / Plus $7.99/mo / Pro $19.99/mo / Ultra $99.99–200/mo）。

## 二、核心技術架構

- **底層模型**：2026 年中已升級至 **Gemini 3**（2025 年 10 月起陸續完成引擎升級），大幅提升推理與多模態理解能力；6 月 8 日的「agentic upgrade」進一步接上 **Gemini 3.5 + Antigravity**，加入逐 notebook 的程式碼執行能力。
- **檢索機制**：採用 **RAG（Retrieval Augmented Generation）**，答案皆附帶可回溯至原始來源的引用（web citations / 來源引用），這與本專案「可追溯推理路徑」的目標方向一致，但實作機制不同——NotebookLM 依賴原生超長上下文（早期版本 2M tokens）做 In-Context 檢索，而非顯式知識圖譜。
- **文件處理**：依賴 Google 原生多模態編碼器，可直接解析 PDF 內的表格、圖表與版面配置，不需額外的 OCR/版面分析管線。

## 三、關鍵特色功能

1. **Audio Overview**：將上傳的文件轉換成兩位 AI 主持人的 Podcast 式對話，支援 80+ 語言；使用者可即時加入對話、要求更詳細說明或換個角度解釋，並可自訂語氣（幽默/正式）與長度。
2. **Video Overview**：2026 年 Studio 面板新增的輸出類型，早期是旁白投影片形式，2026 年 3 月推出 **Cinematic Video Overview**（動態敘事影片，非靜態投影片+旁白），可自訂風格（explainer/brief、whiteboard/kawaii/watercolor/classic），目前限英語、18 歲以上使用者、僅 Ultra 方案。
3. **Mind Map**：自動生成文件內關鍵概念之間的連結、層級與關係的視覺化圖，功能定位上與本專案的知識圖譜視覺化目標相近，但 NotebookLM 的 Mind Map 是「一次性摘要視覺化」，不是可持續查詢、可 CRUD 的底層資料結構。
4. **Studio Panel 多工**：可同時聆聽 Audio Overview、瀏覽 Mind Map、查看 Study Guide，2026 年 6 月更新加入 Studio Panel 匯出能力。
5. **Data Table（2025 年 12 月新增）**：伴隨 Gemini 3 升級推出的新輸出類型，讓使用者將來源中的結構化資訊整理成表格。
6. **Deep Research**（2025 年 10 月起）：主動式多步研究能力，可從網路擴充來源（"start-from-scratch web sourcing"，2026 年 6 月加入）。

## 四、開源狀態

NotebookLM 本身**完全閉源**，是 Google 內部產品，無公開原始碼或自建部署選項。其底層依賴的 Gemini 系列模型也是閉源商業 API。沒有可查證的開源元件可供借鏡；若要參考其技術路線，只能透過公開的架構描述（RAG + 原生多模態編碼器 + 超長上下文）做間接對標，無法直接參考程式碼實作。

## 五、值得借鏡的技術點

1. **二次內容自動生成的產品化思路**：Mind Map / Audio Overview / Study Guide 這類「建庫後自動產出導讀內容」的模式，可以對應到本專案已規劃的社群摘要與自動導讀功能（見 v1 `04_對標NotebookLM...md` 方案四），值得參考其「多種輸出格式並列在同一 Studio 面板」的 UI 模式，而非只做單一 FAQ 列表。
2. **秒級可用的取捨**：NotebookLM 犧牲了持久化、可編輯的結構化知識（沒有底層知識圖譜可 CRUD），換取「上傳即問」的低延遲體驗。本專案若要同時保留知識圖譜的優勢又不犧牲首次可用性，「向量先行、圖譜非同步建構」的雙軌架構（v1 方案一）是務實折衷，NotebookLM 的秒級體驗可作為這個雙軌架構「向量先行」那一軌的體驗基準線。
3. **多模態原生編碼 vs. 外接 OCR/VLM 管線**：NotebookLM 靠 Google 自家多模態模型原生理解表格/圖表，本專案若走外接開源 VLM（如 Qwen2-VL、Llama-3.2-Vision，見 v1 方案二）路線，品質上限會受限於這些開源模型的多模態能力，這是本專案在此功能上難以完全對齊 NotebookLM 的結構性限制，需要在論文範圍聲明中誠實承認。

## 六、與本專案的具體差距

（技術內容取自 v1 `智慧知識庫/docs/報告/04_對標NotebookLM_不足分析與完全超越方案.md`，語氣改寫為中性敘述）

1. **寫入階段延遲**：本專案導入文件需全量呼叫 LLM 抽取三元組並執行實體對齊，百萬字文檔的建圖過程可能需要數小時（尤其在本地 Ollama 環境下）；NotebookLM 僅做輕量向量化與快取分片，秒級可用。
2. **多模態結構解析**：本專案目前 PDF 轉譯依賴純文字提取（pypdf/pdfminer/PaddleOCR），會摧毀複雜表格、圖表與版面排版；NotebookLM 用原生多模態編碼器直接理解這些結構。
3. **Hub Node 路徑爆炸**：本專案 BFS 圖遍歷遇到高連結度節點時，目前僅用 `_PER_SEED_FACT_LIMIT=20` 做隨機硬截斷；NotebookLM 靠 Transformer 原生 Attention 動態分配權重，沒有這類硬性截斷問題（但有其自身的長上下文「大海撈針」風險，見論文 1.1.1 已引用的 Liu et al. 2023 Lost in the Middle）。
4. **產品層面的主動導讀**：本專案目前缺乏建庫後的宏觀導讀/自動洞察功能，NotebookLM 有完整的 Audio/Video Overview、FAQ、Study Guide 產出鏈。

## 七、來源

- 智慧知識庫 v1：`D:\Users\666\Desktop\智慧知識庫\docs\報告\04_對標NotebookLM_不足分析與完全超越方案.md`
- [NotebookLM Update 2026: Every New Feature Explained](https://felloai.com/notebooklm-update-1m-token-chat-goals-saved-history/)
- [NotebookLM now uses Gemini 3, adds new 'Data Tables' output — 9to5google](https://9to5google.com/2025/12/19/notebooklm-gemini-3-data-tables/)
- [What's new in NotebookLM: Video Overviews and an upgraded Studio — Google Blog](https://blog.google/innovation-and-ai/models-and-research/google-labs/notebooklm-video-overviews-studio-upgrades/)
- [What Is NotebookLM? Features and How to Use It in 2026 — DigitalOcean](https://www.digitalocean.com/resources/articles/what-is-notebooklm)
- [Generate Audio Overview in NotebookLM — Google Support](https://support.google.com/notebooklm/answer/16212820?hl=en)
