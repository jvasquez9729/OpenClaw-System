(() => {
  const routes = ["home", "chat", "stage", "gallery", "missions", "agents", "events", "analytics", "settings"];

  const apiBaseInput = document.getElementById("apiBase");
  const saveApiBtn = document.getElementById("saveApi");
  const apiStatus = document.getElementById("apiStatus");
  const pageTitle = document.getElementById("pageTitle");
  const pageSub = document.getElementById("pageSub");
  const themeToggleBtn = document.getElementById("themeToggle");
  const navLinks = [...document.querySelectorAll(".nav a[data-route]")];

  const workingCountEl = document.getElementById("workingCount");
  const agentsBadgeEl = document.getElementById("agentsBadge");
  const badgeBar = document.getElementById("badgeBar");
  const kanbanEl = document.getElementById("kanban");
  const eventsLogEl = document.getElementById("eventsLog");

  const kpiEventsEl = document.getElementById("kpiEvents");
  const kpiMemoriesEl = document.getElementById("kpiMemories");
  const kpiActiveEl = document.getElementById("kpiActive");
  const kpiBudgetEl = document.getElementById("kpiBudget");

  const settingsApiBase = document.getElementById("settingsApiBase");
  const settingsPollMs = document.getElementById("settingsPollMs");
  const saveSettings = document.getElementById("saveSettings");
  const conversationListEl = document.getElementById("conversationList");
  const chatMessagesEl = document.getElementById("chatMessages");
  const chatThreadTitleEl = document.getElementById("chatThreadTitle");
  const chatThreadSubEl = document.getElementById("chatThreadSub");
  const chatInputEl = document.getElementById("chatInput");
  const chatSendBtn = document.getElementById("chatSend");

  const trackExecutionIdInput = document.getElementById("trackExecutionId");
  const addTrackExecutionBtn = document.getElementById("addTrackExecution");
  const clearTrackExecutionsBtn = document.getElementById("clearTrackExecutions");

  const officeCanvas = document.getElementById("office");
  const AGENT_META = {
    chief_of_staff: { emoji: "🧠", color: "#ff7d5f", label: "Chief of Staff" },
    developer: { emoji: "🛠️", color: "#3cc9ff", label: "Developer" },
    code_reviewer: { emoji: "🧪", color: "#9cfa6b", label: "Code Reviewer" },
    security_agent: { emoji: "🛡️", color: "#ffc857", label: "Security Agent" },
    financial_analyst: { emoji: "💸", color: "#c59dff", label: "Financial Analyst" },
    financial_parser: { emoji: "📊", color: "#49e1b8", label: "Financial Parser" },
    fullstack_builder: { emoji: "🛠️", color: "#3cc9ff", label: "Fullstack Builder" },
    security_auditor: { emoji: "🛡️", color: "#ffc857", label: "Security Auditor" },
    finance_specialist: { emoji: "💸", color: "#c59dff", label: "Finance Specialist" },
    devops_engineer: { emoji: "☁️", color: "#49e1b8", label: "DevOps Engineer" },
    system: { emoji: "📡", color: "#91a0b8", label: "System" },
    operator: { emoji: "🧑‍🚀", color: "#ffb45e", label: "Operator" },
  };

  const state = {
    base: localStorage.getItem("apiBase") || apiBaseInput.value || "http://127.0.0.1:8001",
    pollMs: Number(localStorage.getItem("pollMs") || "1000"),
    online: false,
    agents: [],
    permissionRecent: [],
    permissionStats: { active_tokens: 0 },
    executions: [],
    kpiPrev: { events: 0, memories: 0, active: 0, budget: 0 },
    pollTimer: null,
    phaserGame: null,
    metrics: {},
    theme: localStorage.getItem("themeMode") || "dark",
    selectedConversation: localStorage.getItem("selectedConversation") || "chief_of_staff",
    localMessages: {},
    chatHistory: {},
    chatAgents: [],
    trackedExecutionIds: (() => { try { const raw = localStorage.getItem("trackedExecutionIds"); const arr = raw ? JSON.parse(raw) : []; return Array.isArray(arr) ? [...new Set(arr.map((x) => String(x || "").trim()).filter(Boolean))] : []; } catch { return []; } })(),
    chatPollMs: 3000,
    chatPollTimer: null,
    apiCaps: { permissionStats: true, agentsState: true, permissionRecent: true, executions: true, runtimeStatus: false, metrics: false, runtimeApprove: false, runtimeReject: false, runtimeChat: true, runtimeChatHistory: true, runtimeChatAgents: true },
  };

  apiBaseInput.value = state.base;
  if (settingsApiBase) settingsApiBase.value = state.base;
  if (settingsPollMs) settingsPollMs.value = String(state.pollMs);
  applyTheme(state.theme);

  window.agentState = { agents: [], stats: {} };

  function esc(value) {
    return String(value).replace(/[&<>"']/g, (m) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "\"": "&quot;",
      "'": "&#39;",
    }[m]));
  }

  function fmtTime(value) {
    if (!value) return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleTimeString();
  }

  function getAgentMeta(agentId) {
    const key = String(agentId || "system");
    return AGENT_META[key] || { emoji: "🤖", color: "#8fb0ff", label: key.replace(/_/g, " ") };
  }

  function applyTheme(theme) {
    const mode = theme === "light" ? "light" : "dark";
    state.theme = mode;
    document.body.classList.toggle("light-theme", mode === "light");
    localStorage.setItem("themeMode", mode);
    if (themeToggleBtn) themeToggleBtn.textContent = mode === "light" ? "🌙" : "🌗";
  }

  function setOnline(ok) {
    state.online = ok;
    apiStatus.textContent = ok ? "online" : "offline";
    apiStatus.className = "badge " + (ok ? "ok" : "bad");
  }

  function api(path) {
    return `${state.base.replace(/\/$/, "")}${path}`;
  }

  async function fetchJson(url, opts = {}) {
    const response = await fetch(url, {
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    if (!response.ok) {
      const txt = await response.text().catch(() => "");
      throw new Error(`${response.status} ${txt}`.trim());
    }
    return response.json();
  }


  async function fetchText(url) {
    const response = await fetch(url);
    if (!response.ok) {
      const txt = await response.text().catch(() => "");
      throw new Error(`${response.status} ${txt}`.trim());
    }
    return response.text();
  }

  async function fetchChatAgents() {
    if (!state.apiCaps.runtimeChatAgents) return;
    try {
      const response = await fetchJson(api("/runtime/chat/agents"));
      state.chatAgents = Array.isArray(response?.items) ? response.items : [];
    } catch (err) {
      if (String(err?.message || "").startsWith("404")) {
        state.apiCaps.runtimeChatAgents = false;
        state.apiCaps.runtimeChat = false;
      } else {
        console.error(err);
      }
      state.chatAgents = [];
    }
  }

  async function fetchChatHistory(agentId, limit = 50) {
    const id = String(agentId || "").trim();
    if (!id || !state.apiCaps.runtimeChatHistory) return;
    try {
      const response = await fetchJson(api(`/runtime/chat/history/${encodeURIComponent(id)}?limit=${Number(limit) || 50}`));
      state.chatHistory[id] = Array.isArray(response?.items) ? response.items : [];
    } catch (err) {
      if (String(err?.message || "").startsWith("404")) {
        state.apiCaps.runtimeChatHistory = false;
        state.apiCaps.runtimeChat = false;
      } else {
        console.error(err);
      }
      state.chatHistory[id] = [];
    }
  }

  async function refreshChatData(agentId = state.selectedConversation) {
    if (!state.apiCaps.runtimeChat) return;
    const id = String(agentId || "chief_of_staff");
    await Promise.all([
      fetchChatAgents(),
      fetchChatHistory(id, 50),
    ]);
  }

  function addTrackedExecutionId(id) {
    const value = String(id || "").trim();
    if (!value) return false;
    if (!state.trackedExecutionIds.includes(value)) {
      state.trackedExecutionIds.push(value);
      localStorage.setItem("trackedExecutionIds", JSON.stringify(state.trackedExecutionIds));
    }
    return true;
  }

  function parseOpenApiCaps(openapi) {
    const paths = openapi?.paths || {};
    state.apiCaps.runtimeStatus = Boolean(paths["/runtime/status/{execution_id}"]?.get);
    state.apiCaps.metrics = Boolean(paths["/metrics"]?.get);
    state.apiCaps.runtimeApprove = Boolean(paths["/runtime/approve"]?.post);
    state.apiCaps.runtimeReject = Boolean(paths["/runtime/reject"]?.post);
    state.apiCaps.runtimeChat = Boolean(paths["/runtime/chat"]?.post);
    state.apiCaps.runtimeChatHistory = Boolean(paths["/runtime/chat/history/{agent_id}"]?.get);
    state.apiCaps.runtimeChatAgents = Boolean(paths["/runtime/chat/agents"]?.get);
  }

  function parsePromMetrics(text) {
    const out = {};
    const lines = String(text || "").split(/\r?\n/);
    const re = /^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{([^}]*)\})?\s+([-+]?(?:\d+\.?\d*|\d*\.\d+)(?:[eE][-+]?\d+)?)$/;
    const labelRe = /(\w+)="((?:\\"|[^"])*)"/g;

    for (const line of lines) {
      if (!line || line.startsWith("#")) continue;
      const m = line.match(re);
      if (!m) continue;
      const metric = m[1];
      const labelsRaw = m[2] || "";
      const labels = {};
      let lm;
      while ((lm = labelRe.exec(labelsRaw)) !== null) labels[lm[1]] = lm[2].replace(/\\"/g, '"');
      const value = Number(m[3]);
      if (!Number.isFinite(value)) continue;
      if (!out[metric]) out[metric] = [];
      out[metric].push({ labels, value });
    }

    return out;
  }

  function metricSum(name, pred = null) {
    return (state.metrics[name] || [])
      .filter((s) => (pred ? pred(s.labels, s.value) : true))
      .reduce((a, s) => a + Number(s.value || 0), 0);
  }

  function normalizeStatus(raw) {
    const s = String(raw || "").toUpperCase();
    if (!s) return "PROPOSED";
    if (s.includes("HITL") || s.includes("WAIT")) return "HITL_WAIT";
    if (s.includes("RUN") || s === "IN_PROGRESS") return "RUNNING";
    if (s.includes("REJECT")) return "REJECTED";
    if (s.includes("APPROV")) return "APPROVED";
    if (s.includes("DONE") || s.includes("SUCCESS") || s.includes("COMPLETE")) return "DONE";
    if (s.includes("FAIL") || s.includes("ERROR")) return "FAILED";
    return s;
  }

  async function refreshTrackedExecutions() {
    const ids = state.trackedExecutionIds.slice(0, 200);
    if (!state.apiCaps.runtimeStatus || !ids.length) return;

    const list = await Promise.all(ids.map(async (id) => {
      try {
        const x = await fetchJson(api(`/runtime/status/${encodeURIComponent(id)}`));
        const data = x?.item || x?.execution || x || {};
        const status = normalizeStatus(data.status || data.state || data.result || data.decision);
        return {
          execution_id: id,
          status,
          state: status,
          agent_id: data.agent_id || data.agentId || "chief_of_staff",
          title: data.title || data.task || "Execution",
          description: data.reason || data.summary || data.description || "",
          updated_at: data.updated_at || data.timestamp || data.created_at || new Date().toISOString(),
          cost_usd: Number(data.cost_usd || data.cost?.usd || 0),
        };
      } catch {
        return null;
      }
    }));

    state.executions = list.filter(Boolean);
  }
  function animateCount(el, from, to, formatter = (n) => String(Math.round(n))) {
    if (!el) return;
    const start = performance.now();
    const duration = 500;

    function tick(now) {
      const p = Math.min(1, (now - start) / duration);
      const value = from + (to - from) * p;
      el.textContent = formatter(value);
      if (p < 1) requestAnimationFrame(tick);
    }

    requestAnimationFrame(tick);
  }

  function renderHomeKpis() {
    const events = Number(state.permissionStats.active_tokens || Math.round(metricSum("tokens_total", (labels) => labels.direction === "in")) || 0);
    const memories = Number(state.agents.length || 0);
    const active = Number(state.agents.filter((a) => String(a.state || "").toLowerCase() === "working").length);
    const budget = metricSum("cost_usd_total") || state.agents.reduce((sum, a) => sum + Number(a.cost_usd || 0), 0);

    animateCount(kpiEventsEl, state.kpiPrev.events, events);
    animateCount(kpiMemoriesEl, state.kpiPrev.memories, memories);
    animateCount(kpiActiveEl, state.kpiPrev.active, active);
    animateCount(kpiBudgetEl, state.kpiPrev.budget, budget, (n) => `$${n.toFixed(2)}`);

    state.kpiPrev = { events, memories, active, budget };
  }

  function renderBadges() {
    if (!badgeBar) return;
    badgeBar.innerHTML = state.agents.map((a) => {
      const status = String(a.state || "idle").toLowerCase();
      const cls = status === "working" ? "badge ok" : (status.includes("hitl") ? "badge warn" : "badge neutral");
      const meta = getAgentMeta(a.agent_id);
      return `
        <span class="${cls}">
          <span class="avatar" style="background:${esc(meta.color)}">${esc(meta.emoji)}</span>
          ${esc(meta.label)}
          <span class="muted">${esc(status)}</span>
        </span>
      `;
    }).join("");
  }

  function mapMissionState(item) {
    const status = normalizeStatus(item.status || item.state || "");
    if (status === "DONE" || status === "APPROVED" || status === "REJECTED" || status === "FAILED") return "done";
    if (status === "RUNNING" || status === "IN_PROGRESS") return "running";
    return "proposed";
  }

  function missionId(item) {
    return item.execution_id || item.id || item.token_id || item.run_id || "";
  }

  function missionTitle(item) {
    return item.title || item.name || item.agent_id || `Execution ${missionId(item)}`;
  }

  function missionDescription(item) {
    return item.description || item.reason || item.prompt || item.summary || "No description";
  }

  function renderMissionCard(item) {
    const status = normalizeStatus(item.status || item.state || "");
    const id = missionId(item);
    const canReview = status === "HITL_WAIT";

    return `
      <article class="mcard">
        <div class="mcard-title">${esc(missionTitle(item))}</div>
        <div class="mcard-desc">${esc(missionDescription(item))}</div>
        <div class="mcard-foot">
          <span class="chip">${esc(status || "PROPOSED")}</span>
          ${canReview ? `
            <div class="btns">
              <button class="btn ok" data-action="approve" data-id="${esc(id)}">Approve</button>
              <button class="btn bad" data-action="reject" data-id="${esc(id)}">Reject</button>
            </div>
          ` : ""}
        </div>
      </article>
    `;
  }

  function renderKanban() {
    if (!kanbanEl) return;

    const source = state.executions.length
      ? state.executions
      : state.permissionRecent.map((r) => ({
          id: r.token_id,
          status: r.status,
          title: r.agent_id,
          description: r.reason || r.decision_reason || r.action,
        }));

    const cols = {
      proposed: [],
      running: [],
      done: [],
    };

    source.forEach((item) => {
      const lane = mapMissionState(item);
      cols[lane].push(item);
    });

    const order = [
      ["proposed", "Proposed"],
      ["running", "Running"],
      ["done", "Done"],
    ];

    kanbanEl.innerHTML = order.map(([key, title]) => `
      <section class="kcol">
        <div class="khd">
          <div class="name">${title}</div>
          <div class="count">${cols[key].length}</div>
        </div>
        <div class="kbody">${cols[key].map(renderMissionCard).join("") || '<div class="muted">No items</div>'}</div>
      </section>
    `).join("");
  }

  function statusClass(status) {
    const s = normalizeStatus(status);
    if (s === "DONE" || s === "APPROVED") return "done";
    if (s === "HITL_WAIT") return "hitl_wait";
    if (s === "REJECTED" || s === "FAILED") return "rejected";
    if (s === "RUNNING") return "running";
    return "neutral";
  }

  function renderEvents() {
    if (!eventsLogEl) return;
    eventsLogEl.innerHTML = state.permissionRecent.map((e) => {
      const status = String(e.status || e.state || "-").toUpperCase();
      const reason = e.reason || e.action || e.decision_reason || "";
      const ts = e.timestamp || e.created_at || e.time;
      return `
        <div class="event-row ${statusClass(status)}">
          <div class="event-ts">${esc(fmtTime(ts))}</div>
          <div class="event-agent">${esc(e.agent_id || "system")}</div>
          <div class="event-status">${esc(status)}</div>
          <div class="event-msg">${esc(reason)}</div>
        </div>
      `;
    }).join("");

    eventsLogEl.scrollTop = eventsLogEl.scrollHeight;
  }

  function buildConversations() {
    const ids = new Set(["chief_of_staff"]);
    state.chatAgents.forEach((a) => ids.add(String(a.agent_id || "").trim()));
    state.agents.forEach((a) => ids.add(String(a.agent_id || "").trim()));
    state.permissionRecent.forEach((e) => ids.add(String(e.agent_id || "").trim()));
    ids.delete("");
    const rows = [...ids].map((id) => {
      const meta = getAgentMeta(id);
      const stateItem = state.agents.find((a) => a.agent_id === id);
      const chatAgent = state.chatAgents.find((a) => String(a.agent_id || "") === id);
      const chatLast = chatAgent?.last_message || null;
      const recent = [...state.permissionRecent].reverse().find((e) => String(e.agent_id || "") === id);
      const status = String(stateItem?.state || recent?.status || "idle").toLowerCase();
      const last = chatLast?.content || recent?.reason || recent?.action || recent?.decision_reason || "No recent messages";
      const ts = new Date(chatLast?.created_at || recent?.timestamp || recent?.updated_at || recent?.created_at || 0).getTime();
      return {
        id,
        meta,
        status,
        last,
        ts,
      };
    });

    return rows.sort((a, b) => {
      if (a.ts !== b.ts) return b.ts - a.ts;
      const aw = a.status === "working" ? 1 : 0;
      const bw = b.status === "working" ? 1 : 0;
      if (aw !== bw) return bw - aw;
      return a.id.localeCompare(b.id);
    });
  }

  function buildConversationMessages(agentId) {
    const chatRows = (state.chatHistory[agentId] || []).map((m) => ({
      id: m.id,
      ts: new Date(m.created_at || Date.now()).getTime(),
      role: m.role || "assistant",
      text: m.content || "",
      source: m.source || "ui",
    }));
    if (chatRows.length) return chatRows;

    const runtimeRows = state.permissionRecent
      .filter((e) => String(e.agent_id || "") === agentId)
      .slice(-30)
      .map((e) => ({
        ts: new Date(e.timestamp || e.updated_at || e.created_at || Date.now()).getTime(),
        role: "assistant",
        text: e.reason || e.action || e.decision_reason || e.status || "Runtime event",
        source: "ui",
      }));
    const localRows = state.localMessages[agentId] || [];

    const out = [...runtimeRows, ...localRows].sort((a, b) => a.ts - b.ts);
    if (out.length) return out;
    return [{
      ts: Date.now(),
      role: "assistant",
      text: "Ready. Waiting for mission instructions.",
      source: "ui",
    }];
  }

  function renderConversations() {
    if (!conversationListEl) return;
    const conversations = buildConversations();
    if (!conversations.length) {
      conversationListEl.innerHTML = `<div class="muted">No conversations</div>`;
      return;
    }
    if (!conversations.some((c) => c.id === state.selectedConversation)) {
      state.selectedConversation = conversations[0].id;
      localStorage.setItem("selectedConversation", state.selectedConversation);
    }

    conversationListEl.innerHTML = conversations.map((c) => `
      <button class="convo-item ${c.id === state.selectedConversation ? "active" : ""}" data-convo="${esc(c.id)}">
        <span class="avatar" style="background:${esc(c.meta.color)}">${esc(c.meta.emoji)}</span>
        <span class="convo-meta">
          <div class="convo-name">${esc(c.meta.label)}</div>
          <div class="convo-last">${esc(c.last)}</div>
        </span>
      </button>
    `).join("");
  }

  function renderChatMessages() {
    if (!chatMessagesEl) return;
    const agentId = state.selectedConversation || "chief_of_staff";
    const meta = getAgentMeta(agentId);
    if (chatThreadTitleEl) chatThreadTitleEl.textContent = `${meta.emoji} ${meta.label}`;
    if (chatThreadSubEl) chatThreadSubEl.textContent = `Agent ID: ${agentId}`;

    const messages = buildConversationMessages(agentId);
    chatMessagesEl.innerHTML = messages.map((msg) => {
      const self = msg.role === "user" || msg.role === "self";
      const actor = self ? getAgentMeta("operator") : meta;
      const source = String(msg.source || "ui").toLowerCase();
      const roleLabel = self ? "user" : "assistant";
      return `
        <article class="msg ${self ? "self" : ""}">
          <span class="avatar" style="background:${esc(actor.color)}">${esc(actor.emoji)}</span>
          <div class="msg-bubble">
            <div class="msg-head">${esc(actor.label)} · ${esc(roleLabel)} · ${esc(source)} · ${esc(fmtTime(msg.ts))}</div>
            <div>${esc(msg.text)}</div>
          </div>
        </article>
      `;
    }).join("");
    chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
  }

  function renderChatPanel() {
    renderConversations();
    renderChatMessages();
  }

  async function sendLocalMessage() {
    const value = String(chatInputEl?.value || "").trim();
    if (!value) return;
    const id = state.selectedConversation || "chief_of_staff";
    if (!state.apiCaps.runtimeChat) {
      if (!state.localMessages[id]) state.localMessages[id] = [];
      state.localMessages[id].push({ ts: Date.now(), role: "self", text: value, source: "ui" });
      chatInputEl.value = "";
      renderChatPanel();
      return;
    }

    const prevLabel = chatSendBtn?.textContent || "Send";
    if (chatSendBtn) {
      chatSendBtn.disabled = true;
      chatSendBtn.textContent = "Sending...";
    }

    try {
      await fetchJson(api("/runtime/chat"), {
        method: "POST",
        body: JSON.stringify({ agent_id: id, message: value, source: "ui" }),
      });
      chatInputEl.value = "";
      await refreshChatData(id);
      renderChatPanel();
    } catch (err) {
      console.error(err);
      if (!state.localMessages[id]) state.localMessages[id] = [];
      state.localMessages[id].push({ ts: Date.now(), role: "assistant", text: `Error sending message: ${err?.message || err}`, source: "ui" });
      renderChatPanel();
    } finally {
      if (chatSendBtn) {
        chatSendBtn.disabled = false;
        chatSendBtn.textContent = prevLabel;
      }
    }
  }

  async function postMissionAction(action, id) {
    if (!id) return;
    addTrackedExecutionId(id);

    if (action === "approve") {
      await fetchJson(api("/runtime/approve"), {
        method: "POST",
        body: JSON.stringify({ execution_id: id, approved: true }),
      });
    } else if (state.apiCaps.runtimeReject) {
      await fetchJson(api("/runtime/reject"), {
        method: "POST",
        body: JSON.stringify({ execution_id: id, approved: false }),
      });
    } else {
      await fetchJson(api("/runtime/approve"), {
        method: "POST",
        body: JSON.stringify({ execution_id: id, approved: false }),
      });
    }

    await fetchRuntimeState();
  }

  function bindDynamicActions() {
    kanbanEl?.addEventListener("click", async (event) => {
      const btn = event.target.closest("button[data-action]");
      if (!btn) return;
      const action = btn.dataset.action;
      const id = btn.dataset.id;
      btn.disabled = true;
      try {
        await postMissionAction(action, id);
      } catch (err) {
        console.error(err);
      } finally {
        btn.disabled = false;
      }
    });
  }

  async function fetchRuntimeState() {
    try {
      try {
        const openapi = await fetchJson(api("/openapi.json"));
        parseOpenApiCaps(openapi);
      } catch {
        const candidates = [state.base, "http://127.0.0.1:8001", "http://127.0.0.1:8000"];
        let recovered = false;
        for (const candidate of [...new Set(candidates)]) {
          try {
            const openapi = await fetchJson(`${candidate.replace(/\/$/, "")}/openapi.json`);
            parseOpenApiCaps(openapi);
            if (candidate !== state.base) {
              state.base = candidate;
              apiBaseInput.value = state.base;
              if (settingsApiBase) settingsApiBase.value = state.base;
              localStorage.setItem("apiBase", state.base);
            }
            recovered = true;
            break;
          } catch {}
        }
        if (!recovered) throw new Error("API unreachable on known local endpoints");
      }
      setOnline(true);

      if (state.apiCaps.metrics) {
        try {
          state.metrics = parsePromMetrics(await fetchText(api("/metrics")));
        } catch {
          state.metrics = {};
        }
      }

      if (state.apiCaps.permissionStats) {
        try {
          const stats = await fetchJson(api("/runtime/permission/stats"));
          state.permissionStats = stats || { active_tokens: 0 };
        } catch (err) {
          if (String(err?.message || "").startsWith("404")) state.apiCaps.permissionStats = false;
          state.permissionStats = { active_tokens: 0 };
        }
      } else {
        state.permissionStats = { active_tokens: 0 };
      }

      if (state.apiCaps.agentsState) {
        try {
          const agents = await fetchJson(api("/runtime/agents/state"));
          state.agents = Array.isArray(agents.items) ? agents.items : [];
        } catch (err) {
          if (String(err?.message || "").startsWith("404")) state.apiCaps.agentsState = false;
          state.agents = [];
        }
      } else {
        state.agents = [];
      }

      if (state.apiCaps.permissionRecent) {
        try {
          const rec = await fetchJson(api("/runtime/permission/recent?limit=120"));
          state.permissionRecent = Array.isArray(rec.items) ? rec.items : [];
        } catch (err) {
          if (String(err?.message || "").startsWith("404")) state.apiCaps.permissionRecent = false;
          state.permissionRecent = [];
        }
      } else {
        state.permissionRecent = [];
      }

      if (state.apiCaps.executions) {
        try {
          const exec = await fetchJson(api("/runtime/executions?limit=60"));
          state.executions = Array.isArray(exec.items) ? exec.items : [];
          state.executions.forEach((e) => addTrackedExecutionId(missionId(e)));
        } catch (err) {
          if (String(err?.message || "").startsWith("404")) state.apiCaps.executions = false;
          state.executions = [];
        }
      } else {
        state.executions = [];
      }

      await refreshTrackedExecutions();

      if (!state.agents.length) {
        const known = new Set();
        (state.metrics.tokens_total || []).forEach((s) => s.labels?.agent_id && known.add(s.labels.agent_id));
        (state.metrics.cost_usd_total || []).forEach((s) => s.labels?.agent_id && known.add(s.labels.agent_id));
        state.agents = [...known].map((id) => ({ agent_id: id, state: "idle", cost_usd: 0 }));
      }

      if (state.executions.length) {
        const byAgent = new Map();
        for (const ex of state.executions) {
          const id = ex.agent_id || "chief_of_staff";
          const st = normalizeStatus(ex.status || ex.state);
          const prev = byAgent.get(id) || "idle";
          if (st === "HITL_WAIT") byAgent.set(id, "hitl_wait");
          else if (st === "RUNNING" && prev !== "hitl_wait") byAgent.set(id, "working");
          else if (!byAgent.has(id)) byAgent.set(id, "idle");
        }
        state.agents = state.agents.map((a) => ({ ...a, state: byAgent.get(a.agent_id) || a.state || "idle" }));
      }

      const costByAgent = new Map();
      (state.metrics.cost_usd_total || []).forEach((s) => {
        const id = s.labels?.agent_id;
        if (!id) return;
        costByAgent.set(id, (costByAgent.get(id) || 0) + Number(s.value || 0));
      });
      state.agents = state.agents.map((a) => ({ ...a, cost_usd: Number(costByAgent.get(a.agent_id) ?? a.cost_usd ?? 0) }));

      if ((!state.permissionStats.active_tokens || state.permissionStats.active_tokens === 0) && state.apiCaps.metrics) {
        state.permissionStats = {
          active_tokens: Math.round(metricSum("tokens_total", (labels) => labels.direction === "in")),
        };
      }

      if (!state.permissionRecent.length && state.executions.length) {
        state.permissionRecent = state.executions.map((e) => ({
          timestamp: e.updated_at,
          agent_id: e.agent_id,
          status: normalizeStatus(e.status || e.state),
          reason: e.description || e.title || "",
        }));
      }

      await refreshChatData(state.selectedConversation);

      window.agentState = {
        agents: state.agents,
        stats: state.permissionStats,
      };

      const working = state.agents.filter((a) => String(a.state || "").toLowerCase() === "working").length;
      if (workingCountEl) workingCountEl.textContent = String(working);
      if (agentsBadgeEl) agentsBadgeEl.textContent = `agents: ${state.agents.length}`;

      renderBadges();
      renderKanban();
      renderEvents();
      renderChatPanel();
      renderHomeKpis();
    } catch (error) {
      console.error(error);
      setOnline(false);
      renderChatPanel();
    }
  }
  function showPage(route) {
    for (const r of routes) {
      const el = document.getElementById(`page-${r}`);
      if (el) el.classList.toggle("hidden", r !== route);
    }

    navLinks.forEach((a) => a.classList.toggle("active", a.dataset.route === route));

    const titles = {
      home: ["Home", "Overview"],
      chat: ["Chat", "Conversations with agents"],
      stage: ["Stage", "Mission timeline theater"],
      gallery: ["Gallery", "Operational snapshots"],
      missions: ["Missions", "Track proposals and execution"],
      agents: ["Agents", "Live state"],
      events: ["Events", "Runtime events"],
      analytics: ["Analytics", "Metrics"],
      settings: ["Settings", "Config"],
    };
    const [t, s] = titles[route] || ["Mission Control", ""];
    pageTitle.textContent = t;
    pageSub.textContent = s;
  }

  function initRouting() {
    function onHash() {
      const h = (location.hash || "#home").replace("#", "");
      showPage(routes.includes(h) ? h : "home");
    }
    window.addEventListener("hashchange", onHash);
    onHash();
  }

  function initPhaser() {
    if (!officeCanvas || state.phaserGame || typeof Phaser === "undefined" || typeof window.OfficeScene === "undefined") return;

    const wrap = officeCanvas.parentElement;
    const width = Math.max(700, Math.floor(wrap.clientWidth));
    const height = Math.max(420, Math.floor(wrap.clientHeight));

    state.phaserGame = new Phaser.Game({
      type: Phaser.CANVAS,
      canvas: officeCanvas,
      width,
      height,
      transparent: true,
      antialias: false,
      pixelArt: true,
      scene: [window.OfficeScene],
    });

    const resize = () => {
      const game = state.phaserGame;
      if (!game || !game.scale || typeof game.scale.resize !== "function") return;
      const w = Math.max(700, Math.floor(wrap.clientWidth || 0));
      const h = Math.max(420, Math.floor(wrap.clientHeight || 0));
      if (!Number.isFinite(w) || !Number.isFinite(h)) return;
      game.scale.resize(w, h);
    };

    window.addEventListener("resize", resize);
    if (typeof ResizeObserver !== "undefined") {
      const ro = new ResizeObserver(resize);
      ro.observe(wrap);
    }
  }

  function restartPolling() {
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.pollTimer = setInterval(fetchRuntimeState, state.pollMs);
  }

  function restartChatPolling() {
    if (state.chatPollTimer) clearInterval(state.chatPollTimer);
    state.chatPollTimer = setInterval(async () => {
      try {
        await refreshChatData(state.selectedConversation);
        renderChatPanel();
      } catch (err) {
        console.error(err);
      }
    }, state.chatPollMs);
  }

  function saveBaseUrl(value) {
    state.base = value.trim() || state.base;
    apiBaseInput.value = state.base;
    if (settingsApiBase) settingsApiBase.value = state.base;
    localStorage.setItem("apiBase", state.base);
  }

  function savePollMs(value) {
    const ms = Math.max(500, Number(value) || 1000);
    state.pollMs = ms;
    if (settingsPollMs) settingsPollMs.value = String(ms);
    localStorage.setItem("pollMs", String(ms));
    restartPolling();
  }

  function bindUi() {
    themeToggleBtn?.addEventListener("click", () => {
      applyTheme(state.theme === "light" ? "dark" : "light");
    });

    saveApiBtn?.addEventListener("click", async () => {
      saveBaseUrl(apiBaseInput.value);
      await fetchRuntimeState();
    });

    saveSettings?.addEventListener("click", async () => {
      saveBaseUrl(settingsApiBase?.value || state.base);
      savePollMs(settingsPollMs?.value || state.pollMs);
      await fetchRuntimeState();
    });

    addTrackExecutionBtn?.addEventListener("click", async () => {
      const id = trackExecutionIdInput?.value || "";
      if (!addTrackedExecutionId(id)) return;
      if (trackExecutionIdInput) trackExecutionIdInput.value = "";
      await fetchRuntimeState();
    });

    clearTrackExecutionsBtn?.addEventListener("click", async () => {
      state.trackedExecutionIds = [];
      localStorage.removeItem("trackedExecutionIds");
      state.executions = [];
      await fetchRuntimeState();
    });

    trackExecutionIdInput?.addEventListener("keydown", async (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      const id = trackExecutionIdInput.value || "";
      if (!addTrackedExecutionId(id)) return;
      trackExecutionIdInput.value = "";
      await fetchRuntimeState();
    });

    conversationListEl?.addEventListener("click", async (event) => {
      const btn = event.target.closest("[data-convo]");
      if (!btn) return;
      state.selectedConversation = btn.dataset.convo || "chief_of_staff";
      localStorage.setItem("selectedConversation", state.selectedConversation);
      await fetchChatHistory(state.selectedConversation, 50);
      renderChatPanel();
    });

    chatSendBtn?.addEventListener("click", sendLocalMessage);
    chatInputEl?.addEventListener("keydown", async (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      await sendLocalMessage();
    });

    bindDynamicActions();
  }

  initRouting();
  bindUi();
  initPhaser();
  renderChatPanel();
  fetchRuntimeState();
  restartPolling();
  restartChatPolling();
})();
















