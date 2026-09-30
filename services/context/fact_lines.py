"""P2 第一、二刀自 ``routers.agent`` 抽出的事實行渲染純函式群。

本模組無 I/O，只依賴 ``re``、``core`` 與 ``models``，不依賴 ``routers``、
``services`` 或 ``repositories``。
"""

import re

from core.constants import ENTITY_TYPES
from models.knowledge_graph import SVOTriple


# 事實文字裡的型別標記——`（概念）` 或受控 ENTITY_TYPES 中的型別 token。
# 報告25 § 4 發現5：尚未回填的 KG／殘留資料仍可能帶進 prompt（甚至洩漏到
# 最終答案），這裡做一道輸出前的防禦性清除。只比對受控清單，不用任意大寫
# 英文字萬用正則，避免誤刪法規正文中的合法英文縮寫。清單型別同時涵蓋
# `（PERSON,PERSON）` 與裸 `PERSON`；「概念」只保留既有的全形括號格式。
_CONTROLLED_TYPE_TOKEN_PATTERN = "|".join(
    re.escape(token) for token in sorted(ENTITY_TYPES, key=len, reverse=True)
)
_CONTROLLED_TYPE_LIST_PATTERN = (
    rf"(?:{_CONTROLLED_TYPE_TOKEN_PATTERN})"
    rf"(?:\s*[,，]\s*(?:{_CONTROLLED_TYPE_TOKEN_PATTERN}))*"
)
# 報告67 T3 複驗（2026-09-22）：裸字分支原本只在結尾擋 `(?![A-Za-z0-9_])`，
# 沒有對稱的開頭 `(?<![A-Za-z0-9_])`——導致「XORGANIZATION」這類合法詞彙
# 尾端剛好是受控型別詞時，會被誤砍成「X」（已用真實案例重現並修正）。
# 括號版不需要這個左邊界，因為全形括號本身就是非 ASCII 字元、天然斷詞。
_TYPE_MARKER_RE = re.compile(
    rf"\s*(?:（(?:概念|{_CONTROLLED_TYPE_LIST_PATTERN})）|"
    rf"(?<![A-Za-z0-9_]){_CONTROLLED_TYPE_LIST_PATTERN})(?![A-Za-z0-9_])"
)


def strip_type_markers(text: str) -> str:
    return _TYPE_MARKER_RE.sub("", text).strip()


def is_contentful_line(line: str, subject: str | None) -> bool:
    """判斷一行事實文字是否「有內容」——用於取代舊版直接看結構化 `object`
    欄位是否為空的殘缺過濾。

    ⚠️ **報告25 § 4 發現6 追查（2026-09-02）**：舊版 `if not object: continue`
    會把 `X -[RELATED_TO]-> (懸空概念)` 這種**payload 在 verb、object 為空**的
    合法事實一起丟掉——Q8 三筆答案事實（「訓練時數 以三百小時為度」等）正是
    這個形狀，被靜默丟棄、從頭到尾沒進過 prompt。改為看**渲染後的文字**：
    只有「空字串」或「只有 subject、沒有動詞/受詞內容」才算殘缺。
    """
    core = strip_type_markers(line).lstrip("- ").strip()
    if not core:
        return False
    if subject and core == subject.strip():
        return False
    return True


