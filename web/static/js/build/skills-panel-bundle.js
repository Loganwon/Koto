(function() {
  "use strict";
  const SAFE_METHODS = /* @__PURE__ */ new Set(["GET", "HEAD", "OPTIONS", "TRACE"]);
  let refreshPromise = null;
  function _csrfMeta() {
    return document.querySelector('meta[name="csrf-token"]');
  }
  function getCsrfToken() {
    return _csrfMeta()?.getAttribute("content") || "";
  }
  function _setCsrfToken(token) {
    let meta = _csrfMeta();
    if (!meta) {
      meta = document.createElement("meta");
      meta.setAttribute("name", "csrf-token");
      document.head.appendChild(meta);
    }
    meta.setAttribute("content", token || "");
    return token || "";
  }
  async function refreshCsrfToken() {
    if (refreshPromise) return refreshPromise;
    refreshPromise = fetch("/api/csrf-token", {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store"
    }).then(async (response) => {
      if (!response.ok) return getCsrfToken();
      const data = await response.json().catch(() => ({}));
      const token = String(data?.csrf_token || data?.token || "");
      return token ? _setCsrfToken(token) : getCsrfToken();
    }).catch(() => getCsrfToken()).finally(() => {
      refreshPromise = null;
    });
    return refreshPromise;
  }
  function _methodNeedsCsrf(method) {
    return !SAFE_METHODS.has(String(method || "GET").toUpperCase());
  }
  function _withCsrfHeaders(headersInit, token) {
    const headers = new Headers(headersInit || {});
    const nextToken = token || getCsrfToken();
    if (nextToken && !headers.has("X-CSRFToken") && !headers.has("X-CSRF-Token")) {
      headers.set("X-CSRFToken", nextToken);
    }
    return headers;
  }
  async function csrfFetch(url, options = {}) {
    const shared = window.WA?._csrfFetch || window._csrfFetch;
    if (typeof shared === "function") return shared(url, options);
    const method = String(options.method || "GET").toUpperCase();
    const needsCsrf = _methodNeedsCsrf(method);
    const makeInit = (token) => {
      const init = { ...options, credentials: options.credentials || "same-origin" };
      if (needsCsrf) init.headers = _withCsrfHeaders(options.headers, token);
      return init;
    };
    let response = await fetch(url, makeInit());
    if (response.status === 400 && needsCsrf) {
      const token = await refreshCsrfToken();
      if (token) response = await fetch(url, makeInit(token));
    }
    return response;
  }
  let lastSidePanelFocus = null;
  function _panel(id) {
    return document.getElementById(id);
  }
  function _sidePanelScrim() {
    return document.getElementById("sidePanelScrim");
  }
  const PANEL_TRIGGER_IDS = {
    settingsPanel: ["navSettingsBtn"],
    skillsPanel: ["navSkillsBtn", "csbToggleBtn"]
  };
  function _activeSidePanels() {
    return ["settingsPanel", "skillsPanel"].map((id) => _panel(id)).filter((panel) => !!panel && panel.classList.contains("active"));
  }
  function _hasBlockingModal() {
    if (document.querySelector(".modal-overlay.active, .koto-dialog-overlay, .agent-dialog-overlay")) return true;
    const modalSelectors = [".skill-editor-modal", ".edit-modal-overlay", ".sc-overlay", ".sm-drawer-overlay"];
    return modalSelectors.some((selector) => {
      const el = document.querySelector(selector);
      if (!el) return false;
      if (el.classList.contains("open") || el.classList.contains("active")) return true;
      return getComputedStyle(el).display !== "none" && getComputedStyle(el).visibility !== "hidden";
    });
  }
  function _setPanelA11y(panel, isOpen) {
    panel.setAttribute("aria-hidden", isOpen ? "false" : "true");
    panel.setAttribute("aria-modal", isOpen ? "true" : "false");
    if (!panel.hasAttribute("tabindex")) panel.setAttribute("tabindex", "-1");
  }
  function _setPanelTriggerA11y(panelId, isOpen) {
    (PANEL_TRIGGER_IDS[panelId] || []).forEach((triggerId) => {
      const trigger = document.getElementById(triggerId);
      if (!trigger) return;
      trigger.setAttribute("aria-expanded", isOpen ? "true" : "false");
      trigger.setAttribute("aria-controls", panelId);
    });
  }
  function _focusPanel(panel) {
    requestAnimationFrame(() => {
      const active = document.activeElement;
      if (active && panel.contains(active)) return;
      panel.focus({ preventScroll: true });
    });
  }
  function _restoreFocus() {
    const target = lastSidePanelFocus;
    lastSidePanelFocus = null;
    if (!target || !document.contains(target)) return;
    requestAnimationFrame(() => target.focus({ preventScroll: true }));
  }
  function refreshSidePanelScrim() {
    const scrim = _sidePanelScrim();
    const hasOpenPanel = _activeSidePanels().length > 0;
    document.body.classList.toggle("side-panel-open", hasOpenPanel);
    if (!scrim) return;
    scrim.classList.toggle("active", hasOpenPanel);
    scrim.toggleAttribute("hidden", !hasOpenPanel);
    scrim.setAttribute("aria-hidden", hasOpenPanel ? "false" : "true");
  }
  function markSidePanelOpen(panelId) {
    const panel = _panel(panelId);
    if (!panel) return;
    const active = document.activeElement;
    if (active && !panel.contains(active)) lastSidePanelFocus = active;
    _setPanelA11y(panel, true);
    _setPanelTriggerA11y(panelId, true);
    refreshSidePanelScrim();
    _focusPanel(panel);
  }
  function markSidePanelClosed(panelId, restoreFocus = true) {
    const panel = _panel(panelId);
    if (panel) _setPanelA11y(panel, false);
    _setPanelTriggerA11y(panelId, false);
    refreshSidePanelScrim();
    if (restoreFocus && _activeSidePanels().length === 0) _restoreFocus();
  }
  function closeActiveSidePanel() {
    if (_hasBlockingModal()) return false;
    const settings = _panel("settingsPanel");
    if (settings?.classList.contains("active") && typeof window.closeSettings === "function") {
      window.closeSettings();
      return true;
    }
    const skills = _panel("skillsPanel");
    if (skills?.classList.contains("active") && typeof window.closeSkillsPanel === "function") {
      window.closeSkillsPanel();
      return true;
    }
    return false;
  }
  function initSidePanelInteractions() {
    const scrim = _sidePanelScrim();
    if (scrim && !scrim._kotoSidePanelBound) {
      scrim._kotoSidePanelBound = true;
      scrim.addEventListener("click", () => closeActiveSidePanel());
    }
  }
  document.addEventListener("DOMContentLoaded", () => {
    Object.keys(PANEL_TRIGGER_IDS).forEach((panelId) => {
      const isOpen = !!_panel(panelId)?.classList.contains("active");
      _setPanelTriggerA11y(panelId, isOpen);
    });
    initSidePanelInteractions();
    refreshSidePanelScrim();
  });
  window.closeActiveSidePanel = closeActiveSidePanel;
  let _spSkills = [];
  let _spSuppressedIds = /* @__PURE__ */ new Set();
  let _spConflictWinner = {};
  let _spCurrentTab = "catalog";
  let _spCurrentCat = "all";
  const _SP_FILE_SKILL_IDS = /* @__PURE__ */ new Set([
    "pdf_reader",
    "multi_format_reader",
    "long_doc_parser",
    "spreadsheet_analyst",
    "table_extractor",
    "cross_format_extractor",
    "multi_doc_synthesis",
    "doc_format_fixer",
    "doc_structure_optimizer",
    "table_enhancer",
    "doc_tone_adjuster",
    "doc_fact_checker",
    "doc_readability",
    "doc_dedup",
    "legal_doc_review",
    "financial_doc_review",
    "academic_paper_polish",
    "marketing_copy",
    "excel_formula_expert",
    "excel_data_cleaner",
    "pivot_advisor",
    "slide_storyteller",
    "slide_data_viz",
    "doc_smart_compare",
    "questionnaire_filler",
    "comm_digest",
    "data_format_cleaner",
    "ppt_generator_pro",
    "excel_generator_pro",
    "docx_generator_pro",
    "pdf_generator_pro",
    "docx_translator"
  ]);
  let _spCurrentSearch = "";
  let _spCurrentSort = "default";
  let _spSelectedSessionId = null;
  let _spCommunitySkills = [];
  let _spCommunityLoading = false;
  let _spCommunitySearch = "";
  const CAT_LABELS = { behavior: "⚙️ 行为", style: "🎨 风格", domain: "🔬 领域", custom: "🔧 自定义" };
  const LS_LAST_USED = "koto_skill_last_used";
  const LS_USE_COUNT = "koto_skill_use_count";
  const _spCsrfFetch = csrfFetch;
  function spGetLastUsed() {
    try {
      return JSON.parse(localStorage.getItem(LS_LAST_USED) || "{}");
    } catch (_) {
      return {};
    }
  }
  function spGetUseCounts() {
    try {
      return JSON.parse(localStorage.getItem(LS_USE_COUNT) || "{}");
    } catch (_) {
      return {};
    }
  }
  function _syncCsbToggleBtn(isOpen) {
    const btn = document.getElementById("csbToggleBtn");
    if (!btn) return;
    if (isOpen) btn.classList.add("panel-open");
    else btn.classList.remove("panel-open");
  }
  function _setActivityActive(id) {
    document.querySelectorAll(".activity-btn").forEach((button) => button.classList.remove("active"));
    const target = document.getElementById(id);
    if (target) target.classList.add("active");
  }
  function _isUnifiedWorkspace() {
    return document.body.classList.contains("koto-unified-workspace") || document.documentElement.classList.contains("koto-unified-workspace");
  }
  window.openSkillsPanel = function() {
    const panel = document.getElementById("skillsPanel");
    if (!panel) return;
    if (typeof window.closeSettings === "function") window.closeSettings();
    panel.classList.add("active");
    document.body.classList.add("skills-panel-open");
    markSidePanelOpen("skillsPanel");
    _setActivityActive("navSkillsBtn");
    _syncCsbToggleBtn(true);
    spLoadSkills();
    spLoadRecStrip();
  };
  window.closeSkillsPanel = function() {
    const panel = document.getElementById("skillsPanel");
    if (!panel) return;
    panel.classList.remove("active");
    document.body.classList.remove("skills-panel-open");
    markSidePanelClosed("skillsPanel");
    const navBtn = document.getElementById("navSkillsBtn");
    if (navBtn) navBtn.classList.remove("active");
    if (_isUnifiedWorkspace()) _setActivityActive("navWorkspaceBtn");
    _syncCsbToggleBtn(false);
  };
  window.toggleSkillsPanel = function() {
    const panel = document.getElementById("skillsPanel");
    if (!panel) return;
    if (panel.classList.contains("active")) {
      window.closeSkillsPanel();
    } else {
      window.openSkillsPanel();
    }
  };
  window.CoworkPanel = /* @__PURE__ */ (() => {
    let _taskId = null;
    let _sse = null;
    let _pollTimer = null;
    let _sessionId = "default";
    function _el(id) {
      return document.getElementById(id);
    }
    function _phaseLabel(phase) {
      const map = { planning: "规划中", review: "待审批", executing: "执行中", done: "已完成", failed: "失败" };
      return map[phase] || phase;
    }
    function _stepIcon(status) {
      if (status === "done") return "✅";
      if (status === "running") return '<span class="cw-spinner"></span>';
      if (status === "failed") return "❌";
      if (status === "skipped") return "⏭";
      return "⬜";
    }
    function _toolIcon(hint) {
      const m = { web_search: "🌐", read_file: "📄", write_file: "💾", code_exec: "⚙️", memory_search: "🧠" };
      return m[hint] || "🔧";
    }
    function _md(text) {
      if (typeof window.marked !== "undefined") {
        try {
          return window.marked.parse(text || "");
        } catch (e) {
        }
      }
      return (text || "").replace(/\n/g, "<br>");
    }
    function _updateBadge(count) {
      const b = _el("coworkRunningBadge");
      if (!b) return;
      if (count > 0) {
        b.textContent = String(count);
        b.style.display = "";
      } else {
        b.style.display = "none";
      }
    }
    function open() {
      const panel = _el("coworkPanel");
      if (!panel) return;
      if (typeof window.closeSkillsPanel === "function") window.closeSkillsPanel();
      panel.classList.add("active");
      const btn = _el("navCoworkBtn");
      if (btn) btn.classList.add("active");
    }
    function close() {
      const panel = _el("coworkPanel");
      if (!panel) return;
      panel.classList.remove("active");
      const btn = _el("navCoworkBtn");
      if (btn) btn.classList.remove("active");
    }
    function switchTab(tab) {
      ["new", "status", "history"].forEach((t) => {
        const tabEl = _el("cwTab" + t.charAt(0).toUpperCase() + t.slice(1));
        const bodyEl = _el("cwTab" + t.charAt(0).toUpperCase() + t.slice(1) + "Body");
        if (tabEl) tabEl.classList.toggle("active", t === tab);
        if (bodyEl) bodyEl.style.display = t === tab ? "flex" : "none";
      });
      if (tab === "history") _loadHistory();
    }
    async function submit() {
      const goal = (_el("cwGoalInput")?.value || "").trim();
      if (!goal) {
        _el("cwGoalInput")?.focus();
        return;
      }
      const context = (_el("cwContextInput")?.value || "").trim();
      const human_review = _el("cwHumanReviewToggle")?.checked || false;
      _el("cwSubmitBtn").disabled = true;
      _el("cwSubmitBtn").textContent = "提交中…";
      try {
        const resp = await _spCsrfFetch("/api/bg-agent/submit", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            goal,
            context: context ? { info: context } : {},
            human_review,
            session_id: _sessionId
          })
        });
        const json = await resp.json();
        if (!resp.ok || !json.ok) throw new Error(json.error || "提交失败");
        _taskId = json.data.task_id;
        _startMonitor(_taskId);
        switchTab("status");
        _el("cwTabStatus").style.display = "";
        _el("cwCurrentGoal").textContent = "目标: " + goal;
      } catch (e) {
        alert("提交失败: " + e.message);
      } finally {
        _el("cwSubmitBtn").disabled = false;
        _el("cwSubmitBtn").textContent = "▶ 开始执行任务";
      }
    }
    function _startMonitor(taskId) {
      _stopMonitor();
      try {
        _sse = new EventSource("/api/bg-agent/" + taskId + "/stream");
        _sse.onmessage = (ev) => {
          try {
            _handleUpdate(JSON.parse(ev.data));
          } catch (e) {
          }
        };
        _sse.onerror = () => {
          _sse.close();
          _sse = null;
          _startPoll(taskId);
        };
      } catch (e) {
        _startPoll(taskId);
      }
      _updateBadge(1);
    }
    function _startPoll(taskId) {
      _pollTimer = setInterval(() => _fetchStatus(taskId), 2500);
    }
    function _stopMonitor() {
      if (_sse) {
        try {
          _sse.close();
        } catch (e) {
        }
        _sse = null;
      }
      if (_pollTimer) {
        clearInterval(_pollTimer);
        _pollTimer = null;
      }
    }
    async function _fetchStatus(taskId) {
      try {
        const resp = await fetch("/api/bg-agent/" + taskId);
        if (!resp.ok) return;
        const json = await resp.json();
        if (json.ok) _handleUpdate(json.data);
      } catch (e) {
      }
    }
    function _handleUpdate(status) {
      if (!status) return;
      const phase = status.phase;
      const badge = _el("cwPhaseBadge");
      if (badge) {
        badge.textContent = _phaseLabel(phase);
        badge.className = "cw-phase-badge " + phase;
        badge.style.display = "";
      }
      if (status.steps_total > 0) {
        const pct = Math.round(status.steps_done / status.steps_total * 100);
        if (_el("cwProgressBar")) _el("cwProgressBar").style.width = pct + "%";
        if (_el("cwProgressText")) _el("cwProgressText").textContent = status.steps_done + " / " + status.steps_total;
      }
      if (_el("cwReviewBlock")) _el("cwReviewBlock").style.display = phase === "review" ? "" : "none";
      if (_el("cwStepsBlock")) _el("cwStepsBlock").style.display = phase === "executing" ? "" : "none";
      if (_el("cwReportBlock")) _el("cwReportBlock").style.display = phase === "done" ? "" : "none";
      if (_el("cwErrorBlock")) _el("cwErrorBlock").style.display = phase === "failed" ? "" : "none";
      if (phase === "review" && status.plan) _renderPlan(status.plan);
      if (phase === "executing" && status.plan) _renderExecSteps(status.plan.steps, status.current_step);
      if (phase === "done") {
        if (_el("cwReportContent")) _el("cwReportContent").innerHTML = _md(status.final_report || "任务完成。");
        _stopMonitor();
        _updateBadge(0);
      }
      if (phase === "failed") {
        if (_el("cwErrorMsg")) _el("cwErrorMsg").textContent = status.error || "未知错误";
        _stopMonitor();
        _updateBadge(0);
      }
    }
    function _renderPlan(plan) {
      if (_el("cwPlanReasoning")) _el("cwPlanReasoning").textContent = plan.reasoning || "";
      if (_el("cwPlanMeta")) _el("cwPlanMeta").textContent = "预计耗时: " + (plan.estimated_minutes || "?") + " 分钟 · " + (plan.steps || []).length + " 个步骤";
      const container = _el("cwPlanSteps");
      if (!container) return;
      container.innerHTML = (plan.steps || []).map(
        (s, i) => `<div class="cw-step">
        <div class="cw-step-header">
          <span class="cw-step-icon">${_toolIcon(s.tool_hint)}</span>
          <span class="cw-step-title">${i + 1}. ${_esc(s.title)}</span>
        </div>
        <div class="cw-step-desc">${_esc(s.description)}</div>
      </div>`
      ).join("");
    }
    function _renderExecSteps(steps, currentStepId) {
      const container = _el("cwExecSteps");
      if (!container) return;
      container.innerHTML = (steps || []).map((s) => {
        const isCurrent = s.step_id === currentStepId;
        return `<div class="cw-step ${s.status}">
        <div class="cw-step-header">
          <span class="cw-step-icon">${_stepIcon(s.status)}</span>
          <span class="cw-step-title">${_esc(s.title)}</span>
          ${isCurrent ? '<span class="cw-spinner" style="margin-left:auto"></span>' : ""}
        </div>
        ${s.result ? '<div class="cw-step-desc">' + _esc(s.result.slice(0, 120)) + "</div>" : ""}
      </div>`;
      }).join("");
    }
    function _esc(str) {
      return String(str || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }
    async function approve() {
      if (!_taskId) return;
      try {
        const resp = await _spCsrfFetch("/api/bg-agent/" + _taskId + "/approve", { method: "POST" });
        const json = await resp.json();
        if (!json.ok) throw new Error(json.error || "操作失败");
        if (_el("cwReviewBlock")) _el("cwReviewBlock").style.display = "none";
      } catch (e) {
        alert("批准失败: " + e.message);
      }
    }
    function showRejectInput() {
      const row = _el("cwRejectRow");
      if (row) row.style.display = row.style.display === "none" ? "flex" : "none";
    }
    async function reject() {
      if (!_taskId) return;
      const feedback = _el("cwRejectFeedback")?.value || "";
      try {
        const resp = await _spCsrfFetch("/api/bg-agent/" + _taskId + "/reject", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ feedback })
        });
        const json = await resp.json();
        if (!json.ok) throw new Error(json.error || "操作失败");
        _stopMonitor();
        _updateBadge(0);
        newTask();
      } catch (e) {
        alert("拒绝失败: " + e.message);
      }
    }
    async function cancel() {
      if (!_taskId) return;
      if (!confirm("确认取消当前任务？")) return;
      try {
        await _spCsrfFetch("/api/bg-agent/" + _taskId + "/cancel", { method: "POST" });
      } catch (e) {
      }
      _stopMonitor();
      _updateBadge(0);
      newTask();
    }
    function newTask() {
      _taskId = null;
      _stopMonitor();
      const goalInput = _el("cwGoalInput");
      if (goalInput) goalInput.value = "";
      const contextInput = _el("cwContextInput");
      if (contextInput) contextInput.value = "";
      const phaseBadge = _el("cwPhaseBadge");
      if (phaseBadge) phaseBadge.style.display = "none";
      const progressBar = _el("cwProgressBar");
      if (progressBar) progressBar.style.width = "0%";
      const progressText = _el("cwProgressText");
      if (progressText) progressText.textContent = "0 / 0";
      const tabStatus = _el("cwTabStatus");
      if (tabStatus) tabStatus.style.display = "none";
      switchTab("new");
      _updateBadge(0);
    }
    async function _loadHistory() {
      const container = _el("cwHistoryList");
      if (!container) return;
      container.innerHTML = '<div class="cw-empty"><span class="cw-spinner"></span></div>';
      try {
        const resp = await fetch("/api/bg-agent/list?session_id=" + _sessionId);
        const json = await resp.json();
        if (!json.ok) throw new Error(json.error || "加载失败");
        const tasks = json.data || [];
        if (!tasks.length) {
          container.innerHTML = '<div class="cw-empty">暂无历史任务</div>';
          return;
        }
        container.innerHTML = tasks.map((t) => {
          const dt = t.submitted_at ? new Date(t.submitted_at * 1e3).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "";
          return `<div class="cw-history-item" onclick="CoworkPanel.loadTask('${t.task_id}')">
          <div class="cw-history-goal">${_esc(t.goal)}</div>
          <div class="cw-history-meta">
            <span class="cw-phase-badge ${t.phase}" style="padding:1px 7px;font-size:10px;">${_phaseLabel(t.phase)}</span>
            <span style="margin-left:6px;">${dt}</span>
          </div>
        </div>`;
        }).join("");
      } catch (e) {
        container.innerHTML = '<div class="cw-empty" style="color:#f87171;">' + _esc(e.message) + "</div>";
      }
    }
    async function loadTask(taskId) {
      _taskId = taskId;
      switchTab("status");
      const tabStatus = _el("cwTabStatus");
      if (tabStatus) tabStatus.style.display = "";
      _fetchStatus(taskId);
      _startMonitor(taskId);
    }
    return { open, close, switchTab, submit, approve, showRejectInput, reject, cancel, newTask, loadTask };
  })();
  async function spLoadSkills() {
    const content = document.getElementById("spContent");
    if (!content) return;
    content.innerHTML = '<div class="sp-loading">正在加载 Skills…</div>';
    try {
      const resp = await fetch("/api/skills");
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const data = await resp.json();
      if (!data.success) throw new Error(data.error || "加载失败");
      _spSkills = (data.skills || []).filter((s) => s.skill_nature !== "system");
      try {
        const cres = await fetch("/api/skillmarket/conflicts");
        if (cres.ok) {
          const cdata = await cres.json();
          _spSuppressedIds = new Set((cdata.conflicts || []).map((c) => c.loser_id));
          _spConflictWinner = {};
          (cdata.conflicts || []).forEach((c) => {
            _spConflictWinner[c.loser_id] = c.winner_name;
          });
        }
      } catch (_) {
      }
      spRenderCards();
    } catch (e) {
      content.innerHTML = `<div class="sp-loading" style="color:var(--error-color,#e06c75)">⚠️ ${e.message}</div>`;
    }
  }
  function spUpdateActiveBadge() {
    const badge = document.getElementById("spActiveBadge");
    if (!badge) return;
    const count = _spSkills.filter((s) => s.enabled).length;
    if (count > 0) {
      badge.textContent = String(count) + " 激活";
      badge.style.display = "";
    } else {
      badge.style.display = "none";
    }
  }
  function spRenderCards() {
    const content = document.getElementById("spContent");
    if (!content) return;
    spUpdateActiveBadge();
    const tab = _spCurrentTab;
    const cat = _spCurrentCat;
    const q = _spCurrentSearch.toLowerCase();
    let skills = _spSkills;
    if (tab === "library") {
      skills = skills.filter((s) => s.enabled || !s.is_builtin);
    }
    if (cat === "file") {
      skills = skills.filter((s) => _SP_FILE_SKILL_IDS.has(s.id));
    } else if (cat !== "all") {
      skills = skills.filter((s) => s.category === cat);
    }
    if (q) {
      skills = skills.filter(
        (s) => s.name && s.name.toLowerCase().includes(q) || s.description && s.description.toLowerCase().includes(q)
      );
    }
    if (!skills.length) {
      if (tab === "library") {
        content.innerHTML = `<div class="sp-loading" style="padding:24px 12px;line-height:1.8">
        尚未启用任何 Skill，也没有自定义技能。<br>
        <button onclick="spSwitchTab('catalog')" style="margin-top:8px;padding:5px 14px;border-radius:8px;border:1px solid var(--accent-primary);background:transparent;color:var(--accent-primary);cursor:pointer;font-size:12px;">去「全部」启用 Skill</button>
      </div>`;
      } else if (tab === "catalog" && cat === "custom") {
        content.innerHTML = `<div class="sp-loading" style="padding:24px 12px;line-height:1.9">
        还没有自定义 Skill。<br>
        <button onclick="spSwitchTab('studio')" style="margin-top:10px;padding:5px 16px;border-radius:8px;border:1px solid var(--accent-primary);background:transparent;color:var(--accent-primary);cursor:pointer;font-size:12px;">✨ 前往创意工坊创建</button>
      </div>`;
      } else if (tab === "catalog" && q) {
        content.innerHTML = `<div class="sp-loading">本地无匹配结果</div><div id="spLocalSearchCommunity" style="margin-top:10px;"></div>`;
        window.spSearchCommunityFallback(q);
      } else {
        content.innerHTML = `<div class="sp-loading">暂无匹配结果</div>`;
      }
      return;
    }
    if (_spCurrentSort === "recent") {
      const lu = spGetLastUsed();
      const used = skills.filter((s) => lu[s.id]);
      const unused = skills.filter((s) => !lu[s.id]);
      used.sort((a, b) => (lu[b.id] || 0) - (lu[a.id] || 0));
      unused.sort((a, b) => a.name.localeCompare(b.name));
      skills = [...used, ...unused];
    } else if (_spCurrentSort === "popular") {
      const uc = spGetUseCounts();
      const used = skills.filter((s) => uc[s.id]);
      const unused = skills.filter((s) => !uc[s.id]);
      used.sort((a, b) => (uc[b.id] || 0) - (uc[a.id] || 0));
      unused.sort((a, b) => a.name.localeCompare(b.name));
      skills = [...used, ...unused];
    } else {
      skills = [...skills.filter((s) => s.enabled), ...skills.filter((s) => !s.enabled)];
    }
    const CAT_SHORT = { behavior: "行为", style: "风格", domain: "领域", custom: "自定义", workflow: "工作流" };
    function renderTile(s) {
      const isSup = s.enabled && _spSuppressedIds.has(s.id);
      const catCls = `sp-tile-${s.category || "custom"}`;
      const badge = isSup ? `<span style="position:absolute;top:6px;left:30px;font-size:9px;color:#ffb86c;background:rgba(0,0,0,.55);border-radius:4px;padding:1px 4px;line-height:1.5;">⚠</span>` : s.has_template ? `<span style="position:absolute;top:6px;left:30px;font-size:9px;color:var(--text-muted);background:rgba(0,0,0,.45);border-radius:4px;padding:1px 4px;line-height:1.5;">📄</span>` : "";
      const descText = (s.description || "").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      return `<div class="sp-tile ${catCls}${s.enabled ? " active" : ""}${isSup ? " suppressed" : ""}"
      data-sp-id="${s.id}"
      onclick="spToggleSkill('${s.id}', ${!s.enabled})">
      ${badge}
      <button class="sp-tile-pencil" onclick="event.stopPropagation();openSkillEditor('${s.id}')" title="编辑 Prompt">⚙</button>
      <div class="sp-tile-emoji">${s.icon || "🔧"}</div>
      <div class="sp-tile-label">${s.name}</div>
      ${descText ? `<div class="sp-tile-desc">${descText}</div>` : ""}
      <div class="sp-tile-foot">
        <span class="sp-tile-cat">${CAT_SHORT[s.category] || s.category || ""}</span>
        <span class="sp-tile-check">✓ 启用</span>
        <span class="sp-tile-dot"></span>
      </div>
    </div>`;
    }
    const enabledSkills = skills.filter((s) => s.enabled);
    const activeListHtml = enabledSkills.length ? `
    <div class="sp-active-list-section">
      <div class="sp-active-list-title">当前激活 · ${enabledSkills.length} 个</div>
      ${enabledSkills.map((s) => {
      const isSup = _spSuppressedIds.has(s.id);
      const supNote = isSup ? ` <span style="color:#ffb86c;font-size:10px;">⚠ 被「${_spConflictWinner[s.id] || ""}」抑制</span>` : "";
      return `<div class="sp-actv-item">
        <span class="sp-actv-icon">${s.icon || "🔧"}</span>
        <div class="sp-actv-info">
          <div class="sp-actv-name">${s.name}${isSup ? " ⚠️" : ""}</div>
          <div class="sp-actv-meta">${CAT_LABELS[s.category] || s.category}${supNote}</div>
        </div>
        <button class="sp-actv-dismiss" onclick="event.stopPropagation();spToggleSkill('${s.id}',false)" title="禁用"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
      </div>`;
    }).join("")}
    </div>` : "";
    content.innerHTML = `<div class="sp-tile-grid">${skills.map(renderTile).join("")}</div>${activeListHtml}`;
    if (tab === "catalog" && cat === "custom") {
      const studioBanner = document.createElement("div");
      studioBanner.className = "sp-community-promo";
      studioBanner.setAttribute("title", "在创意工坊创建你的专属 Skill");
      studioBanner.onclick = () => window.spSwitchTab("studio");
      studioBanner.innerHTML = `<span style="font-size:16px;flex-shrink:0">✨</span>
      <div class="sp-community-promo-text">
        <div class="sp-community-promo-title">在创意工坊创建专属 Skill</div>
        <div class="sp-community-promo-sub">AI 智能生成 · 从对话提取 · 手动编写，三种方式随意选</div>
      </div>
      <span class="sp-community-promo-enter">›</span>`;
      content.insertBefore(studioBanner, content.firstChild);
    }
    if (tab === "catalog" && !q && cat === "all") {
      const banner = document.createElement("div");
      banner.className = "sp-community-promo";
      banner.setAttribute("title", "浏览社区精选 Skills");
      banner.onclick = () => window.spSwitchTab("community");
      banner.innerHTML = `<span style="font-size:16px;flex-shrink:0">🌐</span>
      <div class="sp-community-promo-text">
        <div class="sp-community-promo-title">探索 Koto 精选社区</div>
        <div class="sp-community-promo-sub">浏览高质量社区 Skills，一键安装即用</div>
      </div>
      <span class="sp-community-promo-enter">›</span>`;
      content.insertBefore(banner, content.firstChild);
    }
  }
  async function spLoadCommunitySkills() {
    if (_spCommunitySkills.length > 0) {
      spRenderCommunityCards();
      return;
    }
    if (_spCommunityLoading) return;
    _spCommunityLoading = true;
    const content = document.getElementById("spCommunityContent");
    if (content) content.innerHTML = '<div class="sp-loading">正在加载社区数据…</div>';
    try {
      const r = await fetch("/api/skillmarket/community/catalog");
      if (r.ok) {
        const data = await r.json();
        _spCommunitySkills = data.skills || [];
        spRenderCommunityCards();
      } else {
        if (content) content.innerHTML = '<div class="sp-loading" style="color:#ffb86c">加载社区数据失败，请重试</div>';
      }
    } catch (e) {
      if (content) content.innerHTML = '<div class="sp-loading" style="color:#ffb86c">无法连接到服务器</div>';
    } finally {
      _spCommunityLoading = false;
    }
  }
  function spSkillStats(id) {
    let h = 0;
    for (let i = 0; i < id.length; i++) h = Math.imul(h, 31) + id.charCodeAt(i) >>> 0;
    const likes = 18 + h % 183;
    const installs = likes + 10 + (h >>> 8) % 320;
    return { likes, installs };
  }
  function spRenderCommunityCards() {
    const content = document.getElementById("spCommunityContent");
    if (!content) return;
    const q = _spCommunitySearch.toLowerCase();
    let skills = _spCommunitySkills;
    if (q) {
      skills = skills.filter(
        (s) => s.name && s.name.toLowerCase().includes(q) || (s.description || "").toLowerCase().includes(q) || (s.author || "").toLowerCase().includes(q)
      );
    }
    if (!skills.length) {
      content.innerHTML = `<div class="sp-loading">暂无匹配的社区 Skills</div>`;
      return;
    }
    const CAT_LABEL = { behavior: "行为", style: "风格", domain: "领域", coding: "代码", writing: "写作", career: "职场", research: "研究", lifestyle: "生活", custom: "自定义", workflow: "工作流" };
    function renderCard(s) {
      const isInstalled = s.is_installed;
      const catLabel = CAT_LABEL[s.category] || s.category || "社区";
      const author = s.author || (s.community_meta ? "Koto 精选社区" : "Koto");
      const desc = (s.description || "").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      const difficulty = s.community_meta?.difficulty || "";
      const useCases = s.community_meta?.use_cases ? s.community_meta.use_cases.join("、") : "";
      const { likes, installs } = spSkillStats(s.id);
      const shortDesc = desc ? desc.length > 45 ? desc.slice(0, 45) + "…" : desc : "";
      return `<div class="sp-comm-card" id="spCommCard_${s.id}">
      <div class="sp-comm-card-row" onclick="spToggleCommunityCard('${s.id}')">
        <span class="sp-comm-card-icon">${s.icon || "🌐"}</span>
        <div class="sp-comm-card-name">
          <div class="sp-comm-card-name-text">${s.name}</div>
          ${shortDesc ? `<div class="sp-comm-card-desc">${shortDesc}</div>` : ""}
        </div>
        <span class="sp-comm-card-cat">${catLabel}</span>
        <span class="sp-comm-card-stats" title="点赞 ${likes} · 安装 ${installs}">❤ ${likes}</span>
        <button class="sp-comm-card-install ${isInstalled ? "installed" : "uninstalled"}"
          onclick="event.stopPropagation();spInstallCommunitySkill('${s.id}',${isInstalled})">
          ${isInstalled ? "✓ 已安装" : "＋ 安装"}
        </button>
        <span class="sp-comm-card-chevron">▾</span>
      </div>
      <div class="sp-comm-card-detail">
        ${desc ? `<div class="sp-comm-card-drow"><span class="sp-comm-card-dlabel">作用</span><span>${desc}</span></div>` : ""}
        <div class="sp-comm-card-drow"><span class="sp-comm-card-dlabel">来源</span><span>${author}</span></div>
        ${difficulty ? `<div class="sp-comm-card-drow"><span class="sp-comm-card-dlabel">难度</span><span>${difficulty}</span></div>` : ""}
        ${useCases ? `<div class="sp-comm-card-drow"><span class="sp-comm-card-dlabel">场景</span><span>${useCases}</span></div>` : ""}
        <div class="sp-comm-card-drow" style="margin-top:4px;">
          <span class="sp-comm-card-dlabel">热度</span>
          <span style="display:flex;gap:10px;align-items:center;">
            <span title="点赞数">❤ <b>${likes}</b></span>
            <span title="安装数" style="color:var(--text-muted);">⬇ <b>${installs}</b> 次安装</span>
          </span>
        </div>
      </div>
    </div>`;
    }
    content.innerHTML = skills.map(renderCard).join("");
  }
  window.spCommunityFilterCards = function(q) {
    _spCommunitySearch = q || "";
    spRenderCommunityCards();
  };
  window.spToggleCommunityCard = function(skillId) {
    const card = document.getElementById("spCommCard_" + skillId);
    if (!card) return;
    card.classList.toggle("open");
  };
  window.spInstallCommunitySkill = async function(skillId, isInstalled) {
    if (isInstalled) {
      if (window.toast) window.toast("该 Skill 已安装，可在「我的库」中管理");
      return;
    }
    const card = document.getElementById("spCommCard_" + skillId);
    try {
      const r = await _spCsrfFetch("/api/skillmarket/community/install/" + encodeURIComponent(skillId), { method: "POST" });
      if (r.ok) {
        if (window.toast) window.toast("安装成功，已为您启用该 Skill！");
        const s = _spCommunitySkills.find((x) => x.id === skillId);
        if (s) s.is_installed = true;
        spRenderCommunityCards();
        spLoadSkills();
        if (card && card.classList.contains("open")) {
          const newCard = document.getElementById("spCommCard_" + skillId);
          if (newCard) newCard.classList.add("open");
        }
      } else {
        const data = await r.json();
        if (window.toast) window.toast("安装失败: " + (data.error || "未知错误"), "error");
      }
    } catch (e) {
      if (window.toast) window.toast("网络错误，请稍后重试", "error");
    }
  };
  window.spPreviewCommunitySkill = async function(skillId) {
    const skill = _spCommunitySkills.find((s) => s.id === skillId);
    if (!skill) return;
    const existing = document.getElementById("spPreviewModalOverlay");
    if (existing) existing.remove();
    const overlay = document.createElement("div");
    overlay.id = "spPreviewModalOverlay";
    overlay.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;display:flex;align-items:center;justify-content:center;";
    overlay.onclick = (e) => {
      if (e.target === overlay) overlay.remove();
    };
    const descText = (skill.description || "无描述").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    const authorText = skill.community_meta?.author ? `by ${skill.community_meta.author}` : "";
    const catText = { behavior: "行为增强", domain: "专业领域", coding: "代码工程", writing: "写作创作", career: "职场效率", research: "研究分析", lifestyle: "生活助手" };
    overlay.innerHTML = `<div class="sp-preview-modal">
    <div class="sp-preview-header">
      <div class="sp-preview-icon">${skill.icon || "🌐"}</div>
      <div style="flex:1;min-width:0;">
        <div class="sp-preview-title">${skill.name}</div>
        <div class="sp-preview-meta">
          <span>${catText[skill.category] || "社区"}</span>
          ${authorText ? `<span>${authorText}</span>` : ""}
        </div>
      </div>
    </div>
    <div class="sp-preview-body">
      <div class="sp-preview-label">描述</div>
      <p style="margin:0 0 16px;line-height:1.6;">${descText}</p>
      <div class="sp-preview-label">System Prompt</div>
      <div class="sp-preview-prompt" id="spPreviewPromptBox">加载中…</div>
    </div>
    <div class="sp-preview-footer">
      <button onclick="document.getElementById('spPreviewModalOverlay').remove()"
        style="padding:6px 14px;border-radius:6px;border:1px solid var(--border-color);background:transparent;color:var(--text-primary);cursor:pointer;font-size:13px;">
        关闭
      </button>
      ${!skill.is_installed ? `<button onclick="spInstallCommunitySkill('${skill.id}',false);document.getElementById('spPreviewModalOverlay').remove();"
        style="padding:6px 14px;border-radius:6px;border:none;background:#238636;color:#fff;cursor:pointer;font-size:13px;font-weight:600;">
        ＋ 立即安装
      </button>` : `<span style="font-size:12px;color:#3fb950;padding:6px 0;">✓ 已安装</span>`}
    </div>
  </div>`;
    document.body.appendChild(overlay);
    try {
      const r = await fetch("/api/skillmarket/community/skill/" + encodeURIComponent(skillId));
      const box = document.getElementById("spPreviewPromptBox");
      if (r.ok) {
        const data = await r.json();
        if (box) box.textContent = data.system_prompt || data.prompt || "（无 System Prompt）";
      } else {
        if (box) box.textContent = skill.prompt || skill.system_prompt || "（无法加载）";
      }
    } catch (e) {
      const box = document.getElementById("spPreviewPromptBox");
      if (box) box.textContent = skill.prompt || skill.system_prompt || "（网络错误）";
    }
  };
  window.spSearchCommunityFallback = async function(q) {
    const container = document.getElementById("spLocalSearchCommunity");
    if (!container) return;
    if (_spCommunitySkills.length === 0) {
      try {
        const r = await fetch("/api/skillmarket/community/catalog");
        if (r.ok) {
          const data = await r.json();
          _spCommunitySkills = data.skills || [];
        }
      } catch (e) {
      }
    }
    const qLower = q.toLowerCase();
    const matched = _spCommunitySkills.filter(
      (s) => !s.is_installed && (s.name.toLowerCase().includes(qLower) || s.description && s.description.toLowerCase().includes(qLower))
    ).slice(0, 5);
    if (matched.length > 0) {
      const CAT_SHORT = { behavior: "行为", style: "风格", domain: "领域", custom: "自定义", workflow: "工作流" };
      const cardsHtml = matched.map((s) => {
        const descText = (s.description || "").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        return `<div class="sp-tile sp-tile-${s.category || "custom"}" data-sp-id="${s.id}" onclick="spInstallCommunitySkill('${s.id}', false)">
        <button class="sp-tile-pencil" onclick="event.stopPropagation();spPreviewCommunitySkill('${s.id}')" title="预览详情">👁️</button>
        <div class="sp-tile-emoji">${s.icon || "🌐"}</div>
        <div class="sp-tile-label">${s.name}</div>
        ${descText ? `<div class="sp-tile-desc">${descText}</div>` : ""}
        <div class="sp-tile-foot">
          <span class="sp-tile-cat">${CAT_SHORT[s.category] || "社区"}</span>
          <span style="font-size:10px;font-weight:600;color:#58a6ff;background:rgba(88,166,255,0.1);padding:2px 6px;border-radius:4px;">＋ 安装</span>
        </div>
      </div>`;
      }).join("");
      container.innerHTML = `<div style="padding:0 14px; margin-bottom:0px; font-size:11px; color:var(--text-muted); font-weight:600;">在社区中找到了以下相关的 Skill：</div>
      <div class="sp-tile-grid">${cardsHtml}</div>`;
    } else {
      container.innerHTML = "";
    }
  };
  window.spSwitchTab = function(tab) {
    _spCurrentTab = tab;
    document.querySelectorAll(".sp-tab").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tab === tab);
    });
    const filterRow = document.getElementById("spFilterRow");
    const sortRow = document.getElementById("spSortRow");
    const recStrip = document.getElementById("spRecStrip");
    const content = document.getElementById("spContent");
    const studio = document.getElementById("spStudio");
    const presets = document.getElementById("spPresets");
    const askKoto = document.getElementById("spAskKoto");
    const community = document.getElementById("spCommunity");
    if (filterRow) filterRow.style.display = "none";
    if (sortRow) sortRow.style.display = "none";
    if (recStrip) recStrip.style.display = "none";
    if (content) content.style.display = "none";
    if (studio) studio.style.display = "none";
    if (presets) presets.style.display = "none";
    if (askKoto) askKoto.style.display = "none";
    if (community) community.style.display = "none";
    if (tab === "studio") {
      if (studio) {
        studio.style.display = "flex";
        spLoadSessionList();
      }
    } else if (tab === "presets") {
      if (presets) {
        presets.style.display = "flex";
        spRenderPresets();
      }
    } else if (tab === "askkoto") {
      if (askKoto) askKoto.style.display = "flex";
    } else if (tab === "community") {
      if (community) {
        community.style.display = "flex";
        spLoadCommunitySkills();
      }
    } else {
      if (filterRow) filterRow.style.display = "flex";
      if (sortRow) sortRow.style.display = "flex";
      if (content) content.style.display = "block";
      spLoadRecStrip();
      if (tab === "library") {
        spLoadSkills();
      } else {
        spRenderCards();
      }
    }
  };
  window.spSetCat = function(cat) {
    _spCurrentCat = cat;
    document.querySelectorAll(".sp-chip").forEach((c) => {
      c.classList.toggle("active", c.dataset.cat === cat);
    });
    spRenderCards();
  };
  window.spSetSort = function(sort) {
    _spCurrentSort = sort;
    document.querySelectorAll(".sp-sort-option").forEach((c) => {
      c.classList.toggle("active", c.dataset.sort === sort);
    });
    const btn = document.getElementById("spSortBtn");
    if (btn) {
      btn.classList.toggle("sorted", sort !== "default");
      btn.classList.remove("open");
    }
    const dd = document.getElementById("spSortDropdown");
    if (dd) dd.classList.remove("open");
    spRenderCards();
  };
  window.spToggleSortMenu = function(e) {
    e.stopPropagation();
    const dd = document.getElementById("spSortDropdown");
    const btn = document.getElementById("spSortBtn");
    const isOpen = dd.classList.toggle("open");
    btn.classList.toggle("open", isOpen);
  };
  document.addEventListener("click", function() {
    const dd = document.getElementById("spSortDropdown");
    const btn = document.getElementById("spSortBtn");
    if (dd) dd.classList.remove("open");
    if (btn) btn.classList.remove("open");
  });
  window.spSearchSkills = function(q) {
    _spCurrentSearch = q;
    if (_spCurrentTab === "community") {
      spRenderCommunityCards();
    } else {
      spRenderCards();
    }
  };
  window.spToggleSkill = async function(skillId, enabled) {
    const tile = document.querySelector(`.sp-tile[data-sp-id="${skillId}"]`);
    if (tile) {
      tile.classList.toggle("active", enabled);
      tile.setAttribute("onclick", `spToggleSkill('${skillId}', ${!enabled})`);
    }
    const skill = _spSkills.find((s) => s.id === skillId);
    if (skill) skill.enabled = enabled;
    spUpdateActiveBadge();
    if (typeof window.toggleSkill === "function") {
      await window.toggleSkill(skillId, enabled);
    }
    spRenderCards();
  };
  window.spBuildSkill = async function() {
    const desc = (document.getElementById("spBuildDesc")?.value || "").trim();
    const name = (document.getElementById("spBuildName")?.value || "").trim();
    const resultEl = document.getElementById("spBuildResult");
    if (!desc) {
      alert("请先描述 Skill 的功能");
      return;
    }
    resultEl.style.display = "block";
    resultEl.innerHTML = '<div class="sp-loading">AI 正在生成 Skill…</div>';
    try {
      const resp = await _spCsrfFetch("/api/skillmarket/auto-build", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ description: desc, name, auto_enable: false })
      });
      const data = await resp.json();
      if (!data.success) throw new Error(data.error || "生成失败");
      const skill = data.skill || {};
      resultEl.innerHTML = `
      <div style="color:var(--accent-secondary,#34d399);font-weight:600;margin-bottom:4px">
        ✓ ${skill.icon || "✨"} ${skill.name || name} 已创建
      </div>
      <div style="font-size:10px;color:var(--text-muted);white-space:pre-wrap;max-height:56px;overflow-y:auto;line-height:1.4;">${(skill.prompt || "").substring(0, 300)}</div>
      <button class="sp-enable-btn" style="margin-top:6px;" onclick="spToggleSkill('${skill.id}', true)">启用</button>
    `;
      await spLoadSkills();
    } catch (e) {
      resultEl.innerHTML = `<div style="color:var(--error-color,#e06c75)">⚠️ ${e.message}</div>`;
    }
  };
  async function spLoadSessionList() {
    const list = document.getElementById("spSessionList");
    if (!list) return;
    list.innerHTML = '<div class="sp-loading">正在加载对话…</div>';
    try {
      const resp = await fetch("/api/skillmarket/sessions");
      const data = await resp.json();
      if (!data.success) throw new Error(data.error || "加载失败");
      const sessions = data.sessions || [];
      if (!sessions.length) {
        list.innerHTML = '<div class="sp-loading">暂无对话记录</div>';
        return;
      }
      list.innerHTML = sessions.map((s) => `
      <div class="sp-session-item" data-sp-sid="${s.id}" onclick="spSelectSession('${s.id}', this)">
        💬 ${s.title || s.id}
        <span style="float:right;color:var(--text-muted)">${s.message_count || 0} 条</span>
      </div>
    `).join("");
    } catch (e) {
      list.innerHTML = `<div class="sp-loading" style="color:var(--error-color,#e06c75)">⚠️ ${e.message}</div>`;
    }
  }
  window.spSelectSession = function(sessionId, el) {
    _spSelectedSessionId = sessionId;
    document.querySelectorAll(".sp-session-item").forEach((i) => i.classList.remove("selected"));
    el.classList.add("selected");
    spWizardGoToStep(2);
  };
  function spWizardGoToStep(n) {
    for (let i = 1; i <= 3; i++) {
      const stepEl = document.getElementById(`spWizardStep${i}`);
      if (stepEl) stepEl.style.display = i === n ? "block" : "none";
      const dotEl = document.getElementById(`sp-wstep-${i}`);
      if (dotEl) {
        dotEl.classList.remove("active", "done");
        if (i < n) dotEl.classList.add("done");
        else if (i === n) dotEl.classList.add("active");
      }
    }
  }
  window.spWizardBack = function() {
    spWizardGoToStep(1);
  };
  window.spWizardReset = function() {
    _spSelectedSessionId = null;
    document.querySelectorAll(".sp-session-item").forEach((i) => i.classList.remove("selected"));
    spWizardGoToStep(1);
  };
  window.spExtractFromSession = async function() {
    const sessionId = _spSelectedSessionId;
    const name = (document.getElementById("spSessionName")?.value || "").trim() || "提取风格";
    const icon = (document.getElementById("spSessionIcon")?.value || "").trim() || "💬";
    const resultEl = document.getElementById("spExtractResult");
    if (!sessionId) {
      alert("请先选择一个对话");
      return;
    }
    spWizardGoToStep(3);
    resultEl.innerHTML = '<div class="sp-loading">AI 正在分析对话风格…</div>';
    try {
      const resp = await _spCsrfFetch("/api/skillmarket/from-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, skill_name: name, icon, auto_enable: true })
      });
      const data = await resp.json();
      if (!data.success) throw new Error(data.error || "提取失败");
      const prompt = data.prompt || data.skill?.prompt || "";
      resultEl.innerHTML = `
      <div style="color:var(--accent-secondary,#34d399);font-weight:600;margin-bottom:6px;">
        ✓ ${icon} ${name} 已创建并启用
      </div>
      <div style="font-size:10px;color:var(--text-muted);margin-bottom:3px;">Prompt 预览：</div>
      <pre style="font-size:10px;white-space:pre-wrap;color:var(--text-muted);max-height:72px;overflow-y:auto;line-height:1.4;margin:0;">${prompt.substring(0, 400)}</pre>
    `;
      await spLoadSkills();
      if (typeof window.refreshActiveSkills === "function") window.refreshActiveSkills();
    } catch (e) {
      resultEl.innerHTML = `<div style="color:var(--error-color,#e06c75)">⚠️ ${e.message}</div>`;
    }
  };
  const _origRefreshActiveSkills = window.refreshActiveSkills;
  window.refreshActiveSkills = async function() {
    if (typeof _origRefreshActiveSkills === "function") await _origRefreshActiveSkills();
    if (document.getElementById("skillsPanel")?.classList.contains("active") && _spSkills.length) {
      spRenderCards();
    }
  };
  window.getSpSkills = function() {
    return _spSkills;
  };
  const LS_PRESETS = "koto_skill_presets";
  const PRESET_ICONS = ["📦", "💻", "📝", "💬", "🔬", "🎨", "⚡", "🧠", "🌙", "🎯", "🛠️", "🚀"];
  let _spPresetIconIdx = 0;
  const BUILTIN_PRESETS = [
    { id: "__builtin_code", name: "编程模式", icon: "💻", skills: ["step_by_step", "concise_mode", "code_expert", "strict_logic"], is_builtin: true, desc: "步骤化输出 + 简洁 + 代码专家 + 严谨逻辑" },
    { id: "__builtin_write", name: "写作模式", icon: "📝", skills: ["polished_writing", "rich_format", "deep_thinking"], is_builtin: true, desc: "文字润色 + 丰富排版 + 深度思考" },
    { id: "__builtin_chat", name: "轻聊模式", icon: "💬", skills: [], is_builtin: true, desc: "关闭所有 Skill，轻松自然对话" },
    { id: "__builtin_analyst", name: "分析模式", icon: "🔬", skills: ["deep_thinking", "strict_logic", "step_by_step"], is_builtin: true, desc: "深度思考 + 严谨逻辑 + 步骤化" },
    { id: "__builtin_file_mgmt", name: "文件管理模式", icon: "📁", skills: ["multi_format_reader", "doc_structure_optimizer", "doc_readability", "table_enhancer", "spreadsheet_analyst", "excel_formula_expert"], is_builtin: true, desc: "多格式读取 + 结构优化 + 可读性 + 表格增强 + 数据分析 + 公式专家" }
  ];
  function spGetUserPresets() {
    try {
      return JSON.parse(localStorage.getItem(LS_PRESETS) || "[]");
    } catch (_) {
      return [];
    }
  }
  function spSaveUserPresets(arr) {
    try {
      localStorage.setItem(LS_PRESETS, JSON.stringify(arr));
    } catch (_) {
    }
  }
  function spGetActivePresetId() {
    const ids = _spSkills.filter((s) => s.enabled).map((s) => s.id).sort().join(",");
    const all = [...BUILTIN_PRESETS, ...spGetUserPresets()];
    const match = all.find((p) => [...p.skills].sort().join(",") === ids);
    return match ? match.id : null;
  }
  window.spCyclePresetIcon = function() {
    _spPresetIconIdx = (_spPresetIconIdx + 1) % PRESET_ICONS.length;
    const el = document.getElementById("spPresetIconPick");
    if (el) el.textContent = PRESET_ICONS[_spPresetIconIdx];
  };
  window.spSaveCurrentPreset = function() {
    const nameEl = document.getElementById("spPresetNameInput");
    const name = (nameEl ? nameEl.value : "").trim();
    if (!name) {
      nameEl && nameEl.focus();
      return;
    }
    const icon = PRESET_ICONS[_spPresetIconIdx];
    const skillIds = _spSkills.filter((s) => s.enabled).map((s) => s.id);
    const presets = spGetUserPresets();
    const existing = presets.findIndex((p) => p.name === name);
    const preset = {
      id: existing >= 0 ? presets[existing].id : "preset_" + Date.now(),
      name,
      icon,
      skills: skillIds,
      created: Date.now(),
      is_builtin: false,
      desc: skillIds.length ? `${skillIds.length} 个 Skill` : "无激活 Skill"
    };
    if (existing >= 0) {
      presets[existing] = preset;
    } else {
      presets.unshift(preset);
    }
    spSaveUserPresets(presets);
    if (nameEl) nameEl.value = "";
    spRenderPresets();
  };
  window.spDeletePreset = function(id) {
    const presets = spGetUserPresets().filter((p) => p.id !== id);
    spSaveUserPresets(presets);
    spRenderPresets();
  };
  window.spApplyPreset = async function(preset) {
    const card = document.querySelector(`.sp-preset-card[data-preset-id="${preset.id}"]`);
    if (card) card.classList.add("sp-preset-applying");
    const toEnable = new Set(preset.skills);
    const ops = _spSkills.map((s) => ({ id: s.id, target: toEnable.has(s.id), current: s.enabled }));
    const changes = ops.filter((o) => o.target !== o.current);
    for (const c of changes) {
      if (typeof window.toggleSkill === "function") {
        await window.toggleSkill(c.id, c.target);
      }
      const sk = _spSkills.find((s) => s.id === c.id);
      if (sk) sk.enabled = c.target;
    }
    if (card) card.classList.remove("sp-preset-applying");
    spRenderPresets();
    if (typeof window.refreshActiveSkills === "function") window.refreshActiveSkills();
  };
  const _spPresetRegistry = {};
  window.spApplyPresetById = function(id) {
    const p = _spPresetRegistry[id];
    if (p) window.spApplyPreset(p);
  };
  function spRenderPresets() {
    const listEl = document.getElementById("spPresetList");
    if (!listEl) return;
    const activeId = spGetActivePresetId();
    const userPresets = spGetUserPresets();
    Object.keys(_spPresetRegistry).forEach((k) => delete _spPresetRegistry[k]);
    [...BUILTIN_PRESETS, ...userPresets].forEach((p) => {
      _spPresetRegistry[p.id] = p;
    });
    function renderPresetCard(p) {
      const isActive = p.id === activeId;
      CSS.escape ? CSS.escape(p.id) : p.id;
      const tagHtml = p.skills.length ? p.skills.slice(0, 6).map((sid) => {
        const sk = _spSkills.find((s) => s.id === sid);
        return `<span class="sp-preset-skill-tag">${sk ? sk.icon + " " + sk.name : sid}</span>`;
      }).join("") + (p.skills.length > 6 ? `<span class="sp-preset-skill-tag">+${p.skills.length - 6}</span>` : "") : '<span class="sp-preset-skill-tag" style="color:var(--text-muted)">无 Skill</span>';
      const badgeHtml = p.is_builtin ? '<span class="sp-preset-badge builtin">内置</span>' : `<span class="sp-preset-badge">${new Date(p.created).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" })}</span>`;
      const delBtn = !p.is_builtin ? `<button class="sp-preset-del-btn" onclick="event.stopPropagation();spDeletePreset('${p.id}')" title="删除"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>` : "";
      return `<div class="sp-preset-card${isActive ? " active-preset" : ""}" data-preset-id="${p.id}" onclick="spApplyPresetById('${p.id}')">
      <div class="sp-preset-head">
        <span class="sp-preset-emoji">${p.icon}</span>
        <span class="sp-preset-name">${p.name}</span>
        ${badgeHtml}
        ${isActive ? '<span style="font-size:10px;color:var(--accent-primary)">✓ 当前</span>' : ""}
      </div>
      <div class="sp-preset-skills">${tagHtml}</div>
      <div class="sp-preset-footer">
        <span class="sp-preset-meta">${(p.desc || "").replace(/</g, "&lt;").replace(/>/g, "&gt;")}</span>
        <div class="sp-preset-actions">
          ${delBtn}
          <button class="sp-preset-apply-btn" onclick="event.stopPropagation();spApplyPresetById('${p.id}')">
            ${isActive ? "已应用" : "▶ 应用"}
          </button>
        </div>
      </div>
    </div>`;
    }
    let html = "";
    if (userPresets.length) {
      html += `<div class="sp-preset-group-label">我的预设</div>`;
      html += userPresets.map(renderPresetCard).join("");
      html += `<div class="sp-preset-group-label" style="margin-top:4px;">内置预设</div>`;
    } else {
      html += `<div class="sp-preset-group-label">内置预设</div>`;
    }
    html += BUILTIN_PRESETS.map(renderPresetCard).join("");
    listEl.innerHTML = html;
  }
  window.spTrackMessageUsage = function() {
    const now = Date.now();
    const enabledIds = _spSkills.filter((s) => s.enabled).map((s) => s.id);
    if (!enabledIds.length) return;
    try {
      const lu = spGetLastUsed();
      const uc = spGetUseCounts();
      enabledIds.forEach((id) => {
        lu[id] = now;
        uc[id] = (uc[id] || 0) + 1;
      });
      localStorage.setItem(LS_LAST_USED, JSON.stringify(lu));
      localStorage.setItem(LS_USE_COUNT, JSON.stringify(uc));
    } catch (_) {
    }
    try {
      _spCsrfFetch("/api/skills/usage", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ skill_ids: enabledIds })
      }).catch(() => {
      });
    } catch (_) {
    }
  };
  async function spLoadRecStrip() {
    const strip = document.getElementById("spRecStrip");
    const chips = document.getElementById("spRecChips");
    if (!strip || !chips) return;
    try {
      const resp = await fetch("/api/skills/recommendations?limit=6");
      if (!resp.ok) return;
      const data = await resp.json();
      if (!data.success || !data.skills || !data.skills.length) return;
      chips.innerHTML = data.skills.map((s) => {
        const active = s.enabled ? " active" : "";
        return `<button class="sp-rec-chip${active}" onclick="spToggleSkill('${s.id}', ${!s.enabled})" title="${(s.description || "").replace(/"/g, "&quot;")}">
        ${s.icon || "🔧"} ${s.name}
      </button>`;
      }).join("");
      strip.style.display = "block";
    } catch (_) {
    }
  }
  window.spAskKoto = async function() {
    const taskInput = document.getElementById("spAkTaskInput");
    const btn = document.getElementById("spAkAskBtn");
    const resultEl = document.getElementById("spAkResult");
    const reasoningEl = document.getElementById("spAkReasoning");
    const cardsEl = document.getElementById("spAkCards");
    const task = (taskInput ? taskInput.value : "").trim();
    if (!task) {
      taskInput && taskInput.focus();
      return;
    }
    btn.disabled = true;
    btn.textContent = "思考中…";
    resultEl.style.display = "none";
    try {
      const resp = await _spCsrfFetch("/api/skills/ask-koto", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task })
      });
      const data = await resp.json();
      if (!data.success) throw new Error(data.error || "请求失败");
      reasoningEl.textContent = data.reasoning || "";
      reasoningEl.style.display = data.reasoning ? "block" : "none";
      if (!data.skills || !data.skills.length) {
        cardsEl.innerHTML = '<div style="font-size:11px;color:var(--text-muted);padding:4px 0;">没有找到特别匹配的 Skill，可以尝试更具体的描述。</div>';
      } else {
        cardsEl.innerHTML = data.skills.map((s) => {
          const isEnabled = _spSkills.find((x) => x.id === s.id)?.enabled || s.enabled;
          return `<div class="sp-ak-card" id="spAkCard_${s.id}">
          <span class="sp-ak-icon">${s.icon || "🔧"}</span>
          <div class="sp-ak-info">
            <div class="sp-ak-name">${s.name}</div>
            <div class="sp-ak-desc">${(s.description || "").replace(/</g, "&lt;")}</div>
          </div>
          <button class="sp-ak-enable-btn${isEnabled ? " enabled" : ""}"
            id="spAkEnableBtn_${s.id}"
            onclick="spAkToggle('${s.id}', this)">
            ${isEnabled ? "✓ 已启用" : "启用"}
          </button>
        </div>`;
        }).join("");
      }
      resultEl.style.display = "block";
    } catch (e) {
      cardsEl.innerHTML = `<div style="font-size:11px;color:var(--error-color,#e06c75);padding:4px 0;">⚠ ${e.message}</div>`;
      resultEl.style.display = "block";
    } finally {
      btn.disabled = false;
      btn.textContent = "✨ 问 Koto";
    }
  };
  window.spAkToggle = async function(skillId, btnEl) {
    const skill = _spSkills.find((s) => s.id === skillId);
    const toEnable = !(skill ? skill.enabled : btnEl.classList.contains("enabled"));
    btnEl.textContent = "…";
    await window.spToggleSkill(skillId, toEnable);
    btnEl.classList.toggle("enabled", toEnable);
    btnEl.textContent = toEnable ? "✓ 已启用" : "启用";
  };
  window.spRenderCards = spRenderCards;
  window.spLoadSkills = spLoadSkills;
  window.spGhInstallUrl = async function() {
    const input = document.getElementById("spGhUrlInput");
    const status = document.getElementById("spGhInstallStatus");
    if (!input || !status) return;
    const rawUrl = (input.value || "").trim();
    if (!rawUrl) {
      input.focus();
      return;
    }
    if (!rawUrl.startsWith("https://raw.githubusercontent.com/")) {
      status.style.display = "block";
      status.style.color = "var(--error-color, #e06c75)";
      status.textContent = "❌ 仅支持 https://raw.githubusercontent.com/ 开头的链接";
      return;
    }
    const btn = input.nextElementSibling;
    if (btn) {
      btn.disabled = true;
      btn.textContent = "⏳ 安装中…";
    }
    status.style.display = "none";
    try {
      const resp = await _spCsrfFetch("/api/skillmarket/github/install", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ raw_url: rawUrl })
      });
      const data = await resp.json();
      if (!data.success) throw new Error(data.error || "安装失败");
      status.style.display = "block";
      status.style.color = "var(--success-color, #98c379)";
      status.textContent = `✅ "${data.skill?.name || "Skill"}" 安装成功！前往「我的库」查看`;
      input.value = "";
      await spLoadSkills();
    } catch (e) {
      status.style.display = "block";
      status.style.color = "var(--error-color, #e06c75)";
      status.textContent = `❌ ${e.message}`;
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = "⬇️ 安装";
      }
    }
  };
  (async function() {
    try {
      const resp = await fetch("/api/skills");
      if (!resp.ok) return;
      const data = await resp.json();
      if (data.success && !_spSkills.length) {
        _spSkills = (data.skills || []).filter((s) => s.skill_nature !== "system");
      }
    } catch (_) {
    }
  })();
})();
//# sourceMappingURL=skills-panel-bundle.js.map
