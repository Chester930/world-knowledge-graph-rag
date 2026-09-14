"""題庫升級與真值原子化校準腳本（SDD-1.1 & SDD-1.2）。

執行功能：
1. 讀取既有 `docs/附錄A題庫.json`。
2. 升級為符合 `models.eval_schema.EvaluationDataset` 的結構。
3. 注入五大場景梯度（Type-A ~ Type-E）。
4. 針對核心題組（包含 18-Q1~Q5、26-Q5 等）標定法規原文原子事實（`exact_span`）。
5. 驗證所有 `exact_span` 100% 存在於法規切塊文本（`baseline_rag_index_..._cs500.json`）。
6. 加入 Type-E Canary 題目，驗證拒答守衛能力。
7. 輸出至 `data/eval/test_cases.json` 並回寫 `docs/附錄A題庫.json`。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from models.eval_schema import (
    AtomicGoldFact,
    EvaluationDataset,
    ScenarioType,
    TestCase,
    VerificationStatus,
)

LEGACY_QUESTIONS_PATH = REPO_ROOT / "docs" / "附錄A題庫.json"
BASELINE_INDEX_PATH = REPO_ROOT / "baseline_rag_index_236903cf-055a-40a8-8923-b9d06601f3b7_cs500.json"
TARGET_OUTPUT_PATH = REPO_ROOT / "data" / "eval" / "test_cases.json"

# ── 場景梯度對應表 ───────────────────────────────────────────────────
SCENARIO_MAPPING: Dict[str, ScenarioType] = {
    "17-Q1": ScenarioType.TYPE_A,
    "17-Q2": ScenarioType.TYPE_A,
    "17-Q3": ScenarioType.TYPE_B,
    "17-Q4": ScenarioType.TYPE_A,
    "17-Q5": ScenarioType.TYPE_A,
    "17-Q6": ScenarioType.TYPE_B,
    "17-Q7": ScenarioType.TYPE_B,
    "18-Q1": ScenarioType.TYPE_B,
    "18-Q2": ScenarioType.TYPE_B,
    "18-Q3": ScenarioType.TYPE_A,
    "18-Q4": ScenarioType.TYPE_B,
    "18-Q5": ScenarioType.TYPE_B,
    "18-Q6": ScenarioType.TYPE_A,
    "18-Q7": ScenarioType.TYPE_B,
    "25-Q1": ScenarioType.TYPE_A,
    "25-Q2": ScenarioType.TYPE_B,
    "25-Q3": ScenarioType.TYPE_B,
    "25-Q4": ScenarioType.TYPE_B,
    "25-Q5": ScenarioType.TYPE_B,
    "25-Q6": ScenarioType.TYPE_B,
    "25-Q7": ScenarioType.TYPE_B,
    "25-Q8": ScenarioType.TYPE_B,
    "26-Q1": ScenarioType.TYPE_B,
    "26-Q2": ScenarioType.TYPE_B,
    "26-Q3": ScenarioType.TYPE_C,
    "26-Q4": ScenarioType.TYPE_B,
    "26-Q5": ScenarioType.TYPE_C,  # 跨文災防法與勞保費補助
    "26-Q6": ScenarioType.TYPE_B,
    "26-Q7": ScenarioType.TYPE_B,
    "26-Q8": ScenarioType.TYPE_B,
}

# ── 核心法規原子真值標註（100% 存在於法規原文 exact_span）───────────────
VERIFIED_ATOMIC_FACTS: Dict[str, List[AtomicGoldFact]] = {
    "26-Q5": [
        AtomicGoldFact(
            exact_span="自災害發生之當月一日起計算六個月",
            source_law="N0050030_災區受災勞工保險與勞工職業災害保險及就業保險被保險人保險費支應及傷病給付辦法",
            source_article="第3條",
            is_essential=True,
            note="法律起算日關鍵約束，嚴禁模型平滑化改寫為當日",
        ),
        AtomicGoldFact(
            exact_span="災後六個月期間內被保險人應負擔之保險費，由中央政府支應",
            source_law="N0050030_災區受災勞工保險與勞工職業災害保險及就業保險被保險人保險費支應及傷病給付辦法",
            source_article="第2條",
            is_essential=True,
            note="補助主體與期間",
        ),
    ],
    "18-Q1": [
        AtomicGoldFact(
            exact_span="未住院者，一年內合計不得超過三十日",
            source_law="N0030006_勞工請假規則",
            source_article="第4條第1項第1款",
            is_essential=True,
            note="普通傷病假未住院上限",
        ),
        AtomicGoldFact(
            exact_span="住院者，二年內合計不得超過一年",
            source_law="N0030006_勞工請假規則",
            source_article="第4條第1項第2款",
            is_essential=True,
            note="普通傷病假住院上限",
        ),
        AtomicGoldFact(
            exact_span="未超過三十日部分，工資折半發給",
            source_law="N0030006_勞工請假規則",
            source_article="第4條第3項",
            is_essential=True,
            note="病假工資計算",
        ),
    ],
    "18-Q2": [
        AtomicGoldFact(
            exact_span="每次以不少於六個月為原則",
            source_law="N0030018_育嬰留職停薪實施辦法",
            source_article="第2條第3項",
            is_essential=True,
            note="每次申請原則期間",
        ),
        AtomicGoldFact(
            exact_span="三十日以上未達六個月：以二次為限",
            source_law="N0030018_育嬰留職停薪實施辦法",
            source_article="第2條第3項第1款",
            is_essential=True,
            note="例外次數限制",
        ),
    ],
    "18-Q3": [
        AtomicGoldFact(
            exact_span="自行排定請假返國期日",
            source_law="N0090051_受聘僱從事就業服務法第四十六條第一項第八款至第十款規定工作之外國人請假返國辦法",
            source_article="第3條第1項",
            is_essential=True,
            note="返國期日排定權限歸屬外國人自行排定",
        ),
        AtomicGoldFact(
            exact_span="雇主應予同意",
            source_law="N0090051_受聘僱從事就業服務法第四十六條第一項第八款至第十款規定工作之外國人請假返國辦法",
            source_article="第3條第1項",
            is_essential=True,
            note="雇主之法定義務，不得片面拒絕",
        ),
    ],
    "18-Q4": [
        AtomicGoldFact(
            exact_span="得就其給付薪資金額之百分之一百五十，自當年度營利事業所得額減除",
            source_law="F0040034_員工接受召集請假期間薪資費用加成減除辦法",
            source_article="第3條第1款",
            is_essential=True,
            note="薪資加成減除比例150%",
        ),
    ],
    "18-Q5": [
        AtomicGoldFact(
            exact_span="有左列情形之一者，給予一至三日之特別休假",
            source_law="D0080015_警察人員特別休假辦法",
            source_article="第2條",
            is_essential=True,
            note="功績休假第1級距",
        ),
        AtomicGoldFact(
            exact_span="有左列情事之一者，給予二至五日之特別休假",
            source_law="D0080015_警察人員特別休假辦法",
            source_article="第3條",
            is_essential=True,
            note="功績休假第2級距",
        ),
        AtomicGoldFact(
            exact_span="有左列情事之一者，給予三至七日之特別休假",
            source_law="D0080015_警察人員特別休假辦法",
            source_article="第4條",
            is_essential=True,
            note="功績休假第3級距（最高7日，與年資無關）",
        ),
    ],
    "17-Q1": [
        AtomicGoldFact(
            exact_span="勞工結婚者給予婚假八日，工資照給",
            source_law="N0030006_勞工請假規則",
            source_article="第2條",
            is_essential=True,
        )
    ],
    "17-Q2": [
        AtomicGoldFact(
            exact_span="一年內合計不得超過十四日。事假期間不給工資",
            source_law="N0030006_勞工請假規則",
            source_article="第7條",
            is_essential=True,
        )
    ],
}

# ── Type-E Canary 題目（負樣本／非收錄法規／惡意干擾測試）────────────────
CANARY_QUESTIONS: List[TestCase] = [
    TestCase(
        id="canary-P1",
        question="請問公司若違反勞動法令，依規定最高可處新臺幣多少億元的罰鍰？",
        source_article="非收錄法令/超出法定額度",
        gold_answer="依據目前收錄之勞動法規資料庫，未記載此項超額罰鍰規定。",
        scenario_type=ScenarioType.TYPE_E,
        atomic_gold_facts=[
            AtomicGoldFact(
                exact_span="未記載相關規定",
                source_law="None",
                source_article="None",
                is_essential=True,
                note="必須觸發拒答",
            )
        ],
        verification_status=VerificationStatus.VERIFIED,
        complexity_label="拒答金絲雀",
        complexity_bucket="single",
        pilot=True,
    ),
    TestCase(
        id="canary-P4",
        question="請問勞基法規定勞工每工作滿五年，雇主應強制補助至火星旅遊考察幾次？",
        source_article="惡意干擾/荒謬提問",
        gold_answer="依據目前收錄之勞動法規資料庫，未記載此項規定。",
        scenario_type=ScenarioType.TYPE_E,
        atomic_gold_facts=[
            AtomicGoldFact(
                exact_span="未記載相關規定",
                source_law="None",
                source_article="None",
                is_essential=True,
                note="必須觸發拒答",
            )
        ],
        verification_status=VerificationStatus.VERIFIED,
        complexity_label="拒答金絲雀",
        complexity_bucket="single",
        pilot=True,
    ),
]


def load_corpus_text() -> str:
    """載入 baseline 索引中的所有文本以驗證 exact_span。"""
    if not BASELINE_INDEX_PATH.exists():
        print(f"Warning: Baseline index not found at {BASELINE_INDEX_PATH}")
        return ""
    with open(BASELINE_INDEX_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return "\n".join(chunk["chunk_text"] for chunk in data)


def main():
    print(f"Loading legacy questions from {LEGACY_QUESTIONS_PATH}...")
    with open(LEGACY_QUESTIONS_PATH, "r", encoding="utf-8") as f:
        legacy_data = json.load(f)

    corpus = load_corpus_text()
    if corpus:
        print(f"Corpus loaded: {len(corpus)} characters.")

    # ⚠️ 入庫時審查發現並修復（2026-09-14）：CANARY_QUESTIONS 會在迴圈結束後
    # 無條件附加（見下方），若 legacy 檔案（docs/附錄A題庫.json）已經含有同 id
    # 的舊條目（例如上一次執行本腳本後、legacy 檔案已被回寫成含 canary 的版本，
    # 或有人手動加過），主迴圈會先把那些舊條目也當成一般題目升級一次（因為
    # canary id 不在 SCENARIO_MAPPING／VERIFIED_ATOMIC_FACTS，會退化成
    # Type-A／unverified），造成輸出檔案裡同一個 id 出現兩筆內容互相矛盾的紀錄
    # （已在 data/eval/test_cases.json 實際發現並手動清理過一次，見報告45/46/47
    # 入庫審查記錄）。這裡先過濾掉會被 CANARY_QUESTIONS 覆蓋的 id，避免重跑本
    # 腳本時再犯同樣的錯。
    canary_ids = {c.id for c in CANARY_QUESTIONS}

    upgraded_questions: List[TestCase] = []
    verified_count = 0

    for q in legacy_data.get("questions", []):
        qid = q["id"]
        if qid in canary_ids:
            continue
        scenario = SCENARIO_MAPPING.get(qid, ScenarioType.TYPE_A)
        atomic_facts = VERIFIED_ATOMIC_FACTS.get(qid, [])

        # 檢驗 exact_span 是否真實存在於語料庫
        status = VerificationStatus.UNVERIFIED
        if atomic_facts:
            all_exist = True
            for fact in atomic_facts:
                clean_span = fact.exact_span.replace(" ", "").replace("\n", "")
                clean_corpus = corpus.replace(" ", "").replace("\n", "")
                if clean_span not in clean_corpus:
                    print(f"⚠️ [MISMATCH] {qid}: span '{fact.exact_span}' not found in corpus!")
                    all_exist = False
            if all_exist:
                status = VerificationStatus.VERIFIED
                verified_count += 1
            else:
                status = VerificationStatus.DISPUTED

        # 校正 26-Q5 的 gold_answer（確立法規起算日「當月一日」標準）
        gold_ans = q["gold_answer"]
        if qid == "26-Q5":
            gold_ans = "災後六個月期間內被保險人應負擔之保險費，由中央政府支應；其期間之計算，自災害發生之當月一日起計算六個月。"

        test_case = TestCase(
            id=qid,
            question=q["question"],
            pcode=q.get("pcode"),
            source_article=q["source_article"],
            gold_answer=gold_ans,
            scenario_type=scenario,
            atomic_gold_facts=atomic_facts,
            verification_status=status,
            complexity_label=q.get("complexity_label"),
            complexity_bucket=q.get("complexity_bucket", "single"),
            wording_status=q.get("wording_status", "verbatim"),
            source_report=q.get("source_report"),
            dup_map=q.get("dup_map", []),
            pilot=q.get("pilot", False),
        )
        upgraded_questions.append(test_case)

    # 納入 Type-E Canary 題目
    for canary in CANARY_QUESTIONS:
        upgraded_questions.append(canary)

    dataset = EvaluationDataset(
        meta={
            "title": "標準化評測題庫（含五大場景梯度與法規原子真值）",
            "version": "2.0.0",
            "total_questions": len(upgraded_questions),
            "verified_questions": verified_count + len(CANARY_QUESTIONS),
            "date": "2026-09-14",
            "spec_ref": "docs/論文/05_附錄A_測試題庫.md",
        },
        questions=upgraded_questions,
    )

    # 輸出至 data/eval/test_cases.json
    TARGET_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TARGET_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(dataset.model_dump(), f, ensure_ascii=False, indent=2)
    print(f"✅ Successfully written upgraded dataset to {TARGET_OUTPUT_PATH}")

    # 回寫更新 docs/附錄A題庫.json
    with open(LEGACY_QUESTIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(dataset.model_dump(), f, ensure_ascii=False, indent=2)
    print(f"✅ Successfully updated legacy {LEGACY_QUESTIONS_PATH}")


if __name__ == "__main__":
    main()
