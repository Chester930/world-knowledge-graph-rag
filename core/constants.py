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
# 上述查證文件誠實記錄。
# ⚠️ 2026-07-27 再訂正為 33 個：查證 ConceptNet 官方 GitHub wiki
# （commonsense/conceptnet5/wiki/Relations，即時查詢版本）發現 ENTAILS／
# INSTANCE_OF 已被 ConceptNet 專案自己列為「已棄用」——官方原文建議 ENTAILS 應併入
# MANNER_OF 或 HAS_PREREQUISITE，INSTANCE_OF 應併入 IS_A，理由是自然語言鮮少能明確
# 區分這兩者與其目標關係的差異。本論文選擇跟進 ConceptNet 官方現行建議，移除這 2
# 個型別，改為 35-2=33 個，取代 2017 年論文快照版本（此為 2026-07-27 使用者確認的
# 訂正，非疏漏）。完整查證見 docs/參考文獻/03_資訊抽取與本體設計/README.md。
# 命名採 Neo4j 關係型別慣例（UPPER_SNAKE_CASE），對應改寫 ConceptNet 原始 CamelCase
# 命名（如 IsA → IS_A）；語意不變。
SVO_REL_TYPES: set[str] = {
    # 對稱關係（7）
    "ANTONYM", "DISTINCT_FROM", "ETYMOLOGICALLY_RELATED_TO", "LOCATED_NEAR",
    "RELATED_TO", "SIMILAR_TO", "SYNONYM",
    # 非對稱關係（26，已依 ConceptNet 官方現行建議移除 ENTAILS／INSTANCE_OF）
    "AT_LOCATION", "CAPABLE_OF", "CAUSES", "CAUSES_DESIRE", "CREATED_BY",
    "DEFINED_AS", "DERIVED_FROM", "DESIRES", "EXTERNAL_URL",
    "FORM_OF", "HAS_A", "HAS_CONTEXT", "HAS_FIRST_SUBEVENT", "HAS_LAST_SUBEVENT",
    "HAS_PREREQUISITE", "HAS_PROPERTY", "IS_A", "MADE_OF",
    "MANNER_OF", "MOTIVATED_BY_GOAL", "OBSTRUCTED_BY", "PART_OF",
    "RECEIVES_ACTION", "SENSE_OF", "SYMBOL_OF", "USED_FOR",
}

# `SIM` 節點比對門檻——見 docs/論文/03_系統設計與方法論.md § 3.1.3 主圖 `COMPARE`
# 節點：embedding 最相似的型別是否與 LLM 自報的 rel_type 一致，且最高分需 ≥ 此門檻，
# 兩者皆成立才視為兩個獨立訊號互相驗證、直接放行；否則交由 `ESCALATE3` 仲裁。
# ⚠️ 暫定值，未經校準：類比 `ENTITY_DEDUP_ESCALATE_LOW_THRESHOLD`（同為 0.75），
# 非從文獻直接推導，第五章消融實驗需依本論文實際資料重新校準（見
# docs/參考文獻/03_資訊抽取與本體設計/README.md「第三十一次調整」查證記錄）。
COMPARE_COSINE_THRESHOLD = 0.75

