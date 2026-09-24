"""`KGConfig` 與其分區子模型 —— 報告33 §3.9.1 的「約二十個未校準門檻常數」收編。

所有子模型 `frozen=True`：一旦建構，任一層（含巢狀）寫入都拋
`pydantic_core.ValidationError`——支撐「單一行程服務多知識圖譜時無共享可變
狀態的競態」（論文 04 §4.10 驗收標準之一）。

**每個 `Field` 的預設值 = 重構前對應模組常數的現值**，來源標於註解。golden test
（`tests/core/test_kg_config.py`）逐欄位比對 live 常數，任何漂移都會 fail。

第 1 步只收 scalar 常數；第 3a 步（2026-09-08）加 `domain` 分區的
`system_context`／`target_language`（generation prompt 前綴、輸出語言）。
`svo_fewshots` 於第 3b 步併入；第 4 步加入 `guard` 分區，收納 SVO
守衛正則的 domain token 清單。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

_FROZEN = ConfigDict(frozen=True, extra="forbid")


# services/svo_service.py::_svo_prompt() 的規則6–10少樣本內容。這是 domain
# 內容的一部分，集中放在 KGConfig 的 domain 層；prompt 組裝端只負責動態加上
# 規則編號，避免 default 與 domain pack 各自維護兩份字串。
_DEFAULT_SVO_FEWSHOTS: tuple[str, ...] = (
    """subject／object 必須是簡潔、可重複使用的名詞或名詞片語（如「勞工」「雇主」「特別休假」「留職停薪」），不可整段抄錄條文子句或完整句子。條件、期限、例外情形等細節應放進 verb 或拆成多筆三元組，不要塞進 subject／object 本身。""",
    """一句話常常包含不只一件事實。除了主要動作之外，若句子還提到任何進一步限定或補充主要動作的內容——**不限於**數量上限、次數限制、期限、給付／工資狀態，也包括方式或單位（如得以小時／以日為請假單位）、對象範圍、例外情形等任何附加規定——這些都要各自拆成獨立的三元組完整抽出，不可以只抽主要動作、把附加規定省略掉——即使某個三元組的 subject 跟其他三元組重複，也要各自輸出。

反例（不要這樣做）：
subject: "適用勞動基準法之外國人於聘僱許可有效期間內，向雇主請求以特別休假以外之假別返國時，應依勞動基準法、性別平等工作法規定及勞動契約之約定辦理。"

正確做法（拆成簡潔實體 + 完整關係描述放 verb）：
{"subject":"外國人", "verb":"於聘僱許可有效期間內向雇主請求以特別休假以外之假別返國時，應依規定辦理", "object":"勞動基準法及性別平等工作法規定"}

反例（不要這樣做——只抽了主要動作，漏掉數量上限與給付狀態）：
原文："勞工因有事故必須親自處理，得請事假，一年內合計不得超過十四日。事假期間不給工資。"
只輸出 {"subject":"勞工", "verb":"因有事故必須親自處理，得請", "object":"事假"}，漏掉了十四日上限與不給工資這兩件事實。

正確做法（同一句話的每一項附加規定都各自拆成三元組）：
{"subject":"勞工", "verb":"因有事故必須親自處理，得請", "object":"事假"}
{"subject":"事假", "verb":"一年內合計不得超過", "object":"十四日"}
{"subject":"事假期間", "verb":"不給", "object":"工資"}

反例（不要這樣做——附加規定不是數量/期限/工資這幾種常見類型時也會被漏抓，例如請假的「方式／單位」彈性）：
原文："勞工為親自照顧家庭成員，除本法或其他法律另有規定者外，得依前項規定請事假，並得擇定以小時為請假單位。"
只輸出 {"subject":"勞工", "verb":"為親自照顧家庭成員，得依前項規定請", "object":"事假"}，漏掉了「得以小時為請假單位」這項方式彈性——這跟數量上限、期限、工資狀態是同一類「附加規定」，不能因為它不屬於這幾種常見類型就不抽。

正確做法（主要動作與方式彈性各自拆成三元組）：
{"subject":"勞工", "verb":"為親自照顧家庭成員，得依前項規定請", "object":"事假"}
{"subject":"勞工", "verb":"因親自照顧家庭成員請事假時，得擇定", "object":"以小時為請假單位"}

