VECTOR_DIM = 384  # paraphrase-multilingual-MiniLM-L12-v2

# KG 路由門檻（v1 舊公式遺留值，見 docs/論文/03_系統設計與方法論.md § 3.2 §a 注意事項——
# 待 RQ2 消融實驗重新校準，第五章尚未排入獨立實驗，不可視為已驗證數值）
KG_ROUTE_THRESHOLD = 0.05      # Agent 問答：低於此分數的 KG 不召回
MAX_KG_PER_QUERY = 5           # Agent 問答：最多召回幾個 KG

# 文件分配門檻——⚠️ 尚未針對新公式校準：這兩個數字是 v1 舊公式
# （cosine × alignment × magnitude）校準的遺留值。3.1.1 節分類分數已改採
# Prototypical Networks 的 centroid cosine 相似度（見 docs/論文/03_系統設計與方法論.md
# § 3.1.1），數值尺度不保證與舊公式相同，舊門檻沒有理由在新公式下依然適用。
# 正式校準實驗設計見 docs/論文/05_實驗設計與評估.md § 5.3.5，校準完成前
# 僅為未驗證的佔位符，不可當作已驗證的生產參數使用。
CLASSIFY_AUTO_THRESHOLD = 0.30  # 自動分配：top score 需超過此值才自動移動
CLASSIFY_MIN_THRESHOLD = 0.05   # 低於此值視為完全無相關，留在暫存區等待

# 兩階段向量粗精篩（Two-Stage Retrieval）
CONCEPT_COARSE_TOP_K = 100

# 暫存區 AI 自動分群（HDBSCAN，見 docs/論文/03_系統設計與方法論.md § 3.1.1 §a）
CLUSTER_MIN_SIZE = 3  # 一個候選分群/新 KG 至少要有幾份文件，依需求由 v1 的 2 調整為 3

# UMAP 降維前處理（見 docs/論文/03_系統設計與方法論.md § 3.1.1 §a「降維前處理的決策」）——
# 僅在未分配資料夾池規模 ≥ 此值才對 HDBSCAN 的輸入做 UMAP 降維，訂在略高於 UMAP
# 預設 n_neighbors=15 的門檻：低於此規模時 UMAP 本身的流形估計不穩定，直接對
# VECTOR_DIM=384 維原始向量分群反而更可靠，並非「越像 BERTopic 越好」。
UMAP_MIN_POOL_SIZE = 20
UMAP_N_COMPONENTS = 5  # BERTopic (Grootendorst, 2022) 預設值，降維後仍保留分群所需的結構

# 實體對齊/去重門檻（見 docs/ARCHITECTURE.md「實體對齊與去重」2026-07-10 決策，
# docs/論文/03_系統設計與方法論.md § 3.1.4／3.4 §b）：先做字串編輯距離篩選（高度
# 相似直接視為同一實體），未命中則做向量餘弦相似度篩選（同類型且 ≥ 此門檻則
# MERGE）；介於 ESCALATE 門檻與 COSINE 門檻之間視為灰色地帶，交由 LLM 仲裁
# （3.4 §b ESCALATE 節點）。⚠️ 三個數值皆為工程預設，未經校準，見第五章消融實驗。
ENTITY_DEDUP_EDIT_RATIO_THRESHOLD = 0.70  # 校準參考：「台積電」對「台積電公司」的 SequenceMatcher ratio ≈ 0.75
ENTITY_DEDUP_COSINE_THRESHOLD = 0.88
ENTITY_DEDUP_ESCALATE_LOW_THRESHOLD = 0.75

# SVO 三元組合法語意關係類型——採 ConceptNet 5.5 核心關係集合（Speer, Chin &
# Havasi, 2017, AAAI 2017；逐字查證清單見 docs/參考文獻/03_資訊抽取與本體設計/README.md），
# 取代原本自行擬定的 30 類，對應 docs/論文/03_系統設計與方法論.md § 3.1.3「關係類型
# 收斂為扁平單一層」定案。⚠️ 論文正文自稱「36 個核心關係」，但逐字核對其明確列出
# 的清單實際只有 35 個（7 對稱＋28 非對稱）——此為原始論文自身的數字不一致，已在
# 上述查證文件誠實記錄，本清單採其列出的 35 個為準，不臆測缺漏的第 36 個是什麼。
# 命名採 Neo4j 關係型別慣例（UPPER_SNAKE_CASE），對應改寫 ConceptNet 原始 CamelCase
# 命名（如 IsA → IS_A）；語意不變。
SVO_REL_TYPES: set[str] = {
    # 對稱關係（7）
    "ANTONYM", "DISTINCT_FROM", "ETYMOLOGICALLY_RELATED_TO", "LOCATED_NEAR",
    "RELATED_TO", "SIMILAR_TO", "SYNONYM",
    # 非對稱關係（28）
    "AT_LOCATION", "CAPABLE_OF", "CAUSES", "CAUSES_DESIRE", "CREATED_BY",
    "DEFINED_AS", "DERIVED_FROM", "DESIRES", "ENTAILS", "EXTERNAL_URL",
    "FORM_OF", "HAS_A", "HAS_CONTEXT", "HAS_FIRST_SUBEVENT", "HAS_LAST_SUBEVENT",
    "HAS_PREREQUISITE", "HAS_PROPERTY", "INSTANCE_OF", "IS_A", "MADE_OF",
    "MANNER_OF", "MOTIVATED_BY_GOAL", "OBSTRUCTED_BY", "PART_OF",
    "RECEIVES_ACTION", "SENSE_OF", "SYMBOL_OF", "USED_FOR",
}

