/**
 * Koto Skill 社区 — 前端逻辑
 * ====================================
 * 纯前端，无外部依赖；通过 /api/skillmarket/community/* 与后端交互
 */

'use strict';

/* ═══════════════ API ════════════════════════════════════════ */
const API = {
  catalog:   (cat, q) => {
    let u = '/api/skillmarket/community/catalog';
    const params = [];
    if (cat && cat !== 'all') params.push(`category=${encodeURIComponent(cat)}`);
    if (q) params.push(`q=${encodeURIComponent(q)}`);
    return params.length ? `${u}?${params.join('&')}` : u;
  },
  detail:    id  => `/api/skillmarket/community/skill/${encodeURIComponent(id)}`,
  install:   id  => `/api/skillmarket/community/install/${encodeURIComponent(id)}`,
};

/* ═══════════════ State ══════════════════════════════════════ */
const state = {
  allSkills:      [],       // 当前过滤后的 skills
  currentFilter:  'all',    // all | koto_thinking | writing | career | research | code_debug
  searchQuery:    '',
  sortBy:         'default', // default | name | difficulty
  openSkillId:    null,
};

/* ═══════════════ Category Config ════════════════════════════ */
const CAT_CONFIG = [
  { id: 'all',          label: '全部',       icon: '⭐' },
  { id: 'koto_thinking', label: '思维增强',   icon: '🧠' },
  { id: 'writing',       label: '写作创作',   icon: '✍️' },
  { id: 'career',        label: '专业咨询',   icon: '💼' },
  { id: 'research',      label: '调研分析',   icon: '🔍' },
  { id: 'code_debug',    label: '代码调试',   icon: '🐛' },
];

const CAT_TAG_CLASS = {
  koto_thinking: 'sc-tag-thinking',
  writing:       'sc-tag-writing',
  career:        'sc-tag-consulting',
  research:      'sc-tag-research',
  code_debug:    'sc-tag-debug',
};

const DIFF_CONFIG = {
  '简单':  { cls: 'diff-easy',   dot: '●' },
  '中等':  { cls: 'diff-medium', dot: '●' },
  '较难':  { cls: 'diff-hard',   dot: '●' },
};

/* ═══════════════ DOM Helpers ════════════════════════════════ */
function qs(sel, ctx = document)  { return ctx.querySelector(sel); }
function qsa(sel, ctx = document) { return [...ctx.querySelectorAll(sel)]; }

function escHtml(s) {
  return String(s || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function toast(msg, type = 'info', duration = 3500) {
  const container = qs('#sc-toast-container');
  const el = document.createElement('div');
  const icons = { success: '✅', error: '❌', info: 'ℹ️' };
  el.className = `sc-toast ${type}`;
  el.innerHTML = `<span>${icons[type] || 'ℹ️'}</span><span>${escHtml(msg)}</span>`;
  container.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity 0.3s'; setTimeout(() => el.remove(), 350); }, duration);
}

async function apiFetch(method, url, body = null) {
  const opts = { method, headers: {} };
  if (body) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({ error: res.statusText }));
  if (!res.ok && res.status !== 409) throw new Error(data.error || res.statusText);
  return data;
}

/* ═══════════════ Init ═══════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', () => {
  buildFilterTabs();
  bindSearch();
  bindSort();
  bindModalClose();
  loadSkills();
});

/* ═══════════════ Filter Tabs ════════════════════════════════ */
function buildFilterTabs() {
  const bar = qs('#sc-filter-bar');
  if (!bar) return;

  CAT_CONFIG.forEach(cat => {
    const btn = document.createElement('button');
    btn.className = `sc-filter-tab${cat.id === 'all' ? ' active' : ''}`;
    btn.dataset.cat = cat.id;
    btn.innerHTML = `${cat.icon} ${escHtml(cat.label)} <span class="tab-count" id="tab-count-${cat.id}">—</span>`;
    btn.addEventListener('click', () => switchFilter(cat.id));
    bar.insertBefore(btn, qs('#sc-sort-select', bar));
  });
}

function switchFilter(catId) {
  state.currentFilter = catId;
  qsa('.sc-filter-tab').forEach(t => t.classList.toggle('active', t.dataset.cat === catId));
  renderGrid();
}

/* ═══════════════ Search ═════════════════════════════════════ */
function bindSearch() {
  const input = qs('#sc-search-input');
  if (!input) return;
  let timer;
  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      state.searchQuery = input.value.trim().toLowerCase();
      renderGrid();
    }, 200);
  });
}

