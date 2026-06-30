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
  const API = "/api/skillmarket";
  const $ = function(id) {
    return document.getElementById(id);
  };
  const searchInput = $("sc-search");
  const searchClear = $("sc-search-clear");
  const statTotal = $("stat-total");
  const statInstalled = $("stat-installed");
  const catList = $("sc-cat-list");
  const sortList = $("sc-sort-list");
  const aiInput = $("sc-ai-input");
  const aiBtn = $("sc-ai-btn");
  const aiLoading = $("sc-ai-loading");
  const gridEl = $("sc-grid");
  const aiGrid = $("sc-ai-grid");
  const aiResults = $("sc-ai-results");
  const aiClose = $("sc-ai-close");
  const countEl = $("sc-count");
  const viewGridBtn = $("sc-view-grid");
  const viewListBtn = $("sc-view-list");
  const overlay = $("sc-overlay");
  const mIcon = $("m-icon");
  const mName = $("m-name");
  const mBadge = $("m-badge");
  const mMeta = $("m-meta");
  const mClose = $("m-close");
  const mDesc = $("m-desc");
  const mSrc = $("m-src");
  const mCases = $("m-cases");
  const mDiff = $("m-diff");
  const mTags = $("m-tags");
  const mPromptHdr = $("m-prompt-hdr");
  const mChevron = $("m-chevron");
  const mPromptBody = $("m-prompt-body");
  const mPrompt = $("m-prompt");
  const mInstall = $("m-install");
  const mUninstall = $("m-uninstall");
  const toasts = $("sc-toasts");
  let allSkills = [];
  let currentCat = "all";
  let currentSort = "default";
  let currentSearch = "";
  let modalSkill = null;
  const CATS = [
    { id: "all", label: "全部", icon: "⭐" },
    { id: "behavior", label: "思维增强", icon: "🧠" },
    { id: "domain", label: "专业领域", icon: "💼" },
    { id: "coding", label: "代码工程", icon: "💻" }
  ];
  const CAT_LABELS = {};
  CATS.forEach(function(c) {
    CAT_LABELS[c.id] = c.label;
  });
  buildSidebar();
  showSkeleton();
  loadCatalog();
  bindEvents();
  function escHtml(s) {
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }
  function escAttr(s) {
    return String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/'/g, "&#39;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function buildSidebar() {
    catList.innerHTML = "";
    CATS.forEach(function(c) {
      const btn = document.createElement("button");
      btn.className = "sc-cat-btn" + (c.id === currentCat ? " active" : "");
      btn.dataset.cat = c.id;
      btn.innerHTML = '<span class="sc-cat-icon">' + c.icon + '</span><span class="sc-cat-label">' + c.label + '</span><span class="sc-cat-count" data-cat-count="' + c.id + '">-</span>';
      btn.addEventListener("click", function() {
        currentCat = c.id;
        const btns = catList.querySelectorAll(".sc-cat-btn");
        for (let i = 0; i < btns.length; i++) btns[i].classList.remove("active");
        btn.classList.add("active");
        renderGrid();
      });
      catList.appendChild(btn);
    });
  }
  function showSkeleton() {
    let html = "";
    for (let i = 0; i < 6; i++) {
      html += '<div class="sc-skel">  <div class="sk-row">    <div class="sk-pulse sk-icon"></div>    <div class="sk-lines"><div class="sk-pulse sk-l1"></div><div class="sk-pulse sk-l2"></div></div>  </div>  <div class="sk-pulse sk-d1"></div>  <div class="sk-pulse sk-d2"></div>  <div class="sk-tags"><div class="sk-pulse sk-tag"></div><div class="sk-pulse sk-tag"></div><div class="sk-pulse sk-tag"></div></div></div>';
    }
    gridEl.innerHTML = html;
  }
  function loadCatalog() {
    fetch(API + "/community/catalog").then(function(r) {
      return r.json();
    }).then(function(d) {
      if (!d.success) throw new Error(d.error || "未知错误");
      allSkills = d.skills || [];
      updateStats();
      renderGrid();
    }).catch(function(err) {
      console.error("[skill_community] loadCatalog error:", err);
      gridEl.innerHTML = '<div class="sc-empty">  <div class="sc-empty-icon">😿</div>  <h3>加载失败</h3>  <p>' + escHtml(err.message || String(err)) + '</p>  <button class="sc-retry" onclick="location.reload()">🔄 重新加载</button></div>';
    });
  }
  function updateStats() {
    statTotal.textContent = String(allSkills.length);
    var instCount = 0;
    for (let i = 0; i < allSkills.length; i++) {
      if (allSkills[i].is_installed) instCount++;
    }
    statInstalled.textContent = String(instCount);
    const counts = { all: allSkills.length, behavior: 0, domain: 0, coding: 0 };
    for (let j = 0; j < allSkills.length; j++) {
      const cat = allSkills[j].category || "domain";
      if (counts[cat] !== void 0) counts[cat]++;
    }
    CATS.forEach(function(c) {
      const el = document.querySelector('[data-cat-count="' + c.id + '"]');
      if (el) el.textContent = String(counts[c.id]);
    });
  }
  function getFiltered() {
    let list = allSkills.slice();
    if (currentCat !== "all") {
      list = list.filter(function(s) {
        return s.category === currentCat;
      });
    }
    if (currentSearch) {
      const q = currentSearch.toLowerCase();
      list = list.filter(function(s) {
        const hay = (s.name || "") + " " + (s.description || "") + " " + (s.tags || []).join(" ") + " " + (s.author || "");
        return hay.toLowerCase().indexOf(q) >= 0;
      });
    }
    if (currentSort === "name") {
      list.sort(function(a, b) {
        return (a.name || "").localeCompare(b.name || "");
      });
    } else if (currentSort === "installed") {
      list.sort(function(a, b) {
        return (b.is_installed ? 1 : 0) - (a.is_installed ? 1 : 0);
      });
    }
    return list;
  }
  function renderGrid() {
    const list = getFiltered();
    countEl.textContent = "共 " + list.length + " 个技能";
    if (list.length === 0) {
      gridEl.innerHTML = '<div class="sc-empty">  <div class="sc-empty-icon">🔍</div>  <h3>没有匹配的技能</h3>  <p>试试换个关键词或切换分类</p></div>';
      return;
    }
    const ordered = [];
    if (currentCat === "all") {
      ["behavior", "domain", "coding"].forEach(function(cat) {
        const group = list.filter(function(s) {
          return s.category === cat;
        });
        if (group.length > 0) {
          ordered.push({ type: "header", cat, count: group.length });
          group.forEach(function(s) {
            ordered.push({ type: "card", skill: s });
          });
        }
      });
      const uncategorized = list.filter(function(s) {
        return !s.category || ["behavior", "domain", "coding"].indexOf(s.category) < 0;
      });
      if (uncategorized.length > 0) {
        ordered.push({ type: "header", cat: "other", count: uncategorized.length });
        uncategorized.forEach(function(s) {
          ordered.push({ type: "card", skill: s });
        });
      }
    } else {
      list.forEach(function(s) {
        ordered.push({ type: "card", skill: s });
      });
    }
    const catIcons = { behavior: "🧠", domain: "💼", coding: "💻", other: "📦" };
    const catNames = { behavior: "思维增强", domain: "专业领域", coding: "代码工程", other: "其他" };
    let html = "";
    for (let i = 0; i < ordered.length; i++) {
      const item = ordered[i];
      if (item.type === "header") {
        html += '<div class="sc-group-hdr">  <span class="sc-group-icon">' + (catIcons[item.cat] || "📦") + '</span>  <span class="sc-group-name">' + (catNames[item.cat] || item.cat) + '</span>  <span class="sc-group-num">' + item.count + "</span></div>";
      } else {
        html += renderCard(item.skill);
      }
    }
    gridEl.innerHTML = html;
  }
  function renderCard(s) {
    const installed = s.is_installed;
    let tagsHtml = "";
    const tags = s.tags || [];
    const showTags = tags.slice(0, 3);
    for (let i = 0; i < showTags.length; i++) {
      tagsHtml += '<span class="sc-tag sc-tag-plain">' + escHtml(showTags[i]) + "</span>";
    }
    if (tags.length > 3) tagsHtml += '<span class="sc-tag sc-tag-plain">+' + (tags.length - 3) + "</span>";
    const catLabel = CAT_LABELS[s.category] || s.category || "";
    const btnCls = installed ? "sc-ibtn done" : "sc-ibtn inst";
    const btnTxt = installed ? "✓ 已装" : "安装";
    return '<div class="sc-card" data-id="' + escAttr(s.id) + '">  <div class="sc-card-hdr">    <div class="sc-card-icon">' + (s.icon || "🤖") + '</div>    <div class="sc-card-info">      <div class="sc-card-name">' + escHtml(s.name) + (installed ? ' <span class="sc-badge-ok">✓</span>' : "") + '      </div>      <div class="sc-card-author">' + escHtml(s.author || "") + '</div>    </div>  </div>  <div class="sc-card-desc">' + escHtml(s.description || "") + '</div>  <div class="sc-card-tags">    <span class="sc-tag sc-tag-cat">' + escHtml(catLabel) + "</span>" + tagsHtml + '  </div>  <div class="sc-card-foot">    <span class="sc-likes">❤ ' + (s.likes || 0) + '</span>    <button class="' + btnCls + '" data-install="' + escAttr(s.id) + '">' + btnTxt + "</button>  </div></div>";
  }
  function toast(type, msg) {
    const el = document.createElement("div");
    el.className = "sc-toast " + type;
    el.textContent = (type === "ok" ? "✅ " : "❌ ") + msg;
    toasts.appendChild(el);
    setTimeout(function() {
      el.style.opacity = "0";
      el.style.transition = "opacity .3s";
      setTimeout(function() {
        el.remove();
      }, 300);
    }, 3e3);
  }
  function quickInstall(skillId, btnEl) {
    if (btnEl.classList.contains("done") || btnEl.classList.contains("busy")) return;
    btnEl.classList.remove("inst");
    btnEl.classList.add("busy");
    btnEl.textContent = "安装中…";
    csrfFetch(API + "/community/install/" + encodeURIComponent(skillId), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({})
    }).then(function(r) {
      return r.json();
    }).then(function(d) {
      if (d.success) {
        btnEl.classList.remove("busy");
        btnEl.classList.add("done");
        btnEl.textContent = "✓ 已装";
        markInstalled(skillId);
        toast("ok", d.message || "安装成功");
      } else if (d.error && d.error.indexOf("已安装") >= 0) {
        return csrfFetch(API + "/community/install/" + encodeURIComponent(skillId), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ overwrite: true })
        }).then(function(r2) {
          return r2.json();
        }).then(function(d2) {
          btnEl.classList.remove("busy");
          if (d2.success) {
            btnEl.classList.add("done");
            btnEl.textContent = "✓ 已装";
            markInstalled(skillId);
            toast("ok", d2.message || "覆盖安装成功");
          } else {
            btnEl.classList.add("inst");
            btnEl.textContent = "安装";
            toast("err", d2.error || "安装失败");
          }
        });
      } else {
        btnEl.classList.remove("busy");
        btnEl.classList.add("inst");
        btnEl.textContent = "安装";
        toast("err", d.error || "安装失败");
      }
    }).catch(function(err) {
      btnEl.classList.remove("busy");
      btnEl.classList.add("inst");
      btnEl.textContent = "安装";
      toast("err", "网络错误: " + err.message);
    });
  }
  function onlineInstall(resultIndex, btnEl) {
    if (btnEl.classList.contains("done") || btnEl.classList.contains("busy")) return;
    const idx = parseInt(resultIndex, 10);
    const result = window._aiResults && window._aiResults[idx];
    if (!result) return;
    btnEl.classList.remove("inst");
    btnEl.classList.add("busy");
    btnEl.textContent = "安装中…";
    csrfFetch(API + "/community/online-install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: result.name,
        full_prompt: result.full_prompt || "",
        source_repo: result.source_repo || "",
        source_path: result.source_path || "",
        source_kind: result.source_kind || "",
        source_name: result.source_name || "",
        source_url: result.source_url || "",
        description: result.description || "",
        author: result.author || "Open Source",
        tags: result.tags || []
      })
    }).then(function(r) {
      return r.json();
    }).then(function(d) {
      btnEl.classList.remove("busy");
      if (d.success) {
        btnEl.classList.add("done");
        btnEl.textContent = "✓ 已装";
        toast("ok", d.message || "安装成功");
      } else {
        btnEl.classList.add("inst");
        btnEl.textContent = "安装";
        toast("err", d.error || "安装失败");
      }
    }).catch(function(err) {
      btnEl.classList.remove("busy");
      btnEl.classList.add("inst");
      btnEl.textContent = "安装";
      toast("err", "网络错误: " + err.message);
    });
  }
  function markInstalled(skillId) {
    for (let i = 0; i < allSkills.length; i++) {
      if (allSkills[i].id === skillId) {
        allSkills[i].is_installed = true;
        break;
      }
    }
    updateStats();
  }
  function markUninstalled(skillId) {
    for (let i = 0; i < allSkills.length; i++) {
      if (allSkills[i].id === skillId) {
        allSkills[i].is_installed = false;
        break;
      }
    }
    updateStats();
  }
  function doAiRecommend() {
    const query = (aiInput ? aiInput.value : "").trim();
    if (!query) return;
    aiLoading.style.display = "block";
    aiBtn.setAttribute("disabled", "true");
    csrfFetch(API + "/community/ai-recommend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query })
    }).then(function(r) {
      return r.json();
    }).then(function(d) {
      aiLoading.style.display = "none";
      aiBtn.removeAttribute("disabled");
      const results = d.results || [];
      window._aiResults = results;
      if (results.length === 0) {
        toast("err", "没有找到匹配的技能，换个关键词试试");
        return;
      }
      renderAiResults(results);
    }).catch(function(err) {
      aiLoading.style.display = "none";
      aiBtn.removeAttribute("disabled");
      toast("err", "AI 推荐失败: " + err.message);
    });
  }
  function renderAiResults(results) {
    let html = "";
    for (let i = 0; i < results.length; i++) {
      const r = results[i];
      html += '<div class="sc-card">  <div class="sc-card-hdr">    <div class="sc-card-icon">✨</div>    <div class="sc-card-info">      <div class="sc-card-name">' + escHtml(r.name) + '</div>      <div class="sc-card-author">' + escHtml(r.source_name || r.author || "Open Source") + '</div>    </div>  </div>  <div class="sc-card-desc">' + escHtml(r.description || "") + '</div>  <div class="sc-card-foot">    <span class="sc-tag sc-tag-plain">' + escHtml(r.source_name || "开源") + '</span>    <button class="sc-ibtn inst" data-install="' + i + '">安装</button>  </div></div>';
    }
    aiGrid.innerHTML = html;
    aiResults.style.display = "block";
  }
  function openDetail(skillId) {
    let local = null;
    for (let i = 0; i < allSkills.length; i++) {
      if (allSkills[i].id === skillId) {
        local = allSkills[i];
        break;
      }
    }
    if (!local) return;
    showModal(local);
    fetch(API + "/community/skill/" + encodeURIComponent(skillId)).then(function(r) {
      return r.json();
    }).then(function(d) {
      if (d.success && d.skill) {
        modalSkill = d.skill;
        mPrompt.textContent = d.skill.prompt || "(无 prompt)";
      }
    }).catch(function() {
    });
  }
  function showModal(s) {
    modalSkill = s;
    mIcon.textContent = s.icon || "🤖";
    mName.textContent = s.name || "";
    mBadge.style.display = s.is_installed ? "inline-flex" : "none";
    mMeta.textContent = (s.author || "") + " · v" + (s.version || "1.0") + " · " + (s.source_name || "社区");
    mDesc.textContent = s.description || "";
    mSrc.textContent = s.source_name ? "来源：" + s.source_name : "";
    const cm = s.community_meta || {};
    mCases.innerHTML = "";
    (cm.use_cases || []).forEach(function(c) {
      const chip = document.createElement("span");
      chip.className = "sc-chip";
      chip.textContent = c;
      mCases.appendChild(chip);
    });
    if (mCases.innerHTML === "") mCases.innerHTML = '<span class="sc-chip">通用</span>';
    const diff = cm.difficulty || "中等";
    const dotClass = diff === "较易" ? "dot-easy" : diff === "较难" ? "dot-hard" : "dot-med";
    mDiff.innerHTML = '<span class="sc-dot ' + dotClass + '"></span> ' + escHtml(diff);
    mTags.innerHTML = "";
    (s.tags || []).forEach(function(t) {
      const tag = document.createElement("span");
      tag.className = "sc-tag sc-tag-plain";
      tag.textContent = t;
      mTags.appendChild(tag);
    });
    mPrompt.textContent = s.prompt || "加载中…";
    mPromptBody.classList.remove("open");
    mChevron.textContent = "▼";
    if (s.is_installed) {
      mInstall.textContent = "✅ 已安装";
      mInstall.classList.add("done");
      mUninstall.style.display = "inline-flex";
    } else {
      mInstall.textContent = "⬇️ 安装到 Koto";
      mInstall.classList.remove("done");
      mUninstall.style.display = "none";
    }
    overlay.classList.add("open");
    document.body.style.overflow = "hidden";
  }
  function closeModal() {
    overlay.classList.remove("open");
    document.body.style.overflow = "";
    modalSkill = null;
  }
  function doInstall(skill) {
    if (mInstall.classList.contains("done")) return;
    mInstall.textContent = "安装中…";
    mInstall.disabled = true;
    csrfFetch(API + "/community/install/" + encodeURIComponent(skill.id), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({})
    }).then(function(r) {
      return r.json();
    }).then(function(d) {
      mInstall.disabled = false;
      if (d.success) {
        mInstall.textContent = "✅ 已安装";
        mInstall.classList.add("done");
        mBadge.style.display = "inline-flex";
        mUninstall.style.display = "inline-flex";
        markInstalled(skill.id);
        renderGrid();
        toast("ok", d.message || "安装成功");
      } else if (d.error && d.error.indexOf("已安装") >= 0) {
        csrfFetch(API + "/community/install/" + encodeURIComponent(skill.id), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ overwrite: true })
        }).then(function(r2) {
          return r2.json();
        }).then(function(d2) {
          if (d2.success) {
            mInstall.textContent = "✅ 已安装";
            mInstall.classList.add("done");
            mBadge.style.display = "inline-flex";
            mUninstall.style.display = "inline-flex";
            markInstalled(skill.id);
            renderGrid();
            toast("ok", d2.message || "覆盖安装成功");
          } else {
            mInstall.textContent = "⬇️ 安装到 Koto";
            toast("err", d2.error || "安装失败");
          }
        });
      } else {
        mInstall.textContent = "⬇️ 安装到 Koto";
        toast("err", d.error || "安装失败");
      }
    }).catch(function(err) {
      mInstall.disabled = false;
      mInstall.textContent = "⬇️ 安装到 Koto";
      toast("err", "网络错误: " + err.message);
    });
  }
  function doUninstall(skill) {
    if (!confirm("确定要卸载「" + skill.name + "」吗？")) return;
    csrfFetch(API + "/uninstall/" + encodeURIComponent(skill.id), {
      method: "DELETE",
      headers: { "Content-Type": "application/json" }
    }).then(function(r) {
      return r.json();
    }).then(function(d) {
      if (d.success) {
        mInstall.textContent = "⬇️ 安装到 Koto";
        mInstall.classList.remove("done");
        mBadge.style.display = "none";
        mUninstall.style.display = "none";
        markUninstalled(skill.id);
        renderGrid();
        toast("ok", "已卸载");
      } else {
        toast("err", d.error || "卸载失败");
      }
    }).catch(function(err) {
      toast("err", "网络错误: " + err.message);
    });
  }
  function bindEvents() {
    searchInput.addEventListener("input", function() {
      currentSearch = searchInput.value.trim();
      searchClear.classList.toggle("show", currentSearch.length > 0);
      renderGrid();
    });
    searchClear.addEventListener("click", function() {
      searchInput.value = "";
      currentSearch = "";
      searchClear.classList.remove("show");
      renderGrid();
    });
    sortList.addEventListener("click", function(e) {
      const btn = e.target.closest(".sc-sort-btn");
      if (!btn) return;
      currentSort = btn.dataset.sort || "default";
      const btns = sortList.querySelectorAll(".sc-sort-btn");
      for (let i = 0; i < btns.length; i++) btns[i].classList.remove("active");
      btn.classList.add("active");
      renderGrid();
    });
    viewGridBtn.addEventListener("click", function() {
      viewGridBtn.classList.add("active");
      viewListBtn.classList.remove("active");
      document.querySelector(".sc-main").classList.remove("list-view");
    });
    viewListBtn.addEventListener("click", function() {
      viewListBtn.classList.add("active");
      viewGridBtn.classList.remove("active");
      document.querySelector(".sc-main").classList.add("list-view");
    });
    gridEl.addEventListener("click", function(e) {
      const installBtn = e.target.closest("[data-install]");
      if (installBtn) {
        e.stopPropagation();
        quickInstall(installBtn.dataset.install, installBtn);
        return;
      }
      const card = e.target.closest(".sc-card");
      if (card) openDetail(card.dataset.id);
    });
    aiGrid.addEventListener("click", function(e) {
      const installBtn = e.target.closest("[data-install]");
      if (installBtn) {
        e.stopPropagation();
        onlineInstall(installBtn.dataset.install, installBtn);
        return;
      }
    });
    aiBtn.addEventListener("click", doAiRecommend);
    aiInput.addEventListener("keydown", function(e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        doAiRecommend();
      }
    });
    aiClose.addEventListener("click", function() {
      aiResults.style.display = "none";
    });
    mClose.addEventListener("click", closeModal);
    overlay.addEventListener("click", function(e) {
      if (e.target === overlay) closeModal();
    });
    document.addEventListener("keydown", function(e) {
      if (e.key === "Escape") closeModal();
    });
    mPromptHdr.addEventListener("click", function() {
      mPromptBody.classList.toggle("open");
      mChevron.textContent = mPromptBody.classList.contains("open") ? "▲" : "▼";
    });
    mInstall.addEventListener("click", function() {
      if (!modalSkill) return;
      doInstall(modalSkill);
    });
    mUninstall.addEventListener("click", function() {
      if (!modalSkill) return;
      doUninstall(modalSkill);
    });
  }
})();
//# sourceMappingURL=skill-community-bundle.js.map
