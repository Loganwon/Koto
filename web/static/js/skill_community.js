/**
 * Koto Skill 社区 — 前端逻辑（v2 完全重写）
 * ====================================
 * 通过 /api/skillmarket/community/* 与后端交互
 * 功能：浏览精选 Skills → 搜索 → 安装 → AI 推荐
 */

'use strict';

/* ═══════════════ Constants ══════════════════════════════════ */
var API_BASE = '/api/skillmarket/community';

var CAT_CONFIG = [
  { id: 'all',           label: '全部',     icon: '⭐' },
  { id: 'koto_thinking', label: '思维增强', icon: '🧠' },
  { id: 'writing',       label: '写作创作', icon: '✍️' },
  { id: 'career',        label: '专业咨询', icon: '💼' },
  { id: 'research',      label: '调研分析', icon: '🔍' },
  { id: 'code_debug',    label: '代码调试', icon: '🐛' },
  { id: 'language',      label: '语言学习', icon: '🗣️' },
  { id: 'lifestyle',     label: '生活实用', icon: '🎤' },
];

var DIFF_DOT = { '简单': 'diff-easy', '中等': 'diff-medium', '较难': 'diff-hard' };

/* ═══════════════ State ══════════════════════════════════════ */
var S = {
  skills: [],
  filter: 'all',
  query: '',
  sort: 'default',
  modalSkillId: null,
};

/* ═══════════════ Util ═══════════════════════════════════════ */
function $(sel, ctx) { return (ctx || document).querySelector(sel); }
function $$(sel, ctx) { return Array.prototype.slice.call((ctx || document).querySelectorAll(sel)); }

function esc(s) {
  var d = document.createElement('div');
  d.textContent = String(s == null ? '' : s);
  return d.innerHTML;
}

function toast(msg, type, ms) {
  type = type || 'info'; ms = ms || 3500;
  var box = $('#sc-toast-container');
  if (!box) return;
  var el = document.createElement('div');
  el.className = 'sc-toast ' + type;
  var icons = { success: '✅', error: '❌', info: 'ℹ️' };
  el.innerHTML = '<span>' + (icons[type] || 'ℹ️') + '</span> <span>' + esc(msg) + '</span>';
  box.appendChild(el);
  setTimeout(function () {
    el.style.opacity = '0';
    el.style.transition = 'opacity .3s';
    setTimeout(function () { el.remove(); }, 350);
  }, ms);
}

function apiFetch(method, path, body) {
  var opts = { method: method, headers: {} };
  if (body) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  return fetch(API_BASE + path, opts)
    .then(function (res) {
      return res.json().catch(function () { return { error: res.statusText }; })
        .then(function (data) {
          if (!res.ok && res.status !== 409) throw new Error(data.error || ('HTTP ' + res.status));
          return data;
        });
    })
    .catch(function (e) {
      throw new Error(e.message || '网络请求失败');
    });
}

/* ═══════════════ Init ═══════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', function () {
  buildFilterTabs();
  bindEvents();
  loadCatalog();
});

/* ═══════════════ Filter Tabs ════════════════════════════════ */
function buildFilterTabs() {
  var bar = $('#sc-filter-bar');
  if (!bar) return;
  var sortSel = $('#sc-sort-select');
  CAT_CONFIG.forEach(function (cat) {
    var btn = document.createElement('button');
    btn.className = 'sc-filter-tab' + (cat.id === 'all' ? ' active' : '');
    btn.dataset.cat = cat.id;
    btn.innerHTML = cat.icon + ' ' + esc(cat.label) +
      ' <span class="tab-count" id="tab-count-' + cat.id + '">—</span>';
    btn.addEventListener('click', function () {
      S.filter = cat.id;
      $$('.sc-filter-tab').forEach(function (t) {
        t.classList.toggle('active', t.dataset.cat === cat.id);
      });
      renderGrid();
    });
    if (sortSel) bar.insertBefore(btn, sortSel);
    else bar.appendChild(btn);
  });
}

