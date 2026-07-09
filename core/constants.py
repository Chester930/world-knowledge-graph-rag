INTEREST_INIT = 0.5
PROFESSIONAL_INIT = 0.5
VECTOR_DIM = 384  # paraphrase-multilingual-MiniLM-L12-v2

# KG 路由門檻
KG_ROUTE_THRESHOLD = 0.05      # Agent 問答：低於此分數的 KG 不召回
MAX_KG_PER_QUERY = 5           # Agent 問答：最多召回幾個 KG

# 文件分配門檻
CLASSIFY_AUTO_THRESHOLD = 0.30  # 自動分配：top score 需超過此值才自動移動
CLASSIFY_MIN_THRESHOLD = 0.05   # 低於此值視為完全無相關，留在暫存區等待

# 兩階段向量粗精篩（Two-Stage Retrieval）
CONCEPT_COARSE_TOP_K = 100

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
