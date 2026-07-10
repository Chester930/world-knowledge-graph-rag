# Obsidian + AI 知識圖譜外掛生態

> 產品競品研究系列之一，見 [00_總覽.md](00_總覽.md)。本文件非學術論文素材，供產品規劃參考。

## 一、定位與背景

Obsidian 是本地優先（local-first）的個人筆記／「第二大腦」應用，核心賣點是 Markdown 檔案完全存在使用者裝置上、資料主權由使用者掌控。2026 年初用戶數突破 150 萬。2026 年 2 月起官方推出 CLI，開放 100+ 指令（搜尋、建立筆記、日誌管理、內容附加等），使 Obsidian 從純筆記工具往「AI 代理可操作的認知基礎設施層」方向擴展。

## 二、核心技術架構

- **手動雙向連結**：使用者在筆記中打 `[[筆記名稱]]` 即建立一條連結，Obsidian 掃描全庫的連結關係建立索引，不涉及任何自動語意理解或實體抽取。
- **Graph View**：以每篇筆記為節點、每條 wikilink 為邊，用**力導向圖演算法（force-directed layout）** 渲染——節點間定義排斥力、相鄰節點定義吸引力，反覆迭代收斂到穩定佈局。密集連結的筆記會聚集在圖的中心，孤立筆記則被推向外圍。
- **Local Graph**：聚焦單一筆記，依可設定的「跳數半徑（depth）」只顯示該筆記鄰近範圍的子圖，概念上類似本專案 BFS 圖遍歷的「以種子節點為中心的鄰域擴展」，但 Obsidian 的邊是使用者手打的顯式連結，沒有信心值、沒有關係類型語意。
- **外掛系統**：Obsidian 核心提供插件 API 供第三方存取筆記內容與 metadata，AI/知識圖譜相關能力幾乎全部由社群外掛實現，核心產品本身不含 LLM 功能。
- **Canvas**：官方內建的自由畫布外掛，可將筆記排列、用箭頭連接、建構視覺化概念圖，每個節點是即時可編輯的筆記——比 Graph View 更接近使用者主動策展的知識結構。

## 三、AI/知識圖譜相關外掛詳細介紹