/* ═══════════════ Events ═════════════════════════════════════ */
function bindEvents() {
  var searchInput = $('#sc-search-input');
  if (searchInput) {
    var timer;
    searchInput.addEventListener('input', function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        S.query = searchInput.value.trim().toLowerCase();
        renderGrid();
      }, 250);
    });
  }
  var sortSel = $('#sc-sort-select');
  if (sortSel) {
    sortSel.addEventListener('change', function () {
      S.sort = sortSel.value;
      renderGrid();
    });
  }
  var overlay = $('#sc-modal-overlay');
  if (overlay) {
    var closeBtn = $('#sc-modal-close');
    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) closeModal();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') closeModal();
    });
  }
}

/* ═══════════════ Load Catalog ═══════════════════════════════ */
function loadCatalog() {
  showSkeletons();
  apiFetch('GET', '/catalog')
    .then(function (data) {
      S.skills = data.skills || [];
      updateCounts();
      renderGrid();
    })
    .catch(function (e) {
      var grid = $('#sc-grid');
      if (grid) {
        grid.innerHTML =
          '<div class="sc-empty" style="grid-column:1/-1">' +
            '<div class="sc-empty-icon">⚠️</div>' +
            '<h3>加载失败</h3>' +
            '<p>' + esc(e.message) + '</p>' +
            '<button class="sc-retry-btn" onclick="loadCatalog()">🔄 重试</button>' +
          '</div>';
      }
    });
}

/* ═══════════════ Counts ═════════════════════════════════════ */
function updateCounts() {
  var skills = S.skills;
  var el;
  el = $('#hero-stat-total');     if (el) el.textContent = skills.length;
  el = $('#hero-stat-cats');      if (el) el.textContent = uniqueValues(skills, 'subcategory');
  el = $('#hero-stat-installed'); if (el) el.textContent = skills.filter(function (s) { return s.is_installed; }).length;

  var allEl = $('#tab-count-all');
  if (allEl) allEl.textContent = skills.length;

  var counts = {};
  skills.forEach(function (s) {
    var c = s.subcategory;
    counts[c] = (counts[c] || 0) + 1;
  });
  Object.keys(counts).forEach(function (c) {
    el = $('#tab-count-' + c);
    if (el) el.textContent = counts[c];
  });
}

function uniqueValues(arr, key) {
  var seen = {};
  arr.forEach(function (o) { if (o[key]) seen[o[key]] = true; });
  return Object.keys(seen).length;
}

/* ═══════════════ Render Grid ════════════════════════════════ */
function getFiltered() {
  var list = S.skills.slice();
  if (S.filter !== 'all') {
    list = list.filter(function (s) {
      return s.subcategory === S.filter || s.category === S.filter;
    });
  }
  if (S.query) {
    var q = S.query;
    list = list.filter(function (s) {
      return (s.name || '').toLowerCase().indexOf(q) >= 0 ||
             (s.description || '').toLowerCase().indexOf(q) >= 0 ||
             (s.author || '').toLowerCase().indexOf(q) >= 0 ||
             (s.tags || []).some(function (t) { return t.toLowerCase().indexOf(q) >= 0; });
    });
  }
  if (S.sort === 'name') {
    list.sort(function (a, b) { return (a.name || '').localeCompare(b.name || ''); });
  } else if (S.sort === 'installed') {
    list.sort(function (a, b) { return (b.is_installed ? 1 : 0) - (a.is_installed ? 1 : 0); });
  }
  return list;
}

