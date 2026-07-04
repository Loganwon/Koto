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
  let _appDocListeners = [];
  const _appOrigAdd = document.addEventListener.bind(document);
  const _appOrigRemove = document.removeEventListener.bind(document);
  document.addEventListener = function(type, listener, options) {
    _appDocListeners.push({ type, listener, options });
    return _appOrigAdd(type, listener, options);
  };
  document.removeEventListener = function(type, listener, options) {
    _appDocListeners = _appDocListeners.filter((e) => !(e.type === type && e.listener === listener));
    return _appOrigRemove(type, listener, options);
  };
  window._cleanupAppListeners = function() {
    let c = 0;
    while (_appDocListeners.length) {
      const e = _appDocListeners.pop();
      try {
        _appOrigRemove(e.type, e.listener, e.options);
        c++;
      } catch (_) {
      }
    }
    document.addEventListener = function(type, listener, options) {
      _appDocListeners.push({ type, listener, options });
      return _appOrigAdd(type, listener, options);
    };
    if (c) console.log("[App] Cleaned up " + c + " listeners");
  };
  window.currentSession = null;
  window.selectedFiles = [];
  window.setupComplete = false;
  window.lockedTaskType = null;
  window.selectedModel = "auto";
  window.enableMiniGame = true;
  window.isScrollLocked = false;
  async function minimizeWindow() {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.minimize) {
      await window.pywebview.api.minimize();
    }
  }
  async function maximizeWindow() {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.maximize) {
      await window.pywebview.api.maximize();
    }
  }
  async function closeWindow() {
    if (window.WA && typeof window.WA.getUnsavedTabs === "function") {
      const unsaved = window.WA.getUnsavedTabs();
      if (unsaved.length > 0) {
        let decision = "discard";
        if (typeof window.WA.showCloseWarning === "function") {
          decision = await window.WA.showCloseWarning(unsaved);
        } else {
          const names = unsaved.map((t) => t.name).join("\n  - ");
          const ok = confirm(`文件助手中有未保存的文件：
  - ${names}

直接关闭将丢失修改，是否继续？`);
          decision = ok ? "discard" : "cancel";
        }
        if (decision === "cancel") return;
      }
    }
    if (window.pywebview && window.pywebview.api && window.pywebview.api.close) {
      await window.pywebview.api.close();
    } else {
      window.close();
    }
  }
  function escapeHtmlLocal(str) {
    return String(str || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function KotoDialog(options) {
    const existing = document.querySelector(".koto-dialog-overlay");
    if (existing) existing.remove();
    const overlay = document.createElement("div");
    overlay.className = "koto-dialog-overlay";
    const dlg = document.createElement("div");
    dlg.className = "koto-dialog";
    const iconMap = { info: "💬", warn: "⚠️", error: "❌" };
    const icon = iconMap[options.type || "info"] || "💬";
    let inputHTML = "";
    if (options.input) {
      inputHTML = `<input class="koto-dialog-input" placeholder="${escapeHtmlLocal(options.inputPlaceholder || "")}" value="${escapeHtmlLocal(options.inputValue || "")}">`;
    }
    dlg.innerHTML = `<div class="koto-dialog-icon">${icon}</div><div class="koto-dialog-title">${escapeHtmlLocal(options.title || "提示")}</div><div class="koto-dialog-msg">${escapeHtmlLocal(options.message || "")}</div>${inputHTML}<div class="koto-dialog-btns">${options.cancelText !== null ? `<button class="koto-dialog-cancel">${escapeHtmlLocal(options.cancelText || "取消")}</button>` : ""}<button class="koto-dialog-confirm">${escapeHtmlLocal(options.confirmText || "确定")}</button></div>`;
    overlay.appendChild(dlg);
    document.body.appendChild(overlay);
    requestAnimationFrame(() => overlay.classList.add("koto-dialog-visible"));
    const inputEl = dlg.querySelector(".koto-dialog-input");
    const close = (confirmed) => {
      overlay.classList.remove("koto-dialog-visible");
      setTimeout(() => overlay.remove(), 250);
      if (confirmed && options.onConfirm) options.onConfirm(inputEl ? inputEl.value : true);
      if (!confirmed && options.onCancel) options.onCancel();
    };
    dlg.querySelector(".koto-dialog-confirm").onclick = () => close(true);
    const cancelBtn = dlg.querySelector(".koto-dialog-cancel");
    if (cancelBtn) cancelBtn.onclick = () => close(false);
    overlay.onclick = (e) => {
      if (e.target === overlay) close(false);
    };
    if (inputEl) {
      inputEl.focus();
      inputEl.onkeydown = (e) => {
        if (e.key === "Enter") close(true);
        if (e.key === "Escape") close(false);
      };
    }
    document.addEventListener("keydown", function _kd(e) {
      if (e.key === "Escape") {
        close(false);
        document.removeEventListener("keydown", _kd);
      }
    });
  }
  function kotoAlert(msg, title) {
    return new Promise((r) => KotoDialog({ title: title || "提示", message: msg, type: "info", cancelText: null, onConfirm: r }));
  }
  function kotoConfirm(msg, title) {
    return new Promise((r) => KotoDialog({ title: title || "确认", message: msg, type: "warn", onConfirm: () => r(true), onCancel: () => r(false) }));
  }
  function kotoPrompt(msg, defaultValue) {
    return new Promise((r) => KotoDialog({ title: "输入", message: msg, input: true, inputValue: defaultValue || "", onConfirm: (v) => r(v), onCancel: () => r(null) }));
  }
  function showNotification(message, type = "info", duration = 3e3) {
    let stack = document.getElementById("notificationStack");
    if (!stack) {
      stack = document.createElement("div");
      stack.id = "notificationStack";
      document.body.appendChild(stack);
    }
    const notification = document.createElement("div");
    notification.className = `notification notification-${type}`;
    notification.innerHTML = `<span>${escapeHtmlLocal(message)}</span><button class="notif-dismiss" onclick="this.parentElement.remove()" title="关闭">×</button>`;
    stack.appendChild(notification);
    setTimeout(() => {
      if (notification.parentElement) {
        notification.classList.add("notif-hiding");
        setTimeout(() => notification.remove(), 300);
      }
    }, duration);
  }
  function hideStartupSplash() {
    const splash = document.getElementById("startupSplash");
    if (!splash) return;
    splash.classList.add("hidden");
    setTimeout(() => splash.remove(), 300);
    document.body.classList.remove("loading");
  }
  async function loadFolderList(path) {
    try {
      const resp = await fetch("/api/browse?path=" + encodeURIComponent(path));
      const data = await resp.json();
      const listEl = document.getElementById("folderList");
      if (!listEl) return;
      window.currentBrowsePath = path;
      const manualInput = document.getElementById("manualPathInput");
      if (manualInput) manualInput.value = path;
      const folders = data.folders || [];
      if (data.error) {
        listEl.innerHTML = `<div style="padding:20px;text-align:center;color:var(--accent-danger);">${escapeHtmlLocal(data.error)}</div>`;
        return;
      }
      if (!folders.length) {
        listEl.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-muted);">此文件夹为空</div>';
        return;
      }
      const parent = data.parent ? `<div class="folder-path-row" onclick="loadFolderList('${String(data.parent).replace(/\\/g, "\\\\").replace(/'/g, "\\'")}')" style="cursor:pointer;padding:6px 10px;color:var(--accent-primary);">.. 上一级</div>` : '<div class="folder-path-row" onclick="loadFolderDrives()" style="cursor:pointer;padding:6px 10px;color:var(--accent-primary);">磁盘与快速访问</div>';
      listEl.innerHTML = parent + folders.map((entry) => {
        const safePath = String(entry.path || "").replace(/\\/g, "\\\\").replace(/'/g, "\\'");
        return `<div class="folder-entry" onclick="loadFolderList('${safePath}')" ondblclick="selectFolderEntry('${safePath}')" style="cursor:pointer;padding:6px 10px;display:flex;align-items:center;gap:8px;"><span>📁</span><span style="flex:1;">${escapeHtmlLocal(entry.name || "")}</span><button onclick="event.stopPropagation();selectFolderEntry('${safePath}')" style="padding:2px 8px;font-size:11px;">选择</button></div>`;
      }).join("");
    } catch (e) {
    }
  }
  async function loadFolderDrives() {
    try {
      const resp = await fetch("/api/browse/drives");
      const data = await resp.json();
      const listEl = document.getElementById("folderList");
      if (!listEl) return;
      const drives = (data.drives || []).map((d) => typeof d === "string" ? { name: d, path: d } : d);
      const quick = data.quick_access || [];
      const entries = [...quick, ...drives];
      listEl.innerHTML = entries.map((entry) => {
        const path = String(entry.path || entry.name || "").replace(/\\/g, "\\\\").replace(/'/g, "\\'");
        const icon = entry.type === "quick" ? "📁" : "💽";
        return `<div class="folder-entry drive-entry" onclick="loadFolderList('${path}')" style="cursor:pointer;padding:8px 10px;"><span>${icon}</span><span>${escapeHtmlLocal(entry.name || entry.path || "")}</span></div>`;
      }).join("");
    } catch (e) {
    }
  }
  function selectFolderEntry(path) {
    if (window.currentBrowseTarget === "setup_workspace") {
      const input = document.getElementById("setupWorkspacePath");
      if (input) input.value = path;
    }
    const manualInput = document.getElementById("manualPathInput");
    if (manualInput) manualInput.value = path;
  }
  function confirmFolderSelection() {
    const path = document.getElementById("manualPathInput")?.value || "";
    if (window.currentBrowseTarget === "setup_workspace") {
      const input = document.getElementById("setupWorkspacePath");
      if (input) input.value = path;
    }
    const modal = document.getElementById("folderModal");
    if (modal) modal.classList.remove("active");
  }
  async function switchToMiniMode() {
    try {
      const response = await csrfFetch("/api/window/switch-to-mini", { method: "POST" });
      const data = await response.json();
      if (data.success) return;
    } catch (error) {
      console.warn("[switchToMiniMode] HTTP fallback:", error);
    }
    if (window.pywebview?.api?.switch_to_mini) {
      try {
        await window.pywebview.api.switch_to_mini();
        return;
      } catch {
      }
    }
    document.body.style.transition = "opacity 0.15s ease-out";
    document.body.style.opacity = "0";
    setTimeout(() => {
      window.location.href = "/mini";
    }, 150);
  }
  function chatSearchNavKey(event) {
    if (event.key === "Enter") {
      event.preventDefault();
      if (event.shiftKey && typeof window.chatSearchPrev === "function") window.chatSearchPrev();
      else if (typeof window.chatSearchNext === "function") window.chatSearchNext();
    } else if (event.key === "Escape" && typeof window.closeChatSearch === "function") {
      window.closeChatSearch();
    }
  }
  let currentArtifact = { code: "", lang: "plaintext", title: "Artifact" };
  function openArtifactPanel() {
    const panel = document.getElementById("artifactsPanel");
    if (!panel) return;
    panel.classList.toggle("active");
  }
  function closeArtifactPanel() {
    const panel = document.getElementById("artifactsPanel");
    if (panel) panel.classList.remove("active");
  }
  function switchArtifactTab(tab) {
    document.querySelectorAll(".artifact-tab-btn").forEach((btn) => btn.classList.toggle("active", btn.dataset.tab === tab));
    const previewEl = document.getElementById("artifactPreview");
    const codeEl = document.getElementById("artifactCode");
    if (previewEl) previewEl.style.display = tab === "preview" ? "" : "none";
    if (codeEl) codeEl.style.display = tab === "code" ? "" : "none";
    if (tab === "preview") renderArtifactPreview();
    else renderArtifactCode();
  }
  function renderArtifactPreview() {
    const el = document.getElementById("artifactPreview");
    if (!el) return;
    const { code, lang } = currentArtifact;
    if (["html", "htm"].includes(lang)) {
      el.innerHTML = '<iframe sandbox="allow-scripts allow-same-origin" style="width:100%;height:calc(100vh - 100px);border:none;border-radius:8px;background:#fff;"></iframe>';
      const iframe = el.querySelector("iframe");
      if (iframe) iframe.srcdoc = code;
      return;
    }
    if (code.trim().startsWith("<svg")) {
      el.innerHTML = `<div style="text-align:center;padding:20px;">${code}</div>`;
      return;
    }
    el.innerHTML = `<pre style="white-space:pre-wrap;margin:0;">${escapeHtmlLocal(code)}</pre>`;
  }
  function renderArtifactCode() {
    const el = document.getElementById("artifactCode");
    if (!el) return;
    el.innerHTML = `<textarea class="artifact-editor" spellcheck="false" style="width:100%;height:calc(100vh - 140px);background:var(--code-bg);color:var(--code-text);border:none;padding:18px;font-family:monospace;font-size:13px;line-height:1.6;resize:none;outline:none;">${escapeHtmlLocal(currentArtifact.code)}</textarea>`;
    const textarea = el.querySelector("textarea");
    if (textarea) textarea.oninput = () => {
      currentArtifact.code = textarea.value;
    };
  }
  async function copyArtifactContent() {
    try {
      await navigator.clipboard.writeText(currentArtifact.code || "");
      showNotification("已复制 Artifact", "success", 1500);
    } catch (error) {
      showNotification("复制失败: " + (error.message || error), "error");
    }
  }
  function downloadArtifact() {
    const extMap = { python: "py", javascript: "js", typescript: "ts", html: "html", css: "css", json: "json", markdown: "md", svg: "svg" };
    const ext = extMap[currentArtifact.lang] || "txt";
    const blob = new Blob([currentArtifact.code || ""], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `artifact.${ext}`;
    a.click();
    URL.revokeObjectURL(url);
  }
  function closeArtifacts() {
    closeArtifactPanel();
  }
  function initProactiveUI() {
  }
  async function sendRating(msgId, userMsg, assistantMsg, taskType, rating, btn) {
    try {
      const resp = await csrfFetch("/api/response/rate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          msg_id: msgId,
          stars: rating === "up" ? 5 : 1,
          session_name: window.currentSession || "default",
          user_input: userMsg,
          ai_response: assistantMsg,
          task_type: taskType || "CHAT"
        })
      });
      const data = await resp.json();
      if (data.success) {
        btn.classList.add("rated");
        setTimeout(() => btn.classList.remove("rated"), 1500);
      }
    } catch (e) {
    }
  }
  async function loadMemories() {
    const listEl = document.getElementById("memoryList");
    if (!listEl) return;
    listEl.innerHTML = '<div class="memory-empty">正在加载记忆...</div>';
    try {
      const response = await fetch("/api/memories");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const memories = await response.json();
      renderMemories(memories);
    } catch (e) {
      listEl.innerHTML = `<div class="memory-empty" style="color:var(--accent-danger)">加载失败: ${e.message}</div>`;
    }
  }
  function renderMemories(memories) {
    const listEl = document.getElementById("memoryList");
    if (!listEl) return;
    if (!memories || memories.length === 0) {
      listEl.innerHTML = '<div class="memory-empty">暂无长期记忆。Koto 会自动记住重要信息，或手动添加。</div>';
      return;
    }
    listEl.innerHTML = memories.map((m) => `<div class="memory-item"><div class="memory-content"><div>${escapeHtmlLocal(m.content)}</div><div class="memory-meta">${m.created_at} · ${m.category}</div></div><button class="memory-delete-btn" onclick="deleteMemory(${m.id})" title="忘记"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg></button></div>`).join("");
  }
  async function addNewMemory() {
    const input = document.getElementById("newMemoryInput");
    const content = input.value.trim();
    if (!content) return;
    try {
      const response = await csrfFetch("/api/memories", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content, category: "user_preference" }) });
      if (response.ok) {
        input.value = "";
        loadMemories();
      } else {
        showNotification(`添加失败 (${response.status})`, "error");
      }
    } catch (e) {
      showNotification(`添加失败: ${e.message}`, "error");
    }
  }
  async function deleteMemory(id) {
    if (!confirm("确定要忘记这条记忆吗？")) return;
    try {
      const response = await csrfFetch(`/api/memories/${id}`, { method: "DELETE" });
      if (response.ok) {
        loadMemories();
      } else {
        showNotification(`删除失败 (${response.status})`, "error");
      }
    } catch (e) {
      showNotification(`删除失败: ${e.message}`, "error");
    }
  }
  async function importProfileMemories() {
    const btn = document.querySelector('[onclick="importProfileMemories()"]');
    const origText = btn ? btn.textContent : "";
    if (btn) {
      btn.disabled = true;
      btn.textContent = "⏳ 导入中...";
    }
    try {
      const response = await csrfFetch("/api/memories/import-profile", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      const result = await response.json();
      if (result.success) {
        loadMemories();
        if (btn) {
          btn.textContent = `✅ 导入了 ${result.added} 条`;
        }
        setTimeout(() => {
          if (btn) {
            btn.disabled = false;
            btn.textContent = origText;
          }
        }, 3e3);
      } else {
        showNotification(`导入失败: ${result.error || "未知错误"}`, "error");
        if (btn) {
          btn.disabled = false;
          btn.textContent = origText;
        }
      }
    } catch (e) {
      showNotification(`导入失败: ${e.message}`, "error");
      if (btn) {
        btn.disabled = false;
        btn.textContent = origText;
      }
    }
  }
  async function batchExtractMemories() {
    const btn = document.querySelector('[onclick="batchExtractMemories()"]');
    const origText = btn ? btn.textContent : "";
    if (btn) {
      btn.disabled = true;
      btn.textContent = "⏳ 提取中（约30秒）...";
    }
    try {
      const response = await csrfFetch("/api/memories/batch-extract", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ max_turns: 60, max_files: 10 }) });
      const result = await response.json();
      if (result.success) {
        if (btn) {
          btn.textContent = "✅ 后台提取中...";
        }
        setTimeout(() => {
          loadMemories();
          if (btn) {
            btn.disabled = false;
            btn.textContent = origText;
          }
        }, 3e4);
      } else {
        showNotification(`提取失败: ${result.error || "未知错误"}`, "error");
        if (btn) {
          btn.disabled = false;
          btn.textContent = origText;
        }
      }
    } catch (e) {
      showNotification(`提取失败: ${e.message}`, "error");
      if (btn) {
        btn.disabled = false;
        btn.textContent = origText;
      }
    }
  }
  async function loadShadowMemories() {
    const listEl = document.getElementById("shadowMemoryList");
    if (!listEl) return;
    listEl.innerHTML = '<div class="memory-empty" style="font-size:12px;color:var(--text-muted);">正在加载...</div>';
    try {
      const resp = await fetch("/api/shadow/memories");
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const data = await resp.json();
      if (!data.ok) throw new Error(data.error || "加载失败");
      renderShadowMemories(data.data || []);
    } catch (e) {
      listEl.innerHTML = `<div class="memory-empty" style="font-size:12px;color:var(--accent-danger)">加载失败: ${e.message}</div>`;
    }
  }
  function renderShadowMemories(memories) {
    const listEl = document.getElementById("shadowMemoryList");
    if (!listEl) return;
    if (!memories || memories.length === 0) {
      listEl.innerHTML = '<div class="memory-empty" style="font-size:12px;color:var(--text-muted);">暂无影子记忆。</div>';
      return;
    }
    const sorted = [...memories].sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
    listEl.innerHTML = sorted.map((m) => `<div class="memory-item"><div><div>${escapeHtmlLocal(m.content)}</div><div>${escapeHtmlLocal(m.created_at || "")} · ${m.source === "shadow" ? "🤖 自动" : "✍️ 手动"} · ${escapeHtmlLocal(m.category || "")}</div></div><button onclick="deleteShadowMemory('${m.id}')">✕</button></div>`).join("");
  }
  async function deleteShadowMemory(id) {
    try {
      await csrfFetch(`/api/shadow/memories/${id}`, { method: "DELETE" });
      loadShadowMemories();
    } catch (e) {
    }
  }
  async function addShadowMemory() {
    const input = document.getElementById("newShadowMemoryInput");
    const content = input.value.trim();
    if (!content) return;
    try {
      const resp = await csrfFetch("/api/shadow/memories", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content }) });
      if (resp.ok) {
        input.value = "";
        loadShadowMemories();
      } else {
        showNotification("添加失败", "error");
      }
    } catch (e) {
      showNotification("添加失败", "error");
    }
  }
  let _shadowPending = [];
  let _shadowCurrentIdx = 0;
  let _pendingShadowContext = null;
  async function shadowPollPending() {
    try {
      const resp = await fetch("/api/shadow/pending");
      if (!resp.ok) return;
      const data = await resp.json();
      if (!data.ok) return;
      _shadowPending = data.data || [];
      _shadowCurrentIdx = 0;
      _shadowUpdateBanner();
      _shadowUpdateBadge();
    } catch (e) {
    }
  }
  function _shadowUpdateBadge() {
    const badge = document.getElementById("shadowBadge");
    if (!badge) return;
    const count = _shadowPending.length;
    badge.textContent = String(count);
    badge.style.display = count > 0 ? "" : "none";
  }
  function _shadowUpdateBanner() {
    const banner = document.getElementById("shadowBanner");
    if (!banner) return;
    if (!_shadowPending.length) {
      banner.style.display = "none";
      const rb = document.getElementById("shadowRetryBtn");
      if (rb) rb.remove();
      return;
    }
    const msg = _shadowPending[_shadowCurrentIdx];
    if (!msg) return;
    banner.style.display = "flex";
    const textEl = document.getElementById("shadowBannerText");
    if (textEl) textEl.textContent = msg.content;
    const countEl = document.getElementById("shadowBannerCount");
    const hasMulti = _shadowPending.length > 1;
    if (countEl) countEl.textContent = hasMulti ? `消息 ${_shadowCurrentIdx + 1} / ${_shadowPending.length}` : "";
    const navBtns = banner.querySelectorAll("button");
    navBtns.forEach((btn) => {
      if (btn.textContent === "‹" || btn.textContent === "›") btn.style.display = hasMulti ? "" : "none";
    });
    banner.dataset.msgId = msg.id;
    const existingRetryBtn = document.getElementById("shadowRetryBtn");
    if (existingRetryBtn) existingRetryBtn.remove();
    if (msg.type === "failed_retry" && msg.task_id) {
      const retryBtn = document.createElement("button");
      retryBtn.id = "shadowRetryBtn";
      retryBtn.textContent = "🔄 立即重试";
      retryBtn.style.cssText = "padding:4px 12px;border:none;border-radius:6px;background:#10b981;color:#fff;cursor:pointer;font-size:12px;flex-shrink:0;";
      retryBtn.addEventListener("click", () => shadowRetryFailedTask(msg.task_id, msg.id));
      banner.appendChild(retryBtn);
    }
  }
  async function shadowRetryFailedTask(taskId, msgId) {
    try {
      const resp = await fetch(`/api/shadow/retry-context/${encodeURIComponent(taskId)}`);
      const data = await resp.json();
      if (!data.ok || !data.data?.original_text) {
        showNotification("获取不到原始请求内容", "warning");
        return;
      }
      const originalText = data.data.original_text;
      try {
        await csrfFetch(`/api/shadow/dismiss/${msgId}`, { method: "POST" });
      } catch (e) {
      }
      _shadowPending = _shadowPending.filter((m) => m.id !== msgId);
      _shadowCurrentIdx = Math.min(_shadowCurrentIdx, Math.max(0, _shadowPending.length - 1));
      _shadowUpdateBanner();
      _shadowUpdateBadge();
      const inputEl = document.getElementById("messageInput");
      if (inputEl) {
        inputEl.value = originalText;
        inputEl.dispatchEvent(new Event("input"));
        setTimeout(() => document.getElementById("sendBtn")?.click(), 80);
      } else {
        showNotification("请在对话框中重新输入：" + originalText.slice(0, 60), "info", 5e3);
      }
    } catch (e) {
      showNotification("重试失败", "error");
    }
  }
  function shadowNextMsg() {
    if (_shadowPending.length < 2) return;
    _shadowCurrentIdx = (_shadowCurrentIdx + 1) % _shadowPending.length;
    _shadowUpdateBanner();
  }
  function shadowPrevMsg() {
    if (_shadowPending.length < 2) return;
    _shadowCurrentIdx = (_shadowCurrentIdx - 1 + _shadowPending.length) % _shadowPending.length;
    _shadowUpdateBanner();
  }
  async function shadowDismissCurrent() {
    const banner = document.getElementById("shadowBanner");
    const msgId = banner?.dataset?.msgId;
    if (!msgId) return;
    try {
      await csrfFetch(`/api/shadow/dismiss/${msgId}`, { method: "POST" });
    } catch (e) {
    }
    _shadowPending = _shadowPending.filter((m) => m.id !== msgId);
    _shadowCurrentIdx = Math.min(_shadowCurrentIdx, Math.max(0, _shadowPending.length - 1));
    _shadowUpdateBanner();
    _shadowUpdateBadge();
  }
  async function shadowDismissAll() {
    try {
      await csrfFetch("/api/shadow/dismiss-all", { method: "POST" });
    } catch (e) {
    }
    _shadowPending = [];
    _shadowUpdateBanner();
    _shadowUpdateBadge();
  }
  function shadowReply() {
    const banner = document.getElementById("shadowBanner");
    const msgId = banner?.dataset?.msgId;
    const msg = _shadowPending.find((m) => m.id === msgId);
    if (!msg) return;
    _pendingShadowContext = { id: msg.id, content: msg.content, type: msg.type };
    _showShadowReplyHint(msg.content);
    const input = document.getElementById("messageInput");
    if (input) {
      input.value = "";
      input.focus();
    }
    shadowDismissCurrent();
  }
  function _showShadowReplyHint(content) {
  }
  function _cancelShadowReply() {
    _pendingShadowContext = null;
    const hint = document.getElementById("shadowReplyHint");
    if (hint) hint.remove();
  }
  function openShadowPanel() {
    if (typeof window.openSettings === "function") {
      window.openSettings();
      setTimeout(() => {
        const el = document.querySelector(".settings-section:has(#shadowWatcherToggle)");
        if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 200);
    }
  }
  async function loadShadowStatus() {
    try {
      const resp = await fetch("/api/shadow/status");
      if (!resp.ok) return;
      const data = await resp.json();
      if (!data.ok) return;
      const s = data.data;
      const toggle = document.getElementById("shadowWatcherToggle");
      const label = document.getElementById("shadowWatcherLabel");
      if (toggle) toggle.checked = !!s.enabled;
      if (label) label.textContent = s.enabled ? "影子追踪已开启" : "影子追踪已关闭";
      const cardsEl = document.getElementById("shadowSummaryCards");
      if (cardsEl) {
        cardsEl.style.display = "";
        const topics = (s.top_topics || []).map((t) => `<span style="background:var(--bg-hover);border-radius:4px;padding:2px 6px;font-size:11px;">${escapeHtmlLocal(t.topic)} ×${t.count}</span>`).join(" ");
        cardsEl.innerHTML = `<div style="display:flex;flex-wrap:wrap;gap:10px;font-size:12px;color:var(--text-muted);"><span>📊 已观察 <strong>${s.total_observations || 0}</strong> 次对话</span><span>🔥 连续 <strong>${s.streak_days || 0}</strong> 天</span><span>📌 开放任务 <strong>${s.open_tasks_count || 0}</strong> 项</span><span>💬 待推送 <strong>${s.pending_messages || 0}</strong> 条</span></div>${topics ? `<div style="margin-top:6px;display:flex;flex-wrap:wrap;gap:4px;">${topics}</div>` : ""}`;
      }
      await loadShadowOpenTasks();
      await loadShadowMemories();
    } catch (e) {
    }
  }
  async function toggleShadowWatcher(enabled) {
    const label = document.getElementById("shadowWatcherLabel");
    try {
      const resp = await csrfFetch("/api/shadow/toggle", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled }) });
      const data = await resp.json();
      if (!data.ok) throw new Error(data.error || "操作失败");
      if (label) label.textContent = enabled ? "影子追踪已开启" : "影子追踪已关闭";
    } catch (e) {
      showNotification("切换失败: " + e.message, "error");
      const toggle = document.getElementById("shadowWatcherToggle");
      if (toggle) toggle.checked = !enabled;
    }
  }
  async function shadowForceTick() {
    try {
      const resp = await csrfFetch("/api/shadow/tick", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ force: true }) });
      const data = await resp.json();
      if (!data.ok) throw new Error(data.error || "检查失败");
      const count = (data.data?.messages || []).length;
      if (count > 0) {
        await shadowPollPending();
        showNotification(`✅ 检查完成，生成 ${count} 条主动消息。`, "success");
      } else {
        showNotification("✅ 检查完成，当前暂无需要主动推送的内容。", "info");
      }
      await loadShadowStatus();
    } catch (e) {
      showNotification("检查失败: " + e.message, "error");
    }
  }
  async function loadShadowOpenTasks() {
    const el = document.getElementById("shadowOpenTasksList");
    if (!el) return;
    try {
      const resp = await fetch("/api/shadow/open-tasks");
      const data = await resp.json();
      if (!data.ok || !data.data?.length) {
        el.innerHTML = "";
        return;
      }
      el.innerHTML = data.data.slice(0, 5).map((t) => `<div style="display:flex;align-items:center;gap:6px;margin-top:4px;font-size:12px;"><span>📌</span><span style="flex:1;">${escapeHtmlLocal(t.text.slice(0, 60))}${t.text.length > 60 ? "…" : ""}</span><button onclick="shadowMarkTaskDone('${t.id}')">✓</button></div>`).join("");
    } catch (e) {
      el.innerHTML = "";
    }
  }
  async function shadowMarkTaskDone(taskId) {
    try {
      await csrfFetch(`/api/shadow/dismiss-task/${taskId}`, { method: "POST" });
      await loadShadowOpenTasks();
      await loadShadowStatus();
    } catch (e) {
    }
  }
  function handleKeyDown(event) {
    const slash = document.getElementById("slashPalette");
    if (slash && slash.style.display !== "none") {
      [...slash.querySelectorAll(".slash-item")];
      if (event.key === "ArrowDown") {
        event.preventDefault();
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        return;
      }
      if (event.key === "Escape") {
        if (typeof window.hideSlashPalette === "function") window.hideSlashPalette();
        return;
      }
    }
    const suggest = document.getElementById("atFileSuggest");
    if (suggest && suggest.style.display !== "none") {
      if (event.key === "Escape") {
        if (typeof window.hideAtSuggest === "function") window.hideAtSuggest();
        return;
      }
    }
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage(event);
    }
  }
  function handleGlobalKeyDown(e) {
    if (document.querySelector(".modal-overlay.active")) return;
    if (e.key === "Escape" && closeActiveSidePanel()) {
      e.preventDefault();
      return;
    }
    if (e.key === "Escape" && window.currentSession && typeof window.isSessionGenerating === "function" && window.isSessionGenerating(window.currentSession)) {
      e.preventDefault();
      document.getElementById("sendBtn")?.click();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key === "k") {
      e.preventDefault();
      if (typeof window.showNewSessionModal === "function") window.showNewSessionModal();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key === "b") {
      e.preventDefault();
      if (typeof window.toggleSidebar === "function") window.toggleSidebar();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key === ",") {
      e.preventDefault();
      if (typeof window.openSettings === "function") window.openSettings();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key === "/") {
      e.preventDefault();
      if (typeof window.toggleHotkeySheet === "function") window.toggleHotkeySheet();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key === "f") {
      if (document.activeElement?.id !== "messageInput") {
        e.preventDefault();
        const hasMessages = document.querySelectorAll("#chatMessages .message").length > 0;
        if (hasMessages) {
          if (typeof window.openChatSearch === "function") window.openChatSearch();
        } else {
          if (typeof window.toggleSidebarSearch === "function") window.toggleSidebarSearch();
        }
      }
      return;
    }
  }
  async function showAgentConfirmDialog(toolName, toolArgs, reason) {
    return new Promise((resolve) => {
      const TIMEOUT = 60;
      let remaining = TIMEOUT;
      const overlay = document.createElement("div");
      overlay.className = "agent-dialog-overlay";
      const dialog = document.createElement("div");
      dialog.className = "agent-confirm-dialog";
      const argsHtml = Object.entries(toolArgs).map(([key, value]) => `<div><strong>${key}:</strong> ${escapeHtmlLocal(String(value))}</div>`).join("");
      dialog.innerHTML = `<h3 style="margin-top:0;">🤖 Agent需要确认</h3><p>${escapeHtmlLocal(reason || "即将执行以下操作：")}</p><div class="agent-args"><div class="tool-label" style="margin-bottom:8px;">🔧 工具: ${escapeHtmlLocal(toolName)}</div><div>${argsHtml}</div></div><div class="agent-confirm-countdown" id="confirm-countdown">${remaining}s 后自动跳过</div><div style="display:flex;gap:12px;justify-content:flex-end;margin-top:16px;"><button id="agent-confirm-no" style="padding:8px 20px;border-radius:6px;border:1px solid var(--border-color);background:transparent;cursor:pointer;">取消</button><button id="agent-confirm-yes" style="padding:8px 20px;border-radius:6px;border:none;background:#4CAF50;color:white;font-weight:bold;cursor:pointer;">确认执行</button></div>`;
      overlay.appendChild(dialog);
      document.body.appendChild(overlay);
      const cleanup = () => {
        if (document.body.contains(overlay)) document.body.removeChild(overlay);
      };
      const timer = setInterval(() => {
        remaining--;
        const countdownEl = document.getElementById("confirm-countdown");
        if (countdownEl) countdownEl.textContent = `${remaining}s 后自动跳过`;
        if (remaining <= 0) {
          clearInterval(timer);
          cleanup();
          resolve({ confirmed: false, message: `⏰ 确认超时，已跳过 \`${toolName}\`` });
        }
      }, 1e3);
      const yesBtn = document.getElementById("agent-confirm-yes");
      const noBtn = document.getElementById("agent-confirm-no");
      if (yesBtn) yesBtn.onclick = () => {
        clearInterval(timer);
        cleanup();
        resolve({ confirmed: true, message: `✅ 已确认执行 \`${toolName}\`` });
      };
      if (noBtn) noBtn.onclick = () => {
        clearInterval(timer);
        cleanup();
        resolve({ confirmed: false, message: `❌ 已取消 \`${toolName}\`` });
      };
      overlay.onclick = (e) => {
        if (e.target === overlay) {
          clearInterval(timer);
          cleanup();
          resolve({ confirmed: false, message: `❌ 已取消 \`${toolName}\`` });
        }
      };
    });
  }
  async function showAgentChoiceDialog(question, options) {
    return new Promise((resolve) => {
      const overlay = document.createElement("div");
      overlay.className = "agent-dialog-overlay";
      const dialog = document.createElement("div");
      dialog.className = "agent-choice-dialog";
      const optionsHtml = options.map((opt, idx) => `<button class="agent-choice-option" data-value="${escapeHtmlLocal(opt.value)}">${idx + 1}. ${escapeHtmlLocal(opt.label)}</button>`).join("");
      dialog.innerHTML = `<h3 style="margin-top:0;">🤖 Agent需要您的选择</h3><p>${escapeHtmlLocal(question)}</p><div>${optionsHtml}</div><div style="text-align:center;margin-top:16px;"><button id="agent-choice-cancel">取消</button></div>`;
      overlay.appendChild(dialog);
      document.body.appendChild(overlay);
      dialog.querySelectorAll(".agent-choice-option").forEach((btn, idx) => {
        btn.onclick = () => {
          const selected = options[idx];
          document.body.removeChild(overlay);
          resolve({ displayText: `✅ 您选择了: **${selected.label}**`, selected: selected.value });
        };
      });
      const cancelBtn = document.getElementById("agent-choice-cancel");
      if (cancelBtn) cancelBtn.onclick = () => {
        document.body.removeChild(overlay);
        resolve({ displayText: `❌ 已取消选择`, selected: "__cancelled__" });
      };
      overlay.onclick = (e) => {
        if (e.target === overlay) {
          document.body.removeChild(overlay);
          resolve(null);
        }
      };
    });
  }
  async function extractMeetingActions() {
    const transcript = prompt("请粘贴会议转录/纪要文本（建议 300 字以上）:");
    if (!transcript || !transcript.trim()) return;
    const btn = document.getElementById("meetingActionsBtn");
    try {
      if (btn) {
        btn.disabled = true;
        btn.textContent = "⏳ 提取中";
      }
      const resp = await csrfFetch("/api/speech/extract-actions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: transcript }) });
      const data = await resp.json();
      if (!resp.ok || !data.success) throw new Error(data.error || "行动项提取失败");
      const summary = (data.summary || "").trim();
      const decisions = Array.isArray(data.decisions) ? data.decisions : [];
      const actions = Array.isArray(data.action_items) ? data.action_items : [];
      const esc = (s) => (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      let actionsHtml = "";
      if (actions.length) {
        actionsHtml = '<table class="meeting-actions-table"><thead><tr><th>任务</th><th>负责人</th><th>截止日期</th><th>优先级</th></tr></thead><tbody>' + actions.map((item) => `<tr><td>${esc(item.task || "")}</td><td>${esc(item.owner || "待定")}</td><td>${esc(item.due_date || "待定")}</td><td>${(item.priority || "medium").toLowerCase() === "high" ? "高" : (item.priority || "medium").toLowerCase() === "low" ? "低" : "中"}</td></tr>`).join("") + "</tbody></table>";
      }
      const html = `<div class="meeting-actions-card"><div class="meeting-actions-header">📝 会议提炼结果</div><div><strong>摘要</strong><p>${esc(summary)}</p></div>${decisions.length ? "<div><strong>关键决策</strong><ul>" + decisions.map((d) => `<li>${esc(d)}</li>`).join("") + "</ul></div>" : ""}<div><strong>行动项</strong>${actionsHtml || "（未提取到）"}</div></div>`;
      const msgDiv = document.createElement("div");
      msgDiv.className = "message assistant-message";
      msgDiv.innerHTML = html;
      const chatMessages = document.getElementById("chatMessages");
      const welcome = document.getElementById("welcomeScreen");
      if (welcome) welcome.style.display = "none";
      if (chatMessages) chatMessages.appendChild(msgDiv);
      if (typeof window.scrollToBottomForce === "function") window.scrollToBottomForce();
      showNotification("会议行动项提取完成", "success", 1800);
    } catch (err) {
      showNotification(`会议提炼失败: ${err.message || err}`, "error", 2600);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = "📝 会议提炼";
      }
    }
  }
  async function createReminderFromAction(task, dueDate, btnEl) {
    let isoTime = null;
    const dateMatch = dueDate && dueDate.match(/(\d{4})-(\d{2})-(\d{2})/);
    if (dateMatch) isoTime = `${dateMatch[0]}T09:00:00`;
    try {
      if (btnEl) {
        btnEl.disabled = true;
        btnEl.textContent = "⏳";
      }
      const body = { title: `📋 ${task}`, message: `会议行动项：${task}（截止：${dueDate}）`, icon: "task" };
      if (isoTime) body.time = isoTime;
      else body.seconds = 3600;
      const resp = await csrfFetch("/api/reminders/add", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const data = await resp.json();
      if (!resp.ok || !data.success) throw new Error(data.error || "添加失败");
      if (btnEl) {
        btnEl.textContent = "✅ 已创建";
        btnEl.classList.add("reminder-done");
      }
      showNotification(`提醒已创建：${task}`, "success", 2e3);
    } catch (err) {
      if (btnEl) {
        btnEl.disabled = false;
        btnEl.textContent = "📅 创建提醒";
      }
      showNotification(`创建提醒失败: ${err.message}`, "error");
    }
  }
  async function generateMorningBrief() {
    try {
      const btn = document.getElementById("morningBriefBtn");
      if (btn) {
        btn.disabled = true;
        btn.textContent = "⏳ 生成中";
      }
      const resp = await fetch("/api/telegram/brief/preview");
      const data = await resp.json();
      if (!resp.ok || data.error || !data.brief) throw new Error(data.error || "简报生成失败");
      const chatMessages = document.getElementById("chatMessages");
      const welcome = document.getElementById("welcomeScreen");
      if (welcome) welcome.style.display = "none";
      if (chatMessages) chatMessages.insertAdjacentHTML("beforeend", window.renderMessage?.("assistant", data.brief, { task: "MORNING_BRIEF" }) || "");
      if (typeof window.scrollToBottomForce === "function") window.scrollToBottomForce();
      showNotification("晨间简报已生成", "success", 1800);
    } catch (err) {
      showNotification(`晨间简报生成失败: ${err.message || err}`, "error", 2600);
    } finally {
      const btn = document.getElementById("morningBriefBtn");
      if (btn) {
        btn.disabled = false;
        btn.textContent = "🌅 简报";
      }
    }
  }
  const suggestionState = {
    filePath: "",
    suggestions: [],
    abort: null
  };
  function openSuggestionPanel(filePath, requirement) {
    const panel = document.getElementById("suggestionPanelModal");
    if (!panel) return;
    panel.style.display = "flex";
    loadSuggestions(filePath, requirement);
  }
  async function loadSuggestions(filePath, requirement) {
    suggestionState.filePath = filePath;
    suggestionState.suggestions = [];
    if (suggestionState.abort) suggestionState.abort.abort();
    suggestionState.abort = new AbortController();
    const list = document.getElementById("suggestionList");
    const progress = document.getElementById("suggestionProgressText");
    const fill = document.getElementById("suggestionProgressFill");
    if (list) list.innerHTML = '<div class="suggestion-empty"><p>正在分析文档...</p></div>';
    if (progress) progress.textContent = "准备分析...";
    if (fill) fill.style.width = "0%";
    try {
      const resp = await csrfFetch("/api/document/suggest-stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_path: filePath, requirement }),
        signal: suggestionState.abort.signal
      });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      if (!resp.body) throw new Error("浏览器不支持流式响应");
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() || "";
        for (const raw of events) handleSuggestionSse(raw);
      }
      renderSuggestionList();
      if (progress) progress.textContent = suggestionState.suggestions.length ? "分析完成" : "暂无修改建议";
      if (fill) fill.style.width = "100%";
    } catch (e) {
      if (e.name === "AbortError") return;
      if (list) list.innerHTML = `<div class="suggestion-empty"><p>分析失败：${escapeHtmlLocal(e.message || String(e))}</p></div>`;
    }
  }
  function applySuggestion(action) {
  }
  function handleSuggestionSse(raw) {
    const lines = raw.split("\n");
    let eventType = "";
    let eventData = "";
    for (const line of lines) {
      if (line.startsWith("event: ")) eventType = line.slice(7).trim();
      else if (line.startsWith("data: ")) eventData += line.slice(6);
    }
    if (!eventData) return;
    let data;
    try {
      data = JSON.parse(eventData);
    } catch {
      return;
    }
    const progress = document.getElementById("suggestionProgressText");
    const fill = document.getElementById("suggestionProgressFill");
    if (eventType === "progress") {
      if (progress) progress.textContent = data.message || data.status || "分析中...";
      if (fill && data.progress != null) fill.style.width = `${Math.max(0, Math.min(100, Number(data.progress)))}%`;
      return;
    }
    if (eventType === "suggestion" || data.suggestion) {
      const item = data.suggestion || data;
      item.id = item.id || `suggestion-${suggestionState.suggestions.length + 1}`;
      item.accepted = item.accepted !== false;
      suggestionState.suggestions.push(item);
      renderSuggestionList();
    }
  }
  function renderSuggestionList() {
    const list = document.getElementById("suggestionList");
    if (!list) return;
    if (!suggestionState.suggestions.length) {
      list.innerHTML = '<div class="suggestion-empty"><p>暂无修改建议</p></div>';
      return;
    }
    list.innerHTML = suggestionState.suggestions.map((s, index) => {
      const title = s.title || s.type || `建议 ${index + 1}`;
      const original = s.original_text || s.original || s["原文"] || "";
      const replacement = s.suggested_text || s.replacement || s["修改"] || "";
      const reason = s.reason || s.description || s.explanation || "";
      return `<div class="suggestion-card ${s.accepted ? "accepted" : "rejected"}" id="suggestion-${escapeHtmlLocal(s.id)}"><div class="suggestion-title">${escapeHtmlLocal(title)}</div><div class="suggestion-desc">${escapeHtmlLocal(reason)}</div>${original ? `<div class="suggestion-desc">原文：${escapeHtmlLocal(original)}</div>` : ""}${replacement ? `<div class="suggestion-desc">修改：${escapeHtmlLocal(replacement)}</div>` : ""}<div class="suggestion-actions"><button class="btn-sm btn-accept ${s.accepted ? "active" : ""}" onclick="acceptSuggestion('${escapeHtmlLocal(s.id)}')">接受</button><button class="btn-sm btn-reject ${!s.accepted ? "active" : ""}" onclick="rejectSuggestion('${escapeHtmlLocal(s.id)}')">拒绝</button></div></div>`;
    }).join("");
  }
  function acceptSuggestion(id) {
    const item = suggestionState.suggestions.find((s) => String(s.id) === String(id));
    if (item) {
      item.accepted = true;
      renderSuggestionList();
    }
  }
  function rejectSuggestion(id) {
    const item = suggestionState.suggestions.find((s) => String(s.id) === String(id));
    if (item) {
      item.accepted = false;
      renderSuggestionList();
    }
  }
  function acceptAllSuggestions() {
    suggestionState.suggestions.forEach((s) => {
      s.accepted = true;
    });
    renderSuggestionList();
  }
  function rejectAllSuggestions() {
    suggestionState.suggestions.forEach((s) => {
      s.accepted = false;
    });
    renderSuggestionList();
  }
  function closeSuggestionPanel() {
    if (suggestionState.abort) suggestionState.abort.abort();
    document.getElementById("suggestionPanelModal").style.display = "none";
  }
  async function applySuggestions() {
    const accepted = suggestionState.suggestions.filter((s) => s.accepted);
    if (!accepted.length) {
      showNotification("请先选择要接受的修改", "warning");
      return;
    }
    try {
      const resp = await csrfFetch("/api/document/apply-suggestions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_path: suggestionState.filePath, suggestions: accepted })
      });
      const result = await resp.json();
      if (!resp.ok || !result.success) throw new Error(result.error || "应用失败");
      showNotification(`已应用 ${result.applied_count || accepted.length} 处修改`, "success", 4e3);
      closeSuggestionPanel();
    } catch (error) {
      showNotification("应用失败: " + (error.message || error), "error");
    }
  }
  const PROACTIVE_USER_ID = "default";
  function openTriggerPanel() {
    const modal = document.getElementById("triggerPanelModal");
    if (modal) modal.style.display = "flex";
  }
  function closeTriggerPanel() {
    const modal = document.getElementById("triggerPanelModal");
    if (modal) modal.style.display = "none";
  }
  async function startTriggerMonitoring() {
    const interval = parseInt(document.getElementById("triggerIntervalInput")?.value || "300", 10) || 300;
    try {
      await fetch("/api/triggers/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: PROACTIVE_USER_ID, interval })
      });
      showNotification("触发监控已启动", "success", 1500);
    } catch (error) {
      showNotification("启动失败: " + (error.message || error), "error");
    }
  }
  async function stopTriggerMonitoring() {
    try {
      await csrfFetch("/api/triggers/stop", { method: "POST" });
      showNotification("触发监控已停止", "warning", 1500);
    } catch (error) {
      showNotification("停止失败: " + (error.message || error), "error");
    }
  }
  async function runTriggerEvaluation() {
    const decisionEl = document.getElementById("triggerDecision");
    if (decisionEl) decisionEl.textContent = "评估中...";
    try {
      const response = await csrfFetch("/api/triggers/evaluate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: PROACTIVE_USER_ID, execute: false })
      });
      const data = await response.json();
      if (!response.ok || data.success === false) throw new Error(data.error || "评估失败");
      const decision = data.decision || data.data || {};
      if (decisionEl) {
        decisionEl.innerHTML = decision.reason ? `<strong>${escapeHtmlLocal(decision.reason)}</strong><br>类型: ${escapeHtmlLocal(decision.interaction_type || "")} · 优先级: ${escapeHtmlLocal(decision.priority || "")}` : "暂无触发结果";
      }
    } catch (error) {
      if (decisionEl) decisionEl.textContent = "评估失败: " + (error.message || error);
    }
  }
  function openCatalogWizard() {
    const modal = document.getElementById("catalogWizardModal") || document.getElementById("catalogScheduleModal");
    if (modal) modal.style.display = "flex";
  }
  function closeCatalogWizard() {
    const modal = document.getElementById("catalogWizardModal") || document.getElementById("catalogScheduleModal");
    if (modal) modal.style.display = "none";
  }
  const closeCatalogScheduleWizard = closeCatalogWizard;
  async function saveCatalogScheduleWizard() {
    const sourceDir = (document.getElementById("cwSourceDir")?.value || "").trim();
    const hours = Math.max(1, parseInt(document.getElementById("cwIntervalHours")?.value || "6", 10) || 6);
    if (!sourceDir) {
      showNotification("请输入要整理的目录路径", "warning");
      return;
    }
    try {
      const resp = await csrfFetch("/api/jobs/triggers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: "下载目录自动整理",
          trigger_type: "interval",
          job_type: "auto_catalog",
          job_payload: { source_dir: sourceDir },
          enabled: true,
          config: { interval_seconds: hours * 3600 }
        })
      });
      const data = await resp.json();
      if (!resp.ok || data.ok === false) throw new Error(data.error || "创建失败");
      closeCatalogWizard();
      if (typeof window.loadTriggers === "function") await window.loadTriggers();
      showNotification("定时整理已启用", "success");
    } catch (error) {
      showNotification("启用失败: " + (error.message || error), "error");
    }
  }
  async function openCreateBindingModal() {
    const select = document.getElementById("cbSkillId");
    if (select) {
      let skills = [];
      if (typeof window.getSpSkills === "function") skills = window.getSpSkills() || [];
      if (!skills.length) {
        try {
          const resp = await fetch("/api/skills");
          const data = await resp.json();
          skills = data.skills || data.data || [];
        } catch {
        }
      }
      select.innerHTML = skills.map((skill) => `<option value="${escapeHtmlLocal(skill.id)}">${escapeHtmlLocal((skill.icon || "") + " " + (skill.name || skill.id))}</option>`).join("") || '<option value="">请先加载 Skill 列表</option>';
    }
    const patterns = document.getElementById("cbPatterns");
    const turns = document.getElementById("cbTurns");
    if (patterns) patterns.value = "";
    if (turns) turns.value = "1";
    const modal = document.getElementById("createBindingModal");
    if (modal) modal.style.display = "flex";
  }
  function closeCreateBindingModal() {
    const modal = document.getElementById("createBindingModal");
    if (modal) modal.style.display = "none";
  }
  async function saveCreateBinding() {
    const skillId = (document.getElementById("cbSkillId")?.value || "").trim();
    const rawPatterns = (document.getElementById("cbPatterns")?.value || "").trim();
    const turns = parseInt(document.getElementById("cbTurns")?.value || "1", 10) || 1;
    const patterns = rawPatterns.split(/[,，]+/).map((s) => s.trim()).filter(Boolean);
    if (!skillId) {
      showNotification("请选择一个 Skill", "warning");
      return;
    }
    if (!patterns.length) {
      showNotification("请至少输入一个关键词", "warning");
      return;
    }
    try {
      const resp = await csrfFetch(`/api/skills/${encodeURIComponent(skillId)}/bindings/intent`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ patterns, auto_disable_after_turns: turns })
      });
      const data = await resp.json();
      if (!resp.ok || data.success === false) throw new Error(data.error || "创建失败");
      closeCreateBindingModal();
      if (typeof window.loadSkillBindings === "function") await window.loadSkillBindings();
      showNotification("意图绑定已创建", "success");
    } catch (error) {
      showNotification("创建失败: " + (error.message || error), "error");
    }
  }
  function openCreateTriggerModal() {
    const setValue = (id, value) => {
      const el = document.getElementById(id);
      if (el) el.value = value;
    };
    setValue("ctName", "");
    setValue("ctType", "interval");
    setValue("ctJobType", "agent_query");
    setValue("ctQuery", "");
    setValue("ctIntervalSecs", "3600");
    setValue("ctCronTime", "09:00");
    onCreateTriggerTypeChange();
    const modal = document.getElementById("createTriggerModal");
    if (modal) modal.style.display = "flex";
  }
  function closeCreateTriggerModal() {
    const modal = document.getElementById("createTriggerModal");
    if (modal) modal.style.display = "none";
  }
  function onCreateTriggerTypeChange() {
    const type = document.getElementById("ctType")?.value || "interval";
    const interval = document.getElementById("ctConfigInterval");
    const cron = document.getElementById("ctConfigCron");
    if (interval) interval.style.display = type === "interval" ? "" : "none";
    if (cron) cron.style.display = type === "cron" ? "" : "none";
  }
  async function saveCreateTrigger() {
    const name = (document.getElementById("ctName")?.value || "").trim() || "Koto 触发器";
    const triggerType = document.getElementById("ctType")?.value || "interval";
    const jobType = document.getElementById("ctJobType")?.value || "agent_query";
    const query = (document.getElementById("ctQuery")?.value || "").trim();
    const config = triggerType === "interval" ? { interval_seconds: Math.max(60, parseInt(document.getElementById("ctIntervalSecs")?.value || "3600", 10) || 3600) } : triggerType === "cron" ? { time: document.getElementById("ctCronTime")?.value || "09:00" } : {};
    try {
      const resp = await csrfFetch("/api/jobs/triggers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, trigger_type: triggerType, job_type: jobType, job_payload: query ? { query } : {}, enabled: false, config })
      });
      const data = await resp.json();
      if (!resp.ok || data.ok === false) throw new Error(data.error || "创建失败");
      closeCreateTriggerModal();
      if (typeof window.loadTriggers === "function") await window.loadTriggers();
      showNotification("触发器已创建", "success");
    } catch (error) {
      showNotification("创建失败: " + (error.message || error), "error");
    }
  }
  function openCreateSkillModal() {
    ["csName", "csDesc", "csPrompt"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.value = "";
    });
    const icon = document.getElementById("csIcon");
    const category = document.getElementById("csCategory");
    if (icon) icon.value = "🤖";
    if (category) category.value = "custom";
    const modal = document.getElementById("createSkillModal");
    if (modal) modal.style.display = "flex";
  }
  function closeCreateSkillModal() {
    const modal = document.getElementById("createSkillModal");
    if (modal) modal.style.display = "none";
  }
  function slugifySkillName(name) {
    const ascii = name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
    return ascii || "custom_skill_" + Date.now();
  }
  async function saveCreateSkill() {
    const name = (document.getElementById("csName")?.value || "").trim();
    const description = (document.getElementById("csDesc")?.value || "").trim();
    const prompt2 = (document.getElementById("csPrompt")?.value || "").trim();
    const icon = (document.getElementById("csIcon")?.value || "🤖").trim();
    const category = document.getElementById("csCategory")?.value || "custom";
    if (!name) {
      showNotification("请输入技能名称", "warning");
      return;
    }
    try {
      const resp = await csrfFetch("/api/skillmarket/install", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: slugifySkillName(name),
          name,
          icon,
          description,
          category,
          prompt: prompt2 || `你是${name}。${description}`,
          skill_nature: "custom",
          enabled: true,
          tags: [category]
        })
      });
      const data = await resp.json();
      if (!resp.ok || data.success === false) throw new Error(data.error || "创建失败");
      closeCreateSkillModal();
      if (typeof window.spLoadSkills === "function") await window.spLoadSkills();
      if (typeof window.loadSkills === "function") await window.loadSkills();
      showNotification("Skill 已创建", "success");
    } catch (error) {
      showNotification("创建失败: " + (error.message || error), "error");
    }
  }
  async function sendMessage(event) {
    event.preventDefault();
    const input = document.getElementById("messageInput");
    const sendBtn = document.getElementById("sendBtn");
    const container = document.getElementById("chatMessages");
    if (!input || !container) return;
    const message = input.value.trim();
    const selectedFiles2 = Array.isArray(window.selectedFiles) ? window.selectedFiles : [];
    let sessionName = window.currentSession || "";
    if (sessionName && typeof window.isSessionGenerating === "function" && window.isSessionGenerating(sessionName)) {
      sendBtn?.setAttribute("disabled", "true");
      const controller = window.getSessionAbortController?.(sessionName);
      if (controller) controller.abort();
      try {
        await fetch("/api/chat/interrupt", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session: sessionName,
            task_id: window.getSessionTaskId?.(sessionName) || null
          })
        });
      } catch (_) {
      }
      if (sendBtn) sendBtn.disabled = false;
      return;
    }
    if (!message && selectedFiles2.length === 0) return;
    if (!sessionName && typeof window.createNewSession === "function") {
      const generatedName = typeof window.generateSessionName === "function" ? window.generateSessionName(message || "新对话") : (message || "新对话").slice(0, 24);
      await window.createNewSession(generatedName);
      sessionName = window.currentSession || "";
      if (sessionName && window._newlyCreatedSessions instanceof Set) {
        window._newlyCreatedSessions.add(sessionName);
      }
    }
    input.value = "";
    input.style.height = "auto";
    const welcome = container.querySelector(".welcome-screen, #welcomeScreen");
    if (welcome) welcome.remove();
    const renderMessageFn = window.renderMessage;
    if (typeof renderMessageFn === "function") {
      container.insertAdjacentHTML("beforeend", renderMessageFn("user", message || "(附件)", { attachments: selectedFiles2.map((f) => ({ name: f.name, type: f.type, size: f.size })) }));
    }
    window.scrollToBottomForce?.();
    let taskInfo = null;
    let taskType = window.lockedTaskType || null;
    const modelToUse = window.selectedModel || "auto";
    try {
      window.showLoading?.("分析任务类型...", "");
      const analyzeResp = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          locked_task: taskType,
          locked_model: modelToUse,
          has_file: selectedFiles2.length > 0,
          file_type: selectedFiles2.length === 1 ? selectedFiles2[0].type : selectedFiles2.length > 1 ? "multiple" : ""
        })
      });
      taskInfo = await analyzeResp.json().catch(() => null);
      taskType = taskType || taskInfo?.task || null;
      const modelDisplay = taskInfo?.model_speed ? `${taskInfo.model_name} ${taskInfo.model_speed}` : taskInfo?.model_name || "";
      window.showLoading?.(`${taskType || "CHAT"} 任务处理中...`, modelDisplay);
    } catch (_) {
      window.showLoading?.("Koto 正在思考...", "");
    }
    const thisSession = sessionName || window.currentSession || "default";
    const abortController = new AbortController();
    window.setSessionGenerating?.(thisSession, true);
    window.setSessionAbortController?.(thisSession, abortController);
    if (sendBtn) {
      sendBtn.classList.add("generating");
      sendBtn.disabled = false;
      sendBtn.title = "停止生成";
    }
    const msgId = `msg-${Date.now()}`;
    const msgDiv = document.createElement("div");
    msgDiv.className = "message assistant";
    msgDiv.id = msgId;
    msgDiv.innerHTML = `
    <div class="message-avatar"><img src="/static/assets/koto_chat_icon.png" alt="Koto" class="avatar-img"></div>
    <div class="message-content">
      <div class="message-header">
        <span class="message-sender">Koto</span>
        <div class="message-meta"><span class="time-info" id="${msgId}-time">...</span></div>
      </div>
      <div class="message-body" id="${msgId}-body"><span class="typing-cursor">▊</span></div>
    </div>`;
    container.appendChild(msgDiv);
    window.scrollToBottom?.();
    const bodyEl = document.getElementById(`${msgId}-body`);
    const timeEl = document.getElementById(`${msgId}-time`);
    const startedAt = Date.now();
    let fullText = "";
    let agentStepCounter = 0;
    let canonicalStepTotal = 0;
    let canonicalCurrentStepIndex = 0;
    const canonicalStepOrder = /* @__PURE__ */ new Map();
    const taskStepStates = /* @__PURE__ */ new Map();
    const safeHtml = (value) => typeof window.escapeHtml === "function" ? window.escapeHtml(String(value || "")) : escapeHtmlLocal(String(value || ""));
    const parse = (text) => {
      try {
        return typeof window.parseMarkdown === "function" ? window.parseMarkdown(text) : `<div class="markdown-fallback" style="white-space:pre-wrap;">${safeHtml(text)}</div>`;
      } catch (_) {
        return `<div class="markdown-fallback" style="white-space:pre-wrap;">${safeHtml(text)}</div>`;
      }
    };
    const describeAction = (toolName, toolArgs) => {
      const args = toolArgs || {};
      const path = String(args.path || args.file_path || args.filename || "");
      const query = String(args.query || args.q || args.search_query || "");
      if (path) return `处理文件：${path.split(/[\\/]/).pop()}`;
      if (query) return `检索：${query.slice(0, 48)}`;
      return String(toolName || "执行工具").replace(/_/g, " ");
    };
    const briefObsText = (raw) => {
      const text = typeof raw === "string" ? raw : JSON.stringify(raw || "");
      return text.length > 60 ? text.slice(0, 57) + "..." : text;
    };
    const ensureCanonicalStepIndex = (rawStepId, fallbackTitle = "") => {
      const key = String(rawStepId || "").trim() || fallbackTitle || `step_${canonicalStepOrder.size + 1}`;
      if (canonicalStepOrder.has(key)) return canonicalStepOrder.get(key);
      const nextIdx = canonicalStepOrder.size + 1;
      canonicalStepOrder.set(key, nextIdx);
      canonicalStepTotal = Math.max(canonicalStepTotal, nextIdx);
      return nextIdx;
    };
    const canonicalProgressFraction = (milestone = "step_progress") => {
      const fractions = {
        phase_running: 0.5,
        phase_done: 1,
        step_start: 0.35,
        tool_call: 0.5,
        step_progress: 0.7,
        tool_result: 0.85,
        step_done: 1,
        step_error: 1
      };
      return Object.prototype.hasOwnProperty.call(fractions, milestone) ? fractions[milestone] : 0;
    };
    const canonicalProgressPercent = (index, total, milestone = "step_progress") => {
      const safeTotal = Math.max(Number(total) || 0, Number(index) || 0, 1);
      const safeIndex = Math.min(Math.max(Number(index) || 1, 1), safeTotal);
      const fraction = canonicalProgressFraction(milestone);
      return Math.max(0, Math.min(100, Math.round((safeIndex - 1 + fraction) / safeTotal * 100)));
    };
    const normalizeEvent = (evt) => {
      if (!evt || typeof evt !== "object") return evt;
      if (evt.type === "error" && evt.data && !evt.message) return { type: "error", message: evt.data.error || "未知错误" };
      if (evt.type === "plan" && Array.isArray(evt.steps)) {
        canonicalStepOrder.clear();
        canonicalCurrentStepIndex = 0;
        canonicalStepTotal = evt.steps.length;
        const steps = evt.steps.map((step, idx) => {
          const title = step.description || step.label || step.text || step.id || `步骤 ${idx + 1}`;
          const key = String(step.id || step.step_id || step.step || title || idx + 1);
          canonicalStepOrder.set(key, idx + 1);
          return { index: idx + 1, title };
        });
        return { type: "task_step", status: "init", steps, step_total: steps.length };
      }
      if (evt.type === "phase" && Array.isArray(evt.phases) && evt.phases.length) {
        const currentKey = String(evt.current || "").trim();
        const currentIdx = evt.phases.findIndex((phase2) => String(phase2.id || phase2.label || "").trim() === currentKey);
        const phaseIndex = currentIdx >= 0 ? currentIdx + 1 : 1;
        const phase = evt.phases[currentIdx] || evt.phases[0];
        return {
          type: "task_step",
          step_index: phaseIndex,
          step_total: evt.phases.length,
          status: evt.status === "done" && phaseIndex >= evt.phases.length ? "done" : "running",
          title: phase?.label || phase?.id || evt.text || currentKey || "执行阶段",
          detail: "",
          progress: canonicalProgressPercent(phaseIndex, evt.phases.length, evt.status === "done" ? "phase_done" : "phase_running")
        };
      }
      if (evt.type === "step_start") {
        const title = evt.text || evt.label || evt.step_id || evt.step || "执行步骤";
        const idx = ensureCanonicalStepIndex(evt.step_id || evt.step, title);
        canonicalCurrentStepIndex = idx;
        return { type: "task_step", step_index: idx, step_total: canonicalStepTotal || idx, status: "running", title, detail: evt.detail || "", progress: canonicalProgressPercent(idx, canonicalStepTotal || idx, "step_start") };
      }
      if (evt.type === "step_progress") {
        const detail = evt.detail || evt.text || "处理中";
        const idx = ensureCanonicalStepIndex(evt.step_id || evt.step, detail);
        canonicalCurrentStepIndex = idx;
        return { type: "task_step", step_index: idx, step_total: canonicalStepTotal || idx, status: "running", title: taskStepStates.get(idx)?.title || `步骤 ${idx}`, detail, progress: canonicalProgressPercent(idx, canonicalStepTotal || idx, "step_progress") };
      }
      if (evt.type === "step_done") {
        const title = evt.text || evt.label || evt.step_id || evt.step || "步骤完成";
        const idx = ensureCanonicalStepIndex(evt.step_id || evt.step, title);
        canonicalCurrentStepIndex = idx;
        return { type: "task_step", step_index: idx, step_total: canonicalStepTotal || idx, status: "done", title, detail: evt.detail || "", progress: canonicalProgressPercent(idx, canonicalStepTotal || idx, "step_done") };
      }
      if (evt.type === "step_error") {
        const errText = evt.error || evt.text || "步骤失败";
        const idx = ensureCanonicalStepIndex(evt.step_id || evt.step, errText);
        canonicalCurrentStepIndex = idx;
        return { type: "task_step", step_index: idx, step_total: canonicalStepTotal || idx, status: "failed", title: taskStepStates.get(idx)?.title || evt.step_id || `步骤 ${idx}`, detail: errText, progress: canonicalProgressPercent(idx, canonicalStepTotal || idx, "step_error") };
      }
      if (evt.type === "tool_call") {
        if (canonicalCurrentStepIndex > 0 || canonicalStepTotal > 0) {
          const idx = canonicalCurrentStepIndex || 1;
          return { type: "task_step", step_index: idx, step_total: canonicalStepTotal || idx, status: "running", title: taskStepStates.get(idx)?.title || `步骤 ${idx}`, detail: describeAction(evt.tool_name, evt.tool_args), progress: canonicalProgressPercent(idx, canonicalStepTotal || idx, "tool_call") };
        }
        agentStepCounter += 1;
        return { type: "agent_step", step_number: agentStepCounter, total_steps: "?", tool_name: evt.tool_name || "tool", tool_args: evt.tool_args || {} };
      }
      if (evt.type === "tool_result") {
        const preview = evt.result_preview || evt.content || "";
        if (canonicalCurrentStepIndex > 0 || canonicalStepTotal > 0) {
          const idx = canonicalCurrentStepIndex || 1;
          return { type: "task_step", step_index: idx, step_total: canonicalStepTotal || idx, status: "running", title: taskStepStates.get(idx)?.title || `步骤 ${idx}`, detail: briefObsText(preview), progress: canonicalProgressPercent(idx, canonicalStepTotal || idx, "tool_result") };
        }
        return { type: "observation", message: preview, observation: preview };
      }
      if (evt.type === "task_final" && evt.data) return { type: "done", content: evt.data.result || "", elapsed_time: evt.data.elapsed_time };
      return evt;
    };
    const renderTaskStep = (data) => {
      if (!bodyEl) return;
      if (Array.isArray(data.steps)) {
        data.steps.forEach((s) => taskStepStates.set(Number(s.index), { status: "pending", title: s.title || `步骤 ${s.index}` }));
      } else if (data.step_index) {
        taskStepStates.set(Number(data.step_index), { status: data.status, title: data.title, detail: data.detail });
      }
      const total = Number(data.step_total || canonicalStepTotal || taskStepStates.size || 1);
      const rows = Array.from({ length: total }, (_, i) => {
        const idx = i + 1;
        const state = taskStepStates.get(idx) || {};
        const done = state.status === "done";
        const failed = state.status === "failed";
        const active = data.step_index === idx && !done && !failed;
        return `<div class="koto-progress-row ${active ? "active" : ""}">
        <span>${done ? "✓" : failed ? "!" : active ? "..." : idx}</span>
        <div><strong>${safeHtml(state.title || `步骤 ${idx}`)}</strong>${state.detail ? `<small>${safeHtml(state.detail)}</small>` : ""}</div>
      </div>`;
      }).join("");
      const pct = Math.max(0, Math.min(100, Number(data.progress || 0)));
      bodyEl.innerHTML = `<div class="koto-stream-progress">${rows}<div class="koto-stream-progress-track"><i style="width:${pct}%"></i></div></div>`;
    };
    const applyStreamEvent = (data) => {
      if (!bodyEl) return;
      if (data.type === "token") {
        fullText += data.content || "";
        bodyEl.innerHTML = parse(fullText) + '<span class="typing-cursor">▊</span>';
      } else if (data.type === "progress") {
        window.showMiniGame?.();
        window.showLoading?.(data.message || "处理中...", data.detail || "");
        if (!fullText) {
          bodyEl.innerHTML = `<div class="doc-progress" style="padding:16px;"><strong>${safeHtml(data.message || "处理中...")}</strong><div style="color:var(--text-muted);font-size:13px;margin-top:4px;">${safeHtml(data.detail || "")}</div><div style="height:6px;border-radius:8px;background:rgba(0,0,0,.08);margin-top:10px;overflow:hidden;"><i style="display:block;height:100%;width:${Math.max(0, Math.min(100, Number(data.progress || 0)))}%;background:var(--accent-primary);"></i></div></div>`;
        }
      } else if (data.type === "task_step") {
        renderTaskStep(data);
      } else if (data.type === "agent_step") {
        bodyEl.innerHTML = `<div class="koto-steps"><div class="koto-steps-row">${safeHtml(describeAction(data.tool_name, data.tool_args))}</div></div>`;
      } else if (data.type === "observation") {
        const obs = safeHtml(data.observation || data.message || "");
        bodyEl.insertAdjacentHTML("beforeend", `<div class="agent-observation-text">${obs}</div>`);
      } else if (data.type === "done") {
        if (data.content && !fullText) fullText = data.content;
        bodyEl.innerHTML = parse(fullText || data.content || "");
      } else if (data.type === "error") {
        bodyEl.innerHTML = `<div class="error-message">${safeHtml(data.message || "请求失败")}</div>`;
      }
      window.scrollToBottom?.();
    };
    try {
      let response;
      if (selectedFiles2.length > 0) {
        const formData = new FormData();
        formData.append("session", thisSession);
        formData.append("message", message);
        formData.append("locked_task", taskType || "");
        formData.append("locked_model", modelToUse || "auto");
        selectedFiles2.forEach((file) => formData.append("file", file));
        response = await fetch("/api/chat/file", { method: "POST", body: formData, signal: abortController.signal });
        window.removeFile?.();
      } else {
        const useUnifiedAgentStream = String(taskType || "").toUpperCase() === "AGENT";
        const streamEndpoint = useUnifiedAgentStream ? "/api/agent/process-stream" : "/api/chat/stream";
        const contextFiles = Array.isArray(window._kotoContextFiles) ? window._kotoContextFiles.map((f) => f.path) : [];
        const payload = useUnifiedAgentStream ? { request: message, context: { history: [] }, session_id: thisSession, model: modelToUse || "gemini-3-flash-preview", ...contextFiles.length ? { context_files: contextFiles } : {} } : { session: thisSession, message, locked_task: taskType, locked_model: modelToUse, ...contextFiles.length ? { context_files: contextFiles } : {} };
        response = await fetch(streamEndpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          signal: abortController.signal
        });
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      const contentType = response.headers.get("Content-Type") || "";
      if (!response.body || !contentType.includes("text/event-stream")) {
        const data = await response.json().catch(() => ({}));
        fullText = data.response || data.content || data.message || "";
        if (bodyEl) bodyEl.innerHTML = parse(fullText || JSON.stringify(data));
      } else {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let streamBuffer = "";
        let done = false;
        while (!done) {
          const chunk = await reader.read();
          done = chunk.done;
          if (chunk.value) {
            streamBuffer += decoder.decode(chunk.value, { stream: true });
            const lines = streamBuffer.split("\n");
            streamBuffer = lines.pop() || "";
            for (const line of lines) {
              if (!line.startsWith("data: ")) continue;
              const raw = line.slice(6).trim();
              if (!raw || raw === "[DONE]") {
                done = true;
                continue;
              }
              try {
                applyStreamEvent(normalizeEvent(JSON.parse(raw)));
              } catch (_) {
              }
            }
          }
        }
        if (bodyEl) bodyEl.innerHTML = parse(fullText || bodyEl.textContent || "");
      }
      if (timeEl) timeEl.textContent = `${Math.max(1, Math.round((Date.now() - startedAt) / 1e3))}s`;
      if (window._newlyCreatedSessions instanceof Set && window._newlyCreatedSessions.has(thisSession) && typeof window.autoTitleSession === "function") {
        window.autoTitleSession(thisSession, message, fullText);
      }
    } catch (error) {
      if (bodyEl) {
        const aborted = error?.name === "AbortError";
        bodyEl.innerHTML = `<div class="${aborted ? "warning-message" : "error-message"}">${safeHtml(aborted ? "已停止生成" : `请求失败：${error?.message || error}`)}</div>`;
      }
    } finally {
      window.hideLoading?.();
      window.hideMiniGame?.();
      window.setSessionGenerating?.(thisSession, false);
      window.setSessionAbortController?.(thisSession, null);
      if (sendBtn) {
        sendBtn.classList.remove("generating");
        sendBtn.disabled = false;
        sendBtn.title = "发送";
      }
      window.scrollToBottom?.();
    }
  }
  console.log("🔥 Koto App.js 已加载 - VERSION: 2026-02-14-03");
  document.addEventListener("DOMContentLoaded", async () => {
    if (typeof window.hideStartupSplash === "function") window.hideStartupSplash();
    if (typeof window.loadSettings === "function") await window.loadSettings();
    const theme = window.currentSettings?.appearance?.theme || "light";
    if (typeof window.applyTheme === "function") window.applyTheme(theme);
    if (typeof window.updateThemeSelector === "function") window.updateThemeSelector(theme);
    const serverZoom = parseFloat(window.currentSettings?.appearance?.ui_zoom || "1");
    if (typeof window.setUIZoom === "function") window.setUIZoom(String(serverZoom), true);
    if (typeof window.checkSetupStatus === "function") await window.checkSetupStatus();
    if (typeof window._syncSidebarState === "function") window._syncSidebarState({ forceOpenOverlay: true });
    if (typeof window.initProjectSelector === "function") window.initProjectSelector();
    if (typeof window.loadSessions === "function") await window.loadSessions();
    if (typeof window.checkStatus === "function") window.checkStatus();
    if (typeof window.initCapabilityButtons === "function") window.initCapabilityButtons();
    if (typeof window.renderWelcomeScreen === "function") window.renderWelcomeScreen();
    if (window.currentSettings?.ai) {
      window.selectedModel = window.currentSettings.ai.default_model || "auto";
    }
    const newSessionInput = document.getElementById("newSessionName");
    if (newSessionInput) newSessionInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        if (typeof window.confirmNewSession === "function") window.confirmNewSession();
      }
    });
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
      if ((window.currentSettings?.appearance?.theme || "light") === "auto" && typeof window.applyTheme === "function") window.applyTheme("auto");
    });
    if (typeof window.initProactiveUI === "function") window.initProactiveUI();
    if (typeof window.initScrollBehavior === "function") window.initScrollBehavior();
    window.addEventListener("keydown", (e) => {
      if (typeof window.handleGlobalKeyDown === "function") window.handleGlobalKeyDown(e);
    });
    window.addEventListener("resize", () => {
      if (typeof window._syncSidebarState === "function") window._syncSidebarState();
    });
    document.addEventListener("click", (e) => {
      const a = e.target?.closest('a[data-ext="1"], a[href^="http://"], a[href^="https://"]');
      if (!a) return;
      const anchor = a;
      if (anchor.target === "_blank" && !window.pywebview) return;
      e.preventDefault();
      const url = anchor.href;
      if (window.pywebview && window.pywebview.api && window.pywebview.api.open_url) {
        window.pywebview.api.open_url(url);
      } else {
        window.open(url, "_blank", "noopener,noreferrer");
      }
    });
    setTimeout(() => {
      if (typeof window.shadowPollPending === "function") window.shadowPollPending();
      setInterval(() => {
        if (typeof window.shadowPollPending === "function") window.shadowPollPending();
      }, 5 * 60 * 1e3);
    }, 3e3);
  });
  window.hideStartupSplash = hideStartupSplash;
  window.showNotification = showNotification;
  window.KotoDialog = KotoDialog;
  window.kotoAlert = kotoAlert;
  window.kotoConfirm = kotoConfirm;
  window.kotoPrompt = kotoPrompt;
  window.handleKeyDown = handleKeyDown;
  window.handleGlobalKeyDown = handleGlobalKeyDown;
  window.minimizeWindow = minimizeWindow;
  window.maximizeWindow = maximizeWindow;
  window.closeWindow = closeWindow;
  window.switchToMiniMode = switchToMiniMode;
  window.chatSearchNavKey = chatSearchNavKey;
  window.loadFolderList = loadFolderList;
  window.loadFolderDrives = loadFolderDrives;
  window.selectFolderEntry = selectFolderEntry;
  window.confirmFolderSelection = confirmFolderSelection;
  window.openArtifactPanel = openArtifactPanel;
  window.closeArtifactPanel = closeArtifactPanel;
  window.switchArtifactTab = switchArtifactTab;
  window.copyArtifactContent = copyArtifactContent;
  window.downloadArtifact = downloadArtifact;
  window.closeArtifacts = closeArtifacts;
  window.initProactiveUI = initProactiveUI;
  window.sendRating = sendRating;
  window.loadMemories = loadMemories;
  window.addNewMemory = addNewMemory;
  window.deleteMemory = deleteMemory;
  window.importProfileMemories = importProfileMemories;
  window.batchExtractMemories = batchExtractMemories;
  window.loadShadowMemories = loadShadowMemories;
  window.deleteShadowMemory = deleteShadowMemory;
  window.addShadowMemory = addShadowMemory;
  window.shadowPollPending = shadowPollPending;
  window.shadowNextMsg = shadowNextMsg;
  window.shadowPrevMsg = shadowPrevMsg;
  window.shadowDismissCurrent = shadowDismissCurrent;
  window.shadowDismissAll = shadowDismissAll;
  window.shadowReply = shadowReply;
  window._cancelShadowReply = _cancelShadowReply;
  window.openShadowPanel = openShadowPanel;
  window.loadShadowStatus = loadShadowStatus;
  window.toggleShadowWatcher = toggleShadowWatcher;
  window.shadowForceTick = shadowForceTick;
  window.shadowRetryFailedTask = shadowRetryFailedTask;
  window.loadShadowOpenTasks = loadShadowOpenTasks;
  window.shadowMarkTaskDone = shadowMarkTaskDone;
  window.showAgentConfirmDialog = showAgentConfirmDialog;
  window.showAgentChoiceDialog = showAgentChoiceDialog;
  window.extractMeetingActions = extractMeetingActions;
  window.createReminderFromAction = createReminderFromAction;
  window.generateMorningBrief = generateMorningBrief;
  window.openSuggestionPanel = openSuggestionPanel;
  window.loadSuggestions = loadSuggestions;
  window.applySuggestion = applySuggestion;
  window.acceptSuggestion = acceptSuggestion;
  window.rejectSuggestion = rejectSuggestion;
  window.acceptAllSuggestions = acceptAllSuggestions;
  window.rejectAllSuggestions = rejectAllSuggestions;
  window.closeSuggestionPanel = closeSuggestionPanel;
  window.applySuggestions = applySuggestions;
  window.openTriggerPanel = openTriggerPanel;
  window.closeTriggerPanel = closeTriggerPanel;
  window.startTriggerMonitoring = startTriggerMonitoring;
  window.stopTriggerMonitoring = stopTriggerMonitoring;
  window.runTriggerEvaluation = runTriggerEvaluation;
  window.openCatalogWizard = openCatalogWizard;
  window.closeCatalogWizard = closeCatalogWizard;
  window.closeCatalogScheduleWizard = closeCatalogScheduleWizard;
  window.saveCatalogScheduleWizard = saveCatalogScheduleWizard;
  window.openCreateBindingModal = openCreateBindingModal;
  window.closeCreateBindingModal = closeCreateBindingModal;
  window.saveCreateBinding = saveCreateBinding;
  window.openCreateTriggerModal = openCreateTriggerModal;
  window.closeCreateTriggerModal = closeCreateTriggerModal;
  window.onCreateTriggerTypeChange = onCreateTriggerTypeChange;
  window.saveCreateTrigger = saveCreateTrigger;
  window.openCreateSkillModal = openCreateSkillModal;
  window.closeCreateSkillModal = closeCreateSkillModal;
  window.saveCreateSkill = saveCreateSkill;
  window.sendMessage = sendMessage;
  window.escapeHtml = escapeHtmlLocal;
  window._pendingShadowContext = _pendingShadowContext;
  let selectedFiles = [];
  let lockedTaskType = null;
  let selectedModel = "auto";
  let enableMiniGame = true;
  const MAX_UPLOAD_FILES = 10;
  const TASK_MODELS = {
    CHAT: "deepseek-v4-pro",
    CODER: "deepseek-v4-pro",
    VISION: "deepseek-v4-pro",
    PAINTER: "nano-banana-pro-preview",
    RESEARCH: "deep-research-pro-preview-12-2025",
    FILE_GEN: "deepseek-v4-pro"
  };
  window.selectedFiles = selectedFiles;
  window.lockedTaskType = lockedTaskType;
  window.selectedModel = selectedModel;
  window.enableMiniGame = enableMiniGame;
  window.TASK_MODELS = TASK_MODELS;
  window.MAX_UPLOAD_FILES = MAX_UPLOAD_FILES;
  const miniGame = {
    initialized: false,
    running: false,
    visible: false,
    canvas: null,
    ctx: null,
    rafId: null,
    lastFrame: 0,
    groundY: 90,
    speed: 160,
    spawnTimer: 0,
    score: 0,
    dino: { x: 20, y: 70, w: 18, h: 18, vy: 0, onGround: true },
    obstacles: []
  };
  function initMiniGame() {
    if (miniGame.initialized) return;
    miniGame.canvas = document.getElementById("miniGameCanvas");
    if (!miniGame.canvas) return;
    miniGame.ctx = miniGame.canvas.getContext("2d");
    if (!miniGame.ctx) return;
    miniGame.dino.y = miniGame.groundY - miniGame.dino.h;
    miniGame.initialized = true;
    window.addEventListener("keydown", (e) => {
      if (!miniGame.visible) return;
      if (e.code === "Space") {
        e.preventDefault();
        if (!miniGame.running) {
          startMiniGame();
        } else {
          miniGameJump();
        }
      }
    });
    if (miniGame.canvas) {
      miniGame.canvas.addEventListener("click", () => {
        if (!miniGame.visible) return;
        if (!miniGame.running) {
          startMiniGame();
        } else {
          miniGameJump();
        }
      });
    }
  }
  function showMiniGame() {
    const panel = document.getElementById("miniGamePanel");
    if (!panel) return;
    panel.classList.remove("hidden");
    miniGame.visible = true;
    initMiniGame();
    startMiniGame();
  }
  function hideMiniGame() {
    const panel = document.getElementById("miniGamePanel");
    if (!panel) return;
    panel.classList.add("hidden");
    miniGame.visible = false;
    stopMiniGame();
  }
  function startMiniGame() {
    if (!miniGame.initialized || miniGame.running) return;
    resetMiniGame();
    miniGame.running = true;
    miniGame.lastFrame = performance.now();
    miniGame.rafId = requestAnimationFrame(miniGameLoop);
  }
  function stopMiniGame() {
    miniGame.running = false;
    if (miniGame.rafId) {
      cancelAnimationFrame(miniGame.rafId);
      miniGame.rafId = null;
    }
  }
  function resetMiniGame() {
    miniGame.dino.y = miniGame.groundY - miniGame.dino.h;
    miniGame.dino.vy = 0;
    miniGame.dino.onGround = true;
    miniGame.obstacles = [];
    miniGame.spawnTimer = 0;
    miniGame.score = 0;
  }
  function miniGameJump() {
    if (!miniGame.running) return;
    if (miniGame.dino.onGround) {
      miniGame.dino.vy = -320;
      miniGame.dino.onGround = false;
    }
  }
  function miniGameLoop(ts) {
    if (!miniGame.running) return;
    const dt = Math.min((ts - miniGame.lastFrame) / 1e3, 0.05);
    miniGame.lastFrame = ts;
    miniGame.dino.vy += 900 * dt;
    miniGame.dino.y += miniGame.dino.vy * dt;
    if (miniGame.dino.y >= miniGame.groundY - miniGame.dino.h) {
      miniGame.dino.y = miniGame.groundY - miniGame.dino.h;
      miniGame.dino.vy = 0;
      miniGame.dino.onGround = true;
    }
    miniGame.spawnTimer -= dt;
    if (miniGame.spawnTimer <= 0) {
      miniGame.spawnTimer = 0.8 + Math.random() * 0.9;
      miniGame.obstacles.push({ x: 260, y: miniGame.groundY - 12, w: 10 + Math.random() * 6, h: 12 });
    }
    const speed = miniGame.speed + Math.min(miniGame.score, 200) * 0.2;
    miniGame.obstacles.forEach((o) => {
      o.x -= speed * dt;
    });
    miniGame.obstacles = miniGame.obstacles.filter((o) => o.x + o.w > -10);
    for (const o of miniGame.obstacles) {
      if (rectHit(miniGame.dino, o)) {
        miniGame.running = false;
        break;
      }
    }
    if (miniGame.running) {
      miniGame.score += dt * 10;
      drawMiniGame();
      miniGame.rafId = requestAnimationFrame(miniGameLoop);
    } else {
      drawMiniGame(true);
    }
  }
  function rectHit(a, b) {
    return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
  }
  function drawMiniGame(gameOver = false) {
    const ctx = miniGame.ctx;
    const canvas = miniGame.canvas;
    if (!ctx || !canvas) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = "#6c7a91";
    ctx.beginPath();
    ctx.moveTo(0, miniGame.groundY + 4);
    ctx.lineTo(canvas.width, miniGame.groundY + 4);
    ctx.stroke();
    ctx.fillStyle = "#10b981";
    ctx.fillRect(miniGame.dino.x, miniGame.dino.y, miniGame.dino.w, miniGame.dino.h);
    ctx.fillStyle = "#ef6b6b";
    miniGame.obstacles.forEach((o) => ctx.fillRect(o.x, o.y, o.w, o.h));
    ctx.fillStyle = "#9fb3d1";
    ctx.font = "11px Segoe UI, sans-serif";
    ctx.fillText(`Score: ${Math.floor(miniGame.score)}`, 170, 16);
    if (gameOver) {
      ctx.fillStyle = "#f3b45c";
      ctx.fillText("Game Over - press Space", 50, 60);
    }
  }
  function renderChatHistory(history) {
    const container = document.getElementById("chatMessages");
    const ws = document.getElementById("welcomeScreen");
    if (!container) return;
    if (history.length === 0) {
      container.querySelectorAll(".message, .chat-date-sep").forEach((el) => el.remove());
      if (ws) ws.style.display = "block";
      if (typeof window.renderWelcomeScreen === "function") window.renderWelcomeScreen();
      return;
    }
    if (ws) ws.style.display = "none";
    container.querySelectorAll(".message, .chat-date-sep").forEach((el) => el.remove());
    let lastDateLabel = "";
    for (let i = 0; i < history.length; i += 2) {
      const userMsg = history[i];
      const assistantMsg = history[i + 1];
      const ts = userMsg && userMsg.timestamp ? userMsg.timestamp : null;
      if (ts) {
        const d = new Date(ts);
        if (!Number.isNaN(d.getTime())) {
          const today = /* @__PURE__ */ new Date();
          const yesterday = new Date(today);
          yesterday.setDate(yesterday.getDate() - 1);
          const sameDay = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
          let label;
          if (sameDay(d, today)) label = "今天";
          else if (sameDay(d, yesterday)) label = "昨天";
          else label = `${d.getFullYear() === today.getFullYear() ? "" : d.getFullYear() + " 年"}${d.getMonth() + 1} 月 ${d.getDate()} 日`;
          if (label !== lastDateLabel) {
            lastDateLabel = label;
            const sep = document.createElement("div");
            sep.className = "chat-date-sep";
            sep.textContent = label;
            container.appendChild(sep);
          }
        }
      }
      if (userMsg) {
        container.insertAdjacentHTML("beforeend", renderMessage("user", userMsg.parts[0], {
          timestamp: userMsg.timestamp,
          attachments: userMsg.attachments || []
        }));
      }
      if (assistantMsg) {
        const msgText = assistantMsg.parts ? assistantMsg.parts[0] : "";
        if (msgText === "⏳ 处理中...") {
          container.insertAdjacentHTML("beforeend", renderMessage("assistant", "⚠️ *此任务未完成（可能因断连或崩溃中断）*", {
            task: assistantMsg.task,
            model: assistantMsg.model_name,
            timestamp: assistantMsg.timestamp
          }));
        } else {
          const meta = {
            task: assistantMsg.task,
            model: assistantMsg.model_name,
            images: assistantMsg.images || [],
            saved_files: assistantMsg.saved_files || [],
            time: assistantMsg.time,
            timestamp: assistantMsg.timestamp
          };
          container.insertAdjacentHTML("beforeend", renderMessage("assistant", assistantMsg.parts[0], meta));
          if (meta.images && meta.images.length > 0) {
            setTimeout(() => {
              const containers = container.querySelectorAll('[id^="images-"]');
              containers.forEach((c) => renderImagesInContainer(c.id));
            }, 0);
          }
        }
      }
    }
    scrollToBottomForce$1();
    highlightCode();
    setTimeout(() => renderMermaidBlocks(), 100);
  }
  function scrollToBottomForce$1() {
    window.isScrollLocked = false;
    const container = document.getElementById("chatMessages");
    if (container) {
      container.scrollTop = container.scrollHeight;
    }
  }
  function renderImagesInContainer(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;
    const imagesJson = container.getAttribute("data-images");
    if (!imagesJson) return;
    try {
      const images = JSON.parse(imagesJson);
      if (!Array.isArray(images) || images.length === 0) return;
      container.innerHTML = "";
      container.style.display = "flex";
      container.style.gap = "10px";
      container.style.flexWrap = "wrap";
      container.style.marginTop = "12px";
      for (let i = 0; i < images.length; i++) {
        const img = images[i];
        const url = `/api/workspace/${img.replace(/\\\\/g, "/")}`;
        const link = document.createElement("a");
        link.href = url;
        link.target = "_blank";
        link.style.display = "inline-block";
        const imgEl = document.createElement("img");
        imgEl.src = url;
        imgEl.alt = `Generated image ${i + 1}`;
        imgEl.className = "generated-image";
        imgEl.style.maxWidth = "400px";
        imgEl.style.maxHeight = "400px";
        imgEl.style.borderRadius = "14px";
        imgEl.style.border = "1px solid var(--border-color)";
        imgEl.style.cursor = "pointer";
        imgEl.onload = () => {
        };
        imgEl.onerror = () => {
        };
        link.appendChild(imgEl);
        container.appendChild(link);
      }
    } catch (e) {
    }
  }
  function renderMessage(role, content, meta = {}) {
    const avatar = role === "user" ? "U" : `<img src="/static/assets/koto_chat_icon.png" alt="Koto" class="avatar-img">`;
    const sender = role === "user" ? "You" : "Koto";
    const timestampText = formatMessageTimestamp(meta.timestamp);
    let metaHtml = "";
    if (meta.task) {
      const showTaskBadge = window.currentSettings?.ai?.show_task_type === true;
      metaHtml = `${showTaskBadge ? `<span class="task-badge ${meta.task.toLowerCase()}">${meta.task}</span>` : ""}<span class="time-info">⏱️ ${meta.time || ""}</span>`;
    }
    if (timestampText) {
      metaHtml += `<span class="time-info" title="${meta.timestamp}">🕒 ${timestampText}</span>`;
    }
    const containerId = `images-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    let imagesHtml = "";
    if (meta.images && meta.images.length > 0) {
      imagesHtml = `<div class="generated-images" id="${containerId}" data-images='${JSON.stringify(meta.images)}'></div>`;
    }
    let filesHtml = "";
    if (meta.saved_files && meta.saved_files.length > 0) {
      filesHtml = `<div class="saved-files"><div class="saved-files-title">✓ Files saved to workspace:</div>${meta.saved_files.map((file) => `
      <a href="${window._workspaceFileUrl?.(file) || "#"}" target="_blank" rel="noopener" class="saved-file-link" title="在 Koto 中打开 ${file}" onclick="openSavedWorkspaceFile('${file.replace(/'/g, "\\'")}');return false;">
        <div class="saved-file"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg><span>${file}</span></div>
      </a>`).join("")}</div>`;
    }
    const parsedContent = role === "assistant" ? parseMarkdown(content) : escapeHtml$1(content);
    let attachmentHtml = "";
    if (meta.attachments && meta.attachments.length > 0) {
      const items = meta.attachments.map((att) => {
        const isImage = att.type && att.type.startsWith("image");
        return `<div class="message-attachment file-attachment"><div class="attachment-icon">${isImage ? "🖼️" : "📄"}</div><div class="attachment-info"><span class="attachment-name">${att.name}</span><span class="attachment-size">${att.size ? "(" + formatFileSize(att.size) + ")" : ""}</span></div></div>`;
      }).join("");
      attachmentHtml = `<div class="message-attachment-list">${items}</div>`;
    }
    const actionBar = `<div class="message-actions">${role === "assistant" ? `<button class="msg-action-btn" onclick="copyMessageText(this)" title="复制回复"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>复制</button>` : ""}${role === "assistant" ? `<button class="msg-action-btn" onclick="regenMessage(this)" title="重新生成"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="1 4 1 10 7 10"></polyline><path d="M3.51 15a9 9 0 1 0 .49-3.35"></path></svg>重生成</button>` : ""}${role === "user" ? `<button class="msg-action-btn" onclick="editUserMessage(this)" title="编辑后重发"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>编辑</button>` : ""}${role === "user" ? `<button class="msg-action-btn" onclick="resendMessage(this)" title="重新发送"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="1 4 1 10 7 10"></polyline><path d="M3.51 15a9 9 0 1 0 .49-3.35"></path></svg>重发</button>` : ""}</div>`;
    return `<div class="message ${role}"${meta.hidden ? ' style="display:none"' : ""}><div class="message-avatar">${avatar}</div><div class="message-content"><div class="message-header"><span class="message-sender">${sender}</span><div class="message-meta">${metaHtml}</div></div>${attachmentHtml}<div class="message-body">${parsedContent}</div>${imagesHtml}${filesHtml}${actionBar}</div></div>`;
  }
  function formatMessageTimestamp(ts) {
    if (!ts) return "";
    const dt = new Date(ts);
    if (Number.isNaN(dt.getTime())) return "";
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(dt.getMonth() + 1)}-${pad(dt.getDate())} ${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
  }
  function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }
  function copyMessageText(btn) {
    const msgBody = btn.closest(".message")?.querySelector(".message-body");
    const text = msgBody ? msgBody.innerText : "";
    navigator.clipboard.writeText(text).then(() => {
      if (typeof window.showNotification === "function") window.showNotification("已复制到剪贴板", "success", 1500);
    }).catch(() => {
      if (typeof window.showNotification === "function") window.showNotification("复制失败，请手动选择", "error", 2e3);
    });
  }
  function resendMessage(btn) {
    const msgBody = btn.closest(".message")?.querySelector(".message-body");
    if (!msgBody) return;
    const text = msgBody.innerText.trim();
    if (!text) return;
    const input = document.getElementById("messageInput");
    if (input) {
      input.value = text;
      autoResize(input);
      input.focus();
    }
  }
  function editUserMessage(btn) {
    const msgBody = btn.closest(".message")?.querySelector(".message-body");
    if (!msgBody) return;
    const text = msgBody.innerText.trim();
    const input = document.getElementById("messageInput");
    if (input) {
      input.value = text;
      autoResize(input);
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
    }
  }
  function regenMessage(btn) {
    const currentSession2 = window.currentSession;
    if (!currentSession2) {
      if (typeof window.showNotification === "function") window.showNotification("请先选择一个对话", "warning");
      return;
    }
    if (typeof window.isSessionGenerating === "function" && window.isSessionGenerating(currentSession2)) {
      if (typeof window.showNotification === "function") window.showNotification("Koto 正在生成中，请稍候...", "warning");
      return;
    }
    const msgEl = btn.closest(".message.assistant");
    if (!msgEl) return;
    let prev = msgEl.previousElementSibling;
    while (prev && !prev.classList.contains("message")) prev = prev.previousElementSibling;
    if (!prev || !prev.classList.contains("user")) {
      if (typeof window.showNotification === "function") window.showNotification("找不到对应的用户消息", "warning");
      return;
    }
    const text = prev.querySelector(".message-body")?.innerText?.trim();
    if (!text) return;
    const input = document.getElementById("messageInput");
    if (input) {
      input.value = text;
      autoResize(input);
    }
    const form = document.querySelector(".chat-input-form");
    if (form) form.dispatchEvent(new Event("submit", { cancelable: true }));
  }
  function updateFilePreview() {
    const preview = document.getElementById("filePreview");
    const listEl = document.getElementById("fileList");
    if (!preview || !listEl) return;
    if (selectedFiles.length === 0) {
      preview.style.display = "none";
      listEl.innerHTML = "";
      return;
    }
    preview.style.display = "flex";
    const html = selectedFiles.map((file, index) => `
    <div class="file-item"><span class="file-name">${file.name}</span><span class="file-size">(${formatFileSize(file.size)})</span><button class="remove-file-btn" onclick="removeSingleFile(${index})" title="移除">×</button></div>`).join("");
    listEl.innerHTML = html;
  }
  function removeSingleFile(index) {
    selectedFiles.splice(index, 1);
    updateFilePreview();
    if (selectedFiles.length === 0) {
      const fileInput = document.getElementById("fileInput");
      if (fileInput) fileInput.value = "";
    }
  }
  function setSelectedFiles(files, appendMode = false) {
    let newFiles = appendMode ? [...selectedFiles, ...files] : files;
    const uniqueFiles = [];
    const seen = /* @__PURE__ */ new Set();
    for (const file of newFiles) {
      const key = `${file.name}_${file.size}`;
      if (!seen.has(key)) {
        seen.add(key);
        uniqueFiles.push(file);
      }
    }
    const trimmed = uniqueFiles.slice(0, MAX_UPLOAD_FILES);
    let tooLargeCount = 0;
    selectedFiles = trimmed.filter((file) => {
      if (file.size > 100 * 1024 * 1024) {
        tooLargeCount += 1;
        return false;
      }
      return true;
    });
    if (newFiles.length > MAX_UPLOAD_FILES) {
      if (typeof window.showNotification === "function") window.showNotification(`⚠️ 最多一次上传 ${MAX_UPLOAD_FILES} 个文件，已截取前 ${MAX_UPLOAD_FILES} 个`, "warning");
    }
    if (tooLargeCount > 0) {
      if (typeof window.showNotification === "function") window.showNotification(`❌ ${tooLargeCount} 个文件超过 100MB 已跳过`, "error");
    }
    if (selectedFiles.length > 0) {
      if (typeof window.showNotification === "function") window.showNotification(`✅ 已选择 ${selectedFiles.length} 个文件`, "success");
    }
    updateFilePreview();
    window.selectedFiles = selectedFiles;
  }
  function handleFileSelect(event) {
    const target = event.target;
    const files = Array.from(target.files || []);
    if (files.length > 0) {
      setSelectedFiles(files, true);
      target.value = "";
    }
  }
  function removeFile() {
    selectedFiles = [];
    updateFilePreview();
    const fileInput = document.getElementById("fileInput");
    if (fileInput) fileInput.value = "";
    window.selectedFiles = selectedFiles;
  }
  function handleDragOver(event) {
    event.preventDefault();
    event.stopPropagation();
    const overlay = document.getElementById("dragOverlay");
    if (overlay) overlay.style.display = "flex";
  }
  function handleDragLeave(event) {
    event.preventDefault();
    event.stopPropagation();
    if (event.target?.id === "chatMessages") {
      const overlay = document.getElementById("dragOverlay");
      if (overlay) overlay.style.display = "none";
    }
  }
  function handleDrop(event) {
    event.preventDefault();
    event.stopPropagation();
    const overlay = document.getElementById("dragOverlay");
    if (overlay) overlay.style.display = "none";
    const files = Array.from(event.dataTransfer?.files || []);
    if (files.length > 0) {
      setSelectedFiles(files, true);
      const inputEl = document.getElementById("messageInput");
      if (inputEl) inputEl.focus();
    }
  }
  function autoResize(textarea) {
    textarea.style.height = "auto";
    textarea.style.height = textarea.scrollHeight + "px";
  }
  function generateSessionName(message) {
    let name = message.trim();
    const prefixes = ["请你", "请问", "请帮我", "请", "帮我", "帮忙", "能不能", "能否", "可以不可以", "可以", "你能", "我想要", "我想让你", "我想", "我要", "给我", "告诉我", "please", "help me", "can you", "could you", "would you"];
    let changed = true;
    while (changed) {
      changed = false;
      for (const prefix of prefixes) {
        if (name.toLowerCase().startsWith(prefix.toLowerCase())) {
          name = name.slice(prefix.length).trim();
          changed = true;
          break;
        }
      }
    }
    name = name.replace(/^[，。？！,.?!\s]+/, "").trim();
    if (name.length > 18) {
      const cutPoints = [...name.matchAll(/[，。？！,.?!\s]/g)];
      const firstCut = cutPoints.find((m) => m.index > 4 && m.index <= 18);
      name = firstCut ? name.slice(0, firstCut.index) : name.slice(0, 18) + "…";
    }
    if (name.length < 2) {
      const now = /* @__PURE__ */ new Date();
      const mm = String(now.getMonth() + 1).padStart(2, "0");
      const dd = String(now.getDate()).padStart(2, "0");
      const hh = String(now.getHours()).padStart(2, "0");
      const min = String(now.getMinutes()).padStart(2, "0");
      name = `对话 ${mm}-${dd} ${hh}:${min}`;
    }
    return name;
  }
  const _newlyCreatedSessions = /* @__PURE__ */ new Set();
  async function autoTitleSession(sessionName) {
    if (!sessionName || !_newlyCreatedSessions.has(sessionName)) return;
    try {
      const res = await csrfFetch(`/api/sessions/${encodeURIComponent(sessionName)}/auto-title`, { method: "POST", headers: { "Content-Type": "application/json" } });
      const data = await res.json();
      if (!data.success || !data.title) return;
      const renameRes = await csrfFetch(`/api/sessions/${encodeURIComponent(sessionName)}/rename`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ new_name: typeof window.toProjectSessionName === "function" ? window.toProjectSessionName(data.title) : data.title }) });
      const renameData = await renameRes.json();
      if (!renameData.success) return;
      const newSession = renameData.new_session;
      _newlyCreatedSessions.delete(sessionName);
      const currentSession2 = window.currentSession;
      if (currentSession2 === sessionName) {
        window.currentSession = newSession;
        const chatTitle = document.getElementById("chatTitle");
        if (chatTitle) chatTitle.textContent = typeof window.toSessionDisplayName === "function" ? window.toSessionDisplayName(newSession) : newSession;
      }
      document.querySelectorAll(".session-item").forEach((item) => {
        if (item.dataset.session === sessionName) {
          item.dataset.session = newSession;
          const nameEl = item.querySelector(".session-name");
          if (nameEl) nameEl.textContent = typeof window.toSessionDisplayName === "function" ? window.toSessionDisplayName(newSession) : newSession;
        }
      });
    } catch (e) {
    }
  }
  let _chatSearchMatches = [];
  let _chatSearchIdx = -1;
  function openChatSearch() {
    const bar = document.getElementById("chatSearchBar");
    if (!bar) return;
    bar.style.display = "flex";
    const input = bar.querySelector("input");
    if (input) {
      input.value = "";
      input.focus();
    }
    clearChatSearchHighlights();
  }
  function closeChatSearch() {
    const bar = document.getElementById("chatSearchBar");
    if (bar) bar.style.display = "none";
    clearChatSearchHighlights();
  }
  function clearChatSearchHighlights() {
    document.querySelectorAll(".chat-search-highlight").forEach((el) => {
      const parent = el.parentNode;
      if (parent) {
        parent.replaceChild(document.createTextNode(el.textContent || ""), el);
        parent.normalize();
      }
    });
    _chatSearchMatches = [];
    _chatSearchIdx = -1;
  }
  function runChatSearch(query) {
    clearChatSearchHighlights();
    if (!query.trim()) return;
    const bodies = document.querySelectorAll("#chatMessages .message-body");
    bodies.forEach((body) => {
      const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT, null);
      const textNodes = [];
      let node;
      while (node = walker.nextNode()) textNodes.push(node);
      for (const tn of textNodes) {
        const text = tn.textContent || "";
        const idx = text.toLowerCase().indexOf(query.toLowerCase());
        if (idx !== -1) {
          const span = document.createElement("span");
          span.className = "chat-search-highlight";
          span.textContent = text.substring(idx, idx + query.length);
          const after = tn.splitText(idx);
          after.splitText(query.length);
          after.parentNode?.replaceChild(span, after.previousSibling);
          _chatSearchMatches.push(span);
        }
      }
    });
    _chatSearchIdx = _chatSearchMatches.length > 0 ? 0 : -1;
    if (_chatSearchMatches.length > 0) _scrollToMatch(0);
  }
  function _scrollToMatch(idx) {
    if (idx < 0 || idx >= _chatSearchMatches.length) return;
    _chatSearchMatches.forEach((el, i) => el.classList.toggle("current", i === idx));
    _chatSearchMatches[idx].scrollIntoView({ behavior: "smooth", block: "center" });
  }
  function chatSearchNext() {
    if (_chatSearchMatches.length === 0) return;
    _chatSearchIdx = (_chatSearchIdx + 1) % _chatSearchMatches.length;
    _scrollToMatch(_chatSearchIdx);
  }
  function chatSearchPrev() {
    if (_chatSearchMatches.length === 0) return;
    _chatSearchIdx = (_chatSearchIdx - 1 + _chatSearchMatches.length) % _chatSearchMatches.length;
    _scrollToMatch(_chatSearchIdx);
  }
  function onModelChange(value) {
    selectedModel = value;
    window.selectedModel = selectedModel;
  }
  window._kotoContextFiles = [];
  let _atSearchTimer = null;
  function handleAtMention(textarea) {
    const val = textarea.value;
    const cursor = textarea.selectionStart;
    const before = val.slice(0, cursor);
    const atIdx = before.lastIndexOf("@");
    if (atIdx === -1) {
      hideAtSuggest();
      return;
    }
    const query = before.slice(atIdx + 1);
    if (query.includes(" ") || query.includes("\n")) {
      hideAtSuggest();
      return;
    }
    if (_atSearchTimer) clearTimeout(_atSearchTimer);
    _atSearchTimer = setTimeout(async () => {
      try {
        const res = await fetch(`/api/files/search?q=${encodeURIComponent(query)}&limit=8`);
        const data = await res.json();
        showAtSuggest(data.results || [], textarea, atIdx);
      } catch (e) {
        hideAtSuggest();
      }
    }, 200);
  }
  function showAtSuggest(files, textarea, atIdx) {
    const el = document.getElementById("atFileSuggest");
    if (!el) return;
    if (!files.length) {
      hideAtSuggest();
      return;
    }
    el.innerHTML = "";
    files.forEach((f, i) => {
      const item = document.createElement("div");
      item.style.cssText = "padding:8px 12px;cursor:pointer;display:flex;align-items:center;gap:8px;";
      item.dataset.idx = i;
      const icon = typeof window._fileIcon === "function" ? window._fileIcon(f.ext || "") : "📄";
      item.innerHTML = `<span style="font-size:16px">${icon}</span><div><div style="font-weight:500;font-size:13px">${escapeHtml$1(f.name)}</div><div style="font-size:11px;opacity:.6">${escapeHtml$1(f.path)}</div></div>`;
      item.addEventListener("mouseenter", () => {
        el.querySelectorAll("[data-idx]").forEach((e) => e.style.background = "");
        item.style.background = "var(--hover-bg, #f0f4ff)";
      });
      item.addEventListener("mouseleave", () => {
        item.style.background = "";
      });
      item.addEventListener("mousedown", (e) => {
        e.preventDefault();
        selectAtFile(f, textarea, atIdx);
      });
      el.appendChild(item);
    });
    const rect = textarea.getBoundingClientRect();
    el.style.display = "block";
    el.style.left = rect.left + "px";
    el.style.bottom = window.innerHeight - rect.top + 4 + "px";
    el.style.top = "";
  }
  function hideAtSuggest() {
    const el = document.getElementById("atFileSuggest");
    if (el) el.style.display = "none";
  }
  function selectAtFile(file, textarea, atIdx) {
    hideAtSuggest();
    const val = textarea.value;
    const cursor = textarea.selectionStart;
    const newVal = val.slice(0, atIdx) + val.slice(cursor);
    textarea.value = newVal;
    textarea.setSelectionRange(atIdx, atIdx);
    pinContextFile(file.path, file.name);
  }
  function pinContextFile(path, name) {
    if (window._kotoContextFiles.find((f) => f.path === path)) return;
    window._kotoContextFiles.push({ path, name });
    renderContextFileBar();
  }
  function removeContextFile(path) {
    window._kotoContextFiles = window._kotoContextFiles.filter((f) => f.path !== path);
    renderContextFileBar();
  }
  function renderContextFileBar() {
    const bar = document.getElementById("contextFileBar");
    if (!bar) return;
    if (!window._kotoContextFiles.length) {
      bar.style.display = "none";
      return;
    }
    bar.style.display = "flex";
    bar.innerHTML = '<span style="opacity:.5;margin-right:4px;align-self:center;">📎</span>' + window._kotoContextFiles.map((f) => `<span style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;background:var(--accent-light,#e8f0fe);border-radius:12px;font-size:12px;">${typeof window._fileIcon === "function" ? window._fileIcon(f.name.split(".").pop().toLowerCase()) : "📄"} ${escapeHtml$1(f.name)}<button onclick="removeContextFile('${f.path.replace(/'/g, "\\'")}')" style="border:none;background:none;cursor:pointer;padding:0;font-size:14px;line-height:1;opacity:.6;" title="移除">×</button></span>`).join("") + `<button onclick="(window as any)._kotoContextFiles=[];renderContextFileBar();" style="border:none;background:none;cursor:pointer;font-size:11px;opacity:.5;padding:0 4px;" title="清除所有">清除</button>`;
  }
  function _fileIcon(ext) {
    const map = { pdf: "📕", docx: "📘", doc: "📘", pptx: "📊", ppt: "📊", xlsx: "📗", xls: "📗", txt: "📄", md: "📝", py: "🐍", js: "🟨", ts: "🔷", tsx: "⚛️", jsx: "⚛️", html: "🌐", css: "🎨", json: "📋", xml: "📋", yaml: "📋", yml: "📋", png: "🖼️", jpg: "🖼️", jpeg: "🖼️", gif: "🖼️", svg: "🖼️", mp4: "🎬", mov: "🎬", avi: "🎬", mp3: "🎵", wav: "🎵", zip: "📦", rar: "📦", tar: "📦", gz: "📦", "7z": "📦" };
    return map[ext.toLowerCase()] || "📄";
  }
  function openSavedWorkspaceFile(file) {
    const cleanPath = file.replace(/\\/g, "/");
    const url = file.startsWith("/") ? `/api/files${cleanPath}` : `/api/workspace/${cleanPath}`;
    window.open(url, "_blank");
  }
  const SLASH_COMMANDS = [
    { cmd: "file", desc: "文件处理", icon: "📄" },
    { cmd: "image", desc: "生成图片", icon: "🖼️" },
    { cmd: "code", desc: "编写代码", icon: "💻" },
    { cmd: "translate", desc: "翻译内容", icon: "🌏" },
    { cmd: "summarize", desc: "总结内容", icon: "📝" },
    { cmd: "search", desc: "搜索信息", icon: "🔍" },
    { cmd: "analyze", desc: "分析数据", icon: "📊" }
  ];
  let _slashMatchedCmds = [];
  function handleSlashCommand(textarea) {
    const val = textarea.value;
    const cursor = textarea.selectionStart;
    const before = val.slice(0, cursor);
    const slashIdx = before.lastIndexOf("/");
    if (slashIdx === -1) {
      hideSlashPalette();
      return;
    }
    if (slashIdx > 0 && before[slashIdx - 1] !== " " && before[slashIdx - 1] !== "\n") {
      hideSlashPalette();
      return;
    }
    const query = before.slice(slashIdx + 1).toLowerCase();
    _slashMatchedCmds = SLASH_COMMANDS.filter((c) => !query || c.cmd.startsWith(query) || c.desc.includes(query));
    if (_slashMatchedCmds.length === 0) {
      hideSlashPalette();
      return;
    }
    showSlashPalette(_slashMatchedCmds);
  }
  function showSlashPalette(cmds) {
    const el = document.getElementById("slashPalette");
    if (!el) return;
    el.innerHTML = cmds.map((c, i) => `<div class="slash-item" data-idx="${i}"><span class="slash-icon">${c.icon}</span><span class="slash-cmd">/${c.cmd}</span><span class="slash-desc">${c.desc}</span></div>`).join("");
    el.style.display = "block";
    if (typeof window.scrollToBottom === "function") window.scrollToBottom();
  }
  function hideSlashPalette() {
    const el = document.getElementById("slashPalette");
    if (el) el.style.display = "none";
  }
  function selectSlashCommand(idx) {
    if (idx < 0 || idx >= _slashMatchedCmds.length) return;
    const cmd = _slashMatchedCmds[idx];
    const textarea = document.getElementById("messageInput");
    if (!textarea) return;
    const val = textarea.value;
    const cursor = textarea.selectionStart;
    const before = val.slice(0, cursor);
    const slashIdx = before.lastIndexOf("/");
    if (slashIdx === -1) return;
    textarea.value = val.slice(0, slashIdx) + cmd.cmd + " " + val.slice(cursor);
    textarea.setSelectionRange(slashIdx + cmd.cmd.length + 2, slashIdx + cmd.cmd.length + 2);
    textarea.focus();
    hideSlashPalette();
  }
  function updateTaskIndicator(taskType) {
    const el = document.getElementById("taskIndicator");
    if (!el) return;
    if (taskType) {
      el.textContent = taskType;
      el.style.display = "inline-block";
    } else {
      el.style.display = "none";
    }
  }
  function initCapabilityButtons() {
    document.querySelectorAll(".capability").forEach((btn) => {
      btn.addEventListener("click", function() {
        const taskType = this.dataset.task || null;
        if (lockedTaskType === taskType) {
          lockedTaskType = null;
          document.querySelectorAll(".capability").forEach((c) => c.classList.remove("selected"));
        } else {
          lockedTaskType = taskType;
          document.querySelectorAll(".capability").forEach((c) => c.classList.remove("selected"));
          this.classList.add("selected");
        }
        window.lockedTaskType = lockedTaskType;
        updateTaskIndicator(lockedTaskType);
      });
    });
  }
  let _thinkingTimerInterval = null;
  let _thinkingStartTime = 0;
  const _THINKING_PHRASES = ["Koto 正在思考...", "正在分析请求...", "整理思路中...", "正在生成回复...", "即将完成..."];
  let _thinkingPhraseIdx = 0;
  function showLoading(text, model) {
    const think = document.getElementById("inputThinking");
    if (!think) return;
    const textEl = document.getElementById("thinkingText");
    const timerEl = document.getElementById("thinkingTimer");
    if (textEl) textEl.textContent = text || "Koto 正在思考...";
    const modelEl = document.getElementById("currentModel");
    if (modelEl) modelEl.textContent = model ? "📦 " + model : "";
    if (timerEl) timerEl.textContent = "";
    think.style.display = "";
    const spinner = think.querySelector(".spinner");
    if (spinner) {
      spinner.style.animation = "";
      spinner.style.animationPlayState = "running";
    }
    _thinkingStartTime = Date.now();
    _thinkingPhraseIdx = 0;
    if (_thinkingTimerInterval) clearInterval(_thinkingTimerInterval);
    _thinkingTimerInterval = setInterval(() => {
      const elapsed = ((Date.now() - _thinkingStartTime) / 1e3).toFixed(0);
      if (timerEl) timerEl.textContent = elapsed + "s";
      if (!text) {
        _thinkingPhraseIdx = Math.floor((Date.now() - _thinkingStartTime) / 8e3) % _THINKING_PHRASES.length;
        if (textEl) textEl.textContent = _THINKING_PHRASES[_thinkingPhraseIdx];
      }
    }, 1e3);
  }
  function hideLoading() {
    if (_thinkingTimerInterval) {
      clearInterval(_thinkingTimerInterval);
      _thinkingTimerInterval = null;
    }
    const think = document.getElementById("inputThinking");
    if (think) {
      think.style.display = "none";
      const spinner = think.querySelector(".spinner");
      if (spinner) {
        spinner.style.animationPlayState = "paused";
        spinner.style.animation = "none";
      }
    }
    const textEl = document.getElementById("thinkingText");
    if (textEl) textEl.textContent = "Koto 正在思考...";
    const modelEl = document.getElementById("currentModel");
    if (modelEl) modelEl.textContent = "";
    const timerEl = document.getElementById("thinkingTimer");
    if (timerEl) timerEl.textContent = "";
  }
  function copyCode(btn) {
    const encoded = btn.dataset.code;
    if (!encoded) return;
    try {
      const code = decodeURIComponent(atob(encoded));
      navigator.clipboard.writeText(code).then(() => {
        const span = btn.querySelector("span");
        if (span) span.textContent = "已复制";
        setTimeout(() => {
          if (span) span.textContent = "复制";
        }, 1500);
      });
    } catch (e) {
    }
  }
  function copyTable(tableId) {
    const wrapper = document.getElementById(tableId);
    if (!wrapper) return;
    const table = wrapper.querySelector("table");
    if (!table) return;
    let text = "";
    table.querySelectorAll("tr").forEach((tr) => {
      const cells = Array.from(tr.querySelectorAll("th, td")).map((td) => td.innerText.trim());
      text += cells.join("	") + "\n";
    });
    navigator.clipboard.writeText(text).then(() => {
      if (typeof window.showNotification === "function") window.showNotification("表格已复制", "success", 1e3);
    }).catch(() => {
    });
  }
  function openInArtifact(btn) {
    const encoded = btn.dataset.code;
    const lang = btn.dataset.lang || "plaintext";
    if (!encoded) return;
    try {
      const code = decodeURIComponent(atob(encoded));
      if (window.WA && typeof window.WA.openFileInArtifact === "function") {
        window.WA.openFileInArtifact(code, lang);
      }
    } catch (e) {
    }
  }
  function downloadPPT(sessionId) {
    fetch(`/api/ppt/download/${encodeURIComponent(sessionId)}`).then((response) => {
      if (response.ok) return response.blob();
      throw new Error("下载失败");
    }).then((blob) => {
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `presentation_${sessionId.substr(0, 8)}.pptx`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
      if (typeof window.showNotification === "function") window.showNotification("✅ PPT 下载成功", "success");
    }).catch((err) => {
      if (typeof window.showNotification === "function") window.showNotification("❌ PPT 下载失败: " + err.message, "error");
    });
  }
  function renderSourcesPanel(sources) {
    if (!Array.isArray(sources) || sources.length === 0) return "";
    const items = sources.slice(0, 8).map((source, idx) => {
      const rawUrl = String(source.url || "").trim();
      const safeUrl = /^https?:\/\//i.test(rawUrl) ? rawUrl : "#";
      return `<a class="message-source-item" href="${safeUrl}" target="_blank"><span class="message-source-index">[${idx + 1}]</span><span class="message-source-title">${escapeHtml$1(String(source.title || `来源 ${idx + 1}`))}</span></a>`;
    }).join("");
    return `<div class="message-sources"><div class="message-sources-title">📚 参考来源</div><div class="message-sources-list">${items}</div></div>`;
  }
  function appendSourcesToBody(bodyEl, sources) {
    if (!bodyEl) return;
    const oldPanel = bodyEl.querySelector(".message-sources");
    if (oldPanel) oldPanel.remove();
    if (!Array.isArray(sources) || sources.length === 0) return;
    bodyEl.insertAdjacentHTML("beforeend", renderSourcesPanel(sources));
  }
  function escapeHtml$1(str) {
    return String(str || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function parseMarkdown(text) {
    if (!text) return "";
    try {
      if (typeof window.marked === "undefined") {
        return `<div class="markdown-fallback" style="white-space: pre-wrap;">${escapeHtml$1(text)}</div>`;
      }
      const marked = window.marked;
      const renderer = new marked.Renderer();
      renderer.table = function(header, body) {
        const tableId = "table-" + Math.random().toString(36).slice(2, 10);
        return `<div class="table-wrapper" id="${tableId}"><div class="table-header"><span class="table-label">📊 表格</span><button class="copy-table-btn" onclick="copyTable('${tableId}')" title="复制表格"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg><span>复制</span></button></div><div class="table-scroll"><table><thead>${header}</thead><tbody>${body}</tbody></table></div></div>`;
      };
      renderer.code = function(code, language) {
        try {
          if (language === "mermaid") {
            const mermaidId = "mermaid-" + Math.random().toString(36).slice(2, 10);
            return `<div class="mermaid-wrapper"><div class="mermaid" id="${mermaidId}">${escapeHtml$1(code)}</div></div>`;
          }
          if (typeof window.hljs === "undefined") return `<pre><code>${escapeHtml$1(code)}</code></pre>`;
          const hljs = window.hljs;
          const validLang = language && hljs.getLanguage(language) ? language : "";
          const highlighted = validLang ? hljs.highlight(code, { language: validLang }).value : hljs.highlightAuto(code).value;
          const encodedCode = btoa(unescape(encodeURIComponent(code)));
          const lineCount = (code.match(/\n/g) || []).length + 1;
          const artifactBtn = lineCount > 5 ? `<button class="open-artifact-btn" data-code="${encodedCode}" data-lang="${validLang || "plaintext"}" onclick="openInArtifact(this)" title="在侧面板中打开"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="3" x2="9" y2="21"/></svg><span>Artifact</span></button>` : "";
          return `<div class="code-block-wrapper"><div class="code-header"><span class="code-lang">${validLang || "code"}</span><div style="display:flex;align-items:center;gap:4px;">${artifactBtn}<button class="copy-btn" data-code="${encodedCode}" onclick="copyCode(this)" title="复制代码"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg><span>复制</span></button></div></div><pre data-lang="${validLang}"><code class="hljs language-${validLang || "plaintext"}">${highlighted}</code></pre></div>`;
        } catch {
          return `<pre><code>${code}</code></pre>`;
        }
      };
      renderer.link = function(href, title, text2) {
        if (href && (href.startsWith("http://") || href.startsWith("https://"))) {
          return `<a href="${href}" data-ext="1"${title ? ` title="${title}"` : ""} class="ext-link">${text2}</a>`;
        }
        return `<a href="${href || "#"}">${text2}</a>`;
      };
      marked.setOptions({ renderer, breaks: true, gfm: true });
      let html = marked.parse(text);
      html = renderKaTeX(html);
      return html;
    } catch (e) {
      return String(text);
    }
  }
  function renderKaTeX(html) {
    if (typeof window.katex === "undefined") return html;
    const katex = window.katex;
    try {
      html = html.replace(/\$\$([\s\S]+?)\$\$/g, (_match, tex) => {
        try {
          return katex.renderToString(tex.trim(), { displayMode: true, throwOnError: false });
        } catch {
          return _match;
        }
      });
      html = html.replace(/(?<!\$)\$(?!\$)([^\n$]+?)\$(?!\$)/g, (_match, tex) => {
        try {
          return katex.renderToString(tex.trim(), { displayMode: false, throwOnError: false });
        } catch {
          return _match;
        }
      });
    } catch (e) {
    }
    return html;
  }
  let _mermaidLoading = null;
  function _ensureMermaid() {
    if (typeof window.mermaid !== "undefined") return Promise.resolve();
    if (_mermaidLoading) return _mermaidLoading;
    _mermaidLoading = new Promise((resolve) => {
      const script = document.createElement("script");
      script.src = "/static/vendor/mermaid/10.9.0/mermaid.min.js";
      script.onload = () => {
        resolve();
      };
      script.onerror = () => resolve();
      document.head.appendChild(script);
    });
    return _mermaidLoading;
  }
  async function renderMermaidBlocks() {
    await _ensureMermaid();
    if (typeof window.mermaid === "undefined") return;
    const mermaid = window.mermaid;
    try {
      const blocks = document.querySelectorAll(".mermaid");
      for (const block of Array.from(blocks)) {
        if (block.dataset.rendered === "true") continue;
        try {
          const id = block.id;
          const code = block.textContent || "";
          const { svg } = await mermaid.render("mermaid-svg-" + id, code);
          block.innerHTML = svg;
          block.dataset.rendered = "true";
        } catch (e) {
        }
      }
    } catch (e) {
    }
  }
  function highlightCode() {
    if (typeof window.hljs === "undefined") return;
    document.querySelectorAll("pre code").forEach((block) => {
      if (!block.classList.contains("hljs")) {
        try {
          window.hljs.highlightElement(block);
        } catch (e) {
        }
      }
    });
  }
  function toggleHotkeySheet() {
    const el = document.getElementById("hotkeySheet");
    if (el) el.classList.toggle("active");
  }
  function closeHotkeySheet() {
    const el = document.getElementById("hotkeySheet");
    if (el) el.classList.remove("active");
  }
  function updateInputMeta(textarea) {
    const metaBar = document.getElementById("inputMetaBar");
    if (!metaBar) return;
    const chars = textarea.value.length;
    metaBar.textContent = chars > 0 ? `${chars} 字` : "";
  }
  async function trainWritingStyle() {
    const sampleText = prompt("请粘贴你的写作样本（建议 200 字以上，用于学习风格）:");
    if (!sampleText || !sampleText.trim()) return;
    const sampleName = prompt("给这个风格样本起个名字（可选）:", "default") || "default";
    try {
      const btn = document.getElementById("writingStyleBtn");
      if (btn) {
        btn.disabled = true;
        btn.textContent = "⏳ 学习中";
      }
      const resp = await csrfFetch("/api/memory/style-profile", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sample_text: sampleText, sample_name: sampleName }) });
      const data = await resp.json();
      if (!resp.ok || !data.success) throw new Error(data.error || "风格学习失败");
      const profile = data.style_profile || {};
      const summary = [`✅ 写作风格学习完成（样本：${sampleName}）`, `- 语气：${profile.formality || "neutral"}`, `- 详细度：${profile.preferred_detail_level || "moderate"}`, `- 结构偏好：${profile.structure_preference || "paragraph_first"}`, `- 风格标签：${Array.isArray(profile.tone_tags) ? profile.tone_tags.join("、") : "无"}`].join("\n");
      const chatMessages = document.getElementById("chatMessages");
      const welcome = document.getElementById("welcomeScreen");
      if (welcome) welcome.style.display = "none";
      if (chatMessages) chatMessages.insertAdjacentHTML("beforeend", renderMessage("assistant", summary, { task: "STYLE_PROFILE" }));
      scrollToBottomForce$1();
      if (typeof window.showNotification === "function") window.showNotification("写作风格已更新", "success", 1800);
    } catch (err) {
      if (typeof window.showNotification === "function") window.showNotification(`风格学习失败: ${err.message || err}`, "error", 2600);
    } finally {
      const btn = document.getElementById("writingStyleBtn");
      if (btn) {
        btn.disabled = false;
        btn.textContent = "✍️ 风格学习";
      }
    }
  }
  window.renderChatHistory = renderChatHistory;
  window.renderMessage = renderMessage;
  window.copyMessageText = copyMessageText;
  window.resendMessage = resendMessage;
  window.editUserMessage = editUserMessage;
  window.regenMessage = regenMessage;
  window.updateFilePreview = updateFilePreview;
  window.removeSingleFile = removeSingleFile;
  window.setSelectedFiles = setSelectedFiles;
  window.handleFileSelect = handleFileSelect;
  window.removeFile = removeFile;
  window.handleDragOver = handleDragOver;
  window.handleDragLeave = handleDragLeave;
  window.handleDrop = handleDrop;
  window.autoResize = autoResize;
  window.generateSessionName = generateSessionName;
  window.autoTitleSession = autoTitleSession;
  window.openChatSearch = openChatSearch;
  window.closeChatSearch = closeChatSearch;
  window.runChatSearch = runChatSearch;
  window.chatSearchNext = chatSearchNext;
  window.chatSearchPrev = chatSearchPrev;
  window.clearChatSearchHighlights = clearChatSearchHighlights;
  window.onModelChange = onModelChange;
  window.handleAtMention = handleAtMention;
  window.pinContextFile = pinContextFile;
  window.removeContextFile = removeContextFile;
  window.openSavedWorkspaceFile = openSavedWorkspaceFile;
  window.handleSlashCommand = handleSlashCommand;
  window.selectSlashCommand = selectSlashCommand;
  window.updateInputMeta = updateInputMeta;
  window.initCapabilityButtons = initCapabilityButtons;
  window.updateTaskIndicator = updateTaskIndicator;
  window.showLoading = showLoading;
  window.hideLoading = hideLoading;
  window.showMiniGame = showMiniGame;
  window.hideMiniGame = hideMiniGame;
  window.copyCode = copyCode;
  window.copyTable = copyTable;
  window.openInArtifact = openInArtifact;
  window.downloadPPT = downloadPPT;
  window.renderSourcesPanel = renderSourcesPanel;
  window.appendSourcesToBody = appendSourcesToBody;
  window.escapeHtml = escapeHtml$1;
  window.parseMarkdown = parseMarkdown;
  window.toggleHotkeySheet = toggleHotkeySheet;
  window.closeHotkeySheet = closeHotkeySheet;
  window.trainWritingStyle = trainWritingStyle;
  window._fileIcon = _fileIcon;
  window._newlyCreatedSessions = _newlyCreatedSessions;
  let _allSkills = [];
  let _currentSkillFilter = "all";
  let _editingSkillId = null;
  const SKILL_CATEGORY_LABELS = { behavior: "⚙️ 行为", style: "🎨 风格", domain: "🔬 领域" };
  const SKILL_CAT_COLORS = { behavior: "#4a9eff", style: "#e06c75", domain: "#98c379" };
  const _csrfFetch = csrfFetch;
  function _html(s) {
    return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function _inlineArg(s) {
    return String(s ?? "").replace(/\\/g, "\\\\").replace(/'/g, "\\'").replace(/\r?\n/g, " ");
  }
  async function loadSkills() {
    const listEl = document.getElementById("skillsList");
    if (!listEl) return;
    listEl.innerHTML = '<div class="memory-empty">正在加载 Skills…</div>';
    try {
      const resp = await fetch("/api/skills");
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const data = await resp.json();
      if (!data.success) throw new Error(data.error || "加载失败");
      _allSkills = data.skills || [];
      renderSkills(_currentSkillFilter);
    } catch (e) {
      listEl.innerHTML = `<div class="memory-empty" style="color:var(--error-color)">⚠️ Skills 加载失败: ${e.message}</div>`;
    }
  }
  function renderSkills(filter) {
    _currentSkillFilter = filter;
    const listEl = document.getElementById("skillsList");
    if (!listEl || !_allSkills.length) return;
    document.querySelectorAll(".skill-tab").forEach((btn) => {
      const btnFilter = (btn.textContent || "").includes("行为") ? "behavior" : (btn.textContent || "").includes("风格") ? "style" : (btn.textContent || "").includes("领域") ? "domain" : "all";
      btn.classList.toggle("active", btnFilter === filter);
    });
    const filtered = filter === "all" ? _allSkills : _allSkills.filter((s) => s.category === filter);
    if (!filtered.length) {
      listEl.innerHTML = '<div class="memory-empty">该分类暂无 Skill</div>';
      return;
    }
    listEl.innerHTML = filtered.map((skill) => {
      const scope = skill.task_types && skill.task_types.length ? skill.task_types.join(" · ") : "全任务类型";
      const catColor = SKILL_CAT_COLORS[skill.category] || "#aaa";
      const customTag = skill.has_custom_prompt ? '<span style="font-size:10px;color:var(--accent);margin-left:4px;">✏️已自定义</span>' : "";
      return `<div class="skill-card ${skill.enabled ? "active" : ""}" data-id="${skill.id}" data-category="${skill.category}"><div class="skill-card-header"><span class="skill-icon">${skill.icon}</span><div class="skill-info"><span class="skill-name">${skill.name}${customTag}</span><span class="skill-scope" style="border-left:2px solid ${catColor};padding-left:5px;">${SKILL_CATEGORY_LABELS[skill.category] || skill.category} &nbsp;·&nbsp; ${scope}</span></div>${skill.is_builtin ? "" : `<button class="skill-gear-btn" onclick="event.stopPropagation();openSkillEditor('${skill.id}')" title="编辑 Prompt">⚙</button>`}<label class="toggle" title="${skill.enabled ? "点击禁用" : "点击启用"}"><input type="checkbox" ${skill.enabled ? "checked" : ""} onchange="toggleSkill('${skill.id}', this.checked)"><span class="toggle-slider"></span></label></div><p class="skill-desc">${skill.description}</p></div>`;
    }).join("");
  }
  function filterSkills(category) {
    renderSkills(category);
  }
  async function toggleSkill(skillId, enabled) {
    const card = document.querySelector(`.skill-card[data-id="${skillId}"]`);
    if (card) card.classList.toggle("active", enabled);
    const skill = _allSkills.find((s) => s.id === skillId);
    if (skill) skill.enabled = enabled;
    try {
      const resp = await _csrfFetch(`/api/skills/${encodeURIComponent(skillId)}/toggle`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled }) });
      const data = await resp.json();
      if (!data.success) throw new Error(data.error || "操作失败");
      if (typeof window.refreshActiveSkills === "function") window.refreshActiveSkills();
    } catch (e) {
      if (card) card.classList.toggle("active", !enabled);
      if (skill) skill.enabled = !enabled;
      if (typeof window.showNotification === "function") window.showNotification("切换失败: " + e.message, "error");
    }
  }
  const _SKE_THEMES = {
    none: null,
    mystic_purple: { "--bg-primary": "#110820", "--bg-secondary": "#1a1135", "--bg-tertiary": "#221848", "--bg-card": "rgba(192,132,252,0.10)", "--accent-primary": "#d8a4ff", "--accent-secondary": "#f0a0ff", "--accent-gradient": "linear-gradient(135deg,#d8a4ff,#f0a0ff)", "--border-color": "rgba(192,132,252,0.28)", "--text-primary": "#f4ecff", "--text-secondary": "#d4b8f0", "--text-muted": "#a888cc", "--user-msg-bg": "linear-gradient(135deg,rgba(192,132,252,0.28),rgba(232,121,249,0.22))", "--assistant-msg-bg": "rgba(192,132,252,0.13)" },
    ocean_blue: { "--bg-primary": "#0d1b2e", "--bg-secondary": "#112240", "--bg-tertiary": "#1a3050", "--bg-card": "rgba(56,189,248,0.09)", "--accent-primary": "#38bdf8", "--accent-secondary": "#7dd3fc", "--accent-gradient": "linear-gradient(135deg,#38bdf8,#818cf8)", "--border-color": "rgba(56,189,248,0.25)", "--text-primary": "#e2f0ff", "--text-secondary": "#93c5fd", "--text-muted": "#5fa8d3", "--user-msg-bg": "linear-gradient(135deg,rgba(56,189,248,0.22),rgba(129,140,248,0.18))", "--assistant-msg-bg": "rgba(56,189,248,0.10)" },
    amber_gold: { "--bg-primary": "#0c0e14", "--bg-secondary": "#13161f", "--bg-tertiary": "#1a1e2e", "--bg-card": "rgba(251,191,36,0.08)", "--accent-primary": "#fbbf24", "--accent-secondary": "#f59e0b", "--accent-gradient": "linear-gradient(135deg,#fbbf24,#f97316)", "--border-color": "rgba(251,191,36,0.22)", "--text-primary": "#f0ead6", "--text-secondary": "#d4b483", "--text-muted": "#8a7355", "--user-msg-bg": "linear-gradient(135deg,rgba(251,191,36,0.20),rgba(249,115,22,0.15))", "--assistant-msg-bg": "rgba(251,191,36,0.08)" },
    rose_pink: { "--bg-primary": "#1a0e14", "--bg-secondary": "#241018", "--bg-tertiary": "#2e1520", "--bg-card": "rgba(244,114,182,0.09)", "--accent-primary": "#f472b6", "--accent-secondary": "#fb7185", "--accent-gradient": "linear-gradient(135deg,#f472b6,#fb7185)", "--border-color": "rgba(244,114,182,0.25)", "--text-primary": "#fce7f3", "--text-secondary": "#f9a8d4", "--text-muted": "#a0527a", "--user-msg-bg": "linear-gradient(135deg,rgba(244,114,182,0.22),rgba(251,113,133,0.16))", "--assistant-msg-bg": "rgba(244,114,182,0.09)" },
    cyan_space: { "--bg-primary": "#0a0f1a", "--bg-secondary": "#0f1726", "--bg-tertiary": "#162035", "--bg-card": "rgba(34,211,238,0.08)", "--accent-primary": "#22d3ee", "--accent-secondary": "#67e8f9", "--accent-gradient": "linear-gradient(135deg,#22d3ee,#818cf8)", "--border-color": "rgba(34,211,238,0.22)", "--text-primary": "#e0f7ff", "--text-secondary": "#a5f3fc", "--text-muted": "#4fa8bf", "--user-msg-bg": "linear-gradient(135deg,rgba(34,211,238,0.20),rgba(129,140,248,0.15))", "--assistant-msg-bg": "rgba(34,211,238,0.08)" },
    forest_green: { "--bg-primary": "#0a1a10", "--bg-secondary": "#0f2218", "--bg-tertiary": "#152e1e", "--bg-card": "rgba(52,211,153,0.09)", "--accent-primary": "#34d399", "--accent-secondary": "#6ee7b7", "--accent-gradient": "linear-gradient(135deg,#34d399,#10b981)", "--border-color": "rgba(52,211,153,0.22)", "--text-primary": "#e0fff0", "--text-secondary": "#a7f3d0", "--text-muted": "#4da87a", "--user-msg-bg": "linear-gradient(135deg,rgba(52,211,153,0.20),rgba(16,185,129,0.15))", "--assistant-msg-bg": "rgba(52,211,153,0.08)" },
    fire_red: { "--bg-primary": "#1a0a0a", "--bg-secondary": "#261010", "--bg-tertiary": "#321515", "--bg-card": "rgba(251,146,60,0.09)", "--accent-primary": "#fb923c", "--accent-secondary": "#f97316", "--accent-gradient": "linear-gradient(135deg,#fb923c,#dc2626)", "--border-color": "rgba(251,146,60,0.25)", "--text-primary": "#fff1e6", "--text-secondary": "#fcd4a8", "--text-muted": "#a06040", "--user-msg-bg": "linear-gradient(135deg,rgba(251,146,60,0.22),rgba(220,38,38,0.15))", "--assistant-msg-bg": "rgba(251,146,60,0.08)" }
  };
  function openSkillEditor(skillId) {
    const spSkills = typeof window.getSpSkills === "function" ? window.getSpSkills() : [];
    const skill = _allSkills.find((s) => s.id === skillId) || spSkills.find((s) => s.id === skillId);
    if (!skill) return;
    _editingSkillId = skillId;
    const skeIcon = document.getElementById("skeIcon");
    if (skeIcon) skeIcon.textContent = skill.icon || "🤖";
    const skeTitle = document.getElementById("skeTitle");
    if (skeTitle) skeTitle.textContent = skill.name;
    const catLabels = { behavior: "⚙️ 行为", style: "🎨 风格", domain: "🔬 领域", custom: "🔧 自定义", workflow: "⚡ 工作流", memory: "🧠 记忆" };
    const skeMeta = document.getElementById("skeMeta");
    if (skeMeta) skeMeta.textContent = (catLabels[skill.category] || skill.category) + (skill.is_builtin ? "  ·  内置 Skill" : "  ·  自定义 Skill");
    const editorContent = document.getElementById("skillEditorContent");
    if (editorContent) {
      editorContent.value = skill.prompt || "";
      skeUpdateCount();
    }
    const skeAiDesc = document.getElementById("skeAiDesc");
    if (skeAiDesc) skeAiDesc.value = "";
    const skeAiPreview = document.getElementById("skeAiPreview");
    if (skeAiPreview) skeAiPreview.style.display = "none";
    const skeExtractZone = document.getElementById("skeExtractZone");
    if (skeExtractZone) skeExtractZone.style.display = "none";
    const skeExtractMsg = document.getElementById("skeExtractMsg");
    if (skeExtractMsg) skeExtractMsg.textContent = "";
    skeLoadUiTab(skill.ui_config || {}, skill.ui_extensions || {});
    skeSwitchTab("edit");
    const modal = document.getElementById("skillEditorModal");
    if (modal) modal.style.display = "flex";
  }
  function closeSkillEditor() {
    const modal = document.getElementById("skillEditorModal");
    if (modal) modal.style.display = "none";
    _editingSkillId = null;
  }
  function skeUpdateCount() {
    const el = document.getElementById("skeCharCount");
    const ta = document.getElementById("skillEditorContent");
    if (el && ta) el.textContent = String(ta.value.length);
  }
  function skeSwitchTab(tab) {
    ["edit", "ai", "extract", "ui"].forEach((t) => {
      const btn = document.querySelector(`.ske-tab[data-tab="${t}"]`);
      if (btn) btn.classList.toggle("active", t === tab);
      const body = document.getElementById("skeTab" + t.charAt(0).toUpperCase() + t.slice(1));
      if (body) body.style.display = t === tab ? "block" : "none";
    });
    if (tab === "extract") skeLoadSessions();
  }
  async function skeGeneratePrompt() {
    const desc = (document.getElementById("skeAiDesc")?.value || "").trim();
    if (!desc) {
      if (typeof window.showNotification === "function") window.showNotification("请先描述你的需求", "warn");
      return;
    }
    const previewEl = document.getElementById("skeAiPreview");
    const previewContent = document.getElementById("skeAiPreviewContent");
    if (previewEl) previewEl.style.display = "block";
    if (previewContent) previewContent.textContent = "⏳ AI 正在生成…";
    try {
      const resp = await _csrfFetch("/api/skillmarket/preview-prompt", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ description: desc }) });
      const data = await resp.json();
      if (!data.success) throw new Error(data.error || "生成失败");
      if (previewContent) previewContent.textContent = data.prompt || data.system_prompt || "（空）";
    } catch (e) {
      if (previewContent) previewContent.textContent = "⚠️ " + e.message;
    }
  }
  function skeApplyGenerated() {
    const previewContent = document.getElementById("skeAiPreviewContent");
    const text = previewContent?.textContent || "";
    if (!text || text.startsWith("⏳") || text.startsWith("⚠️")) return;
    const editor = document.getElementById("skillEditorContent");
    if (editor) {
      editor.value = text;
      skeUpdateCount();
    }
    skeSwitchTab("edit");
  }
  let _skeSelectedSession = null;
  async function skeLoadSessions() {
    const list = document.getElementById("skeSessionList");
    if (!list) return;
    list.innerHTML = '<div style="color:#6c7a91;font-size:12px;padding:6px;">正在加载对话列表…</div>';
    try {
      const resp = await fetch("/api/skillmarket/sessions");
      const data = await resp.json();
      const sessions = data.sessions || [];
      if (!sessions.length) {
        list.innerHTML = '<div style="color:#6c7a91;font-size:12px;padding:6px;">暂无对话记录，请先进行一些对话。</div>';
        return;
      }
      list.innerHTML = sessions.map((s) => `<div class="ske-session-item" data-sid="${s.id}" onclick="skeSelectSession('${s.id}', this)">💬 ${s.title || s.id}<span style="float:right;color:#4a5568;font-size:10px;">${s.message_count || 0} 条</span></div>`).join("");
    } catch (e) {
      list.innerHTML = `<div style="color:#e06c75;font-size:12px;padding:6px;">⚠️ ${e.message}</div>`;
    }
  }
  function skeSelectSession(sessionId, el) {
    _skeSelectedSession = sessionId;
    document.querySelectorAll(".ske-session-item").forEach((i) => i.classList.remove("selected"));
    el.classList.add("selected");
    const extractZone = document.getElementById("skeExtractZone");
    if (extractZone) extractZone.style.display = "block";
    const extractMsg = document.getElementById("skeExtractMsg");
    if (extractMsg) extractMsg.textContent = "";
  }
  async function skeExtractFromSession() {
    if (!_skeSelectedSession || !_editingSkillId) return;
    const msgEl = document.getElementById("skeExtractMsg");
    const btn = document.querySelector("#skeExtractZone .ske-extract-btn");
    if (btn) btn.disabled = true;
    if (msgEl) {
      msgEl.style.color = "#6c7a91";
      msgEl.textContent = "⏳ AI 正在分析对话风格…";
    }
    try {
      const resp = await _csrfFetch("/api/skillmarket/from-session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: _skeSelectedSession, skill_name: _editingSkillId, icon: "", auto_enable: false }) });
      const data = await resp.json();
      if (!data.success) throw new Error(data.error || "提取失败");
      const prompt2 = data.prompt || data.skill?.prompt || "";
      const editor = document.getElementById("skillEditorContent");
      if (editor) {
        editor.value = prompt2;
        skeUpdateCount();
      }
      skeSwitchTab("edit");
      if (msgEl) msgEl.textContent = "";
    } catch (e) {
      if (msgEl) {
        msgEl.style.color = "#e06c75";
        msgEl.textContent = "⚠️ " + e.message;
      }
    } finally {
      if (btn) btn.disabled = false;
    }
  }
  async function saveSkillPromptEdit() {
    if (!_editingSkillId) return;
    const prompt2 = document.getElementById("skillEditorContent").value;
    try {
      const resp = await _csrfFetch(`/api/skills/${encodeURIComponent(_editingSkillId)}/prompt`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt: prompt2 }) });
      const data = await resp.json();
      if (!data.success) throw new Error(data.error);
      const uiPayload = skeCollectUiConfig();
      const hasUiChanges = Object.keys(uiPayload.ui_config || {}).length > 0 || (uiPayload.ui_extensions?.action_buttons || []).length > 0;
      if (hasUiChanges) {
        const permissions = [];
        if (uiPayload.ui_config?.css_vars || uiPayload.ui_config?.theme) permissions.push("ui_style");
        if ((uiPayload.ui_extensions?.action_buttons || []).length > 0) permissions.push("ui_interactive");
        await _csrfFetch(`/api/skills/${encodeURIComponent(_editingSkillId)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...uiPayload, permissions }) });
      }
      const skill = _allSkills.find((s) => s.id === _editingSkillId);
      if (skill) {
        skill.prompt = prompt2;
        skill.has_custom_prompt = prompt2.trim() !== "";
        if (hasUiChanges) {
          skill.ui_config = uiPayload.ui_config;
          skill.ui_extensions = uiPayload.ui_extensions;
        }
      }
      closeSkillEditor();
      renderSkills(_currentSkillFilter);
      if (typeof window.spRenderCards === "function") window.spRenderCards();
      if (typeof window.SkillUI === "object") window.SkillUI.refresh();
    } catch (e) {
      if (typeof window.showNotification === "function") window.showNotification("保存失败: " + e.message, "error");
    }
  }
  async function resetSkillPromptEdit() {
    if (!_editingSkillId) return;
    if (!confirm("确定恢复该 Skill 的默认 Prompt 吗？")) return;
    try {
      const resp = await _csrfFetch(`/api/skills/${encodeURIComponent(_editingSkillId)}/reset`, { method: "POST" });
      const data = await resp.json();
      if (!data.success) throw new Error(data.error);
      const listResp = await fetch("/api/skills");
      const listData = await listResp.json();
      if (listData.success) {
        _allSkills = listData.skills;
        const skill = _allSkills.find((s) => s.id === _editingSkillId);
        if (skill) {
          const editor = document.getElementById("skillEditorContent");
          if (editor) {
            editor.value = skill.prompt || "";
            skeUpdateCount();
          }
        }
      }
      renderSkills(_currentSkillFilter);
    } catch (e) {
      if (typeof window.showNotification === "function") window.showNotification("恢复失败: " + e.message, "error");
    }
  }
  function skePickTheme(el) {
    document.querySelectorAll("#skeColorSwatches .ske-swatch").forEach((s) => s.classList.remove("active"));
    el.classList.add("active");
  }
  function skeLoadUiTab(uiConfig, uiExt) {
    const cssVars = uiConfig.css_vars || {};
    let matchedKey = "none";
    if (cssVars["--accent-primary"]) {
      for (const [key, vars] of Object.entries(_SKE_THEMES)) {
        if (vars && vars["--accent-primary"] === cssVars["--accent-primary"]) {
          matchedKey = key;
          break;
        }
      }
    }
    document.querySelectorAll("#skeColorSwatches .ske-swatch").forEach((s) => {
      s.classList.toggle("active", s.getAttribute("data-theme-key") === matchedKey);
    });
    const overlayEl = document.getElementById("skeOverlayEffect");
    if (overlayEl) overlayEl.value = uiConfig.overlay_effect || "";
    const f = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.value = val || "";
    };
    f("skeTitleText", uiConfig.title_text || "");
    f("skeSubtitleText", uiConfig.subtitle_text || "");
    f("skePlaceholderText", uiConfig.input_placeholder || "");
    f("skeWelcomeText", uiConfig.welcome_text || "");
    f("skeAssistantPrefix", uiConfig.assistant_prefix || "");
    const buttons = (uiExt.action_buttons || []).filter((b) => b.id !== "open_dice");
    const listEl = document.getElementById("skeActionBtnList");
    if (listEl) {
      listEl.innerHTML = "";
      buttons.forEach((b) => skeAddActionBtn(b.label || "", b.message || ""));
    }
  }
  function skeAddActionBtn(label, message) {
    const listEl = document.getElementById("skeActionBtnList");
    if (!listEl) return;
    const row = document.createElement("div");
    row.className = "ske-action-btn-row";
    row.innerHTML = `<input type="text" placeholder="按钮名称" value="${_skeEsc(label || "")}"><span class="ske-action-btn-sep">→</span><input type="text" placeholder="点击后发送的消息" value="${_skeEsc(message || "")}"><button class="ske-rm-btn" title="删除" onclick="this.closest('.ske-action-btn-row').remove()">×</button>`;
    listEl.appendChild(row);
  }
  function _skeEsc(s) {
    return String(s).replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function skeCollectUiConfig() {
    const activeThemeSwatch = document.querySelector("#skeColorSwatches .ske-swatch.active");
    const themeKey = activeThemeSwatch ? activeThemeSwatch.getAttribute("data-theme-key") || "none" : "none";
    const cssVars = _SKE_THEMES[themeKey] || null;
    const overlay = document.getElementById("skeOverlayEffect")?.value || "";
    const titleT = document.getElementById("skeTitleText")?.value || "";
    const subT = document.getElementById("skeSubtitleText")?.value || "";
    const phText = document.getElementById("skePlaceholderText")?.value || "";
    const welcome = document.getElementById("skeWelcomeText")?.value || "";
    const prefix = document.getElementById("skeAssistantPrefix")?.value || "";
    const uiConfig = {};
    if (cssVars) uiConfig.css_vars = cssVars;
    if (overlay) uiConfig.overlay_effect = overlay;
    if (titleT) uiConfig.title_text = titleT;
    if (subT) uiConfig.subtitle_text = subT;
    if (phText) uiConfig.input_placeholder = phText;
    if (welcome) uiConfig.welcome_text = welcome;
    if (prefix) uiConfig.assistant_prefix = prefix;
    const btnRows = document.querySelectorAll(".ske-action-btn-row");
    const actionButtons = [];
    btnRows.forEach((row) => {
      const inputs = row.querySelectorAll("input");
      if (inputs.length >= 2) {
        const label = inputs[0].value.trim();
        const message = inputs[1].value.trim();
        if (label) actionButtons.push({ id: "btn_" + Date.now(), label, message });
      }
    });
    const uiExtensions = {};
    if (actionButtons.length) uiExtensions.action_buttons = actionButtons;
    return { ui_config: uiConfig, ui_extensions: uiExtensions };
  }
  async function loadSkillBindings() {
    const listEl = document.getElementById("skillBindingsList");
    if (!listEl) return;
    try {
      const resp = await fetch("/api/skills/bindings?binding_type=intent");
      const data = await resp.json();
      const bindings = data.bindings || data.data || [];
      if (!bindings.length) {
        listEl.innerHTML = '<div class="memory-empty">暂无意向绑定</div>';
        return;
      }
      listEl.innerHTML = bindings.map((b) => {
        const id = b.binding_id || b.id || "";
        const patterns = Array.isArray(b.intent_patterns) ? b.intent_patterns.join(" / ") : b.intent || b.pattern || b.binding_type || "—";
        return `<div class="binding-card"><strong>${_html(patterns)}</strong> → ${_html(b.skill_id || "—")}<button onclick="deleteSkillBinding('${_inlineArg(id)}')" style="float:right;">✕</button></div>`;
      }).join("");
    } catch (e) {
      listEl.innerHTML = '<div class="memory-empty">加载失败</div>';
    }
  }
  async function deleteSkillBinding(bindingId) {
    try {
      await _csrfFetch(`/api/skills/bindings/${encodeURIComponent(bindingId)}`, { method: "DELETE" });
      loadSkillBindings();
    } catch (e) {
    }
  }
  function _triggerSchedule(t) {
    const cfg = t.config || {};
    if (t.trigger_type === "interval" && cfg.interval_seconds) return `每 ${cfg.interval_seconds}s`;
    if (t.trigger_type === "cron" && cfg.time) return String(cfg.time);
    if (t.cron) return String(t.cron);
    return t.trigger_type || "—";
  }
  async function loadTriggers() {
    const listEl = document.getElementById("triggersList");
    if (!listEl) return;
    try {
      const resp = await fetch("/api/jobs/triggers");
      const data = await resp.json();
      const triggers = data.triggers || data.data || [];
      if (!triggers.length) {
        listEl.innerHTML = '<div class="memory-empty">暂无定时触发器</div>';
        return;
      }
      listEl.innerHTML = triggers.map((t) => {
        const id = t.trigger_id || t.id || "";
        const enabled = t.enabled !== false;
        const target = t.name || t.skill_id || t.job_type || "—";
        return `<div class="trigger-card"><span>${_html(_triggerSchedule(t))}</span><strong>${_html(target)}</strong><span>${enabled ? "✅" : "⏸️"}</span><button onclick="toggleTrigger('${_inlineArg(id)}',${!enabled})">${enabled ? "禁用" : "启用"}</button></div>`;
      }).join("");
    } catch (e) {
      listEl.innerHTML = '<div class="memory-empty">加载失败</div>';
    }
  }
  async function toggleTrigger(triggerId, enabled) {
    try {
      await _csrfFetch(`/api/jobs/triggers/${encodeURIComponent(triggerId)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled }) });
      loadTriggers();
    } catch (e) {
    }
  }
  window.loadSkills = loadSkills;
  window.renderSkills = renderSkills;
  window.filterSkills = filterSkills;
  window.toggleSkill = toggleSkill;
  window.openSkillEditor = openSkillEditor;
  window.closeSkillEditor = closeSkillEditor;
  window.skeUpdateCount = skeUpdateCount;
  window.skeSwitchTab = skeSwitchTab;
  window.skeGeneratePrompt = skeGeneratePrompt;
  window.skeApplyGenerated = skeApplyGenerated;
  window.skeLoadSessions = skeLoadSessions;
  window.skeSelectSession = skeSelectSession;
  window.skeExtractFromSession = skeExtractFromSession;
  window.saveSkillPromptEdit = saveSkillPromptEdit;
  window.resetSkillPromptEdit = resetSkillPromptEdit;
  window.skePickTheme = skePickTheme;
  window.skeLoadUiTab = skeLoadUiTab;
  window.skeAddActionBtn = skeAddActionBtn;
  window.skeCollectUiConfig = skeCollectUiConfig;
  window.loadSkillBindings = loadSkillBindings;
  window.deleteSkillBinding = deleteSkillBinding;
  window.loadTriggers = loadTriggers;
  window.toggleTrigger = toggleTrigger;
  let currentSettings = null;
  let currentBrowseTarget = null;
  let currentBrowsePath = "";
  let allLocalModels = [];
  window.currentSettings = currentSettings;
  window.browseHomeDir = "";
  async function loadSettings() {
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const response = await fetch("/api/settings");
        if (response.ok) {
          currentSettings = await response.json();
          window.currentSettings = currentSettings;
          applySettingsToUI();
          return;
        }
      } catch (error) {
      }
      if (attempt < 2) await new Promise((r) => setTimeout(r, 500));
    }
    console.error("Failed to load settings after all retries");
  }
  function applySettingsToUI() {
    if (!currentSettings) return;
    const s = currentSettings;
    const setVal = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.value = val || "";
    };
    setVal("settingWorkspaceDir", s.storage?.workspace_dir || "");
    setVal("settingDocumentsDir", s.storage?.documents_dir || "");
    setVal("settingImagesDir", s.storage?.images_dir || "");
    setVal("settingChatsDir", s.storage?.chats_dir || "");
    window.browseHomeDir = s.storage?.workspace_dir || "";
    const currentTheme = s.appearance?.theme || "light";
    if (typeof window.updateThemeSelector === "function") window.updateThemeSelector(currentTheme);
    if (typeof window.applyTheme === "function") window.applyTheme(currentTheme);
    localStorage.setItem("koto.theme", currentTheme);
    const cloudProviderEl = document.getElementById("settingCloudProvider");
    if (cloudProviderEl) {
      cloudProviderEl.value = "deepseek";
      syncCloudProviderUi();
    }
    const showThinkingCheckbox = document.getElementById("settingShowThinking");
    if (showThinkingCheckbox) showThinkingCheckbox.checked = s.ai?.show_thinking === true;
    const showTaskTypeCheckbox = document.getElementById("settingShowTaskType");
    if (showTaskTypeCheckbox) showTaskTypeCheckbox.checked = s.ai?.show_task_type === true;
    const autoSaveFilesCheckbox = document.getElementById("settingAutoSaveFiles");
    if (autoSaveFilesCheckbox) autoSaveFilesCheckbox.checked = s.ai?.auto_save_files !== false;
    const miniGameCheckbox = document.getElementById("settingEnableMiniGame");
    if (miniGameCheckbox) {
      const isEnabled = s.ai?.enable_mini_game !== false;
      miniGameCheckbox.checked = isEnabled;
      window.enableMiniGame = isEnabled;
    }
    const localOnlyEl = document.getElementById("settingLocalOnly");
    if (localOnlyEl) {
      const localOnly = s.ai?.use_local_only === true;
      localOnlyEl.checked = localOnly;
      applyLocalOnlyMode(localOnly);
    }
    const savedZoom = parseFloat(String(s.appearance?.ui_zoom || "1"));
    if (Number.isFinite(savedZoom) && typeof window.setUIZoom === "function") {
      window.setUIZoom(String(savedZoom), true);
    }
    const proxyEnabledEl = document.getElementById("settingProxyEnabled");
    if (proxyEnabledEl) proxyEnabledEl.checked = s.proxy?.enabled !== false;
    setVal("settingManualProxy", s.proxy?.manual_proxy || "");
  }
  function setActivityActive(id) {
    document.querySelectorAll(".activity-btn").forEach((button) => button.classList.remove("active"));
    const target = document.getElementById(id);
    if (target) target.classList.add("active");
  }
  function isUnifiedWorkspace() {
    return document.body.classList.contains("koto-unified-workspace") || document.documentElement.classList.contains("koto-unified-workspace");
  }
  function openSettings() {
    if (typeof window.closeSkillsPanel === "function") window.closeSkillsPanel();
    loadSettings();
    if (typeof window.loadSkills === "function") window.loadSkills();
    if (typeof window.loadSkillBindings === "function") window.loadSkillBindings();
    if (typeof window.loadTriggers === "function") window.loadTriggers();
    if (typeof window.loadShadowStatus === "function") window.loadShadowStatus();
    if (typeof window.detectLocalModels === "function") window.detectLocalModels();
    const panel = document.getElementById("settingsPanel");
    if (panel) panel.classList.add("active");
    document.body.classList.add("settings-panel-open");
    markSidePanelOpen("settingsPanel");
    setActivityActive("navSettingsBtn");
  }
  function closeSettings() {
    const panel = document.getElementById("settingsPanel");
    if (panel) panel.classList.remove("active");
    document.body.classList.remove("settings-panel-open");
    markSidePanelClosed("settingsPanel");
    const navBtn = document.getElementById("navSettingsBtn");
    if (navBtn) navBtn.classList.remove("active");
    if (isUnifiedWorkspace()) setActivityActive("navWorkspaceBtn");
  }
  function toggleSettings() {
    const panel = document.getElementById("settingsPanel");
    if (panel && panel.classList.contains("active")) {
      closeSettings();
    } else {
      openSettings();
    }
  }
  function syncCloudProviderUi(provider) {
    const normalized = "deepseek";
    const desc = document.getElementById("settingsApiKeyDesc");
    const hint = document.getElementById("settingCloudProviderHint");
    const input = document.getElementById("settingsApiKeyInput");
    const providerEl = document.getElementById("settingCloudProvider");
    if (providerEl) providerEl.value = normalized;
    if (desc) desc.innerHTML = "更新 DeepSeek API 密钥。选择 DeepSeek 后，云端任务流默认使用 DeepSeek V4 Pro。";
    if (hint) hint.textContent = "云端模式下使用 DeepSeek V4 Pro，支持文字对话、代码和文件任务规划。";
    if (input) input.placeholder = "粘贴 DeepSeek API Key…";
  }
  async function onCloudProviderChange(provider) {
    const normalized = "deepseek";
    syncCloudProviderUi();
    await updateSetting("ai", "cloud_provider", normalized);
    {
      await updateSetting("ai", "deepseek_model", "deepseek-v4-pro");
    }
    csrfFetch("/api/local-model/switch", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode: "cloud" }) }).catch(() => {
    });
    if (window.WA && typeof window.WA.refreshModelCatalog === "function") {
      window.WA.refreshModelCatalog(true);
    }
  }
  async function saveSettingsApiKey() {
    const input = document.getElementById("settingsApiKeyInput");
    const status = document.getElementById("settingsApiKeyStatus");
    document.getElementById("settingCloudProvider");
    const provider = "deepseek";
    const apiKey = input?.value.trim();
    if (!apiKey || apiKey.length < 10) {
      if (status) {
        status.textContent = "❌ 请输入有效的 API Key";
        status.style.color = "var(--accent-error, #ef4444)";
      }
      return;
    }
    if (status) {
      status.textContent = "⏳ 正在保存…";
      status.style.color = "var(--text-secondary)";
    }
    try {
      const res = await csrfFetch("/api/setup/apikey", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ api_key: apiKey, provider }) });
      const data = await res.json();
      if (data.success) {
        if (status) {
          status.textContent = "✅ 已保存，正在生效…";
          status.style.color = "var(--accent-primary, #10b981)";
        }
        if (input) input.value = "";
        const banner = document.getElementById("apiKeyBanner");
        if (banner) banner.style.display = "none";
        setTimeout(() => {
          if (status) status.textContent = "";
        }, 3e3);
      } else {
        if (status) {
          status.textContent = "❌ " + (data.error || "保存失败");
          status.style.color = "var(--accent-error, #ef4444)";
        }
      }
    } catch (e) {
      if (status) {
        status.textContent = "❌ 网络错误: " + e.message;
        status.style.color = "var(--accent-error, #ef4444)";
      }
    }
  }
  function rememberSetting(category, key, value) {
    currentSettings = {
      ...currentSettings || {},
      [category]: {
        ...currentSettings?.[category] || {},
        [key]: value
      }
    };
    window.currentSettings = currentSettings;
  }
  async function updateSetting(category, key, value) {
    try {
      const response = await csrfFetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category, key, value })
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.success === false) {
        throw new Error(data.error || "设置保存失败");
      }
      rememberSetting(category, key, value);
    } catch (e) {
      if (typeof window.showNotification === "function") {
        window.showNotification(e?.message || "设置保存失败", "error", 2200);
      }
      console.warn("Failed to update setting", category, key, e);
    }
  }
  function applyLocalOnlyMode(enabled) {
    window.selectedModel = enabled ? "local" : "auto";
    const modelSelector = document.getElementById("modelSelect");
    if (modelSelector) modelSelector.value = enabled ? "local" : "auto";
  }
  async function onLocalOnlyChange(enabled) {
    const localOnlyEl = document.getElementById("settingLocalOnly");
    const selectEl = document.getElementById("settingLocalModel");
    if (enabled) {
      try {
        const resp = await fetch("/api/local-model/list");
        const data = await resp.json().catch(() => ({}));
        const models = Array.isArray(data.models) ? data.models : [];
        const ollamaOk = data.success !== false && models.length > 0;
        if (!ollamaOk) {
          if (localOnlyEl) localOnlyEl.checked = false;
          applyLocalOnlyMode(false);
          const errMsg = String(data.error || "").trim();
          const msg = errMsg.includes("正在启动") ? "⚠️ Ollama 正在启动，请稍候再试。" : errMsg.includes("未安装") ? "⚠️ Ollama 未安装。请访问 ollama.com 下载安装后再开启本地模式。" : "⚠️ Ollama 未运行。请先启动 Ollama，再开启本地模式。";
          if (typeof window.showNotification === "function") {
            window.showNotification(msg, "warning", 6e3);
          }
          return;
        }
        if (!selectEl || !selectEl.value) {
          if (localOnlyEl) localOnlyEl.checked = false;
          applyLocalOnlyMode(false);
          if (typeof window.showNotification === "function") {
            window.showNotification("⚠️ 请先在下方选择一个本地模型", "warning", 4e3);
          }
          const pickerRow = document.getElementById("localModelPickerRow");
          if (pickerRow) pickerRow.style.display = "";
          detectLocalModels();
          return;
        }
      } catch (_) {
        if (localOnlyEl) localOnlyEl.checked = false;
        applyLocalOnlyMode(false);
        if (typeof window.showNotification === "function") {
          window.showNotification("⚠️ 无法检测 Ollama 状态，请确认 Ollama 已启动", "warning", 5e3);
        }
        return;
      }
    }
    applyLocalOnlyMode(enabled);
    await updateSetting("ai", "use_local_only", enabled);
    const modelTag = selectEl?.value || currentSettings?.local_model || currentSettings?.ai?.local_model || "";
    csrfFetch("/api/local-model/switch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(enabled ? { mode: "local", model_tag: modelTag } : { mode: "cloud" })
    }).catch(() => {
    });
  }
  function filterLocalModels(query) {
    const q = String(query || "").trim().toLowerCase();
    renderLocalModelOptions(q);
  }
  async function detectLocalModels() {
    const hintEl = document.getElementById("localModelHint");
    const badgeEl = document.getElementById("ollamaStatusBadge");
    if (hintEl) hintEl.textContent = "检测中...";
    if (badgeEl) {
      badgeEl.textContent = "检测中...";
      badgeEl.style.color = "var(--text-secondary)";
    }
    try {
      const resp = await fetch("/api/local-model/list");
      const data = await resp.json();
      const container = document.getElementById("localModelsList");
      const models = Array.isArray(data.models) ? data.models.map((m) => String(m.name || m || "").trim()).filter(Boolean) : [];
      allLocalModels = models;
      renderLocalModelOptions(document.getElementById("localModelSearch")?.value || "");
      if (container) {
        container.innerHTML = models.length ? models.map((m) => `<div style="font-size:12px;padding:4px 0;">${escapeHtml(m)}</div>`).join("") : '<div style="color:var(--text-muted);font-size:12px;">未检测到本地模型</div>';
      }
      if (badgeEl) {
        badgeEl.textContent = models.length ? `${models.length} 个模型` : "未检测到";
        badgeEl.style.color = models.length ? "#5cb85c" : "#e87979";
      }
      if (hintEl) {
        const error = String(data.error || "").trim();
        hintEl.textContent = models.length ? `共检测到 ${models.length} 个本地模型` : error || "未检测到已安装的 Ollama 模型";
      }
    } catch (e) {
      allLocalModels = [];
      renderLocalModelOptions("");
      if (badgeEl) {
        badgeEl.textContent = "Ollama 未运行";
        badgeEl.style.color = "#e87979";
      }
      if (hintEl) hintEl.textContent = `检测失败: ${e?.message || e}`;
    }
  }
  function renderLocalModelOptions(query) {
    const selectEl = document.getElementById("settingLocalModel");
    const hintEl = document.getElementById("localModelHint");
    if (!selectEl) return;
    const q = String(query || "").trim().toLowerCase();
    const filtered = q ? allLocalModels.filter((model) => model.toLowerCase().includes(q)) : allLocalModels;
    const saved = currentSettings?.local_model || currentSettings?.ai?.local_model || "";
    if (!filtered.length) {
      selectEl.innerHTML = `<option value="">${allLocalModels.length ? "— 无匹配模型 —" : "— 检测后选择 —"}</option>`;
      if (hintEl && allLocalModels.length) hintEl.textContent = `无匹配结果（共 ${allLocalModels.length} 个模型）`;
      return;
    }
    selectEl.innerHTML = filtered.map((model) => {
      const selected = model === saved ? " selected" : "";
      return `<option value="${escapeHtml(model)}"${selected}>${escapeHtml(model)}</option>`;
    }).join("");
    if (!selectEl.value && filtered[0]) selectEl.value = filtered[0];
    if (hintEl) hintEl.textContent = q ? `过滤结果：${filtered.length} / ${allLocalModels.length} 个模型` : `共 ${filtered.length} 个本地模型`;
  }
  async function onLocalModelChange(modelTag) {
    const nextModel = String(modelTag || "").trim();
    if (!nextModel) return;
    await updateSetting("ai", "local_model", nextModel);
    try {
      const resp = await csrfFetch("/api/local-model/switch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "local", model_tag: nextModel })
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok || data.success === false) throw new Error(data.error || "本地模型切换失败");
      if (currentSettings) {
        currentSettings.local_model = nextModel;
        currentSettings.ai = { ...currentSettings.ai || {}, local_model: nextModel };
        window.currentSettings = currentSettings;
      }
      if (typeof window.showNotification === "function") window.showNotification(`已切换本地模型：${nextModel}`, "success", 1800);
    } catch (error) {
      if (typeof window.showNotification === "function") window.showNotification(error?.message || "本地模型切换失败", "error", 3e3);
    }
  }
  let setupCloudProvider = "deepseek";
  async function checkSetupStatus() {
    try {
      const response = await fetch("/api/setup/status");
      const data = await response.json();
      selectSetupProvider("deepseek");
      if (!data.initialized || !data.has_api_key) {
        showSetupWizard();
      } else {
        window.setupComplete = true;
      }
    } catch (error) {
    }
  }
  function showSetupWizard() {
    const wizard = document.getElementById("setupWizard");
    const step1 = document.getElementById("setupStep1");
    if (wizard) wizard.classList.add("active");
    if (step1) step1.classList.add("active");
  }
  function hideSetupWizard() {
    const wizard = document.getElementById("setupWizard");
    if (wizard) wizard.classList.remove("active");
  }
  function selectSetupProvider(provider) {
    const normalized = "deepseek";
    setupCloudProvider = normalized;
    const deepseekBtn = document.getElementById("setupProviderDeepSeek");
    const desc = document.getElementById("setupApiProviderDesc");
    const input = document.getElementById("setupApiKey");
    const status = document.getElementById("step1Status");
    if (deepseekBtn) deepseekBtn.classList.toggle("active", normalized === "deepseek");
    if (desc) desc.innerHTML = '从 <a href="https://platform.deepseek.com/api_keys" target="_blank">DeepSeek 开放平台</a> 获取 API Key';
    if (input) input.placeholder = "粘贴 DeepSeek API Key...";
    if (status) {
      status.textContent = "";
      status.className = "step-status";
    }
  }
  async function saveApiKey() {
    const apiKey = document.getElementById("setupApiKey").value.trim();
    const status = document.getElementById("step1Status");
    if (!apiKey || apiKey.length < 10) {
      if (status) {
        status.textContent = "❌ 请输入有效的 API Key";
        status.className = "step-status error";
      }
      return;
    }
    if (status) {
      status.textContent = "⏳ 正在验证...";
      status.className = "step-status loading";
    }
    try {
      const response = await csrfFetch("/api/setup/apikey", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ api_key: apiKey, provider: setupCloudProvider }) });
      const data = await response.json();
      if (data.success) {
        if (status) {
          status.textContent = "✅ DeepSeek API Key 已保存";
          status.className = "step-status success";
        }
        const step1 = document.getElementById("setupStep1");
        const step2 = document.getElementById("setupStep2");
        if (step1) {
          step1.classList.remove("active");
          step1.classList.add("completed");
        }
        if (step2) step2.classList.add("active");
      } else {
        if (status) {
          status.textContent = "❌ " + (data.error || "保存失败");
          status.className = "step-status error";
        }
      }
    } catch (error) {
      if (status) {
        status.textContent = "❌ 网络错误";
        status.className = "step-status error";
      }
    }
  }
  async function useActivationCode() {
    const code = (document.getElementById("setupActivateCode")?.value || "").trim().toUpperCase();
    const status = document.getElementById("step1ActivateStatus");
    if (!code) {
      if (status) {
        status.textContent = "❌ 请输入激活码";
        status.className = "step-status error";
      }
      return;
    }
    if (status) {
      status.textContent = "⏳ 正在验证激活码...";
      status.className = "step-status loading";
    }
    try {
      const res = await csrfFetch("/api/setup/activate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code }) });
      const data = await res.json();
      if (data.success) {
        if (status) {
          status.textContent = "✅ 激活成功！";
          status.className = "step-status success";
        }
        setTimeout(() => {
          const step1 = document.getElementById("setupStep1");
          const step2 = document.getElementById("setupStep2");
          if (step1) {
            step1.classList.remove("active");
            step1.classList.add("completed");
          }
          if (step2) step2.classList.add("active");
        }, 800);
      } else {
        if (status) {
          status.textContent = "❌ " + (data.error || "激活失败");
          status.className = "step-status error";
        }
      }
    } catch (err) {
      if (status) {
        status.textContent = "❌ 网络错误，请重试";
        status.className = "step-status error";
      }
    }
  }
  async function saveWorkspace() {
    const workspacePath = document.getElementById("setupWorkspacePath").value.trim();
    const status = document.getElementById("step2Status");
    if (status) {
      status.textContent = "⏳ 正在创建工作区...";
      status.className = "step-status loading";
    }
    try {
      const response = await csrfFetch("/api/setup/workspace", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: workspacePath }) });
      const data = await response.json();
      if (data.success) {
        if (status) {
          status.textContent = "✅ 工作区已创建: " + data.path;
          status.className = "step-status success";
        }
        const step2 = document.getElementById("setupStep2");
        const step3 = document.getElementById("setupStep3");
        if (step2) {
          step2.classList.remove("active");
          step2.classList.add("completed");
        }
        if (step3) step3.classList.add("active");
      } else {
        if (status) {
          status.textContent = "❌ " + (data.error || "创建失败");
          status.className = "step-status error";
        }
      }
    } catch (error) {
      if (status) {
        status.textContent = "❌ 网络错误";
        status.className = "step-status error";
      }
    }
  }
  async function testConnection() {
    const status = document.getElementById("step3Status");
    if (status) {
      status.textContent = "⏳ 正在测试连接...";
      status.className = "step-status loading";
    }
    try {
      const response = await fetch("/api/setup/test");
      const data = await response.json();
      if (data.success) {
        if (status) {
          status.textContent = `✅ 连接成功! (${data.latency}s) - ${data.message}`;
          status.className = "step-status success";
        }
        const step3 = document.getElementById("setupStep3");
        const startBtn = document.getElementById("startKotoBtn");
        if (step3) {
          step3.classList.remove("active");
          step3.classList.add("completed");
        }
        if (startBtn) startBtn.disabled = false;
      } else {
        if (status) {
          status.textContent = "❌ " + (data.error || "连接失败");
          status.className = "step-status error";
        }
      }
    } catch (error) {
      if (status) {
        status.textContent = "❌ 网络错误: " + error.message;
        status.className = "step-status error";
      }
    }
  }
  async function activateWithCode() {
    const codeInput = document.getElementById("activationCode");
    const code = codeInput.value.trim();
    const status = document.getElementById("step1Status");
    if (!code) {
      if (status) {
        status.textContent = "❌ 请输入激活码";
        status.className = "step-status error";
      }
      return;
    }
    if (status) {
      status.textContent = "⏳ 正在验证激活码...";
      status.className = "step-status loading";
    }
    try {
      const response = await csrfFetch("/api/setup/activate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code }) });
      const data = await response.json();
      if (data.success) {
        if (status) {
          status.textContent = "✅ 激活成功！正在启动 Koto...";
          status.className = "step-status success";
        }
        setTimeout(() => {
          window.setupComplete = true;
          hideSetupWizard();
          if (typeof window.loadSessions === "function") window.loadSessions();
          if (typeof window.checkStatus === "function") window.checkStatus();
        }, 800);
      } else {
        if (status) {
          status.textContent = "❌ " + (data.error || "激活失败");
          status.className = "step-status error";
        }
      }
    } catch (error) {
      if (status) {
        status.textContent = "❌ 网络错误";
        status.className = "step-status error";
      }
    }
  }
  function skipSetup() {
    if (confirm("跳过设置可能导致部分功能无法使用，确定要跳过吗？")) {
      hideSetupWizard();
      const banner = document.getElementById("apiKeyBanner");
      if (banner) banner.style.display = "flex";
    }
  }
  function dismissApiKeyBanner() {
    const banner = document.getElementById("apiKeyBanner");
    if (banner) banner.style.display = "none";
  }
  function finishSetup() {
    window.setupComplete = true;
    hideSetupWizard();
    if (typeof window.loadSessions === "function") window.loadSessions();
    if (typeof window.checkStatus === "function") window.checkStatus();
  }
  function browseSetupFolder() {
    currentBrowseTarget = "setup_workspace";
    const pathInput = document.getElementById("setupWorkspacePath");
    const startPath = pathInput?.value.trim() || window.browseHomeDir || "";
    currentBrowsePath = startPath;
    const manualPathInput = document.getElementById("manualPathInput");
    if (manualPathInput) manualPathInput.value = startPath;
    if (startPath) {
      if (typeof window.loadFolderList === "function") window.loadFolderList(startPath);
    } else {
      if (typeof window.loadFolderDrives === "function") window.loadFolderDrives();
    }
    const folderModal = document.getElementById("folderModal");
    if (folderModal) folderModal.classList.add("active");
  }
  function browseFolder(target) {
    currentBrowseTarget = target;
    window.currentBrowseTarget = target;
    const field = document.getElementById(`setting${target.split("_").map((part) => part ? part[0].toUpperCase() + part.slice(1) : "").join("")}`);
    const explicitMap = {
      workspace_dir: "settingWorkspaceDir",
      documents_dir: "settingDocumentsDir",
      images_dir: "settingImagesDir",
      chats_dir: "settingChatsDir"
    };
    const input = document.getElementById(explicitMap[target] || "");
    const startPath = (input || field)?.value.trim() || window.browseHomeDir || "";
    currentBrowsePath = startPath;
    window.currentBrowsePath = startPath;
    const manualPathInput = document.getElementById("manualPathInput");
    if (manualPathInput) manualPathInput.value = startPath;
    if (startPath && typeof window.loadFolderList === "function") {
      window.loadFolderList(startPath);
    } else if (typeof window.loadFolderDrives === "function") {
      window.loadFolderDrives();
    }
    document.getElementById("folderModal")?.classList.add("active");
  }
  function closeFolderModal() {
    document.getElementById("folderModal")?.classList.remove("active");
    currentBrowseTarget = null;
    window.currentBrowseTarget = null;
  }
  async function confirmFolderSelect() {
    const path = (document.getElementById("manualPathInput")?.value || "").trim();
    const target = currentBrowseTarget || window.currentBrowseTarget;
    if (!path || !target) return;
    if (target === "setup_workspace") {
      const input2 = document.getElementById("setupWorkspacePath");
      if (input2) input2.value = path;
      closeFolderModal();
      return;
    }
    await updateSetting("storage", target, path);
    const inputMap = {
      workspace_dir: "settingWorkspaceDir",
      documents_dir: "settingDocumentsDir",
      images_dir: "settingImagesDir",
      chats_dir: "settingChatsDir"
    };
    const input = document.getElementById(inputMap[target] || "");
    if (input) input.value = path;
    closeFolderModal();
  }
  function getLatencyClass(latencyMs) {
    if (latencyMs == null) return "";
    if (latencyMs < 500) return "good";
    if (latencyMs < 1500) return "ok";
    return "slow";
  }
  function formatLatency(providerData) {
    if (!providerData) return "--";
    if (providerData.error === "checking") return "检查中";
    if (providerData.reachable && providerData.latency_ms != null) return `${providerData.latency_ms}ms`;
    if (providerData.error === "timeout") return "超时";
    return "不可达";
  }
  function updateLatencyProvider(provider, providerData) {
    const id = "Deepseek";
    const row = document.getElementById(`latency${id}`);
    const value = document.getElementById(`latency${id}Val`);
    const bar = document.getElementById(`latency${id}Bar`);
    const latencyMs = providerData && providerData.reachable ? providerData.latency_ms : null;
    const latencyClass = getLatencyClass(latencyMs);
    if (value) value.textContent = formatLatency(providerData);
    if (bar) {
      bar.className = `latency-bar-fill ${latencyClass}`.trim();
      bar.style.width = latencyMs == null ? "0%" : `${Math.max(8, Math.min(100, latencyMs / 20))}%`;
    }
    if (row) {
      row.classList.toggle("offline", !(providerData && providerData.reachable));
    }
  }
  function updateLatencyDetail(results) {
    updateLatencyProvider("deepseek", results && results.deepseek);
  }
  function toggleLatencyDetail(event) {
    if (event) event.stopPropagation();
    const detail = document.getElementById("latencyDetail");
    if (!detail) return;
    const willOpen = !detail.classList.contains("open");
    if (willOpen) {
      updateLatencyDetail(window._lastCloudLatency || { deepseek: { reachable: false, error: "checking" } });
      checkStatus();
    }
    const leftSlot = document.getElementById("wa-left-latency-slot");
    if (leftSlot && detail.parentElement !== leftSlot) {
      leftSlot.appendChild(detail);
    }
    if (detail) detail.style.display = willOpen ? "block" : "none";
    detail.classList.toggle("open", willOpen);
    const arrow = document.querySelector(".status-expand-arrow");
    if (arrow) arrow.classList.toggle("open", willOpen);
    const indicator = document.getElementById("statusIndicator");
    if (indicator) indicator.setAttribute("aria-expanded", willOpen ? "true" : "false");
  }
  async function checkStatus() {
    const dot = document.querySelector(".status-dot");
    const text = document.querySelector(".status-text");
    try {
      const response = await fetch("/api/ping");
      const data = await response.json();
      if (data.status === "ok") {
        if (dot) {
          dot.classList.add("online");
          dot.classList.remove("offline");
        }
        if (text) text.textContent = data.ollama ? "🦙 ..." : "...";
      } else {
        if (dot) {
          dot.classList.add("offline");
          dot.classList.remove("online");
        }
        if (text) text.textContent = "Offline";
      }
    } catch (error) {
      if (dot) {
        dot.classList.add("offline");
        dot.classList.remove("online");
      }
      if (text) text.textContent = "Error";
    }
    const noticeBar = document.getElementById("wechat-notice-bar");
    try {
      const cResp = await fetch("/api/ping/cloud/all", { signal: AbortSignal.timeout(12e3) });
      if (cResp.ok) {
        const cloud = await cResp.json();
        window._lastCloudLatency = cloud;
        updateLatencyDetail(cloud);
        const providerOrder = ["deepseek"];
        const reachable = providerOrder.map((p) => cloud && cloud[p]).filter((item) => item && item.reachable && item.latency_ms != null);
        const ollamaHint = text?.textContent?.startsWith("🦙") ? " | 🦙" : "";
        if (reachable.length) {
          const fastest = reachable.reduce((best, item) => item.latency_ms < best.latency_ms ? item : best);
          if (text) text.textContent = `☁ ${fastest.latency_ms}ms${ollamaHint}`;
          if (noticeBar) noticeBar.style.display = "none";
        } else {
          if (text) text.textContent = `☁ 超时${ollamaHint}`;
          if (noticeBar) noticeBar.style.display = "block";
        }
      } else {
        if (noticeBar) noticeBar.style.display = "block";
      }
    } catch (_) {
      updateLatencyDetail(window._lastCloudLatency || {});
      if (noticeBar) noticeBar.style.display = "block";
    }
    try {
      const mResp = await fetch("/api/ops/metrics", { signal: AbortSignal.timeout(3e3) });
      if (mResp.ok) {
        const m = await mResp.json();
        const trigEnabled = m.triggers && m.triggers.enabled || 0;
        const pill = document.getElementById("jobsRunningPill");
        if (pill) pill.style.display = "none";
        const badge = document.getElementById("opsStatusBadge");
        if (badge && trigEnabled > 0) {
          badge.textContent = `${trigEnabled} 触发器活跃`;
          badge.style.display = "block";
        } else if (badge) badge.style.display = "none";
      }
    } catch (_) {
    }
  }
  const batchJobsState = { timer: null };
  function openBatchJobsPanel() {
    const modal = document.getElementById("batchPanelModal");
    if (modal) modal.style.display = "flex";
    refreshBatchJobs();
    if (batchJobsState.timer) clearInterval(batchJobsState.timer);
    batchJobsState.timer = setInterval(refreshBatchJobs, 2e3);
  }
  function closeBatchJobsPanel() {
    const modal = document.getElementById("batchPanelModal");
    if (modal) modal.style.display = "none";
    if (batchJobsState.timer) {
      clearInterval(batchJobsState.timer);
      batchJobsState.timer = null;
    }
  }
  async function refreshBatchJobs() {
    try {
      const response = await fetch("/api/batch/jobs");
      const data = await response.json();
      if (!data.success) return;
      const listEl = document.getElementById("batchJobsList");
      const jobs = data.jobs || [];
      if (!listEl) return;
      if (jobs.length === 0) {
        listEl.innerHTML = '<div class="batch-empty">暂无任务</div>';
        return;
      }
      listEl.innerHTML = jobs.map((job) => {
        const total = job.total_items || 0;
        const processed = job.processed_items || 0;
        const percent = total > 0 ? Math.round(processed / total * 100) : 0;
        const outputDir = job.output_dir || "";
        const encodedOutput = encodeURIComponent(outputDir);
        const status = job.status || "unknown";
        return `<div class="batch-job-card"><div class="batch-job-title">${escapeHtml(job.name || job.job_id)}</div><div class="batch-job-meta"><span>状态: ${escapeHtml(status)}</span><span>${processed}/${total}</span></div><div class="batch-job-progress"><div class="batch-job-progress-fill" style="width:${percent}%"></div></div><div class="batch-job-meta" style="margin-top:6px;"><span>${escapeHtml(outputDir)}</span><button class="ghost-btn" style="padding:2px 8px;font-size:12px;" onclick="openPath('${encodedOutput}')">复制路径</button></div></div>`;
      }).join("");
    } catch (error) {
    }
  }
  async function resetSettings() {
    if (!confirm("确定要重置所有设置为默认值吗？")) return;
    try {
      const response = await csrfFetch("/api/settings/reset", { method: "POST" });
      const data = await response.json();
      if (!response.ok || data.success === false) throw new Error(data.error || "重置失败");
      await loadSettings();
      if (typeof window.showNotification === "function") {
        window.showNotification("设置已恢复默认", "success", 1800);
      }
    } catch (error) {
      if (typeof window.showNotification === "function") {
        window.showNotification("重置失败: " + (error.message || error), "error");
      }
    }
  }
  async function bootstrapTriggers(force = false) {
    const label = force ? "重建" : "初始化";
    if (force && !confirm("确定重建所有推荐触发器吗？已有推荐触发器将被替换。")) return;
    try {
      const resp = await csrfFetch("/api/jobs/triggers/bootstrap", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force })
      });
      const data = await resp.json();
      if (!resp.ok || data.ok === false) throw new Error(data.error || "操作失败");
      if (typeof window.loadTriggers === "function") await window.loadTriggers();
      if (typeof window.showNotification === "function") {
        const created = (data.data && data.data.created || []).length;
        const skipped = (data.data && data.data.skipped || []).length;
        window.showNotification(`${label}完成：创建 ${created}，跳过 ${skipped}`, "success", 2200);
      }
    } catch (error) {
      if (typeof window.showNotification === "function") {
        window.showNotification(`${label}失败: ` + (error.message || error), "error");
      }
    }
  }
  async function shadowOpenObservations() {
    try {
      const resp = await fetch("/api/shadow/observations");
      const data = await resp.json();
      if (!resp.ok || data.ok === false) throw new Error(data.error || "获取失败");
      const obs = data.data || {};
      const topics = Object.entries(obs.topics || {}).sort((a, b) => Number(b[1]) - Number(a[1])).slice(0, 10).map(([key, value]) => `${key}x${value}`).join(", ");
      const hours = Object.entries(obs.active_hours || {}).sort((a, b) => Number(a[0]) - Number(b[0])).map(([hour, count]) => `${hour}时:${count}`).join("  ");
      const detail = [
        `总观察次数: ${obs.total_observations || 0}`,
        `连续天数: ${obs.streak?.days || 0}`,
        `活跃时段: ${hours || "暂无记录"}`,
        `话题词频: ${topics || "暂无"}`,
        `开放任务: ${(obs.open_tasks || []).filter((task) => !task.done).length} 项待处理`,
        `最后活跃: ${obs.last_seen || "无"}`
      ].join("\n");
      if (typeof window.showNotification === "function") {
        window.showNotification(detail, "info", 8e3);
      } else {
        alert(detail);
      }
    } catch (error) {
      if (typeof window.showNotification === "function") {
        window.showNotification("获取失败: " + (error.message || error), "error");
      }
    }
  }
  function escapeHtml(str) {
    return String(str || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  window.loadSettings = loadSettings;
  window.applySettingsToUI = applySettingsToUI;
  window.openSettings = openSettings;
  window.closeSettings = closeSettings;
  window.toggleSettings = toggleSettings;
  window.syncCloudProviderUi = syncCloudProviderUi;
  window.onCloudProviderChange = onCloudProviderChange;
  window.saveSettingsApiKey = saveSettingsApiKey;
  window.updateSetting = updateSetting;
  window.applyLocalOnlyMode = applyLocalOnlyMode;
  window.onLocalOnlyChange = onLocalOnlyChange;
  window.filterLocalModels = filterLocalModels;
  window.detectLocalModels = detectLocalModels;
  window.onLocalModelChange = onLocalModelChange;
  window.checkSetupStatus = checkSetupStatus;
  window.showSetupWizard = showSetupWizard;
  window.hideSetupWizard = hideSetupWizard;
  window.selectSetupProvider = selectSetupProvider;
  window.saveApiKey = saveApiKey;
  window.useActivationCode = useActivationCode;
  window.saveWorkspace = saveWorkspace;
  window.testConnection = testConnection;
  window.activateWithCode = activateWithCode;
  window.skipSetup = skipSetup;
  window.dismissApiKeyBanner = dismissApiKeyBanner;
  window.finishSetup = finishSetup;
  window.browseSetupFolder = browseSetupFolder;
  window.browseFolder = browseFolder;
  window.closeFolderModal = closeFolderModal;
  window.confirmFolderSelect = confirmFolderSelect;
  window.checkStatus = checkStatus;
  window.updateLatencyDetail = updateLatencyDetail;
  window.toggleLatencyDetail = toggleLatencyDetail;
  window.openBatchJobsPanel = openBatchJobsPanel;
  window.closeBatchJobsPanel = closeBatchJobsPanel;
  window.refreshBatchJobs = refreshBatchJobs;
  window.resetSettings = resetSettings;
  window.bootstrapTriggers = bootstrapTriggers;
  window.shadowOpenObservations = shadowOpenObservations;
  window.currentSettings = currentSettings;
  window.currentBrowseTarget = currentBrowseTarget;
  window.currentBrowsePath = currentBrowsePath;
  let currentSession = null;
  let currentProject = localStorage.getItem("koto.currentProject") || "default";
  const _DEFAULT_PROJECT_OPTIONS = [
    { key: "default", label: "默认项目" },
    { key: "work", label: "工作" },
    { key: "study", label: "学习" },
    { key: "life", label: "生活" }
  ];
  const sessionStates = /* @__PURE__ */ new Map();
  window.currentSession = currentSession;
  function getProjectOptions() {
    try {
      const stored = localStorage.getItem("koto.projectOptions");
      if (stored) {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed) && parsed.length > 0) {
          if (!parsed.some((p) => p.key === "default")) {
            parsed.unshift({ key: "default", label: "默认项目" });
          }
          return parsed;
        }
      }
    } catch (e) {
    }
    return _DEFAULT_PROJECT_OPTIONS.map((p) => ({ ...p }));
  }
  function saveProjectOptions(opts) {
    localStorage.setItem("koto.projectOptions", JSON.stringify(opts));
  }
  function getProjectSessionPrefix(projectKey = currentProject) {
    return projectKey === "default" ? "" : `proj_${projectKey}__`;
  }
  function listProjectSessions(allSessions) {
    const list = Array.isArray(allSessions) ? allSessions : [];
    const prefix = getProjectSessionPrefix();
    if (!prefix) {
      return list.filter((name) => !/^proj_[a-z0-9_-]+__/.test(String(name || "")));
    }
    return list.filter((name) => String(name || "").startsWith(prefix));
  }
  function toProjectSessionName(rawName, projectKey = currentProject) {
    const clean = String(rawName || "").trim();
    if (!clean) return clean;
    const prefix = getProjectSessionPrefix(projectKey);
    return prefix ? `${prefix}${clean}` : clean;
  }
  function toSessionDisplayName(sessionName) {
    const text = String(sessionName || "");
    const prefix = getProjectSessionPrefix();
    if (prefix && text.startsWith(prefix)) return text.slice(prefix.length);
    return text;
  }
  function getSessionState(sessionName) {
    if (!sessionStates.has(sessionName)) {
      sessionStates.set(sessionName, { isGenerating: false, abortController: null });
    }
    return sessionStates.get(sessionName);
  }
  function setSessionGenerating(sessionName, isGenerating) {
    const state = getSessionState(sessionName);
    state.isGenerating = isGenerating;
  }
  function isSessionGenerating(sessionName) {
    const state = getSessionState(sessionName);
    return state.isGenerating;
  }
  function getSessionAbortController(sessionName) {
    const state = getSessionState(sessionName);
    return state.abortController;
  }
  function isSessionLoadInterruption(error) {
    const text = String(error instanceof Error ? error.message : error || "").trim();
    return /failed to fetch|networkerror|aborted|load failed/i.test(text);
  }
  async function loadSessions() {
    try {
      const response = await fetch("/api/sessions?preview=1");
      const data = await response.json();
      const raw = data.sessions || [];
      window._allSessions = raw.map((s) => typeof s === "string" ? s : s.id);
      window._sessionPreviews = {};
      raw.forEach((s) => {
        if (typeof s === "object" && s.id) {
          window._sessionPreviews[s.id] = { preview: s.preview || "", mtime: s.mtime || 0 };
        }
      });
      window._projectSessions = listProjectSessions(window._allSessions);
      const q = document.getElementById("sessionSearchInput");
      const query = q ? q.value.trim() : "";
      renderSessions(query ? window._projectSessions.filter((s) => toSessionDisplayName(s).toLowerCase().includes(query.toLowerCase())) : window._projectSessions);
    } catch (error) {
      if (isSessionLoadInterruption(error)) {
        console.debug("Session list refresh interrupted:", error);
        return;
      }
      console.error("Failed to load sessions:", error);
    }
  }
  function filterSessions(query) {
    const all = window._projectSessions || [];
    const filtered = query.trim() ? all.filter((s) => toSessionDisplayName(s).toLowerCase().includes(query.trim().toLowerCase())) : all;
    renderSessions(filtered);
  }
  function renderSessions(sessions) {
    const container = document.getElementById("sessionsList");
    if (!container) return;
    if (sessions.length === 0) {
      container.innerHTML = `
      <div style="text-align: center; padding: 20px; color: var(--text-muted);">
        <p>暂无对话</p>
        <p style="font-size: 12px; margin-top: 8px;">点击“+ 新对话”开始</p>
      </div>`;
      return;
    }
    container.innerHTML = sessions.map((session) => {
      const meta = (window._sessionPreviews || {})[session] || {};
      const preview = meta.preview || "";
      return `
      <div class="session-item ${currentSession === session ? "active" : ""}"
           data-session="${window.escapeHtml(session)}">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
        </svg>
        <div class="session-item-body">
          <div class="session-item-top">
            <span class="session-name">${window.escapeHtml(toSessionDisplayName(session))}</span>
          </div>
          ${preview ? `<span class="session-preview">${window.escapeHtml(preview)}</span>` : ""}
        </div>
        <button class="session-rename-btn" data-session="${window.escapeHtml(session)}" onclick="renameSession(this.dataset.session, event)" title="重命名对话">✎</button>
        <button class="session-delete-btn" data-session="${window.escapeHtml(session)}" onclick="deleteSession(this.dataset.session, event)" title="删除对话">✕</button>
      </div>`;
    }).join("");
    container.querySelectorAll(".session-item").forEach((el) => {
      const htmlEl = el;
      el.addEventListener("click", function(e) {
        if (e.target?.closest(".session-rename-btn") || e.target?.closest(".session-delete-btn")) return;
        if (el.querySelector(".session-name-input")) return;
        if (typeof window.selectSession === "function") {
          window.selectSession(htmlEl.dataset.session);
        }
      });
    });
  }
  function _syncSessionSelectionUi(sessionName) {
    const chatTitle = document.getElementById("chatTitle");
    if (chatTitle) chatTitle.textContent = toSessionDisplayName(sessionName);
    document.querySelectorAll(".session-item").forEach((item) => {
      item.classList.remove("active");
      if (item.dataset.session === sessionName) {
        item.classList.add("active");
      }
    });
  }
  async function createNewSession(name = null) {
    if (!name) {
      if (typeof window.showNewSessionModal === "function") {
        window.showNewSessionModal();
      }
      return;
    }
    try {
      const projectName = toProjectSessionName(name);
      const response = await csrfFetch("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: projectName })
      });
      if (response.ok) {
        const data = await response.json();
        if (data.success) {
          currentSession = data.session;
          const chatTitle = document.getElementById("chatTitle");
          if (chatTitle) chatTitle.textContent = toSessionDisplayName(data.session);
          loadSessions();
          const container = document.getElementById("chatMessages");
          if (container) container.innerHTML = "";
        }
      }
    } catch (error) {
      console.error("Failed to create session:", error);
    }
  }
  async function confirmNewSession() {
    const nameInput = document.getElementById("newSessionName");
    const name = nameInput?.value.trim();
    if (!name) return;
    try {
      const response = await csrfFetch("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: toProjectSessionName(name) })
      });
      const data = await response.json();
      if (data.success) {
        if (typeof window.closeModal === "function") window.closeModal();
        await loadSessions();
        if (typeof window.selectSession === "function") window.selectSession(data.session);
      }
    } catch (error) {
      console.error("Failed to create session:", error);
    }
  }
  function showNewSessionModal() {
    if (typeof window.switchToChatView === "function") window.switchToChatView();
    const modal = document.getElementById("newSessionModal");
    if (modal) modal.classList.add("active");
    const input = document.getElementById("newSessionName");
    if (input) {
      input.value = "";
      input.focus();
    }
  }
  function closeModal() {
    const modal = document.getElementById("newSessionModal");
    if (modal) modal.classList.remove("active");
  }
  async function deleteSession(sessionName, event) {
    if (event) event.stopPropagation();
    if (!sessionName) return;
    if (!confirm(`确认删除对话 "${toSessionDisplayName(sessionName)}"？`)) return;
    if (isSessionGenerating(sessionName)) {
      const controller = getSessionAbortController(sessionName);
      if (controller) controller.abort();
      setSessionGenerating(sessionName, false);
    }
    try {
      const response = await csrfFetch(`/api/sessions/${encodeURIComponent(sessionName)}`, { method: "DELETE" });
      const data = await response.json();
      if (data.success) {
        document.querySelectorAll(".session-item").forEach((item) => {
          if (item.dataset.session === sessionName) item.remove();
        });
        if (currentSession === sessionName) {
          currentSession = null;
          const chatTitle = document.getElementById("chatTitle");
          if (chatTitle) chatTitle.textContent = "Koto";
          const container = document.getElementById("chatMessages");
          if (container) container.querySelectorAll(".message, .chat-date-sep").forEach((el) => el.remove());
          const ws = document.getElementById("welcomeScreen");
          if (ws) ws.style.display = "block";
          if (typeof window.renderWelcomeScreen === "function") window.renderWelcomeScreen();
        }
      }
    } catch (error) {
      console.error("Failed to delete session:", error);
    }
  }
  async function deleteCurrentSession() {
    return deleteSession(currentSession || "", void 0);
  }
  async function renameSession(sessionName, event) {
    if (event) event.stopPropagation();
    const item = document.querySelector(`.session-item[data-session="${CSS.escape(sessionName)}"]`);
    if (!item) return;
    const nameSpan = item.querySelector(".session-name");
    if (!nameSpan) return;
    const oldName = nameSpan.textContent || "";
    const input = document.createElement("input");
    input.className = "session-name-input";
    input.value = oldName;
    nameSpan.replaceWith(input);
    input.focus();
    input.select();
    input.addEventListener("click", (e) => e.stopPropagation());
    let committed = false;
    async function commit() {
      if (committed) return;
      committed = true;
      const newName = input.value.trim();
      const restore = () => {
        const span = document.createElement("span");
        span.className = "session-name";
        span.textContent = oldName;
        input.replaceWith(span);
      };
      if (!newName || newName === oldName) {
        restore();
        return;
      }
      const fullNewName = toProjectSessionName(newName);
      try {
        const resp = await csrfFetch(`/api/sessions/${encodeURIComponent(sessionName)}/rename`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ new_name: fullNewName })
        });
        const data = await resp.json();
        if (data.success) {
          const newSession = data.new_session;
          if (currentSession === sessionName) {
            currentSession = newSession;
            const chatTitle = document.getElementById("chatTitle");
            if (chatTitle) chatTitle.textContent = toSessionDisplayName(newSession);
          }
          document.querySelectorAll(".session-item").forEach((el) => {
            if (el.dataset.session === sessionName) {
              el.dataset.session = newSession;
              const nameEl = el.querySelector(".session-name");
              if (nameEl) nameEl.textContent = toSessionDisplayName(newSession);
            }
          });
        } else {
          restore();
        }
      } catch (e) {
        restore();
      }
    }
    input.addEventListener("blur", commit);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        commit();
      }
      if (e.key === "Escape") {
        committed = true;
        input.value = oldName;
        commit();
      }
    });
  }
  function initProjectSelector() {
    const select = document.getElementById("projectSelect");
    if (!select) return;
    const options = getProjectOptions();
    if (!options.some((p) => p.key === currentProject)) {
      currentProject = "default";
      localStorage.setItem("koto.currentProject", currentProject);
    }
    select.innerHTML = options.map(
      (project) => `<option value="${window.escapeHtml(project.key)}">${window.escapeHtml(project.label)}</option>`
    ).join("");
    select.value = currentProject;
    select.onchange = async (e) => {
      currentProject = e.target.value || "default";
      localStorage.setItem("koto.currentProject", currentProject);
      if (typeof window.goToWelcome === "function") window.goToWelcome();
      await loadSessions();
    };
  }
  function _isSidebarOverlayMode() {
    try {
      return window.matchMedia("(max-width: 1200px)").matches;
    } catch (_) {
      return false;
    }
  }
  function toggleSidebar() {
    const sidebar = document.getElementById("sidebar");
    if (!sidebar) return;
    if (_isSidebarOverlayMode()) {
      sidebar.classList.toggle("open");
    } else {
      sidebar.classList.toggle("expanded");
    }
  }
  function toggleSidebarSearch() {
    const searchBar = document.getElementById("sessionSearchBar");
    if (!searchBar) return;
    const isVisible = searchBar.style.display !== "none";
    searchBar.style.display = isVisible ? "none" : "block";
    if (!isVisible) {
      const input = document.getElementById("sessionSearchInput");
      if (input) input.focus();
    }
  }
  const KotoSessionBridge = {
    getSession() {
      return currentSession || "";
    },
    setSession(sessionName) {
      currentSession = sessionName || null;
      if (currentSession) _syncSessionSelectionUi(currentSession);
      if (window.WA && typeof window.WA.useHostSession === "function") {
        window.WA.useHostSession(currentSession || "", { force: true });
      }
    },
    refreshSessions() {
      return typeof loadSessions === "function" ? loadSessions() : Promise.resolve();
    }
  };
  window.KotoSessionBridge = KotoSessionBridge;
  window.loadSessions = loadSessions;
  window.filterSessions = filterSessions;
  window.renderSessions = renderSessions;
  window.createNewSession = createNewSession;
  window.confirmNewSession = confirmNewSession;
  window.showNewSessionModal = showNewSessionModal;
  window.closeModal = closeModal;
  window.deleteSession = deleteSession;
  window.deleteCurrentSession = deleteCurrentSession;
  window.renameSession = renameSession;
  window.initProjectSelector = initProjectSelector;
  window.toggleSidebar = toggleSidebar;
  window.toggleSidebarSearch = toggleSidebarSearch;
  window.toSessionDisplayName = toSessionDisplayName;
  window.toProjectSessionName = toProjectSessionName;
  window.getProjectSessionPrefix = getProjectSessionPrefix;
  window.listProjectSessions = listProjectSessions;
  window.getProjectOptions = getProjectOptions;
  window.saveProjectOptions = saveProjectOptions;
  window.currentProject = currentProject;
  function goToWelcome() {
    if (typeof window.switchToChatView === "function") window.switchToChatView();
    const currentSession2 = window.currentSession;
    if (currentSession2 && typeof window.isSessionGenerating === "function" && window.isSessionGenerating(currentSession2)) {
      const controller = window.getSessionAbortController?.(currentSession2);
      if (controller) {
        console.log(`[CLEANUP] Aborting previous session ${currentSession2}`);
        controller.abort();
      }
      if (typeof window.setSessionGenerating === "function") {
        window.setSessionGenerating(currentSession2, false);
      }
      const sessionDomCache = window.sessionDomCache;
      if (sessionDomCache) sessionDomCache.delete(currentSession2);
    }
    const sendBtn = document.getElementById("sendBtn");
    if (sendBtn) {
      sendBtn.classList.remove("generating");
      sendBtn.disabled = false;
      sendBtn.title = "发送";
    }
    window.currentSession = null;
    window.isScrollLocked = false;
    const chatTitle = document.getElementById("chatTitle");
    if (chatTitle) chatTitle.textContent = "Koto";
    document.querySelectorAll(".session-item").forEach((item) => {
      item.classList.remove("active");
    });
    const container = document.getElementById("chatMessages");
    const ws = document.getElementById("welcomeScreen");
    if (ws) ws.style.display = "block";
    if (container) container.querySelectorAll(".message, .chat-date-sep").forEach((msg) => msg.remove());
    renderWelcomeScreen();
    window.lockedTaskType = null;
    document.querySelectorAll(".capability").forEach((c) => c.classList.remove("selected"));
    if (typeof window.updateTaskIndicator === "function") window.updateTaskIndicator(null);
  }
  function renderWelcomeScreen() {
    const h = (/* @__PURE__ */ new Date()).getHours();
    const greeting = h < 5 ? "夜深了，还在呢🌙" : h < 12 ? "早上好，有什么需要帮忙？☀️" : h < 18 ? "下午好，有什么需要帮忙？" : "晚上好，有什么需要帮忙？🌟";
    const greetEl = document.getElementById("welcomeGreeting");
    if (greetEl) greetEl.textContent = greeting;
  }
  async function selectSession(sessionName) {
    const currentSession2 = window.currentSession;
    if (currentSession2 && currentSession2 !== sessionName && typeof window.isSessionGenerating === "function" && window.isSessionGenerating(currentSession2)) {
      const chatContainer2 = document.getElementById("chatMessages");
      const frag = document.createDocumentFragment();
      if (chatContainer2) {
        chatContainer2.querySelectorAll(".message, .chat-date-sep").forEach((node) => frag.appendChild(node));
      }
      const sessionDomCache = window.sessionDomCache;
      if (sessionDomCache) sessionDomCache.set(currentSession2, frag);
    }
    const workspaceView = document.getElementById("workspaceView");
    const workspaceOpen = !!(workspaceView && workspaceView.style.display !== "none");
    if (!workspaceOpen && typeof window.switchToChatView === "function") window.switchToChatView();
    window.currentSession = sessionName;
    if (typeof window._syncSessionSelectionUi === "function") window._syncSessionSelectionUi(sessionName);
    if (workspaceOpen && window.WA && typeof window.WA.useHostSession === "function") {
      window.WA.useHostSession(sessionName, { force: true });
    }
    const sb = document.getElementById("sendBtn");
    if (sb) {
      if (typeof window.isSessionGenerating === "function" && window.isSessionGenerating(sessionName)) {
        sb.classList.add("generating");
        sb.disabled = false;
        sb.title = "停止生成";
      } else {
        sb.classList.remove("generating");
        sb.disabled = false;
        sb.title = "发送";
      }
    }
    const chatContainer = document.getElementById("chatMessages");
    if (typeof window.isSessionGenerating === "function" && window.isSessionGenerating(sessionName)) {
      const sessionDomCache = window.sessionDomCache;
      if (sessionDomCache && sessionDomCache.has(sessionName)) {
        const frag = sessionDomCache.get(sessionName);
        sessionDomCache.delete(sessionName);
        if (chatContainer) {
          chatContainer.querySelectorAll(".message, .chat-date-sep").forEach((el) => el.remove());
        }
        const ws = document.getElementById("welcomeScreen");
        if (ws) ws.style.display = "none";
        if (chatContainer) chatContainer.appendChild(frag);
        scrollToBottomForce();
      }
    } else {
      try {
        const response = await fetch(`/api/sessions/${encodeURIComponent(sessionName)}`);
        const data = await response.json();
        if (typeof window.renderChatHistory === "function") {
          window.renderChatHistory(data.history);
        }
      } catch (error) {
        console.error("Failed to load session:", error);
      }
    }
  }
  function scrollToBottom() {
    const isScrollLocked = window.isScrollLocked;
    if (isScrollLocked) return;
    const container = document.getElementById("chatMessages");
    if (container) container.scrollTop = container.scrollHeight;
  }
  function scrollToBottomForce() {
    window.isScrollLocked = false;
    const container = document.getElementById("chatMessages");
    if (container) {
      container.scrollTop = container.scrollHeight;
      updateBackToBottomBtn();
    }
  }
  function initScrollBehavior() {
    const container = document.getElementById("chatMessages");
    if (!container) return;
    container.addEventListener("scroll", () => {
      const distFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
      window.isScrollLocked = distFromBottom > 80;
      updateBackToBottomBtn();
    });
  }
  function updateBackToBottomBtn() {
    const btn = document.getElementById("backToBottomBtn");
    if (!btn) return;
    const container = document.getElementById("chatMessages");
    if (!container) return;
    const distFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
    const currentSession2 = window.currentSession;
    const isGenerating = currentSession2 && typeof window.isSessionGenerating === "function" && window.isSessionGenerating(currentSession2);
    btn.style.display = distFromBottom > 80 && isGenerating ? "flex" : "none";
  }
  function openProjectsManager() {
    const panel = document.getElementById("projectsManagerModal");
    if (panel) panel.style.display = "flex";
    _renderProjectsList();
  }
  function closeProjectsManager() {
    const panel = document.getElementById("projectsManagerModal");
    if (panel) panel.style.display = "none";
  }
  function _renderProjectsList() {
    const list = document.getElementById("projectsList");
    if (!list) return;
    const options = typeof window.getProjectOptions === "function" ? window.getProjectOptions() : [];
    list.innerHTML = options.map((p) => `
    <div class="project-entry">
      <input type="text" value="${window.escapeHtml?.(p.label) || p.label}" data-key="${window.escapeHtml?.(p.key) || p.key}" onchange="_saveProjectLabel(this)" placeholder="项目名称">
      ${p.key !== "default" ? `<button onclick="deleteProjectEntry('${window.escapeHtml?.(p.key) || p.key}')" class="ghost-btn" title="删除项目">✕</button>` : '<span style="font-size:11px;opacity:.5;">默认</span>'}
    </div>`).join("");
  }
  function deleteProjectEntry(key) {
    if (key === "default") return;
    const options = typeof window.getProjectOptions === "function" ? window.getProjectOptions() : [];
    const filtered = options.filter((p) => p.key !== key);
    if (typeof window.saveProjectOptions === "function") window.saveProjectOptions(filtered);
    const currentProject2 = window.currentProject;
    if (currentProject2 === key) {
      window.currentProject = "default";
      localStorage.setItem("koto.currentProject", "default");
    }
    if (typeof window.initProjectSelector === "function") window.initProjectSelector();
    _renderProjectsList();
  }
  function addProjectEntry() {
    const newKey = "proj_" + Date.now().toString(36);
    const options = typeof window.getProjectOptions === "function" ? window.getProjectOptions() : [];
    options.push({ key: newKey, label: "新项目" });
    if (typeof window.saveProjectOptions === "function") window.saveProjectOptions(options);
    if (typeof window.initProjectSelector === "function") window.initProjectSelector();
    _renderProjectsList();
  }
  function openWorkspaceFolder() {
    toggleWorkspace();
    if (typeof window.showNotification === "function") window.showNotification("已展开 Koto 工作区", "info", 2e3);
  }
  function toggleWorkspace() {
    const panel = document.getElementById("workspacePanel");
    if (!panel) return;
    panel.classList.toggle("active");
    if (panel.classList.contains("active")) {
      loadWorkspaceFiles();
    }
  }
  async function loadWorkspaceFiles() {
    try {
      const response = await fetch("/api/workspace");
      const data = await response.json();
      const container = document.getElementById("workspaceFiles");
      if (!container) return;
      if (data.files.length === 0) {
        container.innerHTML = `<div style="text-align: center; padding: 20px; color: var(--text-muted);"><p>No files yet</p></div>`;
        return;
      }
      container.innerHTML = data.files.map((file) => `
      <a href="/api/workspace/${file}" target="_blank" class="workspace-file">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
          <polyline points="14 2 14 8 20 8"></polyline>
        </svg>
        <span>${window.escapeHtml?.(file) || file}</span>
      </a>`).join("");
    } catch (error) {
      console.error("Failed to load workspace files:", error);
    }
  }
  window.goToWelcome = goToWelcome;
  window.renderWelcomeScreen = renderWelcomeScreen;
  window.selectSession = selectSession;
  window.scrollToBottom = scrollToBottom;
  window.scrollToBottomForce = scrollToBottomForce;
  window.initScrollBehavior = initScrollBehavior;
  window.updateBackToBottomBtn = updateBackToBottomBtn;
  window.openProjectsManager = openProjectsManager;
  window.closeProjectsManager = closeProjectsManager;
  window.deleteProjectEntry = deleteProjectEntry;
  window.addProjectEntry = addProjectEntry;
  window.openWorkspaceFolder = openWorkspaceFolder;
  window.toggleWorkspace = toggleWorkspace;
  window.loadWorkspaceFiles = loadWorkspaceFiles;
  function applyTheme(theme) {
    const root = document.documentElement;
    const isDark = theme === "dark" || theme === "auto" && window.matchMedia("(prefers-color-scheme: dark)").matches;
    root.setAttribute("data-theme", isDark ? "dark" : "light");
    document.body.classList.toggle("theme-dark", isDark);
    document.body.classList.toggle("theme-light", !isDark);
  }
  function updateThemeSelector(theme) {
    document.querySelectorAll(".theme-option").forEach((opt) => {
      const el = opt;
      el.classList.remove("active");
      if (el.dataset.theme === theme) {
        el.classList.add("active");
      }
    });
  }
  function selectTheme(theme) {
    updateThemeSelector(theme);
    applyTheme(theme);
    localStorage.setItem("koto.theme", theme);
    if (typeof window.updateSetting === "function") {
      window.updateSetting("appearance", "theme", theme);
    }
  }
  function setUIZoom(zoomStr, suppressSave = false) {
    const rawZoom = parseFloat(zoomStr);
    if (isNaN(rawZoom) || rawZoom <= 0) return;
    const zoom = Math.max(0.7, Math.min(1.5, rawZoom));
    const normalizedZoom = zoom.toFixed(2).replace(/\.?0+$/, "");
    const pct = Math.round(zoom * 100);
    const root = document.documentElement;
    root.style.fontSize = `${16 * zoom}px`;
    const display = document.getElementById("uiZoomDisplay");
    if (display) display.textContent = pct + "%";
    const slider = document.getElementById("uiZoomSlider");
    if (slider) slider.value = String(pct);
    document.querySelectorAll(".fs-preset-btn").forEach((btn) => {
      btn.classList.toggle("active", parseInt((btn.textContent || "").trim()) === pct);
    });
    localStorage.setItem("koto.uiZoom", normalizedZoom);
    if (!suppressSave) {
      if (typeof window.updateSetting === "function") {
        window.updateSetting("appearance", "ui_zoom", normalizedZoom);
      }
    }
  }
  function changeUIScale(delta) {
    const currentZoom = parseFloat(localStorage.getItem("koto.uiZoom") || "1");
    const newZoom = Math.max(0.7, Math.min(1.5, currentZoom + delta));
    setUIZoom(newZoom.toFixed(2));
  }
  window.applyTheme = applyTheme;
  window.updateThemeSelector = updateThemeSelector;
  window.selectTheme = selectTheme;
  window.setUIZoom = setUIZoom;
  window.changeUIScale = changeUIScale;
  class AppFramework {
    constructor() {
      this.apps = /* @__PURE__ */ new Map();
      this.windows = /* @__PURE__ */ new Map();
      this.activeWindow = null;
      this.initContainer();
      this.setupEventListeners();
    }
    initContainer() {
      const container = document.getElementById("appsContainer");
      if (!container) {
        console.error("Apps container not found");
        return;
      }
    }
    setupEventListeners() {
      document.addEventListener("click", (e) => {
        const target = e.target;
        if (target.closest(".app-icon-btn")) {
          const btn = target.closest(".app-icon-btn");
          const appId = btn.dataset["appId"];
          if (appId) this.toggleApp(appId);
        }
      });
      document.addEventListener("contextmenu", (e) => {
        if (e.target.closest(".app-window")) {
          e.preventDefault();
        }
      });
    }
    registerApp(id, config) {
      this.apps.set(id, config);
      if (!config.hidden) {
        this.createTaskbarIcon(id, config);
      }
      console.log(`[App Framework] Registered app: ${config.name}`);
    }
    createTaskbarIcon(appId, config) {
      const taskbarApps = document.getElementById("taskbarApps");
      if (!taskbarApps) return;
      const btn = document.createElement("button");
      btn.className = "app-icon-btn";
      btn.dataset["appId"] = appId;
      btn.title = config.name;
      btn.innerHTML = config.icon;
      taskbarApps.appendChild(btn);
    }
    toggleApp(appId) {
      if (this.windows.has(appId)) {
        const win = this.windows.get(appId);
        win.toggle();
      } else {
        this.openApp(appId);
      }
    }
    openApp(appId) {
      const config = this.apps.get(appId);
      if (!config) {
        console.error(`App not found: ${appId}`);
        return;
      }
      if (this.windows.has(appId)) {
        this.windows.get(appId).show();
        return;
      }
      const appWindow = new AppWindow(appId, config, this);
      this.windows.set(appId, appWindow);
      this.activeWindow = appId;
      this.updateTaskbarState(appId);
    }
    closeApp(appId) {
      if (this.windows.has(appId)) {
        const win = this.windows.get(appId);
        win.close();
        this.windows.delete(appId);
      }
      if (this.activeWindow === appId) {
        this.activeWindow = null;
      }
      this.updateTaskbarState(appId);
    }
    updateTaskbarState(appId) {
      const btn = document.querySelector(`[data-app-id="${appId}"]`);
      if (!btn) return;
      if (this.windows.has(appId) && !this.windows.get(appId).isMinimized) {
        btn.classList.add("active");
      } else {
        btn.classList.remove("active");
      }
    }
  }
  class AppWindow {
    constructor(appId, config, framework) {
      this.appId = appId;
      this.config = config;
      this.framework = framework;
      this.isDragging = false;
      this.dragOffsetX = 0;
      this.dragOffsetY = 0;
      this.isMinimized = false;
      this.create();
      this.setupPosition();
      this.setupDragAndDrop();
      this.setupContent();
    }
    create() {
      const container = document.getElementById("appsContainer");
      this.element = document.createElement("div");
      this.element.className = "app-window";
      this.element.id = `app-${this.appId}`;
      const titlebar = document.createElement("div");
      titlebar.className = "app-titlebar";
      const title = document.createElement("div");
      title.className = "app-title";
      title.innerHTML = `<span class="app-icon">${this.config.icon}</span><span>${this.config.name}</span>`;
      const controls = document.createElement("div");
      controls.className = "app-controls";
      const minBtn = document.createElement("button");
      minBtn.className = "app-btn";
      minBtn.innerHTML = "−";
      minBtn.onclick = (e) => {
        e.stopPropagation();
        this.minimize();
      };
      const closeBtn = document.createElement("button");
      closeBtn.className = "app-btn close";
      closeBtn.innerHTML = "✕";
      closeBtn.onclick = (e) => {
        e.stopPropagation();
        this.close();
      };
      controls.appendChild(minBtn);
      controls.appendChild(closeBtn);
      titlebar.appendChild(title);
      titlebar.appendChild(controls);
      this.contentDiv = document.createElement("div");
      this.contentDiv.className = "app-content";
      this.element.appendChild(titlebar);
      this.element.appendChild(this.contentDiv);
      container.appendChild(this.element);
      this.titlebar = titlebar;
    }
    setupPosition() {
      const offsetX = Math.random() * 100 - 50;
      const offsetY = Math.random() * 100 - 50;
      const x = window.innerWidth - 450 + offsetX;
      const y = 80 + offsetY;
      this.element.style.left = Math.max(0, x) + "px";
      this.element.style.top = Math.max(0, y) + "px";
      this.element.style.width = (this.config.width || 450) + "px";
      this.element.style.height = (this.config.height || 400) + "px";
    }
    setupDragAndDrop() {
      this.titlebar.addEventListener("mousedown", (e) => {
        if (e.target.closest(".app-controls")) return;
        this.isDragging = true;
        this.titlebar.classList.add("dragging");
        const rect = this.element.getBoundingClientRect();
        this.dragOffsetX = e.clientX - rect.left;
        this.dragOffsetY = e.clientY - rect.top;
        const onMouseMove = (moveEvent) => {
          if (this.isDragging) {
            this.element.style.left = moveEvent.clientX - this.dragOffsetX + "px";
            this.element.style.top = moveEvent.clientY - this.dragOffsetY + "px";
          }
        };
        const onMouseUp = () => {
          this.isDragging = false;
          this.titlebar.classList.remove("dragging");
          document.removeEventListener("mousemove", onMouseMove);
          document.removeEventListener("mouseup", onMouseUp);
        };
        document.addEventListener("mousemove", onMouseMove);
        document.addEventListener("mouseup", onMouseUp);
      });
    }
    setupContent() {
      if (this.config.createContent) {
        this.config.createContent(this.contentDiv);
      }
    }
    minimize() {
      this.isMinimized = !this.isMinimized;
      this.element.classList.toggle("minimized");
      const framework = window.appFramework;
      if (framework) {
        framework.updateTaskbarState(this.appId);
      }
    }
    show() {
      this.element.style.display = "flex";
      this.isMinimized = false;
      this.element.classList.remove("minimized");
    }
    toggle() {
      if (this.isMinimized) {
        this.minimize();
      } else {
        this.minimize();
      }
    }
    close() {
      this.element.remove();
      const framework = window.appFramework;
      if (framework) {
        framework.closeApp(this.appId);
      }
    }
  }
  class NotesApp {
    constructor(contentDiv) {
      this.contentDiv = contentDiv;
      this.notes = [];
      this.selectedNoteId = null;
      this.isAddingNote = false;
      this.render();
      this.loadNotes();
    }
    render() {
      this.contentDiv.innerHTML = `
      <div class="notes-app">
        <div class="notes-header">
          <input type="text" class="notes-search" id="notesSearch" placeholder="搜索笔记...">
          <button class="notes-add-btn" id="notesAddBtn">+ 新笔记</button>
        </div>
        <div class="notes-list" id="notesList"></div>
        <div id="notesEditor" style="display: none;"></div>
      </div>
    `;
      document.getElementById("notesAddBtn").addEventListener("click", () => this.showAddForm());
      document.getElementById("notesSearch").addEventListener("input", (e) => this.searchNotes(e.target.value));
    }
    async loadNotes() {
      try {
        const response = await fetch("/api/notes/list?limit=100");
        const data = await response.json();
        this.notes = data.notes || [];
        this.renderNotesList();
      } catch (error) {
        console.error("Failed to load notes:", error);
      }
    }
    renderNotesList() {
      const notesList = document.getElementById("notesList");
      if (!notesList) return;
      if (this.notes.length === 0) {
        notesList.innerHTML = `
        <div class="notes-empty">
          <div>
            <div class="notes-empty-icon">📝</div>
            <p>还没有笔记</p>
            <p style="font-size: 12px; margin-top: 8px;">点击"新笔记"开始记录</p>
          </div>
        </div>
      `;
        return;
      }
      notesList.innerHTML = "";
      this.notes.forEach((note) => {
        const noteItem = document.createElement("div");
        noteItem.className = "note-item";
        if (note.id === this.selectedNoteId) {
          noteItem.classList.add("selected");
        }
        const tagsHtml = (note.tags || []).map((tag) => `<span class="note-tag">#${tag}</span>`).join("");
        noteItem.innerHTML = `
        <div style="display: flex; align-items: start; gap: 8px;">
          <div style="flex: 1;">
            <div class="note-item-title">${this.escapeHtml(note.title)}</div>
            <div class="note-item-preview">${this.escapeHtml(note.content.substring(0, 50))}</div>
            <div class="note-item-meta">
              ${note.category ? `<span>📁 ${note.category}</span>` : ""}
              ${tagsHtml}
            </div>
          </div>
          <button class="note-delete-btn" data-note-id="${note.id}">🗑️</button>
        </div>
      `;
        noteItem.addEventListener("click", () => this.editNote(note));
        noteItem.querySelector(".note-delete-btn").addEventListener("click", (e) => {
          e.stopPropagation();
          this.deleteNote(note.id);
        });
        notesList.appendChild(noteItem);
      });
    }
    showAddForm() {
      const editor = document.getElementById("notesEditor");
      if (!editor) return;
      editor.style.display = "block";
      editor.innerHTML = `
      <div class="note-form">
        <div class="note-form-group">
          <label>标题</label>
          <input type="text" id="noteTitle" placeholder="输入笔记标题">
        </div>
        <div class="note-form-group">
          <label>内容</label>
          <textarea id="noteContent" placeholder="输入笔记内容"></textarea>
        </div>
        <div class="note-form-group">
          <label>分类</label>
          <input type="text" id="noteCategory" placeholder="输入分类(可选)">
        </div>
        <div class="note-form-group">
          <label>标签</label>
          <input type="text" id="noteTags" placeholder="输入标签，用逗号分隔(可选)">
        </div>
        <div class="note-form-actions">
          <button class="note-save-btn" id="noteSaveBtn">保存笔记</button>
          <button class="note-cancel-btn" id="noteCancelBtn">取消</button>
        </div>
      </div>
    `;
      document.getElementById("noteSaveBtn").addEventListener("click", () => this.saveNote());
      document.getElementById("noteCancelBtn").addEventListener("click", () => this.cancelEdit());
      setTimeout(() => document.getElementById("noteTitle").focus(), 100);
    }
    editNote(note) {
      this.selectedNoteId = note.id;
      this.renderNotesList();
      const editor = document.getElementById("notesEditor");
      if (!editor) return;
      editor.style.display = "block";
      editor.innerHTML = `
      <div class="note-form">
        <div class="note-form-group">
          <label>标题</label>
          <input type="text" id="noteTitle" value="${this.escapeHtml(note.title)}">
        </div>
        <div class="note-form-group">
          <label>内容</label>
          <textarea id="noteContent">${this.escapeHtml(note.content)}</textarea>
        </div>
        <div class="note-form-group">
          <label>分类</label>
          <input type="text" id="noteCategory" value="${this.escapeHtml(note.category || "")}">
        </div>
        <div class="note-form-group">
          <label>标签</label>
          <input type="text" id="noteTags" value="${(note.tags || []).join(", ")}">
        </div>
        <div class="note-form-actions">
          <button class="note-save-btn" id="noteSaveBtn">保存更改</button>
          <button class="note-cancel-btn" id="noteCancelBtn">取消</button>
        </div>
      </div>
    `;
      document.getElementById("noteSaveBtn").addEventListener("click", () => this.saveNote(note.id));
      document.getElementById("noteCancelBtn").addEventListener("click", () => this.cancelEdit());
    }
    async saveNote(noteId) {
      const titleEl = document.getElementById("noteTitle");
      const contentEl = document.getElementById("noteContent");
      const categoryEl = document.getElementById("noteCategory");
      const tagsEl = document.getElementById("noteTags");
      const title = titleEl.value.trim();
      const content = contentEl.value.trim();
      const category = categoryEl.value.trim() || "default";
      const tags = tagsEl.value.split(",").map((t) => t.trim()).filter((t) => t);
      if (!title || !content) {
        alert("标题和内容不能为空");
        return;
      }
      try {
        const response = await csrfFetch("/api/notes/add", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title, content, category, tags })
        });
        if (response.ok) {
          await this.loadNotes();
          this.cancelEdit();
          this.showNotification("✅ 笔记已保存");
        } else {
          this.showNotification("❌ 保存失败", true);
        }
      } catch (error) {
        console.error("Failed to save note:", error);
        this.showNotification("❌ 保存失败", true);
      }
    }
    async deleteNote(noteId) {
      if (!confirm("确认删除这条笔记吗？")) return;
      try {
        const response = await csrfFetch(`/api/notes/${noteId}`, { method: "DELETE" });
        if (response.ok) {
          await this.loadNotes();
          this.selectedNoteId = null;
          const editor = document.getElementById("notesEditor");
          if (editor) editor.style.display = "none";
          this.showNotification("✅ 笔记已删除");
        }
      } catch (error) {
        console.error("Failed to delete note:", error);
      }
    }
    searchNotes(query) {
      if (!query) {
        this.renderNotesList();
        return;
      }
      const filtered = this.notes.filter(
        (note) => note.title.toLowerCase().includes(query.toLowerCase()) || note.content.toLowerCase().includes(query.toLowerCase()) || (note.tags || []).some((tag) => tag.toLowerCase().includes(query.toLowerCase()))
      );
      const notesList = document.getElementById("notesList");
      if (!notesList) return;
      notesList.innerHTML = "";
      filtered.forEach((note) => {
        const noteItem = document.createElement("div");
        noteItem.className = "note-item";
        noteItem.innerHTML = `
        <div class="note-item-title">${this.escapeHtml(note.title)}</div>
        <div class="note-item-preview">${this.escapeHtml(note.content.substring(0, 50))}</div>
      `;
        noteItem.addEventListener("click", () => this.editNote(note));
        notesList.appendChild(noteItem);
      });
    }
    cancelEdit() {
      const editor = document.getElementById("notesEditor");
      if (editor) editor.style.display = "none";
      this.selectedNoteId = null;
      this.renderNotesList();
    }
    showNotification(message, isError = false) {
      const notification = document.createElement("div");
      notification.style.cssText = `
      position: fixed;
      top: 20px;
      right: 20px;
      padding: 12px 16px;
      background: ${isError ? "#ef4444" : "#22c55e"};
      color: white;
      border-radius: 8px;
      z-index: 10000;
      animation: slideIn 0.3s ease;
    `;
      notification.textContent = message;
      document.body.appendChild(notification);
      setTimeout(() => {
        notification.style.animation = "slideOut 0.3s ease";
        setTimeout(() => notification.remove(), 300);
      }, 2e3);
    }
    escapeHtml(text) {
      const div = document.createElement("div");
      div.textContent = text;
      return div.innerHTML;
    }
  }
  class ScheduleApp {
    constructor(container) {
      this.container = container;
      this.events = [];
      this.render();
      this.loadEvents();
    }
    render() {
      this.container.innerHTML = `
      <div class="schedule-app">
        <div class="schedule-header">
          <input type="text" class="schedule-search" id="scheduleSearch" placeholder="搜索日程...">
          <button class="schedule-add-btn" id="scheduleAddBtn">+ 新日程</button>
        </div>
        <div class="schedule-list" id="scheduleList"></div>
        <div id="scheduleEditor" style="display:none;"></div>
      </div>
    `;
      document.getElementById("scheduleAddBtn").addEventListener("click", () => this.showAddForm());
      document.getElementById("scheduleSearch").addEventListener("input", (e) => this.searchEvents(e.target.value));
    }
    async loadEvents() {
      try {
        const response = await fetch("/api/calendar/list?limit=200");
        const data = await response.json();
        this.events = data.events || [];
        this.renderEvents();
      } catch (error) {
        console.error("Failed to load events:", error);
        this.showNotification("加载日程失败", true);
      }
    }
    renderEvents(filtered) {
      const list = document.getElementById("scheduleList");
      if (!list) return;
      const items = filtered || this.events;
      if (!items || items.length === 0) {
        list.innerHTML = `
        <div class="schedule-empty">
          <div class="schedule-empty-icon">📅</div>
          <div>还没有日程，点击右上角新增</div>
        </div>
      `;
        return;
      }
      list.innerHTML = "";
      items.forEach((ev) => {
        const start = this.formatDate(ev.start);
        const end = ev.end ? this.formatDate(ev.end) : "";
        const item = document.createElement("div");
        item.className = "schedule-item";
        item.innerHTML = `
        <div class="schedule-item-title">${this.escapeHtml(ev.title)}</div>
        <div class="schedule-item-time">${start}${end ? " - " + end : ""}</div>
        <div class="schedule-item-desc">${this.escapeHtml((ev.description || "").slice(0, 120))}</div>
        <button class="schedule-delete-btn">删除</button>
      `;
        item.querySelector(".schedule-delete-btn").addEventListener("click", () => this.deleteEvent(ev.id));
        list.appendChild(item);
      });
    }
    showAddForm() {
      const editor = document.getElementById("scheduleEditor");
      if (!editor) return;
      editor.innerHTML = `
      <div class="schedule-form">
        <input type="text" id="eventTitle" placeholder="标题" required>
        <textarea id="eventDesc" placeholder="描述" rows="3"></textarea>
        <label>开始时间</label>
        <input type="datetime-local" id="eventStart" required>
        <label>结束时间 (可选)</label>
        <input type="datetime-local" id="eventEnd">
        <label>提前提醒 (分钟，可选)</label>
        <input type="number" id="eventRemind" min="0" placeholder="0">
        <div class="schedule-form-actions">
          <button class="schedule-cancel-btn" id="eventCancel">取消</button>
          <button class="schedule-save-btn" id="eventSave">保存日程</button>
        </div>
      </div>
    `;
      editor.style.display = "block";
      document.getElementById("eventCancel").addEventListener("click", () => {
        editor.style.display = "none";
      });
      document.getElementById("eventSave").addEventListener("click", () => this.saveEvent());
    }
    async saveEvent() {
      const titleEl = document.getElementById("eventTitle");
      const descEl = document.getElementById("eventDesc");
      const startEl = document.getElementById("eventStart");
      const endEl = document.getElementById("eventEnd");
      const remindEl = document.getElementById("eventRemind");
      const title = titleEl.value.trim();
      const description = descEl.value.trim();
      const start = startEl.value;
      const end = endEl.value;
      const remind = remindEl.value;
      if (!title || !start) {
        this.showNotification("标题和开始时间不能为空", true);
        return;
      }
      try {
        const payload = {
          title,
          description,
          start: this.toIso(start)
        };
        if (end) payload.end = this.toIso(end);
        if (remind) payload.remind_before_minutes = parseInt(remind, 10);
        const response = await csrfFetch("/api/calendar/add", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (data.success) {
          await this.loadEvents();
          const editor = document.getElementById("scheduleEditor");
          if (editor) editor.style.display = "none";
          this.showNotification("日程已保存");
        } else {
          this.showNotification(data.error || "保存失败", true);
        }
      } catch (error) {
        console.error("Failed to save event:", error);
        this.showNotification("保存失败", true);
      }
    }
    async deleteEvent(id) {
      if (!id) return;
      try {
        const res = await csrfFetch(`/api/calendar/${id}`, { method: "DELETE" });
        const data = await res.json();
        if (data.success) {
          this.events = this.events.filter((ev) => ev.id !== id);
          this.renderEvents();
          this.showNotification("已删除");
        } else {
          this.showNotification("删除失败", true);
        }
      } catch (error) {
        console.error("Delete event failed:", error);
        this.showNotification("删除失败", true);
      }
    }
    searchEvents(keyword) {
      const query = keyword.trim().toLowerCase();
      if (!query) {
        this.renderEvents();
        return;
      }
      const filtered = this.events.filter(
        (ev) => (ev.title || "").toLowerCase().includes(query) || (ev.description || "").toLowerCase().includes(query)
      );
      this.renderEvents(filtered);
    }
    formatDate(iso) {
      if (!iso) return "";
      try {
        const d = new Date(iso);
        const y = d.getFullYear();
        const m = String(d.getMonth() + 1).padStart(2, "0");
        const day = String(d.getDate()).padStart(2, "0");
        const hh = String(d.getHours()).padStart(2, "0");
        const mm = String(d.getMinutes()).padStart(2, "0");
        return `${y}-${m}-${day} ${hh}:${mm}`;
      } catch (e) {
        return iso;
      }
    }
    toIso(localStr) {
      try {
        const d = new Date(localStr);
        return d.toISOString();
      } catch (e) {
        return localStr;
      }
    }
    showNotification(message, isError = false) {
      const notification = document.createElement("div");
      notification.style.cssText = `
      position: fixed;
      top: 20px;
      right: 20px;
      padding: 12px 16px;
      background: ${isError ? "#ef4444" : "#22c55e"};
      color: white;
      border-radius: 8px;
      z-index: 10000;
      animation: slideIn 0.3s ease;
    `;
      notification.textContent = message;
      document.body.appendChild(notification);
      setTimeout(() => {
        notification.style.animation = "slideOut 0.3s ease";
        setTimeout(() => notification.remove(), 300);
      }, 2e3);
    }
    escapeHtml(text) {
      const div = document.createElement("div");
      div.textContent = text;
      return div.innerHTML;
    }
  }
  document.addEventListener("DOMContentLoaded", () => {
    const framework = new AppFramework();
    window.appFramework = framework;
    framework.registerApp("notes", {
      name: "笔记",
      icon: "📝",
      width: 480,
      height: 540,
      hidden: true,
      createContent: (contentDiv) => {
        new NotesApp(contentDiv);
      }
    });
    framework.registerApp("schedule", {
      name: "我的日程",
      icon: "🗓️",
      width: 520,
      height: 540,
      hidden: true,
      createContent: (contentDiv) => {
        new ScheduleApp(contentDiv);
      }
    });
    window.openScheduleApp = function() {
      window.appFramework.openApp("schedule");
    };
    console.log("[App Framework] 应用框架已初始化");
  });
})();
//# sourceMappingURL=app-bundle.js.map