### Smart Connections
- 開發者 Brian Petro，2023 年首發，GitHub：[brianpetro/obsidian-smart-connections](https://github.com/brianpetro/obsidian-smart-connections)。
- 架構核心是共用的「Smart Environment」本地層，維護全庫筆記的 embedding 索引，同時服務 Smart Connections、Smart Chat 等多個外掛。
- 預設用輕量本地嵌入模型 **BGE-micro**，零設定、不需 API key、可完全離線運作，設計原則明確強調「最小化外部依賴，方便稽核程式碼」。
- 免費核心功能維持開源／原始碼可見（source-available），進階功能（inline connections、Bases scoring、大型庫效能優化等）收攏進 Pro 訂閱。

### Copilot for Obsidian
- 開發者 logancyang，GitHub：[logancyang/obsidian-copilot](https://github.com/logancyang/obsidian-copilot)。
- **前端開源，後端 AI 代理邏輯閉源專有**（由 Brevilabs 提供）——這是一個「開源外殼、專有智慧」的混合開源模式，值得留意。
- 免費層完全不經 Brevilabs 伺服器；付費層（Plus）才會將檔案轉換（PDF/DOCX/EPUB/圖片）等功能導向 Brevilabs 伺服器處理。
- 提供筆記庫內的對話式問答（Vault QA）、可接多家 LLM 供應商或本地 Ollama/LM Studio。

### Simple Graph Builder（本文件重點）
- 開發者 junhewk，GitHub：[junhewk/simple-graph-builder](https://github.com/junhewk/simple-graph-builder)，**MIT 授權，完全開源**。
- 用 LLM 從筆記自動抽取實體與關係，建構輕量知識圖譜，並支援圖譜導向的 RAG 搜尋——是外掛生態裡與本專案架構**最接近**的一個。
- 本體設計採**混合式**：10 種固定實體類型（PERSON、ORGANIZATION、CONCEPT、PROJECT、TOOL、EVENT、PLACE、DOCUMENT、METHOD、TOPIC），但**關係類型是自由文字動詞**（如 develops、uses、causes、cites），並附帶 detail 欄位描述細節，刻意不做固定關係 schema，理由是避免「schema 爆炸」。這與本專案採用**封閉式 30 種語意關係**的設計選擇正好相反，是一個值得在論文 1.1.3/1.2 RQ2（封閉式 vs 開放式關係抽取的 trade-off）討論時引用的真實產品案例。
- 設計上明言融合了 **LightRAG 的簡潔性**與 **KGGen 的混合式實體消解方法**，並針對 Obsidian 的 local-first 架構做了調整。

### InfraNodus AI Graph View
- GitHub：[noduslabs/infranodus-obsidian-plugin](https://github.com/noduslabs/infranodus-obsidian-plugin)，插件本身開源；後端 InfraNodus 分析服務需要帳號才能使用進階 AI 功能與擴充配額，預設不會把庫內資料上傳至 InfraNodus 帳號。
- 技術差異化在於**文字網路分析（text network analysis）**：使用 betweenness centrality 等網路科學指標找出最具影響力的筆記、用社群偵測找出主題群集、並偵測「結構性缺口（structural gap）」提出研究問題建議。
- 特別之處：不只看顯式 wikilink，還會分析**同一段落中共同出現的詞彙/連結**來建立額外的語意連結——比純粹依賴使用者手動連結多了一層自動化語意層。

## 四、開源狀態總覽

| 項目 | 開源狀態 | 說明 |
|---|---|---|
| Obsidian 核心 | ❌ 閉源 | 免費使用但非開源軟體 |
| Smart Connections | 🟡 核心 source-available，Pro 功能付費 | 免費核心功能程式碼可見 |
| Copilot for Obsidian | 🟡 前端開源，後端閉源 | 混合開源模式 |
| **Simple Graph Builder** | ✅ **完全開源（MIT）** | 唯一完全開源、且架構最接近本專案的外掛 |
| InfraNodus 外掛 | ✅ 外掛本身開源 | 後端分析服務為商業產品 |

## 五、值得借鏡的技術點

1. **手動建圖 vs 自動建圖，是本論文可以直接借力的核心對比**：Obsidian 原生圖譜完全依賴使用者手動輸入 `[[wikilink]]`，圖的品質取決於使用者的筆記紀律，無法處理「丟一份未經整理的原始文件」的場景。這呼應論文 1.1.1 已引用的 LeCun (2022) 持久性記憶限制討論——Obsidian 代表「人工維護的外部記憶」路線，本專案代表「自動化建構的外部記憶」路線，是同一個問題的不同解法。此對比若要寫入論文正文，須明確標示 Obsidian 是產品案例，不套用學術引用格式。
2. **Simple Graph Builder 的開放式關係抽取，是 RQ2 討論的絕佳真實案例**：它刻意不用固定關係 schema（只固定 10 種實體類型，關係則自由動詞），這正好是本論文 RQ2「封閉式 30 種語意關係 vs 開放式關係抽取」要驗證的另一端，可作為開放式路線的具體產品實例引用。
3. **「開源外殼、專有智慧」的混合開源模式（Copilot for Obsidian）**：前端/介面開源建立信任與社群貢獻，核心 AI 邏輯保留閉源作為商業護城河——若本專案未來要走開源+商業化雙軌，這是一個可參考的分層模式。
4. **零設定本地 embedding（Smart Connections 的 BGE-micro）**：對應本專案「秒級可用」的建圖冷啟動缺口（v1 文件已點名的頭號弱點）——本地輕量嵌入模型是一個可以立即嘗試的技術方向，不需要依賴外部 API 就能做到基本可用。
5. **段落共現分析（InfraNodus）補足純結構連結的盲點**：只看顯式抽取的三元組可能漏掉「同段落內語意相關但沒有明確 SVO 關係」的資訊，InfraNodus 的做法提示可以考慮加入輕量的共現分析作為 SVO 抽取的補充訊號。

## 六、與本專案的具體差距或相似點

| 面向 | Obsidian 生態 | 本專案 |
|---|---|---|
| 建圖方式 | 手動（核心）／LLM 抽取（外掛層） | LLM 自動 SVO 抽取（核心架構） |
| 關係類型 | 無型別（核心）／自由動詞（Simple Graph Builder） | 封閉式 30 種語意關係 |
| 定位 | 個人筆記優先，KG 是附加能力 | 知識圖譜優先，是系統核心 |
| 多知識庫/租戶 | 單一 vault，無原生多租戶概念 | 明確以多知識庫管理為目標（1.1.4） |
| 開源程度 | 核心閉源，外掛生態多元（開源/混合/閉源皆有） | 待決定 |

## 七、來源

- [Simple Graph Builder GitHub](https://github.com/junhewk/simple-graph-builder)
- [Simple Graph Builder — Obsidian 官方外掛頁](https://community.obsidian.md/plugins/simple-graph-builder)
- [Smart Connections GitHub](https://github.com/brianpetro/obsidian-smart-connections)
- [Smart Connections — Obsidian 官方外掛頁](https://community.obsidian.md/plugins/smart-connections)
- [Copilot for Obsidian GitHub](https://github.com/logancyang/obsidian-copilot)
- [InfraNodus Obsidian Plugin GitHub](https://github.com/noduslabs/infranodus-obsidian-plugin)
- [InfraNodus Obsidian Plugin 官網介紹](https://infranodus.com/obsidian-plugin)
- [Obsidian Graph View 技術說明（DeepWiki）](https://deepwiki.com/obsidianmd/obsidian-help/4.5-graph-view)
- [The Power of Obsidian's Local Graph](https://thesweetsetup.com/the-power-of-obsidians-local-graph/)
- [Obsidian, Supercharged: The AI Revolution in Personal Knowledge Management](https://volodymyrpavlyshyn.substack.com/p/obsidian-supercharged-the-ai-revolution)