function renderGrid() {
  var grid = $('#sc-grid');
  if (!grid) return;
  var list = getFiltered();

  var countEl = $('#sc-results-count');
  if (countEl) countEl.textContent = list.length + ' 个技能';

  if (!list.length) {
    grid.innerHTML =
      '<div class="sc-empty">' +
        '<div class="sc-empty-icon">🔍</div>' +
        '<h3>没有找到匹配的技能</h3>' +
        '<p>尝试更换搜索词或切换分类</p>' +
      '</div>';
    return;
  }

  var showGrouped = S.filter === 'all' && !S.query;
  var html = '';

  if (showGrouped) {
    var groups = {};
    list.forEach(function (s) {
      var c = s.subcategory;
      (groups[c] || (groups[c] = [])).push(s);
    });
    CAT_CONFIG.forEach(function (cat) {
      if (cat.id === 'all') return;
      var items = groups[cat.id];
      if (!items || !items.length) return;
      html += '<div class="sc-group-header">' +
        '<span class="sc-group-label">' + cat.icon + ' ' + esc(cat.label) + '</span>' +
        '<span class="sc-group-count">' + items.length + '</span>' +
      '</div>';
      items.forEach(function (s) { html += renderCard(s); });
    });
  } else {
    list.forEach(function (s) { html += renderCard(s); });
  }

  grid.innerHTML = html;

  // Bind card click → modal
  $$('.sc-card', grid).forEach(function (card) {
    card.addEventListener('click', function (e) {
      if (e.target.closest('.sc-install-btn')) return;
      openModal(card.dataset.id);
    });
  });
  // Bind install button
  $$('[data-action="install"]', grid).forEach(function (btn) {
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      installSkill(btn.dataset.id, btn);
    });
  });
}

function renderCard(s) {
  var catCfg = CAT_CONFIG.find(function (c) { return c.id === s.subcategory; }) || {};
  var diff = (s.community_meta && s.community_meta.difficulty) || '中等';
  var diffCls = DIFF_DOT[diff] || 'diff-medium';
  var installed = s.is_installed;
  var badge = installed ? '<span class="sc-installed-badge">✓ 已安装</span>' : '';
  var installBtn = installed
    ? '<button class="sc-install-btn installed" disabled>✓ 已安装</button>'
    : '<button class="sc-install-btn install" data-action="install" data-id="' + esc(s.id) + '">⬇️ 安装</button>';
  var tagsHtml = (s.tags || []).slice(0, 3).map(function (t) {
    return '<span class="sc-tag sc-tag-plain">' + esc(t) + '</span>';
  }).join('');

  var likesHtml = s.likes ? '<span class="sc-likes">★ ' + esc(s.likes) + '</span>' : '';

  return '<div class="sc-card" data-id="' + esc(s.id) + '">' +
    '<div class="sc-card-header">' +
      '<div class="sc-card-icon">' + esc(s.icon || '🔧') + '</div>' +
      '<div class="sc-card-meta">' +
        '<div class="sc-card-name">' + esc(s.name) + badge + '</div>' +
        '<div class="sc-card-author">' + esc(s.author || 'Koto Community') + likesHtml + '</div>' +
      '</div>' +
    '</div>' +
    '<div class="sc-card-desc">' + esc(s.description || '') + '</div>' +
    var srcTag = s.source_name ? '<span class="sc-tag sc-tag-src">' + esc(s.source_name) + '</span>' : '';
    return '<div class="sc-card" data-id="' + esc(s.id) + '">' +
    '<div class="sc-card-header">' +
      '<div class="sc-card-icon">' + esc(s.icon || '🔧') + '</div>' +
      '<div class="sc-card-meta">' +
        '<div class="sc-card-name">' + esc(s.name) + badge + '</div>' +
        '<div class="sc-card-author">' + esc(s.author || 'Koto Community') + likesHtml + '</div>' +
      '</div>' +
    '</div>' +
    '<div class="sc-card-desc">' + esc(s.description || '') + '</div>' +
    '<div class="sc-card-tags">' +
      '<span class="sc-tag sc-tag-cat">' + (catCfg.icon || '') + ' ' + esc(catCfg.label || s.subcategory || '') + '</span>' +
      tagsHtml + srcTag +
    '</div>' +
    '<div class="sc-card-footer">' +
      '<span class="sc-difficulty"><span class="sc-difficulty-dot ' + diffCls + '"></span>' + esc(diff) + '</span>' +
      installBtn +
    '</div>' +
  '</div>';
}

