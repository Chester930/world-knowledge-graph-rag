"""N4 的選擇性轉繁（報告160 U1 自 ``services.svo_service`` 搬入，行為不變；含被維護函式與 ``routers.agent`` 共用者）。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from models.knowledge_graph import SVOTriple

@lru_cache(maxsize=1)
def _opencc_s2tw():
    """OpenCC 簡→繁（臺灣標準字）轉換器，惰性初始化。用 `s2tw`（字元級）而非
    `s2twp`（含詞彙轉換）——法規語料要的是字形正規化（台→臺、内→內、
    经→經），不希望詞彙層被改（如「软件」→「軟體」可能動到法律用語）。"""
    from opencc import OpenCC

    return OpenCC("s2tw")


def _to_traditional(text: str) -> str:
    """把字串正規化成臺灣標準繁體字。已是繁體時 OpenCC 近乎 identity。
    報告25 § 4 發現4：`qwen2.5:7b` 的自然語言化改寫偶爾漏簡體
    （`补助经费额度`／`训练`／`经费`），在既有 prompt「繁體中文」指示之外
    再加一道字元級保險。

    ⚠️ **會過度轉換**：OpenCC 把 `雇→僱`、`托→託`、`里→裡` 也當簡→繁字元
    映射，但這些字在臺灣法規原文有其正當用法（勞基法用「雇主」不用「僱主」、
    育嬰留停辦法原文是「停托」不是「停託」）。用於**內部比對**（如
    `_normalize_for_binding()` 兩邊都轉、過度轉換相互抵銷）沒問題；用於
    **寫回資料**（Entity 名稱／`fact_text`）時應改用
    `_to_traditional_selective()`，以來源語料實際用字為白名單。"""
    return _opencc_s2tw().convert(text)


def _to_traditional_selective(text: str, source_charset: frozenset[str] | None) -> str:
    """逐字選擇性簡→繁（報告25 §4 發現4，使用者 2026-09-03 選定「來源語料
    當白名單」）：只轉「OpenCC 會改、且該字不出現在這個 KG 的繁體來源文件
    裡」的字。`職`／`經`／`嬰`（來源 0 次）會轉；`雇`／`托`（來源實際在用）
    保留原字。`source_charset` 為 `None` 時退回 `_to_traditional()`（全轉，
    無來源可對照——優雅降級，行為等同舊版）。"""
    if source_charset is None:
        return _to_traditional(text)
    out = []
    for ch in text:
        tw = _opencc_s2tw().convert(ch)
        out.append(tw if (tw != ch and ch not in source_charset) else ch)
    return "".join(out)


@lru_cache(maxsize=8)
def _kg_source_charset(kg_folder: str) -> frozenset[str]:
    """蒐集這個 KG 所有繁體來源文件（`workspace/<kg>/<doc>/original.md`）出現
    過的字元集合，供 `_to_traditional_selective()` 當「這些字是合法繁體用字，
    不要動」的白名單。找不到任何來源檔時回傳空集合（等於全轉）。"""
    from pathlib import Path

    chars: set[str] = set()
    root = Path(kg_folder)
    if not root.exists():
        return frozenset()
    for src in root.glob("*/original.md"):
        try:
            chars.update(src.read_text(encoding="utf-8"))
        except OSError:
            continue
    return frozenset(chars)


#: 報告65 §6/§7 定向重抽驗證發現（2026-09-22）：`_to_traditional_selective()`
#: 是逐字比對白名單，遇到「單字本身是這個KG來源語料裡合法的繁體字、但用在
#: 特定詞組裡卻是簡體殘留」時會結構性失效——例如「准」在「核准」／「批准」
#: 是合法繁體用字，白名單因此保留它，但「准用」本應是「準用」，逐字比對
#: 抓不出「同一個字在這個詞組裡用錯」。這不是白名單邏輯寫錯，是逐字比對
#: 這個方法本身的粒度侷限，需要逐詞比對已知易錯詞組來補救。清單只收錄
#: 真實觀察到、且已核對過另一支語料的案例，不可臆測新增。
_KNOWN_SIMPLIFIED_COMPOUNDS: dict[str, str] = {
    # 報告65定向重抽驗證，57-AGGR19（N0050031 c85）真實案例。
    "准用": "準用",
    "基准法": "基準法",
}


def _fix_known_simplified_compounds(text: str) -> str:
    """逐字白名單處理不了的已知簡體殘留詞組，做逐詞取代補救（見上方常數
    docstring）。在 `_to_traditional_selective()` 之後呼叫，不取代它。"""
    for bad, good in _KNOWN_SIMPLIFIED_COMPOUNDS.items():
        text = text.replace(bad, good)
    return text


def traditionalize_triples(
    triples: list[SVOTriple], source_charset: frozenset[str] | None,
) -> list[SVOTriple]:
    """對一批三元組的 subject／verb／object 就地套用 `_to_traditional_selective()`
    ——抽取端修正 `qwen2.5:7b` 偶發輸出簡體字的失效（報告25 §4 發現4）。
    在 `extraction_worker._process_one()` merge 前呼叫；`source_charset` 由
    `_kg_source_charset(kg_folder)` 提供。逐字轉換後再補一次
    `_fix_known_simplified_compounds()`（報告65 §6/§7），涵蓋逐字白名單
    抓不到的已知易錯詞組。"""
    for t in triples:
        t.subject = _fix_known_simplified_compounds(_to_traditional_selective(t.subject, source_charset))
        t.verb = _fix_known_simplified_compounds(_to_traditional_selective(t.verb, source_charset))
        t.object = _fix_known_simplified_compounds(_to_traditional_selective(t.object, source_charset))
    return triples