# `SIM` 節點的比對目標——33 個關係型別各自的自然語言描述句／範例句（而非型別
# 識別碼字串本身），依據 Chen & Li (2021) ZS-BERT 的描述句 embedding 設計與
# Xue et al. (2024) AutoRE 消融實驗（劣質描述句甚至不如不用描述句），見
# docs/參考文獻/03_資訊抽取與本體設計/README.md「第三十二次調整」。32 筆取自
# ConceptNet 官方 GitHub wiki（commonsense/conceptnet5/wiki/Relations，即時查詢
# 版本），`SENSE_OF` 一筆取自 Speer et al. (2017) 論文正文（現行 wiki 未列出此隱含
# 關係）。key 需與 `SVO_REL_TYPES` 完全一致，兩者以測試互相校驗。
SVO_REL_TYPE_DESCRIPTIONS: dict[str, str] = {
    # 對稱關係（7）
    "RELATED_TO": "A 與 B 有某種一般性的正向關聯，找不到更精確關係時使用，例如 learn 與 erudition",
    "SYNONYM": "A 與 B 是意義幾乎相同的詞，例如 sunlight 與 sunshine",
    "ANTONYM": "A 與 B 意義相反，例如 black 與 white",
    "DISTINCT_FROM": "A 與 B 是互斥、不可能同時成立的對照概念，例如 red 與 blue",
    "SIMILAR_TO": "A 與 B 相似但不完全相同，例如 mixer 與 food processor",
    "LOCATED_NEAR": "A 與 B 通常在彼此附近被發現，例如 chair 與 table",
    "ETYMOLOGICALLY_RELATED_TO": "A 與 B 有共同的字源，例如 folkmusiikki 與 folk music",
    # 非對稱關係（26）
    "FORM_OF": "A 是 B 的一個屈折或變化形式，例如 slept 是 sleep 的過去式",
    "IS_A": "A 是 B 的一個子類型或實例，例如 car 是一種 vehicle",
    "PART_OF": "A 是 B 的一部分，例如 gearshift 是 car 的一部分",
    "HAS_A": "B 屬於 A，或 A 擁有 B 作為部件，例如 bird 有 wing",
    "USED_FOR": "A 被用來做 B，例如 bridge 被用來 cross water",
    "CAPABLE_OF": "A 能夠做 B，例如 knife 能夠 cut",
    "AT_LOCATION": "A 是可以找到 B 的地方，例如 butter 通常在 refrigerator 找到",
    "CAUSES": "A 的發生會導致 B 發生，例如 exercise 導致 sweat",
    "HAS_FIRST_SUBEVENT": "A 是一個事件，B 是其開始時發生的動作，例如 sleep 從 close eyes 開始",
    "HAS_LAST_SUBEVENT": "A 是一個事件，B 是其結束時發生的動作，例如 cook 以 clean up kitchen 結束",
    "HAS_PREREQUISITE": "若要 A 發生，B 必須先發生或存在，例如 dream 的前提是 sleep",
    "HAS_PROPERTY": "A 具有 B 這個性質，例如 ice 是 cold 的",
    "MOTIVATED_BY_GOAL": "做 A 是為了達成目標 B，例如 compete 是為了 win",
    "OBSTRUCTED_BY": "A 會被 B 阻礙或妨礙，例如 sleep 會被 noise 妨礙",
    "DESIRES": "A 是一個會渴望 B 的實體，例如 person 渴望 love",
    "CREATED_BY": "B 是產生 A 的過程或行為，例如 cake 由 bake 這個動作產生",
    "DERIVED_FROM": "A 這個詞是由 B 這個詞衍生而來，例如 pocketbook 衍生自 book",
    "SYMBOL_OF": "A 象徵或代表 B，例如 red 象徵 fervor",
    "DEFINED_AS": "A 與 B 意義幾乎相同，但 B 提供更正式或百科式的定義，例如 peace 被定義為 absence of war",
    "MANNER_OF": "A 是 B 這個較一般行為的特定實現方式，例如 auction 是一種 sale",
    "HAS_CONTEXT": "A 在特定領域或情境 B 下才使用此意義，例如 astern 在 nautical 情境下使用",
    "CAUSES_DESIRE": "A 會讓人產生想做 B 的欲望，例如 having no food 會讓人想 go to a store",
    "MADE_OF": "A 由物質 B 構成，例如 bottle 由 plastic 構成",
    "RECEIVES_ACTION": "B 是可以對 A 做的動作，例如 button 可以被 push",
    "EXTERNAL_URL": "A 對應到外部資源的 URL B，例如 knowledge 對應到一個 dbpedia URL",
    "SENSE_OF": "A 是詞條 B 的一個特定詞義或語意，例如 lead 的名詞義是 lead 這個字的一個 SenseOf",
}