/* ═══════════════ Skeleton ═══════════════════════════════════ */
function showSkeletons() {
  var grid = $('#sc-grid');
  if (!grid) return;
  var h = '';
  for (var i = 0; i < 9; i++) {
    h += '<div class="sc-skeleton">' +
      '<div class="skel-header">' +
        '<div class="skel-pulse skel-icon"></div>' +
        '<div class="skel-meta"><div class="skel-pulse skel-title"></div><div class="skel-pulse skel-subtitle"></div></div>' +
      '</div>' +
      '<div class="skel-pulse skel-desc1"></div>' +
      '<div class="skel-pulse skel-desc2"></div>' +
      '<div class="skel-tags"><div class="skel-pulse skel-tag"></div><div class="skel-pulse skel-tag"></div></div>' +
    '</div>';
  }
  grid.innerHTML = h;
}

/* ═══════════════ Install Skill ══════════════════════════════ */
function installSkill(id, btnEl) {
  if (!btnEl || btnEl.disabled) return;
  var orig = btnEl.innerHTML;
  btnEl.disabled = true;
  btnEl.className = 'sc-install-btn loading';
  btnEl.innerHTML = '⏳ 安装中…';

  apiFetch('POST', '/install/' + encodeURIComponent(id), {})
    .then(function (data) {
      toast(data.message || '安装成功！前往「技能市场」启用', 'success', 4000);
      btnEl.className = 'sc-install-btn installed';
      btnEl.innerHTML = '✓ 已安装';
      btnEl.disabled = true;

      var skill = S.skills.find(function (s) { return s.id === id; });
      if (skill) skill.is_installed = true;

      var instEl = $('#hero-stat-installed');
      if (instEl) instEl.textContent = parseInt(instEl.textContent || '0', 10) + 1;

      if (S.modalSkillId === id) {
        var mb = $('#modal-install-btn');
        if (mb) { mb.className = 'btn btn-success'; mb.innerHTML = '✓ 已安装'; mb.disabled = true; }
        var bb = $('#modal-installed-badge');
        if (bb) bb.style.display = 'inline-flex';
      }
    })
    .catch(function (e) {
      if (e.message && e.message.indexOf('已安装') >= 0) {
        toast('此技能已在你的技能库中', 'info');
        btnEl.className = 'sc-install-btn installed';
        btnEl.innerHTML = '✓ 已安装';
      } else {
        toast('安装失败：' + e.message, 'error');
        btnEl.className = 'sc-install-btn install';
        btnEl.innerHTML = orig;
        btnEl.disabled = false;
      }
    });
}

