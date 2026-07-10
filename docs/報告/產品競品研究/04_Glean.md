# Glean

## 一、定位與背景

Glean 是企業知識搜尋與工作 AI 平台（Work AI Platform），定位為連接企業內部所有應用（Slack、Google Workspace、Jira、Salesforce 等 100+ 個連接器）的統一知識入口。2025 年完成 Series F 融資後估值達 $7.2B，年度經常性收入（ARR）已突破 $200M（近期倍增）。產品線包含 Glean Search（企業搜尋）、Glean Assistant（RAG 對話助理）、Glean Agents（可建構的自動化代理）。

## 二、核心技術架構

### Enterprise Graph（企業圖譜）
Glean 的核心技術主張是「企業搜尋本質上是一個圖問題」。其 Knowledge Graph 將企業內每一筆資訊都表示為三元組（subject, predicate, object），且**語意連結與權限邊是索引中的第一等公民，而非事後補上的附加層**。例如：「某份 Confluence 頁面屬於某專案、由某人撰寫、引用某客戶、連結到某些 Jira 工單、且僅對特定群組成員可見」——這整條關係鏈本身就是圖譜的一部分。

圖譜建構完全透過機器學習完成：系統理解各企業應用的資料結構後自動推論出高價值實體（專案、人員、客戶、產品），並以周邊訊號（文件、支援工單、功能規格）強化這些實體節點。

圖譜的三大支柱：
- **Content**：個別資產、文件、訊息、工單、實體
- **People**：身份、角色、團隊、部門、群組
- **Activity**：內容建立/建立者、編輯歷史、留言、搜尋、點擊行為

### 權限鏡射（Permission Mirroring）機制
這是 Glean 最核心的技術護城河，具體實作方式：
1. **連接器層同步 ACL**：每個連接器透過 OAuth 或服務帳號安全連線來源系統，同步存取控制清單（ACL）或等效的權限模型，權限資訊與內容、metadata 一起被攝入
2. **鏡射 RBAC 並繼承組織階層**：權限自動與來源系統同步，鏡射角色權限控管（RBAC）並繼承組織架構的階層關係
3. **零複製模型（Zero-Copy）**：原始內容**留在來源位置不搬移**，Glean 只暫存索引用的向量與 metadata（含權限標記），這同時解決了資料主權與效能問題
4. **即時爬取架構**：持續攝入企業內容與 metadata（含權限變化），確保索引與來源系統的存取控制保持同步，而非一次性快照
5. **跨產品線統一權限框架**：Search、Assistant、Agents 三條產品線共用同一套權限框架，使用者在任何介面都只能看到其被授權存取的資料

### Agentic Engine 2
2025 年推出的第二代代理引擎，特點是「自適應規劃＋平行子代理協作」——不同於第一版的單次規劃，Agentic Engine 2 能在執行過程中根據系統學到的新資訊調整計畫。每次 Assistant 提示都會觸發：意圖解析 → 計畫提案 → 在 Enterprise Graph 中做上下文錨定（grounding）。官方數據顯示任務完整度達 94%，且 Enterprise Graph 的訊號量較前版增加 3 倍。

## 三、關鍵特色功能

- **即時權限感知檢索**：搜尋結果與 RAG 答案自動過濾成使用者有權限看到的內容，不需額外的存取控制邏輯
- **零複製資料架構**：不搬移原始資料，只快取索引向量與 metadata，降低資料外洩與合規風險
- **100+ 應用連接器**：涵蓋雲端儲存、通訊平台、專案管理、客戶系統、自訂資料庫（透過 API）
- **可視覺化建構代理（Glean Agents）**：任何員工（非只有開發者）都能用自然語言指令建構、部署、協調 AI 代理
- **citation-backed 答案**：RAG 回答附帶可追溯來源，呼應企業對可解釋性的要求

## 四、開源狀態

**Glean 本身是完全閉源的商業 SaaS 產品**，沒有開源版本，也沒有公開的核心程式碼庫。其連接器、Enterprise Graph 建構邏輯、Agentic Engine 皆為專有技術，僅透過官方 API／SDK 對外開放整合，沒有可直接借用的開源元件。

## 五、值得借鏡的技術點

本專案目前「多知識庫管理」在論文 1.1.4 節只是方向性的產品目標，實際只有 Edge et al. (2024) 的學術缺口分析支撐，**沒有具體的權限治理設計**。Glean 的架構提供幾個可轉化為本專案多租戶設計的具體思路：

1. **把權限邊當成圖譜的第一等公民，而非外掛的存取控制層**：本專案目前的知識圖譜（Neo4j）節點/邊只承載事實語意，若要支援多租戶，可仿照 Glean 的做法，直接在關係邊或節點上掛載 `kg_id`／`tenant_id`／`acl` 屬性（其實本專案 `svo_service.py` 的 Cypher 查詢已經在用 `kg_id` 做過濾，這代表雛形已經存在，缺的是更細粒度的群組/角色權限，而非整庫級別的隔離）。
2. **零複製精神值得參考，但本專案的定位不同**：Glean 是連接既有企業應用（資料本來就在別處），本專案是使用者主動上傳文件建圖，「零複製」概念不完全適用，但「敏感資料留在原處、只儲存衍生的結構化事實」這個設計哲學，可以類比應用在「原始文件 vs 已抽取的 SVO 三元組」的儲存分離上（本專案的 `chunk_store` 與 Neo4j 分離儲存架構已經有這個雛形）。
3. **即時同步機制是本專案明顯缺口**：Glean 持續同步來源系統的權限變化；本專案目前沒有討論知識庫權限異動後如何即時反映到既有圖譜查詢結果，這是「多知識庫管理」若要做扎實，必須補上的設計環節。

## 六、與本專案的具體差距

| 面向 | Glean | 本專案現況 |
|---|---|---|
| 權限模型 | 細粒度 RBAC + 組織階層繼承，即時同步 | 僅有 `kg_id` 層級的知識庫區隔，未見角色/群組級權限設計 |
| 資料來源 | 連接既有企業應用（被動接入） | 使用者主動上傳文件建圖（主動輸入） |
| 圖譜性質 | 企業實體關係圖（人、專案、內容、活動） | 文本抽取的語意事實圖（SVO 三元組） |
| 商業模式對照 | 企業級 SaaS，閉源 | 學術研究專案，架構開放討論 |

## 七、來源

- [Glean 官方：Enterprise Graph 產品頁](https://www.glean.com/product/enterprise-graph)
- [Glean 官方：Knowledge Graph 指南](https://www.glean.com/resources/guides/glean-knowledge-graph)
- [Glean 文件：Knowledge Graph 安全性說明](https://docs.glean.com/security/knowledge-graph)
- [Glean 官方：Data Governance 產品部落格](https://www.glean.com/blog/data-gov-product-blog)
- [Glean 官方：連接器如何運作](https://docs.glean.com/connectors/connectors-power-glean)
- [Glean 官方：Agentic Engine 2 效能發表](https://www.glean.com/blog/live-fall-25-agentic-engine2-performance)
- [Glean 官方：Agentic Reasoning Engine 產品頁](https://www.glean.com/product/agentic-engine)
- [AgentMarketCap：Glean $7.2B 估值與知識圖譜報導（2026-04）](https://agentmarketcap.ai/blog/2026/04/05/glean-7b-enterprise-knowledge-graph-agent-microsoft-365-copilot)
- [Futurum Group：Glean ARR 倍增至 $200M 報導](https://futurumgroup.com/insights/glean-doubles-arr-to-200m-can-its-knowledge-graph-beat-copilot/)