反例（不要這樣做——數量緊貼在名詞後面時，把數量黏進 object，導致之後查「婚假」查不到天數）：
原文："勞工結婚者給予婚假八日，工資照給。"
只輸出 {"subject":"勞工", "verb":"結婚者給予", "object":"婚假八日"}，把「婚假」跟「八日」黏成一個詞塞進 object，天數變成查不到的死資訊。

正確做法（即使數量緊貼在名詞後面、看起來像一個詞，也要拆成獨立三元組，不要黏在一起；subject／verb／object 必須反映這段原文本身的措辭，不可以照抄其他範例的用字）：
{"subject":"勞工", "verb":"結婚者給予", "object":"婚假"}
{"subject":"婚假", "verb":"天數為", "object":"八日"}
{"subject":"婚假", "verb":"照給", "object":"工資"}""",
    """若文本是「共同前提＋下列各款列舉項目」的結構（如「……下列各款……均不計入：一、……。二、……。」），每個列舉項目都要各自形成一筆完整的三元組，繼承共同的動詞與另一端實體，不可以 subject 填了、object 卻留空（或反過來）。

反例（不要這樣做——列舉項目的 object 留空，資訊不完整）：
原文："依本法第二條第四款計算平均工資時，下列各款期日或期間均不計入：一、發生計算事由之當日。二、因職業災害尚在醫療中者。五、依勞工請假規則請普通傷病假者。"
只輸出 {"subject":"依勞工請假規則請普通傷病假者", "verb":"", "object":""}，object 是空的，這筆三元組沒有意義。

正確做法（每個列舉項目都繼承共同的動詞與對象，各自形成完整三元組）：
{"subject":"發生計算事由之當日", "verb":"不計入", "object":"平均工資計算期間"}
{"subject":"因職業災害尚在醫療中者", "verb":"不計入", "object":"平均工資計算期間"}
{"subject":"依勞工請假規則請普通傷病假者", "verb":"不計入", "object":"平均工資計算期間"}
（其餘列舉項目依此類推，每一項都各自產生一筆完整三元組，不留空欄位）""",
    """若文本是「分類列舉」結構（如「……分下列N種：一、……。二、……。」），每個列舉項目是類別名稱本身，不是條件——不要照抄前提句的動詞，應推論「屬於」關係，object 用前提句主詞改寫成的類別名稱。

反例（不要這樣做——分類列舉全部留空，因為前提句本身沒有可直接借用的動詞受詞）：
原文："本保險之給付，分下列五種：一、失業給付。二、提早就業獎助津貼。三、職業訓練生活津貼。四、育嬰留職停薪津貼。五、失業之被保險人及隨同被保險人辦理加保之眷屬全民健康保險保險費補助。"
只輸出 {"subject":"失業給付", "verb":"", "object":""} 這類全空的三元組。

正確做法（每個類別項目都用「屬於」連到推論出的類別名稱）：
{"subject":"失業給付", "verb":"屬於", "object":"本保險之給付種類"}
{"subject":"提早就業獎助津貼", "verb":"屬於", "object":"本保險之給付種類"}
{"subject":"職業訓練生活津貼", "verb":"屬於", "object":"本保險之給付種類"}
{"subject":"育嬰留職停薪津貼", "verb":"屬於", "object":"本保險之給付種類"}
（其餘列舉項目依此類推，每一項都各自產生一筆完整三元組，不留空欄位）""",
    """若一句話是「共同條件 → 一個或多個結果」的結構（例如「甲情形時，乙應達 X，且丙不得低於 Y」），依規則7拆成獨立三元組時，**共同條件必須複述進每一筆結果三元組的 verb 裡**，不可以只留在單獨一筆條件三元組上、讓其餘三元組看起來像無條件成立。

反例（不要這樣做——條件只留在一筆，其餘三筆看起來無條件成立）：
原文："雇主依本法第二十四條第二項規定辦理訓練，並申請訓練費用補助者，最低開班人數應達五人，且訓練時數不得低於八十小時。"
輸出 {"subject":"雇主", "verb":"依本法第二十四條第二項規定辦理", "object":"訓練"}、{"subject":"最低開班人數", "verb":"應達", "object":"五人"}、{"subject":"訓練時數", "verb":"不得低於", "object":"八十小時"}——後兩筆完全看不出這是「雇主辦理訓練並申請補助」才適用的門檻。

