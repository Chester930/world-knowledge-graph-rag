"""N4 搬移差分測試的案例產生與執行（報告160 U1）。**不是測試檔**（檔名不以 test_ 開頭）。

``run_all(ns)`` 對 ``ns``（``services.svo_service`` 模組，或任何提供同名 N4 符號的物件）逐案執行，
回傳可 JSON 序列化的結果清單：輸出、例外型別與訊息、``add_candidate``／``log_escalation`` 呼叫序列、
logger 記錄。使用假 LLM／假 embedding provider，不連網路、不碰資料庫。

搬移前以舊實作產生 golden（``python -m tests.services.n4_differential_harness --write-golden``），
搬移後 ``tests/services/test_n4_differential.py`` 用新程式重跑並逐案比對。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from core.constants import SVO_REL_TYPE_DESCRIPTIONS, SVO_REL_TYPES  # noqa: E402
from core.kg_config import GuardConfig, KGConfig, RelTypeExtension  # noqa: E402
from core.providers.base import EmbeddingProvider, LLMProvider  # noqa: E402
from models.knowledge_graph import SVOTriple  # noqa: E402
from services import expand_governance_service, sim_calibration_service  # noqa: E402

GOLDEN = Path(__file__).parent / "fixtures" / "n4_differential_golden.json"
SEED = 20260930

CONSTANT_NAMES = [
    "_ENTITY_TYPE_GUIDE", "_CORE_TYPE_LOOKUP", "UNCOVERED_SENTENCE_THRESHOLD", "_QUANTITY_PATTERN",
    "_CJK_NUMBER_PATTERN", "_MEASURE_NUMBER_PATTERN", "_RANGE_NUMBER_GAP_PATTERN", "_MEASURE_PATTERN",
    "_RANGE_COMPARATOR_PATTERN", "_ENUM_GUARD_PATTERN", "_SCOPE_MODIFIER_PATTERN", "_LEAVE_TYPE_FAMILY",
    "_ENTITY_FAMILIES", "_CLAUSE_SPLIT_PATTERN", "_BINDING_NORMALIZE_PATTERN", "_MIN_BINDING_SUBJECT_LEN",
    "_BINDING_UNITS", "_RISK_LEVEL_BY_BUSINESS_CATEGORY", "_KNOWN_SIMPLIFIED_COMPOUNDS", "_DEFAULT_GUARD_CONFIG",
]


# ── 假 provider ───────────────────────────────────────────────────────


def _hashvec(text: str, dim: int = 16) -> list[float]:
    h = hashlib.sha256(text.encode("utf-8")).digest()
    return [(h[i] - 127.5) / 127.5 for i in range(dim)]


class FakeEmbedding(EmbeddingProvider):
    """「近似:TYPE」的動詞會得到與該型別描述幾乎相同的向量，其餘為雜湊向量。"""

    def __init__(self):
        self.calls: list[str] = []

    @property
    def dim(self) -> int:
        return 16

    @property
    def model_name(self) -> str:
        return "fake-embedding"

    async def encode(self, text: str) -> list[float]:
        self.calls.append(text)
        if text.startswith("近似:"):
            desc = SVO_REL_TYPE_DESCRIPTIONS.get(text[3:], text)
            base, noise = _hashvec(desc), _hashvec(text)
            return [b + 0.02 * n for b, n in zip(base, noise)]
        return _hashvec(text)


class FakeLLM(LLMProvider):
    def __init__(self, answers: list, json_answers: list | None = None):
        self._answers = list(answers)
        self._json = list(json_answers or [])
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        a = self._answers.pop(0) if self._answers else "皆非"
        if isinstance(a, Exception):
            raise a
        return a

    async def stream(self, prompt: str):
        yield ""

    async def generate_json(self, prompt: str) -> str:
        self.prompts.append(prompt)
        a = self._json.pop(0) if self._json else "[]"
        if isinstance(a, Exception):
            raise a
        return a


# ── 序列化 ────────────────────────────────────────────────────────────


def jsonable(x):
    import re

    if isinstance(x, SVOTriple):
        return {"__triple__": x.model_dump(mode="json")}
    if isinstance(x, re.Pattern):
        return {"__re__": x.pattern, "flags": x.flags}
    if isinstance(x, (set, frozenset)):
        return {"__set__": sorted(jsonable(v) if not isinstance(v, str) else v for v in x)}
    if isinstance(x, tuple):
        return {"__tuple__": [jsonable(v) for v in x]}
    if isinstance(x, list):
        return [jsonable(v) for v in x]
    if isinstance(x, dict):
        return {"__dict__": [[jsonable(k), jsonable(v)] for k, v in x.items()]}
    if isinstance(x, Path):
        return {"__path__": "<path>"}
    if isinstance(x, float):
        return {"__float__": repr(x)}
    if isinstance(x, (str, int, bool)) or x is None:
        return x
    if hasattr(x, "model_dump"):
        return {"__model__": type(x).__name__, "v": x.model_dump(mode="json")}
    return {"__repr__": repr(x)}


def call_sync(fn, *a, **k):
    try:
        return {"ok": jsonable(fn(*a, **k))}
    except Exception as e:  # noqa: BLE001
        return {"exc": type(e).__name__, "msg": str(e)}


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records: list[list] = []

    def emit(self, record):
        self.records.append([record.name, record.levelname, record.getMessage()])


def call_async(coro_fn, *a, capture_effects=False, add_raises=False, log_raises=False, **k):
    """執行 async 函式並記錄結果；可選擇攔截 add_candidate／log_escalation 與 logger。"""
    effects: list = []
    handler = LogCapture()
    log = logging.getLogger("services.svo_service")
    log.addHandler(handler)
    old_level = log.level
    log.setLevel(logging.DEBUG)

    def add_candidate(db_path, kg_id, verb, verb_embedding):
        effects.append(["add_candidate", str(Path(db_path).name), kg_id, verb, [round(v, 9) for v in verb_embedding]])
        if add_raises:
            raise RuntimeError("add_candidate boom")

    def log_escalation(db_path, kg_id, a_, b_, score, final):
        effects.append(["log_escalation", str(Path(db_path).name), kg_id, a_, b_, round(score, 9), final])
        if log_raises:
            raise RuntimeError("log_escalation boom")

    try:
        with patch.object(expand_governance_service, "add_candidate", add_candidate), \
                patch.object(sim_calibration_service, "log_escalation", log_escalation):
            try:
                out = {"ok": jsonable(asyncio.run(coro_fn(*a, **k)))}
            except Exception as e:  # noqa: BLE001
                out = {"exc": type(e).__name__, "msg": str(e)}
    finally:
        log.removeHandler(handler)
        log.setLevel(old_level)
    out["effects"] = effects
    out["logs"] = handler.records
    return out


# ── 資料 ──────────────────────────────────────────────────────────────

SUBJ = ["勞工", "雇主", "事業單位", "主管機關", "第一類事業", "第二類事業", "職業災害勞工", "受僱者", "婚假", "事假",
        "產假", "特別休假", "從業人員", "高度在二公尺以上者", "未滿六個月者", "普通傷病假"]
OBJ = ["八日", "工資照給", "三十日", "至少二十分鐘休息", "百分之六", "新臺幣二十萬元", "一年內合計不得超過十四日",
       "二年內合計不得超過一年", "應予同意", "於五日前提出", "六個月為限", "一至三日之特別休假", "三至七日", "二次為限",
       "至少三人", "每逾十人增置一人", "低度風險", "中度風險", "顯著風險", "報請核准"]
VERBS = ["給予", "應為", "不得低於", "得請", "以為限", "準用", "適用", "負擔", "終止", "核發", "補足", "折半發給",
         "應予留職停薪", "由中央主管機關定之", "屬於", "包含", "近似:HAS_PROPERTY", "近似:REQUIRES", "近似:PART_OF"]
SENT = ["勞工結婚者給予婚假八日，工資照給。", "事假一年內合計不得超過十四日，事假期間不給工資。",
        "高度在二公尺以上未滿五公尺者，至少有二十分鐘休息。", "第一類事業之事業單位勞工人數在一百人以上者，應設專責一級管理單位。",
        "雇主應為勞工負擔提繳之退休金，不得低於勞工每月工資百分之六。", "普通傷病假一年內未超過三十日部分，工資折半發給。",
        "一、第一類事業：具顯著風險者。", "二、第二類事業：具中度風險者。", "三、第三類事業：具低度風險者。",
        "從業人員人數在五人以下者，應置就業服務專業人員至少一人。", "產假期間工資照給，未滿六個月者減半發給。",
        "本辦法依勞動基準法第二十七條規定訂定之。", "每次以不少於六個月為原則。"]
SIMP = ["这项规定适用于劳动者", "雇主应当为员工缴纳保险", "职业灾害补偿标准", "请假期间的工资照发", "台湾劳工请假规则",
        "婴儿留职停薪申请", "补助经费由主管机关核发", "勞工結婚者給予婚假八日", "事業單位應予同意", "育婴留职停薪期间"]
FENCED = ["```json\n[]\n```", "```\n[]\n```", "[]", "  ```json\n{\"a\":1}\n```  ", "前言\n```json\n[1]\n```", "no fence"]


def _triple(rng, subj=None, obj=None, **kw) -> SVOTriple:
    return SVOTriple(subject=subj or rng.choice(SUBJ), verb=rng.choice(VERBS[:14]), object=obj or rng.choice(OBJ),
                     rel_type=rng.choice(sorted(SVO_REL_TYPES)), **kw)


def _source(rng, n=None) -> str:
    return "".join(rng.sample(SENT, n or rng.randint(2, 6)))


def _cfgs() -> list[KGConfig]:
    ext = RelTypeExtension(name="CUSTOM_REL", description="自訂關係型別的描述句")
    return [KGConfig(), KGConfig.model_validate({"domain": {"rel_type_extensions": [ext.model_dump()]}})]


# ── 案例 ──────────────────────────────────────────────────────────────


def run_all(ns) -> list[dict]:
    rng = random.Random(SEED)
    out: list[dict] = []

    def add(kind, args, res):
        out.append({"kind": kind, "args": jsonable(args), "res": res})

    for name in CONSTANT_NAMES:
        add("const:" + name, [], {"ok": jsonable(getattr(ns, name))})

    for raw in FENCED * 5:
        add("_strip_json_fence", [raw], call_sync(ns._strip_json_fence, raw))
    payloads = ['[{"subject":"a","verb":"b","object":"c"}]', '{"triples":[{"subject":"a"}]}', '{"data":[1,2]}', "not json",
                "```json\n[{\"x\":1}]\n```", "[]", "{}", '[{"subject":"勞工","verb":"給予","object":"婚假"}]']
    for raw in payloads * 5:
        add("_parse_triples_payload", [raw], call_sync(ns._parse_triples_payload, raw))
    for t in ["Local Business", "local_business", "PERSON", "person", "Organization", "", "  x  ", "概念", "LOCAL-BUSINESS", "a b c"] * 2:
        add("_normalize_type_key", [t], call_sync(ns._normalize_type_key, t))
    types = ["PERSON", "ORGANIZATION", "Person", "LocalBusiness", "local business", "LAW", "概念", "Legislation", "zzz-unknown",
             "", "GovernmentOrganization", "monetary amount", "MonetaryAmount", "Event", "place", "PLACE,PERSON", "組織"]
    for t in types * 5:
        add("resolve_entity_type", [t], call_sync(ns.resolve_entity_type, t))
    add("_load_extended_entity_type_lookup", [], {"ok": jsonable(ns._load_extended_entity_type_lookup())})
    for cfg in _cfgs() * 3:
        add("_effective_rel_types", [], call_sync(ns._effective_rel_types, cfg))
        add("_effective_rel_type_descriptions", [], call_sync(ns._effective_rel_type_descriptions, cfg))
    exts = [RelTypeExtension(name="X_REL", description="擴充型別描述")]
    for i in range(40):
        text = _source(rng)
        kw = {}
        if i % 3 == 1:
            kw["fewshots"] = ["範例一", "範例二"]
        if i % 3 == 2:
            kw["rel_type_extensions"] = exts
        add("_svo_prompt", [text, kw.keys()], call_sync(ns._svo_prompt, text, **kw))

    guard_cfgs = [GuardConfig(), GuardConfig(measure_units=("日", "月", "年")),
                  GuardConfig(scope_modifier_words=("特定", "其他")), GuardConfig(enum_closed_values=("甲", "乙"))]
    for g in guard_cfgs * 2:
        for fn in ("_build_measure_pattern", "_build_range_comparator_pattern", "_build_enum_guard_pattern",
                   "_build_scope_modifier_pattern"):
            add(fn, [], call_sync(getattr(ns, fn), g))
    for tokens in [("a", "b"), ("日", "月"), ("(", ")"), ()]:
        add("_regex_token_alternation", [tokens], call_sync(ns._regex_token_alternation, tokens))
    for name in ["特定行業", "其他事業", "勞工", "一般規定", "特定", "", "適用之其他行業"] * 6:
        add("_has_scope_modifier", [name], call_sync(ns._has_scope_modifier, name))
    quant_texts = ["八日", "三十日", "百分之六", "新臺幣二十萬元", "十四日", "至少二十分鐘", "二年內", "第一類事業", "工資", "五日前"]
    for _ in range(150):
        t = rng.choice(quant_texts) + rng.choice(["", "之勞工", "者"])
        src = _source(rng)
        add("_contains_ungrounded_quantity", [t, src], call_sync(ns._contains_ungrounded_quantity, t, src))
    fam = ns._LEAVE_TYPE_FAMILY
    for _ in range(80):
        t = rng.choice(["事假", "產假", "婚假期間", "病假", "公假", "勞工", "特別休假"]) + rng.choice(["", "工資"])
        src = _source(rng)
        add("_contains_ungrounded_family_term", [t, src], call_sync(ns._contains_ungrounded_family_term, t, src))
    for _ in range(20):
        term = rng.choice(fam)
        src = _source(rng)
        add("_rival_family_term", [term, src], call_sync(ns._rival_family_term, term, fam, src))
    for _ in range(40):
        s = _source(rng)
        add("_split_into_clauses", [s], call_sync(ns._split_into_clauses, s))
        add("_normalize_for_binding", [s], call_sync(ns._normalize_for_binding, s))
    for p in ["八日", "三十日", "百分之六", "二十分鐘", "新臺幣二十萬元", "一年", "五人", "abc", ""] * 3:
        add("_quantity_unit", [p], call_sync(ns._quantity_unit, p))
        clauses = rng.sample(SENT, 3)
        add("_rival_quantity", [p, clauses], call_sync(ns._rival_quantity, p, clauses))
    for _ in range(100):
        tr = _triple(rng)
        src = _source(rng)
        sents = rng.sample(SENT, rng.randint(2, 5)) if rng.random() < 0.7 else None
        add("_quantity_mis_bound_to_clause", [tr, src, sents], call_sync(ns._quantity_mis_bound_to_clause, tr, src, sents))
    risk_objs = ["具顯著風險者", "具中度風險者", "具低度風險者", "第一類事業", "低度風險"]
    for _ in range(60):
        tr = _triple(rng, subj=rng.choice(["第一類事業", "第二類事業", "第三類事業", "事業單位"]), obj=rng.choice(risk_objs))
        src = _source(rng)
        sents = rng.sample(SENT, rng.randint(2, 5)) if rng.random() < 0.7 else None
        add("_risk_category_misbound_to_clause", [tr, src, sents],
            call_sync(ns._risk_category_misbound_to_clause, tr, src, sents))
    for _ in range(80):
        trs = [_triple(rng) for _ in range(rng.randint(1, 5))]
        src = _source(rng)
        sents = rng.sample(SENT, rng.randint(2, 5)) if rng.random() < 0.6 else None
        add("_filter_ungrounded_quantity_triples", [trs, src, sents],
            call_async_free(ns._filter_ungrounded_quantity_triples, trs, src, sents))

    for s in SIMP * 4:
        add("_to_traditional", [s], call_sync(ns._to_traditional, s))
        add("_fix_known_simplified_compounds", [s], call_sync(ns._fix_known_simplified_compounds, s))
    charsets = [None, frozenset(), frozenset("雇托職經嬰"), frozenset("婚假八日勞工結者給予")]
    for s in SIMP * 6:
        cs = rng.choice(charsets)
        add("_to_traditional_selective", [s, cs], call_sync(ns._to_traditional_selective, s, cs))
    for _ in range(30):
        trs = [SVOTriple(subject=rng.choice(SIMP), verb=rng.choice(SIMP), object=rng.choice(SIMP)) for _ in range(rng.randint(1, 3))]
        cs = rng.choice(charsets)
        add("traditionalize_triples", [trs, cs], call_sync(ns.traditionalize_triples, trs, cs))
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        for name, content in [("A", "婚假八日勞工"), ("B", "雇主托育")]:
            (root / name).mkdir()
            (root / name / "original.md").write_text(content, encoding="utf-8")
        ns._kg_source_charset.cache_clear()
        add("_kg_source_charset", ["<tmp>"], call_sync(ns._kg_source_charset, str(root)))
        add("_kg_source_charset", ["<missing>"], call_sync(ns._kg_source_charset, str(root / "nope")))
        ns._kg_source_charset.cache_clear()
    add("_opencc_s2tw", [], {"ok": jsonable(type(ns._opencc_s2tw()).__name__)})

    # async：embedding 相關
    for i in range(40):
        emb = FakeEmbedding()
        verb = rng.choice(VERBS)
        descs = None if i % 4 else {"A": "甲描述", "B": "乙描述"}
        r = call_async(ns.classify_relation_by_embedding, verb, emb, descs)
        r["emb_calls"] = list(emb.calls)
        add("classify_relation_by_embedding", [verb, descs], r)
    for descs in [None, {"A": "甲描述"}, {"A": "甲描述"}]:
        emb = FakeEmbedding()
        r = call_async(ns._type_description_embeddings, emb, descs)
        r["emb_calls"] = len(emb.calls)
        add("_type_description_embeddings", [descs], r)

    # _reconcile_rel_type（含副作用序列）
    answer_cycle = ["ANSWER_BEST", "ANSWER_LLM", "皆非", "garbage", " REQUIRES ", ""]
    for i in range(150):
        emb = None if i % 15 == 14 else FakeEmbedding()
        verb = rng.choice(VERBS)
        llm_type = rng.choice(sorted(SVO_REL_TYPES))
        a = answer_cycle[i % len(answer_cycle)]
        if i % 17 == 16:
            a = ValueError("llm boom")
        llm = None if i % 13 == 12 else FakeLLM([a])
        kg = None if i % 3 == 0 else "kg-1"
        db = None if i % 4 == 0 else Path("cal.db")
        cfg = rng.choice(_cfgs()) if i % 2 else None
        # 決定答案字串需要 best_type：先以同一假 embedding 算出
        if isinstance(a, str) and a in ("ANSWER_BEST", "ANSWER_LLM") and emb is not None:
            best, _ = asyncio.run(ns.classify_relation_by_embedding(
                verb, FakeEmbedding(), descriptions=ns._effective_rel_type_descriptions(cfg or KGConfig())))
            llm = FakeLLM([best if a == "ANSWER_BEST" else llm_type])
        r = call_async(ns._reconcile_rel_type, verb, llm_type, embedding_provider=emb, llm_provider=llm,
                       kg_id=kg, calibration_db_path=db, cfg=cfg,
                       add_raises=(i % 29 == 28), log_raises=(i % 31 == 30))
        r["llm_prompts"] = list(llm.prompts) if llm else None
        add("_reconcile_rel_type", [verb, llm_type, kg, str(db)], r)

    # _find_uncovered_sentences
    for i in range(40):
        emb = FakeEmbedding()
        sents = rng.sample(SENT, rng.randint(2, 6))
        trs = [_triple(rng, subj=rng.choice(SUBJ), obj=rng.choice(OBJ)) for _ in range(rng.randint(0, 4))]
        thr = rng.choice([None, 0.2, 0.9])
        r = call_async(ns._find_uncovered_sentences, sents, trs, emb, threshold=thr, cfg=rng.choice([None, KGConfig()]))
        r["emb_calls"] = len(emb.calls)
        add("_find_uncovered_sentences", [sents, len(trs), thr], r)

    def llm_json_payload(rng):
        items = []
        for _ in range(rng.randint(0, 4)):
            it = {"subject": rng.choice(SUBJ), "verb": rng.choice(VERBS), "object": rng.choice(OBJ),
                  "rel_type": rng.choice(sorted(SVO_REL_TYPES) + ["NOT_A_TYPE", ""]),
                  "subject_type": rng.choice(["PERSON", "organization", "LocalBusiness", "", "zzz"]),
                  "object_type": rng.choice(["ORGANIZATION", "概念", "MonetaryAmount", ""])}
            if rng.random() < 0.1:
                it["subject"] = ["not", "a", "string"]
            if rng.random() < 0.1:
                it.pop("object")
            items.append(it)
        return json.dumps(items, ensure_ascii=False)

    for i in range(100):
        emb = None if i % 5 == 4 else FakeEmbedding()
        text = "" if i % 23 == 22 else _source(rng)
        payload = "not json" if i % 19 == 18 else llm_json_payload(rng)
        llm = None if i % 21 == 20 else FakeLLM(["皆非", "皆非", "皆非"], [payload, payload])
        if i % 27 == 26 and llm is not None:
            llm = FakeLLM([], [RuntimeError("json boom")])
        kg = "kg-1" if i % 2 else None
        db = Path("cal.db") if i % 2 else None
        r = call_async(ns.extract_svo_triples, text, llm, emb, cfg=rng.choice([None, KGConfig()]), kg_id=kg,
                       calibration_db_path=db)
        add("extract_svo_triples", [text[:30], i], r)

    for i in range(80):
        emb = None if i % 6 == 5 else FakeEmbedding()
        text = _source(rng)
        sents = [] if i % 9 == 8 else rng.sample(SENT, rng.randint(2, 5))
        p1, p2 = llm_json_payload(rng), llm_json_payload(rng)
        llm = FakeLLM(["皆非"] * 6, [p1, p2]) if i % 25 != 24 else None
        kg = "kg-1" if i % 2 else None
        db = Path("cal.db") if i % 2 else None
        r = call_async(ns.extract_svo_triples_with_completeness_check, text, sents, llm, emb,
                       cfg=rng.choice([None, KGConfig()]), kg_id=kg, calibration_db_path=db)
        add("extract_svo_triples_with_completeness_check", [text[:30], i], r)
    return out


def call_async_free(fn, *a):
    """同步函式但會寫 logger.warning 的情況：也記錄 logger。"""
    handler = LogCapture()
    log = logging.getLogger("services.svo_service")
    log.addHandler(handler)
    old = log.level
    log.setLevel(logging.DEBUG)
    try:
        res = call_sync(fn, *a)
    finally:
        log.removeHandler(handler)
        log.setLevel(old)
    res["logs"] = handler.records
    return res


def main() -> int:
    if "--write-golden" in sys.argv:
        from services import svo_service

        cases = run_all(svo_service)
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(cases, ensure_ascii=False, indent=0), encoding="utf-8")
        print(len(cases), "cases written to", GOLDEN)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