# 公用實體類型庫——採 schema.org 經實證驗證的最常見類型（2026-07-26 改版，取代原
# OntoNotes 18 類方案）。原方案的「18」總數雖經 Pradhan et al. (2013, CoNLL) 與
# Weischedel et al. (2011, Springer Handbook) 兩篇正式出版文獻交叉確認，但具體 18
# 個標籤名稱始終查無同行評審論文逐一列出，只能靠 spaCy／HuggingFace 等次級來源佐證
# ——查證缺口見 docs/參考文獻/03_資訊抽取與本體設計/README.md。改採 Brinkmann,
# Primpeli & Bizer (2023, WWW '23 Companion)《The Web Data Commons Schema.org Data
# Set Series》Table 1：基於 Common Crawl 實際抓取的 1,068 億筆 RDF quads／31 億個
# 實體／1,280 萬個網站，逐一列出使用量最高的 schema.org 類型——這份清單直接對應同
# 行評審論文的表格數據，不再有「總數有文獻、具體名稱無文獻」的落差。
# ⚠️ **誠實聲明（使用者已知悉此取捨並選擇採用）**：此排名反映的是網站為了讓 Google／
# Bing 顯示 rich snippet 而標註的**商業/行銷導向**分布（Product／Offer／
# LocalBusiness／Review／JobPosting 排名靠前，是因為這些類型能觸發搜尋結果圖文卡片，
# 論文原文明確指出這是站長標註的主要動機），與 OntoNotes 18 類「為新聞/廣播/任意領域
# 文本設計的通用 NER 類型」出發點不同；本專案 SVO 抽取對象含學術/技術文件等非電商網頁
# 內容，此清單未必是語意最貼切的參考類型，但换取的是「每個類型名稱都能追溯到同一份
# 同行評審論文的實測表格」這個更紮實的文獻基礎。
# 對應 § 3.1.4「實體型別選填、可多值、不做強制驗證」定案——本常數僅供 LLM 抽取時的
# 參考清單（見 services/svo_service.py::_svo_prompt()），不像 SVO_REL_TYPES 那樣
# 用於白名單驗證/退回機制，key 為受控標籤、value 為中文語意說明。
ENTITY_TYPES: dict[str, str] = {
    "PERSON": "人物",
    "PRODUCT": "產品",
    "OFFER": "報價/優惠（銷售提案）",
    "LOCAL_BUSINESS": "本地商家",
    "BLOG_POSTING": "部落格文章",
    "AGGREGATE_RATING": "綜合評分",
    "REVIEW": "評論",
    "EVENT": "事件",
    "QUESTION": "提問",
    "ANSWER": "回答",
    "JOB_POSTING": "職缺公告",
}

# 實體型別擴充庫（2026-07-26 新增，尚未接線使用）——上方 ENTITY_TYPES 是文獻佐證的
# 核心 11 類，比對不上時的較大備援池改直接以 schema.org 官方詞彙表本身為權威來源
# （不需另尋論文佐證：schema.org 官網即是第一手權威）。實際清單存於
# `data/schema_org_entity_types.json`（939 個 Type/class 節點，逐字下載自
# schema.org 官方 GitHub 倉庫 release 30.0 的 types.csv，已排除純列舉值實例，如
# ActiveActionStatus 這類 enumerationtype 底下的具體值，僅保留真正的型別階層節點），
# 資料量過大不適合當 Python 常數維護，也不適合塞進每次 LLM prompt——留待需要型別
# 正規化/驗證（如 3.1.4 節 Type 節點建模）時再讀取查閱，具體讀取與比對邏輯尚未實作。