正確做法（條件複述進每一筆結果三元組的 verb）：
{"subject":"雇主", "verb":"依本法第二十四條第二項規定辦理", "object":"訓練"}
{"subject":"最低開班人數", "verb":"（雇主依本法第二十四條第二項規定辦理訓練並申請訓練費用補助時）應達", "object":"五人"}
{"subject":"訓練時數", "verb":"（雇主依本法第二十四條第二項規定辦理訓練並申請訓練費用補助時）不得低於", "object":"八十小時"}

反例（不要這樣做——列舉前言本身單獨抽成一筆時漏了數量，即使各列舉項目都有正確帶數量）：
原文："有左列情事之一者，給予三至七日之特別休假：一、……。"
除了各列舉項目各自正確產出「因……者 給予 三至七日之特別休假」之外，另外把前言本身也抽成一筆 {"subject":"左列情事之一者", "verb":"給予", "object":"特別休假"}——這筆漏了原文明明就有的「三至七日」。

正確做法（前言本身這筆也要帶數量，不可以比各列舉項目少）：
{"subject":"左列情事之一者", "verb":"給予", "object":"三至七日之特別休假"}""",
)


# services/svo_service.py 的 CJK 守衛正則只把這些 domain token 清單交給
# GuardConfig；中文數字、比較句式間隔與序數／分數／小數／附表結構仍固定在
# svo_service.py。順序刻意保持與原模組正則逐字一致，供 golden test 鎖定。
_DEFAULT_MEASURE_UNITS: tuple[str, ...] = (
    "個月", "個年", "個星期", "日", "月", "年", "次", "小時", "分鐘",
    "百分之", "％", "%", "元", "倍", "等級", "歲", "人", "名", "週", "度",
    "種", "類", "條", "款", "項", "點",
)
_DEFAULT_RANGE_TRAILING_COMPARATORS: tuple[str, ...] = ("以上", "以下", "以內")
_DEFAULT_RANGE_LEADING_COMPARATORS: tuple[str, ...] = ("未滿", "超過")
_DEFAULT_SCOPE_MODIFIER_WORDS: tuple[str, ...] = (
    "增加", "增列", "額外", "追加", "新增", "另計", "加計", "超出",
)
_DEFAULT_ENUM_CLOSED_VALUES: tuple[str, ...] = ("顯著", "中度", "低度")


class GuardConfig(BaseModel):
    """實體模糊合併與自然語言化核對的 CJK 守衛 token 清單。

    只收 domain 詞彙清單；中文數字字元類、比較句式間隔長度，以及序數／
    分數／小數／附表格式等結構性樣式維持在 ``services.svo_service`` 固定。
    """

    model_config = _FROZEN

    # services/svo_service.py::_MEASURE_PATTERN 單位詞清單
    measure_units: tuple[str, ...] = Field(default_factory=lambda: _DEFAULT_MEASURE_UNITS)
    # services/svo_service.py::_RANGE_COMPARATOR_PATTERN 後置比較詞（數字在前）
    range_trailing_comparators: tuple[str, ...] = Field(
        default_factory=lambda: _DEFAULT_RANGE_TRAILING_COMPARATORS
    )
    # services/svo_service.py::_RANGE_COMPARATOR_PATTERN 前置比較詞（數字在後）
    range_leading_comparators: tuple[str, ...] = Field(
        default_factory=lambda: _DEFAULT_RANGE_LEADING_COMPARATORS
    )
    # services/svo_service.py::_SCOPE_MODIFIER_PATTERN 修飾詞清單
    scope_modifier_words: tuple[str, ...] = Field(
        default_factory=lambda: _DEFAULT_SCOPE_MODIFIER_WORDS
    )
    # services/svo_service.py::_ENUM_GUARD_PATTERN 封閉列舉值部分（風險等級）
    enum_closed_values: tuple[str, ...] = Field(default_factory=lambda: _DEFAULT_ENUM_CLOSED_VALUES)


class ChunkingConfig(BaseModel):
    """SVO 切塊與主旨前綴錨定（`services/svo_chunking.py`）。"""

    model_config = _FROZEN

    # services/svo_chunking.py::DEFAULT_SVO_CHUNK_MAX_SENTENCES
    max_sentences: int = Field(default=5, ge=1, le=50, description="每塊最大句數")
    # services/svo_chunking.py::DEFAULT_SVO_CHUNK_OVERLAP_SENTENCES
    overlap_sentences: int = Field(default=2, ge=0, le=20, description="相鄰塊重疊句數")
    strategy: Literal["sliding_window", "header_anchored"] = Field(
        default="sliding_window",
        description="切塊策略：sliding_window（純句數滑動視窗）或 header_anchored（主旨前綴錨定）",
    )
    header_regex: str | None = Field(
        default=r"^第[一二三四五六七八九十百千0-9]+條.*",
        description="主旨/法條識別正則表達式",
    )
    prepend_header_to_children: bool = Field(
        default=True,
        description="當條文跨 Chunk 切分時，是否自動將母條文首句條旨作為前綴注入至子款項 Chunk",
    )
    max_chunk_chars: int = Field(
        default=1000, ge=100, le=10000, description="單塊字元軟上限",
    )



class RoutingConfig(BaseModel):
    """ConceptNode 路由層與暫存區分類門檻（`core/constants.py`）。"""

    model_config = _FROZEN

    # core/constants.py::KG_ROUTE_THRESHOLD
    kg_route_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    # core/constants.py::CLASSIFY_AUTO_THRESHOLD
    classify_auto_threshold: float = Field(default=0.30, ge=0.0, le=1.0)
    # core/constants.py::CLASSIFY_MIN_THRESHOLD
    classify_min_threshold: float = Field(default=0.05, ge=0.0, le=1.0)


class BfsConfig(BaseModel):
    """查詢端 BFS 遍歷與種子（`routers/agent.py`、`services/svo_service.py`）。

    報告27 §6.2 待辦2 / 報告32 §9 的 θ 家族——第 2 步優先接這一區。
    """

    model_config = _FROZEN

    # routers/agent.py::_SEED_ENTITY_LIMIT
    seed_entity_limit: int = Field(default=8, ge=1, le=64)
    # routers/agent.py::_SEED_MAX_DEGREE（2026-09-05 §6.2 單題調校 200→100）
    seed_max_degree: int = Field(default=100, ge=1)
    # routers/agent.py::_BFS_PER_SEED_LIMIT（2026-09-05 §6.2 單題調校 60→30）
    per_seed_limit: int = Field(default=30, ge=1)
    # routers/agent.py::_DOC_SCOPE_TOP_N_FACTS
    doc_scope_top_n_facts: int = Field(default=5, ge=1)
    # services/svo_service.py::_BFS_EXPAND_WHEN_BELOW
    expand_when_below: int = Field(default=8, ge=0)
    # services/svo_service.py::_BFS_PRIZE_TOP_K（報告32 §9 L2，prototype 預設）
    prize_top_k: int = Field(default=10, ge=1)


class FactListConfig(BaseModel):
    """生成端事實清單組裝、排序、融合（`routers/agent.py`）。"""

    model_config = _FROZEN

    # routers/agent.py::_FACT_LINE_TRUNCATE_K
    truncate_k: int = Field(default=18, ge=1)
    # routers/agent.py::_FACT_LINE_REORDER_THRESHOLD_K
    reorder_threshold_k: int = Field(default=35, ge=1)
    # routers/agent.py::_BFS_KEEP_MAX
    bfs_keep_max: int = Field(default=18, ge=1)
    # routers/agent.py::_MIN_BFS_SLOTS
    min_bfs_slots: int = Field(default=4, ge=0)
    # routers/agent.py::_RRF_K（Cormack et al. 2009 文獻值；非未校準常數，收此供覆蓋）
    rrf_k: int = Field(default=60, ge=1)
    # 報告62 T3：預設關閉的條文層級 Fact 擴充；每條文只補這麼多兄弟 Fact。
    article_expand: bool = False
    article_expand_sibling_limit: int = Field(default=8, ge=0, le=64)


class DecomposeConfig(BaseModel):
    """複合問題分解與分段清單 completeness guard（`routers/agent.py`）。"""

    model_config = _FROZEN

    # routers/agent.py::_MAX_SUBQUESTIONS
    max_subquestions: int = Field(default=6, ge=1, le=32)
    # routers/agent.py::_TIER_MIN_MEMBERS
    tier_min_members: int = Field(default=3, ge=2)


class DedupConfig(BaseModel):
    """實體模糊合併門檻（`core/constants.py`；`resolve_entity_name()` 三段式）。"""

    model_config = _FROZEN

    # core/constants.py::ENTITY_DEDUP_EDIT_RATIO_THRESHOLD
    edit_ratio_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    # core/constants.py::ENTITY_DEDUP_COSINE_THRESHOLD
    cosine_threshold: float = Field(default=0.88, ge=0.0, le=1.0)
    # core/constants.py::ENTITY_DEDUP_ESCALATE_LOW_THRESHOLD
    escalate_low_threshold: float = Field(default=0.75, ge=0.0, le=1.0)


class RelTypeConfig(BaseModel):
    """關係型別調解門檻（`core/constants.py`；SIM/COMPARE/ESCALATE3、查詢時連結）。"""

    model_config = _FROZEN

    # core/constants.py::COMPARE_COSINE_THRESHOLD
    compare_cosine_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    # core/constants.py::QSIM_ASSIGN_THRESHOLD
    qsim_assign_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    # core/constants.py::QSIM_ESCALATE_LOW_THRESHOLD
    qsim_escalate_low_threshold: float = Field(default=0.60, ge=0.0, le=1.0)


class ExtractionConfig(BaseModel):
    """抽取完整性自檢門檻（報告19）。"""

    model_config = _FROZEN

    # services/svo_service.py::UNCOVERED_SENTENCE_THRESHOLD
    uncovered_sentence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)


# 第 3a 步（2026-09-08）：generation prompt 前綴（領域/語言鎖定）。shipped
# default 逐字等於 `routers/agent.py::_TAIWAN_CONTEXT_INSTRUCTION`——golden test
# 比對。`generic` domain pack 會把 `system_context` 覆蓋成中性版（論文 §2.6.8
# 已聲明這是唯一「非逐字零變化」處，且僅在明確載入 generic pack 時發生）。
_TAIWAN_CONTEXT_INSTRUCTION_DEFAULT = (
    "你是台灣勞動法規顧問，只根據台灣現行法規（例如勞動基準法、勞工保險條例、"
    "性別平等工作法等）回答，絕對不要引用中國大陸、香港、澳門或其他地區的法規、"
    "機關名稱或數值（例如「中華人民共和國勞動法」），也不要混用其他地區的制度或用語。"
    "請一律使用繁體中文回答，不要使用簡體字。"
)


class DomainConfig(BaseModel):
    """領域包層——generation prompt 前綴、輸出語言與 SVO 少樣本規則。"""

    model_config = _FROZEN

    name: str = Field(default="taiwan-labor-law")
    # routers/agent.py::_TAIWAN_CONTEXT_INSTRUCTION（每個生成 prompt 的前綴）
    system_context: str = Field(default=_TAIWAN_CONTEXT_INSTRUCTION_DEFAULT)
    target_language: str = Field(default="zh-Hant")
    # services/svo_service.py::_svo_prompt() 規則 6–10；domain pack 可覆蓋。
    svo_fewshots: tuple[str, ...] = Field(default_factory=lambda: _DEFAULT_SVO_FEWSHOTS)


class KGConfig(BaseModel):
    """一個知識圖譜的完整可調整項。

    `KGConfig()` = shipped defaults 層，逐欄位等於重構前的模組常數 / prompt 字串。
    經 `ConfigLoader` 疊上 domain pack / per-KG profile / per-request 後仍是同一型別。
    """

    model_config = _FROZEN

    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    bfs: BfsConfig = Field(default_factory=BfsConfig)
    factlist: FactListConfig = Field(default_factory=FactListConfig)
    decompose: DecomposeConfig = Field(default_factory=DecomposeConfig)
    dedup: DedupConfig = Field(default_factory=DedupConfig)
    reltype: RelTypeConfig = Field(default_factory=RelTypeConfig)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    guard: GuardConfig = Field(default_factory=GuardConfig)
    domain: DomainConfig = Field(default_factory=DomainConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