/* ═══════════════ Sort ═══════════════════════════════════════ */
function bindSort() {
  const sel = qs('#sc-sort-select');
  if (!sel) return;
  sel.addEventListener('change', () => {
    state.sortBy = sel.value;
    renderGrid();
  });
}

/* ═══════════════ Load Skills ════════════════════════════════ */
async function loadSkills() {
  showSkeletons();
  try {
    const data = await apiFetch('GET', API.catalog());
    state.allSkills = data.skills || [];
    updateTabCounts(state.allSkills);
    updateHeroStats(state.allSkills);
    renderGrid();
  } catch (e) {
    qs('#sc-grid').innerHTML = `
      <div class="sc-empty" style="grid-column:1/-1">
        <div class="sc-empty-icon">⚠️</div>
        <h3>加载失败</h3>
        <p>${escHtml(e.message)}</p>
      </div>`;
  }
}

function updateTabCounts(skills) {
  // all
  const el = qs('#tab-count-all');
  if (el) el.textContent = skills.length;
  // per category
  const counts = {};
  skills.forEach(s => { counts[s.subcategory] = (counts[s.subcategory] || 0) + 1; });
  Object.entries(counts).forEach(([cat, cnt]) => {
    const cel = qs(`#tab-count-${cat}`);
    if (cel) cel.textContent = cnt;
  });
}

function updateHeroStats(skills) {
  const total = qs('#hero-stat-total');
  const cats  = qs('#hero-stat-cats');
  const inst  = qs('#hero-stat-installed');
  if (total) total.textContent = skills.length;
  if (cats)  cats.textContent  = [...new Set(skills.map(s => s.subcategory))].length;
  if (inst)  inst.textContent  = skills.filter(s => s.is_installed).length;
}

/* ═══════════════ Render Grid ════════════════════════════════ */
function getFilteredSorted() {
  let list = [...state.allSkills];

  // Filter by category
  if (state.currentFilter !== 'all') {
    list = list.filter(s => s.subcategory === state.currentFilter || s.category === state.currentFilter);
  }

  // Filter by search
  if (state.searchQuery) {
    const q = state.searchQuery;
    list = list.filter(s =>
      (s.name || '').toLowerCase().includes(q) ||
      (s.description || '').toLowerCase().includes(q) ||
      (s.tags || []).some(t => t.toLowerCase().includes(q))
    );
  }

  // Sort
  if (state.sortBy === 'name') {
    list.sort((a, b) => (a.name || '').localeCompare(b.name || ''));
  } else if (state.sortBy === 'installed') {
    list.sort((a, b) => (b.is_installed ? 1 : 0) - (a.is_installed ? 1 : 0));
  }

  return list;
}

function renderGrid() {
  const grid = qs('#sc-grid');
  if (!grid) return;

  const list = getFilteredSorted();
  const countEl = qs('#sc-results-count');
  if (countEl) countEl.textContent = `${list.length} 个技能`;

  if (!list.length) {
    grid.innerHTML = `
      <div class="sc-empty">
        <div class="sc-empty-icon">🔍</div>
        <h3>没有找到匹配的技能</h3>
        <p>尝试更换搜索词或切换分类</p>
      </div>`;
    return;
  }

  // Group by category when filter = all and no search
  const showGrouped = state.currentFilter === 'all' && !state.searchQuery;

  if (showGrouped) {
    const groups = {};
    list.forEach(s => { (groups[s.subcategory] || (groups[s.subcategory] = [])).push(s); });
    const parts = [];
    CAT_CONFIG.filter(c => c.id !== 'all').forEach(cat => {
      const items = groups[cat.id];
      if (!items || !items.length) return;
      parts.push(`
        <div class="sc-group-header">
          <span class="sc-group-label">${cat.icon} ${escHtml(cat.label)}</span>
          <span class="sc-group-count">${items.length}</span>
        </div>
      `);
      parts.push(...items.map(s => renderCard(s)));
    });
    grid.innerHTML = parts.join('');
  } else {
    grid.innerHTML = list.map(renderCard).join('');
  }

  // Bind card events
  qsa('.sc-card', grid).forEach(card => {
    card.addEventListener('click', e => {
      if (e.target.closest('.sc-install-btn')) return;
      openModal(card.dataset.id);
    });
  });

  qsa('[data-action="install"]', grid).forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      installSkill(btn.dataset.id, btn);
    });
  });
}

