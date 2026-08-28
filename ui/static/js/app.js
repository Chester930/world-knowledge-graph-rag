const kgListEl = document.getElementById("kg-list");
const chatMessagesEl = document.getElementById("chat-messages");
const chatFormEl = document.getElementById("chat-form");
const chatInputEl = document.getElementById("chat-input");
const stagingBtnEl = document.getElementById("staging-classify-btn");
const stagingResultsEl = document.getElementById("staging-results");
const expandRefreshBtnEl = document.getElementById("expand-refresh-btn");
const expandProposalsEl = document.getElementById("expand-proposals");

let activeKgId = null;

function appendMessage(role, content) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = content;
  chatMessagesEl.appendChild(div);
  chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
  return div;
}

async function loadKnowledgeGraphs() {
  try {
    const res = await fetch("/knowledge-graphs");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const kgs = await res.json();
    kgListEl.innerHTML = "";
    if (kgs.length === 0) {
      kgListEl.innerHTML = '<li class="muted">尚無知識圖譜</li>';
      return;
    }
    kgs.forEach((kg) => {
      const li = document.createElement("li");
      li.textContent = kg.name;
      li.onclick = () => {
        activeKgId = kg.id;
        document.getElementById("active-kg-label").textContent = kg.name;
      };
      kgListEl.appendChild(li);
    });
  } catch (err) {
    kgListEl.innerHTML = `<li class="muted">尚未實作（${err.message}）</li>`;
  }
}

async function sendChatMessage(question) {
  appendMessage("user", question);
  const assistantEl = appendMessage("assistant", "…");

  try {
    const res = await fetch("/agent/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, kg_id: activeKgId }),
    });

    if (!res.ok || !res.body) {
      assistantEl.className = "msg error";
      assistantEl.textContent = `請求失敗（HTTP ${res.status}）`;
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    // 2026-08-28：接地性核對升級為方案 B（限制性重新生成，見
    // routers/agent.py::chat() docstring）後，後端不再逐 token 即時串流
    // 第一版草稿——改成先送 `event: status`（generating/verifying/done）
    // 讓這裡顯示「正在核實中…」佔位，核對（必要時已修正）過的最終答案
    // 才會透過一次 `data:` 事件送達，避免使用者看到未核對過的內容。
    assistantEl.textContent = "正在思考中…";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const events = buffer.split("\n\n");
      buffer = events.pop();
      for (const evt of events) {
        const lines = evt.split("\n");
        const eventLine = lines.find((l) => l.startsWith("event:"));
        const dataLine = lines.find((l) => l.startsWith("data:"));
        if (!dataLine) continue;
        const eventName = eventLine ? eventLine.slice(6).trim() : "message";
        let payload;
        try {
          payload = JSON.parse(dataLine.slice(5).trim());
        } catch {
          continue; // 忽略非 JSON 事件
        }

        if (eventName === "status") {
          if (payload.phase === "generating") assistantEl.textContent = "正在思考中…";
          else if (payload.phase === "verifying") assistantEl.textContent = "正在核實答案中…";
          else if (payload.phase === "done" && payload.regenerated) {
            assistantEl.textContent += "\n\n（部分內容經核對後已自動修正）";
          }
        } else if (eventName === "error") {
          assistantEl.className = "msg error";
          assistantEl.textContent = payload.message ?? "發生錯誤";
        } else if (payload.token !== undefined) {
          // 最終、已核對過的答案一次送達，直接取代佔位文字。
          assistantEl.textContent = payload.token;
        }
      }
    }
  } catch (err) {
    assistantEl.className = "msg error";
    assistantEl.textContent = `連線錯誤：${err.message}`;
  }
}

async function classifyStaging() {
  stagingResultsEl.innerHTML = '<li class="muted">分析中…</li>';
  try {
    const res = await fetch("/staging/classify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ threshold: 0.3, auto_assign: false }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const results = await res.json();
    stagingResultsEl.innerHTML = "";
    results.forEach((r) => {
      const li = document.createElement("li");
      li.textContent = `${r.filename} → ${r.matched_kg_name ?? "未分類"}`;
      stagingResultsEl.appendChild(li);
    });
  } catch (err) {
    stagingResultsEl.innerHTML = `<li class="muted">尚未實作（${err.message}）</li>`;
  }
}

async function loadExpandProposals() {
  expandProposalsEl.innerHTML = '<li class="muted">載入中…</li>';
  try {
    const res = await fetch("/expand/proposals");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const proposals = await res.json();
    expandProposalsEl.innerHTML = "";
    if (proposals.length === 0) {
      expandProposalsEl.innerHTML = '<li class="muted">目前沒有待審核提案</li>';
      return;
    }
    proposals.forEach((p) => {
      const li = document.createElement("li");
      li.className = "expand-proposal";

      const summary = document.createElement("div");
      summary.className = "expand-proposal-summary";
      const reuseTag = p.reused_from_registry ? "（沿用既有型別）" : "（全新型別）";
      summary.textContent = `${p.suggested_type_name}${reuseTag}：${p.suggested_description}`;
      li.appendChild(summary);

      const verbs = document.createElement("div");
      verbs.className = "expand-proposal-verbs muted";
      verbs.textContent = `候選動詞：${p.member_verbs.join("、")}`;
      li.appendChild(verbs);

      const actions = document.createElement("div");
      actions.className = "expand-proposal-actions";
      const approveBtn = document.createElement("button");
      approveBtn.type = "button";
      approveBtn.textContent = "核准";
      approveBtn.onclick = () => resolveExpandProposal(p.id, "approved");
      const rejectBtn = document.createElement("button");
      rejectBtn.type = "button";
      rejectBtn.className = "reject";
      rejectBtn.textContent = "駁回";
      rejectBtn.onclick = () => resolveExpandProposal(p.id, "rejected");
      actions.appendChild(approveBtn);
      actions.appendChild(rejectBtn);
      li.appendChild(actions);

      expandProposalsEl.appendChild(li);
    });
  } catch (err) {
    expandProposalsEl.innerHTML = `<li class="muted">尚未實作（${err.message}）</li>`;
  }
}

async function resolveExpandProposal(proposalId, decision) {
  try {
    const res = await fetch(`/expand/proposals/${proposalId}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    await loadExpandProposals();
  } catch (err) {
    expandProposalsEl.innerHTML = `<li class="muted">審核失敗（${err.message}）</li>`;
  }
}

chatFormEl.addEventListener("submit", (e) => {
  e.preventDefault();
  const question = chatInputEl.value.trim();
  if (!question) return;
  chatInputEl.value = "";
  sendChatMessage(question);
});

stagingBtnEl.addEventListener("click", classifyStaging);
expandRefreshBtnEl.addEventListener("click", loadExpandProposals);

loadKnowledgeGraphs();
