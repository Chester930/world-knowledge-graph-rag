"""P2 第一刀自 ``routers.agent`` 抽出的事實行渲染純函式群。

本模組無 I/O，不依賴 ``routers`` 或 ``services`` 的其他模組。
"""

import re

from core.constants import ENTITY_TYPES


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