function renderCard(skill) {
  const catCfg = CAT_CONFIG.find(c => c.id === skill.subcategory) || {};
  const tagCls = CAT_TAG_CLASS[skill.subcategory] || 'sc-tag-plain';
  const diff   = skill.community_meta?.difficulty || '中等';
  const diffCfg = DIFF_CONFIG[diff] || DIFF_CONFIG['中等'];

  const installedBadge = skill.is_installed
    ? `<span class="sc-installed-badge">✓ 已安装</span>`
    : '';

  const installBtn = skill.is_installed
    ? `<button class="sc-install-btn installed" disabled>✓ 已安装</button>`
    : `<button class="sc-install-btn install" data-action="install" data-id="${escHtml(skill.id)}">⬇️ 安装</button>`;

  const tagsHtml = (skill.tags || []).slice(0, 3).map(t =>
    `<span class="sc-tag sc-tag-plain">${escHtml(t)}</span>`
  ).join('');

  return `
  <div class="sc-card" data-id="${escHtml(skill.id)}">
    <div class="sc-card-header">
      <div class="sc-card-icon">${escHtml(skill.icon || '🔧')}</div>
      <div class="sc-card-meta">
        <div class="sc-card-name">
          ${escHtml(skill.name)}
          ${installedBadge}
        </div>
        <div class="sc-card-author">${escHtml(skill.author || 'Koto Community')} · v${escHtml(skill.version || '1.0.0')}</div>
      </div>
    </div>
    <div class="sc-card-desc">${escHtml(skill.description || '')}</div>
    <div class="sc-card-tags">
      <span class="sc-tag ${tagCls}">${catCfg.icon || ''} ${escHtml(catCfg.label || skill.subcategory || '')}</span>
      ${tagsHtml}
    </div>
    <div class="sc-card-footer">
      <span class="sc-difficulty">
        <span class="sc-difficulty-dot ${diffCfg.cls}"></span>${escHtml(diff)}
      </span>
      ${installBtn}
    </div>
  </div>`;
}

/* ═══════════════ Skeleton Loading ═══════════════════════════ */
function showSkeletons(count = 9) {
  const grid = qs('#sc-grid');
  if (!grid) return;
  grid.innerHTML = Array.from({ length: count }, () => `
    <div class="sc-skeleton">
      <div class="skel-header">
        <div class="skel-pulse skel-icon"></div>
        <div class="skel-meta">
          <div class="skel-pulse skel-title"></div>
          <div class="skel-pulse skel-subtitle"></div>
        </div>
      </div>
      <div class="skel-pulse skel-desc1"></div>
      <div class="skel-pulse skel-desc2"></div>
      <div class="skel-tags">
        <div class="skel-pulse skel-tag"></div>
        <div class="skel-pulse skel-tag"></div>
      </div>
    </div>`).join('');
}

/* ═══════════════ Install ════════════════════════════════════ */
async function installSkill(skillId, btnEl) {
  if (!btnEl || btnEl.disabled) return;
  const orig = btnEl.innerHTML;
  btnEl.disabled = true;
  btnEl.className = 'sc-install-btn loading';
  btnEl.innerHTML = '⏳ 安装中…';

  try {
    const data = await apiFetch('POST', API.install(skillId), {});
    toast(data.message || '安装成功！前往「技能市场」启用', 'success', 4000);

    // Update card UI
    btnEl.className = 'sc-install-btn installed';
    btnEl.innerHTML = '✓ 已安装';
    btnEl.disabled = true;

    // Update state
    const skill = state.allSkills.find(s => s.id === skillId);
    if (skill) skill.is_installed = true;

    // Update hero installed count
    const instEl = qs('#hero-stat-installed');
    if (instEl) instEl.textContent = parseInt(instEl.textContent || '0') + 1;

    // Sync modal install button if open
    if (state.openSkillId === skillId) {
      const modalBtn = qs('#modal-install-btn');
      if (modalBtn) {
        modalBtn.className = 'btn btn-success';
        modalBtn.innerHTML = '✓ 已安装';
        modalBtn.disabled = true;
      }
      // Update name badge in modal
      const badgeEl = qs('#modal-installed-badge');
      if (badgeEl) badgeEl.style.display = 'inline-flex';
    }
  } catch (e) {
    if (e.message.includes('已安装')) {
      toast('此技能已在你的技能库中', 'info');
      btnEl.className = 'sc-install-btn installed';
      btnEl.innerHTML = '✓ 已安装';
    } else {
      toast(`安装失败：${e.message}`, 'error');
      btnEl.className = 'sc-install-btn install';
      btnEl.innerHTML = orig;
      btnEl.disabled = false;
    }
  }
}

