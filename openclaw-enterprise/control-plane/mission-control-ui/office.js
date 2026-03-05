(() => {
  const routes = ["home", "missions", "agents", "events", "analytics", "settings"];

  const apiBaseInput = document.getElementById("apiBase");
  const saveApiBtn = document.getElementById("saveApi");
  const apiStatus = document.getElementById("apiStatus");
  const pageTitle = document.getElementById("pageTitle");
  const pageSub = document.getElementById("pageSub");
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

  const trackExecutionIdInput = document.getElementById("trackExecutionId");
  const addTrackExecutionBtn = document.getElementById("addTrackExecution");
  const clearTrackExecutionsBtn = document.getElementById("clearTrackExecutions");

  const officeCanvas = document.getElementById("office");

  const state = {
    base: localStorage.getItem("apiBase") || apiBaseInput.value || "http://127.0.0.1:19000",
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
    trackedExecutionIds: (() => { try { const raw = localStorage.getItem("trackedExecutionIds"); const arr = raw ? JSON.parse(raw) : []; return Array.isArray(arr) ? [...new Set(arr.map((x) => String(x || "").trim()).filter(Boolean))] : []; } catch { return []; } })(),
    apiCaps: { permissionStats: true, agentsState: true, permissionRecent: true, executions: true, runtimeStatus: false, metrics: false, runtimeApprove: false, runtimeReject: false },
  };

  apiBaseInput.value = state.base;
  if (settingsApiBase) settingsApiBase.value = state.base;
  if (settingsPollMs) settingsPollMs.value = String(state.pollMs);

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
      return `<span class="${cls}">${esc(a.agent_id)} <span class="muted">${esc(status)}</span></span>`;
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
        const candidates = [state.base, "http://127.0.0.1:19000", "http://127.0.0.1:8000"];
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
      renderHomeKpis();
    } catch (error) {
      console.error(error);
      setOnline(false);
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
      const h = (location.hash || "#agents").replace("#", "");
      showPage(routes.includes(h) ? h : "agents");
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

    bindDynamicActions();
  }

  initRouting();
  bindUi();
  initPhaser();
  fetchRuntimeState();
  restartPolling();
})();
















