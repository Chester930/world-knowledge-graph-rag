# 30_生成端精確度流失與引用幻覺

對應 `docs/報告/42_全量重抽三階段方法比較與報告39七路評分報告.md` §6 結論 4／5：
- **發現 4**：K／K-2b 在 26-Q5「起算日」子題 6 次執行**全部**把 Gold 的「自災害發生之當月一日起算」簡化改寫成「當日／當天起算」——事實清單確實含正確的「自災害發生之當月一日起計算六個月」（facts=1、triples=1），問題不在檢索缺失，而在生成階段把精確用詞「改寫掉」了。
- **發現 5**：K-2b 出現兩起「引用幻覺」——18-Q4 run1 把 150% 先寫成「百分之二百」才在括號訂正、18-Q5 run3 捏造了辦法實際不存在的條號（辦法僅 §2–§4，run3 卻引用「第五條／第八條／第十條／第十一條／第十二條／第十三條」）。

這兩個現象都屬於「生成端在**正確證據已被檢索到**的前提下，仍產生失真輸出」——與 `docs/參考文獻/18_抽取數值忠實性核對/`（**抽取端**數值誤綁定，不同層級）、`docs/參考文獻/19_生成端長清單事實遺漏與位置偏誤/`（事實**被漏引**，本案例是**被引用但改寫失真**，不同症狀）、`docs/參考文獻/22_生成端過度保守與選擇性拒答/`（事實在場卻拒答，本案例是**答了但答錯精確度／捏造引用**，方向相反）都不同，故另立新資料夾。

## 內容清單

| 檔案 | 文獻 | 來源 | 狀態 |
|---|---|---|---|
| `maynez-et-al-2020-faithfulness-factuality.pdf` | Maynez, Narayan, Bohnet & McDonald (2020), *On Faithfulness and Factuality in Abstractive Summarization*，ACL 2020（Google Research） | [arXiv:2005.00661](https://arxiv.org/abs/2005.00661)；[ACL Anthology 2020.acl-main.173](https://aclanthology.org/2020.acl-main.173/) | ✅ 已下載全文（14 頁）並全文搜尋驗證核心定義（見下） |
| `dahl-et-al-2024-large-legal-fictions.pdf` | Dahl, Magesh, Suzgun & Ho (2024), *Large Legal Fictions: Profiling Legal Hallucinations in Large Language Models*，Journal of Legal Analysis 16(1):64-93（Stanford RegLab） | [arXiv:2401.01301](https://arxiv.org/abs/2401.01301)；DOI [10.1093/jla/laae003](https://doi.org/10.1093/jla/laae003)；[GitHub reglab/legal_hallucinations](https://github.com/reglab/legal_hallucinations) | ✅ 已下載全文（80 頁，含附錄）並全文搜尋驗證核心宣稱（見下） |

## 各文獻在本設計中的角色

### 1. Maynez et al. (2020) —— 「intrinsic hallucination」框架，直接對應發現 4

**全文搜尋驗證**（非僅摘要）：論文明確定義兩種不忠實生成：
> "models hallucinate by manipulating the information present in the input document (**intrinsic hallucinations**) or by adding information not directly inferable from the input document (**extrinsic hallucinations**)"

發現 4 的「當月一日」→「當日」正是教科書等級的 **intrinsic hallucination**：模型讀到了正確的來源資訊（"manipulating the information present"），卻在生成時扭曲了其中的精確度，而非憑空捏造不存在的資訊（那會是 extrinsic）。論文另一發現——「intrinsic + extrinsic hallucination 在單句摘要中發生率合計超過 70%」——也提醒這類失真在生成任務中**普遍存在**，不是本專案獨有的怪異行為。

**誠實侷限**（依本資料夾慣例全文查證後如實記錄）：論文的實驗場景是新聞摘要（XSum），不是法規問答；也不處理「數字/日期精確度」這個子類別，是概括性的忠實度框架，不是針對數值型 unfaithfulness 的專門研究。本專案採用的是其**分類框架**（intrinsic vs extrinsic），不是其量化方法或資料集。

### 2. Dahl et al. (2024) —— 法律引用幻覺的實證基準，對應發現 5

**全文搜尋驗證**：論文對 GPT-4／GPT-3.5／PaLM 2／Llama 2 做「詢問聯邦法院案例的可驗證細節」測試，量到幻覈率 **58%（GPT-4）～88%（Llama 2）**，並提出「a typology of legal hallucinations to guide future research」。

**誠實侷限**：這篇的研究對象是**美國案例法（case law）引用**（案號、法院、判決細節），不是本專案的**台灣法規條號**；且該論文測的是模型的**參數化知識**（parametric knowledge，未接 RAG），不是像本專案這種「有檢索但引用細節仍捏造」的 RAG 情境。**不能當作本專案缺陷的直接方法論來源**，只能作為「LLM 對法律類精確引用細節的幻覺傾向是已有大規模實證基準的已知現象」的**佐證**——降低了「這是本專案怪異 bug」的疑慮，提高了「這是需要專門機制處理的通用問題」的確信度。

## 對應解法建議（供後續設計參考，非本資料夾範圍）

1. **發現 4（起算日精確度流失）**：現有 `verify_fact_grounding()`／`_grounding_prompt()`（`docs/參考文獻/22`）核對的是「主張是否被事實支持」，**沒有核對「數值/日期用詞是否被改寫」**。可考慮在接地核對規則新增一條：若回答中出現日期/期間相關表述，須與事實清單原文逐字（或正規化後）比對，不接受「精簡改寫」。這比照 `docs/參考文獻/18` 抽取端已有的「數值忠實性核對」精神，但要做在**生成端輸出**上，是新的檢查點，非既有機制的自然延伸。
2. **發現 5（引用幻覺）**：`verify_fact_grounding()` 目前只驗證事實/數值，未驗證**引用的法條號本身**是否存在於檢索到的 `LawArticle` 節點。可考慮新增一條規則：回答中若出現「第 X 條」字樣，須比對是否為本次檢索範圍內真實存在的條號，不存在則視為未接地。
3. 兩者都可以先用 `docs/參考文獻/24`（`_RANGE_COMPARATOR_PATTERN` 等既有規則式守衛）的「正規表達式抓取 + 確定性比對」模式實作，不需要額外的 LLM 判斷，成本低、可重現性高，延續本專案「先規則式、失敗才上 LLM」的既有工程慣例（見 `docs/參考文獻/18`／`24`）。