/* ═══════════════ Modal ══════════════════════════════════════ */
async function openModal(skillId) {
  state.openSkillId = skillId;
  const overlay = qs('#sc-modal-overlay');
  if (!overlay) return;
  overlay.classList.add('open');

  // Set loading state
  qs('#modal-icon').textContent = '⏳';
  qs('#modal-name').textContent = '加载中…';
  qs('#modal-meta').textContent = '';
  qs('#modal-desc').textContent = '';
  qs('#modal-use-cases').innerHTML = '';
  qs('#modal-tags').innerHTML = '';
  qs('#modal-prompt-content').textContent = '';
  qs('#modal-installed-badge').style.display = 'none';

  try {
    const data = await apiFetch('GET', API.detail(skillId));
    const skill = data.skill;

    qs('#modal-icon').textContent  = skill.icon || '🔧';
    qs('#modal-name').textContent  = skill.name;
    qs('#modal-meta').innerHTML    = `
      <span>${escHtml(skill.author || 'Koto Community')}</span>
      <span style="color:var(--border)">·</span>
      <span>v${escHtml(skill.version || '1.0.0')}</span>
      <span style="color:var(--border)">·</span>
      <span>${escHtml(CAT_CONFIG.find(c => c.id === skill.subcategory)?.label || skill.subcategory || '')}</span>
    `;
    qs('#modal-desc').textContent = skill.description || '';

    // Use cases
    const useCases = skill.community_meta?.use_cases || [];
    qs('#modal-use-cases').innerHTML = useCases.map(u =>
      `<span class="sc-use-case-chip">💡 ${escHtml(u)}</span>`
    ).join('');

    // Tags
    qs('#modal-tags').innerHTML = (skill.tags || []).map(t =>
      `<span class="sc-tag sc-tag-plain">${escHtml(t)}</span>`
    ).join('');

    // Prompt preview
    const prompt = (skill.prompt || '').trim();
    qs('#modal-prompt-content').textContent = prompt.length > 600
      ? prompt.slice(0, 600) + '\n\n…（点击展开完整内容）'
      : prompt;

    // Difficulty
    const diff = skill.community_meta?.difficulty || '中等';
    const diffEl = qs('#modal-difficulty');
    if (diffEl) {
      const dc = DIFF_CONFIG[diff] || DIFF_CONFIG['中等'];
      diffEl.innerHTML = `<span class="sc-difficulty-dot ${dc.cls}"></span>${escHtml(diff)}`;
    }

    // Installed badge
    if (skill.is_installed) {
      qs('#modal-installed-badge').style.display = 'inline-flex';
    }

    // Install button
    const installBtn = qs('#modal-install-btn');
    if (installBtn) {
      if (skill.is_installed) {
        installBtn.className = 'btn btn-success';
        installBtn.innerHTML = '✓ 已安装';
        installBtn.disabled = true;
        installBtn.onclick = null;
      } else {
        installBtn.className = 'btn btn-primary btn-lg';
        installBtn.innerHTML = '⬇️ 安装到 Koto';
        installBtn.disabled = false;
        installBtn.onclick = () => installSkill(skill.id, installBtn);
      }
    }

  } catch (e) {
    qs('#modal-name').textContent = '加载失败';
    qs('#modal-desc').textContent  = e.message;
  }
}

function bindModalClose() {
  const overlay = qs('#sc-modal-overlay');
  if (!overlay) return;
  qs('#sc-modal-close')?.addEventListener('click', closeModal);
  overlay.addEventListener('click', e => {
    if (e.target === overlay) closeModal();
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeModal();
  });
}

function closeModal() {
  const overlay = qs('#sc-modal-overlay');
  if (overlay) overlay.classList.remove('open');
  state.openSkillId = null;
}

/* ═══════════════ Prompt Toggle ══════════════════════════════ */
function togglePromptPreview() {
  const block = qs('#modal-prompt-content');
  const toggle = qs('#prompt-toggle');
  if (!block || !toggle) return;
  const isOpen = toggle.classList.toggle('open');
  toggle.querySelector('.sc-prompt-toggle-icon').textContent = isOpen ? '▲' : '▼';
  block.style.maxHeight = isOpen ? '600px' : '200px';
}
