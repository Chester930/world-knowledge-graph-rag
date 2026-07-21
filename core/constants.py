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

# SVO 三元組合法語意關係類型（30 種，依 CLAUDE.md 分組）
SVO_REL_TYPES: set[str] = {
    "IS_A", "PART_OF", "CONTAINS", "INSTANCE_OF",
    "CAUSES", "PREVENTS", "ENABLES", "IMPROVES", "INHIBITS",
    "USES", "REQUIRES", "PRODUCES", "IMPLEMENTS", "REPLACES", "EXTENDS",
    "CONTRASTS", "SIMILAR_TO", "OUTPERFORMS",
    "DEFINED_AS", "HAS_PROPERTY", "MEASURED_BY", "APPLIES_TO",
    "PRECEDES", "FOLLOWS", "CO_OCCURS",
    "INPUTS", "TRANSFORMS",
    "CREATED_BY", "SOLVES",
    "RELATED_TO",
}