/* ═══════════════ Detail Modal ═══════════════════════════════ */
function openModal(id) {
  S.modalSkillId = id;
  var overlay = $('#sc-modal-overlay');
  if (!overlay) return;
  overlay.classList.add('open');

  $('#modal-icon').textContent = '⏳';
  var nameNode = $('#modal-name');
  if (nameNode.firstChild) nameNode.firstChild.textContent = '加载中…';
  $('#modal-meta').textContent = '';
  $('#modal-desc').textContent = '';
  var sourceNode = $('#modal-source');
  if (sourceNode) sourceNode.innerHTML = '';
  $('#modal-use-cases').innerHTML = '';
  $('#modal-tags').innerHTML = '';
  $('#modal-prompt-content').textContent = '';
  $('#modal-installed-badge').style.display = 'none';

  apiFetch('GET', '/skill/' + encodeURIComponent(id))
    .then(function (data) {
      var s = data.skill;
      $('#modal-icon').textContent = s.icon || '🔧';
      if (nameNode.firstChild) nameNode.firstChild.textContent = s.name;

      var catLabel = (CAT_CONFIG.find(function (c) { return c.id === s.subcategory; }) || {}).label || s.subcategory || '';
      var metaHtml = esc(s.author || 'Koto Community') + ' · v' + esc(s.version || '1.0.0') + ' · ' + esc(catLabel);
      if (s.likes) metaHtml += ' <span style="margin-left:8px;color:#ff9800;">★ ' + esc(s.likes) + '</span>';
      $('#modal-meta').innerHTML = metaHtml;
      
      $('#modal-desc').textContent = s.description || '';
      if (sourceNode) {
        var sourceUrl = (s.community_meta && s.community_meta.source_url) || s.source_url;
        if (sourceUrl) {
          sourceNode.innerHTML = '<strong>来源 (Source):</strong> <a href="' + esc(sourceUrl) + '" target="_blank" style="color:var(--accent);text-decoration:underline;">' + esc(sourceUrl) + '</a>';
        } else {
          var srcLabel = s.source_name || 'Koto 社区精选';
          sourceNode.innerHTML = '<strong>来源 (Source):</strong> <span style="color:var(--text-secondary);">' + esc(srcLabel) + '</span>';
        }
      }

      var uc = (s.community_meta && s.community_meta.use_cases) || [];
      $('#modal-use-cases').innerHTML = uc.map(function (u) { return '<span class="sc-use-case-chip">💡 ' + esc(u) + '</span>'; }).join('');
      $('#modal-tags').innerHTML = (s.tags || []).map(function (t) { return '<span class="sc-tag sc-tag-plain">' + esc(t) + '</span>'; }).join('');

      var prompt = (s.prompt || '').trim();
      $('#modal-prompt-content').textContent = prompt.length > 600
        ? prompt.slice(0, 600) + '\n\n…（点击展开完整内容）'
        : prompt;

      var diff = (s.community_meta && s.community_meta.difficulty) || '中等';
      var diffEl = $('#modal-difficulty');
      if (diffEl) diffEl.innerHTML = '<span class="sc-difficulty-dot ' + (DIFF_DOT[diff] || 'diff-medium') + '"></span>' + esc(diff);

      if (s.is_installed) $('#modal-installed-badge').style.display = 'inline-flex';

      var ib = $('#modal-install-btn');
      if (ib) {
        if (s.is_installed) {
          ib.className = 'btn btn-success';
          ib.innerHTML = '✓ 已安装';
          ib.disabled = true;
          ib.onclick = null;
        } else {
          ib.className = 'btn btn-primary btn-lg';
          ib.innerHTML = '⬇️ 安装到 Koto';
          ib.disabled = false;
          ib.onclick = function () { installSkill(s.id, ib); };
        }
      }
    })
    .catch(function (e) {
      if (nameNode.firstChild) nameNode.firstChild.textContent = '加载失败';
      $('#modal-desc').textContent = e.message;
    });
}

function closeModal() {
  var overlay = $('#sc-modal-overlay');
  if (overlay) overlay.classList.remove('open');
  S.modalSkillId = null;
}

/* ═══════════════ Prompt Toggle ══════════════════════════════ */
function togglePromptPreview() {
  var block = $('#modal-prompt-content');
  var toggle = $('#prompt-toggle');
  if (!block || !toggle) return;
  var isOpen = toggle.classList.toggle('open');
  var icon = toggle.querySelector('.sc-prompt-toggle-icon');
  if (icon) icon.textContent = isOpen ? '▲' : '▼';
  block.parentElement.style.maxHeight = isOpen ? '600px' : '200px';
}