# 公用實體類型庫——採 schema.org 經實證驗證的最常見類型（2026-07-26 改版，取代原
# OntoNotes 18 類方案；同日再擴充至 52 類，見下方「2026-07-26 擴充」）。原方案的
# 「18」總數雖經 Pradhan et al. (2013, CoNLL) 與 Weischedel et al. (2011, Springer
# Handbook) 兩篇正式出版文獻交叉確認，但具體 18 個標籤名稱始終查無同行評審論文逐一
# 列出，只能靠 spaCy／HuggingFace 等次級來源佐證——查證缺口見
# docs/參考文獻/03_資訊抽取與本體設計/README.md。改採 Brinkmann, Primpeli & Bizer
# (2023, WWW '23 Companion)《The Web Data Commons Schema.org Data Set Series》：
# 基於 Common Crawl 實際抓取的 1,068 億筆 RDF quads／31 億個實體／1,280 萬個網站，
# 列出使用量最高的 schema.org 類型——每個類型名稱都能追溯到同一份同行評審論文的實測
# 數據，不再有「總數有文獻、具體名稱無文獻」的落差。
# ⚠️ **誠實聲明（使用者已知悉此取捨並選擇採用）**：此排名反映的是網站為了讓 Google／
# Bing 顯示 rich snippet 而標註的**商業/行銷導向**分布，與 OntoNotes 18 類「為新聞/
# 廣播/任意領域文本設計的通用 NER 類型」出發點不同；本專案 SVO 抽取對象含學術/技術
# 文件等非電商網頁內容，此清單未必是語意最貼切的參考類型，換取的是文獻可追溯性。
#
# **2026-07-26 擴充（同日，11→52 類）**：使用者認為原本 11 類（僅論文 Table 1「精選
# 展示」子集）數量偏少，要求以量化依據判斷是否足夠、如何擴充。查證發現同一個 2022
# release 官方統計頁（`webdatacommons.org/structureddata/2022-12/stats/
# schema_org_subsets.html`）另外公開了 48 個類型的完整實測數字（Hosts／URLs／
# Quads），且此頁面與 Table 1 的統計角度不同（Table 1 是全語料庫直接計數，統計頁只
# 收錄 WDC 特意建了獨立下載子集的類型），兩者聯集去重後（48 個官方統計頁類型 +
# Table 1 獨有的 4 個：Offer／BlogPosting／AggregateRating／Review）共 **52 個**
# 不重複類型，依 Hosts（使用網站數）由高到低排序，每個都有官方精確數字佐證，非隨意
# 篩選。完整數字見 docs/參考文獻/03_資訊抽取與本體設計/README.md。
# 對應 § 3.1.4「實體型別選填、可多值、不做強制驗證」定案——本常數僅供 LLM 抽取時的
# 參考清單（見 services/svo_service.py::_svo_prompt()），不像 SVO_REL_TYPES 那樣
# 用於白名單驗證/退回機制，key 為受控標籤、value 為中文語意說明。
ENTITY_TYPES: dict[str, str] = {
    "ORGANIZATION": "組織",
    "PERSON": "人物",
    "PRODUCT": "產品",
    "OFFER": "報價/優惠（銷售提案）",
    "LOCAL_BUSINESS": "本地商家",
    "CREATIVE_WORK": "創作作品（廣義內容作品）",
    "BLOG_POSTING": "部落格文章",
    "AGGREGATE_RATING": "綜合評分",
    "GEO_COORDINATES": "地理座標",
    "PLACE": "地點",
    "REVIEW": "評論",
    "EVENT": "事件",
    "QUESTION": "提問",
    "ANSWER": "回答",
    "FAQ_PAGE": "常見問答頁",
    "RESTAURANT": "餐廳",
    "JOB_POSTING": "職缺公告",
    "RECIPE": "食譜",
    "MUSIC_RECORDING": "音樂錄音",
    "COUNTRY": "國家",
    "HOTEL": "飯店",
    "BOOK": "書籍",
    "MUSIC_ALBUM": "音樂專輯",
    "CITY": "城市",
    "QA_PAGE": "問答頁",
    "LANGUAGE": "語言",
    "EDUCATIONAL_ORGANIZATION": "教育機構",
    "MOVIE": "電影",
    "SPORTS_EVENT": "體育賽事",
    "SPORTS_TEAM": "運動隊伍",
    "COLLEGE_OR_UNIVERSITY": "大專院校",
    "ADMINISTRATIVE_AREA": "行政區域",
    "HOSPITAL": "醫院",
    "SCHOOL": "學校",
    "DATASET": "資料集",
    "GOVERNMENT_ORGANIZATION": "政府機構",
    "TV_EPISODE": "電視劇集",
    "SHOPPING_CENTER": "購物中心",
    "RADIO_STATION": "廣播電台",
    "LIBRARY": "圖書館",
    "MUSEUM": "博物館",
    "AIRPORT": "機場",
    "PAINTING": "繪畫作品",
    "LANDMARKS_OR_HISTORICAL_BUILDINGS": "地標/歷史建築",
    "PARK": "公園",
    "STADIUM_OR_ARENA": "體育場館",
    "SKI_RESORT": "滑雪度假村",
    "LAKE_BODY_OF_WATER": "湖泊水體",
    "TELEVISION_STATION": "電視台",
    "CONTINENT": "洲",
    "MOUNTAIN": "山",
    "RIVER_BODY_OF_WATER": "河流水體",
}

# 實體型別擴充庫（2026-07-26 新增，讀取/比對邏輯已接線於
# services/svo_service.py::resolve_entity_type()）——上方 ENTITY_TYPES 是文獻佐證的
# 核心 52 類，比對不上時的較大備援池改直接以 schema.org 官方詞彙表本身為權威來源
# （不需另尋論文佐證：schema.org 官網即是第一手權威）。實際清單存於
# `data/schema_org_entity_types.json`（939 個 Type/class 節點，逐字下載自
# schema.org 官方 GitHub 倉庫 release 30.0 的 types.csv，已排除純列舉值實例，如
# ActiveActionStatus 這類 enumerationtype 底下的具體值，僅保留真正的型別階層節點），
# 資料量過大不適合當 Python 常數維護，也不適合塞進每次 LLM prompt——`extract_svo_triples()`
# 抽取後才用 `resolve_entity_type()` 正規化 subject_type/object_type：核心庫優先，
# 查不到才查此擴充庫，兩者皆查無對應時保留 LLM 原始輸出，不做強制驗證/不拒絕。