def split_fact_lines(
    triples: list[SVOTriple], fact_results: list[dict], *, prefer_fact_on_collision: bool = False,
) -> tuple[list[str], list[str]]:
    """把 BFS 圖遍歷三元組與語意檢索 Fact 各自轉成 prompt 文字行，**分開回傳**
    `(bfs_lines, fact_lines)`，供 `_arrange_fact_lines()` 依來源分別處理——
    報告25 § 4 發現6：語意 Fact 經過 `vector_search_facts()` 的問題相關性
    KNN 檢索，BFS 三元組沒有任何問題相關性排序（`bfs_query()` 無 `LIMIT`／
    無評分），兩者不可等同看待、丟進同一個池子重排（會讓有相關性訊號的
    語意 Fact 被沒有訊號的 BFS 樣板列舉擠掉）。`_merge_fact_lines()` 保留
    為兩者相接的扁平版本，供接地核對等只需要「最終文字清單」的呼叫端。

    去重：優先按 `(subject, rel_type, object)`（三欄皆非空時，**預設 BFS 版
    優先**——純粹是先寫的迴圈先佔位，非經評測驗證的刻意設計）；object 為空
    時 `all(key)` 為 False、無法用 key 比對，改以**渲染後的行文字**比對涵蓋
    這個情況。

    ⚠️ **`prefer_fact_on_collision`（2026-09-22，報告65 §9/§10 pilot，預設
    `False`＝行為零變化）**：報告65 定向重抽驗證發現，BFS 版用邊上的
    `natural_text`（LLM 改寫），語意 Fact 版用 `_verbalize_fact()`
    （規範化實體名稱直接串接）——兩者的 `(subject, rel_type, object)` 結構
    可能完全一致，但顯示文字可能有用字漂移（例：`natural_text` 把「雇主」
    意譯成同義異體字「僱主」），甚至偶爾內容錯置（見報告65 §10 全KG掃描，
    7338 筆碰撞裡找到 `natural_text` 把兩筆不同事實顯示成同一句的真實案例）。
    目前預設 BFS 版優先，代表即使語意 Fact 排名最高、文字更貼近規範化實體
    名稱，去重後看到的仍是 BFS 的改寫版本，這個旗標開啟後改成 Fact 優先。

    ⚠️ **品質守門（2026-09-22，報告65 §10 全KG掃描發現後補）**：`fact_text`
    在 `verb` 為空字串時會渲染成「主詞　　受詞」（雙空格、缺動詞連接），
    比 `natural_text` 的通順句子明顯更差——掃描 7338 筆碰撞裡有 400 筆
    （5.5%）屬於這個情形。因此 `prefer_fact_on_collision=True` 時，**只有
    `verb` 非空的 Fact 才會佔用碰撞鍵**；`verb` 為空的 Fact 讓出鍵，改由
    BFS 的 `natural_text` 版本照舊顯示——不是「Fact 全面優先」，是「較完整
    的一方優先」。
    """
    seen_keys: set[tuple[str, str, str]] = set()
    seen_texts: set[str] = set()
    bfs_lines: list[str] = []
    fact_lines: list[str] = []

    def _add_bfs(t: SVOTriple) -> None:
        if not t.subject:
            return
        raw = t.natural_text if t.natural_text else f"{t.subject} {t.verb} {t.object}".rstrip()
        # 尚未跑過發現5 回填的 KG，其邊 `natural_text` 仍帶 `（型別）`——與
        # `fact_results` 側一致，輸出前一律過 `_strip_type_markers()`（順帶讓
        # 「帶標記的 BFS 版」與「乾淨的語意 Fact 版」文字一致、可被去重）。
        line = f"- {strip_type_markers(raw)}"
        if not is_contentful_line(line, t.subject) or line in seen_texts:
            return
        key = (t.subject, t.rel_type, t.object)
        if all(key) and key in seen_keys:
            return
        if all(key):
            seen_keys.add(key)
        seen_texts.add(line)
        bfs_lines.append(line)

    def _add_fact(f: dict, *, skip_if_empty_verb: bool = False) -> None:
        subject = f.get("subject")
        if subject is not None and subject.strip() == "":
            return
        # 報告65 §10 品質守門：verb 為空時 fact_text 是「主詞　　受詞」的
        # 劣質渲染，不佔碰撞鍵，讓 BFS 的 natural_text 版本有機會照舊顯示。
        if skip_if_empty_verb and not (f.get("verb") or "").strip():
            return
        key = (f.get("subject"), f.get("rel_type"), f.get("object"))
        if all(key) and key in seen_keys:
            return
        line = f"- {strip_type_markers(f['fact_text'])}"
        if not is_contentful_line(line, subject) or line in seen_texts:
            return
        if all(key):
            seen_keys.add(key)
        seen_texts.add(line)
        fact_lines.append(line)

    if prefer_fact_on_collision:
        for f in fact_results:
            _add_fact(f, skip_if_empty_verb=True)
        for t in triples:
            _add_bfs(t)
    else:
        for t in triples:
            _add_bfs(t)
        for f in fact_results:
            _add_fact(f)

    return bfs_lines, fact_lines


def merge_fact_lines(triples: list[SVOTriple], fact_results: list[dict]) -> list[str]:
    """`_split_fact_lines()` 的扁平版本（BFS 行在前、語意 Fact 行在後），供
    接地核對（`verify_fact_grounding()`）等只需要「本輪最終送進 prompt 的
    事實文字清單」、不關心來源分層的呼叫端使用。**排序／截斷／來源分層
    邏輯在 `_arrange_fact_lines()`，不在這裡。**"""
    bfs_lines, fact_lines = split_fact_lines(triples, fact_results)
    return bfs_lines + fact_lines


def litm_reorder(lines: list[str]) -> list[str]:
    """依 Jin et al. (2025, ICLR)《Long-Context LLMs Meet RAG》式1的 zigzag
    重排，把依相關性遞減排序的清單重新排列成「最相關的交替置於首尾」，讓
    最不相關的項目自然被擠到中段——對應 Liu et al. (2023/2024) *Lost in the
    Middle* 的 U 形長上下文效能曲線（相關資訊在開頭/結尾效能最好、中段
    顯著下降）。演算法邏輯與 LangChain `langchain_community.document_
    transformers.LongContextReorder` 的開源實作一致（見 `docs/參考文獻/
    19_生成端長清單事實遺漏與位置偏誤/README.md`，MIT授權，僅參考演算法
    邏輯、不依賴 LangChain 套件本身）。

    `lines` 必須已依相關性由高到低排序（呼叫端負責）。
    """
    reversed_lines = list(reversed(lines))
    reordered: list[str] = []
    for i, line in enumerate(reversed_lines):
        if i % 2 == 1:
            reordered.append(line)
        else:
            reordered.insert(0, line)
    return reordered