/* ═══════════════ AI Recommend ═══════════════════════════════ */
function scAiRecommend() {
  var input = $('#aiRecommendInput');
  var query = (input ? input.value : '').trim();
  if (!query) { toast('请输入你需要的技能描述', 'error'); return; }

  var btn = $('#aiRecommendBtn');
  var loading = $('#aiRecommendLoading');
  var resultsArea = $('#aiRecommendResults');
  var grid = $('#aiRecommendGrid');

  if (btn) { btn.disabled = true; btn.style.opacity = '0.5'; }
  if (loading) loading.style.display = 'block';
  if (resultsArea) resultsArea.style.display = 'none';
  if (grid) grid.innerHTML = '';

  fetch('/api/skillmarket/community/ai-recommend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: query }),
  })
    .then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
        return data;
      });
    })
    .then(function (data) {
      var list = Array.isArray(data.results) ? data.results : [];
      if (!list.length) {
        if (grid) grid.innerHTML = '<div style="color:var(--text-muted,#6c7a91);font-size:14px;text-align:center;padding:20px 0;">未找到合适的匹配项，换个描述试试？</div>';
      } else {
        var html = list.map(function (sk, idx) {
          var payload = encodeURIComponent(JSON.stringify({
            name: sk.name || ('online_skill_' + idx),
            full_prompt: sk.full_prompt || '',
            description: sk.description || '',
            author: sk.author || 'Open Source',
            tags: sk.tags || ['开源推荐'],
            source_name: sk.source_name || '',
            source_repo: sk.source_repo || '',
            source_url: sk.source_url || '',
            source_path: sk.source_path || '',
          }));
          var likesHtml = sk.likes ? '<span class="sc-likes">★ ' + esc(sk.likes) + '</span>' : '';
          return '<div class="sc-card" data-id="' + esc(sk.id || '') + '">' +
            '<div class="sc-card-header"><div class="sc-card-icon">🧠</div>' +
            '<div class="sc-card-meta"><div class="sc-card-name">' + esc(sk.name || '未命名') + '</div>' +
            '<div class="sc-card-author">' + esc(sk.author || 'Open Source') + likesHtml + '</div></div></div>' +
            '<div class="sc-card-desc">' + esc(sk.description || '') + '</div>' +
            '<div class="sc-card-tags"><span class="sc-tag sc-tag-plain">开源推荐</span>' +
            '<span class="sc-tag sc-tag-plain">来源: ' + esc(sk.source_name || sk.source_repo || 'GitHub') + '</span></div>' +
            '<div class="sc-card-footer"><span class="sc-difficulty"><span class="sc-difficulty-dot diff-medium"></span>在线</span>' +
            '<button class="sc-install-btn install" data-action="install-online" data-payload="' + payload + '">⬇️ 下载并安装</button></div></div>';
        }).join('');
        if (grid) grid.innerHTML = html;

        // Bind card click -> modal
        $$('.sc-card', grid).forEach(function (card) {
          card.addEventListener('click', function (e) {
            if (e.target.closest('.sc-install-btn')) return;
            if (card.dataset.id) openModal(card.dataset.id);
          });
        });

        $$('[data-action="install-online"]', grid || document).forEach(function (el) {
          el.addEventListener('click', function (e) {
            e.stopPropagation();
            var raw = el.getAttribute('data-payload') || '';
            var d;
            try { d = JSON.parse(decodeURIComponent(raw)); } catch (ex) { d = null; }
            if (!d) { toast('参数解析失败', 'error'); return; }
            onlineInstall(el, d);
          });
        });
      }
      if (resultsArea) resultsArea.style.display = 'block';
    })
    .catch(function (e) {
      toast('请求失败：' + e.message, 'error');
    })
    .finally(function () {
      if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
      if (loading) loading.style.display = 'none';
    });
}

function onlineInstall(btnEl, payload) {
  if (!btnEl || btnEl.disabled) return;
  var orig = btnEl.innerHTML;
  btnEl.disabled = true;
  btnEl.className = 'sc-install-btn loading';
  btnEl.innerHTML = '⏳ 安装中…';

  fetch('/api/skillmarket/community/online-install', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
    .then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
        return data;
      });
    })
    .then(function (data) {
      btnEl.className = 'sc-install-btn installed';
      btnEl.innerHTML = '✓ 已安装';
      toast(data.message || '安装成功', 'success');
    })
    .catch(function (e) {
      btnEl.className = 'sc-install-btn install';
      btnEl.disabled = false;
      btnEl.innerHTML = orig;
      toast('安装失败：' + e.message, 'error');
    });
}
